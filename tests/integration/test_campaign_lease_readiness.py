from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread

import pytest

from arbogast.backends import BackendStatus
from arbogast.bootstrap import (
    CertifiedBlocked,
    CertifiedReady,
    DispatchReadinessError,
    DispatchReadinessReceipt,
    EnvironmentSnapshot,
    ObligationStatus,
    ReadinessProfile,
    ReadinessVerdict,
    certify_campaign_readiness,
    readiness_receipt,
)
from arbogast.bootstrap.readiness import _certificate_for
from arbogast.campaign import (
    AttemptRecord,
    Campaign,
    CampaignInvariantError,
    CampaignPlan,
    CampaignReadinessError,
    OperationalState,
    Strategy,
    TargetSpec,
)
from arbogast.cert import VerifierRegistry, certificate_from_dict, content_address
from arbogast.fleet import (
    ArtifactRef,
    FleetOperationRegistry,
    FunctionalOperation,
    LeaseRecord,
    LeaseState,
    ResourceHint,
    RetryPolicy,
    ShardSpec,
    TaskSpec,
    Worker,
    WorkerPool,
    WorkerPoolExecutor,
)
from arbogast.formats import (
    JSONValue,
    canonical_bytes,
    canonical_dumps,
    canonical_sha256,
)

_OPERATION = "tests.campaign.lease-readiness"
_RUN_CALLS: list[str] = []
_CLOCK_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_BLOCKING_ROOT = ""


def _test_clock() -> datetime:
    return _CLOCK_NOW


def _plan(_task: TaskSpec) -> tuple[str, ...]:
    return ("only",)


def _plan_two(_task: TaskSpec) -> tuple[str, ...]:
    return ("first", "second")


def _run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
    _RUN_CALLS.append(shard.shard_hash)
    return {"shard": shard.key}


def _blocking_run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
    root = Path(_BLOCKING_ROOT)
    (root / f"started-{shard.key}").write_text("started", encoding="utf-8")
    deadline = time.monotonic() + 10
    while not (root / "release").exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test release marker was not created")
        time.sleep(0.01)
    return {"shard": shard.key}


def _reduce(task: TaskSpec, partials: Sequence[JSONValue]) -> dict[str, object]:
    return {
        "operation": task.operation,
        "outcome": "UNKNOWN",
        "partials": list(partials),
        "task_hash": task.task_hash,
    }


@dataclass(frozen=True)
class _Case:
    campaign: Campaign
    plan: CampaignPlan
    executor: WorkerPoolExecutor
    environment: EnvironmentSnapshot


def _ready_case(
    tmp_path: Path,
    *,
    two_shards: bool = False,
    runner: Callable[[TaskSpec, ShardSpec], object] = _run,
    worker_count: int = 1,
    clock: Callable[[], datetime] | None = None,
    lease_seconds: int = 300,
) -> _Case:
    planner = _plan_two if two_shards else _plan
    operation = FunctionalOperation(planner=planner, runner=runner, reducer=_reduce)
    operations = FleetOperationRegistry({_OPERATION: operation})
    workers = tuple(
        Worker(
            f"lease-worker-{index}",
            (BackendStatus("python", True, ()),),
            resources=ResourceHint(cpu_cores=1),
        )
        for index in range(worker_count)
    )
    executor = WorkerPoolExecutor(
        WorkerPool(workers),
        tmp_path / "fleet",
        operation_registry=operations,
        max_workers=worker_count,
        retry_policy=RetryPolicy(lease_seconds=lease_seconds),
        clock=clock,
    )
    verifiers = VerifierRegistry()
    campaign = Campaign(
        "lease-readiness-integration",
        objective="authorize one exact operation only after live lease refresh",
        targets=(TargetSpec("case:lease-readiness"),),
        strategies=(
            Strategy(
                "lease-guarded",
                _OPERATION,
                "exercise the post-acquisition readiness boundary",
            ),
        ),
        executor=executor,
        operation_registry=operations,
        verifier_registry=verifiers,
        strict_readiness=True,
    )
    plan = campaign.recommend(limit=1)
    environment = EnvironmentSnapshot.capture(
        project_root=Path.cwd(),
        capabilities=campaign.capabilities or (),
    )
    profile = ReadinessProfile.from_plan(
        campaign,
        plan,
        operations,
        verifiers,
        executor,
    )
    result = certify_campaign_readiness(
        environment=environment,
        profile=profile,
    )
    assert isinstance(result, CertifiedReady), result.to_dict()
    campaign.record_environment_claim(result.claim())
    campaign.activate_readiness(result.certificate, environment=environment)
    return _Case(campaign, plan, executor, environment)


