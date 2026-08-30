"""Fail-closed release checks for Arbogast.

This check deliberately stays independent of the installed package so it can catch a
broken source tree or stale editable installation before a tag is created.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
FINAL_VERSION_RE: Final = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
REQUIRED_PATHS: Final = (
    ".github/workflows/ci.yml",
    "README.md",
    "CHANGELOG.md",
    "CITATION.cff",
    "docs/certified-arithmetic.md",
    "pyproject.toml",
    "uv.lock",
    "assets/arbogast-mark.png",
    "assets/arbogast-wordmark.png",
    "src/arbogast/__init__.py",
    "src/arbogast/py.typed",
    "src/arbogast/cli.py",
    "src/arbogast/core/__init__.py",
    "src/arbogast/linalg/__init__.py",
    "src/arbogast/rep/__init__.py",
    "src/arbogast/cohom/__init__.py",
    "src/arbogast/galois/__init__.py",
    "src/arbogast/arithmetic/__init__.py",
    "src/arbogast/hurwitz/__init__.py",
    "src/arbogast/claims/__init__.py",
    "src/arbogast/cert/__init__.py",
    "src/arbogast/specs/__init__.py",
    "src/arbogast/proof/__init__.py",
    "src/arbogast/sources/__init__.py",
    "src/arbogast/agent/__init__.py",
    "src/arbogast/campaign/__init__.py",
    "src/arbogast/export/__init__.py",
    "src/arbogast/fleet/__init__.py",
    "src/arbogast/sinks/__init__.py",
    "src/arbogast/backends/__init__.py",
    "src/arbogast/formats/__init__.py",
    "scripts/build_source_archive.py",
    "scripts/pari_anchor_payload.py",
    "scripts/qualify_artifacts.py",
    "scripts/snapshot_api_cli.py",
    "scripts/snapshot_semantic_contracts.py",
    "scripts/snapshot_v010_api_cli.py",
    "tests/fixtures/compat/index.json",
    "tests/integration/test_release_compatibility_index.py",
    "tests/integration/test_v010_compatibility.py",
    "examples/arithmetic/README.md",
    "examples/arithmetic/aim_a_cocycle/README.md",
    "examples/arithmetic/aim_a_cocycle/run.py",
    "examples/arithmetic/inflation_restriction/README.md",
    "examples/arithmetic/inflation_restriction/run.py",
    "examples/arithmetic/nonabelian_twists/README.md",
    "examples/arithmetic/nonabelian_twists/run.py",
    "examples/arithmetic/q_kummer_selmer/README.md",
    "examples/arithmetic/q_kummer_selmer/run.py",
    "examples/arithmetic/quadratic_field/README.md",
    "examples/arithmetic/quadratic_field/run.py",
    "examples/group_cohomology/cyclic_action_h1.py",
    "examples/campaigns/antieau_klueners_malle/README.md",
    "examples/campaigns/antieau_klueners_malle/LOCAL_GLOBAL.md",
    "examples/campaigns/antieau_klueners_malle/local_global.py",
    "examples/campaigns/antieau_klueners_malle/run.py",
    "examples/hurwitz/m23_real_component/README.md",
    "examples/hurwitz/m23_real_component/compute.py",
    "examples/hurwitz/m23_real_component/fixture.py",
    "examples/hurwitz/m23_real_component/generate.g",
    "examples/hurwitz/m23_real_component/verify.py",
    "examples/hurwitz/m23_real_component/expected/dataset.json",
    "examples/hurwitz/m23_real_component/expected/manifest.json",
    "examples/certificates/prove_without_search/discover.py",
    "examples/certificates/prove_without_search/verify.py",
)
DEFORMATION_INTRODUCED: Final = (0, 3, 0)
DEFORMATION_REQUIRED_PATHS: Final = (
    "docs/deformation.md",
    "src/arbogast/deform/__init__.py",
    "src/arbogast/deform/_schema.py",
    "src/arbogast/deform/certificate.py",
    "src/arbogast/deform/complex.py",
    "src/arbogast/deform/equivariant.py",
    "src/arbogast/deform/errors.py",
    "src/arbogast/deform/framing.py",
    "src/arbogast/deform/lifting.py",
    "src/arbogast/deform/plans.py",
    "src/arbogast/deform/problem.py",
    "src/arbogast/deform/rings.py",
    "src/arbogast/deform/semantic.py",
    "examples/deformation/exact_spaces/README.md",
    "examples/deformation/exact_spaces/run.py",
    "examples/deformation/finite_lifts/README.md",
    "examples/deformation/finite_lifts/run.py",
    "tests/integration/test_deform_examples_acceptance.py",
    "tests/integration/test_deform_fresh_process_acceptance.py",
    "tests/unit/test_deform_artin_rings_acceptance.py",
    "tests/unit/test_deform_certificate_acceptance.py",
    "tests/unit/test_deform_complex_acceptance.py",
    "tests/unit/test_deform_equivariant_acceptance.py",
    "tests/unit/test_deform_lifting_acceptance.py",
    "tests/unit/test_deform_schema_acceptance.py",
    "tests/unit/test_deform_semantic_acceptance.py",
    "tests/unit/test_deform_surface_acceptance.py",
)
NUMERIC_INTRODUCED: Final = (0, 4, 0)
NUMERIC_REQUIRED_PATHS: Final = (
    "docs/numeric.md",
    "docs/release-notes-0.4.0.md",
    "src/arbogast/numeric/__init__.py",
    "src/arbogast/numeric/_schema.py",
    "src/arbogast/numeric/braid.py",
    "src/arbogast/numeric/certificate.py",
    "src/arbogast/numeric/continuation.py",
    "src/arbogast/numeric/dyadic.py",
    "src/arbogast/numeric/errors.py",
    "src/arbogast/numeric/models.py",
    "src/arbogast/numeric/outcomes.py",
    "src/arbogast/numeric/projection.py",
    "src/arbogast/numeric/recognition.py",
    "src/arbogast/numeric/semantic.py",
    "examples/numeric/README.md",
    "examples/numeric/sqrt2_exactification/README.md",
    "examples/numeric/sqrt2_exactification/run.py",
    "examples/numeric/two_sheet_cover/README.md",
    "examples/numeric/two_sheet_cover/fixture.py",
    "examples/numeric/two_sheet_cover/run.py",
    "examples/numeric/weighted_braid_plan/README.md",
    "examples/numeric/weighted_braid_plan/run.py",
    "tests/integration/test_numeric_examples_acceptance.py",
    "tests/integration/test_numeric_fresh_process_acceptance.py",
    "tests/unit/test_numeric_b2_homotopy.py",
    "tests/unit/test_numeric_core.py",
    "tests/unit/test_numeric_cover.py",
    "tests/unit/test_numeric_schema_acceptance.py",
    "tests/unit/test_numeric_surface_acceptance.py",
    "tests/unit/test_numeric_weighted_braid.py",
)
PADIC_INTRODUCED: Final = (0, 5, 0)
PADIC_REQUIRED_PATHS: Final = (
    "docs/padic.md",
    "src/arbogast/padic/__init__.py",
    "src/arbogast/padic/_schema.py",
    "src/arbogast/padic/certificate.py",
    "src/arbogast/padic/covers.py",
    "src/arbogast/padic/descent.py",
    "src/arbogast/padic/errors.py",
    "src/arbogast/padic/fields.py",
    "src/arbogast/padic/frobenius.py",
    "src/arbogast/padic/frontier.py",
    "src/arbogast/padic/inertia.py",
    "src/arbogast/padic/lifts.py",
    "src/arbogast/padic/matrices.py",
    "src/arbogast/padic/modules.py",
    "src/arbogast/padic/plans.py",
    "src/arbogast/padic/reduction.py",
    "src/arbogast/padic/results.py",
    "src/arbogast/padic/semantic.py",
    "src/arbogast/padic/wewers.py",
    "examples/padic/README.md",
    "examples/padic/frobenius_slopes/README.md",
    "examples/padic/frobenius_slopes/run.py",
    "examples/padic/lifts_rigid_descent/README.md",
    "examples/padic/lifts_rigid_descent/run.py",
    "examples/padic/m23_local_frontier/README.md",
    "examples/padic/m23_local_frontier/run.py",
    "examples/padic/special_deformation_datum/README.md",
    "examples/padic/special_deformation_datum/run.py",
    "examples/padic/three_point_good_reduction/README.md",
    "examples/padic/three_point_good_reduction/run.py",
    "tests/integration/test_padic_examples_acceptance.py",
    "tests/integration/test_padic_fresh_process_acceptance.py",
    "tests/integration/test_padic_frobenius_inertia_fresh.py",
    "tests/unit/test_padic_frobenius_inertia.py",
    "tests/unit/test_padic_local_factorization_frontier.py",
    "tests/unit/test_padic_local_substrate.py",
    "tests/unit/test_padic_proof_substrate.py",
    "tests/unit/test_padic_schema_acceptance.py",
    "tests/unit/test_padic_surface_acceptance.py",
    "tests/unit/test_padic_three_point_reduction.py",
    "tests/unit/test_padic_wewers_lifts_descent.py",
)
TEXT_SUFFIXES: Final = {".cff", ".json", ".md", ".py", ".toml", ".yaml", ".yml"}
SKIP_PARTS: Final = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv"}
UNRESOLVED_MARKERS: Final = ("TODO", "FIXME", "will be filled in")
M23_DATASET_SCHEMA: Final = "arbogast.example.m23-real-component.dataset/v2"
M23_MANIFEST_SCHEMA: Final = "arbogast.example.m23-real-component.manifest/v2"
M23_ARTIFACT_PATHS: Final = (
    "expected/dataset.json",
    "fixture.py",
    "generate.g",
)
M23_VERIFIED_CLAIMS: Final[dict[str, object]] = {
    "generating_inner_nielsen_cardinality": 1428,
    "pure_braid_transitive": True,
    "c1_fixed": 20,
    "inner_real_fixed": 70,
    "all_product_one_inner_orbits": 7114,
    "nongenerating_inner_orbits": 5686,
    "nongenerating_c1": 212,
}
M23_COMPLETENESS_COUNTS: Final[dict[str, object]] = {
    "all_inner_orbits": 7114,
    "generating_inner_orbits": 1428,
    "nongenerating_inner_orbits": 5686,
    "generating_c1": 20,
    "nongenerating_c1": 212,
}
STATIC_PRERELEASE_PATTERNS: Final = (
    ("draft wording", re.compile(r"\bdraft\b", re.IGNORECASE)),
    ("pre-release wording", re.compile(r"\bpre[- ]?release\b", re.IGNORECASE)),
    (
        "development-release wording",
        re.compile(
            r"\b(?:development|dev)\s+(?:build|release|snapshot|version)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unpublished-release wording",
        re.compile(r"\bnot\s+(?:a\s+)?published\s+release\b", re.IGNORECASE),
    ),
)
SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
SOURCE_COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
COMPATIBILITY_INDEX: Final = "tests/fixtures/compat/index.json"
V010_COMPATIBILITY_FILES: Final = {
    "docs/release-notes-0.1.0.md": (
        "6bd4a9c04aa7cfadddd80b443fb67df49fb7e3756aa3e70c9e889091d7250ca6",
        8390,
    ),
    "tests/fixtures/compat/v0.1.0/h1-c2-f2.json": (
        "9768c82cb12a7d04f8850244c0b686ce33ba2bb633ffc777c4d72a9aba433743",
        7529,
    ),
    "tests/fixtures/compat/v0.1.0/public-contracts.json": (
        "8cbaf8089635ce156b27b70c1a33ec0e88f02f07ff4274ec15144aa5e158cb30",
        22326,
    ),
    "tests/fixtures/compat/v0.1.0/api-cli-contracts.json": (
        "36c759049c5c30c092fbc96ea4519326513a2f754d5b8158303a8cfe8bd62e4c",
        404644,
    ),
    "tests/fixtures/compat/v0.1.0/release.json": (
        "026e324569dc054bfbea8e7f349a3c021f0eeab6795e2cf6a7bec3c005861811",
        4962,
    ),
}
V010_PUBLISHED_ARTIFACTS: Final = (
    {
        "bytes": 368096,
        "filename": "arbogast-0.1.0-py3-none-any.whl",
        "sha256": "sha256:e5c37b20d94720cd8cd9a14db2689694f4a90e4d009582a7b7837dabf35f9521",
    },
    {
        "bytes": 1238239,
        "filename": "arbogast-0.1.0.tar.gz",
        "sha256": "sha256:6f20622025a0bdebce76ce41c765380e9f4ab2574488fdc443ba1dd098c9b02c",
    },
)
PUBLISHED_GITHUB_RELEASES: Final[dict[str, dict[str, object]]] = {
    "0.4.0": {
        "id": 379302816,
        "platform_immutable": False,
        "published_at": "2026-08-30T14:17:14Z",
        "url": "https://github.com/azide0x37/arbogast/releases/tag/v0.4.0",
    },
}
V010_CERTIFICATE_ID: Final = (
    "sha256:52b76eed5ad4ab3ee16fa7b34920c680cdb68e82470c72cefadf06a3d9439377"
)
PARI_CI_ANCHORS: Final = {
    "2.15.5": (
        "https://pari.math.u-bordeaux.fr/pub/pari/OLD/2.15/pari-2.15.5.tar.gz",
        "0efdda7515d9d954f63324c34b34c560e60f73a81c3924a71260a2cc91d5f981",
    ),
    "2.17.4": (
        "https://pari.math.u-bordeaux.fr/pub/pari/unix/pari-2.17.4.tar.gz",
        "02651d99c391007d384b3fadbc20abc6916b77036f9e496c99e9ce8688ca4b53",
    ),
}


def _project_version(root: Path) -> str | None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    project = value.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    return version if isinstance(version, str) else None


EXPECTED_VERSION: Final = _project_version(PROJECT_ROOT) or ""


def _deformation_release(version: str) -> bool:
    if FINAL_VERSION_RE.fullmatch(version) is None:
        return False
    major, minor, patch = (int(part) for part in version.split("."))
    return (major, minor, patch) >= DEFORMATION_INTRODUCED


def _numeric_release(version: str) -> bool:
    if FINAL_VERSION_RE.fullmatch(version) is None:
        return False
    major, minor, patch = (int(part) for part in version.split("."))
    return (major, minor, patch) >= NUMERIC_INTRODUCED


def _padic_release(version: str) -> bool:
    if FINAL_VERSION_RE.fullmatch(version) is None:
        return False
    major, minor, patch = (int(part) for part in version.split("."))
    return (major, minor, patch) >= PADIC_INTRODUCED


def required_paths(version: str, *, root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    """Return the release surface for ``version`` without forgetting old fixtures."""

    indexed: list[str] = []
    candidate_key = (
        tuple(int(part) for part in version.split("."))
        if FINAL_VERSION_RE.fullmatch(version) is not None
        else None
    )
    path = root / COMPATIBILITY_INDEX
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        value = None
    if isinstance(value, dict) and isinstance(value.get("releases"), list):
        for release in value["releases"]:
            if not isinstance(release, dict):
                continue
            release_version = release.get("version")
            if (
                candidate_key is not None
                and isinstance(release_version, str)
                and FINAL_VERSION_RE.fullmatch(release_version) is not None
                and tuple(int(part) for part in release_version.split(".")) >= candidate_key
            ):
                continue
            notes = release.get("release_notes")
            if isinstance(notes, dict) and isinstance(notes.get("path"), str):
                indexed.append(notes["path"])
            fixtures = release.get("fixture_files")
            if isinstance(fixtures, list):
                indexed.extend(
                    record["path"]
                    for record in fixtures
                    if isinstance(record, dict) and isinstance(record.get("path"), str)
                )
    deformation = DEFORMATION_REQUIRED_PATHS if _deformation_release(version) else ()
    numeric = NUMERIC_REQUIRED_PATHS if _numeric_release(version) else ()
    padic = PADIC_REQUIRED_PATHS if _padic_release(version) else ()
    paths = (
        *REQUIRED_PATHS,
        *indexed,
        *deformation,
        *numeric,
        *padic,
        f"docs/release-notes-{version}.md",
    )
    return tuple(dict.fromkeys(paths))


class _InvalidJson(ValueError):
    """Raised when a release artifact uses a non-deterministic JSON extension."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _InvalidJson(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise _InvalidJson(f"non-finite JSON number {value!r}")


