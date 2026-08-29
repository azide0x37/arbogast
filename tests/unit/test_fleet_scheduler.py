from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Lock, Thread
from typing import cast

import pytest

import arbogast.fleet.builtins as fleet_builtins
from arbogast.backends import BackendStatus
from arbogast.fleet import (
    BackendRequirement,
    BudgetExhaustedError,
    CheckpointManifest,
    CheckpointRef,
    DuplicateDispatchError,
    DuplicateFleetOperationError,
    FleetDispatchError,
    FleetExecutionError,
    FleetOperationRegistry,
    FunctionalOperation,
    InterruptionReceipt,
    LeaseCustody,
    LeaseState,
    NoEligibleWorkerError,
    PreemptedError,
    ResourceHint,
    RetryPolicy,
    ShardSpec,
    StaleLeaseError,
    TaskSpec,
    UnknownFleetOperationError,
    Worker,
    WorkerPool,
    WorkerPoolExecutor,
    WorkerState,
    automatic_local_worker_pool,
)
from arbogast.formats import JSONValue


def _backend(*capabilities: str) -> BackendStatus:
    return BackendStatus(
        "python",
        True,
        tuple(capabilities),
        version="3.13",
    )


def _worker(
    worker_id: str,
    *,
    cpu_cores: int = 2,
    capabilities: tuple[str, ...] = ("exact",),
) -> Worker:
    return Worker(
        worker_id,
        (_backend(*capabilities),),
        resources=ResourceHint(cpu_cores=cpu_cores, memory_mb=256),
    )


def _operation(*keys: str) -> FunctionalOperation[dict[str, object], dict[str, object]]:
    return FunctionalOperation(
        planner=lambda _task: keys,
        runner=lambda _task, shard: {"key": shard.key},
        reducer=lambda _task, partials: {"partials": partials},
    )


def test_persisted_task_names_resolve_only_through_trusted_runtime_registry(tmp_path) -> None:
    operation = _operation("only")
    registry = FleetOperationRegistry({"test.persisted": operation})
    persisted = TaskSpec.from_dict(TaskSpec("test.persisted").to_dict())
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("local"),)),
        tmp_path,
        operation_registry=registry,
    )

    run = executor.execute_registered(persisted)

    assert executor.result_value(run) == {"partials": [{"key": "only"}]}
    assert registry.to_dict() == {
        "names": ["test.persisted"],
        "schema": "arbogast.fleet.operation-registry.v1",
    }
    assert "runner" not in str(registry.to_dict())
    with pytest.raises(UnknownFleetOperationError, match="never loads callables"):
        executor.execute_registered(TaskSpec("test.untrusted"))
    with pytest.raises(DuplicateFleetOperationError, match="already registered"):
        registry.register("test.persisted", _operation("different"))


def test_no_eligible_worker_fails_with_auditable_reasons(tmp_path) -> None:
    task = TaskSpec(
        "test.needs-magma",
        backend=BackendRequirement("magma", capabilities=("cohomology",)),
        resources=ResourceHint(cpu_cores=8, memory_mb=4096),
    )
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("python-small", cpu_cores=2),)),
        tmp_path,
    )

    with pytest.raises(NoEligibleWorkerError) as caught:
        executor.execute(task, _operation("only"))

    assert caught.value.matches[0].worker_id == "python-small"
    assert "backend 'magma' is not advertised" in caught.value.matches[0].reasons
    assert "insufficient CPU cores" in caught.value.matches[0].reasons


