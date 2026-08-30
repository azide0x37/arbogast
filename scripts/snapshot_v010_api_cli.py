#!/usr/bin/env python3
"""Reproduce the immutable v0.1.0 exported-type and CLI contract snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE_COMMIT: Final = "dfd1cc0fd7830ae77de2a04617fa21cece69dde2"
FIXTURE_PATH: Final = PROJECT_ROOT / "tests/fixtures/compat/v0.1.0/api-cli-contracts.json"

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
    records = []
    for export_name in exports:
        value = getattr(module, export_name)
        if not inspect.isclass(value):
            continue
        try:
            signature_object = inspect.signature(value)
        except (TypeError, ValueError):
            parameters = None
            return_annotation = None
            signature = None
        else:
            parameters = [
                {
                    "annotation": normalize(parameter.annotation),
                    "default": normalize(parameter.default),
                    "kind": parameter.kind.name,
                    "name": parameter.name,
                }
                for parameter in signature_object.parameters.values()
            ]
            return_annotation = normalize(signature_object.return_annotation)
            signature = str(signature_object)
        records.append(
            {
                "export": export_name,
                "parameters": parameters,
                "qualified_name": identity(value),
                "return_annotation": return_annotation,
                "signature": signature,
            }
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
print(json.dumps({"cli_parsers": cli_parsers, "exported_types": exported_types}))
"""


def snapshot() -> bytes:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("the immutable v0.1.0 snapshot must be generated with CPython 3.11")
    resolved = subprocess.run(
        ("git", "rev-parse", "--verify", f"{SOURCE_COMMIT}^{{commit}}"),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if resolved != SOURCE_COMMIT:
        raise RuntimeError(f"v0.1.0 source commit resolved unexpectedly: {resolved}")
    archive = subprocess.run(
        ("git", "archive", SOURCE_COMMIT),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="arbogast-v010-api-") as temporary:
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
    payload = json.loads(completed.stdout)
    payload.update(
        {
            "derivation": {
                "command": (
                    "uv run --offline python scripts/snapshot_v010_api_cli.py --check "
                    "tests/fixtures/compat/v0.1.0/api-cli-contracts.json"
                ),
                "import_isolation": "python -I with only git-archive/src explicitly prepended",
                "python": "CPython 3.11",
                "source": f"git archive {SOURCE_COMMIT}",
            },
            "schema_version": "arbogast.compatibility-api-cli/v1",
            "source_commit": SOURCE_COMMIT,
            "source_tag": "v0.1.0",
            "version": "0.1.0",
        }
    )
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", type=Path, help="require an existing snapshot to match byte-for-byte"
    )
    args = parser.parse_args()
    encoded = snapshot()
    if args.check is None:
        sys.stdout.buffer.write(encoded)
        return 0
    expected = args.check.read_bytes()
    if expected != encoded:
        print(f"snapshot mismatch: {args.check}", file=sys.stderr)
        return 1
    print(f"sha256:{hashlib.sha256(encoded).hexdigest()}  {args.check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
