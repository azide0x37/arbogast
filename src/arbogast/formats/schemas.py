"""Versioned schema identifiers and minimal structural validation.

The identifiers are part of Arbogast's public interchange contract.  Schema
versions are explicit; readers must never guess a document type from fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final

from .canonical import JSONValue, normalize_json

TASK_SCHEMA: Final = "arbogast.fleet.task.v1"
SHARD_SCHEMA: Final = "arbogast.fleet.shard.v1"
PLAN_SCHEMA: Final = "arbogast.fleet.plan.v1"
ARTIFACT_SCHEMA: Final = "arbogast.fleet.artifact.v1"
RUN_SCHEMA: Final = "arbogast.fleet.run.v1"
OPERATION_DESCRIPTION_SCHEMA: Final = "arbogast.agent.operation-description.v1"
AGENT_MANIFEST_SCHEMA: Final = "arbogast.agent.manifest.v1"
AGENT_TASK_SCHEMA: Final = "arbogast.agent.task.v1"
AGENT_CONTEXT_SCHEMA: Final = "arbogast.agent.context.v1"
OPERATION_CODE_DEPENDENCIES_SCHEMA: Final = "arbogast.agent.operation-code-dependencies.v1"
CODE_DEPENDENCY_GRAPH_SCHEMA: Final = "arbogast.agent.code-dependency-graph.v1"
ROUTE_SCHEMA: Final = "arbogast.agent.route.v1"
HAZARD_SCHEMA: Final = "arbogast.agent.hazard.v1"
BACKEND_STATUS_SCHEMA: Final = "arbogast.backend.status.v1"
CLI_VERSION_SCHEMA: Final = "arbogast.cli.version.v1"
CLI_DESCRIBE_SCHEMA: Final = "arbogast.cli.describe.v1"
CLI_VERIFY_SCHEMA: Final = "arbogast.cli.verify.v1"
CLI_CLAIMS_SCHEMA: Final = "arbogast.cli.claims.v1"
CLI_PROOF_GAP_SCHEMA: Final = "arbogast.cli.proof-gap.v1"
CLI_ROUTE_SCHEMA: Final = "arbogast.cli.route.v1"
CLI_CAMPAIGN_SCHEMA: Final = "arbogast.cli.campaign.v1"


class SchemaError(ValueError):
    """Raised for an unknown schema or structurally invalid document."""


@dataclass(frozen=True, slots=True)
class SchemaDefinition:
    """A stable schema identifier and its required top-level fields."""

    identifier: str
    required: tuple[str, ...]
    title: str

    def document(self) -> dict[str, JSONValue]:
        """Return a small JSON Schema document for external tooling."""

        properties: dict[str, JSONValue] = {"schema": {"const": self.identifier, "type": "string"}}
        for key in self.required:
            properties.setdefault(key, {})
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": self.identifier,
            "title": self.title,
            "type": "object",
            "required": ["schema", *self.required],
            "properties": properties,
            "additionalProperties": True,
        }


_DEFINITIONS: Final = {
    definition.identifier: definition
    for definition in (
        SchemaDefinition(TASK_SCHEMA, ("operation", "input_refs", "parameters", "backend"), "Task"),
        SchemaDefinition(SHARD_SCHEMA, ("task_hash", "key", "payload"), "Shard"),
        SchemaDefinition(PLAN_SCHEMA, ("task", "shards"), "Fleet plan"),
        SchemaDefinition(ARTIFACT_SCHEMA, ("algorithm", "digest", "size"), "Artifact reference"),
        SchemaDefinition(RUN_SCHEMA, ("task", "shards", "result", "state"), "Fleet run"),
        SchemaDefinition(
            OPERATION_DESCRIPTION_SCHEMA,
            (
                "name",
                "inputs",
                "input_bundles",
                "outputs",
                "preconditions",
                "mathematical_guarantees",
            ),
            "Operation description",
        ),
        SchemaDefinition(
            AGENT_MANIFEST_SCHEMA,
            (
                "package",
                "version",
                "scope",
                "purpose",
                "operations",
                "primary_types",
                "invariants",
                "do_not",
                "code_dependencies",
            ),
            "Agent manifest",
        ),
        SchemaDefinition(AGENT_TASK_SCHEMA, ("objective", "expected_output"), "Agent task"),
        SchemaDefinition(
            AGENT_CONTEXT_SCHEMA,
            (
                "manifest",
                "operations",
                "hazards",
                "capability_routes",
                "capability_frontier",
                "code_dependency_graph",
                "tasks",
                "undeclared_code_dependencies",
                "omitted",
            ),
            "Agent context",
        ),
        SchemaDefinition(
            OPERATION_CODE_DEPENDENCIES_SCHEMA,
            (
                "operation",
                "implementation_module",
                "module_dependencies",
                "required_backends",
                "optional_backends",
            ),
            "Declared operation code dependencies",
        ),
        SchemaDefinition(
            CODE_DEPENDENCY_GRAPH_SCHEMA,
            ("nodes", "edges", "content_id"),
            "Declared code dependency graph",
        ),
        SchemaDefinition(ROUTE_SCHEMA, ("source", "target", "steps"), "Capability route"),
        SchemaDefinition(HAZARD_SCHEMA, ("id", "message", "triggered_by"), "Agent hazard"),
        SchemaDefinition(
            BACKEND_STATUS_SCHEMA,
            ("name", "available", "capabilities"),
            "Backend status",
        ),
        SchemaDefinition(CLI_VERSION_SCHEMA, ("version",), "CLI version response"),
        SchemaDefinition(CLI_DESCRIBE_SCHEMA, ("operation",), "CLI describe response"),
        SchemaDefinition(CLI_VERIFY_SCHEMA, ("valid",), "CLI verification response"),
        SchemaDefinition(CLI_CLAIMS_SCHEMA, ("claims", "count"), "CLI claims response"),
        SchemaDefinition(
            CLI_PROOF_GAP_SCHEMA,
            ("summary", "obligations"),
            "CLI proof-gap response",
        ),
        SchemaDefinition(CLI_ROUTE_SCHEMA, ("route",), "CLI route response"),
        SchemaDefinition(CLI_CAMPAIGN_SCHEMA, ("command", "result"), "CLI campaign response"),
    )
}


def schema_ids() -> tuple[str, ...]:
    """Return all supported schema identifiers in stable order."""

    return tuple(sorted(_DEFINITIONS))


def schema_document(identifier: str) -> dict[str, JSONValue]:
    """Return a copy of the JSON Schema document for ``identifier``."""

    try:
        document = _DEFINITIONS[identifier].document()
    except KeyError as error:
        raise SchemaError(f"unknown schema: {identifier}") from error
    return deepcopy(document)


def validate_document(
    document: Mapping[str, Any], expected: str | None = None
) -> dict[str, JSONValue]:
    """Validate a document's version marker and required top-level fields.

    This intentionally provides structural boundary validation rather than a
    partial reimplementation of a JSON Schema engine.
    """

    normalized = normalize_json(document)
    if not isinstance(normalized, dict):
        raise SchemaError("schema document must be a JSON object")
    identifier = normalized.get("schema")
    if not isinstance(identifier, str):
        raise SchemaError("document has no string 'schema' identifier")
    if expected is not None and identifier != expected:
        raise SchemaError(f"expected schema {expected!r}, got {identifier!r}")
    try:
        definition = _DEFINITIONS[identifier]
    except KeyError as error:
        raise SchemaError(f"unknown schema: {identifier}") from error
    missing = tuple(key for key in definition.required if key not in normalized)
    if missing:
        names = ", ".join(missing)
        raise SchemaError(f"document {identifier!r} is missing required fields: {names}")
    return normalized
