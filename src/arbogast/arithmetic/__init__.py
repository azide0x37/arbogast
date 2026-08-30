"""Certified finite arithmetic over pinned exact presentations."""

from arbogast.galois.proof import Completeness, ProofContext

from .aiming import AffineFamily, AimResult, LeftNullspaceObstruction, aim, unique
from .certificate import (
    AimCertificate,
    ArithmeticError,
    ArithmeticReceipt,
    ArithmeticVerificationError,
    DescentCertificate,
    DualSelmerCertificate,
    LocalConditionCertificate,
    LocalPairingCertificate,
    SelmerCertificate,
    UnsupportedArithmeticOperation,
)
from .conditions import LocalCondition, local_condition
from .descent import (
    DescentOutcome,
    KummerDescentProblem,
    Obstructed,
    Realized,
    Unknown,
    elementary_descent,
)
from .duality import (
    CartierDual,
    DualSelmerResult,
    LocalPairing,
    cartier_dual,
    dual_selmer,
    local_pairing,
)
from .selmer import SelmerGroup, SelmerKernel, SelmerProblem, selmer

__all__ = [
    "AffineFamily",
    "AimCertificate",
    "AimResult",
    "ArithmeticError",
    "ArithmeticReceipt",
    "ArithmeticVerificationError",
    "CartierDual",
    "Completeness",
    "DescentCertificate",
    "DescentOutcome",
    "DualSelmerCertificate",
    "DualSelmerResult",
    "KummerDescentProblem",
    "LeftNullspaceObstruction",
    "LocalCondition",
    "LocalConditionCertificate",
    "LocalPairing",
    "LocalPairingCertificate",
    "Obstructed",
    "ProofContext",
    "Realized",
    "SelmerCertificate",
    "SelmerGroup",
    "SelmerKernel",
    "SelmerProblem",
    "Unknown",
    "UnsupportedArithmeticOperation",
    "aim",
    "cartier_dual",
    "dual_selmer",
    "elementary_descent",
    "local_condition",
    "local_pairing",
    "selmer",
    "unique",
]
