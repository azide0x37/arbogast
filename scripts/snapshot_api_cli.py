#!/usr/bin/env python3
"""Snapshot exported types and CLI contracts from one exact tagged release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
VERSION_RE: Final = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")

_ISOLATED_SNAPSHOT = r"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

archive_root = Path(sys.argv[1]).resolve()
source_root = archive_root / "src"
sys.path.insert(0, str(source_root))


def identity(value):
    module = getattr(value, "__module__", type(value).__module__)
    qualname = getattr(value, "__qualname__", type(value).__qualname__)
    return f"{module}.{qualname}"


def normalize(value):
    if value is inspect.Signature.empty:
        return {"empty": True}
    if value is None or isinstance(value, (bool, float, int, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): normalize(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if callable(value):
        return {"callable": identity(value)}
    return {"identity": identity(value), "repr": repr(value)}


def normalize_function_value(value):
    if value is inspect.Signature.empty:
        return {"empty": True}
    if value is None or isinstance(value, (bool, float, int, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [normalize_function_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): normalize_function_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if callable(value):
        return {"callable": identity(value)}
    return {"identity": identity(value)}


exported_functions = {}
exported_types = {}
package_root = source_root / "arbogast"
for init_file in sorted(package_root.rglob("__init__.py")):
    module_name = ".".join(init_file.relative_to(source_root).with_suffix("").parts[:-1])
    module = __import__(module_name, fromlist=["*"])
    module_file = Path(module.__file__).resolve()
    if not module_file.is_relative_to(source_root):
        raise RuntimeError(f"non-archive import for {module_name}: {module_file}")
    exports = getattr(module, "__all__", None)
    if not isinstance(exports, (tuple, list)):
        continue
    function_records = []
    records = []
    for export_name in exports:
        value = getattr(module, export_name)
        if not inspect.isclass(value) and not inspect.isfunction(value):
            continue
        normalizer = normalize if inspect.isclass(value) else normalize_function_value
        try:
            signature_object = inspect.signature(value)
        except (TypeError, ValueError):
            parameters = None
            return_annotation = None
            signature = None
        else:
            parameters = [
                {
                    "annotation": normalizer(parameter.annotation),
                    "default": normalizer(parameter.default),
                    "kind": parameter.kind.name,
                    "name": parameter.name,
                }
                for parameter in signature_object.parameters.values()
            ]
            return_annotation = normalizer(signature_object.return_annotation)
            signature = str(signature_object) if inspect.isclass(value) else None
        record = (
            {
                "export": export_name,
                "parameters": parameters,
                "qualified_name": identity(value),
                "return_annotation": return_annotation,
                "signature": signature,
            }
        )
        if inspect.isclass(value):
            records.append(record)
        else:
            function_records.append(record)
    if function_records:
        exported_functions[module_name] = sorted(
            function_records, key=lambda record: record["export"]
        )
    if records:
        exported_types[module_name] = sorted(records, key=lambda record: record["export"])

from arbogast.cli import build_parser


def action_record(command_path, action):
    kind = "positional" if not action.option_strings else "optional"
    choices = (
        sorted(action.choices)
        if isinstance(action.choices, dict)
        else normalize(action.choices)
    )
    return {
        "action_class": identity(type(action)),
        "action_path": [*command_path, f"{kind}:{action.dest}"],
        "choices": choices,
        "const": normalize(action.const),
        "default": normalize(action.default),
        "dest": action.dest,
        "metavar": normalize(action.metavar),
        "nargs": normalize(action.nargs),
        "option_strings": list(action.option_strings),
        "required": action.required,
        "type": None if action.type is None else identity(action.type),
    }


cli_parsers = []


def walk(parser, command_path):
    actions = [action_record(command_path, action) for action in parser._actions]
    action_paths = {
        id(action): record["action_path"]
        for action, record in zip(parser._actions, actions, strict=True)
    }
    groups = [
        {
            "action_paths": [action_paths[id(action)] for action in group._group_actions],
            "required": group.required,
        }
        for group in parser._mutually_exclusive_groups
    ]
    cli_parsers.append(
        {
            "actions": actions,
            "command_path": command_path,
            "defaults": {
                key: normalize(value) for key, value in sorted(parser._defaults.items())
            },
            "mutually_exclusive_groups": groups,
        }
    )
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                walk(child, [*command_path, name])


walk(build_parser(), [])
print(
    json.dumps(
        {
            "cli_parsers": cli_parsers,
            "exported_functions": exported_functions,
            "exported_types": exported_types,
        }
    )
)
"""


