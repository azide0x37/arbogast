"""Normalized bar complexes for finite-group cohomology."""

from __future__ import annotations

import hashlib
import inspect
import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from arbogast.core import canonical_json as _shared_canonical_json

from ._linear import SparseMatrix, compose_is_zero, is_prime


class CohomologyError(Exception):
    """Base exception for exact finite cohomology failures."""


class UnsupportedCoefficientFieldError(CohomologyError):
    """Raised when the coefficient field is not a prime finite field."""


class ComplexityLimitError(CohomologyError):
    """Raised before a normalized bar construction exceeds an explicit limit."""


class InvalidGroupError(CohomologyError):
    """Raised when the supplied finite-group data fail the group axioms."""


class InvalidActionError(CohomologyError):
    """Raised when the supplied matrices do not define a left group action."""


@dataclass(frozen=True, slots=True)
class ComplexityLimits:
    """Fail-closed limits for the pure-Python normalized-bar implementation.

    The limits constrain mathematical dimensions and actual sparse nonzero counts, rather than
    the nominal number of dense matrix cells.  Callers may pass a larger explicit instance when
    they understand the cost.
    """

    max_group_order: int = 128
    max_cochain_dimension: int = 50_000
    max_differential_nonzeros: int = 2_000_000
    max_rref_cells: int = 25_000_000

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")


DEFAULT_LIMITS = ComplexityLimits()


def _call_or_value(value: Any) -> Any:
    # Group elements such as permutations are themselves callable.  Only invoke actual bound
    # methods/functions here; a callable property value remains a mathematical object.
    return (
        value()
        if inspect.ismethod(value) or inspect.isfunction(value) or inspect.isbuiltin(value)
        else value
    )


