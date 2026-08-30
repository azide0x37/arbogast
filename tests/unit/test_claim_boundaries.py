from __future__ import annotations

import json

import pytest

from arbogast.cert import (
    CertificateRef,
    ClaimBinding,
    TheoremCertificate,
    VerificationCertificate,
    VerifierRegistry,
)
from arbogast.claims import (
    Certified,
    Claim,
    ClaimError,
    ClaimGraph,
    ClaimKind,
    ClaimVerificationError,
    Conditional,
    Derivation,
    DerivationKind,
    EpistemicBoundaryError,
    EpistemicStatus,
    EvidenceRef,
    Exact,
    FormalStatement,
    Numerical,
    claim_boundary_hash,
    epistemic_from_dict,
    require_certified,
    require_exact,
)
from arbogast.proof import ObligationClass, ProofGap, ProofObligation
from arbogast.sources import Reference, SourceDocument, SourceError, SourceRegistry


def _bound_claim(
    *,
    claim_id: str = "claim.exact",
    text: str = "1 = 1",
) -> tuple[Claim, VerificationCertificate, VerifierRegistry]:
    statement = FormalStatement.create(
        text,
        renderings={"lean": "(1 : Nat) = 1", "latex": "$1=1$"},
    )
    certificate = VerificationCertificate.create(
        "unit exact arithmetic",
        "tests.exact.v1",
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id,
            statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        witness={"lhs": 1, "rhs": 1},
    )
    registry = VerifierRegistry()
    registry.register(
        "tests.exact.v1",
        VerificationCertificate,
        lambda item: item.witness["lhs"] == item.witness["rhs"],
    )
    claim = Claim(
        claim_id,
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("tests.integer_equality"),
        certificate=certificate,
    )
    return claim, certificate, registry


def test_epistemic_wrappers_never_coerce_upward() -> None:
    exact = Exact(3)
    certified = Certified(3, ("sha256:" + "1" * 64,))
    assert require_exact(exact) == 3
    assert require_certified(certified) == 3
    with pytest.raises(EpistemicBoundaryError):
        require_exact(certified)
    with pytest.raises(EpistemicBoundaryError):
        require_certified(exact)
    with pytest.raises(ValueError):
        Conditional(3, ())
    with pytest.raises(ValueError):
        Numerical(3.0)


def test_computed_kind_is_never_inferred_or_unbacked() -> None:
    with pytest.raises(TypeError):
        Claim(  # type: ignore[call-arg]
            "claim.missing-kind",
            statement="x = x",
            status=EpistemicStatus.EXACT,
        )
    with pytest.raises(ClaimError, match="computation derivation"):
        Claim(
            "claim.unbacked",
            statement="x = x",
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
            evidence=("artifact:stdout",),
        )
    with pytest.raises(ClaimError, match="evidence"):
        Claim(
            "claim.unbacked",
            statement="x = x",
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
            how=Derivation.computation("tests.fake"),
        )

    payload = {
        "schema_version": Claim.schema_version,
        "id": "claim.missing-kind",
        "what": {"text": "x = x", "language": "mathematics", "renderings": {}, "parameters": {}},
        "status": "unknown",
        "why": [],
        "how": None,
        "evidence": [],
        "source": [],
        "hypotheses": [],
        "novelty": None,
        "metadata": {},
    }
    with pytest.raises(ClaimError, match="kind is required"):
        Claim.from_dict(payload)


def test_bound_computed_claim_replays_and_round_trips() -> None:
    claim, _, registry = _bound_claim()
    assert claim.verify(verifier_registry=registry).verified
    transport = claim.to_dict()
    json.dumps(transport)
    restored = Claim.from_dict(transport)
    assert restored.digest == claim.digest
    assert restored.verify(verifier_registry=registry).verified


