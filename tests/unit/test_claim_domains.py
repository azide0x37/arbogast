from __future__ import annotations

import json

import pytest

from arbogast.cert import VerificationCertificate, VerifierRegistry
from arbogast.claims import (
    CLAIM_BOUNDARY_SCHEMA_V1,
    CLAIM_BOUNDARY_SCHEMA_V2,
    CLAIM_BOUNDARY_SCHEMA_VERSION,
    CLAIM_SCHEMA_V1,
    CLAIM_SCHEMA_V2,
    CLAIM_SCHEMA_VERSION,
    Claim,
    ClaimDomain,
    ClaimError,
    ClaimGraph,
    ClaimGraphError,
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
from arbogast.formats import SchemaError, schema_document, schema_ids, validate_document
from arbogast.proof import ObligationClass, ProofGap, ProofObligation


def _legacy_claim() -> Claim:
    return Claim(
        "claim.legacy",
        statement="Legacy statement.",
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
    )


def _environmental_claim() -> Claim:
    return Claim(
        "environment.ready",
        statement=FormalStatement.create(
            "The pinned environment is ready.",
            renderings={"lean": "True", "latex": r"\mathrm{EnvironmentReady}"},
        ),
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
        domain=ClaimDomain.ENVIRONMENTAL,
    )


def test_legacy_claim_transport_boundary_and_graph_identity_are_exact() -> None:
    claim = _legacy_claim()
    expected: dict[str, object] = {
        "evidence": [],
        "formalization": None,
        "how": None,
        "hypotheses": [],
        "id": "claim.legacy",
        "kind": "conjectured",
        "metadata": {},
        "novelty": None,
        "schema_version": "arbogast.claim/v1",
        "source": [],
        "status": "unknown",
        "what": {
            "language": "mathematics",
            "parameters": {},
            "renderings": {},
            "text": "Legacy statement.",
        },
        "why": [],
    }

    assert CLAIM_SCHEMA_VERSION == CLAIM_SCHEMA_V1 == Claim.schema_version
    assert CLAIM_BOUNDARY_SCHEMA_VERSION == CLAIM_BOUNDARY_SCHEMA_V1
    assert claim.domain is ClaimDomain.MATHEMATICAL
    assert claim.schema_version == CLAIM_SCHEMA_V1
    assert claim.to_dict() == expected
    assert claim.boundary_hash == (
        "sha256:c4ac91e99c94e4ee017c9ca644e1e590d4aba3c6f22bf0805bceacc3fa4124b1"
    )
    assert claim.digest == (
        "sha256:7d6cb9e340b933ae3dc9cae1e6928d4acfb9c939f09a24b904eeac1789238f12"
    )
    graph = ClaimGraph((claim,), graph_id="legacy")
    assert graph.digest == (
        "sha256:026d0c870dcdb41c66bbbb1d6a8fb8d9c78e34e72fc74b4747f7d4fe5dbbe146"
    )
    assert Claim.from_dict(expected).to_dict() == expected

    explicit_mathematical = Claim(
        claim.id,
        statement=claim.what,
        kind=claim.kind,
        status=claim.status,
        domain=ClaimDomain.MATHEMATICAL,
    )
    assert explicit_mathematical.schema_version == CLAIM_SCHEMA_V2
    assert explicit_mathematical != claim
    assert explicit_mathematical.boundary_hash != claim.boundary_hash


def test_explicit_domain_selects_v2_and_is_certificate_bound() -> None:
    statement = FormalStatement("The environment satisfies its finite readiness profile.")
    boundary = claim_boundary_hash(
        "environment.certified",
        statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.CERTIFIED,
        domain=ClaimDomain.ENVIRONMENTAL,
    )
    certificate = VerificationCertificate.create(
        "environment readiness",
        "tests.environment-readiness.v1",
        claim_id="environment.certified",
        statement_hash=statement.statement_hash,
        claim_boundary_hash=boundary,
        witness={"ready": True},
    )
    registry = VerifierRegistry()
    registry.register(
        "tests.environment-readiness.v1",
        VerificationCertificate,
        lambda item: item.witness["ready"] is True,
    )
    claim = Claim(
        "environment.certified",
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.CERTIFIED,
        how=Derivation.computation("bootstrap.certify_readiness"),
        certificate=certificate,
        domain=ClaimDomain.ENVIRONMENTAL,
    )

    assert claim.schema_version == CLAIM_SCHEMA_V2
    assert claim.to_dict()["domain"] == "ENVIRONMENTAL"
    assert claim.boundary_hash == boundary
    assert claim.verify(verifier_registry=registry).verified
    assert Claim.from_dict(claim.to_dict()) == claim
    assert boundary != claim_boundary_hash(
        claim.id,
        statement,
        kind=claim.kind,
        status=claim.status,
        domain=ClaimDomain.SOFTWARE,
    )

    rebound = Claim(
        claim.id,
        statement=statement,
        kind=claim.kind,
        status=claim.status,
        how=claim.how,
        certificate=certificate,
        domain=ClaimDomain.SOFTWARE,
    )
    report = rebound.verify(verifier_registry=registry, raise_on_failure=False)
    assert not report.verified
    assert report.error is not None
    assert "boundary hash" in report.error


def test_v1_and_v2_decoding_are_strict_and_schema_catalogued() -> None:
    legacy = _legacy_claim().to_dict()
    environmental = _environmental_claim().to_dict()

    leaked = dict(legacy)
    leaked["domain"] = "MATHEMATICAL"
    with pytest.raises(ClaimError, match="unexpected claim fields: domain"):
        Claim.from_dict(leaked)

    missing = dict(environmental)
    missing.pop("domain")
    with pytest.raises(ClaimError, match="v2 domain must be a string"):
        Claim.from_dict(missing)

    assert {
        CLAIM_SCHEMA_V1,
        CLAIM_SCHEMA_V2,
        CLAIM_BOUNDARY_SCHEMA_V1,
        CLAIM_BOUNDARY_SCHEMA_V2,
    } <= set(schema_ids())
    assert validate_document(legacy, CLAIM_SCHEMA_V1) == legacy
    assert validate_document(environmental, CLAIM_SCHEMA_V2) == environmental
    claim_required = schema_document(CLAIM_SCHEMA_V2)["required"]
    boundary_required = schema_document(CLAIM_BOUNDARY_SCHEMA_V2)["required"]
    assert isinstance(claim_required, list)
    assert isinstance(boundary_required, list)
    assert "domain" in claim_required
    assert "domain" in boundary_required

    # The catalog describes canonical interchange output.  The authoritative
    # object decoder separately preserves the published v1 input alias/defaults.
    legacy_alias = {
        "schema_version": CLAIM_SCHEMA_V1,
        "id": "claim.v1-alias",
        "statement": "Published v1 alias input.",
        "kind": "conjectured",
        "status": "unknown",
    }
    decoded_alias = Claim.from_dict(legacy_alias)
    assert decoded_alias.what.text == "Published v1 alias input."
    assert "statement" not in decoded_alias.to_dict()
    with pytest.raises(SchemaError, match="missing required fields"):
        validate_document(legacy_alias, CLAIM_SCHEMA_V1)


def test_mixed_graph_keeps_nonmathematical_nodes_out_of_logical_dependencies() -> None:
    mathematical = _legacy_claim()
    environmental = _environmental_claim()
    graph = ClaimGraph((mathematical, environmental), graph_id="mixed")

    assert graph.schema_version == "arbogast.claim-graph/v1"
    assert ClaimGraph.from_dict(graph.to_dict()).to_dict() == graph.to_dict()
    assert graph.theorem_holes() == (mathematical,)
    aggregate = ClaimGraph((environmental,)).verify(raise_on_failure=False)
    assert not aggregate.verified
    assert aggregate.error is not None
    assert "environment.ready" in aggregate.error

    with pytest.raises(ClaimError, match="cannot use why dependencies"):
        Claim(
            "environment.invalid-dependency",
            statement="Environment depends on a theorem-DAG node.",
            kind=ClaimKind.CONJECTURED,
            status=EpistemicStatus.UNKNOWN,
            why=(mathematical.id,),
            domain=ClaimDomain.ENVIRONMENTAL,
        )
    with pytest.raises(ClaimError, match="derived claims require"):
        Claim(
            "environment.invalid-derived",
            statement="An inference with no theorem-DAG premises.",
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.UNKNOWN,
            domain=ClaimDomain.ENVIRONMENTAL,
        )
    with pytest.raises(ClaimError, match="cannot attach mathematical proof gaps"):
        Claim(
            "environment.invalid-proof-gap",
            statement="An operational obligation disguised as a mathematical proof gap.",
            kind=ClaimKind.CONJECTURED,
            status=EpistemicStatus.UNKNOWN,
            formalization=ProofGap(
                "environment.invalid-proof-gap",
                (
                    ProofObligation.create(
                        "environment.probe",
                        "The environment probe succeeds.",
                        ObligationClass.CERTIFICATE,
                    ),
                ),
            ),
            domain=ClaimDomain.ENVIRONMENTAL,
        )

    mathematical_dependent = Claim(
        "claim.invalid-cross-domain",
        statement="A mathematical claim with an environmental logical premise.",
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
        why=(environmental.id,),
    )
    with pytest.raises(ClaimGraphError, match="cannot depend on non-mathematical"):
        ClaimGraph((mathematical_dependent, environmental))


def test_all_node_aggregate_preserves_independent_per_node_verification() -> None:
    statement = FormalStatement("A replayable mathematical node remains valid.")
    certificate = VerificationCertificate.create(
        "independent mathematical verification",
        "tests.independent-mathematical.v1",
        claim_id="claim.independent",
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            "claim.independent",
            statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.CERTIFIED,
        ),
        witness={"valid": True},
    )
    registry = VerifierRegistry()
    registry.register(
        "tests.independent-mathematical.v1",
        VerificationCertificate,
        lambda item: item.witness["valid"] is True,
    )
    mathematical = Claim(
        "claim.independent",
        statement=statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.CERTIFIED,
        how=Derivation.computation("tests.independent"),
        evidence=(certificate,),
    )
    environmental = _environmental_claim()

    report = ClaimGraph((mathematical, environmental)).verify(
        verifier_registry=registry,
        raise_on_failure=False,
    )
    per_node = {item.claim_id: item for item in report.claims}

    assert not report.verified
    assert per_node[mathematical.id].verified
    assert not per_node[environmental.id].verified
    assert mathematical.why == environmental.why == ()


