"""A rigid, proof-bearing effective-descent slice for finite lift classes.

A fixed lift class is deliberately insufficient.  Positive descent in this
module additionally requires triviality in the pinned labeled-model category,
one exact isomorphism for every arithmetic quotient element, the cocycle law,
an explicit descended coefficient vector, and inverse base-change maps.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from arbogast.cert import VerificationCertificate
from arbogast.core import CanonicalJSON
from arbogast.rep import Permutation

from ._schema import PAdicSchemaObject, canonical_label, strict_int
from .certificate import PAdicPayloadReplay, padic_payload_verifier
from .errors import PAdicValidationError, PAdicVerificationError
from .lifts import (
    FixedLift,
    FixedLiftSet,
    LiftGaloisAction,
    _permutation_data,
    _permutation_from_schema,
    _require_source_evidence,
    fixed_lift_set_from_schema,
)
from .results import Certified, PAdicResult, certified_result, unknown_result

_RIGIDITY_SCOPE = "label-preserving-automorphisms-of-pinned-chart-model"
_ISOMORPHISM_SCOPE = "label-preserving-coordinate-isomorphism"
_DESCENT_SCOPE = "effective-descent-in-pinned-F_p-labeled-chart-model-category"
_MODEL_FIELD_SCOPE = "prime-field-F_p-chart-coefficients"


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


def _transport(values: tuple[int, ...], permutation: Permutation) -> tuple[int, ...]:
    if permutation.degree != len(values):
        raise PAdicValidationError("base-change permutation has the wrong coordinate degree")
    result = [0] * len(values)
    for source, target in enumerate(permutation.images):
        result[target] = values[source]
    return tuple(result)


def _require_label_preserving(fixed: FixedLift, permutation: Permutation) -> None:
    labels = fixed.candidate.chart.coordinate_labels
    if permutation.degree != len(labels):
        raise PAdicValidationError("model isomorphism has the wrong coordinate degree")
    if any(labels[permutation(index)] != label for index, label in enumerate(labels)):
        raise PAdicValidationError("model isomorphism does not preserve coordinate labels")


@dataclass(frozen=True, slots=True, init=False)
class AutomorphismTrivialityWitness(PAdicSchemaObject):
    """Exhaust the label-preserving automorphisms of one pinned model."""

    fixed: FixedLift
    automorphisms: tuple[Permutation, ...]
    category_scope: str
    exhaustive: bool

    schema_version = "arbogast.padic.automorphism-triviality-witness/v1"

    def __init__(
        self,
        fixed: FixedLift,
        automorphisms: Sequence[Permutation],
    ) -> None:
        if not isinstance(fixed, FixedLift):
            raise TypeError("automorphism witness needs a FixedLift")
        fixed.verify()
        if len(automorphisms) != 1:
            raise PAdicValidationError("the rigid slice requires exactly the identity automorphism")
        normalized = tuple(automorphisms)
        identity = Permutation.identity(len(fixed.candidate.model_coefficients))
        if normalized != (identity,):
            raise PAdicValidationError(
                "the rigid slice requires the complete automorphism list to be identity only"
            )
        # Coordinate labels are unique by LiftChart construction.  Therefore a
        # label-preserving coordinate permutation fixes every coordinate.
        _require_label_preserving(fixed, identity)
        object.__setattr__(self, "fixed", fixed)
        object.__setattr__(self, "automorphisms", normalized)
        object.__setattr__(self, "category_scope", _RIGIDITY_SCOPE)
        object.__setattr__(self, "exhaustive", True)

    def verify(self) -> bool:
        if type(self.exhaustive) is not bool or not self.exhaustive:
            raise PAdicVerificationError("automorphism exhaustion flag was altered")
        try:
            replay = AutomorphismTrivialityWitness(self.fixed, self.automorphisms)
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("automorphism triviality or category scope changed")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "automorphisms": [_permutation_data(item) for item in self.automorphisms],
                "category_scope": self.category_scope,
                "exhaustive": self.exhaustive,
                "fixed_lift_id": self.fixed.content_id,
                "type": "arbogast.padic.automorphism_triviality_witness",
            },
        )


@dataclass(frozen=True, slots=True, init=False)
class RigidFixedLift(PAdicSchemaObject):
    """A fixed lift paired with exhaustive triviality in the pinned category."""

    fixed: FixedLift
    triviality: AutomorphismTrivialityWitness
    rigidity_scope: str

    schema_version = "arbogast.padic.rigid-fixed-lift/v1"

    def __init__(
        self,
        fixed: FixedLift,
        triviality: AutomorphismTrivialityWitness,
    ) -> None:
        if not isinstance(fixed, FixedLift):
            raise TypeError("rigid fixed lift needs a FixedLift")
        if not isinstance(triviality, AutomorphismTrivialityWitness):
            raise TypeError("rigid fixed lift needs an AutomorphismTrivialityWitness")
        fixed.verify()
        triviality.verify()
        if triviality.fixed != fixed:
            raise PAdicValidationError("automorphism witness is bound to another fixed lift")
        object.__setattr__(self, "fixed", fixed)
        object.__setattr__(self, "triviality", triviality)
        object.__setattr__(self, "rigidity_scope", _RIGIDITY_SCOPE)

    def verify(self) -> bool:
        try:
            replay = RigidFixedLift(self.fixed, self.triviality)
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("rigid fixed lift binding was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "fixed": self.fixed.to_schema_document(),
            "rigidity_scope": self.rigidity_scope,
            "triviality": self.triviality.to_schema_document(),
            "type": "arbogast.padic.rigid_fixed_lift",
        }


@dataclass(frozen=True, slots=True, init=False)
class DescentIsomorphism(PAdicSchemaObject):
    """One explicit, invertible, label-preserving model isomorphism."""

    rigid: RigidFixedLift
    quotient_element: Permutation
    forward: Permutation
    inverse: Permutation
    isomorphism_scope: str

    schema_version = "arbogast.padic.descent-isomorphism/v1"

    def __init__(
        self,
        rigid: RigidFixedLift,
        quotient_element: Permutation,
        forward: Permutation,
        inverse: Permutation,
    ) -> None:
        if not isinstance(rigid, RigidFixedLift):
            raise TypeError("descent isomorphism needs a RigidFixedLift")
        if not isinstance(quotient_element, Permutation):
            raise TypeError("descent isomorphism quotient element must be a Permutation")
        if not isinstance(forward, Permutation) or not isinstance(inverse, Permutation):
            raise TypeError("descent maps must be Permutation objects")
        rigid.verify()
        identity = Permutation.identity(len(rigid.fixed.candidate.model_coefficients))
        if forward * inverse != identity or inverse * forward != identity:
            raise PAdicValidationError("descent isomorphism maps are not two-sided inverses")
        _require_label_preserving(rigid.fixed, forward)
        _require_label_preserving(rigid.fixed, inverse)
        coefficients = rigid.fixed.candidate.model_coefficients
        if _transport(coefficients, forward) != coefficients:
            raise PAdicValidationError("descent isomorphism does not preserve the pinned model")
        object.__setattr__(self, "rigid", rigid)
        object.__setattr__(self, "quotient_element", quotient_element)
        object.__setattr__(self, "forward", forward)
        object.__setattr__(self, "inverse", inverse)
        object.__setattr__(self, "isomorphism_scope", _ISOMORPHISM_SCOPE)

    def verify(self) -> bool:
        try:
            replay = DescentIsomorphism(
                self.rigid,
                self.quotient_element,
                self.forward,
                self.inverse,
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("descent isomorphism or inverse binding changed")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "forward": _permutation_data(self.forward),
                "inverse": _permutation_data(self.inverse),
                "isomorphism_scope": self.isomorphism_scope,
                "quotient_element": _permutation_data(self.quotient_element),
                "rigid_fixed_lift_id": self.rigid.content_id,
                "type": "arbogast.padic.descent_isomorphism",
            },
        )


@dataclass(frozen=True, slots=True, init=False)
class DescentCocycle(PAdicSchemaObject):
    """One complete exact cocycle over the bound arithmetic quotient."""

    action: LiftGaloisAction
    rigid: RigidFixedLift
    isomorphisms: tuple[DescentIsomorphism, ...]
    cocycle_convention: str

    schema_version = "arbogast.padic.descent-cocycle/v1"

    def __init__(
        self,
        action: LiftGaloisAction,
        rigid: RigidFixedLift,
        isomorphisms: Sequence[DescentIsomorphism],
    ) -> None:
        if not isinstance(action, LiftGaloisAction):
            raise TypeError("descent cocycle needs an arithmetic LiftGaloisAction")
        if not isinstance(rigid, RigidFixedLift):
            raise TypeError("descent cocycle needs a RigidFixedLift")
        action.verify()
        rigid.verify()
        if rigid.fixed.action != action:
            raise PAdicValidationError("rigid fixed lift belongs to another arithmetic action")
        if len(isomorphisms) != action.group.order:
            raise PAdicValidationError(
                "descent cocycle needs exactly one isomorphism per quotient element"
            )
        normalized = tuple(sorted(isomorphisms, key=lambda item: item.quotient_element.images))
        if any(
            not isinstance(item, DescentIsomorphism) or item.rigid != rigid for item in normalized
        ):
            raise PAdicValidationError("descent cocycle contains a foreign isomorphism")
        if tuple(item.quotient_element for item in normalized) != action.group.elements:
            raise PAdicValidationError(
                "descent cocycle needs exactly one isomorphism per quotient element"
            )
        maps = {item.quotient_element: item.forward for item in normalized}
        identity = Permutation.identity(len(rigid.fixed.candidate.model_coefficients))
        if maps[action.group.identity] != identity:
            raise PAdicValidationError("descent cocycle identity map is not identity")
        for left in action.group.elements:
            for right in action.group.elements:
                if maps[action.group.multiply(left, right)] != maps[left] * maps[right]:
                    raise PAdicValidationError("descent isomorphisms fail the cocycle law")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "rigid", rigid)
        object.__setattr__(self, "isomorphisms", normalized)
        object.__setattr__(self, "cocycle_convention", Permutation.COMPOSITION_CONVENTION)

    def verify(self) -> bool:
        try:
            replay = DescentCocycle(self.action, self.rigid, self.isomorphisms)
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("descent cocycle law or convention was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action_id": self.action.content_id,
            "cocycle_convention": self.cocycle_convention,
            "isomorphisms": [item.to_schema_document() for item in self.isomorphisms],
            "quotient_id": self.action.quotient_id,
            "rigid_fixed_lift_id": self.rigid.content_id,
            "type": "arbogast.padic.descent_cocycle",
        }


@dataclass(frozen=True, slots=True, init=False)
class RigidDescentWitness(PAdicSchemaObject):
    """Rigidity, cocycle, explicit model, and two-sided base change together."""

    fixed_set: FixedLiftSet
    rigid: RigidFixedLift
    cocycle: DescentCocycle
    descended_model_coefficients: tuple[int, ...]
    base_change_forward: Permutation
    base_change_inverse: Permutation
    descent_scope: str

    schema_version = "arbogast.padic.rigid-descent-witness/v1"

    def __init__(
        self,
        fixed_set: FixedLiftSet,
        rigid: RigidFixedLift,
        cocycle: DescentCocycle,
        descended_model_coefficients: Sequence[int],
        base_change_forward: Permutation,
        base_change_inverse: Permutation,
    ) -> None:
        if not isinstance(fixed_set, FixedLiftSet):
            raise TypeError("rigid descent witness needs a FixedLiftSet")
        if not isinstance(fixed_set.action, LiftGaloisAction):
            raise PAdicValidationError("effective descent needs an arithmetic Galois action")
        if not isinstance(rigid, RigidFixedLift) or not isinstance(cocycle, DescentCocycle):
            raise TypeError("rigid descent witness needs rigidity and cocycle witnesses")
        fixed_set.verify()
        rigid.verify()
        cocycle.verify()
        if rigid.fixed not in fixed_set.fixed:
            raise PAdicValidationError("rigid lift is not in the supplied fixed set")
        if cocycle.action != fixed_set.action or cocycle.rigid != rigid:
            raise PAdicValidationError("descent cocycle is bound to another fixed lift set")
        prime = rigid.fixed.candidate.chart.prime
        target = rigid.fixed.candidate.model_coefficients
        if len(descended_model_coefficients) != len(target):
            raise PAdicValidationError("descended model has the wrong coordinate length")
        descended = tuple(
            strict_int(item, f"descended coefficient[{index}]", minimum=0)
            for index, item in enumerate(descended_model_coefficients)
        )
        if any(item >= prime for item in descended):
            raise PAdicValidationError("descended coefficients must be canonical modulo p")
        identity = Permutation.identity(len(target))
        if (
            base_change_forward * base_change_inverse != identity
            or base_change_inverse * base_change_forward != identity
        ):
            raise PAdicValidationError("base-change maps are not two-sided inverses")
        _require_label_preserving(rigid.fixed, base_change_forward)
        _require_label_preserving(rigid.fixed, base_change_inverse)
        if (
            _transport(descended, base_change_forward) != target
            or _transport(target, base_change_inverse) != descended
        ):
            raise PAdicValidationError("explicit model fails two-sided base-change replay")
        object.__setattr__(self, "fixed_set", fixed_set)
        object.__setattr__(self, "rigid", rigid)
        object.__setattr__(self, "cocycle", cocycle)
        object.__setattr__(self, "descended_model_coefficients", descended)
        object.__setattr__(self, "base_change_forward", base_change_forward)
        object.__setattr__(self, "base_change_inverse", base_change_inverse)
        object.__setattr__(self, "descent_scope", _DESCENT_SCOPE)

    def verify(self) -> bool:
        try:
            replay = RigidDescentWitness(
                self.fixed_set,
                self.rigid,
                self.cocycle,
                self.descended_model_coefficients,
                self.base_change_forward,
                self.base_change_inverse,
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("rigid descent witness was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "base_change_forward": _permutation_data(self.base_change_forward),
                "base_change_inverse": _permutation_data(self.base_change_inverse),
                "cocycle": self.cocycle.to_schema_document(),
                "descended_model_coefficients": list(self.descended_model_coefficients),
                "descent_scope": self.descent_scope,
                "fixed_set_id": self.fixed_set.content_id,
                "rigid": self.rigid.to_schema_document(),
                "type": "arbogast.padic.rigid_descent_witness",
            },
        )


@dataclass(frozen=True, slots=True, init=False)
class DescendedModel(PAdicSchemaObject):
    """The explicit ``F_p`` chart model certified by rigid finite descent.

    This object does not claim a characteristic-zero model, a number-field
    model, or a descended algebraic cover.  Those geometric conclusions need
    a different base-change functor and are outside the 0.5 slice.
    """

    fixed_set: FixedLiftSet
    witness: RigidDescentWitness
    prime: int
    coordinate_labels: tuple[str, ...]
    coefficients: tuple[int, ...]
    source_fixed_set_certificate_id: str
    descent_scope: str
    model_field_scope: str
    automorphisms_trivial: bool
    cocycle_verified: bool
    two_sided_base_change_verified: bool
    characteristic_zero_descent_claimed: bool
    number_field_descent_claimed: bool
    geometric_cover_descent_claimed: bool

    schema_version = "arbogast.padic.descended-model/v1"

    def __init__(
        self,
        fixed_set: FixedLiftSet,
        witness: RigidDescentWitness,
        *,
        source_fixed_set_certificate_id: str,
    ) -> None:
        if not isinstance(fixed_set, FixedLiftSet):
            raise TypeError("descended model needs a FixedLiftSet")
        if not isinstance(witness, RigidDescentWitness):
            raise TypeError("descended model needs a RigidDescentWitness")
        fixed_set.verify()
        witness.verify()
        if witness.fixed_set != fixed_set:
            raise PAdicValidationError("descent witness is bound to another fixed lift set")
        source_id = canonical_label(
            source_fixed_set_certificate_id,
            "source fixed-set certificate ID",
        )
        candidate = witness.rigid.fixed.candidate
        object.__setattr__(self, "fixed_set", fixed_set)
        object.__setattr__(self, "witness", witness)
        object.__setattr__(self, "prime", candidate.chart.prime)
        object.__setattr__(self, "coordinate_labels", candidate.chart.coordinate_labels)
        object.__setattr__(self, "coefficients", witness.descended_model_coefficients)
        object.__setattr__(self, "source_fixed_set_certificate_id", source_id)
        object.__setattr__(self, "descent_scope", _DESCENT_SCOPE)
        object.__setattr__(self, "model_field_scope", _MODEL_FIELD_SCOPE)
        object.__setattr__(self, "automorphisms_trivial", True)
        object.__setattr__(self, "cocycle_verified", True)
        object.__setattr__(self, "two_sided_base_change_verified", True)
        object.__setattr__(self, "characteristic_zero_descent_claimed", False)
        object.__setattr__(self, "number_field_descent_claimed", False)
        object.__setattr__(self, "geometric_cover_descent_claimed", False)

    def verify(self) -> bool:
        flags = (
            self.automorphisms_trivial,
            self.cocycle_verified,
            self.two_sided_base_change_verified,
            self.characteristic_zero_descent_claimed,
            self.number_field_descent_claimed,
            self.geometric_cover_descent_claimed,
        )
        if any(type(item) is not bool for item in flags):
            raise PAdicVerificationError("descended-model proof flags must be booleans")
        if flags[:3] != (True, True, True) or flags[3:] != (False, False, False):
            raise PAdicVerificationError("descended-model proof boundary flags were altered")
        try:
            replay = DescendedModel(
                self.fixed_set,
                self.witness,
                source_fixed_set_certificate_id=self.source_fixed_set_certificate_id,
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("descended model or proof flags were altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "automorphisms_trivial": self.automorphisms_trivial,
                "characteristic_zero_descent_claimed": (self.characteristic_zero_descent_claimed),
                "cocycle_verified": self.cocycle_verified,
                "coefficients": list(self.coefficients),
                "coordinate_labels": list(self.coordinate_labels),
                "descent_scope": self.descent_scope,
                "fixed_set": self.fixed_set.to_schema_document(),
                "geometric_cover_descent_claimed": self.geometric_cover_descent_claimed,
                "model_field_scope": self.model_field_scope,
                "number_field_descent_claimed": self.number_field_descent_claimed,
                "prime": self.prime,
                "source_fixed_set_certificate_id": self.source_fixed_set_certificate_id,
                "two_sided_base_change_verified": self.two_sided_base_change_verified,
                "type": "arbogast.padic.descended_model",
                "witness": self.witness.to_schema_document(),
            },
        )


def effective_descent(
    fixed: Certified[FixedLiftSet],
    *,
    witness: RigidDescentWitness | None = None,
) -> PAdicResult[DescendedModel]:
    """Certify descent only after all rigid effective-descent data replay."""

    if not isinstance(fixed, Certified) or not isinstance(fixed.value, FixedLiftSet):
        raise TypeError("effective_descent needs a Certified[FixedLiftSet]")
    fixed.verify()
    requested = {
        "fixed_set_certificate_id": fixed.certificate.certificate_id,
        "fixed_set_id": fixed.value.content_id,
    }
    if witness is None:
        return unknown_result(
            "padic.effective_descent",
            "missing-rigid-descent-witness",
            "a fixed lift class alone does not prove effective descent",
            requested=requested,
            family="three-point",
        )
    if not isinstance(witness, RigidDescentWitness):
        raise TypeError("witness must be a RigidDescentWitness")
    if witness.fixed_set != fixed.value:
        raise PAdicValidationError("rigid descent witness is bound to another fixed set")
    certificate = fixed.certificate
    result = DescendedModel(
        fixed.value,
        witness,
        source_fixed_set_certificate_id=certificate.certificate_id,
    )
    return certified_result(result, "descended-model", evidence=(certificate,))


def _fixed_by_index(fixed_set: FixedLiftSet, index: int) -> FixedLift:
    match = next((item for item in fixed_set.fixed if item.lift_index == index), None)
    if match is None:
        raise PAdicVerificationError("descent witness names a non-fixed lift index")
    return match


def _triviality_from_schema(
    value: object,
    fixed: FixedLift,
) -> AutomorphismTrivialityWitness:
    raw = _strict_object(value, "automorphism triviality witness")
    _exact_keys(
        raw,
        {
            "schema",
            "automorphisms",
            "category_scope",
            "exhaustive",
            "fixed_lift_id",
            "type",
        },
        "automorphism triviality witness",
    )
    raw_automorphisms = _strict_array(raw["automorphisms"], "model automorphisms")
    if len(raw_automorphisms) != 1:
        raise PAdicVerificationError("automorphism witness must contain exactly identity")
    automorphisms = tuple(
        _permutation_from_schema(item, f"model automorphism[{index}]")
        for index, item in enumerate(raw_automorphisms)
    )
    result = AutomorphismTrivialityWitness(fixed, automorphisms)
    if raw != result.to_schema_document():
        raise PAdicVerificationError("automorphism triviality transport was altered")
    return result


def _rigid_from_schema(value: object, fixed_set: FixedLiftSet) -> RigidFixedLift:
    raw = _strict_object(value, "rigid fixed lift")
    _exact_keys(
        raw,
        {"schema", "fixed", "rigidity_scope", "triviality", "type"},
        "rigid fixed lift",
    )
    fixed_raw = _strict_object(raw["fixed"], "rigid fixed lift value")
    if type(fixed_raw.get("lift_index")) is not int:
        raise PAdicVerificationError("rigid fixed lift index must be an integer")
    fixed = _fixed_by_index(fixed_set, cast(int, fixed_raw["lift_index"]))
    if fixed_raw != fixed.to_schema_document():
        raise PAdicVerificationError("rigid fixed lift transport names another fixed class")
    result = RigidFixedLift(fixed, _triviality_from_schema(raw["triviality"], fixed))
    if raw != result.to_schema_document():
        raise PAdicVerificationError("rigid fixed-lift transport was altered")
    return result


def _isomorphism_from_schema(
    value: object,
    rigid: RigidFixedLift,
) -> DescentIsomorphism:
    raw = _strict_object(value, "descent isomorphism")
    _exact_keys(
        raw,
        {
            "schema",
            "forward",
            "inverse",
            "isomorphism_scope",
            "quotient_element",
            "rigid_fixed_lift_id",
            "type",
        },
        "descent isomorphism",
    )
    result = DescentIsomorphism(
        rigid,
        _permutation_from_schema(raw["quotient_element"], "quotient element"),
        _permutation_from_schema(raw["forward"], "descent forward map"),
        _permutation_from_schema(raw["inverse"], "descent inverse map"),
    )
    if raw != result.to_schema_document():
        raise PAdicVerificationError("descent-isomorphism transport was altered")
    return result


def _cocycle_from_schema(
    value: object,
    action: LiftGaloisAction,
    rigid: RigidFixedLift,
) -> DescentCocycle:
    raw = _strict_object(value, "descent cocycle")
    _exact_keys(
        raw,
        {
            "schema",
            "action_id",
            "cocycle_convention",
            "isomorphisms",
            "quotient_id",
            "rigid_fixed_lift_id",
            "type",
        },
        "descent cocycle",
    )
    raw_isomorphisms = _strict_array(raw["isomorphisms"], "descent isomorphisms")
    if len(raw_isomorphisms) != action.group.order:
        raise PAdicVerificationError("descent cocycle has the wrong isomorphism cardinality")
    isomorphisms = tuple(_isomorphism_from_schema(item, rigid) for item in raw_isomorphisms)
    result = DescentCocycle(action, rigid, isomorphisms)
    if raw != result.to_schema_document():
        raise PAdicVerificationError("descent-cocycle transport was altered")
    return result


def _witness_from_schema(
    value: object,
    fixed_set: FixedLiftSet,
) -> RigidDescentWitness:
    raw = _strict_object(value, "rigid descent witness")
    _exact_keys(
        raw,
        {
            "schema",
            "base_change_forward",
            "base_change_inverse",
            "cocycle",
            "descended_model_coefficients",
            "descent_scope",
            "fixed_set_id",
            "rigid",
            "type",
        },
        "rigid descent witness",
    )
    if not isinstance(fixed_set.action, LiftGaloisAction):
        raise PAdicVerificationError("rigid descent transport lost its arithmetic action")
    rigid = _rigid_from_schema(raw["rigid"], fixed_set)
    coefficients = _strict_array(
        raw["descended_model_coefficients"],
        "descended model coefficients",
    )
    if len(coefficients) != len(rigid.fixed.candidate.model_coefficients):
        raise PAdicVerificationError("descended model coefficients have the wrong cardinality")
    if any(type(item) is not int for item in coefficients):
        raise PAdicVerificationError("descended model coefficients must be integers")
    result = RigidDescentWitness(
        fixed_set,
        rigid,
        _cocycle_from_schema(raw["cocycle"], fixed_set.action, rigid),
        cast(list[int], coefficients),
        _permutation_from_schema(raw["base_change_forward"], "base-change forward map"),
        _permutation_from_schema(raw["base_change_inverse"], "base-change inverse map"),
    )
    if raw != result.to_schema_document():
        raise PAdicVerificationError("rigid descent witness transport was altered")
    return result


def descended_model_from_schema(value: object) -> DescendedModel:
    raw = _strict_object(value, "descended model")
    _exact_keys(
        raw,
        {
            "schema",
            "automorphisms_trivial",
            "characteristic_zero_descent_claimed",
            "cocycle_verified",
            "coefficients",
            "coordinate_labels",
            "descent_scope",
            "fixed_set",
            "geometric_cover_descent_claimed",
            "model_field_scope",
            "number_field_descent_claimed",
            "prime",
            "source_fixed_set_certificate_id",
            "two_sided_base_change_verified",
            "type",
            "witness",
        },
        "descended model",
    )
    fixed_set = fixed_lift_set_from_schema(raw["fixed_set"])
    if type(raw["source_fixed_set_certificate_id"]) is not str:
        raise PAdicVerificationError("source fixed-set certificate ID must be a string")
    result = DescendedModel(
        fixed_set,
        _witness_from_schema(raw["witness"], fixed_set),
        source_fixed_set_certificate_id=raw["source_fixed_set_certificate_id"],
    )
    if raw != result.to_schema_document():
        raise PAdicVerificationError("descended-model transport was altered")
    return result


@padic_payload_verifier("descended-model")
def _verify_descended_model_payload(
    payload: Mapping[str, object],
    evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    if set(payload) != {"result"}:
        raise PAdicVerificationError("descended-model receipt payload has a foreign shape")
    result = descended_model_from_schema(payload["result"])
    _require_source_evidence(
        evidence,
        result.source_fixed_set_certificate_id,
        "fixed-lift-set",
        result.fixed_set.to_schema_document(),
    )
    return PAdicPayloadReplay(
        checks=(
            "pinned-category-automorphism-triviality",
            "complete-exact-descent-cocycle",
            "explicit-descended-model",
            "prime-field-chart-model-scope-only",
            "no-characteristic-zero-or-geometric-cover-descent-claim",
            "two-sided-base-change-identities",
        ),
        evidence_ids=(result.source_fixed_set_certificate_id,),
    )


__all__ = [
    "AutomorphismTrivialityWitness",
    "DescendedModel",
    "DescentCocycle",
    "DescentIsomorphism",
    "RigidDescentWitness",
    "RigidFixedLift",
    "effective_descent",
]