def test_supporting_certificates_are_reachable_but_not_direct_evidence() -> None:
    statement = FormalStatement("A nested finite verification succeeds")
    leaf = VerificationCertificate.create("leaf", "tests.support.leaf")
    middle = VerificationCertificate.create(
        "middle",
        "tests.support.middle",
        dependencies=(CertificateRef.from_certificate(leaf),),
    )
    outer = VerificationCertificate.create(
        "outer",
        "tests.support.outer",
        claim_id="claim.nested-support",
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            "claim.nested-support",
            statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        dependencies=(CertificateRef.from_certificate(middle),),
    )
    registry = VerifierRegistry()
    for verifier_name in (
        "tests.support.leaf",
        "tests.support.middle",
        "tests.support.outer",
    ):
        registry.register(
            verifier_name,
            VerificationCertificate,
            lambda certificate: True,
        )
    claim = Claim(
        "claim.nested-support",
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("tests.nested_support"),
        certificate=outer,
        supporting_certificates=(middle, leaf),
    )

    assert tuple(item.ref for item in claim.evidence) == (outer.certificate_id,)
    assert claim.verify(verifier_registry=registry).verified
    assert ClaimGraph((claim,)).verify(verifier_registry=registry).verified
    restored = Claim.from_dict(claim.to_dict())
    assert restored.verify(verifier_registry=registry).verified
    permuted = Claim(
        "claim.nested-support",
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("tests.nested_support"),
        certificate=outer,
        supporting_certificates=(leaf, middle),
    )
    assert permuted.to_dict() == claim.to_dict()

    partial = Claim(
        "claim.nested-support",
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("tests.nested_support"),
        certificate=outer,
        supporting_certificates=(middle,),
    )
    with pytest.raises(ClaimVerificationError, match="unresolved verification"):
        partial.verify(verifier_registry=registry)
    assert partial.verify(
        {leaf.certificate_id: leaf},
        verifier_registry=registry,
    ).verified

    foreign = VerificationCertificate.create("foreign", "tests.support.foreign")
    with pytest.raises(ClaimError, match="not reachable"):
        Claim(
            "claim.nested-support",
            statement=statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
            how=Derivation.computation("tests.nested_support"),
            certificate=outer,
            supporting_certificates=(middle, foreign),
        )
    with pytest.raises(ClaimError, match="unique content IDs"):
        Claim(
            "claim.nested-support",
            statement=statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
            how=Derivation.computation("tests.nested_support"),
            certificate=outer,
            supporting_certificates=(middle, middle),
        )

    wrong_schema = VerificationCertificate.create(
        "wrong-schema-root",
        "tests.support.outer",
        claim_id="claim.nested-support",
        statement_hash=statement.statement_hash,
        claim_boundary_hash=outer.claim_boundary_hash,
        dependencies=(
            CertificateRef(
                middle.certificate_id,
                middle.layer,
                "arbogast.cert.verification/foreign",
            ),
        ),
    )
    with pytest.raises(ClaimError, match="schema mismatch"):
        Claim(
            "claim.nested-support",
            statement=statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
            how=Derivation.computation("tests.nested_support"),
            certificate=wrong_schema,
            supporting_certificates=(middle,),
        )

    tampered = claim.to_dict()
    attached = tampered["attached_certificates"]
    assert isinstance(attached, list)
    attached[-1] = foreign.to_dict()
    with pytest.raises(ClaimError, match="not reachable"):
        Claim.from_dict(tampered)


def test_bound_certificate_rejects_hypothesis_and_status_mutation() -> None:
    claim, certificate, registry = _bound_claim()
    altered_hypotheses = Claim(
        claim.id,
        statement=claim.what,
        hypotheses=("An additional unproved hypothesis.",),
        kind=claim.kind,
        status=claim.status,
        how=claim.how,
        certificate=certificate,
    )
    with pytest.raises(ClaimVerificationError, match="claim boundary hash mismatch"):
        altered_hypotheses.verify(verifier_registry=registry)

    altered_status = Claim(
        claim.id,
        statement=claim.what,
        kind=claim.kind,
        status=EpistemicStatus.CERTIFIED,
        how=claim.how,
        certificate=certificate,
    )
    with pytest.raises(ClaimVerificationError, match="claim boundary hash mismatch"):
        altered_status.verify(verifier_registry=registry)

    assumed_boundary = claim_boundary_hash(
        claim.id,
        claim.what,
        kind=ClaimKind.ASSUMED,
        status=EpistemicStatus.UNKNOWN,
    )
    computed_boundary = claim_boundary_hash(
        claim.id,
        claim.what,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.UNKNOWN,
    )
    assert assumed_boundary != computed_boundary


