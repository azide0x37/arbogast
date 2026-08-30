"""Certified finite Galois, Kummer, local, and twist arithmetic."""

from __future__ import annotations

from .certificate import (
    ArithmeticCertificateError,
    KummerReceipt,
    LocalH1Receipt,
    LocalizationReceipt,
    TwistReceipt,
)
from .fields import (
    FieldEmbedding,
    ModularIrreducibilityWitness,
    NumberField,
    NumberFieldElement,
    RationalLike,
)
from .groups import (
    FINITE_QUOTIENT_VERIFIER_ID,
    GALOIS_QUOTIENT_PRESENTATION_VERIFIER_ID,
    FiniteGaloisQuotient,
    FiniteGaloisQuotientReceipt,
    FiniteGroupExtension,
    FiniteGroupMap,
    finite_galois_quotient,
    finite_galois_quotient_certificate,
)
from .ideals import Ideal
from .kummer import KummerClass, KummerSpace, kummer_class, kummer_space
from .local import (
    LocalH1Class,
    LocalH1Space,
    LocalizationMap,
    decomposition_quotient_h1,
    local_h1,
    local_h1_class,
    localize,
)
from .modules import (
    GALOIS_MODULE_VERIFIER_ID,
    GaloisModule,
    GaloisModuleReceipt,
    galois_module,
)
from .places import FinitePlace, InfinitePlace, InfinitePlaceKind, Place
from .proof import (
    Completeness,
    ProofContext,
    Unsupported,
    VerificationRequirement,
    VerifierTrust,
)
from .twists import (
    NonabelianCocycle,
    TwistClass,
    TwistClassSet,
    nonabelian_h1,
    twist_classes,
)

__all__ = [
    "FINITE_QUOTIENT_VERIFIER_ID",
    "GALOIS_MODULE_VERIFIER_ID",
    "GALOIS_QUOTIENT_PRESENTATION_VERIFIER_ID",
    "ArithmeticCertificateError",
    "Completeness",
    "FieldEmbedding",
    "FiniteGaloisQuotient",
    "FiniteGaloisQuotientReceipt",
    "FiniteGroupExtension",
    "FiniteGroupMap",
    "FinitePlace",
    "GaloisModule",
    "GaloisModuleReceipt",
    "Ideal",
    "InfinitePlace",
    "InfinitePlaceKind",
    "KummerClass",
    "KummerReceipt",
    "KummerSpace",
    "LocalH1Class",
    "LocalH1Receipt",
    "LocalH1Space",
    "LocalizationMap",
    "LocalizationReceipt",
    "ModularIrreducibilityWitness",
    "NonabelianCocycle",
    "NumberField",
    "NumberFieldElement",
    "Place",
    "ProofContext",
    "RationalLike",
    "TwistClass",
    "TwistClassSet",
    "TwistReceipt",
    "Unsupported",
    "VerificationRequirement",
    "VerifierTrust",
    "decomposition_quotient_h1",
    "finite_galois_quotient",
    "finite_galois_quotient_certificate",
    "galois_module",
    "kummer_class",
    "kummer_space",
    "local_h1",
    "local_h1_class",
    "localize",
    "nonabelian_h1",
    "twist_classes",
]
