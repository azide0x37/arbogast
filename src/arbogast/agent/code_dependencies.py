"""Declared code dependencies, kept separate from mathematical graphs.

The code graph is intentionally built from explicit declarations.  It never
walks Python imports or inspects callable ``__module__`` attributes: those are
runtime implementation details, not a stable agent contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from arbogast.formats import (
    CODE_DEPENDENCY_GRAPH_SCHEMA,
    OPERATION_CODE_DEPENDENCIES_SCHEMA,
    JSONValue,
    canonical_dumps,
    canonical_sha256,
    loads,
)


class CodeDependencyError(ValueError):
    """Raised when a declared code dependency graph is invalid."""


class CodeDependencyLookupError(LookupError):
    """Raised when an operation has no declared code dependency contract."""


class CodeNodeKind(StrEnum):
    """Kinds of implementation nodes in the code DAG."""

    OPERATION = "operation"
    MODULE = "module"
    BACKEND = "backend"


class CodeDependencyKind(StrEnum):
    """Semantics of an edge from dependent code to a dependency."""

    IMPLEMENTED_BY = "implemented_by"
    DEPENDS_ON = "depends_on"
    REQUIRES_BACKEND = "requires_backend"
    OPTIONAL_BACKEND = "optional_backend"


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CodeDependencyError(f"{label} must be a non-blank string")
    return value


def _string_array(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise CodeDependencyError(f"{label} must be an array of non-blank strings")
    return tuple(value)


def _require_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if unknown:
            detail.append(f"unknown {', '.join(unknown)}")
        raise CodeDependencyError(f"{label} has {'; '.join(detail)} fields")


@dataclass(frozen=True, slots=True)
class OperationCodeDependencies:
    """Stable implementation and backend declarations for one operation."""

    operation: str
    implementation_module: str
    module_dependencies: tuple[str, ...] = ()
    required_backends: tuple[str, ...] = ("python",)
    optional_backends: tuple[str, ...] = ()
    schema: str = OPERATION_CODE_DEPENDENCIES_SCHEMA

    def __post_init__(self) -> None:
        operation = _nonblank(self.operation, "operation")
        implementation = _nonblank(self.implementation_module, "implementation_module")
        if not implementation.startswith("arbogast."):
            raise CodeDependencyError("implementation_module must be an arbogast module")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "implementation_module", implementation)
        for field_name in (
            "module_dependencies",
            "required_backends",
            "optional_backends",
        ):
            raw = tuple(getattr(self, field_name))
            if any(not isinstance(item, str) or not item.strip() for item in raw):
                raise CodeDependencyError(f"{field_name} must contain non-blank strings")
            object.__setattr__(self, field_name, tuple(sorted(set(raw))))
        if implementation in self.module_dependencies:
            raise CodeDependencyError("an implementation module cannot depend on itself")
        if any(not module.startswith("arbogast.") for module in self.module_dependencies):
            raise CodeDependencyError("module dependencies must be arbogast modules")
        overlap = set(self.required_backends).intersection(self.optional_backends)
        if overlap:
            raise CodeDependencyError(
                "a backend cannot be both required and optional: " + ", ".join(sorted(overlap))
            )
        if self.schema != OPERATION_CODE_DEPENDENCIES_SCHEMA:
            raise CodeDependencyError("unsupported operation-code-dependencies schema")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "implementation_module": self.implementation_module,
            "module_dependencies": list(self.module_dependencies),
            "operation": self.operation,
            "optional_backends": list(self.optional_backends),
            "required_backends": list(self.required_backends),
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OperationCodeDependencies:
        expected = {
            "implementation_module",
            "module_dependencies",
            "operation",
            "optional_backends",
            "required_backends",
            "schema",
        }
        _require_fields(value, expected, "operation code dependency declaration")
        if value["schema"] != OPERATION_CODE_DEPENDENCIES_SCHEMA:
            raise CodeDependencyError("unsupported operation-code-dependencies schema")
        return cls(
            operation=_nonblank(value["operation"], "operation"),
            implementation_module=_nonblank(
                value["implementation_module"], "implementation_module"
            ),
            module_dependencies=_string_array(value["module_dependencies"], "module_dependencies"),
            required_backends=_string_array(value["required_backends"], "required_backends"),
            optional_backends=_string_array(value["optional_backends"], "optional_backends"),
        )


@dataclass(frozen=True, order=True, slots=True)
class CodeNode:
    """One operation, module, or backend in the declared code graph."""

    id: str
    kind: CodeNodeKind
    label: str

    def __post_init__(self) -> None:
        node_id = _nonblank(self.id, "code node id")
        label = _nonblank(self.label, "code node label")
        if not isinstance(self.kind, CodeNodeKind):
            raise CodeDependencyError("code node kind is invalid")
        expected_id = f"{self.kind.value}:{label}"
        if node_id != expected_id:
            raise CodeDependencyError(
                f"code node id must be {expected_id!r} for its kind and label"
            )

    def to_dict(self) -> dict[str, JSONValue]:
        return {"id": self.id, "kind": self.kind.value, "label": self.label}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodeNode:
        _require_fields(value, {"id", "kind", "label"}, "code node")
        try:
            kind = CodeNodeKind(value["kind"])
        except (TypeError, ValueError) as error:
            raise CodeDependencyError("code node kind is invalid") from error
        return cls(
            id=_nonblank(value["id"], "code node id"),
            kind=kind,
            label=_nonblank(value["label"], "code node label"),
        )


@dataclass(frozen=True, order=True, slots=True)
class CodeDependencyEdge:
    """One declared dependency edge from dependent to dependency."""

    dependent: str
    dependency: str
    kind: CodeDependencyKind
    required: bool = True

    def __post_init__(self) -> None:
        _nonblank(self.dependent, "code dependency dependent")
        _nonblank(self.dependency, "code dependency dependency")
        if self.dependent == self.dependency:
            raise CodeDependencyError("code dependency edges cannot be self loops")
        if not isinstance(self.kind, CodeDependencyKind):
            raise CodeDependencyError("code dependency kind is invalid")
        if not isinstance(self.required, bool):
            raise CodeDependencyError("code dependency required must be a boolean")
        expected_required = self.kind is not CodeDependencyKind.OPTIONAL_BACKEND
        if self.required is not expected_required:
            raise CodeDependencyError("code dependency required flag conflicts with its kind")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind.value,
            "required": self.required,
            "dependent": self.dependent,
            "dependency": self.dependency,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodeDependencyEdge:
        _require_fields(
            value,
            {"dependency", "dependent", "kind", "required"},
            "code edge",
        )
        try:
            kind = CodeDependencyKind(value["kind"])
        except (TypeError, ValueError) as error:
            raise CodeDependencyError("code dependency kind is invalid") from error
        required = value["required"]
        if not isinstance(required, bool):
            raise CodeDependencyError("code dependency required must be a boolean")
        return cls(
            dependent=_nonblank(value["dependent"], "code dependency dependent"),
            dependency=_nonblank(value["dependency"], "code dependency dependency"),
            kind=kind,
            required=required,
        )


@dataclass(frozen=True, slots=True)
class CodeDependencyGraph:
    """A strict, content-addressed DAG of declared implementation dependencies."""

    nodes: tuple[CodeNode, ...]
    edges: tuple[CodeDependencyEdge, ...]
    schema: str = CODE_DEPENDENCY_GRAPH_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CODE_DEPENDENCY_GRAPH_SCHEMA:
            raise CodeDependencyError("unsupported code-dependency-graph schema")
        nodes = tuple(sorted(self.nodes, key=lambda node: node.id))
        edges = tuple(
            sorted(
                self.edges,
                key=lambda edge: (
                    edge.dependent,
                    edge.dependency,
                    edge.kind.value,
                    edge.required,
                ),
            )
        )
        if len({node.id for node in nodes}) != len(nodes):
            raise CodeDependencyError("code dependency graph has duplicate node ids")
        if len(set(edges)) != len(edges):
            raise CodeDependencyError("code dependency graph has duplicate edges")
        node_ids = {node.id for node in nodes}
        nodes_by_id = {node.id: node for node in nodes}
        for edge in edges:
            if edge.dependent not in node_ids or edge.dependency not in node_ids:
                raise CodeDependencyError("code dependency edge references an unknown node")
            self._validate_edge_semantics(
                edge,
                nodes_by_id[edge.dependent],
                nodes_by_id[edge.dependency],
            )
        implementation_counts = {
            node.id: 0 for node in nodes if node.kind is CodeNodeKind.OPERATION
        }
        incident = {node.id: 0 for node in nodes}
        for edge in edges:
            incident[edge.dependent] += 1
            incident[edge.dependency] += 1
            if edge.kind is CodeDependencyKind.IMPLEMENTED_BY:
                implementation_counts[edge.dependent] += 1
        if any(count != 1 for count in implementation_counts.values()):
            raise CodeDependencyError(
                "every operation code node requires exactly one implemented_by edge"
            )
        if any(
            node.kind is not CodeNodeKind.OPERATION and incident[node.id] == 0 for node in nodes
        ):
            raise CodeDependencyError("code dependency graph contains an orphan dependency node")
        self._check_acyclic(nodes, edges)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)

    @staticmethod
    def _validate_edge_semantics(
        edge: CodeDependencyEdge,
        dependent: CodeNode,
        dependency: CodeNode,
    ) -> None:
        expected = {
            CodeDependencyKind.IMPLEMENTED_BY: (
                CodeNodeKind.OPERATION,
                CodeNodeKind.MODULE,
            ),
            CodeDependencyKind.DEPENDS_ON: (CodeNodeKind.MODULE, CodeNodeKind.MODULE),
            CodeDependencyKind.REQUIRES_BACKEND: (
                CodeNodeKind.OPERATION,
                CodeNodeKind.BACKEND,
            ),
            CodeDependencyKind.OPTIONAL_BACKEND: (
                CodeNodeKind.OPERATION,
                CodeNodeKind.BACKEND,
            ),
        }[edge.kind]
        actual = (dependent.kind, dependency.kind)
        if actual != expected:
            raise CodeDependencyError(
                f"{edge.kind.value} edge requires {expected[0].value} -> {expected[1].value} nodes"
            )

    @staticmethod
    def _check_acyclic(nodes: tuple[CodeNode, ...], edges: tuple[CodeDependencyEdge, ...]) -> None:
        adjacency: dict[str, list[str]] = {node.id: [] for node in nodes}
        for edge in edges:
            adjacency[edge.dependent].append(edge.dependency)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise CodeDependencyError("code dependency graph contains a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for target in sorted(adjacency[node_id]):
                visit(target)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in sorted(adjacency):
            visit(node_id)

    @classmethod
    def from_declarations(
        cls, declarations: Iterable[OperationCodeDependencies]
    ) -> CodeDependencyGraph:
        nodes: dict[str, CodeNode] = {}
        edges: set[CodeDependencyEdge] = set()

        def add_node(kind: CodeNodeKind, label: str) -> str:
            node_id = f"{kind.value}:{label}"
            node = CodeNode(node_id, kind, label)
            existing = nodes.get(node_id)
            if existing is not None and existing != node:
                raise CodeDependencyError(f"conflicting code node declaration: {node_id}")
            nodes[node_id] = node
            return node_id

        seen_operations: set[str] = set()
        for declaration in declarations:
            if declaration.operation in seen_operations:
                raise CodeDependencyError(
                    f"duplicate operation code declaration: {declaration.operation}"
                )
            seen_operations.add(declaration.operation)
            operation_id = add_node(CodeNodeKind.OPERATION, declaration.operation)
            implementation_id = add_node(CodeNodeKind.MODULE, declaration.implementation_module)
            edges.add(
                CodeDependencyEdge(
                    operation_id,
                    implementation_id,
                    CodeDependencyKind.IMPLEMENTED_BY,
                )
            )
            for module in declaration.module_dependencies:
                dependency_id = add_node(CodeNodeKind.MODULE, module)
                edges.add(
                    CodeDependencyEdge(
                        implementation_id,
                        dependency_id,
                        CodeDependencyKind.DEPENDS_ON,
                    )
                )
            for backend in declaration.required_backends:
                backend_id = add_node(CodeNodeKind.BACKEND, backend)
                edges.add(
                    CodeDependencyEdge(
                        operation_id,
                        backend_id,
                        CodeDependencyKind.REQUIRES_BACKEND,
                    )
                )
            for backend in declaration.optional_backends:
                backend_id = add_node(CodeNodeKind.BACKEND, backend)
                edges.add(
                    CodeDependencyEdge(
                        operation_id,
                        backend_id,
                        CodeDependencyKind.OPTIONAL_BACKEND,
                        required=False,
                    )
                )
        return cls(tuple(nodes.values()), tuple(edges))

    def identity_dict(self) -> dict[str, JSONValue]:
        return {
            "edges": [edge.to_dict() for edge in self.edges],
            "nodes": [node.to_dict() for node in self.nodes],
            "schema": self.schema,
        }

    @property
    def content_id(self) -> str:
        return f"sha256:{canonical_sha256(self.identity_dict())}"

    def to_dict(self) -> dict[str, JSONValue]:
        return {**self.identity_dict(), "content_id": self.content_id}

    def to_json(self) -> str:
        """Serialize the graph with Arbogast's canonical JSON encoding."""

        return canonical_dumps(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodeDependencyGraph:
        _require_fields(value, {"content_id", "edges", "nodes", "schema"}, "code graph")
        if value["schema"] != CODE_DEPENDENCY_GRAPH_SCHEMA:
            raise CodeDependencyError("unsupported code-dependency-graph schema")
        raw_nodes = value["nodes"]
        raw_edges = value["edges"]
        if not isinstance(raw_nodes, list) or any(
            not isinstance(item, Mapping) for item in raw_nodes
        ):
            raise CodeDependencyError("code graph nodes must be an array of objects")
        if not isinstance(raw_edges, list) or any(
            not isinstance(item, Mapping) for item in raw_edges
        ):
            raise CodeDependencyError("code graph edges must be an array of objects")
        graph = cls(
            tuple(CodeNode.from_dict(item) for item in raw_nodes),
            tuple(CodeDependencyEdge.from_dict(item) for item in raw_edges),
        )
        content_id = value["content_id"]
        if not isinstance(content_id, str) or content_id != graph.content_id:
            raise CodeDependencyError("code graph content_id does not match its contents")
        return graph

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> CodeDependencyGraph:
        """Decode a strict canonical-JSON graph document."""

        decoded = loads(value)
        if not isinstance(decoded, Mapping):
            raise CodeDependencyError("code graph JSON must contain an object")
        return cls.from_dict(decoded)

    def dependencies_of(self, node_id: str, *, transitive: bool = True) -> tuple[CodeNode, ...]:
        """Return stable declared dependencies of one node."""

        by_id = {node.id: node for node in self.nodes}
        if node_id not in by_id:
            raise CodeDependencyLookupError(node_id)
        adjacency: dict[str, set[str]] = {}
        for edge in self.edges:
            adjacency.setdefault(edge.dependent, set()).add(edge.dependency)
        found: set[str] = set()
        frontier = list(sorted(adjacency.get(node_id, ())))
        while frontier:
            current = frontier.pop(0)
            if current in found:
                continue
            found.add(current)
            if transitive:
                frontier.extend(sorted(adjacency.get(current, ())))
        return tuple(by_id[item] for item in sorted(found))

    def direct_dependencies(self, node_id: str) -> tuple[CodeNode, ...]:
        """Return the immediate declared dependencies of ``node_id``."""

        return self.dependencies_of(node_id, transitive=False)

    def transitive_dependencies(self, node_id: str) -> tuple[CodeNode, ...]:
        """Return the transitive declared dependencies of ``node_id``."""

        return self.dependencies_of(node_id, transitive=True)


class CodeDependencyRegistry:
    """Registry of explicit operation-to-code declarations."""

    def __init__(self, declarations: Iterable[OperationCodeDependencies] = ()) -> None:
        self._declarations: dict[str, OperationCodeDependencies] = {}
        for declaration in declarations:
            self.register(declaration)

    def register(self, declaration: OperationCodeDependencies, *, replace: bool = False) -> None:
        existing = self._declarations.get(declaration.operation)
        if existing is not None and not replace:
            if existing == declaration:
                return
            raise CodeDependencyError(
                f"operation code dependencies already declared: {declaration.operation}"
            )
        self._declarations[declaration.operation] = declaration

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._declarations))

    def get(self, operation: str) -> OperationCodeDependencies:
        try:
            return self._declarations[operation]
        except KeyError as error:
            raise CodeDependencyLookupError(operation) from error

    def select(
        self, operations: Iterable[str]
    ) -> tuple[tuple[OperationCodeDependencies, ...], tuple[str, ...]]:
        selected = []
        missing = []
        for operation in sorted(set(operations)):
            declaration = self._declarations.get(operation)
            if declaration is None:
                missing.append(operation)
            else:
                selected.append(declaration)
        return tuple(selected), tuple(missing)

    def graph(
        self, operations: Iterable[str], *, require_complete: bool = True
    ) -> CodeDependencyGraph:
        selected, missing = self.select(operations)
        if missing and require_complete:
            raise CodeDependencyLookupError(
                "no declared code dependencies for: " + ", ".join(missing)
            )
        return CodeDependencyGraph.from_declarations(selected)

    def operations_for_module(self, module: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                declaration.operation
                for declaration in self._declarations.values()
                if declaration.implementation_module == module
                or declaration.implementation_module.startswith(module + ".")
            )
        )

    def module_dependencies(self, module: str) -> tuple[str, ...]:
        dependencies = {
            dependency
            for declaration in self._declarations.values()
            if declaration.implementation_module == module
            or declaration.implementation_module.startswith(module + ".")
            for dependency in declaration.module_dependencies
        }
        return tuple(sorted(dependencies))


