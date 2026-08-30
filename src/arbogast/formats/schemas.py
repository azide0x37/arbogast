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
CLI_BACKENDS_SCHEMA: Final = "arbogast.cli.backends.v1"
CLI_DESCRIBE_SCHEMA: Final = "arbogast.cli.describe.v1"
CLI_VERIFY_SCHEMA: Final = "arbogast.cli.verify.v1"
CLI_CLAIMS_SCHEMA: Final = "arbogast.cli.claims.v1"
CLI_PROOF_GAP_SCHEMA: Final = "arbogast.cli.proof-gap.v1"
CLI_ROUTE_SCHEMA: Final = "arbogast.cli.route.v1"
CLI_CAMPAIGN_SCHEMA: Final = "arbogast.cli.campaign.v1"

# Certified-arithmetic object identities introduced in 0.2.0.  These are v1
# interchange schemas: the package release and the schema version are kept as
# independent axes so a future Arbogast release can continue reading these
# exact documents without renaming them.
NUMBER_FIELD_SCHEMA: Final = "arbogast.galois.number-field/v1"
NUMBER_FIELD_ELEMENT_SCHEMA: Final = "arbogast.galois.number-field-element/v1"
FIELD_EMBEDDING_SCHEMA: Final = "arbogast.galois.field-embedding/v1"
IDEAL_SCHEMA: Final = "arbogast.galois.ideal/v1"
FINITE_PLACE_SCHEMA: Final = "arbogast.galois.finite-place/v1"
INFINITE_PLACE_SCHEMA: Final = "arbogast.galois.infinite-place/v1"

# Independently versioned Galois and arithmetic receipt families.  The values
# intentionally match the receipt classes' existing ``schema_version``
# contracts; registering them here makes the public schema catalog complete
# without introducing a new evidence layer.
FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA: Final = "arbogast.galois.finite-quotient-receipt/v1"
GALOIS_MODULE_RECEIPT_SCHEMA: Final = "arbogast.galois.module-receipt/v1"
KUMMER_RECEIPT_SCHEMA: Final = "arbogast.galois.kummer/v1"
LOCAL_H1_RECEIPT_SCHEMA: Final = "arbogast.galois.local-h1/v1"
LOCALIZATION_RECEIPT_SCHEMA: Final = "arbogast.galois.localization/v1"
TWIST_RECEIPT_SCHEMA: Final = "arbogast.galois.twists/v1"

AIM_RECEIPT_SCHEMA: Final = "arbogast.aim/v1"
CARTIER_DUAL_RECEIPT_SCHEMA: Final = "arbogast.cartier-dual/v1"
DESCENT_RECEIPT_SCHEMA: Final = "arbogast.descent/v1"
DUAL_SELMER_RECEIPT_SCHEMA: Final = "arbogast.dual-selmer/v1"
LOCAL_CONDITION_RECEIPT_SCHEMA: Final = "arbogast.local-condition/v1"
LOCAL_PAIRING_RECEIPT_SCHEMA: Final = "arbogast.local-pairing/v1"
SELMER_RECEIPT_SCHEMA: Final = "arbogast.selmer/v1"


class SchemaError(ValueError):
    """Raised for an unknown schema or structurally invalid document."""


