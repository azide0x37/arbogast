from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

import pytest

from arbogast.cert import CertificateError, ContentAddressError
from arbogast.deform import (
    PORTABLE_VERIFIER,
    DeformationAction,
    DeformationComplex,
    DeformationError,
    DeformationReceipt,
    DeformationVerificationError,
    Framing,
    UnsupportedDeformation,
    deformation_problem,
    equivariant,
    invariant_deformations,
    verify_deformation_receipt,
)
from arbogast.deform.semantic import receipt_for_result
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import Representation, cyclic_group


def _complex() -> DeformationComplex:
    field = PrimeField(3)
    return DeformationComplex(
        field,
        DenseMatrix(field, ((1, 0), (0, 0))),
        DenseMatrix(field, ((0, 1),)),
        name="receipt-replay",
    )


def _complex_payload() -> dict[str, object]:
    payload = _complex().to_canonical_data()
    assert isinstance(payload, dict)
    return dict(payload)


def test_complex_receipt_round_trips_and_replays_without_runtime_state() -> None:
    receipt = DeformationReceipt.create("complex", _complex_payload())

    checks = receipt.verify()
    decoded = DeformationReceipt.from_dict(receipt.to_dict())

    assert decoded == receipt
    assert decoded.certificate_id == receipt.certificate_id
    assert verify_deformation_receipt(decoded) == checks
    assert PORTABLE_VERIFIER == "deform.finite-exact.v1"
    assert receipt.verifier_trust == "portable-python"
    assert receipt.assumptions == ()
    assert receipt.completeness == "complete"
    assert "zero-differential-composite" in checks
    assert "dependency-closed-portable-evidence" in checks


def test_receipt_transport_tampering_breaks_its_content_identity() -> None:
    receipt = DeformationReceipt.create("complex", _complex_payload())
    tampered = deepcopy(receipt.to_dict())
    payload = tampered["payload"]
    assert isinstance(payload, dict)
    payload["name"] = "altered"

    with pytest.raises(ContentAddressError, match="content address mismatch"):
        DeformationReceipt.from_dict(tampered)


def test_readdressed_mathematical_tampering_fails_independent_replay() -> None:
    payload = deepcopy(_complex_payload())
    d1 = payload["d1"]
    assert isinstance(d1, dict)
    d1["rows"] = [[1, 0]]
    forged = DeformationReceipt.create("complex", payload)

    with pytest.raises(DeformationVerificationError, match="compose to zero"):
        forged.verify()


@pytest.mark.parametrize("name", (" receipt-replay ", "re\u0301play"))
def test_readdressed_runtime_name_must_be_stripped_canonical_nfc(name: str) -> None:
    payload = _complex_payload()
    payload["name"] = name
    forged = DeformationReceipt.create("complex", payload)

    with pytest.raises(DeformationVerificationError, match="canonical NFC"):
        forged.verify()


def test_problem_receipt_binds_the_full_effective_complex_snapshot() -> None:
    receipt = receipt_for_result(deformation_problem(_complex()))
    payload = deepcopy(receipt.payload.to_dict())
    effective = payload["effective_complex"]
    assert isinstance(effective, dict)
    effective["name"] = "forged effective name"
    forged = DeformationReceipt.create(
        "problem",
        payload,
        dependencies=receipt.dependencies,
    )

    with pytest.raises(DeformationVerificationError, match="differs from its presentation"):
        forged.verify()


def _invariant_receipt() -> DeformationReceipt:
    field = PrimeField(3)
    complex_ = DeformationComplex(
        field,
        DenseMatrix.zeros(field, 1, 1),
        DenseMatrix.zeros(field, 1, 1),
        name="invariant receipt source",
    )
    group = cyclic_group(2)
    representation = Representation.from_generators(
        group,
        field,
        {group.generator: DenseMatrix.identity(field, 1)},
    )
    action = DeformationAction(
        complex_,
        representation,
        representation,
        representation,
    )
    return receipt_for_result(invariant_deformations(equivariant(complex_, action)))


@pytest.mark.parametrize("tamper", ("presentation-name", "framing"))
def test_invariant_receipt_binds_the_full_canonical_problem(tamper: str) -> None:
    receipt = _invariant_receipt()
    payload = deepcopy(receipt.payload.to_dict())
    problem = payload["problem"]
    assert isinstance(problem, dict)
    if tamper == "presentation-name":
        presentation = problem["presentation"]
        assert isinstance(presentation, dict)
        presentation["name"] = "forged invariant name"
    else:
        problem["framing"] = Framing(
            DenseMatrix.zeros(PrimeField(3), 0, 1),
            "forged invariant framing",
        ).to_canonical_data()
    forged = DeformationReceipt.create(
        "invariant-complex",
        payload,
        dependencies=receipt.dependencies,
    )

    with pytest.raises(DeformationVerificationError, match="exact canonical unframed"):
        forged.verify()


@pytest.mark.parametrize(
    "leaked_key",
    ("pari_handle", "session_index", "printed_padic"),
)
def test_backend_local_handles_never_cross_the_portable_receipt_boundary(
    leaked_key: str,
) -> None:
    payload = deepcopy(_complex_payload())
    payload["discovery"] = {leaked_key: "backend-local"}
    receipt = DeformationReceipt.create("complex", payload)

    with pytest.raises(DeformationVerificationError, match="backend-local"):
        receipt.verify()


def test_candidate_and_assumption_axes_are_independent_of_portable_trust() -> None:
    receipt = DeformationReceipt.create(
        "complex",
        _complex_payload(),
        assumptions=("imported comparison theorem",),
        completeness="candidate",
    )

    assert receipt.verify()
    assert receipt.assumptions == ("imported comparison theorem",)
    assert receipt.completeness == "candidate"
    assert receipt.verifier_trust == "portable-python"


@pytest.mark.parametrize(
    "requested",
    (
        {"ratio": Fraction(1, 2)},
        {"label": "e\u0301"},
        {"e\u0301": 1},
    ),
)
def test_unsupported_requested_data_must_already_be_strict_core_canonical(
    requested: dict[str, object],
) -> None:
    with pytest.raises(DeformationError, match="strict core canonical data"):
        UnsupportedDeformation("operation", "reason", requested=requested)

    payload = {
        "operation": "operation",
        "reason": "reason",
        "requested": requested,
        "supported": [],
        "type": "arbogast.deform.unsupported",
    }
    with pytest.raises(CertificateError, match="strict core canonical data"):
        DeformationReceipt.create("unsupported", payload)


def test_assumptions_require_nfc_without_stripping_meaningful_spaces() -> None:
    with pytest.raises(CertificateError, match="canonical NFC"):
        DeformationReceipt.create(
            "complex",
            _complex_payload(),
            assumptions=("e\u0301",),
        )

    receipt = DeformationReceipt.create(
        "complex",
        _complex_payload(),
        assumptions=(" hypothesis ",),
    )
    assert receipt.assumptions == (" hypothesis ",)
    assert receipt.verify()

    transport = receipt.to_dict()
    transport["assumptions"] = ["e\u0301"]
    with pytest.raises(CertificateError, match="canonical NFC"):
        DeformationReceipt.from_dict(transport)