def _resolve_commit(reference: str) -> str:
    return subprocess.run(
        ("git", "rev-parse", "--verify", f"{reference}^{{commit}}"),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def snapshot(
    *,
    version: str,
    source_tag: str,
    source_commit: str,
    derivation_command: str | None = None,
) -> bytes:
    """Derive one deterministic snapshot from an isolated Git archive."""

    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("compatibility API/CLI snapshots must be generated with CPython 3.11")
    if VERSION_RE.fullmatch(version) is None:
        raise ValueError("version must have final X.Y.Z form")
    if source_tag != f"v{version}":
        raise ValueError("source tag must be exactly v<version>")
    if COMMIT_RE.fullmatch(source_commit) is None:
        raise ValueError("source commit must be a full lowercase SHA-1")
    resolved_tag = _resolve_commit(source_tag)
    resolved_commit = _resolve_commit(source_commit)
    if resolved_tag != source_commit or resolved_commit != source_commit:
        raise RuntimeError(
            f"{source_tag} source identity mismatch: expected {source_commit}, "
            f"resolved tag={resolved_tag}, commit={resolved_commit}"
        )

    archive = subprocess.run(
        ("git", "archive", source_commit),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    prefix = f"arbogast-v{version.replace('.', '')}-api-"
    with tempfile.TemporaryDirectory(prefix=prefix) as temporary:
        archive_root = Path(temporary)
        with tarfile.open(fileobj=BytesIO(archive), mode="r:") as stream:
            stream.extractall(archive_root, filter="data")
        completed = subprocess.run(
            (sys.executable, "-I", "-c", _ISOLATED_SNAPSHOT, str(archive_root)),
            cwd=archive_root,
            check=True,
            capture_output=True,
            text=True,
        )

    fixture = f"tests/fixtures/compat/v{version}/api-cli-contracts.json"
    if derivation_command is not None:
        command = derivation_command
    elif version == "0.1.0":
        # This string is part of the already-published immutable v0.1 fixture.
        command = (
            "uv run --offline python scripts/snapshot_v010_api_cli.py --check "
            "tests/fixtures/compat/v0.1.0/api-cli-contracts.json"
        )
    else:
        command = (
            "uv run --offline python scripts/snapshot_api_cli.py "
            f"--version {version} --source-tag {source_tag} --source-commit {source_commit} "
            f"--check {fixture}"
        )
    payload = json.loads(completed.stdout)
    if version == "0.1.0":
        # Public functions had a separate immutable v0.1 snapshot; do not alter
        # the already-published exported-type/CLI fixture bytes.
        payload.pop("exported_functions", None)
    payload.update(
        {
            "derivation": {
                "command": command,
                "import_isolation": "python -I with only git-archive/src explicitly prepended",
                "python": "CPython 3.11",
                "source": f"git archive {source_commit}",
            },
            "schema_version": "arbogast.compatibility-api-cli/v1",
            "source_commit": source_commit,
            "source_tag": source_tag,
            "version": version,
        }
    )
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _write_or_check(encoded: bytes, *, output: Path | None, check: Path | None) -> int:
    if output is not None and check is not None:
        raise ValueError("--output and --check are mutually exclusive")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
        print(f"sha256:{hashlib.sha256(encoded).hexdigest()}  {output}")
        return 0
    if check is not None:
        if check.read_bytes() != encoded:
            print(f"snapshot mismatch: {check}", file=sys.stderr)
            return 1
        print(f"sha256:{hashlib.sha256(encoded).hexdigest()}  {check}")
        return 0
    sys.stdout.buffer.write(encoded)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--source-commit", required=True)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--check", type=Path)
    args = parser.parse_args()
    encoded = snapshot(
        version=args.version,
        source_tag=args.source_tag,
        source_commit=args.source_commit,
    )
    return _write_or_check(encoded, output=args.output, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
