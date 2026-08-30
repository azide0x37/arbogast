from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

import arbogast.fleet.builtins as fleet_builtins
from arbogast.backends.pari_certificate import create_pari_verification_certificate
from arbogast.cert import (
    CertificateVerificationError,
    DiscoveryReceipt,
    VerificationCertificate,
    VerificationReport,
    content_address,
)
from arbogast.fleet import (
    ARITHMETIC_FLEET_OPERATIONS,
    CERTIFICATE_FLEET_OPERATIONS,
    LOCAL_H1_MU2_OPERATION,
    LOCALIZE_SQUARECLASS_OPERATION,
    PARI_ARITHMETIC_OPERATION,
    PYTHON_CERTIFICATE_REPLAY_OPERATION,
    SELMER_ASSEMBLE_OPERATION,
    ArithmeticShardError,
    CertificateTaskError,
    FleetOperation,
    FleetPlan,
    LocalExecutor,
    NoEligibleWorkerError,
    TaskSpec,
    automatic_local_worker_pool,
    default_fleet_operation_registry,
    plan_pari_arithmetic_task,
    plan_python_certificate_replay_task,
)
from arbogast.formats import JSONValue
from arbogast.galois import FiniteGaloisQuotient, NumberField, Unsupported, galois_module
from arbogast.linalg import PrimeField
from arbogast.rep import PermutationGroup, Representation


def _task(operation: str) -> TaskSpec:
    parameters: dict[str, object] = {
        "places": [
            {"kind": "finite", "place_id": "p2"},
            {"kind": "infinite", "place_id": "real"},
        ]
    }
    if operation != LOCAL_H1_MU2_OPERATION:
        parameters["generators"] = [
            {"coordinates": [1, 0]},
            {"coordinates": [0, 1]},
        ]
    return TaskSpec(operation, parameters=parameters)


def _partials(operation: FleetOperation, task: TaskSpec) -> tuple[dict[str, JSONValue], ...]:
    plan = operation.plan(task)
    assert isinstance(plan, FleetPlan)
    return tuple(cast(dict[str, JSONValue], operation.run(task, shard)) for shard in plan.shards)


def _pari_certificate() -> VerificationCertificate:
    polynomial = [[0, 1], [1, 1]]
    identity = {
        "defining_polynomial": polynomial,
        "type": "arbogast.pari.raw-number-field/v1",
    }
    field_id = content_address(identity)
    return create_pari_verification_certificate(
        "field_invariants",
        replay={
            "arguments": {},
            "field": {
                "defining_polynomial": polynomial,
                "field_id": field_id,
                "identity": identity,
                "integral_basis": None,
            },
        },
        expected_payload={
            "degree": 1,
            "discriminant": 1,
            "field_id": field_id,
            "index": 1,
            "integral_basis": [[[1, 1]]],
            "signature": [1, 0],
        },
        backend_version="2.17.4",
        request_id="fleet-pari-test",
        deterministic_seed=1,
        proof_mode="unconditional",
        limits={
            "certification_timeout_seconds": "60",
            "cpu_limit_seconds": 60,
            "memory_limit_bytes": 1_073_741_824,
            "output_limit_bytes": 2_000_000,
            "pari_stack_bytes": 268_435_456,
            "timeout_seconds": "15",
        },
    )


def _unsupported_certificate() -> VerificationCertificate:
    return Unsupported(
        "local_h1",
        "automatic local arithmetic is limited to p=2",
        requested={"prime": 3},
        supported=("prime=2",),
    ).certificate


def _operational_pari_policy_certificate() -> VerificationCertificate:
    receipt = DiscoveryReceipt.create(
        "backends.pari.field_invariants",
        backend="pari",
        backend_version="2.17.4",
    )
    return VerificationCertificate.create(
        "pari:operational:policy-test",
        "arbogast.backends.pari.operational.v1",
        witness={
            "operation": "field_invariants",
            "receipt": receipt.to_dict(),
        },
    )


def test_trusted_arithmetic_operations_are_fixed_and_verify_only_candidate_assemblies(
    tmp_path: Path,
) -> None:
    registry = default_fleet_operation_registry()
    assert set(ARITHMETIC_FLEET_OPERATIONS) <= set(registry.names())

    for name in ARITHMETIC_FLEET_OPERATIONS:
        task = _task(name)
        executor = LocalExecutor(tmp_path / name.replace(".", "-"), operation_registry=registry)
        run = executor.execute_registered(task, verify=True)
        result = executor.result_value(run)
        assert isinstance(result, dict)
        assert result["operation"] == name
        assert result["completeness"] == "CANDIDATE"
        assert result["outcome"] == "UNKNOWN"


