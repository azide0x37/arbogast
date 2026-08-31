"""Canonical candidate and execution-attempt records for campaign ledgers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from arbogast.formats import FrozenMapping, JSONValue, canonical_sha256

from .errors import CampaignInvariantError, CampaignSerializationError
from .events import OperationalState

_CONTENT_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _content_ref(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _CONTENT_REF_RE.fullmatch(value):
        raise CampaignInvariantError(f"{field_name} must be a canonical sha256 content reference")
    return value


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CampaignSerializationError(f"{field_name} must be an array of strings")
    result = tuple(dict.fromkeys(value))
    if any(not item.strip() for item in result):
        raise CampaignSerializationError(f"{field_name} entries cannot be blank")
    return result


class CandidateEvidence(StrEnum):
    """Epistemic level of a candidate object, without theorem promotion."""

    UNKNOWN = "UNKNOWN"
    HEURISTIC = "HEURISTIC"
    NUMERICAL = "NUMERICAL"
    EXACT = "EXACT"
    VERIFIED = "VERIFIED"

    @property
    def rank(self) -> int:
        return {
            CandidateEvidence.UNKNOWN: 0,
            CandidateEvidence.HEURISTIC: 1,
            CandidateEvidence.NUMERICAL: 2,
            CandidateEvidence.EXACT: 3,
            CandidateEvidence.VERIFIED: 4,
        }[self]


class CandidateScope(StrEnum):
    """Where a declared canonicalizer's equivalence relation is valid."""

    TARGET = "TARGET"
    GLOBAL = "GLOBAL"


def _counter_mapping(
    value: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> FrozenMapping:
    resolved = {} if value is None else value
    for key, count in resolved.items():
        if not isinstance(key, str) or not key.strip():
            raise CampaignInvariantError(f"{field_name} counter names must be non-blank strings")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise CampaignInvariantError(f"{field_name} counters must be non-negative integers")
    return FrozenMapping(resolved)


@dataclass(frozen=True, slots=True, init=False)
class ExecutionTelemetry:
    """Optional operation-reported counters for one successful fleet result.

    Absence of this envelope means that no measurements were reported.  A
    literal zero inside the envelope is an observed zero and is preserved.
    """

    progress_completed: int | None
    progress_total: int | None
    resources: FrozenMapping
    spent: FrozenMapping

    schema = "arbogast.campaign.execution-telemetry.v1"

    def __init__(
        self,
        *,
        progress_completed: int | None = None,
        progress_total: int | None = None,
        resources: Mapping[str, Any] | None = None,
        spent: Mapping[str, Any] | None = None,
    ) -> None:
        for field_name, count in (
            ("progress_completed", progress_completed),
            ("progress_total", progress_total),
        ):
            if count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or count < 0
            ):
                raise CampaignInvariantError(
                    f"execution telemetry {field_name} must be a non-negative integer or null"
                )
        if (
            progress_completed is not None
            and progress_total is not None
            and progress_completed > progress_total
        ):
            raise CampaignInvariantError("execution telemetry progress exceeds its total")
        resolved_resources = _counter_mapping(resources, field_name="resource")
        resolved_spent = _counter_mapping(spent, field_name="spend")
        if (
            progress_completed is None
            and progress_total is None
            and not resolved_resources
            and not resolved_spent
        ):
            raise CampaignInvariantError(
                "execution telemetry must report at least one progress, resource, or spend counter"
            )
        object.__setattr__(self, "progress_completed", progress_completed)
        object.__setattr__(self, "progress_total", progress_total)
        object.__setattr__(self, "resources", resolved_resources)
        object.__setattr__(self, "spent", resolved_spent)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "progress_completed": self.progress_completed,
            "progress_total": self.progress_total,
            "resources": self.resources.to_dict(),
            "schema": self.schema,
            "spent": self.spent.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ExecutionTelemetry:
        required = {
            "progress_completed",
            "progress_total",
            "resources",
            "schema",
            "spent",
        }
        if set(value) != required:
            raise CampaignSerializationError("execution telemetry has missing or unknown fields")
        if value["schema"] != cls.schema:
            raise CampaignSerializationError("unsupported execution telemetry schema")
        resources = value["resources"]
        spent = value["spent"]
        if not isinstance(resources, Mapping) or not isinstance(spent, Mapping):
            raise CampaignSerializationError("execution telemetry counters must be objects")
        for field_name in ("progress_completed", "progress_total"):
            count = value[field_name]
            if count is not None and (isinstance(count, bool) or not isinstance(count, int)):
                raise CampaignSerializationError(
                    f"execution telemetry {field_name} must be an integer or null"
                )
        try:
            return cls(
                progress_completed=value["progress_completed"],
                progress_total=value["progress_total"],
                resources=resources,
                spent=spent,
            )
        except CampaignInvariantError as error:
            raise CampaignSerializationError("execution telemetry is invalid") from error


