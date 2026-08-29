from __future__ import annotations

import pytest

from arbogast.core import ValidationError, canonical_json
from arbogast.linalg import (
    DenseMatrix,
    DimensionMismatchError,
    FieldMismatchError,
    PrimeField,
    SparseMatrix,
)


@pytest.mark.parametrize("modulus", [-7, 0, 1, 4, 9, 21, 25])
def test_prime_field_rejects_nonprimes(modulus: int) -> None:
    with pytest.raises(ValidationError, match="not prime"):
        PrimeField(modulus)


def test_prime_field_rejects_boolean_modulus() -> None:
    with pytest.raises(TypeError):
        PrimeField(True)  # type: ignore[arg-type]


def test_prime_field_element_arithmetic_is_exact() -> None:
    field = PrimeField(7)
    x = field(10)
    y = field(-2)

    assert int(x) == 3
    assert int(y) == 5
    assert int(x + y) == 1
    assert int(x - y) == 5
    assert int(y - x) == 2
    assert int(x * y) == 1
    assert int(x / y) == 2
    assert int(2 / x) == 3
    assert int(-x) == 4
    assert int(x**0) == 1
    assert int(x**-1) == 5
    assert x * x.inverse() == field.one
    assert not field.zero
    assert field.one
    assert hash(field(3)) == hash(x)


def test_field_element_failures_are_explicit() -> None:
    field = PrimeField(5)

    with pytest.raises(ZeroDivisionError):
        field.zero.inverse()
    with pytest.raises(FieldMismatchError):
        _ = field.one + PrimeField(7).one
    with pytest.raises(TypeError):
        field(True)  # type: ignore[arg-type]


def test_field_canonical_encoding_binds_characteristic() -> None:
    field = PrimeField(11)
    element = field(23)

    assert field.characteristic == field.order == 11
    assert canonical_json(field) == '{"characteristic":11,"type":"arbogast.prime_field"}'
    assert '"value":1' in canonical_json(element)


def test_dense_matrix_normalizes_entries_and_is_hashable() -> None:
    field = PrimeField(5)
    matrix = DenseMatrix(field, [[-1, 7], [10, field(3)]])

    assert matrix.shape == (2, 2)
    assert matrix.rows == ((4, 2), (0, 3))
    assert matrix.to_rows() == matrix.rows
    assert matrix.columns == ((4, 0), (2, 3))
    assert matrix.element(0, 0) == field(4)
    assert hash(matrix) == hash(DenseMatrix(field, matrix.rows))
    assert '"shape":[2,2]' in canonical_json(matrix)


def test_dense_matrix_preserves_degenerate_shapes() -> None:
    field = PrimeField(2)
    zero_by_three = DenseMatrix.zeros(field, 0, 3)
    four_by_zero = DenseMatrix.zeros(field, 4, 0)

    assert zero_by_three.shape == (0, 3)
    assert zero_by_three.transpose().shape == (3, 0)
    assert four_by_zero.shape == (4, 0)
    assert four_by_zero.transpose().shape == (0, 4)
    assert (four_by_zero @ zero_by_three) == DenseMatrix.zeros(field, 4, 3)


def test_dense_matrix_rejects_ragged_or_mismatched_shapes() -> None:
    field = PrimeField(3)

    with pytest.raises(DimensionMismatchError, match="same length"):
        DenseMatrix(field, [[1, 2], [1]])
    with pytest.raises(DimensionMismatchError, match="explicit ncols"):
        DenseMatrix(field, [[1, 2]], ncols=3)
    with pytest.raises(ValidationError):
        DenseMatrix.zeros(field, -1, 2)


def test_dense_matrix_arithmetic_and_map_convention() -> None:
    field = PrimeField(7)
    left = DenseMatrix(field, [[1, 2, 3], [0, 1, 4]])  # F^3 -> F^2
    right = DenseMatrix(field, [[1, 0], [2, 1], [3, 4]])  # F^2 -> F^3

    assert left.matvec([1, 2, 3]) == (0, 0)
    assert (left @ right).rows == ((0, 0), (0, 3))
    assert (left + left).rows == ((2, 4, 6), (0, 2, 1))
    assert (left - left) == DenseMatrix.zeros(field, 2, 3)
    assert left.scale(3).rows == ((3, 6, 2), (0, 3, 5))
    assert (-left).rows == ((6, 5, 4), (0, 6, 3))
    assert left.select_rows([1]).rows == ((0, 1, 4),)
    assert left.select_columns([2, 0]).rows == ((3, 1), (4, 0))


def test_dense_matrix_rejects_bad_map_operations() -> None:
    field = PrimeField(5)
    matrix = DenseMatrix.identity(field, 2)

    with pytest.raises(DimensionMismatchError):
        matrix.matvec([1])
    with pytest.raises(DimensionMismatchError):
        _ = matrix @ DenseMatrix.zeros(field, 3, 1)
    with pytest.raises(FieldMismatchError):
        _ = matrix + DenseMatrix.identity(PrimeField(7), 2)


def test_sparse_matrix_is_sorted_combines_duplicates_and_drops_zero() -> None:
    field = PrimeField(5)
    sparse = SparseMatrix(
        field,
        3,
        4,
        [(2, 1, 4), (0, 3, 2), (2, 1, 3), (1, 0, 5), (2, 1, -2)],
    )

    assert sparse.entries == ((0, 3, 2),)
    assert sparse.nnz == 1
    assert sparse.to_dense().rows == ((0, 0, 0, 2), (0, 0, 0, 0), (0, 0, 0, 0))
    assert SparseMatrix.from_dense(sparse.to_dense()) == sparse
    assert sparse.transpose().shape == (4, 3)
    assert sparse.matvec([1, 2, 3, 4]) == (3, 0, 0)


def test_sparse_matrix_rejects_out_of_bounds_entries() -> None:
    with pytest.raises(DimensionMismatchError, match="outside"):
        SparseMatrix(PrimeField(3), 2, 2, [(2, 0, 1)])


def test_dense_sparse_canonical_forms_encode_representation_explicitly() -> None:
    field = PrimeField(3)
    dense = DenseMatrix(field, [[0, 1], [2, 0]])
    sparse = dense.to_sparse()

    assert dense.to_dense() is dense
    assert sparse.to_dense() == dense
    assert canonical_json(dense) != canonical_json(sparse)
    assert '"entries":[[0,1,1],[1,0,2]]' in canonical_json(sparse)
