"""Certified numerical monodromy bindings and exact weighted braid planning."""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, pairwise
from typing import TypeAlias, cast

from arbogast.cert import content_address
from arbogast.core import CanonicalJSON, canonical_data
from arbogast.hurwitz import (
    BraidAction,
    BraidWord,
    HurwitzError,
    NielsenClass,
    NielsenTuple,
)
from arbogast.rep import Permutation, PermutationGroup

from ._schema import (
    MAX_BRAID_WORD_LENGTH,
    MAX_GRAPH_EDGES,
    MAX_GRAPH_VERTICES,
    NumericSemanticObject,
    strict_int,
)
from .continuation import ContinuationResult
from .dyadic import ComplexDyadic, Dyadic
from .errors import NumericError, NumericVerificationError, UnsupportedNumericOperation
from .models import ExactCover, ExactPolynomial, NumericPoint, ParameterPath
from .outcomes import NumericUnknown, UnsupportedNumeric

PermutationImages: TypeAlias = tuple[int, ...]
CostKey: TypeAlias = str | tuple[str, bool]
CostValue: TypeAlias = Dyadic | int | Fraction

_B2_HOMOTOPY_CONVENTION = (
    "right Hurwitz sigma_0: z1-z0 makes the counterclockwise upper-half-plane "
    "half-turn; the lower-half-plane half-turn is sigma_0 inverse"
)


class _UnreachableBraidTarget(NumericError):
    """The exact finite graph has no path to the requested target."""


def _word_data(word: BraidWord) -> list[CanonicalJSON]:
    normalized = BraidWord.coerce(word)
    if len(normalized) > MAX_BRAID_WORD_LENGTH:
        raise NumericError("braid word exceeds the portable length bound")
    return [{"index": move.index, "inverse": move.inverse} for move in normalized.moves]


def _winding(path: ParameterPath, point: ComplexDyadic) -> int | None:
    """Return the exact polygon winding number, or None on a degenerate ray crossing."""

    if path.start != path.end:
        return None
    total = 0
    for start, end in pairwise(path.vertices):
        x1 = (start.real - point.real).fraction
        y1 = (start.imag - point.imag).fraction
        x2 = (end.real - point.real).fraction
        y2 = (end.imag - point.imag).fraction
        cross = x1 * y2 - x2 * y1
        if cross == 0 and min(x1, x2) <= 0 <= max(x1, x2) and min(y1, y2) <= 0 <= max(y1, y2):
            return None
        if y1 <= 0 < y2 and cross > 0:
            total += 1
        elif y2 <= 0 < y1 and cross < 0:
            total -= 1
    return total


@dataclass(frozen=True, slots=True, init=False)
class BranchLoop(NumericSemanticObject):
    """A positively oriented polygon enclosing exactly one declared branch point."""

    model: ExactCover
    branch_index: int
    path: ParameterPath

    schema_version = "arbogast.numeric.branch-loop/v1"

    def __init__(self, model: ExactCover, branch_index: int, path: ParameterPath) -> None:
        if not isinstance(model, ExactCover) or not isinstance(path, ParameterPath):
            raise TypeError("branch loop needs an ExactCover and ParameterPath")
        index = strict_int(branch_index, "branch index", minimum=0)
        if index >= len(model.branch_points):
            raise NumericError("branch index is out of range")
        winding_numbers = tuple(_winding(path, point) for point in model.branch_points)
        if winding_numbers[index] != 1 or any(
            value != 0 for position, value in enumerate(winding_numbers) if position != index
        ):
            raise NumericError(
                "branch loop must wind once positively around its branch and zero around others"
            )
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "branch_index", index)
        object.__setattr__(self, "path", path)

    def verify(self) -> bool:
        if BranchLoop(self.model, self.branch_index, self.path) != self:
            raise NumericVerificationError("branch-loop winding witness was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "branch_index": self.branch_index,
            "model": self.model.to_canonical_data(),
            "path": self.path.to_canonical_data(),
            "type": "arbogast.numeric.branch_loop",
        }


def _separated(points: tuple[NumericPoint, ...]) -> bool:
    return all(
        any(
            left_ball.disjoint(right_ball)
            for left_ball, right_ball in zip(
                left.coordinates,
                right.coordinates,
                strict=True,
            )
        )
        for left, right in combinations(points, 2)
    )


@dataclass(frozen=True, slots=True, init=False)
class BranchTracking(NumericSemanticObject):
    """Complete sheet tracking around one certified branch loop."""

    loop: BranchLoop
    source_points: tuple[NumericPoint, ...]
    continuations: tuple[ContinuationResult, ...]
    permutation: PermutationImages

    schema_version = "arbogast.numeric.branch-tracking/v1"

    def __init__(
        self,
        loop: BranchLoop,
        source_points: Sequence[NumericPoint],
        continuations: Sequence[ContinuationResult],
        permutation: Sequence[int],
    ) -> None:
        if not isinstance(loop, BranchLoop):
            raise TypeError("branch tracking needs a BranchLoop")
        sources = tuple(source_points)
        results = tuple(continuations)
        images = tuple(
            strict_int(value, "sheet permutation image", minimum=0) for value in permutation
        )
        degree = loop.model.degree
        if (
            len(sources) != degree
            or len(results) != degree
            or sorted(images) != list(range(degree))
        ):
            raise NumericError(
                "branch tracking must give one continuation and a permutation of every sheet"
            )
        object.__setattr__(self, "loop", loop)
        object.__setattr__(self, "source_points", sources)
        object.__setattr__(self, "continuations", results)
        object.__setattr__(self, "permutation", images)
        self.verify()

    def verify(self) -> bool:
        self.loop.verify()
        base_system = self.loop.model.family.fiber(self.loop.path.start)
        if any(point.system != base_system for point in self.source_points):
            raise NumericVerificationError("branch tracking sources use the wrong base fiber")
        if not _separated(self.source_points):
            raise NumericVerificationError("branch tracking source enclosures are not separated")
        for source_index, result in enumerate(self.continuations):
            result.verify()
            if result.tube.family != self.loop.model.family or result.tube.path != self.loop.path:
                raise NumericVerificationError("branch continuation uses the wrong family or loop")
            if result.tube.start_point != self.source_points[source_index]:
                raise NumericVerificationError("branch continuation starts at the wrong sheet")
            target = self.source_points[self.permutation[source_index]]
            if not all(
                target_ball.contains(endpoint_ball)
                for target_ball, endpoint_ball in zip(
                    target.coordinates,
                    result.endpoint.coordinates,
                    strict=True,
                )
            ):
                raise NumericVerificationError(
                    "branch continuation does not end in its claimed sheet"
                )
        for step_index in range(self.loop.path.segment_count):
            step_domains = tuple(
                result.tube.steps[step_index].domain for result in self.continuations
            )
            if not all(
                any(
                    left_ball.disjoint(right_ball)
                    for left_ball, right_ball in zip(left, right, strict=True)
                )
                for left, right in combinations(step_domains, 2)
            ):
                raise NumericVerificationError(
                    "branch continuation tubes do not certify sheet collision avoidance"
                )
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "continuations": [result.to_canonical_data() for result in self.continuations],
            "loop": self.loop.to_canonical_data(),
            "permutation": list(self.permutation),
            "source_points": [point.to_canonical_data() for point in self.source_points],
            "type": "arbogast.numeric.branch_tracking",
        }


