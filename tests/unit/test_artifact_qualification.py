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
deformation_wheel_required = cast(
    tuple[str, ...],
    QUALIFIER["DEFORMATION_WHEEL_REQUIRED"],
)
deformation_sdist_required = cast(
    tuple[str, ...],
    QUALIFIER["DEFORMATION_SDIST_REQUIRED"],
)
numeric_wheel_required = cast(
    tuple[str, ...],
    QUALIFIER["NUMERIC_WHEEL_REQUIRED"],
)
numeric_sdist_required = cast(
    tuple[str, ...],
    QUALIFIER["NUMERIC_SDIST_REQUIRED"],
)
padic_wheel_required = cast(
    tuple[str, ...],
    QUALIFIER["PADIC_WHEEL_REQUIRED"],
)
padic_sdist_required = cast(
    tuple[str, ...],
    QUALIFIER["PADIC_SDIST_REQUIRED"],
)
bootstrap_wheel_required = cast(
    tuple[str, ...],
    QUALIFIER["BOOTSTRAP_WHEEL_REQUIRED"],
)
bootstrap_sdist_required = cast(
    tuple[str, ...],
    QUALIFIER["BOOTSTRAP_SDIST_REQUIRED"],
)
compatibility_index = cast(str, QUALIFIER["COMPATIBILITY_INDEX"])
required_wheel_paths = cast(Callable[[str], tuple[str, ...]], QUALIFIER["required_wheel_paths"])
required_sdist_paths = cast(Callable[..., tuple[str, ...]], QUALIFIER["required_sdist_paths"])
required_source_archive_paths = cast(
    Callable[..., tuple[str, ...]],
    QUALIFIER["required_source_archive_paths"],
)
packaged_example_commands = cast(
    Callable[..., tuple[tuple[str, ...], ...]],
    QUALIFIER["_packaged_example_commands"],
)
campaign_template_test_commands = cast(
    Callable[..., tuple[tuple[str, ...], ...]],
    QUALIFIER["_campaign_template_test_commands"],
)
validate_doctor_result = cast(Callable[..., None], QUALIFIER["_validate_doctor_result"])
doctor_fields = cast(frozenset[str], QUALIFIER["DOCTOR_FIELDS"])
doctor_modes = cast(tuple[str, ...], QUALIFIER["DOCTOR_MODES"])
compare_pari_anchors = cast(Callable[[Path], None], PARI_ANCHOR["compare_directory"])
build_source_archive = cast(Callable[..., Path], SOURCE_BUILDER["build_source_archive"])
cross_artifact_consistency = cast(
    Callable[[Path, Path, Path, str], None],
    QUALIFIER["_cross_artifact_consistency"],
)


def _at_least_030(version: str) -> bool:
    return tuple(int(part) for part in version.split(".")) >= (0, 3, 0)


def _doctor_payload(mode: str, *, ready: bool) -> dict[str, object]:
    payload: dict[str, object] = {field: None for field in doctor_fields}
    payload.update(
        {
            "schema": "arbogast.environment-preflight.v1",
            "mode": mode,
            "profile": {"name": f"{mode}-profile"},
            "authoritative": False,
            "status": "READY" if ready else "BLOCKED",
            "ready": ready,
            "captured_at": "2026-08-30T00:00:00Z",
            "environment_digest": "sha256:" + "0" * 64,
            "arbogast": {},
            "python": {},
            "uv": {},
            "project": {},
            "portable_core": {},
            "capabilities": [],
            "checks": [
                {
                    "name": "installed-identity",
                    "requirement": "REQUIRED",
                    "status": "SATISFIED" if ready else "UNSATISFIED",
                    "detail": "installed candidate identity",
                    "evidence": {},
                }
            ],
            "required_blockers": [] if ready else ["installed-identity"],
            "optional_blockers": [],
            "warnings": [],
            "next_commands": [],
        }
    )
    return payload


