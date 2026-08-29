from __future__ import annotations

import pytest

from arbogast.cohom import CohomologyClass, InvalidGroupError, h1, inflate, restrict


class PrimeField:
    characteristic = 2
    order = 2


class CyclicGroup:
    def __init__(self, order: int) -> None:
        self.order = order
        self.elements = tuple(range(order))
        self.identity = 0

    def multiply(self, left: int, right: int) -> int:
        return (left + right) % self.order


class TrivialModule:
    field = PrimeField()
    dimension = 1

    def action_matrix(self, _element: int) -> tuple[tuple[int, ...], ...]:
        return ((1,),)


class StatefulMap:
    def __init__(self, stable_calls: int, stable: object, changed: object) -> None:
        self.stable_calls = stable_calls
        self.stable = stable
        self.changed = changed
        self.calls = 0

    def __call__(self, element: int) -> int:
        self.calls += 1
        operation = self.stable if self.calls <= self.stable_calls else self.changed
        assert callable(operation)
        return operation(element)


def test_restriction_of_c4_character_to_order_two_subgroup_is_zero() -> None:
    cyclic_four = CyclicGroup(4)
    cyclic_two = CyclicGroup(2)
    source = h1(cyclic_four, TrivialModule()).basis[0]

    restricted = restrict(source, cyclic_two, lambda element: 2 * element)

    assert isinstance(restricted, CohomologyClass)
    assert restricted.is_zero
    assert restricted.verify()


def test_inflation_of_c2_character_through_c4_quotient_is_nonzero() -> None:
    cyclic_four = CyclicGroup(4)
    cyclic_two = CyclicGroup(2)
    source = h1(cyclic_two, TrivialModule()).basis[0]

    inflated = inflate(source, cyclic_four, lambda element: element % 2)

    assert isinstance(inflated, CohomologyClass)
    assert inflated.coordinates == (1,)
    assert inflated.verify()


def test_restriction_checks_injectivity() -> None:
    source = h1(CyclicGroup(4), TrivialModule()).basis[0]
    with pytest.raises(InvalidGroupError, match="injective"):
        restrict(source, CyclicGroup(2), lambda _element: 0)


def test_inflation_checks_surjectivity() -> None:
    source = h1(CyclicGroup(2), TrivialModule()).basis[0]
    with pytest.raises(InvalidGroupError, match="surjective"):
        inflate(source, CyclicGroup(4), lambda _element: 0)


def test_restriction_freezes_validated_images_of_a_stateful_map() -> None:
    source = h1(CyclicGroup(4), TrivialModule()).basis[0]
    inclusion = StatefulMap(2, lambda element: 2 * element, lambda element: element)

    restricted = restrict(source, CyclicGroup(2), inclusion)

    assert isinstance(restricted, CohomologyClass)
    assert restricted.is_zero
    assert inclusion.calls == 2


def test_inflation_freezes_validated_images_of_a_stateful_map() -> None:
    source = h1(CyclicGroup(2), TrivialModule()).basis[0]
    projection = StatefulMap(4, lambda element: element % 2, lambda _element: 0)

    inflated = inflate(source, CyclicGroup(4), projection)

    assert isinstance(inflated, CohomologyClass)
    assert inflated.coordinates == (1,)
    assert projection.calls == 4
