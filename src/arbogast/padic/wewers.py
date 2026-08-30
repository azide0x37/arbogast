"""Bounded rank-one tame deformation data with an explicit origin boundary.

The synthetic objects in this module certify only the displayed finite-field
identities.  They do not claim to arise from stable reduction.  Promotion from
a stable model is a separate operation and remains unavailable for the 0.5
good-reduction profile, which does not contain an inertia character or a
differential-extraction theorem.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import gcd
from typing import TYPE_CHECKING, TypeAlias, cast

from arbogast.cert import VerificationCertificate
from arbogast.core import CanonicalJSON
from arbogast.linalg import PrimeField

from ._schema import (
    MAX_EXACT_REPLAY_WORK,
    MAX_LOCAL_DEGREE,
    MAX_PRIME_BITS,
    PAdicSchemaObject,
    canonical_label,
    strict_canonical_mapping,
    strict_int,
)
from .certificate import (
    PAdicPayloadReplay,
    padic_payload_verifier,
)
from .errors import (
    PAdicResourceError,
    PAdicValidationError,
    PAdicVerificationError,
)
from .results import (
    Certified,
    Unknown,
    Unsupported,
    unknown_result,
    unsupported_result,
)

if TYPE_CHECKING:
    from .reduction import StableReduction

FPPolynomial: TypeAlias = tuple[int, ...]
SignatureEntry: TypeAlias = tuple[str, int, int]

_INTERNAL_SCOPE = "internal-identities-only"
_COMPONENT_RELATION_SCOPE = "componentwise-formal-identities-no-divisor-or-point-binding"
_SPECIAL_PROFILE = "wewers-special-signature-definition-v1"
_GEOMETRIC_PROFILE = "stable-rank-one-tame-extraction-v1"
_MAX_DATUM_PRIME = 65_537


def _prime(value: int) -> int:
    result = strict_int(value, "deformation-datum prime", minimum=2)
    if result.bit_length() > MAX_PRIME_BITS:
        raise PAdicResourceError("deformation-datum prime exceeds the portable bit bound")
    if result > min(_MAX_DATUM_PRIME, MAX_EXACT_REPLAY_WORK):
        raise PAdicResourceError(
            "deformation-datum prime exceeds the bounded exact primality-replay limit"
        )
    PrimeField(result)
    return result


def _fp_polynomial(values: Sequence[int], prime: int, name: str) -> FPPolynomial:
    if isinstance(values, str | bytes):
        raise TypeError(f"{name} must be a sequence of exact integers")
    if len(values) > MAX_LOCAL_DEGREE + 1:
        raise PAdicResourceError(f"{name} exceeds the bounded degree")
    result = tuple(strict_int(value, f"{name} coefficient", minimum=0) for value in values)
    if not result:
        raise PAdicValidationError(f"{name} must be nonempty")
    if any(value >= prime for value in result):
        raise PAdicValidationError(f"{name} coefficients must be canonical modulo {prime}")
    if len(result) > 1 and result[-1] == 0:
        raise PAdicValidationError(f"{name} has a noncanonical trailing zero")
    return result


def _trim(values: Sequence[int], prime: int) -> FPPolynomial:
    result = tuple(value % prime for value in values) or (0,)
    while len(result) > 1 and result[-1] == 0:
        result = result[:-1]
    return result


def _derivative(values: FPPolynomial, prime: int) -> FPPolynomial:
    return _trim(tuple(index * value for index, value in enumerate(values))[1:], prime)


def _remainder(left: FPPolynomial, right: FPPolynomial, prime: int) -> FPPolynomial:
    if right == (0,):
        raise ZeroDivisionError("polynomial division by zero")
    remainder = list(left)
    inverse = pow(right[-1], -1, prime)
    while len(remainder) >= len(right) and any(remainder):
        scale = remainder[-1] * inverse % prime
        offset = len(remainder) - len(right)
        for index, value in enumerate(right):
            remainder[offset + index] = (remainder[offset + index] - scale * value) % prime
        while len(remainder) > 1 and remainder[-1] == 0:
            remainder.pop()
    return _trim(tuple(remainder), prime)


def _gcd(left: FPPolynomial, right: FPPolynomial, prime: int) -> FPPolynomial:
    a, b = left, right
    while b != (0,):
        a, b = b, _remainder(a, b, prime)
    inverse = pow(a[-1], -1, prime)
    return _trim(tuple(inverse * value for value in a), prime)


def _fraction_data(value: Fraction) -> dict[str, CanonicalJSON]:
    return {"denominator": value.denominator, "numerator": value.numerator}


def _strict_object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise PAdicVerificationError(f"{name} must be a strict JSON object")
    return cast(dict[str, object], value)


def _strict_array(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise PAdicVerificationError(f"{name} must be a strict JSON array")
    return cast(list[object], value)


def _exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise PAdicVerificationError(f"{name} fields were altered")


@dataclass(frozen=True, slots=True, init=False)
class RationalDifferential(PAdicSchemaObject):
    """A literal logarithmic form ``dlog(u)`` over ``F_p(x)``.

    The square-free monic polynomial ``u`` is the proof witness.  The stored
    numerator is recomputed as ``u'``; Cartier-fixedness follows only within
    this exact logarithmic slice.
    """

    prime: int
    logarithmic_unit: FPPolynomial
    numerator: FPPolynomial
    denominator: FPPolynomial
    differential_kind: str
    cartier_relation: str

    schema_version = "arbogast.padic.rational-differential/v1"

    def __init__(self, prime: int, logarithmic_unit: Sequence[int]) -> None:
        normalized_prime = _prime(prime)
        unit = _fp_polynomial(logarithmic_unit, normalized_prime, "logarithmic unit")
        if len(unit) < 2 or unit[-1] != 1:
            raise PAdicValidationError("logarithmic unit must be nonconstant and monic")
        numerator = _derivative(unit, normalized_prime)
        if numerator == (0,) or _gcd(unit, numerator, normalized_prime) != (1,):
            raise PAdicValidationError("logarithmic unit must be square-free")
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "logarithmic_unit", unit)
        object.__setattr__(self, "numerator", numerator)
        object.__setattr__(self, "denominator", unit)
        object.__setattr__(self, "differential_kind", "logarithmic")
        object.__setattr__(self, "cartier_relation", "C(du/u)=du/u")

    @property
    def degree(self) -> int:
        return len(self.logarithmic_unit) - 1

    def verify(self) -> bool:
        if type(self.prime) is not int or _prime(self.prime) != self.prime:
            raise PAdicVerificationError("rational differential prime was altered")
        try:
            unit = _fp_polynomial(self.logarithmic_unit, self.prime, "logarithmic unit")
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if (
            len(unit) < 2
            or unit[-1] != 1
            or self.numerator != _derivative(unit, self.prime)
            or self.denominator != unit
            or _gcd(unit, self.numerator, self.prime) != (1,)
        ):
            raise PAdicVerificationError("dlog numerator, denominator, or square-freeness changed")
        if self.differential_kind != "logarithmic" or self.cartier_relation != "C(du/u)=du/u":
            raise PAdicVerificationError("logarithmic or Cartier convention was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cartier_relation": self.cartier_relation,
            "denominator": list(self.denominator),
            "differential_kind": self.differential_kind,
            "logarithmic_unit": list(self.logarithmic_unit),
            "numerator": list(self.numerator),
            "prime": self.prime,
            "type": "arbogast.padic.rational_differential",
        }


@dataclass(frozen=True, slots=True, init=False)
class DeformationSignature(PAdicSchemaObject):
    """Exact critical-point triples ``(label, m, h)`` and ``sigma=h/m``."""

    entries: tuple[SignatureEntry, ...]
    invariants: tuple[Fraction, ...]

    schema_version = "arbogast.padic.deformation-signature/v1"

    def __init__(self, entries: Sequence[SignatureEntry]) -> None:
        if isinstance(entries, str | bytes):
            raise TypeError("deformation signature entries must be a sequence")
        if len(entries) > MAX_LOCAL_DEGREE:
            raise PAdicResourceError("deformation signature exceeds the entry-count bound")
        normalized: list[SignatureEntry] = []
        for raw_label, raw_m, raw_h in entries:
            label = canonical_label(raw_label, "critical-point label")
            m = strict_int(raw_m, "critical stabilizer order", minimum=1)
            h = strict_int(raw_h, "critical differential conductor", minimum=0)
            if m > MAX_LOCAL_DEGREE or h > 2 * MAX_LOCAL_DEGREE:
                raise PAdicResourceError("deformation signature exceeds the bounded local degree")
            if (m, h) == (1, 1):
                raise PAdicValidationError("ordinary (m,h)=(1,1) points are not critical entries")
            normalized.append((label, m, h))
        normalized.sort(key=lambda item: item[0])
        if not normalized or len({item[0] for item in normalized}) != len(normalized):
            raise PAdicValidationError("critical-point labels must be nonempty and unique")
        object.__setattr__(self, "entries", tuple(normalized))
        object.__setattr__(self, "invariants", tuple(Fraction(h, m) for _, m, h in normalized))

    @property
    def wild_labels(self) -> tuple[str, ...]:
        return tuple(label for label, _, h in self.entries if h == 0)

    @property
    def primitive_labels(self) -> tuple[str, ...]:
        return tuple(
            label
            for (label, _, _), invariant in zip(self.entries, self.invariants, strict=True)
            if 0 < invariant < 1
        )

    def verify(self) -> bool:
        replay = DeformationSignature(self.entries)
        if replay != self:
            raise PAdicVerificationError("deformation signature normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "entries": [
                {"h": h, "label": label, "m": m, "sigma": _fraction_data(Fraction(h, m))}
                for label, m, h in self.entries
            ],
            "type": "arbogast.padic.deformation_signature",
        }


@dataclass(frozen=True, slots=True, init=False)
class SpecialityWitness(PAdicSchemaObject):
    """Replay Wewers' numerical definition of a normalized special signature."""

    signature: DeformationSignature
    primitive_labels: tuple[str, ...]
    wild_labels: tuple[str, ...]
    normalized_labels: tuple[str, ...]
    profile: str

    schema_version = "arbogast.padic.speciality-witness/v1"

    def __init__(
        self,
        signature: DeformationSignature,
        *,
        normalized_labels: Sequence[str] = ("infinity", "one", "zero"),
    ) -> None:
        if not isinstance(signature, DeformationSignature):
            raise TypeError("speciality witness needs a DeformationSignature")
        signature.verify()
        if len(normalized_labels) != 3:
            raise PAdicValidationError(
                "normalized special labels must be exactly zero, one, and infinity"
            )
        labels = tuple(
            sorted(canonical_label(item, "normalized critical label") for item in normalized_labels)
        )
        if labels != ("infinity", "one", "zero"):
            raise PAdicValidationError("normalized special labels must be zero, one, and infinity")
        for (_, _, h), invariant in zip(signature.entries, signature.invariants, strict=True):
            if h != 0 and (not 0 < invariant < 2 or invariant == 1):
                raise PAdicValidationError(
                    "non-wild special invariants must lie in (0,2) and differ from 1"
                )
        base_labels = tuple(sorted((*signature.primitive_labels, *signature.wild_labels)))
        if len(base_labels) != 3 or base_labels != labels:
            raise PAdicValidationError(
                "a normalized special signature needs exactly zero, one, infinity "
                "in Bprim union Bwild"
            )
        object.__setattr__(self, "signature", signature)
        object.__setattr__(self, "primitive_labels", signature.primitive_labels)
        object.__setattr__(self, "wild_labels", signature.wild_labels)
        object.__setattr__(self, "normalized_labels", labels)
        object.__setattr__(self, "profile", _SPECIAL_PROFILE)

    def verify(self) -> bool:
        if not isinstance(self.signature, DeformationSignature):
            raise PAdicVerificationError("speciality signature has the wrong type")
        try:
            replay = SpecialityWitness(self.signature, normalized_labels=self.normalized_labels)
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("speciality witness was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "normalized_labels": list(self.normalized_labels),
            "primitive_labels": list(self.primitive_labels),
            "profile": self.profile,
            "signature": self.signature.to_schema_document(),
            "type": "arbogast.padic.speciality_witness",
            "wild_labels": list(self.wild_labels),
        }


