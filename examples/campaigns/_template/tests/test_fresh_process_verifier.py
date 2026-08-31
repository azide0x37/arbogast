from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEMPLATE_ROOT / "src"))

from campaign_name import runtime  # noqa: E402


def _locked_project(root: Path) -> Path:
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "campaign-name"\nversion = "0.1.0"\nrequires-python = ">=3.11,<3.15"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        'version = 1\nrevision = 3\nrequires-python = ">=3.11,<3.15"\n\n'
        '[[package]]\nname = "campaign-name"\nversion = "0.1.0"\n'
        'source = { virtual = "." }\n',
        encoding="utf-8",
    )
    return root


def test_certificate_replays_in_a_fresh_process_without_discovery_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _locked_project(tmp_path / "project")
    monkeypatch.setattr(runtime, "PROJECT_ROOT", project_root)
    output = tmp_path / "run"
    runtime.run_campaign(output)

    script = "\n".join(
        (
            "import sys",
            "from pathlib import Path",
            "from arbogast.export import export_json",
            "from campaign_name.runtime import verifier_registry, verify_certificate_path",
            "manifest = verifier_registry().readiness_manifest(load_builtins=False)",
            "assert manifest['verifiers'][0]['certifiable'] is True",
            "report = verify_certificate_path(Path(sys.argv[1])).require_valid()",
            "assert 'campaign_name.operations' not in sys.modules",
            "print(export_json(report.to_canonical()))",
        )
    )
    environment = os.environ.copy()
    source = str(TEMPLATE_ROOT / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source, environment.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(output / "certificate.json")],
        cwd=TEMPLATE_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["valid"] is True
