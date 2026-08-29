"""Deterministic, strict JSON encoding and SHA-256 content identities.

The canonical format is intentionally smaller than general JSON.  It accepts
``None``, booleans, integers, Unicode strings, arrays, string-keyed mappings,
and :class:`CanonicalObject` instances.  Floating-point numbers are excluded
from the finite exact core: accepting them would admit NaN, signed-zero, and
formatting ambiguities at a proof boundary.

Strings and mapping keys are normalized to Unicode NFC.  Mapping keys that
collide after normalization are rejected.  Objects are encoded with sorted
keys, no insignificant whitespace, UTF-8, and a trailing-newline-free byte
representation.  The same mathematical value therefore has the same bytes on
every supported Python implementation and backend.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import TypeAlias, cast

from .errors import CanonicalEncodingError

CanonicalScalar: TypeAlias = bool | int | str | None
CanonicalJSON: TypeAlias = CanonicalScalar | list["CanonicalJSON"] | dict[str, "CanonicalJSON"]


class CanonicalObject(ABC):
    """Mixin for immutable values with a canonical JSON representation.

    Subclasses should also be immutable and structurally hashable.  The mixin
    supplies convenience methods but intentionally does not define equality or
    ``__hash__``; frozen dataclasses can provide those without hidden identity
    semantics.
    """

    @abstractmethod
    def to_canonical_data(self) -> CanonicalJSON:
        """Return the object's tagged, backend-independent JSON value."""

    def to_canonical_json(self) -> str:
        """Return the canonical JSON text for this object."""

        return canonical_json(self)

    def to_canonical_bytes(self) -> bytes:
        """Return canonical UTF-8 bytes for this object."""

        return canonical_bytes(self)

    @property
    def content_id(self) -> str:
        """Return the object's ``sha256:<hex>`` content identity."""

        return sha256_identity(self)


