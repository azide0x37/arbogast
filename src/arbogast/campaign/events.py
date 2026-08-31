"""Exact campaign outcomes, observations, and append-only ledger events."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from arbogast.cert import (
    Certificate,
    CertificateError,
    CertificateLayer,
    CertificateRef,
    CertificateVerificationError,
    UnknownVerifierError,
    VerificationCertificate,
    VerifierRegistry,
    certificate_from_dict,
    default_verifiers,
)
from arbogast.formats import (
    FrozenMapping,
    JSONValue,
    canonical_sha256,
    normalize_json,
    thaw_json,
)

from .errors import CampaignInvariantError, CampaignSerializationError


class Outcome(StrEnum):
    """User-facing outcome vocabulary, including non-mathematical stops."""

    FOUND = "FOUND"
    PROVED_IMPOSSIBLE = "PROVED_IMPOSSIBLE"
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PREEMPTED = "PREEMPTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class MathematicalOutcome(StrEnum):
    """Mathematical conclusions; ``UNKNOWN`` is deliberately non-closing."""

    FOUND = Outcome.FOUND
    PROVED_IMPOSSIBLE = Outcome.PROVED_IMPOSSIBLE
    SEARCH_EXHAUSTED = Outcome.SEARCH_EXHAUSTED
    UNKNOWN = Outcome.UNKNOWN


class OutcomeScope(StrEnum):
    """The mathematical domain an exact outcome is allowed to close."""

    TASK_LOCAL = "TASK_LOCAL"
    TARGET_GLOBAL = "TARGET_GLOBAL"


class OperationalState(StrEnum):
    """Execution state, kept separate from mathematical outcome."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BUDGET_EXHAUSTED = Outcome.BUDGET_EXHAUSTED
    PREEMPTED = Outcome.PREEMPTED
    FAILED = Outcome.FAILED
    UNKNOWN = Outcome.UNKNOWN


CLOSING_OUTCOMES = frozenset({Outcome.FOUND, Outcome.PROVED_IMPOSSIBLE, Outcome.SEARCH_EXHAUSTED})

