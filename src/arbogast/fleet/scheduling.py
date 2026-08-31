"""Deterministic concurrent local scheduling and execution custody.

This module deliberately separates mathematical task identity from mutable
scheduler state.  Workers are immutable advertisements; occupancy, leases,
retry attempts, and checkpoints are operational receipts.  None of those
receipts promotes a mathematical result or substitutes for a certificate.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Condition, RLock
from typing import Any, TypeVar

from arbogast.formats import FrozenMapping, JSONValue, canonical_sha256, normalize_json

from .artifacts import ArtifactConflictError, ArtifactStore, ArtifactStoreError
from .execution import (
    FleetExecutionError,
    FleetOperation,
    LocalExecutor,
    ResumeUnavailableError,
)
from .leases import (
    BudgetExhaustedError,
    CheckpointRef,
    FleetInterruption,
    InterruptionReason,
    InterruptionReceipt,
    LeaseRecord,
    LeaseState,
    PreemptedError,
)
from .models import (
    ArtifactRef,
    EvidenceState,
    FleetPlan,
    FleetRun,
    ResourceHint,
    ShardResult,
    ShardSpec,
    TaskSpec,
)
from .registry import FleetOperationRegistry
from .workers import CapabilityMatch, Worker, WorkerPool, WorkerState

CommitT = TypeVar("CommitT")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class LeaseCustodyError(RuntimeError):
    """Base class for invalid local lease-custody operations."""


class DuplicateDispatchError(LeaseCustodyError):
    """Raised when a shard already has a live lease."""


class StaleLeaseError(LeaseCustodyError):
    """Raised when a terminal, expired, or superseded lease reports results."""


@dataclass(frozen=True, slots=True)
class CheckpointCustodyRecord:
    """Persisted operational custody for one typed shard checkpoint.

    This is an operational receipt in a trusted local :class:`ArtifactStore`,
    not a mathematical certificate or a signature from an untrusted worker.
    Importing an attacker-controlled store does not establish checkpoint
    custody.
    """

    task_hash: str
    plan_hash: str
    operation: str
    checkpoint: CheckpointRef
    dispatch_id: str
    lease_id: str
    worker_id: str
    attempt: int
    lease_state: LeaseState

    schema = "arbogast.fleet.checkpoint-custody.v1"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("task_hash", self.task_hash),
            ("plan_hash", self.plan_hash),
        ):
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"checkpoint custody {field_name} must be canonical SHA-256")
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("checkpoint custody operation must be a non-empty string")
        if not isinstance(self.checkpoint, CheckpointRef):
            raise ValueError("checkpoint custody checkpoint must be a CheckpointRef")
        if not isinstance(self.dispatch_id, str) or not self.dispatch_id.startswith("dispatch:"):
            raise ValueError("checkpoint custody dispatch_id is invalid")
        if not isinstance(self.lease_id, str) or not self.lease_id.startswith("lease:"):
            raise ValueError("checkpoint custody lease_id is invalid")
        if not isinstance(self.worker_id, str) or not self.worker_id.strip():
            raise ValueError("checkpoint custody worker_id must be a non-empty string")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 0:
            raise ValueError("checkpoint custody attempt must be a non-negative integer")
        if self.lease_state not in {
            LeaseState.PREEMPTED,
            LeaseState.BUDGET_EXHAUSTED,
        }:
            raise ValueError("checkpoint custody requires an interrupted lease state")

    @property
    def acceptance_key(self) -> str:
        checkpoint = self.checkpoint
        return (
            f"fleet:checkpoint:{self.task_hash}:{self.plan_hash}:"
            f"{checkpoint.shard_hash}:{checkpoint.sequence}:{checkpoint.artifact.digest}"
        )

    @property
    def key(self) -> str:
        producer_hash = canonical_sha256(
            {"dispatch_id": self.dispatch_id, "lease_id": self.lease_id}
        )
        return f"{self.acceptance_key}:producer:{producer_hash}"

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "attempt": self.attempt,
            "checkpoint": self.checkpoint.to_dict(),
            "dispatch_id": self.dispatch_id,
            "lease_id": self.lease_id,
            "lease_state": self.lease_state.value,
            "operation": self.operation,
            "plan_hash": self.plan_hash,
            "schema": self.schema,
            "task_hash": self.task_hash,
            "worker_id": self.worker_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CheckpointCustodyRecord:
        required = {
            "attempt",
            "checkpoint",
            "dispatch_id",
            "lease_id",
            "lease_state",
            "operation",
            "plan_hash",
            "schema",
            "task_hash",
            "worker_id",
        }
        if set(value) != required:
            raise ValueError("checkpoint custody record has missing or unknown fields")
        if value["schema"] != cls.schema:
            raise ValueError("unsupported checkpoint custody schema")
        checkpoint_value = value["checkpoint"]
        operation = value["operation"]
        plan_hash = value["plan_hash"]
        task_hash = value["task_hash"]
        dispatch_id = value["dispatch_id"]
        lease_id = value["lease_id"]
        worker_id = value["worker_id"]
        attempt = value["attempt"]
        lease_state = value["lease_state"]
        if not isinstance(checkpoint_value, Mapping):
            raise ValueError("checkpoint custody checkpoint must be an object")
        if not all(
            isinstance(item, str)
            for item in (
                operation,
                plan_hash,
                task_hash,
                dispatch_id,
                lease_id,
                worker_id,
                lease_state,
            )
        ):
            raise ValueError("checkpoint custody identity fields must be strings")
        if isinstance(attempt, bool) or not isinstance(attempt, int):
            raise ValueError("checkpoint custody attempt must be an integer")
        try:
            resolved_lease_state = LeaseState(lease_state)
        except ValueError as error:
            raise ValueError("checkpoint custody lease_state is invalid") from error
        return cls(
            task_hash=task_hash,
            plan_hash=plan_hash,
            operation=operation,
            checkpoint=CheckpointRef.from_dict(checkpoint_value),
            dispatch_id=dispatch_id,
            lease_id=lease_id,
            worker_id=worker_id,
            attempt=attempt,
            lease_state=resolved_lease_state,
        )


@dataclass(frozen=True, slots=True)
class _CheckpointAcceptanceRecord:
    """Stable checkpoint identity linked to its first producer receipt."""

    task_hash: str
    plan_hash: str
    operation: str
    checkpoint: CheckpointRef
    producer_key: str
    producer_receipt: ArtifactRef

    schema = "arbogast.fleet.checkpoint-acceptance.v1"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("task_hash", self.task_hash),
            ("plan_hash", self.plan_hash),
        ):
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"checkpoint acceptance {field_name} is invalid")
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("checkpoint acceptance operation must be non-empty")
        if not isinstance(self.checkpoint, CheckpointRef):
            raise ValueError("checkpoint acceptance checkpoint must be a CheckpointRef")
        if not isinstance(self.producer_key, str) or not self.producer_key.startswith(
            f"{self.key}:producer:"
        ):
            raise ValueError("checkpoint acceptance producer key is not bound")
        if not isinstance(self.producer_receipt, ArtifactRef):
            raise ValueError("checkpoint acceptance producer receipt must be an ArtifactRef")

    @property
    def key(self) -> str:
        checkpoint = self.checkpoint
        return (
            f"fleet:checkpoint:{self.task_hash}:{self.plan_hash}:"
            f"{checkpoint.shard_hash}:{checkpoint.sequence}:{checkpoint.artifact.digest}"
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "checkpoint": self.checkpoint.to_dict(),
            "operation": self.operation,
            "plan_hash": self.plan_hash,
            "producer_key": self.producer_key,
            "producer_receipt": self.producer_receipt.to_dict(),
            "schema": self.schema,
            "task_hash": self.task_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> _CheckpointAcceptanceRecord:
        required = {
            "checkpoint",
            "operation",
            "plan_hash",
            "producer_key",
            "producer_receipt",
            "schema",
            "task_hash",
        }
        if set(value) != required:
            raise ValueError("checkpoint acceptance has missing or unknown fields")
        if value["schema"] != cls.schema:
            raise ValueError("unsupported checkpoint acceptance schema")
        checkpoint = value["checkpoint"]
        producer_receipt = value["producer_receipt"]
        strings = {
            name: value[name] for name in ("operation", "plan_hash", "producer_key", "task_hash")
        }
        if not isinstance(checkpoint, Mapping) or not isinstance(producer_receipt, Mapping):
            raise ValueError("checkpoint acceptance nested fields must be objects")
        if any(not isinstance(item, str) for item in strings.values()):
            raise ValueError("checkpoint acceptance identity fields must be strings")
        return cls(
            task_hash=strings["task_hash"],
            plan_hash=strings["plan_hash"],
            operation=strings["operation"],
            checkpoint=CheckpointRef.from_dict(checkpoint),
            producer_key=strings["producer_key"],
            producer_receipt=ArtifactRef.from_dict(producer_receipt),
        )


@dataclass(frozen=True, slots=True, init=False)
class CheckpointManifest:
    """A deterministic set of per-shard checkpoints for one interrupted plan."""

    task_hash: str
    plan_hash: str
    checkpoints: tuple[CheckpointRef, ...]
    schema: str

    def __init__(
        self,
        task_hash: str,
        plan_hash: str,
        checkpoints: Sequence[CheckpointRef],
    ) -> None:
        if not isinstance(task_hash, str) or not _SHA256_RE.fullmatch(task_hash):
            raise ValueError("checkpoint manifest task_hash must be canonical SHA-256")
        if not isinstance(plan_hash, str) or not _SHA256_RE.fullmatch(plan_hash):
            raise ValueError("checkpoint manifest plan_hash must be canonical SHA-256")
        if any(not isinstance(item, CheckpointRef) for item in checkpoints):
            raise ValueError("checkpoint manifest entries must be CheckpointRef values")
        ordered = tuple(sorted(checkpoints, key=lambda item: item.shard_hash))
        shard_hashes = tuple(item.shard_hash for item in ordered)
        if not ordered:
            raise ValueError("checkpoint manifest must contain at least one checkpoint")
        if len(shard_hashes) != len(set(shard_hashes)):
            raise ValueError("checkpoint manifest contains duplicate shard checkpoints")
        object.__setattr__(self, "task_hash", task_hash)
        object.__setattr__(self, "plan_hash", plan_hash)
        object.__setattr__(self, "checkpoints", ordered)
        object.__setattr__(self, "schema", "arbogast.fleet.checkpoint-manifest.v1")

    def identity_dict(self) -> dict[str, JSONValue]:
        return {
            "checkpoints": [item.to_dict() for item in self.checkpoints],
            "plan_hash": self.plan_hash,
            "schema": self.schema,
            "task_hash": self.task_hash,
        }

    @property
    def manifest_hash(self) -> str:
        return canonical_sha256(self.identity_dict())

    def to_dict(self) -> dict[str, JSONValue]:
        return {**self.identity_dict(), "manifest_hash": self.manifest_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CheckpointManifest:
        required = {
            "checkpoints",
            "manifest_hash",
            "plan_hash",
            "schema",
            "task_hash",
        }
        if set(value) != required:
            raise ValueError("checkpoint manifest has missing or unknown fields")
        if value["schema"] != "arbogast.fleet.checkpoint-manifest.v1":
            raise ValueError("unsupported checkpoint manifest schema")
        task_hash = value["task_hash"]
        plan_hash = value["plan_hash"]
        checkpoint_values = value["checkpoints"]
        if not isinstance(task_hash, str) or not isinstance(plan_hash, str):
            raise ValueError("checkpoint manifest hashes must be strings")
        if not isinstance(checkpoint_values, list) or any(
            not isinstance(item, Mapping) for item in checkpoint_values
        ):
            raise ValueError("checkpoint manifest checkpoints must be objects")
        manifest = cls(
            task_hash,
            plan_hash,
            tuple(CheckpointRef.from_dict(item) for item in checkpoint_values),
        )
        if value["manifest_hash"] != manifest.manifest_hash:
            raise ValueError("checkpoint manifest hash does not match its contents")
        return manifest


@dataclass(frozen=True, slots=True)
class FleetShardDispatch:
    """One planned shard assignment in an incomplete fleet dispatch."""

    ordinal: int
    shard_hash: str
    shard_key: str
    worker_id: str

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("pending shard ordinal must be non-negative")
        if not isinstance(self.shard_hash, str) or not _SHA256_RE.fullmatch(self.shard_hash):
            raise ValueError("pending shard hash must be canonical SHA-256")
        if not isinstance(self.shard_key, str) or not self.shard_key:
            raise ValueError("dispatched shard key must be non-empty")
        if not isinstance(self.worker_id, str) or not self.worker_id:
            raise ValueError("dispatched shard worker_id must be non-empty")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "ordinal": self.ordinal,
            "shard_hash": self.shard_hash,
            "shard_key": self.shard_key,
            "worker_id": self.worker_id,
        }


@dataclass(frozen=True, slots=True)
class FleetDispatchFailure:
    """Deterministic summary of a stopped worker queue and its remainder."""

    worker_id: str
    shard_hash: str
    shard_key: str
    shard_ordinal: int
    error_type: str
    detail: str
    pending: tuple[FleetShardDispatch, ...] = ()
    interruption_reason: InterruptionReason | None = None
    interruption_receipt: InterruptionReceipt | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.worker_id, str) or not self.worker_id.strip():
            raise ValueError("dispatch failure worker_id must be non-empty")
        if not isinstance(self.shard_hash, str) or not _SHA256_RE.fullmatch(self.shard_hash):
            raise ValueError("dispatch failure shard_hash must be canonical SHA-256")
        if not isinstance(self.shard_key, str) or not self.shard_key:
            raise ValueError("dispatch failure shard_key must be non-empty")
        if (
            isinstance(self.shard_ordinal, bool)
            or not isinstance(self.shard_ordinal, int)
            or self.shard_ordinal < 0
        ):
            raise ValueError("dispatch failure shard_ordinal must be non-negative")
        if not isinstance(self.error_type, str) or not self.error_type.strip():
            raise ValueError("dispatch failure error_type must be non-empty")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("dispatch failure detail must be non-empty")
        if not isinstance(self.pending, tuple) or any(
            not isinstance(item, FleetShardDispatch) for item in self.pending
        ):
            raise ValueError("dispatch failure pending values are invalid")
        if self.interruption_reason is not None and not isinstance(
            self.interruption_reason, InterruptionReason
        ):
            raise ValueError("dispatch failure interruption_reason is invalid")
        if self.interruption_receipt is not None:
            if not isinstance(self.interruption_receipt, InterruptionReceipt):
                raise ValueError("dispatch failure interruption receipt is invalid")
            if self.interruption_receipt.lease.worker_id != self.worker_id:
                raise ValueError("dispatch failure receipt belongs to another worker")
            if self.interruption_receipt.lease.shard_hash != self.shard_hash:
                raise ValueError("dispatch failure receipt belongs to another shard")
            if self.interruption_receipt.reason is not self.interruption_reason:
                raise ValueError("dispatch failure receipt reason changed")

    @classmethod
    def from_error(
        cls,
        worker_id: str,
        shard: ShardSpec,
        shard_ordinal: int,
        pending: Sequence[FleetShardDispatch],
        error: Exception,
    ) -> FleetDispatchFailure:
        reason = error.reason if isinstance(error, FleetInterruption) else None
        detail = str(error).strip() or type(error).__qualname__
        receipt = error.receipt if isinstance(error, FleetInterruption) else None
        return cls(
            worker_id=worker_id,
            shard_hash=shard.shard_hash,
            shard_key=shard.key,
            shard_ordinal=shard_ordinal,
            error_type=type(error).__qualname__,
            detail=detail,
            pending=tuple(pending),
            interruption_reason=reason,
            interruption_receipt=receipt,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "detail": self.detail,
            "error_type": self.error_type,
            "interruption_reason": (
                None if self.interruption_reason is None else self.interruption_reason.value
            ),
            "interruption_receipt": (
                None if self.interruption_receipt is None else self.interruption_receipt.to_dict()
            ),
            "pending": [item.to_dict() for item in self.pending],
            "shard_hash": self.shard_hash,
            "shard_key": self.shard_key,
            "shard_ordinal": self.shard_ordinal,
            "worker_id": self.worker_id,
        }


class FleetDispatchError(FleetExecutionError):
    """Aggregate partial-dispatch failure that preserves checkpoint custody."""

    def __init__(
        self,
        failures: Sequence[FleetDispatchFailure],
        *,
        scheduled: Sequence[FleetShardDispatch],
        checkpoint_manifest: CheckpointManifest | None = None,
    ) -> None:
        resolved = tuple(failures)
        if not resolved or any(not isinstance(item, FleetDispatchFailure) for item in resolved):
            raise ValueError("aggregate dispatch requires failure summaries")
        if checkpoint_manifest is not None and not isinstance(
            checkpoint_manifest, CheckpointManifest
        ):
            raise ValueError("aggregate dispatch checkpoint manifest is invalid")
        resolved_scheduled = tuple(scheduled)
        if not resolved_scheduled or any(
            not isinstance(item, FleetShardDispatch) for item in resolved_scheduled
        ):
            raise ValueError("aggregate dispatch requires scheduled shard identities")
        self.failures = resolved
        self.scheduled = resolved_scheduled
        self.checkpoint_manifest = checkpoint_manifest
        summary = "; ".join(
            f"{item.worker_id}/{item.shard_key}:{item.error_type}:{item.detail}"
            for item in resolved
        )
        failure_label = (
            "a terminal failure" if len(resolved) == 1 else f"{len(resolved)} terminal failures"
        )
        super().__init__(f"fleet dispatch ended with {failure_label}: {summary}")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "checkpoint_manifest": (
                None if self.checkpoint_manifest is None else self.checkpoint_manifest.to_dict()
            ),
            "failures": [item.to_dict() for item in self.failures],
            "scheduled": [item.to_dict() for item in self.scheduled],
            "schema": "arbogast.fleet.dispatch-error.v1",
        }


class _WorkerQueueError(RuntimeError):
    """Internal carrier retaining the exact stopped and unstarted shards."""

    def __init__(
        self,
        worker_id: str,
        shard: ShardSpec,
        shard_ordinal: int,
        pending: Sequence[FleetShardDispatch],
        completed: Sequence[tuple[int, ShardResult]],
        cause: Exception,
    ) -> None:
        super().__init__(str(cause))
        self.worker_id = worker_id
        self.shard = shard
        self.shard_ordinal = shard_ordinal
        self.pending = tuple(pending)
        self.completed = tuple(completed)
        self.cause = cause


@dataclass(frozen=True, slots=True)
class _LeaseReadinessGuard:
    """Runtime-only callback installed by a readiness-aware campaign.

    The callback is deliberately neither serialized nor accepted through a
    public executor constructor.  Persisted task data can therefore never
    select code to run at the lease boundary.
    """

    callback: Callable[
        [
            TaskSpec,
            ShardSpec,
            Worker,
            LeaseRecord,
            str,
            str,
            int,
            str,
            str,
            tuple[str, ...],
        ],
        Callable[[LeaseRecord, str, tuple[str, ...]], None],
    ]


class _LeaseReadinessRefusal(RuntimeError):
    """Carry a campaign refusal through deterministic worker-queue joins."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("scheduler clock must return timezone-aware datetimes")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Explicit retry and lease policy for local worker execution.

    ``max_attempts`` includes the initial attempt.  Preemption may be retried;
    budget exhaustion and ordinary failures are terminal unless the caller
    opts in.  This preserves their distinct operational meanings.
    """

    max_attempts: int = 1
    retry_preempted: bool = True
    retry_budget_exhausted: bool = False
    retry_failures: bool = False
    lease_seconds: int = 300

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be an integer >= 1")
        if (
            isinstance(self.lease_seconds, bool)
            or not isinstance(self.lease_seconds, int)
            or self.lease_seconds < 1
        ):
            raise ValueError("lease_seconds must be an integer >= 1")
        for name in (
            "retry_preempted",
            "retry_budget_exhausted",
            "retry_failures",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "lease_seconds": self.lease_seconds,
            "max_attempts": self.max_attempts,
            "retry_budget_exhausted": self.retry_budget_exhausted,
            "retry_failures": self.retry_failures,
            "retry_preempted": self.retry_preempted,
        }


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One terminal attempt with explicit retry and resume provenance."""

    dispatch_id: str
    lease: LeaseRecord
    retry_of: str | None = None
    resumed_from: CheckpointRef | None = None
    interruption_receipt: InterruptionReceipt | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.dispatch_id, str) or not self.dispatch_id:
            raise ValueError("attempt dispatch_id must be a non-empty string")
        if not isinstance(self.lease, LeaseRecord) or not self.lease.terminal:
            raise ValueError("attempt lease must be a terminal LeaseRecord")
        if self.retry_of is not None and (not isinstance(self.retry_of, str) or not self.retry_of):
            raise ValueError("attempt retry_of must be a non-empty string or None")
        if self.resumed_from is not None:
            if not isinstance(self.resumed_from, CheckpointRef):
                raise ValueError("attempt resumed_from must be a CheckpointRef or None")
            if self.resumed_from.shard_hash != self.lease.shard_hash:
                raise ValueError("attempt resume checkpoint belongs to a different shard")
        if self.interruption_receipt is not None:
            if not isinstance(self.interruption_receipt, InterruptionReceipt):
                raise ValueError("attempt interruption_receipt has invalid type")
            if self.interruption_receipt.dispatch_id != self.dispatch_id:
                raise ValueError("attempt interruption receipt belongs to another dispatch")
            if self.interruption_receipt.lease != self.lease:
                raise ValueError("attempt interruption receipt belongs to another lease")
            if self.interruption_receipt.retry_of != self.retry_of:
                raise ValueError("attempt interruption retry provenance changed")
            if self.interruption_receipt.resumed_from != self.resumed_from:
                raise ValueError("attempt interruption resume provenance changed")

    @property
    def state(self) -> LeaseState:
        return self.lease.state

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "dispatch_id": self.dispatch_id,
            "interruption_receipt": (
                None if self.interruption_receipt is None else self.interruption_receipt.to_dict()
            ),
            "lease": self.lease.to_dict(),
            "resumed_from": (None if self.resumed_from is None else self.resumed_from.to_dict()),
            "retry_of": self.retry_of,
        }


