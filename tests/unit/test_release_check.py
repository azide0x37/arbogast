from __future__ import annotations

import hashlib
import json
import runpy
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKER = runpy.run_path(str(PROJECT_ROOT / "scripts/check_release.py"))
CheckSection = Callable[[Path, list[str]], None]
CheckReleaseMetadata = Callable[[Path, list[str], str], None]
CheckRequiredPaths = Callable[[Path, list[str], str], None]
check_release_metadata = cast(CheckReleaseMetadata, CHECKER["_check_release_metadata"])
check_required_paths = cast(CheckRequiredPaths, CHECKER["_check_required_paths"])
check_m23_fixture = cast(CheckSection, CHECKER["_check_m23_fixture"])
check_compatibility_index = cast(CheckSection, CHECKER["_check_compatibility_index"])
check_semantic_snapshot = cast(Callable[..., None], CHECKER["_check_semantic_snapshot"])
check_v010_compatibility = cast(CheckSection, CHECKER["_check_v010_compatibility"])
check_live_pari_matrix = cast(CheckSection, CHECKER["_check_live_pari_matrix"])
required_paths = cast(tuple[str, ...], CHECKER["REQUIRED_PATHS"])
deformation_required_paths = cast(
    tuple[str, ...],
    CHECKER["DEFORMATION_REQUIRED_PATHS"],
)
numeric_required_paths = cast(
    tuple[str, ...],
    CHECKER["NUMERIC_REQUIRED_PATHS"],
)
padic_required_paths = cast(
    tuple[str, ...],
    CHECKER["PADIC_REQUIRED_PATHS"],
)
release_required_paths = cast(Callable[[str], tuple[str, ...]], CHECKER["required_paths"])


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, sort_keys=True))


def _artifact(path: Path, relative: str) -> dict[str, object]:
    encoded = path.read_bytes()
    return {
        "path": relative,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
    }


def test_release_metadata_requires_final_version_date_and_wording(tmp_path: Path) -> None:
    _write(
        tmp_path / "CITATION.cff",
        "cff-version: 1.2.0\nversion: 0.1.0\ndate-released: 2026-08-28\n",
    )
    _write(tmp_path / "CHANGELOG.md", "# Changelog\n\n## [0.1.0] - 2026-08-28\n")
    _write(
        tmp_path / "docs/release-notes-0.1.0.md",
        "# Arbogast 0.1.0 release notes\n\nThe finite exact release.\n",
    )

    failures: list[str] = []
    check_release_metadata(tmp_path, failures, "0.1.0")
    assert failures == []

    _write(
        tmp_path / "CITATION.cff",
        "cff-version: 1.2.0\nversion: 0.1.0-dev\ndate-released: 2026-08-29\n",
    )
    _write(
        tmp_path / "docs/release-notes-0.1.0.md",
        "# Draft Arbogast 0.1.0 release notes\n",
    )
    failures = []
    check_release_metadata(tmp_path, failures, "0.1.0")
    assert any("development-release wording" in failure for failure in failures)
    assert any("release dates must match" in failure for failure in failures)
    assert any("final heading" in failure for failure in failures)

    _write(
        tmp_path / "CITATION.cff",
        "cff-version: 1.2.0\nversion: 0.1.0\ndate-released: 2026-08-28\n",
    )
    _write(
        tmp_path / "docs/release-notes-0.1.0.md",
        "# Arbogast 0.1.0 release notes\n\nThis is a development release.\n",
    )
    failures = []
    check_release_metadata(tmp_path, failures, "0.1.0")
    assert failures == ["docs/release-notes-0.1.0.md contains stale development-release wording"]


