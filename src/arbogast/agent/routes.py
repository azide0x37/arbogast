"""Deterministic capability graph and shortest semantic routes."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import product
from typing import Any

from arbogast.formats import ROUTE_SCHEMA, JSONValue

from .operations import OperationDescription


class CapabilityRouteError(LookupError):
    """Raised when no implemented capability route connects two types."""


@dataclass(frozen=True, order=True, slots=True)
class CapabilityEdge:
    """One operation-induced hyperedge with conjunctive required inputs."""

    required_inputs: tuple[str, ...]
    target: str
    operation: str
    implemented: bool = True

    def __post_init__(self) -> None:
        required_inputs = (
            (self.required_inputs,)
            if isinstance(self.required_inputs, str)
            else tuple(self.required_inputs)
        )
        object.__setattr__(self, "required_inputs", required_inputs)
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (*required_inputs, self.target, self.operation)
        ):
            raise ValueError("capability edges require non-blank inputs, target, and operation")
        if not required_inputs:
            raise ValueError("capability edges require at least one input")
        if not isinstance(self.implemented, bool):
            raise ValueError("capability edge implemented must be a boolean")

    @property
    def source(self) -> str:
        """Return the legacy display label for this edge's complete input bundle."""

        if len(self.required_inputs) == 1:
            return self.required_inputs[0]
        return "(" + " & ".join(self.required_inputs) + ")"

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "implemented": self.implemented,
            "operation": self.operation,
            "required_inputs": list(self.required_inputs),
            "source": self.source,
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CapabilityEdge:
        expected = {"implemented", "operation", "required_inputs", "source", "target"}
        if set(value) != expected:
            raise ValueError("capability edge has missing or unknown fields")
        source = value["source"]
        required_inputs = value["required_inputs"]
        target = value["target"]
        operation = value["operation"]
        implemented = value["implemented"]
        if any(not isinstance(item, str) for item in (source, target, operation)):
            raise ValueError("capability edge labels must be strings")
        if not isinstance(required_inputs, list) or any(
            not isinstance(item, str) for item in required_inputs
        ):
            raise ValueError("capability edge required_inputs must be an array of strings")
        if not isinstance(implemented, bool):
            raise ValueError("capability edge implemented must be a boolean")
        result = cls(tuple(required_inputs), target, operation, implemented)
        if source != result.source:
            raise ValueError("capability edge source does not match its required input bundle")
        return result


@dataclass(frozen=True, slots=True)
class CapabilityRoute:
    """A shortest deterministic route between semantic types."""

    source: str
    target: str
    steps: tuple[CapabilityEdge, ...]
    schema: str = ROUTE_SCHEMA

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip() for value in (self.source, self.target)
        ):
            raise ValueError("capability route endpoints must be non-blank strings")
        if self.schema != ROUTE_SCHEMA:
            raise ValueError("unsupported capability-route schema")
        steps = tuple(self.steps)
        if any(not isinstance(step, CapabilityEdge) for step in steps):
            raise ValueError("capability route steps must be capability edges")
        object.__setattr__(self, "steps", steps)
        available = {self.source}
        for step in steps:
            missing = set(step.required_inputs) - available
            if missing:
                raise ValueError(
                    "capability route step has unavailable required inputs: "
                    + ", ".join(sorted(missing))
                )
            available.add(step.target)
        if self.target not in available:
            raise ValueError("capability route does not reach target")

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(step.operation for step in self.steps)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": self.schema,
            "source": self.source,
            "steps": [step.to_dict() for step in self.steps],
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CapabilityRoute:
        expected = {"schema", "source", "steps", "target"}
        if set(value) != expected:
            raise ValueError("capability route has missing or unknown fields")
        if value["schema"] != ROUTE_SCHEMA:
            raise ValueError("unsupported capability-route schema")
        source = value["source"]
        target = value["target"]
        steps = value["steps"]
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("capability route endpoints must be strings")
        if not isinstance(steps, list) or any(not isinstance(item, Mapping) for item in steps):
            raise ValueError("capability route steps must be an array of objects")
        return cls(source, target, tuple(CapabilityEdge.from_dict(item) for item in steps))


