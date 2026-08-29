"""Compact agent context that preserves theorem boundaries and five-question records."""

from __future__ import annotations

from arbogast.claims import Claim, ClaimGraph
from arbogast.proof import ProofGap

from .json import export_json


def export_agent_context(value: object, *, pretty: bool = False) -> str:
    if isinstance(value, ClaimGraph):
        payload: object = {
            "schema_version": "arbogast.agent-claim-context/v1",
            "graph_id": value.graph_id,
            "graph_digest": value.digest,
            "claims": tuple(_claim(item) for item in value),
            "theorem_holes": tuple(item.id for item in value.theorem_holes()),
        }
    elif isinstance(value, Claim):
        payload = {
            "schema_version": "arbogast.agent-claim-context/v1",
            "claims": (_claim(value),),
        }
    elif isinstance(value, ProofGap):
        payload = {
            "schema_version": "arbogast.agent-proof-gap/v1",
            "claim_id": value.claim_id,
            "distance": value.distance,
            "obligations": value.obligations,
            "unresolved": value.unresolved,
            "blockers": value.blockers,
        }
    else:
        payload = value
    return export_json(payload, pretty=pretty)


def _claim(claim: Claim) -> dict[str, object]:
    return {
        "id": claim.id,
        "what": claim.what,
        "hypotheses": claim.hypotheses,
        "why": claim.dependency_ids,
        "how": claim.how,
        "evidence": claim.evidence,
        "source": claim.source,
        "kind": claim.kind.value,
        "status": claim.status.value,
        "novelty": claim.novelty,
        "formalization": claim.formalization,
        "metadata": claim.metadata,
    }


__all__ = ["export_agent_context"]