def test_theorem_rejects_same_id_dependency_semantic_substitution() -> None:
    original, _, _ = _bound_claim(claim_id="claim.premise", text="P")
    substituted, _, registry = _bound_claim(claim_id="claim.premise", text="not P")
    support = VerificationCertificate.create("inference support", "tests.support")
    registry.register("tests.support", VerificationCertificate, lambda item: True)
    registry.register("tests.inference", TheoremCertificate, lambda item: True)
    conclusion = FormalStatement("Q")
    theorem = TheoremCertificate.create(
        "claim.conclusion",
        conclusion.statement_hash,
        (CertificateRef.from_certificate(support),),
        claim_boundary_hash=claim_boundary_hash(
            "claim.conclusion",
            conclusion,
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            dependency_ids=(original.id,),
        ),
        verifier="tests.inference",
        dependencies=(original.id,),
        claim_dependencies=(original.binding,),
    )
    derived = Claim(
        "claim.conclusion",
        statement=conclusion,
        kind=ClaimKind.DERIVED,
        status=EpistemicStatus.EXACT,
        why=(substituted.id,),
        how=Derivation(DerivationKind.INFERENCE, "P implies Q"),
        evidence=(support,),
        certificate=theorem,
    )

    with pytest.raises(ClaimVerificationError, match="dependency bindings"):
        ClaimGraph((substituted, derived)).verify(verifier_registry=registry)


def test_computed_claim_cannot_erase_dependency_status() -> None:
    sources = SourceRegistry()
    sources.register_document(SourceDocument("paper", "A conditional theorem"))
    sources.register_reference(
        Reference.create(
            "paper.conditional",
            "paper",
            "P",
            theorem_id="Theorem 1",
            imported_as=("claim.conditional",),
        )
    )
    dependency = Claim(
        "claim.conditional",
        statement="P",
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.CONDITIONAL,
        source=("paper.conditional",),
    )
    conclusion = FormalStatement("A finite computation under P returns Q")
    certificate = VerificationCertificate.create(
        conclusion.text,
        "tests.dependent-computation",
        claim_id="claim.computed",
        statement_hash=conclusion.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            "claim.computed",
            conclusion,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
            dependency_ids=(dependency.id,),
        ),
        claim_dependencies=(dependency.binding,),
    )
    computed = Claim(
        "claim.computed",
        statement=conclusion,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        why=(dependency.id,),
        how=Derivation.computation("tests.dependent-computation"),
        certificate=certificate,
    )
    registry = VerifierRegistry()
    registry.register(
        "tests.dependent-computation",
        VerificationCertificate,
        lambda item: True,
    )

    with pytest.raises(ClaimVerificationError, match="conditional status"):
        ClaimGraph((dependency, computed)).verify(
            verifier_registry=registry,
            source_registry=sources,
        )


def test_claim_formalization_is_bound_canonical_and_not_a_math_promotion() -> None:
    base, certificate, registry = _bound_claim()
    obligation = ProofObligation.create(
        "lean.bridge",
        "Formalize the verified finite checker in Lean.",
        ObligationClass.OPEN,
    )
    gap = ProofGap(base.id, (obligation,), analytic_dependencies=1)
    claim = Claim(
        base.id,
        statement=base.what,
        kind=base.kind,
        status=base.status,
        how=base.how,
        certificate=certificate,
        formalization=gap,
    )

    # An open formalization frontier does not weaken or strengthen certificate replay.
    assert claim.verify(verifier_registry=registry).verified
    assert claim.digest != base.digest
    restored = Claim.from_dict(claim.to_dict())
    assert restored == claim
    assert restored.formalization == gap

    rebound = claim.to_dict()
    assert isinstance(rebound["formalization"], dict)
    rebound["formalization"]["claim_id"] = "claim.someone-else"
    with pytest.raises(ClaimError, match="different claim"):
        Claim.from_dict(rebound)

    tampered = claim.to_dict()
    assert isinstance(tampered["formalization"], dict)
    assert isinstance(tampered["formalization"]["distance"], dict)
    tampered["formalization"]["distance"]["score"] = 0
    with pytest.raises(ClaimError, match="distance does not match"):
        Claim.from_dict(tampered)


def test_claim_rejects_foreign_or_untyped_formalization() -> None:
    foreign = ProofGap("claim.foreign", ())
    with pytest.raises(ClaimError, match="different claim"):
        Claim(
            "claim.local",
            statement="P",
            kind=ClaimKind.CONJECTURED,
            status=EpistemicStatus.UNKNOWN,
            formalization=foreign,
        )
    with pytest.raises(ClaimError, match="ProofGap"):
        Claim(
            "claim.local",
            statement="P",
            kind=ClaimKind.CONJECTURED,
            status=EpistemicStatus.UNKNOWN,
            formalization={"claim_id": "claim.local"},  # type: ignore[arg-type]
        )