class CapabilityGraph:
    """A stable graph generated from operation contracts, not code imports."""

    def __init__(self, edges: Iterable[CapabilityEdge] = ()) -> None:
        self._edges = tuple(
            sorted(
                set(edges),
                key=lambda edge: (edge.required_inputs, edge.operation, edge.target),
            )
        )

    @classmethod
    def from_operations(cls, operations: Iterable[OperationDescription]) -> CapabilityGraph:
        edges: list[CapabilityEdge] = []
        for operation in operations:
            for declared_bundle in operation.input_bundles:
                alternatives = tuple(_type_alternatives(item) for item in declared_bundle)
                for required_inputs in product(*alternatives):
                    for target in _targets_for_inputs(operation, required_inputs):
                        edges.append(
                            CapabilityEdge(
                                required_inputs=required_inputs,
                                target=target,
                                operation=operation.name,
                                implemented=operation.implemented,
                            )
                        )
        return cls(edges)

    @property
    def edges(self) -> tuple[CapabilityEdge, ...]:
        return self._edges

    @property
    def types(self) -> tuple[str, ...]:
        sources = {source for edge in self._edges for source in edge.required_inputs}
        targets = {edge.target for edge in self._edges}
        return tuple(sorted(sources | targets))

    def route(
        self,
        source: str,
        target: str,
        *,
        include_unimplemented: bool = False,
    ) -> CapabilityRoute:
        if source == target:
            return CapabilityRoute(source, target, ())
        initial = frozenset((source,))
        queue: deque[tuple[frozenset[str], tuple[CapabilityEdge, ...]]] = deque([(initial, ())])
        visited = {initial}
        while queue:
            available, path = queue.popleft()
            for edge in self._edges:
                if not edge.implemented and not include_unimplemented:
                    continue
                if edge.target in available:
                    continue
                if not set(edge.required_inputs).issubset(available):
                    continue
                candidate = (*path, edge)
                if edge.target == target:
                    return CapabilityRoute(source, target, candidate)
                next_available = available | {edge.target}
                if next_available not in visited:
                    visited.add(next_available)
                    queue.append((next_available, candidate))
        raise CapabilityRouteError(f"no capability route from {source!r} to {target!r}")

    def missing_frontier(self, source: str) -> tuple[CapabilityEdge, ...]:
        """Return unimplemented arrows reachable from implemented capabilities."""

        reachable = {source}
        changed = True
        while changed:
            changed = False
            for edge in self._edges:
                if (
                    edge.implemented
                    and edge.target not in reachable
                    and set(edge.required_inputs).issubset(reachable)
                ):
                    reachable.add(edge.target)
                    changed = True
        return tuple(
            edge
            for edge in self._edges
            if set(edge.required_inputs).issubset(reachable) and not edge.implemented
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "edges": [edge.to_dict() for edge in self.edges],
            "types": list(self.types),
        }


def _type_alternatives(value: str) -> tuple[str, ...]:
    """Expand the catalog's explicit ``A | B`` semantic union notation.

    Operation descriptions retain their published display strings.  Only the
    routing graph expands alternatives, so a concrete ``FinitePlace`` can use
    an operation declared for ``FinitePlace | InfinitePlace`` without making
    the union label itself a fictitious prerequisite.
    """

    alternatives = tuple(item.strip() for item in value.split("|"))
    if any(not item for item in alternatives):
        raise ValueError(f"malformed semantic type union: {value!r}")
    return alternatives


_DEPENDENT_OUTPUTS_BY_SOURCE: dict[str, dict[str, tuple[str, ...]]] = {
    "cohom.corestrict": {
        "Cochain": ("Cochain",),
        "CohomologyClass": ("CohomologyClass",),
    },
    "galois.localize": {
        "KummerSpace": ("LocalizationMap", "Unsupported", "PariArithmeticResult"),
        "KummerClass": ("LocalH1Class", "Unsupported", "PariArithmeticResult"),
    },
}