@dataclass(frozen=True, slots=True, init=False)
class NumericalCover(NumericSemanticObject):
    """A complete quadratic fiber with certified finite and infinity branch cycles."""

    model: ExactCover
    base_parameter: ComplexDyadic
    fiber_points: tuple[NumericPoint, ...]
    trackings: tuple[BranchTracking, ...]

    schema_version = "arbogast.numeric.numerical-cover/v1"

    def __init__(
        self,
        model: ExactCover,
        base_parameter: ComplexDyadic | Dyadic | int | Fraction,
        fiber_points: Sequence[NumericPoint],
        trackings: Sequence[BranchTracking],
    ) -> None:
        if not isinstance(model, ExactCover):
            raise TypeError("numerical cover model must be an ExactCover")
        parameter = ComplexDyadic.coerce(base_parameter)
        points = tuple(fiber_points)
        tracking_tuple = tuple(trackings)
        if len(points) != model.degree:
            raise NumericError("numerical cover needs exactly one enclosure per sheet")
        if len(tracking_tuple) != len(model.branch_points):
            raise NumericError("numerical cover needs one tracking per declared branch point")
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "base_parameter", parameter)
        object.__setattr__(self, "fiber_points", points)
        object.__setattr__(self, "trackings", tracking_tuple)
        self.verify()

    def verify(self) -> bool:
        self.model.verify()
        base_system = self.model.family.fiber(self.base_parameter)
        if any(point.system != base_system for point in self.fiber_points):
            raise NumericVerificationError("numerical fiber point uses the wrong exact fiber")
        if not _separated(self.fiber_points):
            raise NumericVerificationError("numerical fiber enclosures are not pairwise separated")
        if tuple(tracking.loop.branch_index for tracking in self.trackings) != tuple(
            range(len(self.model.branch_points))
        ):
            raise NumericVerificationError("branch trackings are not in canonical divisor order")
        for tracking in self.trackings:
            tracking.verify()
            if tracking.loop.model != self.model or tracking.source_points != self.fiber_points:
                raise NumericVerificationError(
                    "branch tracking is bound to a different cover fiber"
                )
            if tracking.permutation != (1, 0):
                raise NumericVerificationError(
                    "a simple finite branch of the certified quadratic cover must swap its sheets"
                )
        return True

    @property
    def tracked_permutations(self) -> tuple[PermutationImages, ...]:
        finite = tuple(tracking.permutation for tracking in self.trackings)
        if not self.model.infinity_branch:
            return finite
        product = Permutation.identity(self.model.degree)
        for images in finite:
            product = product * Permutation(images)
        return (*finite, product.inverse().images)

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "base_parameter": self.base_parameter.to_canonical_data(),
            "fiber_points": [point.to_canonical_data() for point in self.fiber_points],
            "model": self.model.to_canonical_data(),
            "trackings": [tracking.to_canonical_data() for tracking in self.trackings],
            "type": "arbogast.numeric.numerical_cover",
        }


def _nielsen_snapshot(nielsen_class: NielsenClass, index: int) -> dict[str, CanonicalJSON]:
    certificate = nielsen_class.certificate
    if certificate is None:
        raise NumericError("numeric vertex binding requires a complete Nielsen certificate")
    payload = canonical_data(certificate.to_canonical())
    if not isinstance(payload, dict):
        raise NumericError("Nielsen certificate did not encode as a canonical mapping")
    elements = nielsen_class.context.elements
    if any(not isinstance(element, Permutation) for element in elements):
        raise NumericError(
            "numeric vertex binding requires a concrete permutation-group enumeration"
        )
    return {
        "certificate": payload,
        "element_permutations": [list(cast(Permutation, element).images) for element in elements],
        "vertex_index": index,
        "vertex_key": list(nielsen_class[index].key()),
    }


@dataclass(frozen=True, slots=True, init=False)
class NielsenVertex(NumericalCover):
    """A numerical cover bound to one exact certified Nielsen-class vertex."""

    nielsen_class: NielsenClass
    vertex_index: int

    schema_version = "arbogast.numeric.nielsen-vertex/v1"

    def __init__(
        self, cover: NumericalCover, nielsen_class: NielsenClass, vertex_index: int
    ) -> None:
        if not isinstance(cover, NumericalCover) or not isinstance(nielsen_class, NielsenClass):
            raise TypeError("Nielsen vertex needs a NumericalCover and NielsenClass")
        index = strict_int(vertex_index, "Nielsen vertex index", minimum=0)
        if index >= len(nielsen_class):
            raise NumericError("Nielsen vertex index is out of range")
        object.__setattr__(self, "model", cover.model)
        object.__setattr__(self, "base_parameter", cover.base_parameter)
        object.__setattr__(self, "fiber_points", cover.fiber_points)
        object.__setattr__(self, "trackings", cover.trackings)
        object.__setattr__(self, "nielsen_class", nielsen_class)
        object.__setattr__(self, "vertex_index", index)
        self.verify()

    @property
    def nielsen_tuple(self) -> NielsenTuple:
        return self.nielsen_class[self.vertex_index]

    def verify(self) -> bool:
        NumericalCover.verify(self)
        self.nielsen_class.verify(require_complete=True)
        entries = self.nielsen_tuple.entries
        if len(entries) != self.model.branch_count or any(
            not isinstance(entry, Permutation) for entry in entries
        ):
            raise NumericVerificationError(
                "numeric vertex binding requires concrete permutation branch cycles"
            )
        if tuple(cast(Permutation, entry).images for entry in entries) != self.tracked_permutations:
            raise NumericVerificationError(
                "tracked permutations do not match the exact Nielsen tuple"
            )
        return True

    @property
    def supporting_certificates(self) -> tuple[object, ...]:
        certificate = self.nielsen_class.certificate
        assert certificate is not None
        return (certificate.verification_certificate(),)

    def to_canonical_data(self) -> CanonicalJSON:
        base = NumericalCover.to_canonical_data(self)
        assert isinstance(base, dict)
        return {
            **base,
            "nielsen": _nielsen_snapshot(self.nielsen_class, self.vertex_index),
            "type": "arbogast.numeric.nielsen_vertex",
        }