def _store_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _rebind_receipt_field(
    receipt: DispatchReadinessReceipt,
    field: str,
    value: object,
) -> dict[str, object]:
    document = receipt.to_dict()
    document[field] = value
    return _rehash_receipt_document(document, changed_payload_field=field)


def _rehash_receipt_document(
    document: dict[str, object],
    *,
    changed_payload_field: str | None = None,
) -> dict[str, object]:
    probe = document["artifact_probe"]
    assert isinstance(probe, dict)
    payload = probe["payload"]
    assert isinstance(payload, dict)
    if changed_payload_field is not None and changed_payload_field in payload:
        payload[changed_payload_field] = document[changed_payload_field]
    encoded = canonical_bytes(payload)
    probe["reference"] = ArtifactRef(
        hashlib.sha256(encoded).hexdigest(),
        len(encoded),
        "application/json",
    ).to_dict()
    probe["read_bytes_hex"] = encoded.hex()
    document["receipt_id"] = content_address(
        {key: item for key, item in document.items() if key != "receipt_id"}
    )
    return document


def _rehash_ledger_events(events: list[object]) -> None:
    previous: str | None = None
    for event in events:
        assert isinstance(event, dict)
        event["previous_event_id"] = previous
        event["event_id"] = "sha256:" + canonical_sha256(
            {key: item for key, item in event.items() if key != "event_id"}
        )
        previous = event["event_id"]
        assert isinstance(previous, str)


def _coherently_rehash_campaign_receipt(
    case: _Case,
    field: str,
    value: object,
) -> dict[str, object]:
    document = deepcopy(case.campaign.to_dict())
    ledger = document["ledger"]
    assert isinstance(ledger, dict)
    events = ledger["events"]
    assert isinstance(events, list)
    changed = False
    for event in events:
        assert isinstance(event, dict)
        if changed or event["kind"] != "ATTEMPT_RECORDED":
            continue
        payload = event["payload"]
        assert isinstance(payload, dict)
        attempt = payload["attempt"]
        assert isinstance(attempt, dict)
        raw_receipt = attempt.get("dispatch_readiness_receipt")
        if not isinstance(raw_receipt, dict):
            continue
        receipt = DispatchReadinessReceipt.from_dict(raw_receipt)
        forged = _rebind_receipt_field(receipt, field, value)
        attempt["dispatch_readiness_receipt"] = forged
        attempt["dispatch_readiness_receipt_id"] = forged["receipt_id"]
        if field == "readiness_claim_id":
            attempt["readiness_claim_id"] = value
        attempt["record_id"] = "sha256:" + canonical_sha256(
            {key: item for key, item in attempt.items() if key != "record_id"}
        )
        changed = True
    assert changed
    _rehash_ledger_events(events)
    return document


