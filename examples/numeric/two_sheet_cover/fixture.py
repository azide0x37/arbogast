"""Exact normalized two-finite-branch fixture shared by numeric examples and tests."""

from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from itertools import pairwise

from arbogast.hurwitz import BraidAction, NielsenClass, braid_action, nielsen_class
from arbogast.numeric import (
    BranchLoop,
    BranchTracking,
    ComplexBall,
    ComplexDyadic,
    ContinuationResult,
    ContinuationStep,
    ContinuationTube,
    Dyadic,
    ExactCover,
    ExactPolynomial,
    NielsenVertex,
    NumericalCover,
    NumericPoint,
    ParameterPath,
    PolynomialFamily,
    bind_vertex,
)
from arbogast.rep import Permutation, PermutationGroup

DyadicComplexData = tuple[int, int, int, int]

_FIRST_HALF_CENTERS: tuple[DyadicComplexData, ...] = (
    (0, 0, 1, -1),
    (-1, -10, 1, -1),
    (-3, -10, 1, -1),
    (-3, -9, 1, -1),
    (-5, -9, 1, -1),
    (-15, -10, 2049, -12),
    (-21, -10, 1025, -11),
    (-7, -8, 2051, -12),
    (-9, -8, 2053, -12),
    (-45, -10, 257, -9),
    (-219, -12, 515, -10),
    (-131, -11, 2065, -12),
    (-309, -12, 2071, -12),
    (-359, -12, 2079, -12),
    (-103, -10, 2089, -12),
    (-117, -10, 2101, -12),
    (-527, -12, 2115, -12),
    (-589, -12, 2131, -12),
    (-163, -10, 2149, -12),
    (-359, -11, 1085, -11),
    (-785, -12, 2193, -12),
    (-853, -12, 2219, -12),
    (-923, -12, 1123, -11),
    (-497, -11, 569, -10),
    (-1065, -12, 577, -10),
    (-1137, -12, 1171, -11),
    (-1209, -12, 1189, -11),
    (-641, -11, 151, -8),
    (-1355, -12, 307, -9),
    (-357, -10, 2497, -12),
    (-1501, -12, 2539, -12),
    (-787, -11, 2583, -12),
    (-1633, -12, 2569, -12),
    (-839, -11, 2495, -12),
    (-1723, -12, 2419, -12),
    (-1769, -12, 2343, -12),
    (-1815, -12, 2265, -12),
    (-931, -11, 1093, -11),
    (-955, -11, 1053, -11),
    (-979, -11, 253, -9),
    (-251, -9, 971, -11),
    (-2059, -12, 929, -11),
    (-2111, -12, 1773, -12),
    (-541, -10, 211, -9),
    (-2219, -12, 801, -11),
    (-569, -10, 1515, -12),
    (-1167, -11, 357, -10),
    (-1197, -11, 1341, -12),
    (-2455, -12, 627, -11),
    (-2519, -12, 1167, -12),
    (-2583, -12, 1081, -12),
    (-2649, -12, 995, -12),
    (-2717, -12, 455, -11),
    (-1393, -11, 413, -11),
    (-2855, -12, 743, -12),
    (-1463, -11, 165, -10),
    (-1499, -11, 579, -12),
    (-1535, -11, 499, -12),
    (-1571, -11, 419, -12),
    (-201, -8, 341, -12),
    (-3289, -12, 33, -9),
    (-3363, -12, 187, -12),
    (-859, -10, 7, -8),
    (-1755, -11, 37, -12),
)

_FIRST_HALF_INVERSES: tuple[DyadicComplexData, ...] = (
    (-1, -12, -1, 0),
    (-9, -12, -1, 0),
    (-25, -12, -1, 0),
    (-49, -12, -4095, -12),
    (-81, -12, -2047, -11),
    (-121, -12, -4091, -12),
    (-21, -9, -2043, -11),
    (-223, -12, -2039, -11),
    (-285, -12, -2033, -11),
    (-177, -11, -4049, -12),
    (-429, -12, -4027, -12),
    (-127, -10, -1999, -11),
    (-591, -12, -1981, -11),
    (-169, -10, -1959, -11),
    (-763, -12, -3865, -12),
    (-53, -8, -951, -10),
    (-931, -12, -1867, -11),
    (-505, -11, -3657, -12),
    (-271, -10, -1787, -11),
    (-9, -5, -871, -10),
    (-1213, -12, -3391, -12),
    (-1267, -12, -1647, -11),
    (-1313, -12, -3195, -12),
    (-1351, -12, -3095, -12),
    (-691, -11, -749, -10),
    (-1407, -12, -1449, -11),
    (-1425, -12, -1401, -11),
    (-1437, -12, -2709, -12),
    (-1445, -12, -2619, -12),
    (-181, -9, -633, -10),
    (-1447, -12, -2449, -12),
    (-1443, -12, -2369, -12),
    (-1479, -12, -1163, -11),
    (-1557, -12, -2315, -12),
    (-819, -11, -575, -10),
    (-861, -11, -2281, -12),
    (-1807, -12, -2255, -12),
    (-947, -11, -139, -8),
    (-991, -11, -1093, -11),
    (-2071, -12, -2141, -12),
    (-2159, -12, -261, -9),
    (-1123, -11, -2027, -12),
    (-1165, -11, -1957, -12),
    (-1205, -11, -235, -9),
    (-2485, -12, -897, -11),
    (-1277, -11, -425, -10),
    (-2615, -12, -25, -6),
    (-2667, -12, -747, -11),
    (-1355, -11, -173, -9),
    (-1371, -11, -1271, -12),
    (-2763, -12, -289, -10),
    (-2775, -12, -521, -11),
    (-347, -9, -465, -11),
    (-173, -8, -821, -12),
    (-43, -6, -179, -10),
    (-341, -9, -77, -9),
    (-1349, -11, -521, -12),
    (-1331, -11, -27, -8),
    (-2623, -12, -175, -11),
    (-645, -10, -137, -11),
    (-1267, -11, -203, -12),
    (-2487, -12, -139, -12),
    (-2439, -12, -79, -12),
    (-2389, -12, -25, -12),
)