def test_unresolved_or_unrelated_certificate_fails_closed() -> None:
    claim, certificate, registry = _bound_claim()
    detached = Claim(
        claim.id,
        statement=claim.statement,
        kind=claim.kind,
        status=claim.status,
        how=claim.how,
        evidence=claim.evidence,
    )
    with pytest.raises(ClaimVerificationError, match="unresolved certificate"):
        detached.verify(verifier_registry=registry)

    wrong_statement = FormalStatement("0 = 1")
    unrelated = VerificationCertificate.create(
        "valid but unrelated evidence",
        "tests.exact.v1",
        claim_id=claim.id,
        statement_hash=wrong_statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim.id,
            wrong_statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        witness={"lhs": 1, "rhs": 1},
    )
    wrongly_bound = Claim(
        claim.id,
        statement=claim.statement,
        kind=claim.kind,
        status=claim.status,
        how=claim.how,
        certificate=unrelated,
    )
    with pytest.raises(ClaimVerificationError, match="statement hash mismatch"):
        wrongly_bound.verify(verifier_registry=registry)

    with pytest.raises(ClaimVerificationError, match="resolver key"):
        detached.verify(
            {certificate.certificate_id: unrelated},
            verifier_registry=registry,
        )


def test_imported_claim_is_bound_to_exact_source_proposition_and_id() -> None:
    sources = SourceRegistry()
    sources.register_document(SourceDocument("paper", "A. Author, A theorem"))
    sources.register_reference(
        Reference.create(
            "paper.thm1",
            "paper",
            "A",
            theorem_id="Theorem 1",
            imported_as=("claim.a",),
        )
    )
    good = Claim(
        "claim.a",
        statement="A",
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.CONDITIONAL,
        source=("paper.thm1",),
    )
    assert good.verify(source_registry=sources).verified

    contradiction = Claim(
        "claim.a",
        statement="not A",
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.CONDITIONAL,
        source=("paper.thm1",),
    )
    with pytest.raises(ClaimVerificationError, match="different proposition"):
        contradiction.verify(source_registry=sources)

    wrong_id = Claim(
        "claim.other",
        statement="A",
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.CONDITIONAL,
        source=("paper.thm1",),
    )
    with pytest.raises(ClaimVerificationError, match="not bound"):
        wrong_id.verify(source_registry=sources)


def test_derived_claim_requires_replayable_entailment_evidence() -> None:
    with pytest.raises(ClaimError, match="replayable certificate"):
        Claim(
            "claim.false",
            statement="1 = 0",
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            why=("claim.true",),
            how=Derivation(DerivationKind.INFERENCE, "because I said so"),
        )

    support = VerificationCertificate.create("support", "tests.support")
    false_statement = FormalStatement("1 = 0")
    true_statement = FormalStatement("1 = 1")
    true_binding = ClaimBinding(
        "claim.true",
        true_statement.statement_hash,
        claim_boundary_hash(
            "claim.true",
            true_statement,
            kind=ClaimKind.IMPORTED,
            status=EpistemicStatus.EXACT,
        ),
    )
    theorem = TheoremCertificate.create(
        "claim.false",
        false_statement.statement_hash,
        (CertificateRef.from_certificate(support),),
        claim_boundary_hash=claim_boundary_hash(
            "claim.false",
            false_statement,
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            dependency_ids=("claim.true",),
        ),
        verifier="tests.inference",
        dependencies=("claim.true",),
        claim_dependencies=(true_binding,),
    )
    with pytest.raises(ClaimError, match="inference derivation"):
        Claim(
            "claim.false",
            statement="1 = 0",
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            why=("claim.true",),
            how=Derivation.computation("not-an-inference"),
            certificate=theorem,
        )