def test_lease_custody_rejects_duplicate_dispatch_and_stale_completion() -> None:
    custody = LeaseCustody()
    task = TaskSpec("test.custody")
    shard = ShardSpec(task.task_hash, "only")
    worker = _worker("local")
    now = datetime(2026, 8, 28, tzinfo=UTC)
    first = custody.offer(
        task,
        shard,
        worker,
        attempt=0,
        acquired_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    active = custody.activate(first.id, now=now)

    with pytest.raises(DuplicateDispatchError, match="already has live lease"):
        custody.offer(
            task,
            shard,
            worker,
            attempt=1,
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
        )

    expired = custody.expire(active.id, now=now + timedelta(seconds=1))
    assert expired.state is LeaseState.EXPIRED
    replacement = custody.offer(
        task,
        shard,
        worker,
        attempt=1,
        acquired_at=now + timedelta(seconds=2),
        expires_at=now + timedelta(minutes=5),
    )
    custody.activate(replacement.id, now=now + timedelta(seconds=2))
    committed = False

    def forbidden_commit() -> None:
        nonlocal committed
        committed = True

    with pytest.raises(StaleLeaseError, match="terminal or superseded"):
        custody.commit(
            first.id,
            forbidden_commit,
            now=now + timedelta(seconds=3),
        )
    assert not committed


def test_preemption_retries_from_bound_checkpoint_with_provenance(tmp_path) -> None:
    task = TaskSpec("test.retry")
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("local"),)),
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=2),
    )
    calls: list[str] = []

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        calls.append("run")
        artifact = executor.store.put_json({"visited": 17})
        checkpoint = CheckpointRef(
            artifact,
            shard.shard_hash,
            1,
            "2026-08-28T12:00:00.000000Z",
        )
        raise PreemptedError("worker reclaimed", checkpoint=checkpoint)

    def resume(
        _task: TaskSpec,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> dict[str, object]:
        calls.append("resume")
        assert checkpoint.shard_hash == shard.shard_hash
        assert executor.store.get_json(checkpoint.artifact) == {"visited": 17}
        return {"continued_from": checkpoint.sequence, "key": shard.key}

    operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
        resumer=resume,
    )

    fleet_run = executor.execute(task, operation)
    attempts = executor.attempt_records(task_hash=task.task_hash)

    assert calls == ["run", "resume"]
    assert tuple(attempt.state for attempt in attempts) == (
        LeaseState.PREEMPTED,
        LeaseState.COMPLETED,
    )
    assert attempts[1].retry_of == attempts[0].lease.id
    assert attempts[1].resumed_from == attempts[0].lease.checkpoint
    assert executor.result_value(fleet_run) == {"partials": [{"continued_from": 1, "key": "only"}]}
    receipt = executor.receipt_for(fleet_run)
    assert receipt.worker_ids == ("local",)
    assert receipt.attempts == attempts
    status = executor.status(task_hash=task.task_hash)
    assert status.completed_count == 1
    assert status.preempted_count == 1


