"""Small, explicit trusted operations for the automatic local fleet.

The automatic CLI fleet intentionally exposes only operations defined here.
It does not import a callable named by campaign data.  The built-in echo
operation is operational plumbing: it records canonical task input and returns
``UNKNOWN``; it never claims a mathematical outcome.

The arithmetic operations below are deliberately just as narrow.  Persisted
tasks may select a fixed audited operation name and canonical shard inputs, but
they cannot smuggle an import path or executable callback across the trust
boundary.  Each partial is bound to its task, operation, shard key, shard hash,
ordinal, and payload.  Reduction independently reconstructs the plan and
rejects missing, duplicate, foreign, or reordered shards before returning a
``CANDIDATE`` assembly.  A fleet verification receipt remains operational
evidence; mathematical promotion still requires the domain certificate and its
fresh-process verifier.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from arbogast.backends import BackendStatus
from arbogast.cert import (
    CertificateError,
    CertificateVerificationError,
    DiscoveryReceipt,
    UnknownVerifierError,
    VerificationCertificate,
    certificate_from_dict,
    verify_certificate,
)
from arbogast.formats import FrozenMapping, JSONValue, canonical_sha256, normalize_json

from .execution import FunctionalOperation
from .models import (
    BackendRequirement,
    FleetPlan,
    FleetSpecError,
    ResourceHint,
    ShardSpec,
    TaskSpec,
)
from .registry import FleetOperationRegistry
from .workers import Worker, WorkerPool

LOCAL_ECHO_OPERATION = "fleet.echo.v1"
LOCAL_H1_MU2_OPERATION = "galois.local-h1.mu2.v1"
LOCALIZE_SQUARECLASS_OPERATION = "galois.localize.squareclass.v1"
SELMER_ASSEMBLE_OPERATION = "arithmetic.selmer.assemble.v1"
PARI_ARITHMETIC_OPERATION = "backends.pari.arithmetic.v1"
PYTHON_CERTIFICATE_REPLAY_OPERATION = "cert.python.replay.v1"

ARITHMETIC_FLEET_OPERATIONS = (
    LOCAL_H1_MU2_OPERATION,
    LOCALIZE_SQUARECLASS_OPERATION,
    SELMER_ASSEMBLE_OPERATION,
)

CERTIFICATE_FLEET_OPERATIONS = (
    PARI_ARITHMETIC_OPERATION,
    PYTHON_CERTIFICATE_REPLAY_OPERATION,
)

_PARI_VERIFIER = "arbogast.backends.pari.v1"
_PARI_OPERATIONAL_VERIFIER = "arbogast.backends.pari.operational.v1"
_PARI_OPERATION_CAPABILITIES = {
    "class_group_2_torsion": "class-group-2-torsion",
    "complex_root_isolation": "complex-root-isolation",
    "field_invariants": "field-invariants",
    "local_squareclasses": "local-squareclasses",
    "localization_matrix": "localization-matrices",
    "prime_decomposition": "prime-decomposition",
    "quadratic_hilbert_pairing": "quadratic-hilbert-pairings",
    "relative_norm": "relative-norms",
    "s_unit_squareclasses": "s-unit-squareclasses",
}
_PORTABLE_PYTHON_VERIFIERS = frozenset(
    {
        "arithmetic.finite-linear.v1",
        "campaign.claim-closure.v1",
        "cohom.induced_map.v1",
        "cohom.inflation_restriction.v1",
        "cohom.normalized_bar.v1",
        "galois.finite_quotient.v1",
        "galois.kummer.v1",
        "galois.local_h1.v1",
        "galois.localization.v1",
        "galois.module.v1",
        "galois.quotient_presentation.v1",
        "galois.twists.v1",
        "galois.unsupported.v1",
        "hurwitz.braid_action",
        "hurwitz.boundary",
        "hurwitz.components",
        "hurwitz.cusps",
        "hurwitz.nielsen_class",
        "hurwitz.real_census",
        "hurwitz.real_structure",
        "hurwitz.reduced",
        "numeric.exact-bridge.v1",
    }
)


class ArithmeticShardError(FleetSpecError):
    """Raised when an arithmetic fleet packet crosses a shard boundary."""


class CertificateTaskError(FleetSpecError):
    """Raised when a certificate task crosses the PARI/Python trust boundary."""


def _certificate(value: object) -> VerificationCertificate:
    if isinstance(value, VerificationCertificate):
        value.verify_integrity()
        return value
    if not isinstance(value, Mapping):
        raise CertificateTaskError("certificate task input must be a certificate object")
    try:
        decoded = certificate_from_dict(value)
    except (CertificateError, TypeError, ValueError) as error:
        raise CertificateTaskError(f"invalid certificate task input: {error}") from error
    if not isinstance(decoded, VerificationCertificate):
        raise CertificateTaskError("certificate task requires verification-layer evidence")
    return decoded


def _task_certificate(task: TaskSpec) -> VerificationCertificate:
    parameters = task.parameters.to_dict()
    if set(parameters) != {"certificate"}:
        raise CertificateTaskError(
            "certificate task parameters must contain exactly one certificate"
        )
    return _certificate(parameters["certificate"])


def _pari_requirement(certificate: VerificationCertificate) -> BackendRequirement:
    operation = certificate.witness.get("operation")
    if certificate.verifier == _PARI_VERIFIER:
        version = certificate.witness.get("backend_version")
    elif certificate.verifier == _PARI_OPERATIONAL_VERIFIER:
        raw_receipt = certificate.witness.get("receipt")
        if not isinstance(raw_receipt, Mapping):
            raise CertificateTaskError("PARI operational certificate omits its receipt")
        try:
            receipt = DiscoveryReceipt.from_dict(raw_receipt)
        except (CertificateError, TypeError, ValueError) as error:
            raise CertificateTaskError(
                f"PARI operational certificate has an invalid receipt: {error}"
            ) from error
        if receipt.backend != "pari":
            raise CertificateTaskError("PARI operational receipt names another backend")
        version = receipt.backend_version
    else:
        raise CertificateTaskError(
            "PARI tasks require a proving or non-closing operational PARI certificate"
        )
    if not isinstance(operation, str) or operation not in _PARI_OPERATION_CAPABILITIES:
        raise CertificateTaskError("PARI certificate names an unsupported closed operation")
    if not isinstance(version, str) or not version:
        raise CertificateTaskError("PARI certificate does not pin its backend version")
    return BackendRequirement(
        "pari",
        version=version,
        capabilities=(_PARI_OPERATION_CAPABILITIES[operation],),
    )


def plan_pari_arithmetic_task(
    certificate: VerificationCertificate | Mapping[str, object],
    *,
    resources: ResourceHint | None = None,
) -> TaskSpec:
    """Plan one pinned-PARI certificate replay as a non-closing fleet task."""

    normalized = _certificate(certificate)
    return TaskSpec(
        PARI_ARITHMETIC_OPERATION,
        input_refs=(normalized.certificate_id,),
        parameters={"certificate": normalized.to_dict()},
        backend=_pari_requirement(normalized),
        resources=resources,
    )


def plan_python_certificate_replay_task(
    certificate: VerificationCertificate | Mapping[str, object],
    *,
    resources: ResourceHint | None = None,
) -> TaskSpec:
    """Plan portable Python replay without permitting a pinned-PARI certificate."""

    normalized = _certificate(certificate)
    if normalized.verifier not in _PORTABLE_PYTHON_VERIFIERS:
        if normalized.verifier in {_PARI_VERIFIER, _PARI_OPERATIONAL_VERIFIER}:
            raise CertificateTaskError(
                "pinned PARI evidence requires the distinct PARI arithmetic task kind"
            )
        raise CertificateTaskError(
            f"certificate verifier is not in the portable Python fleet allowlist: "
            f"{normalized.verifier}"
        )
    return TaskSpec(
        PYTHON_CERTIFICATE_REPLAY_OPERATION,
        input_refs=(normalized.certificate_id,),
        parameters={"certificate": normalized.to_dict()},
        backend=BackendRequirement(
            "python",
            capabilities=("certificate-verification",),
        ),
        resources=resources,
    )


def _sequence_parameter(task: TaskSpec, name: str) -> tuple[JSONValue, ...]:
    value = task.parameters.to_dict().get(name)
    if not isinstance(value, list) or not value:
        raise ArithmeticShardError(
            f"operation {task.operation!r} requires a non-empty {name!r} array"
        )
    return tuple(value)


def _identity(value: JSONValue) -> str:
    """Return the full canonical identity used for ordering and duplicate rejection."""

    return canonical_sha256(value)


def _unique_axis(values: Sequence[JSONValue], name: str) -> tuple[tuple[str, JSONValue], ...]:
    identified = tuple((_identity(value), value) for value in values)
    identities = tuple(identity for identity, _ in identified)
    if len(identities) != len(set(identities)):
        raise ArithmeticShardError(f"{name} contains duplicate canonical identities")
    # A mathematical place/generator set is unordered at the fleet boundary.  Sorting by its
    # canonical content makes plan identity independent of discovery enumeration order.
    return tuple(sorted(identified, key=lambda item: item[0]))


@dataclass(frozen=True, slots=True)
class _ArithmeticShardOperation:
    """One fixed data-only arithmetic plan/run/reduce implementation."""

    name: str
    include_generators: bool

    def _shards(self, task: TaskSpec) -> tuple[ShardSpec, ...]:
        if task.operation != self.name:
            raise ArithmeticShardError(
                f"operation {self.name!r} cannot execute foreign task {task.operation!r}"
            )
        places = _unique_axis(_sequence_parameter(task, "places"), "places")
        generators: tuple[tuple[str, JSONValue], ...]
        if self.include_generators:
            generators = _unique_axis(
                _sequence_parameter(task, "generators"),
                "generators",
            )
        else:
            generators = (("", None),)

        shards: list[ShardSpec] = []
        for place_ordinal, (place_id, place) in enumerate(places):
            for generator_ordinal, (generator_id, generator) in enumerate(generators):
                key = f"place-{place_ordinal:08d}-{place_id}"
                payload: dict[str, Any] = {
                    "operation": self.name,
                    "place": place,
                    "place_id": f"sha256:{canonical_sha256(place)}",
                    "place_ordinal": place_ordinal,
                }
                if self.include_generators:
                    key += f"-generator-{generator_ordinal:08d}-{generator_id}"
                    payload.update(
                        {
                            "generator": generator,
                            "generator_id": f"sha256:{canonical_sha256(generator)}",
                            "generator_ordinal": generator_ordinal,
                        }
                    )
                shards.append(ShardSpec(task.task_hash, key, payload))
        return FleetPlan(task, shards).shards

    def plan(self, task: TaskSpec) -> FleetPlan:
        return FleetPlan(task, self._shards(task))

    def run(self, task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        expected = {candidate.key: candidate for candidate in self._shards(task)}
        canonical = expected.get(shard.key)
        if canonical is None:
            raise ArithmeticShardError(f"foreign arithmetic shard key: {shard.key!r}")
        if shard != canonical:
            raise ArithmeticShardError(
                f"arithmetic shard {shard.key!r} does not match its canonical plan payload"
            )
        parameters = task.parameters.to_dict()
        supplied_values = parameters.get("shard_values", {})
        if not isinstance(supplied_values, dict):
            raise ArithmeticShardError("shard_values must be a canonical object when supplied")
        value = supplied_values.get(shard.key)
        return {
            "operation": self.name,
            "ordinal": shard.ordinal,
            "payload": shard.payload.to_dict(),
            "shard_hash": shard.shard_hash,
            "shard_key": shard.key,
            "task_hash": task.task_hash,
            "value": value,
        }

    def _validated_partials(
        self,
        task: TaskSpec,
        partials: Sequence[JSONValue],
    ) -> tuple[dict[str, JSONValue], ...]:
        expected = self._shards(task)
        expected_keys = tuple(shard.key for shard in expected)
        if any(not isinstance(partial, dict) for partial in partials):
            raise ArithmeticShardError("every arithmetic partial must be a canonical object")
        typed = tuple(partial for partial in partials if isinstance(partial, dict))
        actual_keys = tuple(partial.get("shard_key") for partial in typed)
        if any(not isinstance(key, str) for key in actual_keys):
            raise ArithmeticShardError("every arithmetic partial must name its shard key")
        string_keys = tuple(str(key) for key in actual_keys)
        if len(string_keys) != len(set(string_keys)):
            raise ArithmeticShardError("arithmetic reduction contains duplicate shards")
        missing = tuple(key for key in expected_keys if key not in string_keys)
        foreign = tuple(key for key in string_keys if key not in expected_keys)
        if missing:
            raise ArithmeticShardError(
                "arithmetic reduction is missing shards: " + ", ".join(missing)
            )
        if foreign:
            raise ArithmeticShardError(
                "arithmetic reduction contains foreign shards: " + ", ".join(foreign)
            )
        if string_keys != expected_keys:
            raise ArithmeticShardError("arithmetic reduction shards are reordered")

        for partial, shard in zip(typed, expected, strict=True):
            required = {
                "operation",
                "ordinal",
                "payload",
                "shard_hash",
                "shard_key",
                "task_hash",
                "value",
            }
            if set(partial) != required:
                raise ArithmeticShardError(
                    f"arithmetic partial {shard.key!r} has missing or unknown fields"
                )
            if partial["operation"] != self.name:
                raise ArithmeticShardError(f"arithmetic partial {shard.key!r} is foreign")
            if partial["task_hash"] != task.task_hash:
                raise ArithmeticShardError(
                    f"arithmetic partial {shard.key!r} belongs to another task"
                )
            if partial["ordinal"] != shard.ordinal:
                raise ArithmeticShardError(
                    f"arithmetic partial {shard.key!r} has the wrong ordinal"
                )
            if partial["payload"] != shard.payload.to_dict():
                raise ArithmeticShardError(
                    f"arithmetic partial {shard.key!r} has a foreign payload"
                )
            if partial["shard_hash"] != shard.shard_hash:
                raise ArithmeticShardError(
                    f"arithmetic partial {shard.key!r} has a foreign shard hash"
                )
        return typed

    def reduce(self, task: TaskSpec, partials: Sequence[JSONValue]) -> dict[str, object]:
        validated = self._validated_partials(task, partials)
        return {
            "completeness": "CANDIDATE",
            "operation": self.name,
            "outcome": "UNKNOWN",
            "partials": list(validated),
            "task_hash": task.task_hash,
        }

    def verify(self, task: TaskSpec, result: JSONValue) -> bool:
        if not isinstance(result, Mapping):
            return False
        partials = result.get("partials")
        if not isinstance(partials, list):
            return False
        try:
            expected = normalize_json(self.reduce(task, partials))
        except (ArithmeticShardError, TypeError, ValueError):
            return False
        return result == expected


@dataclass(frozen=True, slots=True)
class _CertificateReplayOperation:
    """One fixed certificate task with an explicit verifier-trust boundary."""

    name: str
    pari: bool

    @property
    def stage(self) -> str:
        return "pari-discovery-certification" if self.pari else "portable-python-replay"

    def _validate_task(self, task: TaskSpec) -> VerificationCertificate:
        if task.operation != self.name:
            raise CertificateTaskError(
                f"operation {self.name!r} cannot execute foreign task {task.operation!r}"
            )
        certificate = _task_certificate(task)
        if task.input_refs != (certificate.certificate_id,):
            raise CertificateTaskError("certificate task input reference was altered")
        if self.pari:
            expected = _pari_requirement(certificate)
            if task.backend != expected:
                raise CertificateTaskError(
                    "PARI certificate task backend/version/capability requirement was altered"
                )
        else:
            if certificate.verifier not in _PORTABLE_PYTHON_VERIFIERS:
                raise CertificateTaskError(
                    "portable Python task cannot replay this certificate verifier"
                )
            if (
                task.backend.name != "python"
                or "certificate-verification" not in task.backend.capabilities
            ):
                raise CertificateTaskError(
                    "portable certificate replay requires Python certificate-verification"
                )
        return certificate

    def plan(self, task: TaskSpec) -> FleetPlan:
        certificate = self._validate_task(task)
        shard = ShardSpec(
            task.task_hash,
            f"certificate-{certificate.certificate_id.split(':', 1)[-1]}",
            {
                "certificate_id": certificate.certificate_id,
                "certificate_verifier": certificate.verifier,
                "stage": self.stage,
            },
        )
        return FleetPlan(task, (shard,))

    def _replay(
        self,
        certificate: VerificationCertificate,
    ) -> tuple[bool | None, dict[str, JSONValue] | None, str | None]:
        try:
            verified = verify_certificate(certificate)
        except (
            CertificateError,
            CertificateVerificationError,
            OSError,
            RuntimeError,
            UnknownVerifierError,
            ValueError,
        ) as failure:
            return (
                None if self.pari else False,
                None,
                f"{type(failure).__name__}: {failure}",
            )
        normalized = normalize_json(verified.to_canonical())
        if not isinstance(normalized, dict):  # pragma: no cover - report API invariant
            raise CertificateTaskError("certificate verifier returned a non-object report")
        return True, normalized, None

    def run(self, task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        certificate = self._validate_task(task)
        plan = self.plan(task)
        expected = plan.shards[0]
        if shard != expected:
            raise CertificateTaskError("certificate replay shard is foreign or altered")
        valid, report, error = self._replay(certificate)
        if self.pari:
            outcome = "VERIFIED" if valid is True else "UNKNOWN"
        else:
            outcome = "VALID" if valid is True else "INVALID"
        return {
            "certificate_id": certificate.certificate_id,
            "certificate_verifier": certificate.verifier,
            "error": error,
            "operation": self.name,
            "outcome": outcome,
            "report": report,
            "shard_hash": shard.shard_hash,
            "shard_key": shard.key,
            "stage": self.stage,
            "task_hash": task.task_hash,
            "valid": valid,
        }

    def _partial(
        self,
        task: TaskSpec,
        partials: Sequence[JSONValue],
    ) -> dict[str, JSONValue]:
        certificate = self._validate_task(task)
        shard = self.plan(task).shards[0]
        if len(partials) != 1 or not isinstance(partials[0], dict):
            raise CertificateTaskError("certificate task requires exactly one object partial")
        partial = partials[0]
        expected_fields = {
            "certificate_id",
            "certificate_verifier",
            "error",
            "operation",
            "outcome",
            "report",
            "shard_hash",
            "shard_key",
            "stage",
            "task_hash",
            "valid",
        }
        if set(partial) != expected_fields:
            raise CertificateTaskError("certificate partial has missing or foreign fields")
        if (
            partial["certificate_id"] != certificate.certificate_id
            or partial["certificate_verifier"] != certificate.verifier
            or partial["operation"] != self.name
            or partial["stage"] != self.stage
            or partial["task_hash"] != task.task_hash
            or partial["shard_hash"] != shard.shard_hash
            or partial["shard_key"] != shard.key
        ):
            raise CertificateTaskError("certificate partial belongs to another task or shard")
        valid = partial["valid"]
        outcome = partial["outcome"]
        report = partial["report"]
        error = partial["error"]
        if self.pari:
            if (valid, outcome) not in ((True, "VERIFIED"), (None, "UNKNOWN")):
                raise CertificateTaskError("PARI partial has an invalid non-closing outcome")
        elif (valid, outcome) not in ((True, "VALID"), (False, "INVALID")):
            raise CertificateTaskError("Python replay partial has an invalid validity outcome")
        if valid is True:
            if not isinstance(report, dict) or error is not None:
                raise CertificateTaskError("valid certificate partial lacks its verifier report")
            if (
                report.get("valid") is not True
                or report.get("certificate_id") != certificate.certificate_id
                or report.get("verifier") != certificate.verifier
            ):
                raise CertificateTaskError("certificate report is foreign to the task")
        elif report is not None or not isinstance(error, str) or not error:
            raise CertificateTaskError("failed certificate partial lacks its error boundary")
        if not self.pari:
            expected_valid, expected_report, _ = self._replay(certificate)
            if valid is not expected_valid or report != expected_report:
                raise CertificateTaskError(
                    "portable certificate partial disagrees with independent Python replay"
                )
        return partial

    def reduce(self, task: TaskSpec, partials: Sequence[JSONValue]) -> dict[str, object]:
        partial = self._partial(task, partials)
        return {
            "certificate_id": partial["certificate_id"],
            "certificate_valid": partial["valid"],
            "mathematical_closure": False,
            "operation": self.name,
            "outcome": partial["outcome"],
            "stage": self.stage,
            "task_hash": task.task_hash,
            "verification": partial["report"],
        }

    def verify(self, task: TaskSpec, result: JSONValue) -> bool:
        if not isinstance(result, Mapping):
            return False
        try:
            certificate = self._validate_task(task)
        except (CertificateTaskError, TypeError, ValueError):
            return False
        required = {
            "certificate_id",
            "certificate_valid",
            "mathematical_closure",
            "operation",
            "outcome",
            "stage",
            "task_hash",
            "verification",
        }
        if set(result) != required:
            return False
        valid = result.get("certificate_valid")
        outcome = result.get("outcome")
        if self.pari:
            accepted = (valid, outcome) in ((True, "VERIFIED"), (None, "UNKNOWN"))
        else:
            accepted = (valid, outcome) in ((True, "VALID"), (False, "INVALID"))
            expected_valid, expected_report, _ = self._replay(certificate)
            accepted = bool(
                accepted
                and valid is expected_valid
                and result.get("verification") == expected_report
            )
        return bool(
            accepted
            and result.get("certificate_id") == certificate.certificate_id
            and result.get("mathematical_closure") is False
            and result.get("operation") == self.name
            and result.get("stage") == self.stage
            and result.get("task_hash") == task.task_hash
            and (
                (valid is True and isinstance(result.get("verification"), Mapping))
                or (valid is not True and result.get("verification") is None)
            )
        )


def _echo_run(task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
    return {
        "input_refs": list(task.input_refs),
        "parameters": task.parameters.to_dict(),
        "shard_key": shard.key,
        "task_hash": task.task_hash,
    }


def _echo_reduce(
    task: TaskSpec,
    partials: Sequence[JSONValue],
) -> dict[str, object]:
    return {
        "operation": task.operation,
        "outcome": "UNKNOWN",
        "partials": list(partials),
        "task_hash": task.task_hash,
    }


def _echo_verify(task: TaskSpec, result: JSONValue) -> bool:
    return (
        isinstance(result, dict)
        and result.get("operation") == LOCAL_ECHO_OPERATION
        and result.get("outcome") == "UNKNOWN"
        and result.get("task_hash") == task.task_hash
        and isinstance(result.get("partials"), list)
    )


def default_fleet_operation_registry() -> FleetOperationRegistry:
    """Return a fresh registry containing only audited built-in operations."""

    echo = FunctionalOperation(
        planner=lambda _task: ("all",),
        runner=_echo_run,
        reducer=_echo_reduce,
        verifier=_echo_verify,
    )
    local_h1 = _ArithmeticShardOperation(LOCAL_H1_MU2_OPERATION, False)
    localization = _ArithmeticShardOperation(LOCALIZE_SQUARECLASS_OPERATION, True)
    selmer = _ArithmeticShardOperation(SELMER_ASSEMBLE_OPERATION, True)
    pari_arithmetic = _CertificateReplayOperation(PARI_ARITHMETIC_OPERATION, True)
    python_replay = _CertificateReplayOperation(
        PYTHON_CERTIFICATE_REPLAY_OPERATION,
        False,
    )
    return FleetOperationRegistry(
        {
            LOCAL_ECHO_OPERATION: echo,
            LOCAL_H1_MU2_OPERATION: local_h1,
            LOCALIZE_SQUARECLASS_OPERATION: localization,
            PARI_ARITHMETIC_OPERATION: pari_arithmetic,
            PYTHON_CERTIFICATE_REPLAY_OPERATION: python_replay,
            SELMER_ASSEMBLE_OPERATION: selmer,
        }
    )


def automatic_local_worker_pool() -> WorkerPool:
    """Advertise conservative one-core logical slots for the local process.

    The executor currently runs one shard per Worker.  Advertising the host as
    one many-core Worker would therefore promise parallel capacity it cannot
    schedule.  Logical slots make default one-core work genuinely concurrent;
    a task requesting multiple cores fails capability matching rather than
    pretending one slot owns resources spanning the pool.
    """

    slot_count = max(1, os.cpu_count() or 1)
    backend = BackendStatus(
        name="python",
        available=True,
        capabilities=(
            "arithmetic-witness-replay",
            "canonical-json",
            "certificate-verification",
            "control-plane",
            "kummer-witness-replay",
            "local-execution",
            "selmer-witness-replay",
        ),
        version=platform.python_version(),
    )
    workers = (
        Worker(
            f"local-python-{slot:03d}",
            (backend,),
            resources=ResourceHint(cpu_cores=1),
            labels=FrozenMapping({"logical_slot": slot, "runtime": "automatic-local"}),
        )
        for slot in range(slot_count)
    )
    return WorkerPool(workers)
