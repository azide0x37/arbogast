"""Shared additive schema-document support for deformation objects."""

from __future__ import annotations

from importlib import import_module
from typing import ClassVar, cast

from arbogast.cert import VerificationCertificate
from arbogast.claims import Claim, ClaimGraph
from arbogast.core import CanonicalJSON, CanonicalObject
from arbogast.linalg import DenseMatrix, LinearSubspace, PrimeField, QuotientSpace

MAX_PRIME = 2_147_483_647
MAX_DIMENSION = 256
MAX_MATRIX_CELLS = 1_000_000
MAX_GROUP_ORDER = 256
MAX_TENSOR_CELLS = 1_000_000


def _canonical_prime_field(value: object) -> bool:
    """Return whether *value* is an untampered exact prime-field object."""

    if (
        not isinstance(value, PrimeField)
        or type(value.p) is not int
        or not 2 <= value.p <= MAX_PRIME
    ):
        return False
    try:
        replay = PrimeField(value.p)
    except (TypeError, ValueError):
        return False
    return replay.to_canonical_data() == value.to_canonical_data()


def _canonical_vector(
    field: PrimeField,
    value: object,
    *,
    length: int | None = None,
) -> bool:
    """Return whether *value* is a tuple of canonical residues in *field*."""

    return _canonical_prime_field(field) and _canonical_residue_tuple(
        value,
        field.p,
        length=length,
    )


def _canonical_residue_tuple(
    value: object,
    prime: int,
    *,
    length: int | None = None,
) -> bool:
    return bool(
        isinstance(value, tuple)
        and (length is None or len(value) == length)
        and all(type(entry) is int and 0 <= entry < prime for entry in value)
    )


def _canonical_dense_matrix(
    value: object,
    *,
    field: PrimeField | None = None,
) -> bool:
    """Replay a dense matrix without silently reducing altered entries."""

    if not isinstance(value, DenseMatrix) or not _canonical_prime_field(value.field):
        return False
    if field is not None and (not _canonical_prime_field(field) or value.field != field):
        return False
    if type(value.ncols) is not int or value.ncols < 0:
        return False
    if (
        value.nrows > MAX_DIMENSION
        or value.ncols > MAX_DIMENSION
        or value.nrows * value.ncols > MAX_MATRIX_CELLS
    ):
        return False
    if not isinstance(value.rows, tuple) or any(
        not _canonical_residue_tuple(row, value.field.p, length=value.ncols) for row in value.rows
    ):
        return False
    try:
        replay = DenseMatrix(value.field, value.rows, ncols=value.ncols)
    except (TypeError, ValueError):
        return False
    return replay.to_canonical_data() == value.to_canonical_data()


def _canonical_linear_subspace(
    value: object,
    *,
    field: PrimeField | None = None,
    ambient_dimension: int | None = None,
) -> bool:
    """Replay a reduced subspace basis and all scalar coordinates exactly."""

    if not isinstance(value, LinearSubspace) or not _canonical_prime_field(value.field):
        return False
    if field is not None and (not _canonical_prime_field(field) or value.field != field):
        return False
    if type(value.ambient_dimension) is not int or value.ambient_dimension < 0:
        return False
    if value.ambient_dimension > MAX_DIMENSION:
        return False
    if ambient_dimension is not None and value.ambient_dimension != ambient_dimension:
        return False
    if not isinstance(value.basis, tuple) or any(
        not _canonical_residue_tuple(
            vector,
            value.field.p,
            length=value.ambient_dimension,
        )
        for vector in value.basis
    ):
        return False
    try:
        replay = LinearSubspace(value.field, value.ambient_dimension, value.basis)
    except (TypeError, ValueError):
        return False
    return replay.to_canonical_data() == value.to_canonical_data()


def _canonical_quotient_space(
    value: object,
    *,
    field: PrimeField | None = None,
) -> bool:
    """Replay all subspaces and the canonical complement of a quotient."""

    if not isinstance(value, QuotientSpace):
        return False
    if not all(
        _canonical_linear_subspace(space, field=field)
        for space in (value.numerator, value.denominator, value.representatives)
    ):
        return False
    try:
        return value.verify()
    except (TypeError, ValueError):
        return False


class DeformationSchemaObject(CanonicalObject):
    """Canonical object carrying one immutable additive wire-schema ID."""

    schema_version: ClassVar[str]

    def to_schema_document(self) -> dict[str, CanonicalJSON]:
        data = self.to_canonical_data()
        if not isinstance(data, dict):
            raise TypeError("deformation schema objects must encode as canonical mappings")
        return {"schema": self.schema_version, **data}


class DeformationSemanticObject(DeformationSchemaObject):
    """Schema object exposing lazy central certificate and claim adapters."""

    @property
    def certificate(self) -> VerificationCertificate:
        semantic = import_module("arbogast.deform.semantic")
        return cast(
            VerificationCertificate,
            semantic.verification_certificate_for_result(self),
        )

    def claim(self) -> Claim:
        semantic = import_module("arbogast.deform.semantic")
        return cast(Claim, semantic.claim_for_result(self))

    def claim_graph(self) -> ClaimGraph:
        semantic = import_module("arbogast.deform.semantic")
        return cast(ClaimGraph, semantic.claim_graph_for_result(self))


__all__ = ["DeformationSchemaObject", "DeformationSemanticObject"]