VertexOutcome: TypeAlias = NielsenVertex | NumericUnknown | UnsupportedNumeric


def bind_vertex(
    cover: NumericalCover,
    N: NielsenClass | object,
    *,
    vertex: int | NielsenTuple | None = None,
) -> VertexOutcome:
    """Identify tracked permutations with exactly one certified Nielsen vertex."""

    if not isinstance(cover, NumericalCover):
        raise TypeError("bind_vertex expects a NumericalCover")
    if not isinstance(N, NielsenClass):
        return UnsupportedNumeric(
            "bind_vertex",
            "vertex binding requires an explicit complete NielsenClass, not a summary dataset",
            requested={"cover_id": cover.content_id},
            supported=("NielsenClass with a complete enumeration certificate",),
        )
    N.verify(require_complete=True)
    tracked_tuple = branch_cycles(cover)
    if not isinstance(tracked_tuple, NielsenTuple):
        return NumericUnknown(
            "bind_vertex",
            "the numerical cover did not yield exact tracked branch cycles",
            requested={"cover_id": cover.content_id},
        )
    if vertex is None:
        try:
            index = N.canonicalize(tracked_tuple.entries).representative_index
        except HurwitzError:
            return NumericUnknown(
                "bind_vertex",
                "tracked monodromy is not a vertex of the supplied exact Nielsen class",
                requested={"cover_id": cover.content_id},
            )
    elif isinstance(vertex, NielsenTuple):
        index = N.canonicalize(vertex.entries).representative_index
    else:
        index = strict_int(vertex, "Nielsen vertex", minimum=0)
    try:
        return NielsenVertex(cover, N, index)
    except NumericError as exc:
        return NumericUnknown(
            "bind_vertex",
            str(exc),
            requested={"cover_id": cover.content_id, "vertex_index": index},
        )


class BranchCycleTuple(NielsenTuple, NumericSemanticObject):
    """A Nielsen tuple whose exact entries are backed by a certified NumericalCover."""

    schema_version = "arbogast.numeric.branch-cycle-tuple/v1"
    cover: NumericalCover

    def __init__(self, cover: NumericalCover) -> None:
        if not isinstance(cover, NumericalCover):
            raise TypeError("branch-cycle tuple needs a NumericalCover")
        cover.verify()
        entries = tuple(Permutation(images) for images in cover.tracked_permutations)
        group = PermutationGroup(entries, degree=cover.model.degree, name="tracked monodromy")
        classes = tuple(group.conjugacy_class(entry) for entry in entries)
        NielsenTuple.__init__(self, group, entries, classes)
        self.cover = cover

    def verify(self) -> bool:
        self.cover.verify()
        NielsenTuple.verify(self)
        if tuple(cast(Permutation, entry).images for entry in self.entries) != (
            self.cover.tracked_permutations
        ):
            raise NumericVerificationError("tracked branch-cycle tuple was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cover": NumericalCover.to_canonical_data(self.cover),
            "entries": [list(cast(Permutation, entry).images) for entry in self.entries],
            "type": "arbogast.numeric.branch_cycle_tuple",
        }


BranchCycleOutcome: TypeAlias = BranchCycleTuple | NumericUnknown


def branch_cycles(cover: NumericalCover) -> BranchCycleOutcome:
    """Construct the exact generating product-one tuple tracked by a complete cover."""

    if not isinstance(cover, NumericalCover):
        raise TypeError("branch_cycles expects a NumericalCover")
    cover.verify()
    try:
        return BranchCycleTuple(cover)
    except (HurwitzError, ValueError) as exc:
        return NumericUnknown(
            "branch_cycles",
            f"tracked permutations do not form a generating product-one Nielsen tuple: {exc}",
            requested={"cover_id": cover.content_id},
        )


@dataclass(frozen=True, slots=True, init=False)
class BraidContinuationWitness(NumericSemanticObject):
    """Exact Nielsen-edge and local sheet-path evidence, not a cover deformation."""

    source: NielsenVertex
    word: BraidWord
    target: NielsenVertex
    action: BraidAction
    sheet_continuations: tuple[ContinuationResult, ...]
    sheet_permutation: PermutationImages

    schema_version = "arbogast.numeric.braid-continuation-witness/v1"

    def __init__(
        self,
        source: NielsenVertex,
        word: BraidWord,
        target: NielsenVertex,
        action: BraidAction,
        sheet_continuations: Sequence[ContinuationResult],
        sheet_permutation: Sequence[int],
    ) -> None:
        if not isinstance(source, NielsenVertex) or not isinstance(target, NielsenVertex):
            raise TypeError("braid continuation needs bound source and target vertices")
        if not isinstance(action, BraidAction):
            raise TypeError("braid continuation needs an exact BraidAction")
        normalized_word = BraidWord.coerce(word)
        if len(normalized_word) > MAX_BRAID_WORD_LENGTH:
            raise NumericError("braid word exceeds the portable length bound")
        continuations = tuple(sheet_continuations)
        permutation = tuple(
            strict_int(value, "braid sheet permutation image", minimum=0)
            for value in sheet_permutation
        )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "word", normalized_word)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "sheet_continuations", continuations)
        object.__setattr__(self, "sheet_permutation", permutation)
        self.verify()

    def verify(self) -> bool:
        self.source.verify()
        self.target.verify()
        self.action.verify()
        if self.action.nielsen_class is not self.source.nielsen_class or (
            self.target.nielsen_class is not self.source.nielsen_class
        ):
            raise NumericVerificationError("braid witness uses a different Nielsen class")
        expected = self.action.apply(self.source.vertex_index, self.word)
        if expected != self.target.nielsen_tuple:
            raise NumericVerificationError("target vertex is not the exact braid-word image")
        degree = self.source.model.degree
        if (
            self.source.model != self.target.model
            or len(self.sheet_continuations) != degree
            or sorted(self.sheet_permutation) != list(range(degree))
        ):
            raise NumericVerificationError("braid sheet witness has incompatible cover data")
        for source_index, continuation in enumerate(self.sheet_continuations):
            continuation.verify()
            if continuation.tube.start_point != self.source.fiber_points[source_index]:
                raise NumericVerificationError(
                    "braid continuation starts at the wrong source sheet"
                )
            target_point = self.target.fiber_points[self.sheet_permutation[source_index]]
            if not all(
                target_ball.contains(endpoint_ball)
                for target_ball, endpoint_ball in zip(
                    target_point.coordinates,
                    continuation.endpoint.coordinates,
                    strict=True,
                )
            ):
                raise NumericVerificationError("braid continuation ends at the wrong target sheet")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action": {
                "generator_names": [generator.name for generator in self.action.generators],
                "nielsen_source_id": self.action.nielsen_source_id,
            },
            "sheet_continuations": [
                continuation.to_canonical_data() for continuation in self.sheet_continuations
            ],
            "sheet_permutation": list(self.sheet_permutation),
            "source": NielsenVertex.to_canonical_data(self.source),
            "target": NielsenVertex.to_canonical_data(self.target),
            "type": "arbogast.numeric.braid_continuation_witness",
            "word": _word_data(self.word),
        }

    @property
    def supporting_certificates(self) -> tuple[object, ...]:
        return (self.action.verification_certificate(),)


