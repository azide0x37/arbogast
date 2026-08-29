"""Deterministic, backend-independent canonical encoding.

The encoder is intentionally smaller than a general serialization framework.  It accepts
only values whose mathematical meaning can be represented without consulting ``repr`` or
process-local state.  Unsupported values fail closed.
"""

from __future__ import annotations

import base64
import hashlib
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from pathlib import PurePath
from typing import Any, Protocol, TypeAlias, TypeVar, cast, runtime_checkable

from arbogast.core.canonical import (
    CanonicalObject as CoreCanonicalObject,
)
from arbogast.core.canonical import (
    canonical_bytes as _core_canonical_bytes,
)
from arbogast.core.canonical import (
    canonical_json as _core_canonical_json,
)


class CanonicalizationError(TypeError):
    """Raised when a value has no stable canonical representation."""


class ContentAddressError(ValueError):
    """Raised for malformed or mismatching content addresses."""


CanonicalScalar: TypeAlias = bool | int | str | None
CanonicalValue: TypeAlias = CanonicalScalar | list["CanonicalValue"] | dict[str, "CanonicalValue"]


@runtime_checkable
class Canonicalizable(Protocol):
    """Protocol implemented by semantic objects with a canonical payload."""

    def to_canonical(self) -> object:
        """Return data accepted by :func:`canonicalize`."""


T = TypeVar("T")


@dataclass(frozen=True, init=False)
class FrozenMap(Mapping[str, Any]):
    """A small immutable mapping used inside frozen semantic records."""

    _items: tuple[tuple[str, Any], ...]

    def __init__(
        self,
        values: Mapping[str, object] | Iterable[tuple[str, object]] | None = None,
    ) -> None:
        normalized_source: dict[str, object] = {}
        if values is None:
            items: Iterable[tuple[object, object]] = ()
        elif isinstance(values, Mapping):
            items = values.items()
        else:
            items = values
        for key, item in items:
            if not isinstance(key, str):
                raise CanonicalizationError("canonical mapping keys must be strings")
            normalized = unicodedata.normalize("NFC", key)
            if normalized in normalized_source:
                raise CanonicalizationError(
                    f"mapping keys collide after Unicode normalization: {normalized!r}"
                )
            normalized_source[normalized] = item
        frozen = tuple(
            (key, deep_freeze(normalized_source[key])) for key in sorted(normalized_source)
        )
        object.__setattr__(self, "_items", frozen)

    def __getitem__(self, key: str) -> Any:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def to_canonical(self) -> dict[str, CanonicalValue]:
        return {key: canonicalize(value) for key, value in self._items}

    def to_dict(self) -> dict[str, object]:
        """Return a mutable plain-data copy."""

        return {key: deep_thaw(value) for key, value in self._items}


def deep_freeze(value: object) -> object:
    """Recursively freeze mappings and sequences, rejecting unordered containers."""

    if isinstance(value, FrozenMap):
        return value
    if isinstance(value, Mapping):
        return FrozenMap(cast(Mapping[str, object], value))
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        raise CanonicalizationError("unordered sets are not canonical; provide a sorted sequence")
    return value


def deep_thaw(value: object) -> object:
    """Convert :func:`deep_freeze` output back to JSON-shaped plain data."""

    if isinstance(value, FrozenMap):
        return value.to_dict()
    if isinstance(value, tuple):
        return [deep_thaw(item) for item in value]
    return value


def freeze_mapping(values: Mapping[str, object] | None = None) -> FrozenMap:
    """Normalize an optional mapping to :class:`FrozenMap`."""

    return values if isinstance(values, FrozenMap) else FrozenMap(values)


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise CanonicalizationError("non-finite decimals are not canonical")
    if value.is_zero():
        return "0"
    normalized = value.normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def canonicalize(value: object) -> CanonicalValue:
    """Convert a supported value into deterministic JSON data.

    Floats use their exact hexadecimal representation rather than a platform-dependent
    decimal rendering.  Bytes, rationals, decimals, and paths carry explicit type tags.
    """

    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float):
        raise CanonicalizationError(
            "bare floating-point values are not exact canonical evidence; use an explicit "
            "Numerical wrapper or application-level type tag"
        )
    if isinstance(value, Decimal):
        return {"$decimal": _canonical_decimal(value)}
    if isinstance(value, Fraction):
        return {"$fraction": [value.numerator, value.denominator]}
    if isinstance(value, bytes):
        encoded = base64.b64encode(value).decode("ascii")
        return {"$bytes": encoded}
    if isinstance(value, PurePath):
        return {"$path": value.as_posix()}
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if isinstance(value, Mapping):
        result: dict[str, CanonicalValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("canonical mapping keys must be strings")
            normalized = unicodedata.normalize("NFC", key)
            if normalized in result:
                raise CanonicalizationError(
                    f"mapping keys collide after Unicode normalization: {normalized!r}"
                )
            result[normalized] = canonicalize(item)
        return {key: result[key] for key in sorted(result)}
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise CanonicalizationError("unordered sets are not canonical; provide a sorted sequence")
    if isinstance(value, Canonicalizable):
        payload = value.to_canonical()
        if payload is value:
            raise CanonicalizationError("to_canonical() returned self")
        return canonicalize(payload)
    if isinstance(value, CoreCanonicalObject):
        return canonicalize(value.to_canonical_data())
    raise CanonicalizationError(
        f"unsupported canonical value {type(value).__module__}.{type(value).__qualname__}"
    )


def canonical_json(value: object) -> str:
    """Encode ``value`` as canonical UTF-8 JSON text."""

    return _core_canonical_json(canonicalize(value))


def canonical_bytes(value: object) -> bytes:
    """Encode ``value`` as canonical UTF-8 bytes."""

    return _core_canonical_bytes(canonicalize(value))


def content_address(value: object, *, algorithm: str = "sha256") -> str:
    """Return the content address of a canonical value."""

    try:
        digest = hashlib.new(algorithm)
    except ValueError as exc:
        raise ContentAddressError(f"unsupported digest algorithm: {algorithm}") from exc
    digest.update(canonical_bytes(value))
    return f"{algorithm}:{digest.hexdigest()}"


def validate_content_address(address: str, value: object | None = None) -> str:
    """Validate an address, and optionally require it to match ``value``."""

    try:
        algorithm, hexadecimal = address.split(":", 1)
    except ValueError as exc:
        raise ContentAddressError("content address must have the form algorithm:hex") from exc
    if not algorithm or not hexadecimal:
        raise ContentAddressError("content address must have the form algorithm:hex")
    try:
        expected_size = hashlib.new(algorithm).digest_size * 2
    except ValueError as exc:
        raise ContentAddressError(f"unsupported digest algorithm: {algorithm}") from exc
    if len(hexadecimal) != expected_size or any(ch not in "0123456789abcdef" for ch in hexadecimal):
        raise ContentAddressError(f"malformed {algorithm} content address")
    if value is not None:
        actual = content_address(value, algorithm=algorithm)
        if actual != address:
            raise ContentAddressError(
                f"content address mismatch: expected {address}, computed {actual}"
            )
    return address


__all__ = [
    "CanonicalValue",
    "Canonicalizable",
    "CanonicalizationError",
    "ContentAddressError",
    "FrozenMap",
    "canonical_bytes",
    "canonical_json",
    "canonicalize",
    "content_address",
    "deep_freeze",
    "deep_thaw",
    "freeze_mapping",
    "validate_content_address",
]
