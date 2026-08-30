from __future__ import annotations

import pytest

from arbogast.arithmetic import (
    ArithmeticReceipt,
    ArithmeticVerificationError,
    CartierDual,
    LocalCondition,
    LocalPairing,
    SelmerProblem,
    UnsupportedArithmeticOperation,
    dual_selmer,
)
from arbogast.galois import (
    ArithmeticCertificateError,
    Completeness,
    FiniteGaloisQuotient,
    InfinitePlace,
    LocalH1Space,
    LocalizationMap,
    NumberField,
    Unsupported,
    galois_module,
    kummer_space,
    local_h1,
    localize,
)
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import CyclicGroup


def _mu2_cartier_dual() -> CartierDual:
    group = CyclicGroup(1)
    quotient = FiniteGaloisQuotient(
        NumberField.rationals(),
        group,
        label="complex-place-mu2-coefficient-quotient",
    )
    field = PrimeField(2)
    module = galois_module(
        quotient,
        field,
        {group.identity: DenseMatrix.identity(field, 1)},
        name="mu2",
    )
    return CartierDual(module)


def test_complex_mu2_local_arithmetic_is_portable_zero_and_dual_ready() -> None:
    field = NumberField((5, 0, 1), generator_name="u")
    place = InfinitePlace(field, "complex", (-1, 1, 2, 3))

    local_space = local_h1(place)
    assert isinstance(local_space, LocalH1Space)
    assert local_space.dimension == 0
    assert local_space.completeness is Completeness.COMPLETE
    assert local_space.verify()
    assert local_space.claim().status.value == "exact"
    assert local_space.claim().verify().verified
    assert local_space.claim_graph().verify().verified

    global_space = kummer_space(
        field,
        (place,),
        generators=(field.element(-1),),
    )
    assert not isinstance(global_space, Unsupported)
    localization = localize(global_space, local_space)
    assert isinstance(localization, LocalizationMap)
    assert localization.matrix.shape == (0, 1)
    assert localization.matrix.rows == ()
    assert localization.completeness is Completeness.COMPLETE
    assert localization.localization_witness["method"] == ("portable-complex-zero-localization-v1")
    assert localization.verify()
    assert localization.claim().status.value == "exact"
    assert localization.claim().verify().verified
    assert localization.claim_graph().verify().verified

    pairing = LocalPairing.hilbert(local_space)
    assert pairing.matrix.shape == (0, 0)
    assert pairing.matrix.rows == ()
    assert pairing.completeness is Completeness.COMPLETE
    assert pairing.is_perfect
    assert pairing.pairing_witness is not None
    assert pairing.pairing_witness.to_dict() == {"kind": "complex-zero-hilbert-v1"}
    assert pairing.verify().valid
    pairing.require_perfect()
    assert pairing.claim().status.value == "exact"
    assert pairing.claim().verify().verified
    assert pairing.claim_graph().verify().verified

    condition = LocalCondition(local_space, ())
    orthogonal = pairing.right_orthogonal(condition)
    assert orthogonal.dimension == 0
    assert orthogonal.completeness is Completeness.COMPLETE
    assert orthogonal.verify().valid

    primal = SelmerProblem(
        global_space,
        (localization,),
        (condition,),
    )
    dual = dual_selmer(
        primal,
        pairings=(pairing,),
        cartier_dual=_mu2_cartier_dual(),
    )
    assert dual.verify().valid
    assert dual.claim().verify().verified
    assert dual.claim_graph().verify().verified


def test_complex_zero_witnesses_reject_tampering() -> None:
    field = NumberField((5, 0, 1), generator_name="u")
    place = InfinitePlace(field, "complex", (-1, 1, 2, 3))
    local_space = local_h1(place)
    assert isinstance(local_space, LocalH1Space)
    global_space = kummer_space(
        field,
        (place,),
        generators=(field.element(-1),),
    )
    assert not isinstance(global_space, Unsupported)
    localization = localize(global_space, local_space)
    assert isinstance(localization, LocalizationMap)
    pairing = LocalPairing.hilbert(local_space)

    localization_payload = localization.receipt.to_dict()
    witness = localization_payload["localization_witness"]
    assert isinstance(witness, dict)
    witness["domain_receipt"] = "sha256:" + "0" * 64
    with pytest.raises(ArithmeticCertificateError, match="different domain"):
        type(localization.receipt).from_dict(localization_payload).verify()

    pairing_payload = pairing.receipt.payload.to_dict()
    pairing_witness = pairing_payload["pairing_witness"]
    assert isinstance(pairing_witness, dict)
    pairing_witness["dimension"] = 1
    tampered = ArithmeticReceipt.create(
        "local-pairing",
        pairing_payload,
        context=pairing.proof_context,
        evidence=pairing.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="unexpected arithmetic payload"):
        tampered.verify()


def test_p_greater_than_two_stays_deferred_and_real_signs_replay_exactly() -> None:
    imaginary = NumberField((5, 0, 1), generator_name="u")
    complex_place = InfinitePlace(imaginary, "complex", (-1, 1, 2, 3))
    assert isinstance(local_h1(complex_place, prime=3), Unsupported)

    supplied_p3 = local_h1(complex_place, prime=3, basis=())
    assert isinstance(supplied_p3, LocalH1Space)
    with pytest.raises(UnsupportedArithmeticOperation, match="p=2"):
        LocalPairing.hilbert(supplied_p3)

    real_field = NumberField((-1, -1, 1), generator_name="t")
    real_place = InfinitePlace(real_field, "real", (-1, 0), embedding_index=0)
    real_global = kummer_space(
        real_field,
        (real_place,),
        generators=(real_field.generator, -real_field.generator),
    )
    assert not isinstance(real_global, Unsupported)
    real_local = local_h1(real_place)
    assert isinstance(real_local, LocalH1Space)
    real_localization = localize(real_global, real_local)
    assert isinstance(real_localization, LocalizationMap)
    assert real_localization.matrix.rows == ((1, 0),)
    assert real_localization.completeness is Completeness.COMPLETE
    assert real_localization.localization_witness["method"] == (
        "portable-real-sign-localization-v1"
    )
    sign_witnesses = real_localization.localization_witness["sign_witnesses"]
    assert tuple(witness["sign"] for witness in sign_witnesses) == (-1, 1)
    assert real_localization.verify()
    assert real_localization.claim().verify().verified
    assert real_localization.claim_graph().verify().verified

    tampered_payload = real_localization.receipt.to_dict()
    tampered_witness = tampered_payload["localization_witness"]
    assert isinstance(tampered_witness, dict)
    tampered_signs = tampered_witness["sign_witnesses"]
    assert isinstance(tampered_signs, list)
    assert isinstance(tampered_signs[0], dict)
    tampered_signs[0]["sign"] = 1
    with pytest.raises(ArithmeticCertificateError, match="advertised generator sign"):
        type(real_localization.receipt).from_dict(tampered_payload).verify()
