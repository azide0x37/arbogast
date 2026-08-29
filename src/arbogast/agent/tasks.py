"""Small, immutable coding/proof task packets for agent fleets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from arbogast.formats import AGENT_TASK_SCHEMA, FrozenMapping, JSONValue, canonical_sha256


def _ref(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    uri = getattr(value, "uri", None)
    if isinstance(uri, str) and uri:
        return uri
    raise ValueError("agent task inputs must be non-empty strings or references with a uri")


@dataclass(frozen=True, slots=True, init=False)
class AgentTask:
    """A self-contained, acceptance-test-bearing work packet."""

    objective: str
    inputs: tuple[str, ...]
    expected_output: str
    relevant_api: tuple[str, ...]
    dependencies: tuple[str, ...]
    acceptance_tests: tuple[str, ...]
    max_context: tuple[str, ...]
    metadata: FrozenMapping
    schema: str

    def __init__(
        self,
        objective: str,
        expected_output: str,
        *,
        inputs: Iterable[object] = (),
        relevant_api: Iterable[str] = (),
        dependencies: Iterable[str] = (),
        acceptance_tests: Iterable[str] = (),
        max_context: Iterable[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(objective, str) or not isinstance(expected_output, str):
            raise ValueError("agent task objective and expected_output must be strings")
        if not objective.strip() or not expected_output.strip():
            raise ValueError("agent task objective and expected_output must not be empty")
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "inputs", tuple(_ref(item) for item in inputs))
        object.__setattr__(self, "expected_output", expected_output)
        for name, values in (
            ("relevant_api", relevant_api),
            ("dependencies", dependencies),
            ("acceptance_tests", acceptance_tests),
            ("max_context", max_context),
        ):
            materialized = tuple(values)
            if any(not isinstance(value, str) or not value for value in materialized):
                raise ValueError(f"agent task {name} must contain only non-empty strings")
            object.__setattr__(self, name, materialized)
        object.__setattr__(self, "metadata", FrozenMapping(metadata))
        object.__setattr__(self, "schema", AGENT_TASK_SCHEMA)

    @property
    def task_hash(self) -> str:
        return canonical_sha256(self.identity_dict())

    @property
    def packet_id(self) -> str:
        return f"sha256:{self.task_hash}"

    def identity_dict(self) -> dict[str, JSONValue]:
        return {
            "acceptance_tests": list(self.acceptance_tests),
            "dependencies": list(self.dependencies),
            "expected_output": self.expected_output,
            "inputs": list(self.inputs),
            "max_context": list(self.max_context),
            "metadata": self.metadata.to_dict(),
            "objective": self.objective,
            "relevant_api": list(self.relevant_api),
            "schema": self.schema,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {**self.identity_dict(), "packet_id": self.packet_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AgentTask:
        required = {
            "acceptance_tests",
            "dependencies",
            "expected_output",
            "inputs",
            "max_context",
            "metadata",
            "objective",
            "packet_id",
            "relevant_api",
            "schema",
        }
        if set(value) != required:
            raise ValueError("agent task has missing or unknown fields")
        if value["schema"] != AGENT_TASK_SCHEMA:
            raise ValueError("unsupported agent-task schema")
        objective = value["objective"]
        expected_output = value["expected_output"]
        inputs = value["inputs"]
        relevant_api = value["relevant_api"]
        dependencies = value["dependencies"]
        acceptance_tests = value["acceptance_tests"]
        max_context = value["max_context"]
        metadata = value["metadata"]
        if not isinstance(objective, str) or not isinstance(expected_output, str):
            raise ValueError("agent task objective and expected_output must be strings")
        sequence_fields = {
            "inputs": inputs,
            "relevant_api": relevant_api,
            "dependencies": dependencies,
            "acceptance_tests": acceptance_tests,
            "max_context": max_context,
        }
        for name, items in sequence_fields.items():
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError(f"agent task {name} must be an array of strings")
        if not isinstance(metadata, Mapping):
            raise ValueError("agent task metadata must be an object")
        task = cls(
            objective=objective,
            expected_output=expected_output,
            inputs=inputs,
            relevant_api=relevant_api,
            dependencies=dependencies,
            acceptance_tests=acceptance_tests,
            max_context=max_context,
            metadata=metadata,
        )
        supplied = value["packet_id"]
        if not isinstance(supplied, str):
            raise ValueError("agent task packet_id must be a string")
        if supplied != task.packet_id:
            raise ValueError("agent task packet_id does not match its contents")
        return task
