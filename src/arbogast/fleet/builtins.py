"""Small, explicit trusted operations for the automatic local fleet.

The automatic CLI fleet intentionally exposes only operations defined here.
It does not import a callable named by campaign data.  The built-in echo
operation is operational plumbing: it records canonical task input and returns
``UNKNOWN``; it never claims a mathematical outcome.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Sequence

from arbogast.backends import BackendStatus
from arbogast.formats import FrozenMapping, JSONValue

from .execution import FunctionalOperation
from .models import ResourceHint, ShardSpec, TaskSpec
from .registry import FleetOperationRegistry
from .workers import Worker, WorkerPool

LOCAL_ECHO_OPERATION = "fleet.echo.v1"


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

    operation = FunctionalOperation(
        planner=lambda _task: ("all",),
        runner=_echo_run,
        reducer=_echo_reduce,
        verifier=_echo_verify,
    )
    return FleetOperationRegistry({LOCAL_ECHO_OPERATION: operation})


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
        capabilities=("canonical-json", "control-plane", "local-execution"),
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
