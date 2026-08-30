from __future__ import annotations

import importlib
import inspect

import pytest

from arbogast.agent import (
    DEFAULT_CODE_DEPENDENCIES,
    AgentContext,
    AgentManifest,
    AgentTask,
    CapabilityGraph,
    CodeDependencyEdge,
    CodeDependencyError,
    CodeDependencyGraph,
    CodeDependencyKind,
    CodeDependencyRegistry,
    CodeNode,
    CodeNodeKind,
    Hazard,
    HazardRegistry,
    InMemorySemanticRegistry,
    OperationCodeDependencies,
    OperationDescription,
    compact_context,
    module_manifest,
    operation_descriptions,
)
from arbogast.claims import ClaimGraph, ClaimGraphError
from arbogast.formats import (
    AGENT_CONTEXT_SCHEMA,
    AGENT_MANIFEST_SCHEMA,
    CODE_DEPENDENCY_GRAPH_SCHEMA,
    OPERATION_CODE_DEPENDENCIES_SCHEMA,
    schema_document,
)


def _declaration(
    operation: str = "demo.compute",
    *,
    implementation_module: str = "arbogast.demo",
    module_dependencies: tuple[str, ...] = ("arbogast.core",),
    required_backends: tuple[str, ...] = ("python",),
    optional_backends: tuple[str, ...] = ("gap",),
) -> OperationCodeDependencies:
    return OperationCodeDependencies(
        operation,
        implementation_module,
        module_dependencies=module_dependencies,
        required_backends=required_backends,
        optional_backends=optional_backends,
    )


def _graph() -> CodeDependencyGraph:
    return CodeDependencyGraph.from_declarations((_declaration(),))


def test_code_dependency_graph_is_deterministic_content_addressed_and_queryable() -> None:
    first = _declaration("demo.first")
    second = _declaration(
        "demo.second",
        implementation_module="arbogast.demo.extra",
        module_dependencies=("arbogast.demo",),
        optional_backends=(),
    )
    graph = CodeDependencyGraph.from_declarations((second, first))
    reversed_graph = CodeDependencyGraph.from_declarations((first, second))

    assert graph == reversed_graph
    assert graph.content_id == reversed_graph.content_id
    assert CodeDependencyGraph.from_dict(graph.to_dict()) == graph
    assert CodeDependencyGraph.from_json(graph.to_json()) == graph
    assert tuple(node.id for node in graph.nodes) == tuple(sorted(node.id for node in graph.nodes))
    assert {node.id for node in graph.direct_dependencies("operation:demo.first")} == {
        "backend:gap",
        "backend:python",
        "module:arbogast.demo",
    }
    assert {node.id for node in graph.transitive_dependencies("operation:demo.first")} == {
        "backend:gap",
        "backend:python",
        "module:arbogast.core",
        "module:arbogast.demo",
    }


def test_graph_uses_only_declarations_and_never_import_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration = _declaration(
        implementation_module="arbogast.declared_only",
        module_dependencies=("arbogast.explicit_dependency",),
    )

    def rejected(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"unexpected runtime discovery: {args!r} {kwargs!r}")

    monkeypatch.setattr(importlib, "import_module", rejected)
    monkeypatch.setattr(inspect, "getmodule", rejected)
    graph = CodeDependencyGraph.from_declarations((declaration,))

    assert {node.label for node in graph.nodes} == {
        "arbogast.declared_only",
        "arbogast.explicit_dependency",
        "demo.compute",
        "gap",
        "python",
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: {**value, "unexpected": None}, "unknown"),
        (
            lambda value: {**value, "schema": "arbogast.agent.code-dependency-graph.v0"},
            "unsupported",
        ),
        (lambda value: {**value, "content_id": "sha256:bad"}, "content_id"),
        (lambda value: {key: item for key, item in value.items() if key != "nodes"}, "missing"),
    ),
)
def test_code_dependency_graph_decoder_fails_closed(mutation: object, message: str) -> None:
    mutate = mutation
    assert callable(mutate)
    with pytest.raises(CodeDependencyError, match=message):
        CodeDependencyGraph.from_dict(mutate(_graph().to_dict()))


