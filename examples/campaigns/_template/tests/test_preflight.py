from __future__ import annotations

import sys
import tomllib
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEMPLATE_ROOT / "src"))

import arbogast  # noqa: E402
from arbogast.fleet import ArtifactStore  # noqa: E402

from campaign_name.runtime import operation_registry, verifier_registry  # noqa: E402
from campaign_name.specification import OPERATION, VERIFIER  # noqa: E402


def test_preflight_binds_release_registries_and_artifact_custody(tmp_path: Path) -> None:
    project = tomllib.loads((TEMPLATE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == ["arbogast==0.6.0"]
    assert arbogast.__version__ == "0.6.0"
    assert (TEMPLATE_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13"
    readme = (TEMPLATE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "arbogast doctor --mode campaign --json > doctor-report.json" in readme
    assert "arbogast doctor --mode campaign --json > bootstrap-report.json" not in readme

    operations = operation_registry()
    verifiers = verifier_registry()
    assert operations.names() == (OPERATION,)
    assert verifiers.names() == (VERIFIER,)
    assert operations.resolve(OPERATION) is not None
    assert verifiers.describe(VERIFIER)["name"] == VERIFIER
    operation_manifest = operations.readiness_manifest((OPERATION,))["operations"][0]
    verifier_manifest = verifiers.readiness_manifest(
        (VERIFIER,),
        load_builtins=False,
    )["verifiers"][0]
    assert operation_manifest["certifiable"] is True
    assert operation_manifest["contract"]["closure_verifiers"] == [VERIFIER]
    assert verifier_manifest["certifiable"] is True

    store = ArtifactStore(tmp_path / "artifact-store")
    reference = store.put_json({"fixture": "campaign-template", "value": 2})
    assert store.verify(reference)
    assert store.get_json(reference) == {"fixture": "campaign-template", "value": 2}
