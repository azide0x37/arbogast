"""Canonical exact dyadics and closed real/complex balls.

The proof boundary contains no binary or decimal floating-point values.  A
dyadic is stored uniquely as ``mantissa * 2**exponent`` with odd nonzero
mantissa.  Balls are closed and use exact dyadic radii.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import overload

from arbogast.core import CanonicalJSON

from ._schema import MAX_DYADIC_BITS, MAX_DYADIC_EXPONENT, NumericSemanticObject, strict_int
from .errors import NumericError, NumericVerificationError


def _normalize(mantissa: int, exponent: int) -> tuple[int, int]:
    strict_int(mantissa, "dyadic mantissa")
    strict_int(exponent, "dyadic exponent")
    if abs(exponent) > MAX_DYADIC_EXPONENT:
        raise NumericError("raw dyadic exponent exceeds the portable bound")
    if mantissa.bit_length() > MAX_DYADIC_BITS + MAX_DYADIC_EXPONENT:
        raise NumericError("raw dyadic mantissa exceeds the portable work bound")
    if mantissa == 0:
        return (0, 0)
    absolute = abs(mantissa)
    shift = (absolute & -absolute).bit_length() - 1
    mantissa >>= shift
    exponent += shift
    if mantissa.bit_length() > MAX_DYADIC_BITS:
        raise NumericError("dyadic mantissa exceeds the portable bit bound")
    if abs(exponent) > MAX_DYADIC_EXPONENT:
        raise NumericError("dyadic exponent exceeds the portable bound")
    return (mantissa, exponent)


@dataclass(frozen=True, slots=True, init=False)
class Dyadic(NumericSemanticObject):
    """One canonical rational with power-of-two denominator."""

    mantissa: int
    exponent: int

    schema_version = "arbogast.numeric.dyadic/v1"

    def __init__(self, mantissa: int, exponent: int = 0) -> None:
        normalized = _normalize(mantissa, exponent)
        object.__setattr__(self, "mantissa", normalized[0])
        object.__setattr__(self, "exponent", normalized[1])
        self.verify()

    @classmethod
    def zero(cls) -> Dyadic:
        return cls(0)

    @classmethod
    def one(cls) -> Dyadic:
        return cls(1)

    @classmethod
    def coerce(cls, value: Dyadic | int | Fraction) -> Dyadic:
        if isinstance(value, Dyadic):
            return value
        if isinstance(value, bool):
            raise TypeError("booleans are not dyadics")
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, Fraction):
            denominator = value.denominator
            if denominator & (denominator - 1):
                raise NumericError("rational is not dyadic")
            return cls(value.numerator, -(denominator.bit_length() - 1))
        raise TypeError("dyadic values must be Dyadic, int, or exact Fraction")

    @property
    def fraction(self) -> Fraction:
        if self.exponent >= 0:
            return Fraction(self.mantissa << self.exponent, 1)
        return Fraction(self.mantissa, 1 << -self.exponent)

    @property
    def is_zero(self) -> bool:
        return self.mantissa == 0

    def verify(self) -> bool:
        if _normalize(self.mantissa, self.exponent) != (self.mantissa, self.exponent):
            raise NumericVerificationError("dyadic representation is not canonical")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "exponent": self.exponent,
            "mantissa": self.mantissa,
            "type": "arbogast.numeric.dyadic",
        }

    def __neg__(self) -> Dyadic:
        return Dyadic(-self.mantissa, self.exponent)

    def __abs__(self) -> Dyadic:
        return Dyadic(abs(self.mantissa), self.exponent)

    @overload
    def __add__(self, other: Dyadic) -> Dyadic: ...

    @overload
    def __add__(self, other: int) -> Dyadic: ...

    def __add__(self, other: Dyadic | int) -> Dyadic:
        right = Dyadic.coerce(other)
        exponent = min(self.exponent, right.exponent)
        left_mantissa = self.mantissa << (self.exponent - exponent)
        right_mantissa = right.mantissa << (right.exponent - exponent)
        return Dyadic(left_mantissa + right_mantissa, exponent)

    def __radd__(self, other: int) -> Dyadic:
        return self + other

    def __sub__(self, other: Dyadic | int) -> Dyadic:
        return self + (-Dyadic.coerce(other))

    def __rsub__(self, other: int) -> Dyadic:
        return Dyadic.coerce(other) - self

    def __mul__(self, other: Dyadic | int) -> Dyadic:
        right = Dyadic.coerce(other)
        return Dyadic(self.mantissa * right.mantissa, self.exponent + right.exponent)

    def __rmul__(self, other: int) -> Dyadic:
        return self * other

    def __truediv__(self, other: Dyadic | int) -> Dyadic:
        right = Dyadic.coerce(other)
        if right.is_zero:
            raise ZeroDivisionError("dyadic division by zero")
        quotient = self.fraction / right.fraction
        return Dyadic.coerce(quotient)

    def __lt__(self, other: Dyadic | int) -> bool:
        return self.fraction < Dyadic.coerce(other).fraction

    def __le__(self, other: Dyadic | int) -> bool:
        return self.fraction <= Dyadic.coerce(other).fraction

    def __gt__(self, other: Dyadic | int) -> bool:
        return self.fraction > Dyadic.coerce(other).fraction

    def __ge__(self, other: Dyadic | int) -> bool:
        return self.fraction >= Dyadic.coerce(other).fraction


@dataclass(frozen=True, slots=True, init=False)
class ComplexDyadic(NumericSemanticObject):
    """One exact complex number with dyadic real and imaginary parts."""

    real: Dyadic
    imag: Dyadic

    schema_version = "arbogast.numeric.complex-dyadic/v1"

    def __init__(
        self,
        real: Dyadic | int | Fraction,
        imag: Dyadic | int | Fraction = 0,
    ) -> None:
        object.__setattr__(self, "real", Dyadic.coerce(real))
        object.__setattr__(self, "imag", Dyadic.coerce(imag))
        self.verify()

    @classmethod
    def coerce(cls, value: ComplexDyadic | Dyadic | int | Fraction) -> ComplexDyadic:
        if isinstance(value, ComplexDyadic):
            return value
        return cls(value)

    def verify(self) -> bool:
        if not self.real.verify() or not self.imag.verify():
            raise NumericVerificationError("complex dyadic coordinate failed replay")
        return True

    def conjugate(self) -> ComplexDyadic:
        return ComplexDyadic(self.real, -self.imag)

    def norm_squared(self) -> Dyadic:
        return self.real * self.real + self.imag * self.imag

    def l1_norm(self) -> Dyadic:
        return abs(self.real) + abs(self.imag)

    def __neg__(self) -> ComplexDyadic:
        return ComplexDyadic(-self.real, -self.imag)

    def __add__(self, other: ComplexDyadic | Dyadic | int) -> ComplexDyadic:
        right = ComplexDyadic.coerce(other)
        return ComplexDyadic(self.real + right.real, self.imag + right.imag)

    def __sub__(self, other: ComplexDyadic | Dyadic | int) -> ComplexDyadic:
        right = ComplexDyadic.coerce(other)
        return ComplexDyadic(self.real - right.real, self.imag - right.imag)

    def __mul__(self, other: ComplexDyadic | Dyadic | int) -> ComplexDyadic:
        right = ComplexDyadic.coerce(other)
        return ComplexDyadic(
            self.real * right.real - self.imag * right.imag,
            self.real * right.imag + self.imag * right.real,
        )

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "imag": self.imag.to_canonical_data(),
            "real": self.real.to_canonical_data(),
            "type": "arbogast.numeric.complex_dyadic",
        }


@dataclass(frozen=True, slots=True, init=False)
class RealBall(NumericSemanticObject):
    """A closed real interval encoded by an exact center and nonnegative radius."""

    center: Dyadic
    radius: Dyadic

    schema_version = "arbogast.numeric.real-ball/v1"

    def __init__(self, center: Dyadic | int | Fraction, radius: Dyadic | int | Fraction) -> None:
        normalized_radius = Dyadic.coerce(radius)
        if normalized_radius < 0:
            raise NumericError("real-ball radius must be nonnegative")
        object.__setattr__(self, "center", Dyadic.coerce(center))
        object.__setattr__(self, "radius", normalized_radius)
        self.verify()

    @property
    def lower(self) -> Dyadic:
        return self.center - self.radius

    @property
    def upper(self) -> Dyadic:
        return self.center + self.radius

    def contains(self, value: Dyadic | int | Fraction | RealBall) -> bool:
        if isinstance(value, RealBall):
            return self.lower <= value.lower and value.upper <= self.upper
        point = Dyadic.coerce(value)
        return self.lower <= point <= self.upper

    def overlaps(self, other: RealBall) -> bool:
        return self.lower <= other.upper and other.lower <= self.upper

    def __add__(self, other: RealBall) -> RealBall:
        return RealBall(self.center + other.center, self.radius + other.radius)

    def __mul__(self, other: RealBall) -> RealBall:
        radius = (
            abs(self.center) * other.radius
            + abs(other.center) * self.radius
            + self.radius * other.radius
        )
        return RealBall(self.center * other.center, radius)

    def verify(self) -> bool:
        self.center.verify()
        self.radius.verify()
        if self.radius < 0:
            raise NumericVerificationError("real-ball radius is negative")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "center": self.center.to_canonical_data(),
            "radius": self.radius.to_canonical_data(),
            "type": "arbogast.numeric.real_ball",
        }


@dataclass(frozen=True, slots=True, init=False)
class ComplexBall(NumericSemanticObject):
    """A closed complex disc with exact dyadic center and radius."""

    center: ComplexDyadic
    radius: Dyadic

    schema_version = "arbogast.numeric.complex-ball/v1"

    def __init__(
        self,
        center: ComplexDyadic | Dyadic | int | Fraction,
        radius: Dyadic | int | Fraction,
    ) -> None:
        normalized_radius = Dyadic.coerce(radius)
        if normalized_radius < 0:
            raise NumericError("complex-ball radius must be nonnegative")
        object.__setattr__(self, "center", ComplexDyadic.coerce(center))
        object.__setattr__(self, "radius", normalized_radius)
        self.verify()

    @classmethod
    def point(cls, value: ComplexDyadic | Dyadic | int | Fraction) -> ComplexBall:
        return cls(value, 0)

    def contains(self, value: ComplexDyadic | ComplexBall) -> bool:
        if isinstance(value, ComplexBall):
            delta = self.center - value.center
            bound = delta.l1_norm() + value.radius
        else:
            delta = self.center - value
            bound = delta.l1_norm()
        return bound <= self.radius

    def disjoint(self, other: ComplexBall) -> bool:
        delta = self.center - other.center
        # The l-infinity lower bound is safe for Euclidean separation.
        coordinate_lower = max(abs(delta.real).fraction, abs(delta.imag).fraction)
        return coordinate_lower > (self.radius + other.radius).fraction

    def __add__(self, other: ComplexBall) -> ComplexBall:
        return ComplexBall(self.center + other.center, self.radius + other.radius)

    def __mul__(self, other: ComplexBall) -> ComplexBall:
        radius = (
            self.center.l1_norm() * other.radius
            + other.center.l1_norm() * self.radius
            + self.radius * other.radius
        )
        return ComplexBall(self.center * other.center, radius)

    def verify(self) -> bool:
        self.center.verify()
        self.radius.verify()
        if self.radius < 0:
            raise NumericVerificationError("complex-ball radius is negative")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "center": self.center.to_canonical_data(),
            "radius": self.radius.to_canonical_data(),
            "type": "arbogast.numeric.complex_ball",
        }


__all__ = ["ComplexBall", "ComplexDyadic", "Dyadic", "RealBall"]
