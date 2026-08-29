from __future__ import annotations

from itertools import product

import pytest

from arbogast.core import ValidationError, VerificationError, canonical_json
from arbogast.linalg import (
    DenseMatrix,
    DimensionMismatchError,
    FieldMismatchError,
    LinearSolveResult,
    LinearSubspace,
    PrimeField,
    QuotientSpace,
    RREFResult,
    SingularMatrixError,
    SparseMatrix,
    complement,
    determinant,
    image,
    intersection,
    inverse,
    left_nullspace,
    nullspace,
    quotient_space,
    rank,
    row_space,
    rref,
    solve,
    sum_subspaces,
)


def test_rref_is_deterministic_and_carries_row_equivalence_witness() -> None:
    field = PrimeField(5)
    matrix = DenseMatrix(field, [[0, 2, 4, 1], [1, 2, 3, 4], [2, 1, 0, 3]])
    result = rref(matrix)

    assert result.matrix.rows == ((1, 0, 4, 0), (0, 1, 2, 0), (0, 0, 0, 1))
    assert result.pivot_columns == (0, 1, 3)
    assert result.rank == 3
    assert result.row_transform @ matrix == result.matrix
    assert result.verify(matrix)
    assert rref(matrix) == result
    assert hash(result) == hash(rref(matrix))
    assert '"pivot_columns":[0,1,3]' in canonical_json(result)


def test_rref_verifier_rejects_noninvertible_transform() -> None:
    field = PrimeField(3)
    matrix = DenseMatrix(field, [[1, 0], [0, 1]])
    forged = RREFResult(
        matrix=DenseMatrix.zeros(field, 2, 2),
        pivot_columns=(),
        row_transform=DenseMatrix.zeros(field, 2, 2),
    )

    with pytest.raises(VerificationError, match="not invertible"):
        forged.verify(matrix)


def test_rank_determinant_and_inverse() -> None:
    field = PrimeField(7)
    matrix = DenseMatrix(field, [[1, 2, 3], [0, 1, 4], [5, 6, 0]])
    candidate = inverse(matrix)

    assert rank(matrix) == 3
    assert determinant(matrix) == 1
    assert candidate @ matrix == DenseMatrix.identity(field, 3)
    assert matrix @ candidate == DenseMatrix.identity(field, 3)
    assert determinant(DenseMatrix.zeros(field, 0, 0)) == 1


def test_inverse_and_determinant_validate_shapes_and_singularity() -> None:
    field = PrimeField(5)

    with pytest.raises(DimensionMismatchError):
        determinant(DenseMatrix.zeros(field, 2, 3))
    with pytest.raises(DimensionMismatchError):
        inverse(DenseMatrix.zeros(field, 2, 3))
    with pytest.raises(SingularMatrixError):
        inverse(DenseMatrix(field, [[1, 2], [2, 4]]))


def test_nullspace_image_and_row_space_are_canonical() -> None:
    field = PrimeField(5)
    matrix = DenseMatrix(field, [[1, 2, 3, 4], [2, 4, 1, 2], [1, 2, 3, 4]])
    kernel = nullspace(matrix)
    matrix_image = image(matrix)
    rows = row_space(matrix)

    assert kernel.dimension == 2
    assert all(matrix.matvec(vector) == (0, 0, 0) for vector in kernel.basis)
    assert matrix_image.dimension == 2
    assert matrix_image.ambient_dimension == 3
    assert rows.dimension == 2
    assert rank(matrix) + kernel.dimension == matrix.ncols
    assert rank(matrix) == matrix_image.dimension == rows.dimension


def test_left_nullspace_annihilates_matrix() -> None:
    field = PrimeField(3)
    matrix = DenseMatrix(field, [[1, 0], [0, 1], [1, 1]])
    space = left_nullspace(matrix)

    assert space.dimension == 1
    assert all(matrix.transpose().matvec(vector) == (0, 0) for vector in space.basis)


def test_consistent_solve_returns_particular_and_full_affine_kernel() -> None:
    field = PrimeField(5)
    matrix = DenseMatrix(field, [[1, 2, 3], [2, 4, 1]])
    result = solve(matrix, [4, 3])

    assert result.consistent
    assert result.particular is not None
    assert matrix.matvec(result.particular) == (4, 3)
    assert result.kernel == nullspace(matrix)
    assert result.verify(matrix, [4, 3])
    for homogeneous in result.kernel.basis:
        shifted = tuple(
            (left + right) % field.p
            for left, right in zip(result.particular, homogeneous, strict=True)
        )
        assert matrix.matvec(shifted) == (4, 3)


