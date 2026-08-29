"""Canonical JSON primitives used at persistence and hashing boundaries.

Arbogast deliberately uses a small, strict JSON subset for identities.  In
particular, mappings must have string keys and all bare floating-point values
are rejected.  This keeps a task hash independent of Python object
identity, insertion order, and platform-specific JSON formatting.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import is_dataclass
from enum import Enum
from typing import Any, TypeAlias

from arbogast.core.canonical import (
    _parse_decimal_integer,
    sha256_hex,
)
from arbogast.core.canonical import (
    canonical_bytes as core_canonical_bytes,
)
from arbogast.core.canonical import (
    canonical_data as core_canonical_data,
)
from arbogast.core.canonical import (
    canonical_json as core_canonical_json,
)
from arbogast.core.errors import CanonicalEncodingError

JSONScalar: TypeAlias = bool | int | str | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class CanonicalJSONError(ValueError):
    """Raised when a value cannot participate in canonical JSON."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting keys a normal dict would erase."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalJSONError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


class FrozenMapping(Mapping[str, "FrozenJSONValue"]):
    """A recursively immutable, key-sorted JSON mapping.

    ``dataclass(frozen=True)`` does not make a nested ``dict`` immutable.  This
    lightweight mapping closes that hole for task parameters and packet data.
    """

    __slots__ = ("_items", "_lookup")

    def __init__(self, value: Mapping[str, Any] | None = None) -> None:
        source = {} if value is None else value
        try:
            normalized = core_canonical_data(_object_projection(source))
        except CanonicalEncodingError as error:
            raise CanonicalJSONError(str(error)) from error
        if not isinstance(normalized, dict):
            raise CanonicalJSONError("frozen mapping source must canonicalize to an object")
        items: list[tuple[str, FrozenJSONValue]] = []
        for key, item in normalized.items():
            items.append((key, freeze_json(item)))
        items.sort(key=lambda pair: pair[0])
        self._items = tuple(items)
        self._lookup = dict(items)

    def __getitem__(self, key: str) -> FrozenJSONValue:
        return self._lookup[key]

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"FrozenMapping({dict(self._items)!r})"

    def __hash__(self) -> int:
        return hash(self._items)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenMapping):
            return self._items == other._items
        if isinstance(other, Mapping):
            try:
                return self.to_dict() == normalize_json(other)
            except CanonicalJSONError:
                return False
        return NotImplemented

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a mutable JSON-compatible copy."""

        return {key: thaw_json(value) for key, value in self._items}


FrozenJSONValue: TypeAlias = JSONScalar | tuple["FrozenJSONValue", ...] | FrozenMapping


def _object_projection(value: Any) -> Any:
    """Project supported semantic objects before core canonicalization."""

    if isinstance(value, Enum):
        return value.value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _object_projection(to_dict())
    if is_dataclass(value):
        # Dataclasses used in identity material should explicitly declare their
        # representation.  ``dataclasses.asdict`` can accidentally serialize
        # cache-only fields and therefore is intentionally not used.
        raise CanonicalJSONError(
            f"dataclass {type(value).__qualname__} must define to_dict() for canonical JSON"
        )
    if isinstance(value, Mapping):
        return {key: _object_projection(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_object_projection(item) for item in value]
    return value


def normalize_json(value: Any) -> JSONValue:
    """Return a canonicalizable JSON copy of ``value``.

    Tuples are represented as JSON arrays.  Other arbitrary iterables are not
    accepted because iteration order may not be a semantic invariant.
    """

    try:
        normalized = core_canonical_data(_object_projection(value))
    except CanonicalEncodingError as error:
        raise CanonicalJSONError(str(error)) from error
    return normalized


def freeze_json(value: Any) -> FrozenJSONValue:
    """Recursively freeze a JSON-compatible value."""

    normalized = normalize_json(value)
    if isinstance(normalized, dict):
        return FrozenMapping(normalized)
    if isinstance(normalized, list):
        return tuple(freeze_json(item) for item in normalized)
    return normalized


def thaw_json(value: FrozenJSONValue) -> JSONValue:
    """Return a mutable JSON-compatible copy of a frozen value."""

    if isinstance(value, FrozenMapping):
        return value.to_dict()
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def canonical_dumps(value: Any) -> str:
    """Serialize ``value`` using Arbogast's stable JSON encoding."""

    try:
        return core_canonical_json(_object_projection(value))
    except CanonicalEncodingError as error:
        raise CanonicalJSONError(str(error)) from error


def canonical_bytes(value: Any) -> bytes:
    """Return the UTF-8 bytes of :func:`canonical_dumps`."""

    try:
        return core_canonical_bytes(_object_projection(value))
    except CanonicalEncodingError as error:
        raise CanonicalJSONError(str(error)) from error


def canonical_sha256(value: Any) -> str:
    """Hash a value's canonical JSON representation."""

    try:
        return sha256_hex(_object_projection(value))
    except CanonicalEncodingError as error:
        raise CanonicalJSONError(str(error)) from error


def loads(data: str | bytes | bytearray) -> JSONValue:
    """Load a semantically strict JSON document and return normalized data.

    Duplicate keys, non-exact values, invalid UTF-8, and normalized-key
    collisions are rejected.  Presentation alternatives such as whitespace,
    object insertion order, escaped Unicode, or decomposed Unicode are accepted
    and normalized; callers that bind the literal input bytes must compare them
    with :func:`canonical_bytes` (or use ``core.require_canonical_json``).
    """

    try:
        parsed = json.loads(
            data,
            object_pairs_hook=_unique_object,
            parse_int=_parse_decimal_integer,
        )
    except CanonicalJSONError:
        raise
    except CanonicalEncodingError as error:
        raise CanonicalJSONError(str(error)) from error
    except (UnicodeError, RecursionError, TypeError, ValueError) as error:
        raise CanonicalJSONError(str(error)) from error
    return normalize_json(parsed)
