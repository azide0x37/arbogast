from __future__ import annotations

import pytest

from arbogast.campaign.errors import CampaignInvariantError, CampaignSerializationError
from arbogast.campaign.events import Observation, OperationalState, Outcome
from arbogast.campaign.ledger import TargetLedger
from arbogast.campaign.planner import CampaignTask
from arbogast.campaign.results import (
    AttemptRecord,
    CandidateEvidence,
    CandidateRecord,
    CandidateScope,
    ExecutionTelemetry,
)
from arbogast.campaign.targets import TargetSpec
from arbogast.fleet import TaskSpec


def _ref(character: str) -> str:
    return "sha256:" + character * 64


def test_candidate_identity_deduplicates_declared_mathematical_equivalence() -> None:
    first = CandidateRecord(
        _ref("1"),
        _ref("2"),
        _ref("3"),
        "polynomial:canonical-x3-x-1",
        _ref("4"),
        canonicalizer="test.polynomial-canonicalizer/v1",
        invariants={"degree": 3, "signature": [1, 1]},
        evidence=CandidateEvidence.EXACT,
        quality=7,
        source_refs=("parent-field:12T1",),
    )
    verified = CandidateRecord(
        _ref("1"),
        _ref("5"),
        _ref("6"),
        "polynomial:canonical-x3-x-1",
        _ref("7"),
        canonicalizer="test.polynomial-canonicalizer/v1",
        invariants={"degree": 3, "signature": [1, 1]},
        evidence=CandidateEvidence.VERIFIED,
        quality=7,
        certificate_ref=_ref("8"),
    )

    assert first.candidate_id == verified.candidate_id
    assert first.record_id != verified.record_id
    assert verified.better_than(first)
    assert CandidateRecord.from_dict(verified.to_dict()) == verified


def test_candidate_and_attempt_replay_reject_bool_ids_and_tamper() -> None:
    candidate = CandidateRecord(
        _ref("1"),
        _ref("2"),
        _ref("3"),
        "candidate:one",
        _ref("4"),
        canonicalizer="test.identity/v1",
    )
    document = candidate.to_dict()
    document["quality"] = True
    with pytest.raises(CampaignSerializationError, match="quality"):
        CandidateRecord.from_dict(document)

    attempt = AttemptRecord(
        _ref("1"),
        _ref("2"),
        1,
        OperationalState.RUNNING,
        worker_id="local-gap",
        progress_completed=2,
        progress_total=10,
        resources={"cpu_seconds": 3},
    )
    replayed = AttemptRecord.from_dict(attempt.to_dict())
    assert replayed == attempt
    assert replayed.live

    tampered = attempt.to_dict()
    tampered["worker_id"] = "different-worker"
    with pytest.raises(CampaignSerializationError, match="record_id"):
        AttemptRecord.from_dict(tampered)


def test_verified_candidate_requires_certificate_and_progress_is_exact() -> None:
    with pytest.raises(CampaignInvariantError, match="certificate"):
        CandidateRecord(
            _ref("1"),
            _ref("2"),
            _ref("3"),
            "candidate:unproved",
            _ref("4"),
            canonicalizer="test.identity/v1",
            evidence=CandidateEvidence.VERIFIED,
        )


def test_execution_telemetry_and_attempts_distinguish_absent_from_zero() -> None:
    telemetry = ExecutionTelemetry(
        progress_completed=0,
        progress_total=0,
        resources={"cpu_seconds": 0},
        spent={"credits": 0},
    )
    assert ExecutionTelemetry.from_dict(telemetry.to_dict()) == telemetry

    absent = AttemptRecord(
        _ref("1"),
        _ref("2"),
        1,
        OperationalState.UNKNOWN,
    )
    measured_zero = AttemptRecord(
        _ref("1"),
        _ref("2"),
        1,
        OperationalState.UNKNOWN,
        progress_completed=0,
        progress_total=0,
        resources={"cpu_seconds": 0},
        spent={"credits": 0},
    )
    assert absent.progress_completed is None
    assert measured_zero.progress_completed == 0
    assert absent.record_id != measured_zero.record_id
    assert AttemptRecord.from_dict(absent.to_dict()) == absent
    assert AttemptRecord.from_dict(measured_zero.to_dict()) == measured_zero

    with pytest.raises(CampaignInvariantError, match="at least one"):
        ExecutionTelemetry()
    with pytest.raises(CampaignInvariantError, match="non-negative"):
        ExecutionTelemetry(resources={"cpu_seconds": True})
    with pytest.raises(CampaignSerializationError, match="invalid"):
        ExecutionTelemetry.from_dict(
            {
                **telemetry.to_dict(),
                "progress_completed": 2,
                "progress_total": 1,
            }
        )
    with pytest.raises(CampaignInvariantError, match="progress_total"):
        AttemptRecord(
            _ref("1"),
            _ref("2"),
            1,
            OperationalState.RUNNING,
            progress_completed=5,
            progress_total=4,
        )


