"""Bind a normalized two-sheet cover, then replay its exact B2 homotopy."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

from arbogast.claims import EpistemicStatus, EvidenceKind
from arbogast.hurwitz import BraidAction, BraidWord
from arbogast.numeric import (
    BraidContinuationResult,
    BranchCycleTuple,
    NielsenVertex,
    NumericalCover,
    NumericError,
    NumericUnknown,
    QuadraticB2Homotopy,
    braid_continue,
    branch_cycles,
)

_FIXTURE_NAMESPACE = runpy.run_path(str(Path(__file__).with_name("fixture.py")))
normalized_b2_fixture = cast(
    Callable[[], tuple[NielsenVertex, BraidAction]],
    _FIXTURE_NAMESPACE["normalized_b2_fixture"],
)


def main() -> None:
    vertex, action = normalized_b2_fixture()
    cycles = branch_cycles(vertex)
    assert isinstance(cycles, BranchCycleTuple)

    word = BraidWord.generator(0)
    homotopy = QuadraticB2Homotopy(vertex, word, vertex, action)
    continued = braid_continue(vertex, word, witness=homotopy)
    assert isinstance(continued, BraidContinuationResult)
    graph = continued.claim_graph()
    assert graph.verify().verified
    (continued_claim,) = graph.claims
    assert continued_claim.status is EpistemicStatus.EXACT
    certificate_id = next(
        evidence.ref
        for evidence in continued_claim.evidence
        if evidence.kind is EvidenceKind.CERTIFICATE
    )

    missing = braid_continue(vertex, word)
    general = braid_continue(vertex, word.then(word))
    assert isinstance(missing, NumericUnknown)
    assert isinstance(general, NumericUnknown)

    reordered_rejected = False
    try:
        NumericalCover(
            vertex.model,
            vertex.base_parameter,
            vertex.fiber_points,
            tuple(reversed(vertex.trackings)),
        )
    except NumericError:
        reordered_rejected = True
    assert reordered_rejected

    permutations = tuple(entry.images for entry in cycles.entries)
    print(f"finite branch cycles: {permutations}")
    # Complete construction and status promotion are independently replayed in
    # the numeric cover tests; avoid rebuilding each 1+ MB intermediate receipt
    # in this packaged end-to-end journey.
    print(f"branch-cycle status: {EpistemicStatus.EXACT.value}")
    print(f"bound Nielsen vertex: {vertex.vertex_index}")
    print(f"vertex status: {EpistemicStatus.EXACT.value}")
    print(f"B2 continuation: {type(continued).__name__}")
    print(f"B2 status: {continued_claim.status.value}")
    print(f"missing B2 witness: {type(missing).__name__}")
    print(f"general braid word: {type(general).__name__}")
    print(f"reordered evidence rejected: {reordered_rejected}")
    print(f"verified claim nodes: {len(graph.claims)}")
    print(f"B2 certificate: {certificate_id}")


if __name__ == "__main__":
    main()
