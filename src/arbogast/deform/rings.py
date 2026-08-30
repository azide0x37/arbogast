"""Finite local Artin algebras and exact small extensions.

The bounded deformation core represents an Artin ring as a pinned finite
dimensional algebra over a prime field.  If ``e_0, ..., e_(n-1)`` is the pinned
basis, then ``structure_constants[i][j][k]`` is the coefficient of ``e_k`` in
``e_i * e_j``.  Ring-map matrices act on coordinate columns: a map from an
``n``-dimensional ring to an ``m``-dimensional ring is an ``m``-by-``n``
matrix, and column ``j`` is the image of ``e_j``.

Construction fails closed unless all advertised algebra, augmentation,
locality, map, and exact-sequence laws hold.  Maximal-ideal powers are retained
as deterministic RREF bases, so nilpotence is an explicit replayable witness
rather than an unchecked flag.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TypeAlias

from arbogast.core import CanonicalJSON, ValidationError, VerificationError
from arbogast.formats import (
    DEFORM_ARTIN_RING_ELEMENT_SCHEMA_V1,
    DEFORM_ARTIN_RING_MAP_SCHEMA_V1,
    DEFORM_ARTIN_RING_SCHEMA_V1,
    DEFORM_SMALL_EXTENSION_SCHEMA_V1,
)
from arbogast.linalg import (
    DenseMatrix,
    LinearSubspace,
    PrimeField,
    PrimeFieldElement,
    Scalar,
    nullspace,
)
from arbogast.linalg import image as matrix_image

from ._schema import (
    MAX_DIMENSION,
    MAX_TENSOR_CELLS,
    DeformationSchemaObject,
    DeformationSemanticObject,
    _canonical_prime_field,
)

Vector: TypeAlias = tuple[int, ...]
StructureConstants: TypeAlias = tuple[tuple[Vector, ...], ...]
PowerBasis: TypeAlias = LinearSubspace | Iterable[Iterable[Scalar]]


def _vector(
    field: PrimeField,
    values: Iterable[Scalar],
    length: int,
    name: str,
) -> Vector:
    result = tuple(field.residue(value) for value in values)
    if len(result) != length:
        raise ValidationError(f"{name} has length {len(result)}, expected {length}")
    return result


def _structure_constants(
    field: PrimeField,
    values: Iterable[Iterable[Iterable[Scalar]]],
) -> StructureConstants:
    materialized = tuple(
        tuple(tuple(field.residue(value) for value in product) for product in row) for row in values
    )
    dimension = len(materialized)
    if dimension == 0:
        raise ValidationError("an Artin ring must have positive vector-space dimension")
    if any(len(row) != dimension for row in materialized):
        raise ValidationError("structure constants must have shape n by n by n")
    if any(len(product) != dimension for row in materialized for product in row):
        raise ValidationError("structure constants must have shape n by n by n")
    return materialized


def _names(values: Iterable[str] | None, dimension: int) -> tuple[str, ...]:
    if values is None:
        return tuple(f"e{index}" for index in range(dimension))
    if isinstance(values, (str, bytes, bytearray)):
        raise TypeError("basis_names must be an iterable of strings")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError("basis_names must contain strings")
        normalized = unicodedata.normalize("NFC", value)
        if not normalized.strip():
            raise ValidationError("basis names must be non-blank")
        result.append(normalized)
    if len(result) != dimension:
        raise ValidationError(f"basis_names has length {len(result)}, expected {dimension}")
    if len(set(result)) != len(result):
        raise ValidationError("basis names must be distinct after Unicode normalization")
    return tuple(result)


def _multiply_vectors(
    structure_constants: StructureConstants,
    left: Sequence[int],
    right: Sequence[int],
    modulus: int,
) -> Vector:
    dimension = len(structure_constants)
    result = [0] * dimension
    for left_index, left_value in enumerate(left):
        if left_value == 0:
            continue
        for right_index, right_value in enumerate(right):
            if right_value == 0:
                continue
            coefficient = left_value * right_value
            product = structure_constants[left_index][right_index]
            for output_index, structure_coefficient in enumerate(product):
                result[output_index] = (
                    result[output_index] + coefficient * structure_coefficient
                ) % modulus
    return tuple(result)


def _residue_value(residue: Sequence[int], vector: Sequence[int], modulus: int) -> int:
    return (
        sum(coefficient * value for coefficient, value in zip(residue, vector, strict=True))
        % modulus
    )


def _subspace_product(
    field: PrimeField,
    dimension: int,
    structure_constants: StructureConstants,
    left: LinearSubspace,
    right: LinearSubspace,
) -> LinearSubspace:
    return LinearSubspace(
        field,
        dimension,
        (
            _multiply_vectors(structure_constants, left_vector, right_vector, field.p)
            for left_vector in left.basis
            for right_vector in right.basis
        ),
    )


def _verify_algebra_laws(
    field: PrimeField,
    structure_constants: StructureConstants,
    unit: Vector,
    residue: Vector,
) -> None:
    dimension = len(structure_constants)
    modulus = field.p

    for left in range(dimension):
        for right in range(dimension):
            if structure_constants[left][right] != structure_constants[right][left]:
                raise ValidationError("structure constants do not define a commutative algebra")

    for basis_index in range(dimension):
        expected = tuple(1 if output == basis_index else 0 for output in range(dimension))
        basis_vector = expected
        if (
            _multiply_vectors(structure_constants, unit, basis_vector, modulus) != expected
            or _multiply_vectors(structure_constants, basis_vector, unit, modulus) != expected
        ):
            raise ValidationError("unit coordinates do not define a two-sided identity")

    for left in range(dimension):
        for middle in range(dimension):
            left_middle = structure_constants[left][middle]
            for right in range(dimension):
                middle_right = structure_constants[middle][right]
                for output in range(dimension):
                    left_associated = (
                        sum(
                            left_middle[index] * structure_constants[index][right][output]
                            for index in range(dimension)
                        )
                        % modulus
                    )
                    right_associated = (
                        sum(
                            middle_right[index] * structure_constants[left][index][output]
                            for index in range(dimension)
                        )
                        % modulus
                    )
                    if left_associated != right_associated:
                        raise ValidationError(
                            "structure constants do not define an associative algebra"
                        )

    if _residue_value(residue, unit, modulus) != 1:
        raise ValidationError("residue map does not send the ring unit to one")
    for left in range(dimension):
        for right in range(dimension):
            product_residue = _residue_value(
                residue,
                structure_constants[left][right],
                modulus,
            )
            if product_residue != residue[left] * residue[right] % modulus:
                raise ValidationError("residue coordinates do not define an algebra homomorphism")


def _computed_maximal_ideal_powers(
    field: PrimeField,
    structure_constants: StructureConstants,
    residue: Vector,
) -> tuple[LinearSubspace, ...]:
    dimension = len(structure_constants)
    maximal_ideal = nullspace(DenseMatrix(field, (residue,), ncols=dimension))
    powers = [maximal_ideal]
    current = maximal_ideal
    while current.dimension:
        following = _subspace_product(
            field,
            dimension,
            structure_constants,
            current,
            maximal_ideal,
        )
        if not following.is_subspace_of(current):
            raise ValidationError("computed maximal-ideal powers are not descending ideals")
        if following == current:
            raise ValidationError(
                "the residue kernel is not nilpotent, so the algebra is not local"
            )
        powers.append(following)
        current = following
        if len(powers) > dimension + 1:
            raise ValidationError("maximal-ideal nilpotence exceeded the dimension bound")
    return tuple(powers)


def _normalize_power_witness(
    field: PrimeField,
    dimension: int,
    values: Iterable[PowerBasis],
) -> tuple[LinearSubspace, ...]:
    result: list[LinearSubspace] = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, LinearSubspace):
            if value.field != field or value.ambient_dimension != dimension:
                raise ValidationError(
                    f"maximal-ideal power {index} belongs to a different ambient space"
                )
            result.append(LinearSubspace(field, dimension, value.basis))
            continue
        result.append(
            LinearSubspace(
                field,
                dimension,
                value,
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True, init=False)
class ArtinRing(DeformationSemanticObject):
    """A pinned finite commutative local Artin algebra over ``GF(p)``.

    ``maximal_ideal_powers`` may be omitted, in which case the exact powers are
    computed.  If supplied, it must equal the deterministic sequence
    ``m, m^2, ..., 0`` after canonical RREF normalization.
    """

    field: PrimeField
    structure_constants: StructureConstants
    unit: Vector
    residue: Vector
    basis_names: tuple[str, ...]
    maximal_ideal_powers: tuple[LinearSubspace, ...]

    schema_version = DEFORM_ARTIN_RING_SCHEMA_V1

    def __init__(
        self,
        field: PrimeField,
        structure_constants: Iterable[Iterable[Iterable[Scalar]]],
        unit: Iterable[Scalar],
        residue: Iterable[Scalar],
        *,
        basis_names: Iterable[str] | None = None,
        maximal_ideal_powers: Iterable[PowerBasis] | None = None,
    ) -> None:
        if not isinstance(field, PrimeField):
            raise TypeError("field must be a PrimeField")
        if not _canonical_prime_field(field):
            raise ValidationError("Artin-ring coefficient field is outside the portable boundary")
        constants = _structure_constants(field, structure_constants)
        dimension = len(constants)
        if dimension > MAX_DIMENSION or dimension**3 > MAX_TENSOR_CELLS:
            raise ValidationError("Artin-ring structure tensor exceeds the portable boundary")
        unit_vector = _vector(field, unit, dimension, "unit")
        residue_vector = _vector(field, residue, dimension, "residue")
        normalized_names = _names(basis_names, dimension)
        _verify_algebra_laws(field, constants, unit_vector, residue_vector)
        computed_powers = _computed_maximal_ideal_powers(field, constants, residue_vector)
        if maximal_ideal_powers is None:
            powers = computed_powers
        else:
            powers = _normalize_power_witness(field, dimension, maximal_ideal_powers)
            if powers != computed_powers:
                raise ValidationError(
                    "maximal_ideal_powers is not the exact sequence m, m^2, ..., 0"
                )
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "structure_constants", constants)
        object.__setattr__(self, "unit", unit_vector)
        object.__setattr__(self, "residue", residue_vector)
        object.__setattr__(self, "basis_names", normalized_names)
        object.__setattr__(self, "maximal_ideal_powers", powers)

    @property
    def dimension(self) -> int:
        """Return the dimension over the residue field."""

        return len(self.structure_constants)

    @property
    def prime(self) -> int:
        """Return the residue characteristic."""

        return self.field.p

    @property
    def residue_field(self) -> PrimeField:
        """Return the pinned residue field."""

        return self.field

    @property
    def cardinality(self) -> int:
        """Return the exact number of elements."""

        prime: int = self.field.p
        dimension: int = self.dimension
        result = 1
        for _ in range(dimension):
            result *= prime
        return result

    @property
    def maximal_ideal(self) -> LinearSubspace:
        """Return ``ker(residue)`` with its canonical RREF basis."""

        return self.maximal_ideal_powers[0]

    @property
    def maximal_ideal_basis(self) -> tuple[Vector, ...]:
        """Return the canonical coordinate basis of the maximal ideal."""

        return self.maximal_ideal.basis

    @property
    def nilpotence_index(self) -> int:
        """Return the least positive ``N`` with ``m^N = 0``."""

        return len(self.maximal_ideal_powers)

    @property
    def is_local(self) -> bool:
        """Return ``True``; locality is established during construction."""

        return True

    @property
    def zero(self) -> ArtinRingElement:
        """Return the additive identity."""

        return ArtinRingElement(self, (0,) * self.dimension)

    @property
    def one(self) -> ArtinRingElement:
        """Return the multiplicative identity."""

        return ArtinRingElement(self, self.unit)

    @property
    def basis(self) -> tuple[ArtinRingElement, ...]:
        """Return the pinned coordinate basis as ring elements."""

        return tuple(self.basis_element(index) for index in range(self.dimension))

    def basis_element(self, index: int) -> ArtinRingElement:
        """Return one pinned basis element."""

        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("basis index must be an integer")
        if not 0 <= index < self.dimension:
            raise IndexError("basis index out of range")
        return ArtinRingElement(
            self,
            tuple(1 if coordinate == index else 0 for coordinate in range(self.dimension)),
        )

    def element(
        self,
        value: ArtinRingElement | PrimeFieldElement | int | Iterable[Scalar],
    ) -> ArtinRingElement:
        """Coerce coordinates, a residue-field scalar, or a same-ring element."""

        if isinstance(value, ArtinRingElement):
            if value.ring != self:
                raise ValidationError("element belongs to a different Artin ring")
            return value
        if isinstance(value, (int, PrimeFieldElement)):
            scalar = self.field.residue(value)
            return ArtinRingElement(
                self,
                tuple(scalar * coordinate % self.field.p for coordinate in self.unit),
            )
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Iterable):
            raise TypeError("ring element must be a scalar or an iterable of coordinates")
        return ArtinRingElement(self, value)

    def multiply_coordinates(
        self,
        left: Iterable[Scalar],
        right: Iterable[Scalar],
    ) -> Vector:
        """Multiply two coordinate vectors exactly."""

        left_vector = _vector(self.field, left, self.dimension, "left coordinates")
        right_vector = _vector(self.field, right, self.dimension, "right coordinates")
        return _multiply_vectors(
            self.structure_constants,
            left_vector,
            right_vector,
            self.field.p,
        )

    def residue_of(
        self,
        value: ArtinRingElement | PrimeFieldElement | int | Iterable[Scalar],
    ) -> PrimeFieldElement:
        """Apply the exact residue homomorphism."""

        element = self.element(value)
        return self.field(_residue_value(self.residue, element.coordinates, self.field.p))

    def maximal_ideal_power(self, exponent: int) -> LinearSubspace:
        """Return ``m^exponent``; exponent zero denotes the whole ring."""

        if isinstance(exponent, bool) or not isinstance(exponent, int):
            raise TypeError("exponent must be an integer")
        if exponent < 0:
            raise ValidationError("maximal-ideal powers require a nonnegative exponent")
        if exponent == 0:
            return LinearSubspace.full(self.field, self.dimension)
        if exponent > self.nilpotence_index:
            return LinearSubspace.zero(self.field, self.dimension)
        return self.maximal_ideal_powers[exponent - 1]

    @property
    def ring_id(self) -> str:
        """Return the canonical content identity."""

        return self.content_id

    def verify(self) -> bool:
        """Replay all algebra, residue, and nilpotence checks exactly."""

        if not _canonical_prime_field(self.field):
            raise VerificationError("Artin ring coefficient field is not canonical")
        try:
            rebuilt = ArtinRing(
                self.field,
                self.structure_constants,
                self.unit,
                self.residue,
                basis_names=self.basis_names,
                maximal_ideal_powers=self.maximal_ideal_powers,
            )
        except (TypeError, ValueError) as exc:
            raise VerificationError(f"Artin ring verification failed: {exc}") from exc
        if rebuilt.to_canonical_data() != self.to_canonical_data():
            raise VerificationError("Artin ring canonical snapshot failed exact replay")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        """Return the complete finite local-algebra presentation."""

        return {
            "basis_names": list(self.basis_names),
            "dimension": self.dimension,
            "field": self.field.to_canonical_data(),
            "maximal_ideal_powers": [
                [list(vector) for vector in power.basis] for power in self.maximal_ideal_powers
            ],
            "residue": list(self.residue),
            "structure_constants": [
                [list(product) for product in row] for row in self.structure_constants
            ],
            "type": "arbogast.deform.artin_ring",
            "unit": list(self.unit),
        }


@dataclass(frozen=True, slots=True, init=False)
class ArtinRingElement(DeformationSchemaObject):
    """An immutable element in pinned Artin-ring coordinates."""

    ring: ArtinRing
    coordinates: Vector

    schema_version = DEFORM_ARTIN_RING_ELEMENT_SCHEMA_V1

    def __init__(self, ring: ArtinRing, coordinates: Iterable[Scalar]) -> None:
        if not isinstance(ring, ArtinRing):
            raise TypeError("ring must be an ArtinRing")
        normalized = _vector(ring.field, coordinates, ring.dimension, "coordinates")
        object.__setattr__(self, "ring", ring)
        object.__setattr__(self, "coordinates", normalized)

    @property
    def is_zero(self) -> bool:
        return not any(self.coordinates)

    @property
    def is_unit(self) -> bool:
        """Return whether the element is invertible in the local ring."""

        return bool(self.residue)

    @property
    def residue(self) -> PrimeFieldElement:
        """Return the image in the residue field."""

        return self.ring.residue_of(self)

    def _coerce(self, other: ArtinRingElement | PrimeFieldElement | int) -> ArtinRingElement:
        return self.ring.element(other)

    def __add__(
        self,
        other: ArtinRingElement | PrimeFieldElement | int,
    ) -> ArtinRingElement:
        right = self._coerce(other)
        modulus = self.ring.field.p
        return ArtinRingElement(
            self.ring,
            tuple(
                (left_value + right_value) % modulus
                for left_value, right_value in zip(
                    self.coordinates,
                    right.coordinates,
                    strict=True,
                )
            ),
        )

    def __radd__(
        self,
        other: ArtinRingElement | PrimeFieldElement | int,
    ) -> ArtinRingElement:
        return self + other

    def __sub__(
        self,
        other: ArtinRingElement | PrimeFieldElement | int,
    ) -> ArtinRingElement:
        right = self._coerce(other)
        modulus = self.ring.field.p
        return ArtinRingElement(
            self.ring,
            tuple(
                (left_value - right_value) % modulus
                for left_value, right_value in zip(
                    self.coordinates,
                    right.coordinates,
                    strict=True,
                )
            ),
        )

    def __rsub__(
        self,
        other: ArtinRingElement | PrimeFieldElement | int,
    ) -> ArtinRingElement:
        return self._coerce(other) - self

    def __neg__(self) -> ArtinRingElement:
        return ArtinRingElement(self.ring, tuple(-value for value in self.coordinates))

    def __mul__(
        self,
        other: ArtinRingElement | PrimeFieldElement | int,
    ) -> ArtinRingElement:
        right = self._coerce(other)
        return ArtinRingElement(
            self.ring,
            _multiply_vectors(
                self.ring.structure_constants,
                self.coordinates,
                right.coordinates,
                self.ring.field.p,
            ),
        )

    def __rmul__(
        self,
        other: ArtinRingElement | PrimeFieldElement | int,
    ) -> ArtinRingElement:
        return self * other

    def inverse(self) -> ArtinRingElement:
        """Return the inverse of a unit by a finite nilpotent geometric series."""

        if not self.is_unit:
            raise ZeroDivisionError("a nonunit Artin-ring element has no inverse")
        inverse_residue = self.residue.inverse()
        nilpotent_part = self * inverse_residue - self.ring.one
        total = self.ring.one
        term = self.ring.one
        for _ in range(1, self.ring.nilpotence_index):
            term = -(term * nilpotent_part)
            total = total + term
        candidate = total * inverse_residue
        if self * candidate != self.ring.one:
            raise VerificationError("internal Artin-ring inverse witness failed exact verification")
        return candidate

    def __truediv__(
        self,
        other: ArtinRingElement | PrimeFieldElement | int,
    ) -> ArtinRingElement:
        return self * self._coerce(other).inverse()

    def __rtruediv__(
        self,
        other: ArtinRingElement | PrimeFieldElement | int,
    ) -> ArtinRingElement:
        return self._coerce(other) * self.inverse()

    def __pow__(self, exponent: int) -> ArtinRingElement:
        if isinstance(exponent, bool) or not isinstance(exponent, int):
            raise TypeError("exponent must be an integer")
        if exponent < 0:
            return self.inverse() ** (-exponent)
        result = self.ring.one
        factor = self
        remaining = exponent
        while remaining:
            if remaining & 1:
                result = result * factor
            factor = factor * factor
            remaining >>= 1
        return result

    @property
    def element_id(self) -> str:
        return self.content_id

    def verify(self) -> bool:
        """Verify the ring binding and canonical coordinate residues."""

        try:
            self.ring.verify()
            rebuilt = ArtinRingElement(self.ring, self.coordinates)
        except (TypeError, ValueError) as exc:
            raise VerificationError(f"Artin ring element verification failed: {exc}") from exc
        if rebuilt.to_canonical_data() != self.to_canonical_data():
            raise VerificationError("Artin ring element canonical snapshot failed exact replay")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "coordinates": list(self.coordinates),
            "ring_id": self.ring.content_id,
            "type": "arbogast.deform.artin_ring_element",
        }


def _map_matrix(
    domain: ArtinRing,
    codomain: ArtinRing,
    value: DenseMatrix | Iterable[Iterable[Scalar]],
) -> DenseMatrix:
    if isinstance(value, DenseMatrix):
        if value.field != domain.field:
            raise ValidationError("ring-map matrix has a different coefficient field")
        result = DenseMatrix(value.field, value.rows, ncols=value.ncols)
    else:
        result = DenseMatrix(domain.field, value, ncols=domain.dimension)
    expected = (codomain.dimension, domain.dimension)
    if result.shape != expected:
        raise ValidationError(f"ring-map matrix has shape {result.shape}, expected {expected}")
    return result


def _verify_map_laws(domain: ArtinRing, codomain: ArtinRing, matrix: DenseMatrix) -> None:
    if domain.field != codomain.field:
        raise ValidationError("an Artin-ring map must be linear over the same prime field")
    if matrix.matvec(domain.unit) != codomain.unit:
        raise ValidationError("Artin-ring map does not preserve the unit")

    modulus = domain.field.p
    for basis_index in range(domain.dimension):
        image_vector = matrix.column(basis_index)
        if _residue_value(codomain.residue, image_vector, modulus) != domain.residue[basis_index]:
            raise ValidationError("Artin-ring map does not commute with residue maps")

    for left in range(domain.dimension):
        left_image = matrix.column(left)
        for right in range(domain.dimension):
            source_product = domain.structure_constants[left][right]
            mapped_product = matrix.matvec(source_product)
            image_product = _multiply_vectors(
                codomain.structure_constants,
                left_image,
                matrix.column(right),
                modulus,
            )
            if mapped_product != image_product:
                raise ValidationError("Artin-ring map does not preserve multiplication")


@dataclass(frozen=True, slots=True, init=False)
class ArtinRingMap(DeformationSemanticObject):
    """An exact residue-compatible homomorphism of pinned Artin rings.

    The stored matrix has ``codomain.dimension`` rows and ``domain.dimension``
    columns and acts on coordinate columns.
    """

    domain: ArtinRing
    codomain: ArtinRing
    matrix: DenseMatrix

    schema_version = DEFORM_ARTIN_RING_MAP_SCHEMA_V1

    def __init__(
        self,
        domain: ArtinRing,
        codomain: ArtinRing,
        matrix: DenseMatrix | Iterable[Iterable[Scalar]],
    ) -> None:
        if not isinstance(domain, ArtinRing) or not isinstance(codomain, ArtinRing):
            raise TypeError("domain and codomain must be ArtinRing instances")
        normalized = _map_matrix(domain, codomain, matrix)
        _verify_map_laws(domain, codomain, normalized)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "codomain", codomain)
        object.__setattr__(self, "matrix", normalized)

    @property
    def kernel(self) -> LinearSubspace:
        """Return the canonical coordinate kernel in the domain."""

        return nullspace(self.matrix)

    @property
    def image(self) -> LinearSubspace:
        """Return the canonical coordinate image in the codomain."""

        return matrix_image(self.matrix)

    @property
    def rank(self) -> int:
        return self.image.dimension

    @property
    def is_surjective(self) -> bool:
        return self.rank == self.codomain.dimension

    @property
    def is_injective(self) -> bool:
        return self.kernel.dimension == 0

    @property
    def surjective(self) -> bool:
        """Compatibility alias for :attr:`is_surjective`."""

        return self.is_surjective

    @property
    def injective(self) -> bool:
        """Compatibility alias for :attr:`is_injective`."""

        return self.is_injective

    def apply(
        self,
        value: ArtinRingElement | PrimeFieldElement | int | Iterable[Scalar],
    ) -> ArtinRingElement:
        """Apply the homomorphism to a domain element."""

        source = self.domain.element(value)
        return self.codomain.element(self.matrix.matvec(source.coordinates))

    __call__ = apply

    def compose(self, other: ArtinRingMap) -> ArtinRingMap:
        """Return ``self o other`` with exact ring-boundary checks."""

        if other.codomain != self.domain:
            raise ValidationError("Artin-ring maps cannot compose across different pinned rings")
        return ArtinRingMap(other.domain, self.codomain, self.matrix @ other.matrix)

    @property
    def map_id(self) -> str:
        return self.content_id

    def verify(self) -> bool:
        """Replay the algebra, unit, and residue compatibility checks."""

        try:
            self.domain.verify()
            self.codomain.verify()
            rebuilt = ArtinRingMap(self.domain, self.codomain, self.matrix)
        except (TypeError, ValueError) as exc:
            raise VerificationError(f"Artin ring map verification failed: {exc}") from exc
        if rebuilt.to_canonical_data() != self.to_canonical_data():
            raise VerificationError("Artin ring map canonical snapshot failed exact replay")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "codomain_id": self.codomain.content_id,
            "domain_id": self.domain.content_id,
            "matrix": [list(row) for row in self.matrix.rows],
            "type": "arbogast.deform.artin_ring_map",
        }


def _kernel_space(
    projection: ArtinRingMap,
    kernel_basis: LinearSubspace | Iterable[Iterable[Scalar]],
) -> LinearSubspace:
    if isinstance(kernel_basis, LinearSubspace):
        if (
            kernel_basis.field != projection.domain.field
            or kernel_basis.ambient_dimension != projection.domain.dimension
        ):
            raise ValidationError("small-extension kernel basis belongs to a different space")
        return LinearSubspace(
            projection.domain.field,
            projection.domain.dimension,
            kernel_basis.basis,
        )
    raw = tuple(
        _vector(
            projection.domain.field,
            vector,
            projection.domain.dimension,
            "kernel basis vector",
        )
        for vector in kernel_basis
    )
    result = LinearSubspace(projection.domain.field, projection.domain.dimension, raw)
    if result.dimension != len(raw):
        raise ValidationError("small-extension kernel_basis must be linearly independent")
    return result


def _inclusion_matrix(
    projection: ArtinRingMap,
    kernel: LinearSubspace,
    inclusion: DenseMatrix | Iterable[Iterable[Scalar]] | None,
) -> DenseMatrix:
    expected = DenseMatrix.from_columns(
        projection.domain.field,
        kernel.basis,
        nrows=projection.domain.dimension,
    )
    if inclusion is None:
        return expected
    if isinstance(inclusion, DenseMatrix):
        if inclusion.field != projection.domain.field:
            raise ValidationError("small-extension inclusion has a different coefficient field")
        normalized = DenseMatrix(inclusion.field, inclusion.rows, ncols=inclusion.ncols)
    else:
        normalized = DenseMatrix(
            projection.domain.field,
            inclusion,
            ncols=kernel.dimension,
        )
    if normalized.shape != expected.shape:
        raise ValidationError(
            f"small-extension inclusion has shape {normalized.shape}, expected {expected.shape}"
        )
    if normalized != expected:
        raise ValidationError(
            "small-extension inclusion columns must be the canonical kernel_basis"
        )
    return normalized


@dataclass(frozen=True, slots=True, init=False)
class SmallExtension(DeformationSemanticObject):
    """A surjective Artin-ring map with an explicit small kernel.

    ``inclusion`` is a ``domain.dimension``-by-``kernel_dimension`` linear map;
    its columns are the canonical ``kernel_basis`` vectors.  Thus its image is
    exactly the kernel of ``projection`` and ``projection @ inclusion = 0``.
    Every element of the source maximal ideal annihilates the kernel.  This is
    the replayed small-extension condition; the kernel may have dimension
    greater than one, with one-dimensional correction charts treated as a
    stricter lifting boundary by :class:`~arbogast.deform.lifting.LiftDatum`.
    """

    projection: ArtinRingMap
    kernel_basis: tuple[Vector, ...]
    inclusion: DenseMatrix

    schema_version = DEFORM_SMALL_EXTENSION_SCHEMA_V1

    def __init__(
        self,
        projection: ArtinRingMap,
        kernel_basis: LinearSubspace | Iterable[Iterable[Scalar]],
        inclusion: DenseMatrix | Iterable[Iterable[Scalar]] | None = None,
    ) -> None:
        if not isinstance(projection, ArtinRingMap):
            raise TypeError("projection must be an ArtinRingMap")
        if not projection.is_surjective:
            raise ValidationError("a small-extension projection must be surjective")
        stated_kernel = _kernel_space(projection, kernel_basis)
        actual_kernel = projection.kernel
        if stated_kernel != actual_kernel:
            raise ValidationError("kernel_basis does not span the exact projection kernel")
        for left in stated_kernel.basis:
            for right in stated_kernel.basis:
                if any(projection.domain.multiply_coordinates(left, right)):
                    raise ValidationError("small-extension kernel is not square-zero")
        for maximal_ideal_vector in projection.domain.maximal_ideal_basis:
            for kernel_vector in stated_kernel.basis:
                if any(
                    projection.domain.multiply_coordinates(
                        maximal_ideal_vector,
                        kernel_vector,
                    )
                ):
                    raise ValidationError(
                        "small-extension kernel is not annihilated by the maximal ideal"
                    )
        normalized_inclusion = _inclusion_matrix(projection, stated_kernel, inclusion)
        if any(
            entry
            for column in normalized_inclusion.columns
            for entry in projection.matrix.matvec(column)
        ):
            raise ValidationError("projection composed with kernel inclusion is nonzero")
        object.__setattr__(self, "projection", projection)
        object.__setattr__(self, "kernel_basis", stated_kernel.basis)
        object.__setattr__(self, "inclusion", normalized_inclusion)

    @property
    def domain(self) -> ArtinRing:
        """Return the total/source ring."""

        return self.projection.domain

    @property
    def codomain(self) -> ArtinRing:
        """Return the quotient/target ring."""

        return self.projection.codomain

    @property
    def total_ring(self) -> ArtinRing:
        return self.domain

    @property
    def quotient_ring(self) -> ArtinRing:
        return self.codomain

    @property
    def kernel(self) -> LinearSubspace:
        """Return the explicit kernel as a canonical subspace."""

        return LinearSubspace(self.domain.field, self.domain.dimension, self.kernel_basis)

    @property
    def kernel_dimension(self) -> int:
        return len(self.kernel_basis)

    @property
    def extension_id(self) -> str:
        return self.content_id

    def include(self, coordinates: Iterable[Scalar]) -> ArtinRingElement:
        """Include abstract kernel coordinates into the total ring."""

        values = _vector(
            self.domain.field,
            coordinates,
            self.kernel_dimension,
            "kernel coordinates",
        )
        return self.domain.element(self.inclusion.matvec(values))

    def apply(
        self,
        value: ArtinRingElement | PrimeFieldElement | int | Iterable[Scalar],
    ) -> ArtinRingElement:
        """Apply the quotient projection."""

        return self.projection.apply(value)

    __call__ = apply

    def verify(self) -> bool:
        """Replay surjectivity, exactness, inclusion, and small-kernel laws."""

        try:
            self.projection.verify()
            rebuilt = SmallExtension(
                self.projection,
                self.kernel_basis,
                self.inclusion,
            )
        except (TypeError, ValueError) as exc:
            raise VerificationError(f"small-extension verification failed: {exc}") from exc
        if rebuilt.to_canonical_data() != self.to_canonical_data():
            raise VerificationError("small-extension canonical snapshot failed exact replay")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "inclusion": [list(row) for row in self.inclusion.rows],
            "kernel_basis": [list(vector) for vector in self.kernel_basis],
            "projection_id": self.projection.content_id,
            "type": "arbogast.deform.small_extension",
        }


__all__ = [
    "ArtinRing",
    "ArtinRingElement",
    "ArtinRingMap",
    "SmallExtension",
]
