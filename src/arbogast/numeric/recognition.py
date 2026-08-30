"""Bounded exact algebraic recognition and independently checked exactification."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from typing import TypeAlias

from arbogast.core import CanonicalJSON

from ._schema import NumericSemanticObject, strict_int
from .dyadic import ComplexBall, ComplexDyadic, Dyadic, RealBall
from .errors import NumericError, NumericVerificationError
from .models import ExactPolynomial, NumericPoint
from .outcomes import NumericUnknown, UnsupportedNumeric

PolynomialQ: TypeAlias = tuple[Fraction, ...]
MAX_ENUMERATION_HEIGHT = 16


def _trim(polynomial: PolynomialQ) -> PolynomialQ:
    result = polynomial
    while len(result) > 1 and result[-1] == 0:
        result = result[:-1]
    return result


def _derivative(polynomial: PolynomialQ) -> PolynomialQ:
    return _trim(tuple(index * coefficient for index, coefficient in enumerate(polynomial))[1:])


def _evaluate(polynomial: PolynomialQ, value: Fraction) -> Fraction:
    result = Fraction(0)
    for coefficient in reversed(polynomial):
        result = result * value + coefficient
    return result


def _divmod(left: PolynomialQ, right: PolynomialQ) -> tuple[PolynomialQ, PolynomialQ]:
    numerator = list(_trim(left))
    denominator = _trim(right)
    if denominator == (Fraction(0),):
        raise ZeroDivisionError("polynomial division by zero")
    if len(numerator) < len(denominator):
        return ((Fraction(0),), tuple(numerator))
    quotient = [Fraction(0)] * (len(numerator) - len(denominator) + 1)
    while len(numerator) >= len(denominator) and any(numerator):
        offset = len(numerator) - len(denominator)
        coefficient = numerator[-1] / denominator[-1]
        quotient[offset] = coefficient
        for index, divisor in enumerate(denominator):
            numerator[offset + index] -= coefficient * divisor
        while len(numerator) > 1 and numerator[-1] == 0:
            numerator.pop()
    return (_trim(tuple(quotient)), _trim(tuple(numerator)))


def _sturm(polynomial: PolynomialQ) -> tuple[PolynomialQ, ...]:
    first = _trim(polynomial)
    second = _derivative(first)
    if second == (Fraction(0),):
        return (first,)
    sequence = [first, second]
    while sequence[-1] != (Fraction(0),):
        _, remainder = _divmod(sequence[-2], sequence[-1])
        if remainder == (Fraction(0),):
            break
        sequence.append(tuple(-coefficient for coefficient in remainder))
    return tuple(sequence)


def _variations(sequence: tuple[PolynomialQ, ...], value: Fraction) -> int:
    signs: list[int] = []
    for polynomial in sequence:
        evaluation = _evaluate(polynomial, value)
        if evaluation:
            signs.append(1 if evaluation > 0 else -1)
    return sum(left != right for left, right in pairwise(signs))


def _root_count(polynomial: tuple[int, ...], interval: RealBall) -> int:
    rational = tuple(Fraction(coefficient) for coefficient in polynomial)
    lower = interval.lower.fraction
    upper = interval.upper.fraction
    if len(rational) == 2:
        root = -rational[0] / rational[1]
        return int(lower <= root <= upper)
    if lower == upper:
        return int(_evaluate(rational, lower) == 0)
    if lower > upper:
        return -1
    if _evaluate(rational, lower) == 0 or _evaluate(rational, upper) == 0:
        # Canonical irreducible quadratics have no rational roots, so reaching
        # this branch indicates malformed candidate data rather than a closed
        # endpoint ambiguity.
        return -1
    sequence = _sturm(rational)
    return _variations(sequence, lower) - _variations(sequence, upper)


def _canonical_minimal_polynomial(coefficients: tuple[int, ...]) -> bool:
    if len(coefficients) not in {2, 3} or coefficients[-1] <= 0:
        return False
    if math.gcd(*(abs(coefficient) for coefficient in coefficients)) != 1:
        return False
    if len(coefficients) == 2:
        return True
    if coefficients[0] == 0:
        return False
    constant, linear, leading = coefficients
    discriminant = linear * linear - 4 * leading * constant
    if discriminant < 0:
        return True
    root = math.isqrt(discriminant)
    return root * root != discriminant


@dataclass(frozen=True, slots=True, init=False)
class RecognitionBounds(NumericSemanticObject):
    """Finite search bounds; the automatic portable search supports degree at most two."""

    max_degree: int
    max_height: int

    schema_version = "arbogast.numeric.recognition-bounds/v1"

    def __init__(self, max_degree: int = 2, max_height: int = 8) -> None:
        degree = strict_int(max_degree, "recognition degree", minimum=1)
        height = strict_int(max_height, "recognition height", minimum=1)
        if degree > 64 or height > 1 << 256:
            raise NumericError("recognition bounds exceed the portable serialized limits")
        object.__setattr__(self, "max_degree", degree)
        object.__setattr__(self, "max_height", height)

    def verify(self) -> bool:
        if RecognitionBounds(self.max_degree, self.max_height) != self:
            raise NumericVerificationError("recognition bounds were altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "max_degree": self.max_degree,
            "max_height": self.max_height,
            "type": "arbogast.numeric.recognition_bounds",
        }


@dataclass(frozen=True, slots=True, init=False)
class AlgebraicCandidate(NumericSemanticObject):
    """One primitive irreducible polynomial with exactly one root in a real ball."""

    source: ComplexBall
    minimal_polynomial: tuple[int, ...]
    isolating_interval: RealBall
    bounds: RecognitionBounds

    schema_version = "arbogast.numeric.algebraic-candidate/v1"

    def __init__(
        self,
        source: ComplexBall,
        minimal_polynomial: tuple[int, ...],
        isolating_interval: RealBall,
        bounds: RecognitionBounds,
    ) -> None:
        if not isinstance(source, ComplexBall) or not isinstance(isolating_interval, RealBall):
            raise TypeError("algebraic candidate needs complex and real ball witnesses")
        if not isinstance(bounds, RecognitionBounds):
            raise TypeError("algebraic candidate needs RecognitionBounds")
        polynomial = tuple(
            strict_int(coefficient, "minimal-polynomial coefficient")
            for coefficient in minimal_polynomial
        )
        if not _canonical_minimal_polynomial(polynomial):
            raise NumericError("minimal polynomial is not canonical primitive irreducible data")
        degree = len(polynomial) - 1
        if (
            degree > bounds.max_degree
            or max(abs(value) for value in polynomial) > bounds.max_height
        ):
            raise NumericError("candidate exceeds its declared recognition bounds")
        if source.center.imag != Dyadic.zero():
            raise NumericError(
                "portable algebraic recognition currently requires a real-centered ball"
            )
        if (
            isolating_interval.center != source.center.real
            or isolating_interval.radius > source.radius
        ):
            raise NumericError(
                "isolating interval is not contained in the source ball's real slice"
            )
        if _root_count(polynomial, isolating_interval) != 1:
            raise NumericError("minimal polynomial does not have exactly one isolated root")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "minimal_polynomial", polynomial)
        object.__setattr__(self, "isolating_interval", isolating_interval)
        object.__setattr__(self, "bounds", bounds)

    @property
    def degree(self) -> int:
        return len(self.minimal_polynomial) - 1

    @property
    def height(self) -> int:
        return max(abs(coefficient) for coefficient in self.minimal_polynomial)

    @property
    def rational_value(self) -> Fraction | None:
        if self.degree != 1:
            return None
        return Fraction(-self.minimal_polynomial[0], self.minimal_polynomial[1])

    def verify(self) -> bool:
        self.source.verify()
        self.isolating_interval.verify()
        self.bounds.verify()
        replay = AlgebraicCandidate(
            self.source,
            self.minimal_polynomial,
            self.isolating_interval,
            self.bounds,
        )
        if replay != self:
            raise NumericVerificationError("algebraic candidate witness was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "bounds": self.bounds.to_canonical_data(),
            "isolating_interval": self.isolating_interval.to_canonical_data(),
            "minimal_polynomial": list(self.minimal_polynomial),
            "source": self.source.to_canonical_data(),
            "type": "arbogast.numeric.algebraic_candidate",
        }


RecognitionOutcome: TypeAlias = AlgebraicCandidate | NumericUnknown | UnsupportedNumeric


def _candidate_polynomials(bounds: RecognitionBounds) -> tuple[tuple[int, ...], ...]:
    height = bounds.max_height
    candidates: list[tuple[int, ...]] = []
    for degree in range(1, bounds.max_degree + 1):
        for coefficients in itertools.product(range(-height, height + 1), repeat=degree + 1):
            polynomial = tuple(coefficients)
            if _canonical_minimal_polynomial(polynomial):
                candidates.append(polynomial)
    return tuple(candidates)


def recognize(
    value: ComplexBall | RealBall,
    bounds: RecognitionBounds | None = None,
) -> RecognitionOutcome:
    """Exhaust a bounded degree-one/two polynomial search with Sturm replay."""

    if isinstance(value, RealBall):
        source = ComplexBall(ComplexDyadic(value.center), value.radius)
    elif isinstance(value, ComplexBall):
        source = value
    else:
        raise TypeError("recognize expects a ComplexBall or RealBall")
    limits = RecognitionBounds() if bounds is None else bounds
    if not isinstance(limits, RecognitionBounds):
        raise TypeError("recognition bounds must be RecognitionBounds")
    if limits.max_degree > 2 or limits.max_height > MAX_ENUMERATION_HEIGHT:
        return UnsupportedNumeric(
            "recognize",
            "portable exhaustive recognition supports degree at most 2 and height at most 16",
            requested={
                "max_degree": limits.max_degree,
                "max_height": limits.max_height,
                "value_id": source.content_id,
            },
        )
    if source.center.imag != Dyadic.zero():
        return UnsupportedNumeric(
            "recognize",
            "portable automatic recognition currently handles real-centered balls only",
            requested={"value_id": source.content_id},
        )
    interval = RealBall(source.center.real, source.radius)
    matches = tuple(
        polynomial
        for polynomial in _candidate_polynomials(limits)
        if _root_count(polynomial, interval) == 1
    )
    if len(matches) != 1:
        return NumericUnknown(
            "recognize",
            (
                "bounded recognition found no compatible polynomial"
                if not matches
                else "bounded recognition is ambiguous"
            ),
            requested={
                "compatible_polynomials": len(matches),
                "max_degree": limits.max_degree,
                "max_height": limits.max_height,
                "value_id": source.content_id,
            },
        )
    return AlgebraicCandidate(source, matches[0], interval, limits)


def _rational_polynomial(polynomial: ExactPolynomial) -> PolynomialQ | None:
    if polynomial.nvariables != 1:
        return None
    coefficients = [Fraction(0)] * (polynomial.total_degree + 1)
    for exponent, coefficient in polynomial.terms:
        if coefficient.imag != Dyadic.zero():
            return None
        coefficients[exponent[0]] += coefficient.real.fraction
    return _trim(tuple(coefficients))


@dataclass(frozen=True, slots=True, init=False)
class ExactificationResult(NumericSemanticObject):
    """An algebraic coordinate whose minimal polynomial divides every system equation."""

    point: NumericPoint
    candidate: AlgebraicCandidate

    schema_version = "arbogast.numeric.exactification-result/v1"

    def __init__(self, point: NumericPoint, candidate: AlgebraicCandidate) -> None:
        if not isinstance(point, NumericPoint) or not isinstance(candidate, AlgebraicCandidate):
            raise TypeError("exactification requires a NumericPoint and AlgebraicCandidate")
        if point.system.nvariables != 1 or len(point.coordinates) != 1:
            raise NumericError("portable exactification currently supports one coordinate")
        if candidate.source != point.coordinates[0]:
            raise NumericError("candidate is not bound to the point enclosure")
        divisor = tuple(Fraction(coefficient) for coefficient in candidate.minimal_polynomial)
        for polynomial in point.system.polynomials:
            rational = _rational_polynomial(polynomial)
            if rational is None:
                raise NumericError("exactification requires real univariate dyadic equations")
            _, remainder = _divmod(rational, divisor)
            if remainder != (Fraction(0),):
                raise NumericError("candidate minimal polynomial does not divide a system equation")
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "candidate", candidate)

    def verify(self) -> bool:
        self.point.verify()
        self.candidate.verify()
        if ExactificationResult(self.point, self.candidate) != self:
            raise NumericVerificationError("exactification witness was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "candidate": self.candidate.to_canonical_data(),
            "point": self.point.to_canonical_data(),
            "type": "arbogast.numeric.exactification_result",
        }


ExactificationOutcome: TypeAlias = ExactificationResult | NumericUnknown | UnsupportedNumeric


def exactify(
    point: NumericPoint,
    *,
    candidate: AlgebraicCandidate | None = None,
    bounds: RecognitionBounds | None = None,
) -> ExactificationOutcome:
    """Recognize one coordinate and prove exact polynomial substitution by divisibility."""

    if not isinstance(point, NumericPoint):
        raise TypeError("exactify expects a NumericPoint")
    if candidate is not None and bounds is not None:
        raise NumericError(
            "an explicit algebraic candidate and independent recognition bounds cannot be "
            "supplied together"
        )
    if point.system.nvariables != 1:
        return UnsupportedNumeric(
            "exactify",
            "portable exactification currently supports univariate points only",
            requested={"point_id": point.content_id},
        )
    recognized: RecognitionOutcome = (
        recognize(point.coordinates[0], bounds) if candidate is None else candidate
    )
    if isinstance(recognized, UnsupportedNumeric):
        return recognized
    if isinstance(recognized, NumericUnknown):
        return NumericUnknown(
            "exactify",
            "coordinate recognition did not produce a unique algebraic candidate",
            requested={"point_id": point.content_id},
        )
    try:
        return ExactificationResult(point, recognized)
    except NumericError as exc:
        return NumericUnknown(
            "exactify",
            str(exc),
            requested={
                "candidate_id": recognized.content_id,
                "point_id": point.content_id,
            },
        )


__all__ = [
    "AlgebraicCandidate",
    "ExactificationOutcome",
    "ExactificationResult",
    "RecognitionBounds",
    "RecognitionOutcome",
    "exactify",
    "recognize",
]
