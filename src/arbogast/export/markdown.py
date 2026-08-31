"""Deterministic paper- and agent-readable Markdown export."""

from __future__ import annotations

from arbogast.claims import Claim, ClaimDomain, ClaimGraph, ClaimKind
from arbogast.formats import CLAIM_SCHEMA_V2
from arbogast.proof import ProofGap, ProofObligation

from ._domains import DomainFilter, domain_label, normalize_domains, select_claims
from ._lifting import claim_graph_for_export
from .json import export_json


def export_markdown(value: object, *, domains: DomainFilter = None) -> str:
    selected_domains = normalize_domains(domains)
    if isinstance(value, ClaimGraph):
        return _graph(value, selected_domains)
    if isinstance(value, Claim):
        if selected_domains is not None and value.domain not in selected_domains:
            return _empty_projection(selected_domains)
        return _claim(value, heading=1)
    if isinstance(value, ProofGap):
        return _gap(value)
    if isinstance(value, ProofObligation):
        return _obligation(value, heading=1)
    lifted = claim_graph_for_export(value)
    if lifted is not None:
        return _graph(lifted, selected_domains)
    return f"```json\n{export_json(value, pretty=True).rstrip()}\n```\n"


def _graph(graph: ClaimGraph, domains: frozenset[ClaimDomain] | None) -> str:
    claims = select_claims(graph, domains)
    has_nonmathematical = any(claim.domain is not ClaimDomain.MATHEMATICAL for claim in graph)
    title = graph.graph_id or ("Claim Graph" if has_nonmathematical else "Mathematical Claim Graph")
    lines = [f"# {title}", "", f"Content ID: `{graph.digest}`", ""]
    holes = tuple(
        claim
        for claim in claims
        if claim.domain is ClaimDomain.MATHEMATICAL
        and claim.kind in {ClaimKind.ASSUMED, ClaimKind.IMPORTED, ClaimKind.CONJECTURED}
    )
    if domains is not None:
        lines.extend(
            [
                f"Domain projection: `{domain_label(domains)}`. Displayed claims: "
                f"{len(claims)} of {len(graph)}.",
                "",
            ]
        )
    lines.extend(
        [
            f"Claims: {len(claims)}. External/open trust-base nodes: {len(holes)}.",
            "",
        ]
    )
    for claim in claims:
        lines.append(_claim(claim, heading=2).rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _claim(claim: Claim, *, heading: int) -> str:
    prefix = "#" * heading
    lines = [
        f"{prefix} {claim.id}",
        "",
        claim.what.render("markdown"),
        "",
        f"- Kind: `{claim.kind.value}`",
        f"- Epistemic status: `{claim.status.value}`",
    ]
    if claim.schema_version == CLAIM_SCHEMA_V2:
        lines.append(f"- Domain: `{claim.domain.value}`")
    if claim.hypotheses:
        lines.append(
            "- Hypotheses: " + "; ".join(item.render("markdown") for item in claim.hypotheses)
        )
    if claim.why:
        dependency_text = ", ".join(f"`{item.claim_id}`" for item in claim.why)
    elif claim.domain is ClaimDomain.MATHEMATICAL:
        dependency_text = "root claim"
    else:
        dependency_text = "no theorem-DAG premises"
    lines.append("- Why: " + dependency_text)
    lines.append("- How: " + (claim.how.method if claim.how is not None else "not supplied"))
    lines.append(
        "- Evidence: "
        + (", ".join(f"`{item.ref}` ({item.kind.value})" for item in claim.evidence) or "none")
    )
    lines.append("- Source: " + (", ".join(f"`{item}`" for item in claim.source) or "none"))
    if claim.novelty is not None:
        lines.append(f"- Novelty: {claim.novelty.paper_wording}")
    if claim.formalization is not None:
        lines.extend(["", _gap(claim.formalization, heading=heading + 1).rstrip()])
    return "\n".join(lines) + "\n"


def _empty_projection(domains: frozenset[ClaimDomain]) -> str:
    return f"# Claim projection\n\nNo claims matched domains: `{domain_label(domains)}`.\n"


def _gap(gap: ProofGap, *, heading: int = 1) -> str:
    distance = gap.distance
    lines = [
        f"{'#' * heading} Proof gap: {gap.claim_id}",
        "",
        f"Formalization distance: **{distance.score}**",
        "",
        f"Total obligations: {len(gap.obligations)}; unresolved: {len(gap.unresolved)}; "
        f"blockers: {len(gap.blockers)}.",
        "",
    ]
    for obligation in gap.obligations:
        lines.append(_obligation(obligation, heading=heading + 1).rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _obligation(obligation: ProofObligation, *, heading: int) -> str:
    lines = [
        f"{'#' * heading} {obligation.id}",
        "",
        obligation.statement.render("markdown"),
        "",
        f"- Class: `{obligation.classification.value}`",
        f"- Discharged: `{'yes' if obligation.is_discharged else 'no'}`",
    ]
    if obligation.context:
        lines.append(
            "- Context: " + "; ".join(item.render("markdown") for item in obligation.context)
        )
    else:
        lines.append("- Context: none")
    lines.extend(
        [
            "- Dependencies: " + (", ".join(obligation.dependencies) or "none"),
            "- Evidence: " + (", ".join(obligation.evidence) or "none"),
            "- Discharged by: " + (", ".join(obligation.discharged_by) or "none"),
            "- Notes: " + (obligation.notes or "none"),
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = ["export_markdown"]
