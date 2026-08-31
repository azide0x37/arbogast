"""Paper-ready LaTeX projection of claims and proof maps."""

from __future__ import annotations

from arbogast.claims import Claim, ClaimDomain, ClaimGraph, ClaimKind, FormalStatement
from arbogast.claims.statement import StatementError
from arbogast.formats import CLAIM_SCHEMA_V2
from arbogast.proof import ProofGap, ProofObligation

from ._domains import DomainFilter, domain_label, normalize_domains, select_claims
from ._lifting import claim_graph_for_export


def export_latex(value: object, *, domains: DomainFilter = None) -> str:
    selected_domains = normalize_domains(domains)
    if isinstance(value, ClaimGraph):
        return _claims_projection(value, selected_domains)
    if isinstance(value, Claim):
        if selected_domains is not None and value.domain not in selected_domains:
            return _empty_projection(selected_domains)
        return _claim(value)
    if isinstance(value, ProofGap):
        return _gap(value)
    if isinstance(value, ProofObligation):
        return _obligation(value)
    lifted = claim_graph_for_export(value)
    if lifted is not None:
        return _claims_projection(lifted, selected_domains)
    raise TypeError(f"LaTeX export does not support {type(value).__qualname__}")


def _claim(claim: Claim) -> str:
    if claim.domain is not ClaimDomain.MATHEMATICAL:
        return _nonmathematical_claim(claim)
    environment = "conjecture" if claim.kind is ClaimKind.CONJECTURED else "proposition"
    statement = _statement(claim.what)
    lines = [
        f"\\begin{{{environment}}}[{_escape(claim.id)}]",
    ]
    if claim.hypotheses:
        lines.extend(
            [
                "\\textbf{Hypotheses.}",
                "\\begin{enumerate}",
                *(f"\\item {_statement(item)}" for item in claim.hypotheses),
                "\\end{enumerate}",
                "\\textbf{Conclusion.}",
            ]
        )
    lines.extend([statement, f"\\end{{{environment}}}"])
    if claim.kind in {ClaimKind.COMPUTED, ClaimKind.DERIVED}:
        lines.extend(
            [
                "\\begin{quote}",
                "\\textbf{Recorded derivation (not replayed by this projection).} "
                + _derivation_text(claim),
                "\\end{quote}",
            ]
        )
    elif claim.kind is not ClaimKind.CONJECTURED:
        lines.append("\\emph{This structured record is not a proof of the displayed proposition.}")
    lines.extend(
        [
            "\\begin{quote}\\small",
            f"Claim kind: \\texttt{{{_escape(claim.kind.value)}}}; "
            f"status: \\texttt{{{_escape(claim.status.value)}}}.\\\\",
            "Evidence: "
            + (
                ", ".join(f"\\texttt{{{_escape(item.ref)}}}" for item in claim.evidence)
                or "none recorded"
            )
            + ".",
            "Source: "
            + (
                ", ".join(f"\\texttt{{{_escape(item)}}}" for item in claim.source)
                or "none recorded"
            )
            + ".",
            "This paper projection is not a replayable certificate bundle; use the JSON export "
            "for independent verification.",
            "\\end{quote}",
        ]
    )
    if claim.schema_version == CLAIM_SCHEMA_V2:
        lines.insert(-1, f"Domain: \\texttt{{{_escape(claim.domain.value)}}}.")
    if claim.formalization is not None:
        lines.extend(["", _gap(claim.formalization).rstrip()])
    return "\n".join(lines) + "\n"


def _claims_projection(
    graph: ClaimGraph,
    domains: frozenset[ClaimDomain] | None,
) -> str:
    claims = select_claims(graph, domains)
    if not claims:
        return _empty_projection(domains or frozenset())
    return "\n\n".join(_claim(claim).rstrip() for claim in claims) + "\n"


def _empty_projection(domains: frozenset[ClaimDomain]) -> str:
    return f"% No claims matched domain filter: {domain_label(domains)}.\n"


