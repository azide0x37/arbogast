"""Shared canonical and semantic support for the bounded numeric bridge."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from importlib import import_module
from typing import ClassVar, cast

from arbogast.cert import VerificationCertificate
from arbogast.claims import Claim, ClaimGraph
from arbogast.core import CanonicalJSON, CanonicalObject

MAX_DYADIC_BITS = 4096
MAX_DYADIC_EXPONENT = 1_000_000
MAX_DIMENSION = 64
MAX_POLYNOMIALS = 256
MAX_TERMS = 4096
MAX_TOTAL_DEGREE = 256
MAX_PATH_VERTICES = 4096
MAX_TUBE_STEPS = 4096
MAX_GRAPH_VERTICES = 100_000
MAX_GRAPH_EDGES = 1_000_000
MAX_BRAID_WORD_LENGTH = 4096
MAX_CANONICAL_NODES = 100_000
MAX_CANONICAL_DEPTH = 128
MAX_CANONICAL_INTEGER_BITS = 4096
MAX_TEXT_LENGTH = 16_384
MAX_RECEIPT_DEPENDENCIES = 256
MAX_ASSUMPTIONS = 256
MAX_RECOGNITION_DEGREE = 64
MAX_RECOGNITION_HEIGHT = 1 << 256

_VERIFY_DEPTH: ContextVar[int] = ContextVar("numeric_verify_depth", default=0)


def strict_int(value: object, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def canonical_label(value: str | None, name: str, *, optional: bool = False) -> str | None:
    if value is None:
        if optional:
            return None
        raise TypeError(f"{name} must be a string")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    normalized = unicodedata.normalize("NFC", value.strip())
    if len(normalized) > MAX_TEXT_LENGTH:
        raise ValueError(f"{name} exceeds the portable text-length bound")
    return normalized


def ensure_canonical_bounds(
    value: object,
    name: str = "numeric object",
    *,
    depth: int = 0,
) -> int:
    """Reject runtime objects whose exact snapshot cannot fit the receipt envelope."""

    from .errors import NumericVerificationError

    if depth > MAX_CANONICAL_DEPTH:
        raise NumericVerificationError(f"{name} exceeds the portable nesting-depth bound")
    if value is None or type(value) is bool:
        return 1
    if type(value) is int:
        if value.bit_length() > MAX_CANONICAL_INTEGER_BITS:
            raise NumericVerificationError(f"{name} contains an oversized integer")
        return 1
    if type(value) is str:
        text = value
        if text != unicodedata.normalize("NFC", text):
            raise NumericVerificationError(f"{name} contains noncanonical Unicode text")
        if len(text) > MAX_TEXT_LENGTH:
            raise NumericVerificationError(f"{name} contains oversized text")
        return 1
    if type(value) is list:
        count = 1
        for index, item in enumerate(cast(list[object], value)):
            count += ensure_canonical_bounds(
                item,
                f"{name}[{index}]",
                depth=depth + 1,
            )
            if count > MAX_CANONICAL_NODES:
                raise NumericVerificationError(f"{name} exceeds the portable node bound")
        return count
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise NumericVerificationError(f"{name} contains a non-string mapping key")
        count = 1
        for key, item in mapping.items():
            text_key = cast(str, key)
            if text_key != unicodedata.normalize("NFC", text_key):
                raise NumericVerificationError(f"{name} contains a noncanonical mapping key")
            if len(text_key) > MAX_TEXT_LENGTH:
                raise NumericVerificationError(f"{name} contains an oversized mapping key")
            count += ensure_canonical_bounds(
                item,
                f"{name}.{text_key}",
                depth=depth + 1,
            )
            if count > MAX_CANONICAL_NODES:
                raise NumericVerificationError(f"{name} exceeds the portable node bound")
        return count
    raise NumericVerificationError(
        f"{name} contains noncanonical {type(value).__module__}.{type(value).__qualname__}"
    )


class NumericSchemaObject(CanonicalObject):
    """Canonical numeric object carrying a local additive wire-schema ID."""

    schema_version: ClassVar[str]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Apply the receipt resource envelope to every concrete replay method."""

        super().__init_subclass__(**kwargs)
        raw_verify = cls.__dict__.get("verify")
        if raw_verify is None or getattr(raw_verify, "_numeric_bounds_wrapped", False):
            return
        verify = cast(Callable[..., object], raw_verify)

        @wraps(verify)
        def bounded_verify(self: NumericSchemaObject, *args: object, **inner: object) -> object:
            depth = _VERIFY_DEPTH.get()
            token = _VERIFY_DEPTH.set(depth + 1)
            try:
                result = verify(self, *args, **inner)
                if result is True and depth == 0:
                    try:
                        payload = self.to_canonical_data()
                    except AttributeError:
                        # Some cooperative base constructors replay before the most-derived
                        # immutable object has attached its final ambient witness.
                        return result
                    ensure_canonical_bounds(payload, type(self).__qualname__)
                return result
            finally:
                _VERIFY_DEPTH.reset(token)

        bounded_verify.__dict__["_numeric_bounds_wrapped"] = True
        type.__setattr__(cls, "verify", bounded_verify)

    def to_schema_document(self) -> dict[str, CanonicalJSON]:
        payload = self.to_canonical_data()
        if not isinstance(payload, dict):
            raise TypeError("numeric schema objects must encode as canonical mappings")
        return {"schema": self.schema_version, **payload}


class NumericSemanticObject(NumericSchemaObject):
    """Numeric result exposing the unchanged central certificate/claim adapters."""

    @property
    def certificate(self) -> VerificationCertificate:
        semantic = import_module("arbogast.numeric.semantic")
        return cast(VerificationCertificate, semantic.verification_certificate_for_result(self))

    def claim(self) -> Claim:
        semantic = import_module("arbogast.numeric.semantic")
        return cast(Claim, semantic.claim_for_result(self))

    def claim_graph(self) -> ClaimGraph:
        semantic = import_module("arbogast.numeric.semantic")
        return cast(ClaimGraph, semantic.claim_graph_for_result(self))


__all__ = ["NumericSchemaObject", "NumericSemanticObject"]
