from __future__ import annotations

from copy import deepcopy

import pytest

from arbogast.arithmetic import LocalCondition
from arbogast.arithmetic.certificate import RECEIPT_SCHEMAS
from arbogast.core import ValidationError
from arbogast.formats import (
    AIM_RECEIPT_SCHEMA,
    CARTIER_DUAL_RECEIPT_SCHEMA,
    DESCENT_RECEIPT_SCHEMA,
    DUAL_SELMER_RECEIPT_SCHEMA,
    FIELD_EMBEDDING_SCHEMA,
    FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA,
    FINITE_PLACE_SCHEMA,
    GALOIS_MODULE_RECEIPT_SCHEMA,
    IDEAL_SCHEMA,
    INFINITE_PLACE_SCHEMA,
    KUMMER_RECEIPT_SCHEMA,
    LOCAL_CONDITION_RECEIPT_SCHEMA,
    LOCAL_H1_RECEIPT_SCHEMA,
    LOCAL_PAIRING_RECEIPT_SCHEMA,
    LOCALIZATION_RECEIPT_SCHEMA,
    NUMBER_FIELD_ELEMENT_SCHEMA,
    NUMBER_FIELD_SCHEMA,
    SELMER_RECEIPT_SCHEMA,
    TWIST_RECEIPT_SCHEMA,
    SchemaError,
    canonical_dumps,
    loads,
    schema_document,
    schema_ids,
    validate_document,
)
from arbogast.galois import (
    FieldEmbedding,
    FiniteGaloisQuotientReceipt,
    FinitePlace,
    Ideal,
    InfinitePlace,
    KummerReceipt,
    KummerSpace,
    LocalH1Receipt,
    LocalH1Space,
    LocalizationMap,
    LocalizationReceipt,
    NumberField,
    TwistReceipt,
    kummer_space,
    local_h1,
    localize,
)
from arbogast.galois.modules import GaloisModuleReceipt
from arbogast.rep import PermutationGroup


def _roundtrip(document: dict[str, object], schema: str) -> None:
    decoded = loads(canonical_dumps(document))
    assert isinstance(decoded, dict)
    assert validate_document(decoded, schema) == document
    definition = schema_document(schema)
    assert definition["$id"] == schema


def test_canonical_ideal_binds_field_basis_and_hnf() -> None:
    field = NumberField((-1, -1, 1), generator_name="t")
    ideal = Ideal(field, ((2, 0), (0, 2)))
    assert ideal.norm == 4
    assert ideal.contains(field(2))
    assert not ideal.contains(field.one)
    assert ideal.verify()
    assert ideal.to_dict()["integral_basis"] == field.to_dict()["integral_basis"]
    assert Ideal.from_dict(field, ideal.to_dict()) == ideal
    _roundtrip(ideal.to_dict(), IDEAL_SCHEMA)

    foreign = NumberField.rationals()
    with pytest.raises(ValidationError, match="different pinned field"):
        Ideal.from_dict(foreign, ideal.to_dict())

    altered_basis = deepcopy(ideal.to_dict())
    altered_basis["integral_basis"] = [[[1, 1], [0, 1]], [[1, 1], [1, 1]]]
    with pytest.raises(ValidationError, match="different integral basis"):
        Ideal.from_dict(field, altered_basis)

    altered_hnf = deepcopy(ideal.to_dict())
    altered_hnf["ideal_hnf"] = [[2, 0], [1, 2]]
    with pytest.raises(ValidationError, match="upper triangular"):
        Ideal.from_dict(field, altered_hnf)


def test_ideal_rejects_noncanonical_or_nonideal_lattices() -> None:
    field = NumberField((-1, -1, 1), generator_name="t")
    with pytest.raises(ValidationError, match="canonical residues"):
        Ideal(field, ((2, 2), (0, 1)))
    with pytest.raises(ValidationError, match="not closed"):
        Ideal(field, ((2, 1), (0, 1)))
    with pytest.raises(ValidationError, match="positive"):
        Ideal(field, ((0, 0), (0, 1)))


def test_finite_place_exposes_the_same_standalone_ideal() -> None:
    field = NumberField.rationals()
    place = FinitePlace(field, 2, ((2,),), 1, 1)
    assert place.ideal == Ideal(field, ((2,),))
    assert place.ideal.ideal_id == place.ideal.content_id


def test_arithmetic_object_schema_documents_roundtrip_without_changing_identity() -> None:
    field = NumberField.rationals()
    element = field(2)
    embedding = FieldEmbedding(field, field, field.zero)
    finite = FinitePlace(field, 2, ((2,),), 1, 1)
    infinite = InfinitePlace(field, "real", (-1, 1))

    documents = (
        (field, field.to_schema_document(), NUMBER_FIELD_SCHEMA),
        (element, element.to_schema_document(), NUMBER_FIELD_ELEMENT_SCHEMA),
        (embedding, embedding.to_schema_document(), FIELD_EMBEDDING_SCHEMA),
        (finite, finite.to_schema_document(), FINITE_PLACE_SCHEMA),
        (infinite, infinite.to_schema_document(), INFINITE_PLACE_SCHEMA),
    )
    for value, document, schema in documents:
        identity_before = value.content_id
        _roundtrip(document, schema)
        assert value.content_id == identity_before
        assert "schema" not in value.to_dict()
        assert document["schema"] == value.schema_version