def test_ready_worker_lease_refreshes_before_operation_execution(tmp_path: Path) -> None:
    _RUN_CALLS.clear()
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task

    observation = case.campaign.dispatch(task)

    assert len(_RUN_CALLS) == 1
    assert observation.outcome.value == "UNKNOWN"
    assert case.campaign.ledger.observations == (observation,)
    leases = case.executor.lease_records(task_hash=task.task.task_hash)
    assert len(leases) == 1
    assert leases[0].state is LeaseState.COMPLETED
    assert case.executor.status(task_hash=task.task.task_hash).active_count == 0
    attempts = case.campaign.ledger.attempts_for_task(task.campaign_task_id)
    receipt_attempts = tuple(
        attempt for attempt in attempts if attempt.dispatch_readiness_receipt is not None
    )
    assert receipt_attempts
    assert any(attempt.state is OperationalState.RUNNING for attempt in receipt_attempts)
    terminal = attempts[-1]
    assert terminal.dispatch_readiness_receipt_id is not None
    assert terminal.dispatch_readiness_receipt is not None
    receipt = DispatchReadinessReceipt.from_dict(terminal.dispatch_readiness_receipt.to_dict())
    assert receipt.verify()
    assert receipt.receipt_id == terminal.dispatch_readiness_receipt_id
    assert receipt.campaign_task_id == task.campaign_task_id
    assert receipt.lease.state is LeaseState.ACTIVE
    assert receipt.lease.id == leases[0].id
    assert receipt.worker["id"] == leases[0].worker_id
    artifact_probe = receipt.artifact_probe
    probe_reference = artifact_probe["reference"]
    assert isinstance(probe_reference, Mapping)
    artifact_reference = ArtifactRef.from_dict(probe_reference)
    assert case.executor.store.verify(artifact_reference)
    assert case.executor.store.get_json(artifact_reference) == artifact_probe["payload"]
    assert artifact_probe["write_outcome"] == "completed"
    assert artifact_probe["read_outcome"] == "completed"
    assert bytes.fromhex(artifact_probe["read_bytes_hex"]) == canonical_bytes(
        artifact_probe["payload"]
    )
    assert artifact_probe["payload"]["lease_id"] == receipt.lease.id
    assert artifact_probe["payload"]["profile_id"] == receipt.profile_id
    readiness = case.campaign.status().readiness
    historical = readiness["lease_validity"]
    assert isinstance(historical, Mapping)
    assert historical["receipt_id"] == receipt.receipt_id
    assert historical["task_id"] == task.campaign_task_id
    assert historical["receipt_valid"] is True
    assert historical["valid"] is False
    assert historical["current_valid"] is False
    assert historical["historical"] is True
    assert historical["status"] == "historical-terminal"
    assert historical["lease_state_at_check"] == "active"
    assert historical["lease_state_current"] == "completed"
    assert len(readiness["lease_validities"]) == 1
    assert readiness["current_lease_validities"] == ()
    replayed = Campaign.from_dict(
        case.campaign.to_dict(),
        executor=case.executor,
        operation_registry=case.campaign.operation_registry,
        verifier_registry=case.campaign.verifier_registry,
    )
    assert replayed.campaign_id == case.campaign.campaign_id


