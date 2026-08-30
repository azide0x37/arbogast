from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol, cast

import pytest

from arbogast.arithmetic import (
    KummerDescentProblem,
    LocalCondition,
    LocalPairing,
    elementary_descent,
)
from arbogast.claims import ClaimGraph
from arbogast.export import (
    export_agent_context,
    export_json,
    export_latex,
    export_lean,
    export_markdown,
)
from arbogast.galois import (
    FinitePlace,
    InfinitePlace,
    NumberField,
    Unsupported,
    kummer_space,
    local_h1,
    localize,
)
from arbogast.linalg import DenseMatrix, PrimeField


class _V010StructuralTransport:
    __module__ = "arbogast.hurwitz.compatibility_fixture"

    def to_dict(self) -> dict[str, object]:
        return {"legacy": "structural-transport"}

    def claim_graph(self) -> ClaimGraph:
        return ClaimGraph(())


class _ProofBearing(Protocol):
    def claim_graph(self) -> ClaimGraph: ...


@pytest.fixture
def proof_bearing_results() -> tuple[object, ...]:
    field = NumberField.rationals()
    at_two = FinitePlace(field, 2, ((2,),), 1, 1)
    at_real = InfinitePlace(field, "real", (-1, 1))
    kummer = kummer_space(field, (at_two, at_real))
    assert not isinstance(kummer, Unsupported)
    local = local_h1(at_real)
    assert not isinstance(local, Unsupported)
    localization = localize(kummer, local)
    assert not isinstance(localization, Unsupported)
    pairing = LocalPairing.hilbert(local)
    condition = LocalCondition(local, ((1,),))
    descent = elementary_descent(
        KummerDescentProblem(
            DenseMatrix(PrimeField(2), ((1,),)),
            (1,),
        )
    )
    return kummer, local, localization, pairing, condition, descent


def test_all_exporters_lift_public_proof_bearing_results_to_their_claim_graph(
    proof_bearing_results: tuple[object, ...],
) -> None:
    for result in proof_bearing_results:
        graph = cast(_ProofBearing, result).claim_graph()
        assert graph.verify().verified

        assert export_json(result) == export_json(graph)
        assert export_json(result, pretty=True) == export_json(graph, pretty=True)
        assert export_markdown(result) == export_markdown(graph)
        assert export_latex(result) == export_latex(graph)
        assert export_lean(result) == export_lean(graph)
        assert export_agent_context(result) == export_agent_context(graph)
        assert export_agent_context(result, pretty=True) == export_agent_context(
            graph,
            pretty=True,
        )

        lean = export_lean(result)
        assert graph.claims[0].id in lean
        assert "def claimData_" in lean
        assert json.loads(export_json(result))["schema_version"] == "arbogast.claim-graph/v1"


def test_v010_json_markdown_and_agent_transport_remains_structural() -> None:
    result = _V010StructuralTransport()
    expected = {"legacy": "structural-transport"}

    assert json.loads(export_json(result)) == expected
    assert json.loads(export_markdown(result).removeprefix("```json\n").removesuffix("```\n")) == (
        expected
    )
    assert json.loads(export_agent_context(result)) == expected


class _NonCallableClaimGraph:
    claim_graph = "not callable"


class _WrongClaimGraph:
    def claim_graph(self) -> object:
        return {"claims": []}


@pytest.mark.parametrize("value", (_NonCallableClaimGraph(), _WrongClaimGraph()))
@pytest.mark.parametrize(
    "exporter",
    (
        export_json,
        export_markdown,
        export_latex,
        export_lean,
        export_agent_context,
    ),
)
def test_malformed_claim_graph_providers_are_never_silently_downgraded(
    value: object,
    exporter: Callable[[object], str],
) -> None:
    with pytest.raises(TypeError, match="claim_graph"):
        exporter(value)


def test_lean_rejects_an_object_without_a_semantic_projection() -> None:
    with pytest.raises(TypeError, match="Lean export does not support object"):
        export_lean(object())
