"""Prime finite fields with immutable exact elements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from arbogast.core import CanonicalJSON, CanonicalObject, ValidationError

from .errors import FieldMismatchError


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _is_prime(value: int) -> bool:
    """Return primality by an exact deterministic trial-division test."""

    if value < 2:
        return False
    if value in (2, 3):
        return True
    if value % 2 == 0 or value % 3 == 0:
        return False
    divisor = 5
    step = 2
    while divisor * divisor <= value:
        if value % divisor == 0:
            return False
        divisor += step
        step = 6 - step
    return True


@dataclass(frozen=True, slots=True)
class PrimeField(CanonicalObject):
    """The prime field :math:`GF(p)` for a proven prime integer ``p``.

    Construction performs a deterministic primality check.  Extension fields
    are intentionally not masqueraded as prime fields in the 0.1 exact core.
    """

    p: int

    def __post_init__(self) -> None:
        _require_int(self.p, "p")
        if not _is_prime(self.p):
            raise ValidationError(f"modulus {self.p} is not prime")

    @property
    def characteristic(self) -> int:
        """Return the field characteristic."""

        return self.p

    @property
    def order(self) -> int:
        """Return the number of field elements."""

        return self.p

    @property
    def zero(self) -> PrimeFieldElement:
        """Return the additive identity."""

        return PrimeFieldElement(self, 0)

    @property
    def one(self) -> PrimeFieldElement:
        """Return the multiplicative identity."""

        return PrimeFieldElement(self, 1)

    def element(self, value: int | PrimeFieldElement) -> PrimeFieldElement:
        """Coerce an integer or same-field element into this field."""

        if isinstance(value, PrimeFieldElement):
            if value.field != self:
                raise FieldMismatchError(f"cannot coerce {value.field!r} element into {self!r}")
            return value
        return PrimeFieldElement(self, _require_int(value, "value"))

    def residue(self, value: int | PrimeFieldElement) -> int:
        """Return the canonical integer residue in ``range(p)``."""

        return self.element(value).value

    def __call__(self, value: int | PrimeFieldElement) -> PrimeFieldElement:
        """Alias for :meth:`element`."""

        return self.element(value)

    def to_canonical_data(self) -> CanonicalJSON:
        """Return the standardized prime-field presentation."""

        return {"characteristic": self.p, "type": "arbogast.prime_field"}

    def __repr__(self) -> str:
        return f"GF({self.p})"


@dataclass(frozen=True, slots=True)
class PrimeFieldElement(CanonicalObject):
    """An element of a :class:`PrimeField` in canonical residue form."""

    field: PrimeField
    value: int

    def __post_init__(self) -> None:
        residue = _require_int(self.value, "value") % self.field.p
        object.__setattr__(self, "value", residue)

    def _coerce(self, other: int | PrimeFieldElement) -> int:
        return self.field.residue(other)

    def __add__(self, other: int | PrimeFieldElement) -> PrimeFieldElement:
        return PrimeFieldElement(self.field, self.value + self._coerce(other))

    def __radd__(self, other: int | PrimeFieldElement) -> PrimeFieldElement:
        return self + other

    def __sub__(self, other: int | PrimeFieldElement) -> PrimeFieldElement:
        return PrimeFieldElement(self.field, self.value - self._coerce(other))

    def __rsub__(self, other: int | PrimeFieldElement) -> PrimeFieldElement:
        return PrimeFieldElement(self.field, self._coerce(other) - self.value)

    def __neg__(self) -> PrimeFieldElement:
        return PrimeFieldElement(self.field, -self.value)

    def __mul__(self, other: int | PrimeFieldElement) -> PrimeFieldElement:
        return PrimeFieldElement(self.field, self.value * self._coerce(other))

    def __rmul__(self, other: int | PrimeFieldElement) -> PrimeFieldElement:
        return self * other

    def inverse(self) -> PrimeFieldElement:
        """Return the multiplicative inverse, raising for zero."""

        if self.value == 0:
            raise ZeroDivisionError("zero has no multiplicative inverse")
        return PrimeFieldElement(self.field, pow(self.value, -1, self.field.p))

    def __truediv__(self, other: int | PrimeFieldElement) -> PrimeFieldElement:
        return self * PrimeFieldElement(self.field, self._coerce(other)).inverse()

    def __rtruediv__(self, other: int | PrimeFieldElement) -> PrimeFieldElement:
        return PrimeFieldElement(self.field, self._coerce(other)) * self.inverse()

    def __pow__(self, exponent: int) -> PrimeFieldElement:
        exponent = _require_int(exponent, "exponent")
        if exponent < 0:
            return self.inverse() ** (-exponent)
        return PrimeFieldElement(self.field, pow(self.value, exponent, self.field.p))

    def __int__(self) -> int:
        return self.value

    def __bool__(self) -> bool:
        return self.value != 0

    def to_canonical_data(self) -> CanonicalJSON:
        """Return a field-bound canonical element encoding."""

        return {
            "field": self.field.to_canonical_data(),
            "type": "arbogast.prime_field_element",
            "value": self.value,
        }

    def __repr__(self) -> str:
        return f"{self.value} (mod {self.field.p})"


FiniteField = PrimeField
FieldElement = PrimeFieldElement
Scalar: TypeAlias = int | PrimeFieldElement
