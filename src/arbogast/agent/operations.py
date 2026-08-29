"""Agent-facing projections of the central semantic operation registry."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from arbogast.formats import OPERATION_DESCRIPTION_SCHEMA, JSONValue


class OperationLookupError(LookupError):
    """Raised when an operation is absent from the semantic registry."""


class SemanticRegistry(Protocol):
    """The minimal central-registry surface consumed by agent tools."""

    def names(self) -> Iterable[str]: ...

    def describe(self, name: str) -> object: ...


_BUILTIN_TYPE_PORTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "cohom.h0": (("FiniteGroup", "Module"), ("H0Result",)),
    "cohom.h1": (("FiniteGroup", "Module"), ("H1Result",)),
    "cohom.h2": (("FiniteGroup", "Module"), ("H2Result",)),
    "hurwitz.nielsen_class": (("FiniteGroup", "ConjugacyClassVector"), ("NielsenClass",)),
    "hurwitz.braid_action": (("NielsenClass",), ("BraidAction",)),
    "hurwitz.components": (("NielsenClass", "BraidAction"), ("ComponentCollection",)),
    "hurwitz.real_points": (("NielsenClass",), ("tuple[NielsenTuple, ...]",)),
    "hurwitz.totally_real": (("NielsenClass",), ("tuple[NielsenTuple, ...]",)),
    "hurwitz.reduced": (("HurwitzComponent",), ("ReducedComponent",)),
    "hurwitz.cusps": (("HurwitzComponent",), ("CuspData",)),
    "hurwitz.boundary": (
        ("NielsenTuple", "HurwitzComponent"),
        ("BoundaryTuple | BoundaryIncidence",),
    ),
}


def _string_item(value: object) -> str:
    if isinstance(value, Mapping):
        code = value.get("code")
        description = value.get("description")
        if code is not None and description is not None:
            return f"{code}: {description}"
        if code is not None:
            return str(code)
    for method_name in ("to_dict", "to_canonical"):
        method = getattr(value, method_name, None)
        if callable(method):
            projected = method()
            if projected is not value:
                return _string_item(projected)
    return str(value)


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        result: list[str] = []
        for name, specification in value.items():
            if isinstance(specification, Mapping):
                type_name = specification.get("type", specification.get("annotation", name))
            else:
                type_name = specification
            result.append(str(type_name))
        return tuple(result)
    if isinstance(value, Sequence):
        result = []
        for item in value:
            if isinstance(item, Mapping):
                type_name = item.get("type", item.get("annotation", item.get("name", item)))
                result.append(_string_item(type_name))
            else:
                result.append(_string_item(item))
        return tuple(result)
    return (str(value),)


def _bundles(value: object) -> tuple[tuple[str, ...], ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError("operation input_bundles must be an array of arrays")
    bundles: list[tuple[str, ...]] = []
    for bundle in value:
        if isinstance(bundle, str) or not isinstance(bundle, Sequence):
            raise TypeError("operation input_bundles must be an array of arrays")
        if any(not isinstance(item, str) for item in bundle):
            raise TypeError("operation input_bundles must contain only strings")
        bundles.append(tuple(bundle))
    return tuple(bundles)


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    for method_name in ("to_dict", "to_canonical", "as_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            projected = method()
            if isinstance(projected, Mapping):
                return projected
    fields = getattr(value, "__dict__", None)
    if isinstance(fields, Mapping):
        return fields
    raise TypeError(f"cannot project semantic operation {type(value).__qualname__}")


@dataclass(frozen=True, slots=True)
class OperationDescription:
    """The complete mathematical contract exposed to machine collaborators."""

    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    preconditions: tuple[str, ...] = ()
    guarantees: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    summary: str = ""
    mathematical_domain: str = ""
    certificate_type: str | None = None
    exact: bool | None = None
    shardable: bool = False
    shard_strategy: str | None = None
    complexity: str | None = None
    examples: tuple[str, ...] = ()
    hazards: tuple[str, ...] = ()
    implemented: bool = True
    input_bundles: tuple[tuple[str, ...], ...] = ()
    schema: str = OPERATION_DESCRIPTION_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("operation name must not be empty")
        for field_name in (
            "inputs",
            "outputs",
            "preconditions",
            "guarantees",
            "failure_modes",
            "examples",
            "hazards",
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"operation {field_name} must contain only non-blank strings")
            object.__setattr__(self, field_name, values)
        bundles = tuple(tuple(bundle) for bundle in self.input_bundles)
        if not bundles and self.inputs:
            bundles = (self.inputs,)
        if any(
            not bundle or any(not isinstance(item, str) or not item.strip() for item in bundle)
            for bundle in bundles
        ):
            raise ValueError(
                "operation input_bundles must contain non-empty tuples of non-blank strings"
            )
        if len(set(bundles)) != len(bundles):
            raise ValueError("operation input_bundles must be unique")
        object.__setattr__(self, "input_bundles", bundles)
        if not isinstance(self.summary, str) or not isinstance(self.mathematical_domain, str):
            raise ValueError("operation summary and mathematical_domain must be strings")
        for field_name in (
            "certificate_type",
            "shard_strategy",
            "complexity",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"operation {field_name} must be a string or null")
        if self.exact is not None and not isinstance(self.exact, bool):
            raise ValueError("operation exact must be a boolean or null")
        if not isinstance(self.shardable, bool):
            raise ValueError("operation shardable must be a boolean")
        if not isinstance(self.implemented, bool):
            raise ValueError("operation implemented must be a boolean")
        if self.schema != OPERATION_DESCRIPTION_SCHEMA:
            raise ValueError("unsupported operation-description schema")

    @property
    def mathematical_guarantees(self) -> tuple[str, ...]:
        return self.guarantees

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "certificate_type": self.certificate_type,
            "complexity": self.complexity,
            "exact": self.exact,
            "examples": list(self.examples),
            "failure_modes": list(self.failure_modes),
            "hazards": list(self.hazards),
            "implemented": self.implemented,
            "input_bundles": [list(bundle) for bundle in self.input_bundles],
            "inputs": list(self.inputs),
            "mathematical_domain": self.mathematical_domain,
            "mathematical_guarantees": list(self.guarantees),
            "name": self.name,
            "outputs": list(self.outputs),
            "preconditions": list(self.preconditions),
            "schema": self.schema,
            "shard_strategy": self.shard_strategy,
            "shardable": self.shardable,
            "summary": self.summary,
        }

    def compact(self) -> OperationDescription:
        """Return a routing-safe description without bulky examples/details."""

        return OperationDescription(
            name=self.name,
            inputs=self.inputs,
            outputs=self.outputs,
            input_bundles=self.input_bundles,
            preconditions=self.preconditions,
            guarantees=self.guarantees,
            failure_modes=self.failure_modes,
            summary=self.summary,
            mathematical_domain=self.mathematical_domain,
            certificate_type=self.certificate_type,
            exact=self.exact,
            shardable=self.shardable,
            shard_strategy=self.shard_strategy,
            hazards=self.hazards,
            implemented=self.implemented,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OperationDescription:
        expected = {
            "certificate_type",
            "complexity",
            "exact",
            "examples",
            "failure_modes",
            "hazards",
            "implemented",
            "input_bundles",
            "inputs",
            "mathematical_domain",
            "mathematical_guarantees",
            "name",
            "outputs",
            "preconditions",
            "schema",
            "shard_strategy",
            "shardable",
            "summary",
        }
        if set(value) != expected:
            raise ValueError("operation description has missing or unknown fields")
        if value["schema"] != OPERATION_DESCRIPTION_SCHEMA:
            raise ValueError("unsupported operation-description schema")

        def strings(name: str) -> tuple[str, ...]:
            items = value[name]
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError(f"operation description {name} must be an array of strings")
            return tuple(items)

        def optional_string(name: str) -> str | None:
            item = value[name]
            if item is not None and not isinstance(item, str):
                raise ValueError(f"operation description {name} must be a string or null")
            return item

        def bundles(name: str) -> tuple[tuple[str, ...], ...]:
            items = value[name]
            if not isinstance(items, list) or any(
                not isinstance(bundle, list) or any(not isinstance(item, str) for item in bundle)
                for bundle in items
            ):
                raise ValueError(
                    "operation description input_bundles must be an array of string arrays"
                )
            return tuple(tuple(bundle) for bundle in items)

        name = value["name"]
        summary = value["summary"]
        domain = value["mathematical_domain"]
        if any(not isinstance(item, str) for item in (name, summary, domain)):
            raise ValueError("operation description scalar labels must be strings")
        exact = value["exact"]
        if exact is not None and not isinstance(exact, bool):
            raise ValueError("operation description exact must be a boolean or null")
        shardable = value["shardable"]
        implemented = value["implemented"]
        if not isinstance(shardable, bool):
            raise ValueError("operation description shardable must be a boolean")
        if not isinstance(implemented, bool):
            raise ValueError("operation description implemented must be a boolean")
        return cls(
            name=name,
            inputs=strings("inputs"),
            outputs=strings("outputs"),
            input_bundles=bundles("input_bundles"),
            preconditions=strings("preconditions"),
            guarantees=strings("mathematical_guarantees"),
            failure_modes=strings("failure_modes"),
            summary=summary,
            mathematical_domain=domain,
            certificate_type=optional_string("certificate_type"),
            exact=exact,
            shardable=shardable,
            shard_strategy=optional_string("shard_strategy"),
            complexity=optional_string("complexity"),
            examples=strings("examples"),
            hazards=strings("hazards"),
            implemented=implemented,
        )

    @classmethod
    def from_semantic(cls, value: object, *, name: str | None = None) -> OperationDescription:
        data = _mapping(value)
        operation_name = name or str(data.get("name", ""))
        contract = data.get("contract")
        contract_data = contract if isinstance(contract, Mapping) else {}

        def first(*keys: str, default: object = None) -> object:
            for key in keys:
                if key in data:
                    return data[key]
                if key in contract_data:
                    return contract_data[key]
            return default

        def boolean(name: str, *, default: bool) -> bool:
            raw = first(name, default=default)
            if not isinstance(raw, bool):
                raise ValueError(f"semantic operation {name} must be a boolean")
            return raw

        def optional_boolean(name: str) -> bool | None:
            raw = first(name, default=None)
            if raw is None:
                return None
            if not isinstance(raw, bool):
                raise ValueError(f"semantic operation {name} must be a boolean or null")
            return raw

        declared_inputs = _strings(first("inputs", "input_types", default=()))
        declared_outputs = _strings(
            first("outputs", "output_types", "output_type", "returns", default=())
        )
        declared_bundles = _bundles(first("input_bundles", default=()))
        builtin_inputs, builtin_outputs = _BUILTIN_TYPE_PORTS.get(operation_name, ((), ()))
        return cls(
            name=operation_name,
            inputs=declared_inputs or builtin_inputs,
            outputs=declared_outputs or builtin_outputs,
            input_bundles=declared_bundles,
            preconditions=_strings(first("preconditions", "requires", default=())),
            guarantees=_strings(
                first("mathematical_guarantees", "guarantees", "ensures", default=())
            ),
            failure_modes=_strings(first("failure_modes", "failures", default=())),
            summary=str(first("summary", "description", default="")),
            mathematical_domain=str(first("mathematical_domain", "domain", default="")),
            certificate_type=(
                None
                if first("certificate_type", "certificate", default=None) is None
                else str(first("certificate_type", "certificate", default=None))
            ),
            exact=optional_boolean("exact"),
            shardable=boolean("shardable", default=False),
            shard_strategy=(
                None
                if first("shard_strategy", default=None) is None
                else str(first("shard_strategy"))
            ),
            complexity=(
                None if first("complexity", default=None) is None else str(first("complexity"))
            ),
            examples=_strings(first("examples", default=())),
            hazards=_strings(first("hazards", default=())),
            implemented=bool(first("implemented", default=False)),
        )


class InMemorySemanticRegistry:
    """Small registry useful for tests and dynamically composed applications."""

    def __init__(self, operations: Iterable[OperationDescription] = ()) -> None:
        self._operations: dict[str, OperationDescription] = {}
        for operation in operations:
            self.register(operation)

    def register(self, operation: OperationDescription, *, replace: bool = False) -> None:
        if operation.name in self._operations and not replace:
            raise ValueError(f"operation {operation.name!r} is already registered")
        self._operations[operation.name] = operation

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._operations))

    def describe(self, name: str) -> OperationDescription:
        try:
            return self._operations[name]
        except KeyError as error:
            raise OperationLookupError(name) from error


_DEFAULT_REGISTRY_CANDIDATES = (
    ("arbogast.specs", "operations"),
    ("arbogast.specs", "operation_registry"),
    ("arbogast.specs.registry", "default_registry"),
    ("arbogast.specs.registry", "operations"),
)


def default_semantic_registry() -> SemanticRegistry:
    """Locate the package's central registry without importing algebra backends."""

    for module_name, attribute in _DEFAULT_REGISTRY_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        registry = getattr(module, attribute, None)
        if registry is not None and hasattr(registry, "describe"):
            return cast(SemanticRegistry, registry)
    return InMemorySemanticRegistry()


