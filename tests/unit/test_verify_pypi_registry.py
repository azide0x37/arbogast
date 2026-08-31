from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import verify_pypi_registry as verifier  # noqa: E402

VERIFIER = PROJECT_ROOT / "scripts/verify_pypi_registry.py"
PROJECT = "arbogast"
VERSION = "0.6.0"
WHEEL_NAME = f"arbogast-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"arbogast-{VERSION}.tar.gz"
WHEEL_BYTES = b"exact approved wheel bytes\n"
SDIST_BYTES = b"exact approved sdist bytes\n"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ResponseSpec:
    payload: bytes
    final_url: str
    status: int = 200
    headers: dict[str, str] | None = None
    chunk_size: int | None = None


class FakeResponse:
    def __init__(self, spec: ResponseSpec) -> None:
        self.status = spec.status
        self.headers: Mapping[str, str] = (
            spec.headers if spec.headers is not None else {"Content-Length": str(len(spec.payload))}
        )
        self._payload = io.BytesIO(spec.payload)
        self._final_url = spec.final_url
        self._chunk_size = spec.chunk_size
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if self._chunk_size is not None and (size < 0 or self._chunk_size < size):
            size = self._chunk_size
        return self._payload.read(size)

    def geturl(self) -> str:
        return self._final_url

    def close(self) -> None:
        self.closed = True


class FakeFetcher:
    def __init__(self, responses: dict[str, ResponseSpec]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float, frozenset[str]]] = []

    def open(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
        allowed_hosts: frozenset[str],
    ) -> FakeResponse:
        url = request.full_url
        self.calls.append((url, timeout, allowed_hosts))
        try:
            spec = self.responses[url]
        except KeyError as exc:
            raise AssertionError(f"unexpected network request: {url}") from exc
        return FakeResponse(spec)


def _file_urls(target: str) -> tuple[str, str]:
    file_host = verifier.REGISTRIES[target].file_host
    return (
        f"https://{file_host}/packages/aa/bb/{WHEEL_NAME}",
        f"https://{file_host}/packages/cc/dd/{SDIST_NAME}",
    )