def _source_version(init_path: Path) -> str | None:
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        has_version_target = any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
        if (
            has_version_target
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _text_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not any(part in SKIP_PARTS for part in path.parts)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path, label: str, failures: list[str]) -> dict[str, object] | None:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _InvalidJson) as error:
        failures.append(f"cannot parse {label}: {error}")
        return None
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        failures.append(f"{label} must be a string-keyed JSON object")
        return None
    return value


def _object_field(
    value: object,
    label: str,
    failures: list[str],
) -> dict[str, object] | None:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        failures.append(f"{label} must be a string-keyed JSON object")
        return None
    return value


def _expect_fields(
    value: dict[str, object],
    expected: dict[str, object],
    label: str,
    failures: list[str],
) -> None:
    for key, expected_value in expected.items():
        actual = value.get(key)
        if isinstance(expected_value, int) and not isinstance(expected_value, bool):
            matches = (
                isinstance(actual, int)
                and not isinstance(actual, bool)
                and actual == expected_value
            )
        else:
            matches = type(actual) is type(expected_value) and actual == expected_value
        if not matches:
            failures.append(f"{label}.{key} must be {expected_value!r}, found {actual!r}")


def _cff_scalar(text: str, key: str) -> str | None:
    matches = re.findall(rf"(?m)^{re.escape(key)}:\s*([^#\r\n]+?)\s*$", text)
    if len(matches) != 1:
        return None
    value = str(matches[0]).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def _release_date(value: str | None, label: str, failures: list[str]) -> date | None:
    if value is None:
        failures.append(f"{label} must declare one ISO release date")
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        failures.append(f"{label} release date must be YYYY-MM-DD, found {value!r}")
        return None
    if parsed.isoformat() != value:
        failures.append(f"{label} release date must be canonical YYYY-MM-DD, found {value!r}")
        return None
    return parsed


