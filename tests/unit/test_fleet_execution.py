from __future__ import annotations

import json
from collections.abc import Sequence
from threading import Barrier, Thread
from typing import cast

import pytest

from arbogast.fleet import (
    ArtifactBinding,
    ArtifactConflictError,
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    EvidenceState,
    FleetExecutionError,
    FleetPlan,
    FleetRun,
    FunctionalOperation,
    LocalExecutor,
    ShardResult,
    ShardSpec,
    TaskSpec,
)
from arbogast.formats import JSONValue


def test_content_store_deduplicates_and_rejects_key_rebinding(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    first = store.put_json({"answer": 42})
    second = store.put_json({"answer": 42})
    other = store.put_json({"answer": 43})

    assert first == second
    assert store.get_json(first) == {"answer": 42}
    store.bind("task:key", first, EvidenceState.DISCOVERY)
    with pytest.raises(ArtifactConflictError):
        store.bind("task:key", other, EvidenceState.DISCOVERY)
    with pytest.raises(ArtifactStoreError, match="verify_and_promote"):
        store.bind("task:forged", first, EvidenceState.VERIFICATION)


def test_concurrent_binding_publication_cannot_silently_rebind_a_key(tmp_path) -> None:
    barrier = Barrier(2)

    class BarrierStore(ArtifactStore):
        def _create_binding(self, binding: ArtifactBinding) -> ArtifactBinding:
            barrier.wait()
            return super()._create_binding(binding)

    first_store = BarrierStore(tmp_path)
    second_store = BarrierStore(tmp_path)
    first = first_store.put_json({"answer": 1})
    second = second_store.put_json({"answer": 2})
    outcomes: list[str] = []

    def publish(store: ArtifactStore, artifact: ArtifactRef) -> None:
        try:
            store.bind("shared:key", artifact)
        except ArtifactConflictError:
            outcomes.append("conflict")
        else:
            outcomes.append("published")

    threads = (
        Thread(target=publish, args=(first_store, first)),
        Thread(target=publish, args=(second_store, second)),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["conflict", "published"]
    winner = first_store.resolve("shared:key")
    assert winner is not None
    assert winner.artifact in {first, second}


def test_editing_binding_state_cannot_forge_verification(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = store.put_json({"candidate": True})
    key = "fleet:result:" + "0" * 64
    store.bind(key, artifact)
    binding_path = store._binding_path(key)
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["state"] = "verification"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(ArtifactStoreError, match="verification receipt"):
        store.resolve(key, required_state=EvidenceState.VERIFICATION)


def test_local_executor_is_deterministic_resumable_and_fail_closed(tmp_path) -> None:
    calls: list[str] = []
    reductions: list[tuple[str, ...]] = []

    def runner(task: TaskSpec, shard: ShardSpec) -> object:
        calls.append(shard.key)
        return {"key": shard.key, "operation": task.operation}

    def reducer(task: TaskSpec, values: Sequence[JSONValue]) -> object:
        keys = tuple(str(cast(dict[str, JSONValue], value)["key"]) for value in values)
        reductions.append(keys)
        return {"keys": list(keys), "operation": task.operation}

    operation = FunctionalOperation(
        planner=lambda task: ("z", "a"),
        runner=runner,
        reducer=reducer,
        verifier=lambda task, result: result == {"keys": ["a", "z"], "operation": task.operation},
    )
    executor = LocalExecutor(tmp_path, max_workers=2)
    task = TaskSpec("demo.operation")

    first = executor.execute(task, operation, verify=True)
    second = executor.execute(task, operation, verify=True)

    assert sorted(calls) == ["a", "z"]
    assert reductions == [("a", "z")]
    assert first.state is EvidenceState.VERIFICATION
    assert second.state is EvidenceState.VERIFICATION
    assert second.resumed
    assert all(receipt.resumed for receipt in second.shards)


def test_verification_requires_literal_true(tmp_path) -> None:
    operation = FunctionalOperation(
        planner=lambda task: ("only",),
        runner=lambda task, shard: {"candidate": shard.key},
        reducer=lambda task, values: {"candidate": "only"},
        verifier=cast(object, lambda task, result: None),
    )

    with pytest.raises(FleetExecutionError, match="literal true"):
        LocalExecutor(tmp_path).execute(TaskSpec("demo.none-verifier"), operation, verify=True)


def test_result_cache_is_plan_bound_and_cached_results_are_reverified(tmp_path) -> None:
    task = TaskSpec("demo.plan-bound")
    first_verifications: list[object] = []
    second_verifications: list[object] = []
    first = FunctionalOperation(
        planner=lambda task: ("old-shard",),
        runner=lambda task, shard: {"key": shard.key},
        reducer=lambda task, values: {"plan": "old"},
        verifier=lambda task, result: not first_verifications.append(result),
    )
    second = FunctionalOperation(
        planner=lambda task: ("new-shard",),
        runner=lambda task, shard: {"key": shard.key},
        reducer=lambda task, values: {"plan": "new"},
        verifier=lambda task, result: not second_verifications.append(result),
    )
    executor = LocalExecutor(tmp_path)

    first_run = executor.execute(task, first, verify=True)
    second_run = executor.execute(task, second, verify=True)

    assert executor.result_value(first_run) == {"plan": "old"}
    assert executor.result_value(second_run) == {"plan": "new"}
    assert first_run.result != second_run.result
    assert first_verifications == [{"plan": "old"}]
    assert second_verifications == [{"plan": "new"}]

    rejecting = FunctionalOperation(
        planner=lambda task: ("new-shard",),
        runner=lambda task, shard: {"key": shard.key},
        reducer=lambda task, values: {"plan": "new"},
        verifier=lambda task, result: False,
    )
    with pytest.raises(FleetExecutionError, match="literal true"):
        executor.execute(task, rejecting, verify=True)


def test_reduce_rejects_cross_task_plans_and_unbound_shard_receipts(tmp_path) -> None:
    executor = LocalExecutor(tmp_path)
    operation = FunctionalOperation(
        planner=lambda task: ("only",),
        runner=lambda task, shard: {"task": task.operation},
        reducer=lambda task, values: {"task": task.operation},
    )
    task_a = TaskSpec("demo.a")
    task_b = TaskSpec("demo.b")
    plan_a = executor.plan(task_a, operation)
    shards_a = executor.run(task_a, operation, plan_a)

    with pytest.raises(FleetExecutionError, match="different task"):
        executor.reduce(task_b, operation, plan_a, shards_a)
    assert executor.store.resolve(executor._result_binding(task_b, plan_a)) is None

    plan_b = FleetPlan(task_b, (ShardSpec(task_b.task_hash, "injected"),))
    injected = executor.store.put_json({"not": "executed"})
    receipt = ShardResult(plan_b.shards[0], injected)
    with pytest.raises(FleetExecutionError, match="no bound execution artifact"):
        executor.reduce(task_b, operation, plan_b, (receipt,))


def test_result_value_replays_run_result_and_shard_bindings(tmp_path) -> None:
    executor = LocalExecutor(tmp_path)
    operation = FunctionalOperation(
        planner=lambda task: ("only",),
        runner=lambda task, shard: {"partial": shard.key},
        reducer=lambda task, values: {"honest": True},
    )
    task = TaskSpec("demo.bound-run")
    honest = executor.execute(task, operation)
    forged_artifact = executor.store.put_json(
        {"outcome": "PREEMPTED", "checkpoint_ref": "sha256:forged"}
    )
    forged = FleetRun(
        task=honest.task,
        plan=honest.plan,
        shards=honest.shards,
        result=forged_artifact,
        state=EvidenceState.VERIFICATION,
    )

    with pytest.raises(FleetExecutionError, match="deterministic store binding"):
        executor.result_value(forged)


def test_verification_promotion_rejects_mismatched_result_task_hash(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    task_hash = "a" * 64
    other_hash = "b" * 64
    key = f"fleet:result:{task_hash}"
    artifact = store.put_json({"candidate": True})
    store.bind(key, artifact)
    calls: list[object] = []

    with pytest.raises(ArtifactStoreError, match="does not match result binding"):
        store.verify_and_promote(
            key,
            artifact,
            lambda value: not calls.append(value),
            verifier_name="tests.verifier",
            task_hash=other_hash,
        )
    assert calls == []
    assert store.resolve(key).state is EvidenceState.DISCOVERY  # type: ignore[union-attr]