def test_ledger_projects_candidates_best_known_and_live_attempts() -> None:
    target = TargetSpec("case:candidates")
    task = CampaignTask(TaskSpec("test.search"), target, "search", "find exact objects")
    ledger = TargetLedger((target,))
    ledger.plan_task(task)
    running = AttemptRecord(
        target.target_id,
        task.campaign_task_id,
        1,
        OperationalState.RUNNING,
        worker_id="worker-gap",
    )
    ledger.record_attempt(running)
    assert ledger.live_attempts == (running,)

    result_ref = _ref("4")
    observation = Observation(
        target.target_id,
        task.campaign_task_id,
        Outcome.UNKNOWN,
        result_ref=result_ref,
        details={"candidate_count": 2},
    )
    ledger.record(observation)
    first = CandidateRecord(
        target.target_id,
        task.campaign_task_id,
        observation.observation_id,
        "field:canonical-one",
        result_ref,
        canonicalizer="test.field-canonicalizer/v1",
        invariants={"discriminant": 101},
        evidence=CandidateEvidence.EXACT,
        quality=4,
    )
    improved = CandidateRecord(
        target.target_id,
        task.campaign_task_id,
        observation.observation_id,
        "field:canonical-two",
        result_ref,
        canonicalizer="test.field-canonicalizer/v1",
        invariants={"discriminant": 89},
        evidence=CandidateEvidence.EXACT,
        quality=8,
    )
    other_metric = CandidateRecord(
        target.target_id,
        task.campaign_task_id,
        observation.observation_id,
        "field:canonical-three",
        result_ref,
        canonicalizer="test.field-canonicalizer/v1",
        evidence=CandidateEvidence.EXACT,
        quality=12,
        quality_metric="conductor",
    )
    ledger.record_candidate(first)
    ledger.record_candidate(improved)
    ledger.record_candidate(other_metric)

    finished = AttemptRecord(
        target.target_id,
        task.campaign_task_id,
        1,
        OperationalState.UNKNOWN,
        worker_id="worker-gap",
        progress_completed=2,
        progress_total=2,
    )
    ledger.record_attempt(finished)
    assert not ledger.live_attempts
    with pytest.raises(CampaignInvariantError, match="explicit quality_metric"):
        ledger.best_known(target)
    assert ledger.best_known(target, quality_metric="campaign-quality") == improved
    assert dict(ledger.best_known_by_metric(target)) == {
        "campaign-quality": improved,
        "conductor": other_metric,
    }
    replayed = TargetLedger.from_dict(ledger.to_dict())
    assert replayed.best_known(target, quality_metric="campaign-quality") == improved


def test_candidate_equivalence_scope_and_quality_metrics_are_explicit() -> None:
    first = CandidateRecord(
        _ref("1"),
        _ref("2"),
        _ref("3"),
        "field:global-normal-form",
        _ref("4"),
        canonicalizer="test.field-canonicalizer/v2",
        equivalence_scope=CandidateScope.GLOBAL,
        quality=5,
        quality_metric="small-discriminant",
    )
    sibling = CandidateRecord(
        _ref("5"),
        _ref("6"),
        _ref("7"),
        "field:global-normal-form",
        _ref("8"),
        canonicalizer="test.field-canonicalizer/v2",
        equivalence_scope=CandidateScope.GLOBAL,
        quality=9,
        quality_metric="small-discriminant",
    )
    target_scoped = CandidateRecord(
        _ref("5"),
        _ref("6"),
        _ref("7"),
        "field:global-normal-form",
        _ref("8"),
        canonicalizer="test.field-canonicalizer/v2",
        equivalence_scope=CandidateScope.TARGET,
        quality=9,
        quality_metric="small-discriminant",
    )
    incomparable = CandidateRecord(
        _ref("1"),
        _ref("2"),
        _ref("3"),
        "field:another",
        _ref("4"),
        canonicalizer="test.field-canonicalizer/v2",
        equivalence_scope=CandidateScope.GLOBAL,
        quality=100,
        quality_metric="conductor",
    )

    assert first.candidate_id == sibling.candidate_id
    assert first.candidate_id != target_scoped.candidate_id
    with pytest.raises(CampaignInvariantError, match="different quality metrics"):
        first.better_than(incomparable)