@dataclass(frozen=True, slots=True)
class ShardAssignment:
    """The deterministic worker selected for one planned shard."""

    shard_hash: str
    shard_key: str
    worker_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.shard_hash, str) or not _SHA256_RE.fullmatch(self.shard_hash):
            raise ValueError("assignment shard_hash must be canonical SHA-256")
        if not isinstance(self.shard_key, str) or not self.shard_key:
            raise ValueError("assignment shard_key must be a non-empty string")
        if not isinstance(self.worker_id, str) or not self.worker_id:
            raise ValueError("assignment worker_id must be a non-empty string")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "shard_hash": self.shard_hash,
            "shard_key": self.shard_key,
            "worker_id": self.worker_id,
        }


@dataclass(frozen=True, slots=True)
class FleetExecutionReceipt:
    """Scheduler receipt for a completed :class:`FleetRun`."""

    dispatch_id: str
    task_hash: str
    plan_hash: str
    result: ArtifactRef
    state: EvidenceState
    assignments: tuple[ShardAssignment, ...]
    attempts: tuple[AttemptRecord, ...]
    resumed: bool

    schema = "arbogast.fleet.execution-receipt.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.dispatch_id, str) or not self.dispatch_id.startswith("dispatch:"):
            raise ValueError("execution receipt dispatch_id is invalid")
        for field_name, value in (
            ("task_hash", self.task_hash),
            ("plan_hash", self.plan_hash),
        ):
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"execution receipt {field_name} must be canonical SHA-256")
        if not isinstance(self.result, ArtifactRef):
            raise ValueError("execution receipt result must be an ArtifactRef")
        if not isinstance(self.state, EvidenceState):
            raise ValueError("execution receipt state must be an EvidenceState")
        if not isinstance(self.resumed, bool):
            raise ValueError("execution receipt resumed must be boolean")
        if not isinstance(self.assignments, tuple) or any(
            not isinstance(item, ShardAssignment) for item in self.assignments
        ):
            raise ValueError("execution receipt assignments must be ShardAssignment values")
        if not isinstance(self.attempts, tuple) or any(
            not isinstance(item, AttemptRecord) for item in self.attempts
        ):
            raise ValueError("execution receipt attempts must be AttemptRecord values")
        shard_hashes = tuple(item.shard_hash for item in self.assignments)
        if len(shard_hashes) != len(set(shard_hashes)):
            raise ValueError("execution receipt assignments contain duplicate shards")
        assignment_workers = {
            (assignment.shard_hash, assignment.worker_id) for assignment in self.assignments
        }
        for attempt in self.attempts:
            if attempt.dispatch_id != self.dispatch_id:
                raise ValueError("execution receipt contains an attempt from another dispatch")
            if attempt.lease.task_hash != self.task_hash:
                raise ValueError("execution receipt attempt belongs to another task")
            if (attempt.lease.shard_hash, attempt.lease.worker_id) not in assignment_workers:
                raise ValueError("execution receipt attempt does not match its assignment")

    @property
    def worker_ids(self) -> tuple[str, ...]:
        return tuple(sorted({assignment.worker_id for assignment in self.assignments}))

    @property
    def result_cache_resumed(self) -> bool:
        """Whether reduction reused the deterministic result-cache binding."""

        return self.resumed

    @property
    def checkpoint_resumed_shards(self) -> tuple[str, ...]:
        """Shards completed by calling the operation's checkpoint resumer."""

        return tuple(
            sorted(
                {
                    attempt.lease.shard_hash
                    for attempt in self.attempts
                    if attempt.state is LeaseState.COMPLETED and attempt.resumed_from is not None
                }
            )
        )

    @property
    def checkpoint_resumed(self) -> bool:
        return bool(self.checkpoint_resumed_shards)

    @property
    def cached_shard_hashes(self) -> tuple[str, ...]:
        """Shards satisfied from CAS rather than executed by this dispatch."""

        completed = {
            attempt.lease.shard_hash
            for attempt in self.attempts
            if attempt.state is LeaseState.COMPLETED
        }
        return tuple(
            sorted(
                assignment.shard_hash
                for assignment in self.assignments
                if assignment.shard_hash not in completed
            )
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "assignments": [assignment.to_dict() for assignment in self.assignments],
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "cached_shard_hashes": list(self.cached_shard_hashes),
            "checkpoint_resumed": self.checkpoint_resumed,
            "checkpoint_resumed_shards": list(self.checkpoint_resumed_shards),
            "dispatch_id": self.dispatch_id,
            "plan_hash": self.plan_hash,
            "result": self.result.to_dict(),
            "result_cache_resumed": self.result_cache_resumed,
            # Compatibility name retained for the v0.1 receipt schema.  Its
            # precise meaning is result-cache reuse, not checkpoint resume.
            "resumed": self.resumed,
            "schema": self.schema,
            "state": self.state.value,
            "task_hash": self.task_hash,
            "worker_ids": list(self.worker_ids),
        }


