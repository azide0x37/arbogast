"""Qualify Arbogast wheel and source archives before publication.

The default check is read-only and standard-library-only: it rejects unsafe or
ambiguous archive members, checks package metadata, and emits content-addressed
facts for the exact files inspected.  ``--install`` additionally performs
fresh UV-managed installs of both artifacts and probes each install with the
ambient PATH and with PARI/GP deliberately absent.  ``--examples`` runs the
examples contained in the source archive, never the working-tree copies.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
COMMAND_TIMEOUT_SECONDS: Final = 300
ARCHIVE_SCHEMA: Final = "arbogast.release-qualification/v1"
COMPATIBILITY_INDEX: Final = "tests/fixtures/compat/index.json"
DEFORMATION_INTRODUCED: Final = (0, 3, 0)
WHEEL_REQUIRED: Final = (
    "arbogast/__init__.py",
    "arbogast/py.typed",
    "arbogast/cli.py",
    "arbogast/cohom/__init__.py",
    "arbogast/galois/__init__.py",
    "arbogast/arithmetic/__init__.py",
)
SDIST_REQUIRED: Final = (
    "CITATION.cff",
    "CHANGELOG.md",
    "README.md",
    "docs/certified-arithmetic.md",
    "pyproject.toml",
    "uv.lock",
    "scripts/check_release.py",
    "scripts/pari_anchor_payload.py",
    "scripts/qualify_artifacts.py",
    "scripts/snapshot_v010_api_cli.py",
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
    "examples/campaigns/antieau_klueners_malle/README.md",
    "examples/campaigns/antieau_klueners_malle/LOCAL_GLOBAL.md",
    "examples/campaigns/antieau_klueners_malle/local_global.py",
    "examples/campaigns/antieau_klueners_malle/run.py",
    "src/arbogast/__init__.py",
    "src/arbogast/py.typed",
    "src/arbogast/galois/__init__.py",
    "src/arbogast/arithmetic/__init__.py",
    "tests/fixtures/compat/v0.1.0/release.json",
    "tests/fixtures/compat/v0.1.0/h1-c2-f2.json",
    "tests/fixtures/compat/v0.1.0/public-contracts.json",
    "tests/fixtures/compat/v0.1.0/api-cli-contracts.json",
    "tests/integration/test_v010_compatibility.py",
)
SOURCE_ARCHIVE_REQUIRED: Final = (
    ".github/workflows/ci.yml",
    *SDIST_REQUIRED,
    "scripts/build_source_archive.py",
    "tests/integration/test_pari_live.py",
    "tests/unit/test_artifact_qualification.py",
)
DEFORMATION_WHEEL_REQUIRED: Final = (
    "arbogast/deform/__init__.py",
    "arbogast/deform/_schema.py",
    "arbogast/deform/certificate.py",
    "arbogast/deform/complex.py",
    "arbogast/deform/equivariant.py",
    "arbogast/deform/errors.py",
    "arbogast/deform/framing.py",
    "arbogast/deform/lifting.py",
    "arbogast/deform/plans.py",
    "arbogast/deform/problem.py",
    "arbogast/deform/rings.py",
    "arbogast/deform/semantic.py",
)
DEFORMATION_SDIST_REQUIRED: Final = (
    "docs/deformation.md",
    "examples/deformation/exact_spaces/README.md",
    "examples/deformation/exact_spaces/run.py",
    "examples/deformation/finite_lifts/README.md",
    "examples/deformation/finite_lifts/run.py",
    *(f"src/{relative}" for relative in DEFORMATION_WHEEL_REQUIRED),
)
POST_V020_COMPATIBILITY_REQUIRED: Final = (
    COMPATIBILITY_INDEX,
    "tests/integration/test_release_compatibility_index.py",
)


class QualificationError(ValueError):
    """Raised when an archive cannot cross the release boundary."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_digest(records: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, payload in sorted(records):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_member_name(name: str, *, label: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise QualificationError(f"{label} contains an invalid member name: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"{label} member escapes the archive root: {name!r}")
    if not path.parts or any(part in {"", "."} for part in path.parts):
        raise QualificationError(f"{label} contains a non-canonical member name: {name!r}")
    return path