def test_schema_tampering_and_marker_downgrades_fail_closed() -> None:
    document = NumberField.rationals().to_schema_document()
    wrong_schema = deepcopy(document)
    wrong_schema["schema"] = NUMBER_FIELD_ELEMENT_SCHEMA
    with pytest.raises(SchemaError, match="expected schema"):
        validate_document(wrong_schema, NUMBER_FIELD_SCHEMA)

    missing_basis = deepcopy(document)
    missing_basis.pop("integral_basis")
    with pytest.raises(SchemaError, match="missing required fields"):
        validate_document(missing_basis, NUMBER_FIELD_SCHEMA)

    duplicate_marker = deepcopy(document)
    duplicate_marker["schema_version"] = NUMBER_FIELD_SCHEMA
    with pytest.raises(SchemaError, match="both"):
        validate_document(duplicate_marker)


def test_galois_and_arithmetic_receipt_schemas_are_registered_and_replayed() -> None:
    field = NumberField.rationals()
    at_two = FinitePlace(field, 2, ((2,),), 1, 1)
    at_real = InfinitePlace(field, "real", (-1, 1))
    global_space = kummer_space(field, (at_two, at_real))
    two_space = local_h1(at_two)
    assert isinstance(global_space, KummerSpace)
    assert isinstance(two_space, LocalH1Space)
    localization = localize(global_space, two_space)
    assert isinstance(localization, LocalizationMap)
    condition = LocalCondition(two_space, ((1, 0, 0),))

    assert isinstance(global_space.receipt, KummerReceipt)
    assert isinstance(two_space.receipt, LocalH1Receipt)
    assert isinstance(localization.receipt, LocalizationReceipt)
    _roundtrip(global_space.receipt.to_dict(), KUMMER_RECEIPT_SCHEMA)
    _roundtrip(two_space.receipt.to_dict(), LOCAL_H1_RECEIPT_SCHEMA)
    _roundtrip(localization.receipt.to_dict(), LOCALIZATION_RECEIPT_SCHEMA)
    _roundtrip(condition.receipt.to_dict(), LOCAL_CONDITION_RECEIPT_SCHEMA)

    quotient_receipt = FiniteGaloisQuotientReceipt(
        field,
        PermutationGroup.trivial(1),
        label="schema-test",
        presentation={
            "arithmetic_action": "trivial",
            "method": "portable-trivial-quotient-v1",
        },
    )
    _roundtrip(quotient_receipt.to_dict(), FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA)

    expected = {
        AIM_RECEIPT_SCHEMA,
        CARTIER_DUAL_RECEIPT_SCHEMA,
        DESCENT_RECEIPT_SCHEMA,
        DUAL_SELMER_RECEIPT_SCHEMA,
        FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA,
        GALOIS_MODULE_RECEIPT_SCHEMA,
        KUMMER_RECEIPT_SCHEMA,
        LOCAL_CONDITION_RECEIPT_SCHEMA,
        LOCAL_H1_RECEIPT_SCHEMA,
        LOCAL_PAIRING_RECEIPT_SCHEMA,
        LOCALIZATION_RECEIPT_SCHEMA,
        SELMER_RECEIPT_SCHEMA,
        TWIST_RECEIPT_SCHEMA,
    }
    assert expected <= set(schema_ids())
    assert KummerReceipt.schema_version == KUMMER_RECEIPT_SCHEMA
    assert LocalH1Receipt.schema_version == LOCAL_H1_RECEIPT_SCHEMA
    assert LocalizationReceipt.schema_version == LOCALIZATION_RECEIPT_SCHEMA
    assert TwistReceipt.schema_version == TWIST_RECEIPT_SCHEMA
    assert GaloisModuleReceipt.schema_version == GALOIS_MODULE_RECEIPT_SCHEMA
    assert set(RECEIPT_SCHEMAS.values()) == {
        AIM_RECEIPT_SCHEMA,
        CARTIER_DUAL_RECEIPT_SCHEMA,
        DESCENT_RECEIPT_SCHEMA,
        DUAL_SELMER_RECEIPT_SCHEMA,
        LOCAL_CONDITION_RECEIPT_SCHEMA,
        LOCAL_PAIRING_RECEIPT_SCHEMA,
        SELMER_RECEIPT_SCHEMA,
    }
    required = schema_document(KUMMER_RECEIPT_SCHEMA)["required"]
    assert isinstance(required, list)
    assert required[0] == "schema_version"
