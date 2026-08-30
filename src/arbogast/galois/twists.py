"""Exhaustive finite nonabelian H1 as a pointed set of cocycle orbits."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from arbogast.cert import VerificationCertificate, default_verifiers
from arbogast.claims import Claim, ClaimGraph

from ._common import (
    Rows,
    Vector,
    canonical_group_elements,
    canonical_permutation_or_value,
    group_identity,
    inverse_table,
    multiplication_table,
)
from .certificate import TwistReceipt
from .proof import Unsupported

Action = Callable[[object, object], object]


def _action_function(action: object | None) -> Action:
    if action is None or action == "trivial":
        return lambda _group_element, coefficient: coefficient
    if callable(action):
        return cast(Action, action)
    for name in ("apply", "act"):
        method = getattr(action, name, None)
        if callable(method):
            return cast(Action, method)
    if isinstance(action, Mapping):
        mapping = action

        def apply(group_element: object, coefficient: object) -> object:
            selected = mapping[group_element]
            if callable(selected):
                return selected(coefficient)
            if isinstance(selected, Mapping):
                return selected[coefficient]
            raise TypeError("action mapping values must be callables or element mappings")

        return apply
    raise TypeError("action must be callable, a mapping, an action object, or None")


@dataclass(frozen=True, slots=True)
class NonabelianCocycle:
    """One multiplicative crossed homomorphism ``G -> A``."""

    parent: TwistClassSet
    index: int
    image_indices: Vector

    @property
    def acting_elements(self) -> tuple[object, ...]:
        return self.parent.acting_elements

    @property
    def coefficient_elements(self) -> tuple[object, ...]:
        return self.parent.coefficient_elements

    @property
    def values(self) -> tuple[object, ...]:
        return tuple(self.coefficient_elements[index] for index in self.image_indices)

    def __call__(self, element: object) -> object:
        try:
            index = self.acting_elements.index(element)
        except ValueError as error:
            raise ValueError("element lies outside the cocycle's acting group") from error
        return self.coefficient_elements[self.image_indices[index]]

    @property
    def certificate(self) -> VerificationCertificate:
        return self.parent.certificate

    def verify(self) -> bool:
        self.parent.verify()
        return (
            0 <= self.index < len(self.parent.cocycle_indices)
            and self.parent.cocycle_indices[self.index] == self.image_indices
        )

    def claim(self) -> Claim:
        return self.parent.claim()

    def claim_graph(self) -> ClaimGraph:
        return self.parent.claim_graph()

    def to_canonical(self) -> dict[str, object]:
        return {
            "acting_elements": tuple(
                canonical_permutation_or_value(item) for item in self.acting_elements
            ),
            "coefficient_elements": tuple(
                canonical_permutation_or_value(item) for item in self.coefficient_elements
            ),
            "image_indices": self.image_indices,
            "index": self.index,
            "parent": self.parent.content_id,
            "type": "arbogast.nonabelian_cocycle",
        }


@dataclass(frozen=True, slots=True)
class TwistClass:
    """One coefficient-conjugacy orbit of nonabelian cocycles."""

    parent: TwistClassSet
    index: int
    cocycle_indices: Vector

    @property
    def representative(self) -> NonabelianCocycle:
        return self.parent.cocycles[self.cocycle_indices[0]]

    @property
    def members(self) -> tuple[NonabelianCocycle, ...]:
        return tuple(self.parent.cocycles[index] for index in self.cocycle_indices)

    @property
    def is_basepoint(self) -> bool:
        return self.index == 0

    def verify(self) -> bool:
        self.parent.verify()
        if not 0 <= self.index < len(self.parent.classes):
            return False
        return self.parent.receipt.orbits[self.index] == self.cocycle_indices

    @property
    def certificate(self) -> VerificationCertificate:
        return self.parent.certificate

    def claim(self) -> Claim:
        return self.parent.claim()

    def claim_graph(self) -> ClaimGraph:
        return self.parent.claim_graph()

    def to_canonical(self) -> dict[str, object]:
        return {
            "parent": self.parent.content_id,
            "index": self.index,
            "cocycle_indices": self.cocycle_indices,
            "pointed": self.is_basepoint,
            "type": "arbogast.twist_class",
        }


@dataclass(frozen=True, slots=True)
class TwistClassSet:
    """A finite pointed set; intentionally not a vector space or group."""

    acting_group: object
    coefficient_group: object
    action: Action
    acting_elements: tuple[object, ...]
    coefficient_elements: tuple[object, ...]
    cocycle_indices: Rows
    orbit_indices: tuple[Vector, ...]
    receipt: TwistReceipt

    @property
    def cocycles(self) -> tuple[NonabelianCocycle, ...]:
        return tuple(
            NonabelianCocycle(
                self,
                index,
                images,
            )
            for index, images in enumerate(self.cocycle_indices)
        )

    @property
    def classes(self) -> tuple[TwistClass, ...]:
        return tuple(
            TwistClass(self, index, orbit) for index, orbit in enumerate(self.orbit_indices)
        )

    @property
    def basepoint(self) -> TwistClass:
        return self.classes[0]

    @property
    def cardinality(self) -> int:
        return len(self.orbit_indices)

    def __len__(self) -> int:
        return self.cardinality

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.receipt.assumptions

    @property
    def content_id(self) -> str:
        return self.receipt.content_id

    @property
    def certificate(self) -> VerificationCertificate:
        from .semantic import verification_certificate_for

        return verification_certificate_for(self.receipt)

    def verify(self) -> bool:
        self.receipt.verify()
        if self.cocycle_indices != self.receipt.cocycles:
            raise ValueError("live cocycles are not bound to the twist receipt")
        if self.orbit_indices != self.receipt.orbits:
            raise ValueError("live twist classes are not bound to the twist receipt")
        default_verifiers.verify(self.certificate)
        return True

    def claim(self) -> Claim:
        from .semantic import claim_for

        return claim_for(self.receipt)

    def claim_graph(self) -> ClaimGraph:
        from .semantic import claim_graph_for

        return claim_graph_for(self.receipt)

    def to_canonical(self) -> dict[str, object]:
        return self.receipt.to_dict()


def _build_action_table(
    acting_elements: tuple[object, ...],
    coefficient_elements: tuple[object, ...],
    action: Action,
) -> Rows:
    lookup = {element: index for index, element in enumerate(coefficient_elements)}
    rows: list[Vector] = []
    for acting_element in acting_elements:
        row: list[int] = []
        for coefficient in coefficient_elements:
            image = action(acting_element, coefficient)
            if image not in lookup:
                raise ValueError("action image lies outside the coefficient group")
            row.append(lookup[image])
        rows.append(tuple(row))
    return tuple(rows)


def _is_cocycle(
    values: Vector,
    acting_table: Rows,
    coefficient_table: Rows,
    action_table: Rows,
    acting_identity: int,
    coefficient_identity: int,
) -> bool:
    return values[acting_identity] == coefficient_identity and all(
        values[acting_table[left][right]]
        == coefficient_table[values[left]][action_table[left][values[right]]]
        for left in range(len(acting_table))
        for right in range(len(acting_table))
    )


def _twist(
    cocycle: Vector,
    by: int,
    coefficient_table: Rows,
    coefficient_inverses: Vector,
    action_table: Rows,
) -> Vector:
    inverse = coefficient_inverses[by]
    return tuple(
        coefficient_table[inverse][
            coefficient_table[cocycle[group_index]][action_table[group_index][by]]
        ]
        for group_index in range(len(action_table))
    )


def nonabelian_h1(
    group: object,
    coefficients: object,
    action: object | None = None,
    *,
    max_assignments: int = 1_000_000,
    assumptions: Iterable[str] = (),
) -> TwistClassSet | Unsupported:
    """Exhaustively enumerate finite nonabelian H1 as a pointed set."""

    if isinstance(max_assignments, bool) or not isinstance(max_assignments, int):
        raise TypeError("max_assignments must be an integer")
    if max_assignments <= 0:
        raise ValueError("max_assignments must be positive")
    acting_elements = canonical_group_elements(group)
    coefficient_elements = canonical_group_elements(coefficients)
    acting_identity_element = group_identity(group, acting_elements)
    coefficient_identity_element = group_identity(coefficients, coefficient_elements)
    acting_identity = acting_elements.index(acting_identity_element)
    coefficient_identity = coefficient_elements.index(coefficient_identity_element)
    assignment_count = len(coefficient_elements) ** (len(acting_elements) - 1)
    if assignment_count > max_assignments:
        return Unsupported(
            "galois.nonabelian_h1",
            "the complete finite cocycle enumeration exceeds the declared budget",
            requested={
                "acting_group_order": len(acting_elements),
                "coefficient_group_order": len(coefficient_elements),
                "assignments": assignment_count,
                "max_assignments": max_assignments,
            },
            supported=("finite exhaustive enumeration within max_assignments",),
        )
    acting_table = multiplication_table(group, acting_elements)
    coefficient_table = multiplication_table(coefficients, coefficient_elements)
    acting_inverses = inverse_table(group, acting_elements)
    coefficient_inverses = inverse_table(coefficients, coefficient_elements)
    action_function = _action_function(action)
    action_table = _build_action_table(
        acting_elements,
        coefficient_elements,
        action_function,
    )
    free_indices = tuple(index for index in range(len(acting_elements)) if index != acting_identity)
    cocycles: list[Vector] = []
    for assignment in itertools.product(
        range(len(coefficient_elements)),
        repeat=len(free_indices),
    ):
        values = [coefficient_identity] * len(acting_elements)
        for index, image in zip(free_indices, assignment, strict=True):
            values[index] = image
        candidate = tuple(values)
        if _is_cocycle(
            candidate,
            acting_table,
            coefficient_table,
            action_table,
            acting_identity,
            coefficient_identity,
        ):
            cocycles.append(candidate)
    cocycle_indices = tuple(sorted(cocycles))
    lookup = {cocycle: index for index, cocycle in enumerate(cocycle_indices)}
    identity_cocycle = (coefficient_identity,) * len(acting_elements)
    identity_orbit = tuple(
        sorted(
            {
                lookup[
                    _twist(
                        identity_cocycle,
                        coefficient,
                        coefficient_table,
                        coefficient_inverses,
                        action_table,
                    )
                ]
                for coefficient in range(len(coefficient_elements))
            }
        )
    )
    orbits: list[Vector] = [identity_orbit]
    unseen = set(range(len(cocycle_indices)))
    unseen.difference_update(identity_orbit)
    while unseen:
        seed = min(unseen)
        orbit = tuple(
            sorted(
                {
                    lookup[
                        _twist(
                            cocycle_indices[seed],
                            coefficient,
                            coefficient_table,
                            coefficient_inverses,
                            action_table,
                        )
                    ]
                    for coefficient in range(len(coefficient_elements))
                }
            )
        )
        orbits.append(orbit)
        unseen.difference_update(orbit)
    orbit_indices = tuple(orbits)
    receipt = TwistReceipt(
        acting_elements=tuple(canonical_permutation_or_value(item) for item in acting_elements),
        acting_table=acting_table,
        acting_identity=acting_identity,
        acting_inverses=acting_inverses,
        coefficient_elements=tuple(
            canonical_permutation_or_value(item) for item in coefficient_elements
        ),
        coefficient_table=coefficient_table,
        coefficient_identity=coefficient_identity,
        coefficient_inverses=coefficient_inverses,
        action_table=action_table,
        cocycles=cocycle_indices,
        orbits=orbit_indices,
        representatives=tuple(orbit[0] for orbit in orbit_indices),
        assumptions=tuple(assumptions),
    )
    receipt.verify()
    result = TwistClassSet(
        group,
        coefficients,
        action_function,
        acting_elements,
        coefficient_elements,
        cocycle_indices,
        orbit_indices,
        receipt,
    )
    result.verify()
    return result


def twist_classes(
    group: object,
    coefficients: object,
    action: object | None = None,
    *,
    max_assignments: int = 1_000_000,
    assumptions: Iterable[str] = (),
) -> TwistClassSet | Unsupported:
    """Alias the exhaustive pointed-set computation under descent terminology."""

    return nonabelian_h1(
        group,
        coefficients,
        action,
        max_assignments=max_assignments,
        assumptions=assumptions,
    )


__all__ = [
    "NonabelianCocycle",
    "TwistClass",
    "TwistClassSet",
    "nonabelian_h1",
    "twist_classes",
]
