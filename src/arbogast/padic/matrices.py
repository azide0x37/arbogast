"""Exact matrices over pinned local presentations and finite precision rings."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import islice
from typing import ClassVar, TypeAlias, cast

from arbogast.core import CanonicalJSON

from ._schema import (
    MAX_DIMENSION,
    MAX_EXACT_REPLAY_WORK,
    MAX_MATRIX_CELLS,
    PAdicSchemaObject,
    strict_canonical_equal,
    strict_int,
)
from .errors import PAdicValidationError, PAdicVerificationError
from .fields import (
    PAdicBall,
    PAdicElement,
    PAdicField,
    PAdicPrecisionRing,
    RationalLike,
)

PAdicBase: TypeAlias = PAdicField | PAdicPrecisionRing
PAdicScalar: TypeAlias = PAdicElement | PAdicBall
ScalarLike: TypeAlias = PAdicScalar | RationalLike


class PAdicMatrixError(PAdicValidationError):
    """Raised when an exact matrix operation is undefined over its base."""


def _base_id(base: PAdicBase) -> str:
    return base.field_id if isinstance(base, PAdicField) else base.ring_id


def _zero(base: PAdicBase) -> PAdicScalar:
    return base.zero


def _one(base: PAdicBase) -> PAdicScalar:
    return base.one


def _coerce(base: PAdicBase, value: ScalarLike) -> PAdicScalar:
    if isinstance(base, PAdicField):
        if isinstance(value, PAdicElement):
            if value.field != base:
                raise PAdicValidationError("matrix element belongs to a different local field")
            return value
        if isinstance(value, PAdicBall):
            raise PAdicValidationError("a finite-precision ball is not an exact field element")
        return base.from_power_basis_coordinates((value,))
    if isinstance(value, PAdicBall):
        if value.ring != base:
            raise PAdicValidationError("matrix entry belongs to a different precision ring")
        return value
    if isinstance(value, PAdicElement):
        return base.from_element(value)
    if isinstance(value, Fraction | tuple):
        return base.from_element(base.field.from_power_basis_coordinates((value,)))
    return base.one * value


def _inverse(value: PAdicScalar) -> PAdicScalar:
    try:
        return value.inverse()
    except ZeroDivisionError as error:
        raise PAdicMatrixError("matrix pivot is not a unit") from error


def _is_unit(value: PAdicScalar) -> bool:
    if isinstance(value, PAdicElement):
        return not value.is_zero
    return value.is_unit


def _add(base: PAdicBase, left: PAdicScalar, right: PAdicScalar) -> PAdicScalar:
    if isinstance(base, PAdicField):
        return cast(PAdicElement, left) + cast(PAdicElement, right)
    return cast(PAdicBall, left) + cast(PAdicBall, right)


def _subtract(base: PAdicBase, left: PAdicScalar, right: PAdicScalar) -> PAdicScalar:
    if isinstance(base, PAdicField):
        return cast(PAdicElement, left) - cast(PAdicElement, right)
    return cast(PAdicBall, left) - cast(PAdicBall, right)


def _multiply(base: PAdicBase, left: PAdicScalar, right: PAdicScalar) -> PAdicScalar:
    if isinstance(base, PAdicField):
        return cast(PAdicElement, left) * cast(PAdicElement, right)
    return cast(PAdicBall, left) * cast(PAdicBall, right)


def _negate(value: PAdicScalar) -> PAdicScalar:
    return -value


def _dot(
    left: Sequence[PAdicScalar],
    right: Sequence[PAdicScalar],
    base: PAdicBase,
) -> PAdicScalar:
    if len(left) != len(right):
        raise PAdicMatrixError("dot-product dimensions do not agree")
    result = _zero(base)
    for first, second in zip(left, right, strict=True):
        result = _add(base, result, _multiply(base, first, second))
    return result


@dataclass(frozen=True, slots=True, init=False)
class PAdicMatrix(PAdicSchemaObject):
    """An immutable row-major matrix with a single exact coefficient base."""

    schema_version: ClassVar[str] = "arbogast.padic.matrix/v1"

    base: PAdicBase
    entries: tuple[tuple[PAdicScalar, ...], ...]

    def __init__(
        self,
        base: PAdicBase,
        entries: Iterable[Iterable[ScalarLike]],
    ) -> None:
        if not isinstance(base, PAdicField | PAdicPrecisionRing):
            raise TypeError("matrix base must be a PAdicField or PAdicPrecisionRing")
        raw_rows = tuple(islice(entries, MAX_DIMENSION + 1))
        if len(raw_rows) > MAX_DIMENSION:
            raise PAdicValidationError("p-adic matrix row count exceeds the portable bound")
        rows: list[tuple[PAdicScalar, ...]] = []
        for row in raw_rows:
            raw_entries = tuple(islice(row, MAX_DIMENSION + 1))
            if len(raw_entries) > MAX_DIMENSION:
                raise PAdicValidationError("p-adic matrix column count exceeds the portable bound")
            rows.append(tuple(_coerce(base, value) for value in raw_entries))
        normalized_rows = tuple(rows)
        if not normalized_rows or not normalized_rows[0]:
            raise PAdicValidationError("p-adic matrices must have positive dimensions")
        ncols = len(normalized_rows[0])
        if any(len(row) != ncols for row in normalized_rows):
            raise PAdicValidationError("p-adic matrix rows have different lengths")
        if len(normalized_rows) > MAX_DIMENSION or ncols > MAX_DIMENSION:
            raise PAdicValidationError("p-adic matrix dimension exceeds the portable bound")
        if len(normalized_rows) * ncols > MAX_MATRIX_CELLS:
            raise PAdicValidationError("p-adic matrix exceeds the portable cell bound")
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "entries", normalized_rows)

    @classmethod
    def zero(cls, base: PAdicBase, nrows: int, ncols: int) -> PAdicMatrix:
        rows = strict_int(nrows, "matrix row count", minimum=1)
        columns = strict_int(ncols, "matrix column count", minimum=1)
        if rows > MAX_DIMENSION or columns > MAX_DIMENSION or rows * columns > MAX_MATRIX_CELLS:
            raise PAdicValidationError("p-adic zero-matrix shape exceeds the portable bound")
        return cls(base, ((_zero(base),) * columns for _ in range(rows)))

    @classmethod
    def identity(cls, base: PAdicBase, size: int) -> PAdicMatrix:
        dimension = strict_int(size, "matrix identity size", minimum=1)
        if dimension > MAX_DIMENSION or dimension * dimension > MAX_MATRIX_CELLS:
            raise PAdicValidationError("p-adic identity size exceeds the portable bound")
        return cls(
            base,
            (
                tuple(_one(base) if row == column else _zero(base) for column in range(dimension))
                for row in range(dimension)
            ),
        )

    @property
    def matrix_id(self) -> str:
        return self.content_id

    @property
    def base_id(self) -> str:
        return _base_id(self.base)

    @property
    def nrows(self) -> int:
        return len(self.entries)

    @property
    def ncols(self) -> int:
        return len(self.entries[0])

    @property
    def shape(self) -> tuple[int, int]:
        return (self.nrows, self.ncols)

    @property
    def is_square(self) -> bool:
        return self.nrows == self.ncols

    def _matching(self, other: PAdicMatrix) -> None:
        if not isinstance(other, PAdicMatrix):
            raise TypeError("matrix operand must be a PAdicMatrix")
        if other.base != self.base:
            raise PAdicMatrixError("matrix coefficient bases do not agree")

    def __add__(self, other: PAdicMatrix) -> PAdicMatrix:
        self._matching(other)
        if self.shape != other.shape:
            raise PAdicMatrixError("matrix shapes do not agree for addition")
        return PAdicMatrix(
            self.base,
            (
                tuple(
                    _add(self.base, left, right) for left, right in zip(first, second, strict=True)
                )
                for first, second in zip(self.entries, other.entries, strict=True)
            ),
        )

    def __sub__(self, other: PAdicMatrix) -> PAdicMatrix:
        return self + (-other)

    def __neg__(self) -> PAdicMatrix:
        return PAdicMatrix(
            self.base,
            (tuple(_negate(value) for value in row) for row in self.entries),
        )

    def scale(self, scalar: ScalarLike) -> PAdicMatrix:
        value = _coerce(self.base, scalar)
        return PAdicMatrix(
            self.base,
            (tuple(_multiply(self.base, value, entry) for entry in row) for row in self.entries),
        )

    def __mul__(self, scalar: ScalarLike) -> PAdicMatrix:
        return self.scale(scalar)

    def __rmul__(self, scalar: ScalarLike) -> PAdicMatrix:
        return self.scale(scalar)

    def __matmul__(self, other: PAdicMatrix) -> PAdicMatrix:
        self._matching(other)
        if self.ncols != other.nrows:
            raise PAdicMatrixError("matrix shapes do not agree for multiplication")
        columns = tuple(zip(*other.entries, strict=True))
        return PAdicMatrix(
            self.base,
            (tuple(_dot(row, column, self.base) for column in columns) for row in self.entries),
        )

    def matvec(self, vector: Sequence[ScalarLike]) -> tuple[PAdicScalar, ...]:
        normalized = tuple(_coerce(self.base, value) for value in vector)
        if len(normalized) != self.ncols:
            raise PAdicMatrixError("matrix-vector dimensions do not agree")
        return tuple(_dot(row, normalized, self.base) for row in self.entries)

    def transpose(self) -> PAdicMatrix:
        return PAdicMatrix(self.base, zip(*self.entries, strict=True))

    @property
    def T(self) -> PAdicMatrix:
        return self.transpose()

    def map_entries(self, operation: Callable[[PAdicScalar], ScalarLike]) -> PAdicMatrix:
        return PAdicMatrix(
            self.base,
            (tuple(operation(value) for value in row) for row in self.entries),
        )

    def block(
        self,
        row_start: int,
        row_stop: int,
        column_start: int,
        column_stop: int,
    ) -> PAdicMatrix:
        if not (
            0 <= row_start < row_stop <= self.nrows
            and 0 <= column_start < column_stop <= self.ncols
        ):
            raise PAdicMatrixError("matrix block indices are out of range")
        return PAdicMatrix(
            self.base,
            (row[column_start:column_stop] for row in self.entries[row_start:row_stop]),
        )

    def inverse(self) -> PAdicMatrix:
        """Return the exact inverse, requiring unit pivots over a precision ring."""

        if not self.is_square:
            raise PAdicMatrixError("only square matrices can be inverted")
        size = self.nrows
        work = [
            [*row, *PAdicMatrix.identity(self.base, size).entries[index]]
            for index, row in enumerate(self.entries)
        ]
        for column in range(size):
            pivot = next(
                (row for row in range(column, size) if _is_unit(work[row][column])),
                None,
            )
            if pivot is None:
                raise PAdicMatrixError("matrix is not invertible over its coefficient base")
            work[column], work[pivot] = work[pivot], work[column]
            pivot_inverse = _inverse(work[column][column])
            work[column] = [_multiply(self.base, pivot_inverse, value) for value in work[column]]
            for row in range(size):
                if row == column:
                    continue
                coefficient = work[row][column]
                if coefficient != _zero(self.base):
                    work[row] = [
                        _subtract(
                            self.base,
                            left,
                            _multiply(self.base, coefficient, right),
                        )
                        for left, right in zip(work[row], work[column], strict=True)
                    ]
        result = PAdicMatrix(self.base, (row[size:] for row in work))
        identity = PAdicMatrix.identity(self.base, size)
        if self @ result != identity or result @ self != identity:
            raise PAdicVerificationError("matrix inverse failed exact two-sided replay")
        return result

    def charpoly(self) -> tuple[PAdicScalar, ...]:
        """Return ``det(TI-A)`` constant-first using Berkowitz recursion."""

        if not self.is_square:
            raise PAdicMatrixError("characteristic polynomial requires a square matrix")
        local_degree = (
            self.base.degree if isinstance(self.base, PAdicField) else self.base.field.degree
        )
        if self.nrows**4 * local_degree > MAX_EXACT_REPLAY_WORK:
            raise PAdicMatrixError(
                "characteristic-polynomial computation exceeds the exact replay work bound"
            )

        def descending(matrix: PAdicMatrix) -> tuple[PAdicScalar, ...]:
            size = matrix.nrows
            if size == 1:
                return (_one(matrix.base), -matrix.entries[0][0])
            pivot = matrix.entries[0][0]
            row = matrix.entries[0][1:]
            column = tuple(matrix.entries[index][0] for index in range(1, size))
            minor = matrix.block(1, size, 1, size)
            minor_coefficients = descending(minor)
            first_column: list[PAdicScalar] = [_one(matrix.base), -pivot]
            vector = column
            for power in range(size - 1):
                first_column.append(-_dot(row, vector, matrix.base))
                if power + 1 < size - 1:
                    vector = minor.matvec(vector)
            result: list[PAdicScalar] = []
            for output in range(size + 1):
                value = _zero(matrix.base)
                for index, coefficient in enumerate(minor_coefficients):
                    offset = output - index
                    if 0 <= offset < len(first_column):
                        value = _add(
                            matrix.base,
                            value,
                            _multiply(matrix.base, first_column[offset], coefficient),
                        )
                result.append(value)
            return tuple(result)

        return tuple(reversed(descending(self)))

    @property
    def determinant(self) -> PAdicScalar:
        constant = self.charpoly()[0]
        return constant if self.nrows % 2 == 0 else -constant

    def verify(self) -> bool:
        replay = PAdicMatrix(self.base, self.entries)
        if replay != self:
            raise PAdicVerificationError("p-adic matrix normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "base_id": self.base_id,
                "base_kind": ("field" if isinstance(self.base, PAdicField) else "precision-ring"),
                "column_action": True,
                "entries": [[entry.to_canonical_data() for entry in row] for row in self.entries],
                "shape": [self.nrows, self.ncols],
                "type": "arbogast.padic.matrix",
            },
        )

    @classmethod
    def from_dict(
        cls,
        base: PAdicBase,
        value: Mapping[str, object],
    ) -> PAdicMatrix:
        expected = {
            "base_id",
            "base_kind",
            "column_action",
            "entries",
            "schema",
            "shape",
            "type",
        }
        if type(value) is not dict or set(value) != expected:
            raise PAdicVerificationError("p-adic matrix has a foreign transport shape")
        raw = dict(value)
        expected_kind = "field" if isinstance(base, PAdicField) else "precision-ring"
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.matrix"
            or raw["base_id"] != _base_id(base)
            or raw["base_kind"] != expected_kind
            or raw["column_action"] is not True
            or type(raw["entries"]) is not list
        ):
            raise PAdicVerificationError("p-adic matrix base, schema, or convention was altered")
        rows: list[tuple[PAdicScalar, ...]] = []
        for row_index, item in enumerate(cast(list[object], raw["entries"])):
            if type(item) is not list:
                raise PAdicVerificationError("p-adic matrix row is not a strict array")
            entries: list[PAdicScalar] = []
            for entry in cast(list[object], item):
                if type(entry) is not dict:
                    raise PAdicVerificationError("p-adic matrix entry is not a strict object")
                document = {
                    "schema": (
                        PAdicElement.schema_version
                        if isinstance(base, PAdicField)
                        else PAdicBall.schema_version
                    ),
                    **cast(dict[str, object], entry),
                }
                entries.append(
                    PAdicElement.from_dict(base, document)
                    if isinstance(base, PAdicField)
                    else PAdicBall.from_dict(base, document)
                )
            if not entries:
                raise PAdicVerificationError(f"p-adic matrix row {row_index} has no entries")
            rows.append(tuple(entries))
        result = cls(base, rows)
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("p-adic matrix is not strict canonical transport")
        return result


__all__ = ["PAdicMatrix", "PAdicMatrixError"]
