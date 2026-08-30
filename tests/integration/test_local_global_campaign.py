from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from arbogast.campaign import Outcome, OutcomeScope
from arbogast.cert import CertificateVerificationError, certificate_from_dict, verify_certificate
from arbogast.fleet import TaskSpec


def _load_example() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "examples"
        / "campaigns"
        / "antieau_klueners_malle"
        / "local_global.py"
    )
    spec = importlib.util.spec_from_file_location("arbogast_example_local_global", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXAMPLE = _load_example()


def test_certified_local_global_campaign_preserves_all_three_boundaries(tmp_path: Path) -> None:
    campaign = EXAMPLE.build_campaign(tmp_path)
    observations = campaign.run()

    assert len(observations) == 5
    assert campaign.status().closed_targets == 2
    assert campaign.status().open_targets == 1
    by_target = {
        target.parameters["target"]: campaign.ledger.status(target) for target in campaign.targets
    }
    assert by_target[2].mathematical_outcome.value == Outcome.PROVED_IMPOSSIBLE.value
    assert by_target[-1].mathematical_outcome.value == Outcome.FOUND.value
    assert by_target[11].open
    unknown = next(item for item in observations if item.outcome is Outcome.UNKNOWN)
    assert unknown.outcome_scope is OutcomeScope.TASK_LOCAL
    assert not unknown.closes_target
    assert len(campaign.claims) == 2


def test_local_reducer_rejects_reordered_shards() -> None:
    field = EXAMPLE.golden_field()
    task = TaskSpec(
        operation=EXAMPLE.LOCAL_OPERATION,
        input_refs=(field.content_id,),
        parameters={"field_id": field.field_id, "target": 11, "target_id": "target-11"},
    )
    partials = EXAMPLE._expected_local_partials(task)

    with pytest.raises(ValueError, match="missing, duplicate, foreign, or reordered"):
        EXAMPLE.reduce_local(task, tuple(reversed(partials)))


def test_local_certificate_tamper_is_recomputed_not_trusted() -> None:
    field = EXAMPLE.golden_field()
    task = TaskSpec(
        operation=EXAMPLE.LOCAL_OPERATION,
        input_refs=(field.content_id,),
        parameters={"field_id": field.field_id, "target": 2, "target_id": "target-2"},
    )
    result = EXAMPLE.reduce_local(task, EXAMPLE._expected_local_partials(task))
    payload = dict(result["certificate"])
    witness = dict(payload["witness"])
    rows = [dict(row) for row in witness["local_rows"]]
    rows[1]["hilbert_symbol"] = 1
    rows[1]["obstructed"] = False
    witness["local_rows"] = rows
    payload["witness"] = witness
    payload.pop("certificate_id")
    tampered = certificate_from_dict(payload)

    with pytest.raises(CertificateVerificationError, match="Hilbert table"):
        verify_certificate(tampered)
