"""Proof obligations, formalization gaps, and Lean theorem bridges."""

from .gap import FormalizationDistance, ProofGap, proof_gap
from .lean_bridge import (
    FormalizationStatus,
    LeanBridge,
    LeanBridgeRegistry,
    default_lean_bridges,
    lean_bridge,
)
from .obligations import ObligationClass, ProofObligation, ProofObligationError

__all__ = [
    "FormalizationDistance",
    "FormalizationStatus",
    "LeanBridge",
    "LeanBridgeRegistry",
    "ObligationClass",
    "ProofGap",
    "ProofObligation",
    "ProofObligationError",
    "default_lean_bridges",
    "lean_bridge",
    "proof_gap",
]
