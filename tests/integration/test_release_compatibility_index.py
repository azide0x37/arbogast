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
V020_CERTIFICATE_IDS = (
    "sha256:7fc9a8a70169714070587e7abaebb5700ff4515f4eae9f376b464cedb2055e2e",
    "sha256:6dfabd77769bd8b7b58692c53deadb0caffae30535d526aa487c1c7eebfcbbeb",
    "sha256:2750040c28839e24955eadd6543e62d6a6495e2296a16908a2802516a17127a5",
)
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


def test_compatibility_index_pins_v010_and_v020_source_and_release_identities() -> None:
    index = _json(INDEX_PATH)
    assert index["schema_version"] == "arbogast.compatibility-index/v1"
    releases = index["releases"]
    assert [release["version"] for release in releases] == ["0.1.0", "0.2.0"]
    assert releases[0]["source_commit"] == "dfd1cc0fd7830ae77de2a04617fa21cece69dde2"
    assert releases[0]["source_tag"] == "v0.1.0"
    assert releases[1]["source_commit"] == V020_COMMIT
    assert releases[1]["source_tag"] == "v0.2.0"
    assert releases[1]["published_artifacts"] == V020_ARTIFACTS

    for release in releases:
        for record in (*release["fixture_files"], release["release_notes"]):
            path = PROJECT_ROOT / record["path"]
            assert path.stat().st_size == record["bytes"]
            assert _sha256(path) == record["sha256"].removeprefix("sha256:")


def test_v020_schema_catalog_documents_and_backend_boundary_remain_additive() -> None:
    snapshot = _json(V020_SEMANTIC_PATH)
    assert snapshot["source_commit"] == V020_COMMIT
    catalog = snapshot["schema_catalog"]
    assert len(catalog) == 41
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
    assert (
        tuple(record["certificate_id"] for record in snapshot["central_certificates"])
        == V020_CERTIFICATE_IDS
    )


@pytest.mark.skipif(
    sys.version_info[:2] != (3, 11),
    reason="immutable tag-isolated snapshots are pinned to CPython 3.11",
)
def test_v010_and_v020_api_cli_snapshots_rederive_from_exact_tags() -> None:
    commands = (
        (
            "0.1.0",
            "v0.1.0",
            "dfd1cc0fd7830ae77de2a04617fa21cece69dde2",
            PROJECT_ROOT / "tests/fixtures/compat/v0.1.0/api-cli-contracts.json",
        ),
        ("0.2.0", "v0.2.0", V020_COMMIT, V020_API_PATH),
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
def test_v020_semantic_snapshot_rederives_from_exact_tag() -> None:
    completed = subprocess.run(
        (
            sys.executable,
            "scripts/snapshot_semantic_contracts.py",
            "--version",
            "0.2.0",
            "--source-tag",
            "v0.2.0",
            "--source-commit",
            V020_COMMIT,
            "--check",
            str(V020_SEMANTIC_PATH),
        ),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_v020_central_certificates_replay_in_a_fresh_process() -> None:
    code = """
import json
import sys
import arbogast.arithmetic.semantic
import arbogast.galois.semantic
from arbogast.cert import VerificationCertificate, verify_certificate

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
ids = []
for record in payload["central_certificates"]:
    certificate = VerificationCertificate.from_dict(record["certificate"])
    assert certificate.certificate_id == record["certificate_id"]
    assert verify_certificate(certificate).valid
    ids.append(certificate.certificate_id)
print("\\n".join(ids))
"""
    completed = subprocess.run(
        (sys.executable, "-I", "-c", code, str(V020_SEMANTIC_PATH)),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert tuple(completed.stdout.splitlines()) == V020_CERTIFICATE_IDS
