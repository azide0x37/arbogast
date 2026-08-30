"""Bounded certificate-first p-adic, reduction, lifting, and descent tools."""

from __future__ import annotations

from arbogast.cert import VerificationCertificate
from arbogast.claims import Claim, ClaimGraph

from .certificate import (
    FINITE_EXACT_VERIFIER,
    PORTABLE_TRUST,
    RECEIPT_SCHEMAS,
    THREE_POINT_EXACT_VERIFIER,
    PAdicReceipt,
    ReceiptClosure,
)
from .certificate import (
    verify_padic_receipt as _verify_padic_receipt,
)
from .covers import (
    BranchFiberWitness,
    BranchValue,
    DerivativeWitness,
    FiberFactor,
    FiniteFieldFactor,
    LocalFactorizationFragment,
    ProjectiveRationalPoint,
    RiemannHurwitzWitness,
    ThreePointCover,
    local_factorization_fragment,
)
from .descent import (
    AutomorphismTrivialityWitness,
    DescendedModel,
    DescentCocycle,
    DescentIsomorphism,
    RigidDescentWitness,
    RigidFixedLift,
    effective_descent,
)
from .errors import (
    PAdicCertificateError,
    PAdicError,
    PAdicResourceError,
    PAdicValidationError,
    PAdicVerificationError,
    UnsupportedPAdicOperation,
)
from .fields import (
    LocalFieldEmbedding,
    PAdicAutomorphism,
    PAdicBall,
    PAdicElement,
    PAdicField,
    PAdicFieldWitness,
    PAdicPrecisionRing,
    PAdicPresentationKind,
)
from .frobenius import (
    FrobeniusConvention,
    FrobeniusOperator,
    NewtonSegment,
    SlopeDecomposition,
    SlopeMultiplicity,
    SlopeProjector,
    ValuationInterval,
    frobenius,
    ordinary_part,
    slopes,
)
from .frontier import reduction_frontier
from .inertia import (
    FiniteInertiaQuotient,
    InertiaFiltration,
    InertiaRepresentation,
    inertia_action,
)
from .lifts import (
    FiniteLiftAction,
    FixedLift,
    FixedLiftSet,
    LiftCandidate,
    LiftChart,
    LiftEnumerationWitness,
    LiftGaloisAction,
    LiftSet,
    LiftTransportWitness,
    fixed_lifts,
    lift_galois_action,
    lift_set,
)
from .matrices import PAdicMatrix, PAdicMatrixError
from .modules import PAdicModule, PAdicSubmodule
from .reduction import (
    ComponentMapWitness,
    GoodReduction,
    GoodReductionWitness,
    MarkedReductionComponent,
    ReducedBranchFiber,
    ReducedFiberFactor,
    ReducedProjectivePoint,
    SemistableReduction,
    SemistableReductionWitness,
    SpecialFiberMarking,
    StableReduction,
    StableReductionWitness,
    good_reduction,
    semistable_reduction,
    stable_reduction,
)
from .results import (
    Certified,
    PAdicResult,
    Partial,
    ProofObligation,
    Unknown,
    Unsupported,
    certified_result,
)
from .semantic import (
    VERIFICATION_CHECKS,
    VERIFICATION_GUARANTEES,
    VERIFIER_NAMES,
)
from .semantic import (
    claim_for_result as _claim_for_result,
)
from .semantic import (
    claim_graph_for_result as _claim_graph_for_result,
)
from .semantic import (
    verification_certificate_for_result as _verification_certificate_for_result,
)
from .wewers import (
    DeformationDatum,
    DeformationDatumWitness,
    DeformationSignature,
    RationalDifferential,
    SpecialityWitness,
    deformation_datum,
)


def verification_certificate(result: object) -> VerificationCertificate:
    """Project one bounded p-adic result to its central certificate."""

    return _verification_certificate_for_result(result)


def claim(result: object) -> Claim:
    """Project one bounded p-adic result to its scope-preserving claim."""

    return _claim_for_result(result)


def claim_graph(result: object) -> ClaimGraph:
    """Project one bounded p-adic result to its dependency-closed claim graph."""

    return _claim_graph_for_result(result)


def verify_receipt(receipt: PAdicReceipt) -> tuple[str, ...]:
    """Replay one p-adic receipt through its fixed portable verifier family."""

    return _verify_padic_receipt(receipt)


__all__ = [
    "FINITE_EXACT_VERIFIER",
    "PORTABLE_TRUST",
    "RECEIPT_SCHEMAS",
    "THREE_POINT_EXACT_VERIFIER",
    "VERIFICATION_CHECKS",
    "VERIFICATION_GUARANTEES",
    "VERIFIER_NAMES",
    "AutomorphismTrivialityWitness",
    "BranchFiberWitness",
    "BranchValue",
    "Certified",
    "ComponentMapWitness",
    "DeformationDatum",
    "DeformationDatumWitness",
    "DeformationSignature",
    "DerivativeWitness",
    "DescendedModel",
    "DescentCocycle",
    "DescentIsomorphism",
    "FiberFactor",
    "FiniteFieldFactor",
    "FiniteInertiaQuotient",
    "FiniteLiftAction",
    "FixedLift",
    "FixedLiftSet",
    "FrobeniusConvention",
    "FrobeniusOperator",
    "GoodReduction",
    "GoodReductionWitness",
    "InertiaFiltration",
    "InertiaRepresentation",
    "LiftCandidate",
    "LiftChart",
    "LiftEnumerationWitness",
    "LiftGaloisAction",
    "LiftSet",
    "LiftTransportWitness",
    "LocalFactorizationFragment",
    "LocalFieldEmbedding",
    "MarkedReductionComponent",
    "NewtonSegment",
    "PAdicAutomorphism",
    "PAdicBall",
    "PAdicCertificateError",
    "PAdicElement",
    "PAdicError",
    "PAdicField",
    "PAdicFieldWitness",
    "PAdicMatrix",
    "PAdicMatrixError",
    "PAdicModule",
    "PAdicPrecisionRing",
    "PAdicPresentationKind",
    "PAdicReceipt",
    "PAdicResourceError",
    "PAdicResult",
    "PAdicSubmodule",
    "PAdicValidationError",
    "PAdicVerificationError",
    "Partial",
    "ProjectiveRationalPoint",
    "ProofObligation",
    "RationalDifferential",
    "ReceiptClosure",
    "ReducedBranchFiber",
    "ReducedFiberFactor",
    "ReducedProjectivePoint",
    "RiemannHurwitzWitness",
    "RigidDescentWitness",
    "RigidFixedLift",
    "SemistableReduction",
    "SemistableReductionWitness",
    "SlopeDecomposition",
    "SlopeMultiplicity",
    "SlopeProjector",
    "SpecialFiberMarking",
    "SpecialityWitness",
    "StableReduction",
    "StableReductionWitness",
    "ThreePointCover",
    "Unknown",
    "Unsupported",
    "UnsupportedPAdicOperation",
    "ValuationInterval",
    "certified_result",
    "claim",
    "claim_graph",
    "deformation_datum",
    "effective_descent",
    "fixed_lifts",
    "frobenius",
    "good_reduction",
    "inertia_action",
    "lift_galois_action",
    "lift_set",
    "local_factorization_fragment",
    "ordinary_part",
    "reduction_frontier",
    "semistable_reduction",
    "slopes",
    "stable_reduction",
    "verification_certificate",
    "verify_receipt",
]
