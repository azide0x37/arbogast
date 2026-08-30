"""Finite pinned-chart lift enumeration and exact finite-set actions.

This module proves completeness only inside one displayed finite affine chart.
Its ``FiniteLiftAction`` is a literal action on the enumerated set.  Arithmetic
Galois meaning is added only by ``lift_galois_action`` after consuming a
complete :class:`arbogast.galois.FiniteGaloisQuotient` certificate.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, cast

from arbogast.cert import VerificationCertificate, content_address
from arbogast.core import CanonicalJSON
from arbogast.galois import FiniteGaloisQuotient
from arbogast.rep import Permutation, PermutationGroup

from ._schema import (
    MAX_DIMENSION,
    MAX_EXACT_REPLAY_WORK,
    MAX_GROUP_ORDER,
    MAX_LIFTS,
    MAX_LOCAL_DEGREE,
    PAdicSchemaObject,
    canonical_label,
    strict_canonical_equal,
    strict_canonical_mapping,
    strict_int,
)
from .certificate import PAdicPayloadReplay, padic_payload_verifier
from .errors import PAdicResourceError, PAdicValidationError, PAdicVerificationError
from .results import (
    Certified,
    PAdicResult,
    certified_result,
    unknown_result,
    unsupported_result,
)
from .wewers import DeformationDatum, deformation_datum_from_schema

FPPolynomial: TypeAlias = tuple[int, ...]
ExactLiftAction: TypeAlias = "FiniteLiftAction | LiftGaloisAction"

_CHART_SCOPE = "pinned-chart"
_MODEL_SCOPE = "ordered-labeled-finite-field-coefficients"
_FINITE_ACTION_SCOPE = "declared-finite-set-bijections"
_ARITHMETIC_ACTION_SCOPE = "complete-trivial-galois-quotient-identity-action-on-pinned-F_p-models"
_COEFFICIENT_ACTION_RULE = "trivial-on-prime-field-F_p-coefficients-v1"


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


def _evaluate(values: FPPolynomial, parameter: int, prime: int) -> int:
    result = 0
    for coefficient in reversed(values):
        result = (result * parameter + coefficient) % prime
    return result


def _permutation_data(value: Permutation) -> list[int]:
    if not isinstance(value, Permutation):
        raise TypeError("exact action values must be Permutation objects")
    return list(value.images)


def _permutation_from_schema(value: object, name: str) -> Permutation:
    raw = _strict_array(value, name)
    if len(raw) > MAX_DIMENSION:
        raise PAdicResourceError(f"{name} exceeds the bounded permutation degree")
    if any(type(item) is not int for item in raw):
        raise PAdicVerificationError(f"{name} must contain exact integers")
    try:
        return Permutation(cast(list[int], raw))
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc


def _group_data(group: PermutationGroup) -> dict[str, object]:
    if not isinstance(group, PermutationGroup):
        raise TypeError("finite lift actions need a concrete PermutationGroup")
    if group.order > MAX_GROUP_ORDER:
        raise PAdicResourceError("finite lift action exceeds the bounded group order")
    if group.degree > MAX_DIMENSION:
        raise PAdicResourceError("finite lift action exceeds the bounded permutation degree")
    if group.order**2 * max(1, group.degree) > MAX_EXACT_REPLAY_WORK:
        raise PAdicResourceError("finite lift action exceeds the exact group replay-work bound")
    return {
        "degree": group.degree,
        "elements": [_permutation_data(item) for item in group.elements],
        "fingerprint": group.fingerprint,
        "order": group.order,
        "type": "arbogast.finite_permutation_group",
    }


def _group_from_schema(value: object, name: str) -> PermutationGroup:
    raw = _strict_object(value, name)
    _exact_keys(raw, {"degree", "elements", "fingerprint", "order", "type"}, name)
    if raw["type"] != "arbogast.finite_permutation_group":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    if type(raw["degree"]) is not int or type(raw["order"]) is not int:
        raise PAdicVerificationError(f"{name} degree and order must be exact integers")
    degree = strict_int(raw["degree"], f"{name} degree", minimum=0)
    order = strict_int(raw["order"], f"{name} order", minimum=1)
    if degree > MAX_DIMENSION:
        raise PAdicResourceError(f"{name} exceeds the bounded permutation degree")
    if order > MAX_GROUP_ORDER:
        raise PAdicResourceError(f"{name} exceeds the bounded group order")
    raw_elements = _strict_array(raw["elements"], f"{name}.elements")
    if len(raw_elements) != order:
        raise PAdicVerificationError(f"{name} element list does not match its declared order")
    if order**2 * max(1, degree) > MAX_EXACT_REPLAY_WORK:
        raise PAdicResourceError(f"{name} exceeds the exact group replay-work bound")
    elements = tuple(
        _permutation_from_schema(item, f"{name}.elements[{index}]")
        for index, item in enumerate(raw_elements)
    )
    if any(element.degree != degree for element in elements):
        raise PAdicVerificationError(f"{name} contains a permutation of the wrong degree")

    # ``PermutationGroup`` performs an intentionally unbounded closure search.
    # Receipt data are hostile, so prove the supplied complete element table is
    # closed inside the portable envelope before invoking that constructor.
    identity = Permutation.identity(degree)
    moves = tuple(sorted({move for element in elements for move in (element, element.inverse())}))
    seen = {identity}
    queue: deque[Permutation] = deque((identity,))
    work = 0
    while queue:
        current = queue.popleft()
        for move in moves:
            work += max(1, degree)
            if work > MAX_EXACT_REPLAY_WORK:
                raise PAdicResourceError(f"{name} closure exceeds the exact replay-work bound")
            candidate = current * move
            if candidate in seen:
                continue
            if len(seen) >= order:
                raise PAdicVerificationError(
                    f"{name} declared element table is not closed at its claimed order"
                )
            seen.add(candidate)
            queue.append(candidate)
    if seen != set(elements):
        raise PAdicVerificationError(f"{name} is not the complete generated element table")
    try:
        result = PermutationGroup(elements, degree=degree)
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if raw != _group_data(result):
        raise PAdicVerificationError(f"{name} is not a complete concrete group transport")
    return result


def _receipt_result(certificate: VerificationCertificate, kind: str) -> object:
    witness = certificate.witness.to_dict()
    if set(witness) != {"padic_receipt"}:
        raise PAdicVerificationError("p-adic source evidence has a foreign witness")
    receipt = _strict_object(witness["padic_receipt"], "p-adic source receipt")
    if receipt.get("kind") != kind or receipt.get("closure") != "certified":
        raise PAdicVerificationError("p-adic source evidence has the wrong result kind")
    payload = _strict_object(receipt.get("payload"), "p-adic source receipt payload")
    _exact_keys(payload, {"result"}, "p-adic source receipt payload")
    return payload["result"]


def _require_source_evidence(
    evidence: tuple[VerificationCertificate, ...],
    certificate_id: str,
    kind: str,
    expected_result: object,
) -> None:
    match = next((item for item in evidence if item.certificate_id == certificate_id), None)
    if match is None:
        raise PAdicVerificationError(f"{kind} source certificate evidence is missing")
    if not strict_canonical_equal(_receipt_result(match, kind), expected_result):
        raise PAdicVerificationError(f"{kind} source evidence names another exact result")


@dataclass(frozen=True, slots=True, init=False)
class LiftChart(PAdicSchemaObject):
    """One finite affine chart over ``F_p`` with literal model coordinates."""

    datum: DeformationDatum
    equation_coefficients: FPPolynomial
    model_coordinate_polynomials: tuple[FPPolynomial, ...]
    coordinate_labels: tuple[str, ...]
    completeness_scope: str
    model_scope: str
    label: str | None

    schema_version = "arbogast.padic.lift-chart/v1"

    def __init__(
        self,
        datum: DeformationDatum,
        equation_coefficients: Sequence[int],
        model_coordinate_polynomials: Sequence[Sequence[int]],
        *,
        coordinate_labels: Sequence[str] | None = None,
        label: str | None = None,
    ) -> None:
        if not isinstance(datum, DeformationDatum):
            raise TypeError("lift chart needs a DeformationDatum")
        datum.verify()
        if isinstance(model_coordinate_polynomials, str | bytes):
            raise TypeError("model coordinates must be a sequence of polynomials")
        coordinate_count = len(model_coordinate_polynomials)
        if coordinate_count < 1:
            raise PAdicValidationError("lift chart needs at least one model coordinate")
        if coordinate_count > MAX_LOCAL_DEGREE:
            raise PAdicResourceError("lift chart exceeds the model-coordinate bound")
        if isinstance(coordinate_labels, str | bytes):
            raise TypeError("model coordinate labels must be a sequence of strings")
        if coordinate_labels is not None and len(coordinate_labels) != coordinate_count:
            raise PAdicValidationError("model coordinate labels must be complete")
        equation = _fp_polynomial(
            equation_coefficients,
            datum.prime,
            "lift-chart equation",
        )
        if len(equation) < 2 or equation[-1] != 1:
            raise PAdicValidationError("lift-chart equation must be nonconstant and monic")
        models = tuple(
            _fp_polynomial(values, datum.prime, f"model coordinate[{index}]")
            for index, values in enumerate(model_coordinate_polynomials)
        )
        if coordinate_labels is None:
            labels = tuple(f"coordinate.{index}" for index in range(len(models)))
        else:
            labels = tuple(
                canonical_label(value, f"model coordinate label[{index}]")
                for index, value in enumerate(coordinate_labels)
            )
        if len(labels) != len(models) or len(set(labels)) != len(labels):
            raise PAdicValidationError("model coordinate labels must be complete and unique")
        root_work = datum.prime * len(equation)
        candidate_bound = min(datum.prime, len(equation) - 1)
        model_work = candidate_bound * sum(len(polynomial) for polynomial in models)
        if root_work + model_work > MAX_EXACT_REPLAY_WORK:
            raise PAdicResourceError("lift chart exceeds the exact evaluation-work bound")
        object.__setattr__(self, "datum", datum)
        object.__setattr__(self, "equation_coefficients", equation)
        object.__setattr__(self, "model_coordinate_polynomials", models)
        object.__setattr__(self, "coordinate_labels", labels)
        object.__setattr__(self, "completeness_scope", _CHART_SCOPE)
        object.__setattr__(self, "model_scope", _MODEL_SCOPE)
        object.__setattr__(
            self,
            "label",
            None if label is None else canonical_label(label, "lift-chart label"),
        )

    @property
    def prime(self) -> int:
        return self.datum.prime

    def roots(self) -> tuple[int, ...]:
        if self.prime > MAX_EXACT_REPLAY_WORK:
            raise PAdicResourceError("lift-chart exhaustion exceeds the replay-work bound")
        result = tuple(
            parameter
            for parameter in range(self.prime)
            if _evaluate(self.equation_coefficients, parameter, self.prime) == 0
        )
        if len(result) > MAX_LIFTS:
            raise PAdicResourceError("lift chart exceeds the portable lift-count bound")
        return result

    def model_at(self, parameter: int) -> tuple[int, ...]:
        exact_parameter = strict_int(parameter, "lift parameter", minimum=0)
        if exact_parameter >= self.prime:
            raise PAdicValidationError("lift parameter must be canonical modulo the chart prime")
        return tuple(
            _evaluate(polynomial, exact_parameter, self.prime)
            for polynomial in self.model_coordinate_polynomials
        )

    def verify(self) -> bool:
        if not isinstance(self.datum, DeformationDatum):
            raise PAdicVerificationError("lift-chart datum has the wrong type")
        try:
            replay = LiftChart(
                self.datum,
                self.equation_coefficients,
                self.model_coordinate_polynomials,
                coordinate_labels=self.coordinate_labels,
                label=self.label,
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("lift-chart normalization or scope was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "completeness_scope": self.completeness_scope,
            "coordinate_labels": list(self.coordinate_labels),
            "datum": self.datum.to_schema_document(),
            "equation_coefficients": list(self.equation_coefficients),
            "label": self.label,
            "model_coordinate_polynomials": [
                list(item) for item in self.model_coordinate_polynomials
            ],
            "model_scope": self.model_scope,
            "type": "arbogast.padic.lift_chart",
        }


@dataclass(frozen=True, slots=True, init=False)
class LiftCandidate(PAdicSchemaObject):
    """One root of a pinned chart and its exactly evaluated labeled model."""

    chart: LiftChart
    parameter: int
    model_coefficients: tuple[int, ...]
    isomorphism_key: str

    schema_version = "arbogast.padic.lift-candidate/v1"

    def __init__(self, chart: LiftChart, parameter: int) -> None:
        if not isinstance(chart, LiftChart):
            raise TypeError("lift candidate needs a LiftChart")
        chart.verify()
        exact_parameter = strict_int(parameter, "lift parameter", minimum=0)
        if exact_parameter >= chart.prime:
            raise PAdicValidationError("lift parameter must be canonical modulo the chart prime")
        if _evaluate(chart.equation_coefficients, exact_parameter, chart.prime) != 0:
            raise PAdicValidationError("lift parameter is not a root of the pinned chart")
        model = chart.model_at(exact_parameter)
        key = content_address(
            {
                "coordinate_labels": list(chart.coordinate_labels),
                "model_coefficients": list(model),
                "model_scope": chart.model_scope,
            }
        )
        object.__setattr__(self, "chart", chart)
        object.__setattr__(self, "parameter", exact_parameter)
        object.__setattr__(self, "model_coefficients", model)
        object.__setattr__(self, "isomorphism_key", key)

    def verify(self) -> bool:
        if not isinstance(self.chart, LiftChart):
            raise PAdicVerificationError("lift candidate chart has the wrong type")
        try:
            replay = LiftCandidate(self.chart, self.parameter)
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("lift candidate evaluation or class key was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "chart_id": self.chart.content_id,
            "coordinate_labels": list(self.chart.coordinate_labels),
            "isomorphism_key": self.isomorphism_key,
            "model_coefficients": list(self.model_coefficients),
            "model_scope": self.chart.model_scope,
            "parameter": self.parameter,
            "type": "arbogast.padic.lift_candidate",
        }


@dataclass(frozen=True, slots=True, init=False)
class LiftEnumerationWitness(PAdicSchemaObject):
    """Exact root exhaustion for one finite chart."""

    chart: LiftChart
    candidates: tuple[LiftCandidate, ...]
    exhausted_parameters: tuple[int, ...]
    completeness_scope: str

    schema_version = "arbogast.padic.lift-enumeration-witness/v1"

    def __init__(self, chart: LiftChart, candidates: Sequence[LiftCandidate]) -> None:
        if not isinstance(chart, LiftChart):
            raise TypeError("lift enumeration needs a LiftChart")
        chart.verify()
        if len(candidates) > MAX_LIFTS:
            raise PAdicResourceError("lift enumeration exceeds the portable lift-count bound")
        if len(candidates) > min(chart.prime, len(chart.equation_coefficients) - 1):
            raise PAdicValidationError("lift enumeration exceeds the chart polynomial root bound")
        normalized = tuple(sorted(candidates, key=lambda item: item.parameter))
        if any(not isinstance(item, LiftCandidate) or item.chart != chart for item in normalized):
            raise PAdicValidationError("lift enumeration contains a foreign candidate")
        parameters = tuple(item.parameter for item in normalized)
        if len(set(parameters)) != len(parameters):
            raise PAdicValidationError("lift enumeration repeats a chart parameter")
        exact_roots = chart.roots()
        if parameters != exact_roots:
            raise PAdicValidationError(
                "lift enumeration does not exhaust exactly the roots of the pinned chart"
            )
        object.__setattr__(self, "chart", chart)
        object.__setattr__(self, "candidates", normalized)
        object.__setattr__(self, "exhausted_parameters", exact_roots)
        object.__setattr__(self, "completeness_scope", _CHART_SCOPE)

    def verify(self) -> bool:
        if not isinstance(self.chart, LiftChart):
            raise PAdicVerificationError("lift enumeration chart has the wrong type")
        try:
            replay = LiftEnumerationWitness(self.chart, self.candidates)
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("lift enumeration exhaustion was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "candidates": [item.to_schema_document() for item in self.candidates],
            "chart_id": self.chart.content_id,
            "completeness_scope": self.completeness_scope,
            "exhausted_parameters": list(self.exhausted_parameters),
            "type": "arbogast.padic.lift_enumeration_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class LiftSet(PAdicSchemaObject):
    """All roots of one chart, deduplicated only by literal labeled models."""

    datum: DeformationDatum
    chart: LiftChart
    witness: LiftEnumerationWitness
    candidates: tuple[LiftCandidate, ...]
    representatives: tuple[LiftCandidate, ...]
    class_indices: tuple[int, ...]
    source_datum_certificate_id: str | None
    completeness_scope: str
    deduplication_scope: str

    schema_version = "arbogast.padic.lift-set/v1"

    def __init__(
        self,
        datum: DeformationDatum,
        chart: LiftChart,
        witness: LiftEnumerationWitness,
        *,
        source_datum_certificate_id: str | None = None,
    ) -> None:
        if not isinstance(datum, DeformationDatum):
            raise TypeError("lift set needs a DeformationDatum")
        if not isinstance(chart, LiftChart) or chart.datum != datum:
            raise PAdicValidationError("lift chart is bound to another deformation datum")
        if not isinstance(witness, LiftEnumerationWitness) or witness.chart != chart:
            raise PAdicValidationError("lift enumeration witness is bound to another chart")
        datum.verify()
        chart.verify()
        witness.verify()
        if source_datum_certificate_id is not None:
            canonical_label(source_datum_certificate_id, "source datum certificate ID")
        by_key: dict[str, LiftCandidate] = {}
        for candidate in witness.candidates:
            by_key.setdefault(candidate.isomorphism_key, candidate)
        representatives = tuple(
            sorted(by_key.values(), key=lambda item: (item.isomorphism_key, item.parameter))
        )
        index_by_key = {
            candidate.isomorphism_key: index for index, candidate in enumerate(representatives)
        }
        class_indices = tuple(
            index_by_key[candidate.isomorphism_key] for candidate in witness.candidates
        )
        object.__setattr__(self, "datum", datum)
        object.__setattr__(self, "chart", chart)
        object.__setattr__(self, "witness", witness)
        object.__setattr__(self, "candidates", witness.candidates)
        object.__setattr__(self, "representatives", representatives)
        object.__setattr__(self, "class_indices", class_indices)
        object.__setattr__(self, "source_datum_certificate_id", source_datum_certificate_id)
        object.__setattr__(self, "completeness_scope", _CHART_SCOPE)
        object.__setattr__(self, "deduplication_scope", "literal-labeled-model-equality")

    @property
    def lifts(self) -> tuple[LiftCandidate, ...]:
        return self.representatives

    @property
    def size(self) -> int:
        return len(self.representatives)

    def verify(self) -> bool:
        try:
            replay = LiftSet(
                self.datum,
                self.chart,
                self.witness,
                source_datum_certificate_id=self.source_datum_certificate_id,
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("lift-set exhaustion, deduplication, or scope changed")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "candidates": [item.to_schema_document() for item in self.candidates],
            "chart": self.chart.to_schema_document(),
            "class_indices": list(self.class_indices),
            "completeness_scope": self.completeness_scope,
            "datum_id": self.datum.content_id,
            "deduplication_scope": self.deduplication_scope,
            "representatives": [item.to_schema_document() for item in self.representatives],
            "source_datum_certificate_id": self.source_datum_certificate_id,
            "type": "arbogast.padic.lift_set",
            "witness": self.witness.to_schema_document(),
        }


@dataclass(frozen=True, slots=True, init=False)
class LiftTransportWitness(PAdicSchemaObject):
    """One finite-set bijection, optionally with exact pinned-model transports.

    Transport labels are identifiers only.  Arithmetic promotion consumes the
    coordinate permutations and independently checks their action on every
    displayed model; an arbitrary set permutation remains non-arithmetic.
    """

    lifts: LiftSet
    group_element: Permutation
    lift_permutation: Permutation
    transport_labels: tuple[str, ...]
    model_coordinate_permutations: tuple[Permutation, ...]
    model_transport_verified: bool
    arithmetic_compatible: bool
    transport_scope: str

    schema_version = "arbogast.padic.lift-transport-witness/v1"

    def __init__(
        self,
        lifts: LiftSet,
        group_element: Permutation,
        lift_permutation: Permutation,
        *,
        transport_labels: Sequence[str] | None = None,
        model_coordinate_permutations: Sequence[Permutation] | None = None,
    ) -> None:
        if not isinstance(lifts, LiftSet):
            raise TypeError("lift transport needs a LiftSet")
        if not isinstance(group_element, Permutation):
            raise TypeError("lift transport group element must be a Permutation")
        if not isinstance(lift_permutation, Permutation):
            raise TypeError("lift transport bijection must be a Permutation")
        lifts.verify()
        if lift_permutation.degree != lifts.size:
            raise PAdicValidationError("lift transport has the wrong finite-set degree")
        if transport_labels is None:
            labels = tuple(
                f"transport.{source}.{lift_permutation(source)}" for source in range(lifts.size)
            )
        else:
            if len(transport_labels) != lifts.size:
                raise PAdicValidationError("lift transport labels must be complete")
            labels = tuple(
                canonical_label(item, f"transport label[{index}]")
                for index, item in enumerate(transport_labels)
            )
        if len(labels) != lifts.size or len(set(labels)) != len(labels):
            raise PAdicValidationError("lift transport labels must be complete and unique")
        if (
            model_coordinate_permutations is not None
            and len(model_coordinate_permutations) != lifts.size
        ):
            raise PAdicValidationError(
                "exact model transport needs one coordinate map per lift class"
            )
        model_maps = (
            () if model_coordinate_permutations is None else tuple(model_coordinate_permutations)
        )
        model_verified = model_coordinate_permutations is not None
        if model_verified:
            labels_by_coordinate = lifts.chart.coordinate_labels
            for source, coordinate_map in enumerate(model_maps):
                if not isinstance(coordinate_map, Permutation):
                    raise TypeError("model coordinate transports must be Permutation objects")
                if coordinate_map.degree != len(labels_by_coordinate):
                    raise PAdicValidationError(
                        "model coordinate transport has the wrong coordinate degree"
                    )
                if any(
                    labels_by_coordinate[coordinate_map(index)] != label
                    for index, label in enumerate(labels_by_coordinate)
                ):
                    raise PAdicValidationError(
                        "model coordinate transport does not preserve exact coordinate labels"
                    )
                source_model = lifts.representatives[source].model_coefficients
                target_model = lifts.representatives[lift_permutation(source)].model_coefficients
                transported = [0] * len(source_model)
                for coordinate, image in enumerate(coordinate_map.images):
                    transported[image] = source_model[coordinate]
                if tuple(transported) != target_model:
                    raise PAdicValidationError(
                        "model coordinate transport does not carry source to target"
                    )
        arithmetic_compatible = (
            model_verified
            and lift_permutation.is_identity
            and all(item.is_identity for item in model_maps)
        )
        object.__setattr__(self, "lifts", lifts)
        object.__setattr__(self, "group_element", group_element)
        object.__setattr__(self, "lift_permutation", lift_permutation)
        object.__setattr__(self, "transport_labels", labels)
        object.__setattr__(self, "model_coordinate_permutations", model_maps)
        object.__setattr__(self, "model_transport_verified", model_verified)
        object.__setattr__(self, "arithmetic_compatible", arithmetic_compatible)
        object.__setattr__(self, "transport_scope", _FINITE_ACTION_SCOPE)

    def verify(self) -> bool:
        if (
            type(self.model_transport_verified) is not bool
            or type(self.arithmetic_compatible) is not bool
        ):
            raise PAdicVerificationError("lift transport proof flags must be booleans")
        try:
            replay = LiftTransportWitness(
                self.lifts,
                self.group_element,
                self.lift_permutation,
                transport_labels=self.transport_labels,
                model_coordinate_permutations=(
                    self.model_coordinate_permutations if self.model_transport_verified else None
                ),
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("lift transport bijection or scope was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "group_element": _permutation_data(self.group_element),
                "arithmetic_compatible": self.arithmetic_compatible,
                "lift_permutation": _permutation_data(self.lift_permutation),
                "lift_set_id": self.lifts.content_id,
                "model_coordinate_permutations": [
                    _permutation_data(item) for item in self.model_coordinate_permutations
                ],
                "model_transport_verified": self.model_transport_verified,
                "transport_labels": list(self.transport_labels),
                "transport_scope": self.transport_scope,
                "type": "arbogast.padic.lift_transport_witness",
            },
        )


@dataclass(frozen=True, slots=True, init=False)
class FiniteLiftAction(PAdicSchemaObject):
    """An exact group homomorphism into permutations of a finite lift set."""

    lifts: LiftSet
    group: PermutationGroup
    witnesses: tuple[LiftTransportWitness, ...]
    action_scope: str
    arithmetic_galois_action: bool

    schema_version = "arbogast.padic.finite-lift-action/v1"

    def __init__(
        self,
        lifts: LiftSet,
        group: PermutationGroup,
        witnesses: Sequence[LiftTransportWitness],
    ) -> None:
        if not isinstance(lifts, LiftSet):
            raise TypeError("finite lift action needs a LiftSet")
        if not isinstance(group, PermutationGroup):
            raise TypeError("finite lift action needs a PermutationGroup")
        lifts.verify()
        _group_data(group)
        if len(witnesses) != group.order:
            raise PAdicValidationError(
                "finite lift action needs exactly one transport for every group element"
            )
        normalized = tuple(sorted(witnesses, key=lambda item: item.group_element.images))
        if any(
            not isinstance(item, LiftTransportWitness) or item.lifts != lifts for item in normalized
        ):
            raise PAdicValidationError("finite lift action contains a foreign transport")
        if tuple(item.group_element for item in normalized) != group.elements:
            raise PAdicValidationError(
                "finite lift action needs exactly one transport for every group element"
            )
        action = {item.group_element: item.lift_permutation for item in normalized}
        if action[group.identity] != Permutation.identity(lifts.size):
            raise PAdicValidationError("finite lift action does not send identity to identity")
        work = group.order * group.order * max(1, lifts.size)
        if work > MAX_EXACT_REPLAY_WORK:
            raise PAdicResourceError("finite lift action law exceeds the replay-work bound")
        for left in group.elements:
            for right in group.elements:
                if action[group.multiply(left, right)] != action[left] * action[right]:
                    raise PAdicValidationError("lift transports do not satisfy the group law")
        object.__setattr__(self, "lifts", lifts)
        object.__setattr__(self, "group", group)
        object.__setattr__(self, "witnesses", normalized)
        object.__setattr__(self, "action_scope", _FINITE_ACTION_SCOPE)
        object.__setattr__(self, "arithmetic_galois_action", False)

    def permutation_for(self, element: Permutation) -> Permutation:
        if element not in self.group:
            raise PAdicValidationError("requested element is outside the finite action group")
        return next(
            item.lift_permutation for item in self.witnesses if item.group_element == element
        )

    def verify(self) -> bool:
        if type(self.arithmetic_galois_action) is not bool or self.arithmetic_galois_action:
            raise PAdicVerificationError("finite set action was relabeled arithmetic")
        try:
            replay = FiniteLiftAction(self.lifts, self.group, self.witnesses)
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("finite lift action or arithmetic boundary was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action_scope": self.action_scope,
            "arithmetic_galois_action": self.arithmetic_galois_action,
            "group": cast(CanonicalJSON, _group_data(self.group)),
            "lifts": self.lifts.to_schema_document(),
            "type": "arbogast.padic.finite_lift_action",
            "witnesses": [item.to_schema_document() for item in self.witnesses],
        }


@dataclass(frozen=True, slots=True, init=False)
class LiftGaloisAction(PAdicSchemaObject):
    """A finite lift action bound to a complete arithmetic Galois quotient."""

    finite_action: FiniteLiftAction
    quotient_id: str
    quotient_snapshot: dict[str, CanonicalJSON]
    lift_set_certificate_id: str
    quotient_presentation_certificate_id: str
    quotient_proving_certificate_id: str
    action_scope: str
    coefficient_action_rule: str
    characteristic_zero_lift_action_claimed: bool
    geometric_lift_action_claimed: bool
    arithmetic_galois_action: bool

    schema_version = "arbogast.padic.lift-galois-action/v1"

    def __init__(
        self,
        finite_action: FiniteLiftAction,
        quotient: FiniteGaloisQuotient,
        *,
        lift_set_certificate_id: str,
    ) -> None:
        if not isinstance(finite_action, FiniteLiftAction):
            raise TypeError("Galois lift action needs a FiniteLiftAction")
        if not isinstance(quotient, FiniteGaloisQuotient):
            raise TypeError("Galois lift action needs a FiniteGaloisQuotient")
        finite_action.verify()
        if not quotient.proof_context.complete or quotient.proving_certificate is None:
            raise PAdicValidationError("arithmetic lift action needs a complete Galois quotient")
        if quotient.verify() is not True:
            raise PAdicVerificationError("finite Galois quotient verification returned false")
        if quotient.group != finite_action.group:
            raise PAdicValidationError("finite action group differs from the Galois quotient")
        if quotient.order != 1 or any(
            not item.arithmetic_compatible for item in finite_action.witnesses
        ):
            raise PAdicValidationError(
                "the 0.5 arithmetic slice requires the trivial quotient and exact identity "
                "transport on every pinned model"
            )
        source_id = canonical_label(lift_set_certificate_id, "lift-set certificate ID")
        snapshot = strict_canonical_mapping(quotient.to_dict(), "Galois quotient snapshot")
        presentation_certificate = quotient.certificate
        proving_certificate = quotient.proving_certificate
        object.__setattr__(self, "finite_action", finite_action)
        object.__setattr__(self, "quotient_id", quotient.quotient_id)
        object.__setattr__(self, "quotient_snapshot", snapshot)
        object.__setattr__(self, "lift_set_certificate_id", source_id)
        object.__setattr__(
            self,
            "quotient_presentation_certificate_id",
            presentation_certificate.certificate_id,
        )
        object.__setattr__(
            self,
            "quotient_proving_certificate_id",
            proving_certificate.certificate_id,
        )
        object.__setattr__(self, "action_scope", _ARITHMETIC_ACTION_SCOPE)
        object.__setattr__(self, "coefficient_action_rule", _COEFFICIENT_ACTION_RULE)
        object.__setattr__(self, "characteristic_zero_lift_action_claimed", False)
        object.__setattr__(self, "geometric_lift_action_claimed", False)
        object.__setattr__(self, "arithmetic_galois_action", True)

    @property
    def lifts(self) -> LiftSet:
        return self.finite_action.lifts

    @property
    def group(self) -> PermutationGroup:
        return self.finite_action.group

    @property
    def witnesses(self) -> tuple[LiftTransportWitness, ...]:
        return self.finite_action.witnesses

    def permutation_for(self, element: Permutation) -> Permutation:
        return self.finite_action.permutation_for(element)

    def verify(self) -> bool:
        if not isinstance(self.finite_action, FiniteLiftAction):
            raise PAdicVerificationError("arithmetic lift action has the wrong finite action")
        self.finite_action.verify()
        for value, name in (
            (self.quotient_id, "Galois quotient ID"),
            (self.lift_set_certificate_id, "lift-set certificate ID"),
            (
                self.quotient_presentation_certificate_id,
                "quotient presentation certificate ID",
            ),
            (self.quotient_proving_certificate_id, "quotient proving certificate ID"),
        ):
            canonical_label(value, name)
        snapshot = strict_canonical_mapping(
            self.quotient_snapshot,
            "Galois quotient snapshot",
        )
        if content_address(snapshot) != self.quotient_id:
            raise PAdicVerificationError("Galois quotient snapshot is not content-bound")
        if snapshot.get("group") != _group_data(self.group):
            raise PAdicVerificationError("Galois quotient group differs from the finite action")
        if self.group.order != 1 or any(not item.arithmetic_compatible for item in self.witnesses):
            raise PAdicVerificationError(
                "arithmetic lift action contains an unproved or nonidentity model transport"
            )
        context = _strict_object(snapshot.get("proof_context"), "Galois quotient proof context")
        if context.get("completeness") != "complete":
            raise PAdicVerificationError("arithmetic action lost complete quotient evidence")
        presentation = _strict_object(
            snapshot.get("presentation"),
            "Galois quotient presentation",
        )
        if (
            presentation.get("arithmetic_action") != "trivial"
            or presentation.get("method") != "portable-trivial-quotient-v1"
        ):
            raise PAdicVerificationError(
                "arithmetic action lacks the pinned trivial coefficient-action rule"
            )
        if (
            self.action_scope != _ARITHMETIC_ACTION_SCOPE
            or type(self.arithmetic_galois_action) is not bool
            or not self.arithmetic_galois_action
        ):
            raise PAdicVerificationError("arithmetic lift-action scope was altered")
        if (
            self.coefficient_action_rule != _COEFFICIENT_ACTION_RULE
            or type(self.characteristic_zero_lift_action_claimed) is not bool
            or type(self.geometric_lift_action_claimed) is not bool
            or self.characteristic_zero_lift_action_claimed
            or self.geometric_lift_action_claimed
        ):
            raise PAdicVerificationError(
                "prime-field model-action boundary was altered or overclaimed"
            )
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action_scope": self.action_scope,
            "arithmetic_galois_action": self.arithmetic_galois_action,
            "characteristic_zero_lift_action_claimed": (
                self.characteristic_zero_lift_action_claimed
            ),
            "coefficient_action_rule": self.coefficient_action_rule,
            "finite_action": self.finite_action.to_schema_document(),
            "geometric_lift_action_claimed": self.geometric_lift_action_claimed,
            "lift_set_certificate_id": self.lift_set_certificate_id,
            "quotient_id": self.quotient_id,
            "quotient_presentation_certificate_id": (self.quotient_presentation_certificate_id),
            "quotient_proving_certificate_id": self.quotient_proving_certificate_id,
            "quotient_snapshot": self.quotient_snapshot,
            "type": "arbogast.padic.lift_galois_action",
        }


@dataclass(frozen=True, slots=True, init=False)
class FixedLift(PAdicSchemaObject):
    """One lift class fixed by an action; this is not a descent conclusion."""

    action: ExactLiftAction
    lift_index: int
    candidate: LiftCandidate
    conclusion_scope: str
    descent_claimed: bool

    schema_version = "arbogast.padic.fixed-lift/v1"

    def __init__(self, action: ExactLiftAction, lift_index: int) -> None:
        if not isinstance(action, (FiniteLiftAction, LiftGaloisAction)):
            raise TypeError("fixed lift needs a finite or arithmetic lift action")
        action.verify()
        index = strict_int(lift_index, "fixed lift index", minimum=0)
        if index >= action.lifts.size:
            raise PAdicValidationError("fixed lift index lies outside the lift set")
        if any(item.lift_permutation(index) != index for item in action.witnesses):
            raise PAdicValidationError("selected lift class is not fixed by the action")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "lift_index", index)
        object.__setattr__(self, "candidate", action.lifts.representatives[index])
        object.__setattr__(self, "conclusion_scope", "fixed-class-under-exact-finite-action")
        object.__setattr__(self, "descent_claimed", False)

    def verify(self) -> bool:
        if type(self.descent_claimed) is not bool or self.descent_claimed:
            raise PAdicVerificationError("a fixed lift was relabeled as descended")
        try:
            replay = FixedLift(self.action, self.lift_index)
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("fixed lift or no-descent boundary was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action_id": self.action.content_id,
            "candidate": self.candidate.to_schema_document(),
            "conclusion_scope": self.conclusion_scope,
            "descent_claimed": self.descent_claimed,
            "lift_index": self.lift_index,
            "type": "arbogast.padic.fixed_lift",
        }


@dataclass(frozen=True, slots=True, init=False)
class FixedLiftSet(PAdicSchemaObject):
    """The exhaustive fixed subset of one exact finite action."""

    action: ExactLiftAction
    fixed: tuple[FixedLift, ...]
    source_action_certificate_id: str | None
    completeness_scope: str
    descent_claimed: bool

    schema_version = "arbogast.padic.fixed-lift-set/v1"

    def __init__(
        self,
        action: ExactLiftAction,
        *,
        source_action_certificate_id: str | None = None,
    ) -> None:
        if not isinstance(action, (FiniteLiftAction, LiftGaloisAction)):
            raise TypeError("fixed lift set needs a finite or arithmetic lift action")
        action.verify()
        if source_action_certificate_id is not None:
            canonical_label(source_action_certificate_id, "source action certificate ID")
        indices = tuple(
            index
            for index in range(action.lifts.size)
            if all(item.lift_permutation(index) == index for item in action.witnesses)
        )
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "fixed", tuple(FixedLift(action, index) for index in indices))
        object.__setattr__(self, "source_action_certificate_id", source_action_certificate_id)
        object.__setattr__(self, "completeness_scope", "exhaustive-fixed-subset")
        object.__setattr__(self, "descent_claimed", False)

    def verify(self) -> bool:
        if type(self.descent_claimed) is not bool or self.descent_claimed:
            raise PAdicVerificationError("a fixed lift set was relabeled as descended")
        try:
            replay = FixedLiftSet(
                self.action,
                source_action_certificate_id=self.source_action_certificate_id,
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if replay != self:
            raise PAdicVerificationError("fixed subset or no-descent boundary was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action": self.action.to_schema_document(),
            "action_kind": (
                "arithmetic-galois" if isinstance(self.action, LiftGaloisAction) else "finite-set"
            ),
            "completeness_scope": self.completeness_scope,
            "descent_claimed": self.descent_claimed,
            "fixed": [item.to_schema_document() for item in self.fixed],
            "source_action_certificate_id": self.source_action_certificate_id,
            "type": "arbogast.padic.fixed_lift_set",
        }


def _datum_and_certificate(
    datum: DeformationDatum | Certified[DeformationDatum],
) -> tuple[DeformationDatum, VerificationCertificate | None]:
    if isinstance(datum, Certified):
        if not isinstance(datum.value, DeformationDatum):
            raise TypeError("lift_set needs a DeformationDatum result")
        datum.verify()
        return datum.value, datum.certificate
    if not isinstance(datum, DeformationDatum):
        raise TypeError("lift_set needs a DeformationDatum")
    datum.verify()
    return datum, None


def lift_set(
    datum: DeformationDatum | Certified[DeformationDatum],
    *,
    chart: LiftChart | None = None,
    witness: LiftEnumerationWitness | None = None,
) -> PAdicResult[LiftSet]:
    """Enumerate exactly one supplied chart; never claim global Wewers exhaustion."""

    exact_datum, datum_certificate = _datum_and_certificate(datum)
    requested: dict[str, object] = {"datum_id": exact_datum.content_id}
    if chart is None or witness is None:
        requested.update(
            {
                "chart_id": None if chart is None else chart.content_id,
                "witness_id": None if witness is None else witness.content_id,
            }
        )
        return unknown_result(
            "padic.lift_set",
            "missing-pinned-chart-exhaustion",
            "lift completeness needs both a finite chart and its exact root exhaustion",
            requested=requested,
            family="three-point",
        )
    if chart.datum != exact_datum:
        raise PAdicValidationError("lift chart is bound to another deformation datum")
    if witness.chart != chart:
        raise PAdicValidationError("lift witness is bound to another chart")
    if chart.prime > MAX_EXACT_REPLAY_WORK:
        return unsupported_result(
            "padic.lift_set",
            "chart-exhaustion-resource-bound",
            "the finite field is too large for portable exhaustive chart replay",
            requested={**requested, "chart_id": chart.content_id},
            supported=("finite pinned charts within the exact replay-work bound",),
            family="three-point",
        )
    result = LiftSet(
        exact_datum,
        chart,
        witness,
        source_datum_certificate_id=(
            None if datum_certificate is None else datum_certificate.certificate_id
        ),
    )
    evidence = () if datum_certificate is None else (datum_certificate,)
    return certified_result(result, "lift-set", evidence=evidence)


def lift_galois_action(
    lifts: Certified[LiftSet],
    quotient: FiniteGaloisQuotient,
    *,
    witnesses: Sequence[LiftTransportWitness],
) -> PAdicResult[LiftGaloisAction]:
    """Promote a finite action only across a complete arithmetic quotient."""

    if not isinstance(lifts, Certified) or not isinstance(lifts.value, LiftSet):
        raise TypeError("lift_galois_action needs a Certified[LiftSet]")
    if not isinstance(quotient, FiniteGaloisQuotient):
        raise TypeError("quotient must be a FiniteGaloisQuotient")
    lifts.verify()
    if not quotient.proof_context.complete or quotient.proving_certificate is None:
        return unknown_result(
            "padic.lift_galois_action",
            "incomplete-arithmetic-quotient",
            "a finite set action is not an arithmetic Galois action without quotient evidence",
            requested={
                "lift_set_id": lifts.value.content_id,
                "quotient_id": quotient.quotient_id,
            },
            family="three-point",
        )
    if quotient.order != 1:
        return unsupported_result(
            "padic.lift_galois_action",
            "nontrivial-quotient-outside-pinned-model-action",
            "version 0.5 has no exact nontrivial quotient action on the chart models",
            requested={
                "lift_set_id": lifts.value.content_id,
                "quotient_id": quotient.quotient_id,
            },
            supported=("complete trivial quotient acting identically on pinned F_p models",),
            family="three-point",
        )
    finite_action = FiniteLiftAction(lifts.value, quotient.group, witnesses)
    if any(not item.arithmetic_compatible for item in finite_action.witnesses):
        return unknown_result(
            "padic.lift_galois_action",
            "unverified-arithmetic-model-transport",
            "declared set permutations do not prove the quotient action on exact models",
            requested={
                "lift_set_id": lifts.value.content_id,
                "quotient_id": quotient.quotient_id,
                "transport_witness_ids": [item.content_id for item in finite_action.witnesses],
            },
            family="three-point",
        )
    result = LiftGaloisAction(
        finite_action,
        quotient,
        lift_set_certificate_id=lifts.certificate.certificate_id,
    )
    proving = quotient.proving_certificate
    assert proving is not None
    evidence = (lifts.certificate, quotient.certificate, proving)
    return certified_result(result, "lift-action", evidence=evidence)


def fixed_lifts(
    action: FiniteLiftAction | Certified[LiftGaloisAction],
) -> Certified[FixedLiftSet]:
    """Return the exact fixed classes, with no effective-descent conclusion."""

    if isinstance(action, Certified):
        if not isinstance(action.value, LiftGaloisAction):
            raise TypeError("fixed_lifts certified input must contain a LiftGaloisAction")
        action.verify()
        certificate = action.certificate
        result = FixedLiftSet(
            action.value,
            source_action_certificate_id=certificate.certificate_id,
        )
        return certified_result(result, "fixed-lift-set", evidence=(certificate,))
    if not isinstance(action, FiniteLiftAction):
        raise TypeError("fixed_lifts needs a FiniteLiftAction or certified Galois action")
    result = FixedLiftSet(action)
    return certified_result(result, "fixed-lift-set")


def _chart_from_schema(value: object) -> LiftChart:
    raw = _strict_object(value, "lift chart")
    _exact_keys(
        raw,
        {
            "schema",
            "completeness_scope",
            "coordinate_labels",
            "datum",
            "equation_coefficients",
            "label",
            "model_coordinate_polynomials",
            "model_scope",
            "type",
        },
        "lift chart",
    )
    equation = _strict_array(raw["equation_coefficients"], "lift-chart equation")
    labels = _strict_array(raw["coordinate_labels"], "model coordinate labels")
    polynomials = _strict_array(
        raw["model_coordinate_polynomials"],
        "model coordinate polynomials",
    )
    if not 1 <= len(polynomials) <= MAX_LOCAL_DEGREE:
        raise PAdicResourceError("lift chart exceeds the model-coordinate bound")
    if len(equation) > MAX_LOCAL_DEGREE + 1:
        raise PAdicResourceError("lift-chart equation exceeds the bounded degree")
    if len(labels) != len(polynomials):
        raise PAdicVerificationError("model coordinate labels are not complete")
    if any(type(item) is not int for item in equation):
        raise PAdicVerificationError("lift-chart equation must contain integers")
    if any(type(item) is not str for item in labels):
        raise PAdicVerificationError("model coordinate labels must contain strings")
    decoded_polynomials: list[list[int]] = []
    for index, item in enumerate(polynomials):
        polynomial = _strict_array(item, f"model coordinate polynomial[{index}]")
        if len(polynomial) > MAX_LOCAL_DEGREE + 1:
            raise PAdicResourceError(
                f"model coordinate polynomial[{index}] exceeds the bounded degree"
            )
        if any(type(coefficient) is not int for coefficient in polynomial):
            raise PAdicVerificationError("model coordinate polynomial must contain integers")
        decoded_polynomials.append(cast(list[int], polynomial))
    if raw["label"] is not None and type(raw["label"]) is not str:
        raise PAdicVerificationError("lift-chart label must be a string or null")
    result = LiftChart(
        deformation_datum_from_schema(raw["datum"]),
        cast(list[int], equation),
        decoded_polynomials,
        coordinate_labels=cast(list[str], labels),
        label=raw["label"],
    )
    if raw != result.to_schema_document():
        raise PAdicVerificationError("lift chart transport was altered")
    return result


def _candidate_from_schema(value: object, chart: LiftChart) -> LiftCandidate:
    raw = _strict_object(value, "lift candidate")
    _exact_keys(
        raw,
        {
            "schema",
            "chart_id",
            "coordinate_labels",
            "isomorphism_key",
            "model_coefficients",
            "model_scope",
            "parameter",
            "type",
        },
        "lift candidate",
    )
    if type(raw["parameter"]) is not int:
        raise PAdicVerificationError("lift candidate parameter must be an integer")
    result = LiftCandidate(chart, raw["parameter"])
    if raw != result.to_schema_document():
        raise PAdicVerificationError("lift candidate transport was altered")
    return result


def _enumeration_from_schema(value: object, chart: LiftChart) -> LiftEnumerationWitness:
    raw = _strict_object(value, "lift enumeration witness")
    _exact_keys(
        raw,
        {
            "schema",
            "candidates",
            "chart_id",
            "completeness_scope",
            "exhausted_parameters",
            "type",
        },
        "lift enumeration witness",
    )
    raw_candidates = _strict_array(raw["candidates"], "lift enumeration candidates")
    if len(raw_candidates) > MAX_LIFTS:
        raise PAdicResourceError("lift enumeration exceeds the portable lift-count bound")
    if len(raw_candidates) > min(chart.prime, len(chart.equation_coefficients) - 1):
        raise PAdicVerificationError("lift enumeration exceeds the chart polynomial root bound")
    candidates = tuple(_candidate_from_schema(item, chart) for item in raw_candidates)
    result = LiftEnumerationWitness(chart, candidates)
    if raw != result.to_schema_document():
        raise PAdicVerificationError("lift enumeration transport was altered")
    return result


def lift_set_from_schema(value: object) -> LiftSet:
    raw = _strict_object(value, "lift set")
    _exact_keys(
        raw,
        {
            "schema",
            "candidates",
            "chart",
            "class_indices",
            "completeness_scope",
            "datum_id",
            "deduplication_scope",
            "representatives",
            "source_datum_certificate_id",
            "type",
            "witness",
        },
        "lift set",
    )
    chart = _chart_from_schema(raw["chart"])
    witness = _enumeration_from_schema(raw["witness"], chart)
    source_id = raw["source_datum_certificate_id"]
    if source_id is not None and type(source_id) is not str:
        raise PAdicVerificationError("source datum certificate ID has the wrong type")
    result = LiftSet(
        chart.datum,
        chart,
        witness,
        source_datum_certificate_id=source_id,
    )
    if raw != result.to_schema_document():
        raise PAdicVerificationError("lift-set transport was altered")
    return result


def _transport_from_schema(value: object, lifts: LiftSet) -> LiftTransportWitness:
    raw = _strict_object(value, "lift transport witness")
    _exact_keys(
        raw,
        {
            "schema",
            "group_element",
            "lift_permutation",
            "lift_set_id",
            "arithmetic_compatible",
            "model_coordinate_permutations",
            "model_transport_verified",
            "transport_labels",
            "transport_scope",
            "type",
        },
        "lift transport witness",
    )
    labels = _strict_array(raw["transport_labels"], "lift transport labels")
    if len(labels) != lifts.size:
        raise PAdicVerificationError("lift transport labels are not complete")
    if any(type(item) is not str for item in labels):
        raise PAdicVerificationError("lift transport labels must contain strings")
    raw_model_maps = _strict_array(
        raw["model_coordinate_permutations"],
        "model coordinate transports",
    )
    expected_model_maps = lifts.size if raw["model_transport_verified"] is True else 0
    if len(raw_model_maps) != expected_model_maps:
        raise PAdicVerificationError("model coordinate transport table has the wrong cardinality")
    model_maps = tuple(
        _permutation_from_schema(item, f"model coordinate transport[{index}]")
        for index, item in enumerate(raw_model_maps)
    )
    if type(raw["model_transport_verified"]) is not bool:
        raise PAdicVerificationError("model transport verification flag must be boolean")
    if type(raw["arithmetic_compatible"]) is not bool:
        raise PAdicVerificationError("arithmetic compatibility flag must be boolean")
    result = LiftTransportWitness(
        lifts,
        _permutation_from_schema(raw["group_element"], "transport group element"),
        _permutation_from_schema(raw["lift_permutation"], "transport lift permutation"),
        transport_labels=cast(list[str], labels),
        model_coordinate_permutations=(model_maps if raw["model_transport_verified"] else None),
    )
    if raw != result.to_schema_document():
        raise PAdicVerificationError("lift transport witness was altered")
    return result


def finite_lift_action_from_schema(value: object) -> FiniteLiftAction:
    raw = _strict_object(value, "finite lift action")
    _exact_keys(
        raw,
        {
            "schema",
            "action_scope",
            "arithmetic_galois_action",
            "group",
            "lifts",
            "type",
            "witnesses",
        },
        "finite lift action",
    )
    lifts = lift_set_from_schema(raw["lifts"])
    group = _group_from_schema(raw["group"], "lift group")
    raw_witnesses = _strict_array(raw["witnesses"], "finite lift-action witnesses")
    if len(raw_witnesses) != group.order:
        raise PAdicVerificationError("finite lift-action witness table has the wrong cardinality")
    witnesses = tuple(_transport_from_schema(item, lifts) for item in raw_witnesses)
    result = FiniteLiftAction(lifts, group, witnesses)
    if raw != result.to_schema_document():
        raise PAdicVerificationError("finite lift-action transport was altered")
    return result


def lift_galois_action_from_schema(value: object) -> LiftGaloisAction:
    raw = _strict_object(value, "Galois lift action")
    _exact_keys(
        raw,
        {
            "schema",
            "action_scope",
            "arithmetic_galois_action",
            "characteristic_zero_lift_action_claimed",
            "coefficient_action_rule",
            "finite_action",
            "geometric_lift_action_claimed",
            "lift_set_certificate_id",
            "quotient_id",
            "quotient_presentation_certificate_id",
            "quotient_proving_certificate_id",
            "quotient_snapshot",
            "type",
        },
        "Galois lift action",
    )
    scalar_fields = (
        "action_scope",
        "coefficient_action_rule",
        "lift_set_certificate_id",
        "quotient_id",
        "quotient_presentation_certificate_id",
        "quotient_proving_certificate_id",
    )
    if any(type(raw[field]) is not str for field in scalar_fields):
        raise PAdicVerificationError("Galois lift-action identifiers must be strings")
    boolean_fields = (
        "arithmetic_galois_action",
        "characteristic_zero_lift_action_claimed",
        "geometric_lift_action_claimed",
    )
    if any(type(raw[field]) is not bool for field in boolean_fields):
        raise PAdicVerificationError("Galois lift-action boundary flags must be booleans")
    result = object.__new__(LiftGaloisAction)
    object.__setattr__(
        result,
        "finite_action",
        finite_lift_action_from_schema(raw["finite_action"]),
    )
    object.__setattr__(result, "quotient_id", cast(str, raw["quotient_id"]))
    object.__setattr__(
        result,
        "quotient_snapshot",
        strict_canonical_mapping(
            _strict_object(raw["quotient_snapshot"], "Galois quotient snapshot"),
            "Galois quotient snapshot",
        ),
    )
    object.__setattr__(
        result,
        "lift_set_certificate_id",
        cast(str, raw["lift_set_certificate_id"]),
    )
    object.__setattr__(
        result,
        "quotient_presentation_certificate_id",
        cast(str, raw["quotient_presentation_certificate_id"]),
    )
    object.__setattr__(
        result,
        "quotient_proving_certificate_id",
        cast(str, raw["quotient_proving_certificate_id"]),
    )
    object.__setattr__(result, "action_scope", cast(str, raw["action_scope"]))
    object.__setattr__(
        result,
        "coefficient_action_rule",
        cast(str, raw["coefficient_action_rule"]),
    )
    object.__setattr__(
        result,
        "characteristic_zero_lift_action_claimed",
        raw["characteristic_zero_lift_action_claimed"],
    )
    object.__setattr__(
        result,
        "geometric_lift_action_claimed",
        raw["geometric_lift_action_claimed"],
    )
    object.__setattr__(
        result,
        "arithmetic_galois_action",
        raw["arithmetic_galois_action"],
    )
    result.verify()
    if raw != result.to_schema_document():
        raise PAdicVerificationError("Galois lift-action transport was altered")
    return result


def fixed_lift_set_from_schema(value: object) -> FixedLiftSet:
    raw = _strict_object(value, "fixed lift set")
    _exact_keys(
        raw,
        {
            "schema",
            "action",
            "action_kind",
            "completeness_scope",
            "descent_claimed",
            "fixed",
            "source_action_certificate_id",
            "type",
        },
        "fixed lift set",
    )
    if raw["action_kind"] == "arithmetic-galois":
        action: ExactLiftAction = lift_galois_action_from_schema(raw["action"])
    elif raw["action_kind"] == "finite-set":
        action = finite_lift_action_from_schema(raw["action"])
    else:
        raise PAdicVerificationError("fixed lift set has an unsupported action kind")
    source_id = raw["source_action_certificate_id"]
    if source_id is not None and type(source_id) is not str:
        raise PAdicVerificationError("source action certificate ID has the wrong type")
    result = FixedLiftSet(action, source_action_certificate_id=source_id)
    if raw != result.to_schema_document():
        raise PAdicVerificationError("fixed lift-set transport was altered")
    return result


@padic_payload_verifier("lift-set")
def _verify_lift_set_payload(
    payload: Mapping[str, object],
    evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    if set(payload) != {"result"}:
        raise PAdicVerificationError("lift-set receipt payload has a foreign shape")
    result = lift_set_from_schema(payload["result"])
    consumed: tuple[str, ...] = ()
    if result.source_datum_certificate_id is not None:
        _require_source_evidence(
            evidence,
            result.source_datum_certificate_id,
            "deformation-datum",
            result.datum.to_schema_document(),
        )
        consumed = (result.source_datum_certificate_id,)
    return PAdicPayloadReplay(
        checks=(
            "finite-chart-root-exhaustion",
            "literal-model-equality-deduplication",
            "pinned-chart-completeness-only",
        ),
        evidence_ids=tuple(sorted(consumed)),
    )


def _verify_quotient_evidence(
    result: LiftGaloisAction,
    evidence: tuple[VerificationCertificate, ...],
) -> None:
    by_id = {item.certificate_id: item for item in evidence}
    presentation = by_id.get(result.quotient_presentation_certificate_id)
    proving = by_id.get(result.quotient_proving_certificate_id)
    if presentation is None or proving is None:
        raise PAdicVerificationError("complete quotient certificate evidence is missing")
    witness = presentation.witness.to_dict()
    if set(witness) != {
        "proving_certificate_id",
        "quotient",
        "quotient_id",
        "schema",
    }:
        raise PAdicVerificationError("quotient presentation evidence has a foreign witness")
    if (
        witness["quotient_id"] != result.quotient_id
        or witness["proving_certificate_id"] != proving.certificate_id
        or not strict_canonical_equal(witness["quotient"], result.quotient_snapshot)
    ):
        raise PAdicVerificationError("quotient evidence is not bound to the arithmetic action")
    dependency_ids = {item.certificate_id for item in presentation.dependencies}
    if proving.certificate_id not in dependency_ids:
        raise PAdicVerificationError("quotient presentation omits its proving dependency")


@padic_payload_verifier("lift-action")
def _verify_lift_action_payload(
    payload: Mapping[str, object],
    evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    if set(payload) != {"result"}:
        raise PAdicVerificationError("lift-action receipt payload has a foreign shape")
    result = lift_galois_action_from_schema(payload["result"])
    _require_source_evidence(
        evidence,
        result.lift_set_certificate_id,
        "lift-set",
        result.lifts.to_schema_document(),
    )
    _verify_quotient_evidence(result, evidence)
    consumed = tuple(
        sorted(
            {
                result.lift_set_certificate_id,
                result.quotient_presentation_certificate_id,
                result.quotient_proving_certificate_id,
            }
        )
    )
    return PAdicPayloadReplay(
        checks=(
            "complete-finite-set-action-law",
            "exact-model-transport-for-every-lift",
            "trivial-prime-field-coefficient-action",
            "complete-arithmetic-quotient-binding",
            "finite-action-and-galois-action-separation",
        ),
        evidence_ids=consumed,
    )


@padic_payload_verifier("fixed-lift-set")
def _verify_fixed_lift_set_payload(
    payload: Mapping[str, object],
    evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    if set(payload) != {"result"}:
        raise PAdicVerificationError("fixed-lift receipt payload has a foreign shape")
    result = fixed_lift_set_from_schema(payload["result"])
    consumed: tuple[str, ...] = ()
    if result.source_action_certificate_id is not None:
        _require_source_evidence(
            evidence,
            result.source_action_certificate_id,
            "lift-action",
            result.action.to_schema_document(),
        )
        consumed = (result.source_action_certificate_id,)
    return PAdicPayloadReplay(
        checks=(
            "exhaustive-fixed-class-test",
            "fixed-class-is-not-effective-descent",
        ),
        evidence_ids=tuple(sorted(consumed)),
    )


__all__ = [
    "FiniteLiftAction",
    "FixedLift",
    "FixedLiftSet",
    "LiftCandidate",
    "LiftChart",
    "LiftEnumerationWitness",
    "LiftGaloisAction",
    "LiftSet",
    "LiftTransportWitness",
    "fixed_lifts",
    "lift_galois_action",
    "lift_set",
]
