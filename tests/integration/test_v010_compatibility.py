from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import subprocess
import sys
from copy import deepcopy
from enum import Enum
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import pytest

import arbogast.cohom.semantic  # noqa: F401 - registers the published v1 verifier
from arbogast.cert import ContentAddressError, VerificationCertificate, verify_certificate
from arbogast.cert.registry import _BUILTIN_VERIFIER_MODULES
from arbogast.claims import ClaimGraph
from arbogast.cli import build_parser
from arbogast.specs import PUBLIC_FUNCTION_OPERATIONS, PUBLIC_NON_OPERATION_HELPERS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests/fixtures/compat/v0.1.0"
RELEASE_PATH = FIXTURE_ROOT / "release.json"
H1_PATH = FIXTURE_ROOT / "h1-c2-f2.json"
PUBLIC_CONTRACTS_PATH = FIXTURE_ROOT / "public-contracts.json"
API_CLI_CONTRACTS_PATH = FIXTURE_ROOT / "api-cli-contracts.json"
V020_API_CLI_CONTRACTS_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.2.0/api-cli-contracts.json"
V030_API_CLI_CONTRACTS_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.3.0/api-cli-contracts.json"
V010_CERTIFICATE_ID = "sha256:52b76eed5ad4ab3ee16fa7b34920c680cdb68e82470c72cefadf06a3d9439377"
V010_CLAIM_ID = "cohom.h1.1574520bfd2136329bd615926e159f6fc568faedbf6cce2a988058c8904d562c"
V010_H1_FIXTURE_SHA256 = "9768c82cb12a7d04f8850244c0b686ce33ba2bb633ffc777c4d72a9aba433743"
V010_RELEASE_NOTES_SHA256 = "6bd4a9c04aa7cfadddd80b443fb67df49fb7e3756aa3e70c9e889091d7250ca6"
V010_PUBLIC_CONTRACTS_SHA256 = "8cbaf8089635ce156b27b70c1a33ec0e88f02f07ff4274ec15144aa5e158cb30"
V010_API_CLI_CONTRACTS_SHA256 = "36c759049c5c30c092fbc96ea4519326513a2f754d5b8158303a8cfe8bd62e4c"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_published_v010_release_inputs_are_pinned_and_immutable() -> None:
    release = _json(RELEASE_PATH)
    assert release["version"] == "0.1.0"
    assert release["source_tag"] == "v0.1.0"
    assert release["source_commit"] == "dfd1cc0fd7830ae77de2a04617fa21cece69dde2"
    assert release["published_artifacts"] == [
        {
            "bytes": 368096,
            "filename": "arbogast-0.1.0-py3-none-any.whl",
            "sha256": "sha256:e5c37b20d94720cd8cd9a14db2689694f4a90e4d009582a7b7837dabf35f9521",
        },
        {
            "bytes": 1238239,
            "filename": "arbogast-0.1.0.tar.gz",
            "sha256": "sha256:6f20622025a0bdebce76ce41c765380e9f4ab2574488fdc443ba1dd098c9b02c",
        },
    ]
    assert H1_PATH.stat().st_size == 7529
    assert _sha256(H1_PATH) == V010_H1_FIXTURE_SHA256
    assert PUBLIC_CONTRACTS_PATH.stat().st_size == 22326
    assert _sha256(PUBLIC_CONTRACTS_PATH) == V010_PUBLIC_CONTRACTS_SHA256
    assert API_CLI_CONTRACTS_PATH.stat().st_size == 404644
    assert _sha256(API_CLI_CONTRACTS_PATH) == V010_API_CLI_CONTRACTS_SHA256
    notes = PROJECT_ROOT / "docs/release-notes-0.1.0.md"
    assert notes.stat().st_size == 8390
    assert _sha256(notes) == V010_RELEASE_NOTES_SHA256


def test_every_published_v010_schema_identifier_remains_present() -> None:
    release = _json(RELEASE_PATH)
    stable = cast(list[str], release["stable_schema_ids"])
    assert stable == sorted(stable)
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for base in (PROJECT_ROOT / "src", PROJECT_ROOT / "examples")
        for path in sorted(base.rglob("*.py"))
    )
    missing = [identifier for identifier in stable if identifier not in source]
    assert missing == []


def test_published_v010_certificate_and_claim_graph_replay_unchanged() -> None:
    payload = _json(H1_PATH)
    certificate = VerificationCertificate.from_dict(payload["certificate"])
    assert certificate.certificate_id == V010_CERTIFICATE_ID
    report = verify_certificate(certificate)
    assert report.valid
    assert "kernel-recomputed" in report.checks

    graph = ClaimGraph.from_dict(payload["claim_graph"])
    assert graph.ids() == (V010_CLAIM_ID,)
    assert graph.verify().verified