def _prerelease_patterns(version: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    escaped = re.escape(version)
    return (
        *STATIC_PRERELEASE_PATTERNS,
        (
            "planned-release wording",
            re.compile(
                rf"\bplanned(?:\s+for)?\s+`?v?{escaped}|\bplanned\s+release\b",
                re.IGNORECASE,
            ),
        ),
        (
            "development-release wording",
            re.compile(rf"\bv?{escaped}(?:[.-]?dev\d*)\b", re.IGNORECASE),
        ),
    )


def _reject_prerelease_wording(
    text: str,
    label: str,
    failures: list[str],
    *,
    expected_version: str,
) -> None:
    for description, pattern in _prerelease_patterns(expected_version):
        if pattern.search(text):
            failures.append(f"{label} contains stale {description}")


def _check_release_metadata(
    root: Path,
    failures: list[str],
    expected_version: str = EXPECTED_VERSION,
) -> None:
    citation_path = root / "CITATION.cff"
    changelog_path = root / "CHANGELOG.md"
    notes_path = root / f"docs/release-notes-{expected_version}.md"
    if not citation_path.is_file() or not changelog_path.is_file() or not notes_path.is_file():
        return

    citation = citation_path.read_text(encoding="utf-8")
    changelog = changelog_path.read_text(encoding="utf-8")
    notes = notes_path.read_text(encoding="utf-8")
    _reject_prerelease_wording(
        citation,
        "CITATION.cff",
        failures,
        expected_version=expected_version,
    )
    _reject_prerelease_wording(
        changelog,
        "CHANGELOG.md",
        failures,
        expected_version=expected_version,
    )
    _reject_prerelease_wording(
        notes,
        f"docs/release-notes-{expected_version}.md",
        failures,
        expected_version=expected_version,
    )

    citation_version = _cff_scalar(citation, "version")
    if citation_version != expected_version:
        failures.append(
            f"CITATION.cff version must be {expected_version}, found {citation_version!r}"
        )
    citation_date = _release_date(_cff_scalar(citation, "date-released"), "CITATION.cff", failures)

    release_headings = re.findall(
        rf"(?m)^## \[{re.escape(expected_version)}\] - (\d{{4}}-\d{{2}}-\d{{2}})$",
        changelog,
    )
    if len(release_headings) != 1:
        failures.append(
            "CHANGELOG.md must contain exactly one release heading for "
            f"{expected_version} with a date"
        )
    else:
        changelog_date = _release_date(release_headings[0], "CHANGELOG.md", failures)
        if citation_date is not None and changelog_date != citation_date:
            failures.append("CITATION.cff and CHANGELOG.md release dates must match")

    expected_notes_heading = f"# Arbogast {expected_version} release notes"
    if not notes.startswith(expected_notes_heading + "\n"):
        failures.append(
            f"release notes must begin with the final heading {expected_notes_heading!r}"
        )


def _check_m23_artifacts(
    base: Path,
    manifest: dict[str, object],
    failures: list[str],
) -> None:
    artifacts = _object_field(manifest.get("artifacts"), "M23 manifest.artifacts", failures)
    if artifacts is None:
        return
    recorded_paths: set[str] = set()
    base_resolved = base.resolve()
    for name, raw_record in artifacts.items():
        record = _object_field(raw_record, f"M23 manifest.artifacts.{name}", failures)
        if record is None:
            continue
        relative = record.get("path")
        digest = record.get("sha256")
        size = record.get("bytes")
        if not isinstance(relative, str) or not relative:
            failures.append(f"M23 artifact {name!r} must declare a relative path")
            continue
        relative_path = Path(relative)
        target = (base / relative_path).resolve()
        if relative_path.is_absolute() or not target.is_relative_to(base_resolved):
            failures.append(f"M23 artifact {name!r} path escapes the example directory")
            continue
        normalized = relative_path.as_posix()
        if normalized in recorded_paths:
            failures.append(f"M23 artifact path is recorded more than once: {normalized}")
            continue
        recorded_paths.add(normalized)
        if not target.is_file():
            failures.append(f"M23 artifact is missing: {normalized}")
            continue
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            failures.append(f"M23 artifact {normalized} must have a lowercase SHA-256 digest")
        elif _sha256(target) != digest:
            failures.append(f"M23 artifact SHA-256 mismatch: {normalized}")
        if isinstance(size, bool) or not isinstance(size, int) or size != target.stat().st_size:
            failures.append(f"M23 artifact byte count mismatch: {normalized}")
    for required in M23_ARTIFACT_PATHS:
        if required not in recorded_paths:
            failures.append(f"M23 manifest omits required content-addressed artifact: {required}")


def _check_m23_fixture(root: Path, failures: list[str]) -> None:
    base = root / "examples/hurwitz/m23_real_component"
    manifest_path = base / "expected/manifest.json"
    dataset_path = base / "expected/dataset.json"
    if not manifest_path.is_file() or not dataset_path.is_file():
        return
    manifest = _json_object(manifest_path, "M23 manifest", failures)
    dataset = _json_object(dataset_path, "M23 dataset", failures)
    if manifest is None or dataset is None:
        return
    if manifest.get("schema_version") != M23_MANIFEST_SCHEMA:
        failures.append(f"M23 manifest schema must be {M23_MANIFEST_SCHEMA}")
    if dataset.get("schema_version") != M23_DATASET_SCHEMA:
        failures.append(f"M23 dataset schema must be {M23_DATASET_SCHEMA}")
    _check_m23_artifacts(base, manifest, failures)

    claims = _object_field(manifest.get("verified_claims"), "M23 verified_claims", failures)
    if claims is not None:
        _expect_fields(claims, M23_VERIFIED_CLAIMS, "M23 verified_claims", failures)
    verification = _object_field(manifest.get("verification"), "M23 verification", failures)
    if verification is not None:
        _expect_fields(
            verification,
            {
                "theorem_ready": True,
                "claim_kind": "COMPUTED",
                "epistemic_status": "CERTIFIED",
            },
            "M23 verification",
            failures,
        )
        public_verifier = _object_field(
            verification.get("public_verifier"),
            "M23 verification.public_verifier",
            failures,
        )
        if public_verifier is not None:
            verifier_path = root / "src/arbogast/hurwitz/m23_exact.py"
            _expect_fields(
                public_verifier,
                {"module": "arbogast.hurwitz.m23_exact"},
                "M23 verification.public_verifier",
                failures,
            )
            digest = public_verifier.get("sha256")
            size = public_verifier.get("bytes")
            if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
                failures.append("M23 public verifier must declare a lowercase SHA-256 digest")
            elif verifier_path.is_file() and _sha256(verifier_path) != digest:
                failures.append("M23 public verifier SHA-256 mismatch")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or not verifier_path.is_file()
                or size != verifier_path.stat().st_size
            ):
                failures.append("M23 public verifier byte count mismatch")
    completeness = _object_field(dataset.get("completeness"), "M23 completeness", failures)
    if completeness is not None:
        completeness_counts = _object_field(
            completeness.get("counts"), "M23 completeness.counts", failures
        )
        if completeness_counts is not None:
            _expect_fields(
                completeness_counts,
                M23_COMPLETENESS_COUNTS,
                "M23 completeness.counts",
                failures,
            )
    counts = _object_field(dataset.get("counts"), "M23 counts", failures)
    if counts is not None:
        _expect_fields(
            counts,
            {
                "vertices": 1428,
                "pure_generators": 6,
                "directed_transitions": 8568,
                "inner_real_fixed": 70,
                "c1_fixed": 20,
            },
            "M23 counts",
            failures,
        )

    for field, length in (
        ("vertices", 1428),
        ("class_conjugators", 1428),
        ("transitions", 1428),
        ("pure_braid_generators", 6),
    ):
        value = dataset.get(field)
        if not isinstance(value, list) or len(value) != length:
            failures.append(f"M23 dataset.{field} must contain exactly {length} entries")
    transitions = dataset.get("transitions")
    if isinstance(transitions, list) and any(
        not isinstance(row, list) or len(row) != 6 for row in transitions
    ):
        failures.append("M23 dataset.transitions must have six exact edges per vertex")
    real = _object_field(dataset.get("real"), "M23 real", failures)
    if real is not None:
        for field, length in (
            ("mapping", 1428),
            ("transitions", 1428),
            ("inner_fixed_indices", 70),
            ("c1_indices", 20),
        ):
            value = real.get(field)
            if not isinstance(value, list) or len(value) != length:
                failures.append(f"M23 real.{field} must contain exactly {length} entries")