def _univariate_polynomial(
    coefficients: Sequence[ComplexDyadic | Dyadic | int | Fraction],
) -> ExactPolynomial:
    return ExactPolynomial(
        1,
        tuple(((index,), coefficient) for index, coefficient in enumerate(coefficients)),
        variable_names=("s",),
    )


def _univariate_coefficients(polynomial: ExactPolynomial) -> tuple[ComplexDyadic, ...]:
    if polynomial.nvariables != 1:
        raise NumericError("B2 path polynomial must be univariate")
    coefficients = [ComplexDyadic(0)] * (polynomial.total_degree + 1)
    for exponent, coefficient in polynomial.terms:
        coefficients[exponent[0]] = coefficients[exponent[0]] + coefficient
    return tuple(coefficients)


def _polynomial_add(
    left: tuple[ComplexDyadic, ...], right: tuple[ComplexDyadic, ...]
) -> tuple[ComplexDyadic, ...]:
    size = max(len(left), len(right))
    result = [ComplexDyadic(0)] * size
    for index in range(size):
        if index < len(left):
            result[index] = result[index] + left[index]
        if index < len(right):
            result[index] = result[index] + right[index]
    while len(result) > 1 and result[-1] == ComplexDyadic(0):
        result.pop()
    return tuple(result)


def _polynomial_scale(
    value: tuple[ComplexDyadic, ...], scalar: ComplexDyadic | Dyadic | int
) -> tuple[ComplexDyadic, ...]:
    return tuple(coefficient * scalar for coefficient in value)


def _polynomial_multiply(
    left: tuple[ComplexDyadic, ...], right: tuple[ComplexDyadic, ...]
) -> tuple[ComplexDyadic, ...]:
    result = [ComplexDyadic(0)] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            result[left_index + right_index] = (
                result[left_index + right_index] + left_value * right_value
            )
    while len(result) > 1 and result[-1] == ComplexDyadic(0):
        result.pop()
    return tuple(result)


def _polynomial_power(value: tuple[ComplexDyadic, ...], exponent: int) -> tuple[ComplexDyadic, ...]:
    result: tuple[ComplexDyadic, ...] = (ComplexDyadic(1),)
    for _ in range(exponent):
        result = _polynomial_multiply(result, value)
    return result


def _polynomial_shift(value: tuple[ComplexDyadic, ...], exponent: int) -> tuple[ComplexDyadic, ...]:
    return (ComplexDyadic(0),) * exponent + value


def _complex_power(value: ComplexDyadic, exponent: int) -> ComplexDyadic:
    result = ComplexDyadic(1)
    for _ in range(exponent):
        result = result * value
    return result


def _substitute_sheet_at_midpoint(
    homotopy: ExactPolynomial,
    sheet: ExactPolynomial,
) -> tuple[ComplexDyadic, ...]:
    if homotopy.nvariables != 3 or sheet.nvariables != 1:
        raise NumericVerificationError("quadratic B2 substitution has incompatible dimensions")
    sheet_coefficients = _univariate_coefficients(sheet)
    midpoint = ComplexDyadic(Fraction(1, 2))
    result: tuple[ComplexDyadic, ...] = (ComplexDyadic(0),)
    for (x_power, t_power, s_power), coefficient in homotopy.terms:
        term = _polynomial_power(sheet_coefficients, x_power)
        term = _polynomial_scale(term, coefficient * _complex_power(midpoint, t_power))
        result = _polynomial_add(result, _polynomial_shift(term, s_power))
    return result


def _real_polynomial_coefficients(polynomial: ExactPolynomial) -> tuple[Dyadic, ...]:
    coefficients = _univariate_coefficients(polynomial)
    if any(not coefficient.imag.is_zero for coefficient in coefficients):
        raise NumericVerificationError("quadratic B2 collision SOS must be real")
    return tuple(coefficient.real for coefficient in coefficients)


def _trim_dyadic_coefficients(value: tuple[Dyadic, ...]) -> tuple[Dyadic, ...]:
    result = value
    while len(result) > 1 and result[-1].is_zero:
        result = result[:-1]
    return result


def _polynomial_value(polynomial: ExactPolynomial, value: Dyadic | int) -> ComplexDyadic:
    return polynomial.evaluate((ComplexDyadic.coerce(value),))


def _normalized_b2_polynomial() -> ExactPolynomial:
    terms: tuple[tuple[Sequence[int], ComplexDyadic], ...] = (
        ((2, 0), ComplexDyadic(1)),
        ((0, 2), ComplexDyadic(-1)),
        ((0, 1), ComplexDyadic(1)),
    )
    return ExactPolynomial(
        2,
        terms,
        variable_names=("x", "t"),
    )