def test_release_surface_requires_ci_campaign_and_exact_m23_inputs() -> None:
    assert ".github/workflows/ci.yml" in required_paths
    assert "examples/campaigns/antieau_klueners_malle/README.md" in required_paths
    assert "examples/campaigns/antieau_klueners_malle/run.py" in required_paths
    assert "examples/hurwitz/m23_real_component/fixture.py" in required_paths
    assert "examples/hurwitz/m23_real_component/generate.g" in required_paths
    assert "examples/hurwitz/m23_real_component/expected/dataset.json" in required_paths
    assert "examples/arithmetic/aim_a_cocycle/run.py" in required_paths
    assert "examples/campaigns/antieau_klueners_malle/local_global.py" in required_paths
    assert "docs/release-notes-0.2.0.md" in release_required_paths("0.2.0")
    assert "docs/release-notes-0.1.0.md" in release_required_paths("0.2.0")
    assert "scripts/build_source_archive.py" in required_paths
    assert "scripts/pari_anchor_payload.py" in required_paths
    assert "scripts/snapshot_api_cli.py" in required_paths
    assert "scripts/snapshot_semantic_contracts.py" in required_paths
    assert "scripts/snapshot_v010_api_cli.py" in required_paths
    assert "tests/fixtures/compat/index.json" in required_paths
    assert "tests/fixtures/compat/v0.1.0/release.json" in release_required_paths("0.3.0")
    assert "tests/fixtures/compat/v0.2.0/release.json" in release_required_paths("0.3.0")
    assert "tests/fixtures/compat/v0.2.0/semantic-contracts.json" in release_required_paths("0.3.0")
    assert "docs/release-notes-0.1.0.md" in release_required_paths("0.3.0")
    assert "docs/release-notes-0.2.0.md" in release_required_paths("0.3.0")
    assert "tests/integration/test_v010_compatibility.py" in required_paths
    assert "tests/fixtures/compat/v0.3.0/release.json" in release_required_paths("0.4.0")
    assert "tests/fixtures/compat/v0.3.0/api-cli-contracts.json" in release_required_paths("0.4.0")
    assert "tests/fixtures/compat/v0.3.0/semantic-contracts.json" in release_required_paths("0.4.0")
    assert "docs/release-notes-0.3.0.md" in release_required_paths("0.4.0")


def test_numeric_release_surface_is_additive_from_v040() -> None:
    legacy = set(release_required_paths("0.3.0"))
    v040 = set(release_required_paths("0.4.0"))
    future = set(release_required_paths("0.5.0"))

    assert len(numeric_required_paths) == 30
    assert legacy.isdisjoint(numeric_required_paths)
    assert set(numeric_required_paths).issubset(v040)
    assert set(numeric_required_paths).issubset(future)
    v040_manifest = "tests/fixtures/compat/v0.4.0/release.json"
    assert v040_manifest not in v040
    assert v040_manifest in future
    assert (
        len([path for path in numeric_required_paths if path.startswith("src/arbogast/numeric/")])
        == 12
    )
    assert len([path for path in numeric_required_paths if path.endswith("_acceptance.py")]) == 4
    assert "tests/unit/test_numeric_b2_homotopy.py" in numeric_required_paths
    assert "tests/unit/test_numeric_core.py" in numeric_required_paths
    assert "tests/unit/test_numeric_cover.py" in numeric_required_paths
    assert "tests/unit/test_numeric_weighted_braid.py" in numeric_required_paths
    assert "examples/numeric/two_sheet_cover/fixture.py" in numeric_required_paths


def test_deformation_release_surface_is_additive_from_v030() -> None:
    legacy = set(release_required_paths("0.2.0"))
    v030 = set(release_required_paths("0.3.0"))
    future = set(release_required_paths("0.4.0"))

    assert len(deformation_required_paths) == 27
    assert legacy.isdisjoint(deformation_required_paths)
    assert set(deformation_required_paths).issubset(v030)
    assert set(deformation_required_paths).issubset(future)
    assert (
        len(
            [path for path in deformation_required_paths if path.startswith("src/arbogast/deform/")]
        )
        == 12
    )


def test_padic_release_surface_is_additive_from_v050() -> None:
    legacy = set(release_required_paths("0.4.0"))
    v050 = set(release_required_paths("0.5.0"))
    future = set(release_required_paths("0.6.0"))

    assert len(padic_required_paths) == 41
    assert legacy.isdisjoint(padic_required_paths)
    assert set(padic_required_paths).issubset(v050)
    assert set(padic_required_paths).issubset(future)

    expected_sources = {
        path.removeprefix("src/arbogast/padic/")
        for path in padic_required_paths
        if path.startswith("src/arbogast/padic/")
    }
    actual_sources = {path.name for path in (PROJECT_ROOT / "src/arbogast/padic").glob("*.py")}
    assert len(expected_sources) == 18
    assert expected_sources == actual_sources

    expected_examples = {
        path.removeprefix("examples/padic/")
        for path in padic_required_paths
        if path.startswith("examples/padic/")
    }
    actual_examples = {
        path.relative_to(PROJECT_ROOT / "examples/padic").as_posix()
        for path in (PROJECT_ROOT / "examples/padic").glob("**/*")
        if path.is_file() and (path.name == "README.md" or path.name == "run.py")
    }
    assert len(expected_examples) == 11
    assert expected_examples == actual_examples

    expected_tests = {path for path in padic_required_paths if "/test_padic" in path}
    actual_tests = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for base in (PROJECT_ROOT / "tests/unit", PROJECT_ROOT / "tests/integration")
        for path in base.glob("test_padic*.py")
    }
    assert len(expected_tests) == 11
    assert expected_tests == actual_tests


