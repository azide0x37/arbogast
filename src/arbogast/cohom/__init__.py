"""Exact finite-group cohomology over prime fields.

The implementation uses normalized inhomogeneous bar cochains.  Public results carry explicit
quotient maps, representative cocycles, and backend-free certificates whose verifier rebuilds
the finite linear algebra from the multiplication table and module action.
"""

from __future__ import annotations

from .certificate import (
    CertificateVerificationError,
    CohomologyCertificate,
    VerificationReport,
)
from .complex import (
    DEFAULT_LIMITS,
    Cochain,
    CochainComplex,
    CochainSpace,
    CohomologyError,
    ComplexityLimitError,
    ComplexityLimits,
    InvalidActionError,
    InvalidGroupError,
    UnsupportedCoefficientFieldError,
    cochain_complex,
)
from .maps import inflate, restrict
from .results import (
    H0,
    H1,
    H2,
    CoboundaryWitness,
    CochainSubspace,
    CohomologyClaim,
    CohomologyClass,
    CohomologyResult,
    H0Result,
    H1Result,
    H2Result,
    QuotientMap,
    class_of,
    coboundaries,
    cocycles,
    cohomology,
    h0,
    h1,
    h2,
    is_coboundary,
    is_cocycle,
)

__all__ = [
    "DEFAULT_LIMITS",
    "H0",
    "H1",
    "H2",
    "CertificateVerificationError",
    "CoboundaryWitness",
    "Cochain",
    "CochainComplex",
    "CochainSpace",
    "CochainSubspace",
    "CohomologyCertificate",
    "CohomologyClaim",
    "CohomologyClass",
    "CohomologyError",
    "CohomologyResult",
    "ComplexityLimitError",
    "ComplexityLimits",
    "H0Result",
    "H1Result",
    "H2Result",
    "InvalidActionError",
    "InvalidGroupError",
    "QuotientMap",
    "UnsupportedCoefficientFieldError",
    "VerificationReport",
    "class_of",
    "coboundaries",
    "cochain_complex",
    "cocycles",
    "cohomology",
    "h0",
    "h1",
    "h2",
    "inflate",
    "is_coboundary",
    "is_cocycle",
    "restrict",
]