def _check_indexed_file(
    root: Path,
    record: object,
    label: str,
    failures: list[str],
) -> str | None:
    value = _object_field(record, label, failures)
    if value is None:
        return None
    relative = value.get("path")
    size = value.get("bytes")
    digest = value.get("sha256")
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
    ):
        failures.append(f"{label}.path must be a safe nonempty relative path")
        return None
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        failures.append(f"{label}.bytes must be a non-negative integer")
    if (
        not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or SHA256_RE.fullmatch(digest.removeprefix("sha256:")) is None
    ):
        failures.append(f"{label}.sha256 must be a canonical SHA-256 content address")
    path = root / relative
    if not path.is_file():
        failures.append(f"missing immutable compatibility input: {relative}")
        return relative
    if isinstance(size, int) and not isinstance(size, bool) and path.stat().st_size != size:
        failures.append(f"immutable compatibility byte count mismatch: {relative}")
    if isinstance(digest, str) and _sha256(path) != digest.removeprefix("sha256:"):
        failures.append(f"immutable compatibility SHA-256 mismatch: {relative}")
    return relative


def _check_published_artifacts(
    value: object,
    label: str,
    failures: list[str],
) -> list[object] | None:
    if not isinstance(value, list) or not value:
        failures.append(f"{label} must be a nonempty array")
        return None
    filenames: list[str] = []
    for index, record in enumerate(value):
        artifact = _object_field(record, f"{label}[{index}]", failures)
        if artifact is None:
            continue
        filename = artifact.get("filename")
        size = artifact.get("bytes")
        digest = artifact.get("sha256")
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            failures.append(f"{label}[{index}].filename must be one plain filename")
        else:
            filenames.append(filename)
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            failures.append(f"{label}[{index}].bytes must be a positive integer")
        if (
            not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or SHA256_RE.fullmatch(digest.removeprefix("sha256:")) is None
        ):
            failures.append(f"{label}[{index}].sha256 must be a canonical SHA-256 content address")
    if len(filenames) != len(set(filenames)):
        failures.append(f"{label} contains duplicate filenames")
    return value


