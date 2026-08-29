"""Trusted runtime resolution for named fleet operations.

Fleet task documents contain an operation *name*.  They never contain import
paths, pickles, source text, or another representation of executable code.
This registry is the explicit trust boundary that binds such a persisted name
to a callable ``plan/run/reduce`` implementation in the current process.
"""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from typing import TYPE_CHECKING

from arbogast.formats import JSONValue

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
