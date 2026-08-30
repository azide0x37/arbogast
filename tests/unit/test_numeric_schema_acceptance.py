from __future__ import annotations

import ast
import inspect
from textwrap import dedent
from types import ModuleType

import pytest

from arbogast import formats, numeric
from arbogast.numeric import braid, continuation, dyadic, models, outcomes, projection, recognition
from arbogast.numeric._schema import NumericSchemaObject
from arbogast.numeric.certificate import EXPECTED_TYPES, RECEIPT_SCHEMAS, NumericReceipt

RUNTIME_MODULES: tuple[ModuleType, ...] = (
    braid,
    continuation,
    dyadic,
    models,
    outcomes,
    projection,
    recognition,
)

RUNTIME_FIELDS: dict[str, tuple[str, ...]] = {
    "algebraic-candidate": (
        "bounds",
        "isolating_interval",
        "minimal_polynomial",
        "source",
        "type",
    ),
    "braid-continuation-result": ("homotopy", "type"),
    "braid-continuation-witness": (
        "action",
        "sheet_continuations",
        "sheet_permutation",
        "source",
        "target",
        "type",
        "word",
    ),
    "branch-cycle-tuple": ("cover", "entries", "type"),
    "branch-loop": ("branch_index", "model", "path", "type"),
    "branch-tracking": ("continuations", "loop", "permutation", "source_points", "type"),
    "complex-ball": ("center", "radius", "type"),
    "complex-dyadic": ("imag", "real", "type"),
    "condition-bound": (
        "bound",
        "inverse_jacobian",
        "inverse_norm",
        "jacobian_norm",
        "point",
        "system",
        "type",
    ),
    "continuation-result": ("endpoint", "tube", "type"),
    "continuation-step": (
        "contraction_bound",
        "domain",
        "family",
        "inverse_jacobian",
        "parameter_end",
        "parameter_start",
        "residual_bound",
        "type",
    ),
    "continuation-tube": ("family", "path", "start_point", "steps", "type"),
    "degree-result": ("degree", "generic", "type", "witness"),
    "dyadic": ("exponent", "mantissa", "type"),
    "exact-cover": (
        "branch_points",
        "degree",
        "discriminant",
        "family",
        "infinity_branch",
        "infinity_convention",
        "label",
        "type",
    ),
    "exact-polynomial": ("nvariables", "terms", "type", "variable_names"),
    "exactification-result": ("candidate", "point", "type"),
    "generic-degree-witness": ("degree", "polynomial", "type"),
    "nielsen-vertex": (
        "base_parameter",
        "fiber_points",
        "model",
        "nielsen",
        "trackings",
        "type",
    ),
    "numerical-cover": ("base_parameter", "fiber_points", "model", "trackings", "type"),
    "parameter-path": ("type", "vertices"),
    "point": ("coordinates", "system", "type"),
    "polynomial-family": ("nvariables", "parameter_name", "polynomials", "type"),
    "polynomial-system": ("label", "nvariables", "polynomials", "type"),
    "quadratic-b2-homotopy": (
        "action",
        "branch_paths",
        "coefficient_homotopy",
        "collision_sos",
        "convention",
        "orientation",
        "q",
        "sheet_paths",
        "sheet_permutation",
        "source",
        "target",
        "type",
        "word",
    ),
    "real-ball": ("center", "radius", "type"),
    "recognition-bounds": ("max_degree", "max_height", "type"),
    "regular-fiber-degree": ("degree", "generic", "type", "witness"),
    "regular-fiber-witness": ("degree", "factors", "system", "type"),
    "unknown": ("operation", "reason", "requested", "type"),
    "unsupported": ("operation", "reason", "requested", "supported", "type"),
    "weighted-braid-plan": (
        "costs",
        "distances",
        "graph",
        "source",
        "steps",
        "target",
        "total_cost",
        "type",
        "word",
    ),
}

RECEIPT_FIELDS = (
    "assumptions",
    "completeness",
    "dependencies",
    "kind",
    "layer",
    "payload",
    "verifier_trust",
)


def _schema_constant(kind: str, *, receipt: bool = False) -> str:
    stem = kind.upper().replace("-", "_")
    suffix = "_RECEIPT_SCHEMA_V1" if receipt else "_SCHEMA_V1"
    return f"NUMERIC_{stem}{suffix}"