def _read_attribute(value: Any, names: Sequence[str]) -> Any:
    for name in names:
        if hasattr(value, name):
            return _call_or_value(getattr(value, name))
    raise AttributeError(f"none of {', '.join(names)} is available")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, bytes):
        return {"$arbogast_type": "bytes", "hex": value.hex()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical group-element mapping keys must be strings")
            result[key] = _jsonable(item)
        return result
    for method_name in ("to_canonical_data", "to_canonical"):
        method = getattr(value, method_name, None)
        if callable(method):
            return _jsonable(method())
    if hasattr(value, "canonical_bytes"):
        return {
            "$arbogast_type": "canonical_bytes",
            "hex": bytes(_call_or_value(value.canonical_bytes)).hex(),
        }
    if is_dataclass(value):
        return _jsonable(asdict(value))  # type: ignore[arg-type]
    if hasattr(value, "images"):
        return {"images": _jsonable(_call_or_value(value.images))}
    raise TypeError(
        "group elements need a canonical primitive/dataclass encoding, images, "
        "to_canonical(), or canonical_bytes()"
    )


def _canonical_json(value: Any) -> str:
    return _shared_canonical_json(_jsonable(value))


def _element_identifier(group: Any, element: Any) -> str:
    for name in ("canonical_element_bytes", "encode_element", "element_encoding"):
        if hasattr(group, name):
            encoded = getattr(group, name)(element)
            return _canonical_json(encoded)
    return _canonical_json(element)


def _group_elements(group: Any) -> tuple[Any, ...]:
    try:
        elements = tuple(_read_attribute(group, ("elements", "enumerate_elements")))
    except (AttributeError, TypeError) as error:
        raise TypeError(
            "group must expose a finite elements iterable or elements() method"
        ) from error
    if not elements:
        raise InvalidGroupError("a finite group must contain at least its identity")
    identifiers = [_element_identifier(group, element) for element in elements]
    if len(set(identifiers)) != len(identifiers):
        raise InvalidGroupError("canonical element encodings are not unique")
    return tuple(element for _, element in sorted(zip(identifiers, elements, strict=True)))


def _group_identity(group: Any) -> Any:
    try:
        return _read_attribute(group, ("identity", "one", "identity_element"))
    except AttributeError as error:
        raise TypeError("group must expose identity, one, or identity_element") from error


def _multiply(group: Any, left: Any, right: Any) -> Any:
    for name in ("multiply", "mul", "product"):
        if hasattr(group, name):
            return getattr(group, name)(left, right)
    try:
        return left * right
    except TypeError as error:
        raise TypeError(
            "group must expose multiply(left, right) or element multiplication"
        ) from error


def _element_index(elements: Sequence[Any], element: Any) -> int:
    matches = [index for index, candidate in enumerate(elements) if candidate == element]
    if len(matches) != 1:
        raise InvalidGroupError("a group operation returned an unknown or ambiguous element")
    return matches[0]


def _field_prime(module: Any) -> int:
    field = getattr(module, "field", module)
    candidate: Any | None = None
    for owner in (field, module):
        for name in ("characteristic", "modulus", "prime", "p"):
            if hasattr(owner, name):
                candidate = _call_or_value(getattr(owner, name))
                break
        if candidate is not None:
            break
    if candidate is None and isinstance(field, int):
        candidate = field
    if not isinstance(candidate, int) or not is_prime(candidate):
        raise UnsupportedCoefficientFieldError(
            "normalized-bar cohomology currently requires an explicitly identified prime field"
        )
    for owner in (field, module):
        if hasattr(owner, "order"):
            order = _call_or_value(owner.order)
            if order != candidate:
                raise UnsupportedCoefficientFieldError(
                    "extension fields are not yet supported; the field order must equal "
                    "its characteristic"
                )
            break
    return candidate


def _module_dimension(module: Any) -> int:
    try:
        dimension = _read_attribute(module, ("dimension", "dim"))
    except AttributeError as error:
        raise TypeError("module must expose a positive dimension or dim") from error
    if not isinstance(dimension, int) or dimension <= 0:
        raise ValueError("module dimension must be a positive integer")
    return dimension


def _matrix_rows(matrix: Any) -> tuple[tuple[int, ...], ...]:
    if hasattr(matrix, "to_rows"):
        rows = matrix.to_rows()
    elif hasattr(matrix, "rows"):
        rows = _call_or_value(matrix.rows)
    else:
        rows = matrix
    try:
        return tuple(tuple(int(entry) for entry in row) for row in rows)
    except TypeError as error:
        raise TypeError("action matrix must be an iterable of row iterables") from error


def _action_matrix(module: Any, element: Any) -> Any:
    for name in ("action_matrix", "matrix", "action"):
        if hasattr(module, name):
            operation = getattr(module, name)
            if callable(operation):
                return operation(element)
    matrices = getattr(module, "matrices", None)
    if isinstance(matrices, Mapping):
        try:
            return matrices[element]
        except (KeyError, TypeError):
            pass
    raise TypeError(
        "module must expose action_matrix(element), matrix(element), or action(element)"
    )


def _matrix_product(
    left: Sequence[Sequence[int]], right: Sequence[Sequence[int]], prime: int
) -> tuple[tuple[int, ...], ...]:
    rows = len(left)
    inner = len(right)
    columns = len(right[0]) if right else 0
    if any(len(row) != inner for row in left) or any(len(row) != columns for row in right):
        raise ValueError("matrix product shape mismatch")
    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(inner)) % prime
            for column in range(columns)
        )
        for row in range(rows)
    )


