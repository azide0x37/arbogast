from __future__ import annotations

import importlib
from types import ModuleType

import pytest

from arbogast import formats, padic
from arbogast.padic._schema import PAdicSchemaObject
from arbogast.padic.certificate import RECEIPT_SCHEMAS

RUNTIME_MODULES: tuple[ModuleType, ...] = tuple(
    importlib.import_module(f"arbogast.padic.{name}")
    for name in (
        "covers",
        "descent",
        "fields",
        "frobenius",
        "inertia",
        "lifts",
        "matrices",
        "modules",
        "reduction",
        "results",
        "wewers",
    )
)

EXPECTED_RUNTIME_KINDS = (
    "automorphism",
    "automorphism-triviality-witness",
    "ball",
    "branch-fiber-witness",
    "certified",
    "component-map-witness",
    "deformation-datum",
    "deformation-datum-witness",
    "deformation-signature",
    "derivative-witness",
    "descended-model",
    "descent-cocycle",
    "descent-isomorphism",
    "element",
    "fiber-factor",
    "field",
    "field-witness",
    "finite-field-factor",
    "finite-inertia-quotient",
    "finite-lift-action",
    "fixed-lift",
    "fixed-lift-set",
    "frobenius-operator",
    "good-reduction",
    "good-reduction-witness",
    "inertia-filtration",
    "inertia-representation",
    "lift-candidate",
    "lift-chart",
    "lift-enumeration-witness",
    "lift-galois-action",
    "lift-set",
    "lift-transport-witness",
    "local-factorization-fragment",
    "local-field-embedding",
    "marked-reduction-component",
    "matrix",
    "module",
    "newton-segment",
    "partial",
    "precision-ring",
    "projective-rational-point",
    "proof-obligation",
    "rational-differential",
    "reduced-branch-fiber",
    "reduced-fiber-factor",
    "reduced-projective-point",
    "riemann-hurwitz-witness",
    "rigid-descent-witness",
    "rigid-fixed-lift",
    "semistable-reduction",
    "semistable-reduction-witness",
    "slope-decomposition",
    "slope-multiplicity",
    "slope-projector",
    "special-fiber-marking",
    "speciality-witness",
    "stable-reduction",
    "stable-reduction-witness",
    "submodule",
    "three-point-cover",
    "unknown",
    "unsupported",
    "valuation-interval",
)

EXPECTED_RECEIPT_KINDS = (
    "automorphism",
    "deformation-datum",
    "descended-model",
    "field",
    "finite-partial",
    "finite-unknown",
    "finite-unsupported",
    "fixed-lift-set",
    "frobenius",
    "good-reduction",
    "inertia-representation",
    "lift-action",
    "lift-set",
    "local-factorization-fragment",
    "local-field-embedding",
    "module",
    "ordinary-part",
    "precision-ring",
    "semistable-reduction",
    "slope-decomposition",
    "stable-reduction",
    "submodule",
    "three-point-partial",
    "three-point-unknown",
    "three-point-unsupported",
)

RECEIPT_FIELDS = (
    "closure",
    "evidence",
    "kind",
    "layer",
    "payload",
    "proof_context",
    "verifier",
)

# Freezes the exact top-level field sequence for all 64 runtime schemas without
# duplicating the 500-line registry literal in this test. Any field addition,
# deletion, or reorder requires an intentional schema-version review.
EXPECTED_RUNTIME_FIELD_HASH = "1de6e55c951b46dbc875d409164f43afc0ab5fae7b86f9403e553f569ee83504"


def _schema_constant(kind: str, *, receipt: bool = False) -> str:
    stem = kind.upper().replace("-", "_")
    suffix = "_RECEIPT_SCHEMA_V1" if receipt else "_SCHEMA_V1"
    return f"PADIC_{stem}{suffix}"


