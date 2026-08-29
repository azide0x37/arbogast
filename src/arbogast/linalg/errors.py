"""Errors specific to exact finite-field linear algebra."""

from __future__ import annotations

from arbogast.core import ValidationError


class LinearAlgebraError(ValidationError):
    """Base class for malformed or unsupported exact linear algebra."""


class FieldMismatchError(LinearAlgebraError):
    """Raised when operands belong to different coefficient fields."""


class DimensionMismatchError(LinearAlgebraError):
    """Raised when shapes are incompatible with an operation."""


class SingularMatrixError(LinearAlgebraError):
    """Raised when an inverse is requested for a singular matrix."""