def test_every_deformation_release_path_fails_closed_when_deleted(tmp_path: Path) -> None:
    for relative in deformation_required_paths:
        _write(tmp_path / relative, "release-boundary fixture\n")

    failures: list[str] = []
    check_required_paths(tmp_path, failures, "0.3.0")
    deformation_failures = [
        failure
        for failure in failures
        if any(relative in failure for relative in deformation_required_paths)
    ]
    assert deformation_failures == []

    for relative in deformation_required_paths:
        path = tmp_path / relative
        path.unlink()
        failures = []
        check_required_paths(tmp_path, failures, "0.3.0")
        assert f"missing required path: {relative}" in failures
        _write(path, "release-boundary fixture\n")

    failures = []
    for relative in deformation_required_paths:
        (tmp_path / relative).unlink()
    check_required_paths(tmp_path, failures, "0.2.0")
    assert all(
        f"missing required path: {relative}" not in failures
        for relative in deformation_required_paths
    )


def test_every_numeric_release_path_fails_closed_when_deleted(tmp_path: Path) -> None:
    for relative in numeric_required_paths:
        _write(tmp_path / relative, "release-boundary fixture\n")

    failures: list[str] = []
    check_required_paths(tmp_path, failures, "0.4.0")
    numeric_failures = [
        failure
        for failure in failures
        if any(relative in failure for relative in numeric_required_paths)
    ]
    assert numeric_failures == []

    for relative in numeric_required_paths:
        path = tmp_path / relative
        path.unlink()
        failures = []
        check_required_paths(tmp_path, failures, "0.4.0")
        assert f"missing required path: {relative}" in failures
        _write(path, "release-boundary fixture\n")

    failures = []
    for relative in numeric_required_paths:
        (tmp_path / relative).unlink()
    check_required_paths(tmp_path, failures, "0.3.0")
    assert all(
        f"missing required path: {relative}" not in failures for relative in numeric_required_paths
    )


def test_every_padic_release_path_fails_closed_when_deleted(tmp_path: Path) -> None:
    for relative in padic_required_paths:
        _write(tmp_path / relative, "release-boundary fixture\n")

    failures: list[str] = []
    check_required_paths(tmp_path, failures, "0.5.0")
    padic_failures = [
        failure
        for failure in failures
        if any(relative in failure for relative in padic_required_paths)
    ]
    assert padic_failures == []

    for relative in padic_required_paths:
        path = tmp_path / relative
        path.unlink()
        failures = []
        check_required_paths(tmp_path, failures, "0.5.0")
        assert f"missing required path: {relative}" in failures
        _write(path, "release-boundary fixture\n")

    failures = []
    for relative in padic_required_paths:
        (tmp_path / relative).unlink()
    check_required_paths(tmp_path, failures, "0.4.0")
    assert all(
        f"missing required path: {relative}" not in failures for relative in padic_required_paths
    )


def test_release_gate_pins_both_supported_live_pari_anchors(tmp_path: Path) -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    _write(tmp_path / ".github/workflows/ci.yml", workflow)
    failures: list[str] = []
    check_live_pari_matrix(tmp_path, failures)
    assert failures == []

    damaged = workflow.replace(
        "02651d99c391007d384b3fadbc20abc6916b77036f9e496c99e9ce8688ca4b53",
        "0" * 64,
    )
    _write(tmp_path / ".github/workflows/ci.yml", damaged)
    failures = []
    check_live_pari_matrix(tmp_path, failures)
    assert any("2.17.4" in failure for failure in failures)