def test_code_dependency_declaration_decoder_is_strict() -> None:
    declaration = _declaration()
    assert OperationCodeDependencies.from_dict(declaration.to_dict()) == declaration

    with pytest.raises(CodeDependencyError, match="unsupported"):
        OperationCodeDependencies.from_dict(
            {**declaration.to_dict(), "schema": "arbogast.agent.operation-code-dependencies.v0"}
        )
    with pytest.raises(CodeDependencyError, match="unknown"):
        OperationCodeDependencies.from_dict({**declaration.to_dict(), "extra": []})
    with pytest.raises(CodeDependencyError, match="array"):
        OperationCodeDependencies.from_dict(
            {**declaration.to_dict(), "module_dependencies": "arbogast.core"}
        )
    with pytest.raises(CodeDependencyError, match="both required and optional"):
        OperationCodeDependencies(
            "demo.compute",
            "arbogast.demo",
            required_backends=("gap",),
            optional_backends=("gap",),
        )


def test_code_dependency_graph_rejects_duplicates_dangling_edges_and_cycles() -> None:
    first = CodeNode("module:arbogast.first", CodeNodeKind.MODULE, "arbogast.first")
    second = CodeNode("module:arbogast.second", CodeNodeKind.MODULE, "arbogast.second")
    operation = CodeNode("operation:demo.compute", CodeNodeKind.OPERATION, "demo.compute")
    backend = CodeNode("backend:python", CodeNodeKind.BACKEND, "python")
    forward = CodeDependencyEdge(
        first.id,
        second.id,
        CodeDependencyKind.DEPENDS_ON,
    )

    with pytest.raises(CodeDependencyError, match="duplicate node"):
        CodeDependencyGraph((first, first), ())
    with pytest.raises(CodeDependencyError, match="duplicate edges"):
        CodeDependencyGraph((first, second), (forward, forward))
    with pytest.raises(CodeDependencyError, match="unknown node"):
        CodeDependencyGraph((first,), (forward,))
    with pytest.raises(CodeDependencyError, match="cycle"):
        CodeDependencyGraph(
            (first, second),
            (
                forward,
                CodeDependencyEdge(
                    second.id,
                    first.id,
                    CodeDependencyKind.DEPENDS_ON,
                ),
            ),
        )
    with pytest.raises(CodeDependencyError, match="self loops"):
        CodeDependencyEdge(first.id, first.id, CodeDependencyKind.DEPENDS_ON)
    with pytest.raises(CodeDependencyError, match="required flag"):
        CodeDependencyEdge(
            first.id,
            "backend:gap",
            CodeDependencyKind.OPTIONAL_BACKEND,
            required=True,
        )
    with pytest.raises(CodeDependencyError, match="kind and label"):
        CodeNode("module:arbogast.wrong", CodeNodeKind.MODULE, "arbogast.first")
    with pytest.raises(CodeDependencyError, match="exactly one implemented_by"):
        CodeDependencyGraph((operation,), ())
    with pytest.raises(CodeDependencyError, match="implemented_by edge requires"):
        CodeDependencyGraph(
            (operation, backend),
            (
                CodeDependencyEdge(
                    operation.id,
                    backend.id,
                    CodeDependencyKind.IMPLEMENTED_BY,
                ),
            ),
        )
    with pytest.raises(CodeDependencyError, match="orphan dependency"):
        CodeDependencyGraph((first,), ())
    with pytest.raises(CodeDependencyError, match="exactly one implemented_by"):
        CodeDependencyGraph(
            (operation, first, second),
            (
                CodeDependencyEdge(
                    operation.id,
                    first.id,
                    CodeDependencyKind.IMPLEMENTED_BY,
                ),
                CodeDependencyEdge(
                    operation.id,
                    second.id,
                    CodeDependencyKind.IMPLEMENTED_BY,
                ),
            ),
        )