_CONTENT_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TASK_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _string_ref(value: object | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        result = value
    else:
        uri = getattr(value, "uri", None)
        content_id = getattr(value, "content_id", None)
        digest = getattr(value, "digest", None)
        if isinstance(uri, str):
            result = uri
        elif isinstance(content_id, str):
            result = content_id
        elif isinstance(digest, str):
            algorithm = getattr(value, "algorithm", "sha256")
            result = f"{algorithm}:{digest}"
        else:
            raise CampaignInvariantError(f"{field_name} must be a stable content reference")
    if not result.strip():
        raise CampaignInvariantError(f"{field_name} cannot be blank")
    if not _CONTENT_REF_RE.fullmatch(result):
        raise CampaignInvariantError(f"{field_name} must be a canonical sha256 content reference")
    return result


def _certificate_ref(value: Certificate | CertificateRef | None) -> CertificateRef | None:
    if value is None:
        return None
    if isinstance(value, CertificateRef):
        return value
    if isinstance(value, Certificate):
        return CertificateRef.from_certificate(value)
    raise CampaignInvariantError("certificate must implement the Arbogast certificate protocol")


def closure_subject(
    target_id: str,
    outcome: Outcome | str,
    outcome_scope: OutcomeScope | str,
) -> str:
    """Return the exact subject an outcome certificate must bind."""

    return f"campaign:{target_id}:{OutcomeScope(outcome_scope).value}:{Outcome(outcome).value}"


def closure_certificate(
    target_id: str,
    outcome: Outcome | str,
    verifier: str,
    *,
    outcome_scope: OutcomeScope | str,
    task_hash: str | None = None,
    witness: Mapping[str, object] | None = None,
    checks: Iterable[str] = (),
    guarantees: Iterable[str] = (),
) -> VerificationCertificate:
    """Create a replayable certificate bound to one exact outcome and scope."""

    resolved_outcome = Outcome(outcome)
    resolved_scope = OutcomeScope(outcome_scope)
    if resolved_outcome not in CLOSING_OUTCOMES:
        raise CampaignInvariantError("closure certificates require a closing outcome")
    resolved_witness = dict(witness or {})
    if task_hash is not None:
        if not isinstance(task_hash, str) or not _TASK_HASH_RE.fullmatch(task_hash):
            raise CampaignInvariantError(
                "closure certificate task_hash must be 64 lowercase hexadecimal characters"
            )
        existing_task_hash = resolved_witness.get("task_hash")
        if existing_task_hash is not None and existing_task_hash != task_hash:
            raise CampaignInvariantError("closure certificate witness has a conflicting task_hash")
        resolved_witness["task_hash"] = task_hash
    return VerificationCertificate.create(
        closure_subject(target_id, resolved_outcome, resolved_scope),
        verifier,
        witness=resolved_witness,
        checks=tuple(checks),
        guarantees=tuple(guarantees),
    )


def _replay_certificate(
    payload: Mapping[str, object],
    *,
    target_id: str,
    outcome: Outcome,
    outcome_scope: OutcomeScope,
) -> Certificate:
    schema = payload.get("schema_version")
    common = {"certificate_id", "layer", "schema_version"}
    string_fields: tuple[str, ...]
    sequence_fields: tuple[str, ...]
    if schema == "arbogast.cert.verification/v1":
        expected_keys = common | {
            "checks",
            "claim_boundary_hash",
            "claim_dependencies",
            "claim_id",
            "dependencies",
            "guarantees",
            "statement_hash",
            "subject",
            "verifier",
            "witness",
        }
        string_fields = ("certificate_id", "layer", "schema_version", "subject", "verifier")
        sequence_fields = (
            "checks",
            "claim_dependencies",
            "dependencies",
            "guarantees",
        )
        claim_id = payload.get("claim_id")
        statement_hash = payload.get("statement_hash")
        claim_boundary_hash = payload.get("claim_boundary_hash")
        if claim_id is not None and not isinstance(claim_id, str):
            raise CampaignInvariantError("certificate claim_id must be a string or null")
        if statement_hash is not None and not isinstance(statement_hash, str):
            raise CampaignInvariantError("certificate statement_hash must be a string or null")
        if claim_boundary_hash is not None and not isinstance(claim_boundary_hash, str):
            raise CampaignInvariantError("certificate claim_boundary_hash must be a string or null")
        if not isinstance(payload.get("witness"), Mapping):
            raise CampaignInvariantError("verification witness must be an object")
    else:
        raise CampaignInvariantError(
            "campaign closure requires an independently replayable VerificationCertificate"
        )
    if set(payload) != expected_keys:
        raise CampaignInvariantError("closure certificate has missing or unknown fields")
    if any(not isinstance(payload.get(name), str) for name in string_fields):
        raise CampaignInvariantError("closure certificate string field has the wrong type")
    if any(not isinstance(payload.get(name), list) for name in sequence_fields):
        raise CampaignInvariantError("closure certificate sequence field has the wrong type")
    try:
        certificate = certificate_from_dict(payload)
    except (CertificateError, KeyError, TypeError, ValueError) as error:
        raise CampaignInvariantError("closure certificate failed strict replay") from error
    if certificate.layer is not CertificateLayer.VERIFICATION:
        raise CampaignInvariantError("closure requires independently verified evidence")
    expected_subject = closure_subject(target_id, outcome, outcome_scope)
    actual_subject = getattr(certificate, "subject", None)
    if actual_subject is None:
        actual_subject = getattr(certificate, "claim_id", None)
    if actual_subject != expected_subject:
        raise CampaignInvariantError(
            "closure certificate is not bound to this target, outcome, and scope"
        )
    return certificate


def _default_operational_state(outcome: Outcome) -> OperationalState:
    mapping = {
        Outcome.BUDGET_EXHAUSTED: OperationalState.BUDGET_EXHAUSTED,
        Outcome.PREEMPTED: OperationalState.PREEMPTED,
        Outcome.FAILED: OperationalState.FAILED,
        Outcome.UNKNOWN: OperationalState.UNKNOWN,
    }
    return mapping.get(outcome, OperationalState.COMPLETED)


@dataclass(frozen=True, slots=True, init=False)
class Observation:
    """One task observation with explicit proof and operational boundaries.

    A mathematical closure cannot even be represented without a replayable
    verification certificate.  Its registered independent checker must also
    pass before the ledger projects the target as closed.
    """

    target_id: str
    task_id: str
    outcome: Outcome
    outcome_scope: OutcomeScope
    operational_state: OperationalState
    certificate_ref: CertificateRef | None
    certificate_payload: FrozenMapping | None
    result_ref: str | None
    checkpoint_ref: str | None
    input_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    parameters: FrozenMapping
    details: FrozenMapping
    _verifier_registry: VerifierRegistry = field(
        default=default_verifiers,
        init=False,
        compare=False,
        repr=False,
    )

    def __init__(
        self,
        target_id: str,
        task_id: str,
        outcome: Outcome | str = Outcome.UNKNOWN,
        *,
        outcome_scope: OutcomeScope | str = OutcomeScope.TASK_LOCAL,
        operational_state: OperationalState | str | None = None,
        certificate: Certificate | CertificateRef | None = None,
        certificate_ref: CertificateRef | None = None,
        certificate_payload: Mapping[str, object] | None = None,
        result_ref: object | None = None,
        checkpoint_ref: object | None = None,
        input_refs: Iterable[str] = (),
        source_refs: Iterable[str] = (),
        parameters: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
        verifier_registry: VerifierRegistry = default_verifiers,
    ) -> None:
        if not isinstance(verifier_registry, VerifierRegistry):
            raise TypeError("verifier_registry must be a VerifierRegistry")
        if not target_id.strip() or not task_id.strip():
            raise CampaignInvariantError("observation target_id and task_id cannot be blank")
        resolved_outcome = Outcome(outcome)
        resolved_scope = OutcomeScope(outcome_scope)
        if (
            resolved_scope is OutcomeScope.TARGET_GLOBAL
            and resolved_outcome not in CLOSING_OUTCOMES
        ):
            raise CampaignInvariantError(
                "TARGET_GLOBAL scope requires an exact mathematical outcome"
            )
        resolved_state = (
            _default_operational_state(resolved_outcome)
            if operational_state is None
            else OperationalState(operational_state)
        )
        operational_outcomes = {
            Outcome.BUDGET_EXHAUSTED: OperationalState.BUDGET_EXHAUSTED,
            Outcome.PREEMPTED: OperationalState.PREEMPTED,
            Outcome.FAILED: OperationalState.FAILED,
        }
        required_state = operational_outcomes.get(resolved_outcome)
        if required_state is not None and resolved_state is not required_state:
            raise CampaignInvariantError(
                f"{resolved_outcome.value} requires operational state {required_state.value}"
            )
        if certificate is not None and certificate_payload is not None:
            raise CampaignInvariantError("provide certificate or certificate_payload, not both")
        supplied_ref = _certificate_ref(certificate_ref)
        replay_payload: Mapping[str, object] | None = certificate_payload
        if certificate is not None:
            if isinstance(certificate, CertificateRef):
                supplied_ref = certificate
            else:
                raw_payload = normalize_json(certificate.to_dict())
                if not isinstance(raw_payload, dict):
                    raise CampaignInvariantError("certificate payload must be an object")
                replay_payload = raw_payload
        replayed: Certificate | None = None
        if replay_payload is not None:
            replayed = _replay_certificate(
                replay_payload,
                target_id=target_id,
                outcome=resolved_outcome,
                outcome_scope=resolved_scope,
            )
        resolved_certificate = (
            CertificateRef.from_certificate(replayed) if replayed is not None else supplied_ref
        )
        if (
            supplied_ref is not None
            and replayed is not None
            and supplied_ref != resolved_certificate
        ):
            raise CampaignInvariantError(
                "certificate reference does not match replayed certificate"
            )
        if resolved_outcome in CLOSING_OUTCOMES and replayed is None:
            raise CampaignInvariantError(
                f"{resolved_outcome.value} requires an embedded, replayable "
                "verification certificate"
            )
        normalized_inputs = tuple(dict.fromkeys(input_refs))
        normalized_sources = tuple(dict.fromkeys(source_refs))
        if any(not item.strip() for item in (*normalized_inputs, *normalized_sources)):
            raise CampaignInvariantError("observation provenance references cannot be blank")
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "outcome", resolved_outcome)
        object.__setattr__(self, "outcome_scope", resolved_scope)
        object.__setattr__(self, "operational_state", resolved_state)
        object.__setattr__(self, "certificate_ref", resolved_certificate)
        object.__setattr__(
            self,
            "certificate_payload",
            None if replay_payload is None else FrozenMapping(replay_payload),
        )
        object.__setattr__(
            self,
            "result_ref",
            _string_ref(result_ref, field_name="result_ref"),
        )
        object.__setattr__(
            self,
            "checkpoint_ref",
            _string_ref(checkpoint_ref, field_name="checkpoint_ref"),
        )
        object.__setattr__(self, "input_refs", normalized_inputs)
        object.__setattr__(self, "source_refs", normalized_sources)
        object.__setattr__(self, "parameters", FrozenMapping(parameters))
        object.__setattr__(self, "details", FrozenMapping(details))
        object.__setattr__(self, "_verifier_registry", verifier_registry)

    @property
    def mathematical_outcome(self) -> MathematicalOutcome:
        if self.outcome in CLOSING_OUTCOMES and self.verified:
            return MathematicalOutcome(self.outcome.value)
        return MathematicalOutcome.UNKNOWN

    def verify(
        self,
        verifier_registry: VerifierRegistry = default_verifiers,
    ) -> bool:
        """Replay the embedded certificate with one explicit runtime registry."""

        if self.certificate_payload is None:
            return False
        try:
            raw_payload = thaw_json(self.certificate_payload)
            if not isinstance(raw_payload, dict):
                return False
            certificate = _replay_certificate(
                raw_payload,
                target_id=self.target_id,
                outcome=self.outcome,
                outcome_scope=self.outcome_scope,
            )
            report = verifier_registry.verify(certificate)
        except (
            CampaignInvariantError,
            CertificateVerificationError,
            UnknownVerifierError,
        ):
            return False
        return report.valid is True

    @property
    def verified(self) -> bool:
        """Preserve legacy default replay while honoring an injected ledger V."""

        return self.verify(self._verifier_registry)

    def with_verifier_registry(self, verifier_registry: VerifierRegistry) -> Observation:
        """Return the same canonical observation with runtime-only verifier context."""

        if not isinstance(verifier_registry, VerifierRegistry):
            raise TypeError("verifier_registry must be a VerifierRegistry")
        if verifier_registry is self._verifier_registry:
            return self
        return Observation(
            target_id=self.target_id,
            task_id=self.task_id,
            outcome=self.outcome,
            outcome_scope=self.outcome_scope,
            operational_state=self.operational_state,
            certificate_ref=self.certificate_ref,
            certificate_payload=(
                None if self.certificate_payload is None else self.certificate_payload.to_dict()
            ),
            result_ref=self.result_ref,
            checkpoint_ref=self.checkpoint_ref,
            input_refs=self.input_refs,
            source_refs=self.source_refs,
            parameters=self.parameters.to_dict(),
            details=self.details.to_dict(),
            verifier_registry=verifier_registry,
        )

    def closes_target_with(
        self,
        verifier_registry: VerifierRegistry = default_verifiers,
    ) -> bool:
        """Project mathematical closure through one explicit verifier registry."""

        return (
            self.outcome_scope is OutcomeScope.TARGET_GLOBAL
            and self.outcome in CLOSING_OUTCOMES
            and self.verify(verifier_registry)
        )

    @property
    def closes_target(self) -> bool:
        return self.closes_target_with(self._verifier_registry)

    @property
    def observation_id(self) -> str:
        return f"sha256:{canonical_sha256(self.to_dict(include_id=False))}"

    @property
    def content_id(self) -> str:
        return self.observation_id

    def to_dict(self, *, include_id: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "certificate_ref": (
                None
                if self.certificate_ref is None
                else normalize_json(self.certificate_ref.to_dict())
            ),
            "certificate_payload": (
                None if self.certificate_payload is None else self.certificate_payload.to_dict()
            ),
            "checkpoint_ref": self.checkpoint_ref,
            "details": self.details.to_dict(),
            "input_refs": list(self.input_refs),
            "operational_state": self.operational_state.value,
            "outcome": self.outcome.value,
            "outcome_scope": self.outcome_scope.value,
            "parameters": self.parameters.to_dict(),
            "result_ref": self.result_ref,
            "source_refs": list(self.source_refs),
            "target_id": self.target_id,
            "task_id": self.task_id,
        }
        if include_id:
            payload["observation_id"] = self.observation_id
        return payload

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        verifier_registry: VerifierRegistry = default_verifiers,
    ) -> Observation:
        required = {
            "certificate_payload",
            "certificate_ref",
            "checkpoint_ref",
            "details",
            "input_refs",
            "observation_id",
            "operational_state",
            "outcome",
            "outcome_scope",
            "parameters",
            "result_ref",
            "source_refs",
            "target_id",
            "task_id",
        }
        if set(value) != required:
            raise CampaignSerializationError("observation has missing or unknown fields")
        certificate_value = value["certificate_ref"]
        certificate_ref: CertificateRef | None = None
        if certificate_value is not None:
            if not isinstance(certificate_value, Mapping):
                raise CampaignSerializationError("certificate_ref must be an object")
            certificate_keys = {"certificate_id", "layer"}
            if certificate_value.get("schema_version") is not None:
                certificate_keys.add("schema_version")
            if set(certificate_value) != certificate_keys:
                raise CampaignSerializationError("certificate_ref has unknown fields")
            raw_certificate_id = certificate_value["certificate_id"]
            raw_layer = certificate_value["layer"]
            raw_schema = certificate_value.get("schema_version")
            if not isinstance(raw_certificate_id, str) or not isinstance(raw_layer, str):
                raise CampaignSerializationError("certificate reference fields must be strings")
            if raw_schema is not None and not isinstance(raw_schema, str):
                raise CampaignSerializationError("certificate schema must be a string or null")
            certificate_ref = CertificateRef(
                certificate_id=raw_certificate_id,
                layer=CertificateLayer(raw_layer),
                schema_version=raw_schema,
            )
        certificate_payload_value = value["certificate_payload"]
        if certificate_payload_value is not None and not isinstance(
            certificate_payload_value, Mapping
        ):
            raise CampaignSerializationError("certificate_payload must be an object or null")
        target_id = value["target_id"]
        task_id = value["task_id"]
        raw_outcome = value["outcome"]
        raw_scope = value["outcome_scope"]
        raw_state = value["operational_state"]
        if not all(
            isinstance(item, str)
            for item in (target_id, task_id, raw_outcome, raw_scope, raw_state)
        ):
            raise CampaignSerializationError("observation identifiers and states must be strings")
        raw_inputs = value["input_refs"]
        raw_sources = value["source_refs"]
        if not isinstance(raw_inputs, list) or any(
            not isinstance(item, str) for item in raw_inputs
        ):
            raise CampaignSerializationError("input_refs must be an array of strings")
        if not isinstance(raw_sources, list) or any(
            not isinstance(item, str) for item in raw_sources
        ):
            raise CampaignSerializationError("source_refs must be an array of strings")
        raw_parameters = value["parameters"]
        raw_details = value["details"]
        if not isinstance(raw_parameters, Mapping) or not isinstance(raw_details, Mapping):
            raise CampaignSerializationError("observation parameters/details must be objects")
        result_ref = value["result_ref"]
        checkpoint_ref = value["checkpoint_ref"]
        if result_ref is not None and not isinstance(result_ref, str):
            raise CampaignSerializationError("result_ref must be a string or null")
        if checkpoint_ref is not None and not isinstance(checkpoint_ref, str):
            raise CampaignSerializationError("checkpoint_ref must be a string or null")
        observation = cls(
            target_id=target_id,
            task_id=task_id,
            outcome=Outcome(raw_outcome),
            outcome_scope=OutcomeScope(raw_scope),
            operational_state=OperationalState(raw_state),
            certificate_ref=certificate_ref,
            certificate_payload=certificate_payload_value,
            result_ref=result_ref,
            checkpoint_ref=checkpoint_ref,
            input_refs=tuple(raw_inputs),
            source_refs=tuple(raw_sources),
            parameters=raw_parameters,
            details=raw_details,
            verifier_registry=verifier_registry,
        )
        expected = value["observation_id"]
        if not isinstance(expected, str):
            raise CampaignSerializationError("observation_id must be a string")
        if expected != observation.observation_id:
            raise CampaignSerializationError("observation_id does not match canonical contents")
        return observation


