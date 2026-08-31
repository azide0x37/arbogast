"""Compact agent context that preserves theorem boundaries and five-question records."""

from __future__ import annotations

from arbogast.claims import Claim, ClaimDomain, ClaimGraph, ClaimKind
from arbogast.formats import CLAIM_SCHEMA_V2
from arbogast.proof import ProofGap

from ._domains import DomainFilter, normalize_domains, select_claims
from ._lifting import claim_graph_for_export
from .json import export_json


def export_agent_context(
    value: object,
    *,
    pretty: bool = False,
    domains: DomainFilter = None,
) -> str:
    selected_domains = normalize_domains(domains)
    lifted = claim_graph_for_export(value)
    if lifted is not None:
        value = lifted
    payload: object
    if isinstance(value, ClaimGraph):
        claims = select_claims(value, selected_domains)
        context_v2 = selected_domains is not None or any(
            claim.schema_version == CLAIM_SCHEMA_V2 for claim in claims
        )
        context_payload: dict[str, object] = {
            "schema_version": (
                "arbogast.agent-claim-context/v2"
                if context_v2
                else "arbogast.agent-claim-context/v1"
            ),
            "graph_id": value.graph_id,
            "graph_digest": value.digest,
            "claims": tuple(_claim(item, include_domain=context_v2) for item in claims),
            "theorem_holes": tuple(
                item.id
                for item in claims
                if item.domain is ClaimDomain.MATHEMATICAL
                and item.kind in {ClaimKind.ASSUMED, ClaimKind.IMPORTED, ClaimKind.CONJECTURED}
            ),
        }
        if selected_domains is not None:
            context_payload["domain_filter"] = tuple(
                sorted(domain.value for domain in selected_domains)
            )
            context_payload["filtered_claim_count"] = len(value) - len(claims)
        payload = context_payload
    elif isinstance(value, Claim):
        claims = select_claims((value,), selected_domains)
        context_v2 = selected_domains is not None or value.schema_version == CLAIM_SCHEMA_V2
        context_payload = {
            "schema_version": (
                "arbogast.agent-claim-context/v2"
                if context_v2
                else "arbogast.agent-claim-context/v1"
            ),
            "claims": tuple(_claim(item, include_domain=context_v2) for item in claims),
        }
        if selected_domains is not None:
            context_payload["domain_filter"] = tuple(
                sorted(domain.value for domain in selected_domains)
            )
            context_payload["filtered_claim_count"] = 1 - len(claims)
        payload = context_payload
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


def _claim(claim: Claim, *, include_domain: bool) -> dict[str, object]:
    value: dict[str, object] = {
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
    if include_domain:
        value["domain"] = claim.domain.value
    return value


__all__ = ["export_agent_context"]
