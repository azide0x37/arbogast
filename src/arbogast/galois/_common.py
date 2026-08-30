"""Shared exact helpers for the certified arithmetic layer.

This module deliberately works with canonical snapshots.  Backend handles and
session-local objects must be reduced to the public substrate's canonical data
before they enter a certificate.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction
from typing import Any, TypeAlias, cast

from arbogast.cert import CanonicalValue, canonicalize, content_address, freeze_mapping
from arbogast.linalg import DenseMatrix, PrimeField

Vector: TypeAlias = tuple[int, ...]
Rows: TypeAlias = tuple[Vector, ...]


def strict_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def strict_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name} must be a non-blank string")
    return value


def sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence")
    return value


def string_tuple(value: object, name: str) -> tuple[str, ...]:
    return tuple(
        strict_string(item, f"{name}[{index}]") for index, item in enumerate(sequence(value, name))
    )


def integer_tuple(value: object, name: str) -> tuple[int, ...]:
    return tuple(
        strict_integer(item, f"{name}[{index}]") for index, item in enumerate(sequence(value, name))
    )


def element_from_pari_coefficients(field: Any, value: object, name: str) -> Any:
    """Decode one normalized PARI rational-pair vector into the pinned field."""

    coefficients: list[Fraction] = []
    for index, raw_pair in enumerate(sequence(value, name)):
        pair = integer_tuple(raw_pair, f"{name}[{index}]")
        if len(pair) != 2 or pair[1] == 0:
            raise ValueError(f"{name}[{index}] must be a numerator/denominator pair")
        coefficients.append(Fraction(pair[0], pair[1]))
    if len(coefficients) != getattr(field, "degree", None):
        raise ValueError(f"{name} has the wrong number-field degree")
    return field.element(tuple(coefficients))


def rows_tuple(value: object, name: str) -> Rows:
    return tuple(
        integer_tuple(row, f"{name}[{index}]") for index, row in enumerate(sequence(value, name))
    )


def canonical_snapshot(value: object) -> CanonicalValue:
    """Return backend-independent canonical data for one semantic object."""

    return canonicalize(value)


def snapshot_id(value: object) -> str:
    content_id = getattr(value, "content_id", None)
    if isinstance(content_id, str):
        return content_id
    place_id = getattr(value, "place_id", None)
    if isinstance(place_id, str):
        return place_id
    element_id = getattr(value, "element_id", None)
    if isinstance(element_id, str):
        return element_id
    fingerprint = getattr(value, "fingerprint", None)
    if isinstance(fingerprint, str):
        return fingerprint
    return content_address(canonical_snapshot(value))


def canonical_permutation_or_value(value: object) -> CanonicalValue:
    """Encode common concrete group elements without a ``repr`` fallback."""

    images = getattr(value, "images", None)
    if isinstance(images, tuple) and all(isinstance(item, int) for item in images):
        return {"images": list(images), "type": "permutation"}
    return canonical_snapshot(value)


def canonical_group_elements(group: object) -> tuple[object, ...]:
    raw = getattr(group, "elements", None)
    if raw is None:
        try:
            raw = tuple(cast(Iterable[object], group))
        except TypeError as error:
            raise TypeError("finite group must expose an elements sequence") from error
    elements = tuple(cast(Iterable[object], raw))
    if not elements:
        raise ValueError("finite group must contain an identity")
    return elements


def group_identity(group: object, elements: tuple[object, ...]) -> object:
    identity = getattr(group, "identity", None)
    if identity is None:
        for candidate in elements:
            if all(
                group_multiply(group, candidate, item) == item
                and group_multiply(group, item, candidate) == item
                for item in elements
            ):
                return candidate
        raise ValueError("finite group has no detectable identity")
    if identity not in elements:
        raise ValueError("finite group identity is absent from its elements")
    return identity


def group_multiply(group: object, left: object, right: object) -> object:
    multiply = getattr(group, "multiply", None)
    if callable(multiply):
        return multiply(left, right)
    try:
        return left * right  # type: ignore[operator]
    except TypeError as error:
        raise TypeError("finite group must expose multiply(left, right)") from error


def group_inverse(group: object, element: object, elements: tuple[object, ...]) -> object:
    inverse = getattr(group, "inverse", None)
    if callable(inverse):
        return inverse(element)
    element_inverse = getattr(element, "inverse", None)
    if callable(element_inverse):
        return element_inverse()
    identity = group_identity(group, elements)
    for candidate in elements:
        if (
            group_multiply(group, element, candidate) == identity
            and group_multiply(group, candidate, element) == identity
        ):
            return candidate
    raise ValueError("finite group element has no inverse")


def multiplication_table(group: object, elements: tuple[object, ...]) -> Rows:
    lookup = {element: index for index, element in enumerate(elements)}
    if len(lookup) != len(elements):
        raise ValueError("finite group elements must be hashable and unique")
    rows: list[Vector] = []
    for left in elements:
        row: list[int] = []
        for right in elements:
            product = group_multiply(group, left, right)
            if product not in lookup:
                raise ValueError("finite group elements are not closed under multiplication")
            row.append(lookup[product])
        rows.append(tuple(row))
    return tuple(rows)


def inverse_table(group: object, elements: tuple[object, ...]) -> Vector:
    lookup = {element: index for index, element in enumerate(elements)}
    return tuple(lookup[group_inverse(group, element, elements)] for element in elements)


def validate_group_table(table: Rows, identity_index: int, inverse_indices: Vector) -> None:
    size = len(table)
    if size == 0 or not 0 <= identity_index < size:
        raise ValueError("group table has an invalid identity index")
    if len(inverse_indices) != size or any(len(row) != size for row in table):
        raise ValueError("group table has inconsistent dimensions")
    if any(not 0 <= entry < size for row in table for entry in row):
        raise ValueError("group multiplication index is out of range")
    for index in range(size):
        if table[identity_index][index] != index or table[index][identity_index] != index:
            raise ValueError("group table identity law failed")
        inverse = inverse_indices[index]
        if not 0 <= inverse < size:
            raise ValueError("group inverse index is out of range")
        if table[index][inverse] != identity_index or table[inverse][index] != identity_index:
            raise ValueError("group table inverse law failed")
    for left in range(size):
        for middle in range(size):
            for right in range(size):
                if table[table[left][middle]][right] != table[left][table[middle][right]]:
                    raise ValueError("group table associativity failed")


def prime_field(prime: object) -> PrimeField:
    return PrimeField(strict_integer(prime, "prime"))


def canonical_coordinates(values: Iterable[int], dimension: int, prime: int) -> Vector:
    coordinates = tuple(strict_integer(value, "coordinate") % prime for value in values)
    if len(coordinates) != dimension:
        raise ValueError(f"coordinates have dimension {len(coordinates)}, expected {dimension}")
    return coordinates


def canonical_matrix(
    rows: Iterable[Iterable[int]],
    *,
    prime: int,
    nrows: int,
    ncols: int,
) -> DenseMatrix:
    materialized = tuple(tuple(row) for row in rows)
    if len(materialized) != nrows:
        raise ValueError(f"matrix has {len(materialized)} rows, expected {nrows}")
    matrix = DenseMatrix(prime_field(prime), materialized, ncols=ncols)
    if matrix.ncols != ncols:
        raise ValueError(f"matrix has {matrix.ncols} columns, expected {ncols}")
    return matrix


def proof_context_snapshot(context: object) -> CanonicalValue:
    return canonical_snapshot(context)


def assumptions_from_context(context: object) -> tuple[str, ...]:
    raw = getattr(context, "assumptions", ())
    return tuple(cast(Iterable[str], raw))


def completeness_value(value: object) -> str:
    raw = getattr(value, "value", value)
    if raw not in {"candidate", "complete", "CANDIDATE", "COMPLETE"}:
        raise ValueError("completeness must be CANDIDATE or COMPLETE")
    return str(raw).lower()


def field_of(value: object) -> object | None:
    return getattr(value, "field", None)


def rational_value(element: object) -> Fraction | None:
    coefficients = getattr(element, "coefficients", None)
    if isinstance(coefficients, tuple) and len(coefficients) == 1:
        return Fraction(coefficients[0])
    if isinstance(element, (int, Fraction)) and not isinstance(element, bool):
        return Fraction(element)
    return None


def frozen_witness(value: Mapping[str, object] | None = None) -> Mapping[str, Any]:
    return freeze_mapping(value)


def is_rational_field(field: object) -> bool:
    return getattr(field, "degree", None) == 1


def is_finite_place(place: object) -> bool:
    return hasattr(place, "rational_prime") and hasattr(place, "ideal_hnf")


def is_infinite_place(place: object) -> bool:
    return hasattr(place, "kind") and hasattr(place, "embedding_index")


__all__ = [
    "Rows",
    "Vector",
    "assumptions_from_context",
    "canonical_coordinates",
    "canonical_group_elements",
    "canonical_matrix",
    "canonical_permutation_or_value",
    "canonical_snapshot",
    "completeness_value",
    "element_from_pari_coefficients",
    "field_of",
    "frozen_witness",
    "group_identity",
    "group_inverse",
    "group_multiply",
    "integer_tuple",
    "inverse_table",
    "is_finite_place",
    "is_infinite_place",
    "is_rational_field",
    "multiplication_table",
    "prime_field",
    "proof_context_snapshot",
    "rational_value",
    "rows_tuple",
    "sequence",
    "snapshot_id",
    "strict_integer",
    "strict_string",
    "string_tuple",
    "validate_group_table",
]
