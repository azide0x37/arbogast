"""Bounded, semantically complete JSON packets for machine collaborators."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from arbogast.formats import AGENT_CONTEXT_SCHEMA, JSONValue, canonical_dumps, loads

from .code_dependencies import (
    DEFAULT_CODE_DEPENDENCIES,
    CodeDependencyGraph,
    CodeDependencyRegistry,
    CodeNodeKind,
)
from .hazards import DEFAULT_HAZARDS, Hazard, HazardRegistry
from .manifest import AgentManifest, manifest_for_operations
from .operations import OperationDescription, describe_operation, operation_descriptions
from .routes import CapabilityEdge, CapabilityGraph, CapabilityRoute
from .tasks import AgentTask


@dataclass(frozen=True, slots=True)
class AgentContext:
    """One coherent agent packet with no dangling semantic references."""

    manifest: AgentManifest
    operations: tuple[OperationDescription, ...]
    hazards: tuple[Hazard, ...]
    omitted_operations: int = 0
    omitted_hazards: int = 0
    schema: str = AGENT_CONTEXT_SCHEMA
    capability_routes: tuple[CapabilityRoute, ...] = ()
    capability_frontier: tuple[CapabilityEdge, ...] = ()
    code_dependency_graph: CodeDependencyGraph | None = None
    tasks: tuple[AgentTask, ...] = ()
    undeclared_code_dependencies: tuple[str, ...] = ()
    omitted_routes: int = 0
    omitted_frontier_edges: int = 0
    omitted_code_dependency_edges: int = 0
    omitted_tasks: int = 0

    def __post_init__(self) -> None:
        if self.schema != AGENT_CONTEXT_SCHEMA:
            raise ValueError("unsupported agent-context schema")
        operations = tuple(sorted(self.operations, key=lambda item: item.name))
        hazards = tuple(sorted(self.hazards, key=lambda item: item.id))
        routes = tuple(
            sorted(
                set(self.capability_routes),
                key=lambda route: (route.source, route.target, route.operations),
            )
        )
        frontier = tuple(
            sorted(
                set(self.capability_frontier),
                key=lambda edge: (edge.required_inputs, edge.operation, edge.target),
            )
        )
        tasks = tuple(sorted(set(self.tasks), key=lambda task: task.packet_id))
        undeclared = tuple(sorted(set(self.undeclared_code_dependencies)))
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "hazards", hazards)
        object.__setattr__(self, "capability_routes", routes)
        object.__setattr__(self, "capability_frontier", frontier)
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "undeclared_code_dependencies", undeclared)

        omitted = (
            self.omitted_operations,
            self.omitted_hazards,
            self.omitted_routes,
            self.omitted_frontier_edges,
            self.omitted_code_dependency_edges,
            self.omitted_tasks,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in omitted
        ):
            raise ValueError("agent context omitted counts must be non-negative integers")

        operation_names = {operation.name for operation in operations}
        if set(self.manifest.operations) != operation_names:
            raise ValueError("agent manifest operations do not match context contracts")
        hazard_ids = {hazard.id for hazard in hazards}
        declared_hazards = {
            hazard_id for operation in operations for hazard_id in operation.hazards
        }
        missing_hazards = declared_hazards - hazard_ids
        if missing_hazards:
            raise ValueError(
                "agent context omits declared hazards: " + ", ".join(sorted(missing_hazards))
            )
        for route in routes:
            if any(not step.implemented for step in route.steps):
                raise ValueError("unimplemented capability edges belong in the frontier")
            unknown = set(route.operations) - operation_names
            if unknown:
                raise ValueError(
                    "capability route references missing contracts: " + ", ".join(sorted(unknown))
                )
        for edge in frontier:
            if edge.implemented:
                raise ValueError("capability frontier must contain only unimplemented edges")
            if edge.operation not in operation_names:
                raise ValueError(
                    f"capability frontier references missing contract: {edge.operation}"
                )
        for task in tasks:
            unknown = set(task.relevant_api) - operation_names
            if unknown:
                raise ValueError(
                    "agent task references missing contracts: " + ", ".join(sorted(unknown))
                )
        if self.code_dependency_graph is None:
            if self.manifest.code_dependencies:
                raise ValueError("manifest code dependencies require a code dependency graph")
            if self.undeclared_code_dependencies != tuple(
                sorted(operation.name for operation in operations if operation.implemented)
            ):
                raise ValueError("undeclared code dependencies do not match implemented operations")
        else:
            graph_dependency_ids = {
                node.id
                for node in self.code_dependency_graph.nodes
                if node.kind is not CodeNodeKind.OPERATION
            }
            manifest_dependency_ids = set(self.manifest.code_dependencies)
            if manifest_dependency_ids != graph_dependency_ids:
                missing = graph_dependency_ids - manifest_dependency_ids
                extra = manifest_dependency_ids - graph_dependency_ids
                detail = []
                if missing:
                    detail.append("missing " + ", ".join(sorted(missing)))
                if extra:
                    detail.append("unknown " + ", ".join(sorted(extra)))
                raise ValueError(
                    "manifest code dependencies do not match the code graph: " + "; ".join(detail)
                )
            graph_operations = {
                node.label
                for node in self.code_dependency_graph.nodes
                if node.kind is CodeNodeKind.OPERATION
            }
            unknown = graph_operations - operation_names
            if unknown:
                raise ValueError(
                    "code graph references missing operation contracts: "
                    + ", ".join(sorted(unknown))
                )
            expected_undeclared = {
                operation.name
                for operation in operations
                if operation.implemented and operation.name not in graph_operations
            }
            if set(self.undeclared_code_dependencies) != expected_undeclared:
                raise ValueError("undeclared code dependencies do not match implemented operations")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "capability_frontier": [edge.to_dict() for edge in self.capability_frontier],
            "capability_routes": [route.to_dict() for route in self.capability_routes],
            "code_dependency_graph": (
                None if self.code_dependency_graph is None else self.code_dependency_graph.to_dict()
            ),
            "hazards": [hazard.to_dict() for hazard in self.hazards],
            "manifest": self.manifest.to_dict(),
            "omitted": {
                "code_dependency_edges": self.omitted_code_dependency_edges,
                "frontier_edges": self.omitted_frontier_edges,
                "hazards": self.omitted_hazards,
                "operations": self.omitted_operations,
                "routes": self.omitted_routes,
                "tasks": self.omitted_tasks,
            },
            "operations": [operation.to_dict() for operation in self.operations],
            "schema": self.schema,
            "tasks": [task.to_dict() for task in self.tasks],
            "undeclared_code_dependencies": list(self.undeclared_code_dependencies),
        }

    def to_json(self) -> str:
        return canonical_dumps(self.to_dict())

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> AgentContext:
        decoded = loads(value)
        if not isinstance(decoded, Mapping):
            raise ValueError("agent context JSON must contain an object")
        return cls.from_dict(decoded)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AgentContext:
        expected = {
            "capability_frontier",
            "capability_routes",
            "code_dependency_graph",
            "hazards",
            "manifest",
            "omitted",
            "operations",
            "schema",
            "tasks",
            "undeclared_code_dependencies",
        }
        if set(value) != expected:
            raise ValueError("agent context has missing or unknown fields")
        if value["schema"] != AGENT_CONTEXT_SCHEMA:
            raise ValueError("unsupported agent-context schema")

        def objects(name: str) -> list[Mapping[str, Any]]:
            items = value[name]
            if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
                raise ValueError(f"agent context {name} must be an array of objects")
            return items

        manifest = value["manifest"]
        omitted = value["omitted"]
        graph = value["code_dependency_graph"]
        undeclared = value["undeclared_code_dependencies"]
        if not isinstance(manifest, Mapping):
            raise ValueError("agent context manifest must be an object")
        if not isinstance(omitted, Mapping) or set(omitted) != {
            "code_dependency_edges",
            "frontier_edges",
            "hazards",
            "operations",
            "routes",
            "tasks",
        }:
            raise ValueError("agent context omitted must have the exact counter fields")
        if graph is not None and not isinstance(graph, Mapping):
            raise ValueError("agent context code graph must be an object or null")
        if not isinstance(undeclared, list) or any(
            not isinstance(item, str) for item in undeclared
        ):
            raise ValueError("undeclared code dependencies must be an array of strings")
        counters = tuple(omitted.values())
        if any(isinstance(item, bool) or not isinstance(item, int) for item in counters):
            raise ValueError("agent context omitted counters must be integers")
        return cls(
            manifest=AgentManifest.from_dict(manifest),
            operations=tuple(
                OperationDescription.from_dict(item) for item in objects("operations")
            ),
            hazards=tuple(Hazard.from_dict(item) for item in objects("hazards")),
            omitted_operations=omitted["operations"],
            omitted_hazards=omitted["hazards"],
            capability_routes=tuple(
                CapabilityRoute.from_dict(item) for item in objects("capability_routes")
            ),
            capability_frontier=tuple(
                CapabilityEdge.from_dict(item) for item in objects("capability_frontier")
            ),
            code_dependency_graph=(None if graph is None else CodeDependencyGraph.from_dict(graph)),
            tasks=tuple(AgentTask.from_dict(item) for item in objects("tasks")),
            undeclared_code_dependencies=tuple(undeclared),
            omitted_routes=omitted["routes"],
            omitted_frontier_edges=omitted["frontier_edges"],
            omitted_code_dependency_edges=omitted["code_dependency_edges"],
            omitted_tasks=omitted["tasks"],
        )


def _direct_capabilities(
    descriptions: Iterable[OperationDescription],
) -> tuple[tuple[CapabilityRoute, ...], tuple[CapabilityEdge, ...]]:
    routes = []
    frontier = []
    for edge in CapabilityGraph.from_operations(descriptions).edges:
        if edge.implemented:
            if len(edge.required_inputs) == 1:
                routes.append(CapabilityRoute(edge.required_inputs[0], edge.target, (edge,)))
        else:
            frontier.append(edge)
    return (
        tuple(sorted(set(routes), key=lambda item: (item.source, item.target, item.operations))),
        tuple(
            sorted(
                set(frontier),
                key=lambda item: (item.required_inputs, item.operation, item.target),
            )
        ),
    )


def compact_context(
    operation_names: Iterable[str] | None = None,
    *,
    registry: object | None = None,
    hazards: HazardRegistry = DEFAULT_HAZARDS,
    manifest: AgentManifest | None = None,
    capability_routes: Iterable[CapabilityRoute] = (),
    capability_frontier: Iterable[CapabilityEdge] = (),
    code_dependency_graph: CodeDependencyGraph | None = None,
    code_dependencies: CodeDependencyRegistry | None = None,
    tasks: Iterable[AgentTask] = (),
    max_chars: int = 16_000,
) -> AgentContext:
    """Build a deterministic packet; explicit semantic records are atomic."""

    if max_chars < 256:
        raise ValueError("max_chars must be at least 256")
    explicit_selection = operation_names is not None
    if operation_names is None:
        descriptions = operation_descriptions(registry)
    else:
        descriptions = tuple(
            describe_operation(name, registry) for name in sorted(set(operation_names))
        )
    descriptions = tuple(sorted(descriptions, key=lambda item: item.name))
    supplied_routes = tuple(capability_routes)
    supplied_frontier = tuple(capability_frontier)
    supplied_tasks = tuple(tasks)
    supplied_semantics = bool(
        manifest is not None
        or supplied_routes
        or supplied_frontier
        or code_dependency_graph is not None
        or supplied_tasks
    )
    dependencies = DEFAULT_CODE_DEPENDENCIES if code_dependencies is None else code_dependencies

    def assemble(
        selected: tuple[OperationDescription, ...],
        *,
        omitted_operations: int,
        full_counts: tuple[int, int, int, int] | None,
    ) -> AgentContext:
        operation_ids = tuple(description.name for description in selected)
        triggers = tuple(
            value
            for description in selected
            for value in (description.name, *description.inputs, *description.outputs)
        )
        declared_hazard_ids = tuple(
            hazard_id for description in selected for hazard_id in description.hazards
        )
        relevant_hazards = hazards.relevant(
            triggers,
            declared_ids=declared_hazard_ids,
        )
        automatic_routes, automatic_frontier = _direct_capabilities(selected)
        routes = tuple(
            sorted(
                set((*automatic_routes, *supplied_routes)),
                key=lambda item: (item.source, item.target, item.operations),
            )
        )
        frontier = tuple(
            sorted(
                set((*automatic_frontier, *supplied_frontier)),
                key=lambda item: (item.source, item.operation, item.target),
            )
        )
        declarations, missing = dependencies.select(operation_ids)
        missing_implemented = tuple(
            description.name
            for description in selected
            if description.implemented and description.name in missing
        )
        graph = (
            code_dependency_graph
            if code_dependency_graph is not None
            else CodeDependencyGraph.from_declarations(declarations)
        )
        if code_dependency_graph is not None:
            graph_operations = {
                node.label
                for node in code_dependency_graph.nodes
                if node.kind is CodeNodeKind.OPERATION
            }
            missing_implemented = tuple(
                description.name
                for description in selected
                if description.implemented and description.name not in graph_operations
            )
        if manifest is not None:
            selected_manifest = manifest
        else:
            selected_manifest = manifest_for_operations(selected, code_dependencies=dependencies)
            if code_dependency_graph is not None:
                selected_manifest = replace(
                    selected_manifest,
                    code_dependencies=tuple(
                        node.id
                        for node in code_dependency_graph.nodes
                        if node.kind is not CodeNodeKind.OPERATION
                    ),
                )
        if full_counts is None:
            omitted_hazards = 0
            omitted_routes = 0
            omitted_frontier = 0
            omitted_code_edges = 0
        else:
            omitted_hazards = full_counts[0] - len(relevant_hazards)
            omitted_routes = full_counts[1] - len(routes)
            omitted_frontier = full_counts[2] - len(frontier)
            omitted_code_edges = full_counts[3] - len(graph.edges)
        return AgentContext(
            manifest=selected_manifest,
            operations=selected,
            hazards=relevant_hazards,
            omitted_operations=omitted_operations,
            omitted_hazards=omitted_hazards,
            capability_routes=routes,
            capability_frontier=frontier,
            code_dependency_graph=graph,
            tasks=supplied_tasks,
            undeclared_code_dependencies=missing_implemented,
            omitted_routes=omitted_routes,
            omitted_frontier_edges=omitted_frontier,
            omitted_code_dependency_edges=omitted_code_edges,
        )

    initial = assemble(descriptions, omitted_operations=0, full_counts=None)
    if explicit_selection and initial.undeclared_code_dependencies:
        raise ValueError(
            "selected implemented operations lack declared code dependencies: "
            + ", ".join(initial.undeclared_code_dependencies)
        )
    if len(initial.to_json()) <= max_chars:
        return initial
    if explicit_selection or supplied_semantics:
        raise ValueError("max_chars is too small for the explicitly requested agent context")

    full_counts = (
        len(initial.hazards),
        len(initial.capability_routes),
        len(initial.capability_frontier),
        len(initial.code_dependency_graph.edges) if initial.code_dependency_graph else 0,
    )
    selected = descriptions
    while selected:
        selected = selected[:-1]
        context = assemble(
            selected,
            omitted_operations=len(descriptions) - len(selected),
            full_counts=full_counts,
        )
        if len(context.to_json()) <= max_chars:
            return context
    empty = assemble(
        (),
        omitted_operations=len(descriptions),
        full_counts=full_counts,
    )
    if len(empty.to_json()) <= max_chars:
        return empty
    raise ValueError("max_chars is too small even for an empty agent context envelope")