def test_every_published_v010_public_signature_and_cli_command_remains_additive() -> None:
    inventory = _json(PUBLIC_CONTRACTS_PATH)
    assert inventory["source_commit"] == "dfd1cc0fd7830ae77de2a04617fa21cece69dde2"
    functions = cast(dict[str, dict[str, dict[str, str]]], inventory["functions"])
    for module_name, names in functions.items():
        module = import_module(module_name)
        for public_name, expected in names.items():
            function = getattr(module, public_name)
            assert PUBLIC_FUNCTION_OPERATIONS[module_name][public_name] == expected["operation"]
            assert f"{function.__module__}.{function.__qualname__}" == expected["qualified_name"]
            assert str(inspect.signature(function)) == expected["signature"]

    helpers = cast(dict[str, dict[str, dict[str, str]]], inventory["helpers"])
    for module_name, names in helpers.items():
        module = import_module(module_name)
        for public_name, expected in names.items():
            function = getattr(module, public_name)
            assert public_name in PUBLIC_NON_OPERATION_HELPERS[module_name]
            assert f"{function.__module__}.{function.__qualname__}" == expected["qualified_name"]
            assert str(inspect.signature(function)) == expected["signature"]

    parser = build_parser()
    commands = cast(
        Any,
        next(action for action in parser._actions if getattr(action, "choices", None)),
    )
    expected_cli = cast(dict[str, list[str]], inventory["cli"])
    assert set(expected_cli["commands"]) <= set(commands.choices)
    campaign = commands.choices["campaign"]
    campaign_commands = cast(
        Any,
        next(action for action in campaign._actions if getattr(action, "choices", None)),
    )
    assert set(expected_cli["campaign_commands"]) <= set(campaign_commands.choices)
    assert set(cast(list[str], inventory["builtin_verifier_ids"])) <= set(_BUILTIN_VERIFIER_MODULES)


def _identity(value: object) -> str:
    module = getattr(value, "__module__", type(value).__module__)
    qualname = getattr(value, "__qualname__", type(value).__qualname__)
    return f"{module}.{qualname}"


