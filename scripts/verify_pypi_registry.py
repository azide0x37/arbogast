"""Verify public PyPI bytes against an approved wheel and sdist.

The verifier deliberately supports only PyPI and TestPyPI.  It does not accept
an arbitrary index or download URL, and it treats registry metadata as
untrusted input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPMessage
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final, Protocol, cast
from urllib.parse import quote, unquote, urlsplit

PROJECT_RE: Final = re.compile(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*")
VERSION_RE: Final = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
FILENAME_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]*")
SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
SUMMARY_SCHEMA: Final = "arbogast.pypi-registry-verification/v1"
MAX_JSON_BYTES: Final = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES: Final = 256 * 1024 * 1024
NETWORK_TIMEOUT_SECONDS: Final = 30.0
CHUNK_SIZE: Final = 1024 * 1024


class VerificationError(ValueError):
    """Raised when public registry state does not match the approved release."""


@dataclass(frozen=True)
class Registry:
    """The immutable network boundary for one supported registry."""

    target: str
    api_host: str
    file_host: str

    def version_api_url(self, project: str, version: str) -> str:
        project_component = quote(project, safe="")
        version_component = quote(version, safe="")
        return f"https://{self.api_host}/pypi/{project_component}/{version_component}/json"


REGISTRIES: Final = {
    "pypi": Registry(
        target="pypi",
        api_host="pypi.org",
        file_host="files.pythonhosted.org",
    ),
    "testpypi": Registry(
        target="testpypi",
        api_host="test.pypi.org",
        file_host="test-files.pythonhosted.org",
    ),
}


@dataclass(frozen=True)
class ArtifactExpectation:
    """One exact artifact approved before publication."""

    filename: str
    packagetype: str
    sha256: str
    size: int
    approved_path: Path


@dataclass(frozen=True)
class RegistryArtifact:
    """One validated file record from the version JSON endpoint."""

    filename: str
    packagetype: str
    sha256: str
    size: int
    url: str


class ReadableResponse(Protocol):
    """The small portion of an HTTP response used by this verifier."""

    status: int
    headers: Mapping[str, str]

    def read(self, size: int = -1) -> bytes: ...

    def geturl(self) -> str: ...

    def close(self) -> None: ...


class Fetcher(Protocol):
    """Network seam used by the real client and no-network unit tests."""

    def open(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
        allowed_hosts: frozenset[str],
    ) -> ReadableResponse: ...


def _validate_https_url(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    label: str,
) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise VerificationError(f"{label} is malformed: {exc}") from exc
    if parsed.scheme != "https":
        raise VerificationError(f"{label} must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise VerificationError(f"{label} must not contain credentials")
    if port not in (None, 443):
        raise VerificationError(f"{label} must use the default HTTPS port")
    hostname = parsed.hostname
    if hostname not in allowed_hosts:
        raise VerificationError(
            f"{label} host must be one of {sorted(allowed_hosts)!r}, found {hostname!r}"
        )
    if parsed.query or parsed.fragment:
        raise VerificationError(f"{label} must not contain a query or fragment")


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only when the destination remains in the trust boundary."""

    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: BinaryIO,
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_https_url(
            newurl,
            allowed_hosts=self._allowed_hosts,
            label="redirect destination",
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HTTPSFetcher:
    """urllib client with an allowlisted redirect policy."""

    def open(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
        allowed_hosts: frozenset[str],
    ) -> ReadableResponse:
        _validate_https_url(
            request.full_url,
            allowed_hosts=allowed_hosts,
            label="request URL",
        )
        opener = urllib.request.build_opener(_AllowlistedRedirectHandler(allowed_hosts))
        return cast(ReadableResponse, opener.open(request, timeout=timeout))


def _open_response(
    fetcher: Fetcher,
    request: urllib.request.Request,
    *,
    allowed_hosts: frozenset[str],
    label: str,
) -> ReadableResponse:
    try:
        response = fetcher.open(
            request,
            timeout=NETWORK_TIMEOUT_SECONDS,
            allowed_hosts=allowed_hosts,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VerificationError(f"cannot fetch {label}: {exc}") from exc
    if response.status != 200:
        response.close()
        raise VerificationError(f"{label} returned HTTP status {response.status}")
    try:
        _validate_https_url(
            response.geturl(),
            allowed_hosts=allowed_hosts,
            label=f"final {label} URL",
        )
    except VerificationError:
        response.close()
        raise
    return response


def _content_length(response: ReadableResponse, *, label: str) -> int | None:
    raw_value = response.headers.get("Content-Length")
    if raw_value is None:
        return None
    if re.fullmatch(r"[0-9]+", raw_value) is None:
        raise VerificationError(f"{label} has an invalid Content-Length")
    return int(raw_value)


def _read_bounded(response: ReadableResponse, *, limit: int, label: str) -> bytes:
    length = _content_length(response, label=label)
    if length is not None and length > limit:
        raise VerificationError(f"{label} exceeds the {limit}-byte limit")
    payload = bytearray()
    while True:
        remaining = limit - len(payload)
        block = response.read(min(CHUNK_SIZE, remaining + 1))
        if not block:
            break
        payload.extend(block)
        if len(payload) > limit:
            raise VerificationError(f"{label} exceeds the {limit}-byte limit")
    if length is not None and len(payload) != length:
        raise VerificationError(
            f"{label} length mismatch: header declares {length}, received {len(payload)}"
        )
    return bytes(payload)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"registry JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise VerificationError(f"registry JSON contains invalid constant {value!r}")


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be a JSON object")
    return cast(Mapping[str, object], value)


def _parse_registry_json(
    payload: bytes,
    *,
    registry: Registry,
    project: str,
    version: str,
    expected: tuple[ArtifactExpectation, ArtifactExpectation],
) -> tuple[RegistryArtifact, RegistryArtifact]:
    try:
        text = payload.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise VerificationError(f"registry JSON is malformed: {exc}") from exc
    root = _mapping(document, label="registry JSON")
    info = _mapping(root.get("info"), label="registry JSON info")
    if info.get("name") != project:
        raise VerificationError(
            f"registry project mismatch: expected {project!r}, found {info.get('name')!r}"
        )
    if info.get("version") != version:
        raise VerificationError(
            f"registry version mismatch: expected {version!r}, found {info.get('version')!r}"
        )

    raw_urls = root.get("urls")
    if not isinstance(raw_urls, list):
        raise VerificationError("registry JSON urls must be an array")
    expected_by_name = {item.filename: item for item in expected}
    found_names: list[str] = []
    records: list[RegistryArtifact] = []
    for index, raw_record in enumerate(raw_urls):
        record = _mapping(raw_record, label=f"registry JSON urls[{index}]")
        filename = record.get("filename")
        if not isinstance(filename, str):
            raise VerificationError(f"registry JSON urls[{index}].filename must be a string")
        found_names.append(filename)
        expectation = expected_by_name.get(filename)
        if expectation is None:
            continue
        packagetype = record.get("packagetype")
        if packagetype != expectation.packagetype:
            raise VerificationError(
                f"registry package type mismatch for {filename!r}: "
                f"expected {expectation.packagetype!r}, found {packagetype!r}"
            )
        size = record.get("size")
        if isinstance(size, bool) or not isinstance(size, int):
            raise VerificationError(f"registry size for {filename!r} must be an integer")
        if size != expectation.size:
            raise VerificationError(
                f"registry size mismatch for {filename!r}: "
                f"expected {expectation.size}, found {size}"
            )
        digests = _mapping(record.get("digests"), label=f"digests for {filename!r}")
        digest = digests.get("sha256")
        if digest != expectation.sha256:
            raise VerificationError(
                f"registry SHA-256 mismatch for {filename!r}: "
                f"expected {expectation.sha256}, found {digest!r}"
            )
        url = record.get("url")
        if not isinstance(url, str):
            raise VerificationError(f"registry URL for {filename!r} must be a string")
        _validate_https_url(
            url,
            allowed_hosts=frozenset({registry.file_host}),
            label=f"registry file URL for {filename!r}",
        )
        parsed_path = unquote(urlsplit(url).path)
        if PurePosixPath(parsed_path).name != filename:
            raise VerificationError(
                f"registry file URL path does not end in expected filename {filename!r}"
            )
        records.append(
            RegistryArtifact(
                filename=filename,
                packagetype=expectation.packagetype,
                sha256=expectation.sha256,
                size=expectation.size,
                url=url,
            )
        )

    expected_names = sorted(expected_by_name)
    if len(found_names) != len(expected_names) or sorted(found_names) != expected_names:
        raise VerificationError(
            "registry version must contain exactly the approved wheel and sdist; "
            f"expected {expected_names!r}, found {sorted(found_names)!r}"
        )
    if len(records) != 2:
        raise VerificationError("registry version did not yield exactly two validated records")
    ordered = sorted(records, key=lambda item: item.packagetype)
    return ordered[0], ordered[1]


def _open_regular(path: Path, *, label: str) -> BinaryIO:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise VerificationError(
            f"cannot open {label} as a regular non-symlink file: {exc}"
        ) from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise VerificationError(f"{label} must be a regular non-symlink file")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _verify_approved_artifact(expectation: ArtifactExpectation) -> None:
    if expectation.approved_path.name != expectation.filename:
        raise VerificationError(
            f"approved path name must be exactly {expectation.filename!r}, "
            f"found {expectation.approved_path.name!r}"
        )
    digest = hashlib.sha256()
    size = 0
    with _open_regular(
        expectation.approved_path, label=f"approved {expectation.packagetype}"
    ) as stream:
        for block in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(block)
            size += len(block)
    if size != expectation.size:
        raise VerificationError(
            f"approved size mismatch for {expectation.filename!r}: "
            f"expected {expectation.size}, found {size}"
        )
    actual_digest = digest.hexdigest()
    if actual_digest != expectation.sha256:
        raise VerificationError(
            f"approved SHA-256 mismatch for {expectation.filename!r}: "
            f"expected {expectation.sha256}, found {actual_digest}"
        )


def _download_and_compare(
    *,
    fetcher: Fetcher,
    registry: Registry,
    record: RegistryArtifact,
    expectation: ArtifactExpectation,
    destination: Path,
) -> None:
    request = urllib.request.Request(
        record.url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "arbogast-registry-verifier/1",
        },
        method="GET",
    )
    response = _open_response(
        fetcher,
        request,
        allowed_hosts=frozenset({registry.file_host}),
        label=f"registry artifact {record.filename!r}",
    )
    network_digest = hashlib.sha256()
    approved_digest = hashlib.sha256()
    received = 0
    try:
        length = _content_length(response, label=f"registry artifact {record.filename!r}")
        if length is not None and length != expectation.size:
            raise VerificationError(
                f"download Content-Length mismatch for {record.filename!r}: "
                f"expected {expectation.size}, found {length}"
            )
        with (
            _open_regular(
                expectation.approved_path, label=f"approved {expectation.packagetype}"
            ) as approved,
            destination.open("xb") as output,
        ):
            while True:
                remaining = expectation.size - received
                block = response.read(min(CHUNK_SIZE, remaining + 1))
                if not block:
                    break
                received += len(block)
                if received > expectation.size:
                    raise VerificationError(
                        f"download exceeds approved size for {record.filename!r}"
                    )
                approved_block = approved.read(len(block))
                if block != approved_block:
                    raise VerificationError(
                        f"downloaded bytes differ from approved bytes for {record.filename!r}"
                    )
                output.write(block)
                network_digest.update(block)
                approved_digest.update(approved_block)
            if received == expectation.size and approved.read(1):
                raise VerificationError(
                    f"approved artifact grew during verification for {record.filename!r}"
                )
    except OSError as exc:
        raise VerificationError(f"cannot store or compare {record.filename!r}: {exc}") from exc
    finally:
        response.close()
    if received != expectation.size:
        raise VerificationError(
            f"download size mismatch for {record.filename!r}: "
            f"expected {expectation.size}, received {received}"
        )
    if network_digest.hexdigest() != expectation.sha256:
        raise VerificationError(f"download SHA-256 mismatch for {record.filename!r}")
    if approved_digest.hexdigest() != expectation.sha256:
        raise VerificationError(
            f"approved artifact changed during verification for {record.filename!r}"
        )


def _validate_inputs(
    *,
    project: str,
    version: str,
    expected: tuple[ArtifactExpectation, ArtifactExpectation],
) -> None:
    if PROJECT_RE.fullmatch(project) is None:
        raise VerificationError(f"project must be a simple Python project name, found {project!r}")
    if VERSION_RE.fullmatch(version) is None:
        raise VerificationError(f"version must be final X.Y.Z, found {version!r}")
    expected_types = {item.packagetype for item in expected}
    if expected_types != {"bdist_wheel", "sdist"}:
        raise VerificationError("expectations must contain exactly one wheel and one sdist")
    if len({item.filename for item in expected}) != 2:
        raise VerificationError("wheel and sdist filenames must be distinct")
    if len({item.approved_path for item in expected}) != 2:
        raise VerificationError("approved wheel and sdist paths must be distinct")
    for item in expected:
        if (
            FILENAME_RE.fullmatch(item.filename) is None
            or item.filename != Path(item.filename).name
        ):
            raise VerificationError(f"unsafe artifact filename {item.filename!r}")
        expected_suffix = ".whl" if item.packagetype == "bdist_wheel" else ".tar.gz"
        if not item.filename.endswith(expected_suffix):
            raise VerificationError(f"{item.packagetype} filename must end in {expected_suffix!r}")
        if SHA256_RE.fullmatch(item.sha256) is None:
            raise VerificationError(
                f"SHA-256 for {item.filename!r} must be 64 lowercase hexadecimal characters"
            )
        if isinstance(item.size, bool) or not 0 < item.size <= MAX_ARTIFACT_BYTES:
            raise VerificationError(
                f"size for {item.filename!r} must be between 1 and {MAX_ARTIFACT_BYTES}"
            )


def verify_registry(
    *,
    target: str,
    project: str,
    version: str,
    wheel_filename: str,
    wheel_sha256: str,
    wheel_size: int,
    approved_wheel: Path,
    sdist_filename: str,
    sdist_sha256: str,
    sdist_size: int,
    approved_sdist: Path,
    output_dir: Path,
    fetcher: Fetcher | None = None,
) -> dict[str, object]:
    """Verify one public registry version and download the exact approved pair."""

    registry = REGISTRIES.get(target)
    if registry is None:
        raise VerificationError(f"unsupported registry target {target!r}")
    wheel = ArtifactExpectation(
        filename=wheel_filename,
        packagetype="bdist_wheel",
        sha256=wheel_sha256,
        size=wheel_size,
        approved_path=approved_wheel,
    )
    sdist = ArtifactExpectation(
        filename=sdist_filename,
        packagetype="sdist",
        sha256=sdist_sha256,
        size=sdist_size,
        approved_path=approved_sdist,
    )
    expected = (wheel, sdist)
    _validate_inputs(project=project, version=version, expected=expected)
    for item in expected:
        _verify_approved_artifact(item)

    if output_dir.exists() or output_dir.is_symlink():
        raise VerificationError(f"output directory must not already exist: {output_dir}")
    parent = output_dir.parent
    if parent.is_symlink() or not parent.is_dir():
        raise VerificationError(
            f"output parent must be an existing non-symlink directory: {parent}"
        )

    network = fetcher if fetcher is not None else HTTPSFetcher()
    api_url = registry.version_api_url(project, version)
    api_request = urllib.request.Request(
        api_url,
        headers={"Accept": "application/json", "User-Agent": "arbogast-registry-verifier/1"},
        method="GET",
    )
    api_response = _open_response(
        network,
        api_request,
        allowed_hosts=frozenset({registry.api_host}),
        label="registry version JSON",
    )
    try:
        api_payload = _read_bounded(
            api_response,
            limit=MAX_JSON_BYTES,
            label="registry version JSON",
        )
    finally:
        api_response.close()
    records = _parse_registry_json(
        api_payload,
        registry=registry,
        project=project,
        version=version,
        expected=expected,
    )
    record_by_name = {record.filename: record for record in records}

    temporary_path = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=parent))
    try:
        for item in expected:
            _download_and_compare(
                fetcher=network,
                registry=registry,
                record=record_by_name[item.filename],
                expectation=item,
                destination=temporary_path / item.filename,
            )
        temporary_path.rename(output_dir)
    except BaseException:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise

    files = []
    for item in sorted(expected, key=lambda artifact: artifact.packagetype):
        record = record_by_name[item.filename]
        files.append(
            {
                "filename": item.filename,
                "packagetype": item.packagetype,
                "registry_url": record.url,
                "sha256": item.sha256,
                "size": item.size,
            }
        )
    return {
        "artifacts": files,
        "project": project,
        "registry": {"api_url": api_url, "target": target},
        "schema": SUMMARY_SCHEMA,
        "status": "verified",
        "verification": {
            "approved_local_bytes": "identical",
            "downloaded_registry_bytes": "identical",
            "pep740_provenance": "not_verified_by_version_json",
            "version_json_sha256": hashlib.sha256(api_payload).hexdigest(),
            "version_json_size": len(api_payload),
        },
        "version": version,
    }