def _canonical_document_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _check_semantic_snapshot(
    value: dict[str, object],
    *,
    version: str,
    source_tag: str,
    source_commit: str,
    failures: list[str],
) -> None:
    label = f"{version} semantic compatibility fixture"
    _expect_fields(
        value,
        {
            "schema_version": "arbogast.compatibility-semantic-contracts/v1",
            "version": version,
            "source_tag": source_tag,
            "source_commit": source_commit,
        },
        label,
        failures,
    )
    schemas = value.get("schema_catalog")
    if not isinstance(schemas, list) or not schemas:
        failures.append(f"{label}.schema_catalog must be a nonempty array")
    else:
        identifiers: list[str] = []
        for index, raw in enumerate(schemas):
            record = _object_field(raw, f"{label}.schema_catalog[{index}]", failures)
            if record is None:
                continue
            identifier = record.get("identifier")
            document = record.get("document")
            digest = record.get("document_sha256")
            if not isinstance(identifier, str) or not identifier:
                failures.append(f"{label}.schema_catalog[{index}] has no identifier")
                continue
            identifiers.append(identifier)
            if not isinstance(document, dict) or document.get("$id") != identifier:
                failures.append(
                    f"{label}.schema_catalog[{index}] document is not bound to its identifier"
                )
            elif digest != f"sha256:{_canonical_document_sha256(document)}":
                failures.append(f"{label}.schema_catalog[{index}] document hash does not replay")
        if identifiers != sorted(set(identifiers)):
            failures.append(f"{label}.schema_catalog identifiers must be unique and sorted")

    certificates = value.get("central_certificates")
    labels: list[str] = []
    records_by_label: dict[str, dict[str, object]] = {}
    if not isinstance(certificates, list) or not certificates:
        failures.append(f"{label}.central_certificates must be a nonempty array")
    else:
        for index, raw in enumerate(certificates):
            record = _object_field(raw, f"{label}.central_certificates[{index}]", failures)
            if record is None:
                continue
            certificate = _object_field(
                record.get("certificate"),
                f"{label}.central_certificates[{index}].certificate",
                failures,
            )
            record_label = record.get("label")
            certificate_id = record.get("certificate_id")
            if isinstance(record_label, str):
                labels.append(record_label)
                records_by_label[record_label] = record
            if (
                not isinstance(certificate_id, str)
                or not certificate_id.startswith("sha256:")
                or SHA256_RE.fullmatch(certificate_id.removeprefix("sha256:")) is None
            ):
                failures.append(
                    f"{label}.central_certificates[{index}] has an invalid certificate ID"
                )
            if certificate is not None:
                _expect_fields(
                    certificate,
                    {
                        "schema_version": "arbogast.cert.verification/v1",
                        "certificate_id": certificate_id,
                    },
                    f"{label}.central_certificates[{index}].certificate",
                    failures,
                )
    if not any(item.startswith("galois.") for item in labels):
        failures.append(f"{label} has no representative Galois central certificate")
    if not any(item.startswith("arithmetic.") for item in labels):
        failures.append(f"{label} has no representative arithmetic central certificate")
    if _deformation_release(version) and not any(item.startswith("deform.") for item in labels):
        failures.append(f"{label} has no representative deformation central certificate")
    if _numeric_release(version):
        required_numeric_records = {
            "numeric.recognize-sqrt2-candidate": (
                "numerical",
                "arbogast.numeric.recognition.AlgebraicCandidate",
                "algebraic-candidate",
                "arbogast.numeric.algebraic-candidate-receipt/v1",
            ),
            "numeric.exactify-sqrt2": (
                "exact",
                "arbogast.numeric.recognition.ExactificationResult",
                "exactification-result",
                "arbogast.numeric.exactification-result-receipt/v1",
            ),
        }
        for record_label, (
            claim_status,
            result_type,
            receipt_kind,
            receipt_schema,
        ) in required_numeric_records.items():
            record = records_by_label.get(record_label)
            if record is None:
                failures.append(f"{label} is missing required numeric record {record_label}")
                continue
            _expect_fields(
                record,
                {
                    "numeric_claim_status": claim_status,
                    "result_type": result_type,
                },
                f"{label}.{record_label}",
                failures,
            )
            receipt = _object_field(
                record.get("numeric_receipt"),
                f"{label}.{record_label}.numeric_receipt",
                failures,
            )
            receipt_id = record.get("numeric_receipt_id")
            if (
                not isinstance(receipt_id, str)
                or not receipt_id.startswith("sha256:")
                or SHA256_RE.fullmatch(receipt_id.removeprefix("sha256:")) is None
            ):
                failures.append(f"{label}.{record_label} has an invalid numeric receipt ID")
            if receipt is not None:
                _expect_fields(
                    receipt,
                    {
                        "certificate_id": receipt_id,
                        "kind": receipt_kind,
                        "schema_version": receipt_schema,
                    },
                    f"{label}.{record_label}.numeric_receipt",
                    failures,
                )
            certificate = _object_field(
                record.get("certificate"),
                f"{label}.{record_label}.certificate",
                failures,
            )
            if certificate is not None:
                _expect_fields(
                    certificate,
                    {"verifier": "numeric.exact-bridge.v1"},
                    f"{label}.{record_label}.certificate",
                    failures,
                )

    pari = _object_field(value.get("pari"), f"{label}.pari", failures)
    if pari is not None:
        supported = pari.get("supported_range")
        if not isinstance(supported, str) or not supported:
            failures.append(f"{label}.pari.supported_range must be nonempty")
        anchors = pari.get("ci_anchors")
        if not isinstance(anchors, list) or not anchors:
            failures.append(f"{label}.pari.ci_anchors must be nonempty")
        else:
            versions: list[str] = []
            for index, raw in enumerate(anchors):
                anchor = _object_field(raw, f"{label}.pari.ci_anchors[{index}]", failures)
                if anchor is None:
                    continue
                anchor_version = anchor.get("version")
                source_url = anchor.get("source_url")
                source_sha256 = anchor.get("source_sha256")
                if (
                    not isinstance(anchor_version, str)
                    or FINAL_VERSION_RE.fullmatch(anchor_version) is None
                ):
                    failures.append(f"{label}.pari.ci_anchors[{index}] has an invalid version")
                else:
                    versions.append(anchor_version)
                if not isinstance(source_url, str) or not source_url.startswith("https://"):
                    failures.append(f"{label}.pari.ci_anchors[{index}] has an invalid URL")
                if not isinstance(source_sha256, str) or SHA256_RE.fullmatch(source_sha256) is None:
                    failures.append(f"{label}.pari.ci_anchors[{index}] has an invalid SHA-256")
            if versions != sorted(set(versions)):
                failures.append(f"{label}.pari.ci_anchors versions must be unique and sorted")


