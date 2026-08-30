"""Portable exact contraction witnesses for bounded path continuation."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from typing import TypeAlias

from arbogast.core import CanonicalJSON

from ._schema import MAX_TUBE_STEPS, NumericSemanticObject
from .dyadic import ComplexBall, ComplexDyadic, Dyadic, RealBall
from .errors import NumericError, NumericVerificationError, UnsupportedNumericOperation
from .models import NumericPoint, ParameterPath, PolynomialFamily, PolynomialSystem
from .outcomes import NumericUnknown, UnsupportedNumeric

ComplexMatrix: TypeAlias = tuple[tuple[ComplexDyadic, ...], ...]


def _coerce_matrix(
    value: tuple[tuple[ComplexDyadic | Dyadic | int | Fraction, ...], ...],
    dimension: int,
) -> ComplexMatrix:
    rows = tuple(tuple(ComplexDyadic.coerce(entry) for entry in row) for row in value)
    if len(rows) != dimension or any(len(row) != dimension for row in rows):
        raise NumericError("inverse-Jacobian witness has the wrong square shape")
    return rows


def _ball_sum(values: tuple[ComplexBall, ...]) -> ComplexBall:
    result = ComplexBall.point(0)
    for value in values:
        result = result + value
    return result


def _upper_modulus(value: ComplexBall) -> Dyadic:
    return value.center.l1_norm() + value.radius


def _segment_ball(start: ComplexDyadic, end: ComplexDyadic) -> ComplexBall:
    two = Dyadic(2)
    center = ComplexDyadic(
        (start.real + end.real) / two,
        (start.imag + end.imag) / two,
    )
    delta = end - start
    return ComplexBall(center, delta.l1_norm() / two)


def _matrix_times_vector(
    matrix: ComplexMatrix, vector: tuple[ComplexBall, ...]
) -> tuple[ComplexBall, ...]:
    return tuple(
        _ball_sum(
            tuple(
                ComplexBall.point(coefficient) * entry
                for coefficient, entry in zip(row, vector, strict=True)
            )
        )
        for row in matrix
    )


def _defect_matrix(
    inverse: ComplexMatrix,
    jacobian: tuple[tuple[ComplexBall, ...], ...],
) -> tuple[tuple[ComplexBall, ...], ...]:
    dimension = len(inverse)
    result: list[tuple[ComplexBall, ...]] = []
    for row in range(dimension):
        output_row: list[ComplexBall] = []
        for column in range(dimension):
            product = _ball_sum(
                tuple(
                    ComplexBall.point(inverse[row][inner]) * jacobian[inner][column]
                    for inner in range(dimension)
                )
            )
            identity = ComplexBall.point(1 if row == column else 0)
            output_row.append(identity + ComplexBall(-product.center, product.radius))
        result.append(tuple(output_row))
    return tuple(result)


@dataclass(frozen=True, slots=True, init=False)
class ContinuationStep(NumericSemanticObject):
    """A uniform Banach-contraction tube over one exact parameter segment."""

    family: PolynomialFamily
    parameter_start: ComplexDyadic
    parameter_end: ComplexDyadic
    domain: tuple[ComplexBall, ...]
    inverse_jacobian: ComplexMatrix
    residual_bound: Dyadic
    contraction_bound: Dyadic

    schema_version = "arbogast.numeric.continuation-step/v1"

    def __init__(
        self,
        family: PolynomialFamily,
        parameter_start: ComplexDyadic | Dyadic | int | Fraction,
        parameter_end: ComplexDyadic | Dyadic | int | Fraction,
        domain: tuple[ComplexBall, ...],
        inverse_jacobian: tuple[tuple[ComplexDyadic | Dyadic | int | Fraction, ...], ...],
    ) -> None:
        if not isinstance(family, PolynomialFamily):
            raise TypeError("continuation step family must be a PolynomialFamily")
        if len(family.polynomials) != family.nvariables:
            raise UnsupportedNumericOperation(
                "contraction replay currently requires a square family"
            )
        start = ComplexDyadic.coerce(parameter_start)
        end = ComplexDyadic.coerce(parameter_end)
        if start == end:
            raise NumericError("continuation step parameter segment is stationary")
        enclosure = tuple(domain)
        if len(enclosure) != family.nvariables or any(
            not isinstance(ball, ComplexBall) for ball in enclosure
        ):
            raise NumericError("continuation domain has the wrong dimension or type")
        radii = {ball.radius for ball in enclosure}
        if len(radii) != 1 or next(iter(radii)) <= 0:
            raise NumericError("portable contraction replay requires one positive uniform radius")
        inverse = _coerce_matrix(inverse_jacobian, family.nvariables)
        residual, contraction = self._bounds(family, start, end, enclosure, inverse)
        radius = enclosure[0].radius
        if contraction >= 1:
            raise NumericError("continuation witness is not a strict contraction")
        if residual + contraction * radius > radius:
            raise NumericError("continuation witness does not map its tube into itself")
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "parameter_start", start)
        object.__setattr__(self, "parameter_end", end)
        object.__setattr__(self, "domain", enclosure)
        object.__setattr__(self, "inverse_jacobian", inverse)
        object.__setattr__(self, "residual_bound", residual)
        object.__setattr__(self, "contraction_bound", contraction)

    @staticmethod
    def _bounds(
        family: PolynomialFamily,
        start: ComplexDyadic,
        end: ComplexDyadic,
        domain: tuple[ComplexBall, ...],
        inverse: ComplexMatrix,
    ) -> tuple[Dyadic, Dyadic]:
        parameter = _segment_ball(start, end)
        evaluation_point = (*domain, parameter)
        center_point = (*(ComplexBall.point(ball.center) for ball in domain), parameter)
        residual_vector = tuple(
            polynomial.evaluate_ball(center_point) for polynomial in family.polynomials
        )
        corrected = _matrix_times_vector(inverse, residual_vector)
        residual = max((_upper_modulus(value) for value in corrected), default=Dyadic.zero())
        jacobian = tuple(
            tuple(
                polynomial.derivative(column).evaluate_ball(evaluation_point)
                for column in range(family.nvariables)
            )
            for polynomial in family.polynomials
        )
        defect = _defect_matrix(inverse, jacobian)
        contraction = max(
            (sum((_upper_modulus(value) for value in row), start=Dyadic.zero()) for row in defect),
            default=Dyadic.zero(),
        )
        return residual, contraction

    @property
    def radius(self) -> Dyadic:
        return self.domain[0].radius

    def verify(self) -> bool:
        if not isinstance(self.family, PolynomialFamily):
            raise NumericVerificationError("continuation step has no polynomial family")
        self.family.verify()
        if len(self.family.polynomials) != self.family.nvariables:
            raise NumericVerificationError("continuation step family is not square")
        if not isinstance(self.parameter_start, ComplexDyadic) or not isinstance(
            self.parameter_end, ComplexDyadic
        ):
            raise NumericVerificationError("continuation endpoints are not complex dyadics")
        self.parameter_start.verify()
        self.parameter_end.verify()
        if self.parameter_start == self.parameter_end:
            raise NumericVerificationError("continuation parameter segment is stationary")
        if len(self.domain) != self.family.nvariables or any(
            not isinstance(ball, ComplexBall) for ball in self.domain
        ):
            raise NumericVerificationError("continuation domain has the wrong shape")
        if any(not ball.verify() for ball in self.domain):
            raise NumericVerificationError("continuation domain failed replay")
        radii = {ball.radius for ball in self.domain}
        if len(radii) != 1 or next(iter(radii)) <= 0:
            raise NumericVerificationError("continuation domain lacks a positive uniform radius")
        if len(self.inverse_jacobian) != self.family.nvariables or any(
            len(row) != self.family.nvariables
            or any(not isinstance(entry, ComplexDyadic) for entry in row)
            for row in self.inverse_jacobian
        ):
            raise NumericVerificationError("inverse-Jacobian witness has the wrong shape")
        if any(not entry.verify() for row in self.inverse_jacobian for entry in row):
            raise NumericVerificationError("inverse-Jacobian entry failed replay")
        self.residual_bound.verify()
        self.contraction_bound.verify()
        expected_residual, expected_contraction = self._bounds(
            self.family,
            self.parameter_start,
            self.parameter_end,
            self.domain,
            self.inverse_jacobian,
        )
        if (
            expected_residual != self.residual_bound
            or expected_contraction != self.contraction_bound
        ):
            raise NumericVerificationError("continuation contraction bounds were altered")
        if self.contraction_bound >= 1:
            raise NumericVerificationError("continuation step is not a strict contraction")
        if self.residual_bound + self.contraction_bound * self.radius > self.radius:
            raise NumericVerificationError("continuation step fails the self-map inequality")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "contraction_bound": self.contraction_bound.to_canonical_data(),
            "domain": [ball.to_canonical_data() for ball in self.domain],
            "family": self.family.to_canonical_data(),
            "inverse_jacobian": [
                [entry.to_canonical_data() for entry in row] for row in self.inverse_jacobian
            ],
            "parameter_end": self.parameter_end.to_canonical_data(),
            "parameter_start": self.parameter_start.to_canonical_data(),
            "residual_bound": self.residual_bound.to_canonical_data(),
            "type": "arbogast.numeric.continuation_step",
        }


def _nested_domains(
    left: tuple[ComplexBall, ...],
    right: tuple[ComplexBall, ...],
) -> bool:
    return all(a.contains(b) for a, b in zip(left, right, strict=True)) or all(
        b.contains(a) for a, b in zip(left, right, strict=True)
    )


@dataclass(frozen=True, slots=True, init=False)
class ContinuationTube(NumericSemanticObject):
    """A dependency-closed sequence of compatible uniform contraction steps."""

    family: PolynomialFamily
    path: ParameterPath
    start_point: NumericPoint
    steps: tuple[ContinuationStep, ...]

    schema_version = "arbogast.numeric.continuation-tube/v1"

    def __init__(
        self,
        family: PolynomialFamily,
        path: ParameterPath,
        start_point: NumericPoint,
        steps: tuple[ContinuationStep, ...],
    ) -> None:
        if not isinstance(family, PolynomialFamily) or not isinstance(path, ParameterPath):
            raise TypeError("continuation tube needs a family and parameter path")
        if not isinstance(start_point, NumericPoint):
            raise TypeError("continuation tube start must be a NumericPoint")
        normalized_steps = tuple(steps)
        if not normalized_steps or len(normalized_steps) > MAX_TUBE_STEPS:
            raise NumericError("continuation tube has an unsupported step count")
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "start_point", start_point)
        object.__setattr__(self, "steps", normalized_steps)
        self.verify()

    def verify(self) -> bool:
        self.family.verify()
        self.path.verify()
        self.start_point.verify()
        if self.start_point.system != self.family.fiber(self.path.start):
            raise NumericVerificationError("continuation start point is bound to the wrong fiber")
        if len(self.steps) != self.path.segment_count:
            raise NumericVerificationError("tube steps do not match the exact path segmentation")
        for index, step in enumerate(self.steps):
            step.verify()
            if step.family != self.family:
                raise NumericVerificationError("continuation step uses a different family")
            if (
                step.parameter_start != self.path.vertices[index]
                or step.parameter_end != self.path.vertices[index + 1]
            ):
                raise NumericVerificationError("continuation step has the wrong path endpoints")
        if not all(
            source.contains(domain)
            for source, domain in zip(
                self.start_point.coordinates,
                self.steps[0].domain,
                strict=True,
            )
        ):
            raise NumericVerificationError(
                "start enclosure does not contain the first certified tube"
            )
        if any(
            not _nested_domains(left.domain, right.domain) for left, right in pairwise(self.steps)
        ):
            raise NumericVerificationError(
                "adjacent continuation domains need a nesting witness at their shared endpoint"
            )
        return True

    @property
    def endpoint(self) -> NumericPoint:
        return NumericPoint(self.family.fiber(self.path.end), self.steps[-1].domain)

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "family": self.family.to_canonical_data(),
            "path": self.path.to_canonical_data(),
            "start_point": self.start_point.to_canonical_data(),
            "steps": [step.to_canonical_data() for step in self.steps],
            "type": "arbogast.numeric.continuation_tube",
        }


@dataclass(frozen=True, slots=True, init=False)
class ContinuationResult(NumericSemanticObject):
    """A certified endpoint enclosure for one uniquely tracked solution branch."""

    tube: ContinuationTube
    endpoint: NumericPoint

    schema_version = "arbogast.numeric.continuation-result/v1"

    def __init__(self, tube: ContinuationTube) -> None:
        if not isinstance(tube, ContinuationTube):
            raise TypeError("continuation result requires a ContinuationTube")
        tube.verify()
        object.__setattr__(self, "tube", tube)
        object.__setattr__(self, "endpoint", tube.endpoint)

    def verify(self) -> bool:
        self.tube.verify()
        self.endpoint.verify()
        if self.endpoint != self.tube.endpoint:
            raise NumericVerificationError("continuation endpoint enclosure was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "endpoint": self.endpoint.to_canonical_data(),
            "tube": self.tube.to_canonical_data(),
            "type": "arbogast.numeric.continuation_result",
        }


ContinuationOutcome: TypeAlias = ContinuationResult | NumericUnknown | UnsupportedNumeric


def continue_path(
    system: PolynomialFamily | PolynomialSystem,
    point: NumericPoint,
    path: ParameterPath,
    *,
    tube: ContinuationTube | None = None,
) -> ContinuationOutcome:
    """Certify one isolated branch along an exact path from an explicit tube witness."""

    if isinstance(system, PolynomialSystem):
        return UnsupportedNumeric(
            "continue_path",
            "a static polynomial system has no pinned parameter family",
            requested={"system_id": system.content_id},
            supported=("PolynomialFamily with an explicit ContinuationTube",),
        )
    if not isinstance(system, PolynomialFamily):
        raise TypeError("system must be a PolynomialFamily or PolynomialSystem")
    if not isinstance(point, NumericPoint) or not isinstance(path, ParameterPath):
        raise TypeError("continue_path requires a NumericPoint and ParameterPath")
    if tube is None:
        return NumericUnknown(
            "continue_path",
            "portable continuation requires an explicit contraction-tube witness",
            requested={
                "family_id": system.content_id,
                "path_id": path.content_id,
                "point_id": point.content_id,
            },
        )
    tube.verify()
    if tube.family != system or tube.path != path or tube.start_point != point:
        raise NumericError("continuation tube is bound to different inputs")
    return ContinuationResult(tube)


@dataclass(frozen=True, slots=True, init=False)
class ConditionBound(RealBall):
    """An exact row-sum upper bound for a square Jacobian condition number."""

    system: PolynomialSystem
    point: NumericPoint
    inverse_jacobian: ComplexMatrix
    jacobian_norm: Dyadic
    inverse_norm: Dyadic

    schema_version = "arbogast.numeric.condition-bound/v1"

    def __init__(
        self,
        system: PolynomialSystem,
        point: NumericPoint,
        inverse_jacobian: tuple[tuple[ComplexDyadic | Dyadic | int | Fraction, ...], ...],
    ) -> None:
        if not isinstance(system, PolynomialSystem) or not isinstance(point, NumericPoint):
            raise TypeError("condition witness requires a system and point")
        if system.nequations != system.nvariables:
            raise NumericError("condition replay requires a square system")
        if point.system != system:
            raise NumericError("condition point is bound to a different system")
        inverse = _coerce_matrix(inverse_jacobian, system.nvariables)
        centers = tuple(coordinate.center for coordinate in point.coordinates)
        jacobian = tuple(
            tuple(
                polynomial.derivative(column).evaluate(centers)
                for column in range(system.nvariables)
            )
            for polynomial in system.polynomials
        )
        for row in range(system.nvariables):
            for column in range(system.nvariables):
                entry = ComplexDyadic(0)
                for inner in range(system.nvariables):
                    entry = entry + inverse[row][inner] * jacobian[inner][column]
                if entry != ComplexDyadic(1 if row == column else 0):
                    raise NumericError(
                        "supplied matrix is not an exact inverse of the center Jacobian"
                    )
        jacobian_norm = max(
            (sum((entry.l1_norm() for entry in row), start=Dyadic.zero()) for row in jacobian),
            default=Dyadic.zero(),
        )
        inverse_norm = max(
            (sum((entry.l1_norm() for entry in row), start=Dyadic.zero()) for row in inverse),
            default=Dyadic.zero(),
        )
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "inverse_jacobian", inverse)
        object.__setattr__(self, "jacobian_norm", jacobian_norm)
        object.__setattr__(self, "inverse_norm", inverse_norm)
        object.__setattr__(self, "center", jacobian_norm * inverse_norm)
        object.__setattr__(self, "radius", Dyadic.zero())

    @property
    def bound(self) -> RealBall:
        return RealBall(self.center, self.radius)

    def verify(self) -> bool:
        self.system.verify()
        self.point.verify()
        if any(not entry.verify() for row in self.inverse_jacobian for entry in row):
            raise NumericVerificationError("condition inverse-Jacobian entry failed replay")
        self.jacobian_norm.verify()
        self.inverse_norm.verify()
        self.center.verify()
        self.radius.verify()
        replay = ConditionBound(self.system, self.point, self.inverse_jacobian)
        if replay != self:
            raise NumericVerificationError("condition-number bound was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "bound": self.bound.to_canonical_data(),
            "inverse_jacobian": [
                [entry.to_canonical_data() for entry in row] for row in self.inverse_jacobian
            ],
            "inverse_norm": self.inverse_norm.to_canonical_data(),
            "jacobian_norm": self.jacobian_norm.to_canonical_data(),
            "point": self.point.to_canonical_data(),
            "system": self.system.to_canonical_data(),
            "type": "arbogast.numeric.condition_bound",
        }


ConditionOutcome: TypeAlias = ConditionBound | NumericUnknown | UnsupportedNumeric


def condition_number(
    system: PolynomialSystem,
    point: NumericPoint,
    *,
    inverse_jacobian: tuple[tuple[ComplexDyadic | Dyadic | int | Fraction, ...], ...] | None = None,
) -> ConditionOutcome:
    """Return an exact Jacobian condition bound, never a floating estimate."""

    if not isinstance(system, PolynomialSystem) or not isinstance(point, NumericPoint):
        raise TypeError("condition_number requires a PolynomialSystem and NumericPoint")
    if system.nequations != system.nvariables:
        return UnsupportedNumeric(
            "condition_number",
            "portable Jacobian condition replay requires a square system",
            requested={"system_id": system.content_id},
        )
    if inverse_jacobian is None:
        return NumericUnknown(
            "condition_number",
            "an exact inverse-Jacobian witness was not supplied",
            requested={"point_id": point.content_id, "system_id": system.content_id},
        )
    return ConditionBound(system, point, inverse_jacobian)


__all__ = [
    "ConditionBound",
    "ConditionOutcome",
    "ContinuationOutcome",
    "ContinuationResult",
    "ContinuationStep",
    "ContinuationTube",
    "condition_number",
    "continue_path",
]