def test_dispatch_receipt_strict_replay_rejects_tamper(tmp_path: Path) -> None:
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task
    case.campaign.dispatch(task)
    attempt = case.campaign.ledger.attempts_for_task(task.campaign_task_id)[-1]
    assert attempt.dispatch_readiness_receipt is not None
    document = attempt.dispatch_readiness_receipt.to_dict()

    tampered_profile = deepcopy(document)
    tampered_profile["profile_id"] = "sha256:" + "f" * 64
    tampered_worker = deepcopy(document)
    worker = tampered_worker["worker"]
    assert isinstance(worker, dict)
    worker["id"] = "foreign-worker"
    tampered_lease = deepcopy(document)
    lease = tampered_lease["lease"]
    assert isinstance(lease, dict)
    lease["state"] = "COMPLETED"
    tampered_check = deepcopy(document)
    tampered_check["checked_at"] = "1970-01-01T00:00:00.000000Z"
    forged_lease_id = deepcopy(document)
    forged_lease = forged_lease_id["lease"]
    assert isinstance(forged_lease, dict)
    forged_lease["id"] = "lease:" + "0" * 64
    forged_dispatch_id = deepcopy(document)
    forged_dispatch_id["dispatch_id"] = "dispatch:" + "0" * 64
    tampered_probe = deepcopy(document)
    probe = tampered_probe["artifact_probe"]
    assert isinstance(probe, dict)
    payload = probe["payload"]
    assert isinstance(payload, dict)
    payload["worker_id"] = "foreign-worker"
    tampered_probe["receipt_id"] = content_address(
        {key: value for key, value in tampered_probe.items() if key != "receipt_id"}
    )
    tampered_read_outcome = deepcopy(document)
    outcome_probe = tampered_read_outcome["artifact_probe"]
    assert isinstance(outcome_probe, dict)
    outcome_probe["read_outcome"] = "unknown"
    tampered_read_outcome["receipt_id"] = content_address(
        {key: value for key, value in tampered_read_outcome.items() if key != "receipt_id"}
    )
    noncanonical_lease_time = deepcopy(document)
    raw_lease = noncanonical_lease_time["lease"]
    assert isinstance(raw_lease, dict)
    acquired = raw_lease["acquired_at"]
    assert isinstance(acquired, str) and acquired.endswith("Z")
    raw_lease["acquired_at"] = acquired[:-1] + "+00:00"
    raw_lease["id"] = LeaseRecord.canonical_id(
        task_hash=raw_lease["task_hash"],
        shard_hash=raw_lease["shard_hash"],
        worker_id=raw_lease["worker_id"],
        attempt=raw_lease["attempt"],
        acquired_at=raw_lease["acquired_at"],
        expires_at=raw_lease["expires_at"],
    )
    time_probe = noncanonical_lease_time["artifact_probe"]
    assert isinstance(time_probe, dict)
    time_payload = time_probe["payload"]
    assert isinstance(time_payload, dict)
    time_payload["lease_id"] = raw_lease["id"]
    time_encoded = canonical_bytes(time_payload)
    time_probe["reference"] = ArtifactRef(
        hashlib.sha256(time_encoded).hexdigest(),
        len(time_encoded),
        "application/json",
    ).to_dict()
    time_probe["read_bytes_hex"] = time_encoded.hex()
    noncanonical_lease_time["receipt_id"] = content_address(
        {key: value for key, value in noncanonical_lease_time.items() if key != "receipt_id"}
    )

    for tampered in (
        tampered_profile,
        tampered_worker,
        tampered_lease,
        tampered_check,
        forged_lease_id,
        forged_dispatch_id,
        tampered_probe,
        tampered_read_outcome,
        noncanonical_lease_time,
    ):
        with pytest.raises(DispatchReadinessError):
            DispatchReadinessReceipt.from_dict(tampered)

    mismatched_attempt = attempt.to_dict()
    mismatched_attempt["readiness_claim_id"] = "bootstrap.readiness.foreign.ready"
    with pytest.raises(CampaignInvariantError, match="readiness claim"):
        AttemptRecord.from_dict(mismatched_attempt)

    id_only_attempt = attempt.to_dict()
    del id_only_attempt["dispatch_readiness_receipt"]
    with pytest.raises(CampaignInvariantError, match="present together"):
        AttemptRecord.from_dict(id_only_attempt)


def test_post_acquisition_staleness_releases_lease_without_result_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _RUN_CALLS.clear()
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task
    store_root = case.executor.store.root
    before_files = _store_files(store_root)
    before_observations = case.campaign.ledger.observations
    original = case.campaign._validate_readiness_activation
    calls = 0

    def delayed_staleness(*args: object, **kwargs: object) -> object:
        nonlocal calls
        report = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            return report
        return replace(
            report,
            valid=False,
            blockers=("simulated runtime drift after lease acquisition",),
        )

    monkeypatch.setattr(
        case.campaign,
        "_validate_readiness_activation",
        delayed_staleness,
    )

    with pytest.raises(CampaignReadinessError) as raised:
        case.campaign.dispatch(task)

    assert raised.value.code == "READINESS_LEASE_STALE"
    assert "simulated runtime drift" in " ".join(raised.value.blockers)
    assert calls >= 2
    assert _RUN_CALLS == []
    assert case.campaign.ledger.observations == before_observations == ()
    assert _store_files(store_root) == before_files
    leases = case.executor.lease_records(task_hash=task.task.task_hash)
    assert len(leases) == 1
    assert leases[0].state is LeaseState.RELEASED
    assert case.executor.status(task_hash=task.task.task_hash).active_count == 0
    attempts = case.campaign.ledger.attempts_for_task(task.campaign_task_id)
    assert attempts[-1].state is OperationalState.UNKNOWN
    assert attempts[-1].detail == ("dispatch readiness was refused before operation execution")
    assert all(attempt.dispatch_readiness_receipt_id is None for attempt in attempts)
    assert all(attempt.dispatch_readiness_receipt is None for attempt in attempts)
    assert case.campaign.status().readiness["lease_validity"] is None


