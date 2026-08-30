"""Certified inflation--restriction five-term sequences."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, cast

from arbogast.cert import (
    CertificateVerificationError as CentralCertificateVerificationError,
)
from arbogast.cert import (
    VerificationCertificate,
    default_verifiers,
    freeze_mapping,
)
from arbogast.cert import (
    VerificationReport as CentralVerificationReport,
)
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
    claim_boundary_hash,
)
from arbogast.core import (
    CanonicalJSON,
    CanonicalObject,
    canonical_data,
    canonical_json,
    pretty_canonical_json,
    sha256_hex,
)
from arbogast.rep import FiniteGroupExtension

from ._linear import (
    SparseMatrix,
    Vector,
    contains,
    image_basis,
    linear_combination,
    matrix_vector,
    nullspace,
    rank,
    solve_columns,
    span_basis,
)
from .certificate import (
    CertificateVerificationError,
    CohomologyCertificate,
    VerificationReport,
)
from .complex import CohomologyError, ComplexityLimits, _element_index
from .map_certificate import (
    _cochain_value,
    _contravariant_transport,
    _matrix_action,
    _normalized_tuples,
)
from .maps import _pulled_back_module, restriction_map
from .results import CohomologyResult, h1, h2


def _matrix_from_columns(
    columns: Sequence[Sequence[int]], target_dimension: int
) -> tuple[Vector, ...]:
    return tuple(tuple(column[row] for column in columns) for row in range(target_dimension))


def _column(matrix: Sequence[Sequence[int]], index: int) -> Vector:
    return tuple(row[index] for row in matrix)


def _compose(
    left: Sequence[Sequence[int]], right: Sequence[Sequence[int]], prime: int
) -> tuple[Vector, ...]:
    if not left:
        return ()
    inner = len(left[0])
    if len(right) != inner:
        raise ValueError("linear-map composition shape mismatch")
    columns = len(right[0]) if right else 0
    return tuple(
        tuple(
            sum(left[row][middle] * right[middle][column] for middle in range(inner)) % prime
            for column in range(columns)
        )
        for row in range(len(left))
    )


def _invariant_basis(
    actions: Sequence[Sequence[Sequence[int]]], dimension: int, prime: int
) -> tuple[Vector, ...]:
    rows = tuple(
        tuple(
            (matrix[row][column] - (1 if row == column else 0)) % prime
            for column in range(dimension)
        )
        for matrix in actions
        for row in range(dimension)
    )
    return nullspace(SparseMatrix.from_rows(rows, dimension, prime))


def _inverse(table: Sequence[Sequence[int]], identity: int, element: int) -> int:
    return next(
        candidate
        for candidate in range(len(table))
        if table[element][candidate] == identity and table[candidate][element] == identity
    )


def _validate_homomorphism_indices(
    domain_table: Sequence[Sequence[int]],
    domain_identity: int,
    codomain_table: Sequence[Sequence[int]],
    codomain_identity: int,
    images: Sequence[int],
    *,
    label: str,
) -> None:
    if len(images) != len(domain_table) or any(
        not 0 <= image < len(codomain_table) for image in images
    ):
        raise CertificateVerificationError(f"{label} indices have the wrong shape")
    if images[domain_identity] != codomain_identity:
        raise CertificateVerificationError(f"{label} does not preserve the identity")
    for left in range(len(domain_table)):
        for right in range(len(domain_table)):
            if codomain_table[images[left]][images[right]] != images[domain_table[left][right]]:
                raise CertificateVerificationError(f"{label} does not preserve multiplication")


def _cochain_embedding_matrix(
    source: CohomologyCertificate,
    target: CohomologyCertificate,
    projection_indices: Sequence[int],
    coefficient_basis: Sequence[Sequence[int]],
    degree: int,
) -> tuple[Vector, ...]:
    source_dimension = (len(source.multiplication_table) - 1) ** degree * source.module_dimension
    target_dimension = (len(target.multiplication_table) - 1) ** degree * target.module_dimension
    columns: list[Vector] = []
    for source_coordinate in range(source_dimension):
        source_values = tuple(
            1 if index == source_coordinate else 0 for index in range(source_dimension)
        )
        output: list[int] = []
        for arguments in _normalized_tuples(
            len(target.multiplication_table), target.identity_index, degree
        ):
            value = _cochain_value(
                source_values,
                tuple(projection_indices[index] for index in arguments),
                order=len(source.multiplication_table),
                identity=source.identity_index,
                module_dimension=source.module_dimension,
            )
            output.extend(linear_combination(coefficient_basis, value, source.prime))
        if len(output) != target_dimension:
            raise CohomologyError("cochain embedding has the wrong dimension")
        columns.append(tuple(output))
    return _matrix_from_columns(columns, target_dimension)


def _embedded_inflation_matrix(
    source: CohomologyCertificate,
    target: CohomologyCertificate,
    projection_indices: Sequence[int],
    coefficient_basis: Sequence[Sequence[int]],
) -> tuple[Vector, ...]:
    cochain_matrix = _cochain_embedding_matrix(
        source, target, projection_indices, coefficient_basis, source.degree
    )
    columns = tuple(
        matrix_vector(
            target.quotient_projection,
            matrix_vector(cochain_matrix, representative, source.prime),
            source.prime,
        )
        for representative in source.representative_basis
    )
    return _matrix_from_columns(columns, target.dimension)


def _quotient_actions(
    group: CohomologyCertificate,
    quotient_order: int,
    invariant_basis: Sequence[Vector],
    section_indices: Sequence[int],
) -> tuple[tuple[Vector, ...], ...]:
    dimension = len(invariant_basis)
    actions: list[tuple[Vector, ...]] = []
    for lift in section_indices:
        columns: list[Vector] = []
        for vector in invariant_basis:
            image = _matrix_action(group.action_matrices[lift], vector, group.prime)
            coordinates = solve_columns(invariant_basis, image, group.prime)
            if coordinates is None:
                raise CohomologyError("the N-invariants are not stable under G")
            columns.append(coordinates)
        actions.append(_matrix_from_columns(columns, dimension))
    if len(actions) != quotient_order:
        raise CohomologyError("quotient section has the wrong size")
    return tuple(actions)


def _kernel_cohomology_actions(
    kernel: CohomologyCertificate,
    group: CohomologyCertificate,
    quotient_order: int,
    inclusion_indices: Sequence[int],
    section_indices: Sequence[int],
) -> tuple[tuple[Vector, ...], ...]:
    table = group.multiplication_table
    inclusion_inverse = {image: index for index, image in enumerate(inclusion_indices)}
    actions: list[tuple[Vector, ...]] = []
    for quotient_index in range(quotient_order):
        lift = section_indices[quotient_index]
        lift_inverse = _inverse(table, group.identity_index, lift)
        columns: list[Vector] = []
        for representative in kernel.representative_basis:
            transformed: list[int] = []
            for arguments in _normalized_tuples(
                len(kernel.multiplication_table), kernel.identity_index, 1
            ):
                kernel_index = arguments[0]
                conjugate = table[table[lift_inverse][inclusion_indices[kernel_index]]][lift]
                if conjugate not in inclusion_inverse:
                    raise CohomologyError("extension kernel is not normal")
                value = _cochain_value(
                    representative,
                    (inclusion_inverse[conjugate],),
                    order=len(kernel.multiplication_table),
                    identity=kernel.identity_index,
                    module_dimension=kernel.module_dimension,
                )
                transformed.extend(_matrix_action(group.action_matrices[lift], value, group.prime))
            columns.append(matrix_vector(kernel.quotient_projection, transformed, kernel.prime))
        actions.append(_matrix_from_columns(columns, kernel.dimension))
    return tuple(actions)


def _restriction_to_invariants_matrix(
    group: CohomologyCertificate,
    kernel: CohomologyCertificate,
    inclusion_indices: Sequence[int],
    invariant_basis: Sequence[Vector],
) -> tuple[Vector, ...]:
    columns: list[Vector] = []
    for representative in group.representative_basis:
        restricted = _contravariant_transport(
            representative, group, kernel, inclusion_indices, degree=1
        )
        kernel_coordinates = matrix_vector(kernel.quotient_projection, restricted, group.prime)
        coordinates = solve_columns(invariant_basis, kernel_coordinates, group.prime)
        if coordinates is None:
            raise CohomologyError("restriction image is not quotient-invariant")
        columns.append(coordinates)
    return _matrix_from_columns(columns, len(invariant_basis))


@dataclass(frozen=True, slots=True)
class _PrimeField:
    characteristic: int

    @property
    def order(self) -> int:
        return self.characteristic


@dataclass(frozen=True, slots=True)
class _TabulatedModule:
    field: _PrimeField
    dimension: int
    elements: tuple[Any, ...]
    matrices: tuple[tuple[Vector, ...], ...]

    def action_matrix(self, element: Any) -> tuple[Vector, ...]:
        return self.matrices[_element_index(self.elements, element)]


_FIVE_TERM_MAP_NAMES = (
    "inflation_h1",
    "restriction",
    "transgression",
    "inflation_h2",
)


def _verify_linear_map_structure(
    prime: int,
    source_dimension: int,
    target_dimension: int,
    matrix: Sequence[Sequence[int]],
) -> None:
    """Replay the finite linear-algebra payload without creating public evidence."""

    if prime < 2:
        raise ValueError("linear-map coefficient characteristic is invalid")
    if source_dimension < 0 or target_dimension < 0:
        raise ValueError("linear-map dimensions must be nonnegative")
    if len(matrix) != target_dimension or any(len(row) != source_dimension for row in matrix):
        raise ValueError("linear-map matrix has the wrong shape")
    if any(not 0 <= entry < prime for row in matrix for entry in row):
        raise ValueError("linear-map matrix uses noncanonical residues")


def _verify_exact_sequence_structure(
    dimensions: Sequence[int],
    matrices: Sequence[Sequence[Sequence[int]]],
    prime: int,
) -> None:
    """Independently recompute zero composites and image/kernel exactness."""

    if len(matrices) + 1 != len(dimensions):
        raise ValueError("exact sequence has the wrong number of maps")
    if not matrices:
        raise ValueError("exact sequence must contain at least one map")
    for index, matrix in enumerate(matrices):
        _verify_linear_map_structure(
            prime,
            dimensions[index],
            dimensions[index + 1],
            matrix,
        )
    first_kernel = nullspace(SparseMatrix.from_rows(matrices[0], dimensions[0], prime))
    if first_kernel:
        raise ValueError("the first five-term map is not injective")
    for index, (left, right) in enumerate(pairwise(matrices)):
        composite = _compose(right, left, prime)
        if any(any(row) for row in composite):
            raise ValueError("adjacent exact-sequence maps do not compose to zero")
        middle_dimension = dimensions[index + 1]
        left_image = image_basis(SparseMatrix.from_rows(left, dimensions[index], prime))
        right_kernel = nullspace(SparseMatrix.from_rows(right, middle_dimension, prime))
        image = span_basis(left_image, middle_dimension, prime)
        kernel = span_basis(right_kernel, middle_dimension, prime)
        if image != kernel:
            raise ValueError("exact-sequence image does not equal the next kernel")


@dataclass(frozen=True, slots=True)
class ExactLinearMap(CanonicalObject):
    """A finite prime-field linear map with exact kernel and image operations."""

    name: str
    prime: int
    source_dimension: int
    target_dimension: int
    matrix: tuple[Vector, ...]
    certificate: InflationRestrictionCertificate = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.certificate, InflationRestrictionCertificate):
            raise TypeError("ExactLinearMap requires an inflation-restriction certificate")

    @property
    def rank(self) -> int:
        return rank(self.matrix, self.source_dimension, self.prime)

    @property
    def content_hash(self) -> str:
        return sha256_hex(self)

    def to_canonical_data(self) -> CanonicalJSON:
        return canonical_data(
            {
                "schema_version": "arbogast.exact-linear-map.v1",
                "name": self.name,
                "prime": self.prime,
                "source_dimension": self.source_dimension,
                "target_dimension": self.target_dimension,
                "matrix": [list(row) for row in self.matrix],
            }
        )

    @property
    def kernel_basis(self) -> tuple[Vector, ...]:
        return nullspace(SparseMatrix.from_rows(self.matrix, self.source_dimension, self.prime))

    @property
    def image_basis(self) -> tuple[Vector, ...]:
        return image_basis(SparseMatrix.from_rows(self.matrix, self.source_dimension, self.prime))

    def apply(self, coordinates: Sequence[int]) -> Vector:
        if len(coordinates) != self.source_dimension:
            raise ValueError("linear-map input has the wrong dimension")
        return matrix_vector(self.matrix, tuple(coordinates), self.prime)

    __call__ = apply

    def verify(self) -> bool:
        _verify_linear_map_structure(
            self.prime,
            self.source_dimension,
            self.target_dimension,
            self.matrix,
        )
        try:
            index = _FIVE_TERM_MAP_NAMES.index(self.name)
        except ValueError as error:
            raise ValueError(
                "linear-map name is not part of the certified five-term sequence"
            ) from error
        if (
            self.prime != self.certificate.h1_group.prime
            or self.source_dimension != self.certificate.term_dimensions[index]
            or self.target_dimension != self.certificate.term_dimensions[index + 1]
            or self.matrix != self.certificate.map_matrices[index]
        ):
            raise ValueError("linear-map payload does not match its certificate")
        self.certificate.verify()
        return True

    def certify(self) -> InflationRestrictionCertificate:
        self.verify()
        return self.certificate

    def verification_certificate(self) -> VerificationCertificate:
        return _semantic_certificate(self.certify())

    def claim(self) -> Claim:
        return _claim(self.certify())

    def claim_graph(self) -> ClaimGraph:
        return ClaimGraph((self.claim(),))


@dataclass(frozen=True, slots=True)
class TransgressionWitness:
    extension_cochain: Vector
    kernel_correction: Vector
    quotient_cocycle: Vector

    def to_dict(self) -> dict[str, object]:
        return {
            "extension_cochain": list(self.extension_cochain),
            "kernel_correction": list(self.kernel_correction),
            "quotient_cocycle": list(self.quotient_cocycle),
        }


@dataclass(frozen=True, slots=True)
class InflationRestrictionCertificate:
    """Portable receipt for the complete five-term calculation."""

    schema_version: str
    inclusion_indices: tuple[int, ...]
    projection_indices: tuple[int, ...]
    section_indices: tuple[int, ...]
    module_invariant_basis: tuple[Vector, ...]
    kernel_action_matrices: tuple[tuple[Vector, ...], ...]
    kernel_invariant_basis: tuple[Vector, ...]
    h1_quotient: CohomologyCertificate
    h1_group: CohomologyCertificate
    h1_kernel: CohomologyCertificate
    h2_quotient: CohomologyCertificate
    h2_group: CohomologyCertificate
    map_matrices: tuple[tuple[Vector, ...], ...]
    transgression_witnesses: tuple[TransgressionWitness, ...]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode()).hexdigest()

    @property
    def term_dimensions(self) -> tuple[int, ...]:
        return (
            self.h1_quotient.dimension,
            self.h1_group.dimension,
            len(self.kernel_invariant_basis),
            self.h2_quotient.dimension,
            self.h2_group.dimension,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "inclusion_indices": list(self.inclusion_indices),
            "projection_indices": list(self.projection_indices),
            "section_indices": list(self.section_indices),
            "module_invariant_basis": [list(row) for row in self.module_invariant_basis],
            "kernel_action_matrices": [
                [list(row) for row in matrix] for matrix in self.kernel_action_matrices
            ],
            "kernel_invariant_basis": [list(row) for row in self.kernel_invariant_basis],
            "h1_quotient": self.h1_quotient.to_dict(),
            "h1_group": self.h1_group.to_dict(),
            "h1_kernel": self.h1_kernel.to_dict(),
            "h2_quotient": self.h2_quotient.to_dict(),
            "h2_group": self.h2_group.to_dict(),
            "map_matrices": [[list(row) for row in matrix] for matrix in self.map_matrices],
            "transgression_witnesses": [
                witness.to_dict() for witness in self.transgression_witnesses
            ],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return (
            canonical_json(self.to_dict())
            if indent is None
            else pretty_canonical_json(self.to_dict(), indent=indent)
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> InflationRestrictionCertificate:
        expected = {
            "schema_version",
            "inclusion_indices",
            "projection_indices",
            "section_indices",
            "module_invariant_basis",
            "kernel_action_matrices",
            "kernel_invariant_basis",
            "h1_quotient",
            "h1_group",
            "h1_kernel",
            "h2_quotient",
            "h2_group",
            "map_matrices",
            "transgression_witnesses",
        }
        if set(value) != expected:
            raise ValueError("five-term certificate fields mismatch")

        def integers(raw: object, name: str) -> tuple[int, ...]:
            if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
                raise ValueError(f"{name} must be a sequence")
            if any(isinstance(item, bool) or not isinstance(item, int) for item in raw):
                raise ValueError(f"{name} entries must be integers")
            return tuple(cast("Sequence[int]", raw))

        def rows(raw: object, name: str) -> tuple[Vector, ...]:
            if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
                raise ValueError(f"{name} must be rows")
            return tuple(integers(row, name) for row in raw)

        def matrices(raw: object, name: str) -> tuple[tuple[Vector, ...], ...]:
            if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
                raise ValueError(f"{name} must be matrices")
            return tuple(rows(matrix, name) for matrix in raw)

        def cohom(raw: object, name: str) -> CohomologyCertificate:
            if not isinstance(raw, Mapping):
                raise ValueError(f"{name} must be an object")
            return CohomologyCertificate.from_dict(raw)

        raw_witnesses = value["transgression_witnesses"]
        if isinstance(raw_witnesses, (str, bytes, bytearray)) or not isinstance(
            raw_witnesses, Sequence
        ):
            raise ValueError("transgression_witnesses must be a sequence")
        witnesses: list[TransgressionWitness] = []
        for raw in raw_witnesses:
            if not isinstance(raw, Mapping) or set(raw) != {
                "extension_cochain",
                "kernel_correction",
                "quotient_cocycle",
            }:
                raise ValueError("invalid transgression witness")
            witnesses.append(
                TransgressionWitness(
                    integers(raw["extension_cochain"], "extension_cochain"),
                    integers(raw["kernel_correction"], "kernel_correction"),
                    integers(raw["quotient_cocycle"], "quotient_cocycle"),
                )
            )
        schema = value["schema_version"]
        if not isinstance(schema, str):
            raise ValueError("schema_version must be a string")
        return cls(
            schema,
            integers(value["inclusion_indices"], "inclusion_indices"),
            integers(value["projection_indices"], "projection_indices"),
            integers(value["section_indices"], "section_indices"),
            rows(value["module_invariant_basis"], "module_invariant_basis"),
            matrices(value["kernel_action_matrices"], "kernel_action_matrices"),
            rows(value["kernel_invariant_basis"], "kernel_invariant_basis"),
            cohom(value["h1_quotient"], "h1_quotient"),
            cohom(value["h1_group"], "h1_group"),
            cohom(value["h1_kernel"], "h1_kernel"),
            cohom(value["h2_quotient"], "h2_quotient"),
            cohom(value["h2_group"], "h2_group"),
            matrices(value["map_matrices"], "map_matrices"),
            tuple(witnesses),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> InflationRestrictionCertificate:
        decoded = json.loads(value)
        if not isinstance(decoded, Mapping):
            raise ValueError("five-term certificate JSON must contain an object")
        return cls.from_dict(decoded)

    def verify(self, *, raise_on_error: bool = True) -> VerificationReport:
        checks: list[str] = []
        try:
            self._verify(checks)
        except (TypeError, ValueError, IndexError, CertificateVerificationError) as error:
            if raise_on_error:
                raise CertificateVerificationError(str(error)) from error
            return VerificationReport(False, tuple(checks), str(error))
        return VerificationReport(True, tuple(checks))

    def _verify(self, checks: list[str]) -> None:
        if self.schema_version != "arbogast.inflation-restriction.v1":
            raise CertificateVerificationError("unsupported five-term certificate schema")
        for certificate in (
            self.h1_quotient,
            self.h1_group,
            self.h1_kernel,
            self.h2_quotient,
            self.h2_group,
        ):
            certificate.verify()
        checks.append("endpoint-cohomology-replayed")
        if not (
            self.h1_group.prime
            == self.h1_kernel.prime
            == self.h1_quotient.prime
            == self.h2_group.prime
            == self.h2_quotient.prime
        ):
            raise CertificateVerificationError("five-term endpoints use different fields")
        prime = self.h1_group.prime
        group_snapshot = (
            self.h1_group.group_element_ids,
            self.h1_group.identity_index,
            self.h1_group.multiplication_table,
            self.h1_group.module_dimension,
            self.h1_group.action_matrices,
        )
        if group_snapshot != (
            self.h2_group.group_element_ids,
            self.h2_group.identity_index,
            self.h2_group.multiplication_table,
            self.h2_group.module_dimension,
            self.h2_group.action_matrices,
        ):
            raise CertificateVerificationError("H1 and H2 group modules differ")
        quotient_snapshot = (
            self.h1_quotient.group_element_ids,
            self.h1_quotient.identity_index,
            self.h1_quotient.multiplication_table,
            self.h1_quotient.module_dimension,
            self.h1_quotient.action_matrices,
        )
        if quotient_snapshot != (
            self.h2_quotient.group_element_ids,
            self.h2_quotient.identity_index,
            self.h2_quotient.multiplication_table,
            self.h2_quotient.module_dimension,
            self.h2_quotient.action_matrices,
        ):
            raise CertificateVerificationError("H1 and H2 quotient modules differ")
        if self.h1_kernel.module_dimension != self.h1_group.module_dimension:
            raise CertificateVerificationError("kernel and group module dimensions differ")
        _validate_homomorphism_indices(
            self.h1_kernel.multiplication_table,
            self.h1_kernel.identity_index,
            self.h1_group.multiplication_table,
            self.h1_group.identity_index,
            self.inclusion_indices,
            label="kernel inclusion",
        )
        _validate_homomorphism_indices(
            self.h1_group.multiplication_table,
            self.h1_group.identity_index,
            self.h1_quotient.multiplication_table,
            self.h1_quotient.identity_index,
            self.projection_indices,
            label="quotient projection",
        )
        if len(set(self.inclusion_indices)) != len(self.inclusion_indices):
            raise CertificateVerificationError("kernel inclusion is not injective")
        if set(self.projection_indices) != set(range(len(self.h1_quotient.multiplication_table))):
            raise CertificateVerificationError("quotient projection is not surjective")
        if (
            tuple(self.h1_group.action_matrices[index] for index in self.inclusion_indices)
            != self.h1_kernel.action_matrices
        ):
            raise CertificateVerificationError("kernel module action is not the restriction")
        quotient_identity = self.h1_quotient.identity_index
        if {
            index
            for index, image in enumerate(self.projection_indices)
            if image == quotient_identity
        } != set(self.inclusion_indices):
            raise CertificateVerificationError("extension is not exact at G")
        if len(self.section_indices) != len(self.h1_quotient.multiplication_table):
            raise CertificateVerificationError("section indices have the wrong size")
        if tuple(self.projection_indices[index] for index in self.section_indices) != tuple(
            range(len(self.h1_quotient.multiplication_table))
        ):
            raise CertificateVerificationError("section is not a right inverse")
        if self.section_indices[quotient_identity] != self.h1_group.identity_index:
            raise CertificateVerificationError("section is not normalized")
        checks.append("finite-group-extension")
        fresh_module_invariants = _invariant_basis(
            tuple(self.h1_group.action_matrices[index] for index in self.inclusion_indices),
            self.h1_group.module_dimension,
            prime,
        )
        if fresh_module_invariants != self.module_invariant_basis:
            raise CertificateVerificationError("M^N basis does not replay")
        quotient_actions = _quotient_actions(
            self.h1_group,
            len(self.h1_quotient.multiplication_table),
            self.module_invariant_basis,
            self.section_indices,
        )
        if quotient_actions != self.h1_quotient.action_matrices:
            raise CertificateVerificationError("quotient action on M^N does not replay")
        fresh_kernel_actions = _kernel_cohomology_actions(
            self.h1_kernel,
            self.h1_group,
            len(self.h1_quotient.multiplication_table),
            self.inclusion_indices,
            self.section_indices,
        )
        if fresh_kernel_actions != self.kernel_action_matrices:
            raise CertificateVerificationError("Q action on H1(N,M) does not replay")
        fresh_kernel_invariants = _invariant_basis(
            fresh_kernel_actions, self.h1_kernel.dimension, prime
        )
        if fresh_kernel_invariants != self.kernel_invariant_basis:
            raise CertificateVerificationError("H1(N,M)^Q basis does not replay")
        checks.extend(("module-invariants", "quotient-invariants"))
        if len(self.map_matrices) != 4:
            raise CertificateVerificationError("five-term receipt needs four maps")
        expected_maps = (
            _embedded_inflation_matrix(
                self.h1_quotient,
                self.h1_group,
                self.projection_indices,
                self.module_invariant_basis,
            ),
            _restriction_to_invariants_matrix(
                self.h1_group,
                self.h1_kernel,
                self.inclusion_indices,
                self.kernel_invariant_basis,
            ),
            self.map_matrices[2],
            _embedded_inflation_matrix(
                self.h2_quotient,
                self.h2_group,
                self.projection_indices,
                self.module_invariant_basis,
            ),
        )
        if (
            self.map_matrices[0] != expected_maps[0]
            or self.map_matrices[1] != expected_maps[1]
            or self.map_matrices[3] != expected_maps[3]
        ):
            raise CertificateVerificationError("inflation or restriction matrix does not replay")
        self._verify_transgression_witnesses()
        checks.append("transgression-witnesses")
        _verify_exact_sequence_structure(self.term_dimensions, self.map_matrices, prime)
        checks.extend(("zero-composites", "image-equals-kernel"))

    def _verify_transgression_witnesses(self) -> None:
        prime = self.h1_group.prime
        if len(self.transgression_witnesses) != len(self.kernel_invariant_basis):
            raise CertificateVerificationError("transgression witness count is wrong")
        restriction_cochain = _matrix_from_columns(
            tuple(
                _contravariant_transport(
                    tuple(
                        1 if index == column else 0
                        for index in range(
                            (len(self.h1_group.multiplication_table) - 1)
                            * self.h1_group.module_dimension
                        )
                    ),
                    self.h1_group,
                    self.h1_kernel,
                    self.inclusion_indices,
                    degree=1,
                )
                for column in range(
                    (len(self.h1_group.multiplication_table) - 1) * self.h1_group.module_dimension
                )
            ),
            (len(self.h1_kernel.multiplication_table) - 1) * self.h1_kernel.module_dimension,
        )
        embedded = _cochain_embedding_matrix(
            self.h2_quotient,
            self.h2_group,
            self.projection_indices,
            self.module_invariant_basis,
            2,
        )
        d_kernel = _differential(self.h1_kernel, 0)
        d_group = _differential(self.h1_group, 1)
        transgression_columns: list[Vector] = []
        for invariant, witness in zip(
            self.kernel_invariant_basis, self.transgression_witnesses, strict=True
        ):
            kernel_representative = _section_vector(self.h1_kernel, invariant)
            restricted = matrix_vector(restriction_cochain, witness.extension_cochain, prime)
            correction = d_kernel.apply(witness.kernel_correction)
            if (
                tuple(
                    (left - right) % prime
                    for left, right in zip(restricted, correction, strict=True)
                )
                != kernel_representative
            ):
                raise CertificateVerificationError("transgression restriction equation failed")
            if d_group.apply(witness.extension_cochain) != matrix_vector(
                embedded, witness.quotient_cocycle, prime
            ):
                raise CertificateVerificationError("transgression differential equation failed")
            if not contains(
                self.h2_quotient.cocycle_basis,
                witness.quotient_cocycle,
                prime,
            ):
                raise CertificateVerificationError("transgression target is not a cocycle")
            transgression_columns.append(
                matrix_vector(
                    self.h2_quotient.quotient_projection,
                    witness.quotient_cocycle,
                    prime,
                )
            )
        if (
            _matrix_from_columns(transgression_columns, self.h2_quotient.dimension)
            != self.map_matrices[2]
        ):
            raise CertificateVerificationError("transgression matrix does not match witnesses")


def _section_vector(certificate: CohomologyCertificate, coordinates: Sequence[int]) -> Vector:
    return tuple(
        sum(
            certificate.quotient_section[row][column] * coordinates[column]
            for column in range(certificate.dimension)
        )
        % certificate.prime
        for row in range(len(certificate.quotient_section))
    )


def _differential(certificate: CohomologyCertificate, degree: int) -> SparseMatrix:
    from .complex import _bar_differential_from_snapshot

    return _bar_differential_from_snapshot(
        certificate.prime,
        certificate.multiplication_table,
        certificate.identity_index,
        certificate.action_matrices,
        certificate.module_dimension,
        degree,
    )


@dataclass(frozen=True, slots=True)
class ExactSequence(CanonicalObject):
    """A finite exact sequence certified by independent image/kernel recomputation."""

    dimensions: tuple[int, ...]
    maps: tuple[ExactLinearMap, ...]
    prime: int
    certificate: InflationRestrictionCertificate = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.certificate, InflationRestrictionCertificate):
            raise TypeError("ExactSequence requires an inflation-restriction certificate")

    @property
    def content_hash(self) -> str:
        return sha256_hex(self)

    def to_canonical_data(self) -> CanonicalJSON:
        return canonical_data(
            {
                "schema_version": "arbogast.exact-sequence.v1",
                "prime": self.prime,
                "dimensions": list(self.dimensions),
                "maps": [linear_map.to_canonical_data() for linear_map in self.maps],
            }
        )

    def verify(self) -> bool:
        if (
            self.dimensions != self.certificate.term_dimensions
            or self.prime != self.certificate.h1_group.prime
            or tuple(linear_map.name for linear_map in self.maps) != _FIVE_TERM_MAP_NAMES
            or tuple(linear_map.matrix for linear_map in self.maps) != self.certificate.map_matrices
            or any(linear_map.certificate != self.certificate for linear_map in self.maps)
        ):
            raise ValueError("exact-sequence payload does not match its certificate")
        self.certificate.verify()
        for linear_map in self.maps:
            linear_map.verify()
        _verify_exact_sequence_structure(
            self.dimensions,
            tuple(linear_map.matrix for linear_map in self.maps),
            self.prime,
        )
        return True

    def certify(self) -> InflationRestrictionCertificate:
        self.verify()
        return self.certificate

    def verification_certificate(self) -> VerificationCertificate:
        return _semantic_certificate(self.certify())

    def claim(self) -> Claim:
        return _claim(self.certify())

    def claim_graph(self) -> ClaimGraph:
        return ClaimGraph((self.claim(),))


@dataclass(frozen=True, slots=True)
class InflationRestrictionSequence:
    extension: FiniteGroupExtension = field(repr=False, compare=False)
    module: Any = field(repr=False, compare=False)
    h1_quotient: CohomologyResult
    h1_group: CohomologyResult
    h1_kernel: CohomologyResult
    h2_quotient: CohomologyResult
    h2_group: CohomologyResult
    module_invariant_basis: tuple[Vector, ...]
    kernel_invariant_basis: tuple[Vector, ...]
    inflation_h1: ExactLinearMap
    restriction: ExactLinearMap
    transgression: ExactLinearMap
    inflation_h2: ExactLinearMap
    certificate: InflationRestrictionCertificate

    @property
    def exact_sequence(self) -> ExactSequence:
        return ExactSequence(
            self.certificate.term_dimensions,
            (
                self.inflation_h1,
                self.restriction,
                self.transgression,
                self.inflation_h2,
            ),
            self.h1_group.complex.prime,
            self.certificate,
        )

    def verify(self) -> bool:
        self.extension.verify()
        for result in (
            self.h1_quotient,
            self.h1_group,
            self.h1_kernel,
            self.h2_quotient,
            self.h2_group,
        ):
            result.verify()
        self.certificate.verify()
        self.exact_sequence.verify()
        return True

    def certify(self) -> InflationRestrictionCertificate:
        self.verify()
        return self.certificate

    def verification_certificate(self) -> VerificationCertificate:
        self.verify()
        return _semantic_certificate(self.certificate)

    def claim(self) -> Claim:
        self.verify()
        return _claim(self.certificate)

    def claim_graph(self) -> ClaimGraph:
        self.verify()
        return ClaimGraph((self.claim(),))


def _transgression_data(
    h1_group: CohomologyResult,
    h1_kernel: CohomologyResult,
    h2_quotient: CohomologyResult,
    h2_group: CohomologyResult,
    inclusion_indices: Sequence[int],
    projection_indices: Sequence[int],
    coefficient_basis: Sequence[Vector],
    kernel_invariant_basis: Sequence[Vector],
) -> tuple[tuple[Vector, ...], tuple[TransgressionWitness, ...]]:
    prime = h1_group.complex.prime
    group_c1_dimension = h1_group.complex.space(1).dimension
    kernel_c1_dimension = h1_kernel.complex.space(1).dimension
    quotient_c2_dimension = h2_quotient.complex.space(2).dimension
    group_c2_dimension = h2_group.complex.space(2).dimension
    restriction_columns = tuple(
        _contravariant_transport(
            tuple(1 if index == column else 0 for index in range(group_c1_dimension)),
            h1_group.certificate,
            h1_kernel.certificate,
            inclusion_indices,
            degree=1,
        )
        for column in range(group_c1_dimension)
    )
    d_kernel = h1_kernel.complex.differential(0)
    d_group = h1_group.complex.differential(1)
    embedded = _cochain_embedding_matrix(
        h2_quotient.certificate,
        h2_group.certificate,
        projection_indices,
        coefficient_basis,
        2,
    )
    columns: list[Vector] = []
    for column in range(group_c1_dimension):
        columns.append((*restriction_columns[column], *d_group.column(column)))
    for column in range(d_kernel.ncols):
        columns.append(
            (
                *tuple((-value) % prime for value in d_kernel.column(column)),
                *((0,) * group_c2_dimension),
            )
        )
    for column in range(quotient_c2_dimension):
        columns.append(
            (
                *((0,) * kernel_c1_dimension),
                *tuple((-value) % prime for value in _column(embedded, column)),
            )
        )
    transgression_columns: list[Vector] = []
    witnesses: list[TransgressionWitness] = []
    for invariant in kernel_invariant_basis:
        representative = h1_kernel.quotient_map.section_vector(tuple(invariant))
        target = (*representative, *((0,) * group_c2_dimension))
        solution = solve_columns(columns, target, prime)
        if solution is None:
            raise CohomologyError("failed to construct the five-term transgression")
        extension_cochain = solution[:group_c1_dimension]
        kernel_correction = solution[group_c1_dimension : group_c1_dimension + d_kernel.ncols]
        quotient_cocycle = solution[-quotient_c2_dimension:]
        if quotient_c2_dimension == 0:
            quotient_cocycle = ()
        if not h2_quotient.cocycles.contains(h2_quotient.complex.cochain(2, quotient_cocycle)):
            raise CohomologyError("constructed transgression value is not a cocycle")
        coordinates = h2_quotient.quotient_map.project_vector(quotient_cocycle)
        transgression_columns.append(coordinates)
        witnesses.append(
            TransgressionWitness(
                tuple(extension_cochain),
                tuple(kernel_correction),
                tuple(quotient_cocycle),
            )
        )
    return (
        _matrix_from_columns(transgression_columns, h2_quotient.dimension),
        tuple(witnesses),
    )


def inflation_restriction(
    extension: FiniteGroupExtension,
    module: Any,
    *,
    limits: ComplexityLimits | None = None,
) -> InflationRestrictionSequence:
    """Compute and certify the five-term sequence for ``1 -> N -> G -> Q -> 1``."""

    if not isinstance(extension, FiniteGroupExtension):
        raise TypeError("inflation_restriction requires a FiniteGroupExtension")
    extension.verify()
    h1_group = h1(extension.group, module, limits=limits)
    h2_group = h2(extension.group, module, limits=limits)
    kernel_module = _pulled_back_module(h1_group.complex, extension.inclusion)
    h1_kernel = h1(extension.kernel, kernel_module, limits=limits)
    invariant_basis = _invariant_basis(
        tuple(
            h1_group.complex.action_matrices[index] for index in extension.inclusion.image_indices
        ),
        h1_group.complex.module_dimension,
        h1_group.complex.prime,
    )
    quotient_actions = _quotient_actions(
        h1_group.certificate,
        len(extension.projection.codomain_elements),
        invariant_basis,
        extension.section_indices,
    )
    quotient_module = _TabulatedModule(
        _PrimeField(h1_group.complex.prime),
        len(invariant_basis),
        extension.projection.codomain_elements,
        quotient_actions,
    )
    h1_quotient = h1(extension.quotient, quotient_module, limits=limits)
    h2_quotient = h2(extension.quotient, quotient_module, limits=limits)
    # Recompute against the actual quotient receipt; the provisional value supplied only G data.
    quotient_actions = _quotient_actions(
        h1_group.certificate,
        len(h1_quotient.complex.multiplication_table),
        invariant_basis,
        extension.section_indices,
    )
    if quotient_actions != h1_quotient.complex.action_matrices:
        raise CohomologyError("quotient action changed during construction")
    kernel_actions = _kernel_cohomology_actions(
        h1_kernel.certificate,
        h1_group.certificate,
        len(extension.projection.codomain_elements),
        extension.inclusion.image_indices,
        extension.section_indices,
    )
    kernel_invariants = _invariant_basis(
        kernel_actions, h1_kernel.dimension, h1_group.complex.prime
    )
    inflation_h1_matrix = _embedded_inflation_matrix(
        h1_quotient.certificate,
        h1_group.certificate,
        extension.projection.image_indices,
        invariant_basis,
    )
    restriction_full = restriction_map(
        h1_group, extension.kernel, extension.inclusion, limits=limits
    )
    if restriction_full.target.certificate != h1_kernel.certificate:
        raise CohomologyError("kernel cohomology construction is not canonical")
    restriction_matrix = _restriction_to_invariants_matrix(
        h1_group.certificate,
        h1_kernel.certificate,
        extension.inclusion.image_indices,
        kernel_invariants,
    )
    transgression_matrix, witnesses = _transgression_data(
        h1_group,
        h1_kernel,
        h2_quotient,
        h2_group,
        extension.inclusion.image_indices,
        extension.projection.image_indices,
        invariant_basis,
        kernel_invariants,
    )
    inflation_h2_matrix = _embedded_inflation_matrix(
        h2_quotient.certificate,
        h2_group.certificate,
        extension.projection.image_indices,
        invariant_basis,
    )
    dimensions = (
        h1_quotient.dimension,
        h1_group.dimension,
        len(kernel_invariants),
        h2_quotient.dimension,
        h2_group.dimension,
    )
    matrices = (
        inflation_h1_matrix,
        restriction_matrix,
        transgression_matrix,
        inflation_h2_matrix,
    )
    names = _FIVE_TERM_MAP_NAMES
    certificate = InflationRestrictionCertificate(
        "arbogast.inflation-restriction.v1",
        extension.inclusion.image_indices,
        extension.projection.image_indices,
        extension.section_indices,
        invariant_basis,
        kernel_actions,
        kernel_invariants,
        h1_quotient.certificate,
        h1_group.certificate,
        h1_kernel.certificate,
        h2_quotient.certificate,
        h2_group.certificate,
        matrices,
        witnesses,
    )
    maps = tuple(
        ExactLinearMap(
            name,
            h1_group.complex.prime,
            source,
            target,
            matrix,
            certificate,
        )
        for name, source, target, matrix in zip(
            names, dimensions[:-1], dimensions[1:], matrices, strict=True
        )
    )
    sequence = InflationRestrictionSequence(
        extension,
        module,
        h1_quotient,
        h1_group,
        h1_kernel,
        h2_quotient,
        h2_group,
        invariant_basis,
        kernel_invariants,
        maps[0],
        maps[1],
        maps[2],
        maps[3],
        certificate,
    )
    sequence.verify()
    return sequence


def transgression(
    extension_or_sequence: FiniteGroupExtension | InflationRestrictionSequence,
    module: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> ExactLinearMap:
    """Return the certified middle connecting map in the five-term sequence."""

    if isinstance(extension_or_sequence, InflationRestrictionSequence):
        if module is not None:
            raise TypeError("module must be omitted when passing a computed sequence")
        sequence = extension_or_sequence
    else:
        if module is None:
            raise TypeError("module is required when passing a finite group extension")
        sequence = inflation_restriction(extension_or_sequence, module, limits=limits)
    sequence.verify()
    return sequence.transgression


FIVE_TERM_VERIFIER = "cohom.inflation_restriction.v1"
FIVE_TERM_CHECKS = (
    "endpoint-cohomology-replayed",
    "finite-group-extension",
    "module-and-class-invariants",
    "transgression-witnesses",
    "zero-composites",
    "image-equals-kernel",
)
FIVE_TERM_GUARANTEES: tuple[str, ...] = ()


def _five_term_statement(certificate: InflationRestrictionCertificate) -> FormalStatement:
    return FormalStatement.create(
        text=("The certified inflation-restriction sequence is exact at every interior term."),
        parameters={
            "term_dimensions": certificate.term_dimensions,
            "certificate_hash": f"sha256:{certificate.content_hash}",
        },
    )


def _five_term_claim_id(certificate: InflationRestrictionCertificate) -> str:
    return f"cohom.inflation-restriction.{certificate.content_hash}"


def _verify_semantic(
    certificate: VerificationCertificate,
) -> CentralVerificationReport:
    payload = certificate.witness.to_dict()
    if set(payload) != {"inflation_restriction_certificate"}:
        raise CentralCertificateVerificationError("five-term witness has unexpected fields")
    raw = payload["inflation_restriction_certificate"]
    if not isinstance(raw, dict):
        raise CentralCertificateVerificationError("five-term witness must be an object")
    domain = InflationRestrictionCertificate.from_dict(raw)
    domain.verify()
    statement = _five_term_statement(domain)
    claim_id = _five_term_claim_id(domain)
    if certificate.subject != f"five-term:sha256:{domain.content_hash}":
        raise CentralCertificateVerificationError("five-term subject was altered")
    if certificate.verifier != FIVE_TERM_VERIFIER or certificate.claim_id != claim_id:
        raise CentralCertificateVerificationError("five-term verifier or claim ID was altered")
    if certificate.statement_hash != statement.statement_hash:
        raise CentralCertificateVerificationError("five-term statement hash was altered")
    boundary = claim_boundary_hash(
        claim_id, statement, kind=ClaimKind.COMPUTED, status=EpistemicStatus.EXACT
    )
    if certificate.claim_boundary_hash != boundary:
        raise CentralCertificateVerificationError("five-term claim boundary was altered")
    if certificate.checks != FIVE_TERM_CHECKS or certificate.guarantees != FIVE_TERM_GUARANTEES:
        raise CentralCertificateVerificationError("five-term verification manifest was altered")
    if certificate.claim_dependencies or certificate.dependencies:
        raise CentralCertificateVerificationError(
            "self-contained five-term receipt has dependencies"
        )
    return CentralVerificationReport(
        valid=True,
        verifier=FIVE_TERM_VERIFIER,
        certificate_id=certificate.certificate_id,
        checks=FIVE_TERM_CHECKS,
        details=freeze_mapping({"domain_certificate": f"sha256:{domain.content_hash}"}),
    )


def _register_verifier() -> None:
    if FIVE_TERM_VERIFIER not in default_verifiers.names():
        default_verifiers.register(FIVE_TERM_VERIFIER, VerificationCertificate, _verify_semantic)


_register_verifier()


def _semantic_certificate(
    certificate: InflationRestrictionCertificate,
) -> VerificationCertificate:
    certificate.verify()
    statement = _five_term_statement(certificate)
    claim_id = _five_term_claim_id(certificate)
    return VerificationCertificate.create(
        subject=f"five-term:sha256:{certificate.content_hash}",
        verifier=FIVE_TERM_VERIFIER,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id, statement, kind=ClaimKind.COMPUTED, status=EpistemicStatus.EXACT
        ),
        witness={"inflation_restriction_certificate": certificate.to_dict()},
        checks=FIVE_TERM_CHECKS,
        guarantees=FIVE_TERM_GUARANTEES,
    )


def _claim(certificate: InflationRestrictionCertificate) -> Claim:
    semantic = _semantic_certificate(certificate)
    return Claim(
        id=_five_term_claim_id(certificate),
        statement=_five_term_statement(certificate),
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation(
            "cohom.inflation_restriction",
            method="Finite cochain maps, transgression witnesses, and exact linear algebra",
            artifact=semantic.certificate_id,
        ),
        certificate=semantic,
    )


__all__ = [
    "ExactLinearMap",
    "ExactSequence",
    "InflationRestrictionCertificate",
    "InflationRestrictionSequence",
    "inflation_restriction",
    "transgression",
]
