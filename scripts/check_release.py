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
    "docs/release-notes-0.1.0.md",
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
    "scripts/snapshot_v010_api_cli.py",
    "tests/fixtures/compat/v0.1.0/release.json",
    "tests/fixtures/compat/v0.1.0/h1-c2-f2.json",
    "tests/fixtures/compat/v0.1.0/public-contracts.json",
    "tests/fixtures/compat/v0.1.0/api-cli-contracts.json",
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
M23_VERIFIED_CLAIMS: Final = {
    "generating_inner_nielsen_cardinality": 1428,
    "pure_braid_transitive": True,
    "c1_fixed": 20,
    "inner_real_fixed": 70,
    "all_product_one_inner_orbits": 7114,
    "nongenerating_inner_orbits": 5686,
    "nongenerating_c1": 212,
}
M23_COMPLETENESS_COUNTS: Final = {
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


def required_paths(version: str) -> tuple[str, ...]:
    """Return the release surface for ``version`` without forgetting old fixtures."""

    return (*REQUIRED_PATHS, f"docs/release-notes-{version}.md")


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
    value = matches[0].strip()
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


def check(root: Path, *, expected_version: str | None = None) -> dict[str, object]:
    failures: list[str] = []
    declared_version = _project_version(root)
    version = expected_version or declared_version or ""
    if not version or FINAL_VERSION_RE.fullmatch(version) is None:
        failures.append(f"release version must be final X.Y.Z, found {version!r}")
    if expected_version is not None and declared_version != expected_version:
        failures.append(f"pyproject version must be {expected_version}, found {declared_version!r}")

    for relative in required_paths(version):
        required = root / relative
        if not required.exists():
            failures.append(f"missing required path: {relative}")
        elif (
            required.is_file()
            and relative != "src/arbogast/py.typed"
            and required.stat().st_size == 0
        ):
            failures.append(f"required file is empty: {relative}")

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
    _check_v010_compatibility(root, failures)
    _check_live_pari_matrix(root, failures)

    checked_files = _text_files(root)
    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root)
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=str(relative))
            except SyntaxError as error:
                failures.append(f"invalid Python syntax in {relative}: {error}")
        if relative != Path("scripts/check_release.py"):
            if "arboghast" in text.lower():
                failures.append(f"legacy spelling appears in {relative}")
            for marker in UNRESOLVED_MARKERS:
                if marker in text:
                    failures.append(f"unresolved marker {marker!r} appears in {relative}")

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