def _check_compatibility_index(root: Path, failures: list[str]) -> None:
    index_path = root / COMPATIBILITY_INDEX
    if not index_path.is_file():
        failures.append(f"missing compatibility index: {COMPATIBILITY_INDEX}")
        return
    index = _json_object(index_path, "compatibility index", failures)
    if index is None:
        return
    _expect_fields(
        index,
        {
            "schema_version": "arbogast.compatibility-index/v1",
            "compatibility_policy": "immutable-published-inputs",
        },
        "compatibility index",
        failures,
    )
    releases = index.get("releases")
    if not isinstance(releases, list) or not releases:
        failures.append("compatibility index.releases must be a nonempty array")
        return

    versions: list[str] = []
    source_tags: list[str] = []
    source_commits: list[str] = []
    for index_number, raw_release in enumerate(releases):
        label = f"compatibility index.releases[{index_number}]"
        release = _object_field(raw_release, label, failures)
        if release is None:
            continue
        version = release.get("version")
        source_tag = release.get("source_tag")
        source_commit = release.get("source_commit")
        if not isinstance(version, str) or FINAL_VERSION_RE.fullmatch(version) is None:
            failures.append(f"{label}.version must have final X.Y.Z form")
            continue
        versions.append(version)
        if source_tag != f"v{version}":
            failures.append(f"{label}.source_tag must be v{version}")
        elif isinstance(source_tag, str):
            source_tags.append(source_tag)
        if not isinstance(source_commit, str) or SOURCE_COMMIT_RE.fullmatch(source_commit) is None:
            failures.append(f"{label}.source_commit must be a full lowercase Git SHA-1")
            continue
        source_commits.append(source_commit)

        fixture_records = release.get("fixture_files")
        if not isinstance(fixture_records, list) or not fixture_records:
            failures.append(f"{label}.fixture_files must be a nonempty array")
            continue
        indexed_files: dict[str, dict[str, object]] = {}
        fixture_paths: list[str] = []
        for fixture_index, raw_fixture in enumerate(fixture_records):
            fixture_label = f"{label}.fixture_files[{fixture_index}]"
            fixture = _object_field(raw_fixture, fixture_label, failures)
            relative = _check_indexed_file(root, raw_fixture, fixture_label, failures)
            if fixture is not None and relative is not None:
                fixture_paths.append(relative)
                indexed_files[relative] = fixture
                prefix = f"tests/fixtures/compat/v{version}/"
                if not relative.startswith(prefix):
                    failures.append(f"{fixture_label}.path must remain under {prefix}")
        if fixture_paths != sorted(set(fixture_paths)):
            failures.append(f"{label}.fixture_files paths must be unique and sorted")

        notes = _object_field(release.get("release_notes"), f"{label}.release_notes", failures)
        if notes is not None:
            notes_path = _check_indexed_file(
                root,
                notes,
                f"{label}.release_notes",
                failures,
            )
            if notes_path != f"docs/release-notes-{version}.md":
                failures.append(f"{label}.release_notes.path must name the historical notes")
        artifacts = _check_published_artifacts(
            release.get("published_artifacts"),
            f"{label}.published_artifacts",
            failures,
        )

        manifest_relative = f"tests/fixtures/compat/v{version}/release.json"
        if manifest_relative not in indexed_files:
            failures.append(f"{label} omits {manifest_relative}")
            continue
        manifest_path = root / manifest_relative
        manifest = _json_object(manifest_path, f"{version} compatibility manifest", failures)
        if manifest is None:
            continue
        _expect_fields(
            manifest,
            {
                "schema_version": "arbogast.compatibility-release/v1",
                "compatibility_policy": "immutable-published-input",
                "version": version,
                "source_tag": source_tag,
                "source_commit": source_commit,
                "published_artifacts": artifacts,
                "release_notes": notes,
            },
            f"{version} compatibility manifest",
            failures,
        )
        expected_github_release = PUBLISHED_GITHUB_RELEASES.get(version)
        if expected_github_release is not None:
            _expect_fields(
                manifest,
                {"github_release": expected_github_release},
                f"{version} compatibility manifest",
                failures,
            )
        for field, raw_pointer in manifest.items():
            if field != "representative_fixture" and not field.endswith("_fixture"):
                continue
            pointer = _object_field(
                raw_pointer,
                f"{version} compatibility manifest.{field}",
                failures,
            )
            if pointer is None:
                continue
            pointer_path = pointer.get("path")
            if not isinstance(pointer_path, str):
                continue
            expected = indexed_files.get(pointer_path)
            if expected is None:
                failures.append(
                    f"{version} compatibility manifest.{field} names an unindexed fixture"
                )
                continue
            for key in ("path", "bytes", "sha256"):
                if pointer.get(key) != expected.get(key):
                    failures.append(
                        f"{version} compatibility manifest.{field}.{key} does not match the index"
                    )

        api_relative = f"tests/fixtures/compat/v{version}/api-cli-contracts.json"
        if api_relative in indexed_files:
            api = _json_object(root / api_relative, f"{version} API/CLI fixture", failures)
            if api is not None:
                _expect_fields(
                    api,
                    {
                        "schema_version": "arbogast.compatibility-api-cli/v1",
                        "version": version,
                        "source_tag": source_tag,
                        "source_commit": source_commit,
                    },
                    f"{version} API/CLI fixture",
                    failures,
                )
        semantic_relative = f"tests/fixtures/compat/v{version}/semantic-contracts.json"
        if semantic_relative in indexed_files:
            semantic = _json_object(
                root / semantic_relative,
                f"{version} semantic compatibility fixture",
                failures,
            )
            if semantic is not None:
                _check_semantic_snapshot(
                    semantic,
                    version=version,
                    source_tag=str(source_tag),
                    source_commit=source_commit,
                    failures=failures,
                )

    version_keys = [tuple(int(part) for part in version.split(".")) for version in versions]
    if version_keys != sorted(set(version_keys)):
        failures.append("compatibility releases must be unique and sorted by semantic version")
    if len(source_tags) != len(set(source_tags)):
        failures.append("compatibility releases contain duplicate source tags")
    if len(source_commits) != len(set(source_commits)):
        failures.append("compatibility releases contain duplicate source commits")


