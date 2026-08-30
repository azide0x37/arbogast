from __future__ import annotations

import io
import json
import runpy
import subprocess
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUALIFIER = runpy.run_path(str(PROJECT_ROOT / "scripts/qualify_artifacts.py"))
PARI_ANCHOR = runpy.run_path(str(PROJECT_ROOT / "scripts/pari_anchor_payload.py"))
SOURCE_BUILDER = runpy.run_path(str(PROJECT_ROOT / "scripts/build_source_archive.py"))
inspect_wheel = cast(Callable[[Path, str], dict[str, object]], QUALIFIER["inspect_wheel"])
inspect_sdist = cast(Callable[[Path, str], dict[str, object]], QUALIFIER["inspect_sdist"])
inspect_source_archive = cast(
    Callable[[Path, str], dict[str, object]],
    QUALIFIER["inspect_source_archive"],
)
QualificationError = cast(type[ValueError], QUALIFIER["QualificationError"])
wheel_required = cast(tuple[str, ...], QUALIFIER["WHEEL_REQUIRED"])
sdist_required = cast(tuple[str, ...], QUALIFIER["SDIST_REQUIRED"])
source_required = cast(tuple[str, ...], QUALIFIER["SOURCE_ARCHIVE_REQUIRED"])
compare_pari_anchors = cast(Callable[[Path], None], PARI_ANCHOR["compare_directory"])
build_source_archive = cast(Callable[..., Path], SOURCE_BUILDER["build_source_archive"])
cross_artifact_consistency = cast(
    Callable[[Path, Path, Path, str], None],
    QUALIFIER["_cross_artifact_consistency"],
)


def _wheel(tmp_path: Path, *, version: str = "0.2.0", unsafe: bool = False) -> Path:
    path = tmp_path / f"arbogast-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name in wheel_required:
            payload = (
                f'__version__ = "{version}"\n'.encode()
                if name == "arbogast/__init__.py"
                else b"fixture\n"
            )
            archive.writestr(name, payload)
        archive.writestr(
            f"arbogast-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: arbogast\nVersion: {version}\n",
        )
        archive.writestr(
            f"arbogast-{version}.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(
            f"arbogast-{version}.dist-info/entry_points.txt",
            "[console_scripts]\narb = arbogast.cli:main\narbogast = arbogast.cli:main\n",
        )
        if unsafe:
            archive.writestr("../escape.py", b"pass\n")
    return path


def _tar_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _sdist(
    tmp_path: Path,
    *,
    version: str = "0.2.0",
    metadata_version: str | None = None,
) -> Path:
    path = tmp_path / f"arbogast-{version}.tar.gz"
    prefix = f"arbogast-{version}"
    payloads: dict[str, bytes] = {relative: b"fixture\n" for relative in sdist_required}
    payloads.update({f"src/{relative}": b"fixture\n" for relative in wheel_required})
    payloads["pyproject.toml"] = f'[project]\nname = "arbogast"\nversion = "{version}"\n'.encode()
    payloads["src/arbogast/__init__.py"] = f'__version__ = "{version}"\n'.encode()
    payloads[f"docs/release-notes-{version}.md"] = b"release notes\n"
    payloads["PKG-INFO"] = (
        f"Metadata-Version: 2.4\nName: arbogast\nVersion: {metadata_version or version}\n"
    ).encode()
    with tarfile.open(path, "w:gz") as archive:
        for relative, payload in sorted(payloads.items()):
            _tar_member(archive, f"{prefix}/{relative}", payload)
    return path


def _source_archive(tmp_path: Path, *, version: str = "0.2.0") -> Path:
    path = tmp_path / f"arbogast-{version}-source.tar.gz"
    prefix = f"arbogast-{version}"
    payloads: dict[str, bytes] = {relative: b"fixture\n" for relative in source_required}
    payloads.update({f"src/{relative}": b"fixture\n" for relative in wheel_required})
    payloads["pyproject.toml"] = f'[project]\nname = "arbogast"\nversion = "{version}"\n'.encode()
    payloads["src/arbogast/__init__.py"] = f'__version__ = "{version}"\n'.encode()
    payloads[f"docs/release-notes-{version}.md"] = b"release notes\n"
    with tarfile.open(path, "w:gz", pax_headers={"comment": "a" * 40}) as archive:
        for relative, payload in sorted(payloads.items()):
            _tar_member(archive, f"{prefix}/{relative}", payload)
    return path


def test_release_archives_are_inspected_and_content_addressed(tmp_path: Path) -> None:
    wheel_path = _wheel(tmp_path)
    sdist_path = _sdist(tmp_path)
    source_path = _source_archive(tmp_path)
    wheel = inspect_wheel(wheel_path, "0.2.0")
    sdist = inspect_sdist(sdist_path, "0.2.0")
    source = inspect_source_archive(source_path, "0.2.0")
    cross_artifact_consistency(wheel_path, sdist_path, source_path, "0.2.0")

    assert wheel["kind"] == "wheel"
    assert sdist["kind"] == "sdist"
    assert source["kind"] == "source-archive"
    assert source["source_commit"] == "a" * 40
    for record in (wheel, sdist, source):
        assert cast(str, record["sha256"]).startswith("sha256:")
        assert cast(str, record["payload_sha256"]).startswith("sha256:")
        assert cast(int, record["bytes"]) > 0