def test_typed_checkpoint_replays_in_fresh_executor_and_uri_only_custody_does_not(
    tmp_path,
) -> None:
    task = TaskSpec("test.fresh-resume")
    checkpoints: list[CheckpointRef] = []
    calls: list[str] = []

    first = WorkerPoolExecutor(
        WorkerPool((_worker("local"),)),
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        calls.append("run")
        checkpoint = CheckpointRef(
            first.store.put_json({"cursor": 9}),
            shard.shard_hash,
            9,
            "2026-08-28T12:00:00.000000Z",
        )
        checkpoints.append(checkpoint)
        raise PreemptedError("persist exact cursor", checkpoint=checkpoint)

    def resume(
        _task: TaskSpec,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> dict[str, object]:
        calls.append("resume")
        assert checkpoint.shard_hash == shard.shard_hash
        return {"cursor": checkpoint.sequence, "resumed": True}

    operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
        resumer=resume,
    )
    with pytest.raises(FleetDispatchError):
        first.execute(task, operation)

    replayed = CheckpointRef.from_dict(checkpoints[0].to_dict())
    fresh = WorkerPoolExecutor(
        WorkerPool((_worker("local"),)),
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    with pytest.raises(FleetExecutionError, match="no typed custody"):
        fresh.execute_checkpointed(
            task,
            operation,
            checkpoint_ref=replayed.artifact.uri,
        )
    forged_task = TaskSpec("test.forged-typed-checkpoint")
    forged_plan = fresh.plan(forged_task, operation)
    forged = CheckpointRef(
        fresh.store.put_json({"cursor": "not executor custody"}),
        forged_plan.shards[0].shard_hash,
        1,
        "2026-08-28T12:01:00.000000Z",
    )
    with pytest.raises(FleetExecutionError, match="no persisted typed custody"):
        fresh.execute_checkpointed(
            forged_task,
            operation,
            checkpoint_ref=forged,
        )
    fleet_run = fresh.execute_checkpointed(
        task,
        operation,
        checkpoint_ref=replayed,
    )

    assert calls == ["run", "resume"]
    assert fresh.result_value(fleet_run) == {"partials": [{"cursor": 9, "resumed": True}]}
    attempt = fresh.receipt_for(fleet_run).attempts[0]
    assert attempt.retry_of is None
    assert attempt.resumed_from == replayed
    receipt = fresh.receipt_for(fleet_run)
    assert receipt.checkpoint_resumed
    assert receipt.checkpoint_resumed_shards == (replayed.shard_hash,)
    assert not receipt.result_cache_resumed
    assert receipt.cached_shard_hashes == ()
    assert first.attempt_records(task_hash=task.task_hash)[0].dispatch_id != attempt.dispatch_id
    changed_task = TaskSpec(task.operation, input_refs=(replayed.artifact.uri,))
    with pytest.raises(FleetExecutionError, match="current deterministic plan"):
        fresh.execute_checkpointed(
            changed_task,
            operation,
            checkpoint_ref=replayed,
        )
    tampered = replayed.to_dict()
    tampered["sequence"] = True
    with pytest.raises(ValueError, match="sequence"):
        CheckpointRef.from_dict(tampered)


def test_multi_shard_manifest_replays_every_cooperative_checkpoint_after_reload(
    tmp_path,
) -> None:
    task = TaskSpec("test.multi-checkpoint")
    workers = WorkerPool((_worker("left"), _worker("right")))
    first = WorkerPoolExecutor(
        workers,
        tmp_path,
        max_workers=2,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    rendezvous = Barrier(2)
    resumed: list[str] = []
    resumed_lock = Lock()

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        rendezvous.wait(timeout=5)
        checkpoint = CheckpointRef(
            first.store.put_json({"cursor": shard.key}),
            shard.shard_hash,
            1,
            "2026-08-28T12:00:00.000000Z",
        )
        raise PreemptedError("publish per-shard cursor", checkpoint=checkpoint)

    def resume(
        _task: TaskSpec,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> dict[str, object]:
        with resumed_lock:
            resumed.append(shard.key)
        return {"cursor": checkpoint.sequence, "key": shard.key}

    operation = FunctionalOperation(
        planner=lambda _task: ("right", "left"),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
        resumer=resume,
    )

    with pytest.raises(FleetDispatchError) as interrupted:
        first.execute(task, operation)
    assert interrupted.value.checkpoint_manifest is not None
    assert len(interrupted.value.failures) == 2

    manifest = first.checkpoint_manifest(task.task_hash)
    assert manifest is not None
    assert len(manifest.checkpoints) == 2
    replayed = CheckpointManifest.from_dict(manifest.to_dict())
    tampered = replayed.to_dict()
    tampered["manifest_hash"] = "0" * 64
    with pytest.raises(ValueError, match="manifest hash"):
        CheckpointManifest.from_dict(tampered)

    fresh = WorkerPoolExecutor(
        workers,
        tmp_path,
        max_workers=2,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    fleet_run = fresh.execute_checkpointed(
        task,
        operation,
        checkpoint_ref=replayed,
    )

    assert sorted(resumed) == ["left", "right"]
    assert fresh.result_value(fleet_run) == {
        "partials": [
            {"cursor": 1, "key": "left"},
            {"cursor": 1, "key": "right"},
        ]
    }
    receipt = fresh.receipt_for(fleet_run)
    assert receipt.checkpoint_resumed
    assert receipt.checkpoint_resumed_shards == tuple(
        sorted(checkpoint.shard_hash for checkpoint in replayed.checkpoints)
    )
    assert receipt.cached_shard_hashes == ()
    assert not receipt.result_cache_resumed


def test_fresh_resume_may_idempotently_reemit_the_same_exact_checkpoint(
    tmp_path,
) -> None:
    task = TaskSpec("test.reemit-checkpoint")
    workers = WorkerPool((_worker("local"),))
    checkpoint_holder: list[CheckpointRef] = []
    first = WorkerPoolExecutor(
        workers,
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        checkpoint = CheckpointRef(
            first.store.put_json({"cursor": 7}),
            shard.shard_hash,
            7,
            "2026-08-28T12:00:00.000000Z",
        )
        checkpoint_holder.append(checkpoint)
        raise PreemptedError("first producer", checkpoint=checkpoint)

    first_operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )
    with pytest.raises(FleetDispatchError):
        first.execute(task, first_operation)

    checkpoint = checkpoint_holder[0]
    second = WorkerPoolExecutor(
        workers,
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    reemitting_operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=lambda _task, _shard: {"unexpected": True},
        reducer=lambda _task, partials: {"partials": partials},
        resumer=lambda _task, _shard, resumed: (_ for _ in ()).throw(
            PreemptedError("same cursor, new producer", checkpoint=resumed)
        ),
    )
    with pytest.raises(FleetDispatchError, match="same cursor"):
        second.execute_checkpointed(
            task,
            reemitting_operation,
            checkpoint_ref=checkpoint,
        )

    third = WorkerPoolExecutor(
        workers,
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    completing_operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=lambda _task, _shard: {"unexpected": True},
        reducer=lambda _task, partials: {"partials": partials},
        resumer=lambda _task, shard, resumed: {
            "key": shard.key,
            "sequence": resumed.sequence,
        },
    )
    fleet_run = third.execute_checkpointed(
        task,
        completing_operation,
        checkpoint_ref=checkpoint,
    )
    assert third.result_value(fleet_run) == {"partials": [{"key": "only", "sequence": 7}]}


def test_reinterruption_carries_forward_pending_checkpoints_from_input_manifest(
    tmp_path,
) -> None:
    task = TaskSpec("test.manifest-carry-forward")
    two_workers = WorkerPool((_worker("a-worker"), _worker("b-worker")))
    first = WorkerPoolExecutor(
        two_workers,
        tmp_path,
        max_workers=2,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    rendezvous = Barrier(2)

    def initial_run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        rendezvous.wait(timeout=5)
        checkpoint = CheckpointRef(
            first.store.put_json({"cursor": 1, "key": shard.key}),
            shard.shard_hash,
            1,
            "2026-08-28T12:00:00.000000Z",
        )
        raise PreemptedError("initial checkpoint", checkpoint=checkpoint)

    initial = FunctionalOperation(
        planner=lambda _task: ("a", "b"),
        runner=initial_run,
        reducer=lambda _task, partials: {"partials": partials},
    )
    with pytest.raises(FleetDispatchError) as first_error:
        first.execute(task, initial)
    first_manifest = first_error.value.checkpoint_manifest
    assert first_manifest is not None
    assert len(first_manifest.checkpoints) == 2

    second = WorkerPoolExecutor(
        WorkerPool((_worker("one-worker"),)),
        tmp_path,
        max_workers=1,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    def advance_a(
        _task: TaskSpec,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> dict[str, object]:
        if shard.key != "a":  # pragma: no cover - queue must stop at a
            return {"unexpected": checkpoint.sequence}
        advanced = CheckpointRef(
            second.store.put_json({"cursor": 2, "key": shard.key}),
            shard.shard_hash,
            2,
            "2026-08-28T12:01:00.000000Z",
        )
        raise PreemptedError("a advanced; b remains pending", checkpoint=advanced)

    advancing = FunctionalOperation(
        planner=lambda _task: ("a", "b"),
        runner=lambda _task, _shard: {"unexpected": True},
        reducer=lambda _task, partials: {"partials": partials},
        resumer=advance_a,
    )
    with pytest.raises(FleetDispatchError) as second_error:
        second.execute_checkpointed(
            task,
            advancing,
            checkpoint_ref=first_manifest,
        )
    carried = second_error.value.checkpoint_manifest
    assert carried is not None
    assert {item.sequence for item in carried.checkpoints} == {1, 2}
    assert second_error.value.failures[0].shard_key == "a"
    assert tuple(item.shard_key for item in second_error.value.failures[0].pending) == ("b",)

    resumed: list[tuple[str, int]] = []
    third = WorkerPoolExecutor(
        two_workers,
        tmp_path,
        max_workers=2,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    def finish(
        _task: TaskSpec,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> dict[str, object]:
        resumed.append((shard.key, checkpoint.sequence))
        return {"key": shard.key, "sequence": checkpoint.sequence}

    completing = FunctionalOperation(
        planner=lambda _task: ("a", "b"),
        runner=lambda _task, _shard: {"unexpected": True},
        reducer=lambda _task, partials: {"partials": partials},
        resumer=finish,
    )
    fleet_run = third.execute_checkpointed(
        task,
        completing,
        checkpoint_ref=carried,
    )
    assert sorted(resumed) == [("a", 2), ("b", 1)]
    assert third.result_value(fleet_run) == {
        "partials": [
            {"key": "a", "sequence": 2},
            {"key": "b", "sequence": 1},
        ]
    }


def test_hard_resume_failure_retains_the_accepted_single_shard_manifest(
    tmp_path,
) -> None:
    task = TaskSpec("test.hard-resume-failure")
    workers = WorkerPool((_worker("local"),))
    first = WorkerPoolExecutor(
        workers,
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        checkpoint = CheckpointRef(
            first.store.put_json({"cursor": 3}),
            shard.shard_hash,
            3,
            "2026-08-28T12:00:00.000000Z",
        )
        raise PreemptedError("accepted checkpoint", checkpoint=checkpoint)

    initial = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )
    with pytest.raises(FleetDispatchError) as first_error:
        first.execute(task, initial)
    accepted = first_error.value.checkpoint_manifest
    assert accepted is not None

    fresh = WorkerPoolExecutor(
        workers,
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    def fail_resume(
        _task: TaskSpec,
        _shard: ShardSpec,
        _checkpoint: CheckpointRef,
    ) -> dict[str, object]:
        raise RuntimeError("resumer dependency unavailable")

    failing = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=lambda _task, _shard: {"unexpected": True},
        reducer=lambda _task, partials: {"partials": partials},
        resumer=fail_resume,
    )
    with pytest.raises(FleetDispatchError, match="resumer dependency") as caught:
        fresh.execute_checkpointed(
            task,
            failing,
            checkpoint_ref=accepted,
        )

    retained = caught.value.checkpoint_manifest
    assert retained == accepted
    assert caught.value.failures[0].shard_key == "only"
    assert caught.value.failures[0].pending == ()


def test_checkpoint_sequence_reuse_with_different_content_fails_closed(
    tmp_path,
) -> None:
    task = TaskSpec("test.checkpoint-sequence-reuse")
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("local"),)),
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=2),
    )

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        checkpoint = CheckpointRef(
            executor.store.put_json({"cursor": "first"}),
            shard.shard_hash,
            1,
            "2026-08-28T12:00:00.000000Z",
        )
        raise PreemptedError("first cursor", checkpoint=checkpoint)

    def resume(
        _task: TaskSpec,
        shard: ShardSpec,
        _checkpoint: CheckpointRef,
    ) -> dict[str, object]:
        conflicting = CheckpointRef(
            executor.store.put_json({"cursor": "different"}),
            shard.shard_hash,
            1,
            "2026-08-28T12:00:01.000000Z",
        )
        raise PreemptedError("conflicting cursor", checkpoint=conflicting)

    operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
        resumer=resume,
    )

    with pytest.raises(FleetExecutionError, match="sequence was reused"):
        executor.execute(task, operation)


def test_mixed_worker_terminals_preserve_checkpoint_manifest_and_error_summary(
    tmp_path,
) -> None:
    task = TaskSpec("test.mixed-terminal")
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("worker-a"), _worker("worker-b"))),
        tmp_path,
        max_workers=2,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    rendezvous = Barrier(2)

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        rendezvous.wait(timeout=5)
        if shard.key == "a":
            raise RuntimeError("hard failure")
        checkpoint = CheckpointRef(
            executor.store.put_json({"cursor": shard.key}),
            shard.shard_hash,
            1,
            "2026-08-28T12:00:00.000000Z",
        )
        raise PreemptedError("preserve this cursor", checkpoint=checkpoint)

    operation = FunctionalOperation(
        planner=lambda _task: ("a", "b"),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )

    with pytest.raises(FleetDispatchError) as caught:
        executor.execute(task, operation)

    error = caught.value
    assert tuple(item.worker_id for item in error.failures) == (
        "worker-a",
        "worker-b",
    )
    assert tuple(item.error_type for item in error.failures) == (
        "FleetExecutionError",
        "PreemptedError",
    )
    assert error.checkpoint_manifest is not None
    assert len(error.checkpoint_manifest.checkpoints) == 1
    assert len(error.scheduled) == 2
    assert error.failures[1].interruption_receipt is not None
    assert error.to_dict()["checkpoint_manifest"] == error.checkpoint_manifest.to_dict()


def test_partial_dispatch_structurally_identifies_stopped_and_pending_shards(
    tmp_path,
) -> None:
    task = TaskSpec("test.partial-queue")
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("only-worker"),)),
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        if shard.key == "b":
            raise RuntimeError("stop this queue")
        return {"key": shard.key}

    operation = FunctionalOperation(
        planner=lambda _task: ("a", "b", "c"),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )

    with pytest.raises(FleetDispatchError) as caught:
        executor.execute(task, operation)

    error = caught.value
    assert tuple(item.shard_key for item in error.scheduled) == ("a", "b", "c")
    assert len(error.failures) == 1
    failure = error.failures[0]
    assert failure.shard_key == "b"
    assert failure.shard_ordinal == 1
    assert tuple(item.shard_key for item in failure.pending) == ("c",)
    assert tuple(item.ordinal for item in failure.pending) == (2,)
    plan = executor.plan(task, operation)
    assert executor.store.resolve(executor._shard_binding(plan.shards[0])) is not None
    assert executor.store.resolve(executor._shard_binding(plan.shards[2])) is None


def test_wrong_shard_checkpoint_fails_before_retry_or_binding(tmp_path) -> None:
    task = TaskSpec("test.wrong-checkpoint")
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("local"),)),
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=2),
    )

    def run(_task: TaskSpec, _shard: ShardSpec) -> dict[str, object]:
        artifact = executor.store.put_json({"checkpoint": "forged"})
        checkpoint = CheckpointRef(
            artifact,
            "f" * 64,
            0,
            "2026-08-28T12:00:00.000000Z",
        )
        raise PreemptedError("forged checkpoint", checkpoint=checkpoint)

    operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )

    with pytest.raises(FleetExecutionError, match="different shard"):
        executor.execute(task, operation)

    attempts = executor.attempt_records(task_hash=task.task_hash)
    assert len(attempts) == 1
    assert attempts[0].state is LeaseState.FAILED
    plan = executor.plan(task, operation)
    assert executor.store.resolve(executor._shard_binding(plan.shards[0])) is None