def test_derived_claim_binds_graph_dependencies_and_conditional_status() -> None:
    premise, premise_certificate, registry = _bound_claim(claim_id="claim.premise", text="P")
    support = VerificationCertificate.create("inference support", "tests.support")
    registry.register("tests.support", VerificationCertificate, lambda item: True)
    registry.register("tests.inference", TheoremCertificate, lambda item: True)

    conclusion = FormalStatement("Q")
    wrong_dependency_statement = FormalStatement("not P")
    wrong_dependency_binding = ClaimBinding(
        "claim.not-premise",
        wrong_dependency_statement.statement_hash,
        claim_boundary_hash(
            "claim.not-premise",
            wrong_dependency_statement,
            kind=ClaimKind.IMPORTED,
            status=EpistemicStatus.EXACT,
        ),
    )
    mismatched = TheoremCertificate.create(
        "claim.conclusion",
        conclusion.statement_hash,
        (CertificateRef.from_certificate(support),),
        claim_boundary_hash=claim_boundary_hash(
            "claim.conclusion",
            conclusion,
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            dependency_ids=("claim.not-premise",),
        ),
        verifier="tests.inference",
        dependencies=("claim.not-premise",),
        claim_dependencies=(wrong_dependency_binding,),
    )
    derived = Claim(
        "claim.conclusion",
        statement=conclusion,
        kind=ClaimKind.DERIVED,
        status=EpistemicStatus.EXACT,
        why=(premise.id,),
        how=Derivation(DerivationKind.INFERENCE, "certified implication"),
        certificate=mismatched,
    )
    with pytest.raises(ClaimVerificationError, match="dependency IDs do not match"):
        ClaimGraph((premise, derived)).verify(
            {
                premise_certificate.certificate_id: premise_certificate,
                support.certificate_id: support,
            },
            verifier_registry=registry,
        )

    sources = SourceRegistry()
    sources.register_document(SourceDocument("paper", "A conditional theorem"))
    sources.register_reference(
        Reference.create(
            "paper.conditional",
            "paper",
            "P",
            theorem_id="Theorem 1",
            imported_as=(
                "claim.imported",
                "claim.imported_exact",
                "claim.imported_numerical",
                "claim.imported_heuristic",
            ),
        )
    )
    imported = Claim(
        "claim.imported",
        statement="P",
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.CONDITIONAL,
        source=("paper.conditional",),
    )
    promoted_theorem = TheoremCertificate.create(
        "claim.promoted",
        conclusion.statement_hash,
        (CertificateRef.from_certificate(support),),
        claim_boundary_hash=claim_boundary_hash(
            "claim.promoted",
            conclusion,
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            dependency_ids=(imported.id,),
        ),
        verifier="tests.inference",
        dependencies=(imported.id,),
        claim_dependencies=(imported.binding,),
    )
    promoted = Claim(
        "claim.promoted",
        statement=conclusion,
        kind=ClaimKind.DERIVED,
        status=EpistemicStatus.EXACT,
        why=(imported.id,),
        how=Derivation(DerivationKind.INFERENCE, "uses the imported theorem"),
        certificate=promoted_theorem,
    )
    with pytest.raises(ClaimVerificationError, match="conditional status"):
        ClaimGraph((imported, promoted)).verify(
            {support.certificate_id: support},
            verifier_registry=registry,
            source_registry=sources,
        )

    imported_exact = Claim(
        "claim.imported_exact",
        statement="P",
        kind=ClaimKind.IMPORTED,
        status=EpistemicStatus.EXACT,
        source=("paper.conditional",),
    )
    exact_theorem = TheoremCertificate.create(
        "claim.exact_conclusion",
        conclusion.statement_hash,
        (CertificateRef.from_certificate(support),),
        claim_boundary_hash=claim_boundary_hash(
            "claim.exact_conclusion",
            conclusion,
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            dependency_ids=(imported_exact.id,),
        ),
        verifier="tests.inference",
        dependencies=(imported_exact.id,),
        claim_dependencies=(imported_exact.binding,),
    )
    exact_conclusion = Claim(
        "claim.exact_conclusion",
        statement=conclusion,
        kind=ClaimKind.DERIVED,
        status=EpistemicStatus.EXACT,
        why=(imported_exact.id,),
        how=Derivation(DerivationKind.INFERENCE, "uses an exact imported theorem"),
        certificate=exact_theorem,
    )
    assert (
        ClaimGraph((imported_exact, exact_conclusion))
        .verify(
            {support.certificate_id: support},
            verifier_registry=registry,
            source_registry=sources,
        )
        .verified
    )

    for weak_status in (EpistemicStatus.NUMERICAL, EpistemicStatus.HEURISTIC):
        weak_id = f"claim.imported_{weak_status.value}"
        weak_premise = Claim(
            weak_id,
            statement="P",
            kind=ClaimKind.IMPORTED,
            status=weak_status,
            source=("paper.conditional",),
        )
        exact_id = f"claim.promoted_from_{weak_status.value}"
        weak_theorem = TheoremCertificate.create(
            exact_id,
            conclusion.statement_hash,
            (CertificateRef.from_certificate(support),),
            claim_boundary_hash=claim_boundary_hash(
                exact_id,
                conclusion,
                kind=ClaimKind.DERIVED,
                status=EpistemicStatus.EXACT,
                dependency_ids=(weak_id,),
            ),
            verifier="tests.inference",
            dependencies=(weak_id,),
            claim_dependencies=(weak_premise.binding,),
        )
        weak_promotion = Claim(
            exact_id,
            statement=conclusion,
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            why=(weak_id,),
            how=Derivation(DerivationKind.INFERENCE, "claims an unjustified exact promotion"),
            certificate=weak_theorem,
        )
        with pytest.raises(ClaimVerificationError, match=f"{weak_status.value} status"):
            ClaimGraph((weak_premise, weak_promotion)).verify(
                {support.certificate_id: support},
                verifier_registry=registry,
                source_registry=sources,
            )