def _quadratic_b2_exact_data(
    orientation: int,
) -> tuple[
    ExactPolynomial,
    ExactPolynomial,
    tuple[ExactPolynomial, ExactPolynomial],
    tuple[ExactPolynomial, ExactPolynomial],
    tuple[ExactPolynomial, ExactPolynomial],
]:
    """Return q, H, ordered branch paths, collision SOS, and sheet paths."""

    if orientation not in {-1, 1}:
        raise NumericError("B2 orientation must be +1 or -1")
    q = _univariate_polynomial(
        (
            Fraction(1, 2),
            ComplexDyadic(-1, 2 * orientation),
            ComplexDyadic(0, -2 * orientation),
        )
    )
    homotopy_terms: tuple[tuple[Sequence[int], ComplexDyadic], ...] = (
        ((2, 0, 0), ComplexDyadic(1)),
        ((0, 2, 0), ComplexDyadic(-1)),
        ((0, 1, 0), ComplexDyadic(1)),
        ((0, 0, 1), ComplexDyadic(-1, 2 * orientation)),
        ((0, 0, 2), ComplexDyadic(-3, -6 * orientation)),
        ((0, 0, 3), ComplexDyadic(8, 4 * orientation)),
        ((0, 0, 4), ComplexDyadic(-4)),
    )
    coefficient_homotopy = ExactPolynomial(
        3,
        homotopy_terms,
        variable_names=("x", "t", "s"),
    )
    branch_paths = (
        _univariate_polynomial(
            (0, ComplexDyadic(1, -2 * orientation), ComplexDyadic(0, 2 * orientation))
        ),
        _univariate_polynomial(
            (1, ComplexDyadic(-1, 2 * orientation), ComplexDyadic(0, -2 * orientation))
        ),
    )
    collision_sos = (
        _univariate_polynomial((1, -2)),
        _univariate_polynomial((0, 4 * orientation, -4 * orientation)),
    )
    sheet_paths = (
        _univariate_polynomial(
            (
                ComplexDyadic(0, Fraction(1, 2)),
                ComplexDyadic(-2 * orientation, -1),
                2 * orientation,
            )
        ),
        _univariate_polynomial(
            (
                ComplexDyadic(0, Fraction(-1, 2)),
                ComplexDyadic(2 * orientation, 1),
                -2 * orientation,
            )
        ),
    )
    return q, coefficient_homotopy, branch_paths, collision_sos, sheet_paths


def _verify_b2_polynomial_identities(
    orientation: int,
    q: ExactPolynomial,
    coefficient_homotopy: ExactPolynomial,
    branch_paths: tuple[ExactPolynomial, ExactPolynomial],
    collision_sos: tuple[ExactPolynomial, ExactPolynomial],
    sheet_paths: tuple[ExactPolynomial, ExactPolynomial],
) -> None:
    expected = _quadratic_b2_exact_data(orientation)
    if (q, coefficient_homotopy, branch_paths, collision_sos, sheet_paths) != expected:
        raise NumericVerificationError("quadratic B2 homotopy exact data was altered")
    q_coefficients = _univariate_coefficients(q)
    branch_coefficients = tuple(_univariate_coefficients(path) for path in branch_paths)
    midpoint = (ComplexDyadic(Fraction(1, 2)),)
    if _polynomial_add(branch_coefficients[0], q_coefficients) != midpoint or (
        _polynomial_add(branch_coefficients[1], _polynomial_scale(q_coefficients, -1)) != midpoint
    ):
        raise NumericVerificationError("quadratic B2 branch paths violate z0=m-q or z1=m+q")
    branch_sum = _polynomial_add(branch_coefficients[0], branch_coefficients[1])
    branch_product = _polynomial_multiply(branch_coefficients[0], branch_coefficients[1])
    derived_homotopy: dict[tuple[int, int, int], ComplexDyadic] = {
        (2, 0, 0): ComplexDyadic(1),
        (0, 2, 0): ComplexDyadic(-1),
    }
    for s_power, coefficient in enumerate(branch_sum):
        if coefficient != ComplexDyadic(0):
            derived_homotopy[(0, 1, s_power)] = coefficient
    for s_power, coefficient in enumerate(branch_product):
        if coefficient != ComplexDyadic(0):
            derived_homotopy[(0, 0, s_power)] = -coefficient
    displayed_homotopy = {
        exponent: coefficient for exponent, coefficient in coefficient_homotopy.terms
    }
    if derived_homotopy != displayed_homotopy:
        raise NumericVerificationError("quadratic B2 homotopy is not H=x^2-(t-z0(s))(t-z1(s))")
    source_polynomial = _normalized_b2_polynomial()
    if coefficient_homotopy.substitute_last(0) != source_polynomial or (
        coefficient_homotopy.substitute_last(1) != source_polynomial
    ):
        raise NumericVerificationError("quadratic B2 coefficient homotopy has wrong endpoints")
    branch_difference = _polynomial_add(
        branch_coefficients[1],
        _polynomial_scale(branch_coefficients[0], -1),
    )
    if branch_difference != _polynomial_scale(q_coefficients, 2):
        raise NumericVerificationError("quadratic B2 branch paths do not differ by 2q")
    for path in sheet_paths:
        if _substitute_sheet_at_midpoint(coefficient_homotopy, path) != (ComplexDyadic(0),):
            raise NumericVerificationError(
                "quadratic B2 sheet path does not solve the supplied H(x,1/2,s)"
            )
    real_part = _trim_dyadic_coefficients(
        tuple(coefficient.real for coefficient in branch_difference)
    )
    imaginary_part = _trim_dyadic_coefficients(
        tuple(coefficient.imag for coefficient in branch_difference)
    )
    sos_real = _real_polynomial_coefficients(collision_sos[0])
    sos_imaginary = _real_polynomial_coefficients(collision_sos[1])
    if sos_real != real_part or sos_imaginary != imaginary_part:
        raise NumericVerificationError("quadratic B2 collision SOS is not Re/Im(z1-z0)")
    if len(sos_real) != 2 or sos_real[1].is_zero:
        raise NumericVerificationError("quadratic B2 real separation factor is not linear")
    if (
        len(sos_imaginary) != 3
        or not sos_imaginary[0].is_zero
        or sos_imaginary[1].is_zero
        or sos_imaginary[2] != -sos_imaginary[1]
    ):
        raise NumericVerificationError("quadratic B2 imaginary separation factor is not c*s*(1-s)")
    real_root = -sos_real[0] / sos_real[1]
    if (
        (
            Dyadic.zero() <= real_root <= 1
            and _polynomial_value(collision_sos[1], real_root) == ComplexDyadic(0)
        )
        or _polynomial_value(collision_sos[0], 0) == ComplexDyadic(0)
        or _polynomial_value(collision_sos[0], 1) == ComplexDyadic(0)
    ):
        raise NumericVerificationError(
            "quadratic B2 collision SOS components have a common zero on [0,1]"
        )