@dataclass(frozen=True, slots=True)
class WorkerOccupancy:
    """Current occupancy plus cumulative terminal counts for one worker."""

    worker_id: str
    state: WorkerState
    capabilities: tuple[str, ...]
    active_lease_ids: tuple[str, ...]
    active_task_hashes: tuple[str, ...]
    used_resources: FrozenMapping
    available_resources: FrozenMapping
    completed_count: int
    failed_count: int
    preempted_count: int
    budget_exhausted_count: int
    expired_count: int
    released_count: int

    def to_dict(self) -> dict[str, JSONValue]:
        task_hash: JSONValue = (
            self.active_task_hashes[0] if len(self.active_task_hashes) == 1 else None
        )
        return {
            "active_lease_ids": list(self.active_lease_ids),
            "active_task_hashes": list(self.active_task_hashes),
            "available_resources": self.available_resources.to_dict(),
            "budget_exhausted_count": self.budget_exhausted_count,
            "capabilities": list(self.capabilities),
            "completed_count": self.completed_count,
            "expired_count": self.expired_count,
            "failed_count": self.failed_count,
            "preempted_count": self.preempted_count,
            "released_count": self.released_count,
            "state": self.state.value,
            "task_hash": task_hash,
            "used_resources": self.used_resources.to_dict(),
            "worker_id": self.worker_id,
        }


@dataclass(frozen=True, slots=True)
class FleetSchedulerStatus:
    """A stable read-only projection of local worker and lease state."""

    workers: tuple[WorkerOccupancy, ...]
    active_count: int
    completed_count: int
    failed_count: int
    preempted_count: int
    budget_exhausted_count: int
    expired_count: int
    released_count: int

    schema = "arbogast.fleet.scheduler-status.v1"

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "active_count": self.active_count,
            "budget_exhausted_count": self.budget_exhausted_count,
            "completed_count": self.completed_count,
            "expired_count": self.expired_count,
            "failed_count": self.failed_count,
            "preempted_count": self.preempted_count,
            "released_count": self.released_count,
            "schema": self.schema,
            "workers": [worker.to_dict() for worker in self.workers],
        }


