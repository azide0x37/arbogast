"""Construction, replay, and activation of campaign-readiness theorems."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar, cast

from arbogast.cert import (
    CertificateVerificationError,
    FrozenMap,
    VerificationCertificate,
    VerificationReport,
    VerifierRegistry,
    canonicalize,
    freeze_mapping,
)
from arbogast.claims import (
    Claim,
    ClaimDomain,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
    claim_boundary_hash,
)
from arbogast.formats import canonical_bytes, canonical_dumps

from .models import (
    BootstrapError,
    EnvironmentSnapshot,
    ObligationStatus,
    ReadinessObligation,
    ReadinessProfile,
    ReadinessReceipt,
    ReadinessScope,
    ReadinessVerdict,
    _registry_binding_error,
    verdict_for,
)

READINESS_VERIFIER = "arbogast.bootstrap.readiness.v1"
FRESH_PROCESS_FIXTURE_SCHEMA = "arbogast.bootstrap.fresh-process-fixture/v1"
FRESH_PROCESS_FIXTURE_VALUES = (1, 1, 2, 3, 5, 8)

READINESS_CHECKS = (
    "readiness-receipt-integrity",
    "exact-E-C-P-G-V-X-A-R-binding",
    "profile-obligation-completeness",
    "required-optional-boundary",
    "obligation-evidence-replay",
    "readiness-verdict-recomputation",
    "environmental-claim-boundary",
)
READINESS_GUARANTEES = (
    "The verdict is scoped to the exact E,C,P,G,V,X,A,R subject.",
    "Optional missing capabilities do not block readiness.",
    "UNKNOWN, UNSUPPORTED, and PARTIAL are never promoted to BLOCKED.",
    "Portable replay checks the transcript; activation reruns live custody and process probes.",
    "No mathematical claim logically depends on this environment claim.",
)
READINESS_SUBJECT = "Ready(E,C,P,G,V,X,A) environmental readiness determination"


def _plain(value: object) -> object:
    return canonicalize(value)


def _nested_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CertificateVerificationError(f"{label} must be a string-keyed object")
    return cast(Mapping[str, object], value)


def _backend_coverage(
    environment: EnvironmentSnapshot,
    requirements: Mapping[str, object],
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    unknown: list[str] = []
    for name, raw_requirement in requirements.items():
        requirement = _nested_mapping(raw_requirement, f"backend requirement {name}")
        raw_status = environment.backends.get(name)
        if raw_status is None:
            missing.append(f"backend {name} was not probed")
            continue
        status = _nested_mapping(raw_status, f"backend status {name}")
        available = status.get("available")
        if available is None:
            unknown.append(f"backend {name} availability is unknown")
            continue
        if available is not True:
            missing.append(f"backend {name} is unavailable")
            continue
        required_version = requirement.get("version")
        if required_version is not None and status.get("version") != required_version:
            missing.append(f"backend {name} version does not match {required_version}")
        raw_caps = requirement.get("capabilities", ())
        if isinstance(raw_caps, str) or not isinstance(raw_caps, Sequence):
            raise CertificateVerificationError("backend capability requirements are malformed")
        status_caps = status.get("capabilities", ())
        if isinstance(status_caps, str) or not isinstance(status_caps, Sequence):
            raise CertificateVerificationError("backend status capabilities are malformed")
        absent = sorted(set(raw_caps) - set(status_caps))
        if absent:
            missing.append(f"backend {name} lacks capabilities: {', '.join(absent)}")
        if "conflicting_versions" in requirement:
            missing.append(f"backend {name} has conflicting plan version requirements")
    return missing, unknown


def _python_obligation(
    environment: EnvironmentSnapshot, profile: ReadinessProfile
) -> tuple[ObligationStatus, str, dict[str, object]]:
    try:
        pieces = environment.python_version.split(".")
        version = (int(pieces[0]), int(pieces[1]))
    except (IndexError, ValueError):
        return (
            ObligationStatus.UNKNOWN,
            "the captured Python version could not be parsed",
            {"captured": environment.python_version},
        )
    supported = profile.minimum_python <= version < profile.maximum_python_exclusive
    return (
        ObligationStatus.SATISFIED if supported else ObligationStatus.UNSATISFIED,
        (
            "the captured interpreter is inside the declared support interval"
            if supported
            else "the captured interpreter is outside the declared support interval"
        ),
        {
            "captured": environment.python_version,
            "minimum": profile.minimum_python,
            "maximum_exclusive": profile.maximum_python_exclusive,
        },
    )


def _identity_obligation(
    environment: EnvironmentSnapshot, profile: ReadinessProfile
) -> tuple[ObligationStatus, str, dict[str, object]]:
    facts: dict[str, object] = {
        "captured_version": environment.arbogast_version,
        "expected_version": profile.expected_arbogast_version,
        "location": environment.arbogast_location,
        "tree_sha256": environment.arbogast_tree_sha256,
        "expected_tree_sha256": profile.expected_arbogast_tree_sha256,
        "package_hashes_captured": environment.capture_options.get("package_hashes"),
    }
    if "arbogast.tree" in environment.probe_errors:
        return ObligationStatus.UNKNOWN, "Arbogast tree hashing did not complete", facts
    if any(str(key).startswith("$") for key in environment.packages):
        return ObligationStatus.UNKNOWN, "installed-package hashing did not complete", facts
    if (
        profile.scope in {ReadinessScope.PLAN, ReadinessScope.DISPATCH}
        and environment.capture_options.get("package_hashes") is not True
    ):
        return (
            ObligationStatus.UNSATISFIED,
            "plan readiness requires installed-package identity capture",
            facts,
        )
    matches = (
        environment.arbogast_version == profile.expected_arbogast_version
        and environment.arbogast_tree_sha256 == profile.expected_arbogast_tree_sha256
    )
    return (
        ObligationStatus.SATISFIED if matches else ObligationStatus.UNSATISFIED,
        (
            "the exact Arbogast version and source tree identity are bound"
            if matches
            else "the captured Arbogast version or source tree differs from the profile"
        ),
        facts,
    )


def _lock_obligation(
    environment: EnvironmentSnapshot, profile: ReadinessProfile
) -> tuple[ObligationStatus, str, dict[str, object]]:
    facts: dict[str, object] = {
        "required": profile.require_lock_consistency,
        "captured": environment.lock_consistent,
        "detail": environment.lock_detail,
        "lockfiles": tuple(item.to_dict() for item in environment.lockfiles),
    }
    if not profile.require_lock_consistency:
        return ObligationStatus.SATISFIED, "lock consistency is not required by the profile", facts
    if environment.capture_options.get("lockfile") is not True:
        return (
            ObligationStatus.UNSATISFIED,
            "the environment capture did not run the required lock check",
            facts,
        )
    if environment.lock_consistent is None:
        return ObligationStatus.UNKNOWN, environment.lock_detail, facts
    if environment.lock_consistent:
        return ObligationStatus.SATISFIED, environment.lock_detail, facts
    return ObligationStatus.UNSATISFIED, environment.lock_detail, facts


def _operation_obligation(
    profile: ReadinessProfile,
) -> tuple[ObligationStatus, str, dict[str, object]]:
    manifest = profile.operation_registry.manifest
    missing = tuple(manifest.get("missing", ()))
    uncertifiable = tuple(manifest.get("uncertifiable", ()))
    registry_error = manifest.get("registry_error")
    nested = manifest.get("manifest")
    manifest_digest = manifest.get("manifest_digest")
    blocked = (*missing, *uncertifiable)
    if manifest.get("interface_supported") is not True:
        return (
            ObligationStatus.UNSUPPORTED,
            "the runtime lacks the v1 operation-registry readiness interface",
            {
                "required": profile.required_operations,
                "registry_id": profile.operation_registry.runtime_id,
            },
        )
    if registry_error is not None:
        return (
            ObligationStatus.UNKNOWN,
            "the operation-registry readiness manifest did not complete",
            {
                "required": profile.required_operations,
                "registry_error": registry_error,
                "registry_id": profile.operation_registry.runtime_id,
            },
        )
    integrity_error = _registry_binding_error(
        profile.operation_registry,
        expected_requested=profile.required_operations,
        entries_key="operations",
    )
    if integrity_error is not None:
        return (
            ObligationStatus.UNKNOWN,
            "the operation-registry manifest failed canonical replay",
            {
                "required": profile.required_operations,
                "integrity_error": integrity_error,
                "registry_id": profile.operation_registry.runtime_id,
            },
        )
    complete = (
        isinstance(nested, Mapping)
        and isinstance(manifest_digest, str)
        and nested.get("digest") == manifest_digest
        and not blocked
    )
    return (
        ObligationStatus.SATISFIED if complete else ObligationStatus.UNSATISFIED,
        (
            "every operation has a certifiable contract and executable-identity manifest"
            if complete
            else "the operation registry lacks a complete certifiable plan manifest"
        ),
        {
            "required": profile.required_operations,
            "missing": missing,
            "uncertifiable": uncertifiable,
            "manifest_digest": manifest_digest,
            "registry_error": registry_error,
            "registry_id": profile.operation_registry.runtime_id,
        },
    )


def _capability_obligation(
    environment: EnvironmentSnapshot, profile: ReadinessProfile
) -> tuple[ObligationStatus, str, dict[str, object]]:
    trusted = set(environment.probed_capabilities)
    declared = set(environment.declared_capabilities)
    missing_caps = tuple(sorted(set(profile.required_capabilities) - trusted - declared))
    declared_only = tuple(sorted(set(profile.required_capabilities) & declared - trusted))
    optional_missing_caps = tuple(sorted(set(profile.optional_capabilities) - trusted - declared))
    optional_declared_only = tuple(sorted(set(profile.optional_capabilities) & declared - trusted))
    backend_missing, backend_unknown = _backend_coverage(environment, profile.required_backends)
    optional_backend_missing, optional_backend_unknown = _backend_coverage(
        environment, profile.optional_backends
    )
    evidence: dict[str, object] = {
        "available_capabilities": environment.capabilities,
        "probed_capabilities": environment.probed_capabilities,
        "declared_capabilities": environment.declared_capabilities,
        "required_capabilities": profile.required_capabilities,
        "missing_required_capabilities": missing_caps,
        "declared_only_required_capabilities": declared_only,
        "optional_capabilities": profile.optional_capabilities,
        "missing_optional_capabilities": optional_missing_caps,
        "declared_only_optional_capabilities": optional_declared_only,
        "missing_required_backends": tuple(backend_missing),
        "unknown_required_backends": tuple(backend_unknown),
        "missing_optional_backends": tuple(optional_backend_missing),
        "unknown_optional_backends": tuple(optional_backend_unknown),
    }
    if backend_unknown:
        return ObligationStatus.UNKNOWN, "a required backend probe was inconclusive", evidence
    if missing_caps or backend_missing:
        return (
            ObligationStatus.UNSATISFIED,
            "one or more required plan capabilities are unavailable",
            evidence,
        )
    if declared_only:
        return (
            ObligationStatus.UNKNOWN,
            "caller-declared capabilities lack fixed probe evidence",
            evidence,
        )
    return (
        ObligationStatus.SATISFIED,
        "all required plan capabilities are available; optional absences are non-blocking",
        evidence,
    )


def _verifier_obligation(
    profile: ReadinessProfile,
) -> tuple[ObligationStatus, str, dict[str, object]]:
    manifest = profile.verifier_registry.manifest
    missing_all = set(manifest.get("missing", ()))
    uncertifiable_all = set(manifest.get("uncertifiable", ()))
    missing = tuple(sorted(set(profile.required_verifiers) & missing_all))
    uncertifiable = tuple(sorted(set(profile.required_verifiers) & uncertifiable_all))
    optional_missing = tuple(sorted(set(profile.optional_verifiers) & missing_all))
    optional_uncertifiable = tuple(sorted(set(profile.optional_verifiers) & uncertifiable_all))
    nested = manifest.get("manifest")
    manifest_digest = manifest.get("manifest_digest")
    manifest_invalid = (
        not isinstance(nested, Mapping)
        or not isinstance(manifest_digest, str)
        or nested.get("digest") != manifest_digest
    )
    if manifest.get("interface_supported") is not True:
        return (
            ObligationStatus.UNSUPPORTED,
            "the runtime lacks the v1 verifier-registry readiness interface",
            {
                "required": profile.required_verifiers,
                "registry_id": profile.verifier_registry.runtime_id,
            },
        )
    if manifest.get("registry_error") is not None:
        return (
            ObligationStatus.UNKNOWN,
            "the verifier-registry readiness manifest did not complete",
            {
                "required": profile.required_verifiers,
                "registry_error": manifest.get("registry_error"),
                "registry_id": profile.verifier_registry.runtime_id,
            },
        )
    expected_requested = tuple(
        sorted(set(profile.required_verifiers) | set(profile.optional_verifiers))
    )
    integrity_error = _registry_binding_error(
        profile.verifier_registry,
        expected_requested=expected_requested,
        entries_key="verifiers",
    )
    if integrity_error is not None:
        return (
            ObligationStatus.UNKNOWN,
            "the verifier-registry manifest failed canonical replay",
            {
                "required": profile.required_verifiers,
                "integrity_error": integrity_error,
                "registry_id": profile.verifier_registry.runtime_id,
            },
        )
    required_invalid = bool(missing or uncertifiable or manifest_invalid)
    return (
        ObligationStatus.SATISFIED if not required_invalid else ObligationStatus.UNSATISFIED,
        (
            "every required certificate closure has a bound verifier"
            if not required_invalid
            else "one or more required verifier closures are absent"
        ),
        {
            "required": profile.required_verifiers,
            "missing": missing,
            "uncertifiable": uncertifiable,
            "optional": profile.optional_verifiers,
            "optional_missing": optional_missing,
            "optional_uncertifiable": optional_uncertifiable,
            "manifest_digest": manifest_digest,
            "registry_error": manifest.get("registry_error"),
            "registry_id": profile.verifier_registry.runtime_id,
        },
    )


def _executor_obligation(
    profile: ReadinessProfile,
) -> tuple[ObligationStatus, str, dict[str, object]]:
    manifest = profile.executor.manifest
    methods = _nested_mapping(manifest.get("methods", FrozenMap()), "executor methods")
    missing_methods = tuple(
        method for method in ("plan", "run", "reduce", "execute") if methods.get(method) is not True
    )
    missing_policies: list[str] = []
    if manifest.get("interface_supported") is not True:
        return (
            ObligationStatus.UNSUPPORTED,
            "the runtime lacks the required executor readiness interface",
            {
                "executor_id": profile.executor.runtime_id,
                "missing_methods": missing_methods,
            },
        )
    if manifest.get("checkpoint_error") is not None:
        return (
            ObligationStatus.UNKNOWN,
            "the executor checkpoint-support probe did not complete",
            {
                "executor_id": profile.executor.runtime_id,
                "checkpoint_error": manifest.get("checkpoint_error"),
            },
        )
    binding_errors = manifest.get("binding_errors", ())
    if isinstance(binding_errors, str) or not isinstance(binding_errors, Sequence):
        binding_errors = ("executor binding_errors is malformed",)
    clock = _nested_mapping(manifest.get("clock", FrozenMap()), "executor clock")
    if binding_errors or clock.get("identifiable") is not True:
        return (
            ObligationStatus.UNKNOWN,
            "the executor runtime semantics could not be identified completely",
            {
                "executor_id": profile.executor.runtime_id,
                "binding_errors": tuple(binding_errors),
                "clock": clock,
            },
        )
    if tuple(manifest.get("required_shard_policies", ())) != profile.shard_policies:
        return (
            ObligationStatus.UNKNOWN,
            "the executor binding does not name the exact profile shard policies",
            {"executor_id": profile.executor.runtime_id},
        )
    if "deterministic-sharding" in profile.shard_policies and missing_methods:
        missing_policies.append("deterministic-sharding")
    if (
        "checkpoint-resume" in profile.shard_policies
        and manifest.get("checkpoint_resume") is not True
    ):
        missing_policies.append("checkpoint-resume")
    return (
        ObligationStatus.SATISFIED if not missing_policies else ObligationStatus.UNSATISFIED,
        (
            "the executor supports every shard policy required by the plan"
            if not missing_policies
            else "the executor does not support every required shard policy"
        ),
        {
            "executor_id": profile.executor.runtime_id,
            "required_policies": profile.shard_policies,
            "missing_policies": tuple(missing_policies),
            "missing_methods": missing_methods,
        },
    )


def _artifact_probe(
    environment: EnvironmentSnapshot, profile: ReadinessProfile
) -> dict[str, object]:
    store = profile._runtime_artifact_store
    if store is None:
        return {"outcome": "absent", "reason": "no live artifact store was supplied"}
    payload = canonical_bytes(
        {
            "schema": "arbogast.bootstrap.artifact-roundtrip-fixture/v1",
            "environment_id": environment.environment_id,
            "profile_id": profile.profile_id,
        }
    )
    put_bytes = getattr(store, "put_bytes", None)
    get_bytes = getattr(store, "get_bytes", None)
    if not callable(put_bytes) or not callable(get_bytes):
        return {
            "outcome": "error",
            "error": "artifact store lacks the fixed put_bytes/get_bytes interface",
        }
    try:
        reference = cast(Callable[..., object], put_bytes)(payload, media_type="application/json")
        returned = cast(Callable[[object], bytes], get_bytes)(reference)
        reference_to_dict = getattr(reference, "to_dict", None)
        if not callable(reference_to_dict):
            raise TypeError("artifact reference has no canonical to_dict method")
        reference_dict = cast(Callable[[], dict[str, object]], reference_to_dict)()
    except Exception as error:
        return {
            "outcome": "error",
            "error": f"{type(error).__name__}: {error}",
        }
    return {
        "outcome": "completed",
        "input_hex": payload.hex(),
        "returned_hex": returned.hex(),
        "reference": reference_dict,
    }


def _artifact_obligation(
    evidence: Mapping[str, object],
    environment: EnvironmentSnapshot,
    profile: ReadinessProfile,
) -> tuple[ObligationStatus, str, dict[str, object]]:
    outcome = evidence.get("outcome")
    if outcome == "absent":
        return ObligationStatus.UNSATISFIED, "no artifact store is bound", dict(evidence)
    if outcome == "error":
        return (
            ObligationStatus.UNKNOWN,
            "artifact-store roundtrip raised an exception",
            dict(evidence),
        )
    if outcome != "completed":
        raise CertificateVerificationError("artifact roundtrip evidence has an invalid outcome")
    if set(evidence) != {"outcome", "input_hex", "returned_hex", "reference"}:
        raise CertificateVerificationError("artifact roundtrip evidence fields are not exact")
    input_hex = evidence.get("input_hex")
    returned_hex = evidence.get("returned_hex")
    reference = _nested_mapping(evidence.get("reference"), "artifact reference")
    if not isinstance(input_hex, str) or not isinstance(returned_hex, str):
        raise CertificateVerificationError("artifact roundtrip bytes must be hexadecimal strings")
    try:
        source = bytes.fromhex(input_hex)
        returned = bytes.fromhex(returned_hex)
    except ValueError as error:
        raise CertificateVerificationError(
            "artifact roundtrip bytes are not hexadecimal"
        ) from error
    digest = reference.get("digest")
    size = reference.get("size")
    expected = canonical_bytes(
        {
            "schema": "arbogast.bootstrap.artifact-roundtrip-fixture/v1",
            "environment_id": environment.environment_id,
            "profile_id": profile.profile_id,
        }
    )
    ephemeral = profile.artifact_store.manifest.get("ephemeral")
    persistent = not profile.require_persistent_custody or ephemeral is False
    valid = (
        source == expected
        and source == returned
        and set(reference) == {"algorithm", "digest", "media_type", "schema", "size"}
        and reference.get("schema") == "arbogast.fleet.artifact.v1"
        and reference.get("algorithm") == "sha256"
        and reference.get("media_type") == "application/json"
        and isinstance(digest, str)
        and hashlib.sha256(source).hexdigest() == digest
        and isinstance(size, int)
        and not isinstance(size, bool)
        and len(source) == size
        and persistent
    )
    return (
        ObligationStatus.SATISFIED if valid else ObligationStatus.UNSATISFIED,
        (
            "the bound artifact store returned the exact fixture with required custody"
            if valid
            else "artifact roundtrip or required persistent custody is not satisfied"
        ),
        dict(evidence),
    )


def _fixture_certificate() -> VerificationCertificate:
    return VerificationCertificate.create(
        subject="fixed bootstrap fresh-process replay fixture",
        verifier=READINESS_VERIFIER,
        witness={
            "fresh_process_fixture": {
                "schema": FRESH_PROCESS_FIXTURE_SCHEMA,
                "left": FRESH_PROCESS_FIXTURE_VALUES,
                "right": FRESH_PROCESS_FIXTURE_VALUES,
            }
        },
        checks=("fixed-fixture-equality",),
        guarantees=("Only a fixed bootstrap fixture is replayed; no callable is deserialized.",),
    )


_FRESH_PROCESS_SCRIPT = """\
import json, sys
from arbogast.cert import certificate_from_json
from arbogast.bootstrap import verify_readiness_certificate
certificate = certificate_from_json(sys.stdin.buffer.read())
report = verify_readiness_certificate(certificate)
payload = {
    "certificate_id": report.certificate_id,
    "valid": report.valid,
    "verifier": report.verifier,
}
sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
"""


def _fresh_process_probe(environment: EnvironmentSnapshot) -> dict[str, object]:
    fixture = _fixture_certificate()
    command = [environment.python_executable, "-I", "-c", _FRESH_PROCESS_SCRIPT]
    clean_environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}
    }
    try:
        completed = subprocess.run(
            command,
            input=canonical_dumps(fixture.to_dict()).encode("utf-8"),
            capture_output=True,
            timeout=15,
            check=False,
            env=clean_environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"outcome": "error", "error": f"{type(error).__name__}: {error}"}
    return {
        "outcome": "completed",
        "fixture_certificate": fixture.to_dict(),
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode("utf-8", errors="replace"),
        "stderr": completed.stderr.decode("utf-8", errors="replace"),
        "python_executable": environment.python_executable,
        "python_executable_sha256": (
            None
            if environment.python_executable_identity is None
            else environment.python_executable_identity.sha256
        ),
    }


def _fresh_process_obligation(
    evidence: Mapping[str, object],
    environment: EnvironmentSnapshot,
) -> tuple[ObligationStatus, str, dict[str, object]]:
    outcome = evidence.get("outcome")
    if outcome == "skipped":
        return ObligationStatus.UNCHECKED, "fresh-process replay was not run", dict(evidence)
    if outcome == "error":
        return ObligationStatus.UNKNOWN, "fresh-process replay did not complete", dict(evidence)
    if outcome != "completed":
        raise CertificateVerificationError("fresh-process evidence has an invalid outcome")
    if set(evidence) != {
        "outcome",
        "fixture_certificate",
        "returncode",
        "stdout",
        "stderr",
        "python_executable",
        "python_executable_sha256",
    }:
        raise CertificateVerificationError("fresh-process evidence fields are not exact")
    raw_fixture = _nested_mapping(evidence.get("fixture_certificate"), "fresh-process fixture")
    fixture = VerificationCertificate.from_dict(raw_fixture)
    if fixture != _fixture_certificate():
        raise CertificateVerificationError("fresh-process fixture is not the fixed fixture")
    fixture_report = verify_readiness_certificate(fixture)
    returncode = evidence.get("returncode")
    stdout = evidence.get("stdout")
    stderr = evidence.get("stderr")
    if (
        isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
    ):
        raise CertificateVerificationError("fresh-process result fields are malformed")
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError:
        decoded = None
    valid = (
        returncode == 0
        and stderr == ""
        and fixture_report.valid
        and evidence.get("python_executable") == environment.python_executable
        and evidence.get("python_executable_sha256")
        == (
            None
            if environment.python_executable_identity is None
            else environment.python_executable_identity.sha256
        )
        and isinstance(decoded, dict)
        and decoded
        == {
            "certificate_id": fixture.certificate_id,
            "valid": True,
            "verifier": READINESS_VERIFIER,
        }
    )
    return (
        ObligationStatus.SATISFIED if valid else ObligationStatus.UNKNOWN,
        (
            "the fixed certificate fixture replayed in an isolated fresh process"
            if valid
            else "the fresh process did not return the exact fixture verification result"
        ),
        dict(evidence),
    )


def _build_obligations(
    environment: EnvironmentSnapshot,
    profile: ReadinessProfile,
    *,
    artifact_evidence: Mapping[str, object],
    fresh_process_evidence: Mapping[str, object],
) -> tuple[ReadinessObligation, ...]:
    evaluations = {
        "python.supported": _python_obligation(environment, profile),
        "arbogast.identity-bound": _identity_obligation(environment, profile),
        "lock.consistent": _lock_obligation(environment, profile),
        "operation-registry.covers-plan": _operation_obligation(profile),
        "capabilities.cover-plan": _capability_obligation(environment, profile),
        "verifier-registry.covers-plan": _verifier_obligation(profile),
        "executor.supports-shard-policies": _executor_obligation(profile),
        "artifact-store.roundtrip": _artifact_obligation(artifact_evidence, environment, profile),
        "fresh-process.fixture-replays": _fresh_process_obligation(
            fresh_process_evidence, environment
        ),
    }
    required = set(profile.required_obligation_ids)
    return tuple(
        ReadinessObligation(
            id=obligation_id,
            required=obligation_id in required,
            status=evaluations[obligation_id][0],
            detail=evaluations[obligation_id][1],
            evidence=freeze_mapping(evaluations[obligation_id][2]),
        )
        for obligation_id in profile.obligation_ids
    )


def _claim_spec(receipt: ReadinessReceipt) -> tuple[str, FormalStatement]:
    profile = receipt.profile
    short = receipt.receipt_id.removeprefix("sha256:")[:20]
    claim_id = f"bootstrap.readiness.{short}.{receipt.verdict.value.lower()}"
    if receipt.verdict is ReadinessVerdict.READY:
        text = (
            "The captured environment satisfies the complete readiness profile for the "
            "bound campaign and plan."
        )
    elif receipt.verdict is ReadinessVerdict.BLOCKED:
        text = (
            "The captured environment does not satisfy the readiness profile because at "
            "least one required conjunct is exactly unsatisfied."
        )
    else:
        text = (
            "The readiness procedure returned the displayed non-closing determination; it "
            "does not assert readiness or mathematical failure."
        )
    return (
        claim_id,
        FormalStatement.create(
            text,
            language="environmental-readiness",
            parameters={
                "subject": receipt.subject,
                "verdict": receipt.verdict.value,
                "scope": profile.scope.value,
                "task_ids": profile.task_ids,
            },
        ),
    )


def _certificate_for(receipt: ReadinessReceipt) -> VerificationCertificate:
    claim_id, statement = _claim_spec(receipt)
    boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.CERTIFIED,
        domain=ClaimDomain.ENVIRONMENTAL,
    )
    return VerificationCertificate.create(
        subject=READINESS_SUBJECT,
        verifier=READINESS_VERIFIER,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=boundary,
        witness={"readiness_receipt": receipt.to_dict()},
        checks=READINESS_CHECKS,
        guarantees=READINESS_GUARANTEES,
    )


@dataclass(frozen=True)
class ReadinessResult:
    environment: EnvironmentSnapshot
    profile: ReadinessProfile
    receipt: ReadinessReceipt
    certificate: VerificationCertificate

    expected_verdict: ClassVar[ReadinessVerdict | None] = None

    def __post_init__(self) -> None:
        if not isinstance(self.environment, EnvironmentSnapshot):
            raise BootstrapError("readiness result environment is invalid")
        if not isinstance(self.profile, ReadinessProfile):
            raise BootstrapError("readiness result profile is invalid")
        if not isinstance(self.receipt, ReadinessReceipt):
            raise BootstrapError("readiness result receipt is invalid")
        if not isinstance(self.certificate, VerificationCertificate):
            raise BootstrapError("readiness result certificate is invalid")
        if self.receipt.environment != self.environment or self.receipt.profile != self.profile:
            raise BootstrapError("readiness result subject differs from its receipt")
        embedded = self.certificate.witness.get("readiness_receipt")
        if _plain(embedded) != self.receipt.to_dict():
            raise BootstrapError("readiness result certificate embeds a different receipt")
        expected = type(self).expected_verdict
        if expected is not None and self.receipt.verdict is not expected:
            raise BootstrapError(
                f"{type(self).__name__} requires verdict {expected.value}, "
                f"got {self.receipt.verdict.value}"
            )

    @property
    def verdict(self) -> ReadinessVerdict:
        return self.receipt.verdict

    @property
    def blockers(self) -> tuple[ReadinessObligation, ...]:
        return tuple(
            item
            for item in self.receipt.obligations
            if item.required and item.status is ObligationStatus.UNSATISFIED
        )

    @property
    def unchecked(self) -> tuple[ReadinessObligation, ...]:
        return tuple(
            item
            for item in self.receipt.obligations
            if item.required
            and item.status
            in {
                ObligationStatus.UNKNOWN,
                ObligationStatus.UNSUPPORTED,
                ObligationStatus.UNCHECKED,
            }
        )

    def verify(
        self,
        *,
        verifier_registry: VerifierRegistry | None = None,
    ) -> VerificationReport:
        if verifier_registry is None:
            from arbogast.cert import default_verifiers

            verifier_registry = default_verifiers
        report = verifier_registry.verify(self.certificate)
        expected = type(self).expected_verdict
        if expected is not None and self.verdict is not expected:
            raise CertificateVerificationError("result class does not match receipt verdict")
        if (
            readiness_receipt(self.certificate, verify=False, verifier_registry=verifier_registry)
            != self.receipt
        ):
            raise CertificateVerificationError("result receipt differs from its certificate")
        return report

    def claim(self) -> Claim:
        claim_id, statement = _claim_spec(self.receipt)
        return Claim(
            id=claim_id,
            what=statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.CERTIFIED,
            domain=ClaimDomain.ENVIRONMENTAL,
            why=(),
            how=Derivation.computation(
                "bootstrap.certify_campaign_readiness",
                method="Replay the finite readiness conjunction for exact E,C,P,G,V,X,A,R",
                inputs=(
                    self.environment.environment_id,
                    self.profile.profile_id,
                ),
            ),
            certificate=self.certificate,
            source=("arbogast.bootstrap",),
            metadata={
                "claim_domain": ClaimDomain.ENVIRONMENTAL.value,
                "readiness_verdict": self.verdict.value,
                "environment_id": self.environment.environment_id,
                "profile_id": self.profile.profile_id,
                "campaign_id": self.profile.campaign_id,
                "plan_id": self.profile.plan_id,
                "task_ids": self.profile.task_ids,
            },
        )

    def claim_graph(self) -> ClaimGraph:
        return ClaimGraph((self.claim(),), graph_id=f"bootstrap:{self.profile.profile_id}")

    def write_artifacts(self, root: str | Path) -> dict[str, Path]:
        """Write the four authoritative records and one non-authoritative projection."""

        destination = Path(root)
        destination.mkdir(parents=True, exist_ok=True)
        from .report import BootstrapReport

        values = {
            "environment-snapshot.json": self.environment.to_dict(),
            "readiness-profile.json": self.profile.to_dict(),
            "readiness-certificate.json": self.certificate.to_dict(),
            "readiness-claim.json": self.claim().to_dict(),
            "bootstrap-report.json": BootstrapReport.from_result(self).to_dict(),
        }
        paths: dict[str, Path] = {}
        for name, value in values.items():
            path = destination / name
            payload = canonical_dumps(value).encode("utf-8")
            handle, temporary_name = tempfile.mkstemp(prefix=".bootstrap-", dir=destination)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            paths[name] = path
        return paths


class CertifiedReady(ReadinessResult):
    expected_verdict = ReadinessVerdict.READY


class CertifiedBlocked(ReadinessResult):
    expected_verdict = ReadinessVerdict.BLOCKED


class Partial(ReadinessResult):
    expected_verdict = ReadinessVerdict.PARTIAL


class Unknown(ReadinessResult):
    expected_verdict = ReadinessVerdict.UNKNOWN


class Unsupported(ReadinessResult):
    expected_verdict = ReadinessVerdict.UNSUPPORTED


def _result_type(verdict: ReadinessVerdict) -> type[ReadinessResult]:
    return {
        ReadinessVerdict.READY: CertifiedReady,
        ReadinessVerdict.BLOCKED: CertifiedBlocked,
        ReadinessVerdict.PARTIAL: Partial,
        ReadinessVerdict.UNKNOWN: Unknown,
        ReadinessVerdict.UNSUPPORTED: Unsupported,
    }[verdict]


def certify_campaign_readiness(
    *,
    environment: EnvironmentSnapshot,
    profile: ReadinessProfile,
    run_fresh_process: bool = True,
) -> ReadinessResult:
    """Certify the complete finite readiness predicate for one exact subject."""

    if not isinstance(environment, EnvironmentSnapshot):
        raise TypeError("environment must be an EnvironmentSnapshot")
    if not isinstance(profile, ReadinessProfile):
        raise TypeError("profile must be a ReadinessProfile")
    artifact_evidence = _artifact_probe(environment, profile)
    fresh_evidence = (
        _fresh_process_probe(environment)
        if run_fresh_process
        else {"outcome": "skipped", "reason": "caller disabled the fresh-process probe"}
    )
    obligations = _build_obligations(
        environment,
        profile,
        artifact_evidence=artifact_evidence,
        fresh_process_evidence=fresh_evidence,
    )
    verdict = verdict_for(obligations)
    subject = {"E": environment.environment_id, **profile.bindings, "R": profile.profile_id}
    receipt = ReadinessReceipt(
        environment=environment,
        profile=profile,
        subject=freeze_mapping(subject),
        verdict=verdict,
        obligations=obligations,
    )
    certificate = _certificate_for(receipt)
    result_type = _result_type(verdict)
    return result_type(environment, profile, receipt, certificate)


def _verify_fixture(certificate: VerificationCertificate) -> VerificationReport:
    if set(certificate.witness) != {"fresh_process_fixture"}:
        raise CertificateVerificationError("fresh-process fixture witness has unknown fields")
    fixture = _nested_mapping(certificate.witness["fresh_process_fixture"], "fresh-process fixture")
    if set(fixture) != {"schema", "left", "right"}:
        raise CertificateVerificationError("fresh-process fixture fields are not exact")
    if fixture.get("schema") != FRESH_PROCESS_FIXTURE_SCHEMA:
        raise CertificateVerificationError("unsupported fresh-process fixture schema")
    left = fixture.get("left")
    right = fixture.get("right")
    if (
        isinstance(left, str)
        or not isinstance(left, Sequence)
        or isinstance(right, str)
        or not isinstance(right, Sequence)
        or tuple(left) != FRESH_PROCESS_FIXTURE_VALUES
        or tuple(right) != FRESH_PROCESS_FIXTURE_VALUES
    ):
        raise CertificateVerificationError("fresh-process fixture values are not canonical")
    if certificate.claim_id is not None:
        raise CertificateVerificationError("fresh-process fixture must not bind a claim")
    if certificate.subject != "fixed bootstrap fresh-process replay fixture":
        raise CertificateVerificationError("fresh-process fixture subject is not canonical")
    if certificate.checks != ("fixed-fixture-equality",):
        raise CertificateVerificationError("fresh-process fixture checks are not canonical")
    if certificate.guarantees != (
        "Only a fixed bootstrap fixture is replayed; no callable is deserialized.",
    ):
        raise CertificateVerificationError("fresh-process fixture guarantees are not canonical")
    return VerificationReport(
        valid=True,
        verifier=READINESS_VERIFIER,
        certificate_id=certificate.certificate_id,
        checks=("fixed-fixture-equality", "no-deserialized-callable"),
        details=freeze_mapping({"fixture_schema": FRESH_PROCESS_FIXTURE_SCHEMA}),
    )


def readiness_receipt(
    certificate: VerificationCertificate,
    *,
    verify: bool = True,
    verifier_registry: VerifierRegistry | None = None,
) -> ReadinessReceipt:
    """Decode the strict embedded receipt, verifying it by default."""

    if not isinstance(certificate, VerificationCertificate):
        raise TypeError("readiness certificate must be a VerificationCertificate")
    if certificate.verifier != READINESS_VERIFIER:
        raise CertificateVerificationError("certificate does not name the readiness verifier")
    if verify:
        if verifier_registry is None:
            from arbogast.cert import default_verifiers

            verifier_registry = default_verifiers
        verifier_registry.verify(certificate)
    if set(certificate.witness) != {"readiness_receipt"}:
        raise CertificateVerificationError("readiness certificate witness fields are not exact")
    raw = _nested_mapping(certificate.witness["readiness_receipt"], "readiness receipt")
    try:
        return ReadinessReceipt.from_dict(raw)
    except (TypeError, ValueError) as error:
        raise CertificateVerificationError(f"invalid readiness receipt: {error}") from error


def verify_readiness_certificate(
    certificate: VerificationCertificate,
) -> VerificationReport:
    """Replay transcript integrity without authorizing a live campaign runtime."""

    if not isinstance(certificate, VerificationCertificate):
        raise CertificateVerificationError("readiness verifier requires VerificationCertificate")
    certificate.verify_integrity()
    if certificate.verifier != READINESS_VERIFIER:
        raise CertificateVerificationError("certificate names a different verifier")
    if "fresh_process_fixture" in certificate.witness:
        return _verify_fixture(certificate)
    receipt = readiness_receipt(certificate, verify=False)
    artifact = next(item for item in receipt.obligations if item.id == "artifact-store.roundtrip")
    fresh = next(item for item in receipt.obligations if item.id == "fresh-process.fixture-replays")
    replayed = _build_obligations(
        receipt.environment,
        receipt.profile,
        artifact_evidence=artifact.evidence,
        fresh_process_evidence=fresh.evidence,
    )
    if replayed != receipt.obligations:
        raise CertificateVerificationError("readiness obligations do not replay exactly")
    if verdict_for(replayed) is not receipt.verdict:
        raise CertificateVerificationError("readiness verdict does not replay")
    claim_id, statement = _claim_spec(receipt)
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.CERTIFIED,
        domain=ClaimDomain.ENVIRONMENTAL,
    )
    if (
        certificate.claim_id != claim_id
        or certificate.statement_hash != statement.statement_hash
        or certificate.claim_boundary_hash != expected_boundary
    ):
        raise CertificateVerificationError("certificate environmental claim binding is invalid")
    if certificate.checks != READINESS_CHECKS:
        raise CertificateVerificationError("readiness certificate check set is not canonical")
    if certificate.subject != READINESS_SUBJECT:
        raise CertificateVerificationError("readiness certificate subject is not canonical")
    if certificate.guarantees != READINESS_GUARANTEES:
        raise CertificateVerificationError("readiness certificate guarantees are not canonical")
    return VerificationReport(
        valid=True,
        verifier=READINESS_VERIFIER,
        certificate_id=certificate.certificate_id,
        checks=READINESS_CHECKS,
        details=freeze_mapping(
            {
                "environment_id": receipt.environment.environment_id,
                "profile_id": receipt.profile.profile_id,
                "verdict": receipt.verdict.value,
                "required_blockers": tuple(
                    item.id
                    for item in receipt.obligations
                    if item.required and item.status is ObligationStatus.UNSATISFIED
                ),
            }
        ),
    )


@dataclass(frozen=True)
class ReadinessActivationReport:
    valid: bool
    certificate_id: str
    claim_id: str
    environment_id: str
    profile_id: str
    campaign_id: str
    plan_id: str
    task_ids: tuple[str, ...]
    checks: tuple[str, ...]
    blockers: tuple[str, ...]

    def require_valid(self) -> ReadinessActivationReport:
        if not self.valid:
            raise BootstrapError("readiness activation rejected: " + "; ".join(self.blockers))
        return self


def validate_readiness_activation(
    certificate: VerificationCertificate,
    *,
    campaign: object,
    plan: object,
    operation_registry: object,
    verifier_registry: VerifierRegistry,
    executor: object,
    artifact_store: object | None = None,
    environment: EnvironmentSnapshot | None = None,
) -> ReadinessActivationReport:
    """Authorize only after exact PLAN equality and fresh live probe execution."""

    receipt = readiness_receipt(certificate)
    profile = receipt.profile
    blockers: list[str] = []
    checks = ["certificate-replay"]
    if receipt.verdict is not ReadinessVerdict.READY:
        blockers.append(f"certificate verdict is {receipt.verdict.value}, not READY")
    if profile.scope is not ReadinessScope.PLAN:
        blockers.append("campaign activation requires an exact PLAN readiness profile")
    try:
        current = ReadinessProfile.from_plan(
            campaign,
            plan,
            operation_registry,
            verifier_registry,
            executor,
            required_verifiers=profile.required_verifiers,
            optional_capabilities=profile.optional_capabilities,
            optional_backends=profile.optional_backends,
            optional_verifiers=profile.optional_verifiers,
            optional_obligations=(),
            expected_arbogast_version=profile.expected_arbogast_version,
            require_lock_consistency=profile.require_lock_consistency,
            require_persistent_custody=profile.require_persistent_custody,
            scope=ReadinessScope.PLAN,
        )
    except Exception as error:
        blockers.append(f"current runtime profile failed: {type(error).__name__}: {error}")
        current = None
    if current is not None:
        if artifact_store is not None:
            from .runtime import artifact_store_binding

            current_artifact_binding = artifact_store_binding(
                artifact_store,
                ephemeral=getattr(executor, "_temporary", None) is not None,
            )
            current = replace(
                current,
                artifact_store=current_artifact_binding,
                _runtime_artifact_store=artifact_store,
            )
        comparisons = {
            "profile": (current.profile_id, profile.profile_id),
            "campaign": (current.campaign_id, profile.campaign_id),
            "plan": (current.plan_id, profile.plan_id),
            "task roster": (current.task_ids, profile.task_ids),
            "operation registry": (
                current.operation_registry.runtime_id,
                profile.operation_registry.runtime_id,
            ),
            "verifier registry": (
                current.verifier_registry.runtime_id,
                profile.verifier_registry.runtime_id,
            ),
            "executor": (current.executor.runtime_id, profile.executor.runtime_id),
            "artifact store": (
                current.artifact_store.runtime_id,
                profile.artifact_store.runtime_id,
            ),
        }
        for label, (observed, expected) in comparisons.items():
            if observed != expected:
                blockers.append(f"current {label} identity does not match the certificate")
        checks.extend(f"live-{label.replace(' ', '-')}-binding" for label in comparisons)
    if environment is None:
        from .capture import capture_environment

        campaign_capabilities = getattr(campaign, "capabilities", ())
        if campaign_capabilities is None:
            campaign_capabilities = ()
        options = receipt.environment.capture_options
        external_backends = options.get("probe_external") is True
        try:
            environment = capture_environment(
                project_root=receipt.environment.project_root,
                package_hashes=options.get("package_hashes") is True,
                lockfile=options.get("lockfile") is True,
                backends=external_backends,
                capabilities=campaign_capabilities,
                probe_external=external_backends,
            )
        except Exception as error:
            blockers.append(f"current environment capture failed: {type(error).__name__}: {error}")
    if environment is not None:
        if environment.environment_id != receipt.environment.environment_id:
            blockers.append("current environment identity does not match the certificate")
        checks.append("live-environment-binding")
    if current is not None and environment is not None:
        try:
            live_obligations = _build_obligations(
                environment,
                current,
                artifact_evidence=_artifact_probe(environment, current),
                fresh_process_evidence=_fresh_process_probe(environment),
            )
            live_verdict = verdict_for(live_obligations)
        except Exception as error:
            blockers.append(f"live readiness probes failed: {type(error).__name__}: {error}")
        else:
            if live_verdict is not ReadinessVerdict.READY:
                blockers.extend(
                    f"live obligation {item.id} is {item.status.value}: {item.detail}"
                    for item in live_obligations
                    if item.required and item.status is not ObligationStatus.SATISFIED
                )
            checks.extend(
                (
                    "live-artifact-store-roundtrip",
                    "live-fresh-process-fixture-replay",
                    "live-readiness-conjunction",
                )
            )
    assert certificate.claim_id is not None
    return ReadinessActivationReport(
        valid=not blockers,
        certificate_id=certificate.certificate_id,
        claim_id=certificate.claim_id,
        environment_id=receipt.environment.environment_id,
        profile_id=profile.profile_id,
        campaign_id=profile.campaign_id,
        plan_id=profile.plan_id,
        task_ids=profile.task_ids,
        checks=tuple(checks),
        blockers=tuple(blockers),
    )


__all__ = [
    "READINESS_VERIFIER",
    "CertifiedBlocked",
    "CertifiedReady",
    "Partial",
    "ReadinessActivationReport",
    "ReadinessResult",
    "Unknown",
    "Unsupported",
    "certify_campaign_readiness",
    "readiness_receipt",
    "validate_readiness_activation",
    "verify_readiness_certificate",
]
