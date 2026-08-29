"""Executable mathematical contracts for public operations."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, ParamSpec, TypeVar, cast

from arbogast.cert.canonical import content_address


class OperationSpecError(ValueError):
    """Raised for incomplete contracts or conflicting registrations."""


@dataclass(frozen=True)
class FailureMode:
    """A named way an operation can fail without strengthening its guarantee."""

    code: str
    description: str
    exception: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.description.strip():
            raise OperationSpecError("failure mode code and description cannot be blank")

    def to_canonical(self) -> dict[str, object]:
        return {
            "code": self.code,
            "description": self.description,
            "exception": self.exception,
        }


@dataclass(frozen=True)
class OperationExample:
    """A small contract-level use example."""

    code: str
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise OperationSpecError("operation example code cannot be blank")

    def to_canonical(self) -> dict[str, object]:
        return {"code": self.code, "description": self.description}


@dataclass(frozen=True)
class OperationSpec:
    """Backend-independent mathematical contract discoverable by agents and CLI."""

    name: str
    mathematical_domain: str
    requires: tuple[str, ...]
    ensures: tuple[str, ...]
    exact: bool
    shardable: bool
    complexity: str
    failure_modes: tuple[FailureMode, ...]
    certificate_type: str | None
    examples: tuple[OperationExample, ...]
    shard_strategy: str | None = None
    version: str = "1"
    python_qualified_name: str | None = None
    python_signature: str | None = None
    input_types: tuple[str, ...] = ()
    input_bundles: tuple[tuple[str, ...], ...] = ()
    output_type: str | None = None

    schema_version = "arbogast.operation-spec/v1"

    def __post_init__(self) -> None:
        required_text = {
            "name": self.name,
            "mathematical_domain": self.mathematical_domain,
            "complexity": self.complexity,
            "version": self.version,
        }
        missing = [key for key, value in required_text.items() if not value.strip()]
        if missing:
            raise OperationSpecError(
                f"operation contract fields cannot be blank: {', '.join(missing)}"
            )
        if not isinstance(self.exact, bool):
            raise OperationSpecError("operation exact must be a boolean")
        if not isinstance(self.shardable, bool):
            raise OperationSpecError("operation shardable must be a boolean")
        object.__setattr__(self, "requires", tuple(self.requires))
        object.__setattr__(self, "ensures", tuple(self.ensures))
        object.__setattr__(self, "failure_modes", tuple(self.failure_modes))
        object.__setattr__(self, "examples", tuple(self.examples))
        object.__setattr__(self, "input_types", tuple(self.input_types))
        bundles = tuple(tuple(bundle) for bundle in self.input_bundles)
        if not bundles and self.input_types:
            bundles = (self.input_types,)
        if any(
            not bundle or any(not isinstance(item, str) or not item.strip() for item in bundle)
            for bundle in bundles
        ):
            raise OperationSpecError(
                "operation input_bundles must contain non-empty tuples of non-blank strings"
            )
        if len(set(bundles)) != len(bundles):
            raise OperationSpecError("operation input_bundles must be unique")
        object.__setattr__(self, "input_bundles", bundles)
        if not self.requires or any(not item.strip() for item in self.requires):
            raise OperationSpecError("operation contract requires explicit preconditions")
        if not self.ensures or any(not item.strip() for item in self.ensures):
            raise OperationSpecError("operation contract requires explicit guarantees")
        if not self.failure_modes:
            raise OperationSpecError("operation contract requires explicit failure modes")
        if not self.examples:
            raise OperationSpecError("operation contract requires at least one example")
        if self.shardable and not self.shard_strategy:
            raise OperationSpecError("shardable operations require a shard_strategy")
        if not self.shardable and self.shard_strategy is not None:
            raise OperationSpecError("non-shardable operations cannot advertise a shard_strategy")
        if not self.exact and self.certificate_type is not None:
            # Non-exact operations may emit numerical certificates, but that must be explicit in
            # the type name rather than silently inheriting an exact certificate interface.
            lowered = self.certificate_type.lower()
            if "numer" not in lowered and "heur" not in lowered:
                raise OperationSpecError(
                    "non-exact operation certificate_type must identify numerical/heuristic scope"
                )

    @property
    def digest(self) -> str:
        return content_address(self.to_canonical())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "mathematical_domain": self.mathematical_domain,
            "requires": self.requires,
            "ensures": self.ensures,
            "exact": self.exact,
            "shardable": self.shardable,
            "complexity": self.complexity,
            "failure_modes": self.failure_modes,
            "certificate_type": self.certificate_type,
            "examples": self.examples,
            "shard_strategy": self.shard_strategy,
            "version": self.version,
            "python_qualified_name": self.python_qualified_name,
            "python_signature": self.python_signature,
            "input_types": self.input_types,
            "input_bundles": self.input_bundles,
            "output_type": self.output_type,
        }

    def to_dict(self) -> dict[str, object]:
        return self.to_canonical()


P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True)
class RegisteredOperation:
    spec: OperationSpec
    function: Callable[..., Any] | None = None


class OperationRegistry:
    """Registry keyed by mathematical operation name, not backend function name."""

    def __init__(self) -> None:
        self._operations: dict[str, RegisteredOperation] = {}

    def register(self, spec: OperationSpec, function: Callable[..., Any] | None = None) -> None:
        existing = self._operations.get(spec.name)
        candidate = RegisteredOperation(spec, function)
        if existing is not None:
            if existing == candidate:
                return
            if _unbound_spec(existing.spec) == _unbound_spec(spec):
                if function is None:
                    # Registering the backend-independent catalog after implementations have
                    # already been bound is intentionally idempotent.  Keep the richer bound
                    # contract and its callable.
                    return
                if existing.function is None or existing.function is function:
                    self.bind(spec.name, function)
                    return
            if existing.function is None and existing.spec.to_canonical() == spec.to_canonical():
                self._operations[spec.name] = candidate
                return
            raise OperationSpecError(f"operation already registered: {spec.name}")
        self._operations[spec.name] = candidate

    def register_spec(self, spec: OperationSpec) -> OperationSpec:
        """Register a discoverable contract before its optional implementation is imported."""

        self.register(spec)
        return spec

    def bind(self, name: str, function: Callable[..., Any]) -> None:
        """Bind a loaded implementation to an already registered mathematical contract."""

        registered = self._operations.get(name)
        if registered is None:
            raise OperationSpecError(f"cannot bind unknown operation: {name}")
        if registered.function is not None and registered.function is not function:
            raise OperationSpecError(f"operation already has a different implementation: {name}")
        qualified_name = f"{function.__module__}.{function.__qualname__}"
        signature = str(inspect.signature(function))
        spec = registered.spec
        if spec.python_qualified_name not in (None, qualified_name):
            raise OperationSpecError(
                f"operation {name} names {spec.python_qualified_name!r}, "
                f"but is bound to {qualified_name!r}"
            )
        if spec.python_signature not in (None, signature):
            raise OperationSpecError(
                f"operation {name} advertises signature {spec.python_signature!r}, "
                f"but implementation has {signature!r}"
            )
        bound_spec = replace(
            spec,
            python_qualified_name=qualified_name,
            python_signature=signature,
        )
        self._operations[name] = RegisteredOperation(bound_spec, function)
        existing_contract = getattr(function, "__arbogast_operation__", None)
        if existing_contract not in (None, bound_spec):
            raise OperationSpecError(
                f"callable {qualified_name} is already bound to a different operation"
            )
        cast(Any, function).__arbogast_operation__ = bound_spec

    def implemented(self, name: str) -> bool:
        try:
            return self._operations[name].function is not None
        except KeyError as exc:
            raise OperationSpecError(f"unknown operation: {name}") from exc

    def spec(self, name: str) -> OperationSpec:
        try:
            return self._operations[name].spec
        except KeyError as exc:
            raise OperationSpecError(f"unknown operation: {name}") from exc

    describe = spec

    def function(self, name: str) -> Callable[..., Any]:
        try:
            function = self._operations[name].function
        except KeyError as exc:
            raise OperationSpecError(f"unknown operation: {name}") from exc
        if function is None:
            raise OperationSpecError(f"operation contract has no loaded implementation: {name}")
        return function

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._operations))

    def specs(self) -> tuple[OperationSpec, ...]:
        return tuple(self._operations[name].spec for name in self.names())

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": "arbogast.operation-registry/v1",
            "operations": self.specs(),
        }

    def to_dict(self) -> dict[str, object]:
        return self.to_canonical()


default_operations = OperationRegistry()
operation_registry = default_operations
default_registry = default_operations


def _unbound_spec(spec: OperationSpec) -> OperationSpec:
    """Return the backend-independent portion used for idempotent registration."""

    return replace(spec, python_qualified_name=None, python_signature=None)


FailureModeInput = FailureMode | str | tuple[str, str]
ExampleInput = OperationExample | str | tuple[str, str]


def operation(
    *,
    name: str,
    mathematical_domain: str,
    requires: Sequence[str],
    ensures: Sequence[str],
    exact: bool,
    shardable: bool,
    complexity: str,
    failure_modes: Sequence[FailureModeInput],
    certificate_type: str | type[object] | None,
    examples: Sequence[ExampleInput],
    shard_strategy: str | None = None,
    version: str = "1",
    input_types: Sequence[str] = (),
    input_bundles: Sequence[Sequence[str]] = (),
    output_type: str | None = None,
    registry: OperationRegistry = default_operations,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Attach and register a complete mathematical operation contract."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        qualified = f"{function.__module__}.{function.__qualname__}"
        spec = OperationSpec(
            name=name,
            mathematical_domain=mathematical_domain,
            requires=tuple(requires),
            ensures=tuple(ensures),
            exact=exact,
            shardable=shardable,
            complexity=complexity,
            failure_modes=tuple(_failure_mode(item) for item in failure_modes),
            certificate_type=_type_name(certificate_type),
            examples=tuple(_example(item) for item in examples),
            shard_strategy=shard_strategy,
            version=version,
            python_qualified_name=qualified,
            python_signature=str(inspect.signature(function)),
            input_types=tuple(input_types),
            input_bundles=tuple(tuple(bundle) for bundle in input_bundles),
            output_type=output_type,
        )
        registry.register(spec, function)
        cast(Any, function).__arbogast_operation__ = spec
        return function

    return decorate


def get_operation_spec(
    value: str | Callable[..., object],
    *,
    registry: OperationRegistry = default_operations,
) -> OperationSpec:
    """Resolve a contract from its mathematical name or decorated callable."""

    if isinstance(value, str):
        return registry.spec(value)
    spec = getattr(value, "__arbogast_operation__", None)
    if not isinstance(spec, OperationSpec):
        raise OperationSpecError(f"callable is not a registered operation: {value!r}")
    return spec


def _failure_mode(value: FailureModeInput) -> FailureMode:
    if isinstance(value, FailureMode):
        return value
    if isinstance(value, str):
        return FailureMode(value, value.replace("_", " "))
    return FailureMode(value[0], value[1])


def _example(value: ExampleInput) -> OperationExample:
    if isinstance(value, OperationExample):
        return value
    if isinstance(value, str):
        return OperationExample(value)
    return OperationExample(value[0], value[1])


def _type_name(value: str | type[object] | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return f"{value.__module__}.{value.__qualname__}"


__all__ = [
    "FailureMode",
    "OperationExample",
    "OperationRegistry",
    "OperationSpec",
    "OperationSpecError",
    "RegisteredOperation",
    "default_operations",
    "default_registry",
    "get_operation_spec",
    "operation",
    "operation_registry",
]
