from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arbogast.fleet import (
    ArtifactRef,
    BackendRequirement,
    FleetPlan,
    FleetSpecError,
    ResourceHint,
    ShardSpec,
    TaskSpec,
    deterministic_plan,
)


def test_task_hash_binds_semantics_but_not_resource_scheduling_hints() -> None:
    baseline = TaskSpec(
        "cohom.h1",
        input_refs=("sha256:input",),
        parameters={"degree": 1, "blocks": [2, 1]},
        backend=BackendRequirement("gap", version="4.14", capabilities=("finite-groups",)),
        resources=ResourceHint(cpu_cores=1, memory_mb=64),
        seed=7,
    )
    reordered = TaskSpec(
        "cohom.h1",
        input_refs=("sha256:input",),
        parameters={"blocks": [2, 1], "degree": 1},
        backend=BackendRequirement("gap", version="4.14", capabilities=("finite-groups",)),
        resources=ResourceHint(cpu_cores=16, memory_mb=4096),
        seed=7,
    )

    assert baseline.task_hash == reordered.task_hash
    assert TaskSpec.from_dict(baseline.to_dict()) == baseline
    changed_backend = TaskSpec(
        baseline.operation,
        baseline.input_refs,
        baseline.parameters,
        BackendRequirement("gap", version="4.15", capabilities=("finite-groups",)),
        seed=baseline.seed,
    )
    assert baseline.task_hash != changed_backend.task_hash
    assert (
        baseline.task_hash
        != TaskSpec(
            baseline.operation,
            baseline.input_refs,
            baseline.parameters,
            baseline.backend,
            seed=8,
        ).task_hash
    )


def test_task_parameters_are_deeply_immutable() -> None:
    parameters = {"rows": [1, 2]}
    task = TaskSpec("linear.rank", parameters=parameters)
    parameters["rows"].append(3)

    assert task.parameters.to_dict() == {"rows": [1, 2]}
    with pytest.raises(FrozenInstanceError):
        task.operation = "changed"  # type: ignore[misc]


def test_task_unicode_normalization_is_consistent_with_equality_and_hash() -> None:
    decomposed = TaskSpec("demo", parameters={"e\u0301": "Cafe\u0301"})
    composed = TaskSpec("demo", parameters={"\u00e9": "Caf\u00e9"})

    assert decomposed == composed
    assert hash(decomposed) == hash(composed)
    assert decomposed.task_hash == composed.task_hash


def test_protocol_from_dict_rejects_noncanonical_type_coercions() -> None:
    task = TaskSpec("demo")
    with pytest.raises(FleetSpecError, match="seed"):
        TaskSpec.from_dict({**task.to_dict(), "seed": True})
    with pytest.raises(FleetSpecError, match="cpu_cores"):
        TaskSpec.from_dict(
            {
                **task.to_dict(),
                "resources": {**task.resources.to_dict(), "cpu_cores": "2"},
                "task_hash": None,
            }
        )
    reference = ArtifactRef("0" * 64, 0)
    with pytest.raises(FleetSpecError, match="size"):
        ArtifactRef.from_dict({**reference.to_dict(), "size": "0"})
    shard = ShardSpec(task.task_hash, "a")
    with pytest.raises(FleetSpecError, match="ordinal"):
        ShardSpec.from_dict({**shard.to_dict(), "ordinal": False})
    with pytest.raises(FleetSpecError, match="memory_mb"):
        ResourceHint(memory_mb=True)


def test_protocol_from_dict_rejects_unknown_fields_and_schema_tampering() -> None:
    task = TaskSpec("demo")
    with pytest.raises(FleetSpecError, match="missing or unknown"):
        TaskSpec.from_dict({**task.to_dict(), "unexpected": None})
    with pytest.raises(FleetSpecError, match="unsupported task schema"):
        TaskSpec.from_dict({**task.to_dict(), "schema": "arbogast.fleet.task.v0"})
    with pytest.raises(FleetSpecError, match="task_hash must be a string"):
        TaskSpec.from_dict({**task.to_dict(), "task_hash": None})

    reference = ArtifactRef("0" * 64, 0)
    with pytest.raises(FleetSpecError, match="unsupported artifact-reference schema"):
        ArtifactRef.from_dict({**reference.to_dict(), "schema": "arbogast.fleet.artifact.v0"})


def test_plan_sorts_explicit_keys_and_rejects_duplicates_or_wrong_task() -> None:
    task = TaskSpec("hurwitz.enumerate")
    plan = deterministic_plan(task, ("z", "a", "m"))

    assert tuple(shard.key for shard in plan.shards) == ("a", "m", "z")
    assert tuple(shard.ordinal for shard in plan.shards) == (0, 1, 2)
    with pytest.raises(FleetSpecError, match="unique"):
        deterministic_plan(task, ("same", "same"))
    with pytest.raises(FleetSpecError, match="task hash"):
        FleetPlan(task, (ShardSpec("different", "a"),))