def _version_key(version: str, *, label: str = "version") -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or any(
        not part or not part.isascii() or not part.isdecimal() for part in parts
    ):
        raise QualificationError(f"{label} must be a final X.Y.Z version, found {version!r}")
    major, minor, patch = (int(part) for part in parts)
    return major, minor, patch


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _prior_compatibility_paths(
    payloads: Mapping[str, bytes],
    version: str,
    *,
    label: str,
) -> tuple[str, ...]:
    payload = payloads.get(COMPATIBILITY_INDEX)
    if payload is None:
        return ()
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, QualificationError) as error:
        raise QualificationError(f"cannot read {label} {COMPATIBILITY_INDEX}: {error}") from error
    if not isinstance(value, dict):
        raise QualificationError(f"{label} {COMPATIBILITY_INDEX} must contain a JSON object")
    if value.get("schema_version") != "arbogast.compatibility-index/v1":
        raise QualificationError(f"{label} {COMPATIBILITY_INDEX} has the wrong schema")
    releases = value.get("releases")
    if not isinstance(releases, list) or not releases:
        raise QualificationError(f"{label} {COMPATIBILITY_INDEX}.releases must be nonempty")

    candidate = _version_key(version, label="candidate version")
    required: list[str] = []
    previous: tuple[int, int, int] | None = None
    seen_versions: set[str] = set()
    for index, release in enumerate(releases):
        release_label = f"{label} {COMPATIBILITY_INDEX}.releases[{index}]"
        if not isinstance(release, dict):
            raise QualificationError(f"{release_label} must be a JSON object")
        release_version = release.get("version")
        if not isinstance(release_version, str):
            raise QualificationError(f"{release_label}.version must be a string")
        release_key = _version_key(release_version, label=f"{release_label}.version")
        if release_version in seen_versions or (previous is not None and release_key <= previous):
            raise QualificationError(
                f"{label} compatibility releases must be unique and sorted by version"
            )
        seen_versions.add(release_version)
        previous = release_key

        release_notes = release.get("release_notes")
        if not isinstance(release_notes, dict) or not isinstance(release_notes.get("path"), str):
            raise QualificationError(f"{release_label}.release_notes.path must be a string")
        notes_path = _safe_member_name(
            release_notes["path"],
            label=f"{release_label}.release_notes.path",
        ).as_posix()
        expected_notes = f"docs/release-notes-{release_version}.md"
        if notes_path != expected_notes:
            raise QualificationError(
                f"{release_label}.release_notes.path must be {expected_notes!r}"
            )

        fixture_records = release.get("fixture_files")
        if not isinstance(fixture_records, list) or not fixture_records:
            raise QualificationError(f"{release_label}.fixture_files must be nonempty")
        fixture_paths: list[str] = []
        expected_prefix = f"tests/fixtures/compat/v{release_version}/"
        for fixture_index, record in enumerate(fixture_records):
            fixture_label = f"{release_label}.fixture_files[{fixture_index}]"
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise QualificationError(f"{fixture_label}.path must be a string")
            fixture_path = _safe_member_name(
                record["path"],
                label=f"{fixture_label}.path",
            ).as_posix()
            if not fixture_path.startswith(expected_prefix):
                raise QualificationError(f"{fixture_label}.path must be below {expected_prefix!r}")
            fixture_paths.append(fixture_path)
        manifest = f"{expected_prefix}release.json"
        if manifest not in fixture_paths:
            raise QualificationError(f"{release_label}.fixture_files omits {manifest!r}")

        if release_key < candidate:
            required.append(notes_path)
            required.extend(fixture_paths)
    return tuple(dict.fromkeys(required))


