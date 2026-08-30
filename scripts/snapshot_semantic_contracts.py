#!/usr/bin/env python3
"""Snapshot schema, certificate, and PARI boundaries from one exact tagged release."""

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

from snapshot_api_cli import COMMIT_RE, PROJECT_ROOT, VERSION_RE, _resolve_commit

_ISOLATED_SNAPSHOT = r"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

archive_root = Path(sys.argv[1]).resolve()
snapshot_version = tuple(int(part) for part in sys.argv[2].split("."))
source_root = archive_root / "src"
sys.path.insert(0, str(source_root))

from arbogast.arithmetic import SelmerGroup, aim, local_condition, selmer
from arbogast.backends.pari import PARI_SUPPORTED_RANGE
from arbogast.cert import verify_certificate
from arbogast.formats import canonical_sha256, schema_document, schema_ids
from arbogast.galois import (
    FinitePlace,
    InfinitePlace,
    KummerSpace,
    LocalH1Space,
    LocalizationMap,
    NumberField,
    kummer_space,
    local_h1,
    localize,
)
from arbogast.linalg import DenseMatrix, PrimeField


def certificate_record(label, result):
    report = result.verify()
    if hasattr(report, "valid") and not report.valid:
        raise RuntimeError(f"{label} result verification failed")
    certificate = result.certificate
    replay = verify_certificate(certificate)
    if not replay.valid:
        raise RuntimeError(f"{label} central certificate replay failed")
    claim = result.claim()
    graph = result.claim_graph()
    if not graph.verify().verified:
        raise RuntimeError(f"{label} claim graph replay failed")
    return {
        "certificate": certificate.to_dict(),
        "certificate_id": certificate.certificate_id,
        "claim_id": claim.id,
        "label": label,
        "result_type": f"{type(result).__module__}.{type(result).__qualname__}",
        "verification_checks": list(replay.checks),
    }


schemas = []
for identifier in schema_ids():
    document = schema_document(identifier)
    schemas.append(
        {
            "document": document,
            "document_sha256": f"sha256:{canonical_sha256(document)}",
            "identifier": identifier,
        }
    )

rationals = NumberField.rationals()
place_2 = FinitePlace(rationals, 2, ((2,),), 1, 1)
place_real = InfinitePlace(rationals, "real", (-1, 1), embedding_index=0)
global_space = kummer_space(rationals, (place_2, place_real))
if not isinstance(global_space, KummerSpace):
    raise RuntimeError("tagged rational Kummer fixture became unsupported")
h1_2 = local_h1(place_2)
h1_real = local_h1(place_real)
if not isinstance(h1_2, LocalH1Space) or not isinstance(h1_real, LocalH1Space):
    raise RuntimeError("tagged rational local H1 fixture became unsupported")
localization_2 = localize(global_space, h1_2)
localization_real = localize(global_space, h1_real)
if not isinstance(localization_2, LocalizationMap) or not isinstance(
    localization_real, LocalizationMap
):
    raise RuntimeError("tagged rational localization fixture became unsupported")

condition_2 = local_condition(
    h1_2,
    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
)
condition_real = local_condition(h1_real)
selmer_result = selmer(
    global_space,
    {place_2: localization_2, place_real: localization_real},
    {place_2: condition_2, place_real: condition_real},
    places=global_space.places,
    place_set_complete=True,
)
if not isinstance(selmer_result, SelmerGroup):
    raise RuntimeError("tagged complete rational fixture was not promoted to SelmerGroup")

obstruction = aim(DenseMatrix(PrimeField(2), ((1, 0), (0, 0))), (1, 1))
certificates = [
    certificate_record("galois.kummer-space-q-s2", global_space),
    certificate_record("arithmetic.selmer-group-q-s2", selmer_result),
    certificate_record("arithmetic.aim-obstruction", obstruction),
]

if snapshot_version >= (0, 3, 0):
    from arbogast.deform import ArtinRing
    from arbogast.deform.semantic import receipt_for_result

    deformation_ring = ArtinRing(
        PrimeField(3),
        (((1,),),),
        (1,),
        (1,),
        basis_names=("1",),
    )
    deformation_receipt = receipt_for_result(deformation_ring)
    deformation_record = certificate_record("deform.artin-ring-f3", deformation_ring)
    deformation_record.update(
        {
            "deformation_receipt": deformation_receipt.to_dict(),
            "deformation_receipt_checks": list(deformation_receipt.verify()),
            "deformation_receipt_id": deformation_receipt.certificate_id,
        }
    )
    certificates.append(deformation_record)

workflow = (archive_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
anchor_pattern = re.compile(
    r'- pari-version: "(?P<version>[0-9]+\.[0-9]+\.[0-9]+)"\s+'
    r"source-url: (?P<source_url>\S+)\s+"
    r"source-sha256: (?P<source_sha256>[0-9a-f]{64})"
)
anchors = [match.groupdict() for match in anchor_pattern.finditer(workflow)]
if not anchors:
    raise RuntimeError("tagged CI workflow has no pinned PARI anchors")

print(
    json.dumps(
        {
            "central_certificates": certificates,
            "pari": {
                "ci_anchors": anchors,
                "supported_range": PARI_SUPPORTED_RANGE,
            },
            "schema_catalog": schemas,
        }
    )
)
"""


def snapshot(*, version: str, source_tag: str, source_commit: str) -> bytes:
    """Derive a semantic compatibility snapshot from one exact Git archive."""

    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("semantic compatibility snapshots require CPython 3.11")
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
    prefix = f"arbogast-v{version.replace('.', '')}-semantic-"
    with tempfile.TemporaryDirectory(prefix=prefix) as temporary:
        archive_root = Path(temporary)
        with tarfile.open(fileobj=BytesIO(archive), mode="r:") as stream:
            stream.extractall(archive_root, filter="data")
        completed = subprocess.run(
            (
                sys.executable,
                "-I",
                "-c",
                _ISOLATED_SNAPSHOT,
                str(archive_root),
                version,
            ),
            cwd=archive_root,
            check=True,
            capture_output=True,
            text=True,
        )

    fixture = f"tests/fixtures/compat/v{version}/semantic-contracts.json"
    payload = json.loads(completed.stdout)
    payload.update(
        {
            "derivation": {
                "command": (
                    "uv run --offline python scripts/snapshot_semantic_contracts.py "
                    f"--version {version} --source-tag {source_tag} "
                    f"--source-commit {source_commit} --check {fixture}"
                ),
                "import_isolation": "python -I with only git-archive/src explicitly prepended",
                "python": "CPython 3.11",
                "source": f"git archive {source_commit}",
            },
            "schema_version": "arbogast.compatibility-semantic-contracts/v1",
            "source_commit": source_commit,
            "source_tag": source_tag,
            "version": version,
        }
    )
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


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
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded)
        print(f"sha256:{hashlib.sha256(encoded).hexdigest()}  {args.output}")
        return 0
    if args.check is not None:
        if args.check.read_bytes() != encoded:
            print(f"snapshot mismatch: {args.check}", file=sys.stderr)
            return 1
        print(f"sha256:{hashlib.sha256(encoded).hexdigest()}  {args.check}")
        return 0
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