def registry_names(registry: object) -> tuple[str, ...]:
    names = getattr(registry, "names", None)
    if callable(names):
        return tuple(sorted(str(name) for name in names()))
    all_operations = getattr(registry, "all", None)
    if callable(all_operations):
        values = all_operations()
        if isinstance(values, Mapping):
            return tuple(sorted(str(name) for name in values))
        return tuple(sorted(str(item.name) for item in values))
    if isinstance(registry, Mapping):
        return tuple(sorted(str(name) for name in registry))
    raise TypeError("semantic registry exposes neither names(), all(), nor a mapping")


def describe_operation(
    name: str,
    registry: object | None = None,
) -> OperationDescription:
    """Describe an operation through the central semantic registry."""

    selected = default_semantic_registry() if registry is None else registry
    describe = getattr(selected, "describe", None)
    try:
        if callable(describe):
            raw = describe(name)
        elif isinstance(selected, Mapping):
            raw = selected[name]
        else:
            getter = getattr(selected, "get", None)
            if not callable(getter):
                raise TypeError("semantic registry has no describe() or get()")
            raw = getter(name)
            if raw is None:
                raise KeyError(name)
    except (KeyError, LookupError) as error:
        raise OperationLookupError(name) from error
    if isinstance(raw, OperationDescription):
        return raw
    description = OperationDescription.from_semantic(raw, name=name)
    function = getattr(selected, "function", None)
    if callable(function):
        try:
            registered = function(name)
        except (KeyError, LookupError, RuntimeError, ValueError):
            registered = None
        if callable(registered):
            data = description.to_dict()
            data["implemented"] = True
            return OperationDescription.from_semantic(data, name=name)
    return description


def operation_descriptions(registry: object | None = None) -> tuple[OperationDescription, ...]:
    selected = default_semantic_registry() if registry is None else registry
    return tuple(describe_operation(name, selected) for name in registry_names(selected))
