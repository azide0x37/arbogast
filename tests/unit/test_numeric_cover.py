from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from itertools import pairwise

import pytest

from arbogast.claims import EpistemicStatus
from arbogast.hurwitz import BraidWord, NielsenClass, NielsenTuple, braid_action, nielsen_class
from arbogast.numeric import (
    BraidContinuationWitness,
    BranchCycleTuple,
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
    NumericError,
    NumericPoint,
    NumericReceipt,
    NumericUnknown,
    NumericVerificationError,
    ParameterPath,
    PolynomialFamily,
    bind_vertex,
    braid_continue,
    branch_cycles,
)
from arbogast.numeric.semantic import receipt_for_result
from arbogast.rep import Permutation, PermutationGroup


def _times_i(value: ComplexDyadic) -> ComplexDyadic:
    return ComplexDyadic(-value.imag, value.real)


def _times_minus_i(value: ComplexDyadic) -> ComplexDyadic:
    return ComplexDyadic(value.imag, -value.real)


def _first_quarter_witnesses() -> tuple[
    tuple[ComplexDyadic, ...],
    tuple[ComplexDyadic, ...],
]:
    centers = tuple(
        ComplexDyadic(Dyadic(real, real_exp), Dyadic(imag, imag_exp))
        for real, real_exp, imag, imag_exp in (
            (15899, -14, 1055, -14),
            (7569, -13, 3325, -14),
            (7365, -13, 5695, -14),
            (14667, -14, 8007, -14),
            (14857, -14, 10163, -14),
            (15205, -14, 12137, -14),
            (15643, -14, 6971, -13),
            (8065, -13, 7801, -13),
        )
    )
    inverses = tuple(
        ComplexDyadic(Dyadic(real, real_exp), Dyadic(imag, imag_exp))
        for real, real_exp, imag, imag_exp in (
            (67239, -17, -8923, -18),
            (135331, -18, -29725, -18),
            (126831, -18, -12259, -16),
            (112799, -18, -61579, -18),
            (24617, -16, -67357, -18),
            (21567, -16, -34431, -17),
            (76507, -18, -17047, -16),
            (68783, -18, -66531, -18),
        )
    )
    return centers, inverses


@lru_cache(maxsize=1)
def exact_two_sheet_cover_fixture() -> tuple[NumericalCover, NielsenClass]:
    """Return the portable x^2=t continuation fixture used by docs and tests."""

    polynomial = ExactPolynomial(
        2,
        {(2, 0): 1, (0, 1): -1},
        variable_names=("x", "t"),
    )
    family = PolynomialFamily(1, (polynomial,))
    model = ExactCover(family, 2, (0,), label="x^2=t")

    corners = (
        ComplexDyadic(1),
        ComplexDyadic(0, 2),
        ComplexDyadic(-1),
        ComplexDyadic(0, -2),
        ComplexDyadic(1),
    )
    vertices: list[ComplexDyadic] = []
    for start, end in pairwise(corners):
        for index in range(8):
            weight = Dyadic(index, -3)
            vertices.append(
                ComplexDyadic(
                    start.real + (end.real - start.real) * weight,
                    start.imag + (end.imag - start.imag) * weight,
                )
            )
    vertices.append(corners[-1])
    path = ParameterPath(tuple(vertices))
    loop = BranchLoop(model, 0, path)

    first_centers, first_inverses = _first_quarter_witnesses()
    centers = (
        *first_centers,
        *(_times_i(value.conjugate()) for value in reversed(first_centers)),
        *(_times_i(value) for value in first_centers),
        *(-value.conjugate() for value in reversed(first_centers)),
    )
    inverses = (
        *first_inverses,
        *(_times_minus_i(value.conjugate()) for value in reversed(first_inverses)),
        *(_times_minus_i(value) for value in first_inverses),
        *(-value.conjugate() for value in reversed(first_inverses)),
    )
    radii = tuple(Dyadic(1, -1 if index % 2 == 0 else -2) for index in range(32))

    fiber_system = family.fiber(1)
    source_points = (
        NumericPoint(fiber_system, (ComplexBall(1, Fraction(3, 4)),)),
        NumericPoint(fiber_system, (ComplexBall(-1, Fraction(3, 4)),)),
    )
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
    tracking = BranchTracking(loop, source_points, continuations, (1, 0))
    numerical = NumericalCover(model, 1, source_points, (tracking,))

    transposition = Permutation((1, 0))
    group = PermutationGroup((transposition,), degree=2, name="C2")
    conjugacy_class = group.conjugacy_class(transposition)
    exact_vertices = nielsen_class(group, (conjugacy_class, conjugacy_class))
    return numerical, exact_vertices


def test_branch_cycles_and_vertex_are_exact_only_after_complete_tracking() -> None:
    cover, nielsen = exact_two_sheet_cover_fixture()
    cycles = branch_cycles(cover)
    assert isinstance(cycles, BranchCycleTuple)
    assert isinstance(cycles, NielsenTuple)
    assert cycles.verify()
    assert tuple(entry.images for entry in cycles.entries) == ((1, 0), (1, 0))
    assert cycles.claim().status is EpistemicStatus.EXACT
    assert cycles.claim().verify().verified

    vertex = bind_vertex(cover, nielsen)
    assert isinstance(vertex, NielsenVertex)
    assert vertex.vertex_index == 0
    assert vertex.claim().status is EpistemicStatus.EXACT
    assert vertex.claim().verify().verified

    with pytest.raises(NumericError, match="one tracking"):
        NumericalCover(cover.model, cover.base_parameter, cover.fiber_points, ())


def test_readdressed_tracking_order_tamper_fails_replay() -> None:
    cover, _ = exact_two_sheet_cover_fixture()
    payload = deepcopy(receipt_for_result(cover).payload.to_dict())
    continuations = payload["trackings"][0]["continuations"]
    continuations.reverse()
    tampered = NumericReceipt.create("numerical-cover", payload)
    with pytest.raises(NumericVerificationError, match=r"wrong sheet|altered"):
        tampered.verify()


def test_nonclosing_local_braid_witness_provenance_is_retained() -> None:
    cover, nielsen = exact_two_sheet_cover_fixture()
    vertex = bind_vertex(cover, nielsen)
    assert isinstance(vertex, NielsenVertex)
    action = braid_action(nielsen)
    word = BraidWord.generator(0)
    witness = BraidContinuationWitness(
        vertex,
        word,
        vertex,
        action,
        vertex.trackings[0].continuations,
        (1, 0),
    )
    result = braid_continue(vertex, word, witness=witness)
    assert isinstance(result, NumericUnknown)
    assert result.requested["local_witness_id"] == witness.content_id
