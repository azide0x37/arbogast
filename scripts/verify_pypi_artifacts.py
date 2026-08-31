"""Verify the exact Arbogast distributions admitted to the PyPI boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Final

VERSION_RE: Final = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SOURCE_COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
PROJECT_NAME: Final = "arbogast"
SUMMARY_SCHEMA: Final = "arbogast.pypi-artifact-verification/v1"
MANIFEST_SCHEMA: Final = "arbogast.pypi-release-manifest/v1"
CORE_METADATA_FIELDS: Final = ("Name", "Version", "Requires-Python")


class VerificationError(ValueError):
    """Raised when files cannot cross the PyPI publication boundary."""


@dataclass(frozen=True)
class CoreMetadata:
    """The metadata fields that must agree across both distributions."""

    name: str
    version: str
    requires_python: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise VerificationError(f"cannot read artifact {path.name!r}: {exc}") from exc
    return digest.hexdigest()


def _parse_core_metadata(payload: bytes, *, artifact: str) -> CoreMetadata:
    message = BytesParser(policy=policy.default).parsebytes(payload, headersonly=True)
    if message.defects:
        defect_names = ", ".join(type(defect).__name__ for defect in message.defects)
        raise VerificationError(f"{artifact} metadata is malformed: {defect_names}")

    values: dict[str, str] = {}
    for field in CORE_METADATA_FIELDS:
        field_values = message.get_all(field, [])
        if len(field_values) != 1:
            raise VerificationError(f"{artifact} metadata must contain exactly one {field!r} field")
        value = str(field_values[0]).strip()
        if not value:
            raise VerificationError(f"{artifact} metadata field {field!r} must not be empty")
        values[field] = value

    return CoreMetadata(
        name=values["Name"],
        version=values["Version"],
        requires_python=values["Requires-Python"],
    )


def _wheel_metadata(path: Path, version: str) -> CoreMetadata:
    expected_member = f"arbogast-{version}.dist-info/METADATA"
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [
                member
                for member in archive.infolist()
                if member.filename.endswith(".dist-info/METADATA")
            ]
            if len(candidates) != 1 or candidates[0].filename != expected_member:
                found = sorted(member.filename for member in candidates)
                raise VerificationError(
                    "wheel must contain exactly the expected METADATA member "
                    f"{expected_member!r}; found {found!r}"
                )
            member = candidates[0]
            if member.is_dir():
                raise VerificationError("wheel METADATA member must be a regular file")
            payload = archive.read(member)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise VerificationError(f"cannot read wheel metadata: {exc}") from exc
    return _parse_core_metadata(payload, artifact="wheel")


def _sdist_metadata(path: Path, version: str) -> CoreMetadata:
    expected_member = f"arbogast-{version}/PKG-INFO"
    try:
        with tarfile.open(path, "r:gz") as archive:
            candidates = [
                member for member in archive.getmembers() if member.name == expected_member
            ]
            if len(candidates) != 1:
                raise VerificationError(
                    "sdist must contain exactly one expected PKG-INFO member "
                    f"{expected_member!r}; found {len(candidates)}"
                )
            member = candidates[0]
            if not member.isfile():
                raise VerificationError("sdist PKG-INFO member must be a regular file")
            stream = archive.extractfile(member)
            if stream is None:
                raise VerificationError("sdist PKG-INFO member could not be read")
            payload = stream.read()
    except (OSError, tarfile.TarError) as exc:
        raise VerificationError(f"cannot read sdist metadata: {exc}") from exc
    return _parse_core_metadata(payload, artifact="sdist")


def _validate_identifiers(
    *,
    tag: str,
    version: str,
    source_commit: str,
    wheel_sha256: str,
    sdist_sha256: str,
) -> None:
    if VERSION_RE.fullmatch(version) is None:
        raise VerificationError(f"version must be final X.Y.Z, found {version!r}")
    if tag != f"v{version}":
        raise VerificationError(f"tag must be exactly {'v' + version!r}, found {tag!r}")
    if SOURCE_COMMIT_RE.fullmatch(source_commit) is None:
        raise VerificationError("source commit must be exactly 40 lowercase hexadecimal characters")
    for label, digest in (("wheel", wheel_sha256), ("sdist", sdist_sha256)):
        if SHA256_RE.fullmatch(digest) is None:
            raise VerificationError(
                f"{label} SHA-256 must be exactly 64 lowercase hexadecimal characters"
            )


def _validate_directory(dist_dir: Path, expected_names: tuple[str, str]) -> None:
    if dist_dir.is_symlink() or not dist_dir.is_dir():
        raise VerificationError(f"distribution directory is not a regular directory: {dist_dir}")
    try:
        entries = sorted(dist_dir.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise VerificationError(f"cannot inspect distribution directory: {exc}") from exc
    actual_names = tuple(entry.name for entry in entries)
    if actual_names != tuple(sorted(expected_names)):
        raise VerificationError(
            "distribution directory must contain exactly the expected artifacts; "
            f"expected {tuple(sorted(expected_names))!r}, found {actual_names!r}"
        )
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise VerificationError(f"artifact must be a regular file: {entry.name!r}")


def _verify_manifest(
    manifest_path: Path,
    *,
    tag: str,
    version: str,
    source_commit: str,
    wheel_path: Path,
    wheel_sha256: str,
    sdist_path: Path,
    sdist_sha256: str,
) -> str:
    if manifest_path.name != f"v{version}.json":
        raise VerificationError(f"manifest filename must be exactly {'v' + version + '.json'!r}")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise VerificationError(f"manifest is not a regular file: {manifest_path}")
    try:
        payload = manifest_path.read_bytes()
    except OSError as exc:
        raise VerificationError(f"cannot read publication manifest: {exc}") from exc

    expected = {
        "artifacts": [
            {
                "filename": wheel_path.name,
                "kind": "wheel",
                "sha256": wheel_sha256,
                "size": wheel_path.stat().st_size,
            },
            {
                "filename": sdist_path.name,
                "kind": "sdist",
                "sha256": sdist_sha256,
                "size": sdist_path.stat().st_size,
            },
        ],
        "project": PROJECT_NAME,
        "schema": MANIFEST_SCHEMA,
        "source_commit": source_commit,
        "tag": tag,
        "version": version,
    }
    expected_payload = (json.dumps(expected, indent=2, sort_keys=True) + "\n").encode()
    if payload != expected_payload:
        raise VerificationError(
            "publication manifest must be the canonical exact binding of tag, commit, "
            "filenames, sizes, and SHA-256 digests"
        )
    return hashlib.sha256(payload).hexdigest()


def verify_artifacts(
    *,
    dist_dir: Path,
    manifest_path: Path,
    tag: str,
    version: str,
    source_commit: str,
    wheel_sha256: str,
    sdist_sha256: str,
) -> dict[str, object]:
    """Verify exact filenames, digests, and cross-distribution core metadata."""

    _validate_identifiers(
        tag=tag,
        version=version,
        source_commit=source_commit,
        wheel_sha256=wheel_sha256,
        sdist_sha256=sdist_sha256,
    )

    wheel_name = f"arbogast-{version}-py3-none-any.whl"
    sdist_name = f"arbogast-{version}.tar.gz"
    _validate_directory(dist_dir, (wheel_name, sdist_name))
    wheel_path = dist_dir / wheel_name
    sdist_path = dist_dir / sdist_name

    actual_wheel_sha256 = _sha256(wheel_path)
    actual_sdist_sha256 = _sha256(sdist_path)
    if actual_wheel_sha256 != wheel_sha256:
        raise VerificationError(
            f"wheel SHA-256 mismatch: expected {wheel_sha256}, found {actual_wheel_sha256}"
        )
    if actual_sdist_sha256 != sdist_sha256:
        raise VerificationError(
            f"sdist SHA-256 mismatch: expected {sdist_sha256}, found {actual_sdist_sha256}"
        )

    manifest_sha256 = _verify_manifest(
        manifest_path,
        tag=tag,
        version=version,
        source_commit=source_commit,
        wheel_path=wheel_path,
        wheel_sha256=wheel_sha256,
        sdist_path=sdist_path,
        sdist_sha256=sdist_sha256,
    )

    wheel_metadata = _wheel_metadata(wheel_path, version)
    sdist_metadata = _sdist_metadata(sdist_path, version)
    expected_metadata = CoreMetadata(
        name=PROJECT_NAME,
        version=version,
        requires_python=wheel_metadata.requires_python,
    )
    if wheel_metadata.name != PROJECT_NAME or wheel_metadata.version != version:
        raise VerificationError(
            "wheel METADATA must identify "
            f"Name {PROJECT_NAME!r} and Version {version!r}; found {wheel_metadata!r}"
        )
    if sdist_metadata.name != PROJECT_NAME or sdist_metadata.version != version:
        raise VerificationError(
            "sdist PKG-INFO must identify "
            f"Name {PROJECT_NAME!r} and Version {version!r}; found {sdist_metadata!r}"
        )
    if wheel_metadata != sdist_metadata or wheel_metadata != expected_metadata:
        raise VerificationError(
            "wheel and sdist core Name/Version/Requires-Python metadata must agree; "
            f"wheel={wheel_metadata!r}, sdist={sdist_metadata!r}"
        )

    return {
        "artifacts": [
            {"filename": wheel_name, "kind": "wheel", "sha256": actual_wheel_sha256},
            {"filename": sdist_name, "kind": "sdist", "sha256": actual_sdist_sha256},
        ],
        "metadata": {
            "name": wheel_metadata.name,
            "requires_python": wheel_metadata.requires_python,
            "version": wheel_metadata.version,
        },
        "manifest_sha256": manifest_sha256,
        "schema": SUMMARY_SCHEMA,
        "source_commit": source_commit,
        "status": "verified",
        "tag": tag,
        "version": version,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the exact Arbogast wheel and sdist admitted to PyPI publication."
    )
    parser.add_argument("--dist-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--sdist-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = verify_artifacts(
            dist_dir=args.dist_dir,
            manifest_path=args.manifest,
            tag=args.tag,
            version=args.version,
            source_commit=args.source_commit,
            wheel_sha256=args.wheel_sha256,
            sdist_sha256=args.sdist_sha256,
        )
    except VerificationError as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