def _wheel(
    tmp_path: Path,
    *,
    version: str = "0.2.0",
    unsafe: bool = False,
    omit: str | None = None,
) -> Path:
    path = tmp_path / f"arbogast-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name in required_wheel_paths(version):
            if name == omit:
                continue
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
    omit: str | None = None,
) -> Path:
    path = tmp_path / f"arbogast-{version}.tar.gz"
    prefix = f"arbogast-{version}"
    payloads: dict[str, bytes] = {relative: b"fixture\n" for relative in sdist_required}
    if _at_least_030(version):
        payloads[compatibility_index] = (PROJECT_ROOT / compatibility_index).read_bytes()
    for relative in required_sdist_paths(payloads, version):
        payloads.setdefault(relative, b"fixture\n")
    payloads.update({f"src/{relative}": b"fixture\n" for relative in required_wheel_paths(version)})
    payloads["pyproject.toml"] = f'[project]\nname = "arbogast"\nversion = "{version}"\n'.encode()
    payloads["src/arbogast/__init__.py"] = f'__version__ = "{version}"\n'.encode()
    payloads[f"docs/release-notes-{version}.md"] = b"release notes\n"
    payloads["PKG-INFO"] = (
        f"Metadata-Version: 2.4\nName: arbogast\nVersion: {metadata_version or version}\n"
    ).encode()
    if omit is not None:
        payloads.pop(omit, None)
    with tarfile.open(path, "w:gz") as archive:
        for relative, payload in sorted(payloads.items()):
            _tar_member(archive, f"{prefix}/{relative}", payload)
    return path


def _source_archive(
    tmp_path: Path,
    *,
    version: str = "0.2.0",
    omit: str | None = None,
) -> Path:
    path = tmp_path / f"arbogast-{version}-source.tar.gz"
    prefix = f"arbogast-{version}"
    payloads: dict[str, bytes] = {relative: b"fixture\n" for relative in source_required}
    if _at_least_030(version):
        payloads[compatibility_index] = (PROJECT_ROOT / compatibility_index).read_bytes()
    for relative in required_source_archive_paths(payloads, version):
        payloads.setdefault(relative, b"fixture\n")
    payloads.update({f"src/{relative}": b"fixture\n" for relative in required_wheel_paths(version)})
    payloads["pyproject.toml"] = f'[project]\nname = "arbogast"\nversion = "{version}"\n'.encode()
    payloads["src/arbogast/__init__.py"] = f'__version__ = "{version}"\n'.encode()
    payloads[f"docs/release-notes-{version}.md"] = b"release notes\n"
    if omit is not None:
        payloads.pop(omit, None)
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


def test_pre_deformation_release_surfaces_remain_unchanged() -> None:
    assert required_wheel_paths("0.1.0") == wheel_required
    assert required_wheel_paths("0.2.0") == wheel_required
    for version in ("0.1.0", "0.2.0"):
        required = required_sdist_paths({}, version)
        assert set(sdist_required).issubset(required)
        assert f"docs/release-notes-{version}.md" in required
        assert compatibility_index not in required
        assert not set(deformation_sdist_required).intersection(required)


def test_v030_release_surface_remains_free_of_numeric_040_paths() -> None:
    assert set(numeric_wheel_required).isdisjoint(required_wheel_paths("0.3.0"))
    assert set(numeric_sdist_required).isdisjoint(required_sdist_paths({}, "0.3.0"))


def test_v040_release_surface_remains_free_of_padic_050_paths() -> None:
    assert set(padic_wheel_required).isdisjoint(required_wheel_paths("0.4.0"))
    assert set(padic_sdist_required).isdisjoint(required_sdist_paths({}, "0.4.0"))


def test_v050_release_surface_remains_free_of_bootstrap_060_paths() -> None:
    assert set(bootstrap_wheel_required).isdisjoint(required_wheel_paths("0.5.0"))
    assert set(bootstrap_sdist_required).isdisjoint(required_sdist_paths({}, "0.5.0"))


