"""Worker capability matching without coupling tasks to a scheduler."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from arbogast.backends import BackendStatus
from arbogast.formats import FrozenMapping, JSONValue

from .models import ResourceHint, TaskSpec


class WorkerState(StrEnum):
    AVAILABLE = "available"
    BUSY = "busy"
    DRAINING = "draining"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class CapabilityMatch:
    """An auditable worker/task matching decision."""

    worker_id: str
    eligible: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.worker_id, str) or not self.worker_id:
            raise ValueError("capability match worker_id must be a non-empty string")
        if not isinstance(self.eligible, bool):
            raise ValueError("capability match eligible must be boolean")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, str) or not reason for reason in self.reasons
        ):
            raise ValueError("capability match reasons must be non-empty strings")
        if self.eligible and self.reasons:
            raise ValueError("an eligible capability match cannot carry rejection reasons")
        if not self.eligible and not self.reasons:
            raise ValueError("an ineligible capability match must explain why")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "worker_id": self.worker_id,
        }


@dataclass(frozen=True, slots=True)
class Worker:
    """An immutable advertisement of schedulable resources and capabilities."""

    id: str
    backends: tuple[BackendStatus, ...]
    resources: ResourceHint = field(default_factory=ResourceHint)
    state: WorkerState = WorkerState.AVAILABLE
    labels: FrozenMapping = field(default_factory=FrozenMapping)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("worker id must be a non-empty string")
        if not isinstance(self.backends, tuple) or any(
            not isinstance(backend, BackendStatus) for backend in self.backends
        ):
            raise ValueError("worker backends must be a tuple of BackendStatus values")
        if not isinstance(self.resources, ResourceHint):
            raise ValueError("worker resources must be a ResourceHint")
        if not isinstance(self.state, WorkerState):
            raise ValueError("worker state must be a WorkerState")
        if not isinstance(self.labels, FrozenMapping):
            raise ValueError("worker labels must be a FrozenMapping")
        names = tuple(backend.name for backend in self.backends)
        if len(names) != len(set(names)):
            raise ValueError("worker backend advertisements must have unique names")
        ordered = tuple(sorted(self.backends, key=lambda item: item.name))
        object.__setattr__(self, "backends", ordered)

    def match(self, task: TaskSpec) -> CapabilityMatch:
        reasons: list[str] = []
        if self.state is not WorkerState.AVAILABLE:
            reasons.append(f"worker state is {self.state.value}")
        backend = next(
            (candidate for candidate in self.backends if candidate.name == task.backend.name),
            None,
        )
        if backend is None:
            reasons.append(f"backend {task.backend.name!r} is not advertised")
        elif not backend.meets(task.backend):
            if not backend.available:
                reasons.append(backend.reason or f"backend {backend.name!r} is unavailable")
            else:
                missing = sorted(set(task.backend.capabilities) - set(backend.capabilities))
                if missing:
                    reasons.append(f"missing backend capabilities: {', '.join(missing)}")
                if task.backend.version is not None and task.backend.version != backend.version:
                    reasons.append(
                        f"backend version {backend.version!r} does not equal "
                        f"required {task.backend.version!r}"
                    )
        requested = task.resources
        available = self.resources
        if available.cpu_cores < requested.cpu_cores:
            reasons.append("insufficient CPU cores")
        if available.gpu_count < requested.gpu_count:
            reasons.append("insufficient GPUs")
        for label, capacity, demand in (
            ("memory", available.memory_bytes, requested.memory_bytes),
            ("scratch", available.scratch_bytes, requested.scratch_bytes),
            ("wall-time", available.wall_time_seconds, requested.wall_time_seconds),
        ):
            if demand is not None and (capacity is None or capacity < demand):
                reasons.append(f"insufficient {label} capacity")
        return CapabilityMatch(self.id, not reasons, tuple(reasons))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "backends": [backend.to_dict() for backend in self.backends],
            "id": self.id,
            "labels": self.labels.to_dict(),
            "resources": self.resources.to_dict(),
            "state": self.state.value,
        }


class NoEligibleWorkerError(LookupError):
    """Raised when no advertised worker can honestly execute a task."""

    def __init__(self, task: TaskSpec, matches: tuple[CapabilityMatch, ...]) -> None:
        self.task = task
        self.matches = matches
        detail = (
            "; ".join(f"{match.worker_id}: {', '.join(match.reasons)}" for match in matches)
            or "worker pool is empty"
        )
        super().__init__(f"no eligible worker for {task.operation!r}: {detail}")


@dataclass(frozen=True, slots=True, init=False)
class WorkerPool:
    """A deterministic worker selection surface for any scheduler."""

    workers: tuple[Worker, ...]

    def __init__(self, workers: Iterable[Worker] = ()) -> None:
        ordered = tuple(sorted(workers, key=lambda worker: worker.id))
        identifiers = tuple(worker.id for worker in ordered)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("worker ids must be unique")
        object.__setattr__(self, "workers", ordered)

    def matches(self, task: TaskSpec) -> tuple[CapabilityMatch, ...]:
        return tuple(worker.match(task) for worker in self.workers)

    def eligible(self, task: TaskSpec) -> tuple[Worker, ...]:
        return tuple(worker for worker in self.workers if worker.match(task).eligible)

    @staticmethod
    def _score(worker: Worker) -> tuple[int, int, int, int, int, str]:
        resources = worker.resources
        return (
            resources.gpu_count,
            resources.cpu_cores,
            resources.memory_bytes if resources.memory_bytes is not None else 2**63 - 1,
            resources.scratch_bytes if resources.scratch_bytes is not None else 2**63 - 1,
            (resources.wall_time_seconds if resources.wall_time_seconds is not None else 2**63 - 1),
            worker.id,
        )

    def ranked(self, task: TaskSpec) -> tuple[Worker, ...]:
        """Return all eligible workers in deterministic smallest-first order."""

        eligible = self.eligible(task)
        if not eligible:
            raise NoEligibleWorkerError(task, self.matches(task))
        return tuple(sorted(eligible, key=self._score))

    def select(self, task: TaskSpec) -> Worker:
        """Select the smallest sufficient worker, breaking ties by worker id."""

        return self.ranked(task)[0]

    def to_dict(self) -> dict[str, JSONValue]:
        return {"workers": [worker.to_dict() for worker in self.workers]}
