from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import pytest

from arbogast.cert import CertificateError, VerificationCertificate, verify_certificate
from arbogast.claims import EpistemicStatus
from arbogast.hurwitz import BraidAction, BraidWord
from arbogast.numeric import (
    BraidContinuationResult,
    BraidContinuationWitness,
    BranchCycleTuple,
    NielsenVertex,
    NumericalCover,
    NumericReceipt,
    NumericUnknown,
    NumericVerificationError,
    QuadraticB2Homotopy,
    braid_continue,
    branch_cycles,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_NAMESPACE = runpy.run_path(
    str(PROJECT_ROOT / "examples" / "numeric" / "two_sheet_cover" / "fixture.py")
)
normalized_b2_fixture = cast(
    Callable[[], tuple[NielsenVertex, BraidAction]],
    _FIXTURE_NAMESPACE["normalized_b2_fixture"],
)


@lru_cache(maxsize=1)
def _forward_result() -> BraidContinuationResult:
    vertex, action = normalized_b2_fixture()
    word = BraidWord.generator(0)
    homotopy = QuadraticB2Homotopy(vertex, word, vertex, action)
    result = braid_continue(vertex, word, witness=homotopy)
    assert isinstance(result, BraidContinuationResult)
    return result


@lru_cache(maxsize=1)
def _forward_certificate() -> VerificationCertificate:
    return _forward_result().certificate


@lru_cache(maxsize=1)
def _inverse_result() -> BraidContinuationResult:
    forward = _forward_result()
    _, action = normalized_b2_fixture()
    word = BraidWord.generator(0, inverse=True)
    result = braid_continue(
        forward,
        word,
        witness=QuadraticB2Homotopy(forward, word, forward, action),
    )
    assert isinstance(result, BraidContinuationResult)
    return result


@lru_cache(maxsize=1)
def _inverse_certificate() -> VerificationCertificate:
    return _inverse_result().certificate


@lru_cache(maxsize=1)
def _forward_receipt() -> NumericReceipt:
    witness = _forward_certificate().witness.to_dict()
    raw_receipt = witness.get("numeric_receipt")
    if not isinstance(raw_receipt, dict):
        raise AssertionError("B2 certificate omitted its embedded numeric receipt")
    return NumericReceipt.from_dict(raw_receipt)


def test_normalized_b2_generator_and_inverse_are_exact_composable_covers() -> None:
    vertex, action = normalized_b2_fixture()
    forward_word = BraidWord.generator(0)
    forward = _forward_result()
    assert isinstance(forward, NumericalCover)
    assert forward.verify()
    assert forward.target == vertex
    assert forward.homotopy.sheet_permutation == (1, 0)
    cycles = branch_cycles(forward)
    assert isinstance(cycles, BranchCycleTuple)
    assert cycles.verify()

    inverse = _inverse_result()
    assert isinstance(inverse, NumericalCover)
    assert inverse.verify()
    assert inverse.homotopy.orientation == -1

    missing = braid_continue(vertex, forward_word)
    assert isinstance(missing, NumericUnknown)
    with pytest.raises(NumericVerificationError, match="portable node bound"):
        BraidContinuationWitness(
            vertex,
            forward_word,
            vertex,
            action,
            vertex.trackings[0].continuations,
            (1, 0),
        )


def test_b2_result_receipt_claim_and_graph_replay_fresh(tmp_path: Path) -> None:
    result = _forward_result()
    receipt = _forward_receipt()
    replayed = NumericReceipt.from_dict(receipt.to_dict())
    assert replayed.verify()

    certificate = _forward_certificate()
    inverse_certificate = _inverse_certificate()
    replayed_certificate = VerificationCertificate.from_dict(certificate.to_dict())
    assert verify_certificate(replayed_certificate).valid
    replayed_inverse = VerificationCertificate.from_dict(inverse_certificate.to_dict())
    assert verify_certificate(replayed_inverse).valid
    inverse_witness = inverse_certificate.witness.to_dict()
    inverse_receipt = inverse_witness.get("numeric_receipt")
    assert isinstance(inverse_receipt, dict)
    assert NumericReceipt.from_dict(inverse_receipt).verify()
    claim = result.claim()
    assert claim.status is EpistemicStatus.EXACT
    graph = result.claim_graph()
    assert len(graph.claims) == 1
    assert graph.claims[0].claim_id == claim.claim_id

    certificate_path = tmp_path / "b2-certificate.json"
    certificate_path.write_text(
        json.dumps(
            {
                "forward": certificate.to_dict(),
                "inverse": inverse_certificate.to_dict(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    code = """
import json
import sys
from arbogast.cert import VerificationCertificate, verify_certificate

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
for name in ("forward", "inverse"):
    certificate = VerificationCertificate.from_dict(payload[name])
    report = verify_certificate(certificate)
    assert report.valid
    print(certificate.certificate_id)
"""
    completed = subprocess.run(
        (sys.executable, "-I", "-c", code, str(certificate_path)),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.splitlines() == [
        certificate.certificate_id,
        inverse_certificate.certificate_id,
    ]


def test_b2_receipt_rejects_every_geometric_binding_tamper() -> None:
    receipt = _forward_receipt()
    original = cast(dict[str, Any], receipt.payload.to_dict())

    def orientation(payload: dict[str, Any]) -> None:
        payload["homotopy"]["orientation"] = -1

    def word(payload: dict[str, Any]) -> None:
        payload["homotopy"]["word"][0]["inverse"] = True

    def q_midpoint(payload: dict[str, Any]) -> None:
        payload["homotopy"]["q"]["terms"][0]["coefficient"]["real"]["mantissa"] = 3

    def coefficient_endpoint(payload: dict[str, Any]) -> None:
        payload["homotopy"]["coefficient_homotopy"]["terms"][0]["coefficient"]["real"][
            "mantissa"
        ] = 3

    def branch_definition(payload: dict[str, Any]) -> None:
        payload["homotopy"]["branch_paths"][0]["terms"][0]["coefficient"]["real"]["mantissa"] = 3

    def collision_component(payload: dict[str, Any]) -> None:
        payload["homotopy"]["collision_sos"][0]["terms"][0]["coefficient"]["real"]["mantissa"] = 3

    def sheet_substitution(payload: dict[str, Any]) -> None:
        payload["homotopy"]["sheet_paths"][0]["terms"][0]["coefficient"]["imag"]["mantissa"] = 3

    def target(payload: dict[str, Any]) -> None:
        payload["homotopy"]["target"]["vertex_index"] = 1

    for tamper in (
        orientation,
        word,
        q_midpoint,
        coefficient_endpoint,
        branch_definition,
        collision_component,
        sheet_substitution,
        target,
    ):
        payload = deepcopy(original)
        tamper(payload)
        altered = NumericReceipt.create(
            "braid-continuation-result",
            payload,
            dependencies=receipt.dependencies,
        )
        with pytest.raises((CertificateError, NumericVerificationError, ValueError)):
            altered.verify()

    floating = deepcopy(original)
    floating["homotopy"]["orientation"] = 1.0
    with pytest.raises(CertificateError, match="noncanonical"):
        NumericReceipt.create(
            "braid-continuation-result",
            floating,
            dependencies=receipt.dependencies,
        )
