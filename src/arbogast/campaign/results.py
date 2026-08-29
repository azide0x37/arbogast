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
    progress_completed: int
    progress_total: int | None
    resources: FrozenMapping

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
        progress_completed: int = 0,
        progress_total: int | None = None,
        resources: Mapping[str, Any] | None = None,
    ) -> None:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise CampaignInvariantError("attempt number must be a positive integer")
        if worker_id is not None and (not isinstance(worker_id, str) or not worker_id.strip()):
            raise CampaignInvariantError("attempt worker_id must be a non-blank string or null")
        if detail is not None and (not isinstance(detail, str) or not detail.strip()):
            raise CampaignInvariantError("attempt detail must be a non-blank string or null")
        if (
            isinstance(progress_completed, bool)
            or not isinstance(progress_completed, int)
            or progress_completed < 0
        ):
            raise CampaignInvariantError("attempt progress_completed must be non-negative")
        if progress_total is not None and (
            isinstance(progress_total, bool)
            or not isinstance(progress_total, int)
            or progress_total < 1
            or progress_completed > progress_total
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
        object.__setattr__(self, "resources", FrozenMapping(resources))

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
            "state": self.state.value,
            "target_id": self.target_id,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
        }
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
            "state",
            "target_id",
            "task_id",
            "worker_id",
        }
        if set(value) != required:
            raise CampaignSerializationError("attempt has missing or unknown fields")
        if value["schema"] != cls.schema:
            raise CampaignSerializationError("unsupported attempt schema")
        for field_name in ("attempt", "progress_completed"):
            raw = value[field_name]
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise CampaignSerializationError(f"attempt {field_name} must be an integer")
        total = value["progress_total"]
        if total is not None and (isinstance(total, bool) or not isinstance(total, int)):
            raise CampaignSerializationError("attempt progress_total must be an integer or null")
        resources = value["resources"]
        if not isinstance(resources, Mapping):
            raise CampaignSerializationError("attempt resources must be an object")
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
            progress_completed=value["progress_completed"],
            progress_total=total,
            resources=resources,
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
]
