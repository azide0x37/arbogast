from __future__ import annotations

import pytest

from arbogast import numeric
from arbogast.agent import (
    DEFAULT_CODE_DEPENDENCIES,
    CapabilityGraph,
    CapabilityRouteError,
    compact_context,
    describe_operation,
    module_manifest,
    operation_descriptions,
)
from arbogast.export import export_json
from arbogast.specs import PUBLIC_FUNCTION_OPERATIONS, SHARD_PLANNERS, default_operations

EXPECTED_FUNCTIONS = {
    "bind_vertex": "numeric.bind_vertex",
    "braid_continue": "numeric.braid_continue",
    "branch_cycles": "numeric.branch_cycles",
    "claim_for_result": "numeric.claim",
    "claim_graph_for_result": "numeric.claim_graph",
    "condition_number": "numeric.condition_number",
    "continue_path": "numeric.continue_path",
    "exactify": "numeric.exactify",
    "projection_degree": "numeric.projection_degree",
    "recognize": "numeric.recognize",
    "verification_certificate_for_result": "numeric.verification_certificate",
    "verify_numeric_receipt": "numeric.verify_receipt",
    "weighted_braid_plan": "numeric.weighted_braid_plan",
}

EXACT_OPERATIONS = {
    "numeric.bind_vertex",
    "numeric.branch_cycles",
    "numeric.claim",
    "numeric.claim_graph",
    "numeric.exactify",
    "numeric.projection_degree",
    "numeric.verification_certificate",
    "numeric.verify_receipt",
    "numeric.weighted_braid_plan",
}


def test_every_public_numeric_function_has_one_live_nonshardable_contract() -> None:
    assert PUBLIC_FUNCTION_OPERATIONS["arbogast.numeric"] == EXPECTED_FUNCTIONS

    for public_name, operation_name in EXPECTED_FUNCTIONS.items():
        function = getattr(numeric, public_name)
        spec = default_operations.spec(operation_name)

        assert public_name in numeric.__all__
        assert default_operations.function(operation_name) is function
        assert default_operations.implemented(operation_name)
        assert spec.exact is (operation_name in EXACT_OPERATIONS)
        assert not spec.shardable
        assert spec.shard_strategy is None
        assert operation_name not in SHARD_PLANNERS
        assert DEFAULT_CODE_DEPENDENCIES.get(operation_name).operation == operation_name


def test_numeric_ports_preserve_proof_bearing_success_subtypes() -> None:
    condition = describe_operation("numeric.condition_number")
    branch = describe_operation("numeric.branch_cycles")

    assert condition.outputs == ("ConditionBound | NumericUnknown | UnsupportedNumeric",)
    assert branch.outputs == ("BranchCycleTuple | NumericUnknown",)
    braid = describe_operation("numeric.braid_continue")
    assert braid.outputs == (
        "NumericalCover | BraidContinuationResult | NumericUnknown | UnsupportedNumeric",
    )

    graph = CapabilityGraph.from_operations(operation_descriptions())
    edges = {
        (edge.operation, edge.required_inputs, edge.target)
        for edge in graph.edges
        if edge.operation.startswith("numeric.")
    }
    assert (
        "numeric.condition_number",
        ("PolynomialSystem", "NumericPoint", "InverseJacobianMatrix"),
        "ConditionBound",
    ) in edges
    assert (
        "numeric.branch_cycles",
        ("NumericalCover",),
        "BranchCycleTuple",
    ) in edges
    assert (
        "numeric.projection_degree",
        ("PolynomialSystem", "ProjectionFunctionSequence", "RegularFiberWitness"),
        "RegularFiberDegree",
    ) in edges
    assert (
        "numeric.projection_degree",
        ("PolynomialSystem", "ProjectionFunctionSequence", "RegularFiberWitness"),
        "DegreeResult",
    ) not in edges
    assert (
        "numeric.braid_continue",
        ("NumericalCover", "BraidWord", "QuadraticB2Homotopy"),
        "BraidContinuationResult",
    ) in edges
    assert (
        "numeric.braid_continue",
        ("NumericalCover", "BraidWord", "BraidContinuationWitness"),
        "BraidContinuationResult",
    ) not in edges
    with pytest.raises(CapabilityRouteError):
        graph.route("NumericalCover", "ExactCover")


