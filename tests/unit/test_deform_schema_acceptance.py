from __future__ import annotations

import pytest

from arbogast import formats
from arbogast.deform import DeformationComplex, gauge
from arbogast.deform.certificate import RECEIPT_SCHEMAS as CERTIFICATE_RECEIPT_SCHEMAS
from arbogast.linalg import DenseMatrix, PrimeField

RUNTIME_SCHEMAS = {
    "DEFORM_ACTION_SCHEMA_V1": "arbogast.deform.action/v1",
    "DEFORM_ARTIN_RING_ELEMENT_SCHEMA_V1": "arbogast.deform.artin-ring-element/v1",
    "DEFORM_ARTIN_RING_MAP_SCHEMA_V1": "arbogast.deform.artin-ring-map/v1",
    "DEFORM_ARTIN_RING_SCHEMA_V1": "arbogast.deform.artin-ring/v1",
    "DEFORM_COMPLEX_SCHEMA_V1": "arbogast.deform.complex/v1",
    "DEFORM_CONTRACTION_CERTIFICATE_SCHEMA_V1": ("arbogast.deform.contraction-certificate/v1"),
    "DEFORM_EQUIVARIANT_COMPONENT_SCHEMA_V1": ("arbogast.deform.equivariant-component/v1"),
    "DEFORM_EQUIVARIANT_DECOMPOSITION_SCHEMA_V1": ("arbogast.deform.equivariant-decomposition/v1"),
    "DEFORM_EQUIVARIANT_SCHEMA_V1": "arbogast.deform.equivariant/v1",
    "DEFORM_FIXED_LIFT_SCHEMA_V1": "arbogast.deform.fixed-lift/v1",
    "DEFORM_FRAMING_SCHEMA_V1": "arbogast.deform.framing/v1",
    "DEFORM_GAUGE_SPACE_SCHEMA_V1": "arbogast.deform.gauge-space/v1",
    "DEFORM_INVARIANT_DEFORMATIONS_SCHEMA_V1": ("arbogast.deform.invariant-deformations/v1"),
    "DEFORM_LIFT_DATUM_SCHEMA_V1": "arbogast.deform.lift-datum/v1",
    "DEFORM_LIFT_ENDOMORPHISM_SCHEMA_V1": "arbogast.deform.lift-endomorphism/v1",
    "DEFORM_LIFT_FAMILY_SCHEMA_V1": "arbogast.deform.lift-family/v1",
    "DEFORM_LIFT_OBSTRUCTED_SCHEMA_V1": "arbogast.deform.lift-obstructed/v1",
    "DEFORM_LIFT_UNKNOWN_SCHEMA_V1": "arbogast.deform.lift-unknown/v1",
    "DEFORM_NONRIGID_SCHEMA_V1": "arbogast.deform.nonrigid/v1",
    "DEFORM_NONUNIQUE_LIFT_SCHEMA_V1": "arbogast.deform.nonunique-lift/v1",
    "DEFORM_OBSTRUCTION_CLASS_SCHEMA_V1": "arbogast.deform.obstruction-class/v1",
    "DEFORM_OBSTRUCTION_SPACE_SCHEMA_V1": "arbogast.deform.obstruction-space/v1",
    "DEFORM_PRESENTATION_SCHEMA_V1": "arbogast.deform.presentation/v1",
    "DEFORM_PROBLEM_SCHEMA_V1": "arbogast.deform.problem/v1",
    "DEFORM_RIGID_SCHEMA_V1": "arbogast.deform.rigid/v1",
    "DEFORM_SMALL_EXTENSION_SCHEMA_V1": "arbogast.deform.small-extension/v1",
    "DEFORM_TANGENT_SPACE_SCHEMA_V1": "arbogast.deform.tangent-space/v1",
    "DEFORM_UNIQUE_LIFT_SCHEMA_V1": "arbogast.deform.unique-lift/v1",
    "DEFORM_UNSUPPORTED_SCHEMA_V1": "arbogast.deform.unsupported/v1",
}

