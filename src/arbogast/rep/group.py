"""Small exact finite permutation groups with replayable generation proofs."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from hashlib import sha256
from struct import pack
from types import MappingProxyType

from .permutation import Permutation


@dataclass(frozen=True, slots=True, order=True)
class GeneratorStep:
    """One step in a word over an ordered concrete generator tuple."""

    generator_index: int
    inverse: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.generator_index, bool) or not isinstance(self.generator_index, int):
            raise TypeError("generator_index must be an integer")
        if self.generator_index < 0:
            raise ValueError("generator_index must be nonnegative")

    @property
    def signed_index(self) -> int:
        """The conventional signed one-based representation of this step."""

        index = self.generator_index + 1
        return -index if self.inverse else index


@dataclass(frozen=True, slots=True)
class GenerationWitness:
    """An independently replayable word proving generation of one element."""

    degree: int
    generators: tuple[Permutation, ...]
    steps: tuple[GeneratorStep, ...]
    element: Permutation

    def evaluate(self) -> Permutation:
        result = Permutation.identity(self.degree)
        for step in self.steps:
            if step.generator_index >= len(self.generators):
                raise ValueError("generation witness references a missing generator")
            generator = self.generators[step.generator_index]
            result = result * (generator.inverse() if step.inverse else generator)
        return result

    @property
    def word(self) -> tuple[int, ...]:
        """Signed one-based generator indices; the empty word is identity."""

        return tuple(step.signed_index for step in self.steps)

    def verify(self) -> bool:
        if self.element.degree != self.degree:
            return False
        if any(generator.degree != self.degree for generator in self.generators):
            return False
        try:
            return self.evaluate() == self.element
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class GenerationCertificate:
    """A finite proof that concrete generators produce exactly a target group."""

    degree: int
    generators: tuple[Permutation, ...]
    target_elements: tuple[Permutation, ...]
    witnesses: tuple[GenerationWitness, ...]

    def verify(self) -> bool:
        if tuple(witness.element for witness in self.witnesses) != self.target_elements:
            return False
        if any(
            witness.degree != self.degree
            or witness.generators != self.generators
            or not witness.verify()
            for witness in self.witnesses
        ):
            return False
        try:
            generated = PermutationGroup(self.generators, degree=self.degree)
        except (TypeError, ValueError):
            return False
        return generated.elements == self.target_elements


class PermutationGroup:
    """A deterministic, exhaustively enumerated concrete permutation group.

    This implementation is intentionally for finite exact workloads of modest
    size.  It enumerates closure by deterministic breadth-first search and
    records one word for every element.  It never identifies abstractly
    isomorphic or conjugate embeddings.
    """

    __slots__ = (
        "_canonical_bytes",
        "_class_cache",
        "_class_lookup_cache",
        "_element_set",
        "_elements",
        "_generators",
        "_identity",
        "_name",
        "_steps",
        "degree",
    )

    def __init__(
        self,
        generators: Iterable[Permutation] = (),
        *,
        degree: int | None = None,
        name: str | None = None,
    ) -> None:
        raw_generators = tuple(generators)
        if any(not isinstance(generator, Permutation) for generator in raw_generators):
            raise TypeError("all group generators must be Permutation instances")
        if degree is None:
            if not raw_generators:
                raise ValueError("degree is required when constructing a group without generators")
            degree = raw_generators[0].degree
        if isinstance(degree, bool) or not isinstance(degree, int):
            raise TypeError("degree must be an integer")
        if degree < 0:
            raise ValueError("degree must be nonnegative")
        if any(generator.degree != degree for generator in raw_generators):
            raise ValueError(
                "all generators must have the group's exact concrete degree; "
                "use an explicit embedding or transport"
            )

        # Canonical ordering makes closure and class indices independent of
        # caller container order while preserving the actual embedding.
        normalized_generators = tuple(sorted(set(raw_generators)))
        identity = Permutation.identity(degree)
        elements, steps = self._enumerate(identity, normalized_generators)

        self.degree = degree
        self._name = name
        self._identity = identity
        self._generators = normalized_generators
        self._elements = tuple(sorted(elements))
        self._element_set = frozenset(elements)
        self._steps = MappingProxyType(steps)
        self._class_cache: tuple[tuple[Permutation, ...], ...] | None = None
        self._class_lookup_cache: Mapping[Permutation, int] | None = None
        self._canonical_bytes: bytes | None = None

    @staticmethod
    def _enumerate(
        identity: Permutation,
        generators: tuple[Permutation, ...],
    ) -> tuple[set[Permutation], dict[Permutation, tuple[GeneratorStep, ...]]]:
        moves_by_element: dict[Permutation, GeneratorStep] = {}
        for index, generator in enumerate(generators):
            candidates = (
                (generator, GeneratorStep(index, False)),
                (generator.inverse(), GeneratorStep(index, True)),
            )
            for element, step in candidates:
                previous = moves_by_element.get(element)
                if previous is None or step < previous:
                    moves_by_element[element] = step
        moves = tuple(sorted(moves_by_element.items(), key=lambda pair: (pair[0], pair[1])))

        words: dict[Permutation, tuple[GeneratorStep, ...]] = {identity: ()}
        queue: deque[Permutation] = deque([identity])
        while queue:
            current = queue.popleft()
            prefix = words[current]
            for move, step in moves:
                candidate = current * move
                if candidate not in words:
                    words[candidate] = (*prefix, step)
                    queue.append(candidate)
        return set(words), words

    @classmethod
    def trivial(cls, degree: int) -> PermutationGroup:
        return cls((), degree=degree, name=f"Trivial({degree})")

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def generators(self) -> tuple[Permutation, ...]:
        return self._generators

    @property
    def elements(self) -> tuple[Permutation, ...]:
        return self._elements

    @property
    def identity(self) -> Permutation:
        return self._identity

    @property
    def order(self) -> int:
        return len(self._elements)

    def __len__(self) -> int:
        return self.order

    def __iter__(self) -> Iterator[Permutation]:
        return iter(self._elements)

    def __contains__(self, element: object) -> bool:
        return isinstance(element, Permutation) and element in self._element_set

    def contains(self, element: object) -> bool:
        return element in self

    def _require_element(self, element: Permutation, *, label: str = "element") -> None:
        if not isinstance(element, Permutation):
            raise TypeError(f"{label} must be a Permutation")
        if element.degree != self.degree:
            raise ValueError(
                f"{label} has concrete degree {element.degree}, expected {self.degree}; "
                "no implicit transport is performed"
            )
        if element not in self._element_set:
            raise ValueError(f"{label} is not an element of this concrete group")

    def multiply(self, left: Permutation, right: Permutation) -> Permutation:
        self._require_element(left, label="left factor")
        self._require_element(right, label="right factor")
        return left * right

    def inverse(self, element: Permutation) -> Permutation:
        self._require_element(element)
        return element.inverse()

    def subgroup(
        self,
        generators: Iterable[Permutation],
        *,
        name: str | None = None,
    ) -> PermutationGroup:
        normalized = tuple(generators)
        for generator in normalized:
            self._require_element(generator, label="subgroup generator")
        return PermutationGroup(normalized, degree=self.degree, name=name)

    def generated_subgroup(
        self,
        generators: Iterable[Permutation],
        *,
        name: str | None = None,
    ) -> PermutationGroup:
        return self.subgroup(generators, name=name)

    def is_generated_by(self, generators: Iterable[Permutation]) -> bool:
        normalized = tuple(generators)
        try:
            return self.subgroup(normalized).elements == self.elements
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _parse_word_step(step: GeneratorStep | int) -> GeneratorStep:
        if isinstance(step, GeneratorStep):
            return step
        if isinstance(step, bool) or not isinstance(step, int):
            raise TypeError("word entries must be GeneratorStep objects or signed integers")
        if step == 0:
            raise ValueError("signed generator word entries are one-based and cannot be zero")
        return GeneratorStep(abs(step) - 1, step < 0)

    def evaluate_word(self, word: Iterable[GeneratorStep | int]) -> Permutation:
        result = self.identity
        for raw_step in word:
            step = self._parse_word_step(raw_step)
            if step.generator_index >= len(self.generators):
                raise ValueError("word references a missing generator")
            generator = self.generators[step.generator_index]
            result = result * (generator.inverse() if step.inverse else generator)
        return result

    def generation_witness(self, element: Permutation) -> GenerationWitness:
        self._require_element(element)
        return GenerationWitness(
            degree=self.degree,
            generators=self.generators,
            steps=self._steps[element],
            element=element,
        )

    def word(self, element: Permutation) -> tuple[int, ...]:
        return self.generation_witness(element).word

    def generation_certificate(
        self,
        generators: Iterable[Permutation] | None = None,
    ) -> GenerationCertificate:
        if generators is None:
            source = self
        else:
            normalized = tuple(generators)
            source = self.subgroup(normalized)
            if source.elements != self.elements:
                raise ValueError("the supplied elements do not generate this concrete group")
        witnesses = tuple(source.generation_witness(element) for element in self.elements)
        return GenerationCertificate(
            degree=self.degree,
            generators=source.generators,
            target_elements=self.elements,
            witnesses=witnesses,
        )

    def orbit(
        self,
        point: int,
        *,
        generators: Iterable[Permutation] | None = None,
    ) -> tuple[int, ...]:
        if isinstance(point, bool) or not isinstance(point, int):
            raise TypeError("orbit point must be an integer")
        if not 0 <= point < self.degree:
            raise ValueError(f"point {point} is outside degree {self.degree}")
        acting_group = self if generators is None else self.subgroup(tuple(generators))
        return tuple(sorted({element(point) for element in acting_group.elements}))

    def orbits(self) -> tuple[tuple[int, ...], ...]:
        remaining = set(range(self.degree))
        result: list[tuple[int, ...]] = []
        while remaining:
            orbit = self.orbit(min(remaining))
            result.append(orbit)
            remaining.difference_update(orbit)
        return tuple(result)

    def is_transitive(self, points: Iterable[int] | None = None) -> bool:
        if points is None:
            return self.degree > 0 and len(self.orbit(0)) == self.degree
        domain = tuple(sorted(set(points)))
        if not domain:
            return False
        if any(
            isinstance(point, bool) or not isinstance(point, int) or not 0 <= point < self.degree
            for point in domain
        ):
            raise ValueError("transitivity domain contains a point outside the group degree")
        domain_set = set(domain)
        if any(element(point) not in domain_set for element in self.elements for point in domain):
            raise ValueError("the requested transitivity domain is not group-invariant")
        return set(self.orbit(domain[0])) == domain_set

    @property
    def transitive(self) -> bool:
        return self.is_transitive()

    def conjugate(self, element: Permutation, by: Permutation) -> Permutation:
        self._require_element(element)
        self._require_element(by, label="conjugating element")
        return by * element * by.inverse()

    def conjugacy_class(self, element: Permutation) -> tuple[Permutation, ...]:
        self._require_element(element)
        return tuple(sorted({self.conjugate(element, by) for by in self.elements}))

    def conjugacy_classes(self) -> tuple[tuple[Permutation, ...], ...]:
        if self._class_cache is None:
            remaining = set(self.elements)
            classes: list[tuple[Permutation, ...]] = []
            while remaining:
                conjugacy_class = self.conjugacy_class(min(remaining))
                classes.append(conjugacy_class)
                remaining.difference_update(conjugacy_class)
            classes.sort(key=lambda conjugacy_class: conjugacy_class[0])
            self._class_cache = tuple(classes)
        return self._class_cache

    def conjugacy_class_lookup(self) -> Mapping[Permutation, int]:
        if self._class_lookup_cache is None:
            self._class_lookup_cache = MappingProxyType(
                {
                    element: index
                    for index, conjugacy_class in enumerate(self.conjugacy_classes())
                    for element in conjugacy_class
                }
            )
        return self._class_lookup_cache

    def class_lookup(self, element: Permutation | None = None) -> Mapping[Permutation, int] | int:
        """Return the immutable lookup, or one element's zero-based class index."""

        lookup = self.conjugacy_class_lookup()
        if element is None:
            return lookup
        self._require_element(element)
        return lookup[element]

    def class_index(self, element: Permutation) -> int:
        result = self.class_lookup(element)
        assert isinstance(result, int)
        return result

    def class_of(self, element: Permutation) -> tuple[Permutation, ...]:
        return self.conjugacy_classes()[self.class_index(element)]

    def class_by_index(self, index: int) -> tuple[Permutation, ...]:
        return self.conjugacy_classes()[index]

    def centralizer(
        self,
        target: Permutation | PermutationGroup | Iterable[Permutation],
    ) -> PermutationGroup:
        targets: tuple[Permutation, ...]
        if isinstance(target, Permutation):
            self._require_element(target)
            targets = (target,)
        elif isinstance(target, PermutationGroup):
            if target.degree != self.degree or any(
                element not in self for element in target.elements
            ):
                raise ValueError("centralized subgroup is not a concrete subgroup of this group")
            targets = target.generators
        else:
            targets = tuple(target)
            for element in targets:
                self._require_element(element, label="centralized element")
        commuting = tuple(
            element
            for element in self.elements
            if all(
                element * target_element == target_element * element for target_element in targets
            )
        )
        return PermutationGroup(
            commuting, degree=self.degree, name=f"Centralizer({self.name or 'G'})"
        )

    def conjugate_by(self, transport: Permutation) -> PermutationGroup:
        """Explicitly produce the conjugate concrete embedding."""

        if not isinstance(transport, Permutation):
            raise TypeError("transport must be a Permutation")
        if transport.degree != self.degree:
            raise ValueError("transport has the wrong concrete degree")
        return PermutationGroup(
            (generator.conjugate_by(transport) for generator in self.generators),
            degree=self.degree,
            name=self.name,
        )

    def canonical_bytes(self) -> bytes:
        if self._canonical_bytes is None:
            header = b"ARBOGAST-PERM-GROUP\x01" + pack(">QQ", self.degree, self.order)
            self._canonical_bytes = header + b"".join(
                pack(">Q", len(element.canonical_bytes())) + element.canonical_bytes()
                for element in self.elements
            )
        return self._canonical_bytes

    @property
    def fingerprint(self) -> str:
        return f"sha256:{sha256(self.canonical_bytes()).hexdigest()}"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, PermutationGroup)
            and self.degree == other.degree
            and self.elements == other.elements
        )

    def __hash__(self) -> int:
        return hash((self.degree, self.elements))

    def __repr__(self) -> str:
        prefix = f"{self.name}: " if self.name else ""
        return f"PermutationGroup({prefix}degree={self.degree}, order={self.order})"


