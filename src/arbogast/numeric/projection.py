"""Exact bounded projection-degree witnesses with explicit claim scope."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import TypeAlias

from arbogast.core import CanonicalJSON

from ._schema import NumericSemanticObject, strict_int
from .errors import NumericError, NumericVerificationError
from .models import ExactCover, ExactPolynomial, PolynomialSystem
from .outcomes import NumericUnknown, UnsupportedNumeric

PolynomialQ: TypeAlias = tuple[Fraction, ...]


def _trim(value: PolynomialQ) -> PolynomialQ:
    result = value
    while len(result) > 1 and result[-1] == 0:
        result = result[:-1]
    return result


def _multiply(left: PolynomialQ, right: PolynomialQ) -> PolynomialQ:
    result = [Fraction(0)] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            result[left_index + right_index] += left_value * right_value
    return _trim(tuple(result))


def _derivative(value: PolynomialQ) -> PolynomialQ:
    return _trim(tuple(index * coefficient for index, coefficient in enumerate(value))[1:])


def _divmod(left: PolynomialQ, right: PolynomialQ) -> tuple[PolynomialQ, PolynomialQ]:
    numerator = list(_trim(left))
    denominator = _trim(right)
    quotient = [Fraction(0)] * max(1, len(numerator) - len(denominator) + 1)
    while len(numerator) >= len(denominator) and any(numerator):
        offset = len(numerator) - len(denominator)
        coefficient = numerator[-1] / denominator[-1]
        quotient[offset] = coefficient
        for index, divisor in enumerate(denominator):
            numerator[offset + index] -= coefficient * divisor
        while len(numerator) > 1 and numerator[-1] == 0:
            numerator.pop()
    return (_trim(tuple(quotient)), _trim(tuple(numerator)))


def _gcd(left: PolynomialQ, right: PolynomialQ) -> PolynomialQ:
    a, b = _trim(left), _trim(right)
    while b != (Fraction(0),):
        _, remainder = _divmod(a, b)
        a, b = b, remainder
    if a == (Fraction(0),):
        return a
    return tuple(coefficient / a[-1] for coefficient in a)


def _univariate(polynomial: ExactPolynomial) -> PolynomialQ | None:
    if polynomial.nvariables != 1:
        return None
    coefficients = [Fraction(0)] * (polynomial.total_degree + 1)
    for exponent, coefficient in polynomial.terms:
        if not coefficient.imag.is_zero:
            return None
        coefficients[exponent[0]] += coefficient.real.fraction
    return _trim(tuple(coefficients))


@dataclass(frozen=True, slots=True, init=False)
class RegularFiberWitness(NumericSemanticObject):
    """A complete square-free factorization of one displayed univariate fiber."""

    system: PolynomialSystem
    factors: tuple[tuple[int, ...], ...]
    degree: int

    schema_version = "arbogast.numeric.regular-fiber-witness/v1"

    def __init__(self, system: PolynomialSystem, factors: Sequence[Sequence[int]]) -> None:
        if not isinstance(system, PolynomialSystem):
            raise TypeError("regular-fiber witness needs a PolynomialSystem")
        if system.nvariables != 1 or system.nequations != 1:
            raise NumericError("regular-fiber replay currently supports one univariate equation")
        polynomial = _univariate(system.polynomials[0])
        if polynomial is None or len(polynomial) < 2:
            raise NumericError("regular fiber must be a nonconstant real dyadic polynomial")
        normalized = tuple(
            tuple(strict_int(coefficient, "factor coefficient") for coefficient in factor)
            for factor in factors
        )
        if not normalized or any(len(factor) < 2 or factor[-1] == 0 for factor in normalized):
            raise NumericError("regular-fiber factors must be nonconstant polynomials")
        product: PolynomialQ = (Fraction(1),)
        for factor in normalized:
            product = _multiply(product, tuple(Fraction(coefficient) for coefficient in factor))
        quotient, remainder = _divmod(polynomial, product)
        if remainder != (Fraction(0),) or len(quotient) != 1 or quotient[0] == 0:
            raise NumericError("regular-fiber factorization is not complete up to a scalar")
        if _gcd(polynomial, _derivative(polynomial)) != (Fraction(1),):
            raise NumericError("displayed fiber is not regular (the polynomial is not square-free)")
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "factors", normalized)
        object.__setattr__(self, "degree", len(polynomial) - 1)

    def verify(self) -> bool:
        self.system.verify()
        if type(self.degree) is not int:
            raise NumericVerificationError("regular-fiber witness degree is not an integer")
        if RegularFiberWitness(self.system, self.factors) != self:
            raise NumericVerificationError("regular-fiber witness was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "degree": self.degree,
            "factors": [list(factor) for factor in self.factors],
            "system": self.system.to_canonical_data(),
            "type": "arbogast.numeric.regular_fiber_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class GenericDegreeWitness(NumericSemanticObject):
    """The nonzero leading term of a finite polynomial map A1 -> A1."""

    polynomial: ExactPolynomial
    degree: int

    schema_version = "arbogast.numeric.generic-degree-witness/v1"

    def __init__(self, polynomial: ExactPolynomial) -> None:
        if not isinstance(polynomial, ExactPolynomial):
            raise TypeError("generic-degree witness needs an ExactPolynomial")
        rational = _univariate(polynomial)
        if rational is None or len(rational) < 2 or rational[-1] == 0:
            raise NumericError("generic polynomial-map witness must be nonconstant and univariate")
        object.__setattr__(self, "polynomial", polynomial)
        object.__setattr__(self, "degree", len(rational) - 1)

    def verify(self) -> bool:
        self.polynomial.verify()
        if type(self.degree) is not int:
            raise NumericVerificationError("generic-degree witness degree is not an integer")
        if GenericDegreeWitness(self.polynomial) != self:
            raise NumericVerificationError("generic-degree witness was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "degree": self.degree,
            "polynomial": self.polynomial.to_canonical_data(),
            "type": "arbogast.numeric.generic_degree_witness",
        }


@dataclass(frozen=True, slots=True, init=False)
class RegularFiberDegree(NumericSemanticObject):
    """A certified degree of one regular fiber, explicitly not a generic claim."""

    witness: RegularFiberWitness
    degree: int
    generic: bool = False

    schema_version = "arbogast.numeric.regular-fiber-degree/v1"

    def __init__(self, witness: RegularFiberWitness) -> None:
        if not isinstance(witness, RegularFiberWitness):
            raise TypeError("regular-fiber result needs a RegularFiberWitness")
        witness.verify()
        object.__setattr__(self, "witness", witness)
        object.__setattr__(self, "degree", witness.degree)
        object.__setattr__(self, "generic", False)

    def verify(self) -> bool:
        self.witness.verify()
        if type(self.degree) is not int or type(self.generic) is not bool:
            raise NumericVerificationError("regular-fiber result scope has noncanonical types")
        if self.degree != self.witness.degree or self.generic:
            raise NumericVerificationError("regular-fiber result scope was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "degree": self.degree,
            "generic": False,
            "type": "arbogast.numeric.regular_fiber_degree",
            "witness": self.witness.to_canonical_data(),
        }


@dataclass(frozen=True, slots=True, init=False)
class DegreeResult(NumericSemanticObject):
    """A certified generic degree for the supported polynomial-map presentation."""

    witness: GenericDegreeWitness
    degree: int
    generic: bool = True

    schema_version = "arbogast.numeric.degree-result/v1"

    def __init__(self, witness: GenericDegreeWitness) -> None:
        if not isinstance(witness, GenericDegreeWitness):
            raise TypeError("generic degree result needs a GenericDegreeWitness")
        witness.verify()
        object.__setattr__(self, "witness", witness)
        object.__setattr__(self, "degree", witness.degree)
        object.__setattr__(self, "generic", True)

    def verify(self) -> bool:
        self.witness.verify()
        if type(self.degree) is not int or type(self.generic) is not bool:
            raise NumericVerificationError("generic degree result scope has noncanonical types")
        if self.degree != self.witness.degree or not self.generic:
            raise NumericVerificationError("generic degree result scope was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "degree": self.degree,
            "generic": True,
            "type": "arbogast.numeric.degree_result",
            "witness": self.witness.to_canonical_data(),
        }


ProjectionDegreeOutcome: TypeAlias = (
    DegreeResult | RegularFiberDegree | NumericUnknown | UnsupportedNumeric
)


def projection_degree(
    H: ExactPolynomial | PolynomialSystem | ExactCover,
    functions: Sequence[ExactPolynomial | int],
    *,
    regular_fiber_witness: RegularFiberWitness | None = None,
    generic_witness: GenericDegreeWitness | None = None,
) -> ProjectionDegreeOutcome:
    """Certify generic degree only from a generic witness; keep regular fibers scoped."""

    if not isinstance(H, (ExactPolynomial, PolynomialSystem, ExactCover)):
        raise TypeError("projection model must be an exact polynomial, system, or cover")
    projections = tuple(functions)
    if generic_witness is not None and regular_fiber_witness is not None:
        raise NumericError(
            "generic and regular-fiber witnesses have different claim scopes and cannot be "
            "supplied together"
        )
    if generic_witness is not None:
        generic_witness.verify()
        if not isinstance(H, ExactPolynomial) or generic_witness.polynomial != H:
            return UnsupportedNumeric(
                "projection_degree",
                "generic witnesses beyond one exact univariate polynomial need a fully bound "
                "model-and-functions certificate",
                requested={"model_id": H.content_id},
            )
        if projections not in {(), (H,)}:
            raise NumericError("generic polynomial witness does not bind the declared functions")
        return DegreeResult(generic_witness)
    if isinstance(H, ExactPolynomial) and (not projections or projections == (H,)):
        try:
            return DegreeResult(GenericDegreeWitness(H))
        except NumericError as exc:
            return UnsupportedNumeric(
                "projection_degree",
                str(exc),
                requested={"model_id": H.content_id},
            )
    if regular_fiber_witness is not None:
        regular_fiber_witness.verify()
        if not isinstance(H, PolynomialSystem) or regular_fiber_witness.system != H:
            return UnsupportedNumeric(
                "projection_degree",
                "regular-fiber replay requires that H be the exact witnessed system",
                requested={"model_id": H.content_id},
            )
        if projections:
            return UnsupportedNumeric(
                "projection_degree",
                "regular-fiber witnesses do not certify arbitrary projection functions",
                requested={"function_count": len(projections), "model_id": H.content_id},
            )
        return RegularFiberDegree(regular_fiber_witness)
    if isinstance(H, ExactCover) or projections:
        return UnsupportedNumeric(
            "projection_degree",
            "the bounded slice has no fully bound generic witness for this model/functions pair",
            requested={"function_count": len(projections), "model_id": H.content_id},
        )
    return NumericUnknown(
        "projection_degree",
        "no generic-degree or complete regular-fiber witness was supplied",
        requested={
            "function_count": len(projections),
            "model_id": H.content_id,
        },
    )


__all__ = [
    "DegreeResult",
    "GenericDegreeWitness",
    "ProjectionDegreeOutcome",
    "RegularFiberDegree",
    "RegularFiberWitness",
    "projection_degree",
]