def test_lease_expiring_during_refresh_never_starts_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global _CLOCK_NOW

    _RUN_CALLS.clear()
    _CLOCK_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    case = _ready_case(
        tmp_path,
        clock=_test_clock,
        lease_seconds=1,
    )
    task = case.plan.recommendations[0].task
    original = case.campaign._validate_readiness_activation
    calls = 0

    def expire_during_refresh(*args: object, **kwargs: object) -> object:
        global _CLOCK_NOW
        nonlocal calls

        report = original(*args, **kwargs)
        calls += 1
        if calls >= 2:
            _CLOCK_NOW += timedelta(seconds=2)
        return report

    monkeypatch.setattr(
        case.campaign,
        "_validate_readiness_activation",
        expire_during_refresh,
    )
    before_observations = case.campaign.ledger.observations

    with pytest.raises(CampaignReadinessError) as raised:
        case.campaign.dispatch(task)

    assert raised.value.code == "READINESS_LEASE_STALE"
    assert _RUN_CALLS == []
    assert case.campaign.ledger.observations == before_observations == ()
    attempts = case.campaign.ledger.attempts_for_task(task.campaign_task_id)
    assert all(item.dispatch_readiness_receipt_id is None for item in attempts)
    leases = case.executor.lease_records(task_hash=task.task.task_hash)
    assert len(leases) == 1
    assert leases[0].state in {LeaseState.EXPIRED, LeaseState.RELEASED}


def test_cache_recheck_expiry_precedes_final_launch_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global _CLOCK_NOW

    _RUN_CALLS.clear()
    _CLOCK_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    case = _ready_case(tmp_path, clock=_test_clock, lease_seconds=1)
    task = case.plan.recommendations[0].task
    original_resolve = case.executor.store.resolve
    resolve_calls = 0

    def expire_on_second_resolve(*args: object, **kwargs: object) -> object:
        global _CLOCK_NOW
        nonlocal resolve_calls

        result = original_resolve(*args, **kwargs)
        resolve_calls += 1
        if resolve_calls == 2:
            _CLOCK_NOW += timedelta(seconds=2)
        return result

    monkeypatch.setattr(case.executor.store, "resolve", expire_on_second_resolve)

    with pytest.raises(CampaignReadinessError) as raised:
        case.campaign.dispatch(task)

    assert raised.value.code == "READINESS_LEASE_STALE"
    assert resolve_calls >= 2
    assert _RUN_CALLS == []
    assert case.campaign.ledger.observations == ()
    attempts = case.campaign.ledger.attempts_for_task(task.campaign_task_id)
    assert all(item.dispatch_readiness_receipt_id is None for item in attempts)
    leases = case.executor.lease_records(task_hash=task.task.task_hash)
    assert len(leases) == 1
    assert leases[0].state in {LeaseState.EXPIRED, LeaseState.RELEASED}


def test_read_only_sink_refuses_before_operation_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _RUN_CALLS.clear()
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task
    activation = case.campaign.active_readiness_certificate
    assert activation is not None
    report = case.campaign._validate_readiness_activation(activation, case.plan)
    monkeypatch.setattr(
        case.campaign,
        "_validate_readiness_activation",
        lambda *_args, **_kwargs: report,
    )

    def read_only(_value: object) -> ArtifactRef:
        raise PermissionError("read-only sink")

    monkeypatch.setattr(case.executor.store, "put_json", read_only)
    before_observations = case.campaign.ledger.observations

    with pytest.raises(CampaignReadinessError) as raised:
        case.campaign.dispatch(task)

    assert raised.value.code == "READINESS_ARTIFACT_PROBE_FAILED"
    assert _RUN_CALLS == []
    assert case.campaign.ledger.observations == before_observations == ()
    attempts = case.campaign.ledger.attempts_for_task(task.campaign_task_id)
    assert all(item.dispatch_readiness_receipt_id is None for item in attempts)
    leases = case.executor.lease_records(task_hash=task.task.task_hash)
    assert len(leases) == 1
    assert leases[0].state is LeaseState.RELEASED


