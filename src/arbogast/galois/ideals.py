"""Canonical nonzero integral ideals in a pinned number-field presentation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import ClassVar, cast

from arbogast.core import CanonicalJSON, CanonicalObject, ValidationError
from arbogast.formats import IDEAL_SCHEMA, validate_document

from .fields import NumberField, NumberFieldElement, rational_vector_payload


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _solve_square(
    rows: Sequence[Sequence[Fraction]],
    target: Sequence[Fraction],
) -> tuple[Fraction, ...]:
    size = len(rows)
    if len(target) != size or any(len(row) != size for row in rows):
        raise ValidationError("ideal lattice solve requires a square matrix")
    work = [[*row, target[index]] for index, row in enumerate(rows)]
    for column in range(size):
        pivot = next((row for row in range(column, size) if work[row][column]), None)
        if pivot is None:
            raise ValidationError("ideal HNF must define a full-rank lattice")
        work[column], work[pivot] = work[pivot], work[column]
        pivot_value = work[column][column]
        work[column] = [value / pivot_value for value in work[column]]
        for row in range(size):
            if row == column:
                continue
            coefficient = work[row][column]
            if coefficient:
                work[row] = [
                    left - coefficient * right
                    for left, right in zip(work[row], work[column], strict=True)
                ]
    return tuple(work[index][-1] for index in range(size))


@dataclass(frozen=True, slots=True, init=False)
class Ideal(CanonicalObject):
    """A nonzero integral ideal in canonical column-HNF coordinates.

    Matrix columns generate the ideal relative to ``field.integral_basis``.
    The complete canonical identity binds the field content ID, the exact
    pinned integral basis, and the normalized HNF.  Construction replays both
    HNF normalization and closure under multiplication by the maximal order.
    """

    schema_version: ClassVar[str] = IDEAL_SCHEMA

    field: NumberField
    ideal_hnf: tuple[tuple[int, ...], ...]

    def __init__(
        self,
        field: NumberField,
        ideal_hnf: Iterable[Iterable[int]],
    ) -> None:
        if not isinstance(field, NumberField):
            raise TypeError("field must be a NumberField")
        rows = tuple(
            tuple(_integer(value, "ideal-HNF entry") for value in row) for row in ideal_hnf
        )
        degree = field.degree
        if len(rows) != degree or any(len(row) != degree for row in rows):
            raise ValidationError(f"ideal_hnf must be a {degree}-by-{degree} matrix")
        for row in range(degree):
            if rows[row][row] <= 0:
                raise ValidationError("ideal HNF diagonal entries must be positive")
            if any(rows[row][column] != 0 for column in range(row)):
                raise ValidationError("ideal_hnf must be upper triangular column HNF")
            if any(
                not 0 <= rows[row][column] < rows[row][row] for column in range(row + 1, degree)
            ):
                raise ValidationError("ideal-HNF entries above a pivot must be canonical residues")
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "ideal_hnf", rows)
        self._validate_order_closure()

    @property
    def ideal_id(self) -> str:
        return self.content_id

    @property
    def norm(self) -> int:
        result = 1
        for index in range(self.field.degree):
            result *= self.ideal_hnf[index][index]
        return result

    def _lattice_coordinates(self, vector: Sequence[Fraction]) -> tuple[Fraction, ...]:
        matrix = tuple(tuple(Fraction(value) for value in row) for row in self.ideal_hnf)
        return _solve_square(matrix, vector)

    def _validate_order_closure(self) -> None:
        degree = self.field.degree
        ideal_generators = tuple(
            self.field.from_integral_basis_coordinates(
                tuple(self.ideal_hnf[row][column] for row in range(degree))
            )
            for column in range(degree)
        )
        order_basis = tuple(
            self.field.from_integral_basis_coordinates(
                tuple(1 if index == row else 0 for row in range(degree))
            )
            for index in range(degree)
        )
        for ideal_generator in ideal_generators:
            for basis_element in order_basis:
                product = (ideal_generator * basis_element).coordinates_in_integral_basis()
                if any(
                    coordinate.denominator != 1 for coordinate in self._lattice_coordinates(product)
                ):
                    raise ValidationError(
                        "ideal HNF lattice is not closed under the pinned integral basis"
                    )

    def contains(self, element: NumberFieldElement) -> bool:
        """Return whether ``element`` belongs to this integral ideal."""

        if not isinstance(element, NumberFieldElement) or element.field != self.field:
            raise ValidationError("ideal membership requires an element of the pinned field")
        coordinates = element.coordinates_in_integral_basis()
        return all(value.denominator == 1 for value in self._lattice_coordinates(coordinates))

    def verify(self) -> bool:
        return Ideal(self.field, self.ideal_hnf) == self

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "field_id": self.field.field_id,
                "ideal_hnf": [list(row) for row in self.ideal_hnf],
                "integral_basis": [
                    rational_vector_payload(row) for row in self.field.integral_basis
                ],
                "schema": self.schema_version,
                "type": "arbogast.ideal",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    def to_schema_document(self) -> dict[str, object]:
        """Return this already-versioned canonical interchange document."""

        return self.to_dict()

    @classmethod
    def from_dict(cls, field: NumberField, value: Mapping[str, object]) -> Ideal:
        """Decode a canonical ideal while replaying its field and basis binding."""

        expected = {"field_id", "ideal_hnf", "integral_basis", "schema", "type"}
        if set(value) != expected:
            raise ValidationError("ideal document has a foreign shape")
        try:
            validate_document(value, IDEAL_SCHEMA)
        except ValueError as error:
            raise ValidationError(str(error)) from error
        if value.get("type") != "arbogast.ideal":
            raise ValidationError("ideal document has the wrong object type")
        if value.get("field_id") != field.field_id:
            raise ValidationError("ideal document names a different pinned field")
        expected_basis = [rational_vector_payload(row) for row in field.integral_basis]
        if value.get("integral_basis") != expected_basis:
            raise ValidationError("ideal document names a different integral basis")
        raw_hnf = value.get("ideal_hnf")
        if isinstance(raw_hnf, str | bytes) or not isinstance(raw_hnf, Sequence):
            raise ValidationError("ideal document omits its HNF")
        try:
            rows = tuple(
                tuple(_integer(entry, "ideal-HNF entry") for entry in row)
                for row in raw_hnf
                if isinstance(row, Sequence) and not isinstance(row, str | bytes)
            )
        except TypeError as error:
            raise ValidationError("ideal document has a malformed HNF") from error
        if len(rows) != len(raw_hnf):
            raise ValidationError("ideal document has a malformed HNF row")
        return cls(field, rows)


__all__ = ["Ideal"]