def test_inconsistent_solve_returns_left_null_separation_witness() -> None:
    field = PrimeField(5)
    matrix = DenseMatrix(field, [[1, 2], [2, 4]])
    result = solve(matrix, [1, 0])

    assert not result.consistent
    assert result.particular is None
    assert result.inconsistency_witness is not None
    witness = result.inconsistency_witness
    assert matrix.transpose().matvec(witness) == (0, 0)
    assert sum(a * b for a, b in zip(witness, result.rhs, strict=True)) % field.p != 0
    assert result.verify()
    with pytest.raises(ValidationError, match="inconsistent"):
        result.require_solution()


def test_solve_verifier_binds_inputs_and_rejects_forged_result() -> None:
    field = PrimeField(3)
    matrix = DenseMatrix.identity(field, 2)
    valid = solve(matrix, [1, 2])

    with pytest.raises(VerificationError, match="different right-hand side"):
        valid.verify(rhs=[1, 1])

    forged = LinearSolveResult(
        matrix=matrix,
        rhs=(1, 2),
        consistent=True,
        particular=(0, 0),
        kernel=LinearSubspace.zero(field, 2),
        inconsistency_witness=None,
    )
    with pytest.raises(VerificationError, match="does not solve"):
        forged.verify()


def test_linear_subspace_has_unique_reduced_basis() -> None:
    field = PrimeField(5)
    first = LinearSubspace(field, 4, [[1, 2, 3, 4], [0, 1, 1, 0]])
    second = LinearSubspace(field, 4, [[0, 3, 3, 0], [2, 4, 1, 3]])

    assert first == second
    assert first.basis == ((1, 0, 1, 4), (0, 1, 1, 0))
    assert first.pivot_columns == (0, 1)
    assert first.dimension == 2
    assert first.contains([3, 2, 0, 2])
    assert first.coordinates([3, 2, 0, 2]) == (3, 2)
    assert first.vector((3, 2)) == (3, 2, 0, 2)
    assert first.reduce([3, 2, 1, 2]) == (0, 0, 1, 0)
    assert hash(first) == hash(second)


def test_linear_subspace_rejects_invalid_vectors_and_coordinates() -> None:
    field = PrimeField(5)
    space = LinearSubspace(field, 3, [[1, 0, 0]])

    with pytest.raises(DimensionMismatchError):
        LinearSubspace(field, 3, [[1, 0]])
    with pytest.raises(ValidationError, match="does not belong"):
        space.coordinates([0, 1, 0])
    with pytest.raises(DimensionMismatchError):
        space.vector([1, 2])


def test_subspace_sum_intersection_and_complement() -> None:
    field = PrimeField(5)
    left = LinearSubspace(field, 4, [[1, 0, 1, 0], [0, 1, 0, 1]])
    right = LinearSubspace(field, 4, [[1, 0, 1, 0], [0, 0, 1, 1]])
    overlap = intersection(left, right)
    total = sum_subspaces(left, right)
    left_complement = complement(overlap, within=left)

    assert overlap == LinearSubspace(field, 4, [[1, 0, 1, 0]])
    assert total.dimension == 3
    assert left_complement.dimension == 1
    assert intersection(overlap, left_complement).dimension == 0
    assert sum_subspaces(overlap, left_complement) == left


def test_complement_in_full_space_is_deterministic() -> None:
    field = PrimeField(7)
    subspace = LinearSubspace(field, 4, [[1, 2, 0, 3], [0, 0, 1, 4]])
    result = subspace.canonical_complement()

    assert result.basis == ((0, 1, 0, 0), (0, 0, 0, 1))
    assert intersection(result, subspace).dimension == 0
    assert sum_subspaces(result, subspace) == LinearSubspace.full(field, 4)


def test_quotient_uses_canonical_representatives_and_coordinates() -> None:
    field = PrimeField(5)
    numerator = LinearSubspace(field, 4, [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 1]])
    denominator = LinearSubspace(field, 4, [[1, 0, 1, 0]])
    quotient = quotient_space(numerator, denominator)

    assert isinstance(quotient, QuotientSpace)
    assert quotient.dimension == 2
    assert quotient.verify()
    for coordinates in product(range(field.p), repeat=quotient.dimension):
        representative = quotient.representative(coordinates)
        assert quotient.class_coordinates(representative) == coordinates
    assert '"type":"arbogast.quotient_space"' in canonical_json(quotient)