def _normalized_string(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalEncodingError(
            "canonical JSON strings must contain only UTF-8 Unicode scalar values"
        ) from exc
    return normalized


_DECIMAL_CHUNK_DIGITS = 9
_DECIMAL_CHUNK_BASE = 10**_DECIMAL_CHUNK_DIGITS


def _decimal_integer(value: int) -> str:
    """Render an integer without consulting Python's decimal-digit safety limit.

    Python 3.11 added a process-configurable limit to conversions between large
    decimal strings and integers.  That denial-of-service guard is useful for
    general-purpose parsing, but it must not silently narrow Arbogast's exact
    integer data model or make content identities depend on interpreter flags.
    Dividing into fixed-size chunks keeps each built-in conversion bounded.
    """

    if value == 0:
        return "0"
    negative = value < 0
    magnitude = -value if negative else value
    chunks: list[int] = []
    while magnitude:
        magnitude, chunk = divmod(magnitude, _DECIMAL_CHUNK_BASE)
        chunks.append(chunk)
    leading = str(chunks.pop())
    trailing = "".join(str(chunk).zfill(_DECIMAL_CHUNK_DIGITS) for chunk in reversed(chunks))
    return ("-" if negative else "") + leading + trailing


def _parse_decimal_integer(value: str) -> int:
    """Parse a JSON integer independently of Python's decimal-digit limit."""

    negative = value.startswith("-")
    digits = value[1:] if negative else value
    # ``json.loads`` validates integer syntax before invoking ``parse_int``.
    # Keeping the check here makes this private helper fail predictably if it is
    # ever reused directly.
    if not digits or any(character < "0" or character > "9" for character in digits):
        raise CanonicalEncodingError("invalid decimal integer in canonical JSON")
    first_width = len(digits) % _DECIMAL_CHUNK_DIGITS or _DECIMAL_CHUNK_DIGITS
    result = int(digits[:first_width])
    for offset in range(first_width, len(digits), _DECIMAL_CHUNK_DIGITS):
        result = result * _DECIMAL_CHUNK_BASE + int(digits[offset : offset + _DECIMAL_CHUNK_DIGITS])
    return -result if negative else result


def _encode_canonical_data(value: CanonicalJSON) -> str:
    """Encode already-normalized data without an interpreter-sized int path."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return _decimal_integer(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_encode_canonical_data(item) for item in value) + "]"
    return (
        "{"
        + ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{_encode_canonical_data(value[key])}"
            for key in sorted(value)
        )
        + "}"
    )


def _encode_pretty_canonical_data(
    value: CanonicalJSON,
    *,
    indent: int,
    depth: int = 0,
) -> str:
    """Encode canonical data with whitespace but no decimal string-size limit."""

    indentation = " " * max(indent, 0)
    current_prefix = indentation * depth
    child_prefix = indentation * (depth + 1)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return _decimal_integer(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if not value:
            return "[]"
        items = ",\n".join(
            f"{child_prefix}{_encode_pretty_canonical_data(item, indent=indent, depth=depth + 1)}"
            for item in value
        )
        return f"[\n{items}\n{current_prefix}]"
    if not value:
        return "{}"
    items = ",\n".join(
        f"{child_prefix}{json.dumps(key, ensure_ascii=False)}: "
        f"{_encode_pretty_canonical_data(value[key], indent=indent, depth=depth + 1)}"
        for key in sorted(value)
    )
    return f"{{\n{items}\n{current_prefix}}}"


def canonical_data(value: object) -> CanonicalJSON:
    """Convert *value* to the strict canonical JSON data model.

    Mutable input containers are copied recursively.  Unsupported values fail
    closed with :class:`CanonicalEncodingError`; there is no ``repr`` fallback
    because representations are neither stable nor generally injective.
    """

    if value is None or isinstance(value, bool):
        return cast(CanonicalScalar, value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _normalized_string(value)
    if isinstance(value, float):
        raise CanonicalEncodingError("floating-point values are not part of exact canonical JSON")
    if isinstance(value, CanonicalObject):
        return canonical_data(value.to_canonical_data())
    if isinstance(value, Enum):
        return canonical_data(value.value)
    if isinstance(value, Mapping):
        result: dict[str, CanonicalJSON] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalEncodingError("canonical JSON mapping keys must be strings")
            normalized = _normalized_string(key)
            if normalized in result:
                raise CanonicalEncodingError(
                    f"mapping keys collide after Unicode normalization: {normalized!r}"
                )
            result[normalized] = canonical_data(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [canonical_data(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise CanonicalEncodingError(
            "raw bytes require an explicit application-level encoding and type tag"
        )
    raise CanonicalEncodingError(
        f"unsupported canonical JSON value of type {type(value).__qualname__}"
    )


def canonical_json(value: object) -> str:
    """Serialize *value* as normalized deterministic JSON text."""

    try:
        return _encode_canonical_data(canonical_data(value))
    except CanonicalEncodingError:
        raise
    except (RecursionError, UnicodeError, ValueError, TypeError) as exc:
        raise CanonicalEncodingError(f"cannot encode canonical JSON: {exc}") from exc


def pretty_canonical_json(value: object, *, indent: int = 2) -> str:
    """Serialize *value* as deterministic indented JSON with exact integers.

    This differs from :func:`canonical_json` only in insignificant whitespace.
    The custom encoder avoids the interpreter's configurable decimal digit
    limit, which otherwise makes ``json.dumps(..., indent=...)`` reject valid
    arbitrary-size exact integers.
    """

    if not isinstance(indent, int):
        raise CanonicalEncodingError("canonical JSON indentation must be an integer")
    try:
        return _encode_pretty_canonical_data(canonical_data(value), indent=indent)
    except CanonicalEncodingError:
        raise
    except (RecursionError, UnicodeError, ValueError, TypeError) as exc:
        raise CanonicalEncodingError(f"cannot encode canonical JSON: {exc}") from exc


def canonical_bytes(value: object) -> bytes:
    """Serialize *value* as canonical UTF-8 bytes."""

    try:
        return canonical_json(value).encode("utf-8")
    except CanonicalEncodingError:
        raise
    except UnicodeEncodeError as exc:
        raise CanonicalEncodingError("canonical JSON text is not valid UTF-8") from exc


def sha256_hex(value: object) -> str:
    """Return the lowercase SHA-256 hexadecimal digest of canonical bytes."""

    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_identity(value: object) -> str:
    """Return a self-describing ``sha256:<hex>`` content identity."""

    return f"sha256:{sha256_hex(value)}"


def require_canonical_json(text: str) -> CanonicalJSON:
    """Parse canonical JSON and reject alternate encodings of the same value.

    This is useful at trust boundaries: merely parsing JSON does not establish
    that the supplied bytes are the bytes whose digest a certificate advertises.
    """

    try:
        parsed: object = json.loads(text, parse_int=_parse_decimal_integer)
    except CanonicalEncodingError:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError, TypeError, ValueError) as exc:
        raise CanonicalEncodingError("invalid JSON") from exc
    normalized = canonical_data(parsed)
    if canonical_json(normalized) != text:
        raise CanonicalEncodingError("JSON text is valid but not canonical")
    return normalized
