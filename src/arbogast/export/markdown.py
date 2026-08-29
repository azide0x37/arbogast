"""Deterministic paper- and agent-readable Markdown export."""

from __future__ import annotations

from arbogast.claims import Claim, ClaimGraph
from arbogast.proof import ProofGap, ProofObligation

from .json import export_json


def export_markdown(value: object) -> str:
    if isinstance(value, ClaimGraph):
        return _graph(value)
    if isinstance(value, Claim):
        return _claim(value, heading=1)
    if isinstance(value, ProofGap):
        return _gap(value)
    if isinstance(value, ProofObligation):
        return _obligation(value, heading=1)
    return f"```json\n{export_json(value, pretty=True).rstrip()}\n```\n"


def _graph(graph: ClaimGraph) -> str:
    title = graph.graph_id or "Mathematical Claim Graph"
    lines = [f"# {title}", "", f"Content ID: `{graph.digest}`", ""]
    holes = graph.theorem_holes()
    lines.extend(
        [
            f"Claims: {len(graph)}. External/open trust-base nodes: {len(holes)}.",
            "",
        ]
    )
    for claim in graph:
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
    if claim.hypotheses:
        lines.append(
            "- Hypotheses: " + "; ".join(item.render("markdown") for item in claim.hypotheses)
        )
    lines.append(
        "- Why: "
        + (", ".join(f"`{item.claim_id}`" for item in claim.why) if claim.why else "root claim")
    )
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
