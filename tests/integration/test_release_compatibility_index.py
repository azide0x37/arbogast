"""Generic replay of immutable compatibility inputs from published releases."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from arbogast.formats import canonical_sha256, schema_document, schema_ids

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = PROJECT_ROOT / "tests/fixtures/compat/index.json"
V020_API_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.2.0/api-cli-contracts.json"
V020_SEMANTIC_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.2.0/semantic-contracts.json"
V020_COMMIT = "8cab7f03379b75cfe875e5b9717f5a831332dfa1"
V030_API_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.3.0/api-cli-contracts.json"
V030_SEMANTIC_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.3.0/semantic-contracts.json"
V030_COMMIT = "46aef45d7bb24893d552476aee2d9b17b3da7e43"
V040_API_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.4.0/api-cli-contracts.json"
V040_SEMANTIC_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.4.0/semantic-contracts.json"
V040_COMMIT = "771a1a150e02b0459ff82bf1b44e3c0fb7cdd933"
V050_API_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.5.0/api-cli-contracts.json"
V050_SEMANTIC_PATH = PROJECT_ROOT / "tests/fixtures/compat/v0.5.0/semantic-contracts.json"
V050_COMMIT = "a4852ec2d2d8ab0655cf6d1c2cfa5e641ea763a0"
V020_CERTIFICATE_IDS = (
    "sha256:7fc9a8a70169714070587e7abaebb5700ff4515f4eae9f376b464cedb2055e2e",
    "sha256:6dfabd77769bd8b7b58692c53deadb0caffae30535d526aa487c1c7eebfcbbeb",
    "sha256:2750040c28839e24955eadd6543e62d6a6495e2296a16908a2802516a17127a5",
)
V030_CERTIFICATE_IDS = (
    "sha256:7fc9a8a70169714070587e7abaebb5700ff4515f4eae9f376b464cedb2055e2e",
    "sha256:6dfabd77769bd8b7b58692c53deadb0caffae30535d526aa487c1c7eebfcbbeb",
    "sha256:2750040c28839e24955eadd6543e62d6a6495e2296a16908a2802516a17127a5",
    "sha256:ad8e666111f5c89f81dc558cb763e189216515ee714b3ae6f29ee03434e1db4d",
)
V040_CERTIFICATE_IDS = (
    *V030_CERTIFICATE_IDS,
    "sha256:659d84788e7a1e1cb31c10b37bd2f61c87b92a96b3b3705ba71b1a60a9a75374",
    "sha256:bd6a74e2581ab3aaed0fa6a73ef51e4395b2116670a36030168adb2545d684f3",
)
V050_CERTIFICATE_IDS = V040_CERTIFICATE_IDS
V020_ARTIFACTS = [
    {
        "bytes": 580623,
        "filename": "arbogast-0.2.0-py3-none-any.whl",
        "sha256": "sha256:b00b6c8c7f15e7c2a453d5fe3f4576a6c99a67d100f0278d7b563b09e1c1c7d6",
    },
    {
        "bytes": 1542655,
        "filename": "arbogast-0.2.0.tar.gz",
        "sha256": "sha256:14a3df09c2384074e427b5e9af2de5b44e17e2ffa3c6af2eddee77839d85d69e",
    },
    {
        "bytes": 1614206,
        "filename": "arbogast-0.2.0-source.tar.gz",
        "sha256": "sha256:c116f449544f293f3b7e5c6397101ef1d67114b96437a7d7478b95fcaa355293",
    },
]
V030_ARTIFACTS = [
    {
        "bytes": 645212,
        "filename": "arbogast-0.3.0-py3-none-any.whl",
        "sha256": "sha256:674c7ed3c06726c2e4ae2eb88985ce0b6a21115058d8086a21473253e80a7ec1",
    },
    {
        "bytes": 1693107,
        "filename": "arbogast-0.3.0.tar.gz",
        "sha256": "sha256:9ec291286aea27e997a6de5cfc6c444953e325fd479b42a3d24dce89a7620772",
    },
    {
        "bytes": 1758546,
        "filename": "arbogast-0.3.0-source.tar.gz",
        "sha256": "sha256:ede2a8c5b872168eff6d4abedcd10e5357cbbf9565822b8255303bffac01af4f",
    },
]
V040_ARTIFACTS = [
    {
        "bytes": 711694,
        "filename": "arbogast-0.4.0-py3-none-any.whl",
        "sha256": "sha256:7072e2da27614dbb0159347659b3d5b8518c1baf9ee889704ff6649ce3eb55ad",
    },
    {
        "bytes": 1838152,
        "filename": "arbogast-0.4.0.tar.gz",
        "sha256": "sha256:0e2b2dcb6805e805994c0d613afadbaeae39eb59a19efe7978679c9e645a10c5",
    },
    {
        "bytes": 1904418,
        "filename": "arbogast-0.4.0-source.tar.gz",
        "sha256": "sha256:f3d9dc05c3e5aad6a66248041fc5d20c506e502b8bc9c3bc5f5f90e3bd32cb71",
    },
]
V050_ARTIFACTS = [
    {
        "bytes": 844222,
        "filename": "arbogast-0.5.0-py3-none-any.whl",
        "sha256": "sha256:0c0b4cea977003f7de9032141372c96f1ec2802f1f489511d1444bf84a6fe4b6",
    },
    {
        "bytes": 2075723,
        "filename": "arbogast-0.5.0.tar.gz",
        "sha256": "sha256:5be85fdd516a5ff5125cc4d1b3d2062d6f780fd0ee254222cf2f349b30fd8a0d",
    },
    {
        "bytes": 2145015,
        "filename": "arbogast-0.5.0-source.tar.gz",
        "sha256": "sha256:e5c1e57bf4a4abad0bce17f5e254ddffdc0115029524ab8d4250c380983530cb",
    },
]
PARI_ANCHORS = [
    {
        "source_sha256": "0efdda7515d9d954f63324c34b34c560e60f73a81c3924a71260a2cc91d5f981",
        "source_url": "https://pari.math.u-bordeaux.fr/pub/pari/OLD/2.15/pari-2.15.5.tar.gz",
        "version": "2.15.5",
    },
    {
        "source_sha256": "02651d99c391007d384b3fadbc20abc6916b77036f9e496c99e9ce8688ca4b53",
        "source_url": "https://pari.math.u-bordeaux.fr/pub/pari/unix/pari-2.17.4.tar.gz",
        "version": "2.17.4",
    },
]


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_compatibility_index_pins_all_published_source_and_release_identities() -> None:
    index = _json(INDEX_PATH)
    assert index["schema_version"] == "arbogast.compatibility-index/v1"
    releases = index["releases"]
    assert [release["version"] for release in releases] == [
        "0.1.0",
        "0.2.0",
        "0.3.0",
        "0.4.0",
        "0.5.0",
    ]
    assert releases[0]["source_commit"] == "dfd1cc0fd7830ae77de2a04617fa21cece69dde2"
    assert releases[0]["source_tag"] == "v0.1.0"
    assert releases[1]["source_commit"] == V020_COMMIT
    assert releases[1]["source_tag"] == "v0.2.0"
    assert releases[1]["published_artifacts"] == V020_ARTIFACTS
    assert releases[2]["source_commit"] == V030_COMMIT
    assert releases[2]["source_tag"] == "v0.3.0"
    assert releases[2]["published_artifacts"] == V030_ARTIFACTS
    assert releases[3]["source_commit"] == V040_COMMIT
    assert releases[3]["source_tag"] == "v0.4.0"
    assert releases[3]["published_artifacts"] == V040_ARTIFACTS
    assert releases[4]["source_commit"] == V050_COMMIT
    assert releases[4]["source_tag"] == "v0.5.0"
    assert releases[4]["published_artifacts"] == V050_ARTIFACTS
    v040_manifest = _json(PROJECT_ROOT / "tests/fixtures/compat/v0.4.0/release.json")
    assert v040_manifest["github_release"] == {
        "id": 379302816,
        "platform_immutable": False,
        "published_at": "2026-08-30T14:17:14Z",
        "url": "https://github.com/azide0x37/arbogast/releases/tag/v0.4.0",
    }
    v050_manifest = _json(PROJECT_ROOT / "tests/fixtures/compat/v0.5.0/release.json")
    assert v050_manifest["github_release"] == {
        "id": 379322215,
        "platform_immutable": False,
        "published_at": "2026-08-30T15:32:56Z",
        "url": "https://github.com/azide0x37/arbogast/releases/tag/v0.5.0",
    }

    for release in releases:
        for record in (*release["fixture_files"], release["release_notes"]):
            path = PROJECT_ROOT / record["path"]
            assert path.stat().st_size == record["bytes"]
            assert _sha256(path) == record["sha256"].removeprefix("sha256:")


@pytest.mark.parametrize(
    ("path", "commit", "schema_count"),
    (
        (V020_SEMANTIC_PATH, V020_COMMIT, 41),
        (V030_SEMANTIC_PATH, V030_COMMIT, 96),
        (V040_SEMANTIC_PATH, V040_COMMIT, 160),
        (V050_SEMANTIC_PATH, V050_COMMIT, 249),
    ),
)
def test_published_schema_catalogs_and_backend_boundary_remain_additive(
    path: Path,
    commit: str,
    schema_count: int,
) -> None:
    snapshot = _json(path)
    assert snapshot["source_commit"] == commit
    catalog = snapshot["schema_catalog"]
    assert len(catalog) == schema_count
    current_ids = set(schema_ids())
    for record in catalog:
        identifier = record["identifier"]
        assert identifier in current_ids
        assert schema_document(identifier) == record["document"]
        assert record["document_sha256"] == f"sha256:{canonical_sha256(record['document'])}"

    assert snapshot["pari"] == {
        "ci_anchors": PARI_ANCHORS,
        "supported_range": ">=2.15.5,<2.18.0",
    }
    expected_certificates = {
        V020_SEMANTIC_PATH: V020_CERTIFICATE_IDS,
        V030_SEMANTIC_PATH: V030_CERTIFICATE_IDS,
        V040_SEMANTIC_PATH: V040_CERTIFICATE_IDS,
        V050_SEMANTIC_PATH: V050_CERTIFICATE_IDS,
    }[path]
    assert (
        tuple(record["certificate_id"] for record in snapshot["central_certificates"])
        == expected_certificates
    )
    if path in {V030_SEMANTIC_PATH, V040_SEMANTIC_PATH, V050_SEMANTIC_PATH}:
        identifiers = {record["identifier"] for record in catalog}
        assert {
            "arbogast.deform.artin-ring/v1",
            "arbogast.deform.artin-ring-receipt/v1",
        } <= identifiers
        deformation = next(
            record
            for record in snapshot["central_certificates"]
            if record["label"] == "deform.artin-ring-f3"
        )
        assert deformation["label"] == "deform.artin-ring-f3"
        assert deformation["deformation_receipt"]["schema_version"] == (
            "arbogast.deform.artin-ring-receipt/v1"
        )
        assert (
            deformation["deformation_receipt_id"]
            == deformation["deformation_receipt"]["certificate_id"]
        )
    if path in {V040_SEMANTIC_PATH, V050_SEMANTIC_PATH}:
        identifiers = {record["identifier"] for record in catalog}
        assert {
            "arbogast.numeric.algebraic-candidate/v1",
            "arbogast.numeric.algebraic-candidate-receipt/v1",
        } <= identifiers
        candidate, exactification = snapshot["central_certificates"][-2:]
        assert candidate["label"] == "numeric.recognize-sqrt2-candidate"
        assert candidate["numeric_claim_status"] == "numerical"
        assert candidate["numeric_receipt"]["schema_version"] == (
            "arbogast.numeric.algebraic-candidate-receipt/v1"
        )
        assert candidate["numeric_receipt_id"] == candidate["numeric_receipt"]["certificate_id"]
        assert exactification["label"] == "numeric.exactify-sqrt2"
        assert exactification["numeric_claim_status"] == "exact"
        assert exactification["numeric_receipt"]["schema_version"] == (
            "arbogast.numeric.exactification-result-receipt/v1"
        )
        assert (
            exactification["numeric_receipt_id"]
            == (exactification["numeric_receipt"]["certificate_id"])
        )
    if path == V050_SEMANTIC_PATH:
        identifiers = {record["identifier"] for record in catalog}
        assert {
            "arbogast.padic.ball/v1",
            "arbogast.padic.certified/v1",
            "arbogast.padic.field/v1",
            "arbogast.padic.good-reduction/v1",
            "arbogast.padic.unknown/v1",
            "arbogast.padic.unsupported/v1",
        } <= identifiers


@pytest.mark.skipif(
    sys.version_info[:2] != (3, 11),
    reason="immutable tag-isolated snapshots are pinned to CPython 3.11",
)
def test_published_api_cli_snapshots_rederive_from_exact_tags() -> None:
    commands = (
        (
            "0.1.0",
            "v0.1.0",
            "dfd1cc0fd7830ae77de2a04617fa21cece69dde2",
            PROJECT_ROOT / "tests/fixtures/compat/v0.1.0/api-cli-contracts.json",
        ),
        ("0.2.0", "v0.2.0", V020_COMMIT, V020_API_PATH),
        ("0.3.0", "v0.3.0", V030_COMMIT, V030_API_PATH),
        ("0.4.0", "v0.4.0", V040_COMMIT, V040_API_PATH),
        ("0.5.0", "v0.5.0", V050_COMMIT, V050_API_PATH),
    )
    for version, tag, commit, fixture in commands:
        completed = subprocess.run(
            (
                sys.executable,
                "scripts/snapshot_api_cli.py",
                "--version",
                version,
                "--source-tag",
                tag,
                "--source-commit",
                commit,
                "--check",
                str(fixture),
            ),
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.mark.skipif(
    sys.version_info[:2] != (3, 11),
    reason="immutable tag-isolated snapshots are pinned to CPython 3.11",
)
@pytest.mark.parametrize(
    ("version", "commit", "path"),
    (
        ("0.2.0", V020_COMMIT, V020_SEMANTIC_PATH),
        ("0.3.0", V030_COMMIT, V030_SEMANTIC_PATH),
        ("0.4.0", V040_COMMIT, V040_SEMANTIC_PATH),
        ("0.5.0", V050_COMMIT, V050_SEMANTIC_PATH),
    ),
)
def test_published_semantic_snapshots_rederive_from_exact_tags(
    version: str,
    commit: str,
    path: Path,
) -> None:
    completed = subprocess.run(
        (
            sys.executable,
            "scripts/snapshot_semantic_contracts.py",
            "--version",
            version,
            "--source-tag",
            f"v{version}",
            "--source-commit",
            commit,
            "--check",
            str(path),
        ),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.mark.parametrize(
    ("path", "expected_ids"),
    (
        (V020_SEMANTIC_PATH, V020_CERTIFICATE_IDS),
        (V030_SEMANTIC_PATH, V030_CERTIFICATE_IDS),
        (V040_SEMANTIC_PATH, V040_CERTIFICATE_IDS),
        (V050_SEMANTIC_PATH, V050_CERTIFICATE_IDS),
    ),
)
def test_published_central_certificates_replay_in_a_fresh_process(
    path: Path,
    expected_ids: tuple[str, ...],
) -> None:
    code = """