def _validate_snapshot(
    prime: int,
    multiplication_table: Sequence[Sequence[int]],
    identity_index: int,
    action_matrices: Sequence[Sequence[Sequence[int]]],
    module_dimension: int,
) -> None:
    if not is_prime(prime):
        raise UnsupportedCoefficientFieldError("certificate coefficient modulus is not prime")
    order = len(multiplication_table)
    if order == 0 or not 0 <= identity_index < order:
        raise InvalidGroupError("invalid group order or identity index")
    if len(action_matrices) != order:
        raise InvalidActionError("there must be exactly one action matrix per group element")
    for row in multiplication_table:
        if len(row) != order or any(
            not isinstance(value, int) or not 0 <= value < order for value in row
        ):
            raise InvalidGroupError("multiplication table is not a square table of element indices")
    for element in range(order):
        if multiplication_table[identity_index][element] != element:
            raise InvalidGroupError("identity does not act on the left")
        if multiplication_table[element][identity_index] != element:
            raise InvalidGroupError("identity does not act on the right")
        if not any(
            multiplication_table[element][candidate] == identity_index
            and multiplication_table[candidate][element] == identity_index
            for candidate in range(order)
        ):
            raise InvalidGroupError("an element has no two-sided inverse")
    for left in range(order):
        for middle in range(order):
            for right in range(order):
                lhs = multiplication_table[multiplication_table[left][middle]][right]
                rhs = multiplication_table[left][multiplication_table[middle][right]]
                if lhs != rhs:
                    raise InvalidGroupError("multiplication table is not associative")
    if not isinstance(module_dimension, int) or isinstance(module_dimension, bool):
        raise InvalidActionError("module dimension must be an integer")
    if module_dimension < 0:
        raise InvalidActionError("module dimension must be nonnegative")
    identity_matrix = tuple(
        tuple(1 if row == column else 0 for column in range(module_dimension))
        for row in range(module_dimension)
    )
    normalized_actions: list[tuple[tuple[int, ...], ...]] = []
    for matrix in action_matrices:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < prime
            for row in matrix
            for value in row
        ):
            raise InvalidActionError(
                "action matrices must use canonical integer residues in range(prime)"
            )
        normalized = tuple(tuple(value for value in row) for row in matrix)
        if len(normalized) != module_dimension or any(
            len(row) != module_dimension for row in normalized
        ):
            raise InvalidActionError("action matrix has the wrong shape")
        normalized_actions.append(normalized)
    if normalized_actions[identity_index] != identity_matrix:
        raise InvalidActionError("the identity element does not act as the identity matrix")
    for left in range(order):
        for right in range(order):
            product = multiplication_table[left][right]
            composed = _matrix_product(normalized_actions[left], normalized_actions[right], prime)
            if composed != normalized_actions[product]:
                raise InvalidActionError("action matrices do not define a left representation")


def _normalized_tuples(order: int, identity_index: int, degree: int) -> tuple[tuple[int, ...], ...]:
    nonidentity = tuple(index for index in range(order) if index != identity_index)
    if degree == 0:
        return ((),)
    return tuple(itertools.product(nonidentity, repeat=degree))


def _cochain_dimension(order: int, module_dimension: int, degree: int) -> int:
    return int((order - 1) ** degree * module_dimension)


def _bar_differential_from_snapshot(
    prime: int,
    multiplication_table: Sequence[Sequence[int]],
    identity_index: int,
    action_matrices: Sequence[Sequence[Sequence[int]]],
    module_dimension: int,
    degree: int,
) -> SparseMatrix:
    """Construct ``d_degree`` for the normalized inhomogeneous bar complex."""

    order = len(multiplication_table)
    source_tuples = _normalized_tuples(order, identity_index, degree)
    target_tuples = _normalized_tuples(order, identity_index, degree + 1)
    source_index = {arguments: index for index, arguments in enumerate(source_tuples)}
    rows: list[dict[int, int]] = []

    def add(row: dict[int, int], column: int, value: int) -> None:
        replacement = (row.get(column, 0) + value) % prime
        if replacement:
            row[column] = replacement
        else:
            row.pop(column, None)

    for arguments in target_tuples:
        first = arguments[0]
        tail = arguments[1:]
        prefix = arguments[:-1]
        for output_coordinate in range(module_dimension):
            row: dict[int, int] = {}
            input_block = source_index[tail] * module_dimension
            for input_coordinate in range(module_dimension):
                add(
                    row,
                    input_block + input_coordinate,
                    action_matrices[first][output_coordinate][input_coordinate],
                )
            for merge_index in range(degree):
                merged_element = multiplication_table[arguments[merge_index]][
                    arguments[merge_index + 1]
                ]
                if merged_element == identity_index:
                    continue
                merged = (
                    *arguments[:merge_index],
                    merged_element,
                    *arguments[merge_index + 2 :],
                )
                sign = -1 if (merge_index + 1) % 2 else 1
                add(
                    row,
                    source_index[merged] * module_dimension + output_coordinate,
                    sign,
                )
            final_sign = -1 if (degree + 1) % 2 else 1
            add(
                row,
                source_index[prefix] * module_dimension + output_coordinate,
                final_sign,
            )
            rows.append(row)
    return SparseMatrix.from_rows(
        rows,
        _cochain_dimension(order, module_dimension, degree),
        prime,
    )


