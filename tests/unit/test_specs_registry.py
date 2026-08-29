from __future__ import annotations

import pytest

from arbogast.hurwitz import (
    ExplicitSymmetry,
    boundary,
    braid_action,
    claim_graph_for,
    components,
    cusps,
    nielsen_class,
    real_points,
    reduced,
    totally_real,
    verification_certificate_for,
)
from arbogast.rep import Permutation, PermutationGroup
from arbogast.specs import (
    FailureMode,
    OperationExample,
    OperationRegistry,
    OperationSpec,
    OperationSpecError,
    default_operations,
    operation,
)


def test_builtin_registry_is_live_and_semantic_routes_are_typed() -> None:
    expected = {
        "cohom.h0",
        "cohom.h1",
        "cohom.h2",
        "cohom.claim_graph",
        "hurwitz.nielsen_class",
        "hurwitz.claim_graph",
    }
    assert expected.issubset(default_operations.names())
    assert all(default_operations.implemented(name) for name in expected)
    assert callable(default_operations.function("cohom.h1"))
    route = default_operations.spec("hurwitz.claim_graph")
    assert route.input_types[:2] == ("NielsenClass", "NielsenEnumerationCertificate")
    assert "HurwitzOperationCertificate" in route.input_types
    assert "BoundaryIncidence" in route.input_types
    assert ("NielsenClass",) in route.input_bundles
    assert ("HurwitzComponent",) in route.input_bundles
    assert route.output_type == "ClaimGraph"
    assert default_operations.spec("hurwitz.nielsen_class").certificate_type == (
        "arbogast.hurwitz.NielsenEnumerationCertificate"
    )
    braid_certificate = default_operations.spec("hurwitz.braid_action").certificate_type
    assert braid_certificate is not None
    assert "BraidEdgeCertificate" in braid_certificate
    assert "HurwitzOperationCertificate" in braid_certificate
    component_certificate = default_operations.spec("hurwitz.components").certificate_type
    assert component_certificate is not None
    assert "SpanningTreeCertificate" in component_certificate
    assert "HurwitzOperationCertificate" in component_certificate
    assert default_operations.spec("hurwitz.real_points").certificate_type is None
    assert default_operations.spec("hurwitz.totally_real").certificate_type is None
    assert default_operations.spec("cohom.h1").certificate_type == (
        "arbogast.cohom.CohomologyCertificate"
    )


def test_hurwitz_catalog_examples_execute_against_public_api() -> None:
    left = Permutation.from_cycles(3, ((0, 1),))
    right = Permutation.from_cycles(3, ((1, 2),))
    group = PermutationGroup((left, right), degree=3)
    classes = (group.conjugacy_class(left),) * 4
    nielsen = nielsen_class(group, classes)
    action = braid_action(nielsen, mode="pure")
    component = action.components().one()
    identity_symmetry = ExplicitSymmetry("identity", tuple(range(len(component))))
    namespace = {
        "action": action,
        "boundary": boundary,
        "braid_action": braid_action,
        "claim_graph_for": claim_graph_for,
        "classes": classes,
        "component": component,
        "components": components,
        "cusps": cusps,
        "group": group,
        "identity_symmetry": identity_symmetry,
        "nielsen": nielsen,
        "nielsen_class": nielsen_class,
        "real_points": real_points,
        "reduced": reduced,
        "totally_real": totally_real,
        "verification_certificate_for": verification_certificate_for,
    }
    operation_names = (
        "hurwitz.nielsen_class",
        "hurwitz.braid_action",
        "hurwitz.components",
        "hurwitz.real_points",
        "hurwitz.totally_real",
        "hurwitz.reduced",
        "hurwitz.cusps",
        "hurwitz.boundary",
        "hurwitz.claim_graph",
        "hurwitz.verification_certificate",
    )

    for name in operation_names:
        example = default_operations.spec(name).examples[0]
        assert eval(example.code, {"__builtins__": {}}, namespace) is not None


def test_operation_decorator_requires_complete_contract() -> None:
    registry = OperationRegistry()

    @operation(
        name="tests.identity",
        mathematical_domain="finite sets",
        requires=("finite exact input",),
        ensures=("returns the same input",),
        exact=True,
        shardable=False,
        complexity="O(1)",
        failure_modes=("invalid_input",),
        certificate_type=None,
        examples=("identity(1)",),
        input_types=("Exact[T]",),
        output_type="Exact[T]",
        registry=registry,
    )
    def identity(value: int) -> int:
        return value

    assert registry.function("tests.identity")(4) == 4
    assert registry.spec("tests.identity").ensures == ("returns the same input",)

    with pytest.raises(OperationSpecError, match="preconditions"):

        @operation(
            name="tests.bad",
            mathematical_domain="finite sets",
            requires=(),
            ensures=("anything",),
            exact=True,
            shardable=False,
            complexity="O(1)",
            failure_modes=("invalid",),
            certificate_type=None,
            examples=("bad()",),
            registry=registry,
        )
        def bad() -> None:
            return None


@pytest.mark.parametrize("field", ("exact", "shardable"))
@pytest.mark.parametrize("invalid", (None, 0, 1, "false", "true"))
def test_operation_spec_rejects_non_boolean_contract_flags(field: str, invalid: object) -> None:
    values: dict[str, object] = {
        "name": "tests.strict-flags",
        "mathematical_domain": "finite sets",
        "requires": ("finite exact input",),
        "ensures": ("returns a finite exact output",),
        "exact": True,
        "shardable": False,
        "complexity": "O(1)",
        "failure_modes": (FailureMode("invalid", "invalid input"),),
        "certificate_type": None,
        "examples": (OperationExample("strict_flags()"),),
    }
    values[field] = invalid

    with pytest.raises(OperationSpecError, match=rf"{field} must be a boolean"):
        OperationSpec(**values)  # type: ignore[arg-type]
