from __future__ import annotations

from arbogast.cohom import H0Result, H1Result, H2Result, cochain_complex, h0, h1, h2
from arbogast.linalg import PrimeField
from arbogast.rep import CyclicGroup, Representation


def test_public_group_representation_and_linalg_objects_interoperate() -> None:
    group = CyclicGroup(2)
    module = Representation.trivial(group, PrimeField(2))
    complex_ = cochain_complex(group, module, 2)

    invariant_result = h0(complex_)
    first_result = h1(complex_)
    second_result = h2(complex_)

    assert isinstance(invariant_result, H0Result)
    assert isinstance(first_result, H1Result)
    assert isinstance(second_result, H2Result)
    assert (invariant_result.dimension, first_result.dimension, second_result.dimension) == (
        1,
        1,
        1,
    )
    assert complex_.verify()
    assert all(result.verify() for result in (invariant_result, first_result, second_result))


def test_readme_scale_c5_over_f11_cubed_is_exact_and_fast() -> None:
    group = CyclicGroup(5)
    module = Representation.trivial(group, PrimeField(11), dimension=3)

    result = h1(group, module)

    # Since 5 is invertible in F_11, every positive-degree class vanishes.
    assert result.dimension == 0
    assert result.cocycles.dimension == result.coboundaries.dimension
    assert result.verify()