def test_multi_shard_guard_is_per_lease_not_a_dispatch_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed sibling shard remains durable when a later lease is refused."""

    _RUN_CALLS.clear()
    case = _ready_case(tmp_path, two_shards=True)
    task = case.plan.recommendations[0].task
    before_files = _store_files(case.executor.store.root)
    original = case.campaign._validate_readiness_activation
    calls = 0

    def stale_second_lease(*args: object, **kwargs: object) -> object:
        nonlocal calls
        report = original(*args, **kwargs)
        calls += 1
        if calls < 3:
            return report
        return replace(
            report,
            valid=False,
            blockers=("simulated drift before the second shard lease",),
        )

    monkeypatch.setattr(
        case.campaign,
        "_validate_readiness_activation",
        stale_second_lease,
    )

    with pytest.raises(CampaignReadinessError, match="second shard lease"):
        case.campaign.dispatch(task)

    assert calls >= 3
    assert len(_RUN_CALLS) == 1
    assert case.campaign.ledger.observations == ()
    leases = case.executor.lease_records(task_hash=task.task.task_hash)
    assert tuple(item.state for item in leases) == (
        LeaseState.COMPLETED,
        LeaseState.RELEASED,
    )
    assert _store_files(case.executor.store.root) != before_files
    attempts = case.campaign.ledger.attempts_for_task(task.campaign_task_id)
    receipts = tuple(
        item.dispatch_readiness_receipt_id
        for item in attempts
        if item.dispatch_readiness_receipt_id is not None
    )
    assert receipts
    assert attempts[-1].state is OperationalState.UNKNOWN
    status = case.campaign.status().readiness["lease_validity"]
    assert isinstance(status, Mapping)
    assert status["status"] == "historical-terminal"
    assert status["lease_state_current"] == "completed"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("environment_id", "sha256:" + "0" * 64),
        ("profile_id", "sha256:" + "0" * 64),
        ("readiness_receipt_id", "sha256:" + "0" * 64),
        ("readiness_certificate_id", "sha256:" + "0" * 64),
        ("readiness_claim_id", "bootstrap.readiness.foreign.ready"),
        ("campaign_id", "sha256:" + "0" * 64),
        ("campaign_plan_id", "sha256:" + "0" * 64),
        ("operation_registry_id", "sha256:" + "0" * 64),
        ("verifier_registry_id", "sha256:" + "0" * 64),
        ("executor_id", "sha256:" + "0" * 64),
        ("artifact_store_id", "sha256:" + "0" * 64),
    ),
)
def test_offline_campaign_replay_rejects_coherently_rehashed_authority(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task
    case.campaign.dispatch(task)
    document = _coherently_rehash_campaign_receipt(case, field, value)

    with pytest.raises(CampaignInvariantError, match="dispatch readiness receipt"):
        Campaign.from_dict(
            document,
            executor=case.executor,
            operation_registry=case.campaign.operation_registry,
            verifier_registry=case.campaign.verifier_registry,
        )


def test_dispatch_receipt_rejects_noncanonical_certified_ready_claim(
    tmp_path: Path,
) -> None:
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task
    case.campaign.dispatch(task)
    attempt = case.campaign.ledger.attempts_for_task(task.campaign_task_id)[-1]
    assert attempt.dispatch_readiness_receipt is not None
    receipt = DispatchReadinessReceipt.from_dict(attempt.dispatch_readiness_receipt.to_dict())
    document = receipt.to_dict()
    claim = document["readiness_claim"]
    assert isinstance(claim, dict)
    claim["source"] = ["forged.readiness.source"]
    _rehash_receipt_document(document)

    with pytest.raises(DispatchReadinessError, match="canonical certified-ready claim"):
        DispatchReadinessReceipt.from_dict(document)


def test_offline_campaign_replay_rejects_valid_blocked_readiness_theorem(
    tmp_path: Path,
) -> None:
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task
    case.campaign.dispatch(task)
    document = deepcopy(case.campaign.to_dict())
    ledger = document["ledger"]
    claims = document["claims"]
    assert isinstance(ledger, dict)
    assert isinstance(claims, dict)
    events = ledger["events"]
    graph_claims = claims["claims"]
    assert isinstance(events, list)
    assert isinstance(graph_claims, list)

    changed = False
    original_claim_id: str | None = None
    blocked_claim_document: dict[str, object] | None = None
    for event in events:
        assert isinstance(event, dict)
        if changed or event["kind"] != "ATTEMPT_RECORDED":
            continue
        payload = event["payload"]
        assert isinstance(payload, dict)
        attempt = payload["attempt"]
        assert isinstance(attempt, dict)
        receipt_document = attempt.get("dispatch_readiness_receipt")
        if not isinstance(receipt_document, dict):
            continue
        source = DispatchReadinessReceipt.from_dict(receipt_document)
        decoded = certificate_from_dict(source.readiness_certificate.to_dict())
        theorem = readiness_receipt(decoded)
        blocked_obligations = list(theorem.obligations)
        blocked_index = next(
            index for index, obligation in enumerate(blocked_obligations) if obligation.required
        )
        blocked_obligations[blocked_index] = replace(
            blocked_obligations[blocked_index],
            status=ObligationStatus.UNSATISFIED,
            detail="coherently forged blocked dispatch authority",
        )
        blocked_theorem = replace(
            theorem,
            verdict=ReadinessVerdict.BLOCKED,
            obligations=tuple(blocked_obligations),
        )
        blocked_certificate = _certificate_for(blocked_theorem)
        blocked_claim = CertifiedBlocked(
            blocked_theorem.environment,
            blocked_theorem.profile,
            blocked_theorem,
            blocked_certificate,
        ).claim()
        original_claim_id = source.readiness_claim_id
        blocked_claim_document = blocked_claim.to_dict()
        receipt_document["readiness_receipt_id"] = blocked_theorem.receipt_id
        receipt_document["readiness_certificate_id"] = blocked_certificate.certificate_id
        receipt_document["readiness_certificate"] = blocked_certificate.to_dict()
        receipt_document["readiness_claim_id"] = blocked_claim.id
        receipt_document["readiness_claim"] = blocked_claim_document
        _rehash_receipt_document(
            receipt_document,
            changed_payload_field="readiness_certificate_id",
        )
        attempt["dispatch_readiness_receipt_id"] = receipt_document["receipt_id"]
        attempt["readiness_claim_id"] = blocked_claim.id
        attempt["record_id"] = "sha256:" + canonical_sha256(
            {key: item for key, item in attempt.items() if key != "record_id"}
        )
        changed = True
    assert changed
    assert original_claim_id is not None
    assert blocked_claim_document is not None
    for index, claim in enumerate(graph_claims):
        assert isinstance(claim, dict)
        if claim["id"] == original_claim_id:
            graph_claims[index] = blocked_claim_document
            break
    else:
        raise AssertionError("original readiness claim is absent from campaign graph")
    _rehash_ledger_events(events)

    with pytest.raises(
        CampaignInvariantError,
        match="dispatch readiness receipt failed strict replay",
    ):
        Campaign.from_dict(
            document,
            executor=case.executor,
            operation_registry=case.campaign.operation_registry,
            verifier_registry=case.campaign.verifier_registry,
        )


def test_offline_campaign_replay_requires_embedded_claim_in_claim_graph(
    tmp_path: Path,
) -> None:
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task
    case.campaign.dispatch(task)
    document = deepcopy(case.campaign.to_dict())
    claims = document["claims"]
    assert isinstance(claims, dict)
    claims["claims"] = []

    with pytest.raises(CampaignInvariantError, match="campaign/task/plan"):
        Campaign.from_dict(
            document,
            executor=case.executor,
            operation_registry=case.campaign.operation_registry,
            verifier_registry=case.campaign.verifier_registry,
        )


def test_attempt_receipt_cross_binds_target_attempt_and_conditional_worker(
    tmp_path: Path,
) -> None:
    case = _ready_case(tmp_path)
    task = case.plan.recommendations[0].task
    case.campaign.dispatch(task)
    source = case.campaign.ledger.attempts_for_task(task.campaign_task_id)[-1]
    assert source.dispatch_readiness_receipt is not None
    receipt = DispatchReadinessReceipt.from_dict(source.dispatch_readiness_receipt.to_dict())

    with pytest.raises(CampaignInvariantError, match="campaign target"):
        AttemptRecord(
            "sha256:" + "0" * 64,
            task.campaign_task_id,
            source.attempt,
            OperationalState.RUNNING,
            readiness_claim_id=source.readiness_claim_id,
            dispatch_readiness_receipt_id=receipt.receipt_id,
            dispatch_readiness_receipt=receipt.to_dict(),
        )
    with pytest.raises(CampaignInvariantError, match="campaign attempt"):
        AttemptRecord(
            task.target_id,
            task.campaign_task_id,
            source.attempt + 1,
            OperationalState.RUNNING,
            readiness_claim_id=source.readiness_claim_id,
            dispatch_readiness_receipt_id=receipt.receipt_id,
            dispatch_readiness_receipt=receipt.to_dict(),
        )
    with pytest.raises(CampaignInvariantError, match="lease worker"):
        AttemptRecord(
            task.target_id,
            task.campaign_task_id,
            source.attempt,
            OperationalState.RUNNING,
            worker_id="foreign-worker",
            readiness_claim_id=source.readiness_claim_id,
            dispatch_readiness_receipt_id=receipt.receipt_id,
            dispatch_readiness_receipt=receipt.to_dict(),
        )


def test_status_exposes_every_concurrent_current_lease_authorization(
    tmp_path: Path,
) -> None:
    global _BLOCKING_ROOT

    blocking_root = tmp_path / "blocking"
    blocking_root.mkdir()
    _BLOCKING_ROOT = str(blocking_root)
    case = _ready_case(
        tmp_path,
        two_shards=True,
        runner=_blocking_run,
        worker_count=2,
    )
    task = case.plan.recommendations[0].task
    result: list[object] = []

    def dispatch() -> None:
        try:
            result.append(case.campaign.dispatch(task))
        except BaseException as error:
            result.append(error)

    thread = Thread(target=dispatch, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not all((blocking_root / f"started-{key}").exists() for key in ("first", "second")):
        if time.monotonic() >= deadline:
            pytest.fail("both shard operations did not reach the launch boundary")
        time.sleep(0.01)

    readiness = case.campaign.status().readiness
    current = readiness["current_lease_validities"]
    assert isinstance(current, tuple)
    assert len(current) == 2
    assert {item["status"] for item in current} == {"current-active"}
    assert len({item["lease_id"] for item in current}) == 2
    assert len(readiness["lease_validities"]) == 2
    stale_lease_id = current[0]["lease_id"]
    assert isinstance(stale_lease_id, str)
    with case.executor._condition:
        case.executor._active_dispatch_by_lease.pop(stale_lease_id)
    after_context_loss = case.campaign.status().readiness
    assert len(after_context_loss["current_lease_validities"]) == 1
    stale = next(
        item
        for item in after_context_loss["lease_validities"]
        if item["lease_id"] == stale_lease_id
    )
    assert stale["status"] == "historical-stale-runtime"

    (blocking_root / "release").write_text("release", encoding="utf-8")
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(result) == 1
    assert not isinstance(result[0], BaseException)
    terminal = case.campaign.status().readiness
    assert terminal["current_lease_validities"] == ()
    assert len(terminal["lease_validities"]) == 2
    assert {item["status"] for item in terminal["lease_validities"]} == {"historical-terminal"}


def test_legacy_attempt_bytes_and_identity_omit_dispatch_provenance() -> None:
    attempt = AttemptRecord(
        "sha256:" + "1" * 64,
        "sha256:" + "2" * 64,
        1,
        OperationalState.RUNNING,
        worker_id="local-gap",
        progress_completed=2,
        progress_total=10,
        resources={"cpu_seconds": 3},
    )
    expected = (
        '{"attempt":1,"attempt_id":"sha256:'
        'b32e12b8f7669a33b886e5f3095c1f98559079be4b3ca6aae40a9c047a462672",'
        '"checkpoint_ref":null,"detail":null,"progress_completed":2,'
        '"progress_total":10,"record_id":"sha256:'
        '155117460e5c9da8f69f685f8da8dac91c134dd473e819cd5206abbfdbc0a8ce",'
        '"resources":{"cpu_seconds":3},"schema":"arbogast.campaign.attempt.v1",'
        '"spent":{},"state":"RUNNING","target_id":"sha256:'
        '1111111111111111111111111111111111111111111111111111111111111111",'
        '"task_id":"sha256:'
        '2222222222222222222222222222222222222222222222222222222222222222",'
        '"worker_id":"local-gap"}'
    )

    document = attempt.to_dict()
    assert "dispatch_readiness_receipt_id" not in document
    assert "dispatch_readiness_receipt" not in document
    assert canonical_dumps(document) == expected
    assert attempt.record_id == (
        "sha256:155117460e5c9da8f69f685f8da8dac91c134dd473e819cd5206abbfdbc0a8ce"
    )
    assert AttemptRecord.from_dict(document) == attempt