def test_v060_bootstrap_artifact_lists_cover_the_entire_package() -> None:
    expected_modules = {
        relative.removeprefix("arbogast/bootstrap/") for relative in bootstrap_wheel_required
    }
    actual_modules = {path.name for path in (PROJECT_ROOT / "src/arbogast/bootstrap").glob("*.py")}

    assert expected_modules == actual_modules
    assert {f"src/{relative}" for relative in bootstrap_wheel_required}.issubset(
        bootstrap_sdist_required
    )


def test_v030_release_trio_requires_and_binds_the_deformation_surface(tmp_path: Path) -> None:
    wheel_path = _wheel(tmp_path, version="0.3.0")
    sdist_path = _sdist(tmp_path, version="0.3.0")
    source_path = _source_archive(tmp_path, version="0.3.0")

    inspect_wheel(wheel_path, "0.3.0")
    inspect_sdist(sdist_path, "0.3.0")
    inspect_source_archive(source_path, "0.3.0")
    cross_artifact_consistency(wheel_path, sdist_path, source_path, "0.3.0")

    assert set(deformation_wheel_required).issubset(required_wheel_paths("0.3.0"))
    with tarfile.open(sdist_path, "r:gz") as archive:
        names = {member.name.removeprefix("arbogast-0.3.0/") for member in archive}
    assert set(deformation_sdist_required).issubset(names)


def test_v030_release_trio_rejects_missing_deformation_and_prior_contracts(
    tmp_path: Path,
) -> None:
    missing_wheel = deformation_wheel_required[-1]
    with pytest.raises(QualificationError, match=missing_wheel):
        inspect_wheel(_wheel(tmp_path, version="0.3.0", omit=missing_wheel), "0.3.0")

    missing_documentation = "docs/deformation.md"
    with pytest.raises(QualificationError, match=missing_documentation):
        inspect_sdist(
            _sdist(tmp_path, version="0.3.0", omit=missing_documentation),
            "0.3.0",
        )

    missing_prior_fixture = "tests/fixtures/compat/v0.2.0/semantic-contracts.json"
    with pytest.raises(QualificationError, match=missing_prior_fixture):
        inspect_sdist(
            _sdist(tmp_path, version="0.3.0", omit=missing_prior_fixture),
            "0.3.0",
        )

    missing_journey = "examples/deformation/finite_lifts/run.py"
    with pytest.raises(QualificationError, match=missing_journey):
        inspect_source_archive(
            _source_archive(tmp_path, version="0.3.0", omit=missing_journey),
            "0.3.0",
        )


def test_v040_release_trio_requires_and_binds_the_numeric_surface(tmp_path: Path) -> None:
    wheel_path = _wheel(tmp_path, version="0.4.0")
    sdist_path = _sdist(tmp_path, version="0.4.0")
    source_path = _source_archive(tmp_path, version="0.4.0")

    inspect_wheel(wheel_path, "0.4.0")
    inspect_sdist(sdist_path, "0.4.0")
    inspect_source_archive(source_path, "0.4.0")
    cross_artifact_consistency(wheel_path, sdist_path, source_path, "0.4.0")

    assert set(numeric_wheel_required).issubset(required_wheel_paths("0.4.0"))
    with tarfile.open(sdist_path, "r:gz") as archive:
        names = {member.name.removeprefix("arbogast-0.4.0/") for member in archive}
    assert set(numeric_sdist_required).issubset(names)
    assert "tests/unit/test_numeric_b2_homotopy.py" in numeric_sdist_required
    assert "tests/unit/test_numeric_core.py" in numeric_sdist_required
    assert "tests/unit/test_numeric_cover.py" in numeric_sdist_required
    assert "tests/unit/test_numeric_weighted_braid.py" in numeric_sdist_required
    assert "examples/numeric/two_sheet_cover/fixture.py" in numeric_sdist_required