import json
import sys
import arbogast.arithmetic.semantic
import arbogast.galois.semantic
from arbogast.cert import VerificationCertificate, verify_certificate

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
if payload["version"] >= "0.3.0":
    import arbogast.deform.semantic
    from arbogast.deform import DeformationReceipt, verify_deformation_receipt
if payload["version"] >= "0.4.0":
    import arbogast.numeric.semantic
    from arbogast.numeric import NumericReceipt, verify_numeric_receipt
ids = []
for record in payload["central_certificates"]:
    if "deformation_receipt" in record:
        receipt = DeformationReceipt.from_dict(record["deformation_receipt"])
        assert receipt.certificate_id == record["deformation_receipt_id"]
        assert tuple(verify_deformation_receipt(receipt)) == tuple(
            record["deformation_receipt_checks"]
        )
    if "numeric_receipt" in record:
        receipt = NumericReceipt.from_dict(record["numeric_receipt"])
        assert receipt.certificate_id == record["numeric_receipt_id"]
        assert tuple(verify_numeric_receipt(receipt)) == tuple(record["numeric_receipt_checks"])
    certificate = VerificationCertificate.from_dict(record["certificate"])
    assert certificate.certificate_id == record["certificate_id"]
    assert verify_certificate(certificate).valid
    ids.append(certificate.certificate_id)
print("\\n".join(ids))
"""
    completed = subprocess.run(
        (sys.executable, "-I", "-c", code, str(path)),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert tuple(completed.stdout.splitlines()) == expected_ids