def _complex_dyadic(data: DyadicComplexData) -> ComplexDyadic:
    real, real_exponent, imaginary, imaginary_exponent = data
    return ComplexDyadic(
        Dyadic(real, real_exponent),
        Dyadic(imaginary, imaginary_exponent),
    )


def _symmetric_values(data: tuple[DyadicComplexData, ...]) -> tuple[ComplexDyadic, ...]:
    first = tuple(_complex_dyadic(value) for value in data)
    return (*first, *(value.conjugate() for value in reversed(first)))


def _loop_vertices() -> tuple[ComplexDyadic, ...]:
    half = Fraction(1, 2)
    corners = (
        ComplexDyadic(half),
        ComplexDyadic(0, half),
        ComplexDyadic(-half),
        ComplexDyadic(0, -half),
        ComplexDyadic(half),
    )
    vertices: list[ComplexDyadic] = []
    for start, end in pairwise(corners):
        for index in range(32):
            weight = Dyadic(index, -5)
            vertices.append(
                ComplexDyadic(
                    start.real + (end.real - start.real) * weight,
                    start.imag + (end.imag - start.imag) * weight,
                )
            )
    vertices.append(corners[-1])
    return tuple(vertices)


@lru_cache(maxsize=1)
def normalized_b2_fixture() -> tuple[NielsenVertex, BraidAction]:
    """Return a fully certified x^2-t(t-1) vertex and its standard B2 action."""

    polynomial = ExactPolynomial(
        2,
        (((2, 0), 1), ((0, 2), -1), ((0, 1), 1)),
        variable_names=("x", "t"),
    )
    family = PolynomialFamily(1, (polynomial,))
    model = ExactCover(family, 2, (0, 1), label="normalized two-sheet cover")
    base = Fraction(1, 2)
    fiber = family.fiber(base)
    source_points = (
        NumericPoint(
            fiber,
            (ComplexBall(ComplexDyadic(0, base), Fraction(3, 8)),),
        ),
        NumericPoint(
            fiber,
            (ComplexBall(ComplexDyadic(0, -base), Fraction(3, 8)),),
        ),
    )
    centers = _symmetric_values(_FIRST_HALF_CENTERS)
    inverses = _symmetric_values(_FIRST_HALF_INVERSES)
    radii = tuple(Dyadic(1, -2 if index % 2 == 0 else -3) for index in range(128))
    first_path = ParameterPath(_loop_vertices())
    second_path = ParameterPath(tuple(ComplexDyadic(1) - vertex for vertex in first_path.vertices))

    def tracking(branch_index: int, path: ParameterPath) -> BranchTracking:
        positive_steps = tuple(
            ContinuationStep(
                family,
                start,
                end,
                (ComplexBall(center, radius),),
                ((inverse,),),
            )
            for start, end, center, inverse, radius in zip(
                path.vertices[:-1],
                path.vertices[1:],
                centers,
                inverses,
                radii,
                strict=True,
            )
        )
        negative_steps = tuple(
            ContinuationStep(
                family,
                start,
                end,
                (ComplexBall(-center, radius),),
                ((-inverse,),),
            )
            for start, end, center, inverse, radius in zip(
                path.vertices[:-1],
                path.vertices[1:],
                centers,
                inverses,
                radii,
                strict=True,
            )
        )
        continuations = (
            ContinuationResult(ContinuationTube(family, path, source_points[0], positive_steps)),
            ContinuationResult(ContinuationTube(family, path, source_points[1], negative_steps)),
        )
        return BranchTracking(
            BranchLoop(model, branch_index, path),
            source_points,
            continuations,
            (1, 0),
        )

    cover = NumericalCover(
        model,
        base,
        source_points,
        (tracking(0, first_path), tracking(1, second_path)),
    )
    transposition = Permutation((1, 0))
    group = PermutationGroup((transposition,), degree=2, name="C2")
    conjugacy_class = group.conjugacy_class(transposition)
    nielsen: NielsenClass = nielsen_class(group, (conjugacy_class, conjugacy_class))
    vertex = bind_vertex(cover, nielsen)
    if not isinstance(vertex, NielsenVertex):
        raise AssertionError("normalized exact fixture did not bind its Nielsen vertex")
    return vertex, braid_action(nielsen)


__all__ = ["normalized_b2_fixture"]
