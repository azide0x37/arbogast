"""Certified functorial maps for exact finite-group cohomology."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from arbogast.cert import VerificationCertificate
from arbogast.claims import Claim, ClaimGraph
from arbogast.rep.maps import FiniteGroupExtension, FiniteGroupMap

from ._linear import SparseMatrix, Vector, matrix_vector, nullspace, rank
from .complex import (
    Cochain,
    CochainComplex,
    ComplexityLimits,
    InvalidGroupError,
    _element_index,
    cochain_complex,
)
from .map_certificate import (
    CohomologyMapCertificate,
    MapKind,
    _contravariant_transport,
    _corestriction_transport,
    _expected_matrix,
)
from .map_certificate import (
    claim as _claim_for_certificate,
)
from .map_certificate import (
    claim_graph as _claim_graph_for_certificate,
)
from .map_certificate import (
    verification_certificate as _verification_certificate,
)
from .results import CohomologyClass, CohomologyResult, cohomology


@dataclass(frozen=True, slots=True)
class _PrimeFieldSnapshot:
    characteristic: int

    @property
    def order(self) -> int:
        return self.characteristic


@dataclass(frozen=True, slots=True)
class _PulledBackModule:
    field: _PrimeFieldSnapshot
    dimension: int
    group_map: FiniteGroupMap
    action_matrices: tuple[tuple[tuple[int, ...], ...], ...]

    def action_matrix(self, element: Any) -> tuple[tuple[int, ...], ...]:
        index = _element_index(self.group_map.domain_elements, element)
        return self.action_matrices[index]


def _source_cochain(value: Cochain | CohomologyClass) -> Cochain:
    return value.representative if isinstance(value, CohomologyClass) else value


def _finite_group_map(
    domain: Any,
    codomain: Any,
    mapping: Any | None,
    *,
    injective: bool = False,
    surjective: bool = False,
) -> FiniteGroupMap:
    if isinstance(mapping, FiniteGroupMap):
        result = mapping
        if result.domain_snapshot != FiniteGroupMap(domain, domain, lambda x: x).domain_snapshot:
            raise ValueError("finite group map has a different domain")
        if (
            result.codomain_snapshot
            != FiniteGroupMap(codomain, codomain, lambda x: x).domain_snapshot
        ):
            raise ValueError("finite group map has a different codomain")
        if injective and not result.injective:
            raise ValueError("finite group map is not injective")
        if surjective and not result.surjective:
            raise ValueError("finite group map is not surjective")
        return result
    operation = (lambda element: element) if mapping is None else mapping
    try:
        return FiniteGroupMap(
            domain,
            codomain,
            operation,
            require_injective=injective,
            require_surjective=surjective,
        )
    except ValueError as error:
        raise InvalidGroupError(str(error)) from error


def _pulled_back_module(
    source_complex: CochainComplex, group_map: FiniteGroupMap
) -> _PulledBackModule:
    return _PulledBackModule(
        _PrimeFieldSnapshot(source_complex.prime),
        source_complex.module_dimension,
        group_map,
        tuple(
            source_complex.action_matrices[source_index] for source_index in group_map.image_indices
        ),
    )


def _certificate(
    kind: MapKind,
    source: CohomologyResult,
    target: CohomologyResult,
    group_map: FiniteGroupMap,
    *,
    transversal: tuple[int, ...] = (),
) -> CohomologyMapCertificate:
    provisional = CohomologyMapCertificate(
        schema_version="arbogast.cohomology-map.v1",
        kind=kind,
        degree=source.degree,
        source=source.certificate,
        target=target.certificate,
        source_dimension=source.dimension,
        target_dimension=target.dimension,
        map_domain=group_map.domain_snapshot,
        map_codomain=group_map.codomain_snapshot,
        image_indices=group_map.image_indices,
        transversal=transversal,
        matrix=tuple(() for _ in range(target.dimension)),
    )
    return CohomologyMapCertificate(
        schema_version=provisional.schema_version,
        kind=provisional.kind,
        degree=provisional.degree,
        source=provisional.source,
        target=provisional.target,
        source_dimension=provisional.source_dimension,
        target_dimension=provisional.target_dimension,
        map_domain=provisional.map_domain,
        map_codomain=provisional.map_codomain,
        image_indices=provisional.image_indices,
        transversal=provisional.transversal,
        matrix=_expected_matrix(provisional),
    )


@dataclass(frozen=True, slots=True)
class InducedCohomologyMap:
    """An explicit linear map between two certified cohomology quotients."""

    kind: str
    source: CohomologyResult
    target: CohomologyResult
    group_map: FiniteGroupMap
    matrix: tuple[Vector, ...]
    certificate: CohomologyMapCertificate

    @property
    def degree(self) -> int:
        return self.source.degree

    @property
    def prime(self) -> int:
        return self.source.complex.prime

    @property
    def source_dimension(self) -> int:
        return self.source.dimension

    @property
    def target_dimension(self) -> int:
        return self.target.dimension

    @property
    def rank(self) -> int:
        return rank(self.matrix, self.source_dimension, self.prime)

    @property
    def kernel_basis(self) -> tuple[Vector, ...]:
        return nullspace(SparseMatrix.from_rows(self.matrix, self.source_dimension, self.prime))

    def apply(self, value: CohomologyClass | Sequence[int]) -> CohomologyClass:
        if isinstance(value, CohomologyClass):
            if value.result.certificate.content_hash != self.source.certificate.content_hash:
                raise ValueError("cohomology class belongs to a different source quotient")
            coordinates = value.coordinates
        else:
            coordinates = tuple(value)
            if len(coordinates) != self.source_dimension:
                raise ValueError("source coordinates have the wrong dimension")
        return self.target.from_coordinates(matrix_vector(self.matrix, coordinates, self.prime))

    __call__ = apply

    def verify(self) -> bool:
        self.source.verify()
        self.target.verify()
        self.group_map.verify()
        if self.kind != self.certificate.kind or self.matrix != self.certificate.matrix:
            raise ValueError("runtime map is not bound to its receipt")
        if self.source.certificate != self.certificate.source:
            raise ValueError("runtime map source is not bound to its receipt")
        if self.target.certificate != self.certificate.target:
            raise ValueError("runtime map target is not bound to its receipt")
        self.certificate.verify()
        return True

    def certify(self) -> CohomologyMapCertificate:
        self.verify()
        return self.certificate

    def verification_certificate(self) -> VerificationCertificate:
        self.verify()
        return _verification_certificate(self.certificate)

    def claim(self) -> Claim:
        self.verify()
        return _claim_for_certificate(self.certificate)

    def claim_graph(self) -> ClaimGraph:
        self.verify()
        return _claim_graph_for_certificate(self.certificate)


CohomologyMap = InducedCohomologyMap


def _result_for_target(
    source: CohomologyResult,
    group: Any,
    module: Any,
    limits: ComplexityLimits | None,
) -> CohomologyResult:
    return cohomology(cochain_complex(group, module, source.degree, limits=limits), source.degree)


def restriction_map(
    source: CohomologyResult,
    subgroup: Any,
    inclusion: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> InducedCohomologyMap:
    """Return the certified map ``H^n(G,M) -> H^n(H,M)`` for ``n=0,1,2``."""

    if not isinstance(source, CohomologyResult):
        raise TypeError("restriction_map source must be a CohomologyResult")
    if source.degree not in (0, 1, 2):
        raise ValueError("certified induced maps are currently supported only in degrees 0-2")
    group_map = _finite_group_map(subgroup, source.complex.group, inclusion, injective=True)
    target = _result_for_target(
        source, subgroup, _pulled_back_module(source.complex, group_map), limits
    )
    certificate = _certificate("restriction", source, target, group_map)
    result = InducedCohomologyMap(
        "restriction", source, target, group_map, certificate.matrix, certificate
    )
    result.verify()
    return result


def _extension_parts(extension: Any) -> tuple[Any, Any]:
    group: Any | None = None
    projection: Any | None = None
    for name in ("group", "total_group", "source", "middle"):
        if hasattr(extension, name):
            group = getattr(extension, name)
            break
    for name in ("projection", "quotient_map", "map", "surjection"):
        if hasattr(extension, name):
            projection = getattr(extension, name)
            break
    if group is None or projection is None:
        raise TypeError("extension must expose its total group and quotient projection")
    return group, projection


def inflation_map(
    source: CohomologyResult,
    group_or_extension: Any,
    projection: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> InducedCohomologyMap:
    """Return the certified map ``H^n(Q,M) -> H^n(G,M)`` for a quotient map."""

    if not isinstance(source, CohomologyResult):
        raise TypeError("inflation_map source must be a CohomologyResult")
    if source.degree not in (0, 1, 2):
        raise ValueError("certified induced maps are currently supported only in degrees 0-2")
    if projection is None:
        if isinstance(group_or_extension, FiniteGroupExtension):
            group, projection = group_or_extension.group, group_or_extension.projection
        else:
            group, projection = _extension_parts(group_or_extension)
    else:
        group = group_or_extension
    group_map = _finite_group_map(group, source.complex.group, projection, surjective=True)
    target = _result_for_target(
        source, group, _pulled_back_module(source.complex, group_map), limits
    )
    certificate = _certificate("inflation", source, target, group_map)
    result = InducedCohomologyMap(
        "inflation", source, target, group_map, certificate.matrix, certificate
    )
    result.verify()
    return result


def _canonical_left_transversal(group_map: FiniteGroupMap) -> tuple[int, ...]:
    raw_table = group_map.codomain_snapshot["multiplication_table"]
    table = tuple(tuple(int(entry) for entry in row) for row in raw_table)
    covered: set[int] = set()
    result: list[int] = []
    for representative in range(len(group_map.codomain_elements)):
        if representative in covered:
            continue
        result.append(representative)
        covered.update(table[representative][image] for image in group_map.image_indices)
    return tuple(result)


def corestriction_map(
    source: CohomologyResult,
    ambient_group: Any,
    ambient_module: Any | None = None,
    inclusion: Any | None = None,
    *,
    transversal: Sequence[Any] | None = None,
    limits: ComplexityLimits | None = None,
) -> InducedCohomologyMap:
    """Return the certified transfer ``H^n(H,M) -> H^n(G,M)``."""

    if not isinstance(source, CohomologyResult):
        raise TypeError("corestriction_map source must be a CohomologyResult")
    if source.degree not in (0, 1, 2):
        raise ValueError("certified induced maps are currently supported only in degrees 0-2")
    group_map = _finite_group_map(source.complex.group, ambient_group, inclusion, injective=True)
    selected_module = source.complex.module if ambient_module is None else ambient_module
    target = _result_for_target(source, ambient_group, selected_module, limits)
    transversal_indices = (
        _canonical_left_transversal(group_map)
        if transversal is None
        else tuple(_element_index(group_map.codomain_elements, element) for element in transversal)
    )
    certificate = _certificate(
        "corestriction", source, target, group_map, transversal=transversal_indices
    )
    result = InducedCohomologyMap(
        "corestriction", source, target, group_map, certificate.matrix, certificate
    )
    result.verify()
    return result


def _transport_cochain(
    source: Cochain,
    target: CohomologyResult,
    certificate: CohomologyMapCertificate,
) -> Cochain:
    values = (
        _contravariant_transport(
            source.values,
            certificate.source,
            certificate.target,
            certificate.image_indices,
        )
        if certificate.kind in ("restriction", "inflation")
        else _corestriction_transport(
            source.values,
            certificate.source,
            certificate.target,
            certificate.image_indices,
            certificate.transversal,
        )
    )
    return target.complex.cochain(source.degree, values)


def _restrict_cochain(
    source: Cochain,
    subgroup: Any,
    inclusion: Any | None,
    limits: ComplexityLimits | None,
) -> Cochain:
    """The 0.1 cochain path: validate and pull back without computing cohomology."""

    group_map = _finite_group_map(subgroup, source.complex.group, inclusion, injective=True)
    target_complex = cochain_complex(
        subgroup,
        _pulled_back_module(source.complex, group_map),
        source.degree,
        limits=limits,
    )
    return target_complex.space(source.degree).from_function(
        lambda *arguments: source(*(group_map.apply(argument) for argument in arguments))
    )


def _inflate_cochain(
    source: Cochain,
    group_or_extension: Any,
    projection: Any | None,
    limits: ComplexityLimits | None,
) -> Cochain:
    """The 0.1 cochain path: validate and pull back without computing cohomology."""

    if projection is None:
        if isinstance(group_or_extension, FiniteGroupExtension):
            group, projection = group_or_extension.group, group_or_extension.projection
        else:
            group, projection = _extension_parts(group_or_extension)
    else:
        group = group_or_extension
    group_map = _finite_group_map(group, source.complex.group, projection, surjective=True)
    target_complex = cochain_complex(
        group,
        _pulled_back_module(source.complex, group_map),
        source.degree,
        limits=limits,
    )
    return target_complex.space(source.degree).from_function(
        lambda *arguments: source(*(group_map.apply(argument) for argument in arguments))
    )


def restrict(
    value: Cochain | CohomologyClass,
    subgroup: Any,
    inclusion: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> Cochain | CohomologyClass:
    """Restrict a cochain or class along an explicit subgroup inclusion."""

    source = _source_cochain(value)
    if not isinstance(value, CohomologyClass):
        return _restrict_cochain(source, subgroup, inclusion, limits)
    return restriction_map(value.result, subgroup, inclusion, limits=limits).apply(value)


def inflate(
    value: Cochain | CohomologyClass,
    group_or_extension: Any,
    projection: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> Cochain | CohomologyClass:
    """Inflate a quotient cochain or class through a checked surjection."""

    source = _source_cochain(value)
    if not isinstance(value, CohomologyClass):
        return _inflate_cochain(source, group_or_extension, projection, limits)
    return inflation_map(value.result, group_or_extension, projection, limits=limits).apply(value)


def corestrict(
    value: Cochain | CohomologyClass,
    ambient_group: Any,
    ambient_module: Any | None = None,
    inclusion: Any | None = None,
    *,
    transversal: Sequence[Any] | None = None,
    limits: ComplexityLimits | None = None,
) -> Cochain | CohomologyClass:
    """Corestrict a cochain or class using a complete finite transversal."""

    source = _source_cochain(value)
    source_result = (
        value.result
        if isinstance(value, CohomologyClass)
        else cohomology(source.complex, source.degree)
    )
    induced = corestriction_map(
        source_result,
        ambient_group,
        ambient_module,
        inclusion,
        transversal=transversal,
        limits=limits,
    )
    return (
        induced.apply(value)
        if isinstance(value, CohomologyClass)
        else _transport_cochain(source, induced.target, induced.certificate)
    )


__all__ = [
    "CohomologyMap",
    "InducedCohomologyMap",
    "corestrict",
    "corestriction_map",
    "inflate",
    "inflation_map",
    "restrict",
    "restriction_map",
]