def _least_element_of_order(prime: int, order: int) -> int:
    if order == 1:
        return 1
    if prime > MAX_EXACT_REPLAY_WORK:
        raise PAdicResourceError("character search exceeds the exact replay-work bound")
    for candidate in range(2, prime):
        if pow(candidate, order, prime) != 1:
            continue
        if all(pow(candidate, exponent, prime) != 1 for exponent in range(1, order)):
            return candidate
    raise PAdicValidationError("no element realizes the declared tame character order")


@dataclass(frozen=True, slots=True, init=False)
class DeformationDatum(PAdicSchemaObject):
    """A synthetic rank-one tame tuple with componentwise formal identities.

    Version 0.5 does not identify signature labels with points or divisor data
    of the displayed differential.  The explicit false relation flag prevents
    this internally replayable tuple from being read as a geometric datum.
    """

    differential: RationalDifferential
    signature: DeformationSignature
    speciality: SpecialityWitness
    tame_order: int
    character_exponent: int
    character_values: tuple[int, ...]
    origin_scope: str
    completeness_scope: str
    component_relation_scope: str
    differential_signature_relation_claimed: bool
    label: str | None

    schema_version = "arbogast.padic.deformation-datum/v1"

    def __init__(
        self,
        differential: RationalDifferential,
        signature: DeformationSignature,
        speciality: SpecialityWitness,
        *,
        tame_order: int = 1,
        character_exponent: int = 0,
        origin_scope: str = _INTERNAL_SCOPE,
        label: str | None = None,
    ) -> None:
        if not isinstance(differential, RationalDifferential):
            raise TypeError("deformation datum needs a RationalDifferential")
        if not isinstance(signature, DeformationSignature):
            raise TypeError("deformation datum needs a DeformationSignature")
        if not isinstance(speciality, SpecialityWitness):
            raise TypeError("deformation datum needs a SpecialityWitness")
        differential.verify()
        signature.verify()
        speciality.verify()
        if speciality.signature != signature:
            raise PAdicValidationError("speciality witness is bound to another signature")
        order = strict_int(tame_order, "tame character order", minimum=1)
        if order > MAX_LOCAL_DEGREE or (differential.prime - 1) % order != 0:
            raise PAdicValidationError("tame character order must divide p-1 in the bounded slice")
        exponent = strict_int(character_exponent, "tame character exponent", minimum=0)
        if order == 1:
            if exponent != 0:
                raise PAdicValidationError("the trivial tame character has exponent zero")
        elif not 1 <= exponent < order or gcd(exponent, order) != 1:
            raise PAdicValidationError("rank-one tame character exponent must be faithful")
        if any(order % m != 0 for _, m, _ in signature.entries):
            raise PAdicValidationError("signature stabilizers must divide the tame group order")
        if origin_scope != _INTERNAL_SCOPE:
            raise PAdicValidationError(
                "direct DeformationDatum construction is internal-identities-only"
            )
        generator = _least_element_of_order(differential.prime, order)
        values = tuple(
            pow(generator, exponent * index, differential.prime) for index in range(order)
        )
        object.__setattr__(self, "differential", differential)
        object.__setattr__(self, "signature", signature)
        object.__setattr__(self, "speciality", speciality)
        object.__setattr__(self, "tame_order", order)
        object.__setattr__(self, "character_exponent", exponent)
        object.__setattr__(self, "character_values", values)
        object.__setattr__(self, "origin_scope", _INTERNAL_SCOPE)
        object.__setattr__(
            self,
            "completeness_scope",
            "componentwise-rank-one-tame-formal-identities",
        )
        object.__setattr__(self, "component_relation_scope", _COMPONENT_RELATION_SCOPE)
        object.__setattr__(self, "differential_signature_relation_claimed", False)
        object.__setattr__(
            self,
            "label",
            None if label is None else canonical_label(label, "datum label"),
        )

    @property
    def prime(self) -> int:
        return self.differential.prime

    def verify(self) -> bool:
        if not isinstance(self.differential, RationalDifferential):
            raise PAdicVerificationError("deformation differential has the wrong type")
        if not isinstance(self.signature, DeformationSignature):
            raise PAdicVerificationError("deformation signature has the wrong type")
        if not isinstance(self.speciality, SpecialityWitness):
            raise PAdicVerificationError("deformation speciality has the wrong type")
        if (
            type(self.differential_signature_relation_claimed) is not bool
            or self.differential_signature_relation_claimed
        ):
            raise PAdicVerificationError("differential-signature nonrelation boundary was altered")
        try:
            replay = DeformationDatum(
                self.differential,
                self.signature,
                self.speciality,
                tame_order=self.tame_order,
                character_exponent=self.character_exponent,
                origin_scope=self.origin_scope,
                label=self.label,
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("rank-one tame datum identities were altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "character_exponent": self.character_exponent,
            "character_values": list(self.character_values),
            "component_relation_scope": self.component_relation_scope,
            "completeness_scope": self.completeness_scope,
            "differential": self.differential.to_schema_document(),
            "differential_signature_relation_claimed": (
                self.differential_signature_relation_claimed
            ),
            "label": self.label,
            "origin_scope": self.origin_scope,
            "signature": self.signature.to_schema_document(),
            "speciality": self.speciality.to_schema_document(),
            "tame_order": self.tame_order,
            "type": "arbogast.padic.deformation_datum",
        }


@dataclass(frozen=True, slots=True, init=False)
class DeformationDatumWitness(PAdicSchemaObject):
    """Proposed geometric extraction data, kept separate from internal replay."""

    datum: DeformationDatum
    source_reduction_id: str
    source_component: dict[str, CanonicalJSON]
    group_action: dict[str, CanonicalJSON]
    differential_extraction_rule: str
    divisor_residue_data: dict[str, CanonicalJSON]
    theorem_profile: str

    schema_version = "arbogast.padic.deformation-datum-witness/v1"

    def __init__(
        self,
        datum: DeformationDatum,
        source_reduction_id: str,
        source_component: Mapping[str, object],
        group_action: Mapping[str, object],
        divisor_residue_data: Mapping[str, object],
        *,
        differential_extraction_rule: str,
        theorem_profile: str = _GEOMETRIC_PROFILE,
    ) -> None:
        if not isinstance(datum, DeformationDatum):
            raise TypeError("datum witness needs a DeformationDatum")
        datum.verify()
        reduction_id = canonical_label(source_reduction_id, "source reduction ID")
        component = strict_canonical_mapping(source_component, "source component witness")
        action = strict_canonical_mapping(group_action, "source group-action witness")
        divisor = strict_canonical_mapping(divisor_residue_data, "divisor-residue witness")
        rule = canonical_label(differential_extraction_rule, "differential extraction rule")
        profile = canonical_label(theorem_profile, "deformation-datum theorem profile")
        object.__setattr__(self, "datum", datum)
        object.__setattr__(self, "source_reduction_id", reduction_id)
        object.__setattr__(self, "source_component", component)
        object.__setattr__(self, "group_action", action)
        object.__setattr__(self, "differential_extraction_rule", rule)
        object.__setattr__(self, "divisor_residue_data", divisor)
        object.__setattr__(self, "theorem_profile", profile)

    def verify(self) -> bool:
        if not isinstance(self.datum, DeformationDatum):
            raise PAdicVerificationError("datum witness value has the wrong type")
        self.datum.verify()
        canonical_label(self.source_reduction_id, "source reduction ID")
        strict_canonical_mapping(self.source_component, "source component witness")
        strict_canonical_mapping(self.group_action, "source group-action witness")
        strict_canonical_mapping(self.divisor_residue_data, "divisor-residue witness")
        canonical_label(self.differential_extraction_rule, "differential extraction rule")
        canonical_label(self.theorem_profile, "deformation-datum theorem profile")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "datum": self.datum.to_schema_document(),
            "differential_extraction_rule": self.differential_extraction_rule,
            "divisor_residue_data": self.divisor_residue_data,
            "group_action": self.group_action,
            "source_component": self.source_component,
            "source_reduction_id": self.source_reduction_id,
            "theorem_profile": self.theorem_profile,
            "type": "arbogast.padic.deformation_datum_witness",
        }


