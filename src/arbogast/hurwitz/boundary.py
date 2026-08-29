"""Exact adjacent branch-cycle collisions and finite boundary incidence."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from arbogast.claims import Claim, ClaimGraph

from ._cert import INNER_CONJUGACY_CONVENTION, ExactHurwitzCertificate
from ._group import ConcreteGroupContext, Element
from .braid import HurwitzComponent
from .errors import CertificateVerificationError, UnsupportedHurwitzOperation
from .nielsen import NielsenTuple


@dataclass(frozen=True, order=True)
class Collision:
    """An oriented adjacent collision, using zero-based tuple slots."""

    left: int
    right: int

    def validate(self, length: int) -> None:
        if length < 2:
            raise ValueError("a collision needs at least two branch cycles")
        if not 0 <= self.left < length or not 0 <= self.right < length:
            raise IndexError("collision slot is out of range")
        if self.right != (self.left + 1) % length:
            raise UnsupportedHurwitzOperation(
                "only oriented adjacent collisions are intrinsic here; braid nonadjacent "
                "cycles together explicitly before requesting the collision"
            )


class BoundaryTuple:
    """A product-one lower-point tuple after collision.

    It is intentionally not a :class:`NielsenTuple`: generation can be lost on
    the boundary and must not be silently asserted.
    """

    __slots__ = ("collision", "context", "entries", "merged_monodromy")

    def __init__(
        self,
        context: ConcreteGroupContext,
        entries: Sequence[Element],
        collision: Collision,
        merged_monodromy: Element,
    ) -> None:
        self.context = context
        self.entries = tuple(entries)
        self.collision = collision
        self.merged_monodromy = merged_monodromy
        self.verify()

    @property
    def group(self) -> object:
        return self.context.group

    @property
    def generates_group(self) -> bool:
        return self.context.is_generated_by(self.entries)

    def canonical_inner(self) -> tuple[BoundaryTuple, Element]:
        entries, by = self.context.canonical_conjugate(self.entries)
        merged = self.context.conjugate(self.merged_monodromy, by)
        return BoundaryTuple(self.context, entries, self.collision, merged), by

    def key(self) -> tuple[int, ...]:
        return self.context.tuple_key(self.entries)

    def verify(self) -> bool:
        if self.context.product(self.entries) != self.context.identity:
            raise CertificateVerificationError("boundary tuple does not have product one")
        if not self.context.contains(self.merged_monodromy):
            raise CertificateVerificationError("merged monodromy left the concrete group")
        return True

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[Element]:
        return iter(self.entries)


def collide(value: NielsenTuple, collision: Collision | tuple[int, int]) -> BoundaryTuple:
    """Merge one oriented adjacent pair while preserving cyclic product one."""

    actual = collision if isinstance(collision, Collision) else Collision(*collision)
    length = len(value)
    actual.validate(length)
    context = value.context
    left = value.entries[actual.left]
    right = value.entries[actual.right]
    merged = context.multiply(left, right)
    if actual.right == 0:
        # Cyclic order starts at old slot 1 and ends in g_(r-1) * g_0.
        entries = (*value.entries[1:-1], merged)
    else:
        entries = (
            *value.entries[: actual.left],
            merged,
            *value.entries[actual.right + 1 :],
        )
    return BoundaryTuple(context, entries, actual, merged)


@dataclass(frozen=True, order=True)
class BoundaryStratum:
    """Inner-canonical lower tuple plus exact merged-monodromy class."""

    lower_tuple_key: tuple[int, ...]
    merged_class_key: tuple[int, ...]


@dataclass(frozen=True)
class BoundaryCollisionWitness:
    source_vertex: int
    collision: Collision
    stratum: BoundaryStratum
    conjugator_index: int


def _stratum(value: NielsenTuple, collision: Collision) -> tuple[BoundaryStratum, int]:
    boundary = collide(value, collision)
    canonical, by = boundary.canonical_inner()
    merged_class = tuple(
        sorted(
            {
                value.context.index(value.context.conjugate(boundary.merged_monodromy, h))
                for h in value.context.elements
            }
        )
    )
    return BoundaryStratum(canonical.key(), merged_class), value.context.index(by)


@dataclass(frozen=True)
class BoundaryIncidenceCertificate(ExactHurwitzCertificate):
    component: HurwitzComponent
    collisions: tuple[Collision, ...]
    strata: tuple[BoundaryStratum, ...]
    matrix: tuple[tuple[int, ...], ...]
    witnesses: tuple[BoundaryCollisionWitness, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": "arbogast.hurwitz.boundary-incidence.v1",
            "layer": self.layer.value,
            "group_fingerprint": self.component.nielsen_class.context.fingerprint,
            "class_fingerprints": tuple(
                value.fingerprint for value in self.component.nielsen_class.classes
            ),
            "nielsen_source_id": self.component.action.nielsen_source_id,
            "inner_conjugacy_convention": INNER_CONJUGACY_CONVENTION,
            "component_vertices": self.component.vertex_indices,
            "collisions": tuple(
                {"left": collision.left, "right": collision.right} for collision in self.collisions
            ),
            "strata": tuple(
                {
                    "lower_tuple_key": stratum.lower_tuple_key,
                    "merged_class_key": stratum.merged_class_key,
                }
                for stratum in self.strata
            ),
            "matrix": self.matrix,
            "witnesses": tuple(
                {
                    "source_vertex": witness.source_vertex,
                    "collision": {
                        "left": witness.collision.left,
                        "right": witness.collision.right,
                    },
                    "stratum": {
                        "lower_tuple_key": witness.stratum.lower_tuple_key,
                        "merged_class_key": witness.stratum.merged_class_key,
                    },
                    "conjugator_index": witness.conjugator_index,
                }
                for witness in self.witnesses
            ),
        }

    def verify(self) -> bool:
        if len(self.matrix) != len(self.collisions):
            raise CertificateVerificationError("boundary incidence has the wrong row count")
        if any(len(row) != len(self.strata) for row in self.matrix):
            raise CertificateVerificationError("boundary incidence has the wrong column count")
        stratum_index = {stratum: index for index, stratum in enumerate(self.strata)}
        expected = [[0 for _ in self.strata] for _ in self.collisions]
        expected_witnesses: list[BoundaryCollisionWitness] = []
        for row_index, collision in enumerate(self.collisions):
            collision.validate(len(self.component.nielsen_class.classes))
            for vertex in self.component.vertex_indices:
                value = self.component.nielsen_class[vertex]
                stratum, conjugator = _stratum(value, collision)
                if stratum not in stratum_index:
                    raise CertificateVerificationError(
                        "boundary certificate omitted a reached stratum"
                    )
                expected[row_index][stratum_index[stratum]] += 1
                expected_witnesses.append(
                    BoundaryCollisionWitness(vertex, collision, stratum, conjugator)
                )
        if tuple(tuple(row) for row in expected) != self.matrix:
            raise CertificateVerificationError("boundary incidence counts mismatch")
        if tuple(expected_witnesses) != self.witnesses:
            raise CertificateVerificationError("boundary collision witnesses mismatch")
        for incidence_row in self.matrix:
            if sum(incidence_row) != len(self.component):
                raise CertificateVerificationError(
                    "each source vertex must have one image per collision"
                )
        return True

    def verification_certificate(self) -> object:
        self.verify()
        return self._semantic_certificate(
            subject="exact Hurwitz boundary incidence",
            verifier="arbogast.hurwitz.boundary-incidence.verify.v1",
            checks=(
                "adjacent-collision-product",
                "inner-canonical-lower-tuples",
                "stratum-partition",
                "incidence-counts",
            ),
            guarantees=("every source vertex has exactly one certified image per collision",),
        )


class BoundaryIncidence:
    """Collision-by-stratum incidence with exact multiplicities."""

    def __init__(self, certificate: BoundaryIncidenceCertificate) -> None:
        self.certificate = certificate
        self.component = certificate.component
        self.collisions = certificate.collisions
        self.strata = certificate.strata
        self.matrix = certificate.matrix
        self.witnesses = certificate.witnesses
        certificate.verify()

    def count(self, collision: Collision | tuple[int, int], stratum: BoundaryStratum) -> int:
        actual = collision if isinstance(collision, Collision) else Collision(*collision)
        return self.matrix[self.collisions.index(actual)][self.strata.index(stratum)]

    @property
    def total_incidences(self) -> int:
        return sum(sum(row) for row in self.matrix)

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


def boundary_incidence(
    component: HurwitzComponent,
    collisions: Collision | tuple[int, int] | Sequence[Collision | tuple[int, int]],
) -> BoundaryIncidence:
    """Compute exhaustive incidence for explicit oriented collisions."""

    actual: tuple[Collision, ...]
    if isinstance(collisions, Collision):
        actual = (collisions,)
    elif (
        isinstance(collisions, tuple)
        and len(collisions) == 2
        and all(isinstance(value, int) for value in collisions)
    ):
        actual = (Collision(*collisions),)
    else:
        collision_sequence = cast(Sequence[Collision | tuple[int, int]], collisions)
        actual = tuple(
            value if isinstance(value, Collision) else Collision(*value)
            for value in collision_sequence
        )
    if not actual:
        raise ValueError("at least one collision is required")
    if len(set(actual)) != len(actual):
        raise ValueError("collisions must be distinct")
    for collision in actual:
        collision.validate(len(component.nielsen_class.classes))

    raw: list[tuple[int, Collision, BoundaryStratum, int]] = []
    strata_set: set[BoundaryStratum] = set()
    for collision in actual:
        for vertex in component.vertex_indices:
            value = component.nielsen_class[vertex]
            stratum, conjugator = _stratum(value, collision)
            raw.append((vertex, collision, stratum, conjugator))
            strata_set.add(stratum)
    strata = tuple(sorted(strata_set))
    stratum_index = {stratum: index for index, stratum in enumerate(strata)}
    collision_index = {collision: index for index, collision in enumerate(actual)}
    matrix = [[0 for _ in strata] for _ in actual]
    witnesses: list[BoundaryCollisionWitness] = []
    for vertex, collision, stratum, conjugator in raw:
        matrix[collision_index[collision]][stratum_index[stratum]] += 1
        witnesses.append(BoundaryCollisionWitness(vertex, collision, stratum, conjugator))
    certificate = BoundaryIncidenceCertificate(
        component,
        actual,
        strata,
        tuple(tuple(row) for row in matrix),
        tuple(witnesses),
    )
    return BoundaryIncidence(certificate)


def boundary(
    value: NielsenTuple | HurwitzComponent,
    collision: Collision | tuple[int, int],
) -> BoundaryTuple | BoundaryIncidence:
    """Collide one tuple or compute a whole component's boundary incidence."""

    if isinstance(value, NielsenTuple):
        return collide(value, collision)
    return boundary_incidence(value, collision)