def test_default_code_declarations_cover_every_implemented_contract() -> None:
    implemented = {
        operation.name for operation in operation_descriptions() if operation.implemented
    }

    assert set(DEFAULT_CODE_DEPENDENCIES.names()) == implemented


def test_code_theorem_and_capability_graphs_are_distinct_serializations() -> None:
    code_graph = _graph()
    theorem_graph = ClaimGraph()
    capability_graph = CapabilityGraph.from_operations(
        (OperationDescription("demo.compute", ("Input",), ("Output",)),)
    )

    assert theorem_graph.schema_version != CODE_DEPENDENCY_GRAPH_SCHEMA
    assert "nodes" in code_graph.to_dict()
    assert "claims" in theorem_graph.to_dict()
    assert "types" in capability_graph.to_dict()
    with pytest.raises(CodeDependencyError):
        CodeDependencyGraph.from_dict(theorem_graph.to_dict())  # type: ignore[arg-type]
    with pytest.raises(ClaimGraphError):
        ClaimGraph.from_dict(code_graph.to_dict())
    with pytest.raises(CodeDependencyError):
        CodeDependencyGraph.from_dict(capability_graph.to_dict())  # type: ignore[arg-type]


def test_supplied_code_graph_populates_manifest_without_runtime_guessing() -> None:
    operation = OperationDescription("demo.compute", ("Input",), ("Output",))
    graph = _graph()

    context = compact_context(
        ("demo.compute",),
        registry=InMemorySemanticRegistry((operation,)),
        code_dependency_graph=graph,
        max_chars=8_000,
    )

    assert set(context.manifest.code_dependencies) == {
        node.id for node in graph.nodes if node.kind is not CodeNodeKind.OPERATION
    }
    with pytest.raises(ValueError, match="lack declared code dependencies"):
        compact_context(
            ("demo.compute",),
            registry=InMemorySemanticRegistry((operation,)),
            code_dependency_graph=CodeDependencyGraph((), ()),
            max_chars=8_000,
        )


def _complete_context(*, max_chars: int = 20_000) -> AgentContext:
    compute = OperationDescription(
        "demo.compute",
        ("Input", "Parameter"),
        ("Output",),
        preconditions=("input is finite",),
        guarantees=("output is exact",),
        failure_modes=("invalid input",),
        summary="Compute the exact demo object.",
        mathematical_domain="finite demonstrations",
        certificate_type="DemoCertificate",
        exact=True,
        shardable=True,
        shard_strategy="partition inputs",
        complexity="finite",
        examples=("demo.compute(input, parameter)",),
        hazards=("demo.guard",),
    )
    future = OperationDescription(
        "demo.future",
        ("Output",),
        ("Theorem",),
        preconditions=("output is verified",),
        guarantees=("would construct a theorem projection",),
        failure_modes=("not implemented",),
        implemented=False,
    )
    operations = (compute, future)
    registry = InMemorySemanticRegistry(operations)
    code_registry = CodeDependencyRegistry((_declaration(optional_backends=()),))
    graph = code_registry.graph(("demo.compute",))
    manifest = AgentManifest.from_operations(
        operations,
        version="0.2.0",
        scope="arbogast.demo",
        purpose="A complete bounded agent fixture.",
        primary_types=("Input", "Output", "Theorem"),
        invariants=("Outputs retain exact provenance.",),
        do_not=("Do not promote an unverified output.",),
        code_dependencies=(
            node.id for node in graph.nodes if node.kind is not CodeNodeKind.OPERATION
        ),
    )
    hazard = Hazard(
        "demo.guard",
        "Preserve the finite provenance witness.",
        ("unrelated-trigger",),
    )
    task = AgentTask(
        "Implement the demo verifier",
        "Verifier plus focused tests",
        inputs=("artifact:demo-input",),
        relevant_api=("demo.compute",),
        dependencies=("task:canonical-decoder",),
        acceptance_tests=("pytest tests/unit/test_demo.py",),
        max_context=("arbogast.demo", "DemoCertificate"),
    )
    return compact_context(
        ("demo.compute", "demo.future"),
        registry=registry,
        hazards=HazardRegistry((hazard,)),
        manifest=manifest,
        code_dependencies=code_registry,
        tasks=(task,),
        max_chars=max_chars,
    )


