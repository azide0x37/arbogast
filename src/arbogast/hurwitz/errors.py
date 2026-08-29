"""Fail-closed exceptions for the exact Hurwitz layer."""

from __future__ import annotations


class HurwitzError(Exception):
    """Base class for exact Hurwitz errors."""


class GroupProtocolError(HurwitzError, TypeError):
    """The supplied group does not expose the required exact finite protocol."""


class ConcreteGroupMismatchError(HurwitzError, ValueError):
    """Objects from different concrete group embeddings were mixed."""


class InvalidConjugacyClassError(HurwitzError, ValueError):
    """A purported explicit conjugacy class is not one exact group orbit."""


class InvalidNielsenTupleError(HurwitzError, ValueError):
    """A tuple fails product-one, class-membership, or generation checks."""


class BraidClosureError(HurwitzError, ValueError):
    """A requested braid operation leaves the supplied Nielsen dataset."""


class CertificateVerificationError(HurwitzError, ValueError):
    """A finite certificate failed independent verification."""


class ImportedBoundaryError(HurwitzError, ValueError):
    """An imported dataset does not meet its declared typed boundary."""


class UnsupportedHurwitzOperation(HurwitzError, NotImplementedError):
    """The exact inputs do not determine the requested operation."""
