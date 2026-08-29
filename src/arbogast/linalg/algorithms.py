"""Deterministic exact linear algebra and independently checkable witnesses."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from arbogast.core import CanonicalJSON, CanonicalObject, ValidationError, VerificationError

from .errors import DimensionMismatchError, FieldMismatchError, SingularMatrixError
from .field import PrimeField, Scalar
from .matrix import DenseMatrix, Matrix, SparseMatrix, Vector, as_dense


def _same_field(left: PrimeField, right: PrimeField) -> None:
    if left != right:
        raise FieldMismatchError(f"coefficient fields differ: {left!r} and {right!r}")


def _coerce_vector(
    field: PrimeField,
    vector: Iterable[Scalar],
    length: int,
    name: str = "vector",
) -> Vector:
    values = tuple(field.residue(value) for value in vector)
    if len(values) != length:
        raise DimensionMismatchError(f"{name} has length {len(values)}, expected {length}")
    return values


def _first_nonzero(row: Vector) -> int | None:
    return next((index for index, value in enumerate(row) if value != 0), None)


def _rref_pivots(matrix: DenseMatrix) -> tuple[int, ...] | None:
    """Return pivots if *matrix* is in RREF, otherwise ``None``."""

    pivots: list[int] = []
    encountered_zero_row = False
    for row_index, row in enumerate(matrix.rows):
        pivot = _first_nonzero(row)
        if pivot is None:
            encountered_zero_row = True
            continue
        if encountered_zero_row:
            return None
        if row[pivot] != 1:
            return None
        if pivots and pivot <= pivots[-1]:
            return None
        if any(
            matrix[other_row, pivot] != 0
            for other_row in range(matrix.nrows)
            if other_row != row_index
        ):
            return None
        pivots.append(pivot)
    return tuple(pivots)


@dataclass(frozen=True, slots=True)
class RREFResult(CanonicalObject):
    """Reduced row-echelon form with an invertible row-operation witness.

    ``row_transform @ original == matrix``.  The transform is retained because
    it proves that row space and rank were preserved rather than merely showing
    that the output happens to look reduced.
    """

    matrix: DenseMatrix
    pivot_columns: tuple[int, ...]
    row_transform: DenseMatrix

    @property
    def rank(self) -> int:
        """Return the exact rank."""

        return len(self.pivot_columns)

    def verify(self, original: Matrix) -> bool:
        """Verify the RREF and invertible row-equivalence witness.

        Any failure raises :class:`VerificationError`; success returns ``True``.
        """

        source = as_dense(original)
        try:
            _same_field(self.matrix.field, source.field)
            _same_field(self.row_transform.field, source.field)
        except FieldMismatchError as exc:
            raise VerificationError(str(exc)) from exc
        if self.matrix.shape != source.shape:
            raise VerificationError("RREF shape differs from the original matrix")
        if self.row_transform.shape != (source.nrows, source.nrows):
            raise VerificationError("row transform has the wrong shape")
        actual_pivots = _rref_pivots(self.matrix)
        if actual_pivots is None:
            raise VerificationError("purported RREF is not in reduced row-echelon form")
        if actual_pivots != self.pivot_columns:
            raise VerificationError("advertised pivot columns do not match the RREF")
        if self.row_transform @ source != self.matrix:
            raise VerificationError("row transform does not map the source to the RREF")
        transform_reduction = rref(self.row_transform)
        if transform_reduction.matrix != DenseMatrix.identity(source.field, source.nrows):
            raise VerificationError("row transform is not invertible")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        """Return a self-contained exact witness encoding."""

        return {
            "matrix": self.matrix.to_canonical_data(),
            "pivot_columns": list(self.pivot_columns),
            "row_transform": self.row_transform.to_canonical_data(),
            "type": "arbogast.rref_result",
        }


def rref(matrix: Matrix) -> RREFResult:
    """Compute deterministic reduced row-echelon form over ``GF(p)``.

    Pivots are chosen by the leftmost available column and then the first
    available row.  This rule makes the encoded witness reproducible.
    """

    if isinstance(matrix, SparseMatrix):
        return _sparse_rref(matrix)
    source = matrix
    modulus = source.field.p
    rows = [list(row) for row in source.rows]
    transform = [list(row) for row in DenseMatrix.identity(source.field, source.nrows).rows]
    pivot_columns: list[int] = []
    pivot_row = 0

    for column in range(source.ncols):
        selected = next(
            (row for row in range(pivot_row, source.nrows) if rows[row][column] != 0),
            None,
        )
        if selected is None:
            continue
        if selected != pivot_row:
            rows[pivot_row], rows[selected] = rows[selected], rows[pivot_row]
            transform[pivot_row], transform[selected] = transform[selected], transform[pivot_row]

        inverse_pivot = pow(rows[pivot_row][column], -1, modulus)
        rows[pivot_row] = [entry * inverse_pivot % modulus for entry in rows[pivot_row]]
        transform[pivot_row] = [entry * inverse_pivot % modulus for entry in transform[pivot_row]]

        for row in range(source.nrows):
            if row == pivot_row:
                continue
            factor = rows[row][column]
            if factor == 0:
                continue
            rows[row] = [
                (entry - factor * pivot_entry) % modulus
                for entry, pivot_entry in zip(rows[row], rows[pivot_row], strict=True)
            ]
            transform[row] = [
                (entry - factor * pivot_entry) % modulus
                for entry, pivot_entry in zip(transform[row], transform[pivot_row], strict=True)
            ]

        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == source.nrows:
            break

    return RREFResult(
        matrix=DenseMatrix(source.field, rows, ncols=source.ncols),
        pivot_columns=tuple(pivot_columns),
        row_transform=DenseMatrix(source.field, transform, ncols=source.nrows),
    )


def _sparse_rref(source: SparseMatrix) -> RREFResult:
    """Reduce a sparse matrix using dictionary rows before materializing the witness.

    Elimination can create fill-in, and the public RREF witness is intentionally dense, but this
    path never allocates the input's full rectangular array merely to begin the computation.
    """

    modulus = source.field.p
    rows: list[dict[int, int]] = [dict() for _ in range(source.nrows)]
    for row, column, value in source.entries:
        rows[row][column] = value
    transform: list[dict[int, int]] = [
        ({row: 1} if source.nrows else {}) for row in range(source.nrows)
    ]
    pivot_columns: list[int] = []
    pivot_row = 0

    for column in range(source.ncols):
        selected = next(
            (row for row in range(pivot_row, source.nrows) if rows[row].get(column, 0) != 0),
            None,
        )
        if selected is None:
            continue
        if selected != pivot_row:
            rows[pivot_row], rows[selected] = rows[selected], rows[pivot_row]
            transform[pivot_row], transform[selected] = transform[selected], transform[pivot_row]

        inverse_pivot = pow(rows[pivot_row][column], -1, modulus)
        rows[pivot_row] = {
            index: scaled
            for index, value in rows[pivot_row].items()
            if (scaled := value * inverse_pivot % modulus) != 0
        }
        transform[pivot_row] = {
            index: scaled
            for index, value in transform[pivot_row].items()
            if (scaled := value * inverse_pivot % modulus) != 0
        }

        for row in range(source.nrows):
            if row == pivot_row:
                continue
            factor = rows[row].get(column, 0)
            if factor == 0:
                continue
            _sparse_axpy(rows[row], rows[pivot_row], factor, modulus)
            _sparse_axpy(transform[row], transform[pivot_row], factor, modulus)

        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == source.nrows:
            break

    reduced_rows = tuple(
        tuple(row.get(column, 0) for column in range(source.ncols)) for row in rows
    )
    transform_rows = tuple(
        tuple(row.get(column, 0) for column in range(source.nrows)) for row in transform
    )
    return RREFResult(
        matrix=DenseMatrix(source.field, reduced_rows, ncols=source.ncols),
        pivot_columns=tuple(pivot_columns),
        row_transform=DenseMatrix(source.field, transform_rows, ncols=source.nrows),
    )


def _sparse_axpy(
    target: dict[int, int],
    pivot: dict[int, int],
    factor: int,
    modulus: int,
) -> None:
    """Apply ``target -= factor * pivot`` while preserving sparse canonical rows."""

    for column, value in pivot.items():
        updated = (target.get(column, 0) - factor * value) % modulus
        if updated:
            target[column] = updated
        else:
            target.pop(column, None)


def rank(matrix: Matrix) -> int:
    """Return the exact matrix rank."""

    return rref(matrix).rank


def determinant(matrix: Matrix) -> int:
    """Return the determinant as a canonical residue.

    The empty ``0 x 0`` determinant is one, as required by exact-complex edge
    cases and the standard algebraic convention.
    """

    if isinstance(matrix, SparseMatrix):
        return _sparse_determinant(matrix)
    source = matrix
    if source.nrows != source.ncols:
        raise DimensionMismatchError("determinant requires a square matrix")
    modulus = source.field.p
    rows = [list(row) for row in source.rows]
    value = 1
    for column in range(source.ncols):
        selected = next(
            (row for row in range(column, source.nrows) if rows[row][column] != 0),
            None,
        )
        if selected is None:
            return 0
        if selected != column:
            rows[column], rows[selected] = rows[selected], rows[column]
            value = -value
        pivot = rows[column][column]
        value = value * pivot % modulus
        inverse_pivot = pow(pivot, -1, modulus)
        for row in range(column + 1, source.nrows):
            factor = rows[row][column] * inverse_pivot % modulus
            if factor == 0:
                continue
            for index in range(column, source.ncols):
                rows[row][index] = (rows[row][index] - factor * rows[column][index]) % modulus
    return value % modulus


def _sparse_determinant(source: SparseMatrix) -> int:
    if source.nrows != source.ncols:
        raise DimensionMismatchError("determinant requires a square matrix")
    modulus = source.field.p
    rows: list[dict[int, int]] = [dict() for _ in range(source.nrows)]
    for row, column, value in source.entries:
        rows[row][column] = value
    determinant_value = 1
    for column in range(source.ncols):
        selected = next(
            (row for row in range(column, source.nrows) if rows[row].get(column, 0) != 0),
            None,
        )
        if selected is None:
            return 0
        if selected != column:
            rows[column], rows[selected] = rows[selected], rows[column]
            determinant_value = -determinant_value
        pivot = rows[column][column]
        determinant_value = determinant_value * pivot % modulus
        inverse_pivot = pow(pivot, -1, modulus)
        for row in range(column + 1, source.nrows):
            factor = rows[row].get(column, 0) * inverse_pivot % modulus
            if factor:
                _sparse_axpy(rows[row], rows[column], factor, modulus)
    return determinant_value % modulus


def inverse(matrix: Matrix) -> DenseMatrix:
    """Return the exact inverse or raise :class:`SingularMatrixError`."""

    source = as_dense(matrix)
    if source.nrows != source.ncols:
        raise DimensionMismatchError("inverse requires a square matrix")
    reduction = rref(source)
    identity = DenseMatrix.identity(source.field, source.nrows)
    if reduction.matrix != identity:
        raise SingularMatrixError("matrix is singular")
    candidate = reduction.row_transform
    if candidate @ source != identity or source @ candidate != identity:
        raise VerificationError("internal inverse witness failed exact verification")
    return candidate


@dataclass(frozen=True, slots=True, init=False)
class LinearSubspace(CanonicalObject):
    """A subspace represented by its unique reduced row-space basis."""

    field: PrimeField
    ambient_dimension: int
    basis: tuple[Vector, ...]

    def __init__(
        self,
        field: PrimeField,
        ambient_dimension: int,
        basis: Iterable[Iterable[Scalar]] = (),
    ) -> None:
        if isinstance(ambient_dimension, bool) or not isinstance(ambient_dimension, int):
            raise TypeError("ambient_dimension must be an integer")
        if ambient_dimension < 0:
            raise ValidationError("ambient_dimension must be nonnegative")
        raw = tuple(tuple(field.residue(value) for value in vector) for vector in basis)
        if any(len(vector) != ambient_dimension for vector in raw):
            raise DimensionMismatchError(f"every basis vector must have length {ambient_dimension}")
        reduced = rref(DenseMatrix(field, raw, ncols=ambient_dimension)).matrix.rows
        canonical_basis = tuple(row for row in reduced if any(row))
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "ambient_dimension", ambient_dimension)
        object.__setattr__(self, "basis", canonical_basis)

    @classmethod
    def zero(cls, field: PrimeField, ambient_dimension: int) -> LinearSubspace:
        """Return the zero subspace of ``F^ambient_dimension``."""

        return cls(field, ambient_dimension)

    @classmethod
    def full(cls, field: PrimeField, ambient_dimension: int) -> LinearSubspace:
        """Return the full coordinate space."""

        if isinstance(ambient_dimension, bool) or not isinstance(ambient_dimension, int):
            raise TypeError("ambient_dimension must be an integer")
        if ambient_dimension < 0:
            raise ValidationError("ambient_dimension must be nonnegative")
        return cls(
            field,
            ambient_dimension,
            (
                tuple(1 if row == column else 0 for column in range(ambient_dimension))
                for row in range(ambient_dimension)
            ),
        )

    @property
    def dimension(self) -> int:
        """Return the vector-space dimension."""

        return len(self.basis)

    @property
    def pivot_columns(self) -> tuple[int, ...]:
        """Return the canonical basis pivot coordinates."""

        return tuple(
            pivot for row in self.basis for pivot in [_first_nonzero(row)] if pivot is not None
        )

    @property
    def basis_matrix(self) -> DenseMatrix:
        """Return basis vectors as matrix rows."""

        return DenseMatrix(self.field, self.basis, ncols=self.ambient_dimension)

    def reduce(self, vector: Iterable[Scalar]) -> Vector:
        """Return the canonical representative modulo this subspace."""

        result = list(_coerce_vector(self.field, vector, self.ambient_dimension))
        modulus = self.field.p
        for basis_vector, pivot in zip(self.basis, self.pivot_columns, strict=True):
            factor = result[pivot]
            if factor == 0:
                continue
            result = [
                (entry - factor * basis_entry) % modulus
                for entry, basis_entry in zip(result, basis_vector, strict=True)
            ]
        return tuple(result)

    def contains(self, vector: Iterable[Scalar]) -> bool:
        """Return whether *vector* belongs to the subspace."""

        return not any(self.reduce(vector))

    def coordinates(self, vector: Iterable[Scalar]) -> Vector:
        """Return coordinates in the canonical basis, raising if outside."""

        values = _coerce_vector(self.field, vector, self.ambient_dimension)
        if not self.contains(values):
            raise ValidationError("vector does not belong to the subspace")
        return tuple(values[pivot] for pivot in self.pivot_columns)

    def vector(self, coordinates: Iterable[Scalar]) -> Vector:
        """Reconstruct a vector from canonical-basis coordinates."""

        values = _coerce_vector(self.field, coordinates, self.dimension, "coordinates")
        result = [0] * self.ambient_dimension
        modulus = self.field.p
        for coefficient, basis_vector in zip(values, self.basis, strict=True):
            for index, entry in enumerate(basis_vector):
                result[index] = (result[index] + coefficient * entry) % modulus
        return tuple(result)

    def is_subspace_of(self, other: LinearSubspace) -> bool:
        """Return whether this subspace is contained in *other*."""

        if self.field != other.field or self.ambient_dimension != other.ambient_dimension:
            return False
        return all(other.contains(vector) for vector in self.basis)

    def __contains__(self, vector: object) -> bool:
        if not isinstance(vector, (tuple, list)):
            return False
        try:
            return self.contains(vector)
        except (TypeError, ValidationError):
            return False

    def canonical_complement(self, within: LinearSubspace | None = None) -> LinearSubspace:
        """Return the deterministic complement, in the ambient space or *within*."""

        return complement(self, within=within)

    def to_canonical_data(self) -> CanonicalJSON:
        """Return the unique reduced-basis encoding."""

        return {
            "ambient_dimension": self.ambient_dimension,
            "basis": [list(vector) for vector in self.basis],
            "field": self.field.to_canonical_data(),
            "type": "arbogast.linear_subspace",
        }


def row_space(matrix: Matrix) -> LinearSubspace:
    """Return the row space as a canonical subspace of ``F^n``."""

    reduction = rref(matrix)
    return LinearSubspace(
        matrix.field,
        matrix.ncols,
        (row for row in reduction.matrix.rows if any(row)),
    )


def image(matrix: Matrix) -> LinearSubspace:
    """Return the image/column space of ``F^n -> F^m``."""

    return row_space(matrix.transpose())


column_space = image


def nullspace(matrix: Matrix) -> LinearSubspace:
    """Return the kernel as a canonical subspace of the domain."""

    reduction = rref(matrix)
    pivot_set = set(reduction.pivot_columns)
    free_columns = tuple(column for column in range(matrix.ncols) if column not in pivot_set)
    basis: list[Vector] = []
    modulus = matrix.field.p
    for free in free_columns:
        vector = [0] * matrix.ncols
        vector[free] = 1
        for row, pivot in enumerate(reduction.pivot_columns):
            vector[pivot] = -reduction.matrix[row, free] % modulus
        basis.append(tuple(vector))
    return LinearSubspace(matrix.field, matrix.ncols, basis)


kernel = nullspace


def left_nullspace(matrix: Matrix) -> LinearSubspace:
    """Return vectors ``y`` satisfying ``y^T A = 0``."""

    return nullspace(matrix.transpose())


def sum_subspaces(left: LinearSubspace, right: LinearSubspace) -> LinearSubspace:
    """Return the sum of two subspaces."""

    _same_field(left.field, right.field)
    if left.ambient_dimension != right.ambient_dimension:
        raise DimensionMismatchError("subspaces have different ambient dimensions")
    return LinearSubspace(left.field, left.ambient_dimension, left.basis + right.basis)


def intersection(left: LinearSubspace, right: LinearSubspace) -> LinearSubspace:
    """Return the exact intersection of two subspaces."""

    _same_field(left.field, right.field)
    if left.ambient_dimension != right.ambient_dimension:
        raise DimensionMismatchError("subspaces have different ambient dimensions")
    left_dimension = left.dimension
    joined_columns = left.basis + tuple(
        tuple(-entry % left.field.p for entry in vector) for vector in right.basis
    )
    relation_matrix = DenseMatrix.from_columns(
        left.field,
        joined_columns,
        nrows=left.ambient_dimension,
    )
    relations = nullspace(relation_matrix)
    vectors = []
    for relation in relations.basis:
        result = [0] * left.ambient_dimension
        for coefficient, basis_vector in zip(relation[:left_dimension], left.basis, strict=True):
            for index, entry in enumerate(basis_vector):
                result[index] = (result[index] + coefficient * entry) % left.field.p
        vectors.append(tuple(result))
    return LinearSubspace(left.field, left.ambient_dimension, vectors)


def complement(
    subspace: LinearSubspace,
    *,
    within: LinearSubspace | None = None,
) -> LinearSubspace:
    """Return a canonical direct complement of ``subspace``.

    When ``within`` is supplied, require ``subspace <= within`` and return a
    complement inside ``within``.  Otherwise the containing space is the full
    ambient coordinate space.
    """

    container = within or LinearSubspace.full(subspace.field, subspace.ambient_dimension)
    _same_field(subspace.field, container.field)
    if subspace.ambient_dimension != container.ambient_dimension:
        raise DimensionMismatchError("subspaces have different ambient dimensions")
    if not subspace.is_subspace_of(container):
        raise ValidationError("subspace is not contained in the requested ambient subspace")
    residuals = tuple(subspace.reduce(vector) for vector in container.basis)
    result = LinearSubspace(subspace.field, subspace.ambient_dimension, residuals)
    if result.dimension + subspace.dimension != container.dimension:
        raise VerificationError("internal complement construction has the wrong dimension")
    if intersection(result, subspace).dimension != 0:
        raise VerificationError("internal complement construction is not direct")
    if sum_subspaces(result, subspace) != container:
        raise VerificationError("internal complement construction does not span the container")
    return result


@dataclass(frozen=True, slots=True)
class QuotientSpace(CanonicalObject):
    """A quotient ``numerator / denominator`` with canonical representatives."""

    numerator: LinearSubspace
    denominator: LinearSubspace
    representatives: LinearSubspace

    @property
    def field(self) -> PrimeField:
        """Return the common coefficient field."""

        return self.numerator.field

    @property
    def ambient_dimension(self) -> int:
        """Return the containing coordinate dimension."""

        return self.numerator.ambient_dimension

    @property
    def dimension(self) -> int:
        """Return the quotient dimension."""

        return self.representatives.dimension

    @property
    def basis(self) -> tuple[Vector, ...]:
        """Return canonical representatives of a quotient basis."""

        return self.representatives.basis

    def class_coordinates(self, vector: Iterable[Scalar]) -> Vector:
        """Return quotient coordinates of a numerator vector."""

        values = _coerce_vector(self.field, vector, self.ambient_dimension)
        if not self.numerator.contains(values):
            raise ValidationError("vector does not belong to the quotient numerator")
        reduced = self.denominator.reduce(values)
        return self.representatives.coordinates(reduced)

    def representative(self, coordinates: Iterable[Scalar]) -> Vector:
        """Lift quotient coordinates to the canonical complement."""

        return self.representatives.vector(coordinates)

    def verify(self) -> bool:
        """Verify containment, directness, span, and canonical complement choice."""

        if self.numerator.field != self.denominator.field:
            raise VerificationError("quotient coefficient fields differ")
        if self.numerator.field != self.representatives.field:
            raise VerificationError("representative coefficient field differs")
        if not self.denominator.is_subspace_of(self.numerator):
            raise VerificationError("denominator is not contained in numerator")
        expected = complement(self.denominator, within=self.numerator)
        if self.representatives != expected:
            raise VerificationError("representatives are not the canonical complement")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        """Return the exact quotient presentation."""

        return {
            "denominator": self.denominator.to_canonical_data(),
            "numerator": self.numerator.to_canonical_data(),
            "representatives": self.representatives.to_canonical_data(),
            "type": "arbogast.quotient_space",
        }


def quotient_space(
    numerator: LinearSubspace,
    denominator: LinearSubspace,
) -> QuotientSpace:
    """Construct ``numerator / denominator`` with deterministic representatives."""

    _same_field(numerator.field, denominator.field)
    if numerator.ambient_dimension != denominator.ambient_dimension:
        raise DimensionMismatchError("quotient subspaces have different ambient dimensions")
    if not denominator.is_subspace_of(numerator):
        raise ValidationError("denominator is not contained in numerator")
    result = QuotientSpace(
        numerator=numerator,
        denominator=denominator,
        representatives=complement(denominator, within=numerator),
    )
    result.verify()
    return result


quotient = quotient_space


@dataclass(frozen=True, slots=True)
class LinearSolveResult(CanonicalObject):
    """A complete solution or a Farkas-style inconsistency witness over ``GF(p)``."""

    matrix: DenseMatrix
    rhs: Vector
    consistent: bool
    particular: Vector | None
    kernel: LinearSubspace
    inconsistency_witness: Vector | None

    def verify(
        self,
        matrix: Matrix | None = None,
        rhs: Iterable[Scalar] | None = None,
    ) -> bool:
        """Verify this result, optionally binding it to expected inputs."""

        source = self.matrix
        if matrix is not None and as_dense(matrix) != source:
            raise VerificationError("solution certificate is bound to a different matrix")
        if len(self.rhs) != source.nrows:
            raise VerificationError("stored right-hand side has the wrong length")
        if rhs is not None:
            try:
                expected_rhs = _coerce_vector(source.field, rhs, source.nrows, "rhs")
            except (TypeError, ValidationError) as exc:
                raise VerificationError(str(exc)) from exc
            if expected_rhs != self.rhs:
                raise VerificationError(
                    "solution certificate is bound to a different right-hand side"
                )
        expected_kernel = nullspace(source)
        if self.kernel != expected_kernel:
            raise VerificationError("stored homogeneous solution space is incorrect")

        if self.consistent:
            if self.particular is None:
                raise VerificationError("consistent result has no particular solution")
            if self.inconsistency_witness is not None:
                raise VerificationError("consistent result carries an inconsistency witness")
            if len(self.particular) != source.ncols:
                raise VerificationError("particular solution has the wrong length")
            if source.matvec(self.particular) != self.rhs:
                raise VerificationError("particular vector does not solve the system")
        else:
            if self.particular is not None:
                raise VerificationError("inconsistent result carries a particular solution")
            witness = self.inconsistency_witness
            if witness is None or len(witness) != source.nrows:
                raise VerificationError("inconsistent result lacks a valid witness shape")
            if source.transpose().matvec(witness) != (0,) * source.ncols:
                raise VerificationError("inconsistency witness is not in the left nullspace")
            pairing = (
                sum(left * right for left, right in zip(witness, self.rhs, strict=True))
                % source.field.p
            )
            if pairing == 0:
                raise VerificationError(
                    "inconsistency witness does not separate the right-hand side"
                )
        return True

    def require_solution(self) -> Vector:
        """Return a particular solution or raise if the system is inconsistent."""

        if not self.consistent or self.particular is None:
            raise ValidationError("linear system is inconsistent")
        return self.particular

    def to_canonical_data(self) -> CanonicalJSON:
        """Return a complete exact certificate encoding."""

        return {
            "consistent": self.consistent,
            "inconsistency_witness": (
                None if self.inconsistency_witness is None else list(self.inconsistency_witness)
            ),
            "kernel": self.kernel.to_canonical_data(),
            "matrix": self.matrix.to_canonical_data(),
            "particular": None if self.particular is None else list(self.particular),
            "rhs": list(self.rhs),
            "type": "arbogast.linear_solve_result",
        }


def solve(matrix: Matrix, rhs: Iterable[Scalar]) -> LinearSolveResult:
    """Solve ``A x = b`` and return proof-carrying exact evidence.

    A consistent result includes one particular solution and the full kernel.
    An inconsistent result includes a row vector ``y`` with ``y A = 0`` but
    ``y b != 0``, which independently proves that no solution exists.
    """

    source = as_dense(matrix)
    right_hand_side = _coerce_vector(source.field, rhs, source.nrows, "rhs")
    reduction = rref(source)
    transformed_rhs = reduction.row_transform.matvec(right_hand_side)
    solution_kernel = nullspace(source)

    inconsistent_row = next(
        (row for row in range(reduction.rank, source.nrows) if transformed_rhs[row] != 0),
        None,
    )
    if inconsistent_row is not None:
        result = LinearSolveResult(
            matrix=source,
            rhs=right_hand_side,
            consistent=False,
            particular=None,
            kernel=solution_kernel,
            inconsistency_witness=reduction.row_transform.row(inconsistent_row),
        )
    else:
        particular = [0] * source.ncols
        for row, pivot in enumerate(reduction.pivot_columns):
            particular[pivot] = transformed_rhs[row]
        result = LinearSolveResult(
            matrix=source,
            rhs=right_hand_side,
            consistent=True,
            particular=tuple(particular),
            kernel=solution_kernel,
            inconsistency_witness=None,
        )
    result.verify()
    return result