class CyclicGroup(PermutationGroup):
    """A cyclic group in a declared concrete permutation embedding.

    ``CyclicGroup(n)`` uses the regular cycle on ``n`` points.  Supplying a
    concrete ``generator`` is the explicit way to request a different pinned
    embedding; its exact order is checked.
    """

    __slots__ = ("_cyclic_generator", "_requested_order")

    def __init__(
        self,
        order: int | Permutation,
        *,
        degree: int | None = None,
        generator: Permutation | None = None,
        name: str | None = None,
    ) -> None:
        if isinstance(order, Permutation):
            if generator is not None:
                raise ValueError("provide a concrete generator only once")
            generator = order
            requested_order = generator.order
        else:
            if isinstance(order, bool) or not isinstance(order, int):
                raise TypeError("cyclic group order must be a positive integer")
            requested_order = order
        if requested_order <= 0:
            raise ValueError("cyclic group order must be positive")

        if generator is None:
            if degree is None:
                degree = requested_order
            if degree < requested_order:
                raise ValueError("the regular cycle requires degree at least the group order")
            images = list(range(degree))
            if requested_order > 1:
                for point in range(requested_order):
                    images[point] = (point + 1) % requested_order
            generator = Permutation(images)
        else:
            if degree is not None and degree != generator.degree:
                raise ValueError("declared degree does not match the concrete generator")
            degree = generator.degree
            if generator.order != requested_order:
                raise ValueError(
                    f"concrete generator has order {generator.order}, expected {requested_order}"
                )

        super().__init__((generator,), degree=degree, name=name or f"C{requested_order}")
        self._cyclic_generator = generator
        self._requested_order = requested_order

    @property
    def generator(self) -> Permutation:
        return self._cyclic_generator

    @property
    def cyclic_order(self) -> int:
        return self._requested_order


FinitePermutationGroup = PermutationGroup


def symmetric_group(degree: int) -> PermutationGroup:
    """Return the standard concrete symmetric group ``S_degree``."""

    if isinstance(degree, bool) or not isinstance(degree, int):
        raise TypeError("degree must be an integer")
    if degree < 0:
        raise ValueError("degree must be nonnegative")
    if degree <= 1:
        return PermutationGroup.trivial(degree)
    transposition = Permutation.from_cycles(degree, ((0, 1),))
    cycle = Permutation.from_cycles(degree, (tuple(range(degree)),))
    return PermutationGroup((transposition, cycle), degree=degree, name=f"S{degree}")


def cyclic_group(
    order: int | Permutation,
    *,
    degree: int | None = None,
    generator: Permutation | None = None,
) -> CyclicGroup:
    return CyclicGroup(order, degree=degree, generator=generator)
