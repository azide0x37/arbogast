"""Deterministic local execution of the fleet mathematical task protocol."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

from arbogast.formats import JSONValue, normalize_json

from .artifacts import ArtifactStore
from .leases import CheckpointRef, FleetInterruption
from .models import (
    EvidenceState,
    FleetPlan,
    FleetRun,
    ShardResult,
    ShardSpec,
    TaskSpec,
)
from .registry import FleetOperationRegistry

PartialT = TypeVar("PartialT")
ResultT = TypeVar("ResultT")


class FleetExecutionError(RuntimeError):
    """Raised when planning, execution, reduction, or verification fails."""


class VerificationUnavailableError(FleetExecutionError):
    """Raised when verification was requested but no verifier exists."""


class ResumeUnavailableError(FleetExecutionError):
    """Raised when a checkpoint exists but the operation cannot resume it."""


class FleetOperation(Protocol):
    """Scheduler-independent ``plan/run/reduce`` operation protocol."""

    def plan(self, task: TaskSpec) -> FleetPlan | Iterable[ShardSpec | str]: ...

    def run(self, task: TaskSpec, shard: ShardSpec) -> Any: ...

    def reduce(self, task: TaskSpec, partials: Sequence[JSONValue]) -> Any: ...


class ResumableFleetOperation(FleetOperation, Protocol):
    """An operation with an explicit checkpoint-resume implementation."""

    def resume(
        self,
        task: TaskSpec,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class FunctionalOperation(Generic[PartialT, ResultT]):
    """Convenience adapter for functions implementing the fleet protocol."""

    planner: Callable[[TaskSpec], FleetPlan | Iterable[ShardSpec | str]]
    runner: Callable[[TaskSpec, ShardSpec], PartialT]
    reducer: Callable[[TaskSpec, Sequence[JSONValue]], ResultT]
    verifier: Callable[[TaskSpec, JSONValue], bool] | None = None
    resumer: Callable[[TaskSpec, ShardSpec, CheckpointRef], PartialT] | None = None
    closure_verifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the central verifiers that may certify target closure.

        The fleet-level ``verifier`` checks a reduced result before promotion.
        ``closure_verifiers`` is a separate, data-only contract naming the
        central certificate verifiers that can justify a mathematical closure
        emitted by that result.  Keeping the default empty preserves existing
        operation construction while making verified campaign plans derive
        their verifier requirements instead of trusting a caller-supplied list.
        """

        names = self.closure_verifiers
        if not isinstance(names, tuple) or any(
            not isinstance(name, str) or not name or name != name.strip() for name in names
        ):
            raise ValueError("closure_verifiers must be a tuple of non-empty canonical strings")
        if names != tuple(sorted(set(names))):
            raise ValueError("closure_verifiers must be sorted and unique")

    def plan(self, task: TaskSpec) -> FleetPlan | Iterable[ShardSpec | str]:
        return self.planner(task)

    def run(self, task: TaskSpec, shard: ShardSpec) -> PartialT:
        return self.runner(task, shard)

    def reduce(self, task: TaskSpec, partials: Sequence[JSONValue]) -> ResultT:
        return self.reducer(task, partials)

    def verify(self, task: TaskSpec, result: JSONValue) -> bool:
        if self.verifier is None:
            raise VerificationUnavailableError("operation has no verification function")
        return self.verifier(task, result)

    def resume(
        self,
        task: TaskSpec,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> PartialT:
        if self.resumer is None:
            raise ResumeUnavailableError("operation has no checkpoint-resume function")
        return self.resumer(task, shard, checkpoint)


class LocalExecutor:
    """Run fleet tasks locally while preserving fleet protocol semantics.

    Results always pass through canonical JSON before reduction.  Consequently
    a resumed run and a fresh run provide exactly the same values to the
    reducer.  ``max_workers`` only affects scheduling; reduction order remains
    the plan's canonical shard-key order.
    """

    def __init__(
        self,
        store: ArtifactStore | str | Path | None = None,
        *,
        max_workers: int = 1,
        operation_registry: FleetOperationRegistry | None = None,
    ) -> None:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError("max_workers must be an integer >= 1")
        self.max_workers = max_workers
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        if store is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="arbogast-fleet-")
            self.store = ArtifactStore(self._temporary.name)
        elif isinstance(store, ArtifactStore):
            self.store = store
        else:
            self.store = ArtifactStore(store)
        if operation_registry is not None and not isinstance(
            operation_registry, FleetOperationRegistry
        ):
            raise TypeError("operation_registry must be a FleetOperationRegistry or None")
        self.operation_registry = operation_registry

    @staticmethod
    def _shard_binding(shard: ShardSpec) -> str:
        return f"fleet:shard:{shard.shard_hash}"

    @staticmethod
    def _result_binding(task: TaskSpec, plan: FleetPlan) -> str:
        return f"fleet:result:{task.task_hash}:{plan.plan_hash}"

    def plan(self, task: TaskSpec, operation: FleetOperation) -> FleetPlan:
        planned = operation.plan(task)
        if isinstance(planned, FleetPlan):
            if planned.task != task:
                raise FleetExecutionError("operation returned a plan for a different task")
            # Reconstructing enforces canonical order even for external plans.
            return FleetPlan(task, planned.shards)
        shards: list[ShardSpec] = []
        for item in planned:
            if isinstance(item, str):
                shards.append(ShardSpec(task.task_hash, item))
            elif isinstance(item, ShardSpec):
                shards.append(item)
            else:
                raise FleetExecutionError(
                    "operation plan entries must be explicit shard-key strings or ShardSpec objects"
                )
        return FleetPlan(task, shards)

    def supports_checkpoint_resume(self, task: TaskSpec | None = None) -> bool:
        """Report whether this executor owns replayable typed checkpoint custody.

        The basic local executor validates cooperative checkpoint content but
        deliberately does not persist scheduler custody, so it cannot promise
        resume after Campaign reload.
        """

        if task is not None and not isinstance(task, TaskSpec):
            raise TypeError("task must be a TaskSpec or None")
        return False

    def _run_one(
        self,
        task: TaskSpec,
        operation: FleetOperation,
        shard: ShardSpec,
    ) -> ShardResult:
        key = self._shard_binding(shard)
        cached = self.store.resolve(key, required_state=EvidenceState.DISCOVERY)
        if cached is not None:
            return ShardResult(
                shard=shard,
                artifact=cached.artifact,
                state=cached.state,
                resumed=True,
            )
        try:
            value = normalize_json(operation.run(task, shard))
        except FleetInterruption as error:
            # Preserve preemption/budget exhaustion as operational signals.
            # They are neither generic failures nor mathematical outcomes.
            if error.checkpoint is not None:
                self.validate_checkpoint(shard, error.checkpoint, cause=error)
            raise
        except Exception as error:
            raise FleetExecutionError(f"shard {shard.key!r} failed: {error}") from error
        artifact = self.store.put_json(value)
        binding = self.store.bind(key, artifact, EvidenceState.DISCOVERY)
        return ShardResult(shard=shard, artifact=artifact, state=binding.state, resumed=False)

    def run(
        self,
        task: TaskSpec,
        operation: FleetOperation,
        plan: FleetPlan,
    ) -> tuple[ShardResult, ...]:
        """Execute or resume every shard, returning canonical plan order."""

        if plan.task != task:
            raise FleetExecutionError("cannot run a plan for a different task")
        if self.max_workers == 1 or len(plan.shards) < 2:
            return tuple(self._run_one(task, operation, shard) for shard in plan.shards)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            # executor.map preserves input order even if completion order differs.
            results = pool.map(
                lambda shard: self._run_one(task, operation, shard),
                plan.shards,
            )
            return tuple(results)

    def reduce(
        self,
        task: TaskSpec,
        operation: FleetOperation,
        plan: FleetPlan,
        shards: Sequence[ShardResult],
        *,
        verify: bool = False,
    ) -> FleetRun:
        """Reduce ordered shard artifacts and optionally verify the result."""

        if plan.task != task:
            raise FleetExecutionError("cannot reduce a plan for a different task")
        shard_tuple = tuple(shards)
        if tuple(item.shard for item in shard_tuple) != plan.shards:
            raise FleetExecutionError("shard results are not in deterministic plan order")
        for item in shard_tuple:
            binding = self.store.resolve(
                self._shard_binding(item.shard),
                required_state=EvidenceState.DISCOVERY,
            )
            if binding is None:
                raise FleetExecutionError(
                    f"shard {item.shard.key!r} has no bound execution artifact"
                )
            if binding.artifact != item.artifact or not binding.state.satisfies(item.state):
                raise FleetExecutionError(
                    f"shard {item.shard.key!r} receipt does not match its bound artifact"
                )
        result_key = self._result_binding(task, plan)
        cached = self.store.resolve(result_key, required_state=EvidenceState.DISCOVERY)
        resumed = cached is not None
        if cached is None:
            partials = tuple(self.store.get_json(item.artifact) for item in shard_tuple)
            try:
                reduced = normalize_json(operation.reduce(task, partials))
            except Exception as error:
                raise FleetExecutionError(f"task reduction failed: {error}") from error
            result_ref = self.store.put_json(reduced)
            binding = self.store.bind(result_key, result_ref, EvidenceState.DISCOVERY)
        else:
            result_ref = cached.artifact
            binding = cached

        if verify:
            verifier = getattr(operation, "verify", None)
            if verifier is None or not callable(verifier):
                raise VerificationUnavailableError(
                    f"operation {task.operation!r} does not provide an explicit verifier"
                )
            verifier_name = (
                f"{getattr(verifier, '__module__', '<unknown>')}."
                f"{getattr(verifier, '__qualname__', type(verifier).__qualname__)}"
            )
            try:
                binding = self.store.verify_and_promote(
                    result_key,
                    result_ref,
                    lambda result: verifier(task, result),
                    verifier_name=verifier_name,
                    task_hash=task.task_hash,
                )
            except VerificationUnavailableError:
                raise
            except Exception as error:
                raise FleetExecutionError(f"task verification failed: {error}") from error

        return FleetRun(
            task=task,
            plan=plan,
            shards=shard_tuple,
            result=result_ref,
            state=binding.state,
            resumed=resumed,
        )

    def execute(
        self,
        task: TaskSpec,
        operation: FleetOperation,
        *,
        verify: bool = False,
    ) -> FleetRun:
        """Plan, run, reduce, and optionally verify a task."""

        plan = self.plan(task, operation)
        shards = self.run(task, operation, plan)
        return self.reduce(task, operation, plan, shards, verify=verify)

    def execute_registered(
        self,
        task: TaskSpec,
        *,
        registry: FleetOperationRegistry | None = None,
        verify: bool = False,
    ) -> FleetRun:
        """Resolve ``task.operation`` through a trusted runtime registry.

        The registry is never reconstructed from the serialized task.  Callers
        must inject it either here or when constructing the executor.
        """

        resolved_registry = self.operation_registry if registry is None else registry
        if resolved_registry is None:
            from .registry import UnknownFleetOperationError

            raise UnknownFleetOperationError(task.operation)
        if not isinstance(resolved_registry, FleetOperationRegistry):
            raise TypeError("registry must be a FleetOperationRegistry")
        return self.execute(task, resolved_registry.resolve(task.operation), verify=verify)

    def validate_checkpoint(
        self,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
        *,
        cause: BaseException | None = None,
    ) -> None:
        """Validate shard ownership and local content custody for a checkpoint."""

        if checkpoint.shard_hash != shard.shard_hash:
            error = FleetExecutionError(
                f"checkpoint from shard {shard.key!r} is bound to a different shard"
            )
            if cause is not None:
                raise error from cause
            raise error
        if not self.store.verify(checkpoint.artifact):
            error = FleetExecutionError(f"checkpoint from shard {shard.key!r} is absent or corrupt")
            if cause is not None:
                raise error from cause
            raise error

    def result_value(self, run: FleetRun) -> JSONValue:
        """Load and integrity-check a run's reduced JSON result."""

        self.validate_run(run)
        return self.store.get_json(run.result)

    def validate_run(self, run: FleetRun) -> None:
        """Replay all store bindings that establish a fleet run's provenance."""

        for receipt in run.shards:
            binding = self.store.resolve(
                self._shard_binding(receipt.shard),
                required_state=receipt.state,
            )
            if binding is None or binding.artifact != receipt.artifact:
                raise FleetExecutionError(
                    f"fleet run shard {receipt.shard.key!r} is not bound in this store"
                )
        binding = self.store.resolve(
            self._result_binding(run.task, run.plan),
            required_state=run.state,
        )
        if binding is None or binding.artifact != run.result:
            raise FleetExecutionError(
                "fleet run result does not match its deterministic store binding"
            )


def execute_local(
    task: TaskSpec,
    operation: FleetOperation,
    *,
    store: ArtifactStore | str | Path | None = None,
    max_workers: int = 1,
    verify: bool = False,
) -> tuple[FleetRun, JSONValue]:
    """Functional local-execution convenience wrapper."""

    executor = LocalExecutor(store, max_workers=max_workers)
    run = executor.execute(task, operation, verify=verify)
    return run, executor.result_value(run)
