from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEMPLATE_ROOT / "src"))

from arbogast.bootstrap import (  # noqa: E402
    CertifiedBlocked,
    ReadinessProfile,
    capture_environment,
    certify_campaign_readiness,
)
from arbogast.campaign import CampaignReadinessError  # noqa: E402
from arbogast.cert import CertificateError, ContentAddressError  # noqa: E402
from arbogast.fleet import FleetOperationRegistry  # noqa: E402

from campaign_name import runtime  # noqa: E402
from campaign_name.specification import VERIFIER  # noqa: E402


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


def test_blocked_readiness_and_tampering_never_become_mathematical_negatives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _locked_project(tmp_path / "project")
    monkeypatch.setattr(runtime, "PROJECT_ROOT", project_root)

    blocked_runtime = runtime.build_runtime(tmp_path / "blocked")
    blocked_plan = blocked_runtime.campaign.recommend(limit=1)
    blocked_profile = ReadinessProfile.from_plan(
        blocked_runtime.campaign,
        blocked_plan,
        FleetOperationRegistry(),
        blocked_runtime.verifiers,
        blocked_runtime.executor,
        required_verifiers=(VERIFIER,),
    )
    blocked = certify_campaign_readiness(
        environment=capture_environment(project_root=project_root),
        profile=blocked_profile,
    )

    assert isinstance(blocked, CertifiedBlocked)
    blocked.verify()
    with pytest.raises(CampaignReadinessError) as activation_error:
        blocked_runtime.campaign.activate_readiness(blocked.certificate)
    assert activation_error.value.code == "READINESS_ACTIVATION_INVALID"
    blocked_status = blocked_runtime.campaign.status()
    assert blocked_status.observed_tasks == 0
    assert blocked_status.live_attempts == 0
    assert blocked_status.terminal_attempts == 0

    output = tmp_path / "tamper"
    runtime.run_campaign(output)
    certificate_path = output / "certificate.json"
    encoded = json.loads(certificate_path.read_text(encoding="utf-8"))
    encoded["witness"]["rows"][0]["square"] = 1
    certificate_path.write_text(json.dumps(encoded), encoding="utf-8")
    with pytest.raises((CertificateError, ContentAddressError)):
        runtime.verify_certificate_path(certificate_path)
