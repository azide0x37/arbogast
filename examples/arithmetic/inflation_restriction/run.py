"""Certify inflation--restriction for the nonsplit extension C2 -> C4 -> C2."""

from __future__ import annotations

from arbogast.cohom import (
    corestriction_map,
    h0,
    inflation_map,
    inflation_restriction,
    restriction_map,
    transgression,
)
from arbogast.linalg import PrimeField
from arbogast.rep import CyclicGroup, FiniteGroupExtension, FiniteGroupMap, Representation


def cyclic_exponent(group: CyclicGroup, element: object) -> int:
    """Return the unique exponent in one small concrete cyclic group."""

    return next(exponent for exponent in range(group.order) if group.generator**exponent == element)


def main() -> int:
    kernel = CyclicGroup(2)
    total = CyclicGroup(4)
    quotient = CyclicGroup(2)

    inclusion = FiniteGroupMap(
        kernel,
        total,
        lambda element: total.generator ** (2 * cyclic_exponent(kernel, element)),
        require_injective=True,
    )
    projection = FiniteGroupMap(
        total,
        quotient,
        lambda element: quotient.generator ** (cyclic_exponent(total, element) % 2),
        require_surjective=True,
    )
    extension = FiniteGroupExtension(
        kernel,
        total,
        quotient,
        inclusion,
        projection,
    )
    module = Representation.trivial(total, PrimeField(2))
    quotient_module = Representation.trivial(quotient, PrimeField(2))

    # No element of order two maps to the nontrivial quotient element, so this
    # concrete C4 extension is nonsplit.
    lifts = tuple(
        element for element in total.elements if projection(element) == quotient.generator
    )
    assert lifts and all(element.order == 4 for element in lifts)

    sequence = inflation_restriction(extension, module)
    assert sequence.certificate.term_dimensions == (1, 1, 1, 1, 1)
    assert sequence.inflation_h1.matrix == ((1,),)
    assert sequence.restriction.matrix == ((0,),)
    assert sequence.transgression.matrix == ((1,),)
    assert sequence.inflation_h2.matrix == ((0,),)
    assert transgression(sequence).matrix == ((1,),)
    assert sequence.verify()
    assert sequence.exact_sequence.verify()
    assert sequence.claim_graph().verify().verified

    # The same restriction, inflation, and transfer are first-class maps with
    # independently replayable map receipts.
    restricted = restriction_map(sequence.h1_group, kernel, inclusion)
    inflated = inflation_map(sequence.h1_quotient, extension)
    transferred = corestriction_map(restricted.target, total, module, inclusion)
    assert restricted.matrix == ((0,),)
    assert inflated.matrix == ((1,),)
    assert transferred.matrix == ((1,),)
    assert restricted.verify()
    assert inflated.verify()
    assert transferred.verify()

    # Exercise each first-class functorial map in every supported degree.
    restriction_maps = (
        restriction_map(h0(total, module), kernel, inclusion),
        restricted,
        restriction_map(sequence.h2_group, kernel, inclusion),
    )
    inflation_maps = (
        inflation_map(h0(quotient, quotient_module), extension),
        inflated,
        inflation_map(sequence.h2_quotient, extension),
    )
    corestriction_maps = (
        corestriction_map(restriction_maps[0].target, total, module, inclusion),
        transferred,
        corestriction_map(restriction_maps[2].target, total, module, inclusion),
    )
    assert tuple(item.degree for item in restriction_maps) == (0, 1, 2)
    assert tuple(item.degree for item in inflation_maps) == (0, 1, 2)
    assert tuple(item.degree for item in corestriction_maps) == (0, 1, 2)
    assert all(item.verify() for item in (*restriction_maps, *inflation_maps, *corestriction_maps))

    print(f"term dimensions: {sequence.certificate.term_dimensions}")
    print(
        "five-term matrices: "
        f"{sequence.inflation_h1.matrix}, {sequence.restriction.matrix}, "
        f"{sequence.transgression.matrix}, {sequence.inflation_h2.matrix}"
    )
    print("image equals kernel at every interior term: verified")
    print("first-class restriction/inflation/corestriction maps: degrees 0-2 verified")
    print("claim graph: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