def _nonmathematical_claim(claim: Claim) -> str:
    evidence = (
        ", ".join(f"\\texttt{{{_escape(item.ref)}}}" for item in claim.evidence) or "none recorded"
    )
    sources = ", ".join(f"\\texttt{{{_escape(item)}}}" for item in claim.source) or "none recorded"
    lines = [
        "\\begin{quote}",
        f"\\textbf{{{_escape(claim.domain.value.title())} claim "
        f"\\texttt{{{_escape(claim.id)}}}.}}\\\\",
        _statement(claim.what),
    ]
    if claim.hypotheses:
        lines.extend(
            [
                "",
                "\\textbf{Recorded operational conditions (not theorem premises).}",
                "\\begin{itemize}",
                *(f"\\item {_statement(item)}" for item in claim.hypotheses),
                "\\end{itemize}",
            ]
        )
    lines.extend(
        [
            "",
            f"Claim kind: \\texttt{{{_escape(claim.kind.value)}}}; "
            f"status: \\texttt{{{_escape(claim.status.value)}}}.\\\\",
            "Recorded method: "
            + (_escape(claim.how.method) if claim.how is not None else "none recorded")
            + ".\\\\",
            f"Evidence: {evidence}.\\\\",
            f"Source: {sources}.\\\\",
            "This typed operational claim is not projected as a mathematical proposition.",
            "\\end{quote}",
        ]
    )
    return "\n".join(lines) + "\n"


def _derivation_text(claim: Claim) -> str:
    parts: list[str] = []
    if claim.hypotheses:
        parts.append("Assume the hypotheses displayed in the proposition.")
    if claim.why:
        refs = ", ".join(f"\\texttt{{{_escape(item.claim_id)}}}" for item in claim.why)
        parts.append(f"This follows from claims {refs}.")
    if claim.how is not None:
        parts.append(_escape(claim.how.method))
    if claim.source:
        refs = ", ".join(f"\\texttt{{{_escape(item)}}}" for item in claim.source)
        parts.append(f"Imported source propositions: {refs}.")
    return " ".join(parts) or "The structured claim record contains no derivation."


def _gap(gap: ProofGap) -> str:
    lines = [
        f"\\subsection*{{Proof gap for \\texttt{{{_escape(gap.claim_id)}}}}}",
        f"Formalization distance: {gap.distance.score}.",
        "\\begin{enumerate}",
    ]
    lines.extend(_obligation(item).rstrip() for item in gap.obligations)
    lines.append("\\end{enumerate}")
    return "\n".join(lines) + "\n"


def _obligation(obligation: ProofObligation) -> str:
    parts = [f"\\item[\\texttt{{{_escape(obligation.id)}}}] "]
    if obligation.context:
        hypotheses = "; ".join(_statement(item) for item in obligation.context)
        parts.append(f"\\textbf{{Context:}} {hypotheses}. ")
    parts.append(f"\\textbf{{Obligation:}} {_statement(obligation.statement)} ")
    parts.append(f"(\\texttt{{{_escape(obligation.classification.value)}}}).")
    if obligation.discharged_by:
        references = ", ".join(f"\\texttt{{{_escape(item)}}}" for item in obligation.discharged_by)
        parts.append(f" Discharged by {references}.")
    if obligation.dependencies:
        references = ", ".join(f"\\texttt{{{_escape(item)}}}" for item in obligation.dependencies)
        parts.append(f" Depends on {references}.")
    if obligation.evidence:
        references = ", ".join(f"\\texttt{{{_escape(item)}}}" for item in obligation.evidence)
        parts.append(f" Evidence: {references}.")
    if obligation.notes is not None:
        parts.append(f" Notes: {_escape(obligation.notes)}")
    return "".join(parts) + "\n"


def _escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _statement(statement: FormalStatement) -> str:
    """Render explicit LaTeX verbatim and escape backend-independent prose fallback."""

    try:
        return statement.render("latex", fallback=False)
    except StatementError:
        return _escape(statement.text)


__all__ = ["export_latex"]