def _unknown(
    reason_code: str,
    reason: str,
    requested: Mapping[str, object],
) -> Unknown:
    return unknown_result(
        "padic.deformation_datum",
        reason_code,
        reason,
        requested=requested,
        family="three-point",
    )


def _unsupported(
    reason_code: str,
    reason: str,
    requested: Mapping[str, object],
) -> Unsupported:
    supported = (
        "internal rank-one tame datum identities",
        "explicit pinned Wewers extraction profile",
    )
    return unsupported_result(
        "padic.deformation_datum",
        reason_code,
        reason,
        requested=requested,
        supported=supported,
        family="three-point",
    )


def deformation_datum(
    reduction: Certified[StableReduction],
    *,
    witness: DeformationDatumWitness | None = None,
) -> Certified[DeformationDatum] | Unknown | Unsupported:
    """Attempt geometric extraction without confusing internal consistency with origin."""

    from .reduction import StableReduction

    if not isinstance(reduction, Certified) or not isinstance(reduction.value, StableReduction):
        raise TypeError("deformation_datum needs a Certified[StableReduction]")
    reduction.verify()
    requested = {
        "reduction_certificate_id": reduction.certificate.certificate_id,
        "reduction_id": reduction.value.content_id,
    }
    if witness is None:
        return _unknown(
            "missing-deformation-datum-witness",
            "stable reduction does not itself contain a group action and differential extraction",
            requested,
        )
    if not isinstance(witness, DeformationDatumWitness):
        raise TypeError("witness must be a DeformationDatumWitness")
    witness.verify()
    if witness.source_reduction_id != reduction.value.content_id:
        raise PAdicValidationError("deformation-datum witness names another stable reduction")
    # The 0.5 stable-reduction profile deliberately contains marked components
    # but no group action, inertia character, extraction rule, or theorem profile.
    # An ID match therefore cannot promote a synthetic datum to geometric origin.
    return _unsupported(
        "stable-profile-lacks-wewers-extraction",
        "the certified stable model lacks the exact group action and differential extraction data",
        {**requested, "witness_id": witness.content_id},
    )