def _runtime_classes() -> dict[str, type[PAdicSchemaObject]]:
    by_kind: dict[str, type[PAdicSchemaObject]] = {}
    for module in RUNTIME_MODULES:
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and value.__module__ == module.__name__
                and issubclass(value, PAdicSchemaObject)
                and "schema_version" in vars(value)
            ):
                identifier = value.schema_version
                prefix = "arbogast.padic."
                assert identifier.startswith(prefix) and identifier.endswith("/v1")
                kind = identifier.removeprefix(prefix).removesuffix("/v1")
                assert kind not in by_kind or by_kind[kind] is value
                by_kind[kind] = value
    return by_kind


def test_padic_runtime_receipt_and_format_registries_are_one_to_one() -> None:
    runtime = _runtime_classes()
    assert tuple(sorted(runtime)) == EXPECTED_RUNTIME_KINDS
    assert tuple(sorted(RECEIPT_SCHEMAS)) == EXPECTED_RECEIPT_KINDS

    catalog = set(formats.schema_ids())
    runtime_catalog = {
        identifier
        for identifier in catalog
        if identifier.startswith("arbogast.padic.") and not identifier.endswith("-receipt/v1")
    }
    receipt_catalog = {
        identifier
        for identifier in catalog
        if identifier.startswith("arbogast.padic.") and identifier.endswith("-receipt/v1")
    }
    assert runtime_catalog == {value.schema_version for value in runtime.values()}
    assert receipt_catalog == set(RECEIPT_SCHEMAS.values())

    runtime_fields = {}
    for kind, value in runtime.items():
        assert getattr(padic, value.__name__) is value
        assert value.__name__ in padic.__all__
        assert getattr(formats, _schema_constant(kind)) == value.schema_version
        schema = formats.schema_document(value.schema_version)
        runtime_fields[kind] = schema["required"][1:]

    assert formats.canonical_sha256(runtime_fields) == EXPECTED_RUNTIME_FIELD_HASH

    for kind, identifier in RECEIPT_SCHEMAS.items():
        assert getattr(formats, _schema_constant(kind, receipt=True)) == identifier


@pytest.mark.parametrize("kind", EXPECTED_RUNTIME_KINDS)
def test_each_runtime_schema_has_the_exact_structural_boundary(kind: str) -> None:
    identifier = _runtime_classes()[kind].schema_version
    schema = formats.schema_document(identifier)
    assert schema["$id"] == identifier
    fields = tuple(schema["required"][1:])
    assert fields
    assert schema["required"] == ["schema", *fields]
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["schema"] == {"const": identifier, "type": "string"}

    document = {"schema": identifier, **dict.fromkeys(fields)}
    assert formats.validate_document(document, identifier) == document
    for field in fields:
        missing = dict(document)
        del missing[field]
        with pytest.raises(formats.SchemaError, match="missing required fields"):
            formats.validate_document(missing, identifier)

    duplicate_marker = {**document, "schema_version": identifier}
    with pytest.raises(formats.SchemaError, match="both"):
        formats.validate_document(duplicate_marker, identifier)


@pytest.mark.parametrize("kind", EXPECTED_RECEIPT_KINDS)
def test_each_receipt_schema_has_the_exact_transport_boundary(kind: str) -> None:
    identifier = RECEIPT_SCHEMAS[kind]
    schema = formats.schema_document(identifier)
    assert schema["$id"] == identifier
    assert schema["required"] == ["schema_version", *RECEIPT_FIELDS]
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["schema_version"] == {
        "const": identifier,
        "type": "string",
    }

    document = {"schema_version": identifier, **dict.fromkeys(RECEIPT_FIELDS)}
    assert formats.validate_document(document, identifier) == document
    for field in RECEIPT_FIELDS:
        missing = dict(document)
        del missing[field]
        with pytest.raises(formats.SchemaError, match="missing required fields"):
            formats.validate_document(missing, identifier)

    wrong_marker = dict(document)
    del wrong_marker["schema_version"]
    wrong_marker["schema"] = identifier
    with pytest.raises(formats.SchemaError, match="schema_version"):
        formats.validate_document(wrong_marker, identifier)
