from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from arbogast.backends import BackendStatus
from arbogast.campaign import (
    AttemptRecord,
    Campaign,
    CampaignError,
    CampaignInvariantError,
    CampaignTask,
    CandidateEvidence,
    CapabilityUnavailableError,
    DerivationRule,
    Observation,
    OperationalState,
    Outcome,
    RecommendationAction,
    Strategy,
    TargetSpec,
    TaskProvenance,
    closure_certificate,
    register_campaign_claim_verifier,
)
from arbogast.cert import VerificationCertificate, VerifierRegistry, default_verifiers
from arbogast.claims import Claim, ClaimGraph
from arbogast.fleet import (
    BackendRequirement,
    BudgetExhaustedError,
    CheckpointManifest,
    CheckpointRef,
    FleetOperationRegistry,
    FunctionalOperation,
    LocalExecutor,
    PreemptedError,
    ResourceHint,
    RetryPolicy,
    ShardSpec,
    TaskSpec,
    Worker,
    WorkerPool,
    WorkerPoolExecutor,
)
from arbogast.formats import JSONValue, canonical_dumps


def _found_certificate_verifier(certificate: VerificationCertificate) -> bool:
    witness = certificate.witness.to_dict()
    task_hash = witness.get("task_hash")
    return (
        certificate.subject.endswith(":FOUND")
        and "witness" in witness
        and isinstance(task_hash, str)
        and len(task_hash) == 64
    )


default_verifiers.register(
    "test.campaign-found",
    VerificationCertificate,
    _found_certificate_verifier,
)


def _one_shard(task: TaskSpec) -> tuple[str, ...]:
    del task
    return ("all",)


