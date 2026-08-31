"""Trusted runtime resolution for named fleet operations.

Fleet task documents contain an operation *name*.  They never contain import
paths, pickles, source text, or another representation of executable code.
This registry is the explicit trust boundary that binds such a persisted name
to a callable ``plan/run/reduce`` implementation in the current process.
"""

from __future__ import annotations

import hashlib
import inspect
import marshal
from collections.abc import Callable, Iterable, Mapping
from dataclasses import fields, is_dataclass
from threading import RLock
from types import (
    BuiltinFunctionType,
    BuiltinMethodType,
    CodeType,
    FunctionType,
    MethodType,
    ModuleType,
)
from typing import TYPE_CHECKING, cast

from arbogast.formats import JSONValue, canonical_sha256, normalize_json

if TYPE_CHECKING:
    from .execution import FleetOperation


class FleetOperationRegistryError(RuntimeError):
    """Base class for trusted fleet-operation registry failures."""


class DuplicateFleetOperationError(FleetOperationRegistryError):
    """Raised when a name is rebound to a different implementation."""


class UnknownFleetOperationError(FleetOperationRegistryError, LookupError):
    """Raised when no trusted runtime implementation has been registered."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"no trusted fleet operation is registered for {name!r}; "
            "serialized task data never loads callables"
        )


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name or name != name.strip():
        raise FleetOperationRegistryError(
            "fleet operation names must be non-empty canonical strings"
        )
    return name


def _validate_operation(operation: object) -> None:
    missing = tuple(
        method
        for method in ("plan", "run", "reduce")
        if not callable(getattr(operation, method, None))
    )
    if missing:
        names = ", ".join(missing)
        raise FleetOperationRegistryError(
            f"fleet operation implementation is missing callable methods: {names}"
        )


_REQUIRED_METHODS = ("plan", "run", "reduce")
_OPTIONAL_METHODS = ("verify", "resume")
_FUNCTIONAL_CALLBACKS = {
    "plan": "planner",
    "run": "runner",
    "reduce": "reducer",
    "verify": "verifier",
    "resume": "resumer",
}


def _sha256(value: object) -> str:
    return f"sha256:{canonical_sha256(value)}"


def _stable_code(code: CodeType) -> CodeType:
    """Remove filesystem and source-line coordinates from a Python code object."""

    constants = tuple(
        _stable_code(item) if isinstance(item, CodeType) else item for item in code.co_consts
    )
    return code.replace(co_consts=constants, co_filename="", co_firstlineno=1)


def _source_identity(value: object) -> tuple[str | None, str | None]:
    """Return a relocation-stable source label and hash without importing code."""

    module = getattr(value, "__module__", None)
    try:
        filename = inspect.getsourcefile(cast(Callable[..., object], value))
    except TypeError:
        filename = None
    source_label = None
    if isinstance(module, str) and module:
        basename = (
            filename.replace("\\", "/").rsplit("/", 1)[-1]
            if isinstance(filename, str) and filename
            else "<builtin-or-extension>"
        )
        source_label = f"{module}:{basename}"
    try:
        source = inspect.getsource(cast(Callable[..., object], value))
    except (OSError, TypeError):
        source = None
    source_digest = (
        "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
        if source is not None
        else None
    )
    return source_label, source_digest


def _reference_identity(
    value: object,
    *,
    active: dict[int, str],
    path: str,
) -> tuple[JSONValue, bool, str | None]:
    """Project one referenced value without invoking user-controlled behavior."""

    if value is None or type(value) in (bool, int, str):
        return cast(JSONValue, value), True, None

    object_id = id(value)
    if object_id in active:
        return {"$cycle": active[object_id]}, True, None

    value_type = type(value)
    if value_type in (FunctionType, MethodType):
        identity, valid, reason = _callable_identity(
            value,
            _active=active,
            _anchor=path,
            _bind_references=False,
        )
        return {"$function": identity}, valid, reason

    if value_type in (BuiltinFunctionType, BuiltinMethodType):
        module = getattr(value, "__module__", None)
        qualname = getattr(value, "__qualname__", None)
        if not isinstance(module, str) or not module or not isinstance(qualname, str):
            return {}, False, f"{path} has no stable builtin callable identity"
        source, source_sha256 = _source_identity(value)
        return (
            {
                "$builtin": f"{module}.{qualname}",
                "source": source,
                "source_sha256": source_sha256,
            },
            True,
            None,
        )

    if issubclass(value_type, type):
        module = type.__getattribute__(value, "__module__")
        qualname = type.__getattribute__(value, "__qualname__")
        if not isinstance(module, str) or not module or not isinstance(qualname, str):
            return {}, False, f"{path} has no stable class identity"
        return (
            {
                "$class": f"{module}.{qualname}",
                "source": f"{module}:<class>",
                "source_sha256": None,
            },
            True,
            None,
        )

    if issubclass(value_type, ModuleType):
        name = ModuleType.__getattribute__(value, "__name__")
        if not isinstance(name, str) or not name:
            return {}, False, f"{path} has no stable module identity"
        filename = ModuleType.__getattribute__(value, "__dict__").get("__file__")
        basename = (
            filename.replace("\\", "/").rsplit("/", 1)[-1]
            if isinstance(filename, str) and filename
            else None
        )
        return {"$module": name, "source": basename}, True, None

    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(not isinstance(key, str) for key in mapping):
            return {}, False, f"{path} mapping has a non-string key"
        string_mapping = cast(dict[str, object], mapping)
        active[object_id] = path
        projected: dict[str, JSONValue] = {}
        reasons: list[str] = []
        valid = True
        try:
            for key in sorted(string_mapping):
                item, item_valid, reason = _reference_identity(
                    string_mapping[key],
                    active=active,
                    path=f"{path}.{key}",
                )
                projected[key] = item
                valid = valid and item_valid
                if reason is not None:
                    reasons.append(reason)
        finally:
            active.pop(object_id, None)
        return {"$mapping": projected}, valid, "; ".join(reasons) or None

    if type(value) in (list, tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        active[object_id] = path
        projected_items: list[JSONValue] = []
        reasons = []
        valid = True
        try:
            for index, item_value in enumerate(sequence):
                item, item_valid, reason = _reference_identity(
                    item_value,
                    active=active,
                    path=f"{path}[{index}]",
                )
                projected_items.append(item)
                valid = valid and item_valid
                if reason is not None:
                    reasons.append(reason)
        finally:
            active.pop(object_id, None)
        tag = "$tuple" if type(value) is tuple else "$list"
        return {tag: projected_items}, valid, "; ".join(reasons) or None

    if type(value) in (set, frozenset):
        unordered = cast(set[object] | frozenset[object], value)
        projected_items = []
        for index, item_value in enumerate(unordered):
            item, item_valid, reason = _reference_identity(
                item_value,
                active=active,
                path=f"{path}{{{index}}}",
            )
            if not item_valid:
                return {}, False, reason
            projected_items.append(item)
        projected_items.sort(key=canonical_sha256)
        tag = "$frozenset" if type(value) is frozenset else "$set"
        return {tag: projected_items}, True, None

    return (
        {},
        False,
        f"{path} has unsupported referenced value type "
        f"{type(value).__module__}.{type(value).__qualname__}",
    )


def _callable_identity(
    function: object,
    *,
    _active: dict[int, str] | None = None,
    _anchor: str | None = None,
    _bind_references: bool = True,
) -> tuple[dict[str, JSONValue], bool, str | None]:
    """Describe code and every effective global/nonlocal value it references."""

    function_type = type(function)
    if function_type not in (FunctionType, MethodType):
        type_module = type.__getattribute__(function_type, "__module__")
        type_qualname = type.__getattribute__(function_type, "__qualname__")
        return (
            {
                "module": type_module if isinstance(type_module, str) else None,
                "qualname": type_qualname if isinstance(type_qualname, str) else None,
                "source": None,
                "source_sha256": None,
                "code_sha256": None,
                "bound_values_digest": None,
                "references": {"globals": {}, "nonlocals": {}, "unbound": []},
            },
            False,
            "callable implementation is not a Python function or bound method",
        )
    target = cast(MethodType, function).__func__ if function_type is MethodType else function
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    references: dict[str, JSONValue] = {
        "globals": {},
        "nonlocals": {},
        "unbound": [],
    }
    identity: dict[str, JSONValue] = {
        "module": module if isinstance(module, str) else None,
        "qualname": qualname if isinstance(qualname, str) else None,
        "source": None,
        "source_sha256": None,
        "code_sha256": None,
        "bound_values_digest": None,
        "references": references,
    }
    code = getattr(target, "__code__", None)
    if not isinstance(module, str) or not module or not isinstance(qualname, str) or not qualname:
        return identity, False, "callable has no stable module and qualified name"
    if not isinstance(code, CodeType):
        return identity, False, "callable has no inspectable Python code object"

    active = {} if _active is None else _active
    anchor = _anchor or f"function:{module}.{qualname}"
    object_id = id(target)
    active[object_id] = anchor
    reasons: list[str] = []
    certifiable = True
    try:
        identity["source"], identity["source_sha256"] = _source_identity(target)
        identity["code_sha256"] = (
            "sha256:" + hashlib.sha256(marshal.dumps(_stable_code(code))).hexdigest()
        )

        bound_values: dict[str, JSONValue] = {}
        defaults = getattr(target, "__defaults__", None)
        if defaults:
            projected, valid, reason = _reference_identity(
                defaults,
                active=active,
                path=f"{anchor}.defaults",
            )
            bound_values["defaults"] = projected
            certifiable = certifiable and valid
            if reason is not None:
                reasons.append(reason)
        keyword_defaults = getattr(target, "__kwdefaults__", None)
        if keyword_defaults:
            projected, valid, reason = _reference_identity(
                keyword_defaults,
                active=active,
                path=f"{anchor}.keyword_defaults",
            )
            bound_values["keyword_defaults"] = projected
            certifiable = certifiable and valid
            if reason is not None:
                reasons.append(reason)
        closure = getattr(target, "__closure__", None)
        if closure:
            try:
                closure_values = tuple(cell.cell_contents for cell in closure)
            except ValueError:
                return identity, False, "callable contains an empty closure cell"
            projected, valid, reason = _reference_identity(
                closure_values,
                active=active,
                path=f"{anchor}.closure",
            )
            bound_values["closure"] = projected
            certifiable = certifiable and valid
            if reason is not None:
                reasons.append(reason)
        identity["bound_values_digest"] = _sha256(bound_values)

        if _bind_references:
            closure_variables = inspect.getclosurevars(cast(Callable[..., object], target))
            for group_name, group in (
                ("globals", closure_variables.globals),
                ("nonlocals", closure_variables.nonlocals),
            ):
                projected_group: dict[str, JSONValue] = {}
                for name in sorted(group):
                    projected, valid, reason = _reference_identity(
                        group[name],
                        active=active,
                        path=f"{anchor}.{group_name}.{name}",
                    )
                    projected_group[name] = projected
                    certifiable = certifiable and valid
                    if reason is not None:
                        reasons.append(reason)
                references[group_name] = projected_group
            references["unbound"] = [
                cast(JSONValue, name) for name in sorted(closure_variables.unbound)
            ]
    finally:
        active.pop(object_id, None)
    return identity, certifiable, "; ".join(reasons) or None


def _type_identity(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _effective_method(operation: object, method: str) -> object | None:
    """Return the executable behind a protocol method, including adapters."""

    if _type_identity(operation) == "arbogast.fleet.execution.FunctionalOperation":
        callback = getattr(operation, _FUNCTIONAL_CALLBACKS[method], None)
        return callback if callable(callback) else None
    candidate = getattr(operation, method, None)
    return candidate if callable(candidate) else None


def _operation_state(
    operation: object,
) -> tuple[dict[str, JSONValue], bool, tuple[str, ...]]:
    """Bind canonical instance configuration not already represented by methods."""

    raw: dict[str, object] = {}
    if is_dataclass(operation):
        raw = {item.name: getattr(operation, item.name) for item in fields(operation)}
    elif hasattr(operation, "__dict__"):
        raw = dict(vars(operation))
    else:
        slots: set[str] = set()
        for value_type in type(operation).__mro__:
            declared = value_type.__dict__.get("__slots__", ())
            if isinstance(declared, str):
                slots.add(declared)
            else:
                slots.update(declared)
        raw = {
            name: getattr(operation, name)
            for name in sorted(slots - {"__dict__", "__weakref__"})
            if hasattr(operation, name)
        }

    values: dict[str, object] = {}
    callbacks: dict[str, JSONValue] = {}
    reasons: list[str] = []
    certifiable = True
    effective = {
        id(value)
        for method in (*_REQUIRED_METHODS, *_OPTIONAL_METHODS)
        if (value := _effective_method(operation, method)) is not None
    }
    for name, value in sorted(raw.items()):
        if callable(value):
            if id(value) in effective:
                continue
            identity, valid, reason = _callable_identity(value)
            callbacks[name] = identity
            if not valid:
                certifiable = False
                reasons.append(f"state callback {name}: {reason}")
        else:
            values[name] = value
    try:
        normalized_values = normalize_json(values)
    except (TypeError, ValueError) as error:
        normalized_values = {}
        certifiable = False
        reasons.append(f"operation state is not canonical JSON: {error}")
    if not isinstance(normalized_values, dict):  # pragma: no cover - construction invariant
        raise FleetOperationRegistryError("operation state did not normalize to an object")
    return (
        {"callbacks": callbacks, "values": normalized_values},
        certifiable,
        tuple(reasons),
    )


def _operation_manifest_entry(name: str, operation: object) -> dict[str, JSONValue]:
    optional = tuple(
        method for method in _OPTIONAL_METHODS if _effective_method(operation, method) is not None
    )
    closure_verifiers: tuple[str, ...] = ()
    if _type_identity(operation) == "arbogast.fleet.execution.FunctionalOperation":
        declared = object.__getattribute__(operation, "closure_verifiers")
        if not isinstance(declared, tuple) or any(
            not isinstance(item, str) or not item or item != item.strip() for item in declared
        ):
            raise FleetOperationRegistryError(
                f"fleet operation {name!r} has invalid closure verifier identities"
            )
        closure_verifiers = declared
    contract: dict[str, JSONValue] = {
        "schema": "arbogast.fleet.operation-contract.v1",
        "required_methods": list(_REQUIRED_METHODS),
        "optional_methods": list(optional),
        "closure_verifiers": list(closure_verifiers),
    }
    method_identities: dict[str, JSONValue] = {}
    certifiable = True
    reasons: list[str] = []
    for method in (*_REQUIRED_METHODS, *optional):
        identity, valid, reason = _callable_identity(_effective_method(operation, method))
        method_identities[method] = identity
        if not valid:
            certifiable = False
            reasons.append(f"{method}: {reason}")
    state, state_valid, state_reasons = _operation_state(operation)
    certifiable = certifiable and state_valid
    reasons.extend(state_reasons)
    implementation: dict[str, JSONValue] = {
        "type": _type_identity(operation),
        "methods": method_identities,
        "state": state,
    }
    return {
        "name": name,
        "contract": contract,
        "contract_digest": _sha256(contract),
        "implementation": implementation,
        "implementation_digest": _sha256(implementation),
        "certifiable": certifiable,
        "reason": None if certifiable else "; ".join(reasons),
    }


class FleetOperationRegistry:
    """A thread-safe, fail-closed mapping from names to trusted callables.

    Registration is idempotent for the exact same object and rejects rebinding
    to a different object.  :meth:`to_dict` intentionally exposes only names;
    it is diagnostic metadata, not a deserialization format for callables.
    """

    schema = "arbogast.fleet.operation-registry.v1"

    def __init__(
        self,
        operations: Mapping[str, FleetOperation] | None = None,
    ) -> None:
        self._lock = RLock()
        self._operations: dict[str, FleetOperation] = {}
        for name, operation in (operations or {}).items():
            self.register(name, operation)

    def register(self, name: str, operation: FleetOperation) -> FleetOperation:
        """Bind ``name`` to one trusted runtime implementation."""

        canonical_name = _validate_name(name)
        _validate_operation(operation)
        with self._lock:
            current = self._operations.get(canonical_name)
            if current is not None and current is not operation:
                raise DuplicateFleetOperationError(
                    f"fleet operation {canonical_name!r} is already registered"
                )
            self._operations[canonical_name] = operation
        return operation

    def resolve(self, name: str) -> FleetOperation:
        """Resolve a persisted operation name through this trusted registry."""

        canonical_name = _validate_name(name)
        with self._lock:
            try:
                return self._operations[canonical_name]
            except KeyError as error:
                raise UnknownFleetOperationError(canonical_name) from error

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._operations))

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        with self._lock:
            return name in self._operations

    def __len__(self) -> int:
        with self._lock:
            return len(self._operations)

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a non-executable diagnostic projection."""

        return {"names": list(self.names()), "schema": self.schema}

    def readiness_manifest(
        self,
        names: Iterable[str] | None = None,
    ) -> dict[str, JSONValue]:
        """Bind selected operation contracts to their executable identities.

        This is a readiness-evidence projection, not a deserialization format:
        it contains no import target and never executes a registered operation.
        The manifest digest covers every field except the digest itself.
        """

        if isinstance(names, str):
            raise FleetOperationRegistryError("manifest names must be an iterable of names")
        selected = self.names() if names is None else tuple(_validate_name(name) for name in names)
        if len(selected) != len(set(selected)):
            raise FleetOperationRegistryError("manifest names must be unique")
        selected = tuple(sorted(selected))
        with self._lock:
            operations: list[tuple[str, FleetOperation]] = []
            for name in selected:
                operation = self._operations.get(name)
                if operation is None:
                    raise UnknownFleetOperationError(name)
                operations.append((name, operation))
        payload: dict[str, JSONValue] = {
            "schema": "arbogast.fleet.operation-registry-manifest.v1",
            "operations": [
                _operation_manifest_entry(name, operation) for name, operation in operations
            ],
        }
        payload["digest"] = _sha256(payload)
        return payload
