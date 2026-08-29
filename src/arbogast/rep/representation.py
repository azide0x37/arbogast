"""Exact finite-field linear representations of enumerated finite groups.

Actions are on column vectors.  In agreement with :mod:`arbogast.rep.group`,
``rho(left * right) == rho(left) @ rho(right)``.  Construction binds a matrix
to every element of the supplied concrete group and validates the complete
multiplication table by default.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from inspect import Signature, signature
from itertools import product
from types import MappingProxyType
from typing import Any, cast

from arbogast.linalg import LinearSubspace
from arbogast.linalg.field import PrimeField
from arbogast.linalg.matrix import DenseMatrix, SparseMatrix

from .errors import (
    ConcreteEmbeddingError,
    InvalidActionError,
    NonSemisimpleError,
    NonSplitRepresentationError,
    RepresentationError,
)
from .group import CyclicGroup, PermutationGroup
from .permutation import Permutation

MatrixInput = DenseMatrix | SparseMatrix | Iterable[Iterable[int]]


def _call_or_value(obj: object, name: str) -> Any:
    value = getattr(obj, name)
    if not callable(value):
        return value
    descriptor = getattr(type(obj), name, None)
    if isinstance(descriptor, property):
        return value
    try:
        callable_signature: Signature = signature(value)
        callable_signature.bind()
    except (TypeError, ValueError):
        return value
    return value()


def _group_elements(group: object) -> tuple[Any, ...]:
    if not hasattr(group, "elements"):
        raise TypeError("a representation group must expose a finite .elements iterable")
    elements = tuple(_call_or_value(group, "elements"))
    if not elements:
        raise ValueError("a representation group must contain at least its identity")
    try:
        if len(set(elements)) != len(elements):
            raise ValueError("group.elements contains duplicates")
    except TypeError as exc:
        raise TypeError("group elements must be hashable") from exc
    return elements


def _group_identity(group: object) -> Any:
    if not hasattr(group, "identity"):
        raise TypeError("a representation group must expose .identity")
    return _call_or_value(group, "identity")


def _group_multiply(group: object, left: Any, right: Any) -> Any:
    multiply = getattr(group, "multiply", None)
    return multiply(left, right) if callable(multiply) else left * right


def _group_inverse(group: object, element: Any) -> Any:
    inverse = getattr(group, "inverse", None)
    if callable(inverse):
        return inverse(element)
    element_inverse = getattr(element, "inverse", None)
    if callable(element_inverse):
        return element_inverse()
    return element**-1


def _coerce_field(field: PrimeField | int) -> PrimeField:
    if isinstance(field, PrimeField):
        return field
    if isinstance(field, bool) or not isinstance(field, int):
        raise TypeError("the coefficient field must be a PrimeField or prime integer")
    return PrimeField(field)


def _coerce_matrix(
    field: PrimeField,
    matrix: MatrixInput | object,
    *,
    dimension: int | None = None,
) -> DenseMatrix:
    if isinstance(matrix, SparseMatrix):
        result = matrix.to_dense()
    elif isinstance(matrix, DenseMatrix):
        result = matrix
    else:
        rows = getattr(matrix, "rows", matrix)
        rows = rows() if callable(rows) else rows
        try:
            result = DenseMatrix(field, cast(Iterable[Iterable[int]], rows))
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "action matrices must be DenseMatrix, SparseMatrix, or row data"
            ) from exc
    if result.field != field:
        raise InvalidActionError(
            f"action matrix uses {result.field!r}, expected coefficient field {field!r}"
        )
    if result.nrows != result.ncols:
        raise InvalidActionError(f"action matrix must be square, got shape {result.shape}")
    if dimension is not None and result.shape != (dimension, dimension):
        raise InvalidActionError(
            f"action matrix has shape {result.shape}, expected {(dimension, dimension)}"
        )
    return result


def _matrix_inverse(matrix: DenseMatrix) -> DenseMatrix:
    if matrix.nrows != matrix.ncols:
        raise InvalidActionError("only square matrices can be inverted")
    size = matrix.nrows
    prime = matrix.field.p
    work = [
        [*row, *(1 if column == index else 0 for column in range(size))]
        for index, row in enumerate(matrix.rows)
    ]
    for column in range(size):
        pivot = next((row for row in range(column, size) if work[row][column] % prime), None)
        if pivot is None:
            raise InvalidActionError("a group action matrix is singular")
        work[column], work[pivot] = work[pivot], work[column]
        inverse = pow(work[column][column] % prime, -1, prime)
        work[column] = [(value * inverse) % prime for value in work[column]]
        for row in range(size):
            if row == column:
                continue
            coefficient = work[row][column] % prime
            if coefficient:
                work[row] = [
                    (left - coefficient * right) % prime
                    for left, right in zip(work[row], work[column], strict=True)
                ]
    return DenseMatrix(matrix.field, (row[size:] for row in work), ncols=size)


def _rref_basis(
    vectors: Iterable[Sequence[int]], width: int, prime: int
) -> tuple[tuple[int, ...], ...]:
    work = [[value % prime for value in vector] for vector in vectors]
    if any(len(row) != width for row in work):
        raise ValueError("subspace vector has the wrong ambient dimension")
    pivot_row = 0
    for column in range(width):
        pivot = next(
            (row for row in range(pivot_row, len(work)) if work[row][column] % prime),
            None,
        )
        if pivot is None:
            continue
        work[pivot_row], work[pivot] = work[pivot], work[pivot_row]
        inverse = pow(work[pivot_row][column] % prime, -1, prime)
        work[pivot_row] = [(value * inverse) % prime for value in work[pivot_row]]
        for row in range(len(work)):
            if row == pivot_row:
                continue
            coefficient = work[row][column] % prime
            if coefficient:
                work[row] = [
                    (left - coefficient * right) % prime
                    for left, right in zip(work[row], work[pivot_row], strict=True)
                ]
        pivot_row += 1
        if pivot_row == len(work):
            break
    nonzero = (row for row in work if any(value % prime for value in row))
    return tuple(tuple(value % prime for value in row) for row in nonzero)


def _nullspace_rows(
    rows: Iterable[Sequence[int]], width: int, prime: int
) -> tuple[tuple[int, ...], ...]:
    reduced = _rref_basis(rows, width, prime)
    pivots = tuple(next(index for index, value in enumerate(row) if value) for row in reduced)
    pivot_set = set(pivots)
    basis: list[tuple[int, ...]] = []
    for free in range(width):
        if free in pivot_set:
            continue
        vector = [0] * width
        vector[free] = 1
        for row, pivot in zip(reduced, pivots, strict=True):
            vector[pivot] = (-row[free]) % prime
        basis.append(tuple(vector))
    return _rref_basis(basis, width, prime)


def _make_subspace(
    field: PrimeField,
    ambient_dimension: int,
    basis: Iterable[Sequence[int]],
) -> LinearSubspace:
    canonical_basis = _rref_basis(basis, ambient_dimension, field.p)
    return LinearSubspace(field, ambient_dimension, canonical_basis)


def _matrix_image_subspace(matrix: DenseMatrix) -> LinearSubspace:
    basis = _rref_basis(matrix.columns, matrix.nrows, matrix.field.p)
    return _make_subspace(matrix.field, matrix.nrows, basis)


def _matrix_kernel_subspace(matrix: DenseMatrix) -> LinearSubspace:
    return _make_subspace(
        matrix.field,
        matrix.ncols,
        _nullspace_rows(matrix.rows, matrix.ncols, matrix.field.p),
    )


@dataclass(frozen=True, slots=True)
class RepresentationValidation:
    """A concise receipt for exhaustive action-law validation."""

    group_order: int
    dimension: int
    identity_checks: int
    multiplication_checks: int

    def verify(self, representation: Representation) -> bool:
        try:
            replay = representation.validate()
        except InvalidActionError:
            return False
        return replay == self


@dataclass(frozen=True, slots=True)
class SemisimplicityResult:
    """A conservative exact semisimplicity determination."""

    semisimple: bool
    reason: str
    characteristic: int
    group_order: int

    @property
    def certified(self) -> bool:
        return self.semisimple

    def __bool__(self) -> bool:
        return self.semisimple


class Character:
    """A concrete finite-field class function on one enumerated group."""

    __slots__ = ("_lookup", "_values", "dimension", "field", "group", "name")

    def __init__(
        self,
        group: object,
        field: PrimeField | int,
        values: Mapping[Any, int] | Callable[[Any], int],
        *,
        dimension: int | None = None,
        name: str | None = None,
        validate: bool = True,
    ) -> None:
        self.group = group
        self.field = _coerce_field(field)
        self.name = name
        elements = _group_elements(group)
        if isinstance(values, Mapping):
            if set(values) != set(elements):
                missing = set(elements).difference(values)
                extra = set(values).difference(elements)
                counts = f"missing={len(missing)}, extra={len(extra)}"
                raise ConcreteEmbeddingError(
                    f"character values must be keyed by exactly this group ({counts})"
                )
            normalized = tuple(self.field.residue(values[element]) for element in elements)
        elif callable(values):
            normalized = tuple(self.field.residue(values(element)) for element in elements)
        else:
            raise TypeError("character values must be a mapping or callable")
        identity = _group_identity(group)
        identity_index = elements.index(identity)
        inferred_dimension = normalized[identity_index]
        if dimension is None:
            dimension = inferred_dimension
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 0:
            raise TypeError("character dimension must be a nonnegative integer")
        if self.field.residue(dimension) != inferred_dimension:
            raise ValueError("character value at the identity does not equal its dimension")
        self.dimension = dimension
        self._values = normalized
        self._lookup = MappingProxyType(dict(zip(elements, normalized, strict=True)))
        if validate:
            for element in elements:
                for by in elements:
                    conjugate = _group_multiply(
                        group,
                        _group_multiply(group, by, element),
                        _group_inverse(group, by),
                    )
                    if self._lookup[conjugate] != self._lookup[element]:
                        raise ValueError("character values are not constant on conjugacy classes")

    @property
    def values(self) -> tuple[int, ...]:
        return self._values

    def value(self, element: Any) -> int:
        try:
            return cast(int, self._lookup[element])
        except (KeyError, TypeError) as exc:
            raise ConcreteEmbeddingError(
                "character queried on an element outside its concrete group"
            ) from exc

    def __call__(self, element: Any) -> int:
        return self.value(element)

    def __repr__(self) -> str:
        return f"Character(name={self.name!r}, dimension={self.dimension}, field={self.field!r})"


@dataclass(frozen=True, slots=True)
class IsotypicComponent:
    """A character-selected summand with its exact central idempotent."""

    character: Character
    subspace: LinearSubspace
    projector: DenseMatrix

    @property
    def dimension(self) -> int:
        return self.subspace.dimension


@dataclass(frozen=True, slots=True)
class IsotypicDecomposition:
    """Exact selected isotypic summands plus their canonical residual summand."""

    representation: Representation
    components: tuple[IsotypicComponent, ...]
    remainder: LinearSubspace
    remainder_projector: DenseMatrix

    def __iter__(self) -> Iterator[IsotypicComponent]:
        return iter(self.components)

    def __len__(self) -> int:
        return len(self.components)

    def __getitem__(self, key: int | str | Character) -> IsotypicComponent:
        if isinstance(key, int):
            return self.components[key]
        for component in self.components:
            if key is component.character or key == component.character.name:
                return component
        raise KeyError(key)

    @property
    def complete(self) -> bool:
        return self.remainder.dimension == 0

    def verify(self) -> bool:
        representation = self.representation
        identity = DenseMatrix.identity(representation.field, representation.dimension)
        zero = DenseMatrix.zeros(
            representation.field,
            representation.dimension,
            representation.dimension,
        )
        total = zero
        for left_index, left in enumerate(self.components):
            if left.projector @ left.projector != left.projector:
                return False
            if _matrix_image_subspace(left.projector) != left.subspace:
                return False
            total = total + left.projector
            for right_index, right in enumerate(self.components):
                if left_index != right_index and left.projector @ right.projector != zero:
                    return False
        if self.remainder_projector != identity - total:
            return False
        if self.remainder_projector @ self.remainder_projector != self.remainder_projector:
            return False
        if _matrix_image_subspace(self.remainder_projector) != self.remainder:
            return False
        if any(
            component.projector @ self.remainder_projector != zero
            or self.remainder_projector @ component.projector != zero
            for component in self.components
        ):
            return False
        return total + self.remainder_projector == identity


Polynomial = tuple[int, ...]  # coefficients in ascending order


def _poly_trim(poly: Iterable[int], prime: int) -> Polynomial:
    result = [coefficient % prime for coefficient in poly]
    while len(result) > 1 and result[-1] == 0:
        result.pop()
    return tuple(result or [0])


def _poly_degree(poly: Polynomial) -> int:
    return -1 if poly == (0,) else len(poly) - 1


def _poly_add(left: Polynomial, right: Polynomial, prime: int) -> Polynomial:
    size = max(len(left), len(right))
    return _poly_trim(
        (
            (left[index] if index < len(left) else 0) + (right[index] if index < len(right) else 0)
            for index in range(size)
        ),
        prime,
    )


def _poly_sub(left: Polynomial, right: Polynomial, prime: int) -> Polynomial:
    size = max(len(left), len(right))
    return _poly_trim(
        (
            (left[index] if index < len(left) else 0) - (right[index] if index < len(right) else 0)
            for index in range(size)
        ),
        prime,
    )


def _poly_scale(poly: Polynomial, scalar: int, prime: int) -> Polynomial:
    return _poly_trim((scalar * coefficient for coefficient in poly), prime)


def _poly_mul(left: Polynomial, right: Polynomial, prime: int) -> Polynomial:
    if left == (0,) or right == (0,):
        return (0,)
    result = [0] * (len(left) + len(right) - 1)
    for left_degree, left_coefficient in enumerate(left):
        for right_degree, right_coefficient in enumerate(right):
            result[left_degree + right_degree] += left_coefficient * right_coefficient
    return _poly_trim(result, prime)


def _poly_divmod(
    numerator: Polynomial, denominator: Polynomial, prime: int
) -> tuple[Polynomial, Polynomial]:
    denominator = _poly_trim(denominator, prime)
    if denominator == (0,):
        raise ZeroDivisionError("polynomial division by zero")
    remainder = list(_poly_trim(numerator, prime))
    quotient = [0] * max(1, len(remainder) - len(denominator) + 1)
    inverse_lead = pow(denominator[-1], -1, prime)
    while not (len(remainder) == 1 and remainder[0] == 0) and len(remainder) >= len(denominator):
        shift = len(remainder) - len(denominator)
        coefficient = remainder[-1] * inverse_lead % prime
        quotient[shift] = coefficient
        for index, value in enumerate(denominator):
            remainder[index + shift] = (remainder[index + shift] - coefficient * value) % prime
        remainder = list(_poly_trim(remainder, prime))
    return _poly_trim(quotient, prime), _poly_trim(remainder, prime)


def _poly_xgcd(
    left: Polynomial,
    right: Polynomial,
    prime: int,
) -> tuple[Polynomial, Polynomial, Polynomial]:
    old_r, r = _poly_trim(left, prime), _poly_trim(right, prime)
    old_s: Polynomial = (1,)
    s: Polynomial = (0,)
    old_t: Polynomial = (0,)
    t: Polynomial = (1,)
    while r != (0,):
        quotient, remainder = _poly_divmod(old_r, r, prime)
        old_r, r = r, remainder
        old_s, s = s, _poly_sub(old_s, _poly_mul(quotient, s, prime), prime)
        old_t, t = t, _poly_sub(old_t, _poly_mul(quotient, t, prime), prime)
    normalizer = pow(old_r[-1], -1, prime)
    return (
        _poly_scale(old_r, normalizer, prime),
        _poly_scale(old_s, normalizer, prime),
        _poly_scale(old_t, normalizer, prime),
    )


def _factor_monic_squarefree(poly: Polynomial, prime: int) -> tuple[Polynomial, ...]:
    remaining = _poly_trim(poly, prime)
    if remaining[-1] != 1:
        remaining = _poly_scale(remaining, pow(remaining[-1], -1, prime), prime)
    factors: list[Polynomial] = []
    candidate_count = 0
    degree = 1
    while 2 * degree <= _poly_degree(remaining):
        divided = False
        for lower_coefficients in product(range(prime), repeat=degree):
            candidate_count += 1
            if candidate_count > 1_000_000:
                raise NotImplementedError(
                    "cyclic factorization exceeded the pure-Python v0.1 search bound"
                )
            candidate = (*lower_coefficients, 1)
            quotient, remainder = _poly_divmod(remaining, candidate, prime)
            if remainder == (0,):
                factors.append(candidate)
                remaining = quotient
                divided = True
                break
        if not divided:
            degree += 1
    if _poly_degree(remaining) > 0:
        factors.append(remaining)
    if len(set(factors)) != len(factors):
        raise NonSemisimpleError("the cyclic annihilating polynomial has repeated factors")
    return tuple(sorted(factors, key=lambda factor: (len(factor), factor)))


def _matrix_polynomial(matrix: DenseMatrix, polynomial: Polynomial) -> DenseMatrix:
    identity = DenseMatrix.identity(matrix.field, matrix.nrows)
    result = DenseMatrix.zeros(matrix.field, matrix.nrows, matrix.ncols)
    for coefficient in reversed(polynomial):
        result = result @ matrix
        if coefficient:
            result = result + identity.scale(coefficient)
    return result


@dataclass(frozen=True, slots=True, order=True)
class CyclicFactor:
    """A monic irreducible factor defining one cyclic isotypic component."""

    characteristic: int
    coefficients: Polynomial

    @property
    def degree(self) -> int:
        return len(self.coefficients) - 1

    @property
    def eigenvalue(self) -> int | None:
        if self.degree != 1:
            return None
        return (-self.coefficients[0]) % self.characteristic

    def __repr__(self) -> str:
        if self.eigenvalue is not None:
            return f"CyclicFactor(x - {self.eigenvalue} over GF({self.characteristic}))"
        return f"CyclicFactor({self.coefficients!r} over GF({self.characteristic}))"


@dataclass(frozen=True, slots=True)
class CyclicComponent:
    """One exact primary/isotypic component of a semisimple cyclic action."""

    factor: CyclicFactor
    subspace: LinearSubspace
    projector: DenseMatrix

    @property
    def dimension(self) -> int:
        return int(self.subspace.dimension)

    @property
    def eigenvalue(self) -> int | None:
        return self.factor.eigenvalue


@dataclass(frozen=True, slots=True)
class CyclicDecomposition:
    """CRT decomposition of a semisimple cyclic action over the base field."""

    representation: Representation
    generator: Any
    components: tuple[CyclicComponent, ...]

    def __iter__(self) -> Iterator[CyclicComponent]:
        return iter(self.components)

    def __len__(self) -> int:
        return len(self.components)

    def __getitem__(self, key: int | CyclicFactor) -> CyclicComponent:
        for component in self.components:
            if key == component.factor or key == component.eigenvalue:
                return component
        raise KeyError(key)

    @property
    def is_split(self) -> bool:
        return all(component.factor.degree == 1 for component in self.components)

    def verify(self) -> bool:
        representation = self.representation
        identity = DenseMatrix.identity(representation.field, representation.dimension)
        zero = DenseMatrix.zeros(
            representation.field, representation.dimension, representation.dimension
        )

        try:
            action = representation.action_matrix(self.generator)
            generator_order = representation._cyclic_generator_order(self.generator)
            if generator_order != len(representation.elements):
                return False
            if generator_order % representation.field.p == 0:
                return False

            annihilating_polynomial = _poly_trim(
                (-1, *(0 for _ in range(generator_order - 1)), 1),
                representation.field.p,
            )
            if _matrix_polynomial(action, annihilating_polynomial) != zero:
                return False

            expected_components: list[tuple[CyclicFactor, DenseMatrix, LinearSubspace]] = []
            for coefficients in _factor_monic_squarefree(
                annihilating_polynomial, representation.field.p
            ):
                factor_action = _matrix_polynomial(action, coefficients)
                factor_kernel = _matrix_kernel_subspace(factor_action)
                if factor_kernel.dimension:
                    expected_components.append(
                        (
                            CyclicFactor(representation.field.p, coefficients),
                            factor_action,
                            factor_kernel,
                        )
                    )
        except (TypeError, ValueError, NotImplementedError):
            return False

        if tuple(component.factor for component in self.components) != tuple(
            factor for factor, _factor_action, _factor_kernel in expected_components
        ):
            return False

        total = zero
        for left_index, (left, expected) in enumerate(
            zip(self.components, expected_components, strict=True)
        ):
            _factor, factor_action, factor_kernel = expected
            if left.projector @ left.projector != left.projector:
                return False
            if _matrix_image_subspace(left.projector) != left.subspace:
                return False
            if left.subspace != factor_kernel:
                return False
            if factor_action @ left.projector != zero:
                return False
            if action @ left.projector != left.projector @ action:
                return False
            total = total + left.projector
            for right_index, right in enumerate(self.components):
                if left_index != right_index and left.projector @ right.projector != zero:
                    return False
        return (
            total == identity
            and sum(component.dimension for component in self.components)
            == representation.dimension
        )


@dataclass(frozen=True, slots=True)
class WeightDecomposition:
    """A split cyclic decomposition indexed by base-field eigenvalues."""

    cyclic: CyclicDecomposition

    @property
    def weights(self) -> tuple[int, ...]:
        return tuple(
            component.eigenvalue
            for component in self.cyclic.components
            if component.eigenvalue is not None
        )

    def __iter__(self) -> Iterator[int]:
        return iter(self.weights)

    def __len__(self) -> int:
        return len(self.weights)

    def __getitem__(self, eigenvalue: int) -> LinearSubspace:
        return self.cyclic[eigenvalue].subspace

    def projector(self, eigenvalue: int) -> DenseMatrix:
        return self.cyclic[eigenvalue].projector

    def items(self) -> tuple[tuple[int, LinearSubspace], ...]:
        return tuple((weight, self[weight]) for weight in self.weights)

    def verify(self) -> bool:
        return self.cyclic.is_split and self.cyclic.verify()


class Representation:
    """A completely enumerated exact linear action of one concrete group."""

    ACTION_CONVENTION = "column action: rho(left * right) = rho(left) @ rho(right)"

    __slots__ = (
        "_cyclic_cache",
        "_elements",
        "_matrices",
        "_validation",
        "dimension",
        "field",
        "group",
        "name",
    )

    def __init__(
        self,
        group: object,
        field: PrimeField | int,
        action: Mapping[Any, MatrixInput] | Callable[[Any], MatrixInput] | None = None,
        *,
        matrices: Mapping[Any, MatrixInput] | None = None,
        dimension: int | None = None,
        validate: bool = True,
        name: str | None = None,
    ) -> None:
        if action is not None and matrices is not None:
            raise TypeError("provide action matrices through either action or matrices, not both")
        source = matrices if matrices is not None else action
        if source is None:
            raise TypeError("a matrix mapping or action callable is required")
        self.group = group
        self.field = _coerce_field(field)
        self.name = name
        elements = _group_elements(group)
        identity = _group_identity(group)
        if identity not in elements:
            raise InvalidActionError("group.identity is absent from group.elements")

        if isinstance(source, Mapping):
            try:
                source_keys = set(source)
                element_keys = set(elements)
            except TypeError as exc:
                raise TypeError("group elements and matrix mapping keys must be hashable") from exc
            if source_keys != element_keys:
                missing = element_keys.difference(source_keys)
                extra = source_keys.difference(element_keys)
                raise ConcreteEmbeddingError(
                    "action mapping must be keyed by every and only element of the concrete group "
                    f"(missing={len(missing)}, extra={len(extra)})"
                )
            raw_matrices = tuple(source[element] for element in elements)
        elif callable(source):
            raw_matrices = tuple(source(element) for element in elements)
        else:
            raise TypeError("action must be a mapping keyed by group elements or a callable")

        if dimension is not None and (
            isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 0
        ):
            raise TypeError("representation dimension must be a nonnegative integer")
        first = _coerce_matrix(self.field, raw_matrices[0], dimension=dimension)
        if dimension is None:
            dimension = first.nrows
        normalized = (
            first,
            *(
                _coerce_matrix(self.field, matrix, dimension=dimension)
                for matrix in raw_matrices[1:]
            ),
        )
        self.dimension = dimension
        self._elements = elements
        self._matrices = MappingProxyType(dict(zip(elements, normalized, strict=True)))
        self._validation: RepresentationValidation | None = None
        self._cyclic_cache: dict[Any, CyclicDecomposition] = {}
        if validate:
            self._validation = self.validate()

    @classmethod
    def from_generators(
        cls,
        group: PermutationGroup,
        field: PrimeField | int,
        generator_matrices: Mapping[Permutation, MatrixInput] | Sequence[MatrixInput],
        *,
        validate: bool = True,
        name: str | None = None,
    ) -> Representation:
        """Extend matrices on exact concrete generators using stored words."""

        coefficient_field = _coerce_field(field)
        generators = group.generators
        if isinstance(generator_matrices, Mapping):
            if set(generator_matrices) != set(generators):
                raise ConcreteEmbeddingError(
                    "generator matrix mapping must use exactly group.generators"
                )
            raw = tuple(generator_matrices[generator] for generator in generators)
        else:
            raw = tuple(generator_matrices)
            if len(raw) != len(generators):
                raise ValueError("generator matrix sequence length does not match group.generators")
        if not raw:
            raise ValueError("from_generators requires at least one concrete generator matrix")
        matrices = tuple(_coerce_matrix(coefficient_field, matrix) for matrix in raw)
        dimension = matrices[0].nrows
        if any(matrix.shape != (dimension, dimension) for matrix in matrices):
            raise InvalidActionError("all generator matrices must have the same square shape")
        inverses = tuple(_matrix_inverse(matrix) for matrix in matrices)
        identity = DenseMatrix.identity(coefficient_field, dimension)
        action: dict[Permutation, DenseMatrix] = {}
        for element in group.elements:
            witness = group.generation_witness(element)
            matrix = identity
            for step in witness.steps:
                matrix = matrix @ (
                    inverses[step.generator_index]
                    if step.inverse
                    else matrices[step.generator_index]
                )
            action[element] = matrix
        return cls(
            group,
            coefficient_field,
            action,
            dimension=dimension,
            validate=validate,
            name=name,
        )

    @classmethod
    def trivial(
        cls,
        group: object,
        field: PrimeField | int,
        dimension: int = 1,
        *,
        name: str | None = None,
    ) -> Representation:
        coefficient_field = _coerce_field(field)
        identity = DenseMatrix.identity(coefficient_field, dimension)
        return cls(group, coefficient_field, lambda _element: identity, name=name or "trivial")

    @classmethod
    def permutation(
        cls,
        group: PermutationGroup,
        field: PrimeField | int,
        *,
        points: Sequence[int] | None = None,
        name: str | None = None,
    ) -> Representation:
        """The exact permutation module on an explicitly invariant point set."""

        coefficient_field = _coerce_field(field)
        domain = tuple(range(group.degree)) if points is None else tuple(points)
        if len(set(domain)) != len(domain):
            raise ValueError("permutation-module points must be distinct")
        if any(not 0 <= point < group.degree for point in domain):
            raise ValueError("permutation-module point lies outside the concrete group degree")
        position = {point: index for index, point in enumerate(domain)}
        if any(element(point) not in position for element in group.elements for point in domain):
            raise ValueError("permutation-module point set is not group-invariant")

        def action(element: Permutation) -> DenseMatrix:
            rows = [[0] * len(domain) for _ in domain]
            for source, point in enumerate(domain):
                rows[position[element(point)]][source] = 1
            return DenseMatrix(coefficient_field, rows, ncols=len(domain))

        return cls(group, coefficient_field, action, name=name or "permutation module")

    @property
    def elements(self) -> tuple[Any, ...]:
        return self._elements

    @property
    def matrices(self) -> Mapping[Any, DenseMatrix]:
        return self._matrices

    @property
    def validation(self) -> RepresentationValidation | None:
        return self._validation

    def action_matrix(self, element: Any) -> DenseMatrix:
        try:
            return cast(DenseMatrix, self._matrices[element])
        except (KeyError, TypeError) as exc:
            raise ConcreteEmbeddingError(
                "action requested for an element outside this concrete group; "
                "no transport was inferred"
            ) from exc

    def action(self, element: Any) -> DenseMatrix:
        return self.action_matrix(element)

    def matrix(self, element: Any) -> DenseMatrix:
        return self.action_matrix(element)

    def apply(self, element: Any, vector: Iterable[int]) -> tuple[int, ...]:
        return self.action_matrix(element).matvec(vector)

    def validate(self) -> RepresentationValidation:
        identity = _group_identity(self.group)
        identity_matrix = DenseMatrix.identity(self.field, self.dimension)
        if self.action_matrix(identity) != identity_matrix:
            raise InvalidActionError("identity element does not act by the identity matrix")
        checks = 0
        element_set = set(self.elements)
        for left in self.elements:
            for right in self.elements:
                product_element = _group_multiply(self.group, left, right)
                if product_element not in element_set:
                    raise InvalidActionError("group multiplication left the enumerated element set")
                expected = self.action_matrix(left) @ self.action_matrix(right)
                if self.action_matrix(product_element) != expected:
                    raise InvalidActionError(
                        "action multiplication failed for a concrete element pair: "
                        "rho(left * right) != rho(left) @ rho(right)"
                    )
                checks += 1
        return RepresentationValidation(
            group_order=len(self.elements),
            dimension=self.dimension,
            identity_checks=1,
            multiplication_checks=checks,
        )

    def fixed_space(self, element: Any) -> LinearSubspace:
        matrix = self.action_matrix(element)
        equations = matrix - DenseMatrix.identity(self.field, self.dimension)
        return _matrix_kernel_subspace(equations)

    def fixed_part(self, element: Any) -> LinearSubspace:
        return self.fixed_space(element)

    def invariant_space(self, subgroup: object | None = None) -> LinearSubspace:
        if subgroup is None:
            elements = self.elements
        else:
            elements = _group_elements(subgroup)
            if any(element not in self._matrices for element in elements):
                raise ConcreteEmbeddingError(
                    "invariants requested for a group outside the representation's "
                    "concrete embedding"
                )
        identity = DenseMatrix.identity(self.field, self.dimension)
        equations = tuple(
            row for element in elements for row in (self.action_matrix(element) - identity).rows
        )
        return _make_subspace(
            self.field,
            self.dimension,
            _nullspace_rows(equations, self.dimension, self.field.p),
        )

    @property
    def invariants(self) -> LinearSubspace:
        return self.invariant_space()

    def restrict(self, subgroup: object, *, name: str | None = None) -> Representation:
        subgroup_elements = _group_elements(subgroup)
        if any(element not in self._matrices for element in subgroup_elements):
            raise ConcreteEmbeddingError(
                "restriction requires a literal concrete subgroup; "
                "no isomorphism transport is inferred"
            )
        return Representation(
            subgroup,
            self.field,
            {element: self.action_matrix(element) for element in subgroup_elements},
            dimension=self.dimension,
            name=name or self.name,
        )

    def semisimplicity(self) -> SemisimplicityResult:
        order = len(self.elements)
        if order % self.field.p != 0:
            return SemisimplicityResult(
                True,
                "Maschke's theorem: the characteristic does not divide the group order",
                self.field.p,
                order,
            )
        identity = DenseMatrix.identity(self.field, self.dimension)
        if all(matrix == identity for matrix in self.matrices.values()):
            return SemisimplicityResult(
                True,
                "the action is explicitly a direct sum of trivial simple modules",
                self.field.p,
                order,
            )
        return SemisimplicityResult(
            False,
            "semisimplicity is not certified when the characteristic divides the group order",
            self.field.p,
            order,
        )

    @property
    def is_semisimple(self) -> bool:
        return bool(self.semisimplicity())

    def character(self, *, name: str | None = None) -> Character:
        return Character(
            self.group,
            self.field,
            {
                element: sum(
                    self.action_matrix(element)[index, index] for index in range(self.dimension)
                )
                % self.field.p
                for element in self.elements
            },
            dimension=self.dimension,
            name=name or self.name,
        )

    def character_projector(self, character: Character) -> DenseMatrix:
        if character.group != self.group:
            raise ConcreteEmbeddingError(
                "character and representation use different concrete groups; "
                "no transport was inferred"
            )
        if character.field != self.field:
            raise RepresentationError("character and representation coefficient fields differ")
        order = len(self.elements)
        if order % self.field.p == 0:
            raise NonSemisimpleError(
                "the character projector divides by the group order, which is zero in this field"
            )
        result = DenseMatrix.zeros(self.field, self.dimension, self.dimension)
        for element in self.elements:
            coefficient = character(_group_inverse(self.group, element))
            result = result + self.action_matrix(element).scale(coefficient)
        scalar = character.dimension * pow(order % self.field.p, -1, self.field.p)
        result = result.scale(scalar)
        if result @ result != result:
            raise RepresentationError(
                "the supplied finite-field character does not produce an idempotent projector"
            )
        if any(
            result @ self.action_matrix(element) != self.action_matrix(element) @ result
            for element in self.elements
        ):
            raise RepresentationError("computed character projector is not equivariant")
        return result

    def isotypic_decomposition(
        self,
        characters: Iterable[Character],
        *,
        require_complete: bool = False,
    ) -> IsotypicDecomposition:
        """Decompose by supplied finite-field characters and retain any residual.

        The supplied character projectors must be pairwise orthogonal.  Since a
        full irreducible character table is backend-dependent, v0.1 makes that
        input explicit instead of silently guessing abstract group labels.
        """

        if not self.is_semisimple:
            raise NonSemisimpleError(
                "isotypic decomposition requires a certified semisimple representation"
            )
        selected = tuple(characters)
        if len({id(character) for character in selected}) != len(selected):
            raise ValueError("isotypic character list contains duplicate objects")
        zero = DenseMatrix.zeros(self.field, self.dimension, self.dimension)
        identity = DenseMatrix.identity(self.field, self.dimension)
        components: list[IsotypicComponent] = []
        total = zero
        for character in selected:
            selected_projector = self.character_projector(character)
            if any(
                selected_projector @ component.projector != zero
                or component.projector @ selected_projector != zero
                for component in components
            ):
                raise RepresentationError("supplied character projectors are not orthogonal")
            components.append(
                IsotypicComponent(
                    character,
                    _matrix_image_subspace(selected_projector),
                    selected_projector,
                )
            )
            total = total + selected_projector
        remainder_projector = identity - total
        if remainder_projector @ remainder_projector != remainder_projector:
            raise RepresentationError("selected characters do not define an isotypic direct sum")
        result = IsotypicDecomposition(
            self,
            tuple(components),
            _matrix_image_subspace(remainder_projector),
            remainder_projector,
        )
        if not result.verify():
            raise RepresentationError("isotypic decomposition failed exact projector checks")
        if require_complete and not result.complete:
            raise RepresentationError(
                f"supplied characters leave a residual dimension {result.remainder.dimension}"
            )
        return result

    def cyclic_decomposition(self, generator: Any | None = None) -> CyclicDecomposition:
        if generator is None:
            if isinstance(self.group, CyclicGroup):
                generator = self.group.generator
            else:
                generators = (
                    tuple(_call_or_value(self.group, "generators"))
                    if hasattr(self.group, "generators")
                    else ()
                )
                candidates = [
                    candidate
                    for candidate in generators
                    if self._cyclic_generator_order(candidate) == len(self.elements)
                ]
                if len(candidates) != 1:
                    raise ValueError("supply the distinguished generator for this cyclic action")
                generator = candidates[0]
        self.action_matrix(generator)
        if generator in self._cyclic_cache:
            return self._cyclic_cache[generator]
        generator_order = self._cyclic_generator_order(generator)
        if generator_order != len(self.elements):
            raise ValueError("the selected element does not generate the entire concrete group")
        if generator_order % self.field.p == 0:
            raise NonSemisimpleError(
                "cyclic CRT decomposition requires characteristic prime to the generator order"
            )

        polynomial = _poly_trim((-1, *(0 for _ in range(generator_order - 1)), 1), self.field.p)
        factors = _factor_monic_squarefree(polynomial, self.field.p)
        action = self.action_matrix(generator)
        components: list[CyclicComponent] = []
        for factor_coefficients in factors:
            other: Polynomial = (1,)
            for candidate in factors:
                if candidate != factor_coefficients:
                    other = _poly_mul(other, candidate, self.field.p)
            gcd, _factor_coefficient, other_coefficient = _poly_xgcd(
                factor_coefficients, other, self.field.p
            )
            if gcd != (1,):
                raise NonSemisimpleError("cyclic factors are not pairwise coprime")
            idempotent_polynomial = _poly_mul(other_coefficient, other, self.field.p)
            projector = _matrix_polynomial(action, idempotent_polynomial)
            subspace = _matrix_image_subspace(projector)
            if subspace.dimension == 0:
                continue
            factor = CyclicFactor(self.field.p, factor_coefficients)
            kernel = _matrix_kernel_subspace(_matrix_polynomial(action, factor_coefficients))
            if kernel.dimension != subspace.dimension:
                raise RepresentationError("CRT image and factor-kernel dimensions disagree")
            components.append(CyclicComponent(factor, subspace, projector))
        result = CyclicDecomposition(self, generator, tuple(components))
        if not result.verify():
            raise RepresentationError("cyclic decomposition failed its exact projector checks")
        self._cyclic_cache[generator] = result
        return result

    def _cyclic_generator_order(self, generator: Any) -> int:
        identity = _group_identity(self.group)
        current = identity
        for exponent in range(1, len(self.elements) + 1):
            current = _group_multiply(self.group, current, generator)
            if current == identity:
                return exponent
        raise ValueError("selected cyclic generator does not have finite order in group.elements")

    def weight_spaces(self, generator: Any | None = None) -> WeightDecomposition:
        decomposition = self.cyclic_decomposition(generator)
        if not decomposition.is_split:
            nonsplit = tuple(
                component.factor
                for component in decomposition.components
                if component.factor.degree > 1
            )
            raise NonSplitRepresentationError(
                f"cyclic action has non-linear factors over the base field: {nonsplit!r}"
            )
        return WeightDecomposition(decomposition)

    def projector(
        self,
        target: Character | CyclicFactor | int,
        *,
        generator: Any | None = None,
    ) -> DenseMatrix:
        if isinstance(target, Character):
            return self.character_projector(target)
        decomposition = self.cyclic_decomposition(generator)
        return decomposition[target].projector

    def isotypic(
        self,
        target: Character | CyclicFactor | int,
        *,
        generator: Any | None = None,
    ) -> LinearSubspace:
        return _matrix_image_subspace(self.projector(target, generator=generator))


def representation(
    group: object,
    field: PrimeField | int,
    action: Mapping[Any, MatrixInput] | Callable[[Any], MatrixInput],
    **kwargs: Any,
) -> Representation:
    """Functional constructor for :class:`Representation`."""

    return Representation(group, field, action, **kwargs)


def fixed_part(module: Representation, sigma: Any) -> LinearSubspace:
    return module.fixed_space(sigma)


def weight_spaces(module: Representation, action: Any | None = None) -> WeightDecomposition:
    return module.weight_spaces(action)


def semisimple(action: Representation) -> SemisimplicityResult:
    return action.semisimplicity()


def projector(
    module: Representation,
    character: Character | CyclicFactor | int,
    *,
    generator: Any | None = None,
) -> DenseMatrix:
    return module.projector(character, generator=generator)


def isotypic(
    module: Representation,
    character: Character | CyclicFactor | int,
    *,
    generator: Any | None = None,
) -> LinearSubspace:
    return module.isotypic(character, generator=generator)


def decompose(
    module: Representation,
    group: object | None = None,
    *,
    generator: Any | None = None,
    characters: Iterable[Character] | None = None,
    require_complete: bool = False,
) -> CyclicDecomposition | IsotypicDecomposition:
    if group is not None and group != module.group:
        raise ConcreteEmbeddingError(
            "decomposition group differs from the representation's concrete group"
        )
    if characters is not None:
        return module.isotypic_decomposition(characters, require_complete=require_complete)
    return module.cyclic_decomposition(generator)