def _registry_document(
    target: str,
    *,
    info_name: object = PROJECT,
    info_version: object = VERSION,
    urls: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    wheel_url, sdist_url = _file_urls(target)
    records = [
        {
            "digests": {"sha256": _sha256(WHEEL_BYTES)},
            "filename": WHEEL_NAME,
            "packagetype": "bdist_wheel",
            "size": len(WHEEL_BYTES),
            "url": wheel_url,
        },
        {
            "digests": {"sha256": _sha256(SDIST_BYTES)},
            "filename": SDIST_NAME,
            "packagetype": "sdist",
            "size": len(SDIST_BYTES),
            "url": sdist_url,
        },
    ]
    return {
        "info": {"name": info_name, "version": info_version},
        "urls": records if urls is None else urls,
    }


def _payload(document: dict[str, object]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def _approved_paths(tmp_path: Path) -> tuple[Path, Path]:
    approved = tmp_path / "approved"
    approved.mkdir()
    wheel_path = approved / WHEEL_NAME
    sdist_path = approved / SDIST_NAME
    wheel_path.write_bytes(WHEEL_BYTES)
    sdist_path.write_bytes(SDIST_BYTES)
    return wheel_path, sdist_path


def _responses(
    target: str,
    document_payload: bytes,
    *,
    wheel_spec: ResponseSpec | None = None,
    sdist_spec: ResponseSpec | None = None,
) -> dict[str, ResponseSpec]:
    registry = verifier.REGISTRIES[target]
    api_url = registry.version_api_url(PROJECT, VERSION)
    wheel_url, sdist_url = _file_urls(target)
    return {
        api_url: ResponseSpec(document_payload, api_url, chunk_size=7),
        wheel_url: wheel_spec or ResponseSpec(WHEEL_BYTES, wheel_url, chunk_size=3),
        sdist_url: sdist_spec or ResponseSpec(SDIST_BYTES, sdist_url, chunk_size=4),
    }


def _verify(
    tmp_path: Path,
    fetcher: FakeFetcher,
    *,
    target: str = "pypi",
    output_name: str = "downloaded",
    **overrides: object,
) -> dict[str, object]:
    wheel_path, sdist_path = _approved_paths(tmp_path)
    values: dict[str, Any] = {
        "target": target,
        "project": PROJECT,
        "version": VERSION,
        "wheel_filename": WHEEL_NAME,
        "wheel_sha256": _sha256(WHEEL_BYTES),
        "wheel_size": len(WHEEL_BYTES),
        "approved_wheel": wheel_path,
        "sdist_filename": SDIST_NAME,
        "sdist_sha256": _sha256(SDIST_BYTES),
        "sdist_size": len(SDIST_BYTES),
        "approved_sdist": sdist_path,
        "output_dir": tmp_path / output_name,
        "fetcher": fetcher,
    }
    values.update(overrides)
    return verifier.verify_registry(**values)


@pytest.mark.parametrize(
    ("target", "api_host", "file_host"),
    [
        ("pypi", "pypi.org", "files.pythonhosted.org"),
        ("testpypi", "test.pypi.org", "test-files.pythonhosted.org"),
    ],
)
def test_success_uses_only_hardcoded_registry_boundaries(
    tmp_path: Path,
    target: str,
    api_host: str,
    file_host: str,
) -> None:
    document_payload = _payload(_registry_document(target))
    fetcher = FakeFetcher(_responses(target, document_payload))

    receipt = _verify(tmp_path, fetcher, target=target)

    output_dir = tmp_path / "downloaded"
    assert (output_dir / WHEEL_NAME).read_bytes() == WHEEL_BYTES
    assert (output_dir / SDIST_NAME).read_bytes() == SDIST_BYTES
    assert [call[0] for call in fetcher.calls] == [
        f"https://{api_host}/pypi/{PROJECT}/{VERSION}/json",
        f"https://{file_host}/packages/aa/bb/{WHEEL_NAME}",
        f"https://{file_host}/packages/cc/dd/{SDIST_NAME}",
    ]
    assert [call[2] for call in fetcher.calls] == [
        frozenset({api_host}),
        frozenset({file_host}),
        frozenset({file_host}),
    ]
    assert all(call[1] == verifier.NETWORK_TIMEOUT_SECONDS for call in fetcher.calls)
    assert receipt == {
        "artifacts": [
            {
                "filename": WHEEL_NAME,
                "packagetype": "bdist_wheel",
                "registry_url": f"https://{file_host}/packages/aa/bb/{WHEEL_NAME}",
                "sha256": _sha256(WHEEL_BYTES),
                "size": len(WHEEL_BYTES),
            },
            {
                "filename": SDIST_NAME,
                "packagetype": "sdist",
                "registry_url": f"https://{file_host}/packages/cc/dd/{SDIST_NAME}",
                "sha256": _sha256(SDIST_BYTES),
                "size": len(SDIST_BYTES),
            },
        ],
        "project": PROJECT,
        "registry": {
            "api_url": f"https://{api_host}/pypi/{PROJECT}/{VERSION}/json",
            "target": target,
        },
        "schema": "arbogast.pypi-registry-verification/v1",
        "status": "verified",
        "verification": {
            "approved_local_bytes": "identical",
            "downloaded_registry_bytes": "identical",
            "pep740_provenance": "not_verified_by_version_json",
            "version_json_sha256": _sha256(document_payload),
            "version_json_size": len(document_payload),
        },
        "version": VERSION,
    }
    rendered = json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    assert json.loads(rendered) == receipt


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "foreign"])
def test_registry_requires_exactly_two_distribution_records(
    tmp_path: Path,
    mutation: str,
) -> None:
    records = _registry_document("pypi")["urls"]
    assert isinstance(records, list)
    if mutation == "missing":
        records.pop()
    elif mutation == "extra":
        records.append(
            {
                "filename": "arbogast-0.6.0.zip",
                "packagetype": "sdist",
                "size": 1,
                "digests": {"sha256": "0" * 64},
                "url": "https://files.pythonhosted.org/packages/arbogast-0.6.0.zip",
            }
        )
    elif mutation == "duplicate":
        records.append(dict(records[0]))
    else:
        records[0] = {**records[0], "filename": "foreign.whl"}
    fetcher = FakeFetcher(_responses("pypi", _payload(_registry_document("pypi", urls=records))))

    with pytest.raises(verifier.VerificationError, match="exactly the approved wheel and sdist"):
        _verify(tmp_path, fetcher)

    assert not (tmp_path / "downloaded").exists()
    assert len(fetcher.calls) == 1


