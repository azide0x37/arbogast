from __future__ import annotations

import inspect
from importlib import import_module

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

    group = cyclic_group(1)
    classes = (group.conjugacy_class(group.identity),)
    for operation_name, (module_name, planner_name) in SHARD_PLANNERS.items():
        planner = getattr(import_module(module_name), planner_name)
        assert callable(planner)
        plan = planner(group, classes, shards=2)
        assert callable(plan.run)
        assert callable(plan.run_all)
        assert callable(plan.reduce)
        assert len(plan.shard_specs) == 2
        result = plan.reduce(plan.run_all())
        assert result.verify()
        assert default_operations.spec(operation_name).shard_strategy
