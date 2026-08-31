"""Operational leases, checkpoints, and interruption distinctions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from arbogast.formats import FrozenMapping, JSONValue, canonical_sha256

from .models import ArtifactRef, ShardSpec, TaskSpec
from .workers import Worker, WorkerPool

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LEASE_ID_RE = re.compile(r"^lease:[0-9a-f]{64}$")


def _require_canonical_utc_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("checkpoint created_at must be a string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError("checkpoint created_at must be a canonical UTC timestamp") from error
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value != canonical:
        raise ValueError("checkpoint created_at must be a canonical UTC timestamp")
    return value


class LeaseState(StrEnum):
    OFFERED = "offered"
    ACTIVE = "active"
    COMPLETED = "completed"
    RELEASED = "released"
    EXPIRED = "expired"
    PREEMPTED = "preempted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class InterruptionReason(StrEnum):
    """Operational interruptions that are not mathematical outcomes."""

    PREEMPTED = "preempted"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class CheckpointRef:
    """A shard-bound resume checkpoint stored as immutable content."""

    artifact: ArtifactRef
    shard_hash: str
    sequence: int
    created_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ArtifactRef):
            raise ValueError("checkpoint artifact must be an ArtifactRef")
        if not isinstance(self.shard_hash, str) or not _SHA256_RE.fullmatch(self.shard_hash):
            raise ValueError("checkpoint shard hash is not canonical")
        _require_canonical_utc_timestamp(self.created_at)
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("checkpoint sequence must be a non-negative integer")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "artifact": self.artifact.to_dict(),
            "created_at": self.created_at,
            "sequence": self.sequence,
            "shard_hash": self.shard_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CheckpointRef:
        """Strictly replay a persisted typed checkpoint reference."""

        required = {"artifact", "created_at", "sequence", "shard_hash"}
        if set(value) != required:
            raise ValueError("checkpoint has missing or unknown fields")
        artifact_value = value["artifact"]
        created_at = value["created_at"]
        sequence = value["sequence"]
        shard_hash = value["shard_hash"]
        if not isinstance(artifact_value, Mapping):
            raise ValueError("checkpoint artifact must be an object")
        if not isinstance(created_at, str) or not isinstance(shard_hash, str):
            raise ValueError("checkpoint shard_hash and created_at must be strings")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise ValueError("checkpoint sequence must be an integer")
        return cls(
            ArtifactRef.from_dict(artifact_value),
            shard_hash,
            sequence,
            created_at,
        )


_TERMINAL_STATES = {
    LeaseState.COMPLETED,
    LeaseState.RELEASED,
    LeaseState.EXPIRED,
    LeaseState.PREEMPTED,
    LeaseState.BUDGET_EXHAUSTED,
    LeaseState.FAILED,
}

_TRANSITIONS = {
    LeaseState.OFFERED: {LeaseState.ACTIVE, LeaseState.RELEASED, LeaseState.EXPIRED},
    LeaseState.ACTIVE: {
        LeaseState.COMPLETED,
        LeaseState.RELEASED,
        LeaseState.EXPIRED,
        LeaseState.PREEMPTED,
        LeaseState.BUDGET_EXHAUSTED,
        LeaseState.FAILED,
    },
}


@dataclass(frozen=True, slots=True)
class LeaseRecord:
    """An immutable operational assignment receipt."""

    id: str
    task_hash: str
    shard_hash: str
    worker_id: str
    attempt: int
    acquired_at: str
    expires_at: str
    state: LeaseState = LeaseState.OFFERED
    checkpoint: CheckpointRef | None = None
    detail: str | None = None

    @staticmethod
    def canonical_id(
        *,
        task_hash: str,
        shard_hash: str,
        worker_id: str,
        attempt: int,
        acquired_at: str,
        expires_at: str,
    ) -> str:
        return "lease:" + canonical_sha256(
            {
                "acquired_at": acquired_at,
                "attempt": attempt,
                "expires_at": expires_at,
                "shard_hash": shard_hash,
                "task_hash": task_hash,
                "worker_id": worker_id,
            }
        )

    def __post_init__(self) -> None:
        identity = (self.id, self.task_hash, self.shard_hash, self.worker_id)
        if any(not isinstance(value, str) or not value for value in identity):
            raise ValueError("lease identity fields must not be empty")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 0:
            raise ValueError("lease attempt must be a non-negative integer")
        if not isinstance(self.state, LeaseState):
            raise ValueError("lease state must be a LeaseState")
        if not _SHA256_RE.fullmatch(self.task_hash) or not _SHA256_RE.fullmatch(self.shard_hash):
            raise ValueError("lease task_hash and shard_hash must be canonical SHA-256")
        if (
            not isinstance(self.acquired_at, str)
            or not isinstance(self.expires_at, str)
            or not self.acquired_at.strip()
            or not self.expires_at.strip()
        ):
            raise ValueError("lease timestamps must be non-empty strings")
        try:
            acquired = datetime.fromisoformat(self.acquired_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("lease timestamps must be parseable") from error
        if acquired.tzinfo is None or expires.tzinfo is None:
            raise ValueError("lease timestamps must be timezone-aware")
        if expires <= acquired:
            raise ValueError("lease expiry must be later than acquisition")
        if not _LEASE_ID_RE.fullmatch(self.id):
            raise ValueError("lease id must be lease:<64 lowercase hex>")
        expected_id = self.canonical_id(
            task_hash=self.task_hash,
            shard_hash=self.shard_hash,
            worker_id=self.worker_id,
            attempt=self.attempt,
            acquired_at=self.acquired_at,
            expires_at=self.expires_at,
        )
        if self.id != expected_id:
            raise ValueError("lease id does not match its canonical identity")
        if self.detail is not None and not isinstance(self.detail, str):
            raise ValueError("lease detail must be a string or None")
        if self.checkpoint is not None and not isinstance(self.checkpoint, CheckpointRef):
            raise ValueError("lease checkpoint must be a CheckpointRef or None")
        if self.checkpoint is not None and self.checkpoint.shard_hash != self.shard_hash:
            raise ValueError("checkpoint belongs to a different shard")
        if (
            self.state
            in {
                LeaseState.PREEMPTED,
                LeaseState.BUDGET_EXHAUSTED,
                LeaseState.FAILED,
            }
            and not self.detail
        ):
            raise ValueError(f"{self.state.value} lease records require detail")

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    def transition(
        self,
        state: LeaseState,
        *,
        checkpoint: CheckpointRef | None = None,
        detail: str | None = None,
    ) -> LeaseRecord:
        if not isinstance(state, LeaseState):
            raise ValueError("lease transition state must be a LeaseState")
        if checkpoint is not None and not isinstance(checkpoint, CheckpointRef):
            raise ValueError("lease transition checkpoint must be a CheckpointRef")
        if detail is not None and not isinstance(detail, str):
            raise ValueError("lease transition detail must be a string")
        allowed = _TRANSITIONS.get(self.state, set())
        if state not in allowed:
            raise ValueError(f"invalid lease transition {self.state.value} -> {state.value}")
        return replace(
            self,
            state=state,
            checkpoint=self.checkpoint if checkpoint is None else checkpoint,
            detail=detail,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "acquired_at": self.acquired_at,
            "attempt": self.attempt,
            "checkpoint": None if self.checkpoint is None else self.checkpoint.to_dict(),
            "detail": self.detail,
            "expires_at": self.expires_at,
            "id": self.id,
            "shard_hash": self.shard_hash,
            "state": self.state.value,
            "task_hash": self.task_hash,
            "worker_id": self.worker_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LeaseRecord:
        """Strictly replay a serialized operational lease receipt."""

        required = {
            "acquired_at",
            "attempt",
            "checkpoint",
            "detail",
            "expires_at",
            "id",
            "shard_hash",
            "state",
            "task_hash",
            "worker_id",
        }
        if set(value) != required:
            raise ValueError("lease record has missing or unknown fields")
        checkpoint_value = value["checkpoint"]
        if checkpoint_value is not None and not isinstance(checkpoint_value, Mapping):
            raise ValueError("lease checkpoint must be an object or null")
        strings = {
            name: value[name]
            for name in (
                "acquired_at",
                "expires_at",
                "id",
                "shard_hash",
                "state",
                "task_hash",
                "worker_id",
            )
        }
        if any(not isinstance(item, str) for item in strings.values()):
            raise ValueError("lease identity/state fields must be strings")
        attempt = value["attempt"]
        detail = value["detail"]
        if isinstance(attempt, bool) or not isinstance(attempt, int):
            raise ValueError("lease attempt must be an integer")
        if detail is not None and not isinstance(detail, str):
            raise ValueError("lease detail must be a string or null")
        try:
            state = LeaseState(strings["state"])
        except ValueError as error:
            raise ValueError("lease state is invalid") from error
        return cls(
            id=strings["id"],
            task_hash=strings["task_hash"],
            shard_hash=strings["shard_hash"],
            worker_id=strings["worker_id"],
            attempt=attempt,
            acquired_at=strings["acquired_at"],
            expires_at=strings["expires_at"],
            state=state,
            checkpoint=(
                None if checkpoint_value is None else CheckpointRef.from_dict(checkpoint_value)
            ),
            detail=detail,
        )


@dataclass(frozen=True, slots=True)
class InterruptionReceipt:
    """Typed scheduler custody and telemetry for one interrupted attempt."""

    dispatch_id: str
    lease: LeaseRecord
    reason: InterruptionReason
    retry_of: str | None = None
    resumed_from: CheckpointRef | None = None
    progress_completed: int | None = None
    progress_total: int | None = None
    resources: FrozenMapping = field(default_factory=FrozenMapping)
    spent: FrozenMapping = field(default_factory=FrozenMapping)

    schema = "arbogast.fleet.interruption-receipt.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.dispatch_id, str) or not self.dispatch_id.startswith("dispatch:"):
            raise ValueError("interruption receipt dispatch_id is invalid")
        if not isinstance(self.lease, LeaseRecord) or not self.lease.terminal:
            raise ValueError("interruption receipt lease must be terminal")
        if not isinstance(self.reason, InterruptionReason):
            raise ValueError("interruption receipt reason is invalid")
        expected_state = {
            InterruptionReason.PREEMPTED: LeaseState.PREEMPTED,
            InterruptionReason.BUDGET_EXHAUSTED: LeaseState.BUDGET_EXHAUSTED,
        }[self.reason]
        if self.lease.state is not expected_state:
            raise ValueError("interruption receipt reason does not match lease state")
        if self.retry_of is not None and (
            not isinstance(self.retry_of, str) or not self.retry_of.strip()
        ):
            raise ValueError("interruption receipt retry_of must be non-empty or null")
        if self.resumed_from is not None:
            if not isinstance(self.resumed_from, CheckpointRef):
                raise ValueError("interruption receipt resumed_from is invalid")
            if self.resumed_from.shard_hash != self.lease.shard_hash:
                raise ValueError("interruption resume checkpoint belongs to another shard")
        for name, count in (
            ("progress_completed", self.progress_completed),
            ("progress_total", self.progress_total),
        ):
            if count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or count < 0
            ):
                raise ValueError(f"interruption receipt {name} must be non-negative")
        if (
            self.progress_completed is not None
            and self.progress_total is not None
            and self.progress_completed > self.progress_total
        ):
            raise ValueError("interruption progress exceeds its total")
        if not isinstance(self.resources, FrozenMapping) or not isinstance(
            self.spent, FrozenMapping
        ):
            raise ValueError("interruption resources/spent must be FrozenMapping values")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "dispatch_id": self.dispatch_id,
            "lease": self.lease.to_dict(),
            "progress_completed": self.progress_completed,
            "progress_total": self.progress_total,
            "reason": self.reason.value,
            "resources": self.resources.to_dict(),
            "resumed_from": (None if self.resumed_from is None else self.resumed_from.to_dict()),
            "retry_of": self.retry_of,
            "schema": self.schema,
            "spent": self.spent.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> InterruptionReceipt:
        required = {
            "dispatch_id",
            "lease",
            "progress_completed",
            "progress_total",
            "reason",
            "resources",
            "resumed_from",
            "retry_of",
            "schema",
            "spent",
        }
        if set(value) != required:
            raise ValueError("interruption receipt has missing or unknown fields")
        if value["schema"] != cls.schema:
            raise ValueError("unsupported interruption receipt schema")
        lease = value["lease"]
        resumed_from = value["resumed_from"]
        resources = value["resources"]
        spent = value["spent"]
        if not isinstance(lease, Mapping):
            raise ValueError("interruption receipt lease must be an object")
        if resumed_from is not None and not isinstance(resumed_from, Mapping):
            raise ValueError("interruption receipt resumed_from must be an object or null")
        if not isinstance(resources, Mapping) or not isinstance(spent, Mapping):
            raise ValueError("interruption resources/spent must be objects")
        dispatch_id = value["dispatch_id"]
        reason = value["reason"]
        retry_of = value["retry_of"]
        if not isinstance(dispatch_id, str) or not isinstance(reason, str):
            raise ValueError("interruption receipt identity fields must be strings")
        if retry_of is not None and not isinstance(retry_of, str):
            raise ValueError("interruption receipt retry_of must be a string or null")
        try:
            resolved_reason = InterruptionReason(reason)
        except ValueError as error:
            raise ValueError("interruption receipt reason is invalid") from error
        return cls(
            dispatch_id=dispatch_id,
            lease=LeaseRecord.from_dict(lease),
            reason=resolved_reason,
            retry_of=retry_of,
            resumed_from=(None if resumed_from is None else CheckpointRef.from_dict(resumed_from)),
            progress_completed=value["progress_completed"],
            progress_total=value["progress_total"],
            resources=FrozenMapping(resources),
            spent=FrozenMapping(spent),
        )


class FleetInterruption(RuntimeError):
    """A resumable operational interruption, never a mathematical verdict."""

    def __init__(
        self,
        reason: InterruptionReason,
        detail: str,
        *,
        checkpoint: CheckpointRef | None = None,
        progress_completed: int | None = None,
        progress_total: int | None = None,
        resources: Mapping[str, Any] | None = None,
        spent: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(reason, InterruptionReason):
            raise ValueError("fleet interruption reason must be an InterruptionReason")
        if not isinstance(detail, str) or not detail.strip():
            raise ValueError("fleet interruption detail must be a non-empty string")
        if checkpoint is not None and not isinstance(checkpoint, CheckpointRef):
            raise ValueError("fleet interruption checkpoint must be a CheckpointRef")
        for name, count in (
            ("progress_completed", progress_completed),
            ("progress_total", progress_total),
        ):
            if count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or count < 0
            ):
                raise ValueError(f"fleet interruption {name} must be non-negative")
        if (
            progress_completed is not None
            and progress_total is not None
            and progress_completed > progress_total
        ):
            raise ValueError("fleet interruption progress exceeds its total")
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.checkpoint = checkpoint
        self.progress_completed = progress_completed
        self.progress_total = progress_total
        self.resources = FrozenMapping(resources)
        self.spent = FrozenMapping(spent)
        self.receipt: InterruptionReceipt | None = None

    def bind_receipt(self, receipt: InterruptionReceipt) -> None:
        """Bind this worker report to one terminal scheduler receipt exactly once."""

        if not isinstance(receipt, InterruptionReceipt):
            raise ValueError("fleet interruption receipt has invalid type")
        if self.receipt is not None:
            raise ValueError("fleet interruption already has a scheduler receipt")
        if receipt.reason is not self.reason or receipt.lease.checkpoint != self.checkpoint:
            raise ValueError("fleet interruption receipt does not match the report")
        if (
            receipt.progress_completed != self.progress_completed
            or receipt.progress_total != self.progress_total
            or receipt.resources != self.resources
            or receipt.spent != self.spent
        ):
            raise ValueError("fleet interruption telemetry changed at scheduler binding")
        self.receipt = receipt


class PreemptedError(FleetInterruption):
    def __init__(
        self,
        detail: str,
        *,
        checkpoint: CheckpointRef | None = None,
        progress_completed: int | None = None,
        progress_total: int | None = None,
        resources: Mapping[str, Any] | None = None,
        spent: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            InterruptionReason.PREEMPTED,
            detail,
            checkpoint=checkpoint,
            progress_completed=progress_completed,
            progress_total=progress_total,
            resources=resources,
            spent=spent,
        )


class BudgetExhaustedError(FleetInterruption):
    def __init__(
        self,
        detail: str,
        *,
        checkpoint: CheckpointRef | None = None,
        progress_completed: int | None = None,
        progress_total: int | None = None,
        resources: Mapping[str, Any] | None = None,
        spent: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            InterruptionReason.BUDGET_EXHAUSTED,
            detail,
            checkpoint=checkpoint,
            progress_completed=progress_completed,
            progress_total=progress_total,
            resources=resources,
            spent=spent,
        )


class SchedulerProtocol:
    """Minimal extension point for SSH, Slurm, and other schedulers."""

    def select(self, pool: WorkerPool, task: TaskSpec) -> Worker:
        return pool.select(task)

    def lease(
        self,
        pool: WorkerPool,
        task: TaskSpec,
        shard: ShardSpec,
        *,
        attempt: int,
        acquired_at: str,
        expires_at: str,
    ) -> LeaseRecord:
        if shard.task_hash != task.task_hash:
            raise ValueError("cannot lease a shard belonging to a different task")
        worker = self.select(pool, task)
        return LeaseRecord(
            id=LeaseRecord.canonical_id(
                task_hash=task.task_hash,
                shard_hash=shard.shard_hash,
                worker_id=worker.id,
                attempt=attempt,
                acquired_at=acquired_at,
                expires_at=expires_at,
            ),
            task_hash=task.task_hash,
            shard_hash=shard.shard_hash,
            worker_id=worker.id,
            attempt=attempt,
            acquired_at=acquired_at,
            expires_at=expires_at,
        )
