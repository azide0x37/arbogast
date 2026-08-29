"""Tamper tests for the exact precomputed M23 theorem fixture."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from arbogast.hurwitz import (
    M23ExactCertificate,
    M23ExactDataset,
    load_m23_exact_dataset,
    m23_certificates_for,
    m23_claim_graph_for,
    m23_verifier_registry,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_LANE = PROJECT_ROOT / "examples/hurwitz/m23_real_component"
VERIFY_SCRIPT = SOURCE_LANE / "verify.py"


def _load_fixture_module() -> ModuleType:
    path = SOURCE_LANE / "fixture.py"
    spec = importlib.util.spec_from_file_location("arbogast_m23_fixture_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load M23 fixture verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXTURE = _load_fixture_module()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_lane(tmp_path: Path) -> tuple[Path, Path, Path]:
    lane = tmp_path / "m23_real_component"
    expected = lane / "expected"
    expected.mkdir(parents=True)
    for name in ("generate.g", "fixture.py"):
        shutil.copy2(SOURCE_LANE / name, lane / name)
    for name in ("dataset.json", "manifest.json", "generation-receipt.json", "sources.json"):
        shutil.copy2(SOURCE_LANE / "expected" / name, expected / name)
    return lane, expected / "manifest.json", expected / "dataset.json"


def _rewrite_bindings(lane: Path, manifest_path: Path, dataset_path: Path) -> None:
    """Rebind hashes so semantic tampering reaches the mathematical verifier."""

    receipt_path = lane / "expected/generation-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["dataset"]["sha256"] = _sha256(dataset_path)
    receipt["dataset"]["bytes"] = dataset_path.stat().st_size
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["dataset"]["sha256"] = _sha256(dataset_path)
    manifest["artifacts"]["dataset"]["bytes"] = dataset_path.stat().st_size
    manifest["artifacts"]["generation_receipt"]["sha256"] = _sha256(receipt_path)
    manifest["artifacts"]["generation_receipt"]["bytes"] = receipt_path.stat().st_size
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def test_exact_fixture_rejects_unbound_dataset_hash(tmp_path: Path) -> None:
    _, manifest_path, dataset_path = _copy_lane(tmp_path)
    dataset_path.write_bytes(dataset_path.read_bytes() + b" ")
    with pytest.raises(FIXTURE.FixtureVerificationError, match="SHA-256 mismatch"):
        FIXTURE.verify_fixture(manifest_path=manifest_path, dataset_path=dataset_path)


def test_exact_fixture_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    _, manifest_path, dataset_path = _copy_lane(tmp_path)
    text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        text.replace("{", '{"schema_version":"duplicate",', 1),
        encoding="utf-8",
    )
    with pytest.raises(FIXTURE.FixtureVerificationError, match="duplicate key"):
        FIXTURE.verify_fixture(manifest_path=manifest_path, dataset_path=dataset_path)


def test_exact_fixture_rejects_non_finite_json_numbers(tmp_path: Path) -> None:
    lane, manifest_path, dataset_path = _copy_lane(tmp_path)
    text = dataset_path.read_text(encoding="utf-8")
    changed = text.replace('"c1_fixed": 20', '"c1_fixed": NaN', 1)
    assert changed != text
    dataset_path.write_text(changed, encoding="utf-8")
    _rewrite_bindings(lane, manifest_path, dataset_path)
    with pytest.raises(FIXTURE.FixtureVerificationError, match="non-finite number"):
        FIXTURE.verify_fixture(manifest_path=manifest_path, dataset_path=dataset_path)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('{"schema_version":"a","schema_version":"b"}', "duplicate key"),
        ('{"schema_version":NaN}', "non-finite number"),
    ],
)
def test_projection_transport_rejects_noncanonical_json(
    tmp_path: Path, raw: str, message: str
) -> None:
    projection = tmp_path / "projection.json"
    projection.write_text(raw, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(projection)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert message in completed.stderr


def test_public_typed_loader_and_claim_graph_replay() -> None:
    dataset = load_m23_exact_dataset(
        SOURCE_LANE / "expected/manifest.json",
        SOURCE_LANE / "expected/dataset.json",
    )
    assert isinstance(dataset, M23ExactDataset)
    assert dataset.verification.component_cardinality == 1428
    assert dataset.verification.nongenerating_inner_orbits == 5686
    graph = m23_claim_graph_for(dataset, provenance_record="m23_236_public_exact_projection")
    certificates = m23_certificates_for(dataset)
    report = graph.verify(certificates, verifier_registry=m23_verifier_registry(dataset))
    assert report.verified
    assert len(graph) == len(certificates) == 6
    assert all(claim.source for claim in graph)
    assert all(claim.hypotheses for claim in graph)


def test_compute_uses_public_hurwitz_api_not_private_fixture_stack() -> None:
    compute_source = (SOURCE_LANE / "compute.py").read_text(encoding="utf-8")
    assert "from fixture" not in compute_source
    assert "VerificationCertificate" not in compute_source
    assert "load_m23_exact_dataset" in compute_source
    assert "m23_claim_graph_for" in compute_source
    assert "m23_certificates_for" in compute_source
    assert "m23_verifier_registry" in compute_source


def test_recomputed_summary_id_cannot_replace_full_dataset_replay() -> None:
    dataset = load_m23_exact_dataset(
        SOURCE_LANE / "expected/manifest.json",
        SOURCE_LANE / "expected/dataset.json",
    )
    forged_result = dataset.verification.to_dict()
    forged_result["component_cardinality"] = 999
    forged = M23ExactCertificate(
        dataset_sha256=dataset.verification.dataset_sha256,
        manifest_sha256=dataset.verification.manifest_sha256,
        result=forged_result,  # type: ignore[arg-type]
    )
    transported = M23ExactCertificate.from_dict(forged.to_dict())
    assert transported.certificate_id == forged.certificate_id
    assert not transported.verify(dataset)


def test_m23_certificate_transport_requires_exact_fields() -> None:
    dataset = load_m23_exact_dataset(
        SOURCE_LANE / "expected/manifest.json",
        SOURCE_LANE / "expected/dataset.json",
    )
    transported = dataset.certificate.to_dict()
    del transported["certificate_id"]
    with pytest.raises(FIXTURE.FixtureVerificationError, match="noncanonical fields"):
        M23ExactCertificate.from_dict(transported)


Mutation = Callable[[dict[str, object]], None]


def _vertex_tamper(dataset: dict[str, object]) -> None:
    vertex = dataset["vertices"][0][0]  # type: ignore[index]
    vertex[0], vertex[1] = vertex[1], vertex[0]


def _edge_tamper(dataset: dict[str, object]) -> None:
    transition = dataset["transitions"][0][0]  # type: ignore[index]
    transition[0] = (transition[0] + 1) % 1428


def _conjugator_tamper(dataset: dict[str, object]) -> None:
    transition = dataset["transitions"][0][0]  # type: ignore[index]
    transition[1] = list(range(1, 24))


def _real_index_tamper(dataset: dict[str, object]) -> None:
    indices = dataset["real"]["c1_indices"]  # type: ignore[index]
    indices[0] = 3


def _count_tamper(dataset: dict[str, object]) -> None:
    dataset["counts"]["c1_fixed"] = 21  # type: ignore[index]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (_vertex_tamper, "component contains a tuple absent|first 2A entry"),
        (_edge_tamper, "invalid braid edge"),
        (_conjugator_tamper, "invalid braid edge"),
        (_real_index_tamper, "c=1 fixed set"),
        (_count_tamper, "recorded counts"),
    ],
)
def test_exact_fixture_rejects_semantic_tampering(
    tmp_path: Path,
    mutation: Mutation,
    message: str,
) -> None:
    lane, manifest_path, dataset_path = _copy_lane(tmp_path)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    mutation(dataset)
    dataset_path.write_text(json.dumps(dataset) + "\n", encoding="utf-8")
    _rewrite_bindings(lane, manifest_path, dataset_path)

    with pytest.raises(FIXTURE.FixtureVerificationError, match=message):
        FIXTURE.verify_fixture(manifest_path=manifest_path, dataset_path=dataset_path)
