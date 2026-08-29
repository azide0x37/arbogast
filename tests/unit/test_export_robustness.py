from __future__ import annotations

import pytest

from arbogast.claims import Claim, ClaimKind, EpistemicStatus, FormalStatement
from arbogast.export import export_latex, export_lean
from arbogast.proof import ObligationClass, ProofObligation


def test_latex_escapes_prose_fallback_but_preserves_explicit_rendering() -> None:
    claim = Claim(
        "claim.prose",
        statement="x_1 is 50% of the total & needs {care}",
        hypotheses=(
            "path\\name is literal prose",
            FormalStatement.create("explicit mathematics", renderings={"latex": r"x_1 \in M"}),
        ),
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
    )

    latex = export_latex(claim)

    assert r"x\_1 is 50\% of the total \& needs \{care\}" in latex
    assert r"path\textbackslash{}name is literal prose" in latex
    assert r"\item x_1 \in M" in latex


def test_latex_imported_claim_retains_source_reference() -> None:
    claim = Claim(
        "claim.imported",
        statement="P",
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.EXACT,
        source=("paper.theorem_1",),
    )

    latex = export_latex(claim)

    assert r"Source: \texttt{paper.theorem\_1}." in latex


def test_lean_strings_escape_all_ascii_control_characters() -> None:
    obligation = ProofObligation.create(
        "control.characters",
        "line\rreturn\ttab\vvertical\x00nul",
        ObligationClass.DECIDABLE,
        notes="note\rwith\ttabs\fand form feed\x7f",
    )

    lean = export_lean(obligation)

    assert 'statement := "line\\x0dreturn\\ttab\\x0bvertical\\x00nul"' in lean
    assert 'notes := some "note\\x0dwith\\ttabs\\x0cand form feed\\x7f"' in lean
    assert not any(character in lean for character in ("\r", "\t", "\v", "\f", "\x00", "\x7f"))


@pytest.mark.parametrize("namespace", ("namespace", "Arbogast.theorem", "end.Generated"))
def test_lean_rejects_keyword_namespace_components(namespace: str) -> None:
    with pytest.raises(ValueError, match="invalid Lean namespace"):
        export_lean({}, namespace=namespace)
