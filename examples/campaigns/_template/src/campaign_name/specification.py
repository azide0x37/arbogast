"""Canonical data and names for the template campaign."""

from __future__ import annotations

from arbogast.campaign import CampaignSpec, Strategy, TargetSpec
from arbogast.claims import (
    ClaimKind,
    EpistemicStatus,
    FormalStatement,
    claim_boundary_hash,
)

CAMPAIGN_NAME = "arbogast-campaign-template"
OPERATION = "campaign-template.residue-square.v1"
VERIFIER = "campaign-template.residue-square.v1"
STRATEGY = "complete-residue-scan"
CAPABILITY = "small-exact-computations"
CLAIM_ID = "campaign-template.mod7.residue2.has-square-root"
MODULUS = 7
TARGET_RESIDUE = 2
RESULT_STATEMENT = FormalStatement("The residue 2 has a square root modulo 7.")
RESULT_STATEMENT_HASH = RESULT_STATEMENT.statement_hash
RESULT_BOUNDARY_HASH = claim_boundary_hash(
    CLAIM_ID,
    RESULT_STATEMENT,
    kind=ClaimKind.COMPUTED,
    status=EpistemicStatus.EXACT,
)


def target_spec() -> TargetSpec:
    """Return the exact finite teaching target."""

    return TargetSpec(
        "campaign-template.square-root",
        {"modulus": MODULUS, "target": TARGET_RESIDUE},
        label="Does 2 have a square root modulo 7?",
    )


def campaign_spec() -> CampaignSpec:
    """Return a portable campaign specification with no executable callables."""

    target = target_spec()
    strategy = Strategy(
        STRATEGY,
        OPERATION,
        "Exhaust the complete canonical residue domain and emit a finite certificate.",
        parameters={"modulus": MODULUS, "target_residue": TARGET_RESIDUE},
        capability_requirements=(CAPABILITY,),
        verify_results=True,
        usefulness=1,
        information_gain=1,
        estimated_cost=MODULUS,
    )
    return CampaignSpec(
        CAMPAIGN_NAME,
        objective="Certify whether 2 has a square root in the complete residue domain modulo 7.",
        targets=(target,),
        strategies=(strategy,),
        metadata={"scope": "finite template fixture"},
    )