def _runtime_classes() -> dict[str, type[NumericSchemaObject]]:
    by_kind: dict[str, type[NumericSchemaObject]] = {}
    for module in RUNTIME_MODULES:
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and value.__module__ == module.__name__
                and issubclass(value, NumericSchemaObject)
                and "schema_version" in vars(value)
            ):
                identifier = value.schema_version
                prefix = "arbogast.numeric."
                assert identifier.startswith(prefix) and identifier.endswith("/v1")
                kind = identifier.removeprefix(prefix).removesuffix("/v1")
                assert kind not in by_kind or by_kind[kind] is value
                by_kind[kind] = value
    return by_kind


def _literal_return_keys(value: type[NumericSchemaObject]) -> set[str]:
    source = dedent(inspect.getsource(value.to_canonical_data))
    tree = ast.parse(source)
    returns = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    ]
    assert len(returns) == 1
    keys = {
        key.value
        for key in returns[0].keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    if value is braid.NielsenVertex:
        keys.update(_literal_return_keys(braid.NumericalCover))
    return keys


def test_numeric_runtime_receipt_and_format_registries_are_one_to_one() -> None:
    runtime = _runtime_classes()
    assert len(runtime) == 32
    assert set(runtime) == set(RUNTIME_FIELDS) == set(EXPECTED_TYPES) == set(RECEIPT_SCHEMAS)

    catalog = set(formats.schema_ids())
    runtime_catalog = {
        identifier
        for identifier in catalog
        if identifier.startswith("arbogast.numeric.") and not identifier.endswith("-receipt/v1")
    }
    receipt_catalog = {
        identifier
        for identifier in catalog
        if identifier.startswith("arbogast.numeric.") and identifier.endswith("-receipt/v1")
    }
    assert runtime_catalog == {value.schema_version for value in runtime.values()}
    assert receipt_catalog == set(RECEIPT_SCHEMAS.values())

    for kind, value in runtime.items():
        assert getattr(numeric, value.__name__) is value
        assert value.__name__ in numeric.__all__
        assert getattr(formats, _schema_constant(kind)) == value.schema_version
        assert getattr(formats, _schema_constant(kind, receipt=True)) == RECEIPT_SCHEMAS[kind]
        assert EXPECTED_TYPES[kind] in inspect.getsource(value.to_canonical_data)
        assert _literal_return_keys(value) == set(RUNTIME_FIELDS[kind])


@pytest.mark.parametrize("kind", tuple(sorted(RUNTIME_FIELDS)))
def test_each_runtime_schema_has_the_exact_structural_boundary(kind: str) -> None:
    runtime = _runtime_classes()
    identifier = runtime[kind].schema_version
    fields = RUNTIME_FIELDS[kind]
    schema = formats.schema_document(identifier)
    assert schema["$id"] == identifier
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


@pytest.mark.parametrize("kind", tuple(sorted(RECEIPT_SCHEMAS)))
def test_each_receipt_schema_matches_numeric_receipt_transport(kind: str) -> None:
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

    receipt = NumericReceipt.create(kind, {"type": EXPECTED_TYPES[kind]})
    canonical = receipt.to_canonical()
    transport = receipt.to_dict()
    assert set(canonical) == {"schema_version", *RECEIPT_FIELDS}
    assert set(transport) == {*canonical, "certificate_id"}
    assert formats.validate_document(transport, identifier) == transport

    for field in canonical:
        missing = dict(transport)
        del missing[field]
        with pytest.raises(formats.SchemaError, match=r"missing|required|no string"):
            formats.validate_document(missing, identifier)

    wrong_marker = dict(transport)
    del wrong_marker["schema_version"]
    wrong_marker["schema"] = identifier
    with pytest.raises(formats.SchemaError, match="schema_version"):
        formats.validate_document(wrong_marker, identifier)


def test_numeric_schema_boundary_rejects_foreign_identity() -> None:
    document = numeric.Dyadic(1).to_schema_document()
    assert formats.validate_document(document, formats.NUMERIC_DYADIC_SCHEMA_V1) == document

    foreign = dict(document)
    foreign["schema"] = formats.NUMERIC_COMPLEX_DYADIC_SCHEMA_V1
    with pytest.raises(formats.SchemaError, match="expected schema"):
        formats.validate_document(foreign, formats.NUMERIC_DYADIC_SCHEMA_V1)
