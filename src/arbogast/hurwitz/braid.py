"""Exact Hurwitz braid actions and finite orbit certificates.

Convention
==========

Indices are zero based.  The right Hurwitz generator ``sigma(i)`` acts on
adjacent entries by

``(a, b) -> (a*b*a^-1, a)``.

Its inverse is ``(a, b) -> (b, b^-1*a*b)``.  Products use the multiplication
law of the pinned concrete group.  This is the convention of Haefner,
arXiv:2202.08222v3, (2.4)--(2.5), with Python's zero-based slot indices.
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from arbogast.claims import Claim, ClaimGraph

from ._cert import RIGHT_HURWITZ_CONVENTION, ExactHurwitzCertificate
from ._group import ConcreteGroupContext, Element
from .errors import BraidClosureError, CertificateVerificationError
from .nielsen import NielsenClass, NielsenTuple


@dataclass(frozen=True, order=True)
class BraidMove:
    """One zero-based standard generator or its inverse."""

    index: int
    inverse: bool = False

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("braid generator index must be nonnegative")

    def inverted(self) -> BraidMove:
        return BraidMove(self.index, not self.inverse)


@dataclass(frozen=True)
class BraidWord:
    """A word in zero-based standard braid generators."""

    moves: tuple[BraidMove, ...] = ()

    @classmethod
    def generator(cls, index: int, *, inverse: bool = False) -> BraidWord:
        return cls((BraidMove(index, inverse),))

    @classmethod
    def coerce(cls, value: BraidWord | Iterable[BraidMove | tuple[int, bool] | int]) -> BraidWord:
        if isinstance(value, cls):
            return value
        moves: list[BraidMove] = []
        for item in value:
            if isinstance(item, BraidMove):
                moves.append(item)
            elif isinstance(item, tuple) and len(item) == 2:
                moves.append(BraidMove(int(item[0]), bool(item[1])))
            elif isinstance(item, int):
                if item < 0:
                    raise ValueError(
                        "signed integer braid words are ambiguous at zero; use (index, inverse)"
                    )
                moves.append(BraidMove(item, False))
            else:
                raise TypeError(f"cannot coerce {item!r} to a BraidMove")
        return cls(tuple(moves))

    def inverse(self) -> BraidWord:
        return BraidWord(tuple(move.inverted() for move in reversed(self.moves)))

    def then(self, other: BraidWord) -> BraidWord:
        """Apply this word, then ``other``."""

        return BraidWord(self.moves + other.moves)

    def __matmul__(self, other: BraidWord) -> BraidWord:
        return self.then(other)

    def __len__(self) -> int:
        return len(self.moves)

    def __iter__(self) -> Iterator[BraidMove]:
        return iter(self.moves)


@dataclass(frozen=True)
class NamedBraidGenerator:
    name: str
    word: BraidWord

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("braid generator name cannot be empty")


def pure_braid_word(left: int, right: int) -> BraidWord:
    """Return the standard pure generator ``A(left,right)`` for ``left < right``.

    With zero-based strand indices and the right action above, the chosen word is

    ``sigma(right-1)^-1 ... sigma(left+1)^-1 sigma(left)^2
       sigma(left+1) ... sigma(right-1)``.

    It induces the identity permutation of tuple slots.
    """

    if left < 0 or right <= left:
        raise ValueError("pure braid indices must satisfy 0 <= left < right")
    outward = tuple(BraidMove(index, True) for index in range(right - 1, left, -1))
    center = (BraidMove(left), BraidMove(left))
    returning = tuple(BraidMove(index) for index in range(left + 1, right))
    return BraidWord(outward + center + returning)


def _apply_move_entries(
    context: ConcreteGroupContext,
    entries: Sequence[Element],
    move: BraidMove,
) -> tuple[Element, ...]:
    if move.index + 1 >= len(entries):
        raise IndexError(
            f"sigma({move.index}) needs slots {move.index} and {move.index + 1}, "
            f"but tuple length is {len(entries)}"
        )
    result = list(entries)
    left = entries[move.index]
    right = entries[move.index + 1]
    if move.inverse:
        # (a,b) -> (b, b^-1*a*b)
        result[move.index] = right
        result[move.index + 1] = context.conjugate(left, right)
    else:
        # (a,b) -> (a*b*a^-1, a)
        result[move.index] = context.conjugate_left(right, left)
        result[move.index + 1] = left
    transformed = tuple(result)
    if context.product(transformed) != context.product(entries):
        raise CertificateVerificationError("internal Hurwitz move failed product preservation")
    return transformed


def apply_braid_word_entries(
    context: ConcreteGroupContext,
    entries: Sequence[Element],
    word: BraidWord | Iterable[BraidMove | tuple[int, bool] | int],
) -> tuple[Element, ...]:
    result = tuple(entries)
    for move in BraidWord.coerce(word):
        result = _apply_move_entries(context, result, move)
    return result


def hurwitz_move(
    value: NielsenTuple,
    index: int,
    *,
    inverse: bool = False,
) -> NielsenTuple:
    """Apply one standard generator, carrying the ordered class vector with it."""

    move = BraidMove(index, inverse)
    entries = _apply_move_entries(value.context, value.entries, move)
    classes = list(value.classes)
    classes[index], classes[index + 1] = classes[index + 1], classes[index]
    return NielsenTuple._from_context(value.context, entries, classes)


def apply_braid_word(
    value: NielsenTuple,
    word: BraidWord | Iterable[BraidMove | tuple[int, bool] | int],
) -> NielsenTuple:
    result = value
    for move in BraidWord.coerce(word):
        result = hurwitz_move(result, move.index, inverse=move.inverse)
    return result


@dataclass(frozen=True)
class BraidEdgeCertificate(ExactHurwitzCertificate):
    source_index: int
    generator_name: str
    generator_word: BraidWord
    target_index: int
    inverse_target_index: int
    canonicalizing_conjugator_index: int
    group_fingerprint: str
    class_fingerprints: tuple[str, ...]
    nielsen_source_id: str

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": "arbogast.hurwitz.braid-edge.v1",
            "layer": self.layer.value,
            "group_fingerprint": self.group_fingerprint,
            "class_fingerprints": self.class_fingerprints,
            "nielsen_source_id": self.nielsen_source_id,
            "hurwitz_convention": RIGHT_HURWITZ_CONVENTION,
            "source_index": self.source_index,
            "generator_name": self.generator_name,
            "generator_word": tuple(
                {"index": move.index, "inverse": move.inverse} for move in self.generator_word
            ),
            "target_index": self.target_index,
            "inverse_target_index": self.inverse_target_index,
            "canonicalizing_conjugator_index": self.canonicalizing_conjugator_index,
        }

    def verify(self, action: BraidAction) -> bool:
        if self.group_fingerprint != action.nielsen_class.context.fingerprint:
            raise CertificateVerificationError("braid edge group fingerprint mismatch")
        if self.class_fingerprints != tuple(
            value.fingerprint for value in action.nielsen_class.classes
        ):
            raise CertificateVerificationError("braid edge class-vector mismatch")
        if self.nielsen_source_id != action.nielsen_source_id:
            raise CertificateVerificationError("braid edge Nielsen-source mismatch")
        if not 0 <= self.source_index < len(action.nielsen_class):
            raise CertificateVerificationError("braid edge source is out of range")
        generator = action.generator_by_name(self.generator_name)
        if generator.word != self.generator_word:
            raise CertificateVerificationError("braid edge generator word mismatch")
        source = action.nielsen_class[self.source_index]
        raw = apply_braid_word_entries(source.context, source.entries, generator.word)
        witness = action.nielsen_class.canonicalize(raw)
        if witness.representative_index != self.target_index:
            raise CertificateVerificationError("braid edge target mismatch")
        if source.context.index(witness.conjugator) != self.canonicalizing_conjugator_index:
            raise CertificateVerificationError("braid edge conjugator mismatch")
        inverse_raw = apply_braid_word_entries(
            source.context,
            action.nielsen_class[self.target_index].entries,
            generator.word.inverse(),
        )
        inverse_witness = action.nielsen_class.canonicalize(inverse_raw)
        if inverse_witness.representative_index != self.inverse_target_index:
            raise CertificateVerificationError("inverse braid edge target mismatch")
        if self.inverse_target_index != self.source_index:
            raise CertificateVerificationError("forward and inverse braid edges do not cancel")
        return True

    def verification_certificate(self, action: BraidAction) -> object:
        self.verify(action)
        return self._semantic_certificate(
            subject=f"exact braid edge {self.source_index}:{self.generator_name}",
            verifier="arbogast.hurwitz.braid-edge.verify.v1",
            checks=("right-Hurwitz-move", "inner-canonicalization", "inverse-edge"),
            guarantees=("the advertised generator edge and inverse replay exactly",),
        )


@dataclass(frozen=True)
class SpanningTreeEdge:
    parent: int
    child: int
    generator_name: str
    inverse: bool


@dataclass(frozen=True)
class SpanningTreeCertificate(ExactHurwitzCertificate):
    root: int
    vertices: tuple[int, ...]
    edges: tuple[SpanningTreeEdge, ...]
    group_fingerprint: str
    class_fingerprints: tuple[str, ...]
    nielsen_source_id: str
    generator_words: tuple[tuple[str, BraidWord], ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": "arbogast.hurwitz.spanning-tree.v1",
            "layer": self.layer.value,
            "group_fingerprint": self.group_fingerprint,
            "class_fingerprints": self.class_fingerprints,
            "nielsen_source_id": self.nielsen_source_id,
            "hurwitz_convention": RIGHT_HURWITZ_CONVENTION,
            "root": self.root,
            "vertices": self.vertices,
            "generator_words": tuple(
                {
                    "name": name,
                    "moves": tuple({"index": move.index, "inverse": move.inverse} for move in word),
                }
                for name, word in self.generator_words
            ),
            "edges": tuple(
                {
                    "parent": edge.parent,
                    "child": edge.child,
                    "generator_name": edge.generator_name,
                    "inverse": edge.inverse,
                }
                for edge in self.edges
            ),
        }

    def verify(self, action: BraidAction) -> bool:
        if self.group_fingerprint != action.nielsen_class.context.fingerprint:
            raise CertificateVerificationError("spanning-tree group fingerprint mismatch")
        if self.class_fingerprints != tuple(
            value.fingerprint for value in action.nielsen_class.classes
        ):
            raise CertificateVerificationError("spanning-tree class-vector mismatch")
        if self.nielsen_source_id != action.nielsen_source_id:
            raise CertificateVerificationError("spanning-tree Nielsen-source mismatch")
        if self.generator_words != tuple(
            (generator.name, generator.word) for generator in action.generators
        ):
            raise CertificateVerificationError("spanning-tree generator-word mismatch")
        vertex_set = set(self.vertices)
        if not self.vertices or self.root not in vertex_set:
            raise CertificateVerificationError("invalid spanning-tree root")
        if len(vertex_set) != len(self.vertices):
            raise CertificateVerificationError("duplicate vertex in spanning tree")
        if len(self.edges) != len(self.vertices) - 1:
            raise CertificateVerificationError("spanning tree has the wrong edge count")
        reached = {self.root}
        remaining = list(self.edges)
        while remaining:
            progress = False
            for edge in tuple(remaining):
                if edge.parent not in reached:
                    continue
                if edge.child in reached:
                    raise CertificateVerificationError("spanning tree contains a cycle")
                target = action.step_index(edge.parent, edge.generator_name, inverse=edge.inverse)
                if target != edge.child:
                    raise CertificateVerificationError("spanning-tree edge is not a braid edge")
                if edge.child not in vertex_set:
                    raise CertificateVerificationError("spanning-tree edge leaves component")
                reached.add(edge.child)
                remaining.remove(edge)
                progress = True
            if not progress:
                raise CertificateVerificationError("spanning-tree edges are disconnected")
        if reached != vertex_set:
            raise CertificateVerificationError("spanning tree does not cover its vertices")
        return True

    def verification_certificate(self, action: BraidAction) -> object:
        self.verify(action)
        return self._semantic_certificate(
            subject=f"braid-orbit spanning tree rooted at vertex {self.root}",
            verifier="arbogast.hurwitz.spanning-tree.verify.v1",
            checks=("generator-edge-replay", "acyclic", "connected", "vertex-exhaustion"),
            guarantees=("the listed vertices lie in one connected braid orbit",),
        )


class HurwitzComponent(Sequence[NielsenTuple]):
    """One exact orbit of the configured finite braid action."""

    def __init__(
        self,
        action: BraidAction,
        vertex_indices: Sequence[int],
        certificate: SpanningTreeCertificate,
    ) -> None:
        indices = tuple(sorted(vertex_indices))
        if tuple(sorted(certificate.vertices)) != indices:
            raise CertificateVerificationError("component and spanning-tree vertices differ")
        self.action = action
        self.vertex_indices = indices
        self.certificate = certificate

    @property
    def nielsen_class(self) -> NielsenClass:
        return self.action.nielsen_class

    @property
    def cardinality(self) -> int:
        return len(self.vertex_indices)

    @property
    def representatives(self) -> tuple[NielsenTuple, ...]:
        return tuple(self.nielsen_class[index] for index in self.vertex_indices)

    def verify(self) -> bool:
        self.certificate.verify(self.action)
        vertices = set(self.vertex_indices)
        for vertex in vertices:
            for generator in self.action.generators:
                if self.action.step_index(vertex, generator.name) not in vertices:
                    raise CertificateVerificationError("component is not closed under braid action")
                if self.action.step_index(vertex, generator.name, inverse=True) not in vertices:
                    raise CertificateVerificationError("component is not inverse-closed")
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
        return len(self.vertex_indices)

    @overload
    def __getitem__(self, index: int) -> NielsenTuple: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[NielsenTuple, ...]: ...

    def __getitem__(self, index: int | slice) -> NielsenTuple | tuple[NielsenTuple, ...]:
        if isinstance(index, slice):
            return tuple(self.nielsen_class[i] for i in self.vertex_indices[index])
        return self.nielsen_class[self.vertex_indices[index]]

    def __iter__(self) -> Iterator[NielsenTuple]:
        return iter(self.representatives)


class ComponentCollection(Sequence[HurwitzComponent]):
    def __init__(self, action: BraidAction, components: Sequence[HurwitzComponent]) -> None:
        self.action = action
        self._components = tuple(components)

    def one(self) -> HurwitzComponent:
        if len(self._components) != 1:
            raise ValueError(f"expected exactly one component, found {len(self._components)}")
        return self._components[0]

    def verify(self) -> bool:
        for component in self._components:
            component.verify()
        if self._components:
            expected = set(range(len(self._components[0].nielsen_class)))
            actual: set[int] = set()
            for component in self._components:
                overlap = actual & set(component.vertex_indices)
                if overlap:
                    raise CertificateVerificationError(
                        f"component partition overlaps at vertices {sorted(overlap)}"
                    )
                actual.update(component.vertex_indices)
            if actual != expected:
                raise CertificateVerificationError("components do not partition Nielsen vertices")
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
        return len(self._components)

    @overload
    def __getitem__(self, index: int) -> HurwitzComponent: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[HurwitzComponent, ...]: ...

    def __getitem__(self, index: int | slice) -> HurwitzComponent | tuple[HurwitzComponent, ...]:
        return self._components[index]

    def __iter__(self) -> Iterator[HurwitzComponent]:
        return iter(self._components)


@dataclass(frozen=True)
class BraidPathStep:
    source_index: int
    target_index: int
    generator_name: str
    inverse: bool
    cost: float


@dataclass(frozen=True)
class BraidPath:
    action: BraidAction
    source_index: int
    target_index: int
    steps: tuple[BraidPathStep, ...]
    total_cost: float

    @property
    def distance(self) -> int:
        return len(self.steps)

    @property
    def word(self) -> BraidWord:
        result = BraidWord()
        for step in self.steps:
            generator = self.action.generator_by_name(step.generator_name)
            word = generator.word.inverse() if step.inverse else generator.word
            result = result.then(word)
        return result

    @property
    def vertices(self) -> tuple[int, ...]:
        return (self.source_index, *(step.target_index for step in self.steps))

    def verify(self) -> bool:
        current = self.source_index
        cost = 0.0
        for step in self.steps:
            if step.source_index != current:
                raise CertificateVerificationError("braid path has a discontinuity")
            target = self.action.step_index(current, step.generator_name, inverse=step.inverse)
            if target != step.target_index:
                raise CertificateVerificationError("braid path contains an invalid edge")
            if not math.isfinite(step.cost) or step.cost < 0:
                raise CertificateVerificationError("braid path has invalid edge cost")
            cost += step.cost
            current = target
        if current != self.target_index:
            raise CertificateVerificationError("braid path has wrong target")
        if not math.isclose(cost, self.total_cost, rel_tol=0.0, abs_tol=1e-12):
            raise CertificateVerificationError("braid path total cost mismatch")
        return True


class BraidAction:
    """A closed exact action of named braid words on a Nielsen dataset."""

    def __init__(
        self,
        nielsen_class: NielsenClass,
        generators: Sequence[NamedBraidGenerator],
        *,
        mode: str = "explicit",
    ) -> None:
        if len({generator.name for generator in generators}) != len(generators):
            raise ValueError("braid generator names must be unique")
        self.nielsen_class = nielsen_class
        self.generators = tuple(generators)
        self.mode = mode
        if nielsen_class.certificate is not None:
            self.nielsen_source_id = nielsen_class.certificate.certificate_id
        elif nielsen_class.imported_boundary is not None:
            self.nielsen_source_id = f"imported-sha256:{nielsen_class.imported_boundary.sha256}"
        else:
            raise BraidClosureError("Nielsen dataset has neither computed nor imported provenance")
        tuple_length = len(nielsen_class.classes)
        for generator in self.generators:
            for move in generator.word:
                if move.index + 1 >= tuple_length:
                    raise IndexError(
                        f"generator {generator.name!r} uses sigma({move.index}) "
                        f"on tuple length {tuple_length}"
                    )

        forward: dict[str, tuple[int, ...]] = {}
        backward: dict[str, tuple[int, ...]] = {}
        certificates: list[BraidEdgeCertificate] = []
        for generator in self.generators:
            fwd: list[int] = []
            inv: list[int] = []
            conjugators: list[int] = []
            for source in nielsen_class:
                raw = apply_braid_word_entries(source.context, source.entries, generator.word)
                witness = nielsen_class.canonicalize(raw)
                fwd.append(witness.representative_index)
                conjugators.append(source.context.index(witness.conjugator))
                raw_inverse = apply_braid_word_entries(
                    source.context, source.entries, generator.word.inverse()
                )
                inverse_witness = nielsen_class.canonicalize(raw_inverse)
                inv.append(inverse_witness.representative_index)
            if sorted(fwd) != list(range(len(nielsen_class))):
                raise BraidClosureError(f"generator {generator.name!r} is not bijective")
            if sorted(inv) != list(range(len(nielsen_class))):
                raise BraidClosureError(f"inverse of {generator.name!r} is not bijective")
            for index, target in enumerate(fwd):
                if inv[target] != index:
                    raise BraidClosureError(
                        f"generator {generator.name!r} and its inverse do not cancel"
                    )
                certificates.append(
                    BraidEdgeCertificate(
                        index,
                        generator.name,
                        generator.word,
                        target,
                        inv[target],
                        conjugators[index],
                        nielsen_class.context.fingerprint,
                        tuple(value.fingerprint for value in nielsen_class.classes),
                        self.nielsen_source_id,
                    )
                )
            forward[generator.name] = tuple(fwd)
            backward[generator.name] = tuple(inv)
        self._forward = forward
        self._backward = backward
        self.edge_certificates = tuple(certificates)

    def generator_by_name(self, name: str) -> NamedBraidGenerator:
        for generator in self.generators:
            if generator.name == name:
                return generator
        raise KeyError(f"unknown braid generator {name!r}")

    def index_of(self, value: int | NielsenTuple) -> int:
        if isinstance(value, int):
            if not 0 <= value < len(self.nielsen_class):
                raise IndexError("Nielsen vertex index out of range")
            return value
        return self.nielsen_class.canonicalize(value).representative_index

    def step_index(self, source: int, generator_name: str, *, inverse: bool = False) -> int:
        if not 0 <= source < len(self.nielsen_class):
            raise IndexError("Nielsen vertex index out of range")
        table = self._backward if inverse else self._forward
        try:
            return table[generator_name][source]
        except KeyError as exc:
            raise KeyError(f"unknown braid generator {generator_name!r}") from exc

    def apply(
        self,
        value: int | NielsenTuple,
        word: BraidWord | Iterable[BraidMove | tuple[int, bool] | int],
    ) -> NielsenTuple:
        source = self.nielsen_class[self.index_of(value)]
        entries = apply_braid_word_entries(source.context, source.entries, word)
        return self.nielsen_class.canonicalize(entries).representative

    def verify(self) -> bool:
        for certificate in self.edge_certificates:
            certificate.verify(self)
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

    def components(self) -> ComponentCollection:
        unseen = set(range(len(self.nielsen_class)))
        components: list[HurwitzComponent] = []
        while unseen:
            root = min(unseen)
            seen = {root}
            queue = deque([root])
            tree_edges: list[SpanningTreeEdge] = []
            while queue:
                source = queue.popleft()
                for generator in self.generators:
                    for inverse in (False, True):
                        target = self.step_index(source, generator.name, inverse=inverse)
                        if target not in seen:
                            seen.add(target)
                            queue.append(target)
                            tree_edges.append(
                                SpanningTreeEdge(source, target, generator.name, inverse)
                            )
            unseen -= seen
            vertices = tuple(sorted(seen))
            certificate = SpanningTreeCertificate(
                root,
                vertices,
                tuple(tree_edges),
                self.nielsen_class.context.fingerprint,
                tuple(value.fingerprint for value in self.nielsen_class.classes),
                self.nielsen_source_id,
                tuple((generator.name, generator.word) for generator in self.generators),
            )
            components.append(HurwitzComponent(self, vertices, certificate))
        result = ComponentCollection(self, components)
        result.verify()
        return result

    def orbits(self) -> ComponentCollection:
        return self.components()

    def braid_distance(self, source: int | NielsenTuple, target: int | NielsenTuple) -> BraidPath:
        return _shortest_path(self, self.index_of(source), self.index_of(target), None)

    def weighted_braid_path(
        self,
        source: int | NielsenTuple,
        target: int | NielsenTuple,
        costs: Mapping[str | tuple[str, bool], float] | Callable[[str, bool], float],
    ) -> BraidPath:
        return _shortest_path(self, self.index_of(source), self.index_of(target), costs)


def _edge_cost(
    costs: Mapping[str | tuple[str, bool], float] | Callable[[str, bool], float] | None,
    name: str,
    inverse: bool,
) -> float:
    if costs is None:
        return 1.0
    if callable(costs):
        value = float(costs(name, inverse))
    else:
        value = float(costs.get((name, inverse), costs.get(name, math.nan)))
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"cost for {(name, inverse)!r} must be finite and nonnegative")
    return value


def _shortest_path(
    action: BraidAction,
    source: int,
    target: int,
    costs: Mapping[str | tuple[str, bool], float] | Callable[[str, bool], float] | None,
) -> BraidPath:
    if source == target:
        return BraidPath(action, source, target, (), 0.0)
    counter = itertools.count()
    distances = {source: 0.0}
    predecessors: dict[int, tuple[int, str, bool, float]] = {}
    heap: list[tuple[float, int, int]] = [(0.0, next(counter), source)]
    while heap:
        distance, _, vertex = heapq.heappop(heap)
        if distance != distances[vertex]:
            continue
        if vertex == target:
            break
        for generator in action.generators:
            for inverse in (False, True):
                edge_cost = _edge_cost(costs, generator.name, inverse)
                neighbor = action.step_index(vertex, generator.name, inverse=inverse)
                candidate = distance + edge_cost
                # Generator iteration order and a monotone counter make ties deterministic.
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    predecessors[neighbor] = (vertex, generator.name, inverse, edge_cost)
                    heapq.heappush(heap, (candidate, next(counter), neighbor))
    if target not in distances:
        raise BraidClosureError("vertices lie in different braid components")
    reverse_steps: list[BraidPathStep] = []
    current = target
    while current != source:
        parent, name, inverse, edge_cost = predecessors[current]
        reverse_steps.append(BraidPathStep(parent, current, name, inverse, edge_cost))
        current = parent
    result = BraidPath(action, source, target, tuple(reversed(reverse_steps)), distances[target])
    result.verify()
    return result


def braid_action(
    nielsen_class: NielsenClass,
    *,
    mode: str = "full",
    generators: Sequence[
        NamedBraidGenerator | tuple[str, BraidWord | Iterable[BraidMove | tuple[int, bool] | int]]
    ]
    | None = None,
) -> BraidAction:
    """Construct a closed full, pure, or explicitly generated braid action.

    ``mode='full'`` uses every adjacent standard generator and therefore
    requires the ordered class vector to be closed under those swaps.
    ``mode='pure'`` uses all standard pure generators ``A(i,j)`` and preserves
    every ordered class vector.  ``mode='explicit'`` requires ``generators``.
    """

    length = len(nielsen_class.classes)
    if generators is not None:
        named = tuple(
            item
            if isinstance(item, NamedBraidGenerator)
            else NamedBraidGenerator(item[0], BraidWord.coerce(item[1]))
            for item in generators
        )
        actual_mode = "explicit" if mode == "full" else mode
    elif mode == "full":
        named = tuple(
            NamedBraidGenerator(f"sigma_{index}", BraidWord.generator(index))
            for index in range(length - 1)
        )
        actual_mode = mode
    elif mode == "pure":
        named = tuple(
            NamedBraidGenerator(f"A_{left}_{right}", pure_braid_word(left, right))
            for left in range(length)
            for right in range(left + 1, length)
        )
        actual_mode = mode
    elif mode == "explicit":
        raise ValueError("mode='explicit' requires generators")
    else:
        raise ValueError("mode must be 'full', 'pure', or 'explicit'")
    return BraidAction(nielsen_class, named, mode=actual_mode)


def components(value: NielsenClass | BraidAction, *, mode: str = "full") -> ComponentCollection:
    action = value if isinstance(value, BraidAction) else braid_action(value, mode=mode)
    return action.components()


def braid_distance(
    action: BraidAction,
    source: int | NielsenTuple,
    target: int | NielsenTuple,
) -> BraidPath:
    return action.braid_distance(source, target)


def weighted_braid_path(
    action: BraidAction,
    source: int | NielsenTuple,
    target: int | NielsenTuple,
    costs: Mapping[str | tuple[str, bool], float] | Callable[[str, bool], float],
) -> BraidPath:
    return action.weighted_braid_path(source, target, costs)