def _check_v010_compatibility(root: Path, failures: list[str]) -> None:
    for relative, (digest, size) in V010_COMPATIBILITY_FILES.items():
        path = root / relative
        if not path.is_file():
            failures.append(f"missing immutable 0.1.0 fixture: {relative}")
            continue
        if path.stat().st_size != size:
            failures.append(f"immutable 0.1.0 fixture byte count mismatch: {relative}")
        if _sha256(path) != digest:
            failures.append(f"immutable 0.1.0 fixture SHA-256 mismatch: {relative}")

    manifest_path = root / "tests/fixtures/compat/v0.1.0/release.json"
    fixture_path = root / "tests/fixtures/compat/v0.1.0/h1-c2-f2.json"
    api_cli_path = root / "tests/fixtures/compat/v0.1.0/api-cli-contracts.json"
    if api_cli_path.is_file():
        api_cli = _json_object(api_cli_path, "0.1.0 API/CLI compatibility fixture", failures)
        if api_cli is not None:
            _expect_fields(
                api_cli,
                {
                    "schema_version": "arbogast.compatibility-api-cli/v1",
                    "version": "0.1.0",
                    "source_tag": "v0.1.0",
                    "source_commit": "dfd1cc0fd7830ae77de2a04617fa21cece69dde2",
                },
                "0.1.0 API/CLI compatibility fixture",
                failures,
            )
    if not manifest_path.is_file() or not fixture_path.is_file():
        return
    manifest = _json_object(manifest_path, "0.1.0 compatibility manifest", failures)
    fixture = _json_object(fixture_path, "0.1.0 H1 fixture", failures)
    if manifest is None or fixture is None:
        return
    _expect_fields(
        manifest,
        {
            "schema_version": "arbogast.compatibility-release/v1",
            "compatibility_policy": "immutable-published-input",
            "version": "0.1.0",
            "source_tag": "v0.1.0",
            "source_commit": "dfd1cc0fd7830ae77de2a04617fa21cece69dde2",
        },
        "0.1.0 compatibility manifest",
        failures,
    )
    if manifest.get("published_artifacts") != list(V010_PUBLISHED_ARTIFACTS):
        failures.append("0.1.0 published artifact hashes or sizes changed")
    stable = manifest.get("stable_schema_ids")
    if (
        not isinstance(stable, list)
        or any(not isinstance(identifier, str) for identifier in stable)
        or stable != sorted(set(stable))
    ):
        failures.append("0.1.0 stable schema IDs must be unique strings in canonical order")
    certificate = _object_field(fixture.get("certificate"), "0.1.0 certificate", failures)
    if certificate is not None:
        _expect_fields(
            certificate,
            {
                "schema_version": "arbogast.cert.verification/v1",
                "certificate_id": V010_CERTIFICATE_ID,
                "verifier": "cohom.normalized_bar.v1",
            },
            "0.1.0 certificate",
            failures,
        )