def _differential_from_schema(value: object) -> RationalDifferential:
    raw = _strict_object(value, "rational differential")
    _exact_keys(
        raw,
        {
            "schema",
            "cartier_relation",
            "denominator",
            "differential_kind",
            "logarithmic_unit",
            "numerator",
            "prime",
            "type",
        },
        "rational differential",
    )
    unit = _strict_array(raw["logarithmic_unit"], "logarithmic unit")
    if any(type(item) is not int for item in unit) or type(raw["prime"]) is not int:
        raise PAdicVerificationError("rational differential has non-integer finite-field data")
    result = RationalDifferential(raw["prime"], cast(list[int], unit))
    if raw != result.to_schema_document():
        raise PAdicVerificationError("rational differential transport was altered")
    return result


def _signature_from_schema(value: object) -> DeformationSignature:
    raw = _strict_object(value, "deformation signature")
    _exact_keys(raw, {"schema", "entries", "type"}, "deformation signature")
    raw_entries = _strict_array(raw["entries"], "deformation signature entries")
    if len(raw_entries) > MAX_LOCAL_DEGREE:
        raise PAdicResourceError("deformation signature exceeds the entry-count bound")
    entries: list[SignatureEntry] = []
    for item in raw_entries:
        entry = _strict_object(item, "deformation signature entry")
        _exact_keys(entry, {"h", "label", "m", "sigma"}, "deformation signature entry")
        if (
            type(entry["label"]) is not str
            or type(entry["m"]) is not int
            or type(entry["h"]) is not int
        ):
            raise PAdicVerificationError("deformation signature entry has wrong scalar types")
        entries.append((entry["label"], entry["m"], entry["h"]))
    result = DeformationSignature(entries)
    if raw != result.to_schema_document():
        raise PAdicVerificationError("deformation signature transport was altered")
    return result


