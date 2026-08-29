from __future__ import annotations

import json

import pytest

from arbogast.cert import VerificationCertificate
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
    claim_boundary_hash,
)
from arbogast.export import (
    export_agent_context,
    export_json,
    export_latex,
    export_lean,
    export_markdown,
)
from arbogast.formats import loads
from arbogast.proof import ObligationClass, ProofGap, ProofObligation


def _claim() -> Claim:
    statement = FormalStatement.create(
        "The invariant dimension is one.",
        renderings={
            "latex": r"\(\dim M^G = 1\).",
            "lean": "invariantDimension = 1",
        },
    )
    certificate = VerificationCertificate.create(
        "dimension witness",
        "tests.dimension",
        claim_id="claim.dimension",
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            "claim.dimension",
            statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        witness={"dimension": 1},
    )
    return Claim(
        "claim.dimension",
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("cohom.h0"),
        certificate=certificate,
    )


@pytest.mark.parametrize("sign", [1, -1])
def test_pretty_json_preserves_arbitrarily_large_exact_integers(sign: int) -> None:
    huge = sign * (10**5000 + 12345)
    value = {"nested": [huge, {"again": huge}], "truth": True}

    compact = export_json(value)
    pretty = export_json(value, pretty=True)

    assert pretty.endswith("\n")
    assert loads(pretty) == value
    assert export_json(loads(pretty)) == compact


def test_claim_exports_preserve_boundaries_and_are_deterministic() -> None:
    claim = _claim()
    graph = ClaimGraph((claim,), graph_id="example")
    encoded = export_json(graph)
    assert encoded == export_json(graph)
    payload = json.loads(encoded)
    assert payload["claims"][0]["kind"] == "computed"

    latex = export_latex(graph)
    assert r"\begin{proposition}" in latex
    assert "status: \\texttt{exact}" in latex
    lean = export_lean(graph)
    assert "axiom claim_claim_dimension : invariantDimension = 1" in lean
    agent = json.loads(export_agent_context(graph))
    assert agent["claims"][0]["what"]["text"] == "The invariant dimension is one."
    restored = Claim.from_dict(json.loads(claim.export("json")))
    assert restored.to_dict() == claim.to_dict()


def test_lean_proof_gap_exports_data_and_only_explicit_formulas() -> None:
    formal = ProofObligation.create(
        "finite.check",
        FormalStatement.create("one equals one", renderings={"lean": "(1 : Nat) = 1"}),
        ObligationClass.DECIDABLE,
    )
    prose = ProofObligation.create(
        "external.theorem",
        "A theorem from the literature",
        ObligationClass.EXTERNAL_THEOREM,
    )
    lean = export_lean(ProofGap("claim.example", (formal, prose)))
    assert "axiom obligation_finite_check : (1 : Nat) = 1" in lean
    assert "axiom obligation_external_theorem" not in lean
    assert 'classification := "external_theorem"' in lean


def test_lean_and_latex_exports_preserve_conditions_and_discharge_metadata() -> None:
    hypothesis = FormalStatement.create(
        "P is assumed.",
        renderings={"latex": "P", "lean": "P"},
    )
    conclusion = FormalStatement.create(
        "Q follows.",
        renderings={"latex": "Q", "lean": "Q"},
    )
    obligation = ProofObligation.create(
        "conditional.step",
        conclusion,
        ObligationClass.CERTIFICATE,
        context=(hypothesis,),
        evidence=("sha256:" + "1" * 64,),
        discharged_by=("checker.p-implies-q",),
        notes="Replay the finite implication witness.",
    )
    lean_obligation = export_lean(obligation)
    assert 'context := ["P is assumed."]' in lean_obligation
    assert 'dischargedBy := ["checker.p-implies-q"]' in lean_obligation
    assert 'notes := some "Replay the finite implication witness."' in lean_obligation
    assert "axiom obligation_conditional_step : (P) → (Q)" in lean_obligation

    certificate = VerificationCertificate.create(
        "conditional claim witness",
        "tests.conditional",
        claim_id="claim.conditional",
        statement_hash=conclusion.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            "claim.conditional",
            conclusion,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.CONDITIONAL,
            hypotheses=(hypothesis,),
        ),
        witness={"under": "P"},
    )
    claim = Claim(
        "claim.conditional",
        statement=conclusion,
        hypotheses=(hypothesis,),
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.CONDITIONAL,
        how=Derivation.computation("tests.conditional"),
        certificate=certificate,
        metadata={"campaign_id": "campaign.example"},
    )
    lean_claim = export_lean(claim)
    assert 'def claimHypotheses_claim_conditional : List String := ["P is assumed."]' in lean_claim
    assert "axiom claim_claim_conditional : (P) → (Q)" in lean_claim

    latex = export_latex(claim)
    assert r"\textbf{Hypotheses.}" in latex
    assert latex.index(r"\item P") < latex.index(r"\textbf{Conclusion.}")
    assert r"\begin{proof}" not in latex
    assert "Recorded derivation (not replayed by this projection)." in latex
    assert "Assume the hypotheses displayed in the proposition." in latex

    agent_claim = json.loads(export_agent_context(claim))["claims"][0]
    assert agent_claim["hypotheses"][0]["renderings"]["lean"] == "P"
    assert agent_claim["metadata"] == {"campaign_id": "campaign.example"}

    markdown = export_markdown(obligation)
    assert "- Context: P is assumed." in markdown
    assert "- Evidence: sha256:" in markdown
    assert "- Discharged by: checker.p-implies-q" in markdown
    assert "- Notes: Replay the finite implication witness." in markdown
    latex_obligation = export_latex(obligation)
    assert "Evidence: \\texttt{sha256:" in latex_obligation
    assert "Notes: Replay the finite implication witness." in latex_obligation
    agent_gap = json.loads(export_agent_context(ProofGap("claim.obligation", (obligation,))))
    assert agent_gap["obligations"][0]["notes"] == "Replay the finite implication witness."