class EventKind(StrEnum):
    """Closed event vocabulary for safe replay."""

    TARGET_ADDED = "TARGET_ADDED"
    TASK_PLANNED = "TASK_PLANNED"
    TASK_STARTED = "TASK_STARTED"
    OBSERVATION_RECORDED = "OBSERVATION_RECORDED"
    ATTEMPT_RECORDED = "ATTEMPT_RECORDED"
    CANDIDATE_RECORDED = "CANDIDATE_RECORDED"
    CLAIM_BOUND = "CLAIM_BOUND"
    PLAN_RECORDED = "PLAN_RECORDED"


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """A hash-chained authoritative campaign event."""

    sequence: int
    kind: EventKind
    payload: FrozenMapping = field(default_factory=FrozenMapping)
    previous_event_id: str | None = None
    schema: str = field(default="arbogast.campaign.event.v1", init=False, compare=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise CampaignInvariantError("event sequence must be a non-negative integer")
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", EventKind(self.kind))
        object.__setattr__(self, "payload", FrozenMapping(self.payload))
        if self.sequence == 0 and self.previous_event_id is not None:
            raise CampaignInvariantError("first ledger event cannot have a predecessor")
        if self.sequence > 0 and self.previous_event_id is None:
            raise CampaignInvariantError("non-first ledger event requires a predecessor")

    @property
    def event_id(self) -> str:
        return f"sha256:{canonical_sha256(self.to_dict(include_id=False))}"

    @property
    def content_id(self) -> str:
        return self.event_id

    def to_dict(self, *, include_id: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "kind": self.kind.value,
            "payload": self.payload.to_dict(),
            "previous_event_id": self.previous_event_id,
            "schema": self.schema,
            "sequence": self.sequence,
        }
        if include_id:
            payload["event_id"] = self.event_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LedgerEvent:
        required = {
            "event_id",
            "kind",
            "payload",
            "previous_event_id",
            "schema",
            "sequence",
        }
        if set(value) != required:
            raise CampaignSerializationError("campaign event has missing or unknown fields")
        if value.get("schema") != "arbogast.campaign.event.v1":
            raise CampaignSerializationError("unsupported campaign event schema")
        sequence = value["sequence"]
        kind = value["kind"]
        payload = value["payload"]
        previous = value["previous_event_id"]
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise CampaignSerializationError("event sequence must be an integer")
        if not isinstance(kind, str):
            raise CampaignSerializationError("event kind must be a string")
        if not isinstance(payload, Mapping):
            raise CampaignSerializationError("event payload must be an object")
        if previous is not None and not isinstance(previous, str):
            raise CampaignSerializationError("previous_event_id must be a string or null")
        event = cls(
            sequence=sequence,
            kind=EventKind(kind),
            payload=FrozenMapping(payload),
            previous_event_id=previous,
        )
        expected = value["event_id"]
        if not isinstance(expected, str):
            raise CampaignSerializationError("event_id must be a string")
        if expected != event.event_id:
            raise CampaignSerializationError("event_id does not match canonical contents")
        return event


CampaignOutcome = Outcome

__all__ = [
    "CLOSING_OUTCOMES",
    "CampaignOutcome",
    "EventKind",
    "LedgerEvent",
    "MathematicalOutcome",
    "Observation",
    "OperationalState",
    "Outcome",
    "OutcomeScope",
    "closure_certificate",
    "closure_subject",
]