def test_v040_release_trio_fails_closed_for_every_numeric_path(tmp_path: Path) -> None:
    for relative in numeric_wheel_required:
        with pytest.raises(QualificationError, match=relative):
            inspect_wheel(
                _wheel(tmp_path, version="0.4.0", omit=relative),
                "0.4.0",
            )

    for relative in numeric_sdist_required:
        with pytest.raises(QualificationError, match=relative):
            inspect_sdist(
                _sdist(tmp_path, version="0.4.0", omit=relative),
                "0.4.0",
            )
        with pytest.raises(QualificationError, match=relative):
            inspect_source_archive(
                _source_archive(tmp_path, version="0.4.0", omit=relative),
                "0.4.0",
            )


def test_v050_release_trio_requires_and_binds_the_padic_surface(tmp_path: Path) -> None:
    wheel_path = _wheel(tmp_path, version="0.5.0")
    sdist_path = _sdist(tmp_path, version="0.5.0")
    source_path = _source_archive(tmp_path, version="0.5.0")

    inspect_wheel(wheel_path, "0.5.0")
    inspect_sdist(sdist_path, "0.5.0")
    inspect_source_archive(source_path, "0.5.0")
    cross_artifact_consistency(wheel_path, sdist_path, source_path, "0.5.0")

    assert set(padic_wheel_required).issubset(required_wheel_paths("0.5.0"))
    with tarfile.open(sdist_path, "r:gz") as archive:
        names = {member.name.removeprefix("arbogast-0.5.0/") for member in archive}
    assert set(padic_sdist_required).issubset(names)

    expected_sources = {path.removeprefix("arbogast/padic/") for path in padic_wheel_required}
    actual_sources = {path.name for path in (PROJECT_ROOT / "src/arbogast/padic").glob("*.py")}
    assert len(expected_sources) == 18
    assert expected_sources == actual_sources


def test_v050_release_trio_fails_closed_for_every_padic_path(tmp_path: Path) -> None:
    for relative in padic_wheel_required:
        with pytest.raises(QualificationError, match=relative):
            inspect_wheel(
                _wheel(tmp_path, version="0.5.0", omit=relative),
                "0.5.0",
            )

    for relative in padic_sdist_required:
        with pytest.raises(QualificationError, match=relative):
            inspect_sdist(
                _sdist(tmp_path, version="0.5.0", omit=relative),
                "0.5.0",
            )
        with pytest.raises(QualificationError, match=relative):
            inspect_source_archive(
                _source_archive(tmp_path, version="0.5.0", omit=relative),
                "0.5.0",
            )


def test_v060_release_trio_requires_and_binds_the_bootstrap_surface(tmp_path: Path) -> None:
    assert "arbogast/bootstrap/dispatch.py" in bootstrap_wheel_required
    assert "src/arbogast/bootstrap/dispatch.py" in bootstrap_sdist_required

    wheel_path = _wheel(tmp_path, version="0.6.0")
    sdist_path = _sdist(tmp_path, version="0.6.0")
    source_path = _source_archive(tmp_path, version="0.6.0")

    inspect_wheel(wheel_path, "0.6.0")
    inspect_sdist(sdist_path, "0.6.0")
    inspect_source_archive(source_path, "0.6.0")
    cross_artifact_consistency(wheel_path, sdist_path, source_path, "0.6.0")

    with zipfile.ZipFile(wheel_path) as archive:
        wheel_names = {info.filename for info in archive.infolist()}
    assert set(bootstrap_wheel_required).issubset(wheel_names)
    assert all(not name.startswith(("docs/", "examples/", "prompts/")) for name in wheel_names)

    with tarfile.open(sdist_path, "r:gz") as archive:
        sdist_names = {member.name.removeprefix("arbogast-0.6.0/") for member in archive}
    assert set(bootstrap_sdist_required).issubset(sdist_names)
    assert "docs/release-notes-0.6.0.md" in sdist_names
    assert "tests/fixtures/compat/v0.5.0/release.json" in sdist_names
    assert "tests/fixtures/compat/v0.5.0/api-cli-contracts.json" in sdist_names
    assert "tests/fixtures/compat/v0.5.0/semantic-contracts.json" in sdist_names