def test_agent_context_is_complete_coherent_and_strictly_round_trippable() -> None:
    context = _complete_context()

    assert AgentContext.from_dict(context.to_dict()) == context
    assert AgentContext.from_json(context.to_json()) == context
    assert context.manifest.invariants == ("Outputs retain exact provenance.",)
    assert context.manifest.do_not == ("Do not promote an unverified output.",)
    assert {operation.name for operation in context.operations} == {
        "demo.compute",
        "demo.future",
    }
    assert context.operations[0].examples == ("demo.compute(input, parameter)",)
    assert {hazard.id for hazard in context.hazards} == {"demo.guard"}
    assert context.capability_routes == ()
    assert context.operations[0].input_bundles == (("Input", "Parameter"),)
    assert {edge.operation for edge in context.capability_frontier} == {"demo.future"}
    assert context.tasks[0].acceptance_tests == ("pytest tests/unit/test_demo.py",)
    assert context.undeclared_code_dependencies == ()
    assert context.code_dependency_graph is not None

    with pytest.raises(ValueError, match="missing or unknown"):
        AgentContext.from_dict({**context.to_dict(), "unexpected": None})
    with pytest.raises(ValueError, match="unsupported agent-context schema"):
        AgentContext.from_dict({**context.to_dict(), "schema": "arbogast.agent.context.v0"})


def test_explicit_context_records_are_atomic_at_the_character_budget() -> None:
    context = _complete_context()
    exact_size = len(context.to_json())

    assert len(_complete_context(max_chars=exact_size).to_json()) == exact_size
    with pytest.raises(ValueError, match="too small"):
        _complete_context(max_chars=exact_size - 1)


def test_manifest_is_strict_and_module_api_is_generated_equivalent_of_agent_md() -> None:
    manifest = module_manifest("arbogast.hurwitz.braid")

    assert manifest.scope == "arbogast.hurwitz"
    assert "NielsenTuple" in manifest.primary_types
    assert "hurwitz.braid_action" in manifest.operations
    assert any("source genus" in guardrail for guardrail in manifest.do_not)
    assert "module:arbogast.hurwitz" in manifest.code_dependencies
    assert AgentManifest.from_dict(manifest.to_dict()) == manifest
    assert AgentManifest.from_json(manifest.to_json()) == manifest

    with pytest.raises(ValueError, match="missing or unknown"):
        AgentManifest.from_dict({**manifest.to_dict(), "unexpected": None})
    with pytest.raises(ValueError, match="unsupported agent-manifest schema"):
        AgentManifest.from_dict({**manifest.to_dict(), "schema": "arbogast.agent.manifest.v0"})
    with pytest.raises(LookupError, match="no agent module profile"):
        module_manifest("arbogast.not_a_module")


def test_agent_schema_documents_require_the_enriched_surfaces() -> None:
    manifest_required = set(schema_document(AGENT_MANIFEST_SCHEMA)["required"])
    context_required = set(schema_document(AGENT_CONTEXT_SCHEMA)["required"])
    declaration_required = set(schema_document(OPERATION_CODE_DEPENDENCIES_SCHEMA)["required"])

    assert {"scope", "purpose", "invariants", "do_not", "code_dependencies"} <= (manifest_required)
    assert {
        "capability_routes",
        "capability_frontier",
        "code_dependency_graph",
        "tasks",
        "omitted",
    } <= context_required
    assert {"implementation_module", "required_backends"} <= declaration_required