def _positive_size(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must be an integer") from exc
    if not 0 < parsed <= MAX_ARTIFACT_BYTES:
        raise argparse.ArgumentTypeError(f"size must be between 1 and {MAX_ARTIFACT_BYTES} bytes")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify exact PyPI or TestPyPI release bytes against approved local assets."
    )
    parser.add_argument("--target", required=True, choices=sorted(REGISTRIES))
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--wheel-filename", required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--wheel-size", required=True, type=_positive_size)
    parser.add_argument("--approved-wheel", required=True, type=Path)
    parser.add_argument("--sdist-filename", required=True)
    parser.add_argument("--sdist-sha256", required=True)
    parser.add_argument("--sdist-size", required=True, type=_positive_size)
    parser.add_argument("--approved-sdist", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = verify_registry(
            target=args.target,
            project=args.project,
            version=args.version,
            wheel_filename=args.wheel_filename,
            wheel_sha256=args.wheel_sha256,
            wheel_size=args.wheel_size,
            approved_wheel=args.approved_wheel,
            sdist_filename=args.sdist_filename,
            sdist_sha256=args.sdist_sha256,
            sdist_size=args.sdist_size,
            approved_sdist=args.approved_sdist,
            output_dir=args.output_dir,
        )
    except VerificationError as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
