"""Portable exact receipts for the bounded certified numeric bridge.

The receipt boundary contains only canonical integer JSON and independently
replayable verification certificates.  Discovery state, floating-point values,
backend handles, and unproved recognition guesses are deliberately excluded.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import ClassVar, Literal, TypeAlias, cast

from arbogast.cert import (
    CertificateError,
    CertificateLayer,
    ContentAddressedCertificate,
    FrozenMap,
    VerificationCertificate,
    content_address,
    freeze_mapping,
    verify_certificate,
)
from arbogast.claims import Claim, ClaimGraph
from arbogast.hurwitz.nielsen import verify_nielsen_certificate_payload

from ._schema import (
    MAX_ASSUMPTIONS,
    MAX_BRAID_WORD_LENGTH,
    MAX_CANONICAL_DEPTH,
    MAX_CANONICAL_INTEGER_BITS,
    MAX_CANONICAL_NODES,
    MAX_GRAPH_EDGES,
    MAX_GRAPH_VERTICES,
    MAX_RECEIPT_DEPENDENCIES,
    MAX_TEXT_LENGTH,
)
from .braid import (
    _B2_HOMOTOPY_CONVENTION,
    BranchCycleTuple,
    BranchLoop,
    BranchTracking,
    NumericalCover,
    _normalized_b2_polynomial,
    _polynomial_value,
    _quadratic_b2_exact_data,
    _verify_b2_polynomial_identities,
)
from .continuation import (
    ConditionBound,
    ContinuationResult,
    ContinuationStep,
    ContinuationTube,
)
from .dyadic import ComplexBall, ComplexDyadic, Dyadic, RealBall
from .errors import NumericError, NumericVerificationError
from .models import (
    ExactCover,
    ExactPolynomial,
    NumericPoint,
    ParameterPath,
    PolynomialFamily,
    PolynomialSystem,
)
from .outcomes import NumericUnknown, UnsupportedNumeric
from .projection import (
    DegreeResult,
    GenericDegreeWitness,
    RegularFiberDegree,
    RegularFiberWitness,
)
from .recognition import (
    AlgebraicCandidate,
    ExactificationResult,
    RecognitionBounds,
)

Completeness: TypeAlias = Literal["candidate", "complete"]

PORTABLE_VERIFIER = "numeric.exact-bridge.v1"
PORTABLE_TRUST = "portable-python"

EXPECTED_TYPES: dict[str, str] = {
    "dyadic": "arbogast.numeric.dyadic",
    "complex-dyadic": "arbogast.numeric.complex_dyadic",
    "real-ball": "arbogast.numeric.real_ball",
    "complex-ball": "arbogast.numeric.complex_ball",
    "exact-polynomial": "arbogast.numeric.exact_polynomial",
    "polynomial-system": "arbogast.numeric.polynomial_system",
    "polynomial-family": "arbogast.numeric.polynomial_family",
    "parameter-path": "arbogast.numeric.parameter_path",
    "point": "arbogast.numeric.point",
    "exact-cover": "arbogast.numeric.exact_cover",
    "continuation-step": "arbogast.numeric.continuation_step",
    "continuation-tube": "arbogast.numeric.continuation_tube",
    "continuation-result": "arbogast.numeric.continuation_result",
    "condition-bound": "arbogast.numeric.condition_bound",
    "recognition-bounds": "arbogast.numeric.recognition_bounds",
    "algebraic-candidate": "arbogast.numeric.algebraic_candidate",
    "exactification-result": "arbogast.numeric.exactification_result",
    "regular-fiber-witness": "arbogast.numeric.regular_fiber_witness",
    "generic-degree-witness": "arbogast.numeric.generic_degree_witness",
    "regular-fiber-degree": "arbogast.numeric.regular_fiber_degree",
    "degree-result": "arbogast.numeric.degree_result",
    "branch-loop": "arbogast.numeric.branch_loop",
    "branch-tracking": "arbogast.numeric.branch_tracking",
    "numerical-cover": "arbogast.numeric.numerical_cover",
    "branch-cycle-tuple": "arbogast.numeric.branch_cycle_tuple",
    "nielsen-vertex": "arbogast.numeric.nielsen_vertex",
    "braid-continuation-witness": "arbogast.numeric.braid_continuation_witness",
    "quadratic-b2-homotopy": "arbogast.numeric.quadratic_b2_homotopy",
    "braid-continuation-result": "arbogast.numeric.braid_continuation_result",
    "weighted-braid-plan": "arbogast.numeric.weighted_braid_plan",
    "unknown": "arbogast.numeric.unknown",
    "unsupported": "arbogast.numeric.unsupported",
}

RECEIPT_SCHEMAS: dict[str, str] = {
    kind: f"arbogast.numeric.{kind}-receipt/v1" for kind in EXPECTED_TYPES
}

_KIND_BY_TYPE = {type_tag: kind for kind, type_tag in EXPECTED_TYPES.items()}


class NumericCertificateError(NumericError):
    """Raised when an exact numeric receipt cannot be formed."""


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise NumericVerificationError(f"{name} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise NumericVerificationError(f"{name} must be a sequence")
    return value


def _exact_keys(value: Mapping[str, object], required: set[str], name: str) -> None:
    if set(value) != required:
        raise NumericVerificationError(
            f"{name} fields mismatch; missing={sorted(required - set(value))}, "
            f"extra={sorted(set(value) - required)}"
        )


def _integer(value: object, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NumericVerificationError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise NumericVerificationError(f"{name} must be at least {minimum}")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise NumericVerificationError(f"{name} must be a boolean")
    return value


def _label(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise NumericVerificationError(f"{name} must be a non-blank string")
    if value != unicodedata.normalize("NFC", value.strip()):
        raise NumericVerificationError(f"{name} is not canonical stripped NFC text")
    return value


def _canonical_equal(value: object, expected: object, name: str) -> None:
    if not _strict_equal(value, expected):
        raise NumericVerificationError(f"{name} canonical snapshot was altered")


def _strict_equal(value: object, expected: object) -> bool:
    if type(expected) is dict:
        if type(value) is not dict:
            return False
        left = cast(dict[object, object], value)
        right = cast(dict[object, object], expected)
        return left.keys() == right.keys() and all(
            _strict_equal(left[key], right[key]) for key in left
        )
    if type(expected) is list:
        if type(value) is not list:
            return False
        left_items = cast(list[object], value)
        right_items = cast(list[object], expected)
        return len(left_items) == len(right_items) and all(
            _strict_equal(left_item, right_item)
            for left_item, right_item in zip(left_items, right_items, strict=True)
        )
    return type(value) is type(expected) and value == expected


def _strict_canonical_json(value: object, name: str, *, depth: int = 0) -> int:
    if depth > MAX_CANONICAL_DEPTH:
        raise CertificateError(f"{name} exceeds the portable nesting-depth bound")
    if value is None or type(value) is bool:
        return 1
    if type(value) is int:
        if value.bit_length() > MAX_CANONICAL_INTEGER_BITS:
            raise CertificateError(f"{name} contains an oversized integer")
        return 1
    if type(value) is str:
        text = value
        if text != unicodedata.normalize("NFC", text):
            raise CertificateError(f"{name} contains noncanonical Unicode text")
        if len(text) > MAX_TEXT_LENGTH:
            raise CertificateError(f"{name} contains text beyond the portable length bound")
        return 1
    if type(value) is list:
        count = 1
        for index, item in enumerate(cast(list[object], value)):
            count += _strict_canonical_json(item, f"{name}[{index}]", depth=depth + 1)
            if count > MAX_CANONICAL_NODES:
                raise CertificateError(f"{name} exceeds the portable node bound")
        return count
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise CertificateError(f"{name} contains a non-string mapping key")
        normalized_keys = [unicodedata.normalize("NFC", cast(str, key)) for key in mapping]
        if list(mapping) != normalized_keys or len(set(normalized_keys)) != len(normalized_keys):
            raise CertificateError(f"{name} contains noncanonical mapping keys")
        count = 1
        for key, item in mapping.items():
            if len(cast(str, key)) > MAX_TEXT_LENGTH:
                raise CertificateError(f"{name} contains a key beyond the portable length bound")
            count += _strict_canonical_json(item, f"{name}.{key}", depth=depth + 1)
            if count > MAX_CANONICAL_NODES:
                raise CertificateError(f"{name} exceeds the portable node bound")
        return count
    raise CertificateError(
        f"{name} contains noncanonical {type(value).__module__}.{type(value).__qualname__}"
    )


def _tag(value: Mapping[str, object], expected: str, name: str) -> None:
    if value.get("type") != expected:
        raise NumericVerificationError(f"{name} has the wrong canonical type tag")


def _dyadic(value: object, name: str = "dyadic") -> Dyadic:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "mantissa", "exponent"}, name)
    _tag(snapshot, EXPECTED_TYPES["dyadic"], name)
    result = Dyadic(
        _integer(snapshot["mantissa"], f"{name}.mantissa"),
        _integer(snapshot["exponent"], f"{name}.exponent"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _complex_dyadic(value: object, name: str = "complex dyadic") -> ComplexDyadic:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "real", "imag"}, name)
    _tag(snapshot, EXPECTED_TYPES["complex-dyadic"], name)
    result = ComplexDyadic(
        _dyadic(snapshot["real"], f"{name}.real"),
        _dyadic(snapshot["imag"], f"{name}.imag"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _real_ball(value: object, name: str = "real ball") -> RealBall:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "center", "radius"}, name)
    _tag(snapshot, EXPECTED_TYPES["real-ball"], name)
    result = RealBall(
        _dyadic(snapshot["center"], f"{name}.center"),
        _dyadic(snapshot["radius"], f"{name}.radius"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _complex_ball(value: object, name: str = "complex ball") -> ComplexBall:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "center", "radius"}, name)
    _tag(snapshot, EXPECTED_TYPES["complex-ball"], name)
    result = ComplexBall(
        _complex_dyadic(snapshot["center"], f"{name}.center"),
        _dyadic(snapshot["radius"], f"{name}.radius"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _polynomial(value: object, name: str = "polynomial") -> ExactPolynomial:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "nvariables", "terms", "variable_names"}, name)
    _tag(snapshot, EXPECTED_TYPES["exact-polynomial"], name)
    nvariables = _integer(snapshot["nvariables"], f"{name}.nvariables", minimum=1)
    terms: list[tuple[tuple[int, ...], ComplexDyadic]] = []
    for index, item in enumerate(_sequence(snapshot["terms"], f"{name}.terms")):
        term = _mapping(item, f"{name}.terms[{index}]")
        _exact_keys(term, {"exponents", "coefficient"}, f"{name}.terms[{index}]")
        exponent = tuple(
            _integer(entry, f"{name}.terms[{index}].exponents", minimum=0)
            for entry in _sequence(term["exponents"], f"{name}.terms[{index}].exponents")
        )
        terms.append((exponent, _complex_dyadic(term["coefficient"], f"{name}.coefficient")))
    names = tuple(
        cast(str, _label(item, f"{name}.variable_names[{index}]"))
        for index, item in enumerate(
            _sequence(snapshot["variable_names"], f"{name}.variable_names")
        )
    )
    result = ExactPolynomial(nvariables, terms, variable_names=names)
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _system(value: object, name: str = "system") -> PolynomialSystem:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "nvariables", "polynomials", "label"}, name)
    _tag(snapshot, EXPECTED_TYPES["polynomial-system"], name)
    result = PolynomialSystem(
        _integer(snapshot["nvariables"], f"{name}.nvariables", minimum=1),
        tuple(
            _polynomial(item, f"{name}.polynomials[{index}]")
            for index, item in enumerate(_sequence(snapshot["polynomials"], f"{name}.polynomials"))
        ),
        label=_label(snapshot["label"], f"{name}.label", optional=True),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _family(value: object, name: str = "family") -> PolynomialFamily:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "nvariables", "polynomials", "parameter_name"}, name)
    _tag(snapshot, EXPECTED_TYPES["polynomial-family"], name)
    parameter_name = _label(snapshot["parameter_name"], f"{name}.parameter_name")
    assert parameter_name is not None
    result = PolynomialFamily(
        _integer(snapshot["nvariables"], f"{name}.nvariables", minimum=1),
        tuple(
            _polynomial(item, f"{name}.polynomials[{index}]")
            for index, item in enumerate(_sequence(snapshot["polynomials"], f"{name}.polynomials"))
        ),
        parameter_name=parameter_name,
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _path(value: object, name: str = "path") -> ParameterPath:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "vertices"}, name)
    _tag(snapshot, EXPECTED_TYPES["parameter-path"], name)
    result = ParameterPath(
        tuple(
            _complex_dyadic(item, f"{name}.vertices[{index}]")
            for index, item in enumerate(_sequence(snapshot["vertices"], f"{name}.vertices"))
        )
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _point(value: object, name: str = "point") -> NumericPoint:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "system", "coordinates"}, name)
    _tag(snapshot, EXPECTED_TYPES["point"], name)
    result = NumericPoint(
        _system(snapshot["system"], f"{name}.system"),
        tuple(
            _complex_ball(item, f"{name}.coordinates[{index}]")
            for index, item in enumerate(_sequence(snapshot["coordinates"], f"{name}.coordinates"))
        ),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _cover(value: object, name: str = "cover") -> ExactCover:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {
            "type",
            "family",
            "degree",
            "branch_points",
            "discriminant",
            "infinity_branch",
            "infinity_convention",
            "label",
        },
        name,
    )
    _tag(snapshot, EXPECTED_TYPES["exact-cover"], name)
    result = ExactCover(
        _family(snapshot["family"], f"{name}.family"),
        _integer(snapshot["degree"], f"{name}.degree", minimum=1),
        tuple(
            _complex_dyadic(item, f"{name}.branch_points[{index}]")
            for index, item in enumerate(
                _sequence(snapshot["branch_points"], f"{name}.branch_points")
            )
        ),
        include_infinity=_boolean(snapshot["infinity_branch"], f"{name}.infinity_branch"),
        label=_label(snapshot["label"], f"{name}.label", optional=True),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _complex_matrix(value: object, name: str) -> tuple[tuple[ComplexDyadic, ...], ...]:
    return tuple(
        tuple(
            _complex_dyadic(entry, f"{name}[{row_index}][{column_index}]")
            for column_index, entry in enumerate(_sequence(row, f"{name}[{row_index}]"))
        )
        for row_index, row in enumerate(_sequence(value, name))
    )


def _continuation_step(value: object, name: str = "continuation step") -> ContinuationStep:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {
            "type",
            "family",
            "parameter_start",
            "parameter_end",
            "domain",
            "inverse_jacobian",
            "residual_bound",
            "contraction_bound",
        },
        name,
    )
    _tag(snapshot, EXPECTED_TYPES["continuation-step"], name)
    result = ContinuationStep(
        _family(snapshot["family"], f"{name}.family"),
        _complex_dyadic(snapshot["parameter_start"], f"{name}.parameter_start"),
        _complex_dyadic(snapshot["parameter_end"], f"{name}.parameter_end"),
        tuple(
            _complex_ball(item, f"{name}.domain[{index}]")
            for index, item in enumerate(_sequence(snapshot["domain"], f"{name}.domain"))
        ),
        _complex_matrix(snapshot["inverse_jacobian"], f"{name}.inverse_jacobian"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _continuation_tube(value: object, name: str = "continuation tube") -> ContinuationTube:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "family", "path", "start_point", "steps"}, name)
    _tag(snapshot, EXPECTED_TYPES["continuation-tube"], name)
    result = ContinuationTube(
        _family(snapshot["family"], f"{name}.family"),
        _path(snapshot["path"], f"{name}.path"),
        _point(snapshot["start_point"], f"{name}.start_point"),
        tuple(
            _continuation_step(item, f"{name}.steps[{index}]")
            for index, item in enumerate(_sequence(snapshot["steps"], f"{name}.steps"))
        ),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _continuation_result(value: object, name: str = "continuation result") -> ContinuationResult:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "tube", "endpoint"}, name)
    _tag(snapshot, EXPECTED_TYPES["continuation-result"], name)
    result = ContinuationResult(_continuation_tube(snapshot["tube"], f"{name}.tube"))
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _condition_bound(value: object, name: str = "condition bound") -> ConditionBound:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {
            "type",
            "system",
            "point",
            "inverse_jacobian",
            "jacobian_norm",
            "inverse_norm",
            "bound",
        },
        name,
    )
    _tag(snapshot, EXPECTED_TYPES["condition-bound"], name)
    result = ConditionBound(
        _system(snapshot["system"], f"{name}.system"),
        _point(snapshot["point"], f"{name}.point"),
        _complex_matrix(snapshot["inverse_jacobian"], f"{name}.inverse_jacobian"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _recognition_bounds(value: object, name: str = "recognition bounds") -> RecognitionBounds:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "max_degree", "max_height"}, name)
    _tag(snapshot, EXPECTED_TYPES["recognition-bounds"], name)
    result = RecognitionBounds(
        _integer(snapshot["max_degree"], f"{name}.max_degree", minimum=1),
        _integer(snapshot["max_height"], f"{name}.max_height", minimum=1),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _algebraic_candidate(value: object, name: str = "algebraic candidate") -> AlgebraicCandidate:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"type", "source", "minimal_polynomial", "isolating_interval", "bounds"},
        name,
    )
    _tag(snapshot, EXPECTED_TYPES["algebraic-candidate"], name)
    polynomial = tuple(
        _integer(item, f"{name}.minimal_polynomial[{index}]")
        for index, item in enumerate(
            _sequence(snapshot["minimal_polynomial"], f"{name}.minimal_polynomial")
        )
    )
    result = AlgebraicCandidate(
        _complex_ball(snapshot["source"], f"{name}.source"),
        polynomial,
        _real_ball(snapshot["isolating_interval"], f"{name}.isolating_interval"),
        _recognition_bounds(snapshot["bounds"], f"{name}.bounds"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _exactification(value: object, name: str = "exactification") -> ExactificationResult:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "point", "candidate"}, name)
    _tag(snapshot, EXPECTED_TYPES["exactification-result"], name)
    result = ExactificationResult(
        _point(snapshot["point"], f"{name}.point"),
        _algebraic_candidate(snapshot["candidate"], f"{name}.candidate"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _regular_fiber_witness(
    value: object, name: str = "regular-fiber witness"
) -> RegularFiberWitness:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "system", "factors", "degree"}, name)
    _tag(snapshot, EXPECTED_TYPES["regular-fiber-witness"], name)
    factors = tuple(
        tuple(
            _integer(entry, f"{name}.factors[{index}][{position}]")
            for position, entry in enumerate(_sequence(item, f"{name}.factors[{index}]"))
        )
        for index, item in enumerate(_sequence(snapshot["factors"], f"{name}.factors"))
    )
    result = RegularFiberWitness(_system(snapshot["system"], f"{name}.system"), factors)
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _generic_degree_witness(
    value: object, name: str = "generic-degree witness"
) -> GenericDegreeWitness:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "polynomial", "degree"}, name)
    _tag(snapshot, EXPECTED_TYPES["generic-degree-witness"], name)
    result = GenericDegreeWitness(_polynomial(snapshot["polynomial"], f"{name}.polynomial"))
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _regular_fiber_degree(value: object, name: str = "regular-fiber degree") -> RegularFiberDegree:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "witness", "degree", "generic"}, name)
    _tag(snapshot, EXPECTED_TYPES["regular-fiber-degree"], name)
    result = RegularFiberDegree(_regular_fiber_witness(snapshot["witness"], f"{name}.witness"))
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _degree_result(value: object, name: str = "degree result") -> DegreeResult:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "witness", "degree", "generic"}, name)
    _tag(snapshot, EXPECTED_TYPES["degree-result"], name)
    result = DegreeResult(_generic_degree_witness(snapshot["witness"], f"{name}.witness"))
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _unknown(value: object, name: str = "unknown result") -> NumericUnknown:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "operation", "reason", "requested"}, name)
    _tag(snapshot, EXPECTED_TYPES["unknown"], name)
    operation = _label(snapshot["operation"], f"{name}.operation")
    reason = _label(snapshot["reason"], f"{name}.reason")
    assert operation is not None and reason is not None
    result = NumericUnknown(
        operation,
        reason,
        requested=_mapping(snapshot["requested"], f"{name}.requested"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _unsupported(value: object, name: str = "unsupported result") -> UnsupportedNumeric:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "operation", "reason", "requested", "supported"}, name)
    _tag(snapshot, EXPECTED_TYPES["unsupported"], name)
    operation = _label(snapshot["operation"], f"{name}.operation")
    reason = _label(snapshot["reason"], f"{name}.reason")
    assert operation is not None and reason is not None
    supported = tuple(
        cast(str, _label(item, f"{name}.supported[{index}]"))
        for index, item in enumerate(_sequence(snapshot["supported"], f"{name}.supported"))
    )
    result = UnsupportedNumeric(
        operation,
        reason,
        requested=_mapping(snapshot["requested"], f"{name}.requested"),
        supported=supported,
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _branch_loop(value: object, name: str = "branch loop") -> BranchLoop:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "model", "branch_index", "path"}, name)
    _tag(snapshot, EXPECTED_TYPES["branch-loop"], name)
    result = BranchLoop(
        _cover(snapshot["model"], f"{name}.model"),
        _integer(snapshot["branch_index"], f"{name}.branch_index", minimum=0),
        _path(snapshot["path"], f"{name}.path"),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _branch_tracking(value: object, name: str = "branch tracking") -> BranchTracking:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"type", "loop", "source_points", "continuations", "permutation"},
        name,
    )
    _tag(snapshot, EXPECTED_TYPES["branch-tracking"], name)
    result = BranchTracking(
        _branch_loop(snapshot["loop"], f"{name}.loop"),
        tuple(
            _point(item, f"{name}.source_points[{index}]")
            for index, item in enumerate(
                _sequence(snapshot["source_points"], f"{name}.source_points")
            )
        ),
        tuple(
            _continuation_result(item, f"{name}.continuations[{index}]")
            for index, item in enumerate(
                _sequence(snapshot["continuations"], f"{name}.continuations")
            )
        ),
        tuple(
            _integer(item, f"{name}.permutation[{index}]", minimum=0)
            for index, item in enumerate(_sequence(snapshot["permutation"], f"{name}.permutation"))
        ),
    )
    _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _numerical_cover(
    value: object, name: str = "numerical cover", *, accept_vertex: bool = False
) -> NumericalCover:
    snapshot = _mapping(value, name)
    expected = {
        "type",
        "model",
        "base_parameter",
        "fiber_points",
        "trackings",
    }
    if accept_vertex:
        expected.add("nielsen")
    _exact_keys(snapshot, expected, name)
    _tag(
        snapshot,
        EXPECTED_TYPES["nielsen-vertex"] if accept_vertex else EXPECTED_TYPES["numerical-cover"],
        name,
    )
    result = NumericalCover(
        _cover(snapshot["model"], f"{name}.model"),
        _complex_dyadic(snapshot["base_parameter"], f"{name}.base_parameter"),
        tuple(
            _point(item, f"{name}.fiber_points[{index}]")
            for index, item in enumerate(
                _sequence(snapshot["fiber_points"], f"{name}.fiber_points")
            )
        ),
        tuple(
            _branch_tracking(item, f"{name}.trackings[{index}]")
            for index, item in enumerate(_sequence(snapshot["trackings"], f"{name}.trackings"))
        ),
    )
    if not accept_vertex:
        _canonical_equal(snapshot, result.to_canonical_data(), name)
    return result


def _permutation(value: object, name: str, *, degree: int | None = None) -> tuple[int, ...]:
    images = tuple(
        _integer(item, f"{name}[{index}]", minimum=0)
        for index, item in enumerate(_sequence(value, name))
    )
    actual_degree = len(images)
    if degree is not None and actual_degree != degree:
        raise NumericVerificationError(f"{name} has the wrong permutation degree")
    if sorted(images) != list(range(actual_degree)):
        raise NumericVerificationError(f"{name} is not a permutation")
    return images


def _compose(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(left[right[point]] for point in range(len(left)))


def _inverse(images: tuple[int, ...]) -> tuple[int, ...]:
    result = [0] * len(images)
    for point, target in enumerate(images):
        result[target] = point
    return tuple(result)


def _nielsen_certificate(value: object, name: str) -> Mapping[str, object]:
    snapshot = _mapping(value, name)
    try:
        verify_nielsen_certificate_payload(snapshot)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise NumericVerificationError(f"{name} failed portable Nielsen replay: {exc}") from exc
    return snapshot


def _verify_nielsen_embedding(
    value: object,
    cover: NumericalCover,
    name: str,
) -> tuple[Mapping[str, object], int, tuple[int, ...]]:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"certificate", "element_permutations", "vertex_index", "vertex_key"},
        name,
    )
    certificate = _nielsen_certificate(snapshot["certificate"], f"{name}.certificate")
    table = tuple(
        tuple(
            _integer(entry, f"{name}.multiplication_table[{row_index}][{column_index}]")
            for column_index, entry in enumerate(
                _sequence(row, f"{name}.multiplication_table[{row_index}]")
            )
        )
        for row_index, row in enumerate(
            _sequence(certificate["multiplication_table"], f"{name}.multiplication_table")
        )
    )
    element_permutations = tuple(
        _permutation(item, f"{name}.element_permutations[{index}]", degree=cover.model.degree)
        for index, item in enumerate(
            _sequence(snapshot["element_permutations"], f"{name}.element_permutations")
        )
    )
    if len(element_permutations) != len(table) or len(set(element_permutations)) != len(table):
        raise NumericVerificationError(
            "Nielsen concrete permutation embedding is not injective and exhaustive"
        )
    identity = _integer(certificate["identity_index"], f"{name}.identity_index", minimum=0)
    if element_permutations[identity] != tuple(range(cover.model.degree)):
        raise NumericVerificationError("Nielsen identity has the wrong concrete permutation")
    for left in range(len(table)):
        for right in range(len(table)):
            if (
                _compose(element_permutations[left], element_permutations[right])
                != (element_permutations[table[left][right]])
            ):
                raise NumericVerificationError(
                    "Nielsen group table is not bound to the concrete permutation embedding"
                )
    representatives = tuple(
        tuple(
            _integer(entry, f"{name}.representative_keys[{index}]", minimum=0)
            for entry in _sequence(item, f"{name}.representative_keys[{index}]")
        )
        for index, item in enumerate(
            _sequence(certificate["representative_keys"], f"{name}.representative_keys")
        )
    )
    vertex_index = _integer(snapshot["vertex_index"], f"{name}.vertex_index", minimum=0)
    if vertex_index >= len(representatives):
        raise NumericVerificationError("Nielsen vertex index is out of range")
    vertex_key = tuple(
        _integer(item, f"{name}.vertex_key[{index}]", minimum=0)
        for index, item in enumerate(_sequence(snapshot["vertex_key"], f"{name}.vertex_key"))
    )
    if vertex_key != representatives[vertex_index]:
        raise NumericVerificationError("Nielsen vertex key is not its certified representative")
    if any(index >= len(element_permutations) for index in vertex_key):
        raise NumericVerificationError("Nielsen vertex key leaves its group enumeration")
    concrete_entries = tuple(element_permutations[index] for index in vertex_key)
    if concrete_entries != cover.tracked_permutations:
        raise NumericVerificationError(
            "Nielsen vertex entries do not match the certified tracked permutations"
        )
    return certificate, vertex_index, vertex_key


def _dependency_hurwitz_certificate(
    dependencies: tuple[VerificationCertificate, ...],
    verifier: str,
) -> Mapping[str, object]:
    matches = tuple(certificate for certificate in dependencies if certificate.verifier == verifier)
    if len(matches) != 1 or len(dependencies) != 1:
        raise NumericVerificationError(
            f"numeric receipt needs exactly one {verifier!r} supporting certificate"
        )
    certificate = matches[0]
    verify_certificate(certificate)
    witness = certificate.witness.to_dict()
    if set(witness) != {"hurwitz_certificate"}:
        raise NumericVerificationError("Hurwitz support has a malformed central witness")
    return _mapping(witness["hurwitz_certificate"], "Hurwitz specialized certificate")


def _without_certificate_id(value: Mapping[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if key != "certificate_id"}


def _verify_nielsen_vertex(
    value: object,
    dependencies: tuple[VerificationCertificate, ...],
    name: str = "Nielsen vertex",
) -> None:
    snapshot = _mapping(value, name)
    cover = _numerical_cover(snapshot, name, accept_vertex=True)
    certificate, _, _ = _verify_nielsen_embedding(snapshot["nielsen"], cover, f"{name}.nielsen")
    specialized = _dependency_hurwitz_certificate(dependencies, "hurwitz.nielsen_class")
    _canonical_equal(
        _without_certificate_id(specialized),
        certificate,
        "Nielsen supporting certificate",
    )


def _action_support(
    dependencies: tuple[VerificationCertificate, ...],
) -> tuple[Mapping[str, object], Mapping[str, object], Mapping[str, object]]:
    specialized = _dependency_hurwitz_certificate(dependencies, "hurwitz.braid_action")
    if specialized.get("operation") != "braid_action":
        raise NumericVerificationError("braid support does not certify a braid action")
    nielsen = _mapping(specialized.get("nielsen_certificate"), "braid action Nielsen data")
    nielsen_without_id = _without_certificate_id(nielsen)
    _nielsen_certificate(nielsen_without_id, "braid action Nielsen data")
    inputs = _mapping(specialized.get("inputs"), "braid action inputs")
    result = _mapping(specialized.get("result"), "braid action result")
    return nielsen, inputs, result


def _move(value: object, name: str, *, arity: int) -> tuple[int, bool]:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"index", "inverse"}, name)
    index = _integer(snapshot["index"], f"{name}.index", minimum=0)
    if index + 1 >= arity:
        raise NumericVerificationError(f"{name} addresses a nonexistent braid slot")
    return index, _boolean(snapshot["inverse"], f"{name}.inverse")


def _word(value: object, name: str, *, arity: int) -> tuple[tuple[int, bool], ...]:
    raw = _sequence(value, name)
    if len(raw) > MAX_BRAID_WORD_LENGTH:
        raise NumericVerificationError(f"{name} exceeds the portable braid-word bound")
    moves = tuple(_move(item, f"{name}[{index}]", arity=arity) for index, item in enumerate(raw))
    return moves


def _table_context(
    nielsen: Mapping[str, object],
) -> tuple[tuple[tuple[int, ...], ...], int, tuple[int, ...], tuple[tuple[int, ...], ...]]:
    table = tuple(
        tuple(cast(int, entry) for entry in cast(Sequence[object], row))
        for row in cast(Sequence[object], nielsen["multiplication_table"])
    )
    identity = cast(int, nielsen["identity_index"])
    inverses = tuple(
        next(
            candidate
            for candidate in range(len(table))
            if table[element][candidate] == identity and table[candidate][element] == identity
        )
        for element in range(len(table))
    )
    representatives = tuple(
        tuple(cast(int, entry) for entry in cast(Sequence[object], row))
        for row in cast(Sequence[object], nielsen["representative_keys"])
    )
    return table, identity, inverses, representatives


def _apply_braid_word(
    nielsen: Mapping[str, object],
    source: tuple[int, ...],
    word: tuple[tuple[int, bool], ...],
) -> int:
    table, _, inverses, representatives = _table_context(nielsen)

    def multiply(left: int, right: int) -> int:
        return table[left][right]

    def conjugate(value: int, by: int) -> int:
        return multiply(multiply(inverses[by], value), by)

    def conjugate_left(value: int, by: int) -> int:
        return multiply(multiply(by, value), inverses[by])

    entries = tuple(source)
    for index, inverse in word:
        updated = list(entries)
        left, right = entries[index], entries[index + 1]
        if inverse:
            updated[index] = right
            updated[index + 1] = conjugate(left, right)
        else:
            updated[index] = conjugate_left(right, left)
            updated[index + 1] = left
        entries = tuple(updated)
    canonical = min(tuple(conjugate(entry, by) for entry in entries) for by in range(len(table)))
    try:
        return representatives.index(canonical)
    except ValueError as exc:
        raise NumericVerificationError("braid word leaves the certified Nielsen class") from exc


def _verify_braid_witness(
    value: object,
    dependencies: tuple[VerificationCertificate, ...],
) -> None:
    snapshot = _mapping(value, "braid continuation witness")
    _exact_keys(
        snapshot,
        {
            "type",
            "source",
            "target",
            "word",
            "action",
            "sheet_continuations",
            "sheet_permutation",
        },
        "braid continuation witness",
    )
    _tag(
        snapshot,
        EXPECTED_TYPES["braid-continuation-witness"],
        "braid continuation witness",
    )
    source_snapshot = _mapping(snapshot["source"], "braid source")
    target_snapshot = _mapping(snapshot["target"], "braid target")
    source = _numerical_cover(source_snapshot, "braid source", accept_vertex=True)
    target = _numerical_cover(target_snapshot, "braid target", accept_vertex=True)
    source_nielsen, _, source_key = _verify_nielsen_embedding(
        source_snapshot["nielsen"], source, "braid source.nielsen"
    )
    target_nielsen, target_index, _ = _verify_nielsen_embedding(
        target_snapshot["nielsen"], target, "braid target.nielsen"
    )
    _canonical_equal(source_nielsen, target_nielsen, "braid endpoint Nielsen certificate")
    action_nielsen, action_inputs, _ = _action_support(dependencies)
    _canonical_equal(
        _without_certificate_id(action_nielsen),
        source_nielsen,
        "braid action Nielsen certificate",
    )
    action = _mapping(snapshot["action"], "braid witness action")
    _exact_keys(action, {"generator_names", "nielsen_source_id"}, "braid witness action")
    if action.get("nielsen_source_id") != action_nielsen.get("certificate_id"):
        raise NumericVerificationError("braid action source ID was altered")
    action_data = _mapping(action_inputs.get("action"), "braid action inputs.action")
    generators = tuple(
        _mapping(item, f"braid action generator[{index}]")
        for index, item in enumerate(
            _sequence(action_data.get("generators"), "braid action generators")
        )
    )
    names = tuple(generator.get("name") for generator in generators)
    if list(names) != list(
        _sequence(action.get("generator_names"), "braid witness generator names")
    ):
        raise NumericVerificationError("braid witness action generator names were altered")
    arity = len(cast(Sequence[object], source_nielsen["class_member_indices"]))
    word = _word(snapshot["word"], "braid witness word", arity=arity)
    if _apply_braid_word(source_nielsen, source_key, word) != target_index:
        raise NumericVerificationError("braid target is not the exact word image")
    if source.model != target.model:
        raise NumericVerificationError("braid local-sheet witness changed the exact cover model")
    continuations = tuple(
        _continuation_result(item, f"braid sheet continuation[{index}]")
        for index, item in enumerate(
            _sequence(snapshot["sheet_continuations"], "braid sheet continuations")
        )
    )
    sheet_permutation = _permutation(
        snapshot["sheet_permutation"],
        "braid sheet permutation",
        degree=source.model.degree,
    )
    if len(continuations) != source.model.degree:
        raise NumericVerificationError("braid witness omits a sheet continuation")
    for source_sheet, continuation in enumerate(continuations):
        if continuation.tube.start_point != source.fiber_points[source_sheet]:
            raise NumericVerificationError("braid local path starts at the wrong source sheet")
        target_point = target.fiber_points[sheet_permutation[source_sheet]]
        if not all(
            target_ball.contains(endpoint_ball)
            for target_ball, endpoint_ball in zip(
                target_point.coordinates,
                continuation.endpoint.coordinates,
                strict=True,
            )
        ):
            raise NumericVerificationError("braid local path ends at the wrong target sheet")


def _verify_normalized_b2_cover(cover: NumericalCover, name: str) -> None:
    if (
        cover.model.family.parameter_name != "t"
        or cover.model.family.polynomials != (_normalized_b2_polynomial(),)
        or cover.model.branch_points != (ComplexDyadic(0), ComplexDyadic(1))
        or cover.model.infinity_branch
        or cover.base_parameter != ComplexDyadic(Dyadic(1, -1))
    ):
        raise NumericVerificationError(f"{name} is not the normalized x^2-t(t-1) cover at t=1/2")


def _verify_quadratic_b2_homotopy(
    value: object,
    dependencies: tuple[VerificationCertificate, ...],
    *,
    name: str = "quadratic B2 homotopy",
) -> None:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {
            "type",
            "source",
            "target",
            "word",
            "action",
            "orientation",
            "q",
            "coefficient_homotopy",
            "branch_paths",
            "collision_sos",
            "sheet_paths",
            "sheet_permutation",
            "convention",
        },
        name,
    )
    _tag(snapshot, EXPECTED_TYPES["quadratic-b2-homotopy"], name)
    if snapshot["convention"] != _B2_HOMOTOPY_CONVENTION:
        raise NumericVerificationError("quadratic B2 geometric convention was altered")
    target = _mapping(snapshot["target"], f"{name}.target")
    _exact_keys(target, {"content_id", "vertex_index"}, f"{name}.target")
    target_id = _label(target["content_id"], f"{name}.target.content_id")
    target_index = _integer(target["vertex_index"], f"{name}.target.vertex_index", minimum=0)
    action_nielsen, action_inputs, _ = _action_support(dependencies)
    action = _mapping(snapshot["action"], f"{name}.action")
    _exact_keys(action, {"generator_names", "nielsen_source_id"}, f"{name}.action")
    if action.get("nielsen_source_id") != action_nielsen.get("certificate_id"):
        raise NumericVerificationError("quadratic B2 action source ID was altered")
    generator_names = tuple(
        _label(item, f"{name}.action.generator_names[{index}]")
        for index, item in enumerate(
            _sequence(action["generator_names"], f"{name}.action.generator_names")
        )
    )
    action_data = _mapping(action_inputs.get("action"), "quadratic B2 action inputs")
    generators = tuple(
        _mapping(item, f"quadratic B2 action generator[{index}]")
        for index, item in enumerate(
            _sequence(action_data.get("generators"), "quadratic B2 action generators")
        )
    )
    if len(generators) != 1 or generator_names != ("sigma_0",):
        raise NumericVerificationError("quadratic B2 action is not the standard B2 action")
    if generators[0].get("name") != "sigma_0" or _word(
        generators[0].get("moves"), "quadratic B2 sigma_0", arity=2
    ) != ((0, False),):
        raise NumericVerificationError("quadratic B2 action generator was altered")
    word = _word(snapshot["word"], f"{name}.word", arity=2)
    if len(word) != 1 or word[0][0] != 0:
        raise NumericVerificationError("quadratic B2 witness is not one generator or inverse")
    orientation = _integer(snapshot["orientation"], f"{name}.orientation")
    if orientation != (-1 if word[0][1] else 1):
        raise NumericVerificationError("quadratic B2 word and orientation disagree")
    q = _polynomial(snapshot["q"], f"{name}.q")
    coefficient_homotopy = _polynomial(
        snapshot["coefficient_homotopy"], f"{name}.coefficient_homotopy"
    )
    branch_items = _sequence(snapshot["branch_paths"], f"{name}.branch_paths")
    collision_items = _sequence(snapshot["collision_sos"], f"{name}.collision_sos")
    sheet_items = _sequence(snapshot["sheet_paths"], f"{name}.sheet_paths")
    if len(branch_items) != 2 or len(collision_items) != 2 or len(sheet_items) != 2:
        raise NumericVerificationError("quadratic B2 witness omits an exact path or SOS term")
    branch_paths = tuple(
        _polynomial(item, f"{name}.branch_paths[{index}]")
        for index, item in enumerate(branch_items)
    )
    collision_sos = tuple(
        _polynomial(item, f"{name}.collision_sos[{index}]")
        for index, item in enumerate(collision_items)
    )
    sheet_paths = tuple(
        _polynomial(item, f"{name}.sheet_paths[{index}]") for index, item in enumerate(sheet_items)
    )
    assert len(branch_paths) == len(collision_sos) == len(sheet_paths) == 2
    typed_branches = branch_paths
    typed_collision = collision_sos
    typed_sheets = sheet_paths
    _verify_b2_polynomial_identities(
        orientation,
        q,
        coefficient_homotopy,
        typed_branches,
        typed_collision,
        typed_sheets,
    )
    expected_data = _quadratic_b2_exact_data(orientation)
    if (q, coefficient_homotopy, typed_branches, typed_collision, typed_sheets) != expected_data:
        raise NumericVerificationError("quadratic B2 exact homotopy data was altered")
    if tuple(_polynomial_value(path, 0) for path in typed_branches) != (
        ComplexDyadic(0),
        ComplexDyadic(1),
    ) or tuple(_polynomial_value(path, 1) for path in typed_branches) != (
        ComplexDyadic(1),
        ComplexDyadic(0),
    ):
        raise NumericVerificationError("quadratic B2 branch endpoints were altered")
    sheet_permutation = _permutation(
        snapshot["sheet_permutation"], f"{name}.sheet_permutation", degree=2
    )
    if sheet_permutation != (1, 0):
        raise NumericVerificationError("quadratic B2 sheet permutation was altered")

    # Replay the small exact homotopy boundary before rebuilding the much larger
    # continuation-tube source.  This preserves the same proof boundary while
    # ensuring malformed geometric payloads fail before expensive reconstruction.
    source_snapshot = _mapping(snapshot["source"], f"{name}.source")
    source = _numerical_cover(source_snapshot, f"{name}.source", accept_vertex=True)
    _verify_normalized_b2_cover(source, f"{name}.source")
    source_nielsen, source_index, source_key = _verify_nielsen_embedding(
        source_snapshot["nielsen"], source, f"{name}.source.nielsen"
    )
    if target_id != content_address(source_snapshot) or target_index != source_index:
        raise NumericVerificationError(
            "normalized quadratic B2 target is not the same exact cover and Nielsen vertex"
        )
    _canonical_equal(
        _without_certificate_id(action_nielsen),
        source_nielsen,
        "quadratic B2 action Nielsen certificate",
    )
    if _apply_braid_word(source_nielsen, source_key, word) != target_index:
        raise NumericVerificationError("quadratic B2 target is not the exact Nielsen image")
    for source_index, path in enumerate(typed_sheets):
        start = _polynomial_value(path, 0)
        end = _polynomial_value(path, 1)
        if not source.fiber_points[source_index].coordinates[0].contains(start):
            raise NumericVerificationError("quadratic B2 sheet starts outside the source fiber")
        if not source.fiber_points[sheet_permutation[source_index]].coordinates[0].contains(end):
            raise NumericVerificationError("quadratic B2 sheet ends outside the target fiber")


def _verify_braid_continuation_result(
    value: object,
    dependencies: tuple[VerificationCertificate, ...],
) -> None:
    snapshot = _mapping(value, "braid continuation result")
    _exact_keys(snapshot, {"type", "homotopy"}, "braid continuation result")
    _tag(
        snapshot,
        EXPECTED_TYPES["braid-continuation-result"],
        "braid continuation result",
    )
    _verify_quadratic_b2_homotopy(snapshot["homotopy"], dependencies)


def _action_tables(
    nielsen: Mapping[str, object],
    inputs: Mapping[str, object],
    result: Mapping[str, object],
) -> tuple[tuple[str, tuple[tuple[int, bool], ...], tuple[int, ...], tuple[int, ...]], ...]:
    arity = len(cast(Sequence[object], nielsen["class_member_indices"]))
    action = _mapping(inputs.get("action"), "braid action inputs.action")
    input_generators = tuple(
        _mapping(item, f"braid action input generator[{index}]")
        for index, item in enumerate(
            _sequence(action.get("generators"), "braid action input generators")
        )
    )
    result_generators = tuple(
        _mapping(item, f"braid action result generator[{index}]")
        for index, item in enumerate(
            _sequence(result.get("generators"), "braid action result generators")
        )
    )
    if len(input_generators) != len(result_generators):
        raise NumericVerificationError("braid action input/result generator counts differ")
    tables: list[tuple[str, tuple[tuple[int, bool], ...], tuple[int, ...], tuple[int, ...]]] = []
    vertex_count = len(cast(Sequence[object], nielsen["representative_keys"]))
    for index, (input_generator, result_generator) in enumerate(
        zip(input_generators, result_generators, strict=True)
    ):
        name = _label(input_generator.get("name"), f"braid generator[{index}].name")
        assert name is not None
        if result_generator.get("name") != name:
            raise NumericVerificationError("braid action generator order was altered")
        moves = _word(
            input_generator.get("moves"),
            f"braid generator[{index}].moves",
            arity=arity,
        )
        forward = _permutation(
            result_generator.get("forward"),
            f"braid generator[{index}].forward",
            degree=vertex_count,
        )
        backward = _permutation(
            result_generator.get("inverse"),
            f"braid generator[{index}].inverse",
            degree=vertex_count,
        )
        if _inverse(forward) != backward:
            raise NumericVerificationError("braid action forward/inverse tables do not cancel")
        tables.append((name, moves, forward, backward))
    return tuple(tables)


def _verify_weighted_plan(
    value: object,
    dependencies: tuple[VerificationCertificate, ...],
) -> None:
    snapshot = _mapping(value, "weighted braid plan")
    _exact_keys(
        snapshot,
        {
            "type",
            "graph",
            "source",
            "target",
            "costs",
            "steps",
            "total_cost",
            "distances",
            "word",
        },
        "weighted braid plan",
    )
    _tag(snapshot, EXPECTED_TYPES["weighted-braid-plan"], "weighted braid plan")
    nielsen, action_inputs, action_result = _action_support(dependencies)
    tables = _action_tables(nielsen, action_inputs, action_result)
    vertex_count = len(cast(Sequence[object], nielsen["representative_keys"]))
    if vertex_count > MAX_GRAPH_VERTICES or vertex_count * len(tables) * 2 > MAX_GRAPH_EDGES:
        raise NumericVerificationError("weighted braid graph exceeds the portable bounds")
    graph = _mapping(snapshot["graph"], "weighted braid graph")
    _exact_keys(graph, {"nielsen_source_id", "vertex_count", "generators"}, "weighted graph")
    if graph.get("nielsen_source_id") != nielsen.get("certificate_id"):
        raise NumericVerificationError("weighted graph Nielsen source ID was altered")
    if _integer(graph.get("vertex_count"), "weighted graph vertex_count", minimum=1) != (
        vertex_count
    ):
        raise NumericVerificationError("weighted graph vertex count was altered")
    graph_generators = tuple(
        _mapping(item, f"weighted graph generator[{index}]")
        for index, item in enumerate(
            _sequence(graph.get("generators"), "weighted graph generators")
        )
    )
    if len(graph_generators) != len(tables):
        raise NumericVerificationError("weighted graph generator count was altered")
    for index, (advertised, (name, moves, forward, backward)) in enumerate(
        zip(graph_generators, tables, strict=True)
    ):
        _exact_keys(advertised, {"name", "word", "forward", "backward"}, "graph generator")
        if advertised.get("name") != name:
            raise NumericVerificationError("weighted graph generator name was altered")
        advertised_word = _word(
            advertised.get("word"),
            f"weighted graph word[{index}]",
            arity=len(cast(Sequence[object], nielsen["class_member_indices"])),
        )
        if advertised_word != moves:
            raise NumericVerificationError("weighted graph generator word was altered")
        if tuple(_sequence(advertised.get("forward"), "weighted graph forward")) != forward:
            raise NumericVerificationError("weighted graph forward table was altered")
        if tuple(_sequence(advertised.get("backward"), "weighted graph backward")) != backward:
            raise NumericVerificationError("weighted graph backward table was altered")
    costs_raw = tuple(
        _mapping(item, f"weighted cost[{index}]")
        for index, item in enumerate(_sequence(snapshot["costs"], "weighted costs"))
    )
    expected_pairs = tuple((name, inverse) for name, _, _, _ in tables for inverse in (False, True))
    costs: dict[tuple[str, bool], Dyadic] = {}
    for index, (item, expected_pair) in enumerate(zip(costs_raw, expected_pairs, strict=True)):
        _exact_keys(item, {"generator", "inverse", "cost"}, f"weighted cost[{index}]")
        pair = (
            cast(str, _label(item.get("generator"), f"weighted cost[{index}].generator")),
            _boolean(item.get("inverse"), f"weighted cost[{index}].inverse"),
        )
        if pair != expected_pair:
            raise NumericVerificationError("weighted costs are not in canonical action order")
        cost = _dyadic(item.get("cost"), f"weighted cost[{index}].cost")
        if cost < 0:
            raise NumericVerificationError("weighted braid cost is negative")
        costs[pair] = cost
    if len(costs_raw) != len(expected_pairs):
        raise NumericVerificationError("weighted braid cost table is incomplete")
    source = _integer(snapshot["source"], "weighted source", minimum=0)
    target = _integer(snapshot["target"], "weighted target", minimum=0)
    if source >= vertex_count or target >= vertex_count:
        raise NumericVerificationError("weighted plan endpoint is out of range")
    total = _dyadic(snapshot["total_cost"], "weighted total cost")
    distances = tuple(
        None if item is None else _dyadic(item, f"weighted distance[{index}]")
        for index, item in enumerate(_sequence(snapshot["distances"], "weighted distances"))
    )
    if (
        len(distances) != vertex_count
        or distances[source] != Dyadic.zero()
        or distances[target] != total
    ):
        raise NumericVerificationError("weighted distance potential has altered endpoints")
    table_by_name = {name: (forward, backward, moves) for name, moves, forward, backward in tables}
    steps = tuple(
        _mapping(item, f"weighted step[{index}]")
        for index, item in enumerate(_sequence(snapshot["steps"], "weighted steps"))
    )
    current = source
    path_cost = Dyadic.zero()
    path_word: list[tuple[int, bool]] = []
    for index, step in enumerate(steps):
        _exact_keys(
            step,
            {"source", "target", "generator", "inverse", "cost"},
            f"weighted step[{index}]",
        )
        step_source = _integer(step["source"], f"weighted step[{index}].source", minimum=0)
        step_target = _integer(step["target"], f"weighted step[{index}].target", minimum=0)
        name = cast(str, _label(step["generator"], f"weighted step[{index}].generator"))
        inverse = _boolean(step["inverse"], f"weighted step[{index}].inverse")
        cost = _dyadic(step["cost"], f"weighted step[{index}].cost")
        if step_source != current or name not in table_by_name:
            raise NumericVerificationError("weighted path is not contiguous in its graph")
        forward, backward, moves = table_by_name[name]
        if (backward if inverse else forward)[step_source] != step_target:
            raise NumericVerificationError("weighted path step is not a certified graph edge")
        if costs[(name, inverse)] != cost:
            raise NumericVerificationError("weighted path step cost was altered")
        path_word.extend(
            ((slot, not move_inverse) for slot, move_inverse in reversed(moves))
            if inverse
            else moves
        )
        current = step_target
        path_cost += cost
    if current != target or path_cost != total:
        raise NumericVerificationError("weighted path does not realize its advertised total")
    arity = len(cast(Sequence[object], nielsen["class_member_indices"]))
    if _word(snapshot["word"], "weighted plan word", arity=arity) != tuple(path_word):
        raise NumericVerificationError("weighted path braid word was altered")
    for vertex, distance in enumerate(distances):
        if distance is None:
            continue
        for name, _, forward, backward in tables:
            for inverse, neighbor in ((False, forward[vertex]), (True, backward[vertex])):
                neighbor_distance = distances[neighbor]
                if (
                    neighbor_distance is None
                    or neighbor_distance > distance + costs[(name, inverse)]
                ):
                    raise NumericVerificationError("weighted distance potential violates an edge")


def _branch_cycle_tuple(value: object) -> BranchCycleTuple:
    snapshot = _mapping(value, "branch-cycle tuple")
    _exact_keys(snapshot, {"type", "cover", "entries"}, "branch-cycle tuple")
    _tag(snapshot, EXPECTED_TYPES["branch-cycle-tuple"], "branch-cycle tuple")
    result = BranchCycleTuple(_numerical_cover(snapshot["cover"], "branch-cycle cover"))
    _canonical_equal(snapshot, result.to_canonical_data(), "branch-cycle tuple")
    return result


def _decode_plain(value: object, kind: str) -> object:
    decoders: dict[str, Callable[[object], object]] = {
        "dyadic": _dyadic,
        "complex-dyadic": _complex_dyadic,
        "real-ball": _real_ball,
        "complex-ball": _complex_ball,
        "exact-polynomial": _polynomial,
        "polynomial-system": _system,
        "polynomial-family": _family,
        "parameter-path": _path,
        "point": _point,
        "exact-cover": _cover,
        "continuation-step": _continuation_step,
        "continuation-tube": _continuation_tube,
        "continuation-result": _continuation_result,
        "condition-bound": _condition_bound,
        "recognition-bounds": _recognition_bounds,
        "algebraic-candidate": _algebraic_candidate,
        "exactification-result": _exactification,
        "regular-fiber-witness": _regular_fiber_witness,
        "generic-degree-witness": _generic_degree_witness,
        "regular-fiber-degree": _regular_fiber_degree,
        "degree-result": _degree_result,
        "branch-loop": _branch_loop,
        "branch-tracking": _branch_tracking,
        "numerical-cover": _numerical_cover,
        "branch-cycle-tuple": _branch_cycle_tuple,
        "unknown": _unknown,
        "unsupported": _unsupported,
    }
    try:
        decoder = decoders[kind]
    except KeyError as exc:
        raise NumericVerificationError(f"{kind} needs specialized receipt replay") from exc
    return decoder(value)


def _reject_backend_leaks(value: object) -> None:
    forbidden = {
        "backend_handle",
        "gp_handle",
        "pari_handle",
        "session_id",
        "session_index",
        "raw_output",
        "decimal_approximation",
    }
    if isinstance(value, Mapping):
        lowered = {key: key.casefold().replace("-", "_") for key in value}
        leaked = forbidden.intersection(lowered.values())
        dangerous_tokens = ("backend", "handle", "session", "transcript", "raw_output")
        leaked.update(
            original
            for original, normalized in lowered.items()
            if any(token in normalized for token in dangerous_tokens)
        )
        if leaked:
            raise NumericVerificationError(
                f"backend-local fields crossed the numeric proof boundary: {sorted(leaked)}"
            )
        for item in value.values():
            _reject_backend_leaks(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_backend_leaks(item)


@dataclass(frozen=True)
class NumericReceipt(ContentAddressedCertificate):
    """One independently versioned exact numeric receipt."""

    kind: str
    payload: FrozenMap
    dependencies: tuple[VerificationCertificate, ...] = ()
    assumptions: tuple[str, ...] = ()
    completeness: Completeness = "complete"
    verifier_trust: str = PORTABLE_TRUST

    layer: ClassVar[CertificateLayer] = CertificateLayer.VERIFICATION

    def __post_init__(self) -> None:
        if self.kind not in RECEIPT_SCHEMAS:
            raise CertificateError(f"unsupported numeric receipt kind: {self.kind!r}")
        raw_payload = (
            self.payload.to_dict() if isinstance(self.payload, FrozenMap) else self.payload
        )
        _strict_canonical_json(raw_payload, "numeric receipt payload")
        object.__setattr__(self, "payload", freeze_mapping(self.payload))
        dependencies = tuple(self.dependencies)
        if len(dependencies) > MAX_RECEIPT_DEPENDENCIES:
            raise CertificateError("numeric receipt has too many supporting dependencies")
        if any(not isinstance(item, VerificationCertificate) for item in dependencies):
            raise CertificateError(
                "numeric receipt dependencies must be VerificationCertificate values"
            )
        _strict_canonical_json(
            [item.to_dict() for item in dependencies],
            "numeric receipt serialized dependencies",
        )
        dependency_ids = tuple(item.certificate_id for item in dependencies)
        if dependency_ids != tuple(sorted(set(dependency_ids))):
            raise CertificateError("numeric receipt dependencies must be sorted and unique")
        object.__setattr__(self, "dependencies", dependencies)
        assumptions = tuple(self.assumptions)
        if len(assumptions) > MAX_ASSUMPTIONS:
            raise CertificateError("numeric receipt has too many assumptions")
        if assumptions != tuple(sorted(set(assumptions))):
            raise CertificateError("numeric assumptions must be sorted and unique")
        if any(isinstance(item, str) and len(item) > MAX_TEXT_LENGTH for item in assumptions):
            raise CertificateError(
                "numeric receipt assumption exceeds the portable text-length bound"
            )
        if any(
            not isinstance(item, str)
            or not item.strip()
            or item != unicodedata.normalize("NFC", item.strip())
            for item in assumptions
        ):
            raise CertificateError("numeric assumptions must be nonblank canonical NFC strings")
        object.__setattr__(self, "assumptions", assumptions)
        if self.completeness not in {"candidate", "complete"}:
            raise CertificateError("numeric completeness must be candidate or complete")
        if self.kind in {"unknown", "unsupported"} and self.completeness != "candidate":
            raise CertificateError("numeric non-conclusions must remain candidate")
        if self.kind not in {"unknown", "unsupported"} and self.completeness != "complete":
            raise CertificateError("exact numeric witnesses must be marked complete")
        if self.verifier_trust != PORTABLE_TRUST:
            raise CertificateError("numeric exact receipts require portable Python trust")

    @property
    def schema_version(self) -> str:
        return RECEIPT_SCHEMAS[self.kind]

    @property
    def object_id(self) -> str:
        return content_address(self.payload)

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer.value,
            "kind": self.kind,
            "payload": self.payload,
            "dependencies": tuple(item.to_dict() for item in self.dependencies),
            "assumptions": self.assumptions,
            "completeness": self.completeness,
            "verifier_trust": self.verifier_trust,
        }

    @classmethod
    def create(
        cls,
        kind: str,
        payload: Mapping[str, object],
        *,
        dependencies: Sequence[VerificationCertificate] = (),
        assumptions: Sequence[str] = (),
        completeness: Completeness | None = None,
    ) -> NumericReceipt:
        _strict_canonical_json(payload, "numeric receipt payload")
        normalized_completeness: Completeness = (
            "candidate"
            if completeness is None and kind in {"unknown", "unsupported"}
            else completeness or "complete"
        )
        return cls(
            kind,
            freeze_mapping(payload),
            tuple(sorted(dependencies, key=lambda item: item.certificate_id)),
            tuple(sorted(set(assumptions))),
            normalized_completeness,
            PORTABLE_TRUST,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> NumericReceipt:
        allowed = {
            "schema_version",
            "layer",
            "kind",
            "payload",
            "dependencies",
            "assumptions",
            "completeness",
            "verifier_trust",
            "certificate_id",
        }
        required = allowed - {"certificate_id"}
        if set(value) - allowed or required - set(value):
            raise CertificateError("numeric receipt fields do not match the v1 schema")
        kind = value["kind"]
        if not isinstance(kind, str) or kind not in RECEIPT_SCHEMAS:
            raise CertificateError("unsupported numeric receipt kind")
        if value["schema_version"] != RECEIPT_SCHEMAS[kind]:
            raise CertificateError("unsupported numeric receipt schema")
        if value["layer"] != CertificateLayer.VERIFICATION.value:
            raise CertificateError("numeric receipt has the wrong evidence layer")
        payload = _mapping(value["payload"], "numeric receipt payload")
        _strict_canonical_json(payload, "numeric receipt payload")
        raw_dependencies = _sequence(value["dependencies"], "numeric receipt dependencies")
        if len(raw_dependencies) > MAX_RECEIPT_DEPENDENCIES:
            raise CertificateError("numeric receipt has too many supporting dependencies")
        _strict_canonical_json(
            list(raw_dependencies),
            "numeric receipt serialized dependencies",
        )
        dependencies = tuple(
            VerificationCertificate.from_dict(
                _mapping(item, f"numeric receipt dependency[{index}]")
            )
            for index, item in enumerate(raw_dependencies)
        )
        raw_assumptions = _sequence(value["assumptions"], "numeric receipt assumptions")
        if len(raw_assumptions) > MAX_ASSUMPTIONS:
            raise CertificateError("numeric receipt has too many assumptions")
        assumptions = tuple(item for item in raw_assumptions if isinstance(item, str))
        if len(assumptions) != len(raw_assumptions):
            raise CertificateError("numeric receipt assumptions must contain strings")
        if any(len(item) > MAX_TEXT_LENGTH for item in assumptions):
            raise CertificateError(
                "numeric receipt assumption exceeds the portable text-length bound"
            )
        completeness = value["completeness"]
        if completeness not in {"candidate", "complete"}:
            raise CertificateError("invalid numeric completeness")
        if value["verifier_trust"] != PORTABLE_TRUST:
            raise CertificateError("invalid numeric verifier trust")
        receipt = cls(
            kind,
            freeze_mapping(payload),
            dependencies,
            assumptions,
            completeness,
            PORTABLE_TRUST,
        )
        if "certificate_id" in value:
            expected = value["certificate_id"]
            if not isinstance(expected, str):
                raise CertificateError("numeric receipt certificate_id must be a string")
            receipt.verify_integrity(expected)
        return receipt

    def verify(self) -> tuple[str, ...]:
        return verify_numeric_receipt(self)

    @property
    def certificate(self) -> VerificationCertificate:
        semantic = import_module("arbogast.numeric.semantic")
        return cast(
            VerificationCertificate,
            semantic.verification_certificate_for_receipt(self),
        )

    def claim(self) -> Claim:
        semantic = import_module("arbogast.numeric.semantic")
        return cast(Claim, semantic.claim_for_receipt(self))

    def claim_graph(self) -> ClaimGraph:
        semantic = import_module("arbogast.numeric.semantic")
        return cast(ClaimGraph, semantic.claim_graph_for_receipt(self))


def verify_numeric_receipt(receipt: NumericReceipt) -> tuple[str, ...]:
    """Replay one exact numeric result from canonical data only."""

    if not isinstance(receipt, NumericReceipt):
        raise TypeError("receipt must be a NumericReceipt")
    receipt.verify_integrity()
    payload = receipt.payload.to_dict()
    _reject_backend_leaks(payload)
    _tag(payload, EXPECTED_TYPES[receipt.kind], f"{receipt.kind} payload")
    checks: tuple[str, ...]
    if receipt.kind == "nielsen-vertex":
        _verify_nielsen_vertex(payload, receipt.dependencies)
        checks = (
            "complete-numerical-cover-replay",
            "portable-Nielsen-certificate",
            "concrete-permutation-embedding",
            "tracked-vertex-binding",
        )
    elif receipt.kind == "quadratic-b2-homotopy":
        _verify_quadratic_b2_homotopy(payload, receipt.dependencies)
        checks = (
            "normalized-quadratic-endpoint-identities",
            "exact-oriented-branch-exchange",
            "sum-of-squares-noncollision",
            "fixed-base-sheet-paths",
            "exact-Nielsen-word-image",
        )
    elif receipt.kind == "braid-continuation-result":
        _verify_braid_continuation_result(payload, receipt.dependencies)
        checks = (
            "genuine-cover-coefficient-homotopy",
            "exact-oriented-branch-exchange",
            "sum-of-squares-noncollision",
            "fixed-base-sheet-permutation",
            "exact-Nielsen-endpoint",
        )
    elif receipt.kind == "braid-continuation-witness":
        _verify_braid_witness(payload, receipt.dependencies)
        checks = (
            "portable-braid-action",
            "exact-Nielsen-edge",
            "local-sheet-path-replay",
            "no-cover-deformation-claim",
        )
    elif receipt.kind == "weighted-braid-plan":
        _verify_weighted_plan(payload, receipt.dependencies)
        checks = (
            "portable-braid-action",
            "exact-dyadic-edge-costs",
            "realizing-path",
            "global-optimality-potential",
        )
    else:
        if receipt.dependencies:
            raise NumericVerificationError(
                "numeric receipt carries unreferenced supporting certificates"
            )
        result = _decode_plain(payload, receipt.kind)
        verify = getattr(result, "verify", None)
        if not callable(verify) or verify() is not True:
            raise NumericVerificationError("numeric result failed exact runtime replay")
        checks = (
            "strict-canonical-payload",
            "bounded-exact-arithmetic",
            "runtime-independent-witness-replay",
        )
    return checks


__all__ = [
    "EXPECTED_TYPES",
    "PORTABLE_TRUST",
    "PORTABLE_VERIFIER",
    "RECEIPT_SCHEMAS",
    "Completeness",
    "NumericCertificateError",
    "NumericReceipt",
    "verify_numeric_receipt",
]