def _found_operation() -> FunctionalOperation[dict[str, object], dict[str, object]]:
    def run(task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        return {"shard": shard.key, "target": task.parameters["target"]}

    def reduce(
        task: TaskSpec,
        partials: Sequence[JSONValue],
    ) -> dict[str, object]:
        target_id = task.parameters["target_id"]
        assert isinstance(target_id, str)
        certificate = closure_certificate(
            target_id,
            Outcome.FOUND,
            "test.campaign-found",
            task_hash=task.task_hash,
            witness={"witness": partials[0]},
            checks=("finite witness checked",),
        )
        return {
            "certificate": certificate.to_dict(),
            "outcome": "FOUND",
            "witness": partials[0],
        }

    return FunctionalOperation(
        planner=_one_shard,
        runner=run,
        reducer=reduce,
        verifier=lambda _task, result: (
            isinstance(result, dict) and result.get("outcome") == "FOUND"
        ),
    )


def test_verified_success_derives_sibling_task_with_provenance(tmp_path: Path) -> None:
    initial = TargetSpec("field:parent", {"degree": 12})
    sibling = TargetSpec("field:sibling", {"degree": 24})
    discovery = Strategy(
        "relative-extension",
        "test.find-field",
        "construct a field from the known parent",
        verify_results=True,
    )
    sibling_strategy = Strategy(
        "sibling-action",
        "test.classify-sibling",
        "classify another transitive action using the known subfield",
    )

    def derive_sibling(
        observation: Observation,
        _ledger: object,
    ) -> tuple[CampaignTask, ...]:
        assert observation.outcome is Outcome.FOUND
        return (sibling_strategy.build_task(sibling),)

    rule = DerivationRule("sibling-actions", derive_sibling)
    campaign = Campaign(
        "derivation-demo",
        objective="Construct and propagate exact fields",
        targets=(initial,),
        strategies=(discovery,),
        derivations=(rule,),
        executor=LocalExecutor(tmp_path / "fleet"),
        operations={"test.find-field": _found_operation()},
    )

    observation = campaign.dispatch()

    assert observation.outcome is Outcome.FOUND
    assert campaign.ledger.status(initial).closed
    derived = [task for task in campaign.tasks if task.target_id == sibling.target_id]
    assert len(derived) == 1
    sibling_task = derived[0]
    assert observation.result_ref in sibling_task.task.input_refs
    assert observation.certificate_ref is not None
    assert observation.certificate_ref.certificate_id in sibling_task.task.input_refs
    provenance = sibling_task.task.parameters["campaign_provenance"]
    assert isinstance(provenance, object)
    assert sibling_task.derivation == "sibling-actions"
    claim_candidate = campaign.export_claim_candidates()[0]
    assert claim_candidate["execution_receipt_ref"] == observation.result_ref
    assert claim_candidate["evidence_result_ref"] is None
    assert claim_candidate["result_ref_is_evidence"] is False


def test_run_replans_through_derivation_chain_without_duplicate_loop(tmp_path: Path) -> None:
    initial = TargetSpec("chain:initial", importance=2)
    sibling = TargetSpec("chain:sibling", importance=2)
    initial_strategy = Strategy(
        "initial-search",
        "test.chain-initial",
        "resolve the initial finite case",
    )
    sibling_strategy = Strategy(
        "sibling-search",
        "test.chain-sibling",
        "use the verified initial witness",
        usefulness=5,
    )

    def derive_sibling(
        _observation: Observation,
        _ledger: object,
    ) -> tuple[CampaignTask, ...]:
        return (sibling_strategy.build_task(sibling),)

    campaign = Campaign(
        "chain-demo",
        objective="Continue justified follow-up work",
        targets=(initial,),
        strategies=(initial_strategy,),
        derivations=(DerivationRule("derive-sibling", derive_sibling),),
        executor=LocalExecutor(tmp_path / "fleet"),
        operations={
            "test.chain-initial": _found_operation(),
            "test.chain-sibling": _found_operation(),
        },
    )

    observations = campaign.run()

    assert len(observations) == 2
    assert all(observation.outcome is Outcome.FOUND for observation in observations)
    assert campaign.ledger.status(initial).closed
    assert campaign.ledger.status(sibling).closed
    assert len(campaign.recommend()) == 0


def test_sink_failure_cannot_suppress_derivation_and_observe_is_idempotent(
    tmp_path: Path,
) -> None:
    initial = TargetSpec("sink-failure:initial")
    sibling = TargetSpec("sink-failure:sibling")
    strategy = Strategy("search", "test.sink-failure", "resolve exact case")
    sibling_strategy = Strategy("sibling", "test.sibling", "derive sibling work")

    class FailingSink:
        def write(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("sink unavailable")

    derivation_calls = 0

    def derive_sibling(
        _observation: Observation,
        _ledger: object,
    ) -> tuple[CampaignTask, ...]:
        nonlocal derivation_calls
        derivation_calls += 1
        return (sibling_strategy.build_task(sibling),)

    rule = DerivationRule("sibling", derive_sibling)
    campaign = Campaign(
        "sink-failure-demo",
        objective="Keep mathematical state authoritative",
        targets=(initial,),
        strategies=(strategy,),
        derivations=(rule,),
        executor=LocalExecutor(tmp_path / "fleet"),
        operations={"test.sink-failure": _found_operation()},
        sinks=(FailingSink(),),
    )

    observation = campaign.dispatch()
    event_count = len(campaign.ledger.events)
    task_count = len(campaign.tasks)
    campaign.observe(observation)

    assert campaign.ledger.status(initial).closed
    assert any(task.target_id == sibling.target_id for task in campaign.tasks)
    assert len(campaign.tasks) == task_count
    assert len(campaign.ledger.events) == event_count
    assert derivation_calls == 1
    assert campaign.sink_errors


@pytest.mark.parametrize(
    ("interruption", "expected"),
    [
        ("preempted", Outcome.PREEMPTED),
        ("budget", Outcome.BUDGET_EXHAUSTED),
    ],
)
def test_fleet_interruptions_preserve_outcome_and_checkpoint(
    tmp_path: Path,
    interruption: str,
    expected: Outcome,
) -> None:
    target = TargetSpec(f"case:{interruption}")
    strategy = Strategy("search", f"test.{interruption}", "resume exact work")
    executor = LocalExecutor(tmp_path / interruption)

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        artifact = executor.store.put_json({"checkpoint": interruption})
        checkpoint = CheckpointRef(
            artifact=artifact,
            shard_hash=shard.shard_hash,
            sequence=1,
            created_at="2026-08-28T00:00:00.000000Z",
        )
        if interruption == "preempted":
            raise PreemptedError("worker reclaimed", checkpoint=checkpoint)
        raise BudgetExhaustedError("budget reached", checkpoint=checkpoint)

    operation = FunctionalOperation(
        planner=_one_shard,
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )
    campaign = Campaign(
        f"{interruption}-demo",
        objective="Preserve operational interruption state",
        targets=(target,),
        strategies=(strategy,),
        executor=executor,
        operations={strategy.operation: operation},
    )

    observation = campaign.dispatch()

    assert observation.outcome is expected
    assert observation.operational_state.value == expected.value
    assert observation.checkpoint_ref is not None
    assert campaign.ledger.status(target).open
    plan = campaign.recommend()
    assert not plan.recommendations
    suspended = next(
        item for item in plan.advisories if item.action is RecommendationAction.SUSPEND
    )
    assert "cannot replay typed checkpoints" in suspended.reason
    assert suspended.task.checkpoint_ref == observation.checkpoint_ref
    assert suspended.task.checkpoint_custody_id is not None
    assert suspended.task.task.task_hash == campaign.tasks[0].task.task_hash
    assert observation.checkpoint_ref not in suspended.task.task.input_refs
    with pytest.raises(CampaignError, match="cannot replay typed checkpoints"):
        campaign.dispatch(suspended.task)


def test_successive_checkpoints_replace_active_resume_state_and_replay(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:successive-checkpoints")
    strategy = Strategy("search", "test.successive", "resume successive checkpoints")
    executor = WorkerPoolExecutor(
        WorkerPool((Worker("resume-worker", (BackendStatus("python", True, ()),)),)),
        tmp_path / "fleet",
        retry_policy=RetryPolicy(max_attempts=1),
    )
    calls = 0

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        nonlocal calls
        calls += 1
        # A later sequence may legitimately checkpoint identical state bytes.
        # Resume identity therefore cannot collapse to the artifact URI.
        artifact = executor.store.put_json({"checkpoint": "same-bytes"})
        checkpoint = CheckpointRef(
            artifact=artifact,
            shard_hash=shard.shard_hash,
            sequence=calls,
            created_at=f"2026-08-28T00:00:0{calls}.000000Z",
        )
        raise PreemptedError(f"preemption {calls}", checkpoint=checkpoint)

    operation = FunctionalOperation(
        planner=_one_shard,
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
        resumer=lambda task, shard, _checkpoint: run(task, shard),
    )
    campaign = Campaign(
        "successive-checkpoint-demo",
        objective="Advance resumable state without provenance conflicts",
        targets=(target,),
        strategies=(strategy,),
        executor=executor,
        operations={strategy.operation: operation},
    )

    first = campaign.dispatch()
    first_resume = campaign.recommend().recommendations[0]
    second = campaign.dispatch(first_resume)
    second_resume = campaign.recommend().recommendations[0]

    assert first.checkpoint_ref is not None
    assert second.checkpoint_ref is not None
    assert first.checkpoint_ref == second.checkpoint_ref
    assert second_resume.task.checkpoint_ref == second.checkpoint_ref
    assert first_resume.task.checkpoint_custody_id is not None
    assert second_resume.task.checkpoint_custody_id is not None
    assert first_resume.task.checkpoint_custody_id != second_resume.task.checkpoint_custody_id
    assert second_resume.task.task.task_hash == first_resume.task.task.task_hash
    assert second_resume.task.provenance.parameters.to_dict()["prior_checkpoint_refs"] == [
        first.checkpoint_ref
    ]

    artifact = tmp_path / "successive.json"
    campaign.save(artifact)
    restored = Campaign.load(
        artifact,
        executor=executor,
        operations={strategy.operation: operation},
    )
    assert restored.recommend().plan_id == campaign.recommend().plan_id


def test_external_observation_custody_and_evidence_references_are_strict() -> None:
    target = TargetSpec("case:external-custody")
    strategy = Strategy("search", "test.external", "verify external custody")
    campaign = Campaign(
        "external-custody-demo",
        objective="Reject forged lineage",
        targets=(target,),
        strategies=(strategy,),
    )
    task = campaign.recommend().recommendations[0].task
    certificate = closure_certificate(
        target.target_id,
        Outcome.FOUND,
        "test.campaign-found",
        task_hash=task.task.task_hash,
        witness={"witness": {"candidate": 1}},
        checks=("candidate verified",),
    )
    exact_input_refs = task.task.input_refs
    exact_parameters = task.provenance.parameters.to_dict()
    exact_source_refs = task.provenance.source_refs

    with pytest.raises(CampaignInvariantError, match="input_refs"):
        campaign.observe(
            Observation(
                target.target_id,
                task.campaign_task_id,
                Outcome.FOUND,
                certificate=certificate,
                input_refs=(*task.task.input_refs, "forged-input"),
                parameters=exact_parameters,
                source_refs=exact_source_refs,
            )
        )

    unbound_result = "sha256:" + "d" * 64
    with pytest.raises(CampaignInvariantError, match="result_ref"):
        campaign.observe(
            Observation(
                target.target_id,
                task.campaign_task_id,
                Outcome.FOUND,
                certificate=certificate,
                result_ref=unbound_result,
                input_refs=exact_input_refs,
                parameters=exact_parameters,
                source_refs=exact_source_refs,
            )
        )

    with pytest.raises(CampaignInvariantError, match="checkpoint_ref"):
        campaign.observe(
            Observation(
                target.target_id,
                task.campaign_task_id,
                Outcome.PREEMPTED,
                checkpoint_ref="sha256:" + "e" * 64,
                input_refs=exact_input_refs,
                parameters=exact_parameters,
                source_refs=exact_source_refs,
            )
        )

    bound_certificate = closure_certificate(
        target.target_id,
        Outcome.FOUND,
        "test.campaign-found",
        task_hash=task.task.task_hash,
        witness={"result_ref": unbound_result, "witness": {"candidate": 1}},
        checks=("candidate and result content verified",),
    )
    observation = Observation(
        target.target_id,
        task.campaign_task_id,
        Outcome.FOUND,
        certificate=bound_certificate,
        result_ref=unbound_result,
        input_refs=exact_input_refs,
        parameters=exact_parameters,
        source_refs=exact_source_refs,
    )
    campaign.observe(observation)
    exported = campaign.export_claim_candidates()[0]
    assert exported["evidence_result_ref"] == unbound_result
    assert exported["result_ref_is_evidence"] is True


def test_unverified_found_is_recorded_as_unknown_not_proof(tmp_path: Path) -> None:
    target = TargetSpec("case:unverified")
    strategy = Strategy("search", "test.unverified", "run discovery only")
    campaign = Campaign(
        "unverified-demo",
        objective="Do not confuse discovery with proof",
        targets=(target,),
        strategies=(strategy,),
        executor=LocalExecutor(tmp_path / "fleet"),
        operations={
            "test.unverified": FunctionalOperation(
                planner=_one_shard,
                runner=lambda _task, _shard: {"candidate": 1},
                reducer=lambda _task, partials: {
                    "outcome": "FOUND",
                    "witness": partials[0],
                },
            )
        },
    )

    observation = campaign.dispatch()

    assert observation.outcome is Outcome.UNKNOWN
    assert observation.details["rejected_unverified_outcome"] == "FOUND"
    assert campaign.ledger.status(target).open


def test_checkpoint_resume_survives_campaign_save_and_load(tmp_path: Path) -> None:
    target = TargetSpec("case:resume")
    strategy = Strategy("search", "test.preempt", "resume an exact enumeration")
    store = tmp_path / "fleet"
    workers = WorkerPool((Worker("resume-worker", (BackendStatus("python", True, ()),)),))
    executor = WorkerPoolExecutor(
        workers,
        store,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    def run_preempted(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        artifact = executor.store.put_json({"visited": 5})
        checkpoint = CheckpointRef(
            artifact=artifact,
            shard_hash=shard.shard_hash,
            sequence=1,
            created_at="2026-08-28T00:00:00.000000Z",
        )
        raise PreemptedError(
            "save and resume",
            checkpoint=checkpoint,
            progress_completed=5,
            progress_total=10,
            resources={"cpu_seconds": 3},
            spent={"credits": 2},
        )

    operation = FunctionalOperation(
        planner=_one_shard,
        runner=run_preempted,
        reducer=lambda _task, partials: {
            "outcome": "UNKNOWN",
            "partials": partials,
        },
        resumer=lambda _task, _shard, checkpoint: {
            "resumed_from": checkpoint.artifact.uri,
            "visited": 10,
        },
    )
    campaign = Campaign(
        "resume-demo",
        objective="Resume without promoting interruption to mathematics",
        targets=(target,),
        strategies=(strategy,),
        executor=executor,
        operations={"test.preempt": operation},
    )
    first = campaign.dispatch()
    assert first.outcome is Outcome.PREEMPTED
    assert campaign.ledger.status(target).open
    interruption_receipt = first.details.to_dict()["interruption_receipt"]
    assert isinstance(interruption_receipt, dict)
    lease = interruption_receipt["lease"]
    assert isinstance(lease, dict)
    assert lease["worker_id"] == "resume-worker"
    first_attempt = campaign.ledger.attempts_for_task(first.task_id)[-1]
    assert first_attempt.worker_id == "resume-worker"
    assert first_attempt.progress_completed == 5
    assert first_attempt.progress_total == 10
    assert first_attempt.resources.to_dict() == {"cpu_seconds": 3}
    assert campaign.status().to_dict()["spent"] == {"credits": 2}

    resumed_plan = campaign.recommend()
    assert len(resumed_plan) == 1
    resumed = resumed_plan.recommendations[0]
    checkpoint = first.checkpoint_ref
    assert checkpoint is not None
    assert resumed.action is RecommendationAction.RESUME
    assert resumed.task.checkpoint_ref == checkpoint
    assert checkpoint not in resumed.task.task.input_refs
    assert resumed.task.task.task_hash == campaign.tasks[0].task.task_hash

    artifact = tmp_path / "campaign.json"
    campaign.save(artifact)
    restored = Campaign.load(
        artifact,
        executor=WorkerPoolExecutor(
            workers,
            store,
            retry_policy=RetryPolicy(max_attempts=1),
        ),
        operations={"test.preempt": operation},
    )
    restored_plan = restored.recommend()
    assert restored.to_json() == campaign.to_json()
    assert restored_plan.plan_id == resumed_plan.plan_id
    completed = restored.dispatch(restored_plan.recommendations[0])
    assert completed.outcome is Outcome.UNKNOWN
    assert completed.operational_state.value == "UNKNOWN"
    assert completed.checkpoint_ref is None
    receipt = completed.details.to_dict()["fleet_receipt"]
    assert isinstance(receipt, dict)
    attempts = receipt["attempts"]
    assert isinstance(attempts, list)
    fleet_attempt = attempts[0]
    assert isinstance(fleet_attempt, dict)
    resumed_from = fleet_attempt["resumed_from"]
    assert isinstance(resumed_from, dict)
    artifact_value = resumed_from["artifact"]
    assert isinstance(artifact_value, dict)
    assert f"{artifact_value['algorithm']}:{artifact_value['digest']}" == checkpoint


def test_mixed_shard_failure_preserves_manifest_and_resumes_after_load(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:mixed-checkpoint")
    strategy = Strategy("search", "test.mixed-checkpoint", "resume partial fleet work")
    store = tmp_path / "mixed-fleet"
    workers = WorkerPool(
        (
            Worker("worker-a", (BackendStatus("python", True, ()),)),
            Worker("worker-b", (BackendStatus("python", True, ()),)),
        )
    )
    executor = WorkerPoolExecutor(
        workers,
        store,
        retry_policy=RetryPolicy(max_attempts=1),
        max_workers=2,
    )
    failed_once = False
    interrupted_once = False

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        nonlocal failed_once, interrupted_once
        if shard.key == "failed" and not failed_once:
            failed_once = True
            raise RuntimeError("one shard failed")
        if shard.key == "checkpointed" and not interrupted_once:
            interrupted_once = True
            artifact = executor.store.put_json({"checkpoint": "accepted"})
            raise PreemptedError(
                "other shard checkpointed",
                checkpoint=CheckpointRef(
                    artifact,
                    shard.shard_hash,
                    1,
                    "2026-08-28T00:00:00.000000Z",
                ),
            )
        return {"shard": shard.key, "state": "complete"}

    operation = FunctionalOperation(
        planner=lambda _task: ("checkpointed", "failed"),
        runner=run,
        reducer=lambda _task, partials: {
            "outcome": "UNKNOWN",
            "partials": partials,
        },
        resumer=lambda _task, shard, checkpoint: {
            "resumed_from": checkpoint.sequence,
            "shard": shard.key,
        },
    )
    campaign = Campaign(
        "mixed-checkpoint-demo",
        objective="Keep accepted custody despite another shard failure",
        targets=(target,),
        strategies=(strategy,),
        executor=executor,
        operations={strategy.operation: operation},
    )

    failed = campaign.dispatch()

    assert failed.outcome is Outcome.FAILED
    assert failed.checkpoint_ref is not None
    details = failed.details.to_dict()
    assert details["checkpoint_count"] == 1
    assert details["checkpoint_scope"] == "single-shard-manifest"
    assert isinstance(details["dispatch_failures"], list)
    resumed = campaign.recommend().recommendations[0]
    assert resumed.action is RecommendationAction.RESUME
    assert resumed.task.checkpoint_custody_id is not None

    path = tmp_path / "mixed-campaign.json"
    campaign.save(path)
    restored = Campaign.load(
        path,
        executor=WorkerPoolExecutor(
            workers,
            store,
            retry_policy=RetryPolicy(max_attempts=1),
            max_workers=2,
        ),
        operations={strategy.operation: operation},
    )
    restored_resume = restored.recommend().recommendations[0]
    assert restored_resume.task.checkpoint_custody_id == resumed.task.checkpoint_custody_id
    completed = restored.dispatch(restored_resume)
    assert completed.outcome is Outcome.UNKNOWN
    assert completed.checkpoint_ref is None


def test_pending_queue_interruption_preserves_receipt_and_retries_after_load(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:pending-queue")
    strategy = Strategy("search", "test.pending-queue", "retry an incomplete queue")
    workers = WorkerPool((Worker("queue-worker", (BackendStatus("python", True, ()),)),))
    store = tmp_path / "pending-fleet"
    executor = WorkerPoolExecutor(
        workers,
        store,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    interrupted = False

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise PreemptedError(
                "queue paused before remaining shards",
                progress_completed=1,
                progress_total=3,
                resources={"cpu_seconds": 4},
                spent={"credits": 2},
            )
        return {"shard": shard.key}

    operation = FunctionalOperation(
        planner=lambda _task: ("one", "two", "three"),
        runner=run,
        reducer=lambda _task, partials: {
            "outcome": "UNKNOWN",
            "partials": partials,
        },
    )
    campaign = Campaign(
        "pending-queue-demo",
        objective="Keep exact pending work and scheduler telemetry",
        targets=(target,),
        strategies=(strategy,),
        executor=executor,
        operations={strategy.operation: operation},
    )

    paused = campaign.dispatch()

    assert paused.outcome is Outcome.PREEMPTED
    assert paused.checkpoint_ref is None
    dispatch_error = paused.details.to_dict()["fleet_dispatch_error"]
    assert isinstance(dispatch_error, dict)
    scheduled = dispatch_error["scheduled"]
    failures = dispatch_error["failures"]
    assert isinstance(scheduled, list) and len(scheduled) == 3
    assert isinstance(failures, list) and len(failures) == 1
    failure = failures[0]
    assert isinstance(failure, dict)
    pending = failure["pending"]
    assert isinstance(pending, list) and len(pending) == 2
    attempt = campaign.ledger.attempts_for_task(paused.task_id)[-1]
    assert attempt.worker_id == "queue-worker"
    assert attempt.progress_completed == 1
    assert attempt.progress_total == 3
    assert attempt.resources.to_dict() == {"cpu_seconds": 4}
    status = campaign.status().to_dict()
    assert status["resource_usage"] == {"cpu_seconds": 4}
    assert status["spent"] == {"credits": 2}

    path = tmp_path / "pending-campaign.json"
    campaign.save(path)
    restored = Campaign.load(
        path,
        executor=WorkerPoolExecutor(
            workers,
            store,
            retry_policy=RetryPolicy(max_attempts=1),
        ),
        operations={strategy.operation: operation},
    )
    retry = restored.recommend().recommendations[0]
    assert retry.action is RecommendationAction.DISPATCH
    assert retry.task.task.task_hash == campaign.tasks[0].task.task_hash
    completed = restored.dispatch(retry)
    assert completed.outcome is Outcome.UNKNOWN


def test_homogeneous_multiworker_interruptions_keep_preempted_state(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:multi-preempt")
    strategy = Strategy("search", "test.multi-preempt", "preserve aggregate reason")
    workers = WorkerPool(
        (
            Worker("preempt-a", (BackendStatus("python", True, ()),)),
            Worker("preempt-b", (BackendStatus("python", True, ()),)),
        )
    )
    operation = FunctionalOperation(
        planner=lambda _task: ("a", "b"),
        runner=lambda _task, shard: (_ for _ in ()).throw(
            PreemptedError(
                f"preempted {shard.key}",
                progress_completed=0,
                progress_total=1,
            )
        ),
        reducer=lambda _task, partials: {"partials": partials},
    )
    campaign = Campaign(
        "multi-preempt-demo",
        objective="Never collapse homogeneous preemption into failure",
        targets=(target,),
        strategies=(strategy,),
        executor=WorkerPoolExecutor(
            workers,
            tmp_path / "multi-preempt",
            retry_policy=RetryPolicy(max_attempts=1),
            max_workers=2,
        ),
        operations={strategy.operation: operation},
    )

    observation = campaign.dispatch()

    assert observation.outcome is Outcome.PREEMPTED
    assert observation.operational_state is OperationalState.PREEMPTED
    receipts = observation.details.to_dict()["interruption_receipts"]
    assert isinstance(receipts, list) and len(receipts) == 2
    assert campaign.ledger.status(target).open


def test_successive_multishard_resume_carries_unprocessed_checkpoint(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:manifest-frontier")
    strategy = Strategy("search", "test.manifest-frontier", "retain live shard frontier")
    store = tmp_path / "manifest-frontier"
    workers = WorkerPool(
        (
            Worker("frontier-a", (BackendStatus("python", True, ()),)),
            Worker("frontier-b", (BackendStatus("python", True, ()),)),
        )
    )
    producer = WorkerPoolExecutor(
        workers,
        store,
        retry_policy=RetryPolicy(max_attempts=1),
        max_workers=2,
    )
    resume_calls: dict[str, list[int]] = {"a": [], "b": []}
    advance_a = True

    def checkpoint(
        executor: WorkerPoolExecutor,
        shard: ShardSpec,
        sequence: int,
    ) -> CheckpointRef:
        artifact = executor.store.put_json({"sequence": sequence, "shard": shard.key})
        return CheckpointRef(
            artifact,
            shard.shard_hash,
            sequence,
            f"2026-08-28T00:00:0{sequence}.000000Z",
        )

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        raise PreemptedError(
            f"initial {shard.key}",
            checkpoint=checkpoint(producer, shard, 1),
        )

    def resume(
        _task: TaskSpec,
        shard: ShardSpec,
        prior: CheckpointRef,
    ) -> dict[str, object]:
        nonlocal advance_a
        resume_calls[shard.key].append(prior.sequence)
        if shard.key == "a" and advance_a:
            advance_a = False
            raise PreemptedError(
                "advance a while b remains pending",
                checkpoint=checkpoint(producer, shard, 2),
            )
        return {"resumed": prior.sequence, "shard": shard.key}

    operation = FunctionalOperation(
        planner=lambda _task: ("a", "b"),
        runner=run,
        reducer=lambda _task, partials: {
            "outcome": "UNKNOWN",
            "partials": partials,
        },
        resumer=resume,
    )
    campaign = Campaign(
        "manifest-frontier-demo",
        objective="Preserve every live shard checkpoint across restarts",
        targets=(target,),
        strategies=(strategy,),
        executor=producer,
        operations={strategy.operation: operation},
    )

    first = campaign.dispatch()
    assert first.outcome is Outcome.PREEMPTED
    first_manifest_raw = first.details.to_dict()["checkpoint_manifest"]
    assert isinstance(first_manifest_raw, dict)
    assert len(CheckpointManifest.from_dict(first_manifest_raw).checkpoints) == 2

    first_path = tmp_path / "frontier-first.json"
    campaign.save(first_path)
    one_worker = WorkerPool((Worker("frontier-one", (BackendStatus("python", True, ()),)),))
    restored = Campaign.load(
        first_path,
        executor=WorkerPoolExecutor(
            one_worker,
            store,
            retry_policy=RetryPolicy(max_attempts=1),
            max_workers=1,
        ),
        operations={strategy.operation: operation},
    )
    second = restored.dispatch(restored.recommend().recommendations[0])
    assert second.outcome is Outcome.PREEMPTED
    second_manifest_raw = second.details.to_dict()["checkpoint_manifest"]
    assert isinstance(second_manifest_raw, dict)
    second_manifest = CheckpointManifest.from_dict(second_manifest_raw)
    assert {item.sequence for item in second_manifest.checkpoints} == {1, 2}

    second_path = tmp_path / "frontier-second.json"
    restored.save(second_path)
    final = Campaign.load(
        second_path,
        executor=WorkerPoolExecutor(
            one_worker,
            store,
            retry_policy=RetryPolicy(max_attempts=1),
            max_workers=1,
        ),
        operations={strategy.operation: operation},
    )
    completed = final.dispatch(final.recommend().recommendations[0])
    assert completed.outcome is Outcome.UNKNOWN
    assert resume_calls == {"a": [1, 2], "b": [1]}


def test_resume_hard_failure_retains_checkpoint_for_next_restart(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:resume-hard-failure")
    strategy = Strategy("search", "test.resume-hard-failure", "retain accepted checkpoint")
    workers = WorkerPool((Worker("hard-failure-worker", (BackendStatus("python", True, ()),)),))
    store = tmp_path / "resume-hard-failure"
    producer = WorkerPoolExecutor(
        workers,
        store,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    fail_resume = True

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        artifact = producer.store.put_json({"checkpoint": "stable"})
        raise PreemptedError(
            "initial checkpoint",
            checkpoint=CheckpointRef(
                artifact,
                shard.shard_hash,
                1,
                "2026-08-28T00:00:00.000000Z",
            ),
        )

    def resume(
        _task: TaskSpec,
        _shard: ShardSpec,
        prior: CheckpointRef,
    ) -> dict[str, object]:
        nonlocal fail_resume
        if fail_resume:
            fail_resume = False
            raise RuntimeError("transient resumer failure")
        return {"resumed": prior.sequence}

    operation = FunctionalOperation(
        planner=_one_shard,
        runner=run,
        reducer=lambda _task, partials: {
            "outcome": "UNKNOWN",
            "partials": partials,
        },
        resumer=resume,
    )
    campaign = Campaign(
        "resume-hard-failure-demo",
        objective="A transient resumer failure must not erase accepted custody",
        targets=(target,),
        strategies=(strategy,),
        executor=producer,
        operations={strategy.operation: operation},
    )

    initial = campaign.dispatch()
    assert initial.outcome is Outcome.PREEMPTED
    first_path = tmp_path / "resume-hard-first.json"
    campaign.save(first_path)

    restored = Campaign.load(
        first_path,
        executor=WorkerPoolExecutor(
            workers,
            store,
            retry_policy=RetryPolicy(max_attempts=1),
        ),
        operations={strategy.operation: operation},
    )
    failed = restored.dispatch(restored.recommend().recommendations[0])
    assert failed.outcome is Outcome.FAILED
    assert failed.checkpoint_ref == initial.checkpoint_ref
    assert failed.details.to_dict()["checkpoint_manifest"] is not None
    retry = restored.recommend().recommendations[0]
    assert retry.action is RecommendationAction.RESUME

    second_path = tmp_path / "resume-hard-second.json"
    restored.save(second_path)
    final = Campaign.load(
        second_path,
        executor=WorkerPoolExecutor(
            workers,
            store,
            retry_policy=RetryPolicy(max_attempts=1),
        ),
        operations={strategy.operation: operation},
    )
    completed = final.dispatch(final.recommend().recommendations[0])
    assert completed.outcome is Outcome.UNKNOWN
    assert completed.checkpoint_ref is None


def test_local_executor_cache_is_reused_by_campaign_dispatch(tmp_path: Path) -> None:
    calls = 0
    target = TargetSpec("case:cached")
    strategy = Strategy("search", "test.cache", "cache deterministic work")

    def run(_task: TaskSpec, _shard: ShardSpec) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": 7}

    operation = FunctionalOperation(
        planner=_one_shard,
        runner=run,
        reducer=lambda _task, partials: {
            "outcome": "PREEMPTED",
            "checkpoint_ref": "sha256:" + "b" * 64,
            "partials": partials,
        },
    )
    executor = LocalExecutor(tmp_path / "fleet")
    first = Campaign(
        "cache-demo",
        objective="Reuse exact local artifacts",
        targets=(target,),
        strategies=(strategy,),
        executor=executor,
        operations={"test.cache": operation},
    )
    first.dispatch()
    assert calls == 1

    # A fresh campaign with the same mathematical TaskSpec reads the cached
    # fleet shard and reduction instead of rerunning it.
    second = Campaign(
        "cache-demo",
        objective="Reuse exact local artifacts",
        targets=(target,),
        strategies=(strategy,),
        executor=LocalExecutor(tmp_path / "fleet"),
        operations={"test.cache": operation},
    )
    second.dispatch()
    assert calls == 1


def test_campaign_load_reconciles_orphaned_running_attempt_without_proof(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:orphaned-attempt")
    strategy = Strategy("search", "test.orphaned", "recover local crash state")
    campaign = Campaign(
        "orphaned-attempt-demo",
        objective="Never mistake a lost process for completed work",
        targets=(target,),
        strategies=(strategy,),
    )
    task = campaign.recommend().recommendations[0].task
    running = AttemptRecord(
        target.target_id,
        task.campaign_task_id,
        1,
        OperationalState.RUNNING,
        worker_id="lost-worker",
        progress_completed=4,
        progress_total=10,
    )
    campaign.ledger.record_attempt(running)
    artifact = tmp_path / "orphaned.json"
    campaign.save(artifact)

    restored = Campaign.load(artifact)

    assert not restored.ledger.live_attempts
    latest = restored.ledger.latest_attempts[0]
    assert latest.state is OperationalState.UNKNOWN
    assert latest.progress_completed == 4
    assert latest.detail is not None and "orphaned RUNNING" in latest.detail
    assert restored.ledger.status(target).open
    assert not restored.ledger.observations


def test_worker_pool_registry_candidates_claims_status_and_replay(tmp_path: Path) -> None:
    target = TargetSpec("case:heterogeneous-candidate", importance=7)
    strategy = Strategy(
        "enumerate",
        "test.registry-candidates",
        "enumerate exact candidates on eligible local workers",
    )

    def reduce_candidates(
        task: TaskSpec,
        partials: Sequence[JSONValue],
    ) -> dict[str, object]:
        certificate = closure_certificate(
            target.target_id,
            Outcome.FOUND,
            "test.campaign-found",
            task_hash=task.task_hash,
            witness={"partials": partials, "witness": partials[0]},
            checks=("candidate canonical form independently checked",),
        )
        return {
            "candidates": [
                {
                    "canonical_key": "field:x3-x-1",
                    "canonicalizer": "test.field-normal-form/v1",
                    "evidence": "VERIFIED",
                    "equivalence_scope": "GLOBAL",
                    "invariants": {"degree": 3, "discriminant": -23},
                    "quality": 23,
                    "quality_metric": "small-discriminant",
                }
            ],
            "certificate": certificate.to_dict(),
            "outcome": "FOUND",
        }

    operation = FunctionalOperation(
        planner=lambda _task: ("left", "right"),
        runner=lambda _task, shard: {"shard": shard.key},
        reducer=reduce_candidates,
    )
    registry = FleetOperationRegistry({strategy.operation: operation})
    backend = BackendStatus("python", True, (), version="3.13")
    workers = WorkerPool(
        (
            Worker("cpu-a", (backend,), resources=ResourceHint(cpu_cores=2)),
            Worker("cpu-b", (backend,), resources=ResourceHint(cpu_cores=2)),
        )
    )
    executor = WorkerPoolExecutor(
        workers,
        tmp_path / "fleet",
        operation_registry=registry,
        max_workers=2,
    )
    campaign = Campaign(
        "worker-candidate-demo",
        objective="Own exact candidates, claims, and worker receipts",
        targets=(target,),
        strategies=(strategy,),
        executor=executor,
        operation_registry=registry,
    )

    observation = campaign.dispatch()
    status = campaign.status()

    assert observation.outcome is Outcome.FOUND
    receipt = observation.details.to_dict()["fleet_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["worker_ids"] == ["cpu-a", "cpu-b"]
    assert len(campaign.candidates) == 1
    assert campaign.candidates[0].evidence is CandidateEvidence.VERIFIED
    assert campaign.ledger.best_known(target) == campaign.candidates[0]
    assert len(campaign.claims) == 1
    exported_graph = campaign.export_claims()
    assert exported_graph["schema_version"] == "arbogast.claim-graph/v1"
    exported_claims = exported_graph["claims"]
    assert isinstance(exported_claims, list)
    assert len(exported_claims) == 1
    assert campaign.claims.verify().verified
    assert status.worker_count == 2
    assert status.available_workers == 2
    assert status.busy_workers == 0
    assert status.candidate_count == 1
    assert status.claim_count == 1
    assert status.recorded_plans >= 1
    assert status.fleet_status is not None
    assert campaign.recommend().advisories[0].action is RecommendationAction.EXPAND

    artifact = tmp_path / "worker-campaign.json"
    campaign.save(artifact)
    restored = Campaign.load(
        artifact,
        executor=executor,
        operation_registry=registry,
    )
    assert restored.to_json() == campaign.to_json()
    assert restored.ledger.best_known(target) == campaign.candidates[0]
    assert restored.claims.digest == campaign.claims.digest

    fresh_verifiers = VerifierRegistry()
    fresh_verifiers.register(
        "test.campaign-found",
        VerificationCertificate,
        _found_certificate_verifier,
    )
    register_campaign_claim_verifier(fresh_verifiers)
    assert restored.claims.verify(verifier_registry=fresh_verifiers).verified
    replayed_graph = ClaimGraph.from_dict(restored.export_claims())
    assert replayed_graph.verify(verifier_registry=fresh_verifiers).verified

    standalone_graph = tmp_path / "standalone-claim-graph.json"
    standalone_graph.write_text(
        canonical_dumps(restored.export_claims()),
        encoding="utf-8",
    )
    subprocess.run(
        (
            sys.executable,
            "-c",
            (
                "import json,sys; "
                "from arbogast.claims import ClaimGraph; "
                "from arbogast.cert import default_verifiers; "
                "graph=ClaimGraph.from_dict(json.load(open(sys.argv[1], encoding='utf-8'))); "
                "report=graph.verify(raise_on_failure=False); "
                "assert not report.verified; "
                "assert 'test.campaign-found' in (report.error or ''), report.error; "
                "assert 'campaign.claim-closure.v1' in default_verifiers.names()"
            ),
            str(standalone_graph),
        ),
        check=True,
    )

    claim = restored.claims.claims[0]
    claim_payload = claim.to_dict()
    attached = claim_payload["attached_certificates"]
    assert isinstance(attached, list) and len(attached) == 1
    raw_certificate = attached[0]
    assert isinstance(raw_certificate, dict)
    raw_certificate.pop("certificate_id")
    witness = raw_certificate["witness"]
    assert isinstance(witness, dict)
    witness["campaign_id"] = f"sha256:{'f' * 64}"
    tampered_certificate = VerificationCertificate.from_dict(raw_certificate)
    claim_payload["attached_certificates"] = [tampered_certificate.to_dict()]
    evidence = claim_payload["evidence"]
    assert isinstance(evidence, list) and len(evidence) == 1
    evidence_ref = evidence[0]
    assert isinstance(evidence_ref, dict)
    evidence_ref["ref"] = tampered_certificate.certificate_id
    tampered_claim = Claim.from_dict(claim_payload)
    tampered_report = tampered_claim.verify(
        verifier_registry=fresh_verifiers,
        raise_on_failure=False,
    )
    assert not tampered_report.verified
    assert tampered_report.error is not None
    assert "wrong claim ID" in tampered_report.error


def test_strategy_factory_descriptor_requires_explicit_runtime_rebinding(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:factory")

    def custom_factory(
        target: TargetSpec,
        provenance: TaskProvenance,
        checkpoint_ref: str | None,
    ) -> TaskSpec:
        del provenance, checkpoint_ref
        return TaskSpec(
            "test.custom-factory",
            parameters={"custom_target": target.target_id},
        )

    strategy = Strategy(
        "custom",
        "test.descriptor-only",
        "preserve custom task construction semantics",
        task_factory=custom_factory,
        task_factory_name="tests:custom-factory-v1",
    )
    campaign = Campaign(
        "factory-demo",
        objective="Never deserialize executable strategy code",
        targets=(target,),
        strategies=(strategy,),
    )
    artifact = tmp_path / "factory.json"
    campaign.save(artifact)

    unbound = Campaign.load(artifact)
    with pytest.raises(CampaignInvariantError, match="uninjected task factory"):
        unbound.recommend()

    rebound = Campaign.load(
        artifact,
        task_factories={"tests:custom-factory-v1": custom_factory},
    )
    task = rebound.recommend().recommendations[0].task
    assert task.task.operation == "test.custom-factory"
    assert task.task.parameters["custom_target"] == target.target_id


def test_planner_advisories_are_authoritative_replayable_decisions() -> None:
    target = TargetSpec("case:blocked-plan")
    strategy = Strategy(
        "needs-capability",
        "test.blocked-plan",
        "exercise explicit suspension advice",
        capability_requirements=("magma",),
    )
    campaign = Campaign(
        "blocked-plan-demo",
        objective="Explain why valuable work cannot currently run",
        targets=(target,),
        strategies=(strategy,),
        capabilities=(),
    )

    plan = campaign.recommend()

    assert not plan.recommendations
    assert plan.advisories[0].action is RecommendationAction.SUSPEND
    assert "missing: magma" in plan.advisories[0].reason
    assert campaign.ledger.latest_plan_document == plan.to_dict()
    assert campaign.status().latest_plan_id == plan.plan_id
    assert Campaign.from_dict(campaign.to_dict()).recommend().plan_id == plan.plan_id


def test_worker_backend_and_resource_rejections_suspend_before_dispatch(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:worker-mismatch")

    def task_factory(
        target: TargetSpec,
        provenance: TaskProvenance,
        checkpoint_ref: str | None,
    ) -> TaskSpec:
        del target, provenance, checkpoint_ref
        return TaskSpec(
            "test.needs-magma",
            backend=BackendRequirement("magma"),
            resources=ResourceHint(cpu_cores=8),
        )

    strategy = Strategy(
        "magma-search",
        "test.needs-magma",
        "run only where backend and resources are actually available",
        task_factory=task_factory,
        task_factory_name="tests:needs-magma-v1",
    )
    executor = WorkerPoolExecutor(
        WorkerPool(
            (
                Worker(
                    "python-small",
                    (BackendStatus("python", True, ()),),
                    resources=ResourceHint(cpu_cores=2),
                ),
            )
        ),
        tmp_path / "fleet",
    )
    campaign = Campaign(
        "worker-mismatch-demo",
        objective="Do not dispatch to an ineligible worker",
        targets=(target,),
        strategies=(strategy,),
        executor=executor,
    )

    plan = campaign.recommend()

    assert not plan.recommendations
    reason = plan.advisories[0].reason
    assert "backend 'magma' is not advertised" in reason
    assert "insufficient CPU cores" in reason
    assert "python-small" in campaign.explain(target).blockers[0]
    with pytest.raises(CapabilityUnavailableError, match="no eligible worker"):
        campaign.dispatch(campaign.tasks[0])


def test_reducer_cannot_fabricate_resumable_checkpoint_custody(tmp_path: Path) -> None:
    fabricated = "sha256:" + "f" * 64
    target = TargetSpec("case:fake-checkpoint")
    strategy = Strategy("search", "test.fake-checkpoint", "reject fabricated custody")
    operation = FunctionalOperation(
        planner=_one_shard,
        runner=lambda _task, _shard: {"visited": 1},
        reducer=lambda _task, _partials: {
            "checkpoint_ref": fabricated,
            "outcome": "PREEMPTED",
        },
    )
    campaign = Campaign(
        "fake-checkpoint-demo",
        objective="Resume only executor-validated checkpoints",
        targets=(target,),
        strategies=(strategy,),
        executor=LocalExecutor(tmp_path / "fleet"),
        operations={strategy.operation: operation},
    )

    observation = campaign.dispatch()
    successor = campaign.recommend().recommendations[0]

    assert observation.outcome is Outcome.PREEMPTED
    assert observation.checkpoint_ref is None
    assert observation.details["rejected_untrusted_checkpoint_ref"] == fabricated
    assert successor.action is RecommendationAction.DISPATCH
    assert successor.task.provenance.parent_observation_ids == (observation.observation_id,)
