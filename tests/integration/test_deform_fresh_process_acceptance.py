from __future__ import annotations

import json
import subprocess
import sys

from arbogast.deform import (
    ArtinRing,
    ArtinRingMap,
    DeformationComplex,
    LiftDatum,
    LiftFamily,
    SmallExtension,
    lift,
)
from arbogast.linalg import DenseMatrix, PrimeField


def _residue_ring(field: PrimeField) -> ArtinRing:
    return ArtinRing(field, (((1,),),), (1,), (1,))


def _dual_numbers(field: PrimeField) -> ArtinRing:
    return ArtinRing(
        field,
        (
            ((1, 0), (0, 1)),
            ((0, 1), (0, 0)),
        ),
        (1, 0),
        (1, 0),
    )


def test_dependency_closed_lift_certificate_and_claim_graph_replay_fresh() -> None:
    field = PrimeField(3)
    residue = _residue_ring(field)
    dual = _dual_numbers(field)
    extension = SmallExtension(
        ArtinRingMap(dual, residue, ((1, 0),)),
        ((0, 1),),
    )
    complex_ = DeformationComplex(
        field,
        DenseMatrix.zeros(field, 1, 0),
        DenseMatrix.zeros(field, 1, 1),
        name="fresh-process-lift",
    )
    result = lift(LiftDatum(complex_, extension, (0,)))
    assert isinstance(result, LiftFamily)
    payload = json.dumps(
        {
            "certificate": result.certificate.to_dict(),
            "claim_graph": result.claim_graph().to_dict(),
        }
    )

    program = """
import json, sys
from arbogast.cert import VerificationCertificate, verify_certificate
from arbogast.claims import ClaimGraph

payload = json.load(sys.stdin)
certificate = VerificationCertificate.from_dict(payload["certificate"])
assert certificate.verifier == "deform.finite-exact.v1"
assert verify_certificate(certificate).valid
graph = ClaimGraph.from_dict(payload["claim_graph"])
assert graph.verify().verified
print(certificate.certificate_id)
"""
    completed = subprocess.run(
        (sys.executable, "-I", "-c", program),
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip() == result.certificate.certificate_id