@pytest.mark.parametrize(
    "name",
    (
        LOCAL_H1_MU2_OPERATION,
        LOCALIZE_SQUARECLASS_OPERATION,
        SELMER_ASSEMBLE_OPERATION,
    ),
)
def test_arithmetic_reducers_reject_missing_duplicate_foreign_and_reordered_shards(
    name: str,
) -> None:
    registry = default_fleet_operation_registry()
    operation = registry.resolve(name)
    task = _task(name)
    partials = _partials(operation, task)
    assert len(partials) >= 2

    with pytest.raises(ArithmeticShardError, match="missing"):
        operation.reduce(task, partials[:-1])
    with pytest.raises(ArithmeticShardError, match="duplicate"):
        operation.reduce(task, (*partials[:-1], partials[0]))
    with pytest.raises(ArithmeticShardError, match="reordered"):
        operation.reduce(task, tuple(reversed(partials)))

    foreign = dict(partials[0])
    foreign["task_hash"] = "f" * 64
    with pytest.raises(ArithmeticShardError, match="another task"):
        operation.reduce(task, (foreign, *partials[1:]))


def test_arithmetic_plan_rejects_duplicate_place_and_generator_identities() -> None:
    registry = default_fleet_operation_registry()
    local_h1 = registry.resolve(LOCAL_H1_MU2_OPERATION)
    duplicate_places = TaskSpec(
        LOCAL_H1_MU2_OPERATION,
        parameters={"places": [{"id": "p"}, {"id": "p"}]},
    )
    with pytest.raises(ArithmeticShardError, match="duplicate canonical identities"):
        local_h1.plan(duplicate_places)

    localization = registry.resolve(LOCALIZE_SQUARECLASS_OPERATION)
    duplicate_generators = TaskSpec(
        LOCALIZE_SQUARECLASS_OPERATION,
        parameters={"places": [{"id": "p"}], "generators": [[1], [1]]},
    )
    with pytest.raises(ArithmeticShardError, match="duplicate canonical identities"):
        localization.plan(duplicate_generators)


def test_arithmetic_reducer_rejects_noncanonical_partial_shape() -> None:
    registry = default_fleet_operation_registry()
    operation = registry.resolve(LOCAL_H1_MU2_OPERATION)
    task = _task(LOCAL_H1_MU2_OPERATION)
    partials: Sequence[JSONValue] = _partials(operation, task)
    malformed = dict(cast(dict[str, JSONValue], partials[0]))
    malformed["unexpected"] = True
    with pytest.raises(ArithmeticShardError, match="missing or unknown"):
        operation.reduce(task, (malformed, *partials[1:]))


def test_pari_and_python_certificate_tasks_are_distinct_and_capability_routed() -> None:
    pari = plan_pari_arithmetic_task(_pari_certificate())
    portable = plan_python_certificate_replay_task(_unsupported_certificate())

    assert pari.operation == PARI_ARITHMETIC_OPERATION
    assert pari.backend.name == "pari"
    assert pari.backend.version == "2.17.4"
    assert pari.backend.capabilities == ("field-invariants",)
    assert portable.operation == PYTHON_CERTIFICATE_REPLAY_OPERATION
    assert portable.backend.name == "python"
    assert portable.backend.capabilities == ("certificate-verification",)
    with pytest.raises(CertificateTaskError, match="distinct PARI"):
        plan_python_certificate_replay_task(_pari_certificate())
    operational = plan_pari_arithmetic_task(_operational_pari_policy_certificate())
    assert operational.operation == PARI_ARITHMETIC_OPERATION
    assert operational.backend.name == "pari"
    assert operational.backend.version == "2.17.4"
    with pytest.raises(CertificateTaskError, match="distinct PARI"):
        plan_python_certificate_replay_task(_operational_pari_policy_certificate())

    local_pool = automatic_local_worker_pool()
    assert local_pool.select(portable).id.startswith("local-python-")
    with pytest.raises(NoEligibleWorkerError, match="backend 'pari'"):
        local_pool.select(pari)


