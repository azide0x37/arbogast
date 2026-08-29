"""Exact real structures and the classical real branch-cycle criterion."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from arbogast.claims import Claim, ClaimGraph

from ._cert import ExactHurwitzCertificate
from ._group import ConcreteGroupContext, Element
from .errors import BraidClosureError, CertificateVerificationError
from .nielsen import NielsenClass, NielsenTuple

TupleTransform = Callable[[ConcreteGroupContext, tuple[Element, ...]], tuple[Element, ...]]


def straight_real_transform(
    context: ConcreteGroupContext, entries: tuple[Element, ...]
) -> tuple[Element, ...]:
    """Complex conjugation for a straight real bouquet.

    The ``i``-th image is

    ``(g_0 ... g_(i-1)) * g_i^-1 * (g_0 ... g_(i-1))^-1``.

    This transform is product preserving and involutive on product-one tuples.
    """

    prefix = context.identity
    result: list[Element] = []
    for entry in entries:
        result.append(context.conjugate_left(context.inverse(entry), prefix))
        prefix = context.multiply(prefix, entry)
    transformed = tuple(result)
    if context.product(transformed) != context.identity:
        raise CertificateVerificationError("straight real transform lost product one")
    return transformed


def signed_slot_transform(
    slots: Sequence[tuple[int, bool]],
) -> TupleTransform:
    """Build an explicit transform from ``(source_slot, invert)`` entries."""

    frozen = tuple((int(index), bool(invert)) for index, invert in slots)

    def transform(
        context: ConcreteGroupContext, entries: tuple[Element, ...]
    ) -> tuple[Element, ...]:
        if len(frozen) != len(entries):
            raise ValueError("signed-slot real transform has the wrong arity")
        if sorted(index for index, _ in frozen) != list(range(len(entries))):
            raise ValueError("signed-slot real transform must use every input slot exactly once")
        return tuple(
            context.inverse(entries[index]) if invert else entries[index]
            for index, invert in frozen
        )

    return transform


@dataclass(frozen=True)
class RealStructureCertificate(ExactHurwitzCertificate):
    name: str
    mapping: tuple[int, ...]
    group_fingerprint: str
    class_fingerprints: tuple[str, ...]
    nielsen_source_id: str
    convention: str

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": "arbogast.hurwitz.real-structure.v1",
            "layer": self.layer.value,
            "name": self.name,
            "group_fingerprint": self.group_fingerprint,
            "class_fingerprints": self.class_fingerprints,
            "nielsen_source_id": self.nielsen_source_id,
            "convention": self.convention,
            "mapping": self.mapping,
        }

    def verify(self, structure: RealStructure) -> bool:
        if self.name != structure.name:
            raise CertificateVerificationError("real-structure name mismatch")
        if self.group_fingerprint != structure.nielsen_class.context.fingerprint:
            raise CertificateVerificationError("real-structure group mismatch")
        if self.class_fingerprints != tuple(
            value.fingerprint for value in structure.nielsen_class.classes
        ):
            raise CertificateVerificationError("real-structure class-vector mismatch")
        if self.nielsen_source_id != structure.nielsen_source_id:
            raise CertificateVerificationError("real-structure Nielsen-source mismatch")
        if self.convention != structure.convention:
            raise CertificateVerificationError("real-structure convention mismatch")
        recomputed = structure._compute_mapping()
        if recomputed != self.mapping:
            raise CertificateVerificationError("real-structure mapping mismatch")
        if sorted(self.mapping) != list(range(len(self.mapping))):
            raise CertificateVerificationError("real structure is not a permutation")
        if any(self.mapping[self.mapping[index]] != index for index in range(len(self.mapping))):
            raise CertificateVerificationError("real structure is not involutive")
        return True

    def verification_certificate(self, structure: RealStructure) -> object:
        self.verify(structure)
        return self._semantic_certificate(
            subject=f"real structure {self.name}",
            verifier="arbogast.hurwitz.real-structure.verify.v1",
            checks=("tuple-transform", "Nielsen-closure", "bijection", "involution"),
            guarantees=("the advertised map is an involution of the supplied Nielsen class",),
        )


class RealStructure:
    """An explicitly supplied involution on inner Nielsen vertices."""

    def __init__(
        self,
        nielsen_class: NielsenClass,
        transform: TupleTransform,
        *,
        name: str,
        convention: str,
        portable_transform: tuple[str, tuple[tuple[int, bool], ...] | None] | None = None,
    ) -> None:
        if not name:
            raise ValueError("real structure needs a name")
        self.nielsen_class = nielsen_class
        self.transform = transform
        self.name = name
        self.convention = convention
        self.portable_transform = portable_transform
        if nielsen_class.certificate is not None:
            self.nielsen_source_id = nielsen_class.certificate.certificate_id
        elif nielsen_class.imported_boundary is not None:
            self.nielsen_source_id = f"imported-sha256:{nielsen_class.imported_boundary.sha256}"
        else:
            raise BraidClosureError("Nielsen dataset has no explicit provenance binding")
        mapping = self._compute_mapping()
        certificate = RealStructureCertificate(
            name,
            mapping,
            nielsen_class.context.fingerprint,
            tuple(value.fingerprint for value in nielsen_class.classes),
            self.nielsen_source_id,
            convention,
        )
        self.mapping = mapping
        self.certificate = certificate
        certificate.verify(self)

    def _compute_mapping(self) -> tuple[int, ...]:
        mapping: list[int] = []
        for representative in self.nielsen_class:
            raw = tuple(self.transform(representative.context, representative.entries))
            if representative.context.product(raw) != representative.context.identity:
                raise BraidClosureError(
                    f"real structure {self.name!r} does not preserve product one"
                )
            witness = self.nielsen_class.canonicalize(raw)
            mapping.append(witness.representative_index)
        return tuple(mapping)

    def apply(self, value: int | NielsenTuple) -> NielsenTuple:
        if isinstance(value, int):
            index = value
        else:
            index = self.nielsen_class.canonicalize(value).representative_index
        if not 0 <= index < len(self.mapping):
            raise IndexError("real-structure vertex index out of range")
        return self.nielsen_class[self.mapping[index]]

    def fixed_indices(self) -> tuple[int, ...]:
        return tuple(index for index, target in enumerate(self.mapping) if index == target)

    def fixed_points(self) -> tuple[NielsenTuple, ...]:
        return tuple(self.nielsen_class[index] for index in self.fixed_indices())

    def verify(self) -> bool:
        return self.certificate.verify(self)

    def verification_certificate(self) -> object:
        """Return the claim-bound certificate accepted by the central verifier."""

        from .claims import verification_certificate_for

        return verification_certificate_for(self)

    def claim(self, *, claim_id: str | None = None) -> Claim:
        from .claims import claim_for

        return claim_for(self, claim_id=claim_id)

    def claim_graph(self, *, claim_id: str | None = None) -> ClaimGraph:
        from .claims import claim_graph_for

        return claim_graph_for(self, claim_id=claim_id)


@dataclass(frozen=True)
class RealPointWitness:
    representative_index: int
    representative: NielsenTuple
    fiber_conjugation: Element
    tuple_conjugator: Element

    def verify(self) -> bool:
        concrete = self.representative.conjugated_by(self.tuple_conjugator)
        if not is_real_tuple(concrete, self.fiber_conjugation):
            raise CertificateVerificationError(
                "real-point witness fails the branch-cycle equations"
            )
        return True


class RealCensus(Sequence[NielsenTuple]):
    """An exhaustive, policy-bound census of real inner Nielsen classes.

    Unlike :func:`real_points`, this object retains the exact witness search
    policy and the first deterministic witness for every accepted class, so it
    can cross the portable verification boundary.
    """

    def __init__(
        self,
        nielsen_class: NielsenClass,
        witnesses: Sequence[RealPointWitness],
        *,
        fiber_mode: str,
        fiber_index: int | None,
        up_to_inner: bool,
    ) -> None:
        self.nielsen_class = nielsen_class
        self.witnesses = tuple(witnesses)
        self.fiber_mode = fiber_mode
        self.fiber_index = fiber_index
        self.up_to_inner = up_to_inner
        self.verify()

    @property
    def points(self) -> tuple[NielsenTuple, ...]:
        return tuple(witness.representative for witness in self.witnesses)

    @property
    def representative_indices(self) -> tuple[int, ...]:
        return tuple(witness.representative_index for witness in self.witnesses)

    @property
    def cardinality(self) -> int:
        return len(self.witnesses)

    def verify(self) -> bool:
        if self.fiber_mode == "all_involutions":
            if self.fiber_index is not None:
                raise CertificateVerificationError(
                    "all-involutions real census cannot name a fixed fiber element"
                )
            fiber = None
        elif self.fiber_mode == "fixed":
            if self.fiber_index is None or not 0 <= self.fiber_index < len(
                self.nielsen_class.context.elements
            ):
                raise CertificateVerificationError("fixed real-census fiber index is invalid")
            fiber = self.nielsen_class.context.elements[self.fiber_index]
        else:
            raise CertificateVerificationError("unknown real-census fiber policy")
        expected = real_witnesses(
            self.nielsen_class,
            fiber,
            up_to_inner=self.up_to_inner,
        )
        if self.witnesses != expected:
            raise CertificateVerificationError(
                "real census does not match the exhaustive deterministic witness search"
            )
        return True

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
        return len(self.witnesses)

    @overload
    def __getitem__(self, index: int) -> NielsenTuple: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[NielsenTuple, ...]: ...

    def __getitem__(self, index: int | slice) -> NielsenTuple | tuple[NielsenTuple, ...]:
        return self.points[index]


def is_real_tuple(
    value: NielsenTuple,
    fiber_conjugation: Element,
    *,
    require_involution: bool = True,
) -> bool:
    """Check the exact straight-bouquet real branch-cycle equations.

    For every slot ``i`` this checks

    ``c*g_i*c^-1 = p_i*g_i^-1*p_i^-1``, where
    ``p_i = g_0*...*g_(i-1)``.  By default ``c^2=1`` is also required.
    """

    context = value.context
    if not context.contains(fiber_conjugation):
        return False
    if (
        require_involution
        and context.multiply(fiber_conjugation, fiber_conjugation) != context.identity
    ):
        return False
    target = straight_real_transform(context, value.entries)
    actual = tuple(context.conjugate_left(entry, fiber_conjugation) for entry in value.entries)
    return actual == target


def is_totally_real(value: NielsenTuple) -> bool:
    """Check the ``c=1`` real branch-cycle criterion exactly."""

    return is_real_tuple(value, value.context.identity)


def real_witnesses(
    nielsen_class: NielsenClass,
    c: Element | None = None,
    *,
    up_to_inner: bool = True,
) -> tuple[RealPointWitness, ...]:
    """Find one exact witness per inner class satisfying the real criterion.

    If ``c`` is ``None``, every involution in the concrete group is considered.
    If ``up_to_inner`` is true, concrete representatives in each inner orbit are
    checked and the required conjugator is retained in the witness.
    """

    context = nielsen_class.context
    if c is None:
        conjugations = tuple(
            element
            for element in context.elements
            if context.multiply(element, element) == context.identity
        )
    else:
        if not context.contains(c):
            raise ValueError("fiber conjugation is outside the pinned concrete group")
        if context.multiply(c, c) != context.identity:
            raise ValueError("fiber conjugation must be an involution")
        conjugations = (c,)
    tuple_conjugators = context.elements if up_to_inner else (context.identity,)
    witnesses: list[RealPointWitness] = []
    for index, representative in enumerate(nielsen_class):
        found: RealPointWitness | None = None
        for by in tuple_conjugators:
            concrete = representative.conjugated_by(by)
            for fiber_conjugation in conjugations:
                if is_real_tuple(concrete, fiber_conjugation):
                    found = RealPointWitness(index, representative, fiber_conjugation, by)
                    break
            if found is not None:
                break
        if found is not None:
            found.verify()
            witnesses.append(found)
    return tuple(witnesses)


def real_points(
    nielsen_class: NielsenClass,
    c: Element | None = None,
    *,
    up_to_inner: bool = True,
) -> tuple[NielsenTuple, ...]:
    """Return inner representatives having an exact real witness."""

    return tuple(
        witness.representative
        for witness in real_witnesses(nielsen_class, c, up_to_inner=up_to_inner)
    )


def real_census(
    nielsen_class: NielsenClass,
    c: Element | None = None,
    *,
    up_to_inner: bool = True,
) -> RealCensus:
    """Return a portable exhaustive real-point census with exact witnesses."""

    context = nielsen_class.context
    if c is None:
        fiber_mode = "all_involutions"
        fiber_index = None
    else:
        if not context.contains(c):
            raise ValueError("fiber conjugation is outside the pinned concrete group")
        if context.multiply(c, c) != context.identity:
            raise ValueError("fiber conjugation must be an involution")
        fiber_mode = "fixed"
        fiber_index = context.index(c)
    witnesses = real_witnesses(nielsen_class, c, up_to_inner=up_to_inner)
    return RealCensus(
        nielsen_class,
        witnesses,
        fiber_mode=fiber_mode,
        fiber_index=fiber_index,
        up_to_inner=up_to_inner,
    )


def totally_real(nielsen_class: NielsenClass) -> tuple[NielsenTuple, ...]:
    """Return exactly the inner classes satisfying the ``c=1`` criterion."""

    return real_points(nielsen_class, nielsen_class.context.identity)


def real_structure(
    nielsen_class: NielsenClass,
    *,
    transform: TupleTransform | None = None,
    signed_slots: Sequence[tuple[int, bool]] | None = None,
    name: str = "straight-real-bouquet",
    convention: str | None = None,
) -> RealStructure:
    """Construct and exhaustively verify an explicit Nielsen-class involution."""

    portable_transform: tuple[str, tuple[tuple[int, bool], ...] | None] | None
    if transform is not None and signed_slots is not None:
        raise ValueError("supply either transform or signed_slots, not both")
    if signed_slots is not None:
        frozen_slots = tuple((int(index), bool(invert)) for index, invert in signed_slots)
        actual = signed_slot_transform(frozen_slots)
        actual_convention = convention or "explicit signed output slots (source_index, invert)"
        portable_transform = ("signed_slots", frozen_slots)
    elif transform is not None:
        actual = transform
        actual_convention = convention or "caller-supplied exact tuple transform"
        portable_transform = None
    else:
        actual = straight_real_transform
        actual_convention = convention or ("kappa_i = (g_0...g_(i-1))*g_i^-1*(g_0...g_(i-1))^-1")
        portable_transform = ("straight", None)
    return RealStructure(
        nielsen_class,
        actual,
        name=name,
        convention=actual_convention,
        portable_transform=portable_transform,
    )