def _speciality_from_schema(value: object, signature: DeformationSignature) -> SpecialityWitness:
    raw = _strict_object(value, "speciality witness")
    labels = _strict_array(raw.get("normalized_labels"), "normalized special labels")
    if len(labels) != 3:
        raise PAdicVerificationError("normalized special labels must have cardinality three")
    if any(type(item) is not str for item in labels):
        raise PAdicVerificationError("normalized special labels must be strings")
    result = SpecialityWitness(signature, normalized_labels=cast(list[str], labels))
    if raw != result.to_schema_document():
        raise PAdicVerificationError("speciality witness transport was altered")
    return result


def deformation_datum_from_schema(value: object) -> DeformationDatum:
    """Strict internal decoder shared by the lift receipt replay."""

    raw = _strict_object(value, "deformation datum")
    _exact_keys(
        raw,
        {
            "schema",
            "character_exponent",
            "character_values",
            "component_relation_scope",
            "completeness_scope",
            "differential",
            "differential_signature_relation_claimed",
            "label",
            "origin_scope",
            "signature",
            "speciality",
            "tame_order",
            "type",
        },
        "deformation datum",
    )
    differential = _differential_from_schema(raw["differential"])
    signature = _signature_from_schema(raw["signature"])
    speciality = _speciality_from_schema(raw["speciality"], signature)
    if type(raw["tame_order"]) is not int or type(raw["character_exponent"]) is not int:
        raise PAdicVerificationError("deformation character data must be integers")
    if raw["label"] is not None and type(raw["label"]) is not str:
        raise PAdicVerificationError("deformation datum label has the wrong type")
    result = DeformationDatum(
        differential,
        signature,
        speciality,
        tame_order=raw["tame_order"],
        character_exponent=raw["character_exponent"],
        origin_scope=cast(str, raw["origin_scope"]),
        label=raw["label"],
    )
    if raw != result.to_schema_document():
        raise PAdicVerificationError("deformation datum transport was altered")
    return result


@padic_payload_verifier("deformation-datum")
def _verify_deformation_datum_payload(
    payload: Mapping[str, object],
    evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    if set(payload) != {"result"} or evidence:
        raise PAdicVerificationError("internal deformation datum receipt has foreign evidence")
    deformation_datum_from_schema(payload["result"])
    return PAdicPayloadReplay(
        checks=(
            "rank-one-logarithmic-differential-identities",
            "tame-character-homomorphism",
            "componentwise-special-signature-numerics",
            "no-differential-signature-divisor-relation-claimed",
            "internal-origin-scope-only",
        )
    )


__all__ = [
    "DeformationDatum",
    "DeformationDatumWitness",
    "DeformationSignature",
    "RationalDifferential",
    "SpecialityWitness",
    "deformation_datum",
]