def test_source_builder_binds_one_commit_and_rejects_implicit_dirty_mix(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "arbogast"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )
    subprocess.run(("git", "init"), cwd=repository, check=True, capture_output=True)
    subprocess.run(("git", "add", "pyproject.toml"), cwd=repository, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Arbogast Test",
            "-c",
            "user.email=arbogast@example.invalid",
            "commit",
            "-m",
            "candidate",
        ),
        cwd=repository,
        check=True,
        capture_output=True,
    )
    archive = build_source_archive(repository, tmp_path / "dist", revision=None)
    with tarfile.open(archive, "r:gz") as payload:
        commit = payload.pax_headers["comment"]
    assert len(commit) == 40

    (repository / "dirty.txt").write_text("not committed\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="worktree is dirty"):
        build_source_archive(repository, tmp_path / "dirty-dist", revision=None)
    explicit = build_source_archive(repository, tmp_path / "explicit-dist", revision="HEAD")
    assert explicit.name == "arbogast-0.2.0-source.tar.gz"


def test_candidate_trio_rejects_shared_source_drift(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    sdist = _sdist(tmp_path)
    source = _source_archive(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        payloads = {info.filename: archive.read(info) for info in archive.infolist()}
    payloads["arbogast/cli.py"] = b"# different candidate source\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    inspect_wheel(wheel, "0.2.0")
    with pytest.raises(QualificationError, match="wheel/sdist shared payload mismatch"):
        cross_artifact_consistency(wheel, sdist, source, "0.2.0")


def test_release_archives_reject_unsafe_paths_and_metadata_drift(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="escapes the archive root"):
        inspect_wheel(_wheel(tmp_path, unsafe=True), "0.2.0")

    with pytest.raises(QualificationError, match="metadata mismatch"):
        inspect_sdist(_sdist(tmp_path, metadata_version="0.1.0"), "0.2.0")


def test_sdist_rejects_links_even_when_the_target_looks_internal(tmp_path: Path) -> None:
    path = _sdist(tmp_path)
    malicious = tmp_path / "arbogast-0.2.0-malicious.tar.gz"
    with tarfile.open(path, "r:gz") as source, tarfile.open(malicious, "w:gz") as target:
        for member in source.getmembers():
            stream = source.extractfile(member)
            target.addfile(member, stream)
        link = tarfile.TarInfo("arbogast-0.2.0/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "src/arbogast/__init__.py"
        target.addfile(link)
    expected_name = tmp_path / "arbogast-0.2.0.tar.gz"
    expected_name.unlink()
    malicious.rename(expected_name)

    with pytest.raises(QualificationError, match="non-regular member"):
        inspect_sdist(expected_name, "0.2.0")


def test_source_archive_is_distinct_from_a_renamed_sdist(tmp_path: Path) -> None:
    renamed = tmp_path / "arbogast-0.2.0-source.tar.gz"
    payloads = {relative: b"fixture\n" for relative in source_required}
    payloads["docs/release-notes-0.2.0.md"] = b"release notes\n"
    payloads["PKG-INFO"] = b"Name: arbogast\nVersion: 0.2.0\n"
    with tarfile.open(renamed, "w:gz") as archive:
        for relative, payload in sorted(payloads.items()):
            _tar_member(archive, f"arbogast-0.2.0/{relative}", payload)

    with pytest.raises(QualificationError, match="Git snapshot"):
        inspect_source_archive(renamed, "0.2.0")


def test_qualifier_surface_is_plain_json_data() -> None:
    assert all(isinstance(name, str) for name in wheel_required)
    assert all(isinstance(name, str) for name in sdist_required)
    assert all(isinstance(name, str) for name in source_required)
    assert cast(Any, QUALIFIER["ARCHIVE_SCHEMA"]) == "arbogast.release-qualification/v1"


def test_pari_anchor_payload_comparison_ignores_version_but_not_mathematics(
    tmp_path: Path,
) -> None:
    common_result = {
        "norm": [-1, 1],
        "s_class_2_torsion": [{"ideal_hnf": [[2, 0], [0, 1]]}],
    }
    required_payloads = cast(frozenset[str], PARI_ANCHOR["REQUIRED_MATHEMATICAL_PAYLOADS"])
    shared = {name: common_result for name in required_payloads}
    for version in ("2.15.5", "2.17.4"):
        (tmp_path / f"pari-{version}.json").write_text(
            json.dumps(
                {
                    "mathematical_payloads": shared,
                    "pari_version": version,
                    "schema": "arbogast.pari-anchor-payload/v1",
                }
            ),
            encoding="utf-8",
        )
    compare_pari_anchors(tmp_path)

    changed = json.loads((tmp_path / "pari-2.17.4.json").read_text(encoding="utf-8"))
    changed["mathematical_payloads"]["relative_norm_golden_t"]["norm"] = [1, 1]
    (tmp_path / "pari-2.17.4.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="different mathematical payloads"):
        compare_pari_anchors(tmp_path)
