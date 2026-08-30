from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from arbogast.agent import (
    DEFAULT_CODE_DEPENDENCIES,
    CapabilityGraph,
    CapabilityRouteError,
    compact_context,
    module_manifest,
    operation_descriptions,
)
from arbogast.arithmetic import cartier_dual, local_pairing
from arbogast.galois import (
    FinitePlace,
    LocalH1Space,
    NumberField,
    finite_galois_quotient,
    galois_module,
    local_h1,
    local_h1_class,
)
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import cyclic_group
from arbogast.specs import default_operations


def test_semantic_constructor_operations_are_live_and_claim_bound() -> None:
    rational = NumberField.rationals()
    group = cyclic_group(1)
    quotient = finite_galois_quotient(rational, group, label="surface-registry")
    field = PrimeField(2)
    module = galois_module(
        quotient,
        field,
        {group.identity: DenseMatrix.identity(field, 1)},
    )
    dual = cartier_dual(module)
    place = FinitePlace(rational, 2, ((2,),), 1, 1)
    local_space = local_h1(place)
    assert isinstance(local_space, LocalH1Space)
    local_class = local_h1_class(local_space, (1, 0, 0))
    pairing = local_pairing(local_space)

    expected: tuple[tuple[str, Callable[..., object], Any], ...] = (
        ("galois.finite_galois_quotient", finite_galois_quotient, quotient),
        ("galois.local_h1_class", local_h1_class, local_class),
        ("arithmetic.cartier_dual", cartier_dual, dual),
        ("arithmetic.local_pairing", local_pairing, pairing),
    )
    for operation, function, result in expected:
        assert default_operations.function(operation) is function
        assert result.verify()
        assert result.claim().how.operation == operation
        assert result.claim_graph().verify().verified


def test_capability_routes_preserve_conjunctive_and_dependent_types() -> None:
    graph = CapabilityGraph.from_operations(operation_descriptions())
    edges = {(edge.operation, edge.required_inputs, edge.target) for edge in graph.edges}

    assert (
        "cohom.inflation_map",
        ("CohomologyResult", "FiniteGroup", "FiniteGroupMap"),
        "InducedCohomologyMap",
    ) in edges
    assert (
        "arithmetic.aim",
        ("LocalizationMap", "Vector"),
        "AffineFamily",
    ) in edges
    assert (
        "arithmetic.dual_selmer",
        ("SelmerProblem", "PairingCollection", "CartierDual"),
        "DualSelmerResult",
    ) in edges
    assert not any(
        operation == "arithmetic.dual_selmer" and "CartierDual" not in required
        for operation, required, _target in edges
    )

    localize_edges = {
        (required, target)
        for operation, required, target in edges
        if operation == "galois.localize"
    }
    assert (("KummerSpace", "LocalH1Space"), "LocalizationMap") in localize_edges
    assert (("KummerSpace", "LocalH1Space"), "PariArithmeticResult") in localize_edges
    assert (("KummerClass", "LocalH1Space"), "LocalH1Class") in localize_edges
    assert (("KummerSpace", "LocalH1Space"), "LocalH1Class") not in localize_edges
    assert (("KummerClass", "LocalH1Space"), "LocalizationMap") not in localize_edges

    corestrict_edges = {
        (required, target)
        for operation, required, target in edges
        if operation == "cohom.corestrict"
    }
    assert corestrict_edges == {
        (("Cochain", "FiniteGroup"), "Cochain"),
        (("CohomologyClass", "FiniteGroup"), "CohomologyClass"),
    }
    with pytest.raises(CapabilityRouteError):
        graph.route("SelmerProblem", "DualSelmerResult")
    with pytest.raises(CapabilityRouteError):
        graph.route("PariArithmeticResult", "ClaimGraph")


def test_arithmetic_surface_hazards_profiles_and_backend_dependencies_are_explicit() -> None:
    expected_hazards = {
        "cohom.inflation_map": "cohom.induced-map-needs-explicit-group-map",
        "cohom.restriction_map": "cohom.induced-map-needs-explicit-group-map",
        "galois.localize": "arithmetic.finite-s-kummer-vs-unrestricted-squareclasses",
        "arithmetic.unique": "arithmetic.failed-search-vs-obstruction",
        "arithmetic.local_pairing": "arithmetic.pairing-before-dual-selmer",
    }
    for operation, expected in expected_hazards.items():
        context = compact_context((operation,), max_chars=12_000)
        assert expected in {hazard.id for hazard in context.hazards}

    galois_manifest = module_manifest("arbogast.galois")
    assert {
        "FieldEmbedding",
        "FiniteGroupMap",
        "FinitePlace",
        "Ideal",
        "KummerClass",
        "LocalH1Class",
        "LocalizationMap",
        "NumberFieldElement",
    } <= set(galois_manifest.primary_types)
    assert not any(" | " in type_name for type_name in galois_manifest.primary_types)

    pairing_dependencies = DEFAULT_CODE_DEPENDENCIES.get("arithmetic.local_pairing")
    assert pairing_dependencies.optional_backends == ("pari",)