class LeaseCustody:
    """Thread-safe single-owner custody for shard leases.

    A shard may have at most one offered or active lease.  Completion checks
    both current ownership and expiry before committing any artifact binding.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, LeaseRecord] = {}
        self._order: list[str] = []
        self._current_by_shard: dict[str, str] = {}
        self._deadlines: dict[str, datetime] = {}

    def _require_current(self, lease_id: str) -> LeaseRecord:
        try:
            record = self._records[lease_id]
        except KeyError as error:
            raise StaleLeaseError(f"unknown lease {lease_id!r}") from error
        if record.terminal or self._current_by_shard.get(record.shard_hash) != lease_id:
            raise StaleLeaseError(f"lease {lease_id!r} is terminal or superseded")
        return record

    def _replace(self, record: LeaseRecord) -> LeaseRecord:
        self._records[record.id] = record
        if record.terminal:
            if self._current_by_shard.get(record.shard_hash) == record.id:
                del self._current_by_shard[record.shard_hash]
            self._deadlines.pop(record.id, None)
        return record

    def _expire_stale(self, now: datetime) -> None:
        canonical_now = _as_utc(now)
        for lease_id in tuple(self._current_by_shard.values()):
            deadline = self._deadlines[lease_id]
            if deadline <= canonical_now:
                current = self._records[lease_id]
                self._replace(
                    current.transition(
                        LeaseState.EXPIRED,
                        detail="lease expired before completion",
                    )
                )

    def next_attempt(self, shard_hash: str) -> int:
        with self._lock:
            attempts = (
                record.attempt
                for record in self._records.values()
                if record.shard_hash == shard_hash
            )
            return max(attempts, default=-1) + 1

    def latest(self, shard_hash: str) -> LeaseRecord | None:
        with self._lock:
            records = tuple(
                record
                for lease_id in self._order
                if (record := self._records[lease_id]).shard_hash == shard_hash
            )
            return records[-1] if records else None

    def offer(
        self,
        task: TaskSpec,
        shard: ShardSpec,
        worker: Worker,
        *,
        attempt: int,
        acquired_at: datetime,
        expires_at: datetime,
    ) -> LeaseRecord:
        if shard.task_hash != task.task_hash:
            raise LeaseCustodyError("cannot lease a shard belonging to a different task")
        match = worker.match(task)
        if not match.eligible:
            raise LeaseCustodyError(
                f"worker {worker.id!r} is not eligible: {', '.join(match.reasons)}"
            )
        acquired = _as_utc(acquired_at)
        expires = _as_utc(expires_at)
        if expires <= acquired:
            raise LeaseCustodyError("lease expiry must be later than acquisition")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
            raise LeaseCustodyError("lease attempt must be a non-negative integer")
        with self._lock:
            self._expire_stale(acquired)
            current_id = self._current_by_shard.get(shard.shard_hash)
            if current_id is not None:
                raise DuplicateDispatchError(
                    f"shard {shard.key!r} already has live lease {current_id!r}"
                )
            expected_attempt = self.next_attempt(shard.shard_hash)
            if attempt != expected_attempt:
                raise LeaseCustodyError(
                    f"shard {shard.key!r} attempt {attempt} is not next ordinal {expected_attempt}"
                )
            acquired_text = _timestamp(acquired)
            expires_text = _timestamp(expires)
            lease = LeaseRecord(
                id=LeaseRecord.canonical_id(
                    task_hash=task.task_hash,
                    shard_hash=shard.shard_hash,
                    worker_id=worker.id,
                    attempt=attempt,
                    acquired_at=acquired_text,
                    expires_at=expires_text,
                ),
                task_hash=task.task_hash,
                shard_hash=shard.shard_hash,
                worker_id=worker.id,
                attempt=attempt,
                acquired_at=acquired_text,
                expires_at=expires_text,
            )
            self._records[lease.id] = lease
            self._order.append(lease.id)
            self._current_by_shard[shard.shard_hash] = lease.id
            self._deadlines[lease.id] = expires
            return lease

    def activate(self, lease_id: str, *, now: datetime) -> LeaseRecord:
        with self._lock:
            self._expire_stale(now)
            current = self._require_current(lease_id)
            if current.state is not LeaseState.OFFERED:
                raise StaleLeaseError(f"lease {lease_id!r} is not offered")
            return self._replace(current.transition(LeaseState.ACTIVE))

    def terminate(
        self,
        lease_id: str,
        state: LeaseState,
        *,
        now: datetime,
        checkpoint: CheckpointRef | None = None,
        detail: str | None = None,
    ) -> LeaseRecord:
        if state not in {
            LeaseState.RELEASED,
            LeaseState.EXPIRED,
            LeaseState.PREEMPTED,
            LeaseState.BUDGET_EXHAUSTED,
            LeaseState.FAILED,
        }:
            raise LeaseCustodyError("terminate requires a terminal non-completed state")
        with self._lock:
            self._expire_stale(now)
            current = self._require_current(lease_id)
            return self._replace(current.transition(state, checkpoint=checkpoint, detail=detail))

    def commit(
        self,
        lease_id: str,
        action: Callable[[], CommitT],
        *,
        now: datetime,
    ) -> tuple[LeaseRecord, CommitT]:
        """Commit content and completion atomically with respect to lease custody."""

        with self._lock:
            self._expire_stale(now)
            current = self._require_current(lease_id)
            if current.state is not LeaseState.ACTIVE:
                raise StaleLeaseError(f"lease {lease_id!r} is not active")
            value = action()
            return self._replace(current.transition(LeaseState.COMPLETED)), value

    def expire(self, lease_id: str, *, now: datetime) -> LeaseRecord:
        with self._lock:
            self._expire_stale(now)
            try:
                record = self._records[lease_id]
            except KeyError as error:
                raise StaleLeaseError(f"unknown lease {lease_id!r}") from error
            if record.state is LeaseState.EXPIRED:
                return record
            current = self._require_current(lease_id)
            return self._replace(
                current.transition(LeaseState.EXPIRED, detail="lease explicitly expired")
            )

    def records(self, *, task_hash: str | None = None) -> tuple[LeaseRecord, ...]:
        with self._lock:
            return tuple(
                record
                for lease_id in self._order
                if (record := self._records[lease_id]).task_hash == task_hash or task_hash is None
            )

    def active(self, *, worker_id: str | None = None) -> tuple[LeaseRecord, ...]:
        with self._lock:
            records = (self._records[lease_id] for lease_id in self._current_by_shard.values())
            return tuple(
                sorted(
                    (
                        record
                        for record in records
                        if worker_id is None or record.worker_id == worker_id
                    ),
                    key=lambda record: (record.worker_id, record.shard_hash),
                )
            )

    def validate_active(self, lease_id: str, *, now: datetime) -> LeaseRecord:
        """Return the exact current ACTIVE lease after expiring stale custody."""

        with self._lock:
            self._expire_stale(now)
            current = self._require_current(lease_id)
            if current.state is not LeaseState.ACTIVE:
                raise StaleLeaseError(f"lease {lease_id!r} is not active")
            return current


def _resource_projection(resources: ResourceHint) -> dict[str, JSONValue]:
    return resources.to_dict()


def _available_resources(total: ResourceHint, used: ResourceHint | None) -> dict[str, JSONValue]:
    if used is None:
        return _resource_projection(total)

    def remaining(capacity: int | None, demand: int | None) -> int | None:
        if capacity is None:
            return None
        return capacity - (0 if demand is None else demand)

    return {
        "cpu_cores": total.cpu_cores - used.cpu_cores,
        "gpu_count": total.gpu_count - used.gpu_count,
        "memory_bytes": remaining(total.memory_bytes, used.memory_bytes),
        "scratch_bytes": remaining(total.scratch_bytes, used.scratch_bytes),
        # Wall time is a per-lease limit, not a consumable quantity.
        "wall_time_seconds": total.wall_time_seconds,
    }


class WorkerPoolExecutor(LocalExecutor):
    """Deterministic concurrent executor backed by an immutable WorkerPool.

    Shards are sorted by :class:`FleetPlan`, workers are ranked smallest-first,
    and assignments use deterministic round-robin queues.  Each worker runs
    one shard at a time; queues run concurrently and reduction remains in plan
    order regardless of completion order.

    Checkpoint persistence is cooperative: a runner must publish a typed
    checkpoint by raising :class:`FleetInterruption`.  Such checkpoints can be
    replayed by a fresh executor sharing the same trusted local artifact
    store.  Abrupt process/host failure and durable remote lease recovery are
    outside the v0.1 local executor boundary.
    """

    def __init__(
        self,
        workers: WorkerPool,
        store: ArtifactStore | str | Path | None = None,
        *,
        operation_registry: FleetOperationRegistry | None = None,
        max_workers: int | None = None,
        retry_policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(workers, WorkerPool):
            raise TypeError("workers must be a WorkerPool")
        resolved_max_workers = max(1, len(workers.workers)) if max_workers is None else max_workers
        super().__init__(
            store,
            max_workers=resolved_max_workers,
            operation_registry=operation_registry,
        )
        self.workers = workers
        self.retry_policy = RetryPolicy() if retry_policy is None else retry_policy
        if not isinstance(self.retry_policy, RetryPolicy):
            raise TypeError("retry_policy must be a RetryPolicy")
        self._clock = _utc_now if clock is None else clock
        self.custody = LeaseCustody()
        self._condition = Condition(RLock())
        self._active_by_worker: dict[str, LeaseRecord] = {}
        self._active_tasks: dict[str, TaskSpec] = {}
        self._attempt_lock = RLock()
        self._attempts: list[AttemptRecord] = []
        self._dispatch_counter = 0
        # Operational dispatch identity is deliberately outside TaskSpec.  A
        # per-executor nonce prevents fresh-process receipt collisions while
        # the counter gives stable ordering inside one runtime.
        self._executor_nonce = uuid.uuid4().hex
        self._dispatch_contexts: dict[str, tuple[int, str, str, str]] = {}
        self._active_dispatch_by_lease: dict[str, str] = {}
        self._receipts: dict[tuple[str, str, str], FleetExecutionReceipt] = {}
        self._receipts_by_run: dict[int, tuple[FleetRun, FleetExecutionReceipt]] = {}
        self._checkpoint_records: dict[str, CheckpointCustodyRecord] = {}
        self._interrupted_manifests: dict[str, CheckpointManifest] = {}
        self._lease_readiness_guards: dict[str, _LeaseReadinessGuard] = {}

    def _now(self) -> datetime:
        return _as_utc(self._clock())

    def matches(self, task: TaskSpec) -> tuple[CapabilityMatch, ...]:
        """Return exact backend/resource eligibility diagnostics for planning."""

        return self.workers.matches(task)

    def validate_dispatch_context(
        self,
        *,
        task: TaskSpec,
        lease: LeaseRecord,
        dispatch_id: str,
        dispatch_ordinal: int,
        dispatch_runtime_nonce: str,
        plan_hash: str,
        worker_id: str,
    ) -> LeaseRecord:
        """Require the exact lease and dispatch to remain live in this runtime."""

        expected_dispatch = "dispatch:" + canonical_sha256(
            {
                "ordinal": dispatch_ordinal,
                "plan_hash": plan_hash,
                "runtime_nonce": dispatch_runtime_nonce,
                "task_hash": task.task_hash,
            }
        )
        with self._attempt_lock:
            context = self._dispatch_contexts.get(dispatch_id)
        expected_context = (
            dispatch_ordinal,
            dispatch_runtime_nonce,
            task.task_hash,
            plan_hash,
        )
        if dispatch_id != expected_dispatch or context != expected_context:
            raise FleetExecutionError(
                "dispatch identity is absent or mismatched in the active scheduler runtime"
            )
        with self._condition:
            current = self.custody.validate_active(lease.id, now=self._now())
            if (
                current != lease
                or self._active_by_worker.get(worker_id) != lease
                or self._active_tasks.get(worker_id) != task
                or self._active_dispatch_by_lease.get(lease.id) != dispatch_id
            ):
                raise FleetExecutionError(
                    "lease is not the exact active scheduler custody/dispatch record"
                )
        return current

    @contextmanager
    def _guard_lease_readiness(
        self,
        task: TaskSpec,
        callback: Callable[
            [
                TaskSpec,
                ShardSpec,
                Worker,
                LeaseRecord,
                str,
                str,
                int,
                str,
                str,
                tuple[str, ...],
            ],
            Callable[[LeaseRecord, str, tuple[str, ...]], None],
        ],
    ) -> Iterator[None]:
        """Install a runtime-only guard for leases of one exact task.

        This is an internal integration seam for :class:`Campaign`.  It is a
        context manager so the callback cannot survive the dispatch that
        supplied it, and it is keyed by the mathematical task hash so
        concurrent dispatches for unrelated tasks remain independent.
        """

        if not isinstance(task, TaskSpec):
            raise TypeError("lease readiness guard task must be a TaskSpec")
        if not callable(callback):
            raise TypeError("lease readiness guard callback must be callable")
        guard = _LeaseReadinessGuard(callback)
        with self._attempt_lock:
            if task.task_hash in self._lease_readiness_guards:
                raise FleetExecutionError(
                    "a lease readiness guard is already active for this exact task"
                )
            self._lease_readiness_guards[task.task_hash] = guard
        try:
            yield
        finally:
            with self._attempt_lock:
                if self._lease_readiness_guards.get(task.task_hash) is guard:
                    del self._lease_readiness_guards[task.task_hash]

    def _apply_lease_readiness_guard(
        self,
        task: TaskSpec,
        shard: ShardSpec,
        worker: Worker,
        lease: LeaseRecord,
        plan_hash: str,
        dispatch_id: str,
    ) -> None:
        with self._attempt_lock:
            guard = self._lease_readiness_guards.get(task.task_hash)
        if guard is None:
            return

        def launch_state(
            now: datetime,
        ) -> tuple[LeaseRecord, int, str, tuple[str, ...]]:
            blockers: list[str] = []
            if shard.task_hash != task.task_hash:
                blockers.append("leased shard is bound to a different fleet task")
            if lease.task_hash != task.task_hash or lease.shard_hash != shard.shard_hash:
                blockers.append("active lease is not bound to the exact task and shard")
            if lease.worker_id != worker.id:
                blockers.append("active lease is not bound to the selected worker")
            if lease.state is not LeaseState.ACTIVE:
                blockers.append(f"lease state is {lease.state.value}, not active")
            match = worker.match(task)
            if not match.eligible:
                blockers.extend(f"worker {worker.id}: {reason}" for reason in match.reasons)
            if not isinstance(plan_hash, str) or not _SHA256_RE.fullmatch(plan_hash):
                blockers.append("fleet plan hash is not canonical")
            with self._attempt_lock:
                context = self._dispatch_contexts.get(dispatch_id)
            ordinal = -1
            runtime_nonce = ""
            if context is None:
                blockers.append("dispatch identity is absent from the active scheduler runtime")
            else:
                ordinal, runtime_nonce, context_task, context_plan = context
                expected_dispatch = "dispatch:" + canonical_sha256(
                    {
                        "ordinal": ordinal,
                        "plan_hash": plan_hash,
                        "runtime_nonce": runtime_nonce,
                        "task_hash": task.task_hash,
                    }
                )
                if (
                    context_task != task.task_hash
                    or context_plan != plan_hash
                    or expected_dispatch != dispatch_id
                ):
                    blockers.append("dispatch identity does not match its scheduler context")
            current = lease
            with self._condition:
                active_worker_lease = self._active_by_worker.get(worker.id)
                active_task = self._active_tasks.get(worker.id)
                active_dispatch = self._active_dispatch_by_lease.get(lease.id)
                try:
                    current = self.custody.validate_active(lease.id, now=now)
                except LeaseCustodyError as error:
                    latest = self.custody.latest(shard.shard_hash)
                    if latest is not None:
                        current = latest
                    blockers.append(f"active scheduler custody failed: {error}")
                if active_worker_lease != current or current != lease:
                    blockers.append("lease is no longer the exact active worker custody record")
                if active_task != task:
                    blockers.append("active worker task differs from the authorized task")
                if active_dispatch != dispatch_id:
                    blockers.append("active lease belongs to a different scheduler dispatch")
            try:
                expires = datetime.fromisoformat(lease.expires_at.replace("Z", "+00:00"))
                if expires.tzinfo is None or expires <= now:
                    blockers.append("lease expired before readiness authorization")
            except ValueError:
                blockers.append("lease expiry is not a canonical timestamp")
            return current, ordinal, runtime_nonce, tuple(dict.fromkeys(blockers))

        checked_at = self._now()
        current, ordinal, runtime_nonce, blockers = launch_state(checked_at)
        try:
            finalize = guard.callback(
                task,
                shard,
                worker,
                current,
                plan_hash,
                dispatch_id,
                ordinal,
                runtime_nonce,
                _timestamp(checked_at),
                blockers,
            )
            if not callable(finalize):
                raise FleetExecutionError(
                    "lease readiness callback did not return a launch finalizer"
                )
            final_checked_at = self._now()
            final_lease, _, _, final_blockers = launch_state(final_checked_at)
            finalize(final_lease, _timestamp(final_checked_at), final_blockers)
        except Exception as error:
            raise _LeaseReadinessRefusal(error) from error

    def supports_checkpoint_resume(self, task: TaskSpec | None = None) -> bool:
        """Return true for the persisted typed-custody resume implementation."""

        if task is not None and not isinstance(task, TaskSpec):
            raise TypeError("task must be a TaskSpec or None")
        return True

    @staticmethod
    def _checkpoint_record(
        task: TaskSpec,
        plan_hash: str,
        checkpoint: CheckpointRef,
        dispatch_id: str,
        lease: LeaseRecord,
    ) -> CheckpointCustodyRecord:
        if lease.task_hash != task.task_hash:
            raise LeaseCustodyError("checkpoint producer lease belongs to another task")
        if lease.shard_hash != checkpoint.shard_hash:
            raise LeaseCustodyError("checkpoint producer lease belongs to another shard")
        if lease.checkpoint != checkpoint:
            raise LeaseCustodyError("checkpoint producer lease does not bind the checkpoint")
        return CheckpointCustodyRecord(
            task_hash=task.task_hash,
            plan_hash=plan_hash,
            operation=task.operation,
            checkpoint=checkpoint,
            dispatch_id=dispatch_id,
            lease_id=lease.id,
            worker_id=lease.worker_id,
            attempt=lease.attempt,
            lease_state=lease.state,
        )

    @staticmethod
    def _checkpoint_key(
        task_hash: str,
        plan_hash: str,
        checkpoint: CheckpointRef,
    ) -> str:
        return (
            f"fleet:checkpoint:{task_hash}:{plan_hash}:"
            f"{checkpoint.shard_hash}:{checkpoint.sequence}:{checkpoint.artifact.digest}"
        )

    def _persist_checkpoint(
        self,
        task: TaskSpec,
        plan_hash: str,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
        dispatch_id: str,
        lease: LeaseRecord,
    ) -> CheckpointCustodyRecord:
        self.validate_checkpoint(shard, checkpoint)
        record = self._checkpoint_record(
            task,
            plan_hash,
            checkpoint,
            dispatch_id,
            lease,
        )
        producer_artifact = self.store.put_json(record.to_dict())
        self.store.bind(record.key, producer_artifact, EvidenceState.DISCOVERY)
        acceptance = _CheckpointAcceptanceRecord(
            task_hash=task.task_hash,
            plan_hash=plan_hash,
            operation=task.operation,
            checkpoint=checkpoint,
            producer_key=record.key,
            producer_receipt=producer_artifact,
        )
        acceptance_artifact = self.store.put_json(acceptance.to_dict())
        try:
            self.store.bind(
                acceptance.key,
                acceptance_artifact,
                EvidenceState.DISCOVERY,
            )
        except ArtifactConflictError:
            # Re-emitting the exact same checkpoint in a later process is
            # idempotent even though the producer-attempt receipt is new.  The
            # stable acceptance index remains linked to its first producer.
            existing, _ = self._load_checkpoint_acceptance(acceptance.key)
            if (
                existing.task_hash != task.task_hash
                or existing.plan_hash != plan_hash
                or existing.operation != task.operation
                or existing.checkpoint != checkpoint
            ):
                raise
        with self._attempt_lock:
            self._checkpoint_records[record.key] = record
        return record

    def _load_checkpoint_acceptance(
        self,
        key: str,
    ) -> tuple[_CheckpointAcceptanceRecord, CheckpointCustodyRecord]:
        binding = self.store.resolve(key, required_state=EvidenceState.DISCOVERY)
        if binding is None:
            raise ResumeUnavailableError(
                "checkpoint has no persisted typed custody receipt for this task and plan"
            )
        try:
            value = self.store.get_json(binding.artifact)
            if not isinstance(value, Mapping):
                raise ValueError("checkpoint acceptance receipt must be an object")
            acceptance = _CheckpointAcceptanceRecord.from_dict(value)
            if acceptance.key != key:
                raise ValueError("checkpoint acceptance key does not match its contents")
            producer_binding = self.store.resolve(
                acceptance.producer_key,
                required_state=EvidenceState.DISCOVERY,
            )
            if producer_binding is None or producer_binding.artifact != acceptance.producer_receipt:
                raise ValueError("checkpoint acceptance producer binding is missing")
            producer_value = self.store.get_json(producer_binding.artifact)
            if not isinstance(producer_value, Mapping):
                raise ValueError("checkpoint producer receipt must be an object")
            producer = CheckpointCustodyRecord.from_dict(producer_value)
            if (
                producer.key != acceptance.producer_key
                or producer.task_hash != acceptance.task_hash
                or producer.plan_hash != acceptance.plan_hash
                or producer.operation != acceptance.operation
                or producer.checkpoint != acceptance.checkpoint
            ):
                raise ValueError("checkpoint producer receipt is not bound to acceptance")
        except (ArtifactStoreError, TypeError, ValueError) as error:
            raise ResumeUnavailableError(
                "checkpoint custody receipt failed strict replay"
            ) from error
        return acceptance, producer

    def _build_checkpoint_manifest(
        self,
        task: TaskSpec,
        plan: FleetPlan,
        *,
        dispatch_id: str,
        resume_checkpoints: Mapping[str, CheckpointRef] | None = None,
        completed_shard_hashes: Sequence[str] = (),
    ) -> CheckpointManifest | None:
        with self._attempt_lock:
            records = tuple(
                record
                for record in self._checkpoint_records.values()
                if record.task_hash == task.task_hash
                and record.plan_hash == plan.plan_hash
                and record.operation == task.operation
                and record.dispatch_id == dispatch_id
            )
        plan_shards = {shard.shard_hash for shard in plan.shards}
        completed = set(completed_shard_hashes)
        if not completed <= plan_shards:
            raise FleetExecutionError("completed checkpoint shards are not in this plan")
        latest: dict[str, CheckpointRef] = {}
        for shard_hash, checkpoint in (resume_checkpoints or {}).items():
            if shard_hash != checkpoint.shard_hash or shard_hash not in plan_shards:
                raise FleetExecutionError("resume checkpoint map is not bound to the current plan")
            if shard_hash not in completed:
                latest[shard_hash] = checkpoint
        for record in sorted(
            records,
            key=lambda item: (
                item.checkpoint.shard_hash,
                item.checkpoint.sequence,
                item.checkpoint.artifact.digest,
                item.checkpoint.created_at,
            ),
        ):
            checkpoint = record.checkpoint
            if checkpoint.shard_hash in completed:
                continue
            current = latest.get(checkpoint.shard_hash)
            if current is None or checkpoint.sequence > current.sequence:
                latest[checkpoint.shard_hash] = checkpoint
            elif checkpoint.sequence == current.sequence and checkpoint != current:
                raise FleetExecutionError(
                    "checkpoint sequence was reused for different shard content"
                )
            elif checkpoint.sequence < current.sequence:
                raise FleetExecutionError("checkpoint sequence regressed during resume")
        if not latest:
            return None
        checkpoints = tuple(latest.values())
        manifest = CheckpointManifest(task.task_hash, plan.plan_hash, checkpoints)
        # Persist the manifest bytes as an immutable portable handoff.  Exact
        # per-shard custody is still replayed independently on resume.
        self.store.put_json(manifest.to_dict())
        with self._attempt_lock:
            self._interrupted_manifests[task.task_hash] = manifest
        return manifest

    def checkpoint_manifest(self, task_hash: str) -> CheckpointManifest | None:
        """Return the latest interrupted per-shard manifest for ``task_hash``."""

        if not isinstance(task_hash, str) or not _SHA256_RE.fullmatch(task_hash):
            raise ValueError("task_hash must be canonical SHA-256")
        with self._attempt_lock:
            return self._interrupted_manifests.get(task_hash)

    def _replay_checkpoint(
        self,
        task: TaskSpec,
        plan: FleetPlan,
        shard: ShardSpec,
        checkpoint: CheckpointRef,
    ) -> CheckpointCustodyRecord:
        self.validate_checkpoint(shard, checkpoint)
        expected_key = self._checkpoint_key(
            task.task_hash,
            plan.plan_hash,
            checkpoint,
        )
        acceptance, replayed = self._load_checkpoint_acceptance(expected_key)
        if (
            acceptance.task_hash != task.task_hash
            or acceptance.plan_hash != plan.plan_hash
            or acceptance.operation != task.operation
            or acceptance.checkpoint != checkpoint
            or acceptance.key != expected_key
        ):
            raise ResumeUnavailableError(
                "checkpoint custody receipt does not match the requested task and plan"
            )
        return replayed

    def _new_dispatch_id(self, task: TaskSpec, plan: FleetPlan) -> str:
        with self._attempt_lock:
            ordinal = self._dispatch_counter
            self._dispatch_counter += 1
            runtime_nonce = self._executor_nonce
        dispatch_id = "dispatch:" + canonical_sha256(
            {
                "ordinal": ordinal,
                "plan_hash": plan.plan_hash,
                "runtime_nonce": runtime_nonce,
                "task_hash": task.task_hash,
            }
        )
        with self._attempt_lock:
            self._dispatch_contexts[dispatch_id] = (
                ordinal,
                runtime_nonce,
                task.task_hash,
                plan.plan_hash,
            )
        return dispatch_id

    def _record_attempt(self, record: AttemptRecord) -> None:
        with self._attempt_lock:
            self._attempts.append(record)

    def _acquire(
        self,
        dispatch_id: str,
        task: TaskSpec,
        shard: ShardSpec,
        worker: Worker,
        attempt: int,
    ) -> LeaseRecord:
        with self._condition:
            while worker.id in self._active_by_worker:
                self._condition.wait()
            acquired = self._now()
            offered = self.custody.offer(
                task,
                shard,
                worker,
                attempt=attempt,
                acquired_at=acquired,
                expires_at=acquired + timedelta(seconds=self.retry_policy.lease_seconds),
            )
            active = self.custody.activate(offered.id, now=acquired)
            self._active_by_worker[worker.id] = active
            self._active_tasks[worker.id] = task
            self._active_dispatch_by_lease[active.id] = dispatch_id
            return active

    def _release(self, worker_id: str, lease_id: str) -> None:
        with self._condition:
            current = self._active_by_worker.get(worker_id)
            if current is not None and current.id == lease_id:
                del self._active_by_worker[worker_id]
                self._active_tasks.pop(worker_id, None)
                self._active_dispatch_by_lease.pop(lease_id, None)
                self._condition.notify_all()

    def _terminal_failure(
        self,
        lease: LeaseRecord,
        error: BaseException,
    ) -> LeaseRecord:
        detail = str(error).strip() or type(error).__qualname__
        try:
            return self.custody.terminate(
                lease.id,
                LeaseState.FAILED,
                now=self._now(),
                detail=detail,
            )
        except StaleLeaseError:
            latest = self.custody.latest(lease.shard_hash)
            if latest is None:
                raise
            return latest

    def _run_scheduled_one(
        self,
        dispatch_id: str,
        task: TaskSpec,
        operation: FleetOperation,
        shard: ShardSpec,
        worker: Worker,
        plan_hash: str,
        resume_checkpoint: CheckpointRef | None = None,
    ) -> ShardResult:
        key = self._shard_binding(shard)
        cached = self.store.resolve(key, required_state=EvidenceState.DISCOVERY)
        if cached is not None:
            return ShardResult(shard, cached.artifact, cached.state, resumed=True)

        prior = self.custody.latest(shard.shard_hash)
        if resume_checkpoint is None:
            retry_of = None if prior is None else prior.id
            resumed_from = None if prior is None else prior.checkpoint
        else:
            retry_of = (
                prior.id if prior is not None and prior.checkpoint == resume_checkpoint else None
            )
            resumed_from = resume_checkpoint
        start_attempt = self.custody.next_attempt(shard.shard_hash)
        last_error: BaseException | None = None

        for offset in range(self.retry_policy.max_attempts):
            attempt = start_attempt + offset
            lease = self._acquire(dispatch_id, task, shard, worker, attempt)
            try:
                cached_after_wait = self.store.resolve(
                    key,
                    required_state=EvidenceState.DISCOVERY,
                )
                if cached_after_wait is not None:
                    released = self.custody.terminate(
                        lease.id,
                        LeaseState.RELEASED,
                        now=self._now(),
                    )
                    self._record_attempt(AttemptRecord(dispatch_id, released, retry_of))
                    return ShardResult(
                        shard,
                        cached_after_wait.artifact,
                        cached_after_wait.state,
                        resumed=True,
                    )
                resume_runner: object | None = None
                if resumed_from is not None:
                    self.validate_checkpoint(shard, resumed_from)
                    resumer = getattr(operation, "resume", None)
                    if not callable(resumer):
                        raise ResumeUnavailableError(
                            f"operation {task.operation!r} cannot resume checkpointed shard "
                            f"{shard.key!r}"
                        )
                    resume_runner = resumer
                run_operation = operation.run
                self._apply_lease_readiness_guard(
                    task,
                    shard,
                    worker,
                    lease,
                    plan_hash,
                    dispatch_id,
                )
                if resumed_from is None:
                    raw_value = run_operation(task, shard)
                else:
                    assert callable(resume_runner)
                    raw_value = resume_runner(task, shard, resumed_from)
                value = normalize_json(raw_value)
                artifact = self.store.put_json(value)

                def publish(
                    artifact_ref: ArtifactRef = artifact,
                    did_resume: bool = resumed_from is not None,
                ) -> ShardResult:
                    binding = self.store.bind(
                        key,
                        artifact_ref,
                        EvidenceState.DISCOVERY,
                    )
                    return ShardResult(
                        shard=shard,
                        artifact=artifact_ref,
                        state=binding.state,
                        resumed=did_resume,
                    )

                completed, result = self.custody.commit(
                    lease.id,
                    publish,
                    now=self._now(),
                )
                self._record_attempt(AttemptRecord(dispatch_id, completed, retry_of, resumed_from))
                return result
            except FleetInterruption as interruption:
                try:
                    if interruption.checkpoint is not None:
                        self.validate_checkpoint(
                            shard,
                            interruption.checkpoint,
                            cause=interruption,
                        )
                except (ArtifactStoreError, FleetExecutionError) as validation_error:
                    failed = self._terminal_failure(lease, validation_error)
                    self._record_attempt(AttemptRecord(dispatch_id, failed, retry_of, resumed_from))
                    raise
                state = {
                    "preempted": LeaseState.PREEMPTED,
                    "budget_exhausted": LeaseState.BUDGET_EXHAUSTED,
                }[interruption.reason.value]
                terminal = self.custody.terminate(
                    lease.id,
                    state,
                    now=self._now(),
                    checkpoint=interruption.checkpoint,
                    detail=interruption.detail,
                )
                interruption_receipt = InterruptionReceipt(
                    dispatch_id=dispatch_id,
                    lease=terminal,
                    reason=interruption.reason,
                    retry_of=retry_of,
                    resumed_from=resumed_from,
                    progress_completed=interruption.progress_completed,
                    progress_total=interruption.progress_total,
                    resources=interruption.resources,
                    spent=interruption.spent,
                )
                interruption.bind_receipt(interruption_receipt)
                if interruption.checkpoint is not None:
                    try:
                        self._persist_checkpoint(
                            task,
                            plan_hash,
                            shard,
                            interruption.checkpoint,
                            dispatch_id,
                            terminal,
                        )
                    except (
                        ArtifactStoreError,
                        FleetExecutionError,
                        LeaseCustodyError,
                    ) as error:
                        self._record_attempt(
                            AttemptRecord(
                                dispatch_id,
                                terminal,
                                retry_of,
                                resumed_from,
                                interruption_receipt,
                            )
                        )
                        raise FleetExecutionError(
                            "interrupted shard checkpoint custody could not be persisted"
                        ) from error
                self._record_attempt(
                    AttemptRecord(
                        dispatch_id,
                        terminal,
                        retry_of,
                        resumed_from,
                        interruption_receipt,
                    )
                )
                last_error = interruption
                retry = (
                    isinstance(interruption, PreemptedError) and self.retry_policy.retry_preempted
                ) or (
                    isinstance(interruption, BudgetExhaustedError)
                    and self.retry_policy.retry_budget_exhausted
                )
                if not retry or offset + 1 >= self.retry_policy.max_attempts:
                    raise
                retry_of = terminal.id
                resumed_from = terminal.checkpoint
            except _LeaseReadinessRefusal:
                try:
                    released = self.custody.terminate(
                        lease.id,
                        LeaseState.RELEASED,
                        now=self._now(),
                        detail="dispatch readiness refused before operation execution",
                    )
                except StaleLeaseError:
                    latest = self.custody.latest(shard.shard_hash)
                    if latest is None:
                        raise
                    released = latest
                self._record_attempt(AttemptRecord(dispatch_id, released, retry_of, resumed_from))
                raise
            except StaleLeaseError as error:
                latest = self.custody.latest(shard.shard_hash)
                if latest is not None and latest.terminal:
                    self._record_attempt(AttemptRecord(dispatch_id, latest, retry_of, resumed_from))
                raise FleetExecutionError(
                    f"stale lease rejected result for shard {shard.key!r}: {error}"
                ) from error
            except Exception as error:
                failed = self._terminal_failure(lease, error)
                self._record_attempt(AttemptRecord(dispatch_id, failed, retry_of, resumed_from))
                last_error = error
                if not self.retry_policy.retry_failures or (
                    offset + 1 >= self.retry_policy.max_attempts
                ):
                    if isinstance(error, FleetExecutionError):
                        raise
                    raise FleetExecutionError(
                        f"shard {shard.key!r} failed on worker {worker.id!r}: {error}"
                    ) from error
                retry_of = failed.id
                resumed_from = None
            finally:
                self._release(worker.id, lease.id)

        # The loop always returns or raises on its final iteration.
        raise FleetExecutionError(f"shard {shard.key!r} exhausted retries") from last_error

    def _scheduled_run(
        self,
        dispatch_id: str,
        task: TaskSpec,
        operation: FleetOperation,
        plan: FleetPlan,
        *,
        resume_checkpoints: Mapping[str, CheckpointRef] | None = None,
    ) -> tuple[tuple[ShardResult, ...], tuple[ShardAssignment, ...]]:
        if plan.task != task:
            raise FleetExecutionError("cannot run a plan for a different task")
        if not plan.shards:
            return (), ()
        ranked = self.workers.ranked(task)
        selected = ranked[: min(self.max_workers, len(ranked), len(plan.shards))]
        queues: dict[str, list[tuple[int, ShardSpec]]] = {worker.id: [] for worker in selected}
        workers_by_id = {worker.id: worker for worker in selected}
        assignments: list[ShardAssignment] = []
        for index, shard in enumerate(plan.shards):
            worker = selected[index % len(selected)]
            queues[worker.id].append((index, shard))
            assignments.append(ShardAssignment(shard.shard_hash, shard.key, worker.id))

        scheduled = tuple(
            FleetShardDispatch(
                ordinal=index,
                shard_hash=shard.shard_hash,
                shard_key=shard.key,
                worker_id=assignments[index].worker_id,
            )
            for index, shard in enumerate(plan.shards)
        )

        def run_queue(worker: Worker) -> tuple[tuple[int, ShardResult], ...]:
            completed: list[tuple[int, ShardResult]] = []
            queue = queues[worker.id]
            for position, (index, shard) in enumerate(queue):
                try:
                    result = self._run_scheduled_one(
                        dispatch_id,
                        task,
                        operation,
                        shard,
                        worker,
                        plan.plan_hash,
                        (
                            None
                            if resume_checkpoints is None
                            else resume_checkpoints.get(shard.shard_hash)
                        ),
                    )
                except Exception as error:
                    pending = tuple(
                        FleetShardDispatch(
                            ordinal=pending_index,
                            shard_hash=pending_shard.shard_hash,
                            shard_key=pending_shard.key,
                            worker_id=worker.id,
                        )
                        for pending_index, pending_shard in queue[position + 1 :]
                    )
                    queue_error = _WorkerQueueError(
                        worker.id,
                        shard,
                        index,
                        pending,
                        completed,
                        error,
                    )
                    raise queue_error from error
                completed.append((index, result))
            return tuple(completed)

        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            futures = tuple(
                (worker.id, pool.submit(run_queue, workers_by_id[worker.id])) for worker in selected
            )
            indexed_items: list[tuple[int, ShardResult]] = []
            errors: list[_WorkerQueueError] = []
            # Read every deterministic worker queue so simultaneous per-shard
            # interruptions all persist custody before the first is surfaced.
            for _worker_id, future in futures:
                try:
                    indexed_items.extend(future.result())
                except _WorkerQueueError as error:
                    indexed_items.extend(error.completed)
                    errors.append(error)
        if errors:
            readiness_refusals = tuple(
                error.cause for error in errors if isinstance(error.cause, _LeaseReadinessRefusal)
            )
            if readiness_refusals:
                # A readiness refusal is an authorization decision, not a
                # mathematical or scheduler failure.  In particular, do not
                # synthesize a checkpoint manifest (which would itself write
                # an artifact) and do not aggregate it into FleetDispatchError.
                first = readiness_refusals[0]
                assert isinstance(first, _LeaseReadinessRefusal)
                raise first.cause
            manifest = self._build_checkpoint_manifest(
                task,
                plan,
                dispatch_id=dispatch_id,
                resume_checkpoints=resume_checkpoints,
                completed_shard_hashes=tuple(
                    result.shard.shard_hash for _, result in indexed_items
                ),
            )
            if len(errors) == 1 and not errors[0].pending and manifest is None:
                raise errors[0].cause
            raise FleetDispatchError(
                tuple(
                    FleetDispatchFailure.from_error(
                        error.worker_id,
                        error.shard,
                        error.shard_ordinal,
                        error.pending,
                        error.cause,
                    )
                    for error in errors
                ),
                scheduled=scheduled,
                checkpoint_manifest=manifest,
            )
        indexed = tuple(indexed_items)
        ordered = tuple(result for _, result in sorted(indexed, key=lambda item: item[0]))
        return ordered, tuple(assignments)

    def run(
        self,
        task: TaskSpec,
        operation: FleetOperation,
        plan: FleetPlan,
    ) -> tuple[ShardResult, ...]:
        dispatch_id = self._new_dispatch_id(task, plan)
        results, _ = self._scheduled_run(dispatch_id, task, operation, plan)
        return results

    def execute(
        self,
        task: TaskSpec,
        operation: FleetOperation,
        *,
        verify: bool = False,
    ) -> FleetRun:
        plan = self.plan(task, operation)
        return self._execute_plan(task, operation, plan, verify=verify)

    def _execute_plan(
        self,
        task: TaskSpec,
        operation: FleetOperation,
        plan: FleetPlan,
        *,
        verify: bool,
        resume_checkpoints: Mapping[str, CheckpointRef] | None = None,
    ) -> FleetRun:
        dispatch_id = self._new_dispatch_id(task, plan)
        shards, assignments = self._scheduled_run(
            dispatch_id,
            task,
            operation,
            plan,
            resume_checkpoints=resume_checkpoints,
        )
        run = self.reduce(task, operation, plan, shards, verify=verify)
        attempts = self.attempt_records(dispatch_id=dispatch_id)
        receipt = FleetExecutionReceipt(
            dispatch_id=dispatch_id,
            task_hash=task.task_hash,
            plan_hash=plan.plan_hash,
            result=run.result,
            state=run.state,
            assignments=assignments,
            attempts=attempts,
            resumed=run.resumed,
        )
        key = (task.task_hash, plan.plan_hash, run.result.uri)
        with self._attempt_lock:
            self._receipts[key] = receipt
            # Keep the run object alongside its identity-keyed entry so two
            # concurrent resumptions of the same deterministic result cannot
            # overwrite the "just completed" receipt seen by Campaign.
            self._receipts_by_run[id(run)] = (run, receipt)
        return run

    def resolve_checkpoint(
        self,
        task: TaskSpec,
        plan: FleetPlan,
        checkpoint_ref: CheckpointRef | str,
    ) -> CheckpointRef:
        """Resolve exact typed checkpoint custody for this task and plan.

        Typed references replay a persisted custody receipt and therefore work
        in a fresh executor sharing the same trusted local artifact store.  A
        bare content URI is deliberately weaker and resolves only through
        current-runtime lease custody.
        """

        if isinstance(checkpoint_ref, CheckpointRef):
            checkpoint = checkpoint_ref
            shard = next(
                (
                    candidate
                    for candidate in plan.shards
                    if candidate.shard_hash == checkpoint.shard_hash
                ),
                None,
            )
            if shard is None:
                raise ResumeUnavailableError(
                    "checkpoint is not bound to a shard in the current deterministic plan"
                )
            self._replay_checkpoint(task, plan, shard, checkpoint)
            return checkpoint
        if (
            not isinstance(checkpoint_ref, str)
            or not checkpoint_ref.startswith("sha256:")
            or not _SHA256_RE.fullmatch(checkpoint_ref.removeprefix("sha256:"))
        ):
            raise ResumeUnavailableError(
                "checkpoint_ref must be a canonical sha256 content reference"
            )
        candidates: list[tuple[LeaseRecord, CheckpointRef]] = []
        for record in self.custody.records():
            candidate_checkpoint = record.checkpoint
            if candidate_checkpoint is None or candidate_checkpoint.artifact.uri != checkpoint_ref:
                continue
            if record.task_hash == task.task_hash:
                candidates.append((record, candidate_checkpoint))
        if not candidates:
            raise ResumeUnavailableError(
                "checkpoint reference has no typed custody for this exact fleet task"
            )
        exact = {
            (record.shard_hash, checkpoint)
            for record, checkpoint in candidates
            if self.custody.latest(record.shard_hash) == record
        }
        if len(exact) != 1:
            raise ResumeUnavailableError(
                "checkpoint reference is stale or ambiguous in local custody"
            )
        shard_hash, checkpoint = next(iter(exact))
        shard = next(
            (candidate for candidate in plan.shards if candidate.shard_hash == shard_hash),
            None,
        )
        if shard is None:
            raise ResumeUnavailableError(
                "checkpoint is not bound to a shard in the current deterministic plan"
            )
        self._replay_checkpoint(task, plan, shard, checkpoint)
        return checkpoint

    def execute_checkpointed(
        self,
        task: TaskSpec,
        operation: FleetOperation,
        *,
        checkpoint_ref: CheckpointManifest | CheckpointRef | str,
        verify: bool = False,
    ) -> FleetRun:
        """Resume an exact persisted per-shard checkpoint or manifest."""

        plan = self.plan(task, operation)
        if isinstance(checkpoint_ref, CheckpointManifest):
            if (
                checkpoint_ref.task_hash != task.task_hash
                or checkpoint_ref.plan_hash != plan.plan_hash
            ):
                raise ResumeUnavailableError(
                    "checkpoint manifest is bound to a different task or plan"
                )
            checkpoints = tuple(
                self.resolve_checkpoint(task, plan, checkpoint)
                for checkpoint in checkpoint_ref.checkpoints
            )
        else:
            checkpoints = (self.resolve_checkpoint(task, plan, checkpoint_ref),)
        return self._execute_plan(
            task,
            operation,
            plan,
            verify=verify,
            resume_checkpoints={checkpoint.shard_hash: checkpoint for checkpoint in checkpoints},
        )

    def execute_registered(
        self,
        task: TaskSpec,
        *,
        registry: FleetOperationRegistry | None = None,
        verify: bool = False,
    ) -> FleetRun:
        return super().execute_registered(task, registry=registry, verify=verify)

    def lease_records(self, *, task_hash: str | None = None) -> tuple[LeaseRecord, ...]:
        return self.custody.records(task_hash=task_hash)

    def attempt_records(
        self,
        *,
        task_hash: str | None = None,
        dispatch_id: str | None = None,
    ) -> tuple[AttemptRecord, ...]:
        with self._attempt_lock:
            records = tuple(
                record
                for record in self._attempts
                if (task_hash is None or record.lease.task_hash == task_hash)
                and (dispatch_id is None or record.dispatch_id == dispatch_id)
            )
        return tuple(
            sorted(
                records,
                key=lambda record: (
                    record.lease.shard_hash,
                    record.lease.attempt,
                    record.lease.id,
                ),
            )
        )

    def receipt_for(self, run: FleetRun) -> FleetExecutionReceipt:
        """Return the latest scheduler receipt bound to this exact run."""

        self.validate_run(run)
        key = (run.task.task_hash, run.plan.plan_hash, run.result.uri)
        with self._attempt_lock:
            direct = self._receipts_by_run.get(id(run))
            if direct is not None and direct[0] is run:
                return direct[1]
            try:
                return self._receipts[key]
            except KeyError as error:
                raise FleetExecutionError(
                    "no local worker execution receipt is bound to this fleet run"
                ) from error

    def status(self, *, task_hash: str | None = None) -> FleetSchedulerStatus:
        records = self.lease_records(task_hash=task_hash)
        with self._condition:
            active_by_worker = dict(self._active_by_worker)
            active_tasks = dict(self._active_tasks)
        occupancies: list[WorkerOccupancy] = []
        for worker in self.workers.workers:
            worker_records = tuple(record for record in records if record.worker_id == worker.id)
            active = active_by_worker.get(worker.id)
            active_task = active_tasks.get(worker.id)
            if (
                task_hash is not None
                and active_task is not None
                and active_task.task_hash != task_hash
            ):
                active = None
                active_task = None
            capabilities = tuple(
                sorted(
                    {
                        capability
                        for backend in worker.backends
                        if backend.available
                        for capability in backend.capabilities
                    }
                )
            )
            used = None if active_task is None else active_task.resources
            state = WorkerState.BUSY if active is not None else worker.state
            occupancies.append(
                WorkerOccupancy(
                    worker_id=worker.id,
                    state=state,
                    capabilities=capabilities,
                    active_lease_ids=() if active is None else (active.id,),
                    active_task_hashes=(() if active_task is None else (active_task.task_hash,)),
                    used_resources=FrozenMapping(
                        {
                            "cpu_cores": 0,
                            "gpu_count": 0,
                            "memory_bytes": 0,
                            "scratch_bytes": 0,
                            "wall_time_seconds": None,
                        }
                        if used is None
                        else _resource_projection(used)
                    ),
                    available_resources=FrozenMapping(_available_resources(worker.resources, used)),
                    completed_count=sum(
                        record.state is LeaseState.COMPLETED for record in worker_records
                    ),
                    failed_count=sum(
                        record.state is LeaseState.FAILED for record in worker_records
                    ),
                    preempted_count=sum(
                        record.state is LeaseState.PREEMPTED for record in worker_records
                    ),
                    budget_exhausted_count=sum(
                        record.state is LeaseState.BUDGET_EXHAUSTED for record in worker_records
                    ),
                    expired_count=sum(
                        record.state is LeaseState.EXPIRED for record in worker_records
                    ),
                    released_count=sum(
                        record.state is LeaseState.RELEASED for record in worker_records
                    ),
                )
            )
        return FleetSchedulerStatus(
            workers=tuple(occupancies),
            active_count=sum(not record.terminal for record in records),
            completed_count=sum(record.state is LeaseState.COMPLETED for record in records),
            failed_count=sum(record.state is LeaseState.FAILED for record in records),
            preempted_count=sum(record.state is LeaseState.PREEMPTED for record in records),
            budget_exhausted_count=sum(
                record.state is LeaseState.BUDGET_EXHAUSTED for record in records
            ),
            expired_count=sum(record.state is LeaseState.EXPIRED for record in records),
            released_count=sum(record.state is LeaseState.RELEASED for record in records),
        )