def test_quotient_rejects_noncontained_denominator() -> None:
    field = PrimeField(3)
    numerator = LinearSubspace(field, 2, [[1, 0]])
    denominator = LinearSubspace(field, 2, [[0, 1]])

    with pytest.raises(ValidationError, match="not contained"):
        quotient_space(numerator, denominator)


def test_subspace_operations_reject_field_or_ambient_mismatch() -> None:
    left = LinearSubspace(PrimeField(3), 2, [[1, 0]])

    with pytest.raises(FieldMismatchError):
        sum_subspaces(left, LinearSubspace(PrimeField(5), 2, [[1, 0]]))
    with pytest.raises(DimensionMismatchError):
        intersection(left, LinearSubspace(PrimeField(3), 3, [[1, 0, 0]]))


def test_zero_dimensional_and_empty_equation_edge_cases() -> None:
    field = PrimeField(2)
    no_equations = DenseMatrix.zeros(field, 0, 3)
    no_unknowns = DenseMatrix.zeros(field, 2, 0)

    assert rank(no_equations) == 0
    assert nullspace(no_equations) == LinearSubspace.full(field, 3)
    assert image(no_equations) == LinearSubspace.zero(field, 0)
    assert solve(no_equations, []).particular == (0, 0, 0)
    assert solve(no_unknowns, [0, 0]).particular == ()
    assert not solve(no_unknowns, [1, 0]).consistent
    assert inverse(DenseMatrix.zeros(field, 0, 0)).shape == (0, 0)


def test_exhaustive_small_matrices_satisfy_rank_nullity_and_witnesses() -> None:
    field = PrimeField(2)
    for entries in product(range(field.p), repeat=6):
        matrix = DenseMatrix(field, [entries[:3], entries[3:]])
        reduction = rref(matrix)
        assert reduction.verify(matrix)
        assert rank(matrix) + nullspace(matrix).dimension == 3
        for rhs in product(range(field.p), repeat=2):
            result = solve(matrix, rhs)
            assert result.verify(matrix, rhs)


def test_sparse_elimination_does_not_materialize_the_input(monkeypatch: pytest.MonkeyPatch) -> None:
    field = PrimeField(7)
    sparse = SparseMatrix(
        field,
        5,
        6,
        ((0, 0, 1), (0, 5, 2), (2, 1, 3), (3, 1, 6), (4, 4, 5)),
    )
    dense = sparse.to_dense()

    def refuse_dense(self: SparseMatrix) -> DenseMatrix:
        raise AssertionError("sparse elimination must not call SparseMatrix.to_dense()")

    monkeypatch.setattr(SparseMatrix, "to_dense", refuse_dense)
    assert rref(sparse).matrix == rref(dense).matrix
    assert rank(sparse) == rank(dense)
    assert row_space(sparse) == row_space(dense)
    assert image(sparse) == image(dense)
    assert nullspace(sparse) == nullspace(dense)
    assert left_nullspace(sparse) == left_nullspace(dense)


def test_sparse_determinant_and_multiplication_avoid_dense_input() -> None:
    field = PrimeField(11)
    sparse = SparseMatrix(
        field,
        3,
        3,
        ((0, 0, 2), (0, 2, 1), (1, 1, 3), (2, 0, 4), (2, 2, 5)),
    )
    dense = sparse.to_dense()
    assert determinant(sparse) == determinant(dense)
    assert sparse @ sparse == dense @ dense


def test_exhaustive_small_sparse_paths_match_dense_semantics() -> None:
    field = PrimeField(2)
    for entries in product(range(field.p), repeat=6):
        dense = DenseMatrix(field, (entries[:3], entries[3:]))
        sparse = dense.to_sparse()
        assert rref(sparse) == rref(dense)
        assert row_space(sparse) == row_space(dense)
        assert image(sparse) == image(dense)
        assert nullspace(sparse) == nullspace(dense)
        assert left_nullspace(sparse) == left_nullspace(dense)

    for entries in product(range(field.p), repeat=4):
        dense = DenseMatrix(field, (entries[:2], entries[2:]))
        sparse = dense.to_sparse()
        assert determinant(sparse) == determinant(dense)
        assert sparse @ sparse == dense @ dense
