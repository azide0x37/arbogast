"""Named claim helpers for the public Galois arithmetic result families."""

from __future__ import annotations

from arbogast.claims import Claim, ClaimGraph

from .certificate import KummerReceipt, LocalH1Receipt, LocalizationReceipt, TwistReceipt
from .semantic import claim_for, claim_graph_for


def claim_for_kummer(receipt: KummerReceipt) -> Claim:
    return claim_for(receipt)


def claim_for_local_h1(receipt: LocalH1Receipt) -> Claim:
    return claim_for(receipt)


def claim_for_localization(receipt: LocalizationReceipt) -> Claim:
    return claim_for(receipt)


def claim_for_twists(receipt: TwistReceipt) -> Claim:
    return claim_for(receipt)


def claim_graph_for_kummer(receipt: KummerReceipt) -> ClaimGraph:
    return claim_graph_for(receipt)


def claim_graph_for_local_h1(receipt: LocalH1Receipt) -> ClaimGraph:
    return claim_graph_for(receipt)


def claim_graph_for_localization(receipt: LocalizationReceipt) -> ClaimGraph:
    return claim_graph_for(receipt)


def claim_graph_for_twists(receipt: TwistReceipt) -> ClaimGraph:
    return claim_graph_for(receipt)


__all__ = [
    "claim_for_kummer",
    "claim_for_local_h1",
    "claim_for_localization",
    "claim_for_twists",
    "claim_graph_for_kummer",
    "claim_graph_for_local_h1",
    "claim_graph_for_localization",
    "claim_graph_for_twists",
]