def required_wheel_paths(version: str) -> tuple[str, ...]:
    """Return the wheel surface appropriate for one final release version."""

    version_key = _version_key(version)
    additive = DEFORMATION_WHEEL_REQUIRED if version_key >= DEFORMATION_INTRODUCED else ()
    return tuple(dict.fromkeys((*WHEEL_REQUIRED, *additive)))


def required_sdist_paths(
    payloads: Mapping[str, bytes],
    version: str,
    *,
    label: str = "sdist",
) -> tuple[str, ...]:
    """Return the sdist surface, including every indexed prior release contract."""

    version_key = _version_key(version)
    additive: tuple[str, ...] = ()
    compatibility: tuple[str, ...] = ()
    if version_key >= DEFORMATION_INTRODUCED:
        additive = (*POST_V020_COMPATIBILITY_REQUIRED, *DEFORMATION_SDIST_REQUIRED)
        compatibility = _prior_compatibility_paths(payloads, version, label=label)
    return tuple(
        dict.fromkeys(
            (
                *SDIST_REQUIRED,
                *additive,
                *compatibility,
                f"docs/release-notes-{version}.md",
            )
        )
    )


def required_source_archive_paths(
    payloads: Mapping[str, bytes],
    version: str,
) -> tuple[str, ...]:
    """Return the complete Git archive surface for one release version."""

    sdist_paths = required_sdist_paths(payloads, version, label="source archive")
    return tuple(dict.fromkeys((*SOURCE_ARCHIVE_REQUIRED, *sdist_paths)))