def test_exporters_label_filter_and_never_axiomatize_environmental_claims() -> None:
    mathematical = Claim(
        "claim.mathematical",
        statement=FormalStatement.create("One equals one.", renderings={"lean": "True"}),
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
    )
    environmental = _environmental_claim()
    graph = ClaimGraph((mathematical, environmental), graph_id="mixed")

    payload = json.loads(export_json(graph))
    assert [item["schema_version"] for item in payload["claims"]] == [
        CLAIM_SCHEMA_V1,
        CLAIM_SCHEMA_V2,
    ]
    with pytest.raises(ValueError, match="cannot be domain-filtered"):
        graph.export("json", domains=(ClaimDomain.ENVIRONMENTAL,))

    markdown = export_markdown(graph)
    assert "Domain: `ENVIRONMENTAL`" in markdown
    environmental_markdown = export_markdown(
        graph,
        domains=(ClaimDomain.ENVIRONMENTAL,),
    )
    assert "environment.ready" in environmental_markdown
    assert "claim.mathematical" not in environmental_markdown
    assert "Displayed claims: 1 of 2" in environmental_markdown

    latex = export_latex(environmental)
    assert "Environmental claim" in latex
    assert "Evidence: none recorded" in latex
    assert "Source: none recorded" in latex
    assert r"\begin{proposition}" not in latex
    assert r"\begin{conjecture}" not in latex

    operational = Claim(
        "environment.contextual",
        statement="The bounded environment probe completed.",
        kind=ClaimKind.CONJECTURED,
        status=EpistemicStatus.UNKNOWN,
        how=Derivation.computation("bootstrap.probe", method="Replay fixed probes"),
        evidence=("artifact:doctor-report",),
        source=("runbook:bootstrap",),
        hypotheses=("The selected lock is readable.",),
        domain=ClaimDomain.ENVIRONMENTAL,
    )
    operational_latex = export_latex(operational)
    assert "Recorded operational conditions (not theorem premises)" in operational_latex
    assert "The selected lock is readable" in operational_latex
    assert "Replay fixed probes" in operational_latex
    assert "artifact:doctor-report" in operational_latex
    assert "runbook:bootstrap" in operational_latex
    assert r"\begin{proposition}" not in operational_latex

    lean = export_lean(graph)
    assert 'def claimDomain_environment_ready : String := "ENVIRONMENTAL"' in lean
    assert "axiom claim_claim_mathematical : True" in lean
    assert "axiom claim_environment_ready" not in lean
    assert "domain ENVIRONMENTAL is not mathematical" in lean

    agent = json.loads(export_agent_context(graph, domains=(ClaimDomain.ENVIRONMENTAL,)))
    assert agent["schema_version"] == "arbogast.agent-claim-context/v2"
    assert agent["domain_filter"] == ["ENVIRONMENTAL"]
    assert agent["filtered_claim_count"] == 1
    assert [item["id"] for item in agent["claims"]] == ["environment.ready"]
    assert agent["claims"][0]["domain"] == "ENVIRONMENTAL"
    legacy_agent = json.loads(export_agent_context(mathematical))
    assert legacy_agent["schema_version"] == "arbogast.agent-claim-context/v1"
    assert "domain" not in legacy_agent["claims"][0]
