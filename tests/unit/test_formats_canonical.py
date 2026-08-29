from __future__ import annotations

import hashlib

import pytest

from arbogast.core.canonical import canonical_bytes as core_canonical_bytes
from arbogast.formats import (
    TASK_SCHEMA,
    CanonicalJSONError,
    Envelope,
    FrozenMapping,
    canonical_bytes,
    canonical_dumps,
    canonical_sha256,
    loads,
    schema_document,
    validate_document,
)


def test_formats_and_core_share_canonical_bytes_and_hashes() -> None:
    value = {"z": [1, True, None], "name": "Cafe\u0301"}

    assert canonical_bytes(value) == core_canonical_bytes(value)
    assert canonical_sha256(value) == hashlib.sha256(core_canonical_bytes(value)).hexdigest()
    assert canonical_bytes(value) == canonical_bytes({"name": "Caf\u00e9", "z": [1, True, None]})


def test_exact_canonical_json_rejects_bare_floats_and_normalized_key_collisions() -> None:
    with pytest.raises(CanonicalJSONError, match="floating-point"):
        canonical_bytes({"approximation": 0.5})

    with pytest.raises(CanonicalJSONError, match="collide"):
        canonical_bytes({"e\u0301": 1, "\u00e9": 2})


def test_frozen_mapping_is_deeply_immutable_and_normalized() -> None:
    source = {"e\u0301": [1, {"x": 2}]}
    frozen = FrozenMapping(source)
    source["e\u0301"] = [99]

    assert frozen.to_dict() == {"\u00e9": [1, {"x": 2}]}
    assert isinstance(frozen["\u00e9"], tuple)
    with pytest.raises(CanonicalJSONError, match="collide"):
        FrozenMapping({"e\u0301": 1, "\u00e9": 2})


def test_versioned_schema_documents_and_structural_validation() -> None:
    schema = schema_document(TASK_SCHEMA)
    assert schema["$id"] == TASK_SCHEMA
    document = {
        "schema": TASK_SCHEMA,
        "operation": "example",
        "input_refs": [],
        "parameters": {},
        "backend": {},
    }
    assert validate_document(document, TASK_SCHEMA) == document


def test_json_loading_rejects_duplicate_and_normalized_colliding_keys() -> None:
    with pytest.raises(CanonicalJSONError, match="duplicate JSON object key"):
        loads('{"key":1,"key":2}')
    with pytest.raises(CanonicalJSONError, match="collide"):
        loads('{"e\\u0301":1,"é":2}')


def test_envelope_payload_cannot_override_its_schema() -> None:
    with pytest.raises(ValueError, match="cannot override"):
        Envelope(TASK_SCHEMA, {"schema": "arbogast.fleet.task.v0"})


@pytest.mark.parametrize("sign", [1, -1])
def test_formats_preserve_arbitrarily_large_exact_integers(sign: int) -> None:
    value = sign * 10**5000
    expected = ("-" if sign < 0 else "") + "1" + "0" * 5000

    assert canonical_dumps(value) == expected
    assert canonical_bytes(value) == expected.encode("ascii")
    assert loads(expected) == value
    assert canonical_dumps(loads(expected)) == expected
    assert canonical_sha256(value) == hashlib.sha256(expected.encode("ascii")).hexdigest()


def test_loads_is_semantically_strict_but_normalizes_json_presentation() -> None:
    presented = ' { "z" : 2, "name" : "Cafe\\u0301" }\n'

    assert loads(presented) == {"name": "Caf\u00e9", "z": 2}
    assert canonical_dumps(loads(presented)) == '{"name":"Caf\u00e9","z":2}'


def test_load_failures_stay_inside_the_formats_exception_boundary() -> None:
    with pytest.raises(CanonicalJSONError):
        loads(b"\xff")
    with pytest.raises(CanonicalJSONError, match="Unicode scalar"):
        canonical_bytes("\ud800")
