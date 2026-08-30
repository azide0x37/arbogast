"""Typed failures for the bounded certified p-adic layer."""

from __future__ import annotations


class PAdicError(ValueError):
    """Base class for malformed p-adic inputs and invalid witnesses."""


class PAdicValidationError(PAdicError):
    """Raised when a public p-adic constructor receives invalid exact data."""


class PAdicVerificationError(PAdicError):
    """Raised when independent replay of a p-adic witness fails."""


class PAdicCertificateError(PAdicError):
    """Raised when a strict p-adic receipt or certificate cannot be formed."""


class PAdicResourceError(PAdicVerificationError):
    """Raised before work or transport exceeds the portable replay envelope."""


class UnsupportedPAdicOperation(PAdicError):
    """Raised only by strict APIs that cannot return a typed Unsupported result."""


__all__ = [
    "PAdicCertificateError",
    "PAdicError",
    "PAdicResourceError",
    "PAdicValidationError",
    "PAdicVerificationError",
    "UnsupportedPAdicOperation",
]
