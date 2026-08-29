"""Fail-closed release checks for Arbogast.

This check deliberately stays independent of the installed package so it can catch a
broken source tree or stale editable installation before a tag is created.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Final

EXPECTED_VERSION: Final = "0.1.0"
REQUIRED_PATHS: Final = (
    ".github/workflows/ci.yml",
    "README.md",
    "CHANGELOG.md",
    "CITATION.cff",
    "docs/release-notes-0.1.0.md",
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
    "examples/group_cohomology/cyclic_action_h1.py",
    "examples/campaigns/antieau_klueners_malle/README.md",
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
PRERELEASE_PATTERNS: Final = (
    ("draft wording", re.compile(r"\bdraft\b", re.IGNORECASE)),
    (
        "planned-release wording",
        re.compile(
            r"\bplanned(?:\s+for)?\s+`?v?0\.1\.0|\bplanned\s+release\b",
            re.IGNORECASE,
        ),
    ),
    ("pre-release wording", re.compile(r"\bpre[- ]?release\b", re.IGNORECASE)),
    (
        "development-release wording",
        re.compile(
            r"\b(?:development|dev)\s+(?:build|release|snapshot|version)\b"
            r"|\bv?0\.1\.0(?:[.-]?dev\d*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unpublished-release wording",
        re.compile(r"\bnot\s+(?:a\s+)?published\s+release\b", re.IGNORECASE),
    ),
)
SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


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


def _reject_prerelease_wording(text: str, label: str, failures: list[str]) -> None:
    for description, pattern in PRERELEASE_PATTERNS:
        if pattern.search(text):
            failures.append(f"{label} contains stale {description}")


def _check_release_metadata(root: Path, failures: list[str]) -> None:
    citation_path = root / "CITATION.cff"
    changelog_path = root / "CHANGELOG.md"
    notes_path = root / "docs/release-notes-0.1.0.md"
    if not citation_path.is_file() or not changelog_path.is_file() or not notes_path.is_file():
        return

    citation = citation_path.read_text(encoding="utf-8")
    changelog = changelog_path.read_text(encoding="utf-8")
    notes = notes_path.read_text(encoding="utf-8")
    _reject_prerelease_wording(citation, "CITATION.cff", failures)
    _reject_prerelease_wording(changelog, "CHANGELOG.md", failures)
    _reject_prerelease_wording(notes, "docs/release-notes-0.1.0.md", failures)

    citation_version = _cff_scalar(citation, "version")
    if citation_version != EXPECTED_VERSION:
        failures.append(
            f"CITATION.cff version must be {EXPECTED_VERSION}, found {citation_version!r}"
        )
    citation_date = _release_date(_cff_scalar(citation, "date-released"), "CITATION.cff", failures)

    release_headings = re.findall(
        rf"(?m)^## \[{re.escape(EXPECTED_VERSION)}\] - (\d{{4}}-\d{{2}}-\d{{2}})$",
        changelog,
    )
    if len(release_headings) != 1:
        failures.append(
            "CHANGELOG.md must contain exactly one release heading for "
            f"{EXPECTED_VERSION} with a date"
        )
    else:
        changelog_date = _release_date(release_headings[0], "CHANGELOG.md", failures)
        if citation_date is not None and changelog_date != citation_date:
            failures.append("CITATION.cff and CHANGELOG.md release dates must match")

    expected_notes_heading = f"# Arbogast {EXPECTED_VERSION} release notes"
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


def check(root: Path) -> dict[str, object]:
    failures: list[str] = []
    for relative in REQUIRED_PATHS:
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
        if project.get("version") != EXPECTED_VERSION:
            failures.append(f"pyproject version must be {EXPECTED_VERSION}")
        scripts = project.get("scripts", {})
        if scripts.get("arbogast") != "arbogast.cli:main":
            failures.append("pyproject must publish the arbogast CLI")
        if scripts.get("arb") != "arbogast.cli:main":
            failures.append("pyproject must publish the arb CLI alias")

    init_path = root / "src/arbogast/__init__.py"
    if init_path.exists() and _source_version(init_path) != EXPECTED_VERSION:
        failures.append(f"source __version__ must be {EXPECTED_VERSION}")

    _check_release_metadata(root, failures)
    _check_m23_fixture(root, failures)

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
        "version": EXPECTED_VERSION,
        "checked_files": len(checked_files),
        "source_tree_sha256": digest.hexdigest(),
        "failures": failures,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = check(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
