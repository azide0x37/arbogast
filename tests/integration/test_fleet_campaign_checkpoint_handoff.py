from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from threading import Barrier, Lock

from arbogast.backends import BackendStatus
from arbogast.campaign import Campaign, Outcome, RecommendationAction, Strategy, TargetSpec
from arbogast.fleet import (
    CheckpointManifest,
    CheckpointRef,
    FleetOperationRegistry,
    FunctionalOperation,
    PreemptedError,
    RetryPolicy,
    ShardSpec,
    TaskSpec,
    Worker,
    WorkerPool,
    WorkerPoolExecutor,
)
from arbogast.formats import JSONValue


def test_campaign_reloads_and_resumes_a_full_typed_worker_manifest(
    tmp_path: Path,
) -> None:
    target = TargetSpec("case:multi-shard-resume")
    strategy = Strategy(
        "enumerate",
        "test.campaign-multi-resume",
        "resume every cooperatively checkpointed worker queue",
    )
    workers = WorkerPool(
        (
            Worker("worker-a", (BackendStatus("python", True, ()),)),
            Worker("worker-b", (BackendStatus("python", True, ()),)),
        )
    )
    store = tmp_path / "fleet"
    first_executor = WorkerPoolExecutor(
        workers,
        store,
        max_workers=2,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    rendezvous = Barrier(2)
    resumed: list[str] = []
    resumed_lock = Lock()

    def run(_task: TaskSpec, shard: ShardSpec) -> dict[str, object]:
        rendezvous.wait(timeout=5)
        checkpoint = CheckpointRef(
            first_executor.store.put_json({"cursor": shard.key}),
            shard.shard_hash,
            1,
            "2026-08-28T12:00:00.000000Z",
        )
        raise PreemptedError("cooperative laptop-close checkpoint", checkpoint=checkpoint)

    def resume(
        _task: TaskSpec,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> dict[str, object]:
        with resumed_lock:
            resumed.append(shard.key)
        return {"cursor": checkpoint.sequence, "key": shard.key}

    def reduce(
        _task: TaskSpec,
        partials: Sequence[JSONValue],
    ) -> dict[str, object]:
        return {"outcome": "UNKNOWN", "partials": partials}

    operation = FunctionalOperation(
        planner=lambda _task: ("right", "left"),
        runner=run,
        reducer=reduce,
        resumer=resume,
    )
    registry = FleetOperationRegistry({strategy.operation: operation})
    campaign = Campaign(
        "multi-shard-resume",
        objective="Resume typed local checkpoints without trusting serialized code",
        targets=(target,),
        strategies=(strategy,),
        executor=first_executor,
        operation_registry=registry,
    )

    interrupted = campaign.dispatch()

    assert interrupted.outcome is Outcome.PREEMPTED
    raw_manifest = interrupted.details.to_dict()["checkpoint_manifest"]
    assert isinstance(raw_manifest, dict)
    manifest = CheckpointManifest.from_dict(raw_manifest)
    assert len(manifest.checkpoints) == 2
    artifact = tmp_path / "campaign.json"
    campaign.save(artifact)

    fresh_executor = WorkerPoolExecutor(
        workers,
        store,
        max_workers=2,
        retry_policy=RetryPolicy(max_attempts=1),
        operation_registry=registry,
    )
    restored = Campaign.load(
        artifact,
        executor=fresh_executor,
        operation_registry=registry,
    )
    recommendation = restored.recommend().recommendations[0]
    assert recommendation.action is RecommendationAction.RESUME

    completed = restored.dispatch(recommendation)

    assert completed.outcome is Outcome.UNKNOWN
    assert sorted(resumed) == ["left", "right"]
    receipt = completed.details.to_dict()["fleet_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["checkpoint_resumed"] is True
    assert len(receipt["checkpoint_resumed_shards"]) == 2
    assert receipt["cached_shard_hashes"] == []
    assert receipt["result_cache_resumed"] is False