def test_release_gate_hashes_the_immutable_v010_inputs(tmp_path: Path) -> None:
    shutil.copytree(
        PROJECT_ROOT / "tests/fixtures/compat/v0.1.0",
        tmp_path / "tests/fixtures/compat/v0.1.0",
    )
    notes = tmp_path / "docs/release-notes-0.1.0.md"
    notes.parent.mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "docs/release-notes-0.1.0.md", notes)

    failures: list[str] = []
    check_v010_compatibility(tmp_path, failures)
    assert failures == []

    api_cli = tmp_path / "tests/fixtures/compat/v0.1.0/api-cli-contracts.json"
    api_cli.write_text(api_cli.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    failures = []
    check_v010_compatibility(tmp_path, failures)
    assert any("api-cli-contracts.json" in failure for failure in failures)
    shutil.copyfile(
        PROJECT_ROOT / "tests/fixtures/compat/v0.1.0/api-cli-contracts.json",
        api_cli,
    )

    fixture = tmp_path / "tests/fixtures/compat/v0.1.0/h1-c2-f2.json"
    fixture.write_text(fixture.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    failures = []
    check_v010_compatibility(tmp_path, failures)
    assert any("fixture SHA-256 mismatch" in failure for failure in failures)

    fixture.unlink()
    failures = []
    check_v010_compatibility(tmp_path, failures)
    assert any("missing immutable 0.1.0 fixture" in failure for failure in failures)


def test_release_gate_validates_every_indexed_compatibility_release(tmp_path: Path) -> None:
    shutil.copytree(
        PROJECT_ROOT / "tests/fixtures/compat",
        tmp_path / "tests/fixtures/compat",
    )
    index = json.loads(
        (PROJECT_ROOT / "tests/fixtures/compat/index.json").read_text(encoding="utf-8")
    )
    for version in (release["version"] for release in index["releases"]):
        notes = tmp_path / f"docs/release-notes-{version}.md"
        notes.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / f"docs/release-notes-{version}.md", notes)

    failures: list[str] = []
    check_compatibility_index(tmp_path, failures)
    assert failures == []

    manifest_path = tmp_path / "tests/fixtures/compat/v0.4.0/release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["github_release"]["id"] += 1
    _write_json(manifest_path, manifest)
    index_path = tmp_path / "tests/fixtures/compat/index.json"
    rewritten_index = json.loads(index_path.read_text(encoding="utf-8"))
    v040 = next(release for release in rewritten_index["releases"] if release["version"] == "0.4.0")
    manifest_pointer = next(
        fixture
        for fixture in v040["fixture_files"]
        if fixture["path"] == "tests/fixtures/compat/v0.4.0/release.json"
    )
    manifest_bytes = manifest_path.read_bytes()
    manifest_pointer.update(
        {
            "bytes": len(manifest_bytes),
            "sha256": f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}",
        }
    )
    _write_json(index_path, rewritten_index)
    failures = []
    check_compatibility_index(tmp_path, failures)
    assert any("github_release" in failure for failure in failures)

    shutil.copyfile(
        PROJECT_ROOT / "tests/fixtures/compat/v0.4.0/release.json",
        manifest_path,
    )
    shutil.copyfile(PROJECT_ROOT / "tests/fixtures/compat/index.json", index_path)

    semantic = tmp_path / "tests/fixtures/compat/v0.2.0/semantic-contracts.json"
    semantic.write_text(semantic.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    failures = []
    check_compatibility_index(tmp_path, failures)
    assert any("semantic-contracts.json" in failure for failure in failures)

    shutil.copyfile(
        PROJECT_ROOT / "tests/fixtures/compat/v0.2.0/semantic-contracts.json",
        semantic,
    )
    (tmp_path / "docs/release-notes-0.2.0.md").unlink()
    failures = []
    check_compatibility_index(tmp_path, failures)
    assert any("release-notes-0.2.0.md" in failure for failure in failures)


def test_v040_semantic_fixture_requires_numeric_candidate_and_exactification() -> None:
    semantic = json.loads(
        (PROJECT_ROOT / "tests/fixtures/compat/v0.4.0/semantic-contracts.json").read_text(
            encoding="utf-8"
        )
    )
    semantic["central_certificates"] = [
        record
        for record in semantic["central_certificates"]
        if record["label"] != "numeric.exactify-sqrt2"
    ]
    failures: list[str] = []
    check_semantic_snapshot(
        semantic,
        version="0.4.0",
        source_tag="v0.4.0",
        source_commit="771a1a150e02b0459ff82bf1b44e3c0fb7cdd933",
        failures=failures,
    )
    assert (
        "0.4.0 semantic compatibility fixture is missing required numeric record "
        "numeric.exactify-sqrt2" in failures
    )


def test_m23_release_gate_binds_exact_artifacts_and_theorem_counts(tmp_path: Path) -> None:
    base = tmp_path / "examples/hurwitz/m23_real_component"
    dataset_path = base / "expected/dataset.json"
    fixture_path = base / "fixture.py"
    generator_path = base / "generate.g"
    verifier_path = tmp_path / "src/arbogast/hurwitz/m23_exact.py"
    _write(fixture_path, "# independent exact verifier\n")
    _write(generator_path, "# exact discovery generator\n")
    _write(verifier_path, "# public exact M23 verifier\n")
    public_verifier = _artifact(verifier_path, "src/arbogast/hurwitz/m23_exact.py")
    del public_verifier["path"]
    public_verifier["module"] = "arbogast.hurwitz.m23_exact"
    dataset: dict[str, Any] = {
        "schema_version": "arbogast.example.m23-real-component.dataset/v2",
        "vertices": [None] * 1428,
        "class_conjugators": [None] * 1428,
        "transitions": [[None] * 6 for _ in range(1428)],
        "pure_braid_generators": [None] * 6,
        "real": {
            "mapping": [None] * 1428,
            "transitions": [None] * 1428,
            "inner_fixed_indices": [None] * 70,
            "c1_indices": [None] * 20,
        },
        "completeness": {
            "counts": {
                "all_inner_orbits": 7114,
                "generating_inner_orbits": 1428,
                "nongenerating_inner_orbits": 5686,
                "generating_c1": 20,
                "nongenerating_c1": 212,
            }
        },
        "counts": {
            "vertices": 1428,
            "pure_generators": 6,
            "directed_transitions": 8568,
            "inner_real_fixed": 70,
            "c1_fixed": 20,
        },
    }
    _write_json(dataset_path, dataset)
    manifest = {
        "schema_version": "arbogast.example.m23-real-component.manifest/v2",
        "artifacts": {
            "dataset": _artifact(dataset_path, "expected/dataset.json"),
            "fixture": _artifact(fixture_path, "fixture.py"),
            "generator": _artifact(generator_path, "generate.g"),
        },
        "verified_claims": {
            "generating_inner_nielsen_cardinality": 1428,
            "pure_braid_transitive": True,
            "c1_fixed": 20,
            "inner_real_fixed": 70,
            "all_product_one_inner_orbits": 7114,
            "nongenerating_inner_orbits": 5686,
            "nongenerating_c1": 212,
        },
        "verification": {
            "theorem_ready": True,
            "claim_kind": "COMPUTED",
            "epistemic_status": "CERTIFIED",
            "public_verifier": public_verifier,
        },
    }
    _write_json(base / "expected/manifest.json", manifest)

    failures: list[str] = []
    check_m23_fixture(tmp_path, failures)
    assert failures == []

    manifest_path = base / "expected/manifest.json"
    manifest_text = json.dumps(manifest, sort_keys=True)
    _write(
        manifest_path,
        '{"schema_version":"ignored-duplicate",' + manifest_text.removeprefix("{"),
    )
    failures = []
    check_m23_fixture(tmp_path, failures)
    assert any("duplicate JSON key 'schema_version'" in failure for failure in failures)

    _write_json(manifest_path, manifest)
    dataset_text = json.dumps(dataset, sort_keys=True)
    _write(dataset_path, dataset_text.removesuffix("}") + ', "invalid": NaN}')
    failures = []
    check_m23_fixture(tmp_path, failures)
    assert any("non-finite JSON number 'NaN'" in failure for failure in failures)
    _write_json(dataset_path, dataset)

    verification = cast(dict[str, object], manifest["verification"])
    verification["theorem_ready"] = False
    _write_json(manifest_path, manifest)
    failures = []
    check_m23_fixture(tmp_path, failures)
    assert any("theorem_ready must be True" in failure for failure in failures)
    verification["theorem_ready"] = True

    artifacts = cast(dict[str, object], manifest["artifacts"])
    fixture_record = artifacts.pop("fixture")
    _write_json(manifest_path, manifest)
    failures = []
    check_m23_fixture(tmp_path, failures)
    assert any(
        "omits required content-addressed artifact: fixture.py" in failure for failure in failures
    )
    artifacts["fixture"] = fixture_record
    _write_json(manifest_path, manifest)

    cast(dict[str, object], dataset["completeness"])["counts"] = {
        **cast(dict[str, object], cast(dict[str, object], dataset["completeness"])["counts"]),
        "nongenerating_c1": 211,
    }
    _write_json(dataset_path, dataset)
    failures = []
    check_m23_fixture(tmp_path, failures)
    assert any("artifact SHA-256 mismatch" in failure for failure in failures)
    assert any("nongenerating_c1 must be 212" in failure for failure in failures)
