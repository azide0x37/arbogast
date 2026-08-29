"""Cohomology spaces, classes, quotient maps, and result hooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from arbogast.cert import VerificationCertificate
from arbogast.claims import Claim as CohomologyClaim
from arbogast.claims import ClaimGraph

from ._linear import (
    Vector,
    complement_basis,
    complete_basis,
    contains,
    image_basis,
    inverse_from_columns,
    matrix_vector,
    nullspace,
    solve_columns,
)
from .certificate import CohomologyCertificate, VerificationReport
from .complex import (
    Cochain,
    CochainComplex,
    CohomologyError,
    ComplexityLimits,
    cochain_complex,
)


@dataclass(frozen=True, slots=True)
class CochainSubspace:
    """An exact linear subspace of one cochain space."""

    complex: CochainComplex
    degree: int
    basis_vectors: tuple[Vector, ...]
    kind: Literal["cocycles", "coboundaries"]

    @property
    def dimension(self) -> int:
        return len(self.basis_vectors)

    @property
    def basis(self) -> tuple[Cochain, ...]:
        return tuple(self.complex.cochain(self.degree, vector) for vector in self.basis_vectors)

    def contains(self, cochain: Cochain) -> bool:
        self._validate_cochain(cochain)
        return contains(self.basis_vectors, cochain.values, self.complex.prime)

    def coordinates(self, cochain: Cochain) -> Vector | None:
        self._validate_cochain(cochain)
        return solve_columns(self.basis_vectors, cochain.values, self.complex.prime)

    def _validate_cochain(self, cochain: Cochain) -> None:
        if (
            cochain.degree != self.degree
            or cochain.complex.content_hash != self.complex.content_hash
        ):
            raise ValueError("cochain belongs to a different canonical cochain space")


@dataclass(frozen=True, slots=True)
class QuotientMap:
    """Explicit maps ``Z^n -> H^n`` and ``H^n -> Z^n`` in canonical coordinates."""

    prime: int
    ambient_dimension: int
    projection_matrix: tuple[Vector, ...]
    section_matrix: tuple[Vector, ...]
    coboundary_basis: tuple[Vector, ...]

    @property
    def dimension(self) -> int:
        return len(self.projection_matrix)

    def project_vector(self, vector: tuple[int, ...]) -> Vector:
        if len(vector) != self.ambient_dimension:
            raise ValueError("ambient vector has the wrong dimension")
        return matrix_vector(self.projection_matrix, vector, self.prime)

    def section_vector(self, coordinates: tuple[int, ...]) -> Vector:
        if len(coordinates) != self.dimension:
            raise ValueError("quotient coordinates have the wrong dimension")
        return tuple(
            sum(
                self.section_matrix[row][column] * coordinates[column]
                for column in range(self.dimension)
            )
            % self.prime
            for row in range(self.ambient_dimension)
        )

    def equivalent(self, left: tuple[int, ...], right: tuple[int, ...]) -> bool:
        if len(left) != self.ambient_dimension or len(right) != self.ambient_dimension:
            raise ValueError("ambient vector has the wrong dimension")
        difference = tuple((a - b) % self.prime for a, b in zip(left, right, strict=True))
        return contains(self.coboundary_basis, difference, self.prime)


@dataclass(frozen=True, slots=True)
class CoboundaryWitness:
    """Decision and explicit primitive for coboundary membership."""

    is_boundary: bool
    cochain: Cochain
    primitive: Cochain | None

    def __bool__(self) -> bool:
        return self.is_boundary

    def verify(self) -> bool:
        if self.cochain.degree == 0:
            actual_is_boundary = not any(self.cochain.values)
            return self.is_boundary == actual_is_boundary and self.primitive is None
        previous = self.cochain.complex.differential(self.cochain.degree - 1)
        columns = tuple(previous.column(index) for index in range(previous.ncols))
        actual_is_boundary = (
            solve_columns(columns, self.cochain.values, self.cochain.complex.prime) is not None
        )
        if self.is_boundary != actual_is_boundary:
            return False
        if not self.is_boundary:
            return self.primitive is None
        if self.primitive is None:
            return False
        return (
            self.primitive.complex.content_hash == self.cochain.complex.content_hash
            and self.primitive.degree == self.cochain.degree - 1
            and self.primitive.differential().values == self.cochain.values
        )


@dataclass(frozen=True, slots=True)
class CohomologyClass:
    """A canonical class in one computed cohomology quotient."""

    result: CohomologyResult
    coordinates: Vector
    representative: Cochain

    def __post_init__(self) -> None:
        if len(self.coordinates) != self.result.dimension:
            raise ValueError("class coordinates have the wrong dimension")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value < self.result.complex.prime
            for value in self.coordinates
        ):
            raise ValueError("class coordinates must be canonical prime-field residues")
        if self.representative.degree != self.result.degree:
            raise ValueError("representative has the wrong cohomological degree")
        if self.representative.complex.content_hash != self.result.complex.content_hash:
            raise ValueError("representative belongs to a different cochain complex")

    @property
    def is_zero(self) -> bool:
        return not any(self.coordinates)

    @property
    def content_hash(self) -> str:
        return self.representative.content_hash

    def verify(self) -> bool:
        self.result.verify()
        if self.representative.complex.content_hash != self.result.complex.content_hash:
            raise CohomologyError("class representative belongs to a different complex")
        if not is_cocycle(self.representative):
            raise CohomologyError("class representative is not a cocycle")
        expected = self.result.quotient_map.section_vector(self.coordinates)
        if self.representative.values != expected:
            raise CohomologyError("class representative is not the canonical quotient section")
        if self.result.quotient_map.project_vector(self.representative.values) != self.coordinates:
            raise CohomologyError("representative does not have the stated quotient coordinates")
        return True

    def __add__(self, other: CohomologyClass) -> CohomologyClass:
        self._require_same_result(other)
        coordinates = tuple(
            (a + b) % self.result.complex.prime
            for a, b in zip(self.coordinates, other.coordinates, strict=True)
        )
        return self.result.from_coordinates(coordinates)

    def __rmul__(self, scalar: int) -> CohomologyClass:
        return self.result.from_coordinates(
            tuple(
                scalar * coordinate % self.result.complex.prime for coordinate in self.coordinates
            )
        )

    def _require_same_result(self, other: CohomologyClass) -> None:
        if self.result.certificate.content_hash != other.result.certificate.content_hash:
            raise ValueError("cohomology classes belong to different canonical quotients")


@dataclass(frozen=True, slots=True)
class CohomologyResult:
    """Exact ``H^n = ker(d_n) / im(d_{n-1})`` with representatives and receipt."""

    complex: CochainComplex
    degree: int
    cocycles: CochainSubspace
    coboundaries: CochainSubspace
    representative_vectors: tuple[Vector, ...]
    quotient_map: QuotientMap
    certificate: CohomologyCertificate

    @property
    def dimension(self) -> int:
        return len(self.representative_vectors)

    @property
    def representatives(self) -> tuple[Cochain, ...]:
        return tuple(
            self.complex.cochain(self.degree, vector) for vector in self.representative_vectors
        )

    @property
    def basis(self) -> tuple[CohomologyClass, ...]:
        return tuple(
            self.from_coordinates(
                tuple(1 if coordinate == index else 0 for coordinate in range(self.dimension))
            )
            for index in range(self.dimension)
        )

    def zero(self) -> CohomologyClass:
        return self.from_coordinates((0,) * self.dimension)

    def from_coordinates(self, coordinates: tuple[int, ...]) -> CohomologyClass:
        if len(coordinates) != self.dimension:
            raise ValueError("cohomology coordinates have the wrong dimension")
        reduced = tuple(value % self.complex.prime for value in coordinates)
        vector = self.quotient_map.section_vector(reduced)
        representative = self.complex.cochain(self.degree, vector)
        result = CohomologyClass(self, reduced, representative)
        result.verify()
        return result

    def class_of(self, cochain: Cochain) -> CohomologyClass:
        self._validate_cochain(cochain)
        if not self.cocycles.contains(cochain):
            raise ValueError("cochain is not a cocycle")
        coordinates = self.quotient_map.project_vector(cochain.values)
        return self.from_coordinates(coordinates)

    def is_coboundary(self, cochain: Cochain) -> CoboundaryWitness:
        self._validate_cochain(cochain)
        if not self.cocycles.contains(cochain):
            return CoboundaryWitness(False, cochain, None)
        if self.degree == 0:
            return CoboundaryWitness(not any(cochain.values), cochain, None)
        previous = self.complex.differential(self.degree - 1)
        columns = tuple(previous.column(index) for index in range(previous.ncols))
        solution = solve_columns(columns, cochain.values, self.complex.prime)
        if solution is None:
            return CoboundaryWitness(False, cochain, None)
        primitive = self.complex.cochain(self.degree - 1, solution)
        witness = CoboundaryWitness(True, cochain, primitive)
        if not witness.verify():
            raise CohomologyError("internally produced coboundary witness failed replay")
        return witness

    def verify(self) -> VerificationReport:
        self.complex.verify()
        if self.certificate.degree != self.degree:
            raise CohomologyError("certificate degree is not bound to the result")
        if self.certificate.prime != self.complex.prime:
            raise CohomologyError("certificate field is not bound to the result")
        if self.certificate.group_element_ids != self.complex.element_ids:
            raise CohomologyError("certificate group encoding is not bound to the result")
        if self.certificate.identity_index != self.complex.identity_index:
            raise CohomologyError("certificate identity is not bound to the result")
        if self.certificate.multiplication_table != self.complex.multiplication_table:
            raise CohomologyError("certificate multiplication table is not bound to the result")
        if self.certificate.module_dimension != self.complex.module_dimension:
            raise CohomologyError("certificate module dimension is not bound to the result")
        if self.certificate.action_matrices != self.complex.action_matrices:
            raise CohomologyError("certificate action is not bound to the result")
        if (
            self.certificate.differential_hashes
            != self.complex.differential_hashes[: self.degree + 1]
        ):
            raise CohomologyError("certificate differentials are not bound to the result")
        report = self.certificate.verify(limits=self.complex.limits)
        for name, subspace, expected_kind, expected_basis in (
            ("cocycles", self.cocycles, "cocycles", self.certificate.cocycle_basis),
            (
                "coboundaries",
                self.coboundaries,
                "coboundaries",
                self.certificate.coboundary_basis,
            ),
        ):
            if (
                subspace.complex.content_hash != self.complex.content_hash
                or subspace.degree != self.degree
                or subspace.kind != expected_kind
                or subspace.basis_vectors != expected_basis
            ):
                raise CohomologyError(f"result {name} are not bound to the certificate")
        if self.representative_vectors != self.certificate.representative_basis:
            raise CohomologyError("result representatives are not bound to the certificate")
        quotient = self.quotient_map
        if (
            quotient.prime != self.complex.prime
            or quotient.ambient_dimension != self.complex.space(self.degree).dimension
            or quotient.projection_matrix != self.certificate.quotient_projection
            or quotient.section_matrix != self.certificate.quotient_section
            or quotient.coboundary_basis != self.certificate.coboundary_basis
        ):
            raise CohomologyError("result quotient map is not bound to the certificate")
        return report

    def certify(self) -> CohomologyCertificate:
        """Return the independently replayable verification certificate."""

        self.verify()
        return self.certificate

    def claim(self) -> CohomologyClaim:
        """Return a central computed claim with attached replayable evidence."""

        from .semantic import claim_for_result

        return claim_for_result(self)

    def verification_certificate(self) -> VerificationCertificate:
        """Return the central certificate wrapper without replacing the domain receipt."""

        from .semantic import verification_certificate_for_result

        return verification_certificate_for_result(self)

    def claim_graph(self) -> ClaimGraph:
        """Return a one-node semantic theorem DAG for this computation."""

        from .semantic import claim_graph_for_result

        return claim_graph_for_result(self)

    def _validate_cochain(self, cochain: Cochain) -> None:
        if (
            cochain.degree != self.degree
            or cochain.complex.content_hash != self.complex.content_hash
        ):
            raise ValueError("cochain belongs to a different canonical cochain space")


class H0Result(CohomologyResult):
    """Invariant-space result ``H^0(G, M) = M^G``."""


class H1Result(CohomologyResult):
    """First group-cohomology result with explicit crossed-homomorphism representatives."""


class H2Result(CohomologyResult):
    """Second group-cohomology result with explicit obstruction representatives."""


def _build_quotient_map(
    prime: int,
    ambient_dimension: int,
    coboundary_basis: tuple[Vector, ...],
    representative_basis: tuple[Vector, ...],
) -> QuotientMap:
    initial = (*coboundary_basis, *representative_basis)
    full_basis = complete_basis(initial, ambient_dimension, prime)
    inverse = inverse_from_columns(full_basis, prime)
    boundary_dimension = len(coboundary_basis)
    quotient_dimension = len(representative_basis)
    projection = tuple(
        inverse[index]
        for index in range(boundary_dimension, boundary_dimension + quotient_dimension)
    )
    section = tuple(
        tuple(representative[row] for representative in representative_basis)
        for row in range(ambient_dimension)
    )
    return QuotientMap(
        prime,
        ambient_dimension,
        projection,
        section,
        coboundary_basis,
    )


def cohomology(complex_: CochainComplex, degree: int) -> CohomologyResult:
    """Compute exact cohomology with quotient maps and representative cocycles."""

    if degree < 0 or degree > complex_.max_degree:
        raise ValueError(f"complex supports cohomology only through degree {complex_.max_degree}")
    differential = complex_.differential(degree)
    ambient_dimension = differential.ncols
    cocycle_basis = nullspace(differential)
    if degree == 0:
        coboundary_basis: tuple[Vector, ...] = ()
    else:
        coboundary_basis = image_basis(complex_.differential(degree - 1))
    if any(not contains(cocycle_basis, vector, complex_.prime) for vector in coboundary_basis):
        raise CohomologyError("im(d_{n-1}) is not contained in ker(d_n)")
    representative_basis = complement_basis(
        coboundary_basis,
        cocycle_basis,
        ambient_dimension,
        complex_.prime,
    )
    quotient_map = _build_quotient_map(
        complex_.prime,
        ambient_dimension,
        coboundary_basis,
        representative_basis,
    )
    certificate = CohomologyCertificate(
        schema_version="arbogast.cohomology.v1",
        prime=complex_.prime,
        degree=degree,
        group_element_ids=complex_.element_ids,
        identity_index=complex_.identity_index,
        multiplication_table=complex_.multiplication_table,
        module_dimension=complex_.module_dimension,
        action_matrices=complex_.action_matrices,
        differential_hashes=complex_.differential_hashes[: degree + 1],
        cocycle_basis=cocycle_basis,
        coboundary_basis=coboundary_basis,
        representative_basis=representative_basis,
        quotient_projection=quotient_map.projection_matrix,
        quotient_section=quotient_map.section_matrix,
    )
    result_type: type[CohomologyResult]
    if degree == 0:
        result_type = H0Result
    elif degree == 1:
        result_type = H1Result
    elif degree == 2:
        result_type = H2Result
    else:
        result_type = CohomologyResult
    result = result_type(
        complex_,
        degree,
        CochainSubspace(complex_, degree, cocycle_basis, "cocycles"),
        CochainSubspace(complex_, degree, coboundary_basis, "coboundaries"),
        representative_basis,
        quotient_map,
        certificate,
    )
    result.verify()
    return result


def _ensure_complex(
    group_or_complex: Any,
    module: Any | None,
    degree: int,
    limits: ComplexityLimits | None,
) -> CochainComplex:
    if isinstance(group_or_complex, CochainComplex):
        if module is not None:
            raise TypeError("module must be omitted when a CochainComplex is supplied")
        if group_or_complex.max_degree < degree:
            raise ValueError("the supplied complex was not built through the requested degree")
        return group_or_complex
    if module is None:
        raise TypeError("module is required when supplying a group")
    return cochain_complex(group_or_complex, module, degree, limits=limits)


def h0(
    group_or_complex: Any,
    module: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> H0Result:
    complex_ = _ensure_complex(group_or_complex, module, 0, limits)
    result = cohomology(complex_, 0)
    assert isinstance(result, H0Result)
    return result


def h1(
    group_or_complex: Any,
    module: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> H1Result:
    complex_ = _ensure_complex(group_or_complex, module, 1, limits)
    result = cohomology(complex_, 1)
    assert isinstance(result, H1Result)
    return result


def h2(
    group_or_complex: Any,
    module: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> H2Result:
    complex_ = _ensure_complex(group_or_complex, module, 2, limits)
    result = cohomology(complex_, 2)
    assert isinstance(result, H2Result)
    return result


def cocycles(complex_: CochainComplex, degree: int) -> CochainSubspace:
    """Compute ``Z^degree`` from a complex containing the outgoing differential."""

    return cohomology(complex_, degree).cocycles


def coboundaries(complex_: CochainComplex, degree: int) -> CochainSubspace:
    """Compute ``B^degree`` from a complex containing the preceding differential."""

    return cohomology(complex_, degree).coboundaries


def is_cocycle(cochain: Cochain) -> bool:
    """Check the cocycle equation by applying the outgoing differential."""

    return not any(cochain.differential().values)


def is_coboundary(
    cochain: Cochain,
    result: CohomologyResult | None = None,
) -> CoboundaryWitness:
    """Decide boundary membership and return an explicit primitive when one exists."""

    selected = result or cohomology(cochain.complex, cochain.degree)
    return selected.is_coboundary(cochain)


def class_of(
    cochain: Cochain,
    result: CohomologyResult | None = None,
) -> CohomologyClass:
    """Reduce a cocycle to canonical quotient coordinates and representative."""

    selected = result or cohomology(cochain.complex, cochain.degree)
    return selected.class_of(cochain)


H0 = h0
H1 = h1
H2 = h2


__all__ = [
    "H0",
    "H1",
    "H2",
    "CoboundaryWitness",
    "CochainSubspace",
    "CohomologyClaim",
    "CohomologyClass",
    "CohomologyResult",
    "H0Result",
    "H1Result",
    "H2Result",
    "QuotientMap",
    "class_of",
    "coboundaries",
    "cocycles",
    "cohomology",
    "h0",
    "h1",
    "h2",
    "is_coboundary",
    "is_cocycle",
]