def test_v060_release_trio_fails_closed_for_every_bootstrap_path(tmp_path: Path) -> None:
    for relative in bootstrap_wheel_required:
        with pytest.raises(QualificationError, match=relative):
            inspect_wheel(
                _wheel(tmp_path, version="0.6.0", omit=relative),
                "0.6.0",
            )

    for relative in bootstrap_sdist_required:
        with pytest.raises(QualificationError, match=relative):
            inspect_sdist(
                _sdist(tmp_path, version="0.6.0", omit=relative),
                "0.6.0",
            )
        with pytest.raises(QualificationError, match=relative):
            inspect_source_archive(
                _source_archive(tmp_path, version="0.6.0", omit=relative),
                "0.6.0",
            )

    wheel = _wheel(tmp_path, version="0.6.0")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("docs/agent-bootstrap.md", b"must remain in source artifacts\n")
    with pytest.raises(QualificationError, match="package and dist-info files only"):
        inspect_wheel(wheel, "0.6.0")


@pytest.mark.parametrize(
    "relative",
    (
        "docs/release-notes-0.6.0.md",
        "docs/release-notes-0.5.0.md",
        "tests/fixtures/compat/v0.5.0/api-cli-contracts.json",
        "tests/fixtures/compat/v0.5.0/release.json",
        "tests/fixtures/compat/v0.5.0/semantic-contracts.json",
    ),
)
def test_v060_release_trio_fails_closed_when_a_release_contract_is_missing(
    tmp_path: Path,
    relative: str,
) -> None:
    with pytest.raises(QualificationError, match=relative):
        inspect_sdist(
            _sdist(tmp_path, version="0.6.0", omit=relative),
            "0.6.0",
        )
    with pytest.raises(QualificationError, match=relative):
        inspect_source_archive(
            _source_archive(tmp_path, version="0.6.0", omit=relative),
            "0.6.0",
        )


def test_prior_compatibility_surface_is_derived_from_the_packaged_index() -> None:
    payload = (PROJECT_ROOT / compatibility_index).read_bytes()
    index = json.loads(payload)
    required = set(required_sdist_paths({compatibility_index: payload}, "0.6.0"))

    for release in index["releases"]:
        assert release["release_notes"]["path"] in required
        for fixture in release["fixture_files"]:
            assert fixture["path"] in required
    assert "docs/release-notes-0.3.0.md" in required
    assert "docs/release-notes-0.4.0.md" in required
    assert "docs/release-notes-0.5.0.md" in required
    assert "tests/fixtures/compat/v0.5.0/release.json" in required
    assert "tests/fixtures/compat/v0.5.0/api-cli-contracts.json" in required
    assert "tests/fixtures/compat/v0.5.0/semantic-contracts.json" in required


def test_future_minor_release_adds_newly_indexed_prior_contracts() -> None:
    index = json.loads((PROJECT_ROOT / compatibility_index).read_text(encoding="utf-8"))
    index["releases"].append(
        {
            "fixture_files": [
                {"path": "tests/fixtures/compat/v0.6.0/release.json"},
                {"path": "tests/fixtures/compat/v0.6.0/bootstrap-contracts.json"},
            ],
            "release_notes": {"path": "docs/release-notes-0.6.0.md"},
            "version": "0.6.0",
        }
    )
    payload = json.dumps(index).encode()
    required = set(required_sdist_paths({compatibility_index: payload}, "0.7.0"))

    assert "tests/fixtures/compat/v0.6.0/release.json" in required
    assert "tests/fixtures/compat/v0.6.0/bootstrap-contracts.json" in required
    assert "docs/release-notes-0.6.0.md" in required
    assert "docs/release-notes-0.7.0.md" in required
    assert set(deformation_sdist_required).issubset(required)
    assert set(numeric_sdist_required).issubset(required)
    assert set(padic_sdist_required).issubset(required)
    assert set(bootstrap_sdist_required).issubset(required)