def _verify_normalized_b2_vertex(vertex: NielsenVertex, name: str) -> None:
    vertex.verify()
    model = vertex.model
    if (
        model.family.parameter_name != "t"
        or model.family.polynomials != (_normalized_b2_polynomial(),)
        or model.branch_points != (ComplexDyadic(0), ComplexDyadic(1))
        or model.infinity_branch
        or vertex.base_parameter != ComplexDyadic(Fraction(1, 2))
    ):
        raise NumericVerificationError(f"{name} is not the normalized x^2-t(t-1) cover at t=1/2")


@dataclass(frozen=True, slots=True, init=False)
class QuadraticB2Homotopy(NumericSemanticObject):
    """The genuine normalized sigma_0^(+/-1) coefficient homotopy."""

    source: NielsenVertex
    word: BraidWord
    target: NielsenVertex
    action: BraidAction
    orientation: int
    q: ExactPolynomial
    coefficient_homotopy: ExactPolynomial
    branch_paths: tuple[ExactPolynomial, ExactPolynomial]
    collision_sos: tuple[ExactPolynomial, ExactPolynomial]
    sheet_paths: tuple[ExactPolynomial, ExactPolynomial]
    sheet_permutation: PermutationImages

    schema_version = "arbogast.numeric.quadratic-b2-homotopy/v1"

    def __init__(
        self,
        source: NielsenVertex,
        word: BraidWord,
        target: NielsenVertex,
        action: BraidAction,
    ) -> None:
        if not isinstance(source, NielsenVertex) or not isinstance(target, NielsenVertex):
            raise TypeError("quadratic B2 homotopy needs exact Nielsen source and target vertices")
        if not isinstance(action, BraidAction):
            raise TypeError("quadratic B2 homotopy needs an exact BraidAction")
        normalized_word = BraidWord.coerce(word)
        if len(normalized_word) != 1 or normalized_word.moves[0].index != 0:
            raise NumericError("quadratic B2 homotopy supports one sigma_0 generator or inverse")
        orientation = -1 if normalized_word.moves[0].inverse else 1
        q, coefficient_homotopy, branches, collision_sos, sheets = _quadratic_b2_exact_data(
            orientation
        )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "word", normalized_word)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "orientation", orientation)
        object.__setattr__(self, "q", q)
        object.__setattr__(self, "coefficient_homotopy", coefficient_homotopy)
        object.__setattr__(self, "branch_paths", branches)
        object.__setattr__(self, "collision_sos", collision_sos)
        object.__setattr__(self, "sheet_paths", sheets)
        object.__setattr__(self, "sheet_permutation", (1, 0))
        self.verify()

    def verify(self) -> bool:
        _verify_normalized_b2_vertex(self.source, "quadratic B2 source")
        _verify_normalized_b2_vertex(self.target, "quadratic B2 target")
        self.action.verify()
        if (
            self.action.nielsen_class is not self.source.nielsen_class
            or self.target.nielsen_class is not self.source.nielsen_class
        ):
            raise NumericVerificationError("quadratic B2 endpoints use a different Nielsen class")
        if len(self.action.generators) != 1 or (
            self.action.generators[0].name != "sigma_0"
            or self.action.generators[0].word != BraidWord.generator(0)
        ):
            raise NumericVerificationError("quadratic B2 action is not the standard B2 action")
        if self.orientation != (-1 if self.word.moves[0].inverse else 1):
            raise NumericVerificationError("quadratic B2 word and geometric orientation disagree")
        if self.action.apply(self.source.vertex_index, self.word) != self.target.nielsen_tuple:
            raise NumericVerificationError("quadratic B2 target is not the exact Nielsen image")
        if self.target != self.source:
            raise NumericVerificationError(
                "normalized quadratic B2 returns to the same exact cover and Nielsen vertex"
            )
        _verify_b2_polynomial_identities(
            self.orientation,
            self.q,
            self.coefficient_homotopy,
            self.branch_paths,
            self.collision_sos,
            self.sheet_paths,
        )
        if tuple(_polynomial_value(path, 0) for path in self.branch_paths) != (
            ComplexDyadic(0),
            ComplexDyadic(1),
        ) or tuple(_polynomial_value(path, 1) for path in self.branch_paths) != (
            ComplexDyadic(1),
            ComplexDyadic(0),
        ):
            raise NumericVerificationError("quadratic B2 branch paths do not exchange 0 and 1")
        sheet_starts = tuple(_polynomial_value(path, 0) for path in self.sheet_paths)
        sheet_ends = tuple(_polynomial_value(path, 1) for path in self.sheet_paths)
        if self.sheet_permutation != (1, 0):
            raise NumericVerificationError("quadratic B2 sheet permutation was altered")
        for source_index, value in enumerate(sheet_starts):
            if not self.source.fiber_points[source_index].coordinates[0].contains(value):
                raise NumericVerificationError("quadratic B2 sheet path starts outside its source")
        for source_index, value in enumerate(sheet_ends):
            target_index = self.sheet_permutation[source_index]
            if not self.target.fiber_points[target_index].coordinates[0].contains(value):
                raise NumericVerificationError("quadratic B2 sheet path ends outside its target")
        return True

    @property
    def supporting_certificates(self) -> tuple[object, ...]:
        return (self.action.verification_certificate(),)

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action": {
                "generator_names": [generator.name for generator in self.action.generators],
                "nielsen_source_id": self.action.nielsen_source_id,
            },
            "branch_paths": [path.to_canonical_data() for path in self.branch_paths],
            "coefficient_homotopy": self.coefficient_homotopy.to_canonical_data(),
            "collision_sos": [path.to_canonical_data() for path in self.collision_sos],
            "convention": _B2_HOMOTOPY_CONVENTION,
            "orientation": self.orientation,
            "q": self.q.to_canonical_data(),
            "sheet_paths": [path.to_canonical_data() for path in self.sheet_paths],
            "sheet_permutation": list(self.sheet_permutation),
            "source": NielsenVertex.to_canonical_data(self.source),
            "target": {
                "content_id": content_address(NielsenVertex.to_canonical_data(self.target)),
                "vertex_index": self.target.vertex_index,
            },
            "type": "arbogast.numeric.quadratic_b2_homotopy",
            "word": _word_data(self.word),
        }