def _metadata_fields(payload: bytes, *, label: str) -> Mapping[str, str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise QualificationError(f"{label} is not UTF-8: {error}") from error
    message = Parser().parsestr(text)
    return {"name": message.get("Name", ""), "version": message.get("Version", "")}


def _pyproject_fields(payload: bytes, *, label: str) -> Mapping[str, str]:
    try:
        value = tomllib.loads(payload.decode("utf-8"))
        project = value["project"]
        name = project["name"]
        version = project["version"]
    except (KeyError, TypeError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise QualificationError(f"cannot read {label}: {error}") from error
    if not isinstance(name, str) or not isinstance(version, str):
        raise QualificationError(f"{label} name and version must be strings")
    return {"name": name, "version": version}


def _source_version(payload: bytes, *, label: str) -> str:
    try:
        tree = ast.parse(payload.decode("utf-8"), filename=label)
    except (SyntaxError, UnicodeDecodeError) as error:
        raise QualificationError(f"cannot read {label}: {error}") from error
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise QualificationError(f"{label} does not assign a literal __version__")


def _check_entry_points(payloads: Mapping[str, bytes]) -> None:
    paths = sorted(name for name in payloads if name.endswith(".dist-info/entry_points.txt"))
    if len(paths) != 1:
        raise QualificationError("wheel must contain exactly one entry_points.txt record")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(payloads[paths[0]].decode("utf-8"))
    except (configparser.Error, UnicodeDecodeError) as error:
        raise QualificationError(f"wheel entry points are invalid: {error}") from error
    scripts = dict(parser.items("console_scripts")) if parser.has_section("console_scripts") else {}
    expected = {"arb": "arbogast.cli:main", "arbogast": "arbogast.cli:main"}
    if scripts != expected:
        raise QualificationError(f"wheel console entry points mismatch: {scripts!r}")


def _artifact_record(
    path: Path,
    *,
    kind: str,
    member_count: int,
    payload_sha256: str,
) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "filename": path.name,
        "kind": kind,
        "member_count": member_count,
        "payload_sha256": f"sha256:{payload_sha256}",
        "sha256": f"sha256:{_sha256(path)}",
    }


def inspect_wheel(path: Path, version: str) -> dict[str, object]:
    """Inspect one exact pure-Python wheel without importing it."""

    required = required_wheel_paths(version)
    expected_name = f"arbogast-{version}-py3-none-any.whl"
    if path.name != expected_name:
        raise QualificationError(f"wheel must be named {expected_name!r}, found {path.name!r}")
    if not path.is_file():
        raise QualificationError(f"wheel is missing: {path}")

    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise QualificationError("wheel contains duplicate member names")
        records: list[tuple[str, bytes]] = []
        payloads: dict[str, bytes] = {}
        for info in infos:
            member = _safe_member_name(info.filename.rstrip("/"), label="wheel")
            file_type = stat.S_IFMT(info.external_attr >> 16)
            if file_type == stat.S_IFLNK:
                raise QualificationError(f"wheel contains a symbolic link: {info.filename}")
            if info.is_dir():
                continue
            normalized = member.as_posix()
            payload = archive.read(info)
            payloads[normalized] = payload
            records.append((normalized, payload))

    missing = sorted(set(required) - payloads.keys())
    if missing:
        raise QualificationError(f"wheel omits required files: {', '.join(missing)}")
    metadata_paths = sorted(name for name in payloads if name.endswith(".dist-info/METADATA"))
    wheel_paths = sorted(name for name in payloads if name.endswith(".dist-info/WHEEL"))
    if len(metadata_paths) != 1 or len(wheel_paths) != 1:
        raise QualificationError("wheel must contain exactly one METADATA and one WHEEL record")
    fields = _metadata_fields(payloads[metadata_paths[0]], label="wheel METADATA")
    if fields != {"name": "arbogast", "version": version}:
        raise QualificationError(f"wheel metadata mismatch: {dict(fields)!r}")
    if (
        _source_version(payloads["arbogast/__init__.py"], label="wheel arbogast/__init__.py")
        != version
    ):
        raise QualificationError("wheel source __version__ does not match its filename")
    _check_entry_points(payloads)
    wheel_text = payloads[wheel_paths[0]].decode("utf-8")
    if "Root-Is-Purelib: true" not in wheel_text or "Tag: py3-none-any" not in wheel_text:
        raise QualificationError("wheel must declare a py3-none-any purelib payload")
    return _artifact_record(
        path,
        kind="wheel",
        member_count=len(payloads),
        payload_sha256=_payload_digest(records),
    )


def _sdist_payloads(path: Path, version: str) -> tuple[dict[str, bytes], int]:
    _version_key(version)
    expected_name = f"arbogast-{version}.tar.gz"
    if path.name != expected_name:
        raise QualificationError(f"sdist must be named {expected_name!r}, found {path.name!r}")
    if not path.is_file():
        raise QualificationError(f"sdist is missing: {path}")
    prefix = f"arbogast-{version}"
    payloads: dict[str, bytes] = {}
    member_count = 0
    with tarfile.open(path, mode="r:gz") as archive:
        names: set[str] = set()
        for member in archive.getmembers():
            normalized = _safe_member_name(member.name.rstrip("/"), label="sdist").as_posix()
            if normalized in names:
                raise QualificationError(f"sdist contains duplicate member: {normalized}")
            names.add(normalized)
            member_count += 1
            parts = PurePosixPath(normalized).parts
            if not parts or parts[0] != prefix:
                raise QualificationError(f"sdist member is outside {prefix!r}: {normalized}")
            if member.isdir():
                continue
            if not member.isfile():
                raise QualificationError(f"sdist contains a non-regular member: {normalized}")
            stream = archive.extractfile(member)
            if stream is None:
                raise QualificationError(f"cannot read sdist member: {normalized}")
            payloads[PurePosixPath(*parts[1:]).as_posix()] = stream.read()
    return payloads, member_count


def inspect_sdist(path: Path, version: str) -> dict[str, object]:
    """Inspect one source distribution and bind its complete regular-file payload."""

    payloads, member_count = _sdist_payloads(path, version)
    missing = sorted(set(required_sdist_paths(payloads, version)) - payloads.keys())
    if missing:
        raise QualificationError(f"sdist omits required files: {', '.join(sorted(missing))}")
    metadata_paths = sorted(name for name in payloads if name == "PKG-INFO")
    if metadata_paths != ["PKG-INFO"]:
        raise QualificationError("sdist must contain its root PKG-INFO")
    fields = _metadata_fields(payloads["PKG-INFO"], label="sdist PKG-INFO")
    if fields != {"name": "arbogast", "version": version}:
        raise QualificationError(f"sdist metadata mismatch: {dict(fields)!r}")
    if _pyproject_fields(payloads["pyproject.toml"], label="sdist pyproject.toml") != {
        "name": "arbogast",
        "version": version,
    }:
        raise QualificationError("sdist pyproject metadata does not match its filename")
    if (
        _source_version(payloads["src/arbogast/__init__.py"], label="sdist source __init__.py")
        != version
    ):
        raise QualificationError("sdist source __version__ does not match its filename")
    return _artifact_record(
        path,
        kind="sdist",
        member_count=member_count,
        payload_sha256=_payload_digest(payloads.items()),
    )


def inspect_source_archive(path: Path, version: str) -> dict[str, object]:
    """Inspect the exact Git source archive offered with a release.

    Unlike the PEP 517 sdist, this archive is a snapshot of the complete
    versioned repository.  It deliberately has a distinct filename and proof
    record so neither artifact can be mistaken for the other.
    """

    _version_key(version)
    expected_name = f"arbogast-{version}-source.tar.gz"
    if path.name != expected_name:
        raise QualificationError(
            f"source archive must be named {expected_name!r}, found {path.name!r}"
        )
    if not path.is_file():
        raise QualificationError(f"source archive is missing: {path}")
    prefix = f"arbogast-{version}"
    payloads: dict[str, bytes] = {}
    member_count = 0
    with tarfile.open(path, mode="r:gz") as archive:
        source_commit = archive.pax_headers.get("comment", "")
        names: set[str] = set()
        for member in archive.getmembers():
            normalized = _safe_member_name(
                member.name.rstrip("/"),
                label="source archive",
            ).as_posix()
            if normalized in names:
                raise QualificationError(f"source archive contains duplicate member: {normalized}")
            names.add(normalized)
            member_count += 1
            parts = PurePosixPath(normalized).parts
            if not parts or parts[0] != prefix:
                raise QualificationError(
                    f"source archive member is outside {prefix!r}: {normalized}"
                )
            if member.isdir():
                continue
            if not member.isfile():
                raise QualificationError(
                    f"source archive contains a non-regular member: {normalized}"
                )
            stream = archive.extractfile(member)
            if stream is None:
                raise QualificationError(f"cannot read source archive member: {normalized}")
            relative = PurePosixPath(*parts[1:]).as_posix()
            payloads[relative] = stream.read()
    missing = sorted(set(required_source_archive_paths(payloads, version)) - payloads.keys())
    if missing:
        raise QualificationError(
            f"source archive omits required files: {', '.join(sorted(missing))}"
        )
    if "PKG-INFO" in payloads:
        raise QualificationError(
            "source archive must be a Git snapshot, not a renamed source distribution"
        )
    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise QualificationError("source archive omits its canonical Git commit binding")
    if _pyproject_fields(payloads["pyproject.toml"], label="source archive pyproject.toml") != {
        "name": "arbogast",
        "version": version,
    }:
        raise QualificationError("source archive pyproject metadata does not match its filename")
    if (
        _source_version(
            payloads["src/arbogast/__init__.py"],
            label="source archive src/arbogast/__init__.py",
        )
        != version
    ):
        raise QualificationError("source archive __version__ does not match its filename")
    record = _artifact_record(
        path,
        kind="source-archive",
        member_count=member_count,
        payload_sha256=_payload_digest(payloads.items()),
    )
    record["source_commit"] = source_commit
    return record


def _cross_artifact_consistency(
    wheel: Path,
    sdist: Path,
    source_archive: Path,
    version: str,
) -> None:
    """Require all shared source bytes to agree across the exact candidate trio."""

    with zipfile.ZipFile(wheel) as archive:
        wheel_payloads = {
            info.filename: archive.read(info) for info in archive.infolist() if not info.is_dir()
        }
    sdist_payloads, _ = _sdist_payloads(sdist, version)
    prefix = f"arbogast-{version}"
    source_payloads: dict[str, bytes] = {}
    with tarfile.open(source_archive, mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise QualificationError(f"cannot compare source member: {member.name}")
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != prefix:
                raise QualificationError(f"cannot compare foreign source member: {member.name}")
            source_payloads[PurePosixPath(*parts[1:]).as_posix()] = stream.read()

    for relative, payload in sdist_payloads.items():
        if relative == "PKG-INFO":
            continue
        if source_payloads.get(relative) != payload:
            raise QualificationError(f"sdist/source archive shared payload mismatch: {relative}")
    for relative, payload in wheel_payloads.items():
        if not relative.startswith("arbogast/"):
            continue
        source_relative = f"src/{relative}"
        if sdist_payloads.get(source_relative) != payload:
            raise QualificationError(f"wheel/sdist shared payload mismatch: {relative}")


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise QualificationError(
            f"command failed with exit {completed.returncode}: {' '.join(command)}\n{detail}"
        )
    return completed


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts/python.exe"
    return venv / "bin/python"


def _venv_script(python: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return python.parent / f"{name}{suffix}"


def _smoke_install(
    python: Path,
    *,
    version: str,
    cwd: Path,
    without_gp: bool,
    require_gp: bool = False,
) -> None:
    environment = dict(os.environ)
    if without_gp:
        environment["PATH"] = ""
    probe = (
        "import arbogast; "
        f"assert arbogast.__version__ == {version!r}; "
        "from arbogast.formats import schema_ids; "
        "assert 'arbogast.cli.version.v1' in schema_ids()"
    )
    _run((str(python), "-I", "-c", probe), cwd=cwd, env=environment)
    version_result = _run(
        (str(python), "-I", "-m", "arbogast.cli", "version", "--json"),
        cwd=cwd,
        env=environment,
    )
    decoded = json.loads(version_result.stdout)
    if decoded.get("version") != version:
        raise QualificationError(f"installed CLI version mismatch: {decoded!r}")
    for command_name in ("arbogast", "arb"):
        command = _venv_script(python, command_name)
        if not command.is_file():
            raise QualificationError(f"installed console entry point is missing: {command_name}")
        command_result = _run(
            (str(command), "version", "--json"),
            cwd=cwd,
            env=environment,
        )
        command_payload = json.loads(command_result.stdout)
        if command_payload.get("version") != version:
            raise QualificationError(
                f"installed {command_name} version mismatch: {command_payload!r}"
            )
    backend_result = _run(
        (str(python), "-I", "-m", "arbogast.cli", "backends", "--name", "pari", "--json"),
        cwd=cwd,
        env=environment,
    )
    backend = json.loads(backend_result.stdout).get("backend")
    if not isinstance(backend, dict):
        raise QualificationError("PARI backend probe did not emit one backend object")
    status = backend.get("status", backend)
    if not isinstance(status, dict):
        raise QualificationError("PARI backend probe omitted its status object")
    if without_gp and status.get("available") is not False:
        raise QualificationError("PARI backend must report unavailable when PATH is empty")
    if require_gp and status.get("available") is not True:
        raise QualificationError("PARI backend must pass its algebraic probe when GP is required")


def _smoke_v010_replay(python: Path, fixture: Path, *, cwd: Path) -> None:
    environment = dict(os.environ)
    environment["PATH"] = ""
    replay = """
import json
import sys
from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.claims import ClaimGraph

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
certificate = VerificationCertificate.from_dict(payload["certificate"])
expected_id = (
    "sha256:52b76eed5ad4ab3ee16fa7b34920c680cdb68e82470c72cefadf06a3d9439377"
)
assert certificate.certificate_id == expected_id
assert verify_certificate(certificate).valid
assert ClaimGraph.from_dict(payload["claim_graph"]).verify().verified
"""
    _run((str(python), "-I", "-c", replay, str(fixture)), cwd=cwd, env=environment)


def _extract_sdist(path: Path, version: str, destination: Path) -> Path:
    payloads, _ = _sdist_payloads(path, version)
    root = destination / f"arbogast-{version}"
    for relative, payload in payloads.items():
        target = root.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


def _packaged_example_commands(
    python: Path,
    scratch: Path,
    *,
    version: str,
    require_gp: bool,
) -> tuple[tuple[str, ...], ...]:
    quadratic = [str(python), "examples/arithmetic/quadratic_field/run.py"]
    if require_gp:
        quadratic.append("--with-pari")
    commands: list[tuple[str, ...]] = [
        (str(python), "examples/arithmetic/aim_a_cocycle/run.py"),
        (str(python), "examples/arithmetic/inflation_restriction/run.py"),
        (str(python), "examples/arithmetic/nonabelian_twists/run.py"),
        (str(python), "examples/arithmetic/q_kummer_selmer/run.py"),
        tuple(quadratic),
        (str(python), "examples/group_cohomology/cyclic_action_h1.py"),
        (
            str(python),
            "examples/campaigns/antieau_klueners_malle/run.py",
            "--output",
            str(scratch / "campaign"),
        ),
        (
            str(python),
            "examples/campaigns/antieau_klueners_malle/local_global.py",
            "--output",
            str(scratch / "local-global-campaign"),
        ),
        (
            str(python),
            "examples/certificates/prove_without_search/discover.py",
            "--output",
            str(scratch / "certificate.json"),
        ),
        (
            str(python),
            "examples/certificates/prove_without_search/verify.py",
            str(scratch / "certificate.json"),
        ),
        (
            str(python),
            "examples/hurwitz/m23_real_component/compute.py",
            "--output",
            str(scratch / "m23-claims.json"),
        ),
        (
            str(python),
            "examples/hurwitz/m23_real_component/verify.py",
            str(scratch / "m23-claims.json"),
        ),
    ]
    if _version_key(version) >= DEFORMATION_INTRODUCED:
        commands.extend(
            (
                (str(python), "examples/deformation/exact_spaces/run.py"),
                (str(python), "examples/deformation/finite_lifts/run.py"),
            )
        )
    return tuple(commands)


def _run_packaged_examples(
    python: Path,
    source_root: Path,
    scratch: Path,
    *,
    version: str,
    require_gp: bool,
) -> None:
    for command in _packaged_example_commands(
        python,
        scratch,
        version=version,
        require_gp=require_gp,
    ):
        _run(command, cwd=source_root)


def qualify_installs(
    artifacts: Sequence[Path],
    *,
    version: str,
    python_spec: str,
    sdist: Path,
    run_examples: bool,
    require_gp: bool = False,
) -> tuple[dict[str, object], ...]:
    """Install each artifact into a fresh UV venv and run bounded smoke checks."""

    uv = shutil.which("uv")
    if uv is None:
        raise QualificationError("--install requires uv on PATH")
    reports: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="arbogast-artifact-qualification-") as temporary:
        base = Path(temporary)
        source_root = _extract_sdist(sdist, version, base / "source")
        v010_fixture = source_root / "tests/fixtures/compat/v0.1.0/h1-c2-f2.json"
        installed: list[tuple[Path, Path]] = []
        for index, artifact in enumerate(artifacts):
            venv = base / f"venv-{index}"
            _run((uv, "venv", "--python", python_spec, str(venv)), cwd=base)
            python = _venv_python(venv)
            _run((uv, "pip", "install", "--python", str(python), str(artifact)), cwd=base)
            _smoke_install(
                python,
                version=version,
                cwd=base,
                without_gp=False,
                require_gp=require_gp,
            )
            _smoke_install(python, version=version, cwd=base, without_gp=True)
            _smoke_v010_replay(python, v010_fixture, cwd=base)
            installed.append((artifact, python))
            reports.append(
                {
                    "artifact": artifact.name,
                    "ambient_backend_probe": "passed",
                    "fresh_install": "passed",
                    "installed_console_entry_points": "passed",
                    "v0.1_golden_replay": "passed",
                    "required_gp_backend_probe": "passed" if require_gp else "not-requested",
                    "without_gp_backend_probe": "passed",
                }
            )
        if run_examples:
            for index, (_, python) in enumerate(installed):
                _run_packaged_examples(
                    python,
                    source_root,
                    base / f"example-output-{index}",
                    version=version,
                    require_gp=require_gp,
                )
                reports[index]["packaged_examples"] = "passed"
    return tuple(reports)


def _project_version(root: Path) -> str:
    try:
        value = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        version = value["project"]["version"]
    except (KeyError, OSError, TypeError, tomllib.TOMLDecodeError) as error:
        raise QualificationError(f"cannot read project version: {error}") from error
    if not isinstance(version, str) or not version:
        raise QualificationError("project version must be a non-empty string")
    return version


def qualify(
    root: Path,
    dist_dir: Path,
    *,
    expected_version: str | None = None,
    install: bool = False,
    examples: bool = False,
    require_gp: bool = False,
    python_spec: str = sys.executable,
) -> dict[str, object]:
    declared_version = _project_version(root)
    version = expected_version or declared_version
    if expected_version is not None and declared_version != expected_version:
        raise QualificationError(
            f"pyproject version must be {expected_version}, found {declared_version}"
        )
    wheel = (dist_dir / f"arbogast-{version}-py3-none-any.whl").resolve()
    sdist = (dist_dir / f"arbogast-{version}.tar.gz").resolve()
    source_archive = (dist_dir / f"arbogast-{version}-source.tar.gz").resolve()
    artifact_reports = (
        inspect_wheel(wheel, version),
        inspect_sdist(sdist, version),
        inspect_source_archive(source_archive, version),
    )
    _cross_artifact_consistency(wheel, sdist, source_archive, version)
    install_reports: tuple[dict[str, object], ...] = ()
    if examples and not install:
        raise QualificationError("--examples requires --install")
    if require_gp and not install:
        raise QualificationError("--require-gp requires --install")
    if install:
        install_reports = qualify_installs(
            (wheel, sdist),
            version=version,
            python_spec=python_spec,
            sdist=sdist,
            run_examples=examples,
            require_gp=require_gp,
        )
    return {
        "artifacts": list(artifact_reports),
        "cross_artifact_consistency": "passed",
        "installs": list(install_reports),
        "ok": True,
        "schema": ARCHIVE_SCHEMA,
        "version": version,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--dist-dir", type=Path, default=PROJECT_ROOT / "dist")
    parser.add_argument("--expected-version")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--examples", action="store_true")
    parser.add_argument("--require-gp", action="store_true")
    parser.add_argument("--python", default=sys.executable, dest="python_spec")
    parser.add_argument("--report", type=Path, help="also write the exact JSON report to this path")
    args = parser.parse_args(argv)
    try:
        report = qualify(
            args.root.resolve(),
            args.dist_dir.resolve(),
            expected_version=args.expected_version,
            install=args.install,
            examples=args.examples,
            require_gp=args.require_gp,
            python_spec=args.python_spec,
        )
    except (OSError, QualificationError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        report = {
            "error": str(error),
            "ok": False,
            "schema": ARCHIVE_SCHEMA,
            "version": args.expected_version,
        }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