def _normalize_contract_value(value: object) -> object:
    if value is inspect.Signature.empty:
        return {"empty": True}
    if value is None or isinstance(value, (bool, float, int, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [_normalize_contract_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_contract_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if callable(value):
        return {"callable": _identity(value)}
    return {"identity": _identity(value), "repr": repr(value)}


def _parameter_record(parameter: inspect.Parameter) -> dict[str, object]:
    return {
        "annotation": _normalize_contract_value(parameter.annotation),
        "default": _normalize_contract_value(parameter.default),
        "kind": parameter.kind.name,
        "name": parameter.name,
    }


def _assert_additive_signature(expected: dict[str, object], value: object) -> None:
    if inspect.isclass(value) and issubclass(value, Enum):
        # EnumMeta's synthesized constructor signature changed from the
        # long-form ``(value, names=None, ...)`` on CPython 3.11/3.12 to
        # ``(*values)`` on 3.13/3.14.  That interpreter-owned signature is not
        # an Arbogast API change; replay the stable lookup contract instead.
        for member in value:
            assert value(member.value) is member
        return
    expected_parameters = expected["parameters"]
    if expected_parameters is None:
        assert expected["signature"] is None
        return
    assert isinstance(expected_parameters, list)
    actual = inspect.signature(cast(Any, value))
    actual_records = [_parameter_record(parameter) for parameter in actual.parameters.values()]
    expected_names = [cast(str, record["name"]) for record in expected_parameters]
    actual_names = [cast(str, record["name"]) for record in actual_records]

    # Old parameters must be an ordered subsequence with their complete call contract intact.
    cursor = 0
    for expected_record in expected_parameters:
        while (
            cursor < len(actual_records)
            and actual_records[cursor]["name"] != expected_record["name"]
        ):
            cursor += 1
        assert cursor < len(actual_records), f"missing old parameter {expected_record['name']}"
        actual_record = actual_records[cursor]
        expected_default = expected_record.get("default")
        actual_default = actual_record.get("default")
        if (
            isinstance(expected_default, dict)
            and set(expected_default) == {"identity"}
            and isinstance(actual_default, dict)
            and actual_default.get("identity") == expected_default["identity"]
        ):
            actual_record = {**actual_record, "default": expected_default}
        assert actual_record == expected_record
        cursor += 1

    old_names = set(expected_names)
    positional_kinds = {
        inspect.Parameter.POSITIONAL_ONLY.name,
        inspect.Parameter.POSITIONAL_OR_KEYWORD.name,
    }
    old_positional = [
        cast(str, record["name"])
        for record in expected_parameters
        if record["kind"] in positional_kinds
    ]
    actual_positional = [
        cast(str, record["name"]) for record in actual_records if record["kind"] in positional_kinds
    ]
    assert actual_positional[: len(old_positional)] == old_positional

    for name, parameter in actual.parameters.items():
        if name in old_names:
            continue
        assert (
            parameter.kind
            in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }
            or parameter.default is not inspect.Signature.empty
        ), f"new required parameter {name}"

    assert _normalize_contract_value(actual.return_annotation) == expected["return_annotation"]
    assert set(expected_names) <= set(actual_names)


@pytest.mark.parametrize(
    ("path", "source_commit", "module_count", "type_count"),
    (
        (
            API_CLI_CONTRACTS_PATH,
            "dfd1cc0fd7830ae77de2a04617fa21cece69dde2",
            17,
            346,
        ),
        (
            V020_API_CLI_CONTRACTS_PATH,
            "8cab7f03379b75cfe875e5b9717f5a831332dfa1",
            19,
            424,
        ),
        (
            V030_API_CLI_CONTRACTS_PATH,
            "46aef45d7bb24893d552476aee2d9b17b3da7e43",
            20,
            467,
        ),
    ),
    ids=("v0.1.0", "v0.2.0", "v0.3.0"),
)
def test_every_published_exported_type_identity_and_constructor_remains_additive(
    path: Path,
    source_commit: str,
    module_count: int,
    type_count: int,
) -> None:
    inventory = _json(path)
    assert inventory["source_commit"] == source_commit
    modules = cast(dict[str, list[dict[str, object]]], inventory["exported_types"])
    assert len(modules) == module_count
    assert sum(len(records) for records in modules.values()) == type_count
    for module_name, records in modules.items():
        module = import_module(module_name)
        exports = cast(Any, module).__all__
        for expected in records:
            public_name = cast(str, expected["export"])
            assert public_name in exports
            value = getattr(module, public_name)
            assert inspect.isclass(value)
            assert _identity(value) == expected["qualified_name"]
            _assert_additive_signature(expected, value)


@pytest.mark.parametrize(
    ("path", "module_count", "function_count"),
    (
        (V020_API_CLI_CONTRACTS_PATH, 17, 176),
        (V030_API_CLI_CONTRACTS_PATH, 18, 192),
    ),
    ids=("v0.2.0", "v0.3.0"),
)
def test_every_published_exported_function_identity_and_signature_remains_additive(
    path: Path,
    module_count: int,
    function_count: int,
) -> None:
    inventory = _json(path)
    modules = cast(dict[str, list[dict[str, object]]], inventory["exported_functions"])
    assert len(modules) == module_count
    assert sum(len(records) for records in modules.values()) == function_count
    for module_name, records in modules.items():
        module = import_module(module_name)
        exports = cast(Any, module).__all__
        for expected in records:
            public_name = cast(str, expected["export"])
            assert public_name in exports
            value = getattr(module, public_name)
            assert inspect.isfunction(value)
            assert _identity(value) == expected["qualified_name"]
            _assert_additive_signature(expected, value)


def _action_record(command_path: list[str], action: argparse.Action) -> dict[str, object]:
    kind = "positional" if not action.option_strings else "optional"
    choices = (
        sorted(action.choices)
        if isinstance(action.choices, dict)
        else _normalize_contract_value(action.choices)
    )
    return {
        "action_class": _identity(type(action)),
        "action_path": [*command_path, f"{kind}:{action.dest}"],
        "choices": choices,
        "const": _normalize_contract_value(action.const),
        "default": _normalize_contract_value(action.default),
        "dest": action.dest,
        "metavar": _normalize_contract_value(action.metavar),
        "nargs": _normalize_contract_value(action.nargs),
        "option_strings": list(action.option_strings),
        "required": action.required,
        "type": None if action.type is None else _identity(action.type),
    }


def _current_cli_contracts() -> dict[tuple[str, ...], dict[str, object]]:
    parsers: dict[tuple[str, ...], dict[str, object]] = {}

    def walk(parser: argparse.ArgumentParser, command_path: list[str]) -> None:
        actions = [_action_record(command_path, action) for action in parser._actions]
        paths = {
            id(action): record["action_path"]
            for action, record in zip(parser._actions, actions, strict=True)
        }
        parsers[tuple(command_path)] = {
            "actions": actions,
            "defaults": {
                key: _normalize_contract_value(value)
                for key, value in sorted(parser._defaults.items())
            },
            "mutually_exclusive_groups": [
                {
                    "action_paths": [paths[id(action)] for action in group._group_actions],
                    "required": group.required,
                }
                for group in parser._mutually_exclusive_groups
            ],
        }
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    walk(child, [*command_path, name])

    walk(build_parser(), [])
    return parsers


@pytest.mark.parametrize(
    ("path", "parser_count"),
    (
        (API_CLI_CONTRACTS_PATH, 15),
        (V020_API_CLI_CONTRACTS_PATH, 16),
        (V030_API_CLI_CONTRACTS_PATH, 16),
    ),
    ids=("v0.1.0", "v0.2.0", "v0.3.0"),
)
def test_every_published_cli_option_and_positional_contract_remains_additive(
    path: Path,
    parser_count: int,
) -> None:
    inventory = _json(path)
    expected_parsers = cast(list[dict[str, object]], inventory["cli_parsers"])
    assert len(expected_parsers) == parser_count
    actual_parsers = _current_cli_contracts()
    for expected_parser in expected_parsers:
        command_path = tuple(cast(list[str], expected_parser["command_path"]))
        actual_parser = actual_parsers[command_path]
        expected_actions = cast(list[dict[str, object]], expected_parser["actions"])
        actual_actions = cast(list[dict[str, object]], actual_parser["actions"])
        actual_by_key = {
            (bool(action["option_strings"]), action["dest"]): action for action in actual_actions
        }
        expected_keys = {
            (bool(action["option_strings"]), action["dest"]) for action in expected_actions
        }
        expected_positionals = [
            action["action_path"] for action in expected_actions if not action["option_strings"]
        ]
        actual_positionals = [
            action["action_path"] for action in actual_actions if not action["option_strings"]
        ]
        assert actual_positionals == expected_positionals
        for expected_action in expected_actions:
            action_key = (bool(expected_action["option_strings"]), expected_action["dest"])
            actual_action = actual_by_key[action_key]
            for field, expected_value in expected_action.items():
                actual_value = actual_action[field]
                if (
                    field == "choices"
                    and expected_action["action_class"] == "argparse._SubParsersAction"
                ):
                    assert actual_value is not None
                    assert all(
                        item in cast(list[object], actual_value)
                        for item in cast(list[object], expected_value)
                    )
                else:
                    assert actual_value == expected_value

        for actual_action in actual_actions:
            action_key = (bool(actual_action["option_strings"]), actual_action["dest"])
            if action_key not in expected_keys:
                assert actual_action["option_strings"], "new positional arguments are not additive"
                assert actual_action["required"] is False, "new required options are not additive"

        expected_defaults = cast(dict[str, object], expected_parser["defaults"])
        actual_defaults = cast(dict[str, object], actual_parser["defaults"])
        for default_name, value in expected_defaults.items():
            assert actual_defaults[default_name] == value
        for group in cast(list[dict[str, object]], expected_parser["mutually_exclusive_groups"]):
            assert group in cast(
                list[dict[str, object]], actual_parser["mutually_exclusive_groups"]
            )


def test_v010_api_cli_fixture_rederives_from_the_isolated_commit_on_cpython311() -> None:
    if sys.version_info[:2] != (3, 11):
        pytest.skip("the immutable compatibility snapshot is pinned to CPython 3.11")
    completed = subprocess.run(
        (
            sys.executable,
            "scripts/snapshot_v010_api_cli.py",
            "--check",
            str(API_CLI_CONTRACTS_PATH),
        ),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert V010_API_CLI_CONTRACTS_SHA256 in completed.stdout


def test_published_v010_fixture_replays_in_a_fresh_process() -> None:
    code = """
import json
import sys
import arbogast.cohom.semantic
from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.claims import ClaimGraph

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
certificate = VerificationCertificate.from_dict(payload["certificate"])
assert verify_certificate(certificate).valid
assert ClaimGraph.from_dict(payload["claim_graph"]).verify().verified
print(certificate.certificate_id)
"""
    completed = subprocess.run(
        (sys.executable, "-I", "-c", code, str(H1_PATH)),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip() == V010_CERTIFICATE_ID


def test_published_v010_certificate_id_tampering_is_rejected() -> None:
    payload = _json(H1_PATH)
    tampered = deepcopy(payload["certificate"])
    tampered["certificate_id"] = "sha256:" + "0" * 64
    with pytest.raises(ContentAddressError, match="content address mismatch"):
        VerificationCertificate.from_dict(tampered)