@dataclass(frozen=True, slots=True, init=False)
class BraidContinuationResult(NielsenVertex):
    """An exact endpoint reached by a replayed coefficient homotopy."""

    homotopy: QuadraticB2Homotopy
    source: NielsenVertex
    target: NielsenVertex
    word: BraidWord

    schema_version = "arbogast.numeric.braid-continuation-result/v1"

    def __init__(self, homotopy: QuadraticB2Homotopy) -> None:
        if not isinstance(homotopy, QuadraticB2Homotopy):
            raise TypeError("braid continuation result needs a QuadraticB2Homotopy")
        object.__setattr__(self, "model", homotopy.target.model)
        object.__setattr__(self, "base_parameter", homotopy.target.base_parameter)
        object.__setattr__(self, "fiber_points", homotopy.target.fiber_points)
        object.__setattr__(self, "trackings", homotopy.target.trackings)
        object.__setattr__(self, "nielsen_class", homotopy.target.nielsen_class)
        object.__setattr__(self, "vertex_index", homotopy.target.vertex_index)
        object.__setattr__(self, "homotopy", homotopy)
        object.__setattr__(self, "source", homotopy.source)
        object.__setattr__(self, "target", homotopy.target)
        object.__setattr__(self, "word", homotopy.word)
        self.verify()

    @property
    def cover(self) -> NielsenVertex:
        return self

    def verify(self) -> bool:
        NielsenVertex.verify(self)
        self.homotopy.verify()
        if (
            self.source != self.homotopy.source
            or self.target != self.homotopy.target
            or self.word != self.homotopy.word
            or self.model != self.target.model
            or self.base_parameter != self.target.base_parameter
            or self.fiber_points != self.target.fiber_points
            or self.trackings != self.target.trackings
            or self.nielsen_class is not self.target.nielsen_class
            or self.vertex_index != self.target.vertex_index
        ):
            raise NumericVerificationError("braid continuation result endpoints were altered")
        return True

    @property
    def supporting_certificates(self) -> tuple[object, ...]:
        return self.homotopy.supporting_certificates

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "homotopy": self.homotopy.to_canonical_data(),
            "type": "arbogast.numeric.braid_continuation_result",
        }


BraidContinuationOutcome: TypeAlias = NumericalCover | NumericUnknown | UnsupportedNumeric


def braid_continue(
    cover: NumericalCover,
    word: BraidWord,
    *,
    witness: BraidContinuationWitness | QuadraticB2Homotopy | None = None,
) -> BraidContinuationOutcome:
    """Continue the identity or the witnessed normalized quadratic B2 slice.

    Local continuation of sheets in the base variable is not continuation of
    cover coefficients in Hurwitz space.  A nontrivial word therefore remains
    ``NumericUnknown`` unless the exact normalized ``QuadraticB2Homotopy`` is
    supplied.  The older local-sheet witness never authorizes this promotion.
    """

    if not isinstance(cover, NumericalCover):
        raise TypeError("braid_continue expects a NumericalCover")
    normalized_word = BraidWord.coerce(word)
    if len(normalized_word) > MAX_BRAID_WORD_LENGTH:
        return UnsupportedNumeric(
            "braid_continue",
            "braid word exceeds the portable length bound",
            requested={"word_length": len(normalized_word)},
        )
    if len(normalized_word) == 0:
        cover.verify()
        return cover
    if isinstance(witness, QuadraticB2Homotopy):
        witness.verify()
        if witness.source != cover or witness.word != normalized_word:
            raise NumericError("quadratic B2 homotopy is bound to different inputs")
        return BraidContinuationResult(witness)
    local_witness_id: str | None = None
    if witness is not None:
        witness.verify()
        if witness.source != cover or witness.word != normalized_word:
            raise NumericError("braid continuation witness is bound to different inputs")
        local_witness_id = witness.content_id
    requested: dict[str, CanonicalJSON] = {
        "cover_id": cover.content_id,
        "word_length": len(normalized_word),
    }
    if local_witness_id is not None:
        requested["local_witness_id"] = local_witness_id
    return NumericUnknown(
        "braid_continue",
        "nontrivial braid continuation outside the exact normalized quadratic B2 witness "
        "slice remains unknown; local sheet monodromy is not a coefficient homotopy",
        requested=requested,
    )


@dataclass(frozen=True, slots=True)
class WeightedBraidStep:
    source: int
    target: int
    generator: str
    inverse: bool
    cost: Dyadic

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cost": self.cost.to_canonical_data(),
            "generator": self.generator,
            "inverse": self.inverse,
            "source": self.source,
            "target": self.target,
        }


def _cost_table(
    action: BraidAction,
    costs: Mapping[CostKey, CostValue],
) -> tuple[tuple[str, bool, Dyadic], ...]:
    names = tuple(generator.name for generator in action.generators)
    supplied_keys = set(costs)
    symmetric_keys: set[object] = set(names)
    directed_keys: set[object] = {(name, inverse) for name in names for inverse in (False, True)}
    if supplied_keys == symmetric_keys:
        directed = False
    elif supplied_keys == directed_keys:
        directed = True
    else:
        raise NumericError(
            "cost keys must be exactly one string per generator or exactly both signed keys "
            "per generator, with no mixing or extras"
        )
    result: list[tuple[str, bool, Dyadic]] = []
    for generator in action.generators:
        for inverse in (False, True):
            key: CostKey = (generator.name, inverse) if directed else generator.name
            raw = costs[key]
            cost = Dyadic.coerce(raw)
            if cost < 0:
                raise NumericError("braid generator costs must be nonnegative")
            result.append((generator.name, inverse, cost))
    return tuple(result)


def _dijkstra(
    action: BraidAction,
    source: int,
    costs: tuple[tuple[str, bool, Dyadic], ...],
) -> tuple[tuple[Dyadic | None, ...], dict[int, tuple[int, str, bool, Dyadic]]]:
    vertex_count = len(action.nielsen_class)
    distances: list[Dyadic | None] = [None] * vertex_count
    distances[source] = Dyadic.zero()
    predecessors: dict[int, tuple[int, str, bool, Dyadic]] = {}
    heap: list[tuple[Fraction, int]] = [(Fraction(0), source)]
    while heap:
        raw_distance, vertex = heapq.heappop(heap)
        distance = distances[vertex]
        if distance is None or raw_distance != distance.fraction:
            continue
        for name, inverse, cost in costs:
            target = action.step_index(vertex, name, inverse=inverse)
            candidate = distance + cost
            current = distances[target]
            if current is None or candidate < current:
                distances[target] = candidate
                predecessors[target] = (vertex, name, inverse, cost)
                heapq.heappush(heap, (candidate.fraction, target))
    return tuple(distances), predecessors