def _declarations(
    operations: Iterable[str],
    implementation_module: str,
    module_dependencies: tuple[str, ...],
    *,
    optional_backends: tuple[str, ...] = (),
) -> tuple[OperationCodeDependencies, ...]:
    return tuple(
        OperationCodeDependencies(
            operation,
            implementation_module,
            module_dependencies=module_dependencies,
            optional_backends=optional_backends,
        )
        for operation in operations
    )


DEFAULT_CODE_DEPENDENCIES = CodeDependencyRegistry(
    (
        *_declarations(
            (
                "cohom.claim_graph",
                "cohom.class_of",
                "cohom.coboundaries",
                "cohom.cochain_complex",
                "cohom.cocycles",
                "cohom.cohomology",
                "cohom.corestrict",
                "cohom.corestriction_map",
                "cohom.h0",
                "cohom.h1",
                "cohom.h2",
                "cohom.inflate",
                "cohom.inflation_map",
                "cohom.inflation_restriction",
                "cohom.is_coboundary",
                "cohom.is_cocycle",
                "cohom.restrict",
                "cohom.restriction_map",
                "cohom.transgression",
                "cohom.verification_certificate",
            ),
            "arbogast.cohom",
            ("arbogast.cert", "arbogast.claims", "arbogast.core"),
        ),
        *_declarations(
            (
                "galois.decomposition_quotient_h1",
                "galois.finite_galois_quotient",
                "galois.finite_galois_quotient_certificate",
                "galois.galois_module",
                "galois.kummer_class",
                "galois.local_h1_class",
                "galois.nonabelian_h1",
                "galois.twist_classes",
            ),
            "arbogast.galois",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.cohom",
                "arbogast.core",
                "arbogast.linalg",
                "arbogast.rep",
            ),
        ),
        *_declarations(
            (
                "galois.kummer_space",
                "galois.local_h1",
                "galois.localize",
            ),
            "arbogast.galois",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.core",
                "arbogast.linalg",
            ),
            optional_backends=("pari",),
        ),
        *_declarations(
            (
                "galois.claim",
                "galois.claim_graph",
                "galois.verification_certificate",
            ),
            "arbogast.galois.semantic",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.galois",
            ),
        ),
        *_declarations(
            (
                "arithmetic.aim",
                "arithmetic.cartier_dual",
                "arithmetic.dual_selmer",
                "arithmetic.elementary_descent",
                "arithmetic.local_condition",
                "arithmetic.selmer",
                "arithmetic.unique",
            ),
            "arbogast.arithmetic",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.core",
                "arbogast.galois",
                "arbogast.linalg",
            ),
        ),
        *_declarations(
            ("arithmetic.local_pairing",),
            "arbogast.arithmetic",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.core",
                "arbogast.galois",
                "arbogast.linalg",
            ),
            optional_backends=("pari",),
        ),
        *_declarations(
            (
                "arithmetic.claim",
                "arithmetic.claim_graph",
                "arithmetic.verification_certificate",
            ),
            "arbogast.arithmetic.semantic",
            (
                "arbogast.arithmetic",
                "arbogast.cert",
                "arbogast.claims",
            ),
        ),
        *_declarations(
            (
                "deform.deformation_problem",
                "deform.fixed_lift",
                "deform.frame",
                "deform.gauge",
                "deform.lift",
                "deform.obstructions",
                "deform.rigid",
                "deform.tangent",
                "deform.unique_lift",
            ),
            "arbogast.deform",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.core",
                "arbogast.formats",
                "arbogast.linalg",
            ),
        ),
        *_declarations(
            (
                "deform.equivariant",
                "deform.equivariant_decomposition",
                "deform.invariant_deformations",
            ),
            "arbogast.deform",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.core",
                "arbogast.formats",
                "arbogast.linalg",
                "arbogast.rep",
            ),
        ),
        *_declarations(
            (
                "deform.claim",
                "deform.claim_graph",
                "deform.verification_certificate",
            ),
            "arbogast.deform.semantic",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.deform",
                "arbogast.formats",
            ),
        ),
        *_declarations(
            ("deform.verify_receipt",),
            "arbogast.deform.certificate",
            (
                "arbogast.cert",
                "arbogast.core",
                "arbogast.formats",
                "arbogast.linalg",
            ),
        ),
        *_declarations(
            ("export.json",),
            "arbogast.export",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.formats",
            ),
        ),
        *_declarations(
            ("fleet.plan_pari_arithmetic_task",),
            "arbogast.fleet",
            (
                "arbogast.backends",
                "arbogast.cert",
                "arbogast.formats",
            ),
            optional_backends=("pari",),
        ),
        *_declarations(
            ("fleet.plan_python_certificate_replay_task",),
            "arbogast.fleet",
            (
                "arbogast.cert",
                "arbogast.formats",
            ),
        ),
        *_declarations(
            (
                "hurwitz.apply_braid_word",
                "hurwitz.apply_braid_word_entries",
                "hurwitz.boundary",
                "hurwitz.boundary_incidence",
                "hurwitz.braid_action",
                "hurwitz.braid_distance",
                "hurwitz.claim",
                "hurwitz.claim_graph",
                "hurwitz.collide",
                "hurwitz.components",
                "hurwitz.cusps",
                "hurwitz.hurwitz_move",
                "hurwitz.is_real_tuple",
                "hurwitz.is_totally_real",
                "hurwitz.load_precomputed_nielsen_class",
                "hurwitz.load_m23_exact_dataset",
                "hurwitz.m23_certificates",
                "hurwitz.m23_claim_graph",
                "hurwitz.m23_verification_certificate",
                "hurwitz.nielsen_class",
                "hurwitz.nielsen_tuple",
                "hurwitz.operation_certificate",
                "hurwitz.plan_nielsen_class",
                "hurwitz.pure_braid_word",
                "hurwitz.real_census",
                "hurwitz.real_points",
                "hurwitz.real_structure",
                "hurwitz.real_witnesses",
                "hurwitz.reduced",
                "hurwitz.signed_slot_transform",
                "hurwitz.source_genus",
                "hurwitz.source_genus_result",
                "hurwitz.straight_real_transform",
                "hurwitz.symmetry_from_braid_word",
                "hurwitz.totally_real",
                "hurwitz.verification_certificate",
                "hurwitz.verify_nielsen_certificate_payload",
                "hurwitz.verify_operation_payload",
                "hurwitz.weighted_braid_path",
            ),
            "arbogast.hurwitz",
            (
                "arbogast.cert",
                "arbogast.claims",
                "arbogast.core",
                "arbogast.formats",
            ),
        ),
        *_declarations(
            (
                "linalg.as_dense",
                "linalg.complement",
                "linalg.determinant",
                "linalg.image",
                "linalg.intersection",
                "linalg.inverse",
                "linalg.left_nullspace",
                "linalg.nullspace",
                "linalg.quotient_space",
                "linalg.rank",
                "linalg.row_space",
                "linalg.rref",
                "linalg.solve",
                "linalg.sum_subspaces",
            ),
            "arbogast.linalg",
            ("arbogast.core",),
        ),
        *_declarations(
            (
                "rep.cyclic_group",
                "rep.decompose",
                "rep.fixed_part",
                "rep.isotypic",
                "rep.projector",
                "rep.representation",
                "rep.semisimple",
                "rep.symmetric_group",
                "rep.weight_spaces",
            ),
            "arbogast.rep",
            ("arbogast.linalg",),
        ),
    )
)


__all__ = [
    "DEFAULT_CODE_DEPENDENCIES",
    "CodeDependencyEdge",
    "CodeDependencyError",
    "CodeDependencyGraph",
    "CodeDependencyKind",
    "CodeDependencyLookupError",
    "CodeDependencyRegistry",
    "CodeNode",
    "CodeNodeKind",
    "OperationCodeDependencies",
]
