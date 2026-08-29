"""Immutable dense and sparse matrices over prime finite fields.

An ``m``-by-``n`` matrix always denotes a linear map ``F^n -> F^m`` acting on
column vectors.  Entries are exposed as canonical integer residues to keep the
wire representation small and backend-independent.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TypeAlias, overload

from arbogast.core import CanonicalJSON, CanonicalObject, ValidationError

from .errors import DimensionMismatchError, FieldMismatchError
from .field import PrimeField, PrimeFieldElement, Scalar

Vector: TypeAlias = tuple[int, ...]
Entry: TypeAlias = tuple[int, int, int]


def _require_dimension(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValidationError(f"{name} must be nonnegative")
    return value


def _coerce_vector(field: PrimeField, vector: Iterable[Scalar], length: int, name: str) -> Vector:
    result = tuple(field.residue(value) for value in vector)
    if len(result) != length:
        raise DimensionMismatchError(f"{name} has length {len(result)}, expected {length}")
    return result


def _require_same_field(left: PrimeField, right: PrimeField) -> None:
    if left != right:
        raise FieldMismatchError(f"coefficient fields differ: {left!r} and {right!r}")


@dataclass(frozen=True, slots=True, init=False)
class DenseMatrix(CanonicalObject):
    """A canonical immutable row-major dense matrix."""

    field: PrimeField
    _rows: tuple[Vector, ...]
    _ncols: int

    def __init__(
        self,
        field: PrimeField,
        rows: Iterable[Iterable[Scalar]],
        *,
        ncols: int | None = None,
    ) -> None:
        materialized = tuple(tuple(field.residue(value) for value in row) for row in rows)
        if materialized:
            inferred = len(materialized[0])
            if ncols is not None and _require_dimension(ncols, "ncols") != inferred:
                raise DimensionMismatchError("explicit ncols does not match the supplied rows")
            if any(len(row) != inferred for row in materialized):
                raise DimensionMismatchError("matrix rows must all have the same length")
            column_count = inferred
        else:
            column_count = 0 if ncols is None else _require_dimension(ncols, "ncols")
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "_rows", materialized)
        object.__setattr__(self, "_ncols", column_count)

    @classmethod
    def zeros(cls, field: PrimeField, nrows: int, ncols: int) -> DenseMatrix:
        """Return the ``nrows``-by-``ncols`` zero matrix."""

        nrows = _require_dimension(nrows, "nrows")
        ncols = _require_dimension(ncols, "ncols")
        return cls(field, ((0,) * ncols for _ in range(nrows)), ncols=ncols)

    @classmethod
    def identity(cls, field: PrimeField, size: int) -> DenseMatrix:
        """Return the identity matrix of the requested size."""

        size = _require_dimension(size, "size")
        return cls(
            field,
            (tuple(1 if row == column else 0 for column in range(size)) for row in range(size)),
            ncols=size,
        )

    @classmethod
    def from_columns(
        cls,
        field: PrimeField,
        columns: Iterable[Iterable[Scalar]],
        *,
        nrows: int | None = None,
    ) -> DenseMatrix:
        """Construct a matrix from column vectors.

        ``nrows`` is required only when the column sequence is empty and a
        nonzero row dimension must be retained.
        """

        materialized = tuple(tuple(field.residue(value) for value in column) for column in columns)
        if materialized:
            inferred = len(materialized[0])
            if nrows is not None and _require_dimension(nrows, "nrows") != inferred:
                raise DimensionMismatchError("explicit nrows does not match the supplied columns")
            if any(len(column) != inferred for column in materialized):
                raise DimensionMismatchError("matrix columns must all have the same length")
            row_count = inferred
        else:
            row_count = 0 if nrows is None else _require_dimension(nrows, "nrows")
        rows = tuple(
            tuple(materialized[column][row] for column in range(len(materialized)))
            for row in range(row_count)
        )
        return cls(field, rows, ncols=len(materialized))

    @property
    def nrows(self) -> int:
        """Return the codomain dimension."""

        return len(self._rows)

    @property
    def ncols(self) -> int:
        """Return the domain dimension."""

        return self._ncols

    @property
    def shape(self) -> tuple[int, int]:
        """Return ``(nrows, ncols)``."""

        return (self.nrows, self.ncols)

    @property
    def rows(self) -> tuple[Vector, ...]:
        """Return immutable canonical residue rows."""

        return self._rows

    @property
    def columns(self) -> tuple[Vector, ...]:
        """Return immutable canonical residue columns."""

        return tuple(
            tuple(self._rows[row][column] for row in range(self.nrows))
            for column in range(self.ncols)
        )

    def to_rows(self) -> tuple[Vector, ...]:
        """Return immutable row data (an explicit serialization convenience)."""

        return self._rows

    def __len__(self) -> int:
        return self.nrows

    def __iter__(self) -> Iterator[Vector]:
        return iter(self._rows)

    @overload
    def __getitem__(self, key: int) -> Vector: ...

    @overload
    def __getitem__(self, key: tuple[int, int]) -> int: ...

    def __getitem__(self, key: int | tuple[int, int]) -> Vector | int:
        if isinstance(key, tuple):
            row, column = key
            return self._rows[row][column]
        return self._rows[key]

    def element(self, row: int, column: int) -> PrimeFieldElement:
        """Return an entry as a field-element object."""

        return self.field(self._rows[row][column])

    def row(self, index: int) -> Vector:
        """Return one row."""

        return self._rows[index]

    def column(self, index: int) -> Vector:
        """Return one column."""

        return tuple(self._rows[row][index] for row in range(self.nrows))

    def transpose(self) -> DenseMatrix:
        """Return the matrix transpose."""

        return DenseMatrix(self.field, self.columns, ncols=self.nrows)

    @property
    def T(self) -> DenseMatrix:
        """Return the matrix transpose."""

        return self.transpose()

    def matvec(self, vector: Iterable[Scalar]) -> Vector:
        """Apply this map to a column vector."""

        values = _coerce_vector(self.field, vector, self.ncols, "vector")
        modulus = self.field.p
        return tuple(
            sum(a * b for a, b in zip(row, values, strict=True)) % modulus for row in self._rows
        )

    def matmul(self, other: DenseMatrix | SparseMatrix) -> DenseMatrix:
        """Compose this map with *other* (ordinary matrix multiplication)."""

        right = other.to_dense() if isinstance(other, SparseMatrix) else other
        _require_same_field(self.field, right.field)
        if self.ncols != right.nrows:
            raise DimensionMismatchError(f"cannot multiply shapes {self.shape} and {right.shape}")
        columns = right.columns
        modulus = self.field.p
        result_rows = (
            tuple(
                sum(a * b for a, b in zip(row, column, strict=True)) % modulus for column in columns
            )
            for row in self._rows
        )
        return DenseMatrix(self.field, result_rows, ncols=right.ncols)

    def __matmul__(self, other: DenseMatrix | SparseMatrix) -> DenseMatrix:
        return self.matmul(other)

    def __add__(self, other: DenseMatrix) -> DenseMatrix:
        _require_same_field(self.field, other.field)
        if self.shape != other.shape:
            raise DimensionMismatchError(f"cannot add shapes {self.shape} and {other.shape}")
        modulus = self.field.p
        return DenseMatrix(
            self.field,
            (
                tuple(
                    (left + right) % modulus
                    for left, right in zip(left_row, right_row, strict=True)
                )
                for left_row, right_row in zip(self._rows, other._rows, strict=True)
            ),
            ncols=self.ncols,
        )

    def __sub__(self, other: DenseMatrix) -> DenseMatrix:
        _require_same_field(self.field, other.field)
        if self.shape != other.shape:
            raise DimensionMismatchError(f"cannot subtract shapes {self.shape} and {other.shape}")
        modulus = self.field.p
        return DenseMatrix(
            self.field,
            (
                tuple(
                    (left - right) % modulus
                    for left, right in zip(left_row, right_row, strict=True)
                )
                for left_row, right_row in zip(self._rows, other._rows, strict=True)
            ),
            ncols=self.ncols,
        )

    def __neg__(self) -> DenseMatrix:
        modulus = self.field.p
        return DenseMatrix(
            self.field,
            (tuple((-value) % modulus for value in row) for row in self._rows),
            ncols=self.ncols,
        )

    def scale(self, scalar: Scalar) -> DenseMatrix:
        """Multiply every entry by a scalar."""

        value = self.field.residue(scalar)
        modulus = self.field.p
        return DenseMatrix(
            self.field,
            (tuple(value * entry % modulus for entry in row) for row in self._rows),
            ncols=self.ncols,
        )

    def augment(self, other: DenseMatrix) -> DenseMatrix:
        """Horizontally concatenate matrices with the same row count."""

        _require_same_field(self.field, other.field)
        if self.nrows != other.nrows:
            raise DimensionMismatchError("augmented matrices must have equal row counts")
        return DenseMatrix(
            self.field,
            (left + right for left, right in zip(self._rows, other._rows, strict=True)),
            ncols=self.ncols + other.ncols,
        )

    def select_rows(self, indices: Iterable[int]) -> DenseMatrix:
        """Return rows in the specified order."""

        selected = tuple(self._rows[index] for index in indices)
        return DenseMatrix(self.field, selected, ncols=self.ncols)

    def select_columns(self, indices: Iterable[int]) -> DenseMatrix:
        """Return columns in the specified order."""

        selected = tuple(indices)
        return DenseMatrix(
            self.field,
            (tuple(row[index] for index in selected) for row in self._rows),
            ncols=len(selected),
        )

    def to_sparse(self) -> SparseMatrix:
        """Return the equivalent canonical sparse matrix."""

        return SparseMatrix.from_dense(self)

    def to_dense(self) -> DenseMatrix:
        """Return ``self`` for matrix-like interoperability."""

        return self

    def to_canonical_data(self) -> CanonicalJSON:
        """Return a backend-independent row-major encoding."""

        return {
            "field": self.field.to_canonical_data(),
            "rows": [list(row) for row in self._rows],
            "shape": [self.nrows, self.ncols],
            "type": "arbogast.dense_matrix",
        }


@dataclass(frozen=True, slots=True, init=False)
class SparseMatrix(CanonicalObject):
    """A canonical coordinate-list sparse matrix with unique sorted entries."""

    field: PrimeField
    nrows: int
    ncols: int
    entries: tuple[Entry, ...]

    def __init__(
        self,
        field: PrimeField,
        nrows: int,
        ncols: int,
        entries: Mapping[tuple[int, int], Scalar] | Iterable[tuple[int, int, Scalar]],
    ) -> None:
        nrows = _require_dimension(nrows, "nrows")
        ncols = _require_dimension(ncols, "ncols")
        source = (
            ((row, column, value) for (row, column), value in entries.items())
            if isinstance(entries, Mapping)
            else entries
        )
        accumulated: dict[tuple[int, int], int] = {}
        for row, column, value in source:
            if isinstance(row, bool) or not isinstance(row, int):
                raise TypeError("sparse row index must be an integer")
            if isinstance(column, bool) or not isinstance(column, int):
                raise TypeError("sparse column index must be an integer")
            if not 0 <= row < nrows or not 0 <= column < ncols:
                raise DimensionMismatchError(
                    f"sparse entry index {(row, column)} is outside shape {(nrows, ncols)}"
                )
            key = (row, column)
            accumulated[key] = (accumulated.get(key, 0) + field.residue(value)) % field.p
        canonical_entries = tuple(
            (row, column, value)
            for (row, column), value in sorted(accumulated.items())
            if value != 0
        )
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "nrows", nrows)
        object.__setattr__(self, "ncols", ncols)
        object.__setattr__(self, "entries", canonical_entries)

    @classmethod
    def zeros(cls, field: PrimeField, nrows: int, ncols: int) -> SparseMatrix:
        """Return a sparse zero matrix."""

        return cls(field, nrows, ncols, ())

    @classmethod
    def identity(cls, field: PrimeField, size: int) -> SparseMatrix:
        """Return a sparse identity matrix."""

        size = _require_dimension(size, "size")
        return cls(field, size, size, ((index, index, 1) for index in range(size)))

    @classmethod
    def from_dense(cls, matrix: DenseMatrix) -> SparseMatrix:
        """Construct sparse form without storing zero entries."""

        return cls(
            matrix.field,
            matrix.nrows,
            matrix.ncols,
            (
                (row, column, value)
                for row, values in enumerate(matrix.rows)
                for column, value in enumerate(values)
                if value != 0
            ),
        )

    @property
    def shape(self) -> tuple[int, int]:
        """Return ``(nrows, ncols)``."""

        return (self.nrows, self.ncols)

    @property
    def nnz(self) -> int:
        """Return the number of stored nonzero entries."""

        return len(self.entries)

    def to_dense(self) -> DenseMatrix:
        """Materialize the exact dense matrix."""

        rows = [[0] * self.ncols for _ in range(self.nrows)]
        for row, column, value in self.entries:
            rows[row][column] = value
        return DenseMatrix(self.field, rows, ncols=self.ncols)

    @property
    def rows(self) -> tuple[Vector, ...]:
        """Return dense immutable rows for matrix-like interoperability."""

        return self.to_dense().rows

    def to_rows(self) -> tuple[Vector, ...]:
        """Return dense immutable row data."""

        return self.rows

    def transpose(self) -> SparseMatrix:
        """Return the sparse transpose."""

        return SparseMatrix(
            self.field,
            self.ncols,
            self.nrows,
            ((column, row, value) for row, column, value in self.entries),
        )

    @property
    def T(self) -> SparseMatrix:
        """Return the sparse transpose."""

        return self.transpose()

    def matvec(self, vector: Iterable[Scalar]) -> Vector:
        """Apply this map without dense materialization."""

        values = _coerce_vector(self.field, vector, self.ncols, "vector")
        result = [0] * self.nrows
        for row, column, value in self.entries:
            result[row] = (result[row] + value * values[column]) % self.field.p
        return tuple(result)

    def matmul(self, other: DenseMatrix | SparseMatrix) -> DenseMatrix:
        """Return exact matrix multiplication without densifying the sparse left input."""

        _require_same_field(self.field, other.field)
        if self.ncols != other.nrows:
            raise DimensionMismatchError(f"cannot multiply shapes {self.shape} and {other.shape}")
        right_rows: tuple[dict[int, int], ...]
        if isinstance(other, SparseMatrix):
            mutable_right: list[dict[int, int]] = [dict() for _ in range(other.nrows)]
            for row, column, value in other.entries:
                mutable_right[row][column] = value
            right_rows = tuple(mutable_right)
        else:
            right_rows = tuple(
                {column: value for column, value in enumerate(row) if value} for row in other.rows
            )
        result = [[0] * other.ncols for _ in range(self.nrows)]
        modulus = self.field.p
        for row, inner, left_value in self.entries:
            for column, right_value in right_rows[inner].items():
                result[row][column] = (result[row][column] + left_value * right_value) % modulus
        return DenseMatrix(self.field, result, ncols=other.ncols)

    def __matmul__(self, other: DenseMatrix | SparseMatrix) -> DenseMatrix:
        return self.matmul(other)

    def to_canonical_data(self) -> CanonicalJSON:
        """Return a sorted coordinate-list encoding."""

        return {
            "entries": [list(entry) for entry in self.entries],
            "field": self.field.to_canonical_data(),
            "shape": [self.nrows, self.ncols],
            "type": "arbogast.sparse_matrix",
        }


Matrix: TypeAlias = DenseMatrix | SparseMatrix


def as_dense(matrix: Matrix) -> DenseMatrix:
    """Return a dense exact matrix from either native representation."""

    return matrix.to_dense()
