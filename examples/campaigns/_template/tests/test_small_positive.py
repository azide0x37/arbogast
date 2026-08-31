from __future__ import annotations

import sys
from pathlib import Path

import pytest

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEMPLATE_ROOT / "src"))

from campaign_name import runtime  # noqa: E402

BOOTSTRAP_FILES = {
    "bootstrap-report.json",
    "environment-snapshot.json",
    "readiness-certificate.json",
    "readiness-claim.json",
    "readiness-profile.json",
}


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


def test_small_positive_campaign_is_ready_closed_and_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _locked_project(tmp_path / "project")
    monkeypatch.setattr(runtime, "PROJECT_ROOT", project_root)
    output = tmp_path / "run"

    snapshot = runtime.run_campaign(output)

    assert snapshot == output / "campaign.json"
    assert {path.name for path in output.iterdir()} >= BOOTSTRAP_FILES
    assert (output / "ledger.json").is_file()
    assert (output / "claims.json").is_file()
    assert runtime.verify_certificate_path(output / "certificate.json").require_valid().valid

    saved = runtime.status(snapshot)
    assert saved["closed_targets"] == 1
    assert saved["open_targets"] == 0
    assert saved["observed_tasks"] == 1
    assert saved["candidate_count"] == 1
    assert saved["verified_candidate_count"] == 1
    assert saved["outcomes"] == {"FOUND": 1}
