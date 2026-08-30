"""Three-term finite deformation complexes over prime fields."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from arbogast.core import CanonicalJSON
from arbogast.formats import DEFORM_COMPLEX_SCHEMA_V1
from arbogast.linalg import DenseMatrix, PrimeField, Scalar

from ._schema import (
    DeformationSemanticObject,
    _canonical_dense_matrix,
    _canonical_prime_field,
)
from .errors import DeformationError, DeformationVerificationError


def _name(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DeformationError("complex name must be a non-empty string or None")
    return unicodedata.normalize("NFC", value.strip())


def _matrix(
    field: PrimeField,
    value: DenseMatrix | Iterable[Iterable[Scalar]],
    *,
    ncols: int | None = None,
    name: str,
) -> DenseMatrix:
    result = value if isinstance(value, DenseMatrix) else DenseMatrix(field, value, ncols=ncols)
    if result.field != field:
        raise DeformationError(f"{name} uses a different coefficient field")
    return result


@dataclass(frozen=True, slots=True, init=False)
class DeformationComplex(DeformationSemanticObject):
    """A pinned complex ``C0 --d0--> C1 --d1--> C2`` over ``F_p``."""

    field: PrimeField
    d0: DenseMatrix
    d1: DenseMatrix
    name: str | None

    schema_version = DEFORM_COMPLEX_SCHEMA_V1

    def __init__(
        self,
        field: PrimeField,
        d0: DenseMatrix | Iterable[Iterable[Scalar]],
        d1: DenseMatrix | Iterable[Iterable[Scalar]],
        *,
        name: str | None = None,
    ) -> None:
        if not isinstance(field, PrimeField):
            raise TypeError("field must be a PrimeField")
        first = _matrix(field, d0, name="d0")
        second = _matrix(field, d1, ncols=first.nrows, name="d1")
        if first.nrows != second.ncols:
            raise DeformationError("d0 codomain and d1 domain dimensions differ")
        if second @ first != DenseMatrix.zeros(field, second.nrows, first.ncols):
            raise DeformationError("deformation differentials do not satisfy d1*d0 = 0")
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "d0", first)
        object.__setattr__(self, "d1", second)
        object.__setattr__(self, "name", _name(name))
        self.verify()

    @property
    def dimensions(self) -> tuple[int, int, int]:
        return (self.d0.ncols, self.d0.nrows, self.d1.nrows)

    @property
    def degree0_dimension(self) -> int:
        return self.d0.ncols

    @property
    def degree1_dimension(self) -> int:
        return self.d0.nrows

    @property
    def degree2_dimension(self) -> int:
        return self.d1.nrows

    def differential(self, degree: int) -> DenseMatrix:
        if degree == 0:
            return self.d0
        if degree == 1:
            return self.d1
        raise DeformationError("a three-term complex has differentials only in degrees 0 and 1")

    def verify(self) -> bool:
        if not _canonical_prime_field(self.field):
            raise DeformationVerificationError("complex coefficient field is not canonical")
        if not _canonical_dense_matrix(self.d0, field=self.field) or not _canonical_dense_matrix(
            self.d1, field=self.field
        ):
            raise DeformationVerificationError(
                "complex differential contains noncanonical field coordinates"
            )
        if self.d0.field != self.field or self.d1.field != self.field:
            raise DeformationVerificationError("complex coefficient fields differ")
        if self.d0.nrows != self.d1.ncols:
            raise DeformationVerificationError("complex middle dimensions differ")
        expected_zero = DenseMatrix.zeros(
            self.field,
            self.degree2_dimension,
            self.degree0_dimension,
        )
        if self.d1 @ self.d0 != expected_zero:
            raise DeformationVerificationError("complex identity d1*d0 = 0 failed")
        if _name(self.name) != self.name:
            raise DeformationVerificationError("complex name normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "d0": self.d0.to_canonical_data(),
            "d1": self.d1.to_canonical_data(),
            "dimensions": list(self.dimensions),
            "field": self.field.to_canonical_data(),
            "name": self.name,
            "type": "arbogast.deform.complex",
        }


__all__ = ["DeformationComplex"]