def test_packaged_deformation_journeys_begin_with_v030(tmp_path: Path) -> None:
    python = tmp_path / "venv" / "bin" / "python"
    v020 = packaged_example_commands(
        python,
        tmp_path / "v020",
        version="0.2.0",
        require_gp=False,
    )
    v030 = packaged_example_commands(
        python,
        tmp_path / "v030",
        version="0.3.0",
        require_gp=False,
    )
    v040_with_gp = packaged_example_commands(
        python,
        tmp_path / "v040",
        version="0.4.0",
        require_gp=True,
    )
    v050 = packaged_example_commands(
        python,
        tmp_path / "v050",
        version="0.5.0",
        require_gp=False,
    )

    v020_scripts = {command[1] for command in v020}
    v030_scripts = {command[1] for command in v030}
    v040_scripts = {command[1] for command in v040_with_gp}
    v050_scripts = {command[1] for command in v050}
    deformation_scripts = {
        "examples/deformation/exact_spaces/run.py",
        "examples/deformation/finite_lifts/run.py",
    }
    assert v020_scripts.isdisjoint(deformation_scripts)
    assert deformation_scripts.issubset(v030_scripts)
    assert deformation_scripts.issubset(v040_scripts)
    numeric_scripts = {
        "examples/numeric/two_sheet_cover/run.py",
        "examples/numeric/sqrt2_exactification/run.py",
        "examples/numeric/weighted_braid_plan/run.py",
    }
    assert v020_scripts.isdisjoint(numeric_scripts)
    assert v030_scripts.isdisjoint(numeric_scripts)
    assert numeric_scripts.issubset(v040_scripts)
    padic_scripts = {
        "examples/padic/frobenius_slopes/run.py",
        "examples/padic/three_point_good_reduction/run.py",
        "examples/padic/special_deformation_datum/run.py",
        "examples/padic/lifts_rigid_descent/run.py",
        "examples/padic/m23_local_frontier/run.py",
    }
    assert v020_scripts.isdisjoint(padic_scripts)
    assert v030_scripts.isdisjoint(padic_scripts)
    assert v040_scripts.isdisjoint(padic_scripts)
    assert padic_scripts.issubset(v050_scripts)
    assert v050_scripts - v040_scripts == padic_scripts
    assert any("--with-pari" in command for command in v040_with_gp)


