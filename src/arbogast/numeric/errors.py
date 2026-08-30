"""Typed failures for the bounded numeric bridge."""

from __future__ import annotations


class NumericError(ValueError):
    """Base class for malformed numeric inputs and invalid witnesses."""


class NumericVerificationError(NumericError):
    """Raised when an exact numeric witness fails independent replay."""


class UnsupportedNumericOperation(NumericError):
    """Raised only by strict constructors outside the supported bounded slice."""


__all__ = ["NumericError", "NumericVerificationError", "UnsupportedNumericOperation"]
