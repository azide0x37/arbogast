"""Bounded diagnostic-only environment preflight projection."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from arbogast.cert import canonicalize, content_address
from arbogast.formats import ENVIRONMENT_PREFLIGHT_SCHEMA

from .models import ObligationStatus

if TYPE_CHECKING:
    from .models import EnvironmentSnapshot
    from .readiness import ReadinessResult


_MODES = frozenset({"campaign", "core", "replay"})
_SATISFIED = "SATISFIED"
_UNSATISFIED = "UNSATISFIED"
_UNKNOWN = "UNKNOWN"
_UNSUPPORTED = "UNSUPPORTED"
_PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class EnvironmentPreflightReport:
    """Exact JSON projection emitted by ``arbogast doctor``.

    The record contains local diagnostic evidence only.  It intentionally
    omits certificate, claim, plan, and mathematical-outcome fields and cannot
    authorize campaign dispatch.
    """

    mode: str
    profile: dict[str, object]
    status: str
    ready: bool
    captured_at: str
    environment_digest: str
    arbogast: dict[str, object]
    python: dict[str, object]
    uv: dict[str, object]
    project: dict[str, object]
    portable_core: dict[str, object]
    capabilities: tuple[dict[str, object], ...]
    checks: tuple[dict[str, object], ...]
    required_blockers: tuple[str, ...]
    optional_blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    next_commands: tuple[str, ...]

    schema: ClassVar[str] = ENVIRONMENT_PREFLIGHT_SCHEMA
    authoritative: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError("mode must be campaign, core, or replay")
        required = tuple(check for check in self.checks if check.get("requirement") == "REQUIRED")
        if not required:
            raise ValueError("environment preflight must contain a required check")
        if self.status != _status_for_checks(self.checks):
            raise ValueError("preflight status does not match its required checks")
        if self.ready is not (self.status == "READY"):
            raise ValueError("preflight ready flag does not match its status")
        expected_required = tuple(
            cast(str, check["name"]) for check in required if check.get("status") != _SATISFIED
        )
        expected_optional = tuple(
            cast(str, check["name"])
            for check in self.checks
            if check.get("requirement") == "OPTIONAL" and check.get("status") != _SATISFIED
        )
        if self.required_blockers != expected_required:
            raise ValueError("required blockers do not match required checks")
        if self.optional_blockers != expected_optional:
            raise ValueError("optional blockers do not match optional checks")

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            canonicalize(
                {
                    "schema": self.schema,
                    "mode": self.mode,
                    "profile": self.profile,
                    "authoritative": self.authoritative,
                    "status": self.status,
                    "ready": self.ready,
                    "captured_at": self.captured_at,
                    "environment_digest": self.environment_digest,
                    "arbogast": self.arbogast,
                    "python": self.python,
                    "uv": self.uv,
                    "project": self.project,
                    "portable_core": self.portable_core,
                    "capabilities": self.capabilities,
                    "checks": self.checks,
                    "required_blockers": self.required_blockers,
                    "optional_blockers": self.optional_blockers,
                    "warnings": self.warnings,
                    "next_commands": self.next_commands,
                }
            ),
        )


def _captured_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _file_record(path: Path) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path.resolve()), "present": path.is_file()}
    if not path.is_file():
        return record
    try:
        payload = path.read_bytes()
    except OSError as error:
        record["error"] = f"{type(error).__name__}: {error}"
        return record
    record.update(
        {
            "sha256": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            "size": len(payload),
        }
    )
    return record


def _arbogast_dependency_pin(
    dependencies: Sequence[str], expected_version: str
) -> tuple[str | None, bool]:
    pattern = re.compile(r"^arbogast(?:\[[^]]+\])?\s*(.*)$", re.IGNORECASE)
    for dependency in dependencies:
        match = pattern.match(dependency.strip())
        if match is None:
            continue
        tail = match.group(1).strip()
        exact = re.fullmatch(r"===?\s*" + re.escape(expected_version), tail) is not None
        direct = tail.startswith("@") and bool(
            re.search(
                r"(?:@v?" + re.escape(expected_version) + r"(?:$|[#?])|[?&]sha256=[0-9a-f]{64})",
                tail,
                re.IGNORECASE,
            )
        )
        return dependency, exact or direct
    return None, False


def _locked_arbogast(path: Path, expected_version: str) -> tuple[bool | None, str | None]:
    if not path.is_file():
        return False, None
    try:
        decoded = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        return None, f"{type(error).__name__}: {error}"
    packages = decoded.get("package")
    if not isinstance(packages, Sequence) or isinstance(packages, str):
        return None, "uv.lock has no package array"
    matches = tuple(
        item
        for item in packages
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
        and str(item["name"]).lower().replace("_", "-") == "arbogast"
    )
    if not matches:
        return False, None
    return any(item.get("version") == expected_version for item in matches), None


def _project_record(root: Path, environment: EnvironmentSnapshot) -> dict[str, object]:
    pyproject_path = root / "pyproject.toml"
    project_table: Mapping[str, object] | None = None
    parse_error: str | None = None
    if pyproject_path.is_file():
        try:
            decoded = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            raw_project = decoded.get("project")
            if isinstance(raw_project, Mapping):
                project_table = cast(Mapping[str, object], raw_project)
            else:
                parse_error = "pyproject.toml has no [project] table"
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            parse_error = f"{type(error).__name__}: {error}"

    name = project_table.get("name") if project_table is not None else None
    version = project_table.get("version") if project_table is not None else None
    requires_python = project_table.get("requires-python") if project_table else None
    raw_dependencies = project_table.get("dependencies", ()) if project_table else ()
    dependencies = (
        tuple(value for value in raw_dependencies if isinstance(value, str))
        if isinstance(raw_dependencies, Sequence) and not isinstance(raw_dependencies, str)
        else ()
    )
    dependency, dependency_pinned = _arbogast_dependency_pin(
        dependencies, environment.arbogast_version
    )

    lock_path = root / "uv.lock"
    locked_arbogast, lock_probe_error = _locked_arbogast(lock_path, environment.arbogast_version)
    python_pin_path = root / ".python-version"
    python_pin: str | None = None
    python_pin_error: str | None = None
    if python_pin_path.is_file():
        try:
            python_pin = python_pin_path.read_text(encoding="utf-8").strip() or None
        except (OSError, UnicodeError) as error:
            python_pin_error = f"{type(error).__name__}: {error}"

    location = Path(environment.arbogast_location).resolve()
    source_candidates = (
        (root / "src" / "arbogast").resolve(),
        (root / "arbogast").resolve(),
    )
    source_matches = location in source_candidates
    if parse_error is not None:
        kind = "unknown"
    elif isinstance(name, str) and name.lower().replace("_", "-") == "arbogast":
        kind = "core" if source_matches else "arbogast-project"
    elif isinstance(name, str):
        kind = "campaign"
    else:
        kind = "none"

    return {
        "root": str(root),
        "kind": kind,
        "name": name if isinstance(name, str) else None,
        "version": version if isinstance(version, str) else None,
        "requires_python": requires_python if isinstance(requires_python, str) else None,
        "pyproject": _file_record(pyproject_path),
        "parse_error": parse_error,
        "lock": {
            "consistent": environment.lock_consistent,
            "detail": environment.lock_detail,
            "files": tuple(item.to_dict() for item in environment.lockfiles),
            "uv_lock": _file_record(lock_path),
            "arbogast_record_matches": locked_arbogast,
            "probe_error": lock_probe_error,
        },
        "python_pin": {
            **_file_record(python_pin_path),
            "value": python_pin,
            "error": python_pin_error,
        },
        "arbogast_dependency": dependency,
        "arbogast_dependency_pinned": dependency_pinned,
        "import_matches_source_tree": source_matches,
    }


def _probe_uv() -> dict[str, object]:
    executable = shutil.which("uv")
    if executable is None:
        return {
            "available": False,
            "version": None,
            "executable": None,
            "probe_error": None,
        }
    try:
        completed = subprocess.run(
            (executable, "--version"),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "available": None,
            "version": None,
            "executable": executable,
            "probe_error": f"{type(error).__name__}: {error}",
        }
    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0:
        return {
            "available": None,
            "version": None,
            "executable": executable,
            "probe_error": f"uv --version exited {completed.returncode}: {output}",
        }
    pieces = output.split()
    version = pieces[1] if len(pieces) >= 2 and pieces[0].lower() == "uv" else output or None
    return {
        "available": True,
        "version": version,
        "executable": str(Path(executable).resolve()),
        "probe_error": None,
    }


def _check(
    name: str,
    requirement: str,
    status: str,
    detail: str,
    evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "requirement": requirement,
        "status": status,
        "detail": detail,
        "evidence": {} if evidence is None else dict(evidence),
    }


def _result_checks(result: ReadinessResult, mode: str) -> list[dict[str, object]]:
    status_map = {
        ObligationStatus.SATISFIED: _SATISFIED,
        ObligationStatus.UNSATISFIED: _UNSATISFIED,
        ObligationStatus.UNKNOWN: _UNKNOWN,
        ObligationStatus.UNSUPPORTED: _UNSUPPORTED,
        ObligationStatus.UNCHECKED: _PARTIAL,
    }
    required = {
        "python.supported",
        "arbogast.identity-bound",
        "capabilities.cover-plan",
        "fresh-process.fixture-replays",
    }
    checks: list[dict[str, object]] = []
    for item in result.receipt.obligations:
        if item.id == "lock.consistent":
            requirement = "REQUIRED" if mode in {"campaign", "core"} else "INFORMATIONAL"
        elif item.id in required:
            requirement = "REQUIRED"
        else:
            requirement = "INFORMATIONAL"
        checks.append(
            _check(
                item.id,
                requirement,
                status_map[item.status],
                item.detail,
                item.evidence.to_dict(),
            )
        )
    return checks


def _project_checks(
    mode: str, project: Mapping[str, object], expected_version: str
) -> list[dict[str, object]]:
    role_required = mode in {"campaign", "core"}
    parse_error = project.get("parse_error")
    manifest_present = project.get("kind") not in {"none", "unknown"}
    manifest_status = (
        _UNKNOWN if parse_error is not None else _SATISFIED if manifest_present else _UNSATISFIED
    )
    checks = [
        _check(
            "project.manifest",
            "REQUIRED" if role_required else "INFORMATIONAL",
            manifest_status,
            (
                "pyproject.toml identifies the current project"
                if manifest_status == _SATISFIED
                else "pyproject.toml could not be parsed"
                if manifest_status == _UNKNOWN
                else "no project manifest is present"
            ),
            {
                "kind": project.get("kind"),
                "name": project.get("name"),
                "error": parse_error,
            },
        )
    ]
    source_checkout = project.get("kind") == "core"
    checks.append(
        _check(
            "project.source-checkout",
            "REQUIRED" if mode == "core" else "INFORMATIONAL",
            _SATISFIED if source_checkout else _UNSATISFIED,
            (
                "the imported package is the source tree of this Arbogast checkout"
                if source_checkout
                else "the imported package is not bound to an Arbogast source checkout here"
            ),
            {
                "kind": project.get("kind"),
                "import_matches_source_tree": project.get("import_matches_source_tree"),
            },
        )
    )
    separate_campaign = project.get("kind") == "campaign"
    checks.append(
        _check(
            "project.separate-from-core",
            "REQUIRED" if mode == "campaign" else "INFORMATIONAL",
            _SATISFIED if separate_campaign else _UNSATISFIED,
            (
                "the campaign is a separate project rather than the Arbogast core checkout"
                if separate_campaign
                else "campaign mode requires a separate project, not the Arbogast core checkout"
            ),
            {"kind": project.get("kind")},
        )
    )
    locked = project.get("lock")
    lock_match = locked.get("arbogast_record_matches") if isinstance(locked, Mapping) else None
    if lock_match is None:
        pin_status = _UNKNOWN
        pin_detail = "the campaign lock could not be inspected for its Arbogast record"
    else:
        pinned = project.get("arbogast_dependency_pinned") is True and lock_match is True
        pin_status = _SATISFIED if pinned else _UNSATISFIED
        pin_detail = (
            f"the project dependency and lock select Arbogast {expected_version}"
            if pinned
            else "the project does not pin and lock the imported Arbogast version"
        )
    checks.append(
        _check(
            "project.arbogast-pin",
            "REQUIRED" if mode == "campaign" else "INFORMATIONAL",
            pin_status,
            pin_detail,
            {
                "dependency": project.get("arbogast_dependency"),
                "dependency_pinned": project.get("arbogast_dependency_pinned"),
                "lock_record_matches": lock_match,
            },
        )
    )
    return checks


def _backend_checks(environment: EnvironmentSnapshot) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    names = tuple(sorted({"python", *environment.backends.keys()}))
    for name in names:
        raw = environment.backends.get(name)
        requirement = "REQUIRED" if name == "python" else "OPTIONAL"
        if not isinstance(raw, Mapping):
            checks.append(
                _check(
                    f"backend.{name}",
                    requirement,
                    _UNKNOWN,
                    f"the {name} backend did not return a status record",
                )
            )
            continue
        available = raw.get("available")
        if available is True:
            status = _SATISFIED
            detail = f"the {name} backend passed its bounded availability probe"
        elif available is False:
            status = _UNSATISFIED
            detail = str(raw.get("reason") or f"the {name} backend is unavailable")
        else:
            status = _UNKNOWN
            detail = str(raw.get("reason") or f"the {name} backend probe was inconclusive")
        checks.append(_check(f"backend.{name}", requirement, status, detail, raw))
    return checks


def _capability_records(environment: EnvironmentSnapshot) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for name in sorted({"python", *environment.backends.keys()}):
        raw = environment.backends.get(name)
        status = dict(raw) if isinstance(raw, Mapping) else {}
        records.append(
            {
                "name": name,
                "requirement": "REQUIRED" if name == "python" else "OPTIONAL",
                "available": status.get("available"),
                "version": status.get("version"),
                "executable": status.get("executable"),
                "capabilities": tuple(status.get("capabilities", ())),
                "reason": status.get("reason"),
                "probe_error": environment.probe_errors.get(f"backend.{name}"),
            }
        )
    return tuple(records)


def _status_for_checks(checks: Sequence[Mapping[str, object]]) -> str:
    required_statuses = {
        check.get("status") for check in checks if check.get("requirement") == "REQUIRED"
    }
    if _UNSATISFIED in required_statuses:
        return "BLOCKED"
    if _UNKNOWN in required_statuses:
        return "UNKNOWN"
    if _UNSUPPORTED in required_statuses:
        return "UNSUPPORTED"
    if required_statuses == {_SATISFIED}:
        return "READY"
    return "PARTIAL"


def _next_commands(mode: str, checks: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    failing = {
        check.get("name")
        for check in checks
        if check.get("requirement") == "REQUIRED" and check.get("status") != _SATISFIED
    }
    commands: list[str] = []
    if "uv.available" in failing:
        commands.append("Install uv, then rerun the same doctor command")
    if "project.mode" in failing:
        commands.append(
            "Open the Arbogast source checkout"
            if mode == "core"
            else "Open a separate campaign project that pins the intended Arbogast release"
        )
    if "lock.consistent" in failing:
        commands.append("uv lock && uv sync --frozen")
    if not failing and mode == "campaign":
        commands.append("Run the explicit campaign runtime and certify its exact readiness profile")
    return tuple(commands)


def _environment_preflight_report(
    result: ReadinessResult,
    *,
    mode: str,
    root: Path,
) -> EnvironmentPreflightReport:
    environment = result.environment
    project = _project_record(root, environment)
    uv = _probe_uv()
    checks = _result_checks(result, mode)
    checks.extend(_project_checks(mode, project, environment.arbogast_version))
    uv_required = mode in {"campaign", "core"}
    uv_available = uv.get("available")
    checks.append(
        _check(
            "uv.available",
            "REQUIRED" if uv_required else "INFORMATIONAL",
            (
                _SATISFIED
                if uv_available is True
                else _UNSATISFIED
                if uv_available is False
                else _UNKNOWN
            ),
            (
                "uv is available and reported its version"
                if uv_available is True
                else "uv is not available on PATH"
                if uv_available is False
                else "the uv version probe did not complete"
            ),
            uv,
        )
    )
    if mode != "replay":
        pin = project["python_pin"]
        assert isinstance(pin, Mapping)  # local construction invariant
        checks.append(
            _check(
                "project.python-pin",
                "REQUIRED" if mode == "campaign" else "OPTIONAL",
                (
                    _SATISFIED
                    if pin.get("value") is not None
                    else _UNKNOWN
                    if pin.get("error") is not None
                    else _UNSATISFIED
                ),
                (
                    "the project records an explicit .python-version"
                    if pin.get("value") is not None
                    else "the optional project Python pin could not be read"
                    if pin.get("error") is not None
                    else "the project has no .python-version pin"
                ),
                cast(Mapping[str, object], pin),
            )
        )
    checks.extend(_backend_checks(environment))

    required_blockers = tuple(
        cast(str, check["name"])
        for check in checks
        if check["requirement"] == "REQUIRED" and check["status"] != _SATISFIED
    )
    optional_blockers = tuple(
        cast(str, check["name"])
        for check in checks
        if check["requirement"] == "OPTIONAL" and check["status"] != _SATISFIED
    )
    status = _status_for_checks(checks)
    warnings = tuple(
        sorted(
            {
                *(f"{name}: {detail}" for name, detail in environment.probe_errors.items()),
                *(
                    f"optional check {check['name']} is {check['status']}: {check['detail']}"
                    for check in checks
                    if check["requirement"] == "OPTIONAL" and check["status"] != _SATISFIED
                ),
            }
        )
    )
    requirements = {
        kind.lower(): tuple(
            cast(str, check["name"]) for check in checks if check["requirement"] == kind
        )
        for kind in ("REQUIRED", "OPTIONAL", "INFORMATIONAL")
    }
    profile_payload: dict[str, object] = {
        "name": f"{mode}-preflight-v1",
        "mode": mode,
        "scope": "DIAGNOSTIC",
        "required_checks": requirements["required"],
        "optional_checks": requirements["optional"],
        "informational_checks": requirements["informational"],
    }
    profile: dict[str, object] = {
        **profile_payload,
        "digest": content_address(
            {"schema": "arbogast.environment-preflight-profile/v1", **profile_payload}
        ),
    }
    portable_names = {
        "python.supported",
        "arbogast.identity-bound",
        "capabilities.cover-plan",
        "artifact-store.roundtrip",
        "fresh-process.fixture-replays",
        "backend.python",
    }
    portable_checks = tuple(check for check in checks if check["name"] in portable_names)
    portable_ready = all(check["status"] == _SATISFIED for check in portable_checks)
    source_matches = project.get("import_matches_source_tree") is True
    capabilities = _capability_records(environment)
    environment_digest = content_address(
        {
            "schema": "arbogast.environment-preflight-subject/v1",
            "snapshot": environment.environment_id,
            "uv": uv,
            "project": project,
            "capabilities": capabilities,
        }
    )
    return EnvironmentPreflightReport(
        mode=mode,
        profile=profile,
        status=status,
        ready=status == "READY",
        captured_at=_captured_at(),
        environment_digest=environment_digest,
        arbogast={
            "version": environment.arbogast_version,
            "location": environment.arbogast_location,
            "tree_sha256": environment.arbogast_tree_sha256,
            "distribution_identity": environment.arbogast_tree_sha256,
            "installation": "source-checkout" if source_matches else "installed-distribution",
        },
        python={
            "implementation": environment.python_implementation,
            "version": environment.python_version,
            "executable": environment.python_executable,
            "executable_identity": (
                None
                if environment.python_executable_identity is None
                else environment.python_executable_identity.to_dict()
            ),
            "executable_sha256": (
                None
                if environment.python_executable_identity is None
                else environment.python_executable_identity.sha256
            ),
            "platform": environment.platform,
            "supported_range": ">=3.11,<3.15",
        },
        uv=uv,
        project=project,
        portable_core={
            "ready": portable_ready,
            "external_backend_required": False,
            "checks": tuple(cast(str, check["name"]) for check in portable_checks),
        },
        capabilities=capabilities,
        checks=tuple(checks),
        required_blockers=required_blockers,
        optional_blockers=optional_blockers,
        warnings=warnings,
        next_commands=_next_commands(mode, checks),
    )


def environment_preflight(
    mode: str,
    *,
    project_root: str | Path | None = None,
    artifact_root: str | Path | None = None,
    probe_external: bool = True,
) -> EnvironmentPreflightReport:
    """Run the bounded diagnostic projection without loading user callables."""

    if mode not in _MODES:
        raise ValueError("mode must be campaign, core, or replay")
    from arbogast.cert import default_verifiers
    from arbogast.fleet import ArtifactStore, FleetOperationRegistry, LocalExecutor

    from .capture import capture_environment
    from .readiness import certify_campaign_readiness
    from .runtime import diagnostic_profile

    root = Path.cwd().resolve() if project_root is None else Path(project_root).resolve()
    store = None if artifact_root is None else ArtifactStore(Path(artifact_root))
    executor = LocalExecutor(store=store, operation_registry=FleetOperationRegistry())
    environment = capture_environment(
        project_root=root,
        package_hashes=True,
        lockfile=True,
        backends=probe_external,
        probe_external=probe_external,
    )
    profile = diagnostic_profile(
        mode=mode,
        operation_registry=executor.operation_registry,
        verifier_registry=default_verifiers,
        executor=executor,
        require_lock_consistency=mode in {"campaign", "core"},
    )
    result = certify_campaign_readiness(environment=environment, profile=profile)
    return _environment_preflight_report(result, mode=mode, root=root)


__all__ = ["EnvironmentPreflightReport", "environment_preflight"]
