"""Small protocol adapters shared by arithmetic modules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from typing import Any, cast

from arbogast.cert import CanonicalizationError, content_address
from arbogast.linalg import DenseMatrix, LinearSubspace, PrimeField, Scalar, SparseMatrix, as_dense

from .certificate import ArithmeticError, Completeness, coerce_completeness


def prime_of(value: object) -> int:
    raw = getattr(value, "prime", None)
    if raw is None:
        field = getattr(value, "field", None)
        raw = getattr(field, "p", getattr(field, "characteristic", None))
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ArithmeticError(f"{type(value).__qualname__} does not expose an integer prime")
    PrimeField(raw)  # deterministic primality validation
    return raw


def dimension_of(value: object) -> int:
    raw = getattr(value, "dimension", None)
    if raw is None:
        raw = getattr(value, "ambient_dimension", None)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ArithmeticError(f"{type(value).__qualname__} does not expose a valid dimension")
    return raw


def field_of(value: object) -> PrimeField:
    field = getattr(value, "field", None)
    if isinstance(field, PrimeField):
        return field
    return PrimeField(prime_of(value))


def assumptions_of(value: object) -> tuple[str, ...]:
    raw = getattr(value, "assumptions", ())
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, Sequence):
        raise ArithmeticError("assumptions must be a sequence")
    result = tuple(raw)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ArithmeticError("assumptions must contain non-blank strings")
    return result


def completeness_of(
    value: object,
    *,
    default: Completeness = Completeness.CANDIDATE,
) -> Completeness:
    return coerce_completeness(getattr(value, "completeness", None), default=default)


def _identifier_attribute(value: object) -> str | None:
    for attribute in (
        "place_id",
        "space_id",
        "module_id",
        "field_id",
        "content_id",
        "certificate_id",
        "content_hash",
        "digest",
    ):
        raw = getattr(value, attribute, None)
        if isinstance(raw, str) and raw.strip():
            if attribute == "content_hash" and ":" not in raw:
                return f"sha256:{raw}"
            return raw
    return None


def identity_of(value: object, *, role: str = "object") -> str:
    """Return a stable canonical binding for a protocol object."""

    if value is None:
        return f"arbogast:{role}:none"
    explicit = _identifier_attribute(value)
    if explicit is not None:
        return explicit
    try:
        return content_address(value)
    except (CanonicalizationError, TypeError, ValueError):
        pass
    structural: dict[str, object] = {
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
        "role": role,
    }
    for attribute in (
        "name",
        "label",
        "prime",
        "dimension",
        "rational_prime",
        "embedding_index",
        "kind",
    ):
        raw = getattr(value, attribute, None)
        if raw is not None and isinstance(raw, (bool, int, str, Enum)):
            structural[attribute] = raw
    if len(structural) == 2:
        raise ArithmeticError(
            f"{role} must expose a canonical payload or stable content/place/module ID"
        )
    return content_address(structural)


def place_of(value: object, *, fallback: object | None = None) -> object:
    raw = getattr(value, "place", None)
    if raw is not None:
        return raw
    codomain = getattr(value, "codomain", None)
    raw = getattr(codomain, "place", None)
    if raw is not None:
        return raw
    if fallback is not None:
        return fallback
    raise ArithmeticError(f"{type(value).__qualname__} does not expose its place")


def matrix_of(value: object) -> DenseMatrix:
    raw = getattr(value, "matrix", value)
    if not isinstance(raw, (DenseMatrix, SparseMatrix)):
        raise ArithmeticError(f"{type(value).__qualname__} does not expose an exact matrix")
    return as_dense(raw)


def coordinates_of(
    value: object,
    *,
    field: PrimeField,
    length: int,
    name: str = "coordinates",
) -> tuple[int, ...]:
    raw = getattr(value, "coordinates", value)
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Iterable):
        raise ArithmeticError(f"{name} must be an iterable of prime-field scalars")
    result = tuple(field.residue(item) for item in raw)
    if len(result) != length:
        raise ArithmeticError(f"{name} has length {len(result)}, expected {length}")
    return result


def subspace_of(
    space: object,
    basis: LinearSubspace | Iterable[Iterable[object]],
) -> LinearSubspace:
    field = field_of(space)
    dimension = dimension_of(space)
    if isinstance(basis, LinearSubspace):
        if basis.field != field or basis.ambient_dimension != dimension:
            raise ArithmeticError("local-condition subspace belongs to a different local space")
        return basis
    return LinearSubspace(field, dimension, cast(Iterable[Iterable[Scalar]], basis))


def stack_matrices(
    field: PrimeField,
    matrices: Sequence[DenseMatrix],
    *,
    ncols: int,
) -> DenseMatrix:
    if any(matrix.field != field for matrix in matrices):
        raise ArithmeticError("cannot stack matrices over different coefficient fields")
    if any(matrix.ncols != ncols for matrix in matrices):
        raise ArithmeticError("stacked matrices have different domain dimensions")
    rows = tuple(row for matrix in matrices for row in matrix.rows)
    return DenseMatrix(field, rows, ncols=ncols)


def mapping_values_in_order(
    values: Mapping[object, Any],
    places: Sequence[object] | None,
) -> tuple[Any, ...]:
    """Canonicalize a place-indexed mapping without accepting ambiguous keys."""

    if places is None:
        return tuple(
            value
            for _, value in sorted(
                values.items(),
                key=lambda item: identity_of(item[0], role="place"),
            )
        )
    result: list[Any] = []
    unused = dict(values)
    for place in places:
        if place in unused:
            result.append(unused.pop(place))
            continue
        target = identity_of(place, role="place")
        matches = [key for key in unused if identity_of(key, role="place") == target]
        if len(matches) != 1:
            raise ArithmeticError(f"place-indexed mapping has no unique entry for {target}")
        key = matches[0]
        result.append(unused.pop(key))
    if unused:
        raise ArithmeticError("place-indexed mapping contains foreign entries")
    return tuple(result)


__all__ = [
    "assumptions_of",
    "completeness_of",
    "coordinates_of",
    "dimension_of",
    "field_of",
    "identity_of",
    "mapping_values_in_order",
    "matrix_of",
    "place_of",
    "prime_of",
    "stack_matrices",
    "subspace_of",
]