@dataclass(frozen=True, slots=True, init=False)
class CandidateRecord:
    """One canonical mathematical object and its observation-bound provenance.

    ``canonical_key`` is supplied by the mathematical operation.  The ledger
    can therefore deduplicate objects only under that declared canonicalizer;
    it never guesses mathematical equivalence from filenames or stdout.
    ``quality`` is an inspectable integer where larger is better.
    """

    target_id: str
    task_id: str
    observation_id: str
    canonical_key: str
    canonicalizer: str
    equivalence_scope: CandidateScope
    artifact_ref: str
    invariants: FrozenMapping
    evidence: CandidateEvidence
    quality: int
    quality_metric: str
    certificate_ref: str | None
    source_refs: tuple[str, ...]

    schema = "arbogast.campaign.candidate.v1"

    def __init__(
        self,
        target_id: str,
        task_id: str,
        observation_id: str,
        canonical_key: str,
        artifact_ref: object,
        *,
        canonicalizer: str,
        equivalence_scope: CandidateScope | str = CandidateScope.TARGET,
        invariants: Mapping[str, Any] | None = None,
        evidence: CandidateEvidence | str = CandidateEvidence.UNKNOWN,
        quality: int = 0,
        quality_metric: str = "campaign-quality",
        certificate_ref: object | None = None,
        source_refs: tuple[str, ...] = (),
    ) -> None:
        resolved_ids = (
            _content_ref(target_id, "candidate target_id"),
            _content_ref(task_id, "candidate task_id"),
            _content_ref(observation_id, "candidate observation_id"),
        )
        if not isinstance(canonical_key, str) or not canonical_key.strip():
            raise CampaignInvariantError("candidate canonical_key cannot be blank")
        if not isinstance(canonicalizer, str) or not canonicalizer.strip():
            raise CampaignInvariantError("candidate canonicalizer cannot be blank")
        if isinstance(quality, bool) or not isinstance(quality, int):
            raise CampaignInvariantError("candidate quality must be an integer")
        if not isinstance(quality_metric, str) or not quality_metric.strip():
            raise CampaignInvariantError("candidate quality_metric cannot be blank")
        resolved_sources = tuple(dict.fromkeys(source_refs))
        if any(not isinstance(item, str) or not item.strip() for item in resolved_sources):
            raise CampaignInvariantError("candidate source references cannot be blank")
        resolved_evidence = CandidateEvidence(evidence)
        resolved_certificate = (
            None
            if certificate_ref is None
            else _content_ref(certificate_ref, "candidate certificate_ref")
        )
        if resolved_evidence is CandidateEvidence.VERIFIED and resolved_certificate is None:
            raise CampaignInvariantError(
                "a VERIFIED candidate requires a verification certificate reference"
            )
        object.__setattr__(self, "target_id", resolved_ids[0])
        object.__setattr__(self, "task_id", resolved_ids[1])
        object.__setattr__(self, "observation_id", resolved_ids[2])
        object.__setattr__(self, "canonical_key", canonical_key)
        object.__setattr__(self, "canonicalizer", canonicalizer)
        object.__setattr__(self, "equivalence_scope", CandidateScope(equivalence_scope))
        object.__setattr__(
            self,
            "artifact_ref",
            _content_ref(artifact_ref, "candidate artifact_ref"),
        )
        object.__setattr__(self, "invariants", FrozenMapping(invariants))
        object.__setattr__(self, "evidence", resolved_evidence)
        object.__setattr__(self, "quality", quality)
        object.__setattr__(self, "quality_metric", quality_metric)
        object.__setattr__(self, "certificate_ref", resolved_certificate)
        object.__setattr__(self, "source_refs", resolved_sources)

    @property
    def candidate_id(self) -> str:
        identity = {
            "canonical_key": self.canonical_key,
            "canonicalizer": self.canonicalizer,
            "equivalence_scope": self.equivalence_scope.value,
            "schema": "arbogast.campaign.candidate-identity.v1",
        }
        if self.equivalence_scope is CandidateScope.TARGET:
            identity["target_id"] = self.target_id
        return f"sha256:{canonical_sha256(identity)}"

    @property
    def record_id(self) -> str:
        return f"sha256:{canonical_sha256(self.to_dict(include_record_id=False))}"

    def preference_key(self) -> tuple[int, int, str]:
        """Deterministic best-known ordering; larger first two fields win."""

        return (self.evidence.rank, self.quality, self.record_id)

    def better_than(self, other: CandidateRecord) -> bool:
        if self.quality_metric != other.quality_metric:
            raise CampaignInvariantError("cannot compare candidates with different quality metrics")
        left = (self.evidence.rank, self.quality)
        right = (other.evidence.rank, other.quality)
        if left != right:
            return left > right
        return self.record_id < other.record_id

    def to_dict(self, *, include_record_id: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "artifact_ref": self.artifact_ref,
            "candidate_id": self.candidate_id,
            "canonical_key": self.canonical_key,
            "canonicalizer": self.canonicalizer,
            "certificate_ref": self.certificate_ref,
            "evidence": self.evidence.value,
            "equivalence_scope": self.equivalence_scope.value,
            "invariants": self.invariants.to_dict(),
            "observation_id": self.observation_id,
            "quality": self.quality,
            "quality_metric": self.quality_metric,
            "schema": self.schema,
            "source_refs": list(self.source_refs),
            "target_id": self.target_id,
            "task_id": self.task_id,
        }
        if include_record_id:
            payload["record_id"] = self.record_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CandidateRecord:
        required = {
            "artifact_ref",
            "candidate_id",
            "canonical_key",
            "canonicalizer",
            "certificate_ref",
            "evidence",
            "equivalence_scope",
            "invariants",
            "observation_id",
            "quality",
            "quality_metric",
            "record_id",
            "schema",
            "source_refs",
            "target_id",
            "task_id",
        }
        if set(value) != required:
            raise CampaignSerializationError("candidate has missing or unknown fields")
        if value["schema"] != cls.schema:
            raise CampaignSerializationError("unsupported candidate schema")
        invariants = value["invariants"]
        if not isinstance(invariants, Mapping):
            raise CampaignSerializationError("candidate invariants must be an object")
        strings = {
            name: value[name]
            for name in (
                "artifact_ref",
                "canonical_key",
                "canonicalizer",
                "evidence",
                "equivalence_scope",
                "observation_id",
                "quality_metric",
                "target_id",
                "task_id",
            )
        }
        if any(not isinstance(item, str) for item in strings.values()):
            raise CampaignSerializationError("candidate string field has the wrong type")
        quality = value["quality"]
        if isinstance(quality, bool) or not isinstance(quality, int):
            raise CampaignSerializationError("candidate quality must be an integer")
        certificate = value["certificate_ref"]
        if certificate is not None and not isinstance(certificate, str):
            raise CampaignSerializationError("candidate certificate_ref must be a string or null")
        candidate = cls(
            target_id=strings["target_id"],
            task_id=strings["task_id"],
            observation_id=strings["observation_id"],
            canonical_key=strings["canonical_key"],
            canonicalizer=strings["canonicalizer"],
            artifact_ref=strings["artifact_ref"],
            equivalence_scope=CandidateScope(strings["equivalence_scope"]),
            invariants=invariants,
            evidence=CandidateEvidence(strings["evidence"]),
            quality=quality,
            quality_metric=strings["quality_metric"],
            certificate_ref=certificate,
            source_refs=_strings(value["source_refs"], "candidate source_refs"),
        )
        if not isinstance(value["candidate_id"], str) or (
            value["candidate_id"] != candidate.candidate_id
        ):
            raise CampaignSerializationError("candidate_id does not match canonical identity")
        if not isinstance(value["record_id"], str) or value["record_id"] != candidate.record_id:
            raise CampaignSerializationError("candidate record_id does not match contents")
        return candidate