def _check_live_pari_matrix(root: Path, failures: list[str]) -> None:
    workflow_path = root / ".github/workflows/ci.yml"
    if not workflow_path.is_file():
        return
    workflow = workflow_path.read_text(encoding="utf-8")
    for version, (source_url, source_sha256) in PARI_CI_ANCHORS.items():
        for required in (version, source_url, source_sha256):
            if required not in workflow:
                failures.append(f"live-PARI CI anchor {version} omits {required!r}")
    for required in (
        "ARBOGAST_LIVE_PARI",
        "--require-gp",
        "pari-anchor-agreement",
        "scripts/build_source_archive.py",
        "scripts/pari_anchor_payload.py",
        "tests/integration/test_pari_live.py",
        "sha256sum --check --strict",
    ):
        if required not in workflow:
            failures.append(f"live-PARI CI matrix omits {required!r}")


def _check_required_paths(root: Path, failures: list[str], version: str) -> None:
    for relative in required_paths(version, root=root):
        required = root / relative
        if not required.exists():
            failures.append(f"missing required path: {relative}")
        elif (
            required.is_file()
            and relative != "src/arbogast/py.typed"
            and required.stat().st_size == 0
        ):
            failures.append(f"required file is empty: {relative}")


def check(root: Path, *, expected_version: str | None = None) -> dict[str, object]:
    failures: list[str] = []
    declared_version = _project_version(root)
    version = expected_version or declared_version or ""
    if not version or FINAL_VERSION_RE.fullmatch(version) is None:
        failures.append(f"release version must be final X.Y.Z, found {version!r}")
    if expected_version is not None and declared_version != expected_version:
        failures.append(f"pyproject version must be {expected_version}, found {declared_version!r}")

    _check_required_paths(root, failures, version)

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = pyproject.get("project", {})
        if project.get("name") != "arbogast":
            failures.append("pyproject project.name must be arbogast")
        if project.get("version") != version:
            failures.append(f"pyproject version must be {version}")
        scripts = project.get("scripts", {})
        if scripts.get("arbogast") != "arbogast.cli:main":
            failures.append("pyproject must publish the arbogast CLI")
        if scripts.get("arb") != "arbogast.cli:main":
            failures.append("pyproject must publish the arb CLI alias")

    init_path = root / "src/arbogast/__init__.py"
    if init_path.exists() and _source_version(init_path) != version:
        failures.append(f"source __version__ must be {version}")

    _check_release_metadata(root, failures, version)
    _check_m23_fixture(root, failures)
    _check_compatibility_index(root, failures)
    _check_v010_compatibility(root, failures)
    _check_live_pari_matrix(root, failures)

    checked_files = _text_files(root)
    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(root)
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=str(relative_path))
            except SyntaxError as error:
                failures.append(f"invalid Python syntax in {relative_path}: {error}")
        if relative_path != Path("scripts/check_release.py"):
            if "arboghast" in text.lower():
                failures.append(f"legacy spelling appears in {relative_path}")
            for marker in UNRESOLVED_MARKERS:
                if marker in text:
                    failures.append(f"unresolved marker {marker!r} appears in {relative_path}")

    cli_path = root / "src/arbogast/cli.py"
    if cli_path.exists():
        cli_tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
        has_main = any(
            isinstance(node, ast.FunctionDef) and node.name == "main" for node in cli_tree.body
        )
        if not has_main:
            failures.append("CLI module does not define main()")

    readme = root / "README.md"
    if readme.exists():
        readme_text = readme.read_text(encoding="utf-8")
        for phrase in (
            "Campaign",
            "ClaimGraph",
            "H^0",
            "H^1",
            "H^2",
            "Nielsen",
            "mathematical outcome",
            "operational state",
            "verify",
        ):
            if phrase not in readme_text:
                failures.append(f"README omits required concept: {phrase}")

    digest = hashlib.sha256()
    for path in checked_files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    return {
        "ok": not failures,
        "version": version,
        "checked_files": len(checked_files),
        "source_tree_sha256": digest.hexdigest(),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="source tree to qualify (default: repository containing this script)",
    )
    parser.add_argument(
        "--expected-version",
        help="require an exact final version instead of deriving it from pyproject.toml",
    )
    args = parser.parse_args(argv)
    report = check(args.root.resolve(), expected_version=args.expected_version)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
