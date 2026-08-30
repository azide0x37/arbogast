"""Tame good, semistable, and stable reduction for exact three-point covers.

Version 0.5 certifies the complete one-component lane for a normalized marked
polynomial cover whose displayed rational model has tame good reduction.  It
does not search for coordinate changes, field extensions, blow-ups, or a
semistable model after the displayed model fails the good-reduction checks.
Those failures therefore remain typed non-conclusions at the operation layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import isqrt
from typing import TYPE_CHECKING, TypeAlias, cast

from arbogast.cert import VerificationCertificate
from arbogast.core import CanonicalJSON
from arbogast.numeric import ComplexDyadic, Dyadic, ExactPolynomial

from ._schema import (
    MAX_LOCAL_DEGREE,
    PAdicSchemaObject,
    canonical_label,
    strict_canonical_equal,
    strict_int,
)
from .certificate import PAdicPayloadReplay, padic_payload_verifier
from .covers import (
    BranchFiberWitness,
    BranchValue,
    DerivativeWitness,
    FiberFactor,
    ProjectiveRationalPoint,
    ThreePointCover,
    _fraction_data,
    _univariate_rational,
)
from .errors import PAdicValidationError, PAdicVerificationError

if TYPE_CHECKING:
    from .results import Certified, PAdicResult, Unsupported

FPPolynomial: TypeAlias = tuple[int, ...]

# This focused lane uses an elementary deterministic primality replay.  The
# generic p-adic layer permits larger exact primes, but cover reduction at such
# primes needs a separately certified prime presentation in a later release.
MAX_REDUCTION_PRIME = 5


class _GoodReductionFailure(PAdicValidationError):
    """Internal distinction between malformed input and a failed model criterion."""


def _is_prime(value: int) -> bool:
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


def _prime(value: int) -> int:
    prime = strict_int(value, "reduction prime", minimum=2)
    if prime > MAX_REDUCTION_PRIME:
        raise PAdicValidationError(
            f"reduction prime exceeds the bounded deterministic limit {MAX_REDUCTION_PRIME}"
        )
    if not _is_prime(prime):
        raise PAdicValidationError("reduction characteristic must be prime")
    return prime


def _factor_signature(
    cover_fiber: BranchFiberWitness | DerivativeWitness,
) -> tuple[tuple[int, int, int], ...]:
    factors = cover_fiber.factors
    return tuple(
        (factor.point.numerator, factor.point.denominator, factor.multiplicity)
        for factor in factors
    )


def _is_supported_beta_cover(cover: ThreePointCover) -> bool:
    """Recognize the one exact marked presentation certified in version 0.5."""

    try:
        cover.verify()
    except (TypeError, ValueError):
        return False
    polynomial = _univariate_rational(cover.polynomial)
    return bool(
        polynomial
        == (
            Fraction(0),
            Fraction(0),
            Fraction(27, 4),
            Fraction(-27, 4),
        )
        and cover.polynomial.variable_names == ("z",)
        and cover.degree == 3
        and cover.ramification_profiles == ((2, 1), (2, 1), (3,))
        and cover.zero_fiber.scalar == Fraction(-27, 4)
        and _factor_signature(cover.zero_fiber) == ((0, 1, 2), (1, 1, 1))
        and cover.one_fiber.scalar == Fraction(-1, 4)
        and _factor_signature(cover.one_fiber) == ((-1, 3, 1), (2, 3, 2))
        and cover.infinity_fiber.scalar == 1
        and _factor_signature(cover.infinity_fiber) == ((1, 0, 3),)
        and cover.derivative_witness.scalar == Fraction(-27, 4)
        and _factor_signature(cover.derivative_witness) == ((0, 1, 1), (2, 3, 1))
    )


def _fp_trim(value: FPPolynomial, prime: int) -> FPPolynomial:
    result = tuple(coefficient % prime for coefficient in value) or (0,)
    while len(result) > 1 and result[-1] == 0:
        result = result[:-1]
    return result


def _fp_multiply(left: FPPolynomial, right: FPPolynomial, prime: int) -> FPPolynomial:
    result = [0] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            result[left_index + right_index] = (
                result[left_index + right_index] + left_value * right_value
            ) % prime
    return _fp_trim(tuple(result), prime)


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


def _fp_scale(value: FPPolynomial, scalar: int, prime: int) -> FPPolynomial:
    return _fp_trim(tuple(scalar * coefficient for coefficient in value), prime)


def _fp_subtract_constant(value: FPPolynomial, scalar: int, prime: int) -> FPPolynomial:
    result = list(value)
    result[0] = (result[0] - scalar) % prime
    return _fp_trim(tuple(result), prime)


def _fp_derivative(value: FPPolynomial, prime: int) -> FPPolynomial:
    return _fp_trim(
        tuple(index * coefficient for index, coefficient in enumerate(value))[1:],
        prime,
    )


def _reduce_fraction(numerator: int, denominator: int, prime: int, name: str) -> int:
    if denominator % prime == 0:
        raise _GoodReductionFailure(f"{name} has denominator divisible by {prime}")
    return numerator * pow(denominator, -1, prime) % prime


def _reduce_rational_polynomial(cover: ThreePointCover, prime: int) -> FPPolynomial:
    polynomial = _univariate_rational(cover.polynomial)
    assert polynomial is not None
    return _fp_trim(
        tuple(
            _reduce_fraction(
                coefficient.numerator,
                coefficient.denominator,
                prime,
                "cover coefficient",
            )
            for coefficient in polynomial
        ),
        prime,
    )


@dataclass(frozen=True, slots=True, init=False)
class ReducedProjectivePoint(PAdicSchemaObject):
    """A canonical point of ``P^1(F_p)``; ``None`` denotes infinity."""

    prime: int
    residue: int | None

    schema_version = "arbogast.padic.reduced-projective-point/v1"

    def __init__(self, prime: int, residue: int | None) -> None:
        normalized_prime = _prime(prime)
        if residue is None:
            normalized_residue = None
        else:
            normalized_residue = strict_int(residue, "projective residue", minimum=0)
            if normalized_residue >= normalized_prime:
                raise PAdicValidationError("projective residue is not canonical modulo the prime")
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "residue", normalized_residue)

    @classmethod
    def reduce(
        cls,
        point: ProjectiveRationalPoint,
        prime: int,
    ) -> ReducedProjectivePoint:
        if not isinstance(point, ProjectiveRationalPoint):
            raise TypeError("point reduction needs a ProjectiveRationalPoint")
        normalized_prime = _prime(prime)
        point.verify()
        if point.is_infinity:
            return cls(normalized_prime, None)
        return cls(
            normalized_prime,
            _reduce_fraction(
                point.numerator,
                point.denominator,
                normalized_prime,
                "marked point",
            ),
        )

    @property
    def is_infinity(self) -> bool:
        return self.residue is None

    def verify(self) -> bool:
        if type(self.prime) is not int or not 2 <= self.prime <= MAX_REDUCTION_PRIME:
            raise PAdicVerificationError("reduced point prime exceeds the bounded lane")
        if not _is_prime(self.prime):
            raise PAdicVerificationError("reduced point prime was altered")
        if self.residue is not None and (
            type(self.residue) is not int or not 0 <= self.residue < self.prime
        ):
            raise PAdicVerificationError("reduced projective residue was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "prime": self.prime,
            "residue": self.residue,
            "type": "arbogast.padic.reduced_projective_point",
        }


@dataclass(frozen=True, slots=True, init=False)
class ReducedFiberFactor(PAdicSchemaObject):
    """A reduced linear factor, including its unit normalization and multiplicity."""

    point: ReducedProjectivePoint
    multiplicity: int
    linear_coefficient: int | None

    schema_version = "arbogast.padic.reduced-fiber-factor/v1"

    def __init__(
        self,
        point: ReducedProjectivePoint,
        multiplicity: int,
        linear_coefficient: int | None,
    ) -> None:
        if not isinstance(point, ReducedProjectivePoint):
            raise TypeError("reduced fiber factor needs a ReducedProjectivePoint")
        point.verify()
        normalized_multiplicity = strict_int(
            multiplicity,
            "reduced fiber multiplicity",
            minimum=1,
        )
        if normalized_multiplicity > MAX_LOCAL_DEGREE:
            raise PAdicValidationError("reduced fiber multiplicity exceeds the bounded degree")
        if point.is_infinity:
            if linear_coefficient is not None:
                raise PAdicValidationError("infinity has no affine linear coefficient")
            normalized_coefficient = None
        else:
            if linear_coefficient is None:
                raise PAdicValidationError("finite reduced factor needs a linear coefficient")
            normalized_coefficient = strict_int(
                linear_coefficient,
                "reduced linear coefficient",
                minimum=1,
            )
            if normalized_coefficient >= point.prime:
                raise PAdicValidationError("reduced linear coefficient is not canonical")
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "multiplicity", normalized_multiplicity)
        object.__setattr__(self, "linear_coefficient", normalized_coefficient)

    def affine_polynomial(self) -> FPPolynomial:
        if self.point.residue is None or self.linear_coefficient is None:
            raise PAdicValidationError("infinity has no affine factor polynomial")
        prime = self.point.prime
        return (
            (-self.point.residue * self.linear_coefficient) % prime,
            self.linear_coefficient,
        )

    def verify(self) -> bool:
        if not isinstance(self.point, ReducedProjectivePoint):
            raise PAdicVerificationError("reduced factor point has the wrong type")
        self.point.verify()
        if type(self.multiplicity) is not int or not 1 <= self.multiplicity <= MAX_LOCAL_DEGREE:
            raise PAdicVerificationError("reduced factor multiplicity was altered")
        if self.point.is_infinity:
            if self.linear_coefficient is not None:
                raise PAdicVerificationError("infinity factor normalization was altered")
        elif (
            type(self.linear_coefficient) is not int
            or not 1 <= self.linear_coefficient < self.point.prime
        ):
            raise PAdicVerificationError("finite factor normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "linear_coefficient": self.linear_coefficient,
            "multiplicity": self.multiplicity,
            "point": self.point.to_canonical_data(),
            "type": "arbogast.padic.reduced_fiber_factor",
        }


@dataclass(frozen=True, slots=True, init=False)
class ReducedBranchFiber(PAdicSchemaObject):
    """A complete branch-fibre identity over the residue field."""

    branch: BranchValue
    prime: int
    scalar: int
    factors: tuple[ReducedFiberFactor, ...]

    schema_version = "arbogast.padic.reduced-branch-fiber/v1"

    def __init__(
        self,
        branch: BranchValue,
        prime: int,
        scalar: int,
        factors: Sequence[ReducedFiberFactor],
    ) -> None:
        if not isinstance(branch, BranchValue):
            raise TypeError("reduced branch fibre needs a BranchValue")
        normalized_prime = _prime(prime)
        normalized_scalar = strict_int(scalar, "reduced branch scalar", minimum=0)
        if not 0 < normalized_scalar < normalized_prime:
            raise PAdicValidationError("reduced branch scalar must be a nonzero residue")
        if not 1 <= len(factors) <= MAX_LOCAL_DEGREE:
            raise PAdicValidationError("reduced branch factor count exceeds the bounded degree")
        normalized_factors = tuple(factors)
        if any(not isinstance(factor, ReducedFiberFactor) for factor in normalized_factors):
            raise PAdicValidationError("reduced branch fibre needs typed factors")
        if any(factor.point.prime != normalized_prime for factor in normalized_factors):
            raise PAdicValidationError("reduced branch factors use the wrong prime")
        if sum(factor.multiplicity for factor in normalized_factors) > MAX_LOCAL_DEGREE:
            raise PAdicValidationError("reduced branch degree exceeds the bounded degree")
        if len({factor.point for factor in normalized_factors}) != len(normalized_factors):
            raise _GoodReductionFailure("two marked fibre points collide after reduction")
        if branch is BranchValue.INFINITY:
            if (
                normalized_scalar != 1
                or len(normalized_factors) != 1
                or not normalized_factors[0].point.is_infinity
            ):
                raise PAdicValidationError("reduced infinity fibre is not normalized")
        elif any(factor.point.is_infinity for factor in normalized_factors):
            raise PAdicValidationError("finite reduced branch fibre contains infinity")
        object.__setattr__(self, "branch", branch)
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "scalar", normalized_scalar)
        object.__setattr__(self, "factors", normalized_factors)

    @property
    def degree(self) -> int:
        return sum(factor.multiplicity for factor in self.factors)

    def affine_polynomial(self) -> FPPolynomial:
        if self.branch is BranchValue.INFINITY:
            raise PAdicValidationError("infinity fibre has no affine polynomial")
        result: FPPolynomial = (1,)
        for factor in self.factors:
            result = _fp_multiply(
                result,
                _fp_power(factor.affine_polynomial(), factor.multiplicity, self.prime),
                self.prime,
            )
        return _fp_scale(result, self.scalar, self.prime)

    def verify(self) -> bool:
        if not isinstance(self.branch, BranchValue):
            raise PAdicVerificationError("reduced branch tag was altered")
        if type(self.prime) is not int or not 2 <= self.prime <= MAX_REDUCTION_PRIME:
            raise PAdicVerificationError("reduced branch prime exceeds the bounded lane")
        if not _is_prime(self.prime):
            raise PAdicVerificationError("reduced branch prime was altered")
        if type(self.scalar) is not int or not 0 < self.scalar < self.prime:
            raise PAdicVerificationError("reduced branch scalar was altered")
        if not isinstance(self.factors, tuple) or not 1 <= len(self.factors) <= MAX_LOCAL_DEGREE:
            raise PAdicVerificationError("reduced branch factor tuple was altered")
        if any(not isinstance(factor, ReducedFiberFactor) for factor in self.factors):
            raise PAdicVerificationError("reduced branch factor type was altered")
        if self.degree > MAX_LOCAL_DEGREE:
            raise PAdicVerificationError("reduced branch degree exceeds the bounded degree")
        for factor in self.factors:
            factor.verify()
        if any(factor.point.prime != self.prime for factor in self.factors) or len(
            {factor.point for factor in self.factors}
        ) != len(self.factors):
            raise PAdicVerificationError("reduced branch point data was altered")
        if self.branch is BranchValue.INFINITY:
            if self.scalar != 1 or len(self.factors) != 1 or not self.factors[0].point.is_infinity:
                raise PAdicVerificationError("reduced infinity fibre was altered")
        elif any(factor.point.is_infinity for factor in self.factors):
            raise PAdicVerificationError("finite reduced branch fibre contains infinity")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "branch": self.branch.value,
            "factors": [factor.to_canonical_data() for factor in self.factors],
            "prime": self.prime,
            "scalar": self.scalar,
            "type": "arbogast.padic.reduced_branch_fiber",
        }


def _reduce_factor(
    factor: FiberFactor,
    prime: int,
) -> ReducedFiberFactor:
    point = factor.point
    multiplicity = factor.multiplicity
    reduced_point = ReducedProjectivePoint.reduce(point, prime)
    linear_coefficient = None if point.is_infinity else point.denominator % prime
    if linear_coefficient == 0:
        raise _GoodReductionFailure("fiber factor loses its linear term after reduction")
    return ReducedFiberFactor(reduced_point, multiplicity, linear_coefficient)


@dataclass(frozen=True, slots=True)
class _GoodReductionData:
    reduced_polynomial: FPPolynomial
    reduced_derivative: FPPolynomial
    reduced_fibers: tuple[ReducedBranchFiber, ...]
    reduced_derivative_factors: tuple[ReducedFiberFactor, ...]
    marked_source_points: tuple[ReducedProjectivePoint, ...]
    ramification_points: tuple[ReducedProjectivePoint, ...]


def _good_reduction_data(cover: ThreePointCover, prime: int) -> _GoodReductionData:
    cover.verify()
    if prime != 5 or not _is_supported_beta_cover(cover):
        raise _GoodReductionFailure("version 0.5 certifies only beta(z)=27/4*z^2*(1-z) at p=5")
    reduced_polynomial = _reduce_rational_polynomial(cover, prime)
    if len(reduced_polynomial) - 1 != cover.degree or reduced_polynomial[-1] == 0:
        raise _GoodReductionFailure("the displayed map loses degree after reduction")

    reduced_fibers: list[ReducedBranchFiber] = []
    all_marked_points: list[ReducedProjectivePoint] = []
    for fiber in cover.fibers:
        scalar = _reduce_fraction(
            fiber.scalar.numerator,
            fiber.scalar.denominator,
            prime,
            f"{fiber.branch.value}-fiber scalar",
        )
        factors = tuple(_reduce_factor(factor, prime) for factor in fiber.factors)
        reduced = ReducedBranchFiber(fiber.branch, prime, scalar, factors)
        if reduced.degree != cover.degree:
            raise _GoodReductionFailure("a reduced branch fibre loses degree")
        reduced_fibers.append(reduced)
        all_marked_points.extend(factor.point for factor in factors)

    zero, one, _infinity = reduced_fibers
    if zero.affine_polynomial() != reduced_polynomial:
        raise _GoodReductionFailure("the zero-fibre identity fails after reduction")
    if one.affine_polynomial() != _fp_subtract_constant(reduced_polynomial, 1, prime):
        raise _GoodReductionFailure("the one-fibre identity fails after reduction")
    if len(set(all_marked_points)) != len(all_marked_points):
        raise _GoodReductionFailure("marked branch-preimage sections collide after reduction")

    reduced_derivative = _fp_derivative(reduced_polynomial, prime)
    if reduced_derivative == (0,):
        raise _GoodReductionFailure("the reduced map is inseparable")
    derivative_scalar = _reduce_fraction(
        cover.derivative_witness.scalar.numerator,
        cover.derivative_witness.scalar.denominator,
        prime,
        "derivative scalar",
    )
    derivative_factors = tuple(
        _reduce_factor(factor, prime) for factor in cover.derivative_witness.factors
    )
    if len({factor.point for factor in derivative_factors}) != len(derivative_factors):
        raise _GoodReductionFailure("critical points collide after reduction")
    derivative_product: FPPolynomial = (1,)
    for factor in derivative_factors:
        derivative_product = _fp_multiply(
            derivative_product,
            _fp_power(factor.affine_polynomial(), factor.multiplicity, prime),
            prime,
        )
    if _fp_scale(derivative_product, derivative_scalar, prime) != reduced_derivative:
        raise _GoodReductionFailure("the derivative factorization fails after reduction")
    if any(
        factor.multiplicity % prime == 0 for fiber in reduced_fibers for factor in fiber.factors
    ):
        raise _GoodReductionFailure("a ramification index is wild at the reduction prime")

    return _GoodReductionData(
        reduced_polynomial,
        reduced_derivative,
        tuple(reduced_fibers),
        derivative_factors,
        tuple(all_marked_points),
        (
            *tuple(factor.point for factor in derivative_factors),
            ReducedProjectivePoint(prime, None),
        ),
    )


@dataclass(frozen=True, slots=True, init=False)
class GoodReductionWitness(PAdicSchemaObject):
    """Portable replay data for tame good reduction of the displayed marked model."""

    cover: ThreePointCover
    prime: int
    reduced_polynomial: FPPolynomial
    reduced_derivative: FPPolynomial
    reduced_fibers: tuple[ReducedBranchFiber, ...]
    reduced_derivative_factors: tuple[ReducedFiberFactor, ...]
    marked_source_points: tuple[ReducedProjectivePoint, ...]
    ramification_points: tuple[ReducedProjectivePoint, ...]
    degree_preserved: bool
    tame: bool

    schema_version = "arbogast.padic.good-reduction-witness/v1"

    def __init__(self, cover: ThreePointCover, prime: int) -> None:
        if not isinstance(cover, ThreePointCover):
            raise TypeError("good-reduction witness needs a ThreePointCover")
        normalized_prime = _prime(prime)
        data = _good_reduction_data(cover, normalized_prime)
        object.__setattr__(self, "cover", cover)
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "reduced_polynomial", data.reduced_polynomial)
        object.__setattr__(self, "reduced_derivative", data.reduced_derivative)
        object.__setattr__(self, "reduced_fibers", data.reduced_fibers)
        object.__setattr__(self, "reduced_derivative_factors", data.reduced_derivative_factors)
        object.__setattr__(self, "marked_source_points", data.marked_source_points)
        object.__setattr__(self, "ramification_points", data.ramification_points)
        object.__setattr__(self, "degree_preserved", True)
        object.__setattr__(self, "tame", True)

    def verify(self) -> bool:
        if not isinstance(self.cover, ThreePointCover):
            raise PAdicVerificationError("good-reduction cover has the wrong type")
        self.cover.verify()
        if type(self.prime) is not int or not 2 <= self.prime <= MAX_REDUCTION_PRIME:
            raise PAdicVerificationError("good-reduction prime exceeds the bounded lane")
        if not _is_prime(self.prime):
            raise PAdicVerificationError("good-reduction prime was altered")
        try:
            expected = _good_reduction_data(self.cover, self.prime)
        except PAdicValidationError as exc:
            raise PAdicVerificationError(f"good-reduction replay failed: {exc}") from exc
        fields = (
            (self.reduced_polynomial, expected.reduced_polynomial, "polynomial"),
            (self.reduced_derivative, expected.reduced_derivative, "derivative"),
            (self.reduced_fibers, expected.reduced_fibers, "branch fibres"),
            (
                self.reduced_derivative_factors,
                expected.reduced_derivative_factors,
                "derivative factors",
            ),
            (self.marked_source_points, expected.marked_source_points, "marked points"),
            (self.ramification_points, expected.ramification_points, "ramification points"),
        )
        for actual, replayed, name in fields:
            if actual != replayed:
                raise PAdicVerificationError(f"reduced {name} were altered")
        if type(self.degree_preserved) is not bool or not self.degree_preserved:
            raise PAdicVerificationError("degree-preservation flag was altered")
        if type(self.tame) is not bool or not self.tame:
            raise PAdicVerificationError("tameness flag was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cover": self.cover.to_canonical_data(),
            "degree_preserved": self.degree_preserved,
            "marked_source_points": [
                point.to_canonical_data() for point in self.marked_source_points
            ],
            "prime": self.prime,
            "ramification_points": [
                point.to_canonical_data() for point in self.ramification_points
            ],
            "reduced_derivative": list(self.reduced_derivative),
            "reduced_derivative_factors": [
                factor.to_canonical_data() for factor in self.reduced_derivative_factors
            ],
            "reduced_fibers": [fiber.to_canonical_data() for fiber in self.reduced_fibers],
            "reduced_polynomial": list(self.reduced_polynomial),
            "tame": self.tame,
            "type": "arbogast.padic.good_reduction_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class GoodReduction(PAdicSchemaObject):
    """The certified good-reduction value, kept distinct from its proof witness."""

    cover: ThreePointCover
    prime: int
    witness: GoodReductionWitness

    schema_version = "arbogast.padic.good-reduction/v1"

    def __init__(self, cover: ThreePointCover, prime: int, witness: GoodReductionWitness) -> None:
        if not isinstance(cover, ThreePointCover):
            raise TypeError("good reduction needs a ThreePointCover")
        normalized_prime = _prime(prime)
        if not isinstance(witness, GoodReductionWitness):
            raise TypeError("good reduction needs a GoodReductionWitness")
        witness.verify()
        if witness.cover != cover or witness.prime != normalized_prime:
            raise PAdicValidationError("good-reduction witness is not bound to the request")
        object.__setattr__(self, "cover", cover)
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "witness", witness)

    @property
    def reduced_polynomial(self) -> FPPolynomial:
        return self.witness.reduced_polynomial

    @property
    def ramification_points(self) -> tuple[ReducedProjectivePoint, ...]:
        return self.witness.ramification_points

    def verify(self) -> bool:
        if not isinstance(self.cover, ThreePointCover):
            raise PAdicVerificationError("good-reduction cover has the wrong type")
        if not isinstance(self.witness, GoodReductionWitness):
            raise PAdicVerificationError("good-reduction witness has the wrong type")
        self.cover.verify()
        self.witness.verify()
        if (
            type(self.prime) is not int
            or self.witness.cover != self.cover
            or self.witness.prime != self.prime
        ):
            raise PAdicVerificationError("good-reduction request binding was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cover_id": self.cover.content_id,
            "prime": self.prime,
            "type": "arbogast.padic.good_reduction",
            "witness": self.witness.to_canonical_data(),
        }


@dataclass(frozen=True, slots=True, init=False)
class SpecialFiberMarking(PAdicSchemaObject):
    """One marked specialization above a normalized target branch value."""

    label: str
    branch: BranchValue
    point: ReducedProjectivePoint
    ramification_index: int

    schema_version = "arbogast.padic.special-fiber-marking/v1"

    def __init__(
        self,
        label: str,
        branch: BranchValue,
        point: ReducedProjectivePoint,
        ramification_index: int,
    ) -> None:
        normalized_label = canonical_label(label, "special-fiber marking label")
        if not isinstance(branch, BranchValue):
            raise TypeError("special-fiber marking needs a BranchValue")
        if not isinstance(point, ReducedProjectivePoint):
            raise TypeError("special-fiber marking needs a ReducedProjectivePoint")
        point.verify()
        index = strict_int(ramification_index, "ramification index", minimum=1)
        if index > MAX_LOCAL_DEGREE:
            raise PAdicValidationError("ramification index exceeds the bounded degree")
        object.__setattr__(self, "label", normalized_label)
        object.__setattr__(self, "branch", branch)
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "ramification_index", index)

    def verify(self) -> bool:
        if canonical_label(self.label, "special-fiber marking label") != self.label:
            raise PAdicVerificationError("special-fiber marking label was altered")
        if not isinstance(self.branch, BranchValue):
            raise PAdicVerificationError("special-fiber marking branch was altered")
        if not isinstance(self.point, ReducedProjectivePoint):
            raise PAdicVerificationError("special-fiber marking point has the wrong type")
        self.point.verify()
        if (
            type(self.ramification_index) is not int
            or not 1 <= self.ramification_index <= MAX_LOCAL_DEGREE
        ):
            raise PAdicVerificationError("special-fiber ramification index was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "branch": self.branch.value,
            "label": self.label,
            "point": self.point.to_canonical_data(),
            "ramification_index": self.ramification_index,
            "type": "arbogast.padic.special_fiber_marking",
        }


@dataclass(frozen=True, slots=True, init=False)
class MarkedReductionComponent(PAdicSchemaObject):
    """One smooth component with explicit markings and node incidences."""

    component_id: str
    role: str
    genus: int
    markings: tuple[SpecialFiberMarking, ...]
    incident_nodes: tuple[str, ...]
    smooth: bool

    schema_version = "arbogast.padic.marked-reduction-component/v1"

    def __init__(
        self,
        component_id: str,
        role: str,
        genus: int,
        markings: Sequence[SpecialFiberMarking],
        *,
        incident_nodes: Sequence[str] = (),
    ) -> None:
        normalized_id = canonical_label(component_id, "reduction component ID")
        normalized_role = canonical_label(role, "reduction component role")
        if normalized_role not in {"source", "target"}:
            raise PAdicValidationError("reduction component role must be source or target")
        normalized_genus = strict_int(genus, "reduction component genus", minimum=0)
        normalized_markings = tuple(markings)
        if any(not isinstance(marking, SpecialFiberMarking) for marking in normalized_markings):
            raise PAdicValidationError("reduction component markings have the wrong type")
        if len({marking.label for marking in normalized_markings}) != len(normalized_markings):
            raise PAdicValidationError("reduction component marking labels are not unique")
        if len({marking.point for marking in normalized_markings}) != len(normalized_markings):
            raise PAdicValidationError("reduction component markings collide")
        nodes = tuple(canonical_label(node, "incident node ID") for node in incident_nodes)
        if len(set(nodes)) != len(nodes) or nodes != tuple(sorted(nodes)):
            raise PAdicValidationError("incident node IDs must be unique and sorted")
        object.__setattr__(self, "component_id", normalized_id)
        object.__setattr__(self, "role", normalized_role)
        object.__setattr__(self, "genus", normalized_genus)
        object.__setattr__(self, "markings", normalized_markings)
        object.__setattr__(self, "incident_nodes", nodes)
        object.__setattr__(self, "smooth", True)

    @property
    def stability_index(self) -> int:
        return 2 * self.genus - 2 + len(self.markings) + len(self.incident_nodes)

    def verify(self) -> bool:
        if canonical_label(self.component_id, "reduction component ID") != self.component_id:
            raise PAdicVerificationError("reduction component ID was altered")
        if self.role not in {"source", "target"}:
            raise PAdicVerificationError("reduction component role was altered")
        if type(self.genus) is not int or self.genus < 0:
            raise PAdicVerificationError("reduction component genus was altered")
        if not isinstance(self.markings, tuple) or any(
            not isinstance(marking, SpecialFiberMarking) for marking in self.markings
        ):
            raise PAdicVerificationError("reduction component markings were altered")
        for marking in self.markings:
            marking.verify()
        if len({marking.label for marking in self.markings}) != len(self.markings) or len(
            {marking.point for marking in self.markings}
        ) != len(self.markings):
            raise PAdicVerificationError("reduction component marking separation was altered")
        if (
            not isinstance(self.incident_nodes, tuple)
            or any(type(node) is not str for node in self.incident_nodes)
            or len(set(self.incident_nodes)) != len(self.incident_nodes)
            or tuple(sorted(self.incident_nodes)) != self.incident_nodes
        ):
            raise PAdicVerificationError("reduction component node incidences were altered")
        if type(self.smooth) is not bool or not self.smooth:
            raise PAdicVerificationError("component smoothness flag was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "component_id": self.component_id,
            "genus": self.genus,
            "incident_nodes": list(self.incident_nodes),
            "markings": [marking.to_canonical_data() for marking in self.markings],
            "role": self.role,
            "smooth": self.smooth,
            "stability_index": self.stability_index,
            "type": "arbogast.padic.marked_reduction_component",
        }


@dataclass(frozen=True, slots=True, init=False)
class ComponentMapWitness(PAdicSchemaObject):
    """The degree of a special-fiber component map."""

    source_component_id: str
    target_component_id: str
    degree: int

    schema_version = "arbogast.padic.component-map-witness/v1"

    def __init__(self, source_component_id: str, target_component_id: str, degree: int) -> None:
        source = canonical_label(source_component_id, "source component ID")
        target = canonical_label(target_component_id, "target component ID")
        normalized_degree = strict_int(degree, "component-map degree", minimum=1)
        if normalized_degree > MAX_LOCAL_DEGREE:
            raise PAdicValidationError("component-map degree exceeds the bounded slice")
        object.__setattr__(self, "source_component_id", source)
        object.__setattr__(self, "target_component_id", target)
        object.__setattr__(self, "degree", normalized_degree)

    def verify(self) -> bool:
        if (
            canonical_label(self.source_component_id, "source component ID")
            != self.source_component_id
        ):
            raise PAdicVerificationError("source component ID was altered")
        if (
            canonical_label(self.target_component_id, "target component ID")
            != self.target_component_id
        ):
            raise PAdicVerificationError("target component ID was altered")
        if type(self.degree) is not int or not 1 <= self.degree <= MAX_LOCAL_DEGREE:
            raise PAdicVerificationError("component-map degree was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "degree": self.degree,
            "source_component_id": self.source_component_id,
            "target_component_id": self.target_component_id,
            "type": "arbogast.padic.component_map_witness",
        }


def _source_markings(good: GoodReduction) -> tuple[SpecialFiberMarking, ...]:
    markings: list[SpecialFiberMarking] = []
    for fiber in good.witness.reduced_fibers:
        for index, factor in enumerate(fiber.factors):
            markings.append(
                SpecialFiberMarking(
                    f"source.{fiber.branch.value}.{index}",
                    fiber.branch,
                    factor.point,
                    factor.multiplicity,
                )
            )
    return tuple(markings)


def _target_markings(prime: int) -> tuple[SpecialFiberMarking, ...]:
    return (
        SpecialFiberMarking(
            "target.zero",
            BranchValue.ZERO,
            ReducedProjectivePoint(prime, 0),
            1,
        ),
        SpecialFiberMarking(
            "target.one",
            BranchValue.ONE,
            ReducedProjectivePoint(prime, 1),
            1,
        ),
        SpecialFiberMarking(
            "target.infinity",
            BranchValue.INFINITY,
            ReducedProjectivePoint(prime, None),
            1,
        ),
    )


@dataclass(frozen=True, slots=True, init=False)
class SemistableReductionWitness(PAdicSchemaObject):
    """A one-component smooth marked semistable model induced by good reduction."""

    good_reduction: GoodReduction
    source_components: tuple[MarkedReductionComponent, ...]
    target_components: tuple[MarkedReductionComponent, ...]
    nodes: tuple[str, ...]
    component_maps: tuple[ComponentMapWitness, ...]
    complete: bool

    schema_version = "arbogast.padic.semistable-reduction-witness/v1"

    def __init__(self, good_reduction: GoodReduction) -> None:
        if not isinstance(good_reduction, GoodReduction):
            raise TypeError("semistable witness needs a GoodReduction")
        good_reduction.verify()
        source = MarkedReductionComponent(
            "source.0",
            "source",
            0,
            _source_markings(good_reduction),
        )
        target = MarkedReductionComponent(
            "target.0",
            "target",
            0,
            _target_markings(good_reduction.prime),
        )
        component_map = ComponentMapWitness(
            source.component_id,
            target.component_id,
            good_reduction.cover.degree,
        )
        object.__setattr__(self, "good_reduction", good_reduction)
        object.__setattr__(self, "source_components", (source,))
        object.__setattr__(self, "target_components", (target,))
        object.__setattr__(self, "nodes", ())
        object.__setattr__(self, "component_maps", (component_map,))
        object.__setattr__(self, "complete", True)

    def verify(self) -> bool:
        if not isinstance(self.good_reduction, GoodReduction):
            raise PAdicVerificationError("semistable good-reduction input has the wrong type")
        self.good_reduction.verify()
        replay = SemistableReductionWitness(self.good_reduction)
        fields = (
            self.source_components,
            self.target_components,
            self.nodes,
            self.component_maps,
        )
        expected = (
            replay.source_components,
            replay.target_components,
            replay.nodes,
            replay.component_maps,
        )
        if fields != expected:
            raise PAdicVerificationError("semistable component model was altered")
        if type(self.complete) is not bool or not self.complete:
            raise PAdicVerificationError("semistable completeness flag was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "complete": self.complete,
            "component_maps": [item.to_canonical_data() for item in self.component_maps],
            "good_reduction": self.good_reduction.to_canonical_data(),
            "nodes": list(self.nodes),
            "source_components": [item.to_canonical_data() for item in self.source_components],
            "target_components": [item.to_canonical_data() for item in self.target_components],
            "type": "arbogast.padic.semistable_reduction_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class SemistableReduction(PAdicSchemaObject):
    """A complete marked semistable-reduction value distinct from its witness."""

    cover: ThreePointCover
    prime: int
    witness: SemistableReductionWitness

    schema_version = "arbogast.padic.semistable-reduction/v1"

    def __init__(
        self,
        cover: ThreePointCover,
        prime: int,
        witness: SemistableReductionWitness,
    ) -> None:
        if not isinstance(cover, ThreePointCover):
            raise TypeError("semistable reduction needs a ThreePointCover")
        normalized_prime = _prime(prime)
        if not isinstance(witness, SemistableReductionWitness):
            raise TypeError("semistable reduction needs a SemistableReductionWitness")
        witness.verify()
        if (
            witness.good_reduction.cover != cover
            or witness.good_reduction.prime != normalized_prime
        ):
            raise PAdicValidationError("semistable witness is not bound to the request")
        object.__setattr__(self, "cover", cover)
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "witness", witness)

    @property
    def source_components(self) -> tuple[MarkedReductionComponent, ...]:
        return self.witness.source_components

    @property
    def target_components(self) -> tuple[MarkedReductionComponent, ...]:
        return self.witness.target_components

    @property
    def nodes(self) -> tuple[str, ...]:
        return self.witness.nodes

    def verify(self) -> bool:
        if not isinstance(self.cover, ThreePointCover):
            raise PAdicVerificationError("semistable cover has the wrong type")
        if not isinstance(self.witness, SemistableReductionWitness):
            raise PAdicVerificationError("semistable witness has the wrong type")
        self.cover.verify()
        self.witness.verify()
        if (
            type(self.prime) is not int
            or self.witness.good_reduction.cover != self.cover
            or self.witness.good_reduction.prime != self.prime
        ):
            raise PAdicVerificationError("semistable request binding was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cover_id": self.cover.content_id,
            "prime": self.prime,
            "type": "arbogast.padic.semistable_reduction",
            "witness": self.witness.to_canonical_data(),
        }


@dataclass(frozen=True, slots=True, init=False)
class StableReductionWitness(PAdicSchemaObject):
    """Proof that the one-component marked semistable model is already stable."""

    semistable_reduction: SemistableReduction
    source_stability_indices: tuple[int, ...]
    target_stability_indices: tuple[int, ...]
    contracted_components: tuple[str, ...]
    complete: bool

    schema_version = "arbogast.padic.stable-reduction-witness/v1"

    def __init__(self, semistable_reduction: SemistableReduction) -> None:
        if not isinstance(semistable_reduction, SemistableReduction):
            raise TypeError("stable witness needs a SemistableReduction")
        semistable_reduction.verify()
        source_indices = tuple(
            component.stability_index for component in semistable_reduction.source_components
        )
        target_indices = tuple(
            component.stability_index for component in semistable_reduction.target_components
        )
        if any(index <= 0 for index in source_indices + target_indices):
            raise PAdicValidationError(
                "automatic component contraction is outside the bounded stable lane"
            )
        object.__setattr__(self, "semistable_reduction", semistable_reduction)
        object.__setattr__(self, "source_stability_indices", source_indices)
        object.__setattr__(self, "target_stability_indices", target_indices)
        object.__setattr__(self, "contracted_components", ())
        object.__setattr__(self, "complete", True)

    def verify(self) -> bool:
        if not isinstance(self.semistable_reduction, SemistableReduction):
            raise PAdicVerificationError("stable semistable input has the wrong type")
        self.semistable_reduction.verify()
        source_indices = tuple(
            component.stability_index for component in self.semistable_reduction.source_components
        )
        target_indices = tuple(
            component.stability_index for component in self.semistable_reduction.target_components
        )
        if (
            self.source_stability_indices != source_indices
            or self.target_stability_indices != target_indices
            or any(index <= 0 for index in source_indices + target_indices)
        ):
            raise PAdicVerificationError("stable component inequalities were altered")
        if self.contracted_components != ():
            raise PAdicVerificationError("bounded good-reduction lane cannot contract components")
        if type(self.complete) is not bool or not self.complete:
            raise PAdicVerificationError("stable completeness flag was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "complete": self.complete,
            "contracted_components": list(self.contracted_components),
            "semistable_reduction": self.semistable_reduction.to_canonical_data(),
            "source_stability_indices": list(self.source_stability_indices),
            "target_stability_indices": list(self.target_stability_indices),
            "type": "arbogast.padic.stable_reduction_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class StableReduction(PAdicSchemaObject):
    """A complete marked stable-reduction value distinct from its witness."""

    cover: ThreePointCover
    prime: int
    semistable_reduction: SemistableReduction
    witness: StableReductionWitness

    schema_version = "arbogast.padic.stable-reduction/v1"

    def __init__(
        self,
        cover: ThreePointCover,
        prime: int,
        semistable_reduction: SemistableReduction,
        witness: StableReductionWitness,
    ) -> None:
        if not isinstance(cover, ThreePointCover):
            raise TypeError("stable reduction needs a ThreePointCover")
        normalized_prime = _prime(prime)
        if not isinstance(semistable_reduction, SemistableReduction):
            raise TypeError("stable reduction needs a SemistableReduction")
        if not isinstance(witness, StableReductionWitness):
            raise TypeError("stable reduction needs a StableReductionWitness")
        semistable_reduction.verify()
        witness.verify()
        if (
            semistable_reduction.cover != cover
            or semistable_reduction.prime != normalized_prime
            or witness.semistable_reduction != semistable_reduction
        ):
            raise PAdicValidationError("stable witness is not bound to the request")
        object.__setattr__(self, "cover", cover)
        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "semistable_reduction", semistable_reduction)
        object.__setattr__(self, "witness", witness)

    @property
    def source_components(self) -> tuple[MarkedReductionComponent, ...]:
        return self.semistable_reduction.source_components

    @property
    def target_components(self) -> tuple[MarkedReductionComponent, ...]:
        return self.semistable_reduction.target_components

    @property
    def nodes(self) -> tuple[str, ...]:
        return self.semistable_reduction.nodes

    def verify(self) -> bool:
        if not isinstance(self.cover, ThreePointCover):
            raise PAdicVerificationError("stable cover has the wrong type")
        if not isinstance(self.semistable_reduction, SemistableReduction):
            raise PAdicVerificationError("stable semistable input has the wrong type")
        if not isinstance(self.witness, StableReductionWitness):
            raise PAdicVerificationError("stable witness has the wrong type")
        self.cover.verify()
        self.semistable_reduction.verify()
        self.witness.verify()
        if (
            type(self.prime) is not int
            or self.semistable_reduction.cover != self.cover
            or self.semistable_reduction.prime != self.prime
            or self.witness.semistable_reduction != self.semistable_reduction
        ):
            raise PAdicVerificationError("stable request binding was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cover_id": self.cover.content_id,
            "prime": self.prime,
            "semistable_reduction_id": self.semistable_reduction.content_id,
            "type": "arbogast.padic.stable_reduction",
            "witness": self.witness.to_canonical_data(),
        }


def _raw_mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise PAdicVerificationError(f"{name} must be a strict JSON object")
    return cast(dict[str, object], value)


def _raw_list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise PAdicVerificationError(f"{name} must be a strict JSON array")
    return cast(list[object], value)


def _exact_fields(value: dict[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise PAdicVerificationError(f"{name} fields do not match the v1 schema")


def _raw_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise PAdicVerificationError(f"{name} must be an exact integer")
    return value


def _decode_fraction(value: object, name: str) -> Fraction:
    raw = _raw_mapping(value, name)
    _exact_fields(raw, {"denominator", "numerator"}, name)
    numerator = _raw_integer(raw["numerator"], f"{name}.numerator")
    denominator = _raw_integer(raw["denominator"], f"{name}.denominator")
    if denominator <= 0:
        raise PAdicVerificationError(f"{name} denominator must be positive")
    result = Fraction(numerator, denominator)
    if not strict_canonical_equal(raw, _fraction_data(result)):
        raise PAdicVerificationError(f"{name} was not in lowest terms")
    return result


def _decode_dyadic(value: object, name: str) -> Dyadic:
    raw = _raw_mapping(value, name)
    _exact_fields(raw, {"exponent", "mantissa", "type"}, name)
    if raw["type"] != "arbogast.numeric.dyadic":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    try:
        result = Dyadic(
            _raw_integer(raw["mantissa"], f"{name}.mantissa"),
            _raw_integer(raw["exponent"], f"{name}.exponent"),
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} normalization was altered")
    return result


def _decode_complex_dyadic(value: object, name: str) -> ComplexDyadic:
    raw = _raw_mapping(value, name)
    _exact_fields(raw, {"imag", "real", "type"}, name)
    if raw["type"] != "arbogast.numeric.complex_dyadic":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    result = ComplexDyadic(
        _decode_dyadic(raw["real"], f"{name}.real"),
        _decode_dyadic(raw["imag"], f"{name}.imag"),
    )
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} normalization was altered")
    return result


def _decode_polynomial(value: object, name: str) -> ExactPolynomial:
    raw = _raw_mapping(value, name)
    _exact_fields(raw, {"nvariables", "terms", "type", "variable_names"}, name)
    if raw["type"] != "arbogast.numeric.exact_polynomial":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    names = _raw_list(raw["variable_names"], f"{name}.variable_names")
    if any(type(item) is not str for item in names):
        raise PAdicVerificationError(f"{name} variable names must be strings")
    terms: list[tuple[tuple[int, ...], ComplexDyadic]] = []
    for index, value_term in enumerate(_raw_list(raw["terms"], f"{name}.terms")):
        term = _raw_mapping(value_term, f"{name}.terms[{index}]")
        _exact_fields(term, {"coefficient", "exponents"}, f"{name}.terms[{index}]")
        exponents = tuple(
            _raw_integer(item, f"{name}.terms[{index}].exponents")
            for item in _raw_list(
                term["exponents"],
                f"{name}.terms[{index}].exponents",
            )
        )
        terms.append(
            (
                exponents,
                _decode_complex_dyadic(
                    term["coefficient"],
                    f"{name}.terms[{index}].coefficient",
                ),
            )
        )
    try:
        result = ExactPolynomial(
            _raw_integer(raw["nvariables"], f"{name}.nvariables"),
            terms,
            variable_names=cast(list[str], names),
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} canonical presentation was altered")
    return result


def _decode_projective_point(value: object, name: str) -> ProjectiveRationalPoint:
    raw = _raw_mapping(value, name)
    _exact_fields(raw, {"denominator", "numerator", "type"}, name)
    if raw["type"] != "arbogast.padic.projective_rational_point":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    try:
        result = ProjectiveRationalPoint(
            _raw_integer(raw["numerator"], f"{name}.numerator"),
            _raw_integer(raw["denominator"], f"{name}.denominator"),
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} canonical coordinate was altered")
    return result


def _decode_fiber_factor(value: object, name: str) -> object:
    from .covers import FiberFactor

    raw = _raw_mapping(value, name)
    _exact_fields(raw, {"multiplicity", "point", "type"}, name)
    if raw["type"] != "arbogast.padic.fiber_factor":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    try:
        result = FiberFactor(
            _decode_projective_point(raw["point"], f"{name}.point"),
            _raw_integer(raw["multiplicity"], f"{name}.multiplicity"),
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} canonical data was altered")
    return result


def _decode_branch_fiber(value: object, name: str) -> object:
    from .covers import BranchFiberWitness, FiberFactor

    raw = _raw_mapping(value, name)
    _exact_fields(raw, {"branch", "factors", "scalar", "type"}, name)
    if raw["type"] != "arbogast.padic.branch_fiber_witness":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    if type(raw["branch"]) is not str:
        raise PAdicVerificationError(f"{name}.branch must be a string")
    raw_factors = _raw_list(raw["factors"], f"{name}.factors")
    if not 1 <= len(raw_factors) <= MAX_LOCAL_DEGREE:
        raise PAdicVerificationError(f"{name} factor count exceeds the bounded slice")
    factors = tuple(
        cast(FiberFactor, _decode_fiber_factor(item, f"{name}.factors[{index}]"))
        for index, item in enumerate(raw_factors)
    )
    try:
        result = BranchFiberWitness(
            raw["branch"],
            _decode_fraction(raw["scalar"], f"{name}.scalar"),
            factors,
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} canonical data was altered")
    return result


def _decode_derivative_witness(value: object, name: str) -> object:
    from .covers import DerivativeWitness, FiberFactor

    raw = _raw_mapping(value, name)
    _exact_fields(raw, {"derivative", "factors", "scalar", "type"}, name)
    if raw["type"] != "arbogast.padic.derivative_witness":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    raw_factors = _raw_list(raw["factors"], f"{name}.factors")
    if not 1 <= len(raw_factors) <= MAX_LOCAL_DEGREE - 1:
        raise PAdicVerificationError(f"{name} factor count exceeds the bounded slice")
    factors = tuple(
        cast(FiberFactor, _decode_fiber_factor(item, f"{name}.factors[{index}]"))
        for index, item in enumerate(raw_factors)
    )
    try:
        result = DerivativeWitness(
            _decode_polynomial(raw["derivative"], f"{name}.derivative"),
            _decode_fraction(raw["scalar"], f"{name}.scalar"),
            factors,
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} canonical data was altered")
    return result


def _decode_cover(value: object, name: str, *, document: bool = False) -> ThreePointCover:
    from .covers import BranchFiberWitness, DerivativeWitness

    raw = _raw_mapping(value, name)
    fields = {
        "degree",
        "derivative_witness",
        "fibers",
        "generic_degree_witness",
        "label",
        "polynomial",
        "riemann_hurwitz_witness",
        "type",
    }
    if document:
        fields.add("schema")
    _exact_fields(raw, fields, name)
    if document and raw["schema"] != ThreePointCover.schema_version:
        raise PAdicVerificationError(f"{name} has the wrong schema")
    if raw["type"] != "arbogast.padic.three_point_cover":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    if raw["label"] is not None and type(raw["label"]) is not str:
        raise PAdicVerificationError(f"{name}.label must be a string or null")
    raw_fibers = _raw_list(raw["fibers"], f"{name}.fibers")
    if len(raw_fibers) != 3:
        raise PAdicVerificationError(f"{name} must contain exactly three branch fibres")
    fibers = tuple(
        cast(BranchFiberWitness, _decode_branch_fiber(item, f"{name}.fibers[{index}]"))
        for index, item in enumerate(raw_fibers)
    )
    try:
        result = ThreePointCover(
            _decode_polynomial(raw["polynomial"], f"{name}.polynomial"),
            fibers,
            cast(
                DerivativeWitness,
                _decode_derivative_witness(
                    raw["derivative_witness"],
                    f"{name}.derivative_witness",
                ),
            ),
            label=raw["label"],
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    expected = result.to_schema_document() if document else result.to_canonical_data()
    if not strict_canonical_equal(raw, expected):
        raise PAdicVerificationError(f"{name} exact identities were altered")
    return result


def _decode_good_witness(value: object, name: str) -> GoodReductionWitness:
    raw = _raw_mapping(value, name)
    _exact_fields(
        raw,
        {
            "cover",
            "degree_preserved",
            "marked_source_points",
            "prime",
            "ramification_points",
            "reduced_derivative",
            "reduced_derivative_factors",
            "reduced_fibers",
            "reduced_polynomial",
            "tame",
            "type",
        },
        name,
    )
    if raw["type"] != "arbogast.padic.good_reduction_witness":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    try:
        result = GoodReductionWitness(
            _decode_cover(raw["cover"], f"{name}.cover"),
            _raw_integer(raw["prime"], f"{name}.prime"),
        )
    except (TypeError, ValueError) as exc:
        raise PAdicVerificationError(f"invalid {name}: {exc}") from exc
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} exact replay data were altered")
    return result


def _decode_good_reduction(value: object, name: str, *, document: bool) -> GoodReduction:
    raw = _raw_mapping(value, name)
    fields = {"cover_id", "prime", "type", "witness"}
    if document:
        fields.add("schema")
    _exact_fields(raw, fields, name)
    if document and raw["schema"] != GoodReduction.schema_version:
        raise PAdicVerificationError(f"{name} has the wrong schema")
    if raw["type"] != "arbogast.padic.good_reduction":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    witness = _decode_good_witness(raw["witness"], f"{name}.witness")
    result = GoodReduction(
        witness.cover,
        _raw_integer(raw["prime"], f"{name}.prime"),
        witness,
    )
    expected = result.to_schema_document() if document else result.to_canonical_data()
    if not strict_canonical_equal(raw, expected):
        raise PAdicVerificationError(f"{name} request binding was altered")
    return result


def _decode_semistable_witness(value: object, name: str) -> SemistableReductionWitness:
    raw = _raw_mapping(value, name)
    _exact_fields(
        raw,
        {
            "complete",
            "component_maps",
            "good_reduction",
            "nodes",
            "source_components",
            "target_components",
            "type",
        },
        name,
    )
    if raw["type"] != "arbogast.padic.semistable_reduction_witness":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    result = SemistableReductionWitness(
        _decode_good_reduction(
            raw["good_reduction"],
            f"{name}.good_reduction",
            document=False,
        )
    )
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} component data were altered")
    return result


def _decode_semistable_reduction(
    value: object,
    name: str,
    *,
    document: bool,
) -> SemistableReduction:
    raw = _raw_mapping(value, name)
    fields = {"cover_id", "prime", "type", "witness"}
    if document:
        fields.add("schema")
    _exact_fields(raw, fields, name)
    if document and raw["schema"] != SemistableReduction.schema_version:
        raise PAdicVerificationError(f"{name} has the wrong schema")
    if raw["type"] != "arbogast.padic.semistable_reduction":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    witness = _decode_semistable_witness(raw["witness"], f"{name}.witness")
    good = witness.good_reduction
    result = SemistableReduction(
        good.cover,
        _raw_integer(raw["prime"], f"{name}.prime"),
        witness,
    )
    expected = result.to_schema_document() if document else result.to_canonical_data()
    if not strict_canonical_equal(raw, expected):
        raise PAdicVerificationError(f"{name} request binding was altered")
    return result


def _decode_stable_witness(value: object, name: str) -> StableReductionWitness:
    raw = _raw_mapping(value, name)
    _exact_fields(
        raw,
        {
            "complete",
            "contracted_components",
            "semistable_reduction",
            "source_stability_indices",
            "target_stability_indices",
            "type",
        },
        name,
    )
    if raw["type"] != "arbogast.padic.stable_reduction_witness":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    result = StableReductionWitness(
        _decode_semistable_reduction(
            raw["semistable_reduction"],
            f"{name}.semistable_reduction",
            document=False,
        )
    )
    if not strict_canonical_equal(raw, result.to_canonical_data()):
        raise PAdicVerificationError(f"{name} stability data were altered")
    return result


def _decode_stable_reduction(value: object, name: str, *, document: bool) -> StableReduction:
    raw = _raw_mapping(value, name)
    fields = {
        "cover_id",
        "prime",
        "semistable_reduction_id",
        "type",
        "witness",
    }
    if document:
        fields.add("schema")
    _exact_fields(raw, fields, name)
    if document and raw["schema"] != StableReduction.schema_version:
        raise PAdicVerificationError(f"{name} has the wrong schema")
    if raw["type"] != "arbogast.padic.stable_reduction":
        raise PAdicVerificationError(f"{name} has the wrong type tag")
    witness = _decode_stable_witness(raw["witness"], f"{name}.witness")
    semistable = witness.semistable_reduction
    result = StableReduction(
        semistable.cover,
        _raw_integer(raw["prime"], f"{name}.prime"),
        semistable,
        witness,
    )
    expected = result.to_schema_document() if document else result.to_canonical_data()
    if not strict_canonical_equal(raw, expected):
        raise PAdicVerificationError(f"{name} request binding was altered")
    return result


def _certified_source_value(source: object, expected_type: type[object], name: str) -> object:
    from .results import Certified

    if not isinstance(source, Certified):
        raise TypeError(f"{name} must be a ThreePointCover or Certified result")
    source.verify()
    if not isinstance(source.value, expected_type):
        raise TypeError(f"{name} Certified value has the wrong result type")
    return source.value


def _operation_prime(value: int) -> int:
    return strict_int(value, "reduction prime", minimum=2)


def _unsupported_geometry(
    operation: str,
    cover: ThreePointCover,
    prime: int,
) -> Unsupported:
    from .results import unsupported_result

    return unsupported_result(
        operation,
        "outside-beta-p5-certified-slice",
        "Version 0.5 certifies automatic reduction geometry only for the exact marked "
        "beta(z)=27/4*z^2*(1-z) presentation at p=5.",
        requested={"cover_id": cover.content_id, "prime": prime},
        supported=("exact marked beta(z)=27/4*z^2*(1-z) at p=5",),
        family="three-point",
    )


def good_reduction(
    cover: ThreePointCover,
    prime: int,
    *,
    witness: GoodReductionWitness | None = None,
) -> PAdicResult[GoodReduction]:
    """Certify tame good reduction of the displayed normalized marked model.

    Failure of these checks is explicitly ``Unknown``: it is not a proof that
    no coordinate change, extension, or alternate model has good reduction.
    """

    from .results import certified_result, unknown_result

    if not isinstance(cover, ThreePointCover):
        raise TypeError("good_reduction needs a ThreePointCover")
    cover.verify()
    normalized_prime = _operation_prime(prime)
    if normalized_prime != 5 or not _is_supported_beta_cover(cover):
        return _unsupported_geometry("padic.good_reduction", cover, normalized_prime)
    if witness is None:
        try:
            exact_witness = GoodReductionWitness(cover, normalized_prime)
        except _GoodReductionFailure as exc:
            return unknown_result(
                "padic.good_reduction",
                "displayed-model-not-certified-good",
                f"The displayed marked model failed a sufficient good-reduction check: {exc}",
                requested={"cover_id": cover.content_id, "prime": normalized_prime},
                family="three-point",
            )
    else:
        if not isinstance(witness, GoodReductionWitness):
            raise TypeError("witness must be a GoodReductionWitness or None")
        witness.verify()
        if witness.cover != cover or witness.prime != normalized_prime:
            raise PAdicValidationError("good-reduction witness is foreign to the request")
        exact_witness = witness
    value = GoodReduction(cover, normalized_prime, exact_witness)
    return certified_result(value, "good-reduction")


def semistable_reduction(
    source: ThreePointCover | Certified[GoodReduction],
    prime: int | None = None,
    *,
    witness: SemistableReductionWitness | None = None,
) -> PAdicResult[SemistableReduction]:
    """Produce the one-component semistable model in the tame good lane only."""

    from .results import Certified, certified_result, unsupported_result

    if isinstance(source, ThreePointCover):
        source.verify()
        if prime is None:
            raise TypeError("prime is required when source is a ThreePointCover")
        normalized_prime = _operation_prime(prime)
        if normalized_prime != 5 or not _is_supported_beta_cover(source):
            return _unsupported_geometry("padic.semistable_reduction", source, normalized_prime)
        if witness is None:
            try:
                good = GoodReduction(
                    source,
                    normalized_prime,
                    GoodReductionWitness(source, normalized_prime),
                )
            except _GoodReductionFailure as exc:
                return unsupported_result(
                    "padic.semistable_reduction",
                    "non-good-semistable-discovery-unsupported",
                    "Automatic blow-ups, extensions, and non-good semistable discovery are "
                    f"outside 0.5; the displayed model failed because: {exc}",
                    requested={"cover_id": source.content_id, "prime": normalized_prime},
                    supported=("one-component tame good-reduction models",),
                    family="three-point",
                )
            exact_witness = SemistableReductionWitness(good)
        else:
            if not isinstance(witness, SemistableReductionWitness):
                raise TypeError("witness must be a SemistableReductionWitness or None")
            witness.verify()
            if (
                witness.good_reduction.cover != source
                or witness.good_reduction.prime != normalized_prime
            ):
                raise PAdicValidationError("semistable witness is foreign to the request")
            exact_witness = witness
        cover = source
    elif isinstance(source, Certified):
        good = cast(
            GoodReduction,
            _certified_source_value(source, GoodReduction, "semistable source"),
        )
        normalized_prime = good.prime
        if prime is not None and _operation_prime(prime) != normalized_prime:
            raise PAdicValidationError("explicit prime disagrees with certified good reduction")
        if witness is None:
            exact_witness = SemistableReductionWitness(good)
        else:
            if not isinstance(witness, SemistableReductionWitness):
                raise TypeError("witness must be a SemistableReductionWitness or None")
            witness.verify()
            if witness.good_reduction != good:
                raise PAdicValidationError("semistable witness is foreign to the source")
            exact_witness = witness
        cover = good.cover
    else:
        raise TypeError("semistable source must be ThreePointCover or Certified[GoodReduction]")
    value = SemistableReduction(cover, normalized_prime, exact_witness)
    return certified_result(value, "semistable-reduction")


def stable_reduction(
    source: ThreePointCover | Certified[SemistableReduction],
    prime: int | None = None,
    *,
    witness: StableReductionWitness | None = None,
) -> PAdicResult[StableReduction]:
    """Certify that the supported marked semistable model is already stable."""

    from .results import Certified, certified_result, unsupported_result

    if isinstance(source, ThreePointCover):
        source.verify()
        if prime is None:
            raise TypeError("prime is required when source is a ThreePointCover")
        normalized_prime = _operation_prime(prime)
        if normalized_prime != 5 or not _is_supported_beta_cover(source):
            return _unsupported_geometry("padic.stable_reduction", source, normalized_prime)
        if witness is None:
            try:
                good = GoodReduction(
                    source,
                    normalized_prime,
                    GoodReductionWitness(source, normalized_prime),
                )
            except _GoodReductionFailure as exc:
                return unsupported_result(
                    "padic.stable_reduction",
                    "non-good-stable-discovery-unsupported",
                    "Automatic semistable discovery and component contraction are outside 0.5; "
                    f"the displayed model failed because: {exc}",
                    requested={"cover_id": source.content_id, "prime": normalized_prime},
                    supported=("already-stable one-component tame good-reduction models",),
                    family="three-point",
                )
            semistable = SemistableReduction(
                source,
                normalized_prime,
                SemistableReductionWitness(good),
            )
            exact_witness = StableReductionWitness(semistable)
        else:
            if not isinstance(witness, StableReductionWitness):
                raise TypeError("witness must be a StableReductionWitness or None")
            witness.verify()
            if (
                witness.semistable_reduction.cover != source
                or witness.semistable_reduction.prime != normalized_prime
            ):
                raise PAdicValidationError("stable witness is foreign to the request")
            exact_witness = witness
            semistable = witness.semistable_reduction
        cover = source
    elif isinstance(source, Certified):
        semistable = cast(
            SemistableReduction,
            _certified_source_value(source, SemistableReduction, "stable source"),
        )
        normalized_prime = semistable.prime
        if prime is not None and _operation_prime(prime) != normalized_prime:
            raise PAdicValidationError(
                "explicit prime disagrees with certified semistable reduction"
            )
        if witness is None:
            exact_witness = StableReductionWitness(semistable)
        else:
            if not isinstance(witness, StableReductionWitness):
                raise TypeError("witness must be a StableReductionWitness or None")
            witness.verify()
            if witness.semistable_reduction != semistable:
                raise PAdicValidationError("stable witness is foreign to the source")
            exact_witness = witness
        cover = semistable.cover
    else:
        raise TypeError("stable source must be ThreePointCover or Certified[SemistableReduction]")
    value = StableReduction(cover, normalized_prime, semistable, exact_witness)
    return certified_result(value, "stable-reduction")


@padic_payload_verifier("good-reduction")
def _verify_good_reduction_payload(
    payload: Mapping[str, object],
    _evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    raw = _raw_mapping(payload, "good-reduction payload")
    _exact_fields(raw, {"result"}, "good-reduction payload")
    _decode_good_reduction(raw["result"], "good-reduction result", document=True)
    return PAdicPayloadReplay(
        checks=(
            "exact-normalized-three-point-cover",
            "degree-preserving-special-fiber",
            "tame-separated-marked-ramification",
        )
    )


@padic_payload_verifier("semistable-reduction")
def _verify_semistable_reduction_payload(
    payload: Mapping[str, object],
    _evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    raw = _raw_mapping(payload, "semistable-reduction payload")
    _exact_fields(raw, {"result"}, "semistable-reduction payload")
    _decode_semistable_reduction(raw["result"], "semistable-reduction result", document=True)
    return PAdicPayloadReplay(
        checks=(
            "good-reduction-witness-replay",
            "one-smooth-component-on-source-and-target",
            "complete-marking-and-node-incidence",
        )
    )


@padic_payload_verifier("stable-reduction")
def _verify_stable_reduction_payload(
    payload: Mapping[str, object],
    _evidence: tuple[VerificationCertificate, ...],
) -> PAdicPayloadReplay:
    raw = _raw_mapping(payload, "stable-reduction payload")
    _exact_fields(raw, {"result"}, "stable-reduction payload")
    _decode_stable_reduction(raw["result"], "stable-reduction result", document=True)
    return PAdicPayloadReplay(
        checks=(
            "semistable-model-replay",
            "strict-positive-marked-stability-indices",
            "no-unproved-component-contractions",
        )
    )


__all__ = [
    "MAX_REDUCTION_PRIME",
    "ComponentMapWitness",
    "GoodReduction",
    "GoodReductionWitness",
    "MarkedReductionComponent",
    "ReducedBranchFiber",
    "ReducedFiberFactor",
    "ReducedProjectivePoint",
    "SemistableReduction",
    "SemistableReductionWitness",
    "SpecialFiberMarking",
    "StableReduction",
    "StableReductionWitness",
    "good_reduction",
    "semistable_reduction",
    "stable_reduction",
]