def _matrix_hash(matrix: SparseMatrix) -> str:
    payload = {
        "nrows": matrix.nrows,
        "ncols": matrix.ncols,
        "prime": matrix.prime,
        "rows": matrix.rows,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _complex_content_hash(
    *,
    prime: int,
    element_ids: Sequence[str],
    identity_index: int,
    multiplication_table: Sequence[Sequence[int]],
    module_dimension: int,
    action_matrices: Sequence[Sequence[Sequence[int]]],
    max_degree: int,
    differential_hashes: Sequence[str],
) -> str:
    payload = {
        "schema": "arbogast.normalized-bar.v1",
        "prime": prime,
        "elements": tuple(element_ids),
        "identity_index": identity_index,
        "multiplication_table": tuple(tuple(row) for row in multiplication_table),
        "module_dimension": module_dimension,
        "action_matrices": tuple(tuple(tuple(row) for row in matrix) for matrix in action_matrices),
        "max_degree": max_degree,
        "differential_hashes": tuple(differential_hashes),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CochainSpace:
    """A normalized cochain space ``C^n(G, M)`` with its canonical basis."""

    complex: CochainComplex
    degree: int

    @property
    def dimension(self) -> int:
        return _cochain_dimension(
            self.complex.group_order, self.complex.module_dimension, self.degree
        )

    @property
    def argument_indices(self) -> tuple[tuple[int, ...], ...]:
        return _normalized_tuples(
            self.complex.group_order, self.complex.identity_index, self.degree
        )

    @property
    def basis_arguments(self) -> tuple[tuple[Any, ...], ...]:
        return tuple(
            tuple(self.complex.elements[index] for index in arguments)
            for arguments in self.argument_indices
        )

    def zero(self) -> Cochain:
        return Cochain(self.complex, self.degree, (0,) * self.dimension)

    def from_values(self, values: Sequence[int]) -> Cochain:
        return Cochain(self.complex, self.degree, tuple(values))

    def from_function(self, function: Callable[..., int | Sequence[int]]) -> Cochain:
        values: list[int] = []
        for arguments in self.basis_arguments:
            result = function(*arguments)
            vector: tuple[int, ...]
            if self.complex.module_dimension == 1 and isinstance(result, int):
                vector = (result,)
            else:
                vector = tuple(result)  # type: ignore[arg-type]
            if len(vector) != self.complex.module_dimension:
                raise ValueError("cochain function returned a vector of the wrong dimension")
            values.extend(vector)
        return self.from_values(values)


@dataclass(frozen=True, slots=True)
class Cochain:
    """An exact normalized cochain represented in the complex's canonical basis."""

    complex: CochainComplex
    degree: int
    values: tuple[int, ...]

    def __post_init__(self) -> None:
        expected = self.complex.space(self.degree).dimension
        if len(self.values) != expected:
            raise ValueError(f"expected {expected} cochain entries, got {len(self.values)}")
        object.__setattr__(
            self, "values", tuple(value % self.complex.prime for value in self.values)
        )

    @property
    def space(self) -> CochainSpace:
        return self.complex.space(self.degree)

    @property
    def content_hash(self) -> str:
        payload = {
            "complex": self.complex.content_hash,
            "degree": self.degree,
            "values": self.values,
        }
        return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

    def __call__(self, *arguments: Any) -> tuple[int, ...]:
        if len(arguments) != self.degree:
            raise ValueError(f"expected {self.degree} group arguments")
        indices = tuple(_element_index(self.complex.elements, element) for element in arguments)
        if self.complex.identity_index in indices:
            return (0,) * self.complex.module_dimension
        block = self.space.argument_indices.index(indices) * self.complex.module_dimension
        return self.values[block : block + self.complex.module_dimension]

    def scalar_value(self, *arguments: Any) -> int:
        if self.complex.module_dimension != 1:
            raise ValueError("scalar_value is defined only for one-dimensional modules")
        return self(*arguments)[0]

    def differential(self) -> Cochain:
        differential = self.complex.differential(self.degree)
        return Cochain(self.complex, self.degree + 1, differential.apply(self.values))

    def __add__(self, other: Cochain) -> Cochain:
        self._require_same_space(other)
        return Cochain(
            self.complex,
            self.degree,
            tuple(a + b for a, b in zip(self.values, other.values, strict=True)),
        )

    def __sub__(self, other: Cochain) -> Cochain:
        self._require_same_space(other)
        return Cochain(
            self.complex,
            self.degree,
            tuple(a - b for a, b in zip(self.values, other.values, strict=True)),
        )

    def __rmul__(self, scalar: int) -> Cochain:
        return Cochain(
            self.complex,
            self.degree,
            tuple(scalar * value for value in self.values),
        )

    def _require_same_space(self, other: Cochain) -> None:
        if self.complex.content_hash != other.complex.content_hash or self.degree != other.degree:
            raise ValueError("cochains belong to different canonical spaces")


@dataclass(frozen=True, slots=True)
class CochainComplex:
    """Finite normalized bar complex through ``max_degree``.

    Spaces through degree ``max_degree + 1`` and differentials ``d_0`` through
    ``d_max_degree`` are available, which is exactly the data needed to compute cohomology
    through the requested degree.
    """

    group: Any
    module: Any
    prime: int
    elements: tuple[Any, ...]
    element_ids: tuple[str, ...]
    identity_index: int
    multiplication_table: tuple[tuple[int, ...], ...]
    module_dimension: int
    action_matrices: tuple[tuple[tuple[int, ...], ...], ...]
    max_degree: int
    differentials: tuple[SparseMatrix, ...]
    differential_hashes: tuple[str, ...]
    content_hash: str
    limits: ComplexityLimits

    @property
    def group_order(self) -> int:
        return len(self.elements)

    def space(self, degree: int) -> CochainSpace:
        if degree < 0 or degree > self.max_degree + 1:
            raise ValueError(
                f"complex contains spaces only in degrees 0 through {self.max_degree + 1}"
            )
        return CochainSpace(self, degree)

    def differential(self, degree: int) -> SparseMatrix:
        if degree < 0 or degree > self.max_degree:
            raise ValueError(f"complex contains differentials only through d_{self.max_degree}")
        return self.differentials[degree]

    def cochain(self, degree: int, values: Sequence[int]) -> Cochain:
        return self.space(degree).from_values(values)

    def verify(self) -> bool:
        fresh_element_ids = tuple(
            _element_identifier(self.group, element) for element in self.elements
        )
        if fresh_element_ids != self.element_ids:
            raise CohomologyError(
                "stored element identifiers do not match the concrete group elements"
            )
        _validate_snapshot(
            self.prime,
            self.multiplication_table,
            self.identity_index,
            self.action_matrices,
            self.module_dimension,
        )
        rebuilt = tuple(
            _bar_differential_from_snapshot(
                self.prime,
                self.multiplication_table,
                self.identity_index,
                self.action_matrices,
                self.module_dimension,
                degree,
            )
            for degree in range(self.max_degree + 1)
        )
        if rebuilt != self.differentials:
            raise CohomologyError(
                "stored differentials do not match a fresh normalized-bar construction"
            )
        fresh_hashes = tuple(_matrix_hash(matrix) for matrix in rebuilt)
        if fresh_hashes != self.differential_hashes:
            raise CohomologyError(
                "stored differential hashes do not match a fresh bar construction"
            )
        for degree in range(1, len(rebuilt)):
            if not compose_is_zero(rebuilt[degree], rebuilt[degree - 1]):
                raise CohomologyError(f"bar differentials fail d_{degree} d_{degree - 1} = 0")
        fresh_content_hash = _complex_content_hash(
            prime=self.prime,
            element_ids=self.element_ids,
            identity_index=self.identity_index,
            multiplication_table=self.multiplication_table,
            module_dimension=self.module_dimension,
            action_matrices=self.action_matrices,
            max_degree=self.max_degree,
            differential_hashes=self.differential_hashes,
        )
        if fresh_content_hash != self.content_hash:
            raise CohomologyError("stored complex content hash does not match its finite snapshot")
        return True


def cochain_complex(
    group: Any,
    module: Any,
    degree: int,
    *,
    limits: ComplexityLimits | None = None,
) -> CochainComplex:
    """Construct the exact normalized bar complex through a requested degree.

    ``group`` is intentionally duck typed: it must enumerate its elements and expose identity
    and multiplication.  ``module`` must expose a prime field, dimension, and action matrices.
    No backend-specific objects enter the resulting certificate boundary.
    """

    if not isinstance(degree, int) or degree < 0:
        raise ValueError("degree must be a nonnegative integer")
    selected_limits = limits or DEFAULT_LIMITS
    elements = _group_elements(group)
    order = len(elements)
    if order > selected_limits.max_group_order:
        raise ComplexityLimitError(
            f"group order {order} exceeds max_group_order={selected_limits.max_group_order}"
        )
    element_ids = tuple(_element_identifier(group, element) for element in elements)
    identity = _group_identity(group)
    identity_index = _element_index(elements, identity)
    multiplication_table = tuple(
        tuple(_element_index(elements, _multiply(group, left, right)) for right in elements)
        for left in elements
    )
    prime = _field_prime(module)
    module_dimension = _module_dimension(module)
    action_matrices = tuple(
        tuple(
            tuple(value % prime for value in row)
            for row in _matrix_rows(_action_matrix(module, element))
        )
        for element in elements
    )
    _validate_snapshot(
        prime,
        multiplication_table,
        identity_index,
        action_matrices,
        module_dimension,
    )
    for cochain_degree in range(degree + 2):
        dimension = _cochain_dimension(order, module_dimension, cochain_degree)
        if dimension > selected_limits.max_cochain_dimension:
            raise ComplexityLimitError(
                f"C^{cochain_degree} has dimension {dimension}, exceeding "
                f"max_cochain_dimension={selected_limits.max_cochain_dimension}"
            )
    differentials: list[SparseMatrix] = []
    for differential_degree in range(degree + 1):
        source_dimension = _cochain_dimension(order, module_dimension, differential_degree)
        target_dimension = _cochain_dimension(order, module_dimension, differential_degree + 1)
        if source_dimension * target_dimension > selected_limits.max_rref_cells:
            raise ComplexityLimitError(
                f"d_{differential_degree} has nominal shape {target_dimension}x{source_dimension}, "
                f"exceeding max_rref_cells={selected_limits.max_rref_cells}"
            )
        differential = _bar_differential_from_snapshot(
            prime,
            multiplication_table,
            identity_index,
            action_matrices,
            module_dimension,
            differential_degree,
        )
        if differential.nnz > selected_limits.max_differential_nonzeros:
            raise ComplexityLimitError(
                f"d_{differential_degree} has {differential.nnz} nonzeros, exceeding "
                f"max_differential_nonzeros={selected_limits.max_differential_nonzeros}"
            )
        differentials.append(differential)
    differential_hashes = tuple(_matrix_hash(matrix) for matrix in differentials)
    content_hash = _complex_content_hash(
        prime=prime,
        element_ids=element_ids,
        identity_index=identity_index,
        multiplication_table=multiplication_table,
        module_dimension=module_dimension,
        action_matrices=action_matrices,
        max_degree=degree,
        differential_hashes=differential_hashes,
    )
    complex_ = CochainComplex(
        group=group,
        module=module,
        prime=prime,
        elements=elements,
        element_ids=element_ids,
        identity_index=identity_index,
        multiplication_table=multiplication_table,
        module_dimension=module_dimension,
        action_matrices=action_matrices,
        max_degree=degree,
        differentials=tuple(differentials),
        differential_hashes=differential_hashes,
        content_hash=content_hash,
        limits=selected_limits,
    )
    complex_.verify()
    return complex_


__all__ = [
    "DEFAULT_LIMITS",
    "Cochain",
    "CochainComplex",
    "CochainSpace",
    "CohomologyError",
    "ComplexityLimitError",
    "ComplexityLimits",
    "InvalidActionError",
    "InvalidGroupError",
    "UnsupportedCoefficientFieldError",
    "cochain_complex",
]
