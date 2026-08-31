from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = PROJECT_ROOT / "scripts/verify_pypi_artifacts.py"
VERSION = "0.6.0"
TAG = f"v{VERSION}"
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
REQUIRES_PYTHON = ">=3.11,<3.15"


def _metadata(
    *,
    name: str = "arbogast",
    version: str = VERSION,
    requires_python: str = REQUIRES_PYTHON,
) -> bytes:
    return (
        "Metadata-Version: 2.4\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        f"Requires-Python: {requires_python}\n"
    ).encode()


def _tar_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    archive.addfile(member, io.BytesIO(payload))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(
    tmp_path: Path,
    *,
    wheel_metadata: bytes | None = None,
    sdist_metadata: bytes | None = None,
) -> tuple[Path, Path, str, str]:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    wheel_path = dist_dir / f"arbogast-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as archive:
        archive.writestr(
            f"arbogast-{VERSION}.dist-info/METADATA",
            wheel_metadata if wheel_metadata is not None else _metadata(),
        )
        archive.writestr(
            f"arbogast-{VERSION}.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )

    sdist_path = dist_dir / f"arbogast-{VERSION}.tar.gz"
    with tarfile.open(sdist_path, "w:gz") as archive:
        _tar_member(
            archive,
            f"arbogast-{VERSION}/PKG-INFO",
            sdist_metadata if sdist_metadata is not None else _metadata(),
        )
    wheel_sha256 = _sha256(wheel_path)
    sdist_sha256 = _sha256(sdist_path)
    manifest_path = tmp_path / f"v{VERSION}.json"
    _write_manifest(
        manifest_path,
        _manifest_payload(dist_dir, wheel_sha256, sdist_sha256),
    )
    return dist_dir, manifest_path, wheel_sha256, sdist_sha256


def _manifest_payload(
    dist_dir: Path,
    wheel_sha256: str,
    sdist_sha256: str,
) -> dict[str, object]:
    wheel_path = dist_dir / f"arbogast-{VERSION}-py3-none-any.whl"
    sdist_path = dist_dir / f"arbogast-{VERSION}.tar.gz"
    return {
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
        "project": "arbogast",
        "schema": "arbogast.pypi-release-manifest/v1",
        "source_commit": SOURCE_COMMIT,
        "tag": TAG,
        "version": VERSION,
    }


def _write_manifest(
    path: Path,
    payload: dict[str, object],
    *,
    canonical: bool = True,
) -> None:
    if canonical:
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    else:
        rendered = json.dumps(payload, sort_keys=True) + "\n"
    path.write_text(rendered)


def _run(
    dist_dir: Path,
    manifest_path: Path,
    expected_wheel_sha256: str,
    expected_sdist_sha256: str,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    values = {
        "tag": TAG,
        "version": VERSION,
        "source_commit": SOURCE_COMMIT,
        "wheel_sha256": expected_wheel_sha256,
        "sdist_sha256": expected_sdist_sha256,
        **overrides,
    }
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--dist-dir",
            str(dist_dir),
            "--manifest",
            str(manifest_path),
            "--tag",
            values["tag"],
            "--version",
            values["version"],
            "--source-commit",
            values["source_commit"],
            "--wheel-sha256",
            values["wheel_sha256"],
            "--sdist-sha256",
            values["sdist_sha256"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_success_emits_deterministic_json_summary(tmp_path: Path) -> None:
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(tmp_path)

    assert manifest_path.name == "v0.6.0.json"
    first = _run(dist_dir, manifest_path, wheel_sha256, sdist_sha256)
    second = _run(dist_dir, manifest_path, wheel_sha256, sdist_sha256)

    assert first.returncode == 0
    assert first.stderr == ""
    assert second.stdout == first.stdout
    expected = {
        "artifacts": [
            {
                "filename": f"arbogast-{VERSION}-py3-none-any.whl",
                "kind": "wheel",
                "sha256": wheel_sha256,
            },
            {
                "filename": f"arbogast-{VERSION}.tar.gz",
                "kind": "sdist",
                "sha256": sdist_sha256,
            },
        ],
        "metadata": {
            "name": "arbogast",
            "requires_python": REQUIRES_PYTHON,
            "version": VERSION,
        },
        "manifest_sha256": _sha256(manifest_path),
        "schema": "arbogast.pypi-artifact-verification/v1",
        "source_commit": SOURCE_COMMIT,
        "status": "verified",
        "tag": TAG,
        "version": VERSION,
    }
    assert json.loads(first.stdout) == expected
    assert first.stdout == json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("version", "0.6"),
        ("tag", "0.6.0"),
        ("tag", "v0.6.1"),
        ("source_commit", "A" * 40),
        ("source_commit", "0" * 39),
        ("wheel_sha256", "A" * 64),
        ("sdist_sha256", "0" * 63),
    ],
)
def test_identifier_tampering_fails_closed(tmp_path: Path, field: str, tampered: str) -> None:
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(tmp_path)

    completed = _run(
        dist_dir,
        manifest_path,
        wheel_sha256,
        sdist_sha256,
        **{field: tampered},
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr.startswith("verification failed: ")


@pytest.mark.parametrize("mutation", ["extra", "foreign", "missing"])
def test_nonexact_distribution_directory_fails_closed(tmp_path: Path, mutation: str) -> None:
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(tmp_path)
    if mutation == "extra":
        (dist_dir / "checksums.txt").write_text("not publishable\n")
    elif mutation == "foreign":
        (dist_dir / f"arbogast-{VERSION}.tar.gz").rename(
            dist_dir / f"arbogast-{VERSION}-source.tar.gz"
        )
    else:
        (dist_dir / f"arbogast-{VERSION}-py3-none-any.whl").unlink()

    completed = _run(dist_dir, manifest_path, wheel_sha256, sdist_sha256)

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "must contain exactly the expected artifacts" in completed.stderr


@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
def test_hash_tampering_fails_closed(tmp_path: Path, artifact: str) -> None:
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(tmp_path)
    tampered = "0" * 64
    if artifact == "wheel":
        assert tampered != wheel_sha256
        completed = _run(dist_dir, manifest_path, tampered, sdist_sha256)
    else:
        assert tampered != sdist_sha256
        completed = _run(dist_dir, manifest_path, wheel_sha256, tampered)

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert f"{artifact} SHA-256 mismatch" in completed.stderr


@pytest.mark.parametrize("tamper", ["digest", "size", "commit"])
def test_manifest_binding_tampering_fails_closed(tmp_path: Path, tamper: str) -> None:
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(tmp_path)
    payload = _manifest_payload(dist_dir, wheel_sha256, sdist_sha256)
    artifacts = cast(list[dict[str, object]], payload["artifacts"])
    if tamper == "digest":
        artifacts[0]["sha256"] = "0" * 64
    elif tamper == "size":
        size = artifacts[1]["size"]
        assert isinstance(size, int)
        artifacts[1]["size"] = size + 1
    else:
        payload["source_commit"] = "f" * 40
    _write_manifest(manifest_path, payload)

    completed = _run(dist_dir, manifest_path, wheel_sha256, sdist_sha256)

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "publication manifest must be the canonical exact binding" in completed.stderr


def test_noncanonical_manifest_json_fails_closed(tmp_path: Path) -> None:
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(tmp_path)
    _write_manifest(
        manifest_path,
        _manifest_payload(dist_dir, wheel_sha256, sdist_sha256),
        canonical=False,
    )

    completed = _run(dist_dir, manifest_path, wheel_sha256, sdist_sha256)

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "publication manifest must be the canonical exact binding" in completed.stderr


def test_wrong_manifest_filename_fails_closed(tmp_path: Path) -> None:
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(tmp_path)
    wrong_path = manifest_path.with_name("release.json")
    manifest_path.rename(wrong_path)

    completed = _run(dist_dir, wrong_path, wheel_sha256, sdist_sha256)

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "manifest filename must be exactly 'v0.6.0.json'" in completed.stderr


@pytest.mark.parametrize("state", ["missing", "symlink"])
def test_nonregular_manifest_fails_closed(tmp_path: Path, state: str) -> None:
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(tmp_path)
    if state == "missing":
        manifest_path.unlink()
    else:
        target_path = manifest_path.with_name("manifest-target.json")
        manifest_path.rename(target_path)
        manifest_path.symlink_to(target_path)

    completed = _run(dist_dir, manifest_path, wheel_sha256, sdist_sha256)

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "manifest is not a regular file" in completed.stderr


@pytest.mark.parametrize("mismatch", ["name", "version", "requires-python"])
def test_cross_artifact_metadata_mismatch_fails_closed(tmp_path: Path, mismatch: str) -> None:
    wheel_metadata = _metadata()
    sdist_metadata = _metadata()
    if mismatch == "name":
        wheel_metadata = _metadata(name="other-project")
    elif mismatch == "version":
        sdist_metadata = _metadata(version="0.6.1")
    else:
        sdist_metadata = _metadata(requires_python=">=3.12,<3.15")
    dist_dir, manifest_path, wheel_sha256, sdist_sha256 = _artifacts(
        tmp_path,
        wheel_metadata=wheel_metadata,
        sdist_metadata=sdist_metadata,
    )

    completed = _run(dist_dir, manifest_path, wheel_sha256, sdist_sha256)

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "metadata" in completed.stderr.lower()


def test_cli_arguments_are_required() -> None:
    completed = subprocess.run(
        [sys.executable, str(VERIFIER)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    for option in (
        "--dist-dir",
        "--manifest",
        "--tag",
        "--version",
        "--source-commit",
        "--wheel-sha256",
        "--sdist-sha256",
    ):
        assert option in completed.stderr
