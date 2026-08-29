"""Small exact prime-field linear algebra used by the cohomology verifier.

This module is intentionally private and backend independent.  Discovery may eventually use
FLINT, but a certificate verifier must be able to replay the finite calculation using only the
Python standard library.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

Vector = tuple[int, ...]
DenseRows = tuple[Vector, ...]
SparseRow = dict[int, int]


def is_prime(value: int) -> bool:
    """Return whether *value* is prime, using deterministic trial division."""

    if value < 2:
        return False
    if value in (2, 3):
        return True
    if value % 2 == 0 or value % 3 == 0:
        return False
    divisor = 5
    step = 2
    while divisor * divisor <= value:
        if value % divisor == 0:
            return False
        divisor += step
        step = 6 - step
    return True


def _clean_sparse(row: SparseRow, prime: int) -> SparseRow:
    return {column: value % prime for column, value in row.items() if value % prime}


def _as_sparse(row: Sequence[int] | SparseRow, prime: int) -> SparseRow:
    if isinstance(row, dict):
        return _clean_sparse(row, prime)
    return {column: value % prime for column, value in enumerate(row) if value % prime}


def _as_dense(row: SparseRow, width: int) -> Vector:
    return tuple(row.get(column, 0) for column in range(width))


def rref_sparse(
    rows: Iterable[Sequence[int] | SparseRow],
    width: int,
    prime: int,
) -> tuple[tuple[SparseRow, ...], tuple[int, ...]]:
    """Compute canonical reduced row echelon form over ``GF(prime)``."""

    work = [_as_sparse(row, prime) for row in rows]
    work = [row for row in work if row]
    pivot_row = 0
    pivots: list[int] = []
    for column in range(width):
        candidate = next(
            (index for index in range(pivot_row, len(work)) if work[index].get(column, 0)),
            None,
        )
        if candidate is None:
            continue
        work[pivot_row], work[candidate] = work[candidate], work[pivot_row]
        inverse = pow(work[pivot_row][column], -1, prime)
        work[pivot_row] = {key: (value * inverse) % prime for key, value in work[pivot_row].items()}
        for index, row in enumerate(work):
            if index == pivot_row:
                continue
            coefficient = row.get(column, 0)
            if not coefficient:
                continue
            replacement = dict(row)
            for key, value in work[pivot_row].items():
                new_value = (replacement.get(key, 0) - coefficient * value) % prime
                if new_value:
                    replacement[key] = new_value
                else:
                    replacement.pop(key, None)
            work[index] = replacement
        pivots.append(column)
        pivot_row += 1
        if pivot_row == len(work):
            break
    canonical = tuple(work[:pivot_row])
    return canonical, tuple(pivots)


def span_basis(vectors: Iterable[Sequence[int]], width: int, prime: int) -> tuple[Vector, ...]:
    """Return the unique RREF row basis for the span of *vectors*."""

    reduced, _ = rref_sparse(vectors, width, prime)
    return tuple(_as_dense(row, width) for row in reduced)


def rank(vectors: Iterable[Sequence[int]], width: int, prime: int) -> int:
    """Return the dimension of the row span of *vectors*."""

    reduced, _ = rref_sparse(vectors, width, prime)
    return len(reduced)


@dataclass(frozen=True, slots=True)
class SparseMatrix:
    """An immutable sparse matrix representing a map ``F^ncols -> F^nrows``."""

    nrows: int
    ncols: int
    prime: int
    rows: tuple[tuple[tuple[int, int], ...], ...]

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[Sequence[int] | SparseRow],
        ncols: int,
        prime: int,
    ) -> SparseMatrix:
        materialized: list[tuple[tuple[int, int], ...]] = []
        for row in rows:
            sparse = _as_sparse(row, prime)
            if any(column < 0 or column >= ncols for column in sparse):
                raise ValueError("matrix column index is out of range")
            materialized.append(tuple(sorted(sparse.items())))
        return cls(len(materialized), ncols, prime, tuple(materialized))

    @classmethod
    def zero(cls, nrows: int, ncols: int, prime: int) -> SparseMatrix:
        return cls(nrows, ncols, prime, tuple(() for _ in range(nrows)))

    @property
    def shape(self) -> tuple[int, int]:
        return (self.nrows, self.ncols)

    @property
    def nnz(self) -> int:
        return sum(len(row) for row in self.rows)

    def sparse_rows(self) -> tuple[SparseRow, ...]:
        return tuple(dict(row) for row in self.rows)

    def to_rows(self) -> DenseRows:
        return tuple(_as_dense(dict(row), self.ncols) for row in self.rows)

    def apply(self, vector: Sequence[int]) -> Vector:
        if len(vector) != self.ncols:
            raise ValueError(f"expected vector of length {self.ncols}, got {len(vector)}")
        return tuple(
            sum(value * vector[column] for column, value in row) % self.prime for row in self.rows
        )

    def column(self, column: int) -> Vector:
        if column < 0 or column >= self.ncols:
            raise IndexError(column)
        return tuple(dict(row).get(column, 0) for row in self.rows)


def nullspace(matrix: SparseMatrix) -> tuple[Vector, ...]:
    """Return a canonical basis for the kernel of *matrix*."""

    reduced, pivots = rref_sparse(matrix.sparse_rows(), matrix.ncols, matrix.prime)
    pivot_set = set(pivots)
    free_columns = [column for column in range(matrix.ncols) if column not in pivot_set]
    basis: list[Vector] = []
    for free in free_columns:
        vector = [0] * matrix.ncols
        vector[free] = 1
        for row, pivot in zip(reduced, pivots, strict=True):
            vector[pivot] = (-row.get(free, 0)) % matrix.prime
        basis.append(tuple(vector))
    return span_basis(basis, matrix.ncols, matrix.prime)


def image_basis(matrix: SparseMatrix) -> tuple[Vector, ...]:
    """Return a canonical basis for the image of *matrix*."""

    columns = (matrix.column(column) for column in range(matrix.ncols))
    return span_basis(columns, matrix.nrows, matrix.prime)


def solve_columns(
    columns: Sequence[Sequence[int]],
    target: Sequence[int],
    prime: int,
) -> Vector | None:
    """Solve ``sum(x_i * columns[i]) = target``, choosing free variables as zero."""

    height = len(target)
    if any(len(column) != height for column in columns):
        raise ValueError("column height mismatch")
    width = len(columns)
    rows: list[SparseRow] = []
    for row_index in range(height):
        row = {
            column_index: column[row_index] % prime
            for column_index, column in enumerate(columns)
            if column[row_index] % prime
        }
        rhs = target[row_index] % prime
        if rhs:
            row[width] = rhs
        rows.append(row)
    reduced, pivots = rref_sparse(rows, width + 1, prime)
    if width in pivots:
        return None
    solution = [0] * width
    for row, pivot in zip(reduced, pivots, strict=True):
        if pivot < width:
            solution[pivot] = row.get(width, 0) % prime
    return tuple(solution)


def contains(span: Sequence[Sequence[int]], vector: Sequence[int], prime: int) -> bool:
    """Return whether *vector* lies in the span of the supplied basis."""

    return solve_columns(span, vector, prime) is not None


def complement_basis(
    subspace: Sequence[Vector],
    space: Sequence[Vector],
    width: int,
    prime: int,
) -> tuple[Vector, ...]:
    """Choose a deterministic complement of ``subspace`` inside ``space``."""

    chosen = list(span_basis(subspace, width, prime))
    initial_dimension = len(chosen)
    current_dimension = initial_dimension
    complement: list[Vector] = []
    for vector in span_basis(space, width, prime):
        candidate_dimension = rank([*chosen, vector], width, prime)
        if candidate_dimension > current_dimension:
            chosen.append(vector)
            complement.append(vector)
            current_dimension = candidate_dimension
    if current_dimension != len(span_basis(space, width, prime)):
        raise ValueError("the alleged subspace is not contained in the space")
    return tuple(complement)


def complete_basis(vectors: Sequence[Vector], width: int, prime: int) -> tuple[Vector, ...]:
    """Extend independent vectors to a basis using standard basis vectors in order."""

    chosen = list(vectors)
    current_dimension = rank(chosen, width, prime)
    if current_dimension != len(chosen):
        raise ValueError("vectors are not independent")
    for index in range(width):
        if current_dimension == width:
            break
        standard = tuple(1 if coordinate == index else 0 for coordinate in range(width))
        candidate_dimension = rank([*chosen, standard], width, prime)
        if candidate_dimension > current_dimension:
            chosen.append(standard)
            current_dimension = candidate_dimension
    if current_dimension != width:
        raise AssertionError("failed to complete a finite-dimensional basis")
    return tuple(chosen)


def inverse_from_columns(columns: Sequence[Vector], prime: int) -> DenseRows:
    """Invert a square matrix supplied as columns."""

    width = len(columns)
    if any(len(column) != width for column in columns):
        raise ValueError("matrix is not square")
    inverse_columns: list[Vector] = []
    for index in range(width):
        target = tuple(1 if coordinate == index else 0 for coordinate in range(width))
        solution = solve_columns(columns, target, prime)
        if solution is None:
            raise ValueError("matrix is singular")
        inverse_columns.append(solution)
    return tuple(
        tuple(inverse_columns[column][row] for column in range(width)) for row in range(width)
    )


def matrix_vector(rows: Sequence[Sequence[int]], vector: Sequence[int], prime: int) -> Vector:
    """Multiply a dense row matrix by a column vector."""

    if rows and any(len(row) != len(vector) for row in rows):
        raise ValueError("matrix/vector dimension mismatch")
    return tuple(sum(a * b for a, b in zip(row, vector, strict=True)) % prime for row in rows)


def linear_combination(
    columns: Sequence[Sequence[int]], coordinates: Sequence[int], prime: int
) -> Vector:
    """Form a linear combination of equally sized column vectors."""

    if len(columns) != len(coordinates):
        raise ValueError("coordinate dimension mismatch")
    if not columns:
        return ()
    height = len(columns[0])
    if any(len(column) != height for column in columns):
        raise ValueError("column height mismatch")
    return tuple(
        sum(
            coefficient * column[row]
            for coefficient, column in zip(coordinates, columns, strict=True)
        )
        % prime
        for row in range(height)
    )


def compose_is_zero(left: SparseMatrix, right: SparseMatrix) -> bool:
    """Check exactly that ``left @ right`` is the zero map."""

    if right.nrows != left.ncols or right.prime != left.prime:
        raise ValueError("differential composition mismatch")
    return all(not any(left.apply(right.column(column))) for column in range(right.ncols))
