"""Riemann--Hurwitz, explicit reduced quotients, and cusp cycles."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from arbogast.claims import Claim, ClaimGraph

from ._cert import RIGHT_HURWITZ_CONVENTION, ExactHurwitzCertificate
from .braid import BraidWord, HurwitzComponent, apply_braid_word_entries
from .errors import CertificateVerificationError, UnsupportedHurwitzOperation
from .nielsen import NielsenTuple


def _permutation_images(element: object, degree: int) -> tuple[int, ...]:
    for name in ("images", "one_line", "values"):
        if hasattr(element, name):
            value = getattr(element, name)
            raw = value() if callable(value) else value
            break
    else:
        if isinstance(element, (tuple, list)):
            raw = element
        else:
            raise UnsupportedHurwitzOperation(
                "source_genus needs concrete permutation images; no abstract-group "
                "embedding is inferred"
            )
    images = tuple(int(value) for value in raw)
    if len(images) != degree:
        raise UnsupportedHurwitzOperation(
            f"permutation has degree {len(images)}, expected pinned degree {degree}"
        )
    if sorted(images) != list(range(degree)):
        raise UnsupportedHurwitzOperation(
            "permutation images must be the zero-based set {0,...,degree-1}"
        )
    return images


def _cycle_count(images: Sequence[int]) -> int:
    seen: set[int] = set()
    count = 0
    for start in range(len(images)):
        if start in seen:
            continue
        count += 1
        current = start
        while current not in seen:
            seen.add(current)
            current = images[current]
    return count


@dataclass(frozen=True)
class SourceGenusCertificate(ExactHurwitzCertificate):
    degree: int
    cycle_counts: tuple[int, ...]
    indices: tuple[int, ...]
    genus: int
    group_fingerprint: str
    class_fingerprints: tuple[str, ...]
    tuple_key: tuple[int, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": "arbogast.hurwitz.source-genus.v1",
            "layer": self.layer.value,
            "group_fingerprint": self.group_fingerprint,
            "class_fingerprints": self.class_fingerprints,
            "tuple_key": self.tuple_key,
            "degree": self.degree,
            "cycle_counts": self.cycle_counts,
            "permutation_indices": self.indices,
            "genus": self.genus,
            "formula": "2g-2=-2*degree+sum(permutation_index)",
        }

    def verify(self, value: NielsenTuple) -> bool:
        degree = getattr(value.group, "degree", None)
        if self.group_fingerprint != value.context.fingerprint:
            raise CertificateVerificationError("source-genus group fingerprint mismatch")
        if self.class_fingerprints != tuple(item.fingerprint for item in value.classes):
            raise CertificateVerificationError("source-genus class-vector mismatch")
        if self.tuple_key != value.key():
            raise CertificateVerificationError("source-genus tuple binding mismatch")
        if not isinstance(degree, int) or degree <= 0:
            raise CertificateVerificationError("group has no positive concrete permutation degree")
        cycle_counts = tuple(
            _cycle_count(_permutation_images(entry, degree)) for entry in value.entries
        )
        indices = tuple(degree - count for count in cycle_counts)
        numerator = 2 - 2 * degree + sum(indices)
        if numerator % 2:
            raise CertificateVerificationError("Riemann--Hurwitz numerator is odd")
        genus = numerator // 2
        if genus < 0:
            raise CertificateVerificationError("Riemann--Hurwitz produced negative genus")
        if (
            degree != self.degree
            or cycle_counts != self.cycle_counts
            or indices != self.indices
            or genus != self.genus
        ):
            raise CertificateVerificationError("source-genus certificate mismatch")
        return True

    def verification_certificate(self, value: NielsenTuple) -> object:
        self.verify(value)
        return self._semantic_certificate(
            subject="source-cover genus by Riemann-Hurwitz",
            verifier="arbogast.hurwitz.source-genus.verify.v1",
            checks=("permutation-cycle-counts", "indices", "Riemann-Hurwitz"),
            guarantees=("the source-cover genus equals the advertised integer",),
        )


@dataclass(frozen=True)
class SourceGenusResult:
    genus: int
    certificate: SourceGenusCertificate
    source: NielsenTuple | None = None

    def verify(self, value: NielsenTuple) -> bool:
        if self.genus != self.certificate.genus:
            raise CertificateVerificationError("source-genus result/certificate mismatch")
        return self.certificate.verify(value)

    def __int__(self) -> int:
        return self.genus

    def __index__(self) -> int:
        return self.genus

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.genus == other
        if isinstance(other, SourceGenusResult):
            return self.genus == other.genus and self.certificate == other.certificate
        return NotImplemented

    def claim(self, *, claim_id: str | None = None) -> Claim:
        from .claims import claim_for

        return claim_for(self, claim_id=claim_id)

    def claim_graph(self, *, claim_id: str | None = None) -> ClaimGraph:
        from .claims import claim_graph_for

        return claim_graph_for(self, claim_id=claim_id)


def source_genus_result(value: NielsenTuple) -> SourceGenusResult:
    """Compute the source-cover genus in the pinned permutation representation."""

    degree = getattr(value.group, "degree", None)
    if not isinstance(degree, int) or degree <= 0:
        raise UnsupportedHurwitzOperation(
            "source_genus requires group.degree from an explicit permutation action"
        )
    cycle_counts = tuple(
        _cycle_count(_permutation_images(entry, degree)) for entry in value.entries
    )
    indices = tuple(degree - count for count in cycle_counts)
    numerator = 2 - 2 * degree + sum(indices)
    if numerator % 2:
        raise UnsupportedHurwitzOperation("Riemann--Hurwitz numerator is not even")
    genus = numerator // 2
    if genus < 0:
        raise UnsupportedHurwitzOperation(
            "branch-cycle data gives a negative source genus; input convention is inconsistent"
        )
    certificate = SourceGenusCertificate(
        degree,
        cycle_counts,
        indices,
        genus,
        value.context.fingerprint,
        tuple(item.fingerprint for item in value.classes),
        value.key(),
    )
    result = SourceGenusResult(genus, certificate, value)
    result.verify(value)
    return result


def source_genus(value: NielsenTuple) -> int:
    """Return the exact source genus (not the genus of a Hurwitz parameter curve)."""

    return source_genus_result(value).genus


@dataclass(frozen=True)
class ExplicitSymmetry:
    """A named, fully materialized permutation of component vertices."""

    name: str
    mapping: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("symmetry name cannot be empty")
        if len(set(self.mapping)) != len(self.mapping):
            raise ValueError("explicit symmetry mapping must be injective")

    def inverse(self) -> ExplicitSymmetry:
        result = [0] * len(self.mapping)
        for source, target in enumerate(self.mapping):
            if not 0 <= target < len(self.mapping):
                raise ValueError("explicit symmetry target is out of range")
            result[target] = source
        return ExplicitSymmetry(f"{self.name}^-1", tuple(result))


@dataclass(frozen=True)
class ReducedQuotientCertificate(ExactHurwitzCertificate):
    component: HurwitzComponent
    component_vertices: tuple[int, ...]
    symmetries: tuple[ExplicitSymmetry, ...]
    blocks: tuple[tuple[int, ...], ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": "arbogast.hurwitz.reduced-quotient.v1",
            "layer": self.layer.value,
            "group_fingerprint": self.component.nielsen_class.context.fingerprint,
            "class_fingerprints": tuple(
                value.fingerprint for value in self.component.nielsen_class.classes
            ),
            "nielsen_source_id": self.component.action.nielsen_source_id,
            "hurwitz_convention": RIGHT_HURWITZ_CONVENTION,
            "component_vertices": self.component_vertices,
            "symmetries": tuple(
                {"name": symmetry.name, "mapping": symmetry.mapping} for symmetry in self.symmetries
            ),
            "blocks": self.blocks,
        }

    def verify(self) -> bool:
        if self.component_vertices != self.component.vertex_indices:
            raise CertificateVerificationError("reduced certificate component binding mismatch")
        vertex_set = set(self.component_vertices)
        if len(vertex_set) != len(self.component_vertices):
            raise CertificateVerificationError("reduced source vertices contain duplicates")
        for symmetry in self.symmetries:
            if len(symmetry.mapping) != len(self.component_vertices):
                raise CertificateVerificationError("symmetry mapping has wrong size")
            if sorted(symmetry.mapping) != list(range(len(self.component_vertices))):
                raise CertificateVerificationError("symmetry mapping is not a permutation")
        flattened = [vertex for block in self.blocks for vertex in block]
        if any(not block for block in self.blocks):
            raise CertificateVerificationError("reduced quotient contains an empty block")
        if len(flattened) != len(set(flattened)) or set(flattened) != vertex_set:
            raise CertificateVerificationError("reduced blocks do not partition component")
        vertex_to_local = {vertex: local for local, vertex in enumerate(self.component_vertices)}
        for block in self.blocks:
            block_set = set(block)
            for vertex in block:
                local = vertex_to_local[vertex]
                for symmetry in self.symmetries:
                    target_global = self.component_vertices[symmetry.mapping[local]]
                    if target_global not in block_set:
                        raise CertificateVerificationError(
                            "reduced block is not closed under explicit symmetry"
                        )
            reached = {block[0]}
            queue = deque((block[0],))
            while queue:
                source = queue.popleft()
                local = vertex_to_local[source]
                for symmetry in self.symmetries:
                    for mapping in (symmetry.mapping, symmetry.inverse().mapping):
                        target = self.component_vertices[mapping[local]]
                        if target not in reached:
                            reached.add(target)
                            queue.append(target)
            if reached != block_set:
                raise CertificateVerificationError(
                    "reduced block merges distinct explicit-symmetry orbits"
                )
        return True

    def verification_certificate(self) -> object:
        self.verify()
        return self._semantic_certificate(
            subject="reduced Hurwitz component by explicit finite symmetry",
            verifier="arbogast.hurwitz.reduced-quotient.verify.v1",
            checks=("symmetry-bijections", "orbit-partition", "source-exhaustion"),
            guarantees=("blocks are exactly the orbits of the supplied explicit symmetries",),
        )


class ReducedComponent(Sequence[tuple[NielsenTuple, ...]]):
    """The orbit quotient by an explicitly supplied finite symmetry action."""

    def __init__(
        self,
        component: HurwitzComponent,
        blocks: Sequence[Sequence[int]],
        certificate: ReducedQuotientCertificate,
    ) -> None:
        self.component = component
        self.blocks = tuple(tuple(sorted(block)) for block in blocks)
        self.certificate = certificate
        self._block_of = {
            vertex: block_index for block_index, block in enumerate(self.blocks) for vertex in block
        }
        certificate.verify()

    @property
    def cardinality(self) -> int:
        return len(self.blocks)

    @property
    def quotient_edges(self) -> tuple[tuple[int, str, int], ...]:
        edges: set[tuple[int, str, int]] = set()
        action = self.component.action
        for block_index, block in enumerate(self.blocks):
            for vertex in block:
                for generator in action.generators:
                    target = action.step_index(vertex, generator.name)
                    edges.add((block_index, generator.name, self._block_of[target]))
        return tuple(sorted(edges))

    def verify(self) -> bool:
        return self.certificate.verify()

    def verification_certificate(self) -> object:
        from .claims import verification_certificate_for

        return verification_certificate_for(self)

    def claim(self, *, claim_id: str | None = None) -> Claim:
        from .claims import claim_for

        return claim_for(self, claim_id=claim_id)

    def claim_graph(self, *, claim_id: str | None = None) -> ClaimGraph:
        from .claims import claim_graph_for

        return claim_graph_for(self, claim_id=claim_id)

    def __len__(self) -> int:
        return len(self.blocks)

    @overload
    def __getitem__(self, index: int) -> tuple[NielsenTuple, ...]: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[tuple[NielsenTuple, ...], ...]: ...

    def __getitem__(
        self, index: int | slice
    ) -> tuple[NielsenTuple, ...] | tuple[tuple[NielsenTuple, ...], ...]:
        if isinstance(index, slice):
            return tuple(
                tuple(self.component.nielsen_class[vertex] for vertex in block)
                for block in self.blocks[index]
            )
        return tuple(self.component.nielsen_class[vertex] for vertex in self.blocks[index])

    def __iter__(self) -> Iterator[tuple[NielsenTuple, ...]]:
        for index in range(len(self.blocks)):
            yield self[index]


def symmetry_from_braid_word(
    component: HurwitzComponent,
    word: BraidWord,
    *,
    name: str = "explicit-braid-symmetry",
) -> ExplicitSymmetry:
    """Materialize a braid word as a permutation of one component."""

    local_of = {vertex: local for local, vertex in enumerate(component.vertex_indices)}
    mapping: list[int] = []
    for vertex in component.vertex_indices:
        representative = component.nielsen_class[vertex]
        entries = apply_braid_word_entries(representative.context, representative.entries, word)
        target = component.nielsen_class.canonicalize(entries).representative_index
        try:
            mapping.append(local_of[target])
        except KeyError as exc:
            raise ValueError("explicit symmetry braid word leaves the component") from exc
    return ExplicitSymmetry(name, tuple(mapping))


def reduced(
    component: HurwitzComponent,
    symmetries: Sequence[ExplicitSymmetry | tuple[str, BraidWord]],
) -> ReducedComponent:
    """Quotient by supplied symmetries; no mapping-class quotient is inferred."""

    if not symmetries:
        raise ValueError("reduced quotient requires at least one explicit symmetry")
    explicit = tuple(
        symmetry
        if isinstance(symmetry, ExplicitSymmetry)
        else symmetry_from_braid_word(component, symmetry[1], name=symmetry[0])
        for symmetry in symmetries
    )
    size = len(component)
    for symmetry in explicit:
        if len(symmetry.mapping) != size or sorted(symmetry.mapping) != list(range(size)):
            raise ValueError(f"symmetry {symmetry.name!r} is not a permutation of the component")

    unseen = set(range(size))
    blocks: list[tuple[int, ...]] = []
    while unseen:
        root = min(unseen)
        local_orbit = {root}
        queue = deque([root])
        while queue:
            source = queue.popleft()
            for symmetry in explicit:
                for mapping in (symmetry.mapping, symmetry.inverse().mapping):
                    target = mapping[source]
                    if target not in local_orbit:
                        local_orbit.add(target)
                        queue.append(target)
        unseen -= local_orbit
        blocks.append(tuple(component.vertex_indices[local] for local in sorted(local_orbit)))
    blocks.sort()
    certificate = ReducedQuotientCertificate(
        component, component.vertex_indices, explicit, tuple(blocks)
    )
    return ReducedComponent(component, blocks, certificate)


@dataclass(frozen=True)
class Cusp:
    vertices: tuple[int, ...]
    width: int

    def __post_init__(self) -> None:
        if self.width != len(self.vertices) or self.width <= 0:
            raise ValueError("cusp width must equal its positive cycle length")


@dataclass(frozen=True)
class CuspCertificate(ExactHurwitzCertificate):
    component: HurwitzComponent
    operator_name: str
    operator_word: BraidWord
    mapping: tuple[int, ...]
    cusps: tuple[Cusp, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": "arbogast.hurwitz.cusps.v1",
            "layer": self.layer.value,
            "group_fingerprint": self.component.nielsen_class.context.fingerprint,
            "class_fingerprints": tuple(
                value.fingerprint for value in self.component.nielsen_class.classes
            ),
            "nielsen_source_id": self.component.action.nielsen_source_id,
            "hurwitz_convention": RIGHT_HURWITZ_CONVENTION,
            "component_vertices": self.component.vertex_indices,
            "operator_name": self.operator_name,
            "operator_word": tuple(
                {"index": move.index, "inverse": move.inverse} for move in self.operator_word
            ),
            "mapping": self.mapping,
            "cusps": tuple({"vertices": cusp.vertices, "width": cusp.width} for cusp in self.cusps),
        }

    def verify(self) -> bool:
        if self.mapping != _cusp_mapping(self.component, self.operator_word):
            raise CertificateVerificationError("cusp operator mapping does not replay")
        if sorted(self.mapping) != list(range(len(self.mapping))):
            raise CertificateVerificationError("cusp operator is not a permutation")
        seen: set[int] = set()
        for cusp in self.cusps:
            if set(cusp.vertices) & seen:
                raise CertificateVerificationError("cusp cycles overlap")
            seen.update(cusp.vertices)
            for source, target in zip(
                cusp.vertices, cusp.vertices[1:] + cusp.vertices[:1], strict=True
            ):
                if self.mapping[source] != target:
                    raise CertificateVerificationError("cusp is not a cycle of its operator")
        if seen != set(range(len(self.mapping))):
            raise CertificateVerificationError("cusp cycles do not exhaust component")
        return True

    def verification_certificate(self) -> object:
        self.verify()
        return self._semantic_certificate(
            subject=f"cusp cycles for {self.operator_name}",
            verifier="arbogast.hurwitz.cusps.verify.v1",
            checks=("operator-replay", "cycle-partition", "widths"),
            guarantees=("the listed cusps exhaust the component with exact widths",),
        )


class CuspData(Sequence[Cusp]):
    def __init__(self, component: HurwitzComponent, certificate: CuspCertificate) -> None:
        self.component = component
        self.certificate = certificate
        self._cusps = certificate.cusps
        certificate.verify()

    @property
    def widths(self) -> tuple[int, ...]:
        return tuple(cusp.width for cusp in self._cusps)

    def verify(self) -> bool:
        return self.certificate.verify()

    def verification_certificate(self) -> object:
        from .claims import verification_certificate_for

        return verification_certificate_for(self)

    def claim(self, *, claim_id: str | None = None) -> Claim:
        from .claims import claim_for

        return claim_for(self, claim_id=claim_id)

    def claim_graph(self, *, claim_id: str | None = None) -> ClaimGraph:
        from .claims import claim_graph_for

        return claim_graph_for(self, claim_id=claim_id)

    def __len__(self) -> int:
        return len(self._cusps)

    @overload
    def __getitem__(self, index: int) -> Cusp: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Cusp, ...]: ...

    def __getitem__(self, index: int | slice) -> Cusp | tuple[Cusp, ...]:
        return self._cusps[index]

    def __iter__(self) -> Iterator[Cusp]:
        return iter(self._cusps)


def cusps(
    component: HurwitzComponent,
    operator: str | BraidWord,
    *,
    name: str | None = None,
) -> CuspData:
    """Compute exact cusp cycles and widths for an explicit braid operator."""

    if isinstance(operator, str):
        operator_name = name or operator
        operator_word = component.action.generator_by_name(operator).word
    else:
        operator_name = name or "explicit-cusp-braid-word"
        operator_word = operator
    mapping = list(_cusp_mapping(component, operator_word))
    if sorted(mapping) != list(range(len(mapping))):
        raise CertificateVerificationError("cusp operator is not bijective")
    unseen = set(range(len(mapping)))
    cusp_values: list[Cusp] = []
    while unseen:
        start = min(unseen)
        cycle: list[int] = []
        current = start
        while current not in cycle:
            cycle.append(current)
            current = mapping[current]
        if current != start:
            raise CertificateVerificationError("cusp walk entered a previous cycle")
        unseen -= set(cycle)
        global_vertices = tuple(component.vertex_indices[local] for local in cycle)
        # The certificate mapping is local, so record local cycle positions there.
        cusp_values.append(Cusp(tuple(cycle), len(cycle)))
        _ = global_vertices  # retained conceptually; component provides the local/global binding.
    certificate = CuspCertificate(
        component, operator_name, operator_word, tuple(mapping), tuple(cusp_values)
    )
    return CuspData(component, certificate)


def _cusp_mapping(component: HurwitzComponent, word: BraidWord) -> tuple[int, ...]:
    local_of = {vertex: local for local, vertex in enumerate(component.vertex_indices)}
    mapping: list[int] = []
    for vertex in component.vertex_indices:
        representative = component.nielsen_class[vertex]
        entries = apply_braid_word_entries(representative.context, representative.entries, word)
        target = component.nielsen_class.canonicalize(entries).representative_index
        if target not in local_of:
            raise ValueError("cusp operator leaves component")
        mapping.append(local_of[target])
    return tuple(mapping)