def test_budget_exhaustion_is_not_retried_without_explicit_policy(tmp_path) -> None:
    task = TaskSpec("test.budget")
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("local"),)),
        tmp_path,
        retry_policy=RetryPolicy(max_attempts=3, retry_budget_exhausted=False),
    )
    calls = 0

    def run(_task: TaskSpec, _shard: ShardSpec) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise BudgetExhaustedError(
            "local budget reached",
            progress_completed=3,
            progress_total=10,
            resources={"cpu_seconds": 7},
            spent={"wall_seconds": 9},
        )

    operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )

    with pytest.raises(BudgetExhaustedError, match="local budget reached") as caught:
        executor.execute(task, operation)

    assert calls == 1
    attempts = executor.attempt_records(task_hash=task.task_hash)
    assert len(attempts) == 1
    assert attempts[0].state is LeaseState.BUDGET_EXHAUSTED
    receipt = caught.value.receipt
    assert receipt is not None
    assert receipt.progress_completed == 3
    assert receipt.progress_total == 10
    assert receipt.resources.to_dict() == {"cpu_seconds": 7}
    assert receipt.spent.to_dict() == {"wall_seconds": 9}
    assert attempts[0].interruption_receipt == receipt
    replayed = InterruptionReceipt.from_dict(receipt.to_dict())
    assert replayed == receipt
    tampered = receipt.to_dict()
    tampered["progress_completed"] = "3"
    with pytest.raises(ValueError, match="progress_completed"):
        InterruptionReceipt.from_dict(tampered)