def test_numeric_specs_do_not_advertise_mutually_exclusive_witnesses() -> None:
    exactify = default_operations.spec("numeric.exactify")
    projection = default_operations.spec("numeric.projection_degree")
    braid = default_operations.spec("numeric.braid_continue")

    assert any("mutually exclusive" in item for item in exactify.requires)
    assert (
        "NumericPoint",
        "AlgebraicCandidate",
        "RecognitionBounds",
    ) not in exactify.input_bundles
    assert any("mutually exclusive" in item for item in projection.requires)
    assert (
        "ExactPolynomial | PolynomialSystem | ExactCover",
        "ProjectionFunctionSequence",
        "RegularFiberWitness",
        "GenericDegreeWitness",
    ) not in projection.input_bundles

    graph = CapabilityGraph.from_operations(operation_descriptions())
    required_inputs = {
        (edge.operation, edge.required_inputs)
        for edge in graph.edges
        if edge.operation in {"numeric.exactify", "numeric.projection_degree"}
    }
    assert (
        "numeric.exactify",
        ("NumericPoint", "AlgebraicCandidate", "RecognitionBounds"),
    ) not in required_inputs
    assert not any(
        operation == "numeric.projection_degree"
        and "RegularFiberWitness" in inputs
        and "GenericDegreeWitness" in inputs
        for operation, inputs in required_inputs
    )
    assert any("rejects a witness bound to a different cover" in item for item in braid.ensures)


def test_numeric_module_profile_and_hazards_keep_the_claim_boundaries_visible() -> None:
    manifest = module_manifest("arbogast.numeric")
    assert {
        "AlgebraicCandidate",
        "BraidContinuationResult",
        "BranchCycleTuple",
        "ConditionBound",
        "ContinuationResult",
        "ExactificationResult",
        "NielsenVertex",
        "NumericReceipt",
        "NumericUnknown",
        "NumericalCover",
        "QuadraticB2Homotopy",
        "RegularFiberDegree",
        "WeightedBraidPlan",
    } <= set(manifest.primary_types)
    assert any("complete separated tracking" in item for item in manifest.invariants)
    assert any("regular fiber" in item.lower() for item in manifest.invariants)

    # The 13-operation packet intentionally uses the stable NumericSemanticResult
    # alias for evidence projections; keep the complete surface within a 48 KiB
    # agent-context budget instead of expanding every result type three times.
    context = compact_context(tuple(EXPECTED_FUNCTIONS.values()), max_chars=48_000)
    assert len(context.to_json()) <= 48_000
    hazard_ids = {hazard.id for hazard in context.hazards}
    assert {
        "numeric.approximation-vs-exact-value",
        "numeric.continuation-vs-exact-braid-action",
        "numeric.incomplete-tracking-vs-exact-branch-cycles",
        "numeric.label-permutation-vs-model-identity",
        "numeric.precision-increase-vs-proof",
        "numeric.recognition-candidate-vs-exactification",
        "numeric.regular-fiber-vs-generic-degree",
        "numeric.weight-vs-mathematical-shortest-path",
    } <= hazard_ids


def test_exporters_lift_numeric_results_to_their_verified_claim_graph() -> None:
    bounds = numeric.RecognitionBounds(2, 2)
    candidate = numeric.recognize(
        numeric.ComplexBall(numeric.Dyadic(181, -7), numeric.Dyadic(1, -10)),
        bounds,
    )
    assert isinstance(candidate, numeric.AlgebraicCandidate)
    graph = candidate.claim_graph()

    assert graph.verify().verified
    assert export_json(candidate) == export_json(graph)
