from __future__ import annotations

from arbogast import deform
from arbogast.agent import (
    DEFAULT_CODE_DEPENDENCIES,
    CapabilityGraph,
    compact_context,
    module_manifest,
    operation_descriptions,
)
from arbogast.export import export_json
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.specs import (
    PUBLIC_FUNCTION_OPERATIONS,
    SHARD_PLANNERS,
    default_operations,
)

EXPECTED_FUNCTIONS = {
    "claim_for_result": "deform.claim",
    "claim_graph_for_result": "deform.claim_graph",
    "deformation_problem": "deform.deformation_problem",
    "equivariant": "deform.equivariant",
    "equivariant_decomposition": "deform.equivariant_decomposition",
    "fixed_lift": "deform.fixed_lift",
    "frame": "deform.frame",
    "gauge": "deform.gauge",
    "invariant_deformations": "deform.invariant_deformations",
    "lift": "deform.lift",
    "obstructions": "deform.obstructions",
    "rigid": "deform.rigid",
    "tangent": "deform.tangent",
    "unique_lift": "deform.unique_lift",
    "verification_certificate_for_result": "deform.verification_certificate",
    "verify_deformation_receipt": "deform.verify_receipt",
}

EXPECTED_HAZARDS = {
    "deform.deformation_problem": "deform.finite-complex-vs-geometric-presentation",
    "deform.obstructions": "deform.obstruction-space-vs-lift-existence",
    "deform.invariant_deformations": ("deform.invariant-complex-vs-invariant-cohomology"),
    "deform.equivariant_decomposition": ("deform.modular-action-vs-projector-decomposition"),
    "deform.rigid": "deform.tangent-zero-vs-unscoped-rigidity",
    "deform.fixed_lift": "deform.unique-lift-vs-canonical-fixed-lift",
}


def test_every_public_deformation_function_has_one_live_nonshardable_contract() -> None:
    assert PUBLIC_FUNCTION_OPERATIONS["arbogast.deform"] == EXPECTED_FUNCTIONS

    for public_name, operation_name in EXPECTED_FUNCTIONS.items():
        function = getattr(deform, public_name)
        spec = default_operations.spec(operation_name)

        assert public_name in deform.__all__
        assert default_operations.function(operation_name) is function
        assert default_operations.implemented(operation_name)
        assert not spec.shardable
        assert spec.shard_strategy is None
        assert operation_name not in SHARD_PLANNERS
        assert DEFAULT_CODE_DEPENDENCIES.get(operation_name).operation == operation_name


def test_capability_graph_and_module_profile_close_the_deformation_surface() -> None:
    graph = CapabilityGraph.from_operations(operation_descriptions())
    routed_operations = {edge.operation for edge in graph.edges}

    assert set(EXPECTED_FUNCTIONS.values()) <= routed_operations
    manifest = module_manifest("arbogast.deform")
    assert {
        "ArtinRing",
        "ArtinRingMap",
        "ContractionCertificate",
        "DeformationAction",
        "DeformationComplex",
        "DeformationProblem",
        "DeformationReceipt",
        "EquivariantDecomposition",
        "FixedLift",
        "Framing",
        "GaugeSpace",
        "LiftFamily",
        "LiftObstructed",
        "LiftUnknown",
        "NonRigid",
        "ObstructionSpace",
        "Rigid",
        "SmallExtension",
        "TangentSpace",
        "UniqueLift",
        "UnsupportedDeformation",
    } <= set(manifest.primary_types)
    assert any("H0, H1, and H2" in invariant for invariant in manifest.invariants)
    assert any("H(C^G)" in invariant for invariant in manifest.invariants)


def test_deformation_hazards_are_selected_by_their_public_operations() -> None:
    for operation_name, hazard_id in EXPECTED_HAZARDS.items():
        context = compact_context((operation_name,), max_chars=16_000)
        assert hazard_id in {hazard.id for hazard in context.hazards}


def test_exporters_lift_a_deformation_result_to_its_verified_claim_graph() -> None:
    field = PrimeField(3)
    complex_ = deform.DeformationComplex(
        field,
        DenseMatrix.zeros(field, 1, 1),
        DenseMatrix.zeros(field, 1, 1),
    )
    result = deform.tangent(complex_)
    graph = result.claim_graph()

    assert graph.verify().verified
    assert export_json(result) == export_json(graph)
