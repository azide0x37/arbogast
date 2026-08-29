"""Shared exceptions for Arbogast's exact core.

Validation errors are deliberately distinct from ordinary arithmetic failures.  A
certificate verifier raises :class:`VerificationError` rather than returning a
truthy partial result when any advertised invariant fails.
"""

from __future__ import annotations


class ArbogastError(Exception):
    """Base class for package-defined errors."""


class ValidationError(ArbogastError, ValueError):
    """Raised when an exact mathematical object violates its contract."""


class VerificationError(ValidationError):
    """Raised when purported evidence does not verify exactly."""


class CanonicalEncodingError(ValidationError):
    """Raised when a value has no unambiguous canonical JSON encoding."""