@dataclass(frozen=True, slots=True, init=False)
class AttemptRecord:
    """One state in the event-sourced history of a local execution attempt."""

    target_id: str
    task_id: str
    attempt: int
    state: OperationalState
    worker_id: str | None
    checkpoint_ref: str | None
    detail: str | None
    progress_completed: int | None
    progress_total: int | None
    resources: FrozenMapping
    spent: FrozenMapping
    readiness_claim_id: str | None
    dispatch_readiness_receipt_id: str | None
    dispatch_readiness_receipt: FrozenMapping | None

    schema = "arbogast.campaign.attempt.v1"

    def __init__(
        self,
        target_id: str,
        task_id: str,
        attempt: int,
        state: OperationalState | str,
        *,
        worker_id: str | None = None,
        checkpoint_ref: object | None = None,
        detail: str | None = None,
        progress_completed: int | None = None,
        progress_total: int | None = None,
        resources: Mapping[str, Any] | None = None,
        spent: Mapping[str, Any] | None = None,
        readiness_claim_id: str | None = None,
        dispatch_readiness_receipt_id: str | None = None,
        dispatch_readiness_receipt: Mapping[str, Any] | None = None,
    ) -> None:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise CampaignInvariantError("attempt number must be a positive integer")
        if worker_id is not None and (not isinstance(worker_id, str) or not worker_id.strip()):
            raise CampaignInvariantError("attempt worker_id must be a non-blank string or null")
        if detail is not None and (not isinstance(detail, str) or not detail.strip()):
            raise CampaignInvariantError("attempt detail must be a non-blank string or null")
        if readiness_claim_id is not None and (
            not isinstance(readiness_claim_id, str) or not readiness_claim_id.strip()
        ):
            raise CampaignInvariantError(
                "attempt readiness_claim_id must be a non-blank string or null"
            )
        if dispatch_readiness_receipt_id is not None:
            dispatch_readiness_receipt_id = _content_ref(
                dispatch_readiness_receipt_id,
                "attempt dispatch_readiness_receipt_id",
            )
        if (dispatch_readiness_receipt_id is None) != (dispatch_readiness_receipt is None):
            raise CampaignInvariantError(
                "attempt dispatch receipt ID and data must be present together"
            )
        replayed_dispatch: FrozenMapping | None = None
        if dispatch_readiness_receipt is not None:
            if dispatch_readiness_receipt_id is None:
                raise CampaignInvariantError(
                    "attempt dispatch receipt data requires its receipt ID"
                )
            from arbogast.bootstrap.dispatch import DispatchReadinessReceipt

            try:
                replayed = DispatchReadinessReceipt.from_dict(dispatch_readiness_receipt)
            except (KeyError, TypeError, ValueError) as error:
                raise CampaignInvariantError(
                    "attempt dispatch readiness receipt failed strict replay"
                ) from error
            if replayed.receipt_id != dispatch_readiness_receipt_id:
                raise CampaignInvariantError(
                    "attempt dispatch receipt ID differs from its canonical data"
                )
            if replayed.campaign_task_id != task_id:
                raise CampaignInvariantError(
                    "attempt dispatch receipt belongs to a different campaign task"
                )
            if replayed.campaign_target_id != target_id:
                raise CampaignInvariantError(
                    "attempt dispatch receipt belongs to a different campaign target"
                )
            expected_attempt_id = "sha256:" + canonical_sha256(
                {
                    "attempt": attempt,
                    "schema": "arbogast.campaign.attempt-identity.v1",
                    "task_id": task_id,
                }
            )
            if (
                replayed.campaign_attempt != attempt
                or replayed.campaign_attempt_id != expected_attempt_id
            ):
                raise CampaignInvariantError(
                    "attempt dispatch receipt belongs to a different campaign attempt"
                )
            if worker_id is not None and replayed.lease.worker_id != worker_id:
                raise CampaignInvariantError(
                    "attempt worker differs from its dispatch receipt lease worker"
                )
            if readiness_claim_id != replayed.readiness_claim_id:
                raise CampaignInvariantError(
                    "attempt readiness claim differs from its dispatch receipt"
                )
            replayed_dispatch = FrozenMapping(replayed.to_dict())
        if progress_completed is not None and (
            isinstance(progress_completed, bool)
            or not isinstance(progress_completed, int)
            or progress_completed < 0
        ):
            raise CampaignInvariantError("attempt progress_completed must be non-negative or null")
        if progress_total is not None and (
            isinstance(progress_total, bool)
            or not isinstance(progress_total, int)
            or progress_total < 0
            or (progress_completed is not None and progress_completed > progress_total)
        ):
            raise CampaignInvariantError("attempt progress_total is invalid")
        object.__setattr__(self, "target_id", _content_ref(target_id, "attempt target_id"))
        object.__setattr__(self, "task_id", _content_ref(task_id, "attempt task_id"))
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "state", OperationalState(state))
        object.__setattr__(self, "worker_id", worker_id)
        object.__setattr__(
            self,
            "checkpoint_ref",
            (
                None
                if checkpoint_ref is None
                else _content_ref(checkpoint_ref, "attempt checkpoint_ref")
            ),
        )
        object.__setattr__(self, "detail", detail)
        object.__setattr__(self, "progress_completed", progress_completed)
        object.__setattr__(self, "progress_total", progress_total)
        object.__setattr__(
            self,
            "resources",
            _counter_mapping(resources, field_name="attempt resource"),
        )
        object.__setattr__(
            self,
            "spent",
            _counter_mapping(spent, field_name="attempt spend"),
        )
        object.__setattr__(self, "readiness_claim_id", readiness_claim_id)
        object.__setattr__(
            self,
            "dispatch_readiness_receipt_id",
            dispatch_readiness_receipt_id,
        )
        object.__setattr__(self, "dispatch_readiness_receipt", replayed_dispatch)

    @property
    def attempt_id(self) -> str:
        identity = {
            "attempt": self.attempt,
            "schema": "arbogast.campaign.attempt-identity.v1",
            "task_id": self.task_id,
        }
        return f"sha256:{canonical_sha256(identity)}"

    @property
    def record_id(self) -> str:
        return f"sha256:{canonical_sha256(self.to_dict(include_record_id=False))}"

    @property
    def live(self) -> bool:
        return self.state is OperationalState.RUNNING

    def to_dict(self, *, include_record_id: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "attempt": self.attempt,
            "attempt_id": self.attempt_id,
            "checkpoint_ref": self.checkpoint_ref,
            "detail": self.detail,
            "progress_completed": self.progress_completed,
            "progress_total": self.progress_total,
            "resources": self.resources.to_dict(),
            "schema": self.schema,
            "spent": self.spent.to_dict(),
            "state": self.state.value,
            "target_id": self.target_id,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
        }
        # Preserve the exact v1 transport and record IDs for every legacy
        # attempt.  The additive provenance field is emitted only for work
        # actually authorized by an environmental readiness claim.
        if self.readiness_claim_id is not None:
            payload["readiness_claim_id"] = self.readiness_claim_id
        if self.dispatch_readiness_receipt_id is not None:
            payload["dispatch_readiness_receipt_id"] = self.dispatch_readiness_receipt_id
        if self.dispatch_readiness_receipt is not None:
            payload["dispatch_readiness_receipt"] = self.dispatch_readiness_receipt.to_dict()
        if include_record_id:
            payload["record_id"] = self.record_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AttemptRecord:
        required = {
            "attempt",
            "attempt_id",
            "checkpoint_ref",
            "detail",
            "progress_completed",
            "progress_total",
            "record_id",
            "resources",
            "schema",
            "spent",
            "state",
            "target_id",
            "task_id",
            "worker_id",
        }
        allowed = required | {
            "readiness_claim_id",
            "dispatch_readiness_receipt_id",
            "dispatch_readiness_receipt",
        }
        if not required <= set(value) or not set(value) <= allowed:
            raise CampaignSerializationError("attempt has missing or unknown fields")
        if value["schema"] != cls.schema:
            raise CampaignSerializationError("unsupported attempt schema")
        raw_attempt = value["attempt"]
        if isinstance(raw_attempt, bool) or not isinstance(raw_attempt, int):
            raise CampaignSerializationError("attempt attempt must be an integer")
        completed = value["progress_completed"]
        if completed is not None and (
            isinstance(completed, bool) or not isinstance(completed, int)
        ):
            raise CampaignSerializationError(
                "attempt progress_completed must be an integer or null"
            )
        total = value["progress_total"]
        if total is not None and (isinstance(total, bool) or not isinstance(total, int)):
            raise CampaignSerializationError("attempt progress_total must be an integer or null")
        resources = value["resources"]
        spent = value["spent"]
        if not isinstance(resources, Mapping) or not isinstance(spent, Mapping):
            raise CampaignSerializationError("attempt resources/spent must be objects")
        strings: dict[str, str | None] = {}
        for field_name in (
            "checkpoint_ref",
            "detail",
            "state",
            "target_id",
            "task_id",
            "worker_id",
        ):
            raw = value[field_name]
            if raw is not None and not isinstance(raw, str):
                raise CampaignSerializationError(f"attempt {field_name} must be a string or null")
            strings[field_name] = raw
        readiness_claim_id = value.get("readiness_claim_id")
        if readiness_claim_id is not None and not isinstance(readiness_claim_id, str):
            raise CampaignSerializationError("attempt readiness_claim_id must be a string or null")
        dispatch_receipt_id = value.get("dispatch_readiness_receipt_id")
        if dispatch_receipt_id is not None and not isinstance(dispatch_receipt_id, str):
            raise CampaignSerializationError(
                "attempt dispatch_readiness_receipt_id must be a string or null"
            )
        dispatch_receipt = value.get("dispatch_readiness_receipt")
        if dispatch_receipt is not None and not isinstance(dispatch_receipt, Mapping):
            raise CampaignSerializationError(
                "attempt dispatch_readiness_receipt must be an object or null"
            )
        if strings["state"] is None or strings["target_id"] is None or strings["task_id"] is None:
            raise CampaignSerializationError("attempt state and IDs cannot be null")
        record = cls(
            target_id=strings["target_id"],
            task_id=strings["task_id"],
            attempt=value["attempt"],
            state=strings["state"],
            worker_id=strings["worker_id"],
            checkpoint_ref=strings["checkpoint_ref"],
            detail=strings["detail"],
            progress_completed=completed,
            progress_total=total,
            resources=resources,
            spent=spent,
            readiness_claim_id=readiness_claim_id,
            dispatch_readiness_receipt_id=dispatch_receipt_id,
            dispatch_readiness_receipt=dispatch_receipt,
        )
        if not isinstance(value["attempt_id"], str) or value["attempt_id"] != record.attempt_id:
            raise CampaignSerializationError("attempt_id does not match canonical identity")
        if not isinstance(value["record_id"], str) or value["record_id"] != record.record_id:
            raise CampaignSerializationError("attempt record_id does not match contents")
        return record


__all__ = [
    "AttemptRecord",
    "CandidateEvidence",
    "CandidateRecord",
    "CandidateScope",
    "ExecutionTelemetry",
]
