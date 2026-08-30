from __future__ import annotations

import inspect
from importlib import import_module

from arbogast.arithmetic import SelmerProblem, local_condition
from arbogast.galois import FinitePlace, InfinitePlace, NumberField, kummer_space, local_h1
from arbogast.galois import localize as kummer_localize
from arbogast.rep import cyclic_group
from arbogast.specs import (
    BUILTIN_IMPLEMENTATIONS,
    OPERATION_CONTRACT_MODULES,
    PUBLIC_FUNCTION_OPERATIONS,
    PUBLIC_NON_OPERATION_HELPERS,
    SHARD_PLANNERS,
    default_operations,
    get_operation_spec,
)


def test_every_exported_mathematical_function_has_one_live_contract() -> None:
    assert set(default_operations.names()) == set(BUILTIN_IMPLEMENTATIONS)
    assert tuple(PUBLIC_FUNCTION_OPERATIONS) == OPERATION_CONTRACT_MODULES

    for module_name, declared in PUBLIC_FUNCTION_OPERATIONS.items():
        module = import_module(module_name)
        helpers = PUBLIC_NON_OPERATION_HELPERS.get(module_name, {})
        actual_functions = {
            name for name in module.__all__ if inspect.isfunction(getattr(module, name))
        }
        assert actual_functions == set(declared) | set(helpers)

        for public_name, operation_name in declared.items():
            function = getattr(module, public_name)
            spec = default_operations.spec(operation_name)
            assert default_operations.implemented(operation_name)
            assert default_operations.function(operation_name) is function
            assert get_operation_spec(function) == spec
            assert spec.python_qualified_name == (f"{function.__module__}.{function.__qualname__}")
            assert spec.python_signature == str(inspect.signature(function))
            assert spec.input_types
            assert spec.output_type
            assert spec.requires
            assert spec.ensures
            assert spec.failure_modes
            assert spec.examples

        for helper_name, reason in helpers.items():
            helper = getattr(module, helper_name)
            assert inspect.isfunction(helper)
            assert reason.strip()
            assert not hasattr(helper, "__arbogast_operation__")


def test_shardability_is_backed_by_a_real_plan_run_reduce_surface() -> None:
    advertised = {spec.name for spec in default_operations.specs() if spec.shardable}
    assert advertised == set(SHARD_PLANNERS)
    for spec in default_operations.specs():
        assert bool(spec.shard_strategy) is spec.shardable

    for operation_name, (module_name, planner_name) in SHARD_PLANNERS.items():
        planner = getattr(import_module(module_name), planner_name)
        assert callable(planner)
        if operation_name == "hurwitz.nielsen_class":
            group = cyclic_group(1)
            classes = (group.conjugacy_class(group.identity),)
            plan = planner(group, classes, shards=2)
        else:
            field = NumberField.rationals()
            at_two = FinitePlace(field, 2, ((2,),), 1, 1)
            at_infinity = InfinitePlace(field, "real", (-1, 1))
            if operation_name == "galois.local_h1":
                plan = planner((at_two, at_infinity))
            elif operation_name == "galois.localize":
                global_space = kummer_space(field, (at_two, at_infinity))
                local_spaces = (local_h1(at_two), local_h1(at_infinity))
                plan = planner(global_space, local_spaces)
            elif operation_name == "arithmetic.selmer":
                global_space = kummer_space(field, (at_two, at_infinity))
                local_spaces = (local_h1(at_two), local_h1(at_infinity))
                localizations = tuple(
                    kummer_localize(global_space, local_space) for local_space in local_spaces
                )
                conditions = (
                    local_condition(
                        local_spaces[0],
                        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
                    ),
                    local_condition(local_spaces[1]),
                )
                problem = SelmerProblem(
                    global_space,
                    localizations,
                    conditions,
                    places=tuple(local_space.place for local_space in local_spaces),
                    place_set_complete=True,
                )
                plan = planner(problem)
            else:  # pragma: no cover - the equality assertion above closes this branch.
                raise AssertionError(f"unexercised shard planner: {operation_name}")
        assert callable(plan.run)
        assert callable(plan.run_all)
        assert callable(plan.reduce)
        if operation_name == "hurwitz.nielsen_class":
            # Immutable v0.1 behavior: asking the Nielsen planner for two
            # shards produces exactly two shard specifications.
            assert len(plan.shard_specs) == 2
        else:
            assert plan.shard_specs
        result = plan.reduce(plan.run_all())
        if isinstance(result, tuple):
            assert all(item.verify() for item in result)
        else:
            assert result.verify()
        assert default_operations.spec(operation_name).shard_strategy