def test_python_certificate_task_allowlists_quotient_presentation_and_module_replay(
    tmp_path: Path,
) -> None:
    group = PermutationGroup.trivial(1)
    quotient = FiniteGaloisQuotient(
        NumberField.rationals(),
        group,
        label="portable-candidate-quotient",
    )
    module = galois_module(
        quotient,
        Representation.trivial(group, PrimeField(2)),
        name="portable-trivial-module",
    )
    executor = LocalExecutor(
        tmp_path / "galois-portable",
        operation_registry=default_fleet_operation_registry(),
    )

    for certificate in (quotient.certificate, module.certificate):
        task = plan_python_certificate_replay_task(certificate)
        result = executor.result_value(executor.execute_registered(task, verify=True))
        assert isinstance(result, dict)
        assert result["certificate_valid"] is True
        assert result["outcome"] == "VALID"
        assert result["mathematical_closure"] is False


def test_python_certificate_task_decides_portable_validity_without_claim_closure(
    tmp_path: Path,
) -> None:
    registry = default_fleet_operation_registry()
    assert set(CERTIFICATE_FLEET_OPERATIONS) <= set(registry.names())
    executor = LocalExecutor(tmp_path / "portable", operation_registry=registry)

    valid_task = plan_python_certificate_replay_task(_unsupported_certificate())
    valid_run = executor.execute_registered(valid_task, verify=True)
    valid = executor.result_value(valid_run)
    assert isinstance(valid, dict)
    assert valid["certificate_valid"] is True
    assert valid["outcome"] == "VALID"
    assert valid["mathematical_closure"] is False

    payload = _unsupported_certificate().to_dict()
    payload.pop("certificate_id")
    witness = payload["witness"]
    assert isinstance(witness, dict)
    unsupported = witness["unsupported"]
    assert isinstance(unsupported, dict)
    unsupported["reason"] = "forged broader boundary"
    forged = VerificationCertificate.from_dict(payload)
    invalid_task = plan_python_certificate_replay_task(forged)
    invalid_run = executor.execute_registered(invalid_task, verify=True)
    invalid = executor.result_value(invalid_run)
    assert isinstance(invalid, dict)
    assert invalid["certificate_valid"] is False
    assert invalid["outcome"] == "INVALID"
    assert invalid["verification"] is None
    assert invalid["mathematical_closure"] is False


def test_pari_failure_is_unknown_and_nonclosing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unavailable(_certificate: VerificationCertificate) -> VerificationReport:
        raise CertificateVerificationError("pinned GP worker unavailable")

    monkeypatch.setattr(fleet_builtins, "verify_certificate", unavailable)
    registry = default_fleet_operation_registry()
    executor = LocalExecutor(tmp_path / "pari", operation_registry=registry)
    task = plan_pari_arithmetic_task(_pari_certificate())
    run = executor.execute_registered(task, verify=True)
    result = executor.result_value(run)
    assert isinstance(result, dict)
    assert result["certificate_valid"] is None
    assert result["outcome"] == "UNKNOWN"
    assert result["mathematical_closure"] is False


def test_certificate_task_reducer_rejects_missing_and_foreign_partials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate = _pari_certificate()

    def accepted(item: VerificationCertificate) -> VerificationReport:
        return VerificationReport(
            valid=True,
            verifier=item.verifier,
            certificate_id=item.certificate_id,
            checks=("stubbed pinned replay",),
        )

    monkeypatch.setattr(fleet_builtins, "verify_certificate", accepted)
    registry = default_fleet_operation_registry()
    operation = registry.resolve(PARI_ARITHMETIC_OPERATION)
    task = plan_pari_arithmetic_task(certificate)
    plan = operation.plan(task)
    assert isinstance(plan, FleetPlan)
    partial = cast(dict[str, JSONValue], operation.run(task, plan.shards[0]))
    with pytest.raises(CertificateTaskError, match="exactly one"):
        operation.reduce(task, ())
    foreign = dict(partial)
    foreign["certificate_id"] = "sha256:" + "0" * 64
    with pytest.raises(CertificateTaskError, match="another task"):
        operation.reduce(task, (foreign,))


def test_portable_reducer_independently_replays_instead_of_trusting_worker_report() -> None:
    registry = default_fleet_operation_registry()
    operation = registry.resolve(PYTHON_CERTIFICATE_REPLAY_OPERATION)
    task = plan_python_certificate_replay_task(_unsupported_certificate())
    plan = operation.plan(task)
    assert isinstance(plan, FleetPlan)
    partial = cast(dict[str, JSONValue], operation.run(task, plan.shards[0]))
    forged = dict(partial)
    report = forged["report"]
    assert isinstance(report, dict)
    forged["report"] = {**report, "checks": ["worker asserted success without replay"]}

    with pytest.raises(CertificateTaskError, match="independent Python replay"):
        operation.reduce(task, (forged,))
