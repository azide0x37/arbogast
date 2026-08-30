"""Canonical exact polynomial, family, path, point, and cover presentations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from typing import TypeAlias

from arbogast.core import CanonicalJSON

from ._schema import (
    MAX_DIMENSION,
    MAX_PATH_VERTICES,
    MAX_POLYNOMIALS,
    MAX_TERMS,
    MAX_TOTAL_DEGREE,
    NumericSemanticObject,
    canonical_label,
    strict_int,
)
from .dyadic import ComplexBall, ComplexDyadic, Dyadic
from .errors import NumericError, NumericVerificationError

Exponent: TypeAlias = tuple[int, ...]
Coefficient: TypeAlias = ComplexDyadic | Dyadic | int | Fraction


def _power(value: ComplexDyadic, exponent: int) -> ComplexDyadic:
    result = ComplexDyadic(1)
    base = value
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = result * base
        base = base * base
        remaining >>= 1
    return result


def _ball_power(value: ComplexBall, exponent: int) -> ComplexBall:
    result = ComplexBall.point(1)
    base = value
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = result * base
        base = base * base
        remaining >>= 1
    return result


@dataclass(frozen=True, slots=True, init=False)
class ExactPolynomial(NumericSemanticObject):
    """A sparse multivariate polynomial with exact complex-dyadic coefficients."""

    nvariables: int
    terms: tuple[tuple[Exponent, ComplexDyadic], ...]
    variable_names: tuple[str, ...]

    schema_version = "arbogast.numeric.exact-polynomial/v1"

    def __init__(
        self,
        nvariables: int,
        terms: Mapping[Sequence[int], Coefficient] | Iterable[tuple[Sequence[int], Coefficient]],
        *,
        variable_names: Sequence[str] | None = None,
    ) -> None:
        dimension = strict_int(nvariables, "number of polynomial variables", minimum=1)
        if dimension > MAX_DIMENSION:
            raise NumericError("polynomial variable count exceeds the portable bound")
        names = (
            tuple(f"x{index}" for index in range(dimension))
            if variable_names is None
            else tuple(
                canonical_label(name, "polynomial variable name") or "" for name in variable_names
            )
        )
        if len(names) != dimension or len(set(names)) != dimension:
            raise NumericError("polynomial variable names have the wrong length or duplicates")
        source = terms.items() if isinstance(terms, Mapping) else terms
        combined: dict[Exponent, ComplexDyadic] = {}
        for count, (raw_exponent, raw_coefficient) in enumerate(source, start=1):
            if count > MAX_TERMS:
                raise NumericError("polynomial term count exceeds the portable bound")
            exponent = tuple(
                strict_int(value, "polynomial exponent", minimum=0) for value in raw_exponent
            )
            if len(exponent) != dimension:
                raise NumericError("polynomial exponent has the wrong dimension")
            if sum(exponent) > MAX_TOTAL_DEGREE:
                raise NumericError("polynomial total degree exceeds the portable bound")
            coefficient = ComplexDyadic.coerce(raw_coefficient)
            combined[exponent] = combined.get(exponent, ComplexDyadic(0)) + coefficient
        normalized = tuple(
            (exponent, coefficient)
            for exponent, coefficient in sorted(combined.items())
            if not coefficient.real.is_zero or not coefficient.imag.is_zero
        )
        object.__setattr__(self, "nvariables", dimension)
        object.__setattr__(self, "terms", normalized)
        object.__setattr__(self, "variable_names", names)

    @property
    def total_degree(self) -> int:
        return max((sum(exponent) for exponent, _ in self.terms), default=0)

    def evaluate(self, point: Sequence[ComplexDyadic | Dyadic | int | Fraction]) -> ComplexDyadic:
        coordinates = tuple(ComplexDyadic.coerce(value) for value in point)
        if len(coordinates) != self.nvariables:
            raise NumericError("polynomial point has the wrong dimension")
        result = ComplexDyadic(0)
        for exponent, coefficient in self.terms:
            term = coefficient
            for value, power in zip(coordinates, exponent, strict=True):
                term = term * _power(value, power)
            result = result + term
        return result

    def evaluate_ball(self, point: Sequence[ComplexBall]) -> ComplexBall:
        coordinates = tuple(point)
        if len(coordinates) != self.nvariables or any(
            not isinstance(value, ComplexBall) for value in coordinates
        ):
            raise NumericError("polynomial ball point has the wrong dimension or type")
        result = ComplexBall.point(0)
        for exponent, coefficient in self.terms:
            term = ComplexBall.point(coefficient)
            for value, power in zip(coordinates, exponent, strict=True):
                term = term * _ball_power(value, power)
            result = result + term
        return result

    def derivative(self, variable: int) -> ExactPolynomial:
        index = strict_int(variable, "derivative variable", minimum=0)
        if index >= self.nvariables:
            raise NumericError("derivative variable is out of range")
        terms: list[tuple[Exponent, ComplexDyadic]] = []
        for exponent, coefficient in self.terms:
            power = exponent[index]
            if power == 0:
                continue
            reduced = list(exponent)
            reduced[index] -= 1
            terms.append((tuple(reduced), coefficient * power))
        return ExactPolynomial(self.nvariables, terms, variable_names=self.variable_names)

    def substitute_last(self, value: ComplexDyadic | Dyadic | int | Fraction) -> ExactPolynomial:
        if self.nvariables == 1:
            raise NumericError("cannot remove the only polynomial variable")
        parameter = ComplexDyadic.coerce(value)
        terms: list[tuple[Exponent, ComplexDyadic]] = []
        for exponent, coefficient in self.terms:
            terms.append((exponent[:-1], coefficient * _power(parameter, exponent[-1])))
        return ExactPolynomial(
            self.nvariables - 1,
            terms,
            variable_names=self.variable_names[:-1],
        )

    def verify(self) -> bool:
        for _, coefficient in self.terms:
            coefficient.verify()
        replay = ExactPolynomial(
            self.nvariables,
            self.terms,
            variable_names=self.variable_names,
        )
        if replay != self:
            raise NumericVerificationError("polynomial canonical presentation was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "nvariables": self.nvariables,
            "terms": [
                {"coefficient": coefficient.to_canonical_data(), "exponents": list(exponent)}
                for exponent, coefficient in self.terms
            ],
            "type": "arbogast.numeric.exact_polynomial",
            "variable_names": list(self.variable_names),
        }


@dataclass(frozen=True, slots=True, init=False)
class PolynomialSystem(NumericSemanticObject):
    """An ordered exact square or rectangular polynomial system."""

    nvariables: int
    polynomials: tuple[ExactPolynomial, ...]
    label: str | None

    schema_version = "arbogast.numeric.polynomial-system/v1"

    def __init__(
        self,
        nvariables: int,
        polynomials: Sequence[ExactPolynomial],
        *,
        label: str | None = None,
    ) -> None:
        dimension = strict_int(nvariables, "system variable count", minimum=1)
        equations = tuple(polynomials)
        if dimension > MAX_DIMENSION or not equations or len(equations) > MAX_POLYNOMIALS:
            raise NumericError("polynomial system dimensions exceed the bounded slice")
        if any(
            not isinstance(polynomial, ExactPolynomial) or polynomial.nvariables != dimension
            for polynomial in equations
        ):
            raise NumericError("system polynomials use incompatible variable dimensions")
        object.__setattr__(self, "nvariables", dimension)
        object.__setattr__(self, "polynomials", equations)
        object.__setattr__(self, "label", canonical_label(label, "system label", optional=True))

    @property
    def nequations(self) -> int:
        return len(self.polynomials)

    def evaluate(
        self, point: Sequence[ComplexDyadic | Dyadic | int | Fraction]
    ) -> tuple[ComplexDyadic, ...]:
        return tuple(polynomial.evaluate(point) for polynomial in self.polynomials)

    def evaluate_ball(self, point: Sequence[ComplexBall]) -> tuple[ComplexBall, ...]:
        return tuple(polynomial.evaluate_ball(point) for polynomial in self.polynomials)

    def jacobian(self) -> tuple[tuple[ExactPolynomial, ...], ...]:
        return tuple(
            tuple(polynomial.derivative(index) for index in range(self.nvariables))
            for polynomial in self.polynomials
        )

    def verify(self) -> bool:
        if any(not polynomial.verify() for polynomial in self.polynomials):
            raise NumericVerificationError("system polynomial failed replay")
        if PolynomialSystem(self.nvariables, self.polynomials, label=self.label) != self:
            raise NumericVerificationError("polynomial-system presentation was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "label": self.label,
            "nvariables": self.nvariables,
            "polynomials": [polynomial.to_canonical_data() for polynomial in self.polynomials],
            "type": "arbogast.numeric.polynomial_system",
        }


@dataclass(frozen=True, slots=True, init=False)
class PolynomialFamily(NumericSemanticObject):
    """A polynomial system in solution variables followed by one parameter."""

    nvariables: int
    polynomials: tuple[ExactPolynomial, ...]
    parameter_name: str

    schema_version = "arbogast.numeric.polynomial-family/v1"

    def __init__(
        self,
        nvariables: int,
        polynomials: Sequence[ExactPolynomial],
        *,
        parameter_name: str = "t",
    ) -> None:
        dimension = strict_int(nvariables, "family solution-variable count", minimum=1)
        equations = tuple(polynomials)
        if not equations or len(equations) > MAX_POLYNOMIALS:
            raise NumericError("polynomial family has an unsupported equation count")
        if any(
            not isinstance(polynomial, ExactPolynomial) or polynomial.nvariables != dimension + 1
            for polynomial in equations
        ):
            raise NumericError("family polynomials must have solution variables plus one parameter")
        normalized_name = canonical_label(parameter_name, "parameter name")
        assert normalized_name is not None
        object.__setattr__(self, "nvariables", dimension)
        object.__setattr__(self, "polynomials", equations)
        object.__setattr__(self, "parameter_name", normalized_name)

    def fiber(self, parameter: ComplexDyadic | Dyadic | int | Fraction) -> PolynomialSystem:
        return PolynomialSystem(
            self.nvariables,
            tuple(polynomial.substitute_last(parameter) for polynomial in self.polynomials),
            label=f"fiber at {ComplexDyadic.coerce(parameter).content_id}",
        )

    def verify(self) -> bool:
        if any(not polynomial.verify() for polynomial in self.polynomials):
            raise NumericVerificationError("family polynomial failed replay")
        if (
            PolynomialFamily(
                self.nvariables,
                self.polynomials,
                parameter_name=self.parameter_name,
            )
            != self
        ):
            raise NumericVerificationError("polynomial-family presentation was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "nvariables": self.nvariables,
            "parameter_name": self.parameter_name,
            "polynomials": [polynomial.to_canonical_data() for polynomial in self.polynomials],
            "type": "arbogast.numeric.polynomial_family",
        }


@dataclass(frozen=True, slots=True, init=False)
class ParameterPath(NumericSemanticObject):
    """An exact piecewise-linear path through complex-dyadic vertices."""

    vertices: tuple[ComplexDyadic, ...]

    schema_version = "arbogast.numeric.parameter-path/v1"

    def __init__(self, vertices: Sequence[ComplexDyadic | Dyadic | int | Fraction]) -> None:
        normalized = tuple(ComplexDyadic.coerce(vertex) for vertex in vertices)
        if not 2 <= len(normalized) <= MAX_PATH_VERTICES:
            raise NumericError("parameter path must have between 2 and the bounded vertex count")
        if any(left == right for left, right in pairwise(normalized)):
            raise NumericError("parameter path contains a stationary segment")
        object.__setattr__(self, "vertices", normalized)

    @property
    def start(self) -> ComplexDyadic:
        return self.vertices[0]

    @property
    def end(self) -> ComplexDyadic:
        return self.vertices[-1]

    @property
    def segment_count(self) -> int:
        return len(self.vertices) - 1

    def reversed(self) -> ParameterPath:
        return ParameterPath(tuple(reversed(self.vertices)))

    def verify(self) -> bool:
        if any(not vertex.verify() for vertex in self.vertices):
            raise NumericVerificationError("parameter-path vertex failed replay")
        if ParameterPath(self.vertices) != self:
            raise NumericVerificationError("parameter-path presentation was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "type": "arbogast.numeric.parameter_path",
            "vertices": [vertex.to_canonical_data() for vertex in self.vertices],
        }


@dataclass(frozen=True, slots=True, init=False)
class NumericPoint(NumericSemanticObject):
    """A tuple of certified complex enclosures bound to one exact system."""

    system: PolynomialSystem
    coordinates: tuple[ComplexBall, ...]

    schema_version = "arbogast.numeric.point/v1"

    def __init__(self, system: PolynomialSystem, coordinates: Sequence[ComplexBall]) -> None:
        if not isinstance(system, PolynomialSystem):
            raise TypeError("numeric point system must be a PolynomialSystem")
        normalized = tuple(coordinates)
        if len(normalized) != system.nvariables or any(
            not isinstance(coordinate, ComplexBall) for coordinate in normalized
        ):
            raise NumericError("numeric point coordinates have the wrong dimension or type")
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "coordinates", normalized)

    def residuals(self) -> tuple[ComplexBall, ...]:
        return self.system.evaluate_ball(self.coordinates)

    def verify(self) -> bool:
        self.system.verify()
        if any(not coordinate.verify() for coordinate in self.coordinates):
            raise NumericVerificationError("numeric point coordinate failed replay")
        if NumericPoint(self.system, self.coordinates) != self:
            raise NumericVerificationError("numeric point presentation was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "coordinates": [coordinate.to_canonical_data() for coordinate in self.coordinates],
            "system": self.system.to_canonical_data(),
            "type": "arbogast.numeric.point",
        }


def _polynomial_coefficients_in_parameter(
    polynomial: ExactPolynomial,
) -> tuple[dict[int, ComplexDyadic], dict[int, ComplexDyadic], dict[int, ComplexDyadic]]:
    """Return the x^0, x^1, x^2 coefficient polynomials of F(x,t)."""

    coefficients: tuple[
        dict[int, ComplexDyadic],
        dict[int, ComplexDyadic],
        dict[int, ComplexDyadic],
    ] = ({}, {}, {})
    for exponent, coefficient in polynomial.terms:
        x_power, parameter_power = exponent
        if x_power > 2:
            raise NumericError("bounded exact covers currently require a quadratic in x")
        bucket = coefficients[x_power]
        bucket[parameter_power] = bucket.get(parameter_power, ComplexDyadic(0)) + coefficient
    return coefficients


def _parameter_polynomial_add(
    left: Mapping[int, ComplexDyadic],
    right: Mapping[int, ComplexDyadic],
) -> dict[int, ComplexDyadic]:
    result = dict(left)
    for exponent, coefficient in right.items():
        result[exponent] = result.get(exponent, ComplexDyadic(0)) + coefficient
    return {
        exponent: coefficient
        for exponent, coefficient in result.items()
        if not coefficient.real.is_zero or not coefficient.imag.is_zero
    }


def _parameter_polynomial_multiply(
    left: Mapping[int, ComplexDyadic],
    right: Mapping[int, ComplexDyadic],
) -> dict[int, ComplexDyadic]:
    result: dict[int, ComplexDyadic] = {}
    for left_exponent, left_coefficient in left.items():
        for right_exponent, right_coefficient in right.items():
            exponent = left_exponent + right_exponent
            result[exponent] = result.get(exponent, ComplexDyadic(0)) + (
                left_coefficient * right_coefficient
            )
    return {
        exponent: coefficient
        for exponent, coefficient in result.items()
        if not coefficient.real.is_zero or not coefficient.imag.is_zero
    }


def _quadratic_discriminant(polynomial: ExactPolynomial) -> dict[int, ComplexDyadic]:
    if polynomial.nvariables != 2:
        raise NumericError("bounded exact covers require one solution variable and one parameter")
    constant, linear, quadratic = _polynomial_coefficients_in_parameter(polynomial)
    if quadratic != {0: ComplexDyadic(1)}:
        raise NumericError("bounded exact covers require a monic quadratic in the sheet variable")
    return _parameter_polynomial_add(
        _parameter_polynomial_multiply(linear, linear),
        {exponent: coefficient * -4 for exponent, coefficient in constant.items()},
    )


def _branch_factorization(
    discriminant: Mapping[int, ComplexDyadic],
    branch_points: tuple[ComplexDyadic, ...],
) -> bool:
    if not discriminant:
        return False
    degree = max(discriminant)
    if degree != len(branch_points):
        return False
    product: dict[int, ComplexDyadic] = {0: ComplexDyadic(1)}
    for point in branch_points:
        product = _parameter_polynomial_multiply(
            product,
            {0: -point, 1: ComplexDyadic(1)},
        )
    leading = discriminant[degree]
    expected = {exponent: coefficient * leading for exponent, coefficient in product.items()}
    return expected == discriminant


@dataclass(frozen=True, slots=True, init=False)
class ExactCover(NumericSemanticObject):
    """A monic quadratic cover with a completely replayed branch divisor."""

    family: PolynomialFamily
    degree: int
    branch_points: tuple[ComplexDyadic, ...]
    discriminant: ExactPolynomial
    infinity_branch: bool
    label: str | None

    schema_version = "arbogast.numeric.exact-cover/v1"

    def __init__(
        self,
        family: PolynomialFamily,
        degree: int,
        branch_points: Sequence[ComplexDyadic | Dyadic | int | Fraction],
        *,
        include_infinity: bool | None = None,
        label: str | None = None,
    ) -> None:
        if not isinstance(family, PolynomialFamily):
            raise TypeError("exact cover family must be a PolynomialFamily")
        normalized_degree = strict_int(degree, "cover degree", minimum=1)
        if normalized_degree != 2:
            raise NumericError("bounded certified covers currently support degree two only")
        if family.nvariables != 1 or len(family.polynomials) != 1:
            raise NumericError("bounded certified covers require one quadratic equation in x,t")
        points = tuple(ComplexDyadic.coerce(point) for point in branch_points)
        if not points or len(points) > MAX_DIMENSION or len(set(points)) != len(points):
            raise NumericError("branch divisor must be nonempty, bounded, and pairwise distinct")
        discriminant_coefficients = _quadratic_discriminant(family.polynomials[0])
        if not _branch_factorization(discriminant_coefficients, points):
            raise NumericError(
                "declared finite branch points do not exhaust the exact quadratic discriminant"
            )
        discriminant_degree = max(discriminant_coefficients)
        expected_infinity = bool(discriminant_degree % 2)
        if include_infinity is not None and not isinstance(include_infinity, bool):
            raise TypeError("include_infinity must be a boolean or null")
        if include_infinity is not None and include_infinity != expected_infinity:
            raise NumericError(
                "infinity ramification must equal the parity of the quadratic discriminant degree"
            )
        discriminant = ExactPolynomial(
            1,
            [
                ((exponent,), coefficient)
                for exponent, coefficient in discriminant_coefficients.items()
            ],
            variable_names=(family.parameter_name,),
        )
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "degree", normalized_degree)
        object.__setattr__(self, "branch_points", points)
        object.__setattr__(self, "discriminant", discriminant)
        object.__setattr__(self, "infinity_branch", expected_infinity)
        object.__setattr__(self, "label", canonical_label(label, "cover label", optional=True))

    @property
    def branch_count(self) -> int:
        return len(self.branch_points) + int(self.infinity_branch)

    def verify(self) -> bool:
        self.family.verify()
        if any(not point.verify() for point in self.branch_points):
            raise NumericVerificationError("exact-cover branch point failed replay")
        self.discriminant.verify()
        if (
            ExactCover(
                self.family,
                self.degree,
                self.branch_points,
                include_infinity=self.infinity_branch,
                label=self.label,
            )
            != self
        ):
            raise NumericVerificationError("exact-cover presentation was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "branch_points": [point.to_canonical_data() for point in self.branch_points],
            "degree": self.degree,
            "discriminant": self.discriminant.to_canonical_data(),
            "family": self.family.to_canonical_data(),
            "infinity_branch": self.infinity_branch,
            "infinity_convention": (
                "finite counterclockwise loops in declared order, followed by the "
                "positive loop at infinity; branch-cycle product is identity"
            ),
            "label": self.label,
            "type": "arbogast.numeric.exact_cover",
        }


Path = ParameterPath
Point = NumericPoint

__all__ = [
    "ExactCover",
    "ExactPolynomial",
    "NumericPoint",
    "ParameterPath",
    "Path",
    "Point",
    "PolynomialFamily",
    "PolynomialSystem",
]
