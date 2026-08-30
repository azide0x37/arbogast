from __future__ import annotations

import pytest

from arbogast.agent import (
    AgentManifest,
    AgentTask,
    CapabilityGraph,
    CapabilityRouteError,
    CodeDependencyRegistry,
    Hazard,
    HazardRegistry,
    InMemorySemanticRegistry,
    OperationCodeDependencies,
    OperationDescription,
    compact_context,
    describe_operation,
    operation_descriptions,
)


def test_describe_uses_central_semantic_registry_and_real_type_ports() -> None:
    description = describe_operation("cohom.h1")

    assert description.inputs == ("FiniteGroup", "Module")
    assert description.outputs == ("H1Result",)
    assert description.exact is True
    assert description.implemented
    assert description.guarantees


@pytest.mark.parametrize("field", ("exact", "shardable"))
@pytest.mark.parametrize("invalid", (0, 1, "false", "true"))
def test_operation_description_semantic_projection_rejects_non_boolean_flags(
    field: str, invalid: object
) -> None:
    raw: dict[str, object] = {
        "name": "demo.strict-flags",
        "inputs": ("Input",),
        "outputs": ("Output",),
        "exact": True,
        "shardable": False,
    }
    raw[field] = invalid

    with pytest.raises(ValueError, match=rf"semantic operation {field} must be a boolean"):
        OperationDescription.from_semantic(raw)


@pytest.mark.parametrize("field", ("exact", "shardable"))
@pytest.mark.parametrize("invalid", (0, 1, "false", "true"))
def test_operation_description_transport_rejects_non_boolean_flags(
    field: str, invalid: object
) -> None:
    payload = OperationDescription(
        "demo.strict-transport", ("Input",), ("Output",), exact=True
    ).to_dict()
    payload[field] = invalid  # type: ignore[assignment]

    with pytest.raises(ValueError, match=rf"{field}.*boolean"):
        OperationDescription.from_dict(payload)


def test_operation_description_rejects_null_shardable_in_all_transports() -> None:
    raw: dict[str, object] = {
        "name": "demo.null-shardable",
        "inputs": ("Input",),
        "outputs": ("Output",),
        "exact": True,
        "shardable": None,
    }
    with pytest.raises(ValueError, match=r"shardable must be a boolean"):
        OperationDescription.from_semantic(raw)

    payload = OperationDescription(
        "demo.null-shardable", ("Input",), ("Output",), exact=True
    ).to_dict()
    payload["shardable"] = None
    with pytest.raises(ValueError, match=r"shardable must be a boolean"):
        OperationDescription.from_dict(payload)


def test_capability_graph_uses_deterministic_shortest_route() -> None:
    operations = (
        OperationDescription("z.slow", ("A",), ("B",)),
        OperationDescription("a.fast", ("A",), ("B",)),
        OperationDescription("b.finish", ("B",), ("C",)),
    )
    graph = CapabilityGraph.from_operations(operations)

    assert graph.route("A", "C").operations == ("a.fast", "b.finish")
    with pytest.raises(CapabilityRouteError):
        graph.route("C", "A")


def test_capability_graph_requires_complete_conjunctive_input_bundles() -> None:
    operations = (
        OperationDescription("demo.make_b", ("A",), ("B",)),
        OperationDescription("demo.combine", ("A", "B"), ("C",)),
    )
    graph = CapabilityGraph.from_operations(operations)

    route = graph.route("A", "C")
    assert route.operations == ("demo.make_b", "demo.combine")
    assert route.steps[-1].required_inputs == ("A", "B")
    assert type(route).from_dict(route.to_dict()) == route
    with pytest.raises(CapabilityRouteError):
        graph.route("B", "C")


def test_capability_graph_distinguishes_alternative_unary_inputs() -> None:
    operation = OperationDescription(
        "demo.project",
        ("Left", "Right"),
        ("Output",),
        input_bundles=(("Left",), ("Right",)),
    )
    graph = CapabilityGraph.from_operations((operation,))

    assert graph.route("Left", "Output").operations == ("demo.project",)
    assert graph.route("Right", "Output").operations == ("demo.project",)
    assert graph.edges[0].from_dict(graph.edges[0].to_dict()) == graph.edges[0]


