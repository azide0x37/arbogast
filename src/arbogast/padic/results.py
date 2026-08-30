"""Strict proof-bearing result variants for bounded p-adic computations."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeAlias, TypeVar, cast

from arbogast.cert import FrozenMap, VerificationCertificate, content_address, freeze_mapping
from arbogast.core import CanonicalJSON
from arbogast.galois.proof import Completeness, ProofContext, VerificationRequirement

from ._schema import (
    MAX_PROOF_OBLIGATIONS,
    PADIC_CERTIFIED_SCHEMA_V1,
    PADIC_PARTIAL_SCHEMA_V1,
    PADIC_PROOF_OBLIGATION_SCHEMA_V1,
    PADIC_UNKNOWN_SCHEMA_V1,
    PADIC_UNSUPPORTED_SCHEMA_V1,
    PAdicSchemaObject,
    PAdicSemanticObject,
    canonical_label,
    ensure_canonical_envelope,
    strict_canonical_equal,
    strict_canonical_mapping,
)
from .errors import PAdicValidationError, PAdicVerificationError

if TYPE_CHECKING:
    from .certificate import PAdicReceipt

T = TypeVar("T", bound=PAdicSchemaObject)


def _raw_object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise PAdicVerificationError(f"{name} must be a strict JSON object")
    return cast(dict[str, object], value)


def _raw_array(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise PAdicVerificationError(f"{name} must be a strict JSON array")
    return cast(list[object], value)


def _exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise PAdicVerificationError(
            f"{name} fields mismatch; missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _receipt(value: object) -> PAdicReceipt:
    from .certificate import PAdicReceipt

    if not isinstance(value, PAdicReceipt):
        raise TypeError("receipt must be a PAdicReceipt")
    return value


def _value(value: object) -> PAdicSchemaObject:
    if not isinstance(value, PAdicSchemaObject):
        raise TypeError("certified value must be a PAdicSchemaObject")
    if value.verify() is not True:
        raise PAdicVerificationError("certified value verification returned false")
    return value


def _context(receipt: PAdicReceipt, completeness: Completeness) -> ProofContext:
    context = receipt.proof_context
    if not isinstance(context, ProofContext) or not context.verify():
        raise PAdicVerificationError("receipt carries an invalid proof context")
    if context.completeness is not completeness:
        raise PAdicValidationError(
            f"{receipt.closure} receipts require {completeness.value} completeness"
        )
    return context


def _payload_equal(receipt: PAdicReceipt, expected: Mapping[str, object], name: str) -> None:
    if not strict_canonical_equal(receipt.payload.to_dict(), dict(expected)):
        raise PAdicVerificationError(f"{name} receipt payload does not bind the exact result")


def _sorted_unique_labels(values: Iterable[str], name: str) -> tuple[str, ...]:
    labels = tuple(canonical_label(value, name) for value in values)
    if len(set(labels)) != len(labels):
        raise PAdicValidationError(f"{name} values must be unique")
    return tuple(sorted(labels))


@dataclass(frozen=True, slots=True, init=False)
class ProofObligation(PAdicSchemaObject):
    """One exact missing witness blocking promotion of a partial result."""

    statement: str
    required_witness_kind: str
    blocked_result_kind: str
    input_ids: tuple[str, ...]
    obligation_id: str

    schema_version = PADIC_PROOF_OBLIGATION_SCHEMA_V1

    def __init__(
        self,
        statement: str,
        required_witness_kind: str,
        blocked_result_kind: str,
        *,
        input_ids: Iterable[str] = (),
    ) -> None:
        normalized_statement = canonical_label(statement, "obligation statement")
        witness_kind = canonical_label(required_witness_kind, "required witness kind")
        result_kind = canonical_label(blocked_result_kind, "blocked result kind")
        normalized_inputs = _sorted_unique_labels(input_ids, "obligation input ID")
        body = {
            "blocked_result_kind": result_kind,
            "input_ids": list(normalized_inputs),
            "required_witness_kind": witness_kind,
            "statement": normalized_statement,
        }
        object.__setattr__(self, "statement", normalized_statement)
        object.__setattr__(self, "required_witness_kind", witness_kind)
        object.__setattr__(self, "blocked_result_kind", result_kind)
        object.__setattr__(self, "input_ids", normalized_inputs)
        object.__setattr__(self, "obligation_id", content_address(body))

    def verify(self) -> bool:
        replay = ProofObligation(
            self.statement,
            self.required_witness_kind,
            self.blocked_result_kind,
            input_ids=self.input_ids,
        )
        if replay != self:
            raise PAdicVerificationError("proof-obligation normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "blocked_result_kind": self.blocked_result_kind,
            "input_ids": list(self.input_ids),
            "obligation_id": self.obligation_id,
            "required_witness_kind": self.required_witness_kind,
            "statement": self.statement,
            "type": "arbogast.padic.proof_obligation",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ProofObligation:
        raw = _raw_object(value, "proof obligation")
        _exact_keys(
            raw,
            {
                "schema",
                "blocked_result_kind",
                "input_ids",
                "obligation_id",
                "required_witness_kind",
                "statement",
                "type",
            },
            "proof obligation",
        )
        if raw["schema"] != cls.schema_version or raw["type"] != "arbogast.padic.proof_obligation":
            raise PAdicVerificationError("proof-obligation schema or type was altered")
        inputs = _raw_array(raw["input_ids"], "proof obligation input_ids")
        if any(type(item) is not str for item in inputs):
            raise PAdicVerificationError("proof obligation input_ids must contain strings")
        result = cls(
            cast(str, raw["statement"]),
            cast(str, raw["required_witness_kind"]),
            cast(str, raw["blocked_result_kind"]),
            input_ids=cast(list[str], inputs),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("proof obligation is not strict canonical transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class Certified(PAdicSemanticObject, Generic[T]):
    """A complete p-adic result bound to its portable proving receipt."""

    value: T
    receipt: PAdicReceipt

    schema_version = PADIC_CERTIFIED_SCHEMA_V1

    def __init__(self, value: T, receipt: PAdicReceipt) -> None:
        exact_value = cast(T, _value(value))
        exact_receipt = _receipt(receipt)
        if exact_receipt.closure != "certified":
            raise PAdicValidationError("Certified requires a certified receipt")
        _context(exact_receipt, Completeness.COMPLETE)
        _payload_equal(
            exact_receipt,
            {"result": exact_value.to_schema_document()},
            "certified",
        )
        object.__setattr__(self, "value", exact_value)
        object.__setattr__(self, "receipt", exact_receipt)

    @property
    def proof_context(self) -> ProofContext:
        return self.receipt.proof_context

    def verify(self) -> bool:
        if self.value.verify() is not True or not self.receipt.verify():
            raise PAdicVerificationError("certified result replay returned false")
        if Certified(self.value, self.receipt) != self:
            raise PAdicVerificationError("certified result normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "receipt": self.receipt.to_dict(),
                "type": "arbogast.padic.certified",
                "value": self.value.to_schema_document(),
            },
        )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
        *,
        value_decoder: Callable[[Mapping[str, object]], T],
    ) -> Certified[T]:
        from .certificate import PAdicReceipt

        raw = _raw_object(value, "certified result")
        _exact_keys(raw, {"schema", "receipt", "type", "value"}, "certified result")
        if raw["schema"] != cls.schema_version or raw["type"] != "arbogast.padic.certified":
            raise PAdicVerificationError("certified result schema or type was altered")
        result = cls(
            value_decoder(_raw_object(raw["value"], "certified value")),
            PAdicReceipt.from_dict(_raw_object(raw["receipt"], "certified receipt")),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("certified result is not strict canonical transport")
        return result


def _fragment_descriptor(fragment: Certified[PAdicSchemaObject]) -> dict[str, object]:
    claim = fragment.claim()
    return {
        "certificate_id": fragment.certificate.certificate_id,
        "claim_id": claim.claim_id,
        "result_id": fragment.value.content_id,
        "result_schema": fragment.value.schema_version,
    }


@dataclass(frozen=True, slots=True, init=False)
class Partial(PAdicSemanticObject):
    """Certified fragments plus explicit obligations; never a completed result."""

    operation: str
    reason: str
    fragments: tuple[Certified[PAdicSchemaObject], ...]
    obligations: tuple[ProofObligation, ...]
    receipt: PAdicReceipt

    schema_version = PADIC_PARTIAL_SCHEMA_V1

    def __init__(
        self,
        operation: str,
        reason: str,
        fragments: Sequence[Certified[PAdicSchemaObject]],
        obligations: Sequence[ProofObligation],
        receipt: PAdicReceipt,
    ) -> None:
        normalized_operation = canonical_label(operation, "partial operation")
        normalized_reason = canonical_label(reason, "partial reason")
        exact_fragments = tuple(fragments)
        if not exact_fragments or any(not isinstance(item, Certified) for item in exact_fragments):
            raise PAdicValidationError("Partial requires at least one Certified fragment")
        fragment_ids = tuple(item.certificate.certificate_id for item in exact_fragments)
        if len(set(fragment_ids)) != len(fragment_ids) or fragment_ids != tuple(
            sorted(fragment_ids)
        ):
            raise PAdicValidationError("partial fragments must be unique and receipt-ID sorted")
        exact_obligations = tuple(obligations)
        if not exact_obligations or any(
            not isinstance(item, ProofObligation) for item in exact_obligations
        ):
            raise PAdicValidationError("Partial requires at least one ProofObligation")
        if len(exact_obligations) > MAX_PROOF_OBLIGATIONS:
            raise PAdicValidationError("partial result exceeds the proof-obligation bound")
        obligation_ids = tuple(item.obligation_id for item in exact_obligations)
        if len(set(obligation_ids)) != len(obligation_ids) or obligation_ids != tuple(
            sorted(obligation_ids)
        ):
            raise PAdicValidationError("partial obligations must be unique and ID sorted")
        exact_receipt = _receipt(receipt)
        if exact_receipt.closure != "partial":
            raise PAdicValidationError("Partial requires a partial receipt")
        _context(exact_receipt, Completeness.CANDIDATE)
        payload = {
            "fragments": [_fragment_descriptor(item) for item in exact_fragments],
            "obligations": [item.to_schema_document() for item in exact_obligations],
            "operation": normalized_operation,
            "reason": normalized_reason,
        }
        _payload_equal(exact_receipt, payload, "partial")
        object.__setattr__(self, "operation", normalized_operation)
        object.__setattr__(self, "reason", normalized_reason)
        object.__setattr__(self, "fragments", exact_fragments)
        object.__setattr__(self, "obligations", exact_obligations)
        object.__setattr__(self, "receipt", exact_receipt)

    @property
    def proof_context(self) -> ProofContext:
        return self.receipt.proof_context

    def verify(self) -> bool:
        if any(item.verify() is not True for item in self.fragments):
            raise PAdicVerificationError("partial fragment replay returned false")
        if any(item.verify() is not True for item in self.obligations):
            raise PAdicVerificationError("partial obligation replay returned false")
        if not self.receipt.verify():
            raise PAdicVerificationError("partial receipt replay returned false")
        if (
            Partial(
                self.operation,
                self.reason,
                self.fragments,
                self.obligations,
                self.receipt,
            )
            != self
        ):
            raise PAdicVerificationError("partial result normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "fragments": [item.to_schema_document() for item in self.fragments],
                "obligations": [item.to_schema_document() for item in self.obligations],
                "operation": self.operation,
                "reason": self.reason,
                "receipt": self.receipt.to_dict(),
                "type": "arbogast.padic.partial",
            },
        )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
        *,
        fragment_decoder: Callable[
            [Mapping[str, object]],
            Certified[PAdicSchemaObject],
        ],
    ) -> Partial:
        from .certificate import PAdicReceipt

        raw = _raw_object(value, "partial result")
        _exact_keys(
            raw,
            {"schema", "fragments", "obligations", "operation", "reason", "receipt", "type"},
            "partial result",
        )
        if raw["schema"] != cls.schema_version or raw["type"] != "arbogast.padic.partial":
            raise PAdicVerificationError("partial result schema or type was altered")
        fragments = tuple(
            fragment_decoder(_raw_object(item, f"partial fragment[{index}]"))
            for index, item in enumerate(_raw_array(raw["fragments"], "partial fragments"))
        )
        obligations = tuple(
            ProofObligation.from_dict(_raw_object(item, f"partial obligation[{index}]"))
            for index, item in enumerate(_raw_array(raw["obligations"], "partial obligations"))
        )
        result = cls(
            cast(str, raw["operation"]),
            cast(str, raw["reason"]),
            fragments,
            obligations,
            PAdicReceipt.from_dict(_raw_object(raw["receipt"], "partial receipt")),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("partial result is not strict canonical transport")
        return result


def _requested(value: Mapping[str, object] | None) -> FrozenMap:
    normalized = strict_canonical_mapping(dict(value or {}), "requested p-adic boundary")
    dangerous = ("backend", "handle", "session", "transcript", "raw_output", "printed_padic")
    for key in normalized:
        folded = key.casefold().replace("-", "_")
        if any(token in folded for token in dangerous):
            raise PAdicValidationError("backend-local data cannot cross the p-adic proof boundary")
    return freeze_mapping(normalized)


@dataclass(frozen=True, slots=True, init=False)
class Unknown(PAdicSemanticObject):
    """A bounded p-adic computation that establishes no mathematical conclusion."""

    operation: str
    reason_code: str
    reason: str
    requested: FrozenMap
    receipt: PAdicReceipt

    schema_version = PADIC_UNKNOWN_SCHEMA_V1

    def __init__(
        self,
        operation: str,
        reason_code: str,
        reason: str,
        *,
        requested: Mapping[str, object] | None,
        receipt: PAdicReceipt,
    ) -> None:
        normalized_operation = canonical_label(operation, "unknown operation")
        normalized_code = canonical_label(reason_code, "unknown reason code")
        normalized_reason = canonical_label(reason, "unknown reason")
        normalized_requested = _requested(requested)
        exact_receipt = _receipt(receipt)
        if exact_receipt.closure != "unknown":
            raise PAdicValidationError("Unknown requires an unknown receipt")
        _context(exact_receipt, Completeness.CANDIDATE)
        payload = {
            "operation": normalized_operation,
            "reason": normalized_reason,
            "reason_code": normalized_code,
            "requested": normalized_requested.to_dict(),
        }
        _payload_equal(exact_receipt, payload, "unknown")
        object.__setattr__(self, "operation", normalized_operation)
        object.__setattr__(self, "reason_code", normalized_code)
        object.__setattr__(self, "reason", normalized_reason)
        object.__setattr__(self, "requested", normalized_requested)
        object.__setattr__(self, "receipt", exact_receipt)

    @property
    def proof_context(self) -> ProofContext:
        return self.receipt.proof_context

    def verify(self) -> bool:
        if not self.receipt.verify():
            raise PAdicVerificationError("unknown receipt replay returned false")
        if (
            Unknown(
                self.operation,
                self.reason_code,
                self.reason,
                requested=self.requested.to_dict(),
                receipt=self.receipt,
            )
            != self
        ):
            raise PAdicVerificationError("unknown result normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "operation": self.operation,
                "reason": self.reason,
                "reason_code": self.reason_code,
                "receipt": self.receipt.to_dict(),
                "requested": self.requested.to_dict(),
                "type": "arbogast.padic.unknown",
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Unknown:
        from .certificate import PAdicReceipt

        raw = _raw_object(value, "unknown result")
        _exact_keys(
            raw,
            {"schema", "operation", "reason", "reason_code", "receipt", "requested", "type"},
            "unknown result",
        )
        if raw["schema"] != cls.schema_version or raw["type"] != "arbogast.padic.unknown":
            raise PAdicVerificationError("unknown result schema or type was altered")
        result = cls(
            cast(str, raw["operation"]),
            cast(str, raw["reason_code"]),
            cast(str, raw["reason"]),
            requested=_raw_object(raw["requested"], "unknown requested boundary"),
            receipt=PAdicReceipt.from_dict(_raw_object(raw["receipt"], "unknown receipt")),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("unknown result is not strict canonical transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class Unsupported(PAdicSemanticObject):
    """A typed software-boundary refusal with no mathematical conclusion."""

    operation: str
    reason_code: str
    reason: str
    requested: FrozenMap
    supported: tuple[str, ...]
    receipt: PAdicReceipt

    schema_version = PADIC_UNSUPPORTED_SCHEMA_V1

    def __init__(
        self,
        operation: str,
        reason_code: str,
        reason: str,
        *,
        requested: Mapping[str, object] | None,
        supported: Iterable[str],
        receipt: PAdicReceipt,
    ) -> None:
        normalized_operation = canonical_label(operation, "unsupported operation")
        normalized_code = canonical_label(reason_code, "unsupported reason code")
        normalized_reason = canonical_label(reason, "unsupported reason")
        normalized_requested = _requested(requested)
        normalized_supported = _sorted_unique_labels(
            supported,
            "supported p-adic capability",
        )
        exact_receipt = _receipt(receipt)
        if exact_receipt.closure != "unsupported":
            raise PAdicValidationError("Unsupported requires an unsupported receipt")
        _context(exact_receipt, Completeness.CANDIDATE)
        payload = {
            "operation": normalized_operation,
            "reason": normalized_reason,
            "reason_code": normalized_code,
            "requested": normalized_requested.to_dict(),
            "supported": list(normalized_supported),
        }
        _payload_equal(exact_receipt, payload, "unsupported")
        object.__setattr__(self, "operation", normalized_operation)
        object.__setattr__(self, "reason_code", normalized_code)
        object.__setattr__(self, "reason", normalized_reason)
        object.__setattr__(self, "requested", normalized_requested)
        object.__setattr__(self, "supported", normalized_supported)
        object.__setattr__(self, "receipt", exact_receipt)

    @property
    def proof_context(self) -> ProofContext:
        return self.receipt.proof_context

    def verify(self) -> bool:
        if not self.receipt.verify():
            raise PAdicVerificationError("unsupported receipt replay returned false")
        if (
            Unsupported(
                self.operation,
                self.reason_code,
                self.reason,
                requested=self.requested.to_dict(),
                supported=self.supported,
                receipt=self.receipt,
            )
            != self
        ):
            raise PAdicVerificationError("unsupported result normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "operation": self.operation,
                "reason": self.reason,
                "reason_code": self.reason_code,
                "receipt": self.receipt.to_dict(),
                "requested": self.requested.to_dict(),
                "supported": list(self.supported),
                "type": "arbogast.padic.unsupported",
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Unsupported:
        from .certificate import PAdicReceipt

        raw = _raw_object(value, "unsupported result")
        _exact_keys(
            raw,
            {
                "schema",
                "operation",
                "reason",
                "reason_code",
                "receipt",
                "requested",
                "supported",
                "type",
            },
            "unsupported result",
        )
        if raw["schema"] != cls.schema_version or raw["type"] != "arbogast.padic.unsupported":
            raise PAdicVerificationError("unsupported result schema or type was altered")
        supported = _raw_array(raw["supported"], "supported capabilities")
        if any(type(item) is not str for item in supported):
            raise PAdicVerificationError("supported capabilities must contain strings")
        result = cls(
            cast(str, raw["operation"]),
            cast(str, raw["reason_code"]),
            cast(str, raw["reason"]),
            requested=_raw_object(raw["requested"], "unsupported requested boundary"),
            supported=cast(list[str], supported),
            receipt=PAdicReceipt.from_dict(_raw_object(raw["receipt"], "unsupported receipt")),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("unsupported result is not strict canonical transport")
        return result


PAdicResult: TypeAlias = Certified[T] | Partial | Unknown | Unsupported


def certified_result(
    value: T,
    kind: str,
    *,
    assumptions: Iterable[str] = (),
    verification_requirements: Iterable[VerificationRequirement] = (),
    evidence: Sequence[VerificationCertificate] = (),
) -> Certified[T]:
    """Build one complete result and its exact kind-specific receipt."""

    from .certificate import PAdicReceipt, complete_proof_context

    exact_value = cast(T, _value(value))
    context = complete_proof_context(
        kind,
        assumptions=assumptions,
        verification_requirements=verification_requirements,
    )
    receipt = PAdicReceipt.create(
        kind,
        "certified",
        {"result": exact_value.to_schema_document()},
        proof_context=context,
        evidence=evidence,
    )
    return Certified(exact_value, receipt)


def partial_result(
    operation: str,
    reason: str,
    fragments: Sequence[Certified[PAdicSchemaObject]],
    obligations: Sequence[ProofObligation],
    *,
    family: str,
    assumptions: Iterable[str] = (),
    verification_requirements: Iterable[VerificationRequirement] = (),
    evidence: Sequence[VerificationCertificate] = (),
) -> Partial | Unknown:
    """Build a partial result, or Unknown when no fragment is independently proved."""

    from .certificate import PAdicReceipt, candidate_proof_context, nonconclusion_kind

    sorted_obligations = tuple(sorted(obligations, key=lambda item: item.obligation_id))
    if not fragments:
        return unknown_result(
            operation,
            "no-certified-fragments",
            reason,
            requested={
                "blocked_obligations": [item.to_schema_document() for item in sorted_obligations]
            },
            family=family,
            assumptions=assumptions,
            verification_requirements=verification_requirements,
            evidence=evidence,
        )
    sorted_fragments = tuple(sorted(fragments, key=lambda item: item.certificate.certificate_id))
    kind = nonconclusion_kind(family, "partial")
    payload = {
        "fragments": [_fragment_descriptor(item) for item in sorted_fragments],
        "obligations": [item.to_schema_document() for item in sorted_obligations],
        "operation": canonical_label(operation, "partial operation"),
        "reason": canonical_label(reason, "partial reason"),
    }
    direct = tuple(item.certificate for item in sorted_fragments)
    all_evidence = tuple({item.certificate_id: item for item in (*direct, *evidence)}.values())
    receipt = PAdicReceipt.create(
        kind,
        "partial",
        payload,
        proof_context=candidate_proof_context(
            kind,
            assumptions=assumptions,
            verification_requirements=verification_requirements,
        ),
        evidence=all_evidence,
    )
    return Partial(
        cast(str, payload["operation"]),
        cast(str, payload["reason"]),
        sorted_fragments,
        sorted_obligations,
        receipt,
    )


def unknown_result(
    operation: str,
    reason_code: str,
    reason: str,
    *,
    requested: Mapping[str, object] | None = None,
    family: str,
    assumptions: Iterable[str] = (),
    verification_requirements: Iterable[VerificationRequirement] = (),
    evidence: Sequence[VerificationCertificate] = (),
) -> Unknown:
    """Build a canonical mathematical non-conclusion."""

    from .certificate import PAdicReceipt, candidate_proof_context, nonconclusion_kind

    normalized_requested = _requested(requested)
    kind = nonconclusion_kind(family, "unknown")
    payload = {
        "operation": canonical_label(operation, "unknown operation"),
        "reason": canonical_label(reason, "unknown reason"),
        "reason_code": canonical_label(reason_code, "unknown reason code"),
        "requested": normalized_requested.to_dict(),
    }
    receipt = PAdicReceipt.create(
        kind,
        "unknown",
        payload,
        proof_context=candidate_proof_context(
            kind,
            assumptions=assumptions,
            verification_requirements=verification_requirements,
        ),
        evidence=evidence,
    )
    return Unknown(
        cast(str, payload["operation"]),
        cast(str, payload["reason_code"]),
        cast(str, payload["reason"]),
        requested=normalized_requested.to_dict(),
        receipt=receipt,
    )


def unsupported_result(
    operation: str,
    reason_code: str,
    reason: str,
    *,
    requested: Mapping[str, object] | None = None,
    supported: Iterable[str] = (),
    family: str,
    assumptions: Iterable[str] = (),
    verification_requirements: Iterable[VerificationRequirement] = (),
    evidence: Sequence[VerificationCertificate] = (),
) -> Unsupported:
    """Build a canonical exact software-boundary refusal."""

    from .certificate import PAdicReceipt, candidate_proof_context, nonconclusion_kind

    normalized_requested = _requested(requested)
    normalized_supported = _sorted_unique_labels(
        supported,
        "supported p-adic capability",
    )
    kind = nonconclusion_kind(family, "unsupported")
    payload = {
        "operation": canonical_label(operation, "unsupported operation"),
        "reason": canonical_label(reason, "unsupported reason"),
        "reason_code": canonical_label(reason_code, "unsupported reason code"),
        "requested": normalized_requested.to_dict(),
        "supported": list(normalized_supported),
    }
    receipt = PAdicReceipt.create(
        kind,
        "unsupported",
        payload,
        proof_context=candidate_proof_context(
            kind,
            assumptions=assumptions,
            verification_requirements=verification_requirements,
        ),
        evidence=evidence,
    )
    return Unsupported(
        cast(str, payload["operation"]),
        cast(str, payload["reason_code"]),
        cast(str, payload["reason"]),
        requested=normalized_requested.to_dict(),
        supported=normalized_supported,
        receipt=receipt,
    )


def validate_result_envelope(result: PAdicSemanticObject) -> bool:
    """Check runtime verification and the full receipt-sized transport together."""

    if result.verify() is not True:
        raise PAdicVerificationError("p-adic result verification returned false")
    ensure_canonical_envelope(result.to_schema_document(), type(result).__qualname__)
    return True


__all__ = [
    "Certified",
    "PAdicResult",
    "Partial",
    "ProofObligation",
    "Unknown",
    "Unsupported",
    "certified_result",
    "partial_result",
    "unknown_result",
    "unsupported_result",
    "validate_result_envelope",
]