@dataclass(frozen=True, slots=True, init=False)
class WeightedBraidPlan(NumericSemanticObject):
    """An exact shortest path plus a feasible distance potential proving optimality."""

    action: BraidAction
    source: int
    target: int
    costs: tuple[tuple[str, bool, Dyadic], ...]
    steps: tuple[WeightedBraidStep, ...]
    total_cost: Dyadic
    distances: tuple[Dyadic | None, ...]

    schema_version = "arbogast.numeric.weighted-braid-plan/v1"

    def __init__(
        self,
        action: BraidAction,
        source: int | NielsenTuple,
        target: int | NielsenTuple,
        costs: Mapping[CostKey, CostValue],
    ) -> None:
        if not isinstance(action, BraidAction):
            raise TypeError("weighted braid plan needs a BraidAction")
        action.verify()
        if len(action.nielsen_class) > MAX_GRAPH_VERTICES or (
            len(action.nielsen_class) * len(action.generators) * 2 > MAX_GRAPH_EDGES
        ):
            raise UnsupportedNumericOperation("braid graph exceeds the portable planning bounds")
        source_index = action.index_of(source)
        target_index = action.index_of(target)
        table = _cost_table(action, costs)
        distances, predecessors = _dijkstra(action, source_index, table)
        if distances[target_index] is None:
            raise _UnreachableBraidTarget("target lies outside the source braid component")
        reverse: list[WeightedBraidStep] = []
        current = target_index
        while current != source_index:
            parent, name, inverse, cost = predecessors[current]
            reverse.append(WeightedBraidStep(parent, current, name, inverse, cost))
            current = parent
        steps = tuple(reversed(reverse))
        if (
            sum(len(action.generator_by_name(step.generator).word) for step in steps)
            > MAX_BRAID_WORD_LENGTH
        ):
            raise UnsupportedNumericOperation(
                "optimal braid word exceeds the portable length bound"
            )
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "source", source_index)
        object.__setattr__(self, "target", target_index)
        object.__setattr__(self, "costs", table)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "total_cost", cast(Dyadic, distances[target_index]))
        object.__setattr__(self, "distances", distances)
        self.verify()

    def verify(self) -> bool:
        self.action.verify()
        if len(self.word) > MAX_BRAID_WORD_LENGTH:
            raise NumericVerificationError("weighted plan word exceeds the portable length bound")
        if len(self.distances) != len(self.action.nielsen_class):
            raise NumericVerificationError("weighted plan distance potential has the wrong size")
        if (
            self.distances[self.source] != Dyadic.zero()
            or self.distances[self.target] != self.total_cost
        ):
            raise NumericVerificationError("weighted plan endpoint distances were altered")
        current = self.source
        path_cost = Dyadic.zero()
        cost_lookup = {(name, inverse): cost for name, inverse, cost in self.costs}
        for step in self.steps:
            if step.source != current:
                raise NumericVerificationError("weighted plan steps are not contiguous")
            if (
                self.action.step_index(step.source, step.generator, inverse=step.inverse)
                != step.target
            ):
                raise NumericVerificationError("weighted plan step is not a graph edge")
            if cost_lookup.get((step.generator, step.inverse)) != step.cost:
                raise NumericVerificationError("weighted plan step cost was altered")
            path_cost += step.cost
            current = step.target
        if current != self.target or path_cost != self.total_cost:
            raise NumericVerificationError("weighted plan path does not realize its target cost")
        # Every edge inequality certifies that the displayed distance is a lower bound.
        for vertex, distance in enumerate(self.distances):
            if distance is None:
                continue
            for name, inverse, cost in self.costs:
                neighbor = self.action.step_index(vertex, name, inverse=inverse)
                neighbor_distance = self.distances[neighbor]
                if neighbor_distance is None or neighbor_distance > distance + cost:
                    raise NumericVerificationError(
                        "weighted plan distance potential violates an edge"
                    )
        return True

    @property
    def word(self) -> BraidWord:
        word = BraidWord()
        for step in self.steps:
            generator = self.action.generator_by_name(step.generator).word
            word = word.then(generator.inverse() if step.inverse else generator)
        return word

    @property
    def supporting_certificates(self) -> tuple[object, ...]:
        return (self.action.verification_certificate(),)

    def to_canonical_data(self) -> CanonicalJSON:
        graph: dict[str, CanonicalJSON] = {
            "generators": [
                {
                    "backward": [
                        self.action.step_index(index, generator.name, inverse=True)
                        for index in range(len(self.action.nielsen_class))
                    ],
                    "forward": [
                        self.action.step_index(index, generator.name)
                        for index in range(len(self.action.nielsen_class))
                    ],
                    "name": generator.name,
                    "word": _word_data(generator.word),
                }
                for generator in self.action.generators
            ],
            "nielsen_source_id": self.action.nielsen_source_id,
            "vertex_count": len(self.action.nielsen_class),
        }
        return {
            "costs": [
                {"cost": cost.to_canonical_data(), "generator": name, "inverse": inverse}
                for name, inverse, cost in self.costs
            ],
            "distances": [
                None if distance is None else distance.to_canonical_data()
                for distance in self.distances
            ],
            "graph": graph,
            "source": self.source,
            "steps": [step.to_canonical_data() for step in self.steps],
            "target": self.target,
            "total_cost": self.total_cost.to_canonical_data(),
            "type": "arbogast.numeric.weighted_braid_plan",
            "word": _word_data(self.word),
        }


WeightedPlanOutcome: TypeAlias = WeightedBraidPlan | NumericUnknown | UnsupportedNumeric


def weighted_braid_plan(
    action: BraidAction,
    source: int | NielsenTuple,
    target: int | NielsenTuple,
    costs: Mapping[CostKey, CostValue],
) -> WeightedPlanOutcome:
    """Find and certify the globally minimum exact-cost path in a finite braid graph."""

    try:
        return WeightedBraidPlan(action, source, target, costs)
    except UnsupportedNumericOperation as exc:
        return UnsupportedNumeric(
            "weighted_braid_plan",
            str(exc),
            requested={"target_supplied": True},
        )
    except _UnreachableBraidTarget as exc:
        return NumericUnknown(
            "weighted_braid_plan",
            str(exc),
            requested={"target_supplied": True},
        )


__all__ = [
    "BraidContinuationOutcome",
    "BraidContinuationResult",
    "BraidContinuationWitness",
    "BranchCycleOutcome",
    "BranchLoop",
    "BranchTracking",
    "NielsenVertex",
    "NumericalCover",
    "QuadraticB2Homotopy",
    "VertexOutcome",
    "WeightedBraidPlan",
    "WeightedPlanOutcome",
    "bind_vertex",
    "braid_continue",
    "branch_cycles",
    "weighted_braid_plan",
]