def test_lean_omits_axiom_when_a_condition_has_no_explicit_rendering() -> None:
    conclusion = FormalStatement.create("Q", renderings={"lean": "Q"})
    prose_only = FormalStatement("A prose-only condition")
    obligation = ProofObligation.create(
        "unformalized.context",
        conclusion,
        ObligationClass.OPEN,
        context=(prose_only,),
    )

    lean = export_lean(obligation)

    assert 'context := ["A prose-only condition"]' in lean
    assert "axiom obligation_unformalized_context" not in lean
    assert "context statement has no explicit Lean rendering" in lean


def test_exports_do_not_imply_imported_proofs_or_emit_colliding_lean_names() -> None:
    imported = Claim(
        "claim.imported",
        statement=FormalStatement.create("P", renderings={"latex": "P", "lean": "P"}),
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.EXACT,
        source=("paper.theorem",),
    )
    latex = export_latex(imported)
    assert r"\begin{proof}" not in latex
    assert "not a proof" in latex

    left = Claim(
        "claim.a-b",
        statement=FormalStatement.create("P", renderings={"lean": "P"}),
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
    )
    right = Claim(
        "claim.a/b",
        statement=FormalStatement.create("Q", renderings={"lean": "Q"}),
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
    )
    with pytest.raises(ValueError, match="duplicate Lean name"):
        export_lean(ClaimGraph((left, right)))


def test_latex_never_promotes_an_unreplayed_derivation_to_a_proof() -> None:
    claim = Claim(
        "claim.unreplayed",
        statement="An exact-looking statement.",
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("demo.unknown"),
        evidence=("artifact:unverified",),
    )
    assert not claim.verify(raise_on_failure=False).verified

    latex = export_latex(claim)

    assert r"\begin{proof}" not in latex
    assert "Recorded derivation (not replayed by this projection)." in latex


def test_claim_graph_exports_bound_formalization_without_local_id_collisions() -> None:
    obligation = ProofObligation.create(
        "finite.check",
        FormalStatement.create("P", renderings={"lean": "P", "latex": "P"}),
        ObligationClass.DECIDABLE,
    )
    claims = tuple(
        Claim(
            claim_id,
            statement=FormalStatement.create(
                f"Conclusion {claim_id}",
                renderings={"lean": proposition, "latex": proposition},
            ),
            kind=ClaimKind.CONJECTURED,
            status=EpistemicStatus.UNKNOWN,
            formalization=ProofGap(claim_id, (obligation,)),
        )
        for claim_id, proposition in (("claim.left", "L"), ("claim.right", "R"))
    )
    graph = ClaimGraph(claims)

    lean = export_lean(graph)
    assert 'id := "owned/10:claim.left/finite.check"' in lean
    assert 'id := "owned/11:claim.right/finite.check"' in lean
    assert "axiom obligation_owned_10_claim_left_finite_check : P" in lean
    agent = json.loads(export_agent_context(graph))
    assert agent["claims"][0]["formalization"]["claim_id"] == "claim.left"
    latex = export_latex(graph)
    assert "Proof gap for" in latex


def test_claim_owned_lean_obligation_ids_are_injective_across_slashes() -> None:
    left = Claim(
        "claim/a",
        statement="L",
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
        formalization=ProofGap(
            "claim/a",
            (
                ProofObligation.create(
                    "b",
                    FormalStatement.create("P", renderings={"lean": "P"}),
                    ObligationClass.OPEN,
                ),
            ),
        ),
    )
    right = Claim(
        "claim",
        statement="R",
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
        formalization=ProofGap(
            "claim",
            (
                ProofObligation.create(
                    "a/b",
                    FormalStatement.create("Q", renderings={"lean": "Q"}),
                    ObligationClass.OPEN,
                ),
            ),
        ),
    )

    lean = export_lean(ClaimGraph((left, right)))

    assert lean.count('id := "owned/7:claim/a/b"') == 1
    assert lean.count('id := "owned/5:claim/a/b"') == 1
    axiom_names = [
        line.split(" :", 1)[0] for line in lean.splitlines() if line.startswith("axiom ")
    ]
    assert len(axiom_names) == len(set(axiom_names))