RECEIPT_SCHEMAS = {
    "DEFORM_ACTION_RECEIPT_SCHEMA_V1": "arbogast.deform.action-receipt/v1",
    "DEFORM_ARTIN_MAP_RECEIPT_SCHEMA_V1": "arbogast.deform.artin-map-receipt/v1",
    "DEFORM_ARTIN_RING_RECEIPT_SCHEMA_V1": "arbogast.deform.artin-ring-receipt/v1",
    "DEFORM_COMPLEX_RECEIPT_SCHEMA_V1": "arbogast.deform.complex-receipt/v1",
    "DEFORM_CONTRACTION_RECEIPT_SCHEMA_V1": ("arbogast.deform.contraction-receipt/v1"),
    "DEFORM_DECOMPOSITION_RECEIPT_SCHEMA_V1": ("arbogast.deform.decomposition-receipt/v1"),
    "DEFORM_EQUIVARIANT_RECEIPT_SCHEMA_V1": ("arbogast.deform.equivariant-receipt/v1"),
    "DEFORM_FIXED_LIFT_RECEIPT_SCHEMA_V1": "arbogast.deform.fixed-lift-receipt/v1",
    "DEFORM_FRAMING_RECEIPT_SCHEMA_V1": "arbogast.deform.framing-receipt/v1",
    "DEFORM_GAUGE_RECEIPT_SCHEMA_V1": "arbogast.deform.gauge-receipt/v1",
    "DEFORM_INVARIANT_COMPLEX_RECEIPT_SCHEMA_V1": ("arbogast.deform.invariant-complex-receipt/v1"),
    "DEFORM_LIFT_DATUM_RECEIPT_SCHEMA_V1": "arbogast.deform.lift-datum-receipt/v1",
    "DEFORM_LIFT_ENDOMORPHISM_RECEIPT_SCHEMA_V1": ("arbogast.deform.lift-endomorphism-receipt/v1"),
    "DEFORM_LIFT_FAMILY_RECEIPT_SCHEMA_V1": "arbogast.deform.lift-family-receipt/v1",
    "DEFORM_LIFT_OBSTRUCTED_RECEIPT_SCHEMA_V1": ("arbogast.deform.lift-obstructed-receipt/v1"),
    "DEFORM_LIFT_UNKNOWN_RECEIPT_SCHEMA_V1": ("arbogast.deform.lift-unknown-receipt/v1"),
    "DEFORM_NONRIGID_RECEIPT_SCHEMA_V1": "arbogast.deform.nonrigid-receipt/v1",
    "DEFORM_NONUNIQUE_LIFT_RECEIPT_SCHEMA_V1": ("arbogast.deform.nonunique-lift-receipt/v1"),
    "DEFORM_OBSTRUCTION_CLASS_RECEIPT_SCHEMA_V1": ("arbogast.deform.obstruction-class-receipt/v1"),
    "DEFORM_OBSTRUCTION_SPACE_RECEIPT_SCHEMA_V1": ("arbogast.deform.obstruction-space-receipt/v1"),
    "DEFORM_PROBLEM_RECEIPT_SCHEMA_V1": "arbogast.deform.problem-receipt/v1",
    "DEFORM_RIGID_RECEIPT_SCHEMA_V1": "arbogast.deform.rigid-receipt/v1",
    "DEFORM_SMALL_EXTENSION_RECEIPT_SCHEMA_V1": ("arbogast.deform.small-extension-receipt/v1"),
    "DEFORM_TANGENT_RECEIPT_SCHEMA_V1": "arbogast.deform.tangent-receipt/v1",
    "DEFORM_UNIQUE_LIFT_RECEIPT_SCHEMA_V1": ("arbogast.deform.unique-lift-receipt/v1"),
    "DEFORM_UNSUPPORTED_RECEIPT_SCHEMA_V1": ("arbogast.deform.unsupported-receipt/v1"),
}


def test_every_deformation_schema_is_exported_and_independently_versioned() -> None:
    current = set(formats.schema_ids())

    for name, identifier in {**RUNTIME_SCHEMAS, **RECEIPT_SCHEMAS}.items():
        assert getattr(formats, name) == identifier
        assert identifier in current
        document = formats.schema_document(identifier)
        assert document["$id"] == identifier
        marker = "schema_version" if name.endswith("RECEIPT_SCHEMA_V1") else "schema"
        required = document["required"]
        properties = document["properties"]
        assert isinstance(required, list)
        assert isinstance(properties, dict)
        assert marker in required
        marker_schema = properties[marker]
        assert isinstance(marker_schema, dict)
        assert marker_schema["const"] == identifier

    registered_receipts = {
        identifier
        for identifier in current
        if identifier.startswith("arbogast.deform.") and identifier.endswith("-receipt/v1")
    }
    assert set(CERTIFICATE_RECEIPT_SCHEMAS.values()) == registered_receipts
    assert registered_receipts == set(RECEIPT_SCHEMAS.values())


def test_runtime_schema_document_round_trips_through_the_structural_boundary() -> None:
    field = PrimeField(3)
    complex_ = DeformationComplex(
        field,
        DenseMatrix.zeros(field, 1, 1),
        DenseMatrix.zeros(field, 1, 1),
        name="schema-round-trip",
    )
    result = gauge(complex_)

    for value in (complex_, result):
        document = value.to_schema_document()
        assert formats.validate_document(document, value.schema_version) == document


def test_schema_boundary_rejects_missing_or_foreign_identity() -> None:
    field = PrimeField(3)
    complex_ = DeformationComplex(
        field,
        DenseMatrix.zeros(field, 1, 1),
        DenseMatrix.zeros(field, 1, 1),
    )
    document = complex_.to_schema_document()
    missing = dict(document)
    del missing["d0"]
    foreign = dict(document)
    foreign["schema"] = formats.DEFORM_PROBLEM_SCHEMA_V1

    with pytest.raises(formats.SchemaError, match="missing required fields"):
        formats.validate_document(missing, complex_.schema_version)
    with pytest.raises(formats.SchemaError, match="expected schema"):
        formats.validate_document(foreign, complex_.schema_version)