@pytest.mark.parametrize("tamper", ["packagetype", "size", "digest"])
def test_registry_metadata_must_match_exact_expectations(tmp_path: Path, tamper: str) -> None:
    document = _registry_document("pypi")
    records = document["urls"]
    assert isinstance(records, list)
    wheel = records[0]
    assert isinstance(wheel, dict)
    if tamper == "packagetype":
        wheel["packagetype"] = "sdist"
        message = "package type mismatch"
    elif tamper == "size":
        wheel["size"] = len(WHEEL_BYTES) + 1
        message = "size mismatch"
    else:
        wheel["digests"] = {"sha256": "0" * 64}
        message = "SHA-256 mismatch"
    fetcher = FakeFetcher(_responses("pypi", _payload(document)))

    with pytest.raises(verifier.VerificationError, match=message):
        _verify(tmp_path, fetcher)

    assert len(fetcher.calls) == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "other-project", "project mismatch"),
        ("version", "0.6.1", "version mismatch"),
    ],
)
def test_registry_identity_must_match(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    if field == "name":
        document = _registry_document("pypi", info_name=value)
    else:
        document = _registry_document("pypi", info_version=value)
    fetcher = FakeFetcher(_responses("pypi", _payload(document)))

    with pytest.raises(verifier.VerificationError, match=message):
        _verify(tmp_path, fetcher)


@pytest.mark.parametrize("tamper", ["http", "foreign-host", "query", "filename"])
def test_registry_file_url_is_confined_to_exact_https_host(tmp_path: Path, tamper: str) -> None:
    document = _registry_document("pypi")
    records = document["urls"]
    assert isinstance(records, list)
    wheel = records[0]
    assert isinstance(wheel, dict)
    url = str(wheel["url"])
    if tamper == "http":
        wheel["url"] = url.replace("https://", "http://")
        message = "must use HTTPS"
    elif tamper == "foreign-host":
        wheel["url"] = url.replace("files.pythonhosted.org", "example.invalid")
        message = "host must be one of"
    elif tamper == "query":
        wheel["url"] = f"{url}?token=secret"
        message = "query or fragment"
    else:
        wheel["url"] = url.replace(WHEEL_NAME, "foreign.whl")
        message = "does not end in expected filename"
    fetcher = FakeFetcher(_responses("pypi", _payload(document)))

    with pytest.raises(verifier.VerificationError, match=message):
        _verify(tmp_path, fetcher)

    assert len(fetcher.calls) == 1


def test_redirected_download_cannot_leave_allowlisted_file_host(tmp_path: Path) -> None:
    document_payload = _payload(_registry_document("pypi"))
    wheel_url, _ = _file_urls("pypi")
    wheel_spec = ResponseSpec(WHEEL_BYTES, "https://example.invalid/stolen.whl")
    fetcher = FakeFetcher(_responses("pypi", document_payload, wheel_spec=wheel_spec))

    with pytest.raises(verifier.VerificationError, match="host must be one of"):
        _verify(tmp_path, fetcher)

    assert not (tmp_path / "downloaded").exists()
    assert len(fetcher.calls) == 2
    assert fetcher.calls[1][0] == wheel_url


@pytest.mark.parametrize("failure", ["different", "truncated", "oversized", "bad-header"])
def test_download_must_be_byte_identical_and_exactly_bounded(
    tmp_path: Path,
    failure: str,
) -> None:
    document_payload = _payload(_registry_document("pypi"))
    wheel_url, _ = _file_urls("pypi")
    if failure == "different":
        body = b"X" + WHEEL_BYTES[1:]
        wheel_spec = ResponseSpec(body, wheel_url)
        message = "downloaded bytes differ"
    elif failure == "truncated":
        body = WHEEL_BYTES[:-1]
        wheel_spec = ResponseSpec(
            body,
            wheel_url,
            headers={"Content-Length": str(len(WHEEL_BYTES))},
        )
        message = "download size mismatch"
    elif failure == "oversized":
        body = WHEEL_BYTES + b"x"
        wheel_spec = ResponseSpec(body, wheel_url, headers={})
        message = "download exceeds approved size"
    else:
        wheel_spec = ResponseSpec(WHEEL_BYTES, wheel_url, headers={"Content-Length": "many"})
        message = "invalid Content-Length"
    fetcher = FakeFetcher(_responses("pypi", document_payload, wheel_spec=wheel_spec))

    with pytest.raises(verifier.VerificationError, match=message):
        _verify(tmp_path, fetcher)

    assert not (tmp_path / "downloaded").exists()


@pytest.mark.parametrize("tamper", ["wheel-hash", "wheel-size", "wrong-name", "symlink"])
def test_approved_local_artifacts_are_verified_before_network(
    tmp_path: Path,
    tamper: str,
) -> None:
    document_payload = _payload(_registry_document("pypi"))
    fetcher = FakeFetcher(_responses("pypi", document_payload))
    overrides: dict[str, Any] = {}
    if tamper == "wheel-hash":
        overrides["wheel_sha256"] = "0" * 64
        message = "approved SHA-256 mismatch"
    elif tamper == "wheel-size":
        overrides["wheel_size"] = len(WHEEL_BYTES) + 1
        message = "approved size mismatch"
    elif tamper == "wrong-name":
        overrides["wheel_filename"] = "wrong.whl"
        message = "approved path name must be exactly"
    else:
        approved = tmp_path / "manual-approved"
        approved.mkdir()
        target = approved / "target.whl"
        target.write_bytes(WHEEL_BYTES)
        link = approved / WHEEL_NAME
        link.symlink_to(target)
        overrides["approved_wheel"] = link
        message = "regular non-symlink"

    with pytest.raises(verifier.VerificationError, match=message):
        _verify(tmp_path, fetcher, **overrides)

    assert fetcher.calls == []


def test_existing_output_directory_is_rejected_before_network(tmp_path: Path) -> None:
    document_payload = _payload(_registry_document("pypi"))
    fetcher = FakeFetcher(_responses("pypi", document_payload))
    (tmp_path / "downloaded").mkdir()

    with pytest.raises(verifier.VerificationError, match="must not already exist"):
        _verify(tmp_path, fetcher)

    assert fetcher.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"info":{"name":"arbogast","name":"other"},"urls":[]}',
        b'{"info":{"name":"arbogast","version":NaN},"urls":[]}',
    ],
)
def test_malformed_or_ambiguous_json_fails_closed(tmp_path: Path, payload: bytes) -> None:
    fetcher = FakeFetcher(_responses("pypi", payload))

    with pytest.raises(verifier.VerificationError):
        _verify(tmp_path, fetcher)

    assert len(fetcher.calls) == 1


def test_json_download_is_bounded_even_without_content_length() -> None:
    response = FakeResponse(
        ResponseSpec(b"123456", "https://pypi.org/pypi/arbogast/0.6.0/json", headers={})
    )

    with pytest.raises(verifier.VerificationError, match="exceeds the 5-byte limit"):
        verifier._read_bounded(response, limit=5, label="test JSON")


def test_cli_rejects_arbitrary_registry_target_without_network(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--target",
            "https://example.invalid/simple",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "invalid choice" in completed.stderr
    assert "pypi" in completed.stderr
    assert "testpypi" in completed.stderr
