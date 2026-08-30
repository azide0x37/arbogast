"""Exact normalized three-point covers for the bounded p-adic reduction lane.

The initial slice deliberately supports polynomial maps
``P^1_Q -> P^1_Q`` whose fibres over ``0`` and ``1`` split into displayed
rational linear factors.  Infinity is represented projectively rather than by
a backend convention.  This is independent of :mod:`arbogast.numeric`'s
quadratic ``ExactCover``: only the exact polynomial and its already-public
generic-degree witness are reused.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from math import gcd, isqrt
from typing import TYPE_CHECKING, TypeAlias, cast

from arbogast.cert import VerificationCertificate
from arbogast.core import CanonicalJSON
from arbogast.numeric import ExactPolynomial, GenericDegreeWitness

from ._schema import (
    MAX_CANONICAL_INTEGER_BITS,
    MAX_LOCAL_DEGREE,
    PAdicSchemaObject,
    canonical_label,
    strict_int,
)
from .certificate import PAdicPayloadReplay, padic_payload_verifier
from .errors import PAdicValidationError, PAdicVerificationError

if TYPE_CHECKING:
    from .results import Certified

PolynomialQ: TypeAlias = tuple[Fraction, ...]
FPPolynomial: TypeAlias = tuple[int, ...]

MAX_FACTORIZATION_PRIME = 97
MAX_FACTORIZATION_DEGREE = 32
MAX_FACTORIZATION_FACTORS = 16
MAX_FACTORIZATION_WORK = 4096


def _trim(polynomial: PolynomialQ) -> PolynomialQ:
    result = polynomial or (Fraction(0),)
    while len(result) > 1 and result[-1] == 0:
        result = result[:-1]
    return result


def _multiply(left: PolynomialQ, right: PolynomialQ) -> PolynomialQ:
    result = [Fraction(0)] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            result[left_index + right_index] += left_value * right_value
    return _trim(tuple(result))


def _power(polynomial: PolynomialQ, exponent: int) -> PolynomialQ:
    result: PolynomialQ = (Fraction(1),)
    base = polynomial
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = _multiply(result, base)
        base = _multiply(base, base)
        remaining >>= 1
    return result


def _scale(polynomial: PolynomialQ, scalar: Fraction) -> PolynomialQ:
    return _trim(tuple(scalar * coefficient for coefficient in polynomial))


def _subtract_constant(polynomial: PolynomialQ, value: Fraction) -> PolynomialQ:
    result = list(polynomial)
    result[0] -= value
    return _trim(tuple(result))


def _univariate_rational(polynomial: ExactPolynomial) -> PolynomialQ | None:
    if polynomial.nvariables != 1:
        return None
    coefficients = [Fraction(0)] * (polynomial.total_degree + 1)
    for exponent, coefficient in polynomial.terms:
        if not coefficient.imag.is_zero:
            return None
        coefficients[exponent[0]] += coefficient.real.fraction
    return _trim(tuple(coefficients))


def _fraction(value: int | Fraction, name: str, *, nonzero: bool = False) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise TypeError(f"{name} must be an integer or Fraction")
    result = Fraction(value)
    if (
        result.numerator.bit_length() > MAX_CANONICAL_INTEGER_BITS
        or result.denominator.bit_length() > MAX_CANONICAL_INTEGER_BITS
    ):
        raise PAdicValidationError(f"{name} exceeds the portable rational bound")
    if nonzero and result == 0:
        raise PAdicValidationError(f"{name} must be nonzero")
    return result


def _fraction_data(value: Fraction) -> dict[str, CanonicalJSON]:
    return {"denominator": value.denominator, "numerator": value.numerator}


def _optional_label(value: str | None, name: str) -> str | None:
    return None if value is None else canonical_label(value, name)


class BranchValue(StrEnum):
    """The fixed normalized target branch values ``0``, ``1``, and infinity."""

    ZERO = "zero"
    ONE = "one"
    INFINITY = "infinity"


_BRANCH_ORDER = {
    BranchValue.ZERO: 0,
    BranchValue.ONE: 1,
    BranchValue.INFINITY: 2,
}


def _branch(value: BranchValue | str) -> BranchValue:
    if not isinstance(value, (BranchValue, str)):
        raise TypeError("branch value must be a BranchValue or string")
    try:
        return BranchValue(value)
    except ValueError as exc:
        raise PAdicValidationError("branch value must be zero, one, or infinity") from exc


@dataclass(frozen=True, slots=True, init=False)
class ProjectiveRationalPoint(PAdicSchemaObject):
    """A canonical point of ``P^1(Q)`` with infinity encoded as ``(1:0)``."""

    numerator: int
    denominator: int

    schema_version = "arbogast.padic.projective-rational-point/v1"

    def __init__(self, numerator: int, denominator: int = 1) -> None:
        raw_numerator = strict_int(numerator, "projective numerator")
        raw_denominator = strict_int(denominator, "projective denominator")
        if (
            raw_numerator.bit_length() > MAX_CANONICAL_INTEGER_BITS
            or raw_denominator.bit_length() > MAX_CANONICAL_INTEGER_BITS
        ):
            raise PAdicValidationError("projective coordinate exceeds the portable integer bound")
        if raw_denominator == 0:
            if raw_numerator == 0:
                raise PAdicValidationError("(0:0) is not a projective point")
            normalized_numerator, normalized_denominator = 1, 0
        else:
            value = Fraction(raw_numerator, raw_denominator)
            normalized_numerator = value.numerator
            normalized_denominator = value.denominator
        object.__setattr__(self, "numerator", normalized_numerator)
        object.__setattr__(self, "denominator", normalized_denominator)

    @classmethod
    def finite(cls, value: int | Fraction) -> ProjectiveRationalPoint:
        rational = _fraction(value, "finite projective point")
        return cls(rational.numerator, rational.denominator)

    @classmethod
    def infinity(cls) -> ProjectiveRationalPoint:
        return cls(1, 0)

    @property
    def is_infinity(self) -> bool:
        return self.denominator == 0

    @property
    def fraction(self) -> Fraction:
        if self.is_infinity:
            raise PAdicValidationError("infinity has no affine rational coordinate")
        return Fraction(self.numerator, self.denominator)

    def verify(self) -> bool:
        if type(self.numerator) is not int or type(self.denominator) is not int:
            raise PAdicVerificationError("projective coordinates are not exact integers")
        if (
            self.numerator.bit_length() > MAX_CANONICAL_INTEGER_BITS
            or self.denominator.bit_length() > MAX_CANONICAL_INTEGER_BITS
        ):
            raise PAdicVerificationError("projective coordinate exceeds the portable integer bound")
        if self.denominator == 0:
            if self.numerator != 1:
                raise PAdicVerificationError("projective infinity was altered")
        elif (
            self.denominator < 1
            or gcd(abs(self.numerator), self.denominator) != 1
            or Fraction(self.numerator, self.denominator).numerator != self.numerator
        ):
            raise PAdicVerificationError("finite projective coordinate is not canonical")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "denominator": self.denominator,
            "numerator": self.numerator,
            "type": "arbogast.padic.projective_rational_point",
        }


def _point_key(point: ProjectiveRationalPoint) -> tuple[int, Fraction]:
    return (1, Fraction(0)) if point.is_infinity else (0, point.fraction)


def _linear_factor(point: ProjectiveRationalPoint) -> PolynomialQ:
    if point.is_infinity:
        raise PAdicValidationError("infinity has no affine linear factor")
    return (Fraction(-point.numerator), Fraction(point.denominator))


@dataclass(frozen=True, slots=True, init=False)
class FiberFactor(PAdicSchemaObject):
    """One rational projective point with its complete fibre multiplicity."""

    point: ProjectiveRationalPoint
    multiplicity: int

    schema_version = "arbogast.padic.fiber-factor/v1"

    def __init__(self, point: ProjectiveRationalPoint, multiplicity: int) -> None:
        if not isinstance(point, ProjectiveRationalPoint):
            raise TypeError("fiber factor point must be a ProjectiveRationalPoint")
        normalized_multiplicity = strict_int(multiplicity, "fiber multiplicity", minimum=1)
        if normalized_multiplicity > MAX_LOCAL_DEGREE:
            raise PAdicValidationError("fiber multiplicity exceeds the bounded local degree")
        point.verify()
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "multiplicity", normalized_multiplicity)

    def verify(self) -> bool:
        if not isinstance(self.point, ProjectiveRationalPoint):
            raise PAdicVerificationError("fiber factor point has the wrong type")
        self.point.verify()
        if type(self.multiplicity) is not int or not 1 <= self.multiplicity <= MAX_LOCAL_DEGREE:
            raise PAdicVerificationError("fiber multiplicity was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "multiplicity": self.multiplicity,
            "point": self.point.to_canonical_data(),
            "type": "arbogast.padic.fiber_factor",
        }


@dataclass(frozen=True, slots=True, init=False)
class BranchFiberWitness(PAdicSchemaObject):
    """A complete rational-linear factorization of one normalized branch fibre."""

    branch: BranchValue
    scalar: Fraction
    factors: tuple[FiberFactor, ...]

    schema_version = "arbogast.padic.branch-fiber-witness/v1"

    def __init__(
        self,
        branch: BranchValue | str,
        scalar: int | Fraction,
        factors: Sequence[FiberFactor],
    ) -> None:
        normalized_branch = _branch(branch)
        normalized_scalar = _fraction(scalar, "branch-fiber scalar", nonzero=True)
        if not 1 <= len(factors) <= MAX_LOCAL_DEGREE:
            raise PAdicValidationError("branch fibre factor count exceeds the bounded slice")
        normalized_factors = tuple(factors)
        if any(not isinstance(factor, FiberFactor) for factor in normalized_factors):
            raise PAdicValidationError("branch fibre needs one or more typed factors")
        normalized_factors = tuple(
            sorted(normalized_factors, key=lambda factor: _point_key(factor.point))
        )
        if len({factor.point for factor in normalized_factors}) != len(normalized_factors):
            raise PAdicValidationError("branch fibre contains a duplicate projective point")
        if sum(factor.multiplicity for factor in normalized_factors) > MAX_LOCAL_DEGREE:
            raise PAdicValidationError("branch fibre degree exceeds the bounded slice")
        if normalized_branch is BranchValue.INFINITY:
            if (
                normalized_scalar != 1
                or len(normalized_factors) != 1
                or not normalized_factors[0].point.is_infinity
            ):
                raise PAdicValidationError(
                    "the normalized infinity fibre must be scalar 1 at the point infinity"
                )
        elif any(factor.point.is_infinity for factor in normalized_factors):
            raise PAdicValidationError("a finite branch fibre cannot contain infinity")
        for factor in normalized_factors:
            factor.verify()
        object.__setattr__(self, "branch", normalized_branch)
        object.__setattr__(self, "scalar", normalized_scalar)
        object.__setattr__(self, "factors", normalized_factors)

    @property
    def degree(self) -> int:
        return sum(factor.multiplicity for factor in self.factors)

    @property
    def profile(self) -> tuple[int, ...]:
        return tuple(sorted((factor.multiplicity for factor in self.factors), reverse=True))

    def affine_polynomial(self) -> PolynomialQ:
        if self.branch is BranchValue.INFINITY:
            raise PAdicValidationError("the infinity fibre is projective, not affine")
        result: PolynomialQ = (Fraction(1),)
        for factor in self.factors:
            result = _multiply(result, _power(_linear_factor(factor.point), factor.multiplicity))
        return _scale(result, self.scalar)

    def verify(self) -> bool:
        if not isinstance(self.branch, BranchValue):
            raise PAdicVerificationError("branch-fibre branch tag was altered")
        if not isinstance(self.scalar, Fraction) or self.scalar == 0:
            raise PAdicVerificationError("branch-fibre scalar was altered")
        if (
            self.scalar.numerator.bit_length() > MAX_CANONICAL_INTEGER_BITS
            or self.scalar.denominator.bit_length() > MAX_CANONICAL_INTEGER_BITS
        ):
            raise PAdicVerificationError("branch-fibre scalar exceeds the portable rational bound")
        if not isinstance(self.factors, tuple) or not 1 <= len(self.factors) <= MAX_LOCAL_DEGREE:
            raise PAdicVerificationError("branch-fibre factor tuple was altered")
        if any(not isinstance(factor, FiberFactor) for factor in self.factors):
            raise PAdicVerificationError("branch-fibre factor type was altered")
        for factor in self.factors:
            factor.verify()
        if tuple(sorted(self.factors, key=lambda factor: _point_key(factor.point))) != self.factors:
            raise PAdicVerificationError("branch-fibre factor order was altered")
        if len({factor.point for factor in self.factors}) != len(self.factors):
            raise PAdicVerificationError("branch-fibre factors contain a duplicate point")
        if not 1 <= self.degree <= MAX_LOCAL_DEGREE:
            raise PAdicVerificationError("branch-fibre degree was altered")
        if self.branch is BranchValue.INFINITY:
            if self.scalar != 1 or len(self.factors) != 1 or not self.factors[0].point.is_infinity:
                raise PAdicVerificationError("normalized infinity fibre was altered")
        elif any(factor.point.is_infinity for factor in self.factors):
            raise PAdicVerificationError("finite branch fibre contains infinity")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "branch": self.branch.value,
            "factors": [factor.to_canonical_data() for factor in self.factors],
            "scalar": _fraction_data(self.scalar),
            "type": "arbogast.padic.branch_fiber_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class DerivativeWitness(PAdicSchemaObject):
    """The exact finite critical divisor and scalar of a polynomial derivative."""

    derivative: ExactPolynomial
    scalar: Fraction
    factors: tuple[FiberFactor, ...]

    schema_version = "arbogast.padic.derivative-witness/v1"

    def __init__(
        self,
        derivative: ExactPolynomial,
        scalar: int | Fraction,
        factors: Sequence[FiberFactor],
    ) -> None:
        if not isinstance(derivative, ExactPolynomial):
            raise TypeError("derivative witness needs an ExactPolynomial")
        if len(factors) > MAX_LOCAL_DEGREE - 1:
            raise PAdicValidationError("derivative factor count exceeds the bounded slice")
        rational = _univariate_rational(derivative)
        if rational is None or rational == (Fraction(0),):
            raise PAdicValidationError("derivative witness must be nonzero, real, and univariate")
        if len(rational) - 1 > MAX_LOCAL_DEGREE - 1:
            raise PAdicValidationError("derivative degree exceeds the bounded cover slice")
        normalized_scalar = _fraction(scalar, "derivative scalar", nonzero=True)
        normalized_factors = tuple(factors)
        if not normalized_factors or any(
            not isinstance(factor, FiberFactor) for factor in normalized_factors
        ):
            raise PAdicValidationError("derivative witness needs finite typed factors")
        normalized_factors = tuple(
            sorted(normalized_factors, key=lambda factor: _point_key(factor.point))
        )
        if any(factor.point.is_infinity for factor in normalized_factors):
            raise PAdicValidationError("derivative witness cannot use an infinity factor")
        if len({factor.point for factor in normalized_factors}) != len(normalized_factors):
            raise PAdicValidationError("derivative witness contains a duplicate point")
        if sum(factor.multiplicity for factor in normalized_factors) > MAX_LOCAL_DEGREE - 1:
            raise PAdicValidationError("derivative factor degree exceeds the bounded cover slice")
        reconstructed: PolynomialQ = (Fraction(1),)
        for factor in normalized_factors:
            reconstructed = _multiply(
                reconstructed,
                _power(_linear_factor(factor.point), factor.multiplicity),
            )
        if _scale(reconstructed, normalized_scalar) != rational:
            raise PAdicValidationError("derivative factors and scalar do not reconstruct exactly")
        derivative.verify()
        object.__setattr__(self, "derivative", derivative)
        object.__setattr__(self, "scalar", normalized_scalar)
        object.__setattr__(self, "factors", normalized_factors)

    def verify(self) -> bool:
        if (
            not isinstance(self.factors, tuple)
            or not self.factors
            or len(self.factors) > MAX_LOCAL_DEGREE - 1
        ):
            raise PAdicVerificationError("derivative factor tuple was altered")
        if not isinstance(self.derivative, ExactPolynomial):
            raise PAdicVerificationError("derivative polynomial has the wrong type")
        self.derivative.verify()
        rational = _univariate_rational(self.derivative)
        if rational is None or rational == (Fraction(0),):
            raise PAdicVerificationError("derivative polynomial was altered")
        if len(rational) - 1 > MAX_LOCAL_DEGREE - 1:
            raise PAdicVerificationError("derivative degree exceeds the bounded cover slice")
        if not isinstance(self.scalar, Fraction) or self.scalar == 0:
            raise PAdicVerificationError("derivative scalar was altered")
        if (
            self.scalar.numerator.bit_length() > MAX_CANONICAL_INTEGER_BITS
            or self.scalar.denominator.bit_length() > MAX_CANONICAL_INTEGER_BITS
        ):
            raise PAdicVerificationError("derivative scalar exceeds the portable rational bound")
        if any(not isinstance(factor, FiberFactor) for factor in self.factors):
            raise PAdicVerificationError("derivative factor type was altered")
        for factor in self.factors:
            factor.verify()
        if (
            any(factor.point.is_infinity for factor in self.factors)
            or len({factor.point for factor in self.factors}) != len(self.factors)
            or tuple(sorted(self.factors, key=lambda factor: _point_key(factor.point)))
            != self.factors
        ):
            raise PAdicVerificationError("derivative critical divisor was altered")
        if sum(factor.multiplicity for factor in self.factors) > MAX_LOCAL_DEGREE - 1:
            raise PAdicVerificationError("derivative factor degree exceeds the bounded cover slice")
        reconstructed: PolynomialQ = (Fraction(1),)
        for factor in self.factors:
            reconstructed = _multiply(
                reconstructed,
                _power(_linear_factor(factor.point), factor.multiplicity),
            )
        if _scale(reconstructed, self.scalar) != rational:
            raise PAdicVerificationError("derivative factorization no longer replays")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "derivative": self.derivative.to_canonical_data(),
            "factors": [factor.to_canonical_data() for factor in self.factors],
            "scalar": _fraction_data(self.scalar),
            "type": "arbogast.padic.derivative_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class RiemannHurwitzWitness(PAdicSchemaObject):
    """A complete genus-zero Riemann--Hurwitz replay for three branch fibres."""

    degree: int
    profiles: tuple[tuple[int, ...], ...]
    ramification_sum: int
    expected_ramification: int

    schema_version = "arbogast.padic.riemann-hurwitz-witness/v1"

    def __init__(self, degree: int, profiles: Sequence[Sequence[int]]) -> None:
        normalized_degree = strict_int(degree, "cover degree", minimum=2)
        if normalized_degree > MAX_LOCAL_DEGREE:
            raise PAdicValidationError("cover degree exceeds the bounded local degree")
        if len(profiles) != 3:
            raise PAdicValidationError("Riemann--Hurwitz witness needs exactly three profiles")
        if any(not 1 <= len(profile) <= normalized_degree for profile in profiles):
            raise PAdicValidationError("ramification profile cardinality exceeds the cover degree")
        normalized_profiles = tuple(
            tuple(
                sorted(
                    (strict_int(entry, "ramification index", minimum=1) for entry in profile),
                    reverse=True,
                )
            )
            for profile in profiles
        )
        if any(sum(profile) != normalized_degree for profile in normalized_profiles):
            raise PAdicValidationError("ramification profile is not a partition of the degree")
        ramification_sum = sum(entry - 1 for profile in normalized_profiles for entry in profile)
        expected = 2 * normalized_degree - 2
        if ramification_sum != expected:
            raise PAdicValidationError("displayed branch fibres fail Riemann--Hurwitz")
        object.__setattr__(self, "degree", normalized_degree)
        object.__setattr__(self, "profiles", normalized_profiles)
        object.__setattr__(self, "ramification_sum", ramification_sum)
        object.__setattr__(self, "expected_ramification", expected)

    def verify(self) -> bool:
        if type(self.degree) is not int or not 2 <= self.degree <= MAX_LOCAL_DEGREE:
            raise PAdicVerificationError("Riemann--Hurwitz degree was altered")
        if (
            not isinstance(self.profiles, tuple)
            or len(self.profiles) != 3
            or any(
                not isinstance(profile, tuple) or not 1 <= len(profile) <= self.degree
                for profile in self.profiles
            )
            or any(
                type(entry) is not int or entry < 1
                for profile in self.profiles
                for entry in profile
            )
            or any(tuple(sorted(profile, reverse=True)) != profile for profile in self.profiles)
            or any(sum(profile) != self.degree for profile in self.profiles)
        ):
            raise PAdicVerificationError("Riemann--Hurwitz profiles were altered")
        replay_sum = sum(entry - 1 for profile in self.profiles for entry in profile)
        if (
            type(self.ramification_sum) is not int
            or type(self.expected_ramification) is not int
            or replay_sum != self.ramification_sum
            or self.expected_ramification != 2 * self.degree - 2
            or replay_sum != self.expected_ramification
        ):
            raise PAdicVerificationError("Riemann--Hurwitz equality was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "degree": self.degree,
            "expected_ramification": self.expected_ramification,
            "profiles": [list(profile) for profile in self.profiles],
            "ramification_sum": self.ramification_sum,
            "type": "arbogast.padic.riemann_hurwitz_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class ThreePointCover(PAdicSchemaObject):
    """A normalized exact polynomial three-point cover of ``P^1_Q``.

    The object proves more than a displayed formula: both finite branch fibres,
    the projective fibre over infinity, the complete finite critical divisor,
    the generic degree, and the genus-zero Riemann--Hurwitz equality all replay
    independently with rational arithmetic.
    """

    polynomial: ExactPolynomial
    fibers: tuple[BranchFiberWitness, ...]
    derivative_witness: DerivativeWitness
    generic_degree_witness: GenericDegreeWitness
    riemann_hurwitz_witness: RiemannHurwitzWitness
    degree: int
    label: str | None

    schema_version = "arbogast.padic.three-point-cover/v1"

    def __init__(
        self,
        polynomial: ExactPolynomial,
        fibers: Sequence[BranchFiberWitness],
        derivative_witness: DerivativeWitness,
        *,
        label: str | None = None,
    ) -> None:
        if not isinstance(polynomial, ExactPolynomial):
            raise TypeError("three-point cover polynomial must be an ExactPolynomial")
        if len(fibers) != 3:
            raise PAdicValidationError("three-point cover needs exactly three branch fibres")
        rational = _univariate_rational(polynomial)
        if rational is None or len(rational) < 3:
            raise PAdicValidationError(
                "three-point cover must be a real univariate polynomial of degree at least two"
            )
        degree_witness = GenericDegreeWitness(polynomial)
        if degree_witness.degree > MAX_LOCAL_DEGREE:
            raise PAdicValidationError("three-point cover degree exceeds the bounded slice")
        normalized_fibers = tuple(fibers)
        if any(not isinstance(fiber, BranchFiberWitness) for fiber in normalized_fibers):
            raise PAdicValidationError("three-point cover needs three typed branch fibres")
        normalized_fibers = tuple(
            sorted(normalized_fibers, key=lambda fiber: _BRANCH_ORDER[fiber.branch])
        )
        if tuple(fiber.branch for fiber in normalized_fibers) != tuple(BranchValue):
            raise PAdicValidationError("branch fibres must be exactly zero, one, and infinity")
        if not isinstance(derivative_witness, DerivativeWitness):
            raise TypeError("three-point cover needs a DerivativeWitness")
        for fiber in normalized_fibers:
            fiber.verify()
        derivative_witness.verify()
        polynomial.verify()
        degree = degree_witness.degree
        zero, one, infinity = normalized_fibers
        if zero.degree != degree or one.degree != degree or infinity.degree != degree:
            raise PAdicValidationError("each projective branch fibre must have the generic degree")
        if zero.affine_polynomial() != rational:
            raise PAdicValidationError("zero-fibre factorization does not reconstruct the map")
        if one.affine_polynomial() != _subtract_constant(rational, Fraction(1)):
            raise PAdicValidationError("one-fibre factorization does not reconstruct map minus one")
        if not all(any(entry > 1 for entry in fiber.profile) for fiber in normalized_fibers):
            raise PAdicValidationError("zero, one, and infinity must all be genuine branch values")
        exact_derivative = polynomial.derivative(0)
        if derivative_witness.derivative != exact_derivative:
            raise PAdicValidationError("derivative witness is not the derivative of the cover map")
        expected_factors = tuple(
            sorted(
                (
                    FiberFactor(factor.point, factor.multiplicity - 1)
                    for fiber in (zero, one)
                    for factor in fiber.factors
                    if factor.multiplicity > 1
                ),
                key=lambda factor: _point_key(factor.point),
            )
        )
        if derivative_witness.factors != expected_factors:
            raise PAdicValidationError(
                "derivative witness does not equal the finite ramification divisor"
            )
        riemann_hurwitz = RiemannHurwitzWitness(
            degree,
            tuple(fiber.profile for fiber in normalized_fibers),
        )
        object.__setattr__(self, "polynomial", polynomial)
        object.__setattr__(self, "fibers", normalized_fibers)
        object.__setattr__(self, "derivative_witness", derivative_witness)
        object.__setattr__(self, "generic_degree_witness", degree_witness)
        object.__setattr__(self, "riemann_hurwitz_witness", riemann_hurwitz)
        object.__setattr__(self, "degree", degree)
        object.__setattr__(self, "label", _optional_label(label, "three-point cover label"))

    @property
    def zero_fiber(self) -> BranchFiberWitness:
        return self.fibers[0]

    @property
    def one_fiber(self) -> BranchFiberWitness:
        return self.fibers[1]

    @property
    def infinity_fiber(self) -> BranchFiberWitness:
        return self.fibers[2]

    @property
    def ramification_profiles(self) -> tuple[tuple[int, ...], ...]:
        return tuple(fiber.profile for fiber in self.fibers)

    def verify(self) -> bool:
        if not isinstance(self.polynomial, ExactPolynomial):
            raise PAdicVerificationError("three-point polynomial has the wrong type")
        self.polynomial.verify()
        rational = _univariate_rational(self.polynomial)
        if rational is None or len(rational) < 3:
            raise PAdicVerificationError("three-point polynomial was altered")
        if (
            not isinstance(self.fibers, tuple)
            or len(self.fibers) != 3
            or any(not isinstance(fiber, BranchFiberWitness) for fiber in self.fibers)
        ):
            raise PAdicVerificationError("three-point branch fibres were altered")
        for fiber in self.fibers:
            fiber.verify()
        if tuple(fiber.branch for fiber in self.fibers) != tuple(BranchValue):
            raise PAdicVerificationError("three-point branch-fibre order was altered")
        if not isinstance(self.generic_degree_witness, GenericDegreeWitness):
            raise PAdicVerificationError("generic-degree witness has the wrong type")
        self.generic_degree_witness.verify()
        if (
            self.generic_degree_witness.polynomial != self.polynomial
            or type(self.degree) is not int
            or self.degree != self.generic_degree_witness.degree
            or not 2 <= self.degree <= MAX_LOCAL_DEGREE
        ):
            raise PAdicVerificationError("generic cover degree was altered")
        if any(fiber.degree != self.degree for fiber in self.fibers):
            raise PAdicVerificationError("branch-fibre degree was altered")
        if self.zero_fiber.affine_polynomial() != rational:
            raise PAdicVerificationError("zero-fibre identity failed replay")
        if self.one_fiber.affine_polynomial() != _subtract_constant(rational, Fraction(1)):
            raise PAdicVerificationError("one-fibre identity failed replay")
        if not all(any(entry > 1 for entry in profile) for profile in self.ramification_profiles):
            raise PAdicVerificationError("a normalized branch value ceased to ramify")
        if not isinstance(self.derivative_witness, DerivativeWitness):
            raise PAdicVerificationError("derivative witness has the wrong type")
        self.derivative_witness.verify()
        if self.derivative_witness.derivative != self.polynomial.derivative(0):
            raise PAdicVerificationError("cover derivative identity failed replay")
        expected_factors = tuple(
            sorted(
                (
                    FiberFactor(factor.point, factor.multiplicity - 1)
                    for fiber in (self.zero_fiber, self.one_fiber)
                    for factor in fiber.factors
                    if factor.multiplicity > 1
                ),
                key=lambda factor: _point_key(factor.point),
            )
        )
        if self.derivative_witness.factors != expected_factors:
            raise PAdicVerificationError("finite ramification divisor failed replay")
        if not isinstance(self.riemann_hurwitz_witness, RiemannHurwitzWitness):
            raise PAdicVerificationError("Riemann--Hurwitz witness has the wrong type")
        self.riemann_hurwitz_witness.verify()
        if (
            self.riemann_hurwitz_witness.degree != self.degree
            or self.riemann_hurwitz_witness.profiles != self.ramification_profiles
        ):
            raise PAdicVerificationError("Riemann--Hurwitz witness is not bound to the cover")
        if _optional_label(self.label, "three-point cover label") != self.label:
            raise PAdicVerificationError("three-point cover label was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "degree": self.degree,
            "derivative_witness": self.derivative_witness.to_canonical_data(),
            "fibers": [fiber.to_canonical_data() for fiber in self.fibers],
            "generic_degree_witness": self.generic_degree_witness.to_canonical_data(),
            "label": self.label,
            "polynomial": self.polynomial.to_canonical_data(),
            "riemann_hurwitz_witness": self.riemann_hurwitz_witness.to_canonical_data(),
            "type": "arbogast.padic.three_point_cover",
        }


def _is_small_prime(value: int) -> bool:
    if value < 2:
        return False
    if value in {2, 3}:
        return True
    if value % 2 == 0 or value % 3 == 0:
        return False
    divisor = 5
    while divisor <= isqrt(value):
        if value % divisor == 0 or value % (divisor + 2) == 0:
            return False
        divisor += 6
    return True


def _fragment_prime(value: int) -> int:
    prime = strict_int(value, "factorization prime", minimum=2)
    if prime > MAX_FACTORIZATION_PRIME:
        raise PAdicValidationError(
            f"factorization prime exceeds the bounded limit {MAX_FACTORIZATION_PRIME}"
        )
    if not _is_small_prime(prime):
        raise PAdicValidationError("factorization characteristic must be prime")
    return prime


def _fp_trim(value: Sequence[int], prime: int) -> FPPolynomial:
    result = tuple(value)
    if not result or any(type(coefficient) is not int for coefficient in result):
        raise PAdicValidationError("finite-field polynomial needs exact integer coefficients")
    if any(not 0 <= coefficient < prime for coefficient in result):
        raise PAdicValidationError("finite-field coefficients must be canonical residues")
    while len(result) > 1 and result[-1] == 0:
        result = result[:-1]
    return result


def _fp_add(left: FPPolynomial, right: FPPolynomial, prime: int) -> FPPolynomial:
    size = max(len(left), len(right))
    result = tuple(
        ((left[index] if index < len(left) else 0) + (right[index] if index < len(right) else 0))
        % prime
        for index in range(size)
    )
    return _fp_trim(result, prime)


def _fp_negate(value: FPPolynomial, prime: int) -> FPPolynomial:
    return _fp_trim(tuple((-coefficient) % prime for coefficient in value), prime)


def _fp_subtract(left: FPPolynomial, right: FPPolynomial, prime: int) -> FPPolynomial:
    return _fp_add(left, _fp_negate(right, prime), prime)


def _fp_multiply(left: FPPolynomial, right: FPPolynomial, prime: int) -> FPPolynomial:
    result = [0] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            result[left_index + right_index] = (
                result[left_index + right_index] + left_value * right_value
            ) % prime
    return _fp_trim(result, prime)


def _fp_divmod(
    numerator: FPPolynomial,
    denominator: FPPolynomial,
    prime: int,
) -> tuple[FPPolynomial, FPPolynomial]:
    if denominator == (0,):
        raise ZeroDivisionError("finite-field polynomial division by zero")
    remainder = list(numerator)
    quotient = [0] * max(1, len(numerator) - len(denominator) + 1)
    inverse_lead = pow(denominator[-1], -1, prime)
    while len(remainder) >= len(denominator) and any(remainder):
        offset = len(remainder) - len(denominator)
        coefficient = remainder[-1] * inverse_lead % prime
        quotient[offset] = coefficient
        for index, divisor in enumerate(denominator):
            remainder[offset + index] = (remainder[offset + index] - coefficient * divisor) % prime
        while len(remainder) > 1 and remainder[-1] == 0:
            remainder.pop()
    return _fp_trim(quotient, prime), _fp_trim(remainder, prime)


def _fp_remainder(value: FPPolynomial, modulus: FPPolynomial, prime: int) -> FPPolynomial:
    return _fp_divmod(value, modulus, prime)[1]


def _fp_gcd(left: FPPolynomial, right: FPPolynomial, prime: int) -> FPPolynomial:
    a, b = left, right
    while b != (0,):
        a, b = b, _fp_remainder(a, b, prime)
    if a == (0,):
        return a
    inverse = pow(a[-1], -1, prime)
    return _fp_trim(tuple(inverse * coefficient % prime for coefficient in a), prime)


def _fp_powmod(
    value: FPPolynomial,
    exponent: int,
    modulus: FPPolynomial,
    prime: int,
) -> FPPolynomial:
    result: FPPolynomial = (1,)
    base = _fp_remainder(value, modulus, prime)
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = _fp_remainder(_fp_multiply(result, base, prime), modulus, prime)
        base = _fp_remainder(_fp_multiply(base, base, prime), modulus, prime)
        remaining >>= 1
    return result


def _fp_power(value: FPPolynomial, exponent: int, prime: int) -> FPPolynomial:
    result: FPPolynomial = (1,)
    base = value
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = _fp_multiply(result, base, prime)
        base = _fp_multiply(base, base, prime)
        remaining >>= 1
    return result


def _is_irreducible_monic(value: FPPolynomial, prime: int) -> bool:
    degree = len(value) - 1
    if degree == 1:
        return True
    x: FPPolynomial = (0, 1)
    frobenius_power = x
    for exponent in range(1, degree + 1):
        frobenius_power = _fp_powmod(frobenius_power, prime, value, prime)
        difference = _fp_subtract(frobenius_power, x, prime)
        if exponent <= degree // 2 and _fp_gcd(value, difference, prime) != (1,):
            return False
    return _fp_remainder(frobenius_power, value, prime) == _fp_remainder(x, value, prime)


@dataclass(frozen=True, slots=True, init=False)
class FiniteFieldFactor(PAdicSchemaObject):
    """One canonical monic irreducible factor over a small prime field."""

    prime: int
    coefficients: FPPolynomial
    multiplicity: int
    irreducible: bool

    schema_version = "arbogast.padic.finite-field-factor/v1"

    def __init__(self, prime: int, coefficients: Sequence[int], multiplicity: int = 1) -> None:
        normalized_prime = _fragment_prime(prime)
        if len(coefficients) > MAX_FACTORIZATION_DEGREE + 1:
            raise PAdicValidationError("finite-field factor degree exceeds the bounded slice")
        normalized_coefficients = _fp_trim(coefficients, normalized_prime)
        degree = len(normalized_coefficients) - 1
        if not 1 <= degree <= MAX_FACTORIZATION_DEGREE:
            raise PAdicValidationError("finite-field factor degree is outside the bounded slice")
        if normalized_coefficients[-1] != 1:
            raise PAdicValidationError("finite-field factors must be monic")
        if normalized_prime * degree > MAX_FACTORIZATION_WORK:
            raise PAdicValidationError("finite-field irreducibility work exceeds the bound")
        normalized_multiplicity = strict_int(
            multiplicity,
            "finite-field factor multiplicity",
            minimum=1,
        )
        if normalized_multiplicity > MAX_FACTORIZATION_DEGREE:
            raise PAdicValidationError("factor multiplicity exceeds the bounded slice")
        if not _is_irreducible_monic(normalized_coefficients, normalized_prime):
            raise PAdicValidationError("displayed finite-field factor is reducible")
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "coefficients", normalized_coefficients)
        object.__setattr__(self, "multiplicity", normalized_multiplicity)
        object.__setattr__(self, "irreducible", True)

    @property
    def degree(self) -> int:
        return len(self.coefficients) - 1

    def verify(self) -> bool:
        if type(self.prime) is not int or not 2 <= self.prime <= MAX_FACTORIZATION_PRIME:
            raise PAdicVerificationError("finite-field factor prime was altered")
        if not _is_small_prime(self.prime):
            raise PAdicVerificationError("finite-field factor characteristic is not prime")
        if not isinstance(self.coefficients, tuple):
            raise PAdicVerificationError("finite-field factor coefficients were altered")
        if not 2 <= len(self.coefficients) <= MAX_FACTORIZATION_DEGREE + 1:
            raise PAdicVerificationError("finite-field factor degree exceeds the bounded slice")
        degree = len(self.coefficients) - 1
        if self.prime * degree > MAX_FACTORIZATION_WORK:
            raise PAdicVerificationError("finite-field irreducibility work exceeds the bound")
        try:
            normalized = _fp_trim(self.coefficients, self.prime)
        except PAdicValidationError as exc:
            raise PAdicVerificationError(str(exc)) from exc
        if normalized != self.coefficients or self.coefficients[-1] != 1:
            raise PAdicVerificationError("finite-field factor is not canonical monic")
        if (
            type(self.multiplicity) is not int
            or not 1 <= self.multiplicity <= MAX_FACTORIZATION_DEGREE
        ):
            raise PAdicVerificationError("finite-field factor multiplicity was altered")
        if type(self.irreducible) is not bool or not self.irreducible:
            raise PAdicVerificationError("finite-field irreducibility flag was altered")
        if not _is_irreducible_monic(self.coefficients, self.prime):
            raise PAdicVerificationError("finite-field factor is not irreducible")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "coefficients": list(self.coefficients),
            "degree": self.degree,
            "irreducible": self.irreducible,
            "multiplicity": self.multiplicity,
            "prime": self.prime,
            "type": "arbogast.padic.finite_field_factor",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> FiniteFieldFactor:
        """Replay one strict standalone schema document before irreducibility work."""

        raw = _strict_map(value, "finite-field factor")
        _strict_keys(
            raw,
            {
                "coefficients",
                "degree",
                "irreducible",
                "multiplicity",
                "prime",
                "schema",
                "type",
            },
            "finite-field factor",
        )
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.finite_field_factor"
        ):
            raise PAdicVerificationError("finite-field factor schema or type was altered")
        raw_coefficients = _strict_array(raw["coefficients"], "finite-field factor coefficients")
        if not 2 <= len(raw_coefficients) <= MAX_FACTORIZATION_DEGREE + 1:
            raise PAdicVerificationError("finite-field factor degree exceeds the bounded slice")
        coefficients = tuple(
            _strict_integer(item, "finite-field factor coefficient") for item in raw_coefficients
        )
        try:
            result = cls(
                _strict_integer(raw["prime"], "finite-field factor prime"),
                coefficients,
                _strict_integer(raw["multiplicity"], "finite-field factor multiplicity"),
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(f"invalid finite-field factor: {exc}") from exc
        if raw != result.to_schema_document():
            raise PAdicVerificationError("finite-field factor canonical data were altered")
        return result


@dataclass(frozen=True, slots=True, init=False)
class LocalFactorizationFragment(PAdicSchemaObject):
    """Complete factorization of one displayed polynomial over ``F_p`` only."""

    source_id: str
    prime: int
    polynomial: FPPolynomial
    unit: int
    factors: tuple[FiniteFieldFactor, ...]
    factor_degrees: tuple[int, ...]
    ramification_indices: tuple[int, ...]
    factorization_complete: bool
    scope: str

    schema_version = "arbogast.padic.local-factorization-fragment/v1"
    SCOPE = "displayed-mod-p-polynomial-only; no local model/stable reduction/lift/descent claim"

    def __init__(
        self,
        source_id: str,
        prime: int,
        polynomial: Sequence[int],
        unit: int,
        factors: Sequence[FiniteFieldFactor],
    ) -> None:
        normalized_source = canonical_label(source_id, "factorization source ID")
        normalized_prime = _fragment_prime(prime)
        if len(polynomial) > MAX_FACTORIZATION_DEGREE + 1:
            raise PAdicValidationError("displayed polynomial degree exceeds the bounded slice")
        normalized_polynomial = _fp_trim(polynomial, normalized_prime)
        degree = len(normalized_polynomial) - 1
        if not 1 <= degree <= MAX_FACTORIZATION_DEGREE:
            raise PAdicValidationError("displayed polynomial degree is outside the bounded slice")
        normalized_unit = strict_int(unit, "factorization unit", minimum=1)
        if normalized_unit >= normalized_prime:
            raise PAdicValidationError("factorization unit is not a nonzero canonical residue")
        if not 1 <= len(factors) <= MAX_FACTORIZATION_FACTORS:
            raise PAdicValidationError("factorization factor count exceeds the bounded slice")
        normalized_factors = tuple(factors)
        if any(not isinstance(factor, FiniteFieldFactor) for factor in normalized_factors):
            raise PAdicValidationError("factorization needs a bounded nonempty typed factor list")
        normalized_factors = tuple(
            sorted(normalized_factors, key=lambda factor: (factor.degree, factor.coefficients))
        )
        if any(factor.prime != normalized_prime for factor in normalized_factors):
            raise PAdicValidationError("factorization factors use the wrong prime")
        if len({factor.coefficients for factor in normalized_factors}) != len(normalized_factors):
            raise PAdicValidationError("factorization contains duplicate irreducible factors")
        if (
            sum(factor.degree * factor.multiplicity for factor in normalized_factors)
            > MAX_FACTORIZATION_DEGREE
        ):
            raise PAdicValidationError("factorization product degree exceeds the bounded slice")
        product: FPPolynomial = (normalized_unit,)
        for factor in normalized_factors:
            factor.verify()
            product = _fp_multiply(
                product,
                _fp_power(factor.coefficients, factor.multiplicity, normalized_prime),
                normalized_prime,
            )
        if product != normalized_polynomial:
            raise PAdicValidationError("unit times displayed factors does not equal the polynomial")
        object.__setattr__(self, "source_id", normalized_source)
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "polynomial", normalized_polynomial)
        object.__setattr__(self, "unit", normalized_unit)
        object.__setattr__(self, "factors", normalized_factors)
        object.__setattr__(
            self,
            "factor_degrees",
            tuple(factor.degree for factor in normalized_factors),
        )
        object.__setattr__(
            self,
            "ramification_indices",
            tuple(factor.multiplicity for factor in normalized_factors),
        )
        object.__setattr__(self, "factorization_complete", True)
        object.__setattr__(self, "scope", self.SCOPE)

    def verify(self) -> bool:
        if type(self.factorization_complete) is not bool or not self.factorization_complete:
            raise PAdicVerificationError("factorization completeness flag was altered")
        if self.scope != self.SCOPE:
            raise PAdicVerificationError("local factorization claim scope was altered")
        try:
            replay = LocalFactorizationFragment(
                self.source_id,
                self.prime,
                self.polynomial,
                self.unit,
                self.factors,
            )
        except (TypeError, ValueError) as exc:
            raise PAdicVerificationError(f"local factorization replay failed: {exc}") from exc
        if replay != self:
            raise PAdicVerificationError("local factorization fragment was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "factor_degrees": list(self.factor_degrees),
            "factorization_complete": self.factorization_complete,
            "factors": [factor.to_canonical_data() for factor in self.factors],
            "polynomial": list(self.polynomial),
            "prime": self.prime,
            "ramification_indices": list(self.ramification_indices),
            "scope": self.scope,
            "source_id": self.source_id,
            "type": "arbogast.padic.local_factorization_fragment",
            "unit": self.unit,
        }


def local_factorization_fragment(
    source_id: str,
    prime: int,
    polynomial: Sequence[int],
    unit: int,
    factors: Sequence[FiniteFieldFactor],
) -> Certified[LocalFactorizationFragment]:
    """Certify a complete displayed finite-field factorization and nothing beyond it."""

    from .results import certified_result

    return certified_result(
        LocalFactorizationFragment(source_id, prime, polynomial, unit, factors),
        "local-factorization-fragment",
    )


def _strict_map(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise PAdicVerificationError(f"{name} must be a strict JSON object")
    return cast(dict[str, object], value)


def _strict_array(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise PAdicVerificationError(f"{name} must be a strict JSON array")
    return cast(list[object], value)


def _strict_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise PAdicVerificationError(f"{name} fields do not match the v1 schema")


def _strict_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise PAdicVerificationError(f"{name} must be an exact integer")
    return value


def _decode_finite_field_factor(value: object, name: str) -> FiniteFieldFactor:
    raw = _strict_map(value, name)
    _strict_keys(
        raw,
        {"coefficients", "degree", "irreducible", "multiplicity", "prime", "type"},
        name,
    )
    if raw["type"] != "arbogast.padic.finite_field_factor":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    raw_coefficients = _strict_array(raw["coefficients"], f"{name}.coefficients")
    if len(raw_coefficients) > MAX_FACTORIZATION_DEGREE + 1:
        raise PAdicVerificationError("finite-field factor exceeds the degree bound")
    coefficients = tuple(_strict_integer(item, f"{name}.coefficients") for item in raw_coefficients)
    try:
        result = FiniteFieldFactor(
            _strict_integer(raw["prime"], f"{name}.prime"),
            coefficients,
            _strict_integer(raw["multiplicity"], f"{name}.multiplicity"),
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if raw != result.to_canonical_data():
        raise PAdicVerificationError(f"{name} irreducibility or canonical data were altered")
    return result


def _decode_local_factorization(value: object, name: str) -> LocalFactorizationFragment:
    raw = _strict_map(value, name)
    _strict_keys(
        raw,
        {
            "factor_degrees",
            "factorization_complete",
            "factors",
            "polynomial",
            "prime",
            "ramification_indices",
            "schema",
            "scope",
            "source_id",
            "type",
            "unit",
        },
        name,
    )
    if (
        raw["schema"] != LocalFactorizationFragment.schema_version
        or raw["type"] != "arbogast.padic.local_factorization_fragment"
        or type(raw["source_id"]) is not str
    ):
        raise PAdicVerificationError(f"{name} schema, type, or source ID was altered")
    raw_factors = _strict_array(raw["factors"], f"{name}.factors")
    if len(raw_factors) > MAX_FACTORIZATION_FACTORS:
        raise PAdicVerificationError("local factorization has too many factors")
    factors = tuple(
        _decode_finite_field_factor(item, f"{name}.factors[{index}]")
        for index, item in enumerate(raw_factors)
    )
    raw_polynomial = _strict_array(raw["polynomial"], f"{name}.polynomial")
    if len(raw_polynomial) > MAX_FACTORIZATION_DEGREE + 1:
        raise PAdicVerificationError("local factorization polynomial exceeds the degree bound")
    polynomial = tuple(_strict_integer(item, f"{name}.polynomial") for item in raw_polynomial)
    try:
        result = LocalFactorizationFragment(
            raw["source_id"],
            _strict_integer(raw["prime"], f"{name}.prime"),
            polynomial,
            _strict_integer(raw["unit"], f"{name}.unit"),
            factors,
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if raw != result.to_schema_document():
        raise PAdicVerificationError(f"{name} exact factorization or scope was altered")
    return result


@padic_payload_verifier("local-factorization-fragment")
def _verify_local_factorization_payload(
    payload: Mapping[str, object],
    _evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    raw = _strict_map(payload, "local-factorization payload")
    _strict_keys(raw, {"result"}, "local-factorization payload")
    _decode_local_factorization(raw["result"], "local-factorization result")
    return PAdicPayloadReplay(
        checks=(
            "complete-displayed-polynomial-product",
            "monic-irreducible-distinct-factors",
            "strict-local-fragment-scope",
        )
    )


__all__ = [
    "MAX_FACTORIZATION_DEGREE",
    "MAX_FACTORIZATION_FACTORS",
    "MAX_FACTORIZATION_PRIME",
    "MAX_FACTORIZATION_WORK",
    "BranchFiberWitness",
    "BranchValue",
    "DerivativeWitness",
    "FiberFactor",
    "FiniteFieldFactor",
    "LocalFactorizationFragment",
    "ProjectiveRationalPoint",
    "RiemannHurwitzWitness",
    "ThreePointCover",
    "local_factorization_fragment",
]
