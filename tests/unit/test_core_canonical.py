from __future__ import annotations

import json
import unicodedata

import pytest

from arbogast.core import (
    CanonicalEncodingError,
    canonical_bytes,
    canonical_data,
    canonical_json,
    pretty_canonical_json,
    require_canonical_json,
    sha256_hex,
    sha256_identity,
)


def test_canonical_json_is_order_independent_compact_and_utf8() -> None:
    left = {"z": [3, 2, 1], "é": {"truth": True, "none": None}}
    right = {"é": {"none": None, "truth": True}, "z": (3, 2, 1)}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_json(left) == '{"z":[3,2,1],"é":{"none":null,"truth":true}}'
    assert canonical_bytes(left) == canonical_json(left).encode("utf-8")
    assert sha256_hex(left) == sha256_hex(right)
    assert sha256_identity(left) == f"sha256:{sha256_hex(left)}"


def test_strings_and_keys_are_normalized_to_nfc() -> None:
    decomposed = "e\N{COMBINING ACUTE ACCENT}"
    composed = unicodedata.normalize("NFC", decomposed)

    assert canonical_data(decomposed) == composed
    assert canonical_json({decomposed: decomposed}) == canonical_json({composed: composed})


@pytest.mark.parametrize("value", [1.0, float("nan"), b"bytes", bytearray(b"bytes")])
def test_exact_canonical_json_rejects_ambiguous_values(value: object) -> None:
    with pytest.raises(CanonicalEncodingError):
        canonical_json(value)


def test_canonical_json_rejects_nonstring_keys_and_normalization_collisions() -> None:
    with pytest.raises(CanonicalEncodingError, match="keys must be strings"):
        canonical_json({1: "value"})

    with pytest.raises(CanonicalEncodingError, match="collide"):
        canonical_json({"é": 1, "e\N{COMBINING ACUTE ACCENT}": 2})


def test_canonical_json_has_no_repr_fallback() -> None:
    class TemptingRepr:
        def __repr__(self) -> str:
            return "looks-stable"

    with pytest.raises(CanonicalEncodingError, match="TemptingRepr"):
        canonical_json(TemptingRepr())


def test_require_canonical_json_rejects_equivalent_noncanonical_text() -> None:
    assert require_canonical_json('{"a":1,"b":[2]}') == {"a": 1, "b": [2]}

    for alternate in ('{"b":[2],"a":1}', '{"a": 1,"b":[2]}', '{"a":1,"b":[2]}\n'):
        with pytest.raises(CanonicalEncodingError, match="not canonical"):
            require_canonical_json(alternate)


def test_require_canonical_json_rejects_invalid_input() -> None:
    with pytest.raises(CanonicalEncodingError, match="invalid JSON"):
        require_canonical_json("not json")


@pytest.mark.parametrize("indent", [0, 1, 4, -2])
def test_pretty_canonical_json_preserves_stdlib_indent_layout(indent: int) -> None:
    value = {"z": [3, {"empty": []}], "a": {"truth": True, "none": None}}

    assert pretty_canonical_json(value, indent=indent) == json.dumps(
        canonical_data(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=indent,
    )


@pytest.mark.parametrize("sign", [1, -1])
def test_arbitrarily_large_integers_have_stable_canonical_roundtrips(sign: int) -> None:
    magnitude = 10**5000
    value = sign * magnitude
    expected = ("-" if sign < 0 else "") + "1" + "0" * 5000

    assert canonical_json(value) == expected
    assert canonical_bytes(value) == expected.encode("ascii")
    assert require_canonical_json(expected) == value
    assert canonical_json({"z": value, "a": [value]}) == (f'{{"a":[{expected}],"z":{expected}}}')
    pretty = pretty_canonical_json({"z": value, "a": [value]}, indent=3)
    assert pretty == (f'{{\n   "a": [\n      {expected}\n   ],\n   "z": {expected}\n}}')


def test_utf8_encoding_failures_use_the_canonical_exception_boundary() -> None:
    with pytest.raises(CanonicalEncodingError, match="Unicode scalar"):
        canonical_bytes("\ud800")