def test_verification_certificate_dependencies_are_replayed() -> None:
    statement = FormalStatement("P")
    missing = CertificateRef(
        "sha256:" + "0" * 64,
        VerificationCertificate.layer,
        VerificationCertificate.schema_version,
    )
    certificate = VerificationCertificate.create(
        "dependent check",
        "tests.dependent",
        claim_id="claim.dependent",
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            "claim.dependent",
            statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        dependencies=(missing,),
    )
    claim = Claim(
        "claim.dependent",
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("tests.dependent"),
        certificate=certificate,
    )
    registry = VerifierRegistry()
    registry.register("tests.dependent", VerificationCertificate, lambda item: True)
    with pytest.raises(ClaimVerificationError, match="unresolved verification certificate"):
        claim.verify(verifier_registry=registry)


def test_semantic_transport_rejects_unknown_and_coerced_fields() -> None:
    with pytest.raises(EpistemicBoundaryError, match="unexpected exact wrapper"):
        epistemic_from_dict({"status": "exact", "value": 1, "ignored": True})
    with pytest.raises(ValueError, match="derivation method must be a string"):
        Derivation.from_dict({"kind": "inference", "method": 7})
    with pytest.raises(ClaimError, match="evidence ref must be a string"):
        EvidenceRef.from_dict({"ref": 7})

    claim, _, _ = _bound_claim()
    payload = claim.to_dict()
    payload["ignored"] = "not committed by the v1 schema"
    with pytest.raises(ClaimError, match="unexpected claim fields"):
        Claim.from_dict(payload)

    with pytest.raises(SourceError, match="citation must be a string"):
        SourceDocument.from_dict({"key": "paper", "citation": 7})

    sources = SourceRegistry()
    sources.register_document(SourceDocument("paper", "Citation"))
    encoded_sources = sources.to_dict()
    json.dumps(encoded_sources)
    encoded_sources["ignored"] = True
    with pytest.raises(SourceError, match="unexpected source registry fields"):
        SourceRegistry.from_dict(encoded_sources)


def test_theorem_certificate_cannot_promote_unrelated_valid_evidence() -> None:
    support_statement = FormalStatement("H1 has dimension zero")
    support = VerificationCertificate.create(
        "valid finite calculation",
        "tests.support",
        claim_id="claim.support",
        statement_hash=support_statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            "claim.support",
            support_statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        witness={"dimension": 0},
    )
    false_statement = FormalStatement("One equals zero")
    theorem = TheoremCertificate.create(
        "claim.false",
        false_statement.statement_hash,
        (CertificateRef.from_certificate(support),),
        claim_boundary_hash=claim_boundary_hash(
            "claim.false",
            false_statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        verifier="tests.missing-inference-rule",
        conclusion={"text": false_statement.text},
    )
    claim = Claim(
        "claim.false",
        statement=false_statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("tests.false-promotion"),
        certificate=theorem,
    )
    registry = VerifierRegistry()
    registry.register(
        "tests.support",
        VerificationCertificate,
        lambda item: item.witness["dimension"] == 0,
    )
    with pytest.raises(ClaimVerificationError, match="missing-inference-rule"):
        claim.verify(
            {support.certificate_id: support},
            verifier_registry=registry,
        )


def test_graph_structural_verification_is_not_theorem_verification() -> None:
    claim, _, registry = _bound_claim()
    graph = ClaimGraph([claim])
    structural = graph.verify(structural_only=True)
    assert structural.structural_valid
    assert not structural.verified
    assert graph.verify(verifier_registry=registry).verified