_DEPENDENT_OUTPUTS_BY_INPUTS: dict[str, dict[tuple[str, ...], tuple[str, ...]]] = {
    "deform.lift": {
        ("LiftDatum",): ("LiftFamily", "LiftObstructed"),
        ("DeformationComplex", "SmallExtension"): ("UnsupportedDeformation",),
        ("DeformationPresentation", "SmallExtension"): ("UnsupportedDeformation",),
        ("DeformationProblem", "SmallExtension"): ("UnsupportedDeformation",),
        ("DeformationComplex", "SmallExtension", "Vector"): (
            "LiftFamily",
            "LiftObstructed",
        ),
        ("DeformationPresentation", "SmallExtension", "Vector"): (
            "LiftFamily",
            "LiftObstructed",
        ),
        ("DeformationProblem", "SmallExtension", "Vector"): (
            "LiftFamily",
            "LiftObstructed",
        ),
        (
            "DeformationComplex",
            "SmallExtension",
            "Vector",
            "Vector",
            "DenseMatrix",
            "DenseMatrix",
            "str",
        ): ("LiftFamily", "LiftObstructed"),
        (
            "DeformationPresentation",
            "SmallExtension",
            "Vector",
            "Vector",
            "DenseMatrix",
            "DenseMatrix",
            "str",
        ): ("LiftFamily", "LiftObstructed"),
        (
            "DeformationProblem",
            "SmallExtension",
            "Vector",
            "Vector",
            "DenseMatrix",
            "DenseMatrix",
            "str",
        ): ("LiftFamily", "LiftObstructed"),
    },
    "deform.unique_lift": {
        ("LiftDatum",): ("UniqueLift", "NonUniqueLift", "LiftObstructed"),
        ("LiftFamily",): ("UniqueLift", "NonUniqueLift"),
        ("LiftObstructed",): ("LiftObstructed",),
        ("LiftUnknown",): ("LiftUnknown",),
        ("UnsupportedDeformation",): ("UnsupportedDeformation",),
        ("DeformationComplex", "SmallExtension"): ("UnsupportedDeformation",),
        ("DeformationPresentation", "SmallExtension"): ("UnsupportedDeformation",),
        ("DeformationProblem", "SmallExtension"): ("UnsupportedDeformation",),
        ("DeformationComplex", "SmallExtension", "Vector"): (
            "UniqueLift",
            "NonUniqueLift",
            "LiftObstructed",
        ),
        ("DeformationPresentation", "SmallExtension", "Vector"): (
            "UniqueLift",
            "NonUniqueLift",
            "LiftObstructed",
        ),
        ("DeformationProblem", "SmallExtension", "Vector"): (
            "UniqueLift",
            "NonUniqueLift",
            "LiftObstructed",
        ),
        (
            "DeformationComplex",
            "SmallExtension",
            "Vector",
            "Vector",
            "DenseMatrix",
            "DenseMatrix",
            "str",
        ): ("UniqueLift", "NonUniqueLift", "LiftObstructed"),
        (
            "DeformationPresentation",
            "SmallExtension",
            "Vector",
            "Vector",
            "DenseMatrix",
            "DenseMatrix",
            "str",
        ): ("UniqueLift", "NonUniqueLift", "LiftObstructed"),
        (
            "DeformationProblem",
            "SmallExtension",
            "Vector",
            "Vector",
            "DenseMatrix",
            "DenseMatrix",
            "str",
        ): ("UniqueLift", "NonUniqueLift", "LiftObstructed"),
    },
    "deform.equivariant_decomposition": {
        ("EquivariantDeformation",): ("UnsupportedDeformation",),
        ("EquivariantDeformation", "ProjectorMapping"): ("EquivariantDecomposition",),
    },
    "deform.fixed_lift": {
        ("LiftDatum",): ("LiftObstructed", "LiftUnknown"),
        ("LiftFamily",): ("LiftUnknown",),
        ("LiftObstructed",): ("LiftObstructed",),
        ("LiftUnknown",): ("LiftUnknown",),
        ("UnsupportedDeformation",): ("UnsupportedDeformation",),
        ("LiftDatum", "LiftEndomorphism"): ("LiftObstructed", "LiftUnknown"),
        ("LiftFamily", "LiftEndomorphism"): ("LiftUnknown",),
        ("LiftObstructed", "LiftEndomorphism"): ("LiftObstructed",),
        ("LiftUnknown", "LiftEndomorphism"): ("LiftUnknown",),
        ("UnsupportedDeformation", "LiftEndomorphism"): ("UnsupportedDeformation",),
        ("LiftDatum", "LiftEndomorphism", "ContractionCertificate"): (
            "FixedLift",
            "LiftObstructed",
        ),
        ("LiftDatum", "LiftEndomorphism", "int"): ("FixedLift", "LiftObstructed"),
        ("LiftFamily", "LiftEndomorphism", "ContractionCertificate"): ("FixedLift",),
        ("LiftFamily", "LiftEndomorphism", "int"): ("FixedLift",),
        ("LiftObstructed", "LiftEndomorphism", "ContractionCertificate"): ("LiftObstructed",),
        ("LiftObstructed", "LiftEndomorphism", "int"): ("LiftObstructed",),
        ("LiftUnknown", "LiftEndomorphism", "ContractionCertificate"): ("LiftUnknown",),
        ("LiftUnknown", "LiftEndomorphism", "int"): ("LiftUnknown",),
        (
            "UnsupportedDeformation",
            "LiftEndomorphism",
            "ContractionCertificate",
        ): ("UnsupportedDeformation",),
        ("UnsupportedDeformation", "LiftEndomorphism", "int"): ("UnsupportedDeformation",),
    },
}


def _targets_for_inputs(
    operation: OperationDescription,
    required_inputs: tuple[str, ...],
) -> tuple[str, ...]:
    """Correlate dependent return types instead of inventing a union cross-product."""

    declared_targets: list[str] = []
    for output in operation.outputs:
        declared_targets.extend(_type_alternatives(output))
    declared = tuple(declared_targets)
    by_inputs = _DEPENDENT_OUTPUTS_BY_INPUTS.get(operation.name)
    if by_inputs is not None:
        try:
            selected = by_inputs[required_inputs]
        except KeyError as error:
            raise ValueError(
                f"dependent capability operation {operation.name!r} has no route for "
                f"{required_inputs!r}"
            ) from error
        missing = set(selected) - set(declared)
        if missing:
            raise ValueError(
                f"dependent capability operation {operation.name!r} omits declared targets: "
                + ", ".join(sorted(missing))
            )
        return selected
    by_source = _DEPENDENT_OUTPUTS_BY_SOURCE.get(operation.name)
    if by_source is None:
        return declared
    source = required_inputs[0]
    try:
        selected = by_source[source]
    except KeyError as error:
        raise ValueError(
            f"dependent capability operation {operation.name!r} has no route for {source!r}"
        ) from error
    missing = set(selected) - set(declared)
    if missing:
        raise ValueError(
            f"dependent capability operation {operation.name!r} omits declared targets: "
            + ", ".join(sorted(missing))
        )
    return selected