def test_capability_graph_expands_explicit_input_and_output_unions() -> None:
    operation = OperationDescription(
        "demo.union",
        ("Left | Right",),
        ("First | Second",),
    )
    graph = CapabilityGraph.from_operations((operation,))

    assert graph.route("Left", "First").operations == ("demo.union",)
    assert graph.route("Left", "Second").operations == ("demo.union",)
    assert graph.route("Right", "First").operations == ("demo.union",)
    assert graph.route("Right", "Second").operations == ("demo.union",)
    assert "Left | Right" not in graph.types
    assert "First | Second" not in graph.types


def test_arithmetic_catalog_routes_concrete_places_and_result_projections() -> None:
    graph = CapabilityGraph.from_operations(operation_descriptions())

    assert graph.route("FinitePlace", "LocalH1Space").operations == ("galois.local_h1",)
    assert graph.route("InfinitePlace", "LocalH1Space").operations == ("galois.local_h1",)
    assert graph.route("KummerSpace", "ClaimGraph").operations == ("galois.claim_graph",)
    assert graph.route("GaloisModule", "VerificationCertificate").operations == (
        "galois.verification_certificate",
    )
    assert graph.route("SelmerGroup", "Claim").operations == ("arithmetic.claim",)
    assert graph.route("KummerSpace", "JSONDocument").operations[-1] == "export.json"


@pytest.mark.parametrize("source", ("Matrix", "int", "bool", "Module"))
def test_catalog_does_not_invent_unary_routes_to_claim_graph(source: str) -> None:
    graph = CapabilityGraph.from_operations(operation_descriptions())

    with pytest.raises(CapabilityRouteError):
        graph.route(source, "ClaimGraph")


def test_manifest_hazards_and_compact_context_are_machine_readable() -> None:
    operation = OperationDescription("demo.op", ("Input",), ("Output",))
    registry = InMemorySemanticRegistry((operation,))
    hazard = Hazard("demo.guard", "Do not erase provenance.", ("demo.op",))
    context = compact_context(
        ("demo.op",),
        registry=registry,
        hazards=HazardRegistry((hazard,)),
        code_dependencies=CodeDependencyRegistry(
            (OperationCodeDependencies("demo.op", "arbogast.demo"),)
        ),
        max_chars=2_000,
    )

    assert AgentManifest.from_registry(registry).operations == ("demo.op",)
    assert context.hazards == (hazard,)
    assert len(context.to_json()) <= 2_000


def test_default_context_surfaces_historical_regression_hazards() -> None:
    context = compact_context(("cohom.h1",), max_chars=4_000)

    assert "cohom.full-shift-quotient-descent" in {hazard.id for hazard in context.hazards}


def test_agent_task_packet_is_immutable_content_addressed_and_tamper_evident() -> None:
    task = AgentTask(
        "Formalize a finite rank witness",
        "Lean theorem",
        inputs=("sha256:input",),
        relevant_api=("cohom.h1",),
        acceptance_tests=("lake build",),
    )
    restored = AgentTask.from_dict(task.to_dict())

    assert restored == task
    assert task.packet_id.startswith("sha256:")
    tampered = {**task.to_dict(), "objective": "different"}
    with pytest.raises(ValueError, match="packet_id"):
        AgentTask.from_dict(tampered)
    with pytest.raises(ValueError, match="missing or unknown"):
        AgentTask.from_dict({**task.to_dict(), "unexpected": None})
    with pytest.raises(ValueError, match="unsupported agent-task schema"):
        AgentTask.from_dict({**task.to_dict(), "schema": "arbogast.agent.task.v0"})
    with pytest.raises(ValueError, match="non-empty strings"):
        AgentTask("objective", "output", relevant_api=(1,))  # type: ignore[arg-type]
