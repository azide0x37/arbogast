"""Structured records of how a mathematical claim was obtained."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from arbogast.cert.canonical import FrozenMap, freeze_mapping


class DerivationKind(StrEnum):
    ASSUMPTION = "assumption"
    IMPORT = "import"
    COMPUTATION = "computation"
    INFERENCE = "inference"
    CONJECTURE = "conjecture"


@dataclass(frozen=True)
class Derivation:
    """Explain the mathematical method, independently of stdout or backend logs."""

    kind: DerivationKind
    method: str
    operation: str | None = None
    inputs: tuple[str, ...] = ()
    artifact: str | None = None
    parameters: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            try:
                object.__setattr__(self, "kind", DerivationKind(self.kind))
            except ValueError as exc:
                raise ValueError(f"invalid derivation kind: {self.kind!r}") from exc
        elif not isinstance(self.kind, DerivationKind):
            raise ValueError("derivation kind must be a DerivationKind")
        if not isinstance(self.method, str):
            raise ValueError("derivation method must be a string")
        if not self.method.strip():
            raise ValueError("derivation method cannot be blank")
        if self.operation is not None and (
            not isinstance(self.operation, str) or not self.operation.strip()
        ):
            raise ValueError("operation must be a non-blank string")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))
        if any(not isinstance(item, str) or not item.strip() for item in self.inputs):
            raise ValueError("derivation input references must be non-blank strings")
        if self.artifact is not None and (
            not isinstance(self.artifact, str) or not self.artifact.strip()
        ):
            raise ValueError("derivation artifact must be a non-blank string")

    @classmethod
    def computation(
        cls,
        operation: str,
        *,
        method: str | None = None,
        inputs: Sequence[str] = (),
        artifact: str | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> Derivation:
        return cls(
            kind=DerivationKind.COMPUTATION,
            method=method or f"Exact computation by {operation}",
            operation=operation,
            inputs=tuple(inputs),
            artifact=artifact,
            parameters=freeze_mapping(parameters),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "method": self.method,
            "operation": self.operation,
            "inputs": self.inputs,
            "artifact": self.artifact,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Derivation:
        allowed = {"kind", "method", "operation", "inputs", "artifact", "parameters"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ValueError(f"unexpected derivation fields: {', '.join(unexpected)}")
        missing = sorted({"kind", "method"} - set(value))
        if missing:
            raise ValueError(f"derivation is missing required fields: {', '.join(missing)}")
        raw_inputs = value.get("inputs", ())
        if isinstance(raw_inputs, str) or not isinstance(raw_inputs, Sequence):
            raise ValueError("derivation inputs must be a sequence")
        if any(not isinstance(item, str) for item in raw_inputs):
            raise ValueError("derivation inputs must be strings")
        raw_parameters = value.get("parameters")
        if raw_parameters is not None and not isinstance(raw_parameters, Mapping):
            raise ValueError("derivation parameters must be a mapping")
        raw_kind = value.get("kind")
        raw_method = value.get("method")
        raw_operation = value.get("operation")
        raw_artifact = value.get("artifact")
        if not isinstance(raw_kind, str):
            raise ValueError("derivation kind must be a string")
        if not isinstance(raw_method, str):
            raise ValueError("derivation method must be a string")
        if raw_operation is not None and not isinstance(raw_operation, str):
            raise ValueError("derivation operation must be a string or null")
        if raw_artifact is not None and not isinstance(raw_artifact, str):
            raise ValueError("derivation artifact must be a string or null")
        return cls(
            kind=DerivationKind(raw_kind),
            method=raw_method,
            operation=raw_operation,
            inputs=tuple(raw_inputs),
            artifact=raw_artifact,
            parameters=freeze_mapping(raw_parameters),
        )


Computation = Derivation


__all__ = ["Computation", "Derivation", "DerivationKind"]