def test_packaged_campaign_template_tests_use_installed_candidate_without_tag_resolution(
    tmp_path: Path,
) -> None:
    uv = str(tmp_path / "tools" / "uv")
    python = tmp_path / "candidate-venv" / "bin" / "python"
    source_root = tmp_path / "source" / "arbogast-0.6.0"
    commands = campaign_template_test_commands(uv, python, source_root)

    assert commands == (
        (uv, "pip", "install", "--python", str(python), "pytest==9.1.1"),
        (
            str(python),
            "-I",
            "-m",
            "pytest",
            "-q",
            str(source_root / "examples/campaigns/_template/tests"),
        ),
    )
    encoded = "\n".join(" ".join(command) for command in commands)
    assert "git+" not in encoded
    assert "@v0.6.0" not in encoded
    assert "github.com" not in encoded
    assert "uv lock" not in encoded
    assert "uv sync" not in encoded
    lock = (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "pytest"\nversion = "9.1.1"' in lock


@pytest.mark.parametrize(
    ("mode", "ready", "returncode"),
    (
        ("campaign", False, 1),
        ("core", False, 1),
        ("replay", True, 0),
    ),
)
def test_installed_doctor_smoke_validates_complete_json_and_exact_exit_semantics(
    mode: str,
    ready: bool,
    returncode: int,
) -> None:
    completed = subprocess.CompletedProcess(
        ("python", "-m", "arbogast.cli", "doctor"),
        returncode,
        json.dumps(_doctor_payload(mode, ready=ready)),
        "",
    )
    validate_doctor_result(completed, mode=mode, expected_ready=ready)

    wrong_exit = subprocess.CompletedProcess(
        completed.args,
        1 - returncode,
        completed.stdout,
        "",
    )
    with pytest.raises(QualificationError, match="exit semantics mismatch"):
        validate_doctor_result(wrong_exit, mode=mode, expected_ready=ready)


def test_installed_doctor_smoke_rejects_false_authority_and_inconsistent_readiness() -> None:
    assert doctor_modes == ("campaign", "core", "replay")
    payload = _doctor_payload("replay", ready=True)
    payload["authoritative"] = True
    completed = subprocess.CompletedProcess(("doctor",), 0, json.dumps(payload), "")
    with pytest.raises(QualificationError, match="non-authoritative"):
        validate_doctor_result(completed, mode="replay", expected_ready=True)

    payload = _doctor_payload("replay", ready=True)
    payload["checks"] = [
        {
            "name": "installed-identity",
            "requirement": "REQUIRED",
            "status": "UNSATISFIED",
            "detail": "installed candidate identity",
            "evidence": {},
        }
    ]
    completed = subprocess.CompletedProcess(("doctor",), 0, json.dumps(payload), "")
    with pytest.raises(QualificationError, match="status does not match"):
        validate_doctor_result(completed, mode="replay", expected_ready=True)


def test_installed_doctor_smoke_derives_readiness_from_status_and_required_checks() -> None:
    payload = _doctor_payload("campaign", ready=False)
    payload["status"] = "PARTIAL"
    payload["checks"] = [
        {
            "name": "installed-identity",
            "requirement": "REQUIRED",
            "status": "PARTIAL",
            "detail": "installed candidate identity",
            "evidence": {},
        }
    ]
    completed = subprocess.CompletedProcess(("doctor",), 1, json.dumps(payload), "")

    validate_doctor_result(completed, mode="campaign", expected_ready=False)


def test_release_workflow_derives_candidate_identity_and_preserves_ci_anchors() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "0.2.0" not in workflow
    assert 'python-version: ["3.11", "3.12", "3.13", "3.14"]' in workflow
    assert "command -v gp" in workflow
    assert "candidate_name=arbogast-{version}-candidates" in workflow
    assert 're.fullmatch(r"[0-9]+\\.[0-9]+\\.[0-9]+", version)' in workflow
    assert "needs.release-qualification.outputs.candidate_name" in workflow
    assert "needs.release-qualification.outputs.version" in workflow
    assert "pari-2.15.5.tar.gz" in workflow
    assert "pari-2.17.4.tar.gz" in workflow
    assert "scripts/pari_anchor_payload.py" in workflow
    assert "tests/integration/test_pari_live.py" in workflow
    assert "--require-gp" in workflow
    assert "uv run python examples/numeric/two_sheet_cover/run.py" in workflow
    assert "uv run python examples/numeric/sqrt2_exactification/run.py" in workflow
    assert "uv run python examples/numeric/weighted_braid_plan/run.py" in workflow
    assert "uv run python examples/padic/frobenius_slopes/run.py" in workflow
    assert "uv run python examples/padic/three_point_good_reduction/run.py" in workflow
    assert "uv run python examples/padic/special_deformation_datum/run.py" in workflow
    assert "uv run python examples/padic/lifts_rigid_descent/run.py" in workflow
    assert "uv run python examples/padic/m23_local_frontier/run.py" in workflow
    assert "PYTHONPATH=examples/campaigns/_template/src" in workflow
    assert "examples/campaigns/_template/tests" in workflow
    assert "_smoke_doctor_modes" in workflow


@pytest.mark.parametrize("version", ("0.3", "v0.3.0", "0.3.0.dev1", "../../0.3.0"))
def test_release_version_must_be_a_safe_final_version(version: str) -> None:
    with pytest.raises(QualificationError, match=r"final X\.Y\.Z version"):
        required_wheel_paths(version)


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
