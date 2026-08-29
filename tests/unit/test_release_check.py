from __future__ import annotations

import hashlib
import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKER = runpy.run_path(str(PROJECT_ROOT / "scripts/check_release.py"))
CheckSection = Callable[[Path, list[str]], None]
check_release_metadata = cast(CheckSection, CHECKER["_check_release_metadata"])
check_m23_fixture = cast(CheckSection, CHECKER["_check_m23_fixture"])
required_paths = cast(tuple[str, ...], CHECKER["REQUIRED_PATHS"])


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
    check_release_metadata(tmp_path, failures)
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
    check_release_metadata(tmp_path, failures)
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
    check_release_metadata(tmp_path, failures)
    assert failures == ["docs/release-notes-0.1.0.md contains stale development-release wording"]


def test_release_surface_requires_ci_campaign_and_exact_m23_inputs() -> None:
    assert ".github/workflows/ci.yml" in required_paths
    assert "examples/campaigns/antieau_klueners_malle/README.md" in required_paths
    assert "examples/campaigns/antieau_klueners_malle/run.py" in required_paths
    assert "examples/hurwitz/m23_real_component/fixture.py" in required_paths
    assert "examples/hurwitz/m23_real_component/generate.g" in required_paths
    assert "examples/hurwitz/m23_real_component/expected/dataset.json" in required_paths


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
