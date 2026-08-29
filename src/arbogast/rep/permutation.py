"""Immutable, concrete, zero-based permutations.

The convention in this module is deliberately explicit: ``p * q`` means
``p`` after ``q``.  Thus ``(p * q)(i) == p(q(i))``.  A permutation's degree is
part of its value; no operation silently adds or removes fixed points.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from math import gcd
from struct import pack, unpack_from
from typing import ClassVar


def _lcm(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    return left // gcd(left, right) * right


@dataclass(frozen=True, slots=True, order=True)
class Permutation:
    """A permutation of ``range(degree)`` in one-line notation.

    ``images[i]`` is the image of ``i``.  Points are always zero-based.  The
    concrete degree is retained even when the final points are fixed, so a
    degree-three identity is not equal to a degree-four identity.
    """

    images: tuple[int, ...]

    COMPOSITION_CONVENTION: ClassVar[str] = "p * q means p after q: (p * q)(i) = p(q(i))"
    _ENCODING_MAGIC: ClassVar[bytes] = b"ARBOGAST-PERM\x01"

    def __init__(self, images: Iterable[int]) -> None:
        normalized = tuple(images)
        degree = len(normalized)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in normalized):
            raise TypeError("permutation images must be integers")
        if sorted(normalized) != list(range(degree)):
            raise ValueError(
                "permutation images must contain every integer from 0 through degree - 1"
            )
        object.__setattr__(self, "images", normalized)

    @classmethod
    def identity(cls, degree: int) -> Permutation:
        """Return the identity in the concrete degree ``degree``."""

        if isinstance(degree, bool) or not isinstance(degree, int):
            raise TypeError("degree must be an integer")
        if degree < 0:
            raise ValueError("degree must be nonnegative")
        return cls(range(degree))

    @classmethod
    def from_cycles(
        cls,
        degree: int,
        cycles: Iterable[Sequence[int]],
    ) -> Permutation:
        """Construct a permutation from pairwise-disjoint cycles.

        One-cycles may be supplied but are not required.  Repeated points,
        out-of-range points, and implicit degree changes are rejected.
        """

        if isinstance(degree, bool) or not isinstance(degree, int):
            raise TypeError("degree must be an integer")
        if degree < 0:
            raise ValueError("degree must be nonnegative")
        images = list(range(degree))
        seen: set[int] = set()
        for raw_cycle in cycles:
            cycle = tuple(raw_cycle)
            if not cycle:
                raise ValueError("cycles must be nonempty")
            for point in cycle:
                if isinstance(point, bool) or not isinstance(point, int):
                    raise TypeError("cycle points must be integers")
                if not 0 <= point < degree:
                    raise ValueError(f"cycle point {point} is outside degree {degree}")
                if point in seen:
                    raise ValueError(f"cycle point {point} occurs more than once")
                seen.add(point)
            for point, image in zip(cycle, cycle[1:] + cycle[:1], strict=True):
                images[point] = image
        return cls(images)

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> Permutation:
        """Decode :meth:`canonical_bytes`, rejecting noncanonical payloads."""

        if not payload.startswith(cls._ENCODING_MAGIC):
            raise ValueError("not an Arbogast permutation encoding")
        offset = len(cls._ENCODING_MAGIC)
        if len(payload) < offset + 8:
            raise ValueError("truncated permutation encoding")
        (degree,) = unpack_from(">Q", payload, offset)
        offset += 8
        expected_length = offset + 8 * degree
        if len(payload) != expected_length:
            raise ValueError("permutation encoding has the wrong length")
        images = tuple(unpack_from(">Q", payload, offset + 8 * i)[0] for i in range(degree))
        permutation = cls(images)
        if permutation.canonical_bytes() != payload:
            raise ValueError("noncanonical permutation encoding")
        return permutation

    @property
    def degree(self) -> int:
        return len(self.images)

    @property
    def is_identity(self) -> bool:
        return all(point == image for point, image in enumerate(self.images))

    @property
    def support(self) -> tuple[int, ...]:
        """The moved points, in increasing order."""

        return tuple(point for point, image in enumerate(self.images) if point != image)

    def __len__(self) -> int:
        return self.degree

    def __iter__(self) -> Iterator[int]:
        return iter(self.images)

    def __getitem__(self, point: int) -> int:
        return self.images[point]

    def __call__(self, point: int) -> int:
        if isinstance(point, bool) or not isinstance(point, int):
            raise TypeError("a permutation can only act on an integer point")
        if not 0 <= point < self.degree:
            raise IndexError(f"point {point} is outside degree {self.degree}")
        return self.images[point]

    def _require_same_degree(self, other: Permutation) -> None:
        if not isinstance(other, Permutation):
            raise TypeError("permutation composition requires another Permutation")
        if self.degree != other.degree:
            raise ValueError(
                "cannot compose concrete permutations of different degrees; "
                "use an explicit embedding or transport"
            )

    def compose(self, other: Permutation) -> Permutation:
        """Return ``self`` after ``other``.

        This is the same operation as ``self * other``.
        """

        self._require_same_degree(other)
        return Permutation(self.images[other.images[point]] for point in range(self.degree))

    def __mul__(self, other: object) -> Permutation:
        if not isinstance(other, Permutation):
            return NotImplemented
        return self.compose(other)

    def inverse(self) -> Permutation:
        inverse_images = [0] * self.degree
        for point, image in enumerate(self.images):
            inverse_images[image] = point
        return Permutation(inverse_images)

    def __invert__(self) -> Permutation:
        return self.inverse()

    def __pow__(self, exponent: int) -> Permutation:
        if isinstance(exponent, bool) or not isinstance(exponent, int):
            raise TypeError("a permutation exponent must be an integer")
        if exponent < 0:
            return self.inverse() ** (-exponent)
        result = Permutation.identity(self.degree)
        base = self
        remaining = exponent
        while remaining:
            if remaining & 1:
                result = result * base
            base = base * base
            remaining >>= 1
        return result

    def cycles(self, *, include_fixed: bool = False) -> tuple[tuple[int, ...], ...]:
        """Return disjoint cycles in deterministic canonical order.

        Each cycle begins at its least point and cycles are ordered by those
        points.  Fixed points are omitted unless ``include_fixed`` is true.
        """

        visited = [False] * self.degree
        result: list[tuple[int, ...]] = []
        for start in range(self.degree):
            if visited[start]:
                continue
            cycle: list[int] = []
            point = start
            while not visited[point]:
                visited[point] = True
                cycle.append(point)
                point = self.images[point]
            if include_fixed or len(cycle) > 1:
                result.append(tuple(cycle))
        return tuple(result)

    @property
    def disjoint_cycles(self) -> tuple[tuple[int, ...], ...]:
        return self.cycles()

    @property
    def cycle_type(self) -> tuple[int, ...]:
        """Cycle lengths, including fixed points, in decreasing order."""

        return tuple(
            sorted((len(cycle) for cycle in self.cycles(include_fixed=True)), reverse=True)
        )

    @property
    def parity(self) -> int:
        """Return ``0`` for an even permutation and ``1`` for an odd one."""

        return (self.degree - len(self.cycles(include_fixed=True))) % 2

    @property
    def sign(self) -> int:
        return -1 if self.parity else 1

    @property
    def is_even(self) -> bool:
        return self.parity == 0

    @property
    def is_odd(self) -> bool:
        return self.parity == 1

    @property
    def order(self) -> int:
        result = 1
        for cycle in self.cycles(include_fixed=True):
            result = _lcm(result, len(cycle))
        return result

    def conjugate_by(self, transport: Permutation) -> Permutation:
        """Return ``transport * self * transport.inverse()``.

        The method is explicit because Arbogast never silently moves an
        element between conjugate concrete embeddings.
        """

        self._require_same_degree(transport)
        return transport * self * transport.inverse()

    def canonical_bytes(self) -> bytes:
        """A backend-independent, stable, injective binary encoding."""

        return (
            self._ENCODING_MAGIC
            + pack(">Q", self.degree)
            + b"".join(pack(">Q", image) for image in self.images)
        )

    def canonical_encoding(self) -> bytes:
        """Alias for :meth:`canonical_bytes` used by generic serializers."""

        return self.canonical_bytes()

    def to_canonical(self) -> dict[str, object]:
        return {"type": "permutation", "degree": self.degree, "images": list(self.images)}

    def __repr__(self) -> str:
        return f"Permutation({self.images!r})"