@dataclass(frozen=True, slots=True)
class SchemaDefinition:
    """A stable schema identifier and its required top-level fields."""

    identifier: str
    required: tuple[str, ...]
    title: str
    marker: str = "schema"

    def document(self) -> dict[str, JSONValue]:
        """Return a small JSON Schema document for external tooling."""

        properties: dict[str, JSONValue] = {
            self.marker: {"const": self.identifier, "type": "string"}
        }
        for key in self.required:
            properties.setdefault(key, {})
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": self.identifier,
            "title": self.title,
            "type": "object",
            "required": [self.marker, *self.required],
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
        SchemaDefinition(CLI_BACKENDS_SCHEMA, ("backend",), "CLI backend probe response"),
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
        SchemaDefinition(
            NUMBER_FIELD_SCHEMA,
            (
                "defining_polynomial",
                "integral_basis",
                "irreducibility_requirement",
                "irreducibility_witness",
                "type",
            ),
            "Pinned number field",
        ),
        SchemaDefinition(
            NUMBER_FIELD_ELEMENT_SCHEMA,
            ("coefficients", "field_id", "type"),
            "Pinned number-field element",
        ),
        SchemaDefinition(
            FIELD_EMBEDDING_SCHEMA,
            ("codomain_id", "domain_id", "generator_image", "type"),
            "Explicit number-field embedding",
        ),
        SchemaDefinition(
            IDEAL_SCHEMA,
            ("field_id", "integral_basis", "ideal_hnf", "type"),
            "Canonical nonzero integral ideal",
        ),
        SchemaDefinition(
            FINITE_PLACE_SCHEMA,
            (
                "field_id",
                "ideal_hnf",
                "ramification_index",
                "rational_prime",
                "residue_degree",
                "residue_field_witness",
                "type",
                "verification_requirement",
            ),
            "Canonical finite place",
        ),
        SchemaDefinition(
            INFINITE_PLACE_SCHEMA,
            (
                "embedding_index",
                "field_id",
                "isolation",
                "kind",
                "type",
                "verification_requirement",
            ),
            "Canonical infinite place",
        ),
        SchemaDefinition(
            FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA,
            (
                "arithmetic_witness",
                "base_field",
                "base_field_id",
                "group",
                "label",
                "presentation",
                "type",
            ),
            "Finite Galois quotient receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            GALOIS_MODULE_RECEIPT_SCHEMA,
            (
                "module",
                "module_id",
                "quotient",
                "quotient_certificate_id",
                "quotient_id",
                "type",
            ),
            "Galois module receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            KUMMER_RECEIPT_SCHEMA,
            (
                "object_type",
                "field",
                "field_id",
                "prime",
                "places",
                "place_ids",
                "generators",
                "generator_ids",
                "coordinates",
                "proof_context",
                "completeness_witness",
                "proving_certificates",
            ),
            "Kummer receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            LOCAL_H1_RECEIPT_SCHEMA,
            (
                "object_type",
                "place",
                "place_id",
                "prime",
                "basis",
                "basis_ids",
                "coordinates",
                "proof_context",
                "presentation",
                "proving_certificates",
            ),
            "Local H1 receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            LOCALIZATION_RECEIPT_SCHEMA,
            (
                "domain",
                "codomain",
                "matrix",
                "proof_context",
                "localization_witness",
                "proving_certificates",
                "source_coordinates",
                "image_coordinates",
            ),
            "Localization receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            TWIST_RECEIPT_SCHEMA,
            (
                "acting_elements",
                "acting_table",
                "acting_identity",
                "acting_inverses",
                "coefficient_elements",
                "coefficient_table",
                "coefficient_identity",
                "coefficient_inverses",
                "action_table",
                "cocycles",
                "orbits",
                "representatives",
                "assumptions",
            ),
            "Nonabelian twist receipt",
            marker="schema_version",
        ),
        *(
            SchemaDefinition(
                identifier,
                ("layer", "kind", "payload", "proof_context", "evidence"),
                title,
                marker="schema_version",
            )
            for identifier, title in (
                (AIM_RECEIPT_SCHEMA, "Cocycle aiming receipt"),
                (CARTIER_DUAL_RECEIPT_SCHEMA, "Cartier dual receipt"),
                (DESCENT_RECEIPT_SCHEMA, "Elementary descent receipt"),
                (DUAL_SELMER_RECEIPT_SCHEMA, "Dual Selmer receipt"),
                (LOCAL_CONDITION_RECEIPT_SCHEMA, "Local condition receipt"),
                (LOCAL_PAIRING_RECEIPT_SCHEMA, "Local pairing receipt"),
                (SELMER_RECEIPT_SCHEMA, "Selmer receipt"),
            )
        ),
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
    schema_marker = normalized.get("schema")
    version_marker = normalized.get("schema_version")
    if schema_marker is not None and version_marker is not None:
        raise SchemaError("document cannot carry both 'schema' and 'schema_version'")
    identifier = schema_marker if schema_marker is not None else version_marker
    if not isinstance(identifier, str):
        raise SchemaError("document has no string 'schema' identifier")
    if expected is not None and identifier != expected:
        raise SchemaError(f"expected schema {expected!r}, got {identifier!r}")
    try:
        definition = _DEFINITIONS[identifier]
    except KeyError as error:
        raise SchemaError(f"unknown schema: {identifier}") from error
    if definition.marker not in normalized:
        raise SchemaError(
            f"document {identifier!r} must use the {definition.marker!r} version marker"
        )
    missing = tuple(key for key in definition.required if key not in normalized)
    if missing:
        names = ", ".join(missing)
        raise SchemaError(f"document {identifier!r} is missing required fields: {names}")
    return normalized
