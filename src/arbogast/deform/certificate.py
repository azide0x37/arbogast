"""Portable finite witnesses for deformation calculations.

The deformation core retains rich immutable objects.  This module is the
narrow proof boundary: a :class:`DeformationReceipt` freezes one object's
canonical snapshot, embeds every prerequisite verification certificate, and
replays the advertised conclusion using only exact arithmetic over a prime
field.  No backend handle, session-local identifier, or discovery transcript
is accepted by this boundary.

The specialized receipt is verification-layer evidence nested inside the
existing :class:`arbogast.cert.VerificationCertificate` v1 envelope.  It does
not introduce another evidence layer.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, TypeAlias, cast

from arbogast.cert import (
    CertificateError,
    CertificateLayer,
    ContentAddressedCertificate,
    FrozenMap,
    VerificationCertificate,
    content_address,
    freeze_mapping,
)
from arbogast.core import ValidationError
from arbogast.linalg import (
    DenseMatrix,
    LinearSubspace,
    PrimeField,
    image,
    nullspace,
    quotient_space,
    rank,
    solve,
)

from ._schema import (
    MAX_DIMENSION,
    MAX_GROUP_ORDER,
    MAX_MATRIX_CELLS,
    MAX_PRIME,
    MAX_TENSOR_CELLS,
)
from .errors import (
    DeformationError,
    DeformationVerificationError,
    UnsupportedDeformation,
    _canonical_requested,
)

if TYPE_CHECKING:
    from arbogast.claims import Claim, ClaimGraph

Vector: TypeAlias = tuple[int, ...]
Rows: TypeAlias = tuple[Vector, ...]
Completeness: TypeAlias = Literal["candidate", "complete"]

PORTABLE_VERIFIER = "deform.finite-exact.v1"
PORTABLE_TRUST = "portable-python"

RECEIPT_SCHEMAS: dict[str, str] = {
    "artin-ring": "arbogast.deform.artin-ring-receipt/v1",
    "artin-map": "arbogast.deform.artin-map-receipt/v1",
    "small-extension": "arbogast.deform.small-extension-receipt/v1",
    "complex": "arbogast.deform.complex-receipt/v1",
    "problem": "arbogast.deform.problem-receipt/v1",
    "gauge": "arbogast.deform.gauge-receipt/v1",
    "tangent": "arbogast.deform.tangent-receipt/v1",
    "obstruction-space": "arbogast.deform.obstruction-space-receipt/v1",
    "obstruction-class": "arbogast.deform.obstruction-class-receipt/v1",
    "framing": "arbogast.deform.framing-receipt/v1",
    "action": "arbogast.deform.action-receipt/v1",
    "equivariant": "arbogast.deform.equivariant-receipt/v1",
    "invariant-complex": "arbogast.deform.invariant-complex-receipt/v1",
    "decomposition": "arbogast.deform.decomposition-receipt/v1",
    "lift-datum": "arbogast.deform.lift-datum-receipt/v1",
    "lift-family": "arbogast.deform.lift-family-receipt/v1",
    "lift-obstructed": "arbogast.deform.lift-obstructed-receipt/v1",
    "lift-unknown": "arbogast.deform.lift-unknown-receipt/v1",
    "unique-lift": "arbogast.deform.unique-lift-receipt/v1",
    "nonunique-lift": "arbogast.deform.nonunique-lift-receipt/v1",
    "lift-endomorphism": "arbogast.deform.lift-endomorphism-receipt/v1",
    "contraction": "arbogast.deform.contraction-receipt/v1",
    "fixed-lift": "arbogast.deform.fixed-lift-receipt/v1",
    "rigid": "arbogast.deform.rigid-receipt/v1",
    "nonrigid": "arbogast.deform.nonrigid-receipt/v1",
    "unsupported": "arbogast.deform.unsupported-receipt/v1",
}

EXPECTED_TYPES: dict[str, str] = {
    "artin-ring": "arbogast.deform.artin_ring",
    "artin-map": "arbogast.deform.artin_ring_map",
    "small-extension": "arbogast.deform.small_extension",
    "complex": "arbogast.deform.complex",
    "problem": "arbogast.deform.problem",
    "gauge": "arbogast.deform.gauge_space",
    "tangent": "arbogast.deform.tangent_space",
    "obstruction-space": "arbogast.deform.obstruction_space",
    "obstruction-class": "arbogast.deform.obstruction_class",
    "framing": "arbogast.deform.framing",
    "action": "arbogast.deform.deformation_action",
    "equivariant": "arbogast.deform.equivariant_deformation",
    "invariant-complex": "arbogast.deform.invariant_deformations",
    "decomposition": "arbogast.deform.equivariant_decomposition",
    "lift-datum": "arbogast.deform.lift_datum",
    "lift-family": "arbogast.deform.lift_family",
    "lift-obstructed": "arbogast.deform.lift_obstructed",
    "lift-unknown": "arbogast.deform.lift_unknown",
    "unique-lift": "arbogast.deform.unique_lift",
    "nonunique-lift": "arbogast.deform.nonunique_lift",
    "lift-endomorphism": "arbogast.deform.lift_endomorphism",
    "contraction": "arbogast.deform.contraction_certificate",
    "fixed-lift": "arbogast.deform.fixed_lift",
    "rigid": "arbogast.deform.rigid",
    "nonrigid": "arbogast.deform.nonrigid",
    "unsupported": "arbogast.deform.unsupported",
}


class DeformationCertificateError(DeformationError):
    """Raised when a deformation receipt cannot be formed."""


def _strict_int(value: object, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DeformationVerificationError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise DeformationVerificationError(f"{name} must be at least {minimum}")
    return value


def _dimension(value: object, name: str) -> int:
    result = _strict_int(value, name, minimum=0)
    if result > MAX_DIMENSION:
        raise DeformationVerificationError(
            f"{name} exceeds the portable dimension limit {MAX_DIMENSION}"
        )
    return result


def _strict_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeformationVerificationError(f"{name} must be a non-blank string")
    return value


def _runtime_label(value: object, name: str) -> str:
    result = _strict_string(value, name)
    if result != unicodedata.normalize("NFC", result.strip()):
        raise DeformationVerificationError(f"{name} is not stripped canonical NFC text")
    return result


def _nfc_string(value: object, name: str) -> str:
    result = _strict_string(value, name)
    if result != unicodedata.normalize("NFC", result):
        raise DeformationVerificationError(f"{name} is not canonical NFC text")
    return result


def _strict_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise DeformationVerificationError(f"{name} must be a boolean")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise DeformationVerificationError(f"{name} must be a sequence")
    return value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DeformationVerificationError(f"{name} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _exact_keys(
    value: Mapping[str, object],
    required: set[str],
    *,
    name: str,
    optional: Set[str] = frozenset(),
) -> None:
    missing = sorted(required - set(value))
    unexpected = sorted(set(value) - required - optional)
    if missing or unexpected:
        raise DeformationVerificationError(
            f"{name} fields mismatch; missing={missing}, extra={unexpected}"
        )


def _type(value: Mapping[str, object], expected: str, name: str) -> None:
    if value.get("type") != expected:
        raise DeformationVerificationError(f"{name} has the wrong canonical type tag")


def _field(value: object, name: str = "field") -> PrimeField:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "characteristic"}, name=name)
    if snapshot.get("type") != "arbogast.prime_field":
        raise DeformationVerificationError(f"{name} is not a prime-field snapshot")
    prime = _strict_int(snapshot.get("characteristic"), f"{name}.characteristic", minimum=2)
    if prime > MAX_PRIME:
        raise DeformationVerificationError(
            f"{name}.characteristic exceeds the portable prime limit"
        )
    try:
        return PrimeField(prime)
    except ValidationError as exc:
        raise DeformationVerificationError(str(exc)) from exc


def _residue(value: object, name: str, field: PrimeField) -> int:
    result = _strict_int(value, name)
    if not 0 <= result < field.p:
        raise DeformationVerificationError(f"{name} is not a canonical field residue")
    return result


def _vector(value: object, name: str, field: PrimeField, length: int) -> Vector:
    result = tuple(
        _residue(item, f"{name}[{index}]", field)
        for index, item in enumerate(_sequence(value, name))
    )
    if len(result) != length:
        raise DeformationVerificationError(f"{name} has length {len(result)}, expected {length}")
    return result


def _rows(value: object, name: str, field: PrimeField, ncols: int) -> Rows:
    result = tuple(
        _vector(row, f"{name}[{index}]", field, ncols)
        for index, row in enumerate(_sequence(value, name))
    )
    if len(result) * ncols > MAX_MATRIX_CELLS:
        raise DeformationVerificationError(f"{name} exceeds the portable matrix cell limit")
    return result


def _matrix(
    value: object,
    name: str,
    *,
    field: PrimeField | None = None,
    nrows: int | None = None,
    ncols: int | None = None,
) -> DenseMatrix:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "field", "rows", "shape"}, name=name)
    if snapshot.get("type") != "arbogast.dense_matrix":
        raise DeformationVerificationError(f"{name} is not a dense-matrix snapshot")
    matrix_field = _field(snapshot.get("field"), f"{name}.field")
    if field is not None and matrix_field != field:
        raise DeformationVerificationError(f"{name} uses a different prime field")
    shape = tuple(
        _dimension(item, f"{name}.shape[{index}]")
        for index, item in enumerate(_sequence(snapshot.get("shape"), f"{name}.shape"))
    )
    if len(shape) != 2:
        raise DeformationVerificationError(f"{name}.shape must have two entries")
    if shape[0] * shape[1] > MAX_MATRIX_CELLS:
        raise DeformationVerificationError(f"{name} exceeds the portable matrix cell limit")
    rows = _rows(snapshot.get("rows"), f"{name}.rows", matrix_field, shape[1])
    if len(rows) != shape[0]:
        raise DeformationVerificationError(f"{name} row count does not match its shape")
    if nrows is not None and shape[0] != nrows:
        raise DeformationVerificationError(f"{name} has the wrong row count")
    if ncols is not None and shape[1] != ncols:
        raise DeformationVerificationError(f"{name} has the wrong column count")
    return DenseMatrix(matrix_field, rows, ncols=shape[1])


def _subspace(
    value: object,
    name: str,
    *,
    field: PrimeField | None = None,
    ambient_dimension: int | None = None,
) -> LinearSubspace:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"type", "field", "ambient_dimension", "basis"},
        name=name,
    )
    if snapshot.get("type") != "arbogast.linear_subspace":
        raise DeformationVerificationError(f"{name} is not a linear-subspace snapshot")
    subspace_field = _field(snapshot.get("field"), f"{name}.field")
    if field is not None and subspace_field != field:
        raise DeformationVerificationError(f"{name} uses a different prime field")
    ambient = _dimension(snapshot.get("ambient_dimension"), f"{name}.ambient_dimension")
    if ambient_dimension is not None and ambient != ambient_dimension:
        raise DeformationVerificationError(f"{name} has the wrong ambient dimension")
    basis = _rows(snapshot.get("basis"), f"{name}.basis", subspace_field, ambient)
    canonical = LinearSubspace(subspace_field, ambient, basis)
    if canonical.basis != basis:
        raise DeformationVerificationError(f"{name} basis is not canonical RREF data")
    return canonical


def _quotient(value: object, name: str) -> tuple[LinearSubspace, LinearSubspace, LinearSubspace]:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"type", "numerator", "denominator", "representatives"},
        name=name,
    )
    if snapshot.get("type") != "arbogast.quotient_space":
        raise DeformationVerificationError(f"{name} is not a quotient-space snapshot")
    numerator = _subspace(snapshot.get("numerator"), f"{name}.numerator")
    denominator = _subspace(
        snapshot.get("denominator"),
        f"{name}.denominator",
        field=numerator.field,
        ambient_dimension=numerator.ambient_dimension,
    )
    representatives = _subspace(
        snapshot.get("representatives"),
        f"{name}.representatives",
        field=numerator.field,
        ambient_dimension=numerator.ambient_dimension,
    )
    expected = quotient_space(numerator, denominator)
    if expected.representatives != representatives:
        raise DeformationVerificationError(
            f"{name} representatives are not the canonical quotient complement"
        )
    return numerator, denominator, representatives


def _zero_matrix(matrix: DenseMatrix) -> bool:
    return all(value == 0 for row in matrix.rows for value in row)


def _identity_matrix(matrix: DenseMatrix) -> bool:
    return matrix == DenseMatrix.identity(matrix.field, matrix.nrows)


def _matrix_power(matrix: DenseMatrix, exponent: int) -> DenseMatrix:
    if matrix.nrows != matrix.ncols:
        raise DeformationVerificationError("matrix power requires a square matrix")
    result = DenseMatrix.identity(matrix.field, matrix.nrows)
    base = matrix
    value = exponent
    while value:
        if value & 1:
            result = result @ base
        base = base @ base
        value >>= 1
    return result


def _dot(left: Sequence[int], right: Sequence[int], prime: int) -> int:
    if len(left) != len(right):
        raise DeformationVerificationError("dot-product vectors have different lengths")
    return sum(a * b for a, b in zip(left, right, strict=True)) % prime


def _difference(left: Sequence[int], right: Sequence[int], prime: int) -> Vector:
    if len(left) != len(right):
        raise DeformationVerificationError("vectors have different lengths")
    return tuple((a - b) % prime for a, b in zip(left, right, strict=True))


def _sum_vectors(left: Sequence[int], right: Sequence[int], prime: int) -> Vector:
    if len(left) != len(right):
        raise DeformationVerificationError("vectors have different lengths")
    return tuple((a + b) % prime for a, b in zip(left, right, strict=True))


def _linear_combination(
    basis: Sequence[Sequence[int]], coefficients: Sequence[int], prime: int, ambient: int
) -> Vector:
    if len(basis) != len(coefficients):
        raise DeformationVerificationError("basis coefficient count is wrong")
    return tuple(
        sum(coefficients[index] * basis[index][coordinate] for index in range(len(basis))) % prime
        for coordinate in range(ambient)
    )


def _reject_backend_leaks(value: object) -> None:
    forbidden = {
        "backend_handle",
        "gp_handle",
        "pari_handle",
        "session",
        "session_index",
        "printed_padic",
        "polredbest_identification",
    }
    if isinstance(value, Mapping):
        leaked = forbidden.intersection(value)
        if leaked:
            raise DeformationVerificationError(
                f"backend-local fields cannot cross the proof boundary: {sorted(leaked)}"
            )
        for item in value.values():
            _reject_backend_leaks(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_backend_leaks(item)


def _validate_unsupported_requested_payload(payload: Mapping[str, object]) -> None:
    requested = payload.get("requested")
    if not isinstance(requested, Mapping):
        return
    _canonical_requested(cast(Mapping[str, object], requested))


@dataclass(frozen=True)
class DeformationReceipt(ContentAddressedCertificate):
    """One independently versioned, content-addressed finite deformation receipt."""

    kind: str
    payload: FrozenMap
    dependencies: tuple[VerificationCertificate, ...] = ()
    assumptions: tuple[str, ...] = ()
    completeness: Completeness = "complete"
    verifier_trust: str = PORTABLE_TRUST

    layer: ClassVar[CertificateLayer] = CertificateLayer.VERIFICATION

    def __post_init__(self) -> None:
        if self.kind not in RECEIPT_SCHEMAS:
            raise CertificateError(f"unsupported deformation receipt kind: {self.kind!r}")
        if self.kind == "unsupported":
            try:
                _validate_unsupported_requested_payload(self.payload)
            except DeformationError as exc:
                raise CertificateError(str(exc)) from exc
        object.__setattr__(self, "payload", freeze_mapping(self.payload))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        if any(not isinstance(item, VerificationCertificate) for item in self.dependencies):
            raise CertificateError(
                "deformation dependencies must contain VerificationCertificate values"
            )
        dependency_ids = tuple(item.certificate_id for item in self.dependencies)
        if len(set(dependency_ids)) != len(dependency_ids):
            raise CertificateError("deformation dependency certificates must be unique")
        if dependency_ids != tuple(sorted(dependency_ids)):
            raise CertificateError("deformation dependency certificates must be canonicalized")
        assumptions = tuple(self.assumptions)
        if any(not isinstance(item, str) or not item.strip() for item in assumptions):
            raise CertificateError("deformation assumptions must be non-blank strings")
        if any(item != unicodedata.normalize("NFC", item) for item in assumptions):
            raise CertificateError("deformation assumptions must use canonical NFC text")
        if assumptions != tuple(sorted(set(assumptions))):
            raise CertificateError("deformation assumptions must be sorted and unique")
        object.__setattr__(self, "assumptions", assumptions)
        if self.completeness not in {"candidate", "complete"}:
            raise CertificateError("deformation completeness must be candidate or complete")
        if self.verifier_trust != PORTABLE_TRUST:
            raise CertificateError("finite deformation receipts require portable Python trust")

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
    ) -> DeformationReceipt:
        if kind == "unsupported":
            try:
                _validate_unsupported_requested_payload(payload)
            except DeformationError as exc:
                raise CertificateError(str(exc)) from exc
        canonical_dependencies = tuple(
            sorted(dependencies, key=lambda certificate: certificate.certificate_id)
        )
        normalized_assumptions = tuple(sorted(set(assumptions)))
        normalized_completeness: Completeness = (
            "candidate"
            if completeness is None and kind in {"lift-unknown", "unsupported"}
            else completeness or "complete"
        )
        return cls(
            kind,
            freeze_mapping(payload),
            canonical_dependencies,
            normalized_assumptions,
            normalized_completeness,
            PORTABLE_TRUST,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> DeformationReceipt:
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
        unexpected = sorted(set(value) - allowed)
        missing = sorted(required - set(value))
        if unexpected or missing:
            raise CertificateError(
                f"deformation receipt fields mismatch; missing={missing}, extra={unexpected}"
            )
        kind = value["kind"]
        if not isinstance(kind, str) or kind not in RECEIPT_SCHEMAS:
            raise CertificateError("unsupported deformation receipt kind")
        if value["schema_version"] != RECEIPT_SCHEMAS[kind]:
            raise CertificateError("missing or unsupported deformation receipt schema")
        if value["layer"] != CertificateLayer.VERIFICATION.value:
            raise CertificateError("deformation receipt has the wrong evidence layer")
        payload = value["payload"]
        if not isinstance(payload, Mapping):
            raise CertificateError("deformation receipt payload must be a mapping")
        if kind == "unsupported":
            try:
                _validate_unsupported_requested_payload(payload)
            except DeformationError as exc:
                raise CertificateError(str(exc)) from exc
        raw_dependencies = value["dependencies"]
        if isinstance(raw_dependencies, (str, bytes)) or not isinstance(raw_dependencies, Sequence):
            raise CertificateError("deformation dependencies must be a sequence")
        dependencies: list[VerificationCertificate] = []
        for raw in raw_dependencies:
            if not isinstance(raw, Mapping):
                raise CertificateError("deformation dependency must be a certificate mapping")
            dependencies.append(VerificationCertificate.from_dict(raw))
        raw_assumptions = value["assumptions"]
        if isinstance(raw_assumptions, (str, bytes)) or not isinstance(raw_assumptions, Sequence):
            raise CertificateError("deformation assumptions must be a sequence")
        assumptions: list[str] = []
        for item in raw_assumptions:
            if not isinstance(item, str):
                raise CertificateError("deformation assumptions must contain strings")
            assumptions.append(item)
        completeness = value["completeness"]
        if completeness not in {"candidate", "complete"}:
            raise CertificateError("invalid deformation completeness")
        trust = value["verifier_trust"]
        if trust != PORTABLE_TRUST:
            raise CertificateError("invalid deformation verifier trust")
        receipt = cls(
            kind,
            freeze_mapping(payload),
            tuple(dependencies),
            tuple(assumptions),
            completeness,
            trust,
        )
        expected = value.get("certificate_id")
        if expected is not None:
            if not isinstance(expected, str):
                raise CertificateError("deformation certificate_id must be a string")
            receipt.verify_integrity(expected)
        return receipt

    def verify(self) -> tuple[str, ...]:
        """Replay this receipt without consulting its originating runtime object."""

        self.verify_integrity()
        return verify_deformation_receipt(self)

    @property
    def certificate(self) -> VerificationCertificate:
        from .semantic import verification_certificate_for_receipt

        return verification_certificate_for_receipt(self)

    def claim(self) -> Claim:
        from .semantic import claim_for_receipt

        return claim_for_receipt(self)

    def claim_graph(self) -> ClaimGraph:
        from .semantic import claim_graph_for_receipt

        return claim_graph_for_receipt(self)


def _ring_multiply(
    constants: Sequence[Sequence[Sequence[int]]],
    left: Sequence[int],
    right: Sequence[int],
    prime: int,
) -> Vector:
    dimension = len(constants)
    return tuple(
        sum(
            left[i] * right[j] * constants[i][j][coordinate]
            for i in range(dimension)
            for j in range(dimension)
        )
        % prime
        for coordinate in range(dimension)
    )


def _ring_data(
    value: object, name: str = "artin ring"
) -> tuple[
    Mapping[str, object],
    PrimeField,
    tuple[tuple[Vector, ...], ...],
    Vector,
    Vector,
    tuple[LinearSubspace, ...],
]:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {
            "type",
            "field",
            "dimension",
            "basis_names",
            "structure_constants",
            "unit",
            "residue",
            "maximal_ideal_powers",
        },
        name=name,
    )
    _type(snapshot, "arbogast.deform.artin_ring", name)
    field = _field(snapshot.get("field"), f"{name}.field")
    dimension = _dimension(snapshot.get("dimension"), f"{name}.dimension")
    if dimension == 0:
        raise DeformationVerificationError("an Artin ring must have positive dimension")
    if dimension**3 > MAX_TENSOR_CELLS:
        raise DeformationVerificationError("ring structure tensor exceeds the portable limit")
    basis_names = tuple(
        _nfc_string(item, f"{name}.basis_names[{index}]")
        for index, item in enumerate(_sequence(snapshot.get("basis_names"), f"{name}.basis_names"))
    )
    if len(basis_names) != dimension or len(set(basis_names)) != dimension:
        raise DeformationVerificationError("ring basis names must be complete and unique")
    raw_constants = _sequence(snapshot.get("structure_constants"), f"{name}.structure_constants")
    if len(raw_constants) != dimension:
        raise DeformationVerificationError("ring structure tensor has the wrong first dimension")
    constants: list[tuple[Vector, ...]] = []
    for left, raw_slice in enumerate(raw_constants):
        rows = _sequence(raw_slice, f"{name}.structure_constants[{left}]")
        if len(rows) != dimension:
            raise DeformationVerificationError(
                "ring structure tensor has the wrong second dimension"
            )
        constants.append(
            tuple(
                _vector(
                    row,
                    f"{name}.structure_constants[{left}][{right}]",
                    field,
                    dimension,
                )
                for right, row in enumerate(rows)
            )
        )
    structure = tuple(constants)
    unit = _vector(snapshot.get("unit"), f"{name}.unit", field, dimension)
    residue = _vector(snapshot.get("residue"), f"{name}.residue", field, dimension)
    basis = tuple(
        tuple(1 if row == column else 0 for row in range(dimension)) for column in range(dimension)
    )
    for element in basis:
        if _ring_multiply(structure, unit, element, field.p) != element:
            raise DeformationVerificationError("ring unit does not act on the left")
        if _ring_multiply(structure, element, unit, field.p) != element:
            raise DeformationVerificationError("ring unit does not act on the right")
    for left in range(dimension):
        for right in range(dimension):
            if structure[left][right] != structure[right][left]:
                raise DeformationVerificationError("Artin ring multiplication is not commutative")
            product = structure[left][right]
            if _dot(residue, product, field.p) != residue[left] * residue[right] % field.p:
                raise DeformationVerificationError("ring residue map is not multiplicative")
            for third in range(dimension):
                left_product = _ring_multiply(
                    structure, structure[left][right], basis[third], field.p
                )
                right_product = _ring_multiply(
                    structure, basis[left], structure[right][third], field.p
                )
                if left_product != right_product:
                    raise DeformationVerificationError(
                        "Artin ring multiplication is not associative"
                    )
    if _dot(residue, unit, field.p) != 1:
        raise DeformationVerificationError("ring residue map does not preserve the unit")
    residue_matrix = DenseMatrix(field, (residue,), ncols=dimension)
    maximal_ideal = nullspace(residue_matrix)
    raw_powers = _sequence(snapshot.get("maximal_ideal_powers"), f"{name}.maximal_ideal_powers")
    if not raw_powers or len(raw_powers) > dimension + 1:
        raise DeformationVerificationError(
            "maximal-ideal powers must run from m through a bounded terminal zero"
        )
    powers: list[LinearSubspace] = []
    for power, raw_basis in enumerate(raw_powers, start=1):
        rows = _rows(
            raw_basis,
            f"{name}.maximal_ideal_powers[{power - 1}]",
            field,
            dimension,
        )
        subspace = LinearSubspace(field, dimension, rows)
        if subspace.basis != rows:
            raise DeformationVerificationError("maximal-ideal power basis is not canonical")
        powers.append(subspace)
    if powers[0] != maximal_ideal:
        raise DeformationVerificationError("first ideal power is not the residue-map kernel")
    for index in range(1, len(powers)):
        products = tuple(
            _ring_multiply(structure, left, right, field.p)
            for left in powers[index - 1].basis
            for right in maximal_ideal.basis
        )
        expected = LinearSubspace(field, dimension, products)
        if powers[index] != expected:
            raise DeformationVerificationError("maximal-ideal power does not replay")
    if powers[-1].dimension != 0:
        raise DeformationVerificationError("maximal-ideal powers do not end at zero")
    if len(powers) > 1 and powers[-2].dimension == 0:
        raise DeformationVerificationError("maximal-ideal power list has redundant zero terms")
    return snapshot, field, structure, unit, residue, tuple(powers)


@dataclass(frozen=True, slots=True)
class _ComplexData:
    snapshot: Mapping[str, object]
    field: PrimeField
    dimensions: tuple[int, int, int]
    d0: DenseMatrix
    d1: DenseMatrix


def _complex_data(value: object, name: str = "complex") -> _ComplexData:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"type", "field", "d0", "d1", "dimensions", "name"},
        name=name,
    )
    _type(snapshot, "arbogast.deform.complex", name)
    field = _field(snapshot.get("field"), f"{name}.field")
    raw_dimensions = tuple(
        _dimension(item, f"{name}.dimensions[{index}]")
        for index, item in enumerate(_sequence(snapshot.get("dimensions"), f"{name}.dimensions"))
    )
    if len(raw_dimensions) != 3:
        raise DeformationVerificationError("deformation complex must have degrees 0, 1, and 2")
    dimensions = raw_dimensions
    d0 = _matrix(
        snapshot.get("d0"),
        f"{name}.d0",
        field=field,
        nrows=dimensions[1],
        ncols=dimensions[0],
    )
    d1 = _matrix(
        snapshot.get("d1"),
        f"{name}.d1",
        field=field,
        nrows=dimensions[2],
        ncols=dimensions[1],
    )
    complex_name = snapshot.get("name")
    if complex_name is not None:
        _runtime_label(complex_name, f"{name}.name")
    if not _zero_matrix(d1 @ d0):
        raise DeformationVerificationError("deformation differentials do not compose to zero")
    return _ComplexData(snapshot, field, dimensions, d0, d1)


def _tangent_quotient(complex_: _ComplexData) -> tuple[LinearSubspace, LinearSubspace]:
    numerator = nullspace(complex_.d1)
    denominator = image(complex_.d0)
    return numerator, denominator


def _obstruction_quotient(complex_: _ComplexData) -> tuple[LinearSubspace, LinearSubspace]:
    numerator = LinearSubspace.full(complex_.field, complex_.dimensions[2])
    denominator = image(complex_.d1)
    return numerator, denominator


def _raw_matrix(
    value: object,
    name: str,
    *,
    field: PrimeField,
    nrows: int,
    ncols: int,
) -> DenseMatrix:
    rows = _rows(value, name, field, ncols)
    if len(rows) != nrows:
        raise DeformationVerificationError(f"{name} has the wrong row count")
    return DenseMatrix(field, rows, ncols=ncols)


def _canonical_object_id(value: Mapping[str, object]) -> str:
    return content_address(value)


def _receipt_from_dependency(certificate: VerificationCertificate) -> DeformationReceipt:
    if certificate.verifier != PORTABLE_VERIFIER:
        raise DeformationVerificationError(
            "finite deformation receipts may depend only on deformation verification receipts"
        )
    raw = certificate.witness.get("deformation_receipt")
    if not isinstance(raw, Mapping) or set(certificate.witness) != {"deformation_receipt"}:
        raise DeformationVerificationError(
            "deformation dependency does not embed exactly one deformation receipt"
        )
    try:
        return DeformationReceipt.from_dict(raw)
    except (CertificateError, TypeError, ValueError) as exc:
        raise DeformationVerificationError(
            f"deformation dependency receipt cannot be decoded: {exc}"
        ) from exc


def _dependency_receipts(receipt: DeformationReceipt) -> tuple[DeformationReceipt, ...]:
    if not receipt.dependencies:
        return ()
    # Importing the semantic bridge here makes the verifier available even when
    # callers imported this low-level module directly.
    from . import semantic as _semantic

    result_by_id: dict[str, DeformationReceipt] = {}
    active: set[str] = set()

    def collect(certificate: VerificationCertificate) -> None:
        certificate_id = certificate.certificate_id
        if certificate_id in result_by_id:
            return
        if certificate_id in active:
            raise DeformationVerificationError(
                "deformation dependency graph contains a certificate cycle"
            )
        active.add(certificate_id)
        dependency = _receipt_from_dependency(certificate)
        result_by_id[certificate_id] = dependency
        for nested in dependency.dependencies:
            collect(nested)
        active.remove(certificate_id)

    for certificate in receipt.dependencies:
        dependency = _receipt_from_dependency(certificate)
        try:
            replay_checks = verify_deformation_receipt(dependency)
            _semantic._verify_semantic_certificate_with_receipt(
                certificate,
                dependency,
                replay_checks,
            )
        except Exception as exc:
            raise DeformationVerificationError(
                f"deformation dependency failed replay: {certificate.certificate_id}: {exc}"
            ) from exc
        collect(certificate)
    result = tuple(result_by_id[certificate_id] for certificate_id in sorted(result_by_id))
    inherited_assumptions = {
        assumption for dependency in result for assumption in dependency.assumptions
    }
    if not inherited_assumptions.issubset(receipt.assumptions):
        raise DeformationVerificationError(
            "deformation receipt hides an assumption required by a dependency"
        )
    if receipt.completeness == "complete" and any(
        dependency.completeness != "complete" for dependency in result
    ):
        raise DeformationVerificationError(
            "a complete deformation receipt depends on candidate evidence"
        )
    return result


def _walk_snapshots(value: object) -> Iterable[Mapping[str, object]]:
    if isinstance(value, Mapping):
        snapshot = cast(Mapping[str, object], value)
        if isinstance(snapshot.get("type"), str):
            yield snapshot
        for item in snapshot.values():
            yield from _walk_snapshots(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _walk_snapshots(item)


@dataclass(frozen=True, slots=True)
class _ProofIndex:
    snapshots: Mapping[str, Mapping[str, object]]

    @classmethod
    def create(
        cls,
        receipt: DeformationReceipt,
        dependencies: Sequence[DeformationReceipt],
    ) -> _ProofIndex:
        snapshots: dict[str, Mapping[str, object]] = {}
        for source in (receipt, *dependencies):
            for snapshot in _walk_snapshots(source.payload.to_dict()):
                identifier = _canonical_object_id(snapshot)
                existing = snapshots.get(identifier)
                if existing is not None and existing != snapshot:
                    raise DeformationVerificationError(
                        "canonical deformation object identity is not injective"
                    )
                snapshots[identifier] = snapshot
        return cls(snapshots)

    def resolve(self, identifier: object, expected_type: str, name: str) -> Mapping[str, object]:
        value = _strict_string(identifier, name)
        snapshot = self.snapshots.get(value)
        if snapshot is None:
            raise DeformationVerificationError(
                f"{name} lacks an embedded proving dependency for {value}"
            )
        _type(snapshot, expected_type, name)
        return snapshot


@dataclass(frozen=True, slots=True)
class _RingMapData:
    snapshot: Mapping[str, object]
    domain: Mapping[str, object]
    codomain: Mapping[str, object]
    field: PrimeField
    domain_structure: tuple[tuple[Vector, ...], ...]
    codomain_structure: tuple[tuple[Vector, ...], ...]
    domain_unit: Vector
    codomain_unit: Vector
    domain_residue: Vector
    codomain_residue: Vector
    matrix: DenseMatrix


def _artin_map_data(
    value: object,
    index: _ProofIndex,
    name: str = "Artin-ring map",
) -> _RingMapData:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "domain_id", "codomain_id", "matrix"}, name=name)
    _type(snapshot, EXPECTED_TYPES["artin-map"], name)
    domain = index.resolve(snapshot.get("domain_id"), EXPECTED_TYPES["artin-ring"], "domain_id")
    codomain = index.resolve(
        snapshot.get("codomain_id"), EXPECTED_TYPES["artin-ring"], "codomain_id"
    )
    (
        _,
        field,
        domain_structure,
        domain_unit,
        domain_residue,
        _,
    ) = _ring_data(domain, "Artin-map domain")
    (
        _,
        codomain_field,
        codomain_structure,
        codomain_unit,
        codomain_residue,
        _,
    ) = _ring_data(codomain, "Artin-map codomain")
    if codomain_field != field:
        raise DeformationVerificationError("Artin-ring map changes the residue prime field")
    domain_dimension = len(domain_structure)
    codomain_dimension = len(codomain_structure)
    matrix = _raw_matrix(
        snapshot.get("matrix"),
        f"{name}.matrix",
        field=field,
        nrows=codomain_dimension,
        ncols=domain_dimension,
    )
    if matrix.matvec(domain_unit) != codomain_unit:
        raise DeformationVerificationError("Artin-ring map does not preserve the unit")
    for left in range(domain_dimension):
        image_left = matrix.column(left)
        if _dot(codomain_residue, image_left, field.p) != domain_residue[left]:
            raise DeformationVerificationError("Artin-ring map does not commute with residues")
        for right in range(domain_dimension):
            mapped_product = matrix.matvec(domain_structure[left][right])
            image_product = _ring_multiply(
                codomain_structure,
                image_left,
                matrix.column(right),
                field.p,
            )
            if mapped_product != image_product:
                raise DeformationVerificationError(
                    "Artin-ring map does not preserve multiplication"
                )
    return _RingMapData(
        snapshot,
        domain,
        codomain,
        field,
        domain_structure,
        codomain_structure,
        domain_unit,
        codomain_unit,
        domain_residue,
        codomain_residue,
        matrix,
    )


def _verify_small_extension(value: object, index: _ProofIndex) -> _RingMapData:
    snapshot = _mapping(value, "small extension")
    _exact_keys(
        snapshot,
        {"type", "projection_id", "kernel_basis", "inclusion"},
        name="small extension",
    )
    _type(snapshot, EXPECTED_TYPES["small-extension"], "small extension")
    projection_snapshot = index.resolve(
        snapshot.get("projection_id"),
        EXPECTED_TYPES["artin-map"],
        "projection_id",
    )
    projection = _artin_map_data(projection_snapshot, index, "small-extension projection")
    domain_dimension = projection.matrix.ncols
    kernel_rows = _rows(
        snapshot.get("kernel_basis"),
        "small extension kernel_basis",
        projection.field,
        domain_dimension,
    )
    kernel = LinearSubspace(projection.field, domain_dimension, kernel_rows)
    if kernel.basis != kernel_rows or kernel != nullspace(projection.matrix):
        raise DeformationVerificationError(
            "small-extension kernel_basis is not the exact canonical projection kernel"
        )
    if rank(projection.matrix) != projection.matrix.nrows:
        raise DeformationVerificationError("small-extension projection is not surjective")
    maximal_ideal = nullspace(
        DenseMatrix(
            projection.field,
            (projection.domain_residue,),
            ncols=domain_dimension,
        )
    )
    for maximal_ideal_vector in maximal_ideal.basis:
        for kernel_vector in kernel.basis:
            if any(
                _ring_multiply(
                    projection.domain_structure,
                    maximal_ideal_vector,
                    kernel_vector,
                    projection.field.p,
                )
            ):
                raise DeformationVerificationError(
                    "small-extension kernel is not annihilated by the source maximal ideal"
                )
    for left in kernel.basis:
        for right in kernel.basis:
            if any(
                _ring_multiply(
                    projection.domain_structure,
                    left,
                    right,
                    projection.field.p,
                )
            ):
                raise DeformationVerificationError("small-extension kernel is not square-zero")
    inclusion = _raw_matrix(
        snapshot.get("inclusion"),
        "small extension inclusion",
        field=projection.field,
        nrows=domain_dimension,
        ncols=kernel.dimension,
    )
    expected_inclusion = DenseMatrix.from_columns(
        projection.field,
        kernel.basis,
        nrows=domain_dimension,
    )
    if inclusion != expected_inclusion:
        raise DeformationVerificationError(
            "small-extension inclusion columns are not the canonical kernel basis"
        )
    if not _zero_matrix(projection.matrix @ inclusion):
        raise DeformationVerificationError("small-extension projection-inclusion is nonzero")
    return projection


def _framing_data(value: object, name: str = "framing") -> tuple[DenseMatrix, LinearSubspace]:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"type", "constraints", "ambient_dimension", "allowed_gauge", "label"},
        name=name,
    )
    _type(snapshot, EXPECTED_TYPES["framing"], name)
    constraints = _matrix(snapshot.get("constraints"), f"{name}.constraints")
    ambient = _dimension(snapshot.get("ambient_dimension"), f"{name}.ambient_dimension")
    if constraints.ncols != ambient:
        raise DeformationVerificationError("framing ambient dimension was altered")
    allowed = _subspace(
        snapshot.get("allowed_gauge"),
        f"{name}.allowed_gauge",
        field=constraints.field,
        ambient_dimension=ambient,
    )
    if allowed != nullspace(constraints):
        raise DeformationVerificationError("allowed gauge space is not the framing kernel")
    label = snapshot.get("label")
    if label is not None:
        _runtime_label(label, f"{name}.label")
    return constraints, allowed


def _presentation_data(value: object, name: str = "presentation") -> _ComplexData:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "complex", "source_id", "name"}, name=name)
    _type(snapshot, "arbogast.deform.presentation", name)
    complex_ = _complex_data(snapshot.get("complex"), f"{name}.complex")
    _runtime_label(snapshot.get("source_id"), f"{name}.source_id")
    presentation_name = snapshot.get("name")
    if presentation_name is not None:
        _runtime_label(presentation_name, f"{name}.name")
    return complex_


def _restricted_complex(
    complex_: _ComplexData,
    allowed_gauge: LinearSubspace,
) -> tuple[DenseMatrix, DenseMatrix, tuple[int, int, int]]:
    inclusion = DenseMatrix.from_columns(
        complex_.field,
        allowed_gauge.basis,
        nrows=complex_.dimensions[0],
    )
    return (
        complex_.d0 @ inclusion,
        complex_.d1,
        (allowed_gauge.dimension, complex_.dimensions[1], complex_.dimensions[2]),
    )


def _expected_complex_snapshot(
    field: PrimeField,
    d0: DenseMatrix,
    d1: DenseMatrix,
    dimensions: tuple[int, int, int],
    name: object,
) -> dict[str, object]:
    return {
        "d0": d0.to_canonical_data(),
        "d1": d1.to_canonical_data(),
        "dimensions": list(dimensions),
        "field": field.to_canonical_data(),
        "name": name,
        "type": "arbogast.deform.complex",
    }


def _problem_data(value: object, name: str = "problem") -> _ComplexData:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"type", "presentation", "effective_complex", "framing"},
        name=name,
    )
    _type(snapshot, EXPECTED_TYPES["problem"], name)
    presented = _presentation_data(snapshot.get("presentation"), f"{name}.presentation")
    effective = _complex_data(snapshot.get("effective_complex"), f"{name}.effective_complex")
    raw_framing = snapshot.get("framing")
    if raw_framing is None:
        if dict(effective.snapshot) != dict(presented.snapshot):
            raise DeformationVerificationError(
                "unframed problem effective complex differs from its presentation"
            )
        return effective
    _, allowed = _framing_data(raw_framing, f"{name}.framing")
    if allowed.field != presented.field or allowed.ambient_dimension != presented.dimensions[0]:
        raise DeformationVerificationError("problem framing belongs to a different degree zero")
    expected_d0, expected_d1, expected_dimensions = _restricted_complex(presented, allowed)
    expected_snapshot = _expected_complex_snapshot(
        presented.field,
        expected_d0,
        expected_d1,
        expected_dimensions,
        presented.snapshot.get("name"),
    )
    if dict(effective.snapshot) != expected_snapshot:
        raise DeformationVerificationError("framed problem effective complex does not replay")
    return effective


def _resolve_problem(
    snapshot: Mapping[str, object], index: _ProofIndex, name: str = "problem_id"
) -> _ComplexData:
    problem = index.resolve(snapshot.get(name), EXPECTED_TYPES["problem"], name)
    return _problem_data(problem, name.removesuffix("_id"))


def _verify_gauge(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "gauge space")
    _exact_keys(snapshot, {"type", "problem_id", "complex_id", "space"}, name="gauge")
    _type(snapshot, EXPECTED_TYPES["gauge"], "gauge")
    complex_ = _resolve_problem(snapshot, index)
    if snapshot.get("complex_id") != _canonical_object_id(complex_.snapshot):
        raise DeformationVerificationError("gauge complex_id is not the effective complex")
    space = _subspace(
        snapshot.get("space"),
        "gauge.space",
        field=complex_.field,
        ambient_dimension=complex_.dimensions[0],
    )
    if space != nullspace(complex_.d0):
        raise DeformationVerificationError("gauge space is not ker(d0)")
    return ("problem-and-complex-binding", "canonical-gauge-kernel")


def _verify_cohomology_space(
    value: object,
    index: _ProofIndex,
    *,
    obstruction: bool,
) -> tuple[_ComplexData, LinearSubspace, LinearSubspace, LinearSubspace]:
    kind = "obstruction-space" if obstruction else "tangent"
    snapshot = _mapping(value, kind)
    _exact_keys(
        snapshot,
        {"type", "problem_id", "complex_id", "quotient"},
        name=kind,
    )
    _type(snapshot, EXPECTED_TYPES[kind], kind)
    complex_ = _resolve_problem(snapshot, index)
    if snapshot.get("complex_id") != _canonical_object_id(complex_.snapshot):
        raise DeformationVerificationError(f"{kind} complex_id is not the effective complex")
    numerator, denominator, representatives = _quotient(
        snapshot.get("quotient"), f"{kind}.quotient"
    )
    expected_numerator, expected_denominator = (
        _obstruction_quotient(complex_) if obstruction else _tangent_quotient(complex_)
    )
    if numerator != expected_numerator or denominator != expected_denominator:
        description = "coker(d1)" if obstruction else "ker(d1)/im(d0)"
        raise DeformationVerificationError(f"{kind} is not the exact {description}")
    return complex_, numerator, denominator, representatives


def _verify_obstruction_class(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "obstruction class")
    _exact_keys(
        snapshot,
        {"type", "space_id", "ambient_vector", "class_coordinates", "is_zero"},
        name="obstruction class",
    )
    _type(snapshot, EXPECTED_TYPES["obstruction-class"], "obstruction class")
    space = index.resolve(snapshot.get("space_id"), EXPECTED_TYPES["obstruction-space"], "space_id")
    _, _, _, representatives = _verify_cohomology_space(space, index, obstruction=True)
    vector = _vector(
        snapshot.get("ambient_vector"),
        "obstruction_class.ambient_vector",
        representatives.field,
        representatives.ambient_dimension,
    )
    coordinates = _vector(
        snapshot.get("class_coordinates"),
        "obstruction_class.class_coordinates",
        representatives.field,
        representatives.dimension,
    )
    expected_vector = representatives.vector(coordinates)
    if vector != expected_vector or representatives.coordinates(vector) != coordinates:
        raise DeformationVerificationError(
            "obstruction class is not its canonical quotient representative"
        )
    if _strict_bool(snapshot.get("is_zero"), "obstruction_class.is_zero") != (not any(coordinates)):
        raise DeformationVerificationError("obstruction-class zero flag was altered")
    return ("obstruction-space-binding", "canonical-obstruction-class")


def _group_table(
    value: object,
    identity_value: object,
    order_value: object,
) -> tuple[tuple[tuple[int, ...], ...], int]:
    order = _dimension(order_value, "group_order")
    if order == 0 or order > MAX_GROUP_ORDER:
        raise DeformationVerificationError("action group order is outside the portable bound")
    identity = _strict_int(identity_value, "identity_index", minimum=0)
    if identity >= order:
        raise DeformationVerificationError("action identity index is outside the group")
    raw_rows = _sequence(value, "multiplication_table")
    if len(raw_rows) != order:
        raise DeformationVerificationError("group multiplication table has the wrong row count")
    table = tuple(
        tuple(
            _strict_int(entry, f"multiplication_table[{row}][{column}]", minimum=0)
            for column, entry in enumerate(_sequence(raw, f"multiplication_table[{row}]"))
        )
        for row, raw in enumerate(raw_rows)
    )
    if any(len(row) != order or any(entry >= order for entry in row) for row in table):
        raise DeformationVerificationError("group multiplication table has invalid entries")
    for element in range(order):
        if table[identity][element] != element or table[element][identity] != element:
            raise DeformationVerificationError("group multiplication table has the wrong identity")
        if not any(
            table[element][candidate] == identity and table[candidate][element] == identity
            for candidate in range(order)
        ):
            raise DeformationVerificationError("group multiplication table lacks an inverse")
    for left in range(order):
        for middle in range(order):
            for right in range(order):
                if table[table[left][middle]][right] != table[left][table[middle][right]]:
                    raise DeformationVerificationError(
                        "group multiplication table is not associative"
                    )
    return table, identity


@dataclass(frozen=True, slots=True)
class _ActionData:
    snapshot: Mapping[str, object]
    complex: _ComplexData
    table: tuple[tuple[int, ...], ...]
    identity: int
    actions: tuple[tuple[DenseMatrix, ...], ...]


def _action_data(
    value: object,
    index: _ProofIndex,
    name: str = "deformation action",
) -> _ActionData:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {
            "type",
            "complex_id",
            "degree_matrices",
            "group_order",
            "identity_index",
            "multiplication_table",
        },
        name=name,
    )
    _type(snapshot, "arbogast.deform.deformation_action", name)
    complex_snapshot = index.resolve(
        snapshot.get("complex_id"), EXPECTED_TYPES["complex"], f"{name}.complex_id"
    )
    complex_ = _complex_data(complex_snapshot, f"{name}.complex")
    table, identity = _group_table(
        snapshot.get("multiplication_table"),
        snapshot.get("identity_index"),
        snapshot.get("group_order"),
    )
    order = len(table)
    raw_degrees = _sequence(snapshot.get("degree_matrices"), f"{name}.degree_matrices")
    if len(raw_degrees) != 3:
        raise DeformationVerificationError("deformation action needs matrices in degrees 0, 1, 2")
    degrees: list[tuple[DenseMatrix, ...]] = []
    for degree, raw_actions in enumerate(raw_degrees):
        actions = _sequence(raw_actions, f"{name}.degree_matrices[{degree}]")
        if len(actions) != order:
            raise DeformationVerificationError(
                "every action degree must enumerate the complete group"
            )
        dimension = complex_.dimensions[degree]
        matrices = tuple(
            _matrix(
                raw,
                f"{name}.degree_matrices[{degree}][{element}]",
                field=complex_.field,
                nrows=dimension,
                ncols=dimension,
            )
            for element, raw in enumerate(actions)
        )
        if matrices[identity] != DenseMatrix.identity(complex_.field, dimension):
            raise DeformationVerificationError("group action does not preserve the identity")
        for left in range(order):
            for right in range(order):
                if matrices[left] @ matrices[right] != matrices[table[left][right]]:
                    raise DeformationVerificationError(
                        f"degree-{degree} matrices do not form a group representation"
                    )
        degrees.append(matrices)
    action_tuple = cast(tuple[tuple[DenseMatrix, ...], ...], tuple(degrees))
    for element in range(order):
        if complex_.d0 @ action_tuple[0][element] != action_tuple[1][element] @ complex_.d0:
            raise DeformationVerificationError("d0 is not equivariant")
        if complex_.d1 @ action_tuple[1][element] != action_tuple[2][element] @ complex_.d1:
            raise DeformationVerificationError("d1 is not equivariant")
    return _ActionData(snapshot, complex_, table, identity, action_tuple)


def _invariant_space(actions: Sequence[DenseMatrix], dimension: int) -> LinearSubspace:
    if not actions:
        raise DeformationVerificationError("invariant-space replay needs a complete action")
    field = actions[0].field
    identity = DenseMatrix.identity(field, dimension)
    equations = tuple(row for action in actions for row in (action - identity).rows)
    return nullspace(DenseMatrix(field, equations, ncols=dimension))


def _restriction_matrix(
    differential: DenseMatrix,
    domain: LinearSubspace,
    codomain: LinearSubspace,
) -> DenseMatrix:
    columns: list[Vector] = []
    for vector in domain.basis:
        mapped = differential.matvec(vector)
        if not codomain.contains(mapped):
            raise DeformationVerificationError(
                "differential does not preserve the advertised subspaces"
            )
        columns.append(codomain.coordinates(mapped))
    return DenseMatrix.from_columns(differential.field, columns, nrows=codomain.dimension)


def _verify_equivariant(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "equivariant deformation")
    _exact_keys(snapshot, {"type", "problem_id", "action"}, name="equivariant")
    _type(snapshot, EXPECTED_TYPES["equivariant"], "equivariant")
    problem = _resolve_problem(snapshot, index)
    action = _action_data(snapshot.get("action"), index)
    if _canonical_object_id(problem.snapshot) != _canonical_object_id(action.complex.snapshot):
        raise DeformationVerificationError("equivariant action is bound to a different complex")
    return (
        "problem-and-complex-binding",
        "finite-group-representation",
        "chain-equivariance",
    )


def _verify_invariant_complex(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "invariant deformations")
    _exact_keys(
        snapshot,
        {"type", "equivariant_id", "identifies_invariant_cohomology", "problem"},
        name="invariant deformations",
    )
    _type(snapshot, EXPECTED_TYPES["invariant-complex"], "invariant deformations")
    if _strict_bool(
        snapshot.get("identifies_invariant_cohomology"),
        "identifies_invariant_cohomology",
    ):
        raise DeformationVerificationError(
            "invariant subcomplex must not identify H(C^G) with H(C)^G"
        )
    equivariant = index.resolve(
        snapshot.get("equivariant_id"), EXPECTED_TYPES["equivariant"], "equivariant_id"
    )
    equivariant_snapshot = _mapping(equivariant, "equivariant dependency")
    action = _action_data(equivariant_snapshot.get("action"), index)
    problem_snapshot = _mapping(snapshot.get("problem"), "invariant problem")
    invariant_complex = _problem_data(problem_snapshot, "invariant problem")
    presentation = _mapping(problem_snapshot.get("presentation"), "invariant presentation")
    if presentation.get("source_id") != snapshot.get("equivariant_id"):
        raise DeformationVerificationError("invariant problem source binding was altered")
    spaces = tuple(
        _invariant_space(action.actions[degree], action.complex.dimensions[degree])
        for degree in range(3)
    )
    expected_d0 = _restriction_matrix(action.complex.d0, spaces[0], spaces[1])
    expected_d1 = _restriction_matrix(action.complex.d1, spaces[1], spaces[2])
    expected_dimensions = (
        spaces[0].dimension,
        spaces[1].dimension,
        spaces[2].dimension,
    )
    expected_complex = _expected_complex_snapshot(
        action.complex.field,
        expected_d0,
        expected_d1,
        expected_dimensions,
        "invariant subcomplex",
    )
    expected_presentation = {
        "complex": expected_complex,
        "name": "invariant subcomplex",
        "source_id": snapshot.get("equivariant_id"),
        "type": "arbogast.deform.presentation",
    }
    expected_problem = {
        "effective_complex": expected_complex,
        "framing": None,
        "presentation": expected_presentation,
        "type": EXPECTED_TYPES["problem"],
    }
    if dict(problem_snapshot) != expected_problem:
        raise DeformationVerificationError(
            "invariant problem is not the exact canonical unframed subcomplex"
        )
    if dict(invariant_complex.snapshot) != expected_complex:
        raise DeformationVerificationError("invariant subcomplex does not replay")
    return (
        "equivariant-dependency-binding",
        "degreewise-fixed-subspaces",
        "invariant-subcomplex",
        "no-invariant-cohomology-identification",
    )


def _component_data(
    value: object,
    ambient: _ComplexData,
    name: str,
) -> tuple[tuple[DenseMatrix, ...], tuple[LinearSubspace, ...]]:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {"type", "label", "ambient_id", "projectors", "subspaces", "complex"},
        name=name,
    )
    _type(snapshot, "arbogast.deform.equivariant_component", name)
    if snapshot.get("ambient_id") != _canonical_object_id(ambient.snapshot):
        raise DeformationVerificationError(
            "equivariant component is bound to another ambient complex"
        )
    label = _runtime_label(snapshot.get("label"), f"{name}.label")
    raw_projectors = _sequence(snapshot.get("projectors"), f"{name}.projectors")
    raw_subspaces = _sequence(snapshot.get("subspaces"), f"{name}.subspaces")
    if len(raw_projectors) != 3 or len(raw_subspaces) != 3:
        raise DeformationVerificationError("equivariant component must cover all three degrees")
    projectors = tuple(
        _matrix(
            raw,
            f"{name}.projectors[{degree}]",
            field=ambient.field,
            nrows=ambient.dimensions[degree],
            ncols=ambient.dimensions[degree],
        )
        for degree, raw in enumerate(raw_projectors)
    )
    subspaces = tuple(
        _subspace(
            raw,
            f"{name}.subspaces[{degree}]",
            field=ambient.field,
            ambient_dimension=ambient.dimensions[degree],
        )
        for degree, raw in enumerate(raw_subspaces)
    )
    for degree in range(3):
        projector = projectors[degree]
        if projector @ projector != projector:
            raise DeformationVerificationError("equivariant component projector is not idempotent")
        if image(projector) != subspaces[degree]:
            raise DeformationVerificationError("equivariant component subspace is not the image")
    if ambient.d0 @ projectors[0] != projectors[1] @ ambient.d0:
        raise DeformationVerificationError("component projectors do not commute with d0")
    if ambient.d1 @ projectors[1] != projectors[2] @ ambient.d1:
        raise DeformationVerificationError("component projectors do not commute with d1")
    component = _complex_data(snapshot.get("complex"), f"{name}.complex")
    if (
        component.field != ambient.field
        or component.dimensions != tuple(space.dimension for space in subspaces)
        or component.d0 != _restriction_matrix(ambient.d0, subspaces[0], subspaces[1])
        or component.d1 != _restriction_matrix(ambient.d1, subspaces[1], subspaces[2])
        or component.snapshot.get("name") != label
    ):
        raise DeformationVerificationError("equivariant component complex was altered")
    return projectors, subspaces


def _verify_decomposition(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "equivariant decomposition")
    _exact_keys(
        snapshot,
        {"type", "equivariant_id", "components", "complete"},
        name="equivariant decomposition",
    )
    _type(snapshot, EXPECTED_TYPES["decomposition"], "equivariant decomposition")
    if not _strict_bool(snapshot.get("complete"), "decomposition.complete"):
        raise DeformationVerificationError("equivariant decomposition is not complete")
    equivariant = index.resolve(
        snapshot.get("equivariant_id"), EXPECTED_TYPES["equivariant"], "equivariant_id"
    )
    equivariant_snapshot = _mapping(equivariant, "equivariant dependency")
    action = _action_data(equivariant_snapshot.get("action"), index)
    components_raw = _sequence(snapshot.get("components"), "decomposition.components")
    if len(components_raw) > 3 * MAX_DIMENSION:
        raise DeformationVerificationError(
            "decomposition has too many components for portable replay"
        )
    components = tuple(
        _component_data(raw, action.complex, f"decomposition.components[{number}]")
        for number, raw in enumerate(components_raw)
    )
    labels = tuple(
        _runtime_label(_mapping(raw, "component").get("label"), "component.label")
        for raw in components_raw
    )
    if labels != tuple(sorted(set(labels))):
        raise DeformationVerificationError("decomposition labels are not canonical and unique")
    if any(not any(space.dimension for space in subspaces) for _, subspaces in components):
        raise DeformationVerificationError("decomposition contains an all-zero component")
    for projectors, _ in components:
        for degree, projector in enumerate(projectors):
            for group_matrix in action.actions[degree]:
                if projector @ group_matrix != group_matrix @ projector:
                    raise DeformationVerificationError(
                        "component projector does not commute with the group action"
                    )
    for degree, dimension in enumerate(action.complex.dimensions):
        zero = DenseMatrix.zeros(action.complex.field, dimension, dimension)
        total = zero
        for left_index, (left, _) in enumerate(components):
            total = total + left[degree]
            for right_index, (right, _) in enumerate(components):
                if left_index != right_index and (
                    left[degree] @ right[degree] != zero or right[degree] @ left[degree] != zero
                ):
                    raise DeformationVerificationError(
                        "decomposition projectors are not pairwise orthogonal"
                    )
        if total != DenseMatrix.identity(action.complex.field, dimension):
            raise DeformationVerificationError("decomposition projectors are not complete")
    return (
        "equivariant-dependency-binding",
        "idempotent-chain-projectors",
        "action-compatible-components",
        "bounded-nonzero-components",
        "orthogonal-complete-decomposition",
    )


@dataclass(frozen=True, slots=True)
class _LiftDatumData:
    snapshot: Mapping[str, object]
    problem: Mapping[str, object]
    problem_complex: _ComplexData
    extension: Mapping[str, object]
    field: PrimeField
    target: Vector
    base_point: Vector
    correction: DenseMatrix
    gauge: DenseMatrix


def _lift_datum_data(
    value: object,
    index: _ProofIndex,
    name: str = "lift datum",
) -> _LiftDatumData:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {
            "type",
            "problem_id",
            "extension_id",
            "target",
            "base_point",
            "correction_matrix",
            "gauge_matrix",
            "label",
        },
        name=name,
    )
    _type(snapshot, EXPECTED_TYPES["lift-datum"], name)
    problem = index.resolve(snapshot.get("problem_id"), EXPECTED_TYPES["problem"], "problem_id")
    problem_complex = _problem_data(problem, f"{name}.problem")
    extension = index.resolve(
        snapshot.get("extension_id"), EXPECTED_TYPES["small-extension"], "extension_id"
    )
    projection = _verify_small_extension(extension, index)
    if projection.field != problem_complex.field:
        raise DeformationVerificationError(
            "lift datum extension and problem use different prime fields"
        )
    correction = _matrix(
        snapshot.get("correction_matrix"),
        f"{name}.correction_matrix",
        field=problem_complex.field,
    )
    target = _vector(
        snapshot.get("target"),
        f"{name}.target",
        problem_complex.field,
        correction.nrows,
    )
    base_point = _vector(
        snapshot.get("base_point"),
        f"{name}.base_point",
        problem_complex.field,
        correction.ncols,
    )
    gauge = _matrix(
        snapshot.get("gauge_matrix"),
        f"{name}.gauge_matrix",
        field=problem_complex.field,
        nrows=correction.ncols,
    )
    if not _zero_matrix(correction @ gauge):
        raise DeformationVerificationError("lift gauge corrections are not homogeneous directions")
    label = snapshot.get("label")
    if label is not None:
        _runtime_label(label, f"{name}.label")
    return _LiftDatumData(
        snapshot,
        problem,
        problem_complex,
        extension,
        problem_complex.field,
        target,
        base_point,
        correction,
        gauge,
    )


@dataclass(frozen=True, slots=True)
class _LiftFamilyData:
    snapshot: Mapping[str, object]
    datum: _LiftDatumData
    particular: Vector
    representative: Vector
    directions: LinearSubspace
    gauge_directions: LinearSubspace
    quotient_representatives: LinearSubspace

    def contains(self, point: Sequence[int]) -> bool:
        correction = _difference(point, self.datum.base_point, self.datum.field.p)
        return self.datum.correction.matvec(correction) == self.datum.target


def _lift_family_data(
    value: object,
    index: _ProofIndex,
    name: str = "lift family",
) -> _LiftFamilyData:
    snapshot = _mapping(value, name)
    _exact_keys(
        snapshot,
        {
            "type",
            "datum_id",
            "particular",
            "representative",
            "directions",
            "gauge_directions",
            "mod_gauge",
        },
        name=name,
    )
    _type(snapshot, EXPECTED_TYPES["lift-family"], name)
    datum_snapshot = index.resolve(
        snapshot.get("datum_id"), EXPECTED_TYPES["lift-datum"], f"{name}.datum_id"
    )
    datum = _lift_datum_data(datum_snapshot, index, f"{name}.datum")
    solution = solve(datum.correction, datum.target)
    if not solution.consistent or solution.particular is None:
        raise DeformationVerificationError("lift family is attached to an inconsistent datum")
    particular = _vector(
        snapshot.get("particular"),
        f"{name}.particular",
        datum.field,
        datum.correction.ncols,
    )
    if particular != solution.particular:
        raise DeformationVerificationError("lift-family particular solution was altered")
    directions = _subspace(
        snapshot.get("directions"),
        f"{name}.directions",
        field=datum.field,
        ambient_dimension=datum.correction.ncols,
    )
    if directions != solution.kernel:
        raise DeformationVerificationError("lift-family homogeneous directions were altered")
    gauge_directions = _subspace(
        snapshot.get("gauge_directions"),
        f"{name}.gauge_directions",
        field=datum.field,
        ambient_dimension=datum.correction.ncols,
    )
    if gauge_directions != image(datum.gauge):
        raise DeformationVerificationError("lift-family gauge directions were altered")
    quotient_numerator, quotient_denominator, quotient_representatives = _quotient(
        snapshot.get("mod_gauge"), f"{name}.mod_gauge"
    )
    if quotient_numerator != directions or quotient_denominator != gauge_directions:
        raise DeformationVerificationError("lift-family mod-gauge quotient was altered")
    representative = _vector(
        snapshot.get("representative"),
        f"{name}.representative",
        datum.field,
        datum.correction.ncols,
    )
    expected_representative = _sum_vectors(datum.base_point, particular, datum.field.p)
    if representative != expected_representative:
        raise DeformationVerificationError("lift-family representative was altered")
    result = _LiftFamilyData(
        snapshot,
        datum,
        particular,
        representative,
        directions,
        gauge_directions,
        quotient_representatives,
    )
    if not result.contains(representative):
        raise DeformationVerificationError("lift-family representative does not solve the datum")
    return result


def _verify_nested_obstruction_class(
    value: object,
    datum: _LiftDatumData,
) -> None:
    snapshot = _mapping(value, "lift obstruction class")
    _exact_keys(
        snapshot,
        {"type", "space_id", "ambient_vector", "class_coordinates", "is_zero"},
        name="lift obstruction class",
    )
    _type(snapshot, EXPECTED_TYPES["obstruction-class"], "lift obstruction class")
    numerator, denominator = _obstruction_quotient(datum.problem_complex)
    quotient = quotient_space(numerator, denominator)
    expected_space = {
        "complex_id": _canonical_object_id(datum.problem_complex.snapshot),
        "problem_id": _canonical_object_id(datum.problem),
        "quotient": quotient.to_canonical_data(),
        "type": EXPECTED_TYPES["obstruction-space"],
    }
    if snapshot.get("space_id") != content_address(expected_space):
        raise DeformationVerificationError("lift obstruction class is bound to another space")
    coordinates = _vector(
        snapshot.get("class_coordinates"),
        "lift obstruction class coordinates",
        datum.field,
        quotient.dimension,
    )
    ambient = _vector(
        snapshot.get("ambient_vector"),
        "lift obstruction ambient vector",
        datum.field,
        quotient.ambient_dimension,
    )
    expected_coordinates = quotient.class_coordinates(datum.target)
    expected_ambient = quotient.representative(expected_coordinates)
    if (
        quotient.representative(coordinates) != ambient
        or coordinates != expected_coordinates
        or ambient != expected_ambient
    ):
        raise DeformationVerificationError(
            "lift obstruction class is not the canonical class of the lift target"
        )
    is_zero = _strict_bool(snapshot.get("is_zero"), "lift obstruction is_zero")
    if is_zero != (not any(coordinates)) or is_zero:
        raise DeformationVerificationError("lift obstruction class is zero or mislabelled")


def _verify_lift_obstructed(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "obstructed lift")
    _exact_keys(
        snapshot,
        {"type", "datum_id", "separating_witness", "obstruction_class"},
        name="obstructed lift",
    )
    _type(snapshot, EXPECTED_TYPES["lift-obstructed"], "obstructed lift")
    datum_snapshot = index.resolve(
        snapshot.get("datum_id"), EXPECTED_TYPES["lift-datum"], "datum_id"
    )
    datum = _lift_datum_data(datum_snapshot, index)
    solution = solve(datum.correction, datum.target)
    if solution.consistent or solution.inconsistency_witness is None:
        raise DeformationVerificationError("obstructed lift has a consistent correction equation")
    witness = _vector(
        snapshot.get("separating_witness"),
        "separating_witness",
        datum.field,
        datum.correction.nrows,
    )
    if witness != solution.inconsistency_witness:
        raise DeformationVerificationError("lift separating witness was altered")
    obstruction_class = snapshot.get("obstruction_class")
    if obstruction_class is not None:
        if datum.correction != datum.problem_complex.d1:
            raise DeformationVerificationError(
                "nonstandard correction law cannot claim the problem obstruction class"
            )
        _verify_nested_obstruction_class(obstruction_class, datum)
    return (
        "lift-datum-binding",
        "left-nullspace-separating-witness",
        "inconsistent-correction-equation",
    )


def _verify_lift_unknown(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "unknown lift")
    _exact_keys(snapshot, {"type", "datum_id", "reason"}, name="unknown lift")
    _type(snapshot, EXPECTED_TYPES["lift-unknown"], "unknown lift")
    datum_id = snapshot.get("datum_id")
    if datum_id is not None:
        datum = index.resolve(datum_id, EXPECTED_TYPES["lift-datum"], "datum_id")
        _lift_datum_data(datum, index)
    _runtime_label(snapshot.get("reason"), "unknown lift reason")
    return ("explicit-nonconclusion", "reason-binding")


def _verify_unique_lift(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "unique lift")
    _exact_keys(snapshot, {"type", "family_id", "representative"}, name="unique lift")
    _type(snapshot, EXPECTED_TYPES["unique-lift"], "unique lift")
    family_snapshot = index.resolve(
        snapshot.get("family_id"), EXPECTED_TYPES["lift-family"], "family_id"
    )
    family = _lift_family_data(family_snapshot, index)
    representative = _vector(
        snapshot.get("representative"),
        "unique lift representative",
        family.datum.field,
        family.datum.correction.ncols,
    )
    if representative != family.representative:
        raise DeformationVerificationError("unique lift representative was altered")
    if family.quotient_representatives.dimension != 0:
        raise DeformationVerificationError("unique lift has nontrivial mod-gauge directions")
    return ("lift-family-binding", "zero-mod-gauge-tangent", "unique-representative")


def _verify_nonunique_lift(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "nonunique lift")
    _exact_keys(
        snapshot,
        {"type", "family_id", "first", "second", "separating_class_coordinates"},
        name="nonunique lift",
    )
    _type(snapshot, EXPECTED_TYPES["nonunique-lift"], "nonunique lift")
    family_snapshot = index.resolve(
        snapshot.get("family_id"), EXPECTED_TYPES["lift-family"], "family_id"
    )
    family = _lift_family_data(family_snapshot, index)
    size = family.datum.correction.ncols
    first = _vector(snapshot.get("first"), "first lift", family.datum.field, size)
    second = _vector(snapshot.get("second"), "second lift", family.datum.field, size)
    if not family.contains(first) or not family.contains(second):
        raise DeformationVerificationError("nonunique witnesses do not both solve the datum")
    difference = _difference(second, first, family.datum.field.p)
    coordinates = family.quotient_representatives.coordinates(
        family.gauge_directions.reduce(difference)
    )
    advertised = _vector(
        snapshot.get("separating_class_coordinates"),
        "separating class coordinates",
        family.datum.field,
        family.quotient_representatives.dimension,
    )
    if advertised != coordinates or not any(coordinates):
        raise DeformationVerificationError("nonunique lifts are not gauge-inequivalent")
    return (
        "lift-family-binding",
        "two-checked-solutions",
        "nonzero-mod-gauge-separator",
    )


@dataclass(frozen=True, slots=True)
class _EndomorphismData:
    snapshot: Mapping[str, object]
    family: _LiftFamilyData
    linear: DenseMatrix
    translation: Vector

    def apply(self, point: Sequence[int]) -> Vector:
        return _sum_vectors(self.linear.matvec(point), self.translation, self.family.datum.field.p)


def _endomorphism_data(
    value: object,
    index: _ProofIndex,
    name: str = "lift endomorphism",
) -> _EndomorphismData:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "family_id", "linear", "translation"}, name=name)
    _type(snapshot, EXPECTED_TYPES["lift-endomorphism"], name)
    family_snapshot = index.resolve(
        snapshot.get("family_id"), EXPECTED_TYPES["lift-family"], f"{name}.family_id"
    )
    family = _lift_family_data(family_snapshot, index, f"{name}.family")
    size = family.datum.correction.ncols
    linear = _matrix(
        snapshot.get("linear"),
        f"{name}.linear",
        field=family.datum.field,
        nrows=size,
        ncols=size,
    )
    translation = _vector(
        snapshot.get("translation"), f"{name}.translation", family.datum.field, size
    )
    result = _EndomorphismData(snapshot, family, linear, translation)
    if not family.contains(result.apply(family.representative)):
        raise DeformationVerificationError("endomorphism does not preserve the affine family")
    if any(
        not family.directions.contains(linear.matvec(direction))
        for direction in family.directions.basis
    ):
        raise DeformationVerificationError("endomorphism does not preserve lift directions")
    return result


@dataclass(frozen=True, slots=True)
class _ContractionData:
    snapshot: Mapping[str, object]
    endomorphism: _EndomorphismData
    exponent: int


def _contraction_data(
    value: object,
    index: _ProofIndex,
    name: str = "contraction",
) -> _ContractionData:
    snapshot = _mapping(value, name)
    _exact_keys(snapshot, {"type", "endomorphism_id", "exponent"}, name=name)
    _type(snapshot, EXPECTED_TYPES["contraction"], name)
    endomorphism_snapshot = index.resolve(
        snapshot.get("endomorphism_id"),
        EXPECTED_TYPES["lift-endomorphism"],
        f"{name}.endomorphism_id",
    )
    endomorphism = _endomorphism_data(endomorphism_snapshot, index, f"{name}.endomorphism")
    exponent = _strict_int(snapshot.get("exponent"), f"{name}.exponent", minimum=0)
    if exponent > MAX_DIMENSION:
        raise DeformationVerificationError("contraction exponent exceeds the portable bound")
    power = _matrix_power(endomorphism.linear, exponent)
    if any(any(power.matvec(direction)) for direction in endomorphism.family.directions.basis):
        raise DeformationVerificationError(
            "claimed contraction exponent does not kill all lift differences"
        )
    return _ContractionData(snapshot, endomorphism, exponent)


def _verify_fixed_lift(value: object, index: _ProofIndex) -> tuple[str, ...]:
    snapshot = _mapping(value, "fixed lift")
    _exact_keys(
        snapshot,
        {"type", "family_id", "endomorphism_id", "contraction_id", "representative"},
        name="fixed lift",
    )
    _type(snapshot, EXPECTED_TYPES["fixed-lift"], "fixed lift")
    family_snapshot = index.resolve(
        snapshot.get("family_id"), EXPECTED_TYPES["lift-family"], "family_id"
    )
    family = _lift_family_data(family_snapshot, index)
    endomorphism_snapshot = index.resolve(
        snapshot.get("endomorphism_id"),
        EXPECTED_TYPES["lift-endomorphism"],
        "endomorphism_id",
    )
    endomorphism = _endomorphism_data(endomorphism_snapshot, index)
    contraction_snapshot = index.resolve(
        snapshot.get("contraction_id"), EXPECTED_TYPES["contraction"], "contraction_id"
    )
    contraction = _contraction_data(contraction_snapshot, index)
    if endomorphism.family.snapshot != family.snapshot:
        raise DeformationVerificationError("fixed-lift endomorphism belongs to another family")
    if contraction.endomorphism.snapshot != endomorphism.snapshot:
        raise DeformationVerificationError("fixed lift uses a different contraction")
    expected = family.representative
    for _ in range(contraction.exponent):
        expected = endomorphism.apply(expected)
    representative = _vector(
        snapshot.get("representative"),
        "fixed lift representative",
        family.datum.field,
        family.datum.correction.ncols,
    )
    if representative != expected:
        raise DeformationVerificationError("fixed lift is not the contracted iterate")
    if not family.contains(representative):
        raise DeformationVerificationError("fixed lift is outside its affine family")
    if endomorphism.apply(representative) != representative:
        raise DeformationVerificationError("claimed fixed lift is not fixed")
    return (
        "family-endomorphism-contraction-binding",
        "contracted-iterate",
        "checked-fixed-point",
    )


def _verify_rigidity(
    value: object,
    index: _ProofIndex,
    *,
    rigid: bool,
) -> tuple[str, ...]:
    kind = "rigid" if rigid else "nonrigid"
    snapshot = _mapping(value, kind)
    required = {"type", "problem_id", "tangent_id"}
    if not rigid:
        required.add("witness")
    _exact_keys(snapshot, required, name=kind)
    _type(snapshot, EXPECTED_TYPES[kind], kind)
    problem = index.resolve(snapshot.get("problem_id"), EXPECTED_TYPES["problem"], "problem_id")
    complex_ = _problem_data(problem)
    tangent_snapshot = index.resolve(
        snapshot.get("tangent_id"), EXPECTED_TYPES["tangent"], "tangent_id"
    )
    tangent_mapping = _mapping(tangent_snapshot, "tangent dependency")
    if tangent_mapping.get("problem_id") != snapshot.get("problem_id"):
        raise DeformationVerificationError("rigidity tangent belongs to another problem")
    _, numerator, denominator, representatives = _verify_cohomology_space(
        tangent_snapshot, index, obstruction=False
    )
    if rigid:
        if representatives.dimension != 0:
            raise DeformationVerificationError("rigid result has a nonzero tangent quotient")
        return ("problem-and-tangent-binding", "zero-tangent-quotient", "rigidity")
    if representatives.dimension == 0:
        raise DeformationVerificationError("nonrigid result has a zero tangent quotient")
    witness = _vector(
        snapshot.get("witness"),
        "nonrigidity witness",
        complex_.field,
        complex_.dimensions[1],
    )
    quotient = quotient_space(numerator, denominator)
    if not any(quotient.class_coordinates(witness)):
        raise DeformationVerificationError("nonrigidity witness represents the zero tangent class")
    return (
        "problem-and-tangent-binding",
        "nonzero-tangent-class",
        "literal-nonrigidity-witness",
    )


def _verify_unsupported(value: object) -> tuple[str, ...]:
    snapshot = _mapping(value, "unsupported deformation")
    _exact_keys(
        snapshot,
        {"type", "operation", "reason", "requested", "supported"},
        name="unsupported deformation",
    )
    _type(snapshot, EXPECTED_TYPES["unsupported"], "unsupported deformation")
    operation = _runtime_label(snapshot.get("operation"), "unsupported operation")
    reason = _runtime_label(snapshot.get("reason"), "unsupported reason")
    requested = _mapping(snapshot.get("requested"), "unsupported requested parameters")
    _reject_backend_leaks(requested)
    supported = tuple(
        _runtime_label(item, f"supported[{index}]")
        for index, item in enumerate(_sequence(snapshot.get("supported"), "supported"))
    )
    if supported != tuple(sorted(set(supported))):
        raise DeformationVerificationError(
            "supported deformation capabilities are not canonical and unique"
        )
    try:
        replay = UnsupportedDeformation(
            operation,
            reason,
            requested=requested,
            supported=supported,
        )
    except DeformationError as exc:
        raise DeformationVerificationError(str(exc)) from exc
    if replay.to_canonical_data() != dict(snapshot):
        raise DeformationVerificationError(
            "unsupported deformation payload is not the strict core canonical snapshot"
        )
    return ("typed-unsupported-boundary", "explicit-nonconclusion")


def _referenced_ids(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.endswith("_id") and isinstance(item, str):
                result.add(item)
            result.update(_referenced_ids(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            result.update(_referenced_ids(item))
    return result


def _verify_direct_dependency_manifest(receipt: DeformationReceipt) -> None:
    references = _referenced_ids(receipt.payload)
    for certificate in receipt.dependencies:
        dependency = _receipt_from_dependency(certificate)
        if dependency.object_id not in references:
            raise DeformationVerificationError(
                "deformation receipt carries an unreferenced dependency certificate"
            )


def verify_deformation_receipt(receipt: DeformationReceipt) -> tuple[str, ...]:
    """Strictly replay one finite receipt from its canonical payload and dependencies."""

    if not isinstance(receipt, DeformationReceipt):
        raise TypeError("receipt must be a DeformationReceipt")
    receipt.verify_integrity()
    payload = receipt.payload.to_dict()
    _reject_backend_leaks(payload)
    _type(payload, EXPECTED_TYPES[receipt.kind], f"{receipt.kind} payload")
    dependencies = _dependency_receipts(receipt)
    _verify_direct_dependency_manifest(receipt)
    index = _ProofIndex.create(receipt, dependencies)
    kind = receipt.kind
    checks: tuple[str, ...]
    if kind == "artin-ring":
        _ring_data(payload)
        checks = (
            "prime-field-local-algebra",
            "unit-commutativity-associativity",
            "residue-homomorphism",
            "nilpotent-maximal-ideal-powers",
        )
    elif kind == "artin-map":
        _artin_map_data(payload, index)
        checks = (
            "domain-and-codomain-ring-dependencies",
            "linear-map-shape",
            "unit-residue-multiplication-homomorphism",
        )
    elif kind == "small-extension":
        _verify_small_extension(payload, index)
        checks = (
            "projection-dependency",
            "surjective-ring-map",
            "exact-kernel-inclusion",
            "maximal-ideal-annihilated-kernel",
            "square-zero-kernel",
        )
    elif kind == "complex":
        _complex_data(payload)
        checks = ("prime-field-three-term-complex", "zero-differential-composite")
    elif kind == "problem":
        _problem_data(payload)
        checks = (
            "presentation-binding",
            "framing-replay",
            "effective-complex-replay",
        )
    elif kind == "framing":
        _framing_data(payload)
        checks = ("framing-constraint-matrix", "canonical-allowed-gauge-kernel")
    elif kind == "gauge":
        checks = _verify_gauge(payload, index)
    elif kind == "tangent":
        _verify_cohomology_space(payload, index, obstruction=False)
        checks = (
            "problem-and-complex-binding",
            "kernel-image-quotient",
            "canonical-tangent-space",
        )
    elif kind == "obstruction-space":
        _verify_cohomology_space(payload, index, obstruction=True)
        checks = (
            "problem-and-complex-binding",
            "cokernel-quotient",
            "canonical-obstruction-space",
        )
    elif kind == "obstruction-class":
        checks = _verify_obstruction_class(payload, index)
    elif kind == "action":
        _action_data(payload, index)
        checks = (
            "complex-dependency-binding",
            "finite-group-axioms",
            "degreewise-representations",
            "chain-equivariance",
        )
    elif kind == "equivariant":
        checks = _verify_equivariant(payload, index)
    elif kind == "invariant-complex":
        checks = _verify_invariant_complex(payload, index)
    elif kind == "decomposition":
        checks = _verify_decomposition(payload, index)
    elif kind == "lift-datum":
        _lift_datum_data(payload, index)
        checks = (
            "problem-and-small-extension-dependencies",
            "affine-correction-equation",
            "homogeneous-gauge-directions",
        )
    elif kind == "lift-family":
        _lift_family_data(payload, index)
        checks = (
            "lift-datum-binding",
            "canonical-affine-solution-family",
            "complete-mod-gauge-quotient",
        )
    elif kind == "lift-obstructed":
        checks = _verify_lift_obstructed(payload, index)
    elif kind == "lift-unknown":
        checks = _verify_lift_unknown(payload, index)
    elif kind == "unique-lift":
        checks = _verify_unique_lift(payload, index)
    elif kind == "nonunique-lift":
        checks = _verify_nonunique_lift(payload, index)
    elif kind == "lift-endomorphism":
        _endomorphism_data(payload, index)
        checks = ("lift-family-binding", "affine-family-endomorphism")
    elif kind == "contraction":
        _contraction_data(payload, index)
        checks = ("endomorphism-binding", "nilpotent-difference-action")
    elif kind == "fixed-lift":
        checks = _verify_fixed_lift(payload, index)
    elif kind == "rigid":
        checks = _verify_rigidity(payload, index, rigid=True)
    elif kind == "nonrigid":
        checks = _verify_rigidity(payload, index, rigid=False)
    elif kind == "unsupported":
        checks = _verify_unsupported(payload)
    else:  # pragma: no cover - constructor and decoder already reject this
        raise DeformationVerificationError(f"unsupported deformation receipt kind: {kind}")
    if kind in {"lift-unknown", "unsupported"} and receipt.completeness != "candidate":
        raise DeformationVerificationError(
            "unknown and unsupported deformation outcomes cannot be marked complete"
        )
    return (
        *checks,
        "dependency-closed-portable-evidence",
        "assumptions-axis",
        "completeness-axis",
        "portable-verifier-trust",
    )


# Public aliases keep operation-specific terminology without multiplying
# decoder implementations or evidence layers.
ArtinRingCertificate = DeformationReceipt
ArtinMapCertificate = DeformationReceipt
SmallExtensionCertificate = DeformationReceipt
DeformationComplexCertificate = DeformationReceipt
DeformationSpaceCertificate = DeformationReceipt
FramingCertificate = DeformationReceipt
EquivarianceCertificate = DeformationReceipt
LiftCertificate = DeformationReceipt
RigidityCertificate = DeformationReceipt


__all__ = [
    "EXPECTED_TYPES",
    "PORTABLE_TRUST",
    "PORTABLE_VERIFIER",
    "RECEIPT_SCHEMAS",
    "ArtinMapCertificate",
    "ArtinRingCertificate",
    "DeformationCertificateError",
    "DeformationComplexCertificate",
    "DeformationReceipt",
    "DeformationSpaceCertificate",
    "DeformationVerificationError",
    "EquivarianceCertificate",
    "FramingCertificate",
    "LiftCertificate",
    "RigidityCertificate",
    "SmallExtensionCertificate",
    "verify_deformation_receipt",
]
