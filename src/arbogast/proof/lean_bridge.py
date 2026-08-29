"""Registry connecting Python operations to Lean theorem interfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ParamSpec, TypeVar, cast


class FormalizationStatus(StrEnum):
    VERIFIED = "verified"
    NEEDS_LEMMA = "needs_lemma"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LeanBridge:
    theorem: str
    exporter: str
    status: FormalizationStatus

    def __post_init__(self) -> None:
        if not self.theorem.strip() or not self.exporter.strip():
            raise ValueError("Lean theorem and exporter names cannot be blank")

    def to_canonical(self) -> dict[str, object]:
        return {
            "theorem": self.theorem,
            "exporter": self.exporter,
            "status": self.status.value,
        }


class LeanBridgeRegistry:
    def __init__(self) -> None:
        self._bridges: dict[str, LeanBridge] = {}

    def register(self, operation: str, bridge: LeanBridge) -> None:
        existing = self._bridges.get(operation)
        if existing is not None and existing != bridge:
            raise ValueError(f"Lean bridge already registered: {operation}")
        self._bridges[operation] = bridge

    def get(self, operation: str) -> LeanBridge:
        try:
            return self._bridges[operation]
        except KeyError as exc:
            raise KeyError(f"no Lean bridge for operation: {operation}") from exc

    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._bridges))

    def to_canonical(self) -> dict[str, object]:
        return {operation: self._bridges[operation] for operation in self.operations()}


default_lean_bridges = LeanBridgeRegistry()
P = ParamSpec("P")
R = TypeVar("R")


def lean_bridge(
    *,
    theorem: str,
    exporter: str,
    status: FormalizationStatus,
    operation: str | None = None,
    registry: LeanBridgeRegistry = default_lean_bridges,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Attach a Lean theorem mapping beside a Python operation."""

    bridge = LeanBridge(theorem, exporter, status)

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        operation_name = operation
        if operation_name is None:
            spec = getattr(function, "__arbogast_operation__", None)
            operation_name = getattr(spec, "name", None)
        if not isinstance(operation_name, str) or not operation_name:
            operation_name = f"{function.__module__}.{function.__qualname__}"
        registry.register(operation_name, bridge)
        cast(Any, function).__arbogast_lean_bridge__ = bridge
        return function

    return decorate


__all__ = [
    "FormalizationStatus",
    "LeanBridge",
    "LeanBridgeRegistry",
    "default_lean_bridges",
    "lean_bridge",
]