def test_expired_lease_cannot_publish_a_late_shard_result(tmp_path) -> None:
    class AdvancingClock:
        def __init__(self) -> None:
            self.now = datetime(2026, 8, 28, tzinfo=UTC)

        def __call__(self) -> datetime:
            return self.now

    clock = AdvancingClock()
    task = TaskSpec("test.expired")
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("local"),)),
        tmp_path,
        retry_policy=RetryPolicy(lease_seconds=1),
        clock=clock,
    )

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        clock.now += timedelta(seconds=2)
        return {"late": shard.key}

    operation = FunctionalOperation(
        planner=lambda _task: ("only",),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )

    with pytest.raises(FleetExecutionError, match="stale lease rejected"):
        executor.execute(task, operation)

    attempts = executor.attempt_records(task_hash=task.task_hash)
    assert len(attempts) == 1
    assert attempts[0].state is LeaseState.EXPIRED
    plan = executor.plan(task, operation)
    assert executor.store.resolve(executor._shard_binding(plan.shards[0])) is None


def test_concurrent_workers_report_occupancy_and_reduce_in_plan_order(tmp_path) -> None:
    task = TaskSpec(
        "test.concurrent",
        backend=BackendRequirement("python", capabilities=("exact",)),
    )
    executor = WorkerPoolExecutor(
        WorkerPool((_worker("small", cpu_cores=2), _worker("large", cpu_cores=4))),
        tmp_path,
        max_workers=2,
    )
    release = Event()
    both_started = Event()
    started: set[str] = set()
    start_lock = Lock()
    reductions: list[tuple[str, ...]] = []

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        if shard.key in {"a", "m"}:
            with start_lock:
                started.add(shard.key)
                if started == {"a", "m"}:
                    both_started.set()
            assert release.wait(timeout=5)
        return {"key": shard.key}

    def reduce(
        _task: TaskSpec,
        partials: Sequence[JSONValue],
    ) -> dict[str, object]:
        keys = tuple(cast(dict[str, JSONValue], partial)["key"] for partial in partials)
        assert all(isinstance(key, str) for key in keys)
        string_keys = cast(tuple[str, ...], keys)
        reductions.append(string_keys)
        return {"keys": list(string_keys)}

    operation = FunctionalOperation(
        planner=lambda _task: ("z", "a", "m"),
        runner=run,
        reducer=reduce,
    )
    outcomes: list[object] = []

    def execute() -> None:
        try:
            outcomes.append(executor.execute(task, operation))
        except BaseException as error:  # pragma: no cover - asserted below
            outcomes.append(error)

    thread = Thread(target=execute)
    thread.start()
    assert both_started.wait(timeout=5)
    live = executor.status(task_hash=task.task_hash)
    assert live.active_count == 2
    assert tuple(worker.state for worker in live.workers) == (
        WorkerState.BUSY,
        WorkerState.BUSY,
    )
    assert all(worker.active_task_hashes == (task.task_hash,) for worker in live.workers)
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(outcomes) == 1
    assert not isinstance(outcomes[0], BaseException)
    fleet_run = outcomes[0]
    assert reductions == [("a", "m", "z")]
    receipt = executor.receipt_for(fleet_run)  # type: ignore[arg-type]
    assert tuple(
        (assignment.shard_key, assignment.worker_id) for assignment in receipt.assignments
    ) == (("a", "small"), ("m", "large"), ("z", "small"))
    assert executor.result_value(fleet_run) == {"keys": ["a", "m", "z"]}  # type: ignore[arg-type]


def test_automatic_pool_advertises_real_one_core_slots_and_runs_them_in_parallel(
    tmp_path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(fleet_builtins.os, "cpu_count", lambda: 2)
    workers = automatic_local_worker_pool()
    assert tuple(worker.id for worker in workers.workers) == (
        "local-python-000",
        "local-python-001",
    )
    assert all(worker.resources.cpu_cores == 1 for worker in workers.workers)
    rendezvous = Barrier(2)

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, str]:
        rendezvous.wait(timeout=5)
        return {"key": shard.key}

    operation = FunctionalOperation(
        planner=lambda _task: ("a", "b"),
        runner=run,
        reducer=lambda _task, partials: {"partials": partials},
    )
    executor = WorkerPoolExecutor(workers, tmp_path)
    executor.execute(TaskSpec("test.auto-parallel"), operation)

    multi_core = TaskSpec(
        "test.multi-core",
        resources=ResourceHint(cpu_cores=2),
    )
    with pytest.raises(NoEligibleWorkerError, match="insufficient CPU cores"):
        executor.execute(multi_core, operation)
