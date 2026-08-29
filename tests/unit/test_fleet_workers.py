from __future__ import annotations

import pytest

from arbogast.backends import BackendStatus
from arbogast.fleet import (
    BackendRequirement,
    BudgetExhaustedError,
    CheckpointRef,
    FleetExecutionError,
    FleetInterruption,
    FunctionalOperation,
    LeaseRecord,
    LeaseState,
    LocalExecutor,
    PreemptedError,
    ResourceHint,
    SchedulerProtocol,
    ShardSpec,
    TaskSpec,
    Worker,
    WorkerPool,
)


def _python_status() -> BackendStatus:
    return BackendStatus(
        name="python",
        available=True,
        capabilities=("control-plane", "small-exact-computations"),
        version="3.13",
    )


def test_worker_pool_matches_capabilities_and_selects_smallest_sufficient() -> None:
    small = Worker(
        "small",
        (_python_status(),),
        resources=ResourceHint(cpu_cores=2, memory_mb=256),
    )
    large = Worker(
        "large",
        (_python_status(),),
        resources=ResourceHint(cpu_cores=8, memory_mb=2048),
    )
    task = TaskSpec(
        "exact.small",
        backend=BackendRequirement("python", capabilities=("small-exact-computations",)),
        resources=ResourceHint(cpu_cores=2, memory_mb=128),
    )

    assert WorkerPool((large, small)).select(task).id == "small"
    too_large = TaskSpec(
        "exact.large",
        resources=ResourceHint(cpu_cores=32, memory_mb=8192),
    )
    assert not any(match.eligible for match in WorkerPool((small, large)).matches(too_large))


def test_leases_preserve_preemption_and_budget_exhaustion_as_operational_states() -> None:
    task = TaskSpec("demo.lease")
    shard = ShardSpec(task.task_hash, "0")
    worker = Worker("local", (_python_status(),))
    lease = SchedulerProtocol().lease(
        WorkerPool((worker,)),
        task,
        shard,
        attempt=0,
        acquired_at="2026-08-28T12:00:00Z",
        expires_at="2026-08-28T12:05:00Z",
    )

    active = lease.transition(LeaseState.ACTIVE)
    preempted = active.transition(LeaseState.PREEMPTED, detail="host reclaimed")
    assert preempted.state is LeaseState.PREEMPTED
    assert preempted.terminal
    with pytest.raises(ValueError, match="invalid lease transition"):
        preempted.transition(LeaseState.COMPLETED)
    assert BudgetExhaustedError("limit").reason.value == "budget_exhausted"


def test_local_executor_does_not_collapse_preemption_into_generic_failure(tmp_path) -> None:
    operation = FunctionalOperation(
        planner=lambda task: ("only",),
        runner=lambda task, shard: (_ for _ in ()).throw(PreemptedError("spot reclaim")),
        reducer=lambda task, values: {},
    )
    with pytest.raises(FleetInterruption) as caught:
        LocalExecutor(tmp_path).execute(TaskSpec("demo.preempted"), operation)
    assert caught.value.reason.value == "preempted"


def test_local_executor_rejects_checkpoint_bound_to_another_shard(tmp_path) -> None:
    executor = LocalExecutor(tmp_path)
    artifact = executor.store.put_json({"checkpoint": 1})
    checkpoint = CheckpointRef(
        artifact,
        "f" * 64,
        0,
        "2026-08-28T12:00:00.000000Z",
    )
    operation = FunctionalOperation(
        planner=lambda task: ("only",),
        runner=lambda task, shard: (_ for _ in ()).throw(
            PreemptedError("spot reclaim", checkpoint=checkpoint)
        ),
        reducer=lambda task, values: {},
    )

    with pytest.raises(FleetExecutionError, match="bound to a different shard"):
        executor.execute(TaskSpec("demo.bad-checkpoint"), operation)


@pytest.mark.parametrize(
    "created_at",
    (
        "not-a-timestamp",
        "2026-08-28T12:00:00Z",
        "2026-08-28T12:00:00.1Z",
        "2026-08-28T12:00:00.000000+00:00",
        "2026-08-28T07:00:00.000000-05:00",
    ),
)
def test_checkpoint_timestamp_rejects_noncanonical_utc_forms(tmp_path, created_at: str) -> None:
    artifact = LocalExecutor(tmp_path).store.put_json({"checkpoint": 1})

    with pytest.raises(ValueError, match="canonical UTC timestamp"):
        CheckpointRef(artifact, "a" * 64, 1, created_at)


def test_checkpoint_timestamp_strict_roundtrip(tmp_path) -> None:
    artifact = LocalExecutor(tmp_path).store.put_json({"checkpoint": 1})
    checkpoint = CheckpointRef(
        artifact,
        "a" * 64,
        1,
        "2026-08-28T12:00:00.123456Z",
    )

    assert CheckpointRef.from_dict(checkpoint.to_dict()) == checkpoint

    tampered = checkpoint.to_dict()
    tampered["created_at"] = "2026-08-28T12:00:00.123456+00:00"
    with pytest.raises(ValueError, match="canonical UTC timestamp"):
        CheckpointRef.from_dict(tampered)


def test_worker_matching_enforces_wall_time_capacity() -> None:
    worker = Worker(
        "short-queue",
        (_python_status(),),
        resources=ResourceHint(cpu_cores=2, wall_time_seconds=60),
    )
    task = TaskSpec(
        "demo.long",
        resources=ResourceHint(cpu_cores=1, wall_time_seconds=120),
    )

    match = worker.match(task)
    assert not match.eligible
    assert "insufficient wall-time capacity" in match.reasons


def test_lease_protocol_rejects_non_integral_counters_and_cross_task_shards() -> None:
    artifact = LocalExecutor().store.put_json({"checkpoint": 1})
    with pytest.raises(ValueError, match="sequence"):
        CheckpointRef(
            artifact,
            "a" * 64,
            1.5,  # type: ignore[arg-type]
            "2026-08-28T12:00:00.000000Z",
        )
    with pytest.raises(ValueError, match="attempt"):
        LeaseRecord(
            "lease:id",
            "a" * 64,
            "b" * 64,
            "worker",
            2.5,  # type: ignore[arg-type]
            "2026-08-28T12:00:00Z",
            "2026-08-28T12:05:00Z",
        )

    task_a = TaskSpec("demo.a")
    task_b = TaskSpec("demo.b")
    shard_a = ShardSpec(task_a.task_hash, "only")
    pool = WorkerPool((Worker("local", (_python_status(),)),))
    with pytest.raises(ValueError, match="different task"):
        SchedulerProtocol().lease(
            pool,
            task_b,
            shard_a,
            attempt=0,
            acquired_at="2026-08-28T12:00:00Z",
            expires_at="2026-08-28T12:05:00Z",
        )


def test_worker_backend_and_lease_protocol_objects_reject_wrong_runtime_types() -> None:
    with pytest.raises(ValueError, match="available must be boolean"):
        BackendStatus("python", "yes", ("cap",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tuple"):
        BackendStatus("python", True, ["cap"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="worker id"):
        Worker(7, (_python_status(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="WorkerState"):
        Worker("worker", (_python_status(),), state="available")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="LeaseState"):
        LeaseRecord(
            "lease:id",
            "a" * 64,
            "b" * 64,
            "worker",
            0,
            "2026-08-28T12:00:00Z",
            "2026-08-28T12:05:00Z",
            state="active",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="timestamps"):
        LeaseRecord(
            "lease:id",
            "a" * 64,
            "b" * 64,
            "worker",
            0,
            "",
            "2026-08-28T12:05:00Z",
        )
