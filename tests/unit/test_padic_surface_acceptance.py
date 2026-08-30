from __future__ import annotations

import pytest

from arbogast import padic
from arbogast.agent import (
    DEFAULT_CODE_DEPENDENCIES,
    DEFAULT_HAZARDS,
    CapabilityGraph,
    CapabilityRouteError,
    describe_operation,
    module_manifest,
    operation_descriptions,
)
from arbogast.cert import VerificationCertificate, default_verifiers
from arbogast.claims import Claim, ClaimGraph
from arbogast.export import export_json
from arbogast.specs import (
    PUBLIC_FUNCTION_OPERATIONS,
    PUBLIC_NON_OPERATION_HELPERS,
    SHARD_PLANNERS,
    default_operations,
)

EXPECTED_FUNCTIONS = {
    "claim": "padic.claim",
    "claim_graph": "padic.claim_graph",
    "deformation_datum": "padic.deformation_datum",
    "effective_descent": "padic.effective_descent",
    "fixed_lifts": "padic.fixed_lifts",
    "frobenius": "padic.frobenius",
    "good_reduction": "padic.good_reduction",
    "inertia_action": "padic.inertia_action",
    "lift_galois_action": "padic.lift_galois_action",
    "lift_set": "padic.lift_set",
    "local_factorization_fragment": "padic.local_factorization_fragment",
    "ordinary_part": "padic.ordinary_part",
    "reduction_frontier": "padic.reduction_frontier",
    "semistable_reduction": "padic.semistable_reduction",
    "slopes": "padic.slopes",
    "stable_reduction": "padic.stable_reduction",
    "verification_certificate": "padic.verification_certificate",
    "verify_receipt": "padic.verify_receipt",
}


def _fragment() -> padic.Certified[padic.LocalFactorizationFragment]:
    return padic.local_factorization_fragment(
        "surface-test.mod3",
        3,
        (0, 1),
        1,
        (padic.FiniteFieldFactor(3, (0, 1)),),
    )


def test_every_public_padic_operation_has_one_live_nonshardable_contract() -> None:
    assert PUBLIC_FUNCTION_OPERATIONS["arbogast.padic"] == EXPECTED_FUNCTIONS
    assert PUBLIC_NON_OPERATION_HELPERS["arbogast.padic"] == {
        "certified_result": (
            "constructs the proof-bearing result envelope used by documented exact fixtures"
        )
    }

    for public_name, operation_name in EXPECTED_FUNCTIONS.items():
        function = getattr(padic, public_name)
        spec = default_operations.spec(operation_name)

        assert public_name in padic.__all__
        assert default_operations.function(operation_name) is function
        assert default_operations.implemented(operation_name)
        assert spec.exact
        assert not spec.shardable
        assert spec.shard_strategy is None
        assert operation_name not in SHARD_PLANNERS
        assert DEFAULT_CODE_DEPENDENCIES.get(operation_name).operation == operation_name


def test_padic_ports_and_routes_preserve_proof_bearing_result_boundaries() -> None:
    assert describe_operation("padic.good_reduction").outputs == (
        "Certified[GoodReduction] | Unknown | Unsupported",
    )
    assert describe_operation("padic.lift_galois_action").outputs == (
        "Certified[LiftGaloisAction] | Unknown | Unsupported",
    )
    assert describe_operation("padic.local_factorization_fragment").outputs == (
        "Certified[LocalFactorizationFragment]",
    )

    graph = CapabilityGraph.from_operations(operation_descriptions())
    edges = {
        (edge.operation, edge.required_inputs, edge.target)
        for edge in graph.edges
        if edge.operation.startswith("padic.")
    }
    assert (
        "padic.semistable_reduction",
        ("Certified[GoodReduction]",),
        "Certified[SemistableReduction]",
    ) in edges
    assert (
        "padic.stable_reduction",
        ("Certified[SemistableReduction]",),
        "Certified[StableReduction]",
    ) in edges
    assert (
        "padic.local_factorization_fragment",
        (
            "str",
            "int",
            "IntegerCoefficientSequence",
            "int",
            "FiniteFieldFactorSequence",
        ),
        "Certified[LocalFactorizationFragment]",
    ) in edges
    assert (
        "padic.reduction_frontier",
        ("Certified[LocalFactorizationFragment]", "int"),
        "Partial",
    ) in edges
    assert (
        "padic.reduction_frontier",
        ("M23ExactDataset", "int"),
        "Unsupported",
    ) in edges
    assert not any(
        edge.operation == "padic.slopes" and "Certified[FrobeniusOperator]" in edge.required_inputs
        for edge in graph.edges
    )
    with pytest.raises(CapabilityRouteError):
        graph.route("Certified[FrobeniusOperator]", "Certified[SlopeDecomposition]")


def test_padic_profile_and_hazards_state_the_nonpromotion_boundaries() -> None:
    manifest = module_manifest("arbogast.padic")
    assert set(EXPECTED_FUNCTIONS.values()) <= set(manifest.operations)
    assert {
        "DescendedModel",
        "FiniteInertiaQuotient",
        "FrobeniusOperator",
        "LocalFactorizationFragment",
        "PAdicReceipt",
        "Partial",
        "StableReduction",
        "Unknown",
        "Unsupported",
    } <= set(manifest.primary_types)
    assert any("arithmetic_lower_numbering_claimed=False" in item for item in manifest.invariants)
    assert any("rigid pinned F_p chart model" in item for item in manifest.invariants)
    assert any("certified_result" in item for item in manifest.do_not)

    hazards = {hazard.id: hazard for hazard in DEFAULT_HAZARDS.all()}
    expected = {
        "padic.bounded-frontier-vs-nonexistence",
        "padic.deformation-datum-vs-realized-lift",
        "padic.finite-inertia-vs-full-local-action",
        "padic.fixed-lift-vs-effective-descent",
        "padic.frobenius-convention-and-period",
        "padic.lift-set-vs-galois-action",
        "padic.local-factorization-vs-reduction-model",
        "padic.newton-slopes-vs-slope-summands",
        "padic.precision-ball-vs-exact-element",
        "padic.reduction-levels-are-distinct",
    }
    assert expected <= set(hazards)
    assert (
        "arithmetic_lower_numbering_claimed=False"
        in hazards["padic.finite-inertia-vs-full-local-action"].remediation
    )


def test_exact_semantic_facades_preserve_type_and_error_behavior() -> None:
    fragment = _fragment()

    certificate = padic.verification_certificate(fragment)
    projected_claim = padic.claim(fragment)
    graph = padic.claim_graph(fragment)

    assert isinstance(certificate, VerificationCertificate)
    assert isinstance(projected_claim, Claim)
    assert isinstance(graph, ClaimGraph)
    assert graph.verify().verified
    assert certificate == fragment.certificate
    assert projected_claim == fragment.claim()
    assert graph.to_dict() == fragment.claim_graph().to_dict()
    assert padic.verify_receipt(fragment.receipt) == fragment.receipt.verify()
    assert export_json(fragment) == export_json(graph)

    for verifier in ("padic.finite-exact.v1", "padic.three-point-exact.v1"):
        assert default_verifiers.describe(verifier)["name"] == verifier
    assert {name for name in default_verifiers.names() if name.startswith("padic.")} == {
        "padic.finite-exact.v1",
        "padic.three-point-exact.v1",
    }

    for projection in (
        padic.verification_certificate,
        padic.claim,
        padic.claim_graph,
    ):
        with pytest.raises(TypeError, match="p-adic result"):
            projection(object())
    with pytest.raises(TypeError, match="PAdicReceipt"):
        padic.verify_receipt(object())  # type: ignore[arg-type]
