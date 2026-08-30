from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from arbogast.arithmetic import (
    ArithmeticError,
    ArithmeticReceipt,
    ArithmeticVerificationError,
    LocalPairing,
    UnsupportedArithmeticOperation,
)
from arbogast.backends.pari_certificate import create_pari_verification_certificate
from arbogast.backends.pari_results import PariOutcome
from arbogast.cert import VerificationCertificate, VerificationReport, default_verifiers
from arbogast.galois import (
    Completeness,
    FinitePlace,
    LocalH1Space,
    NumberField,
    ProofContext,
    Unsupported,
    VerificationRequirement,
    local_h1,
)


def _limits() -> dict[str, object]:
    return {
        "certification_timeout_seconds": "60",
        "cpu_limit_seconds": 60,
        "memory_limit_bytes": 1_073_741_824,
        "output_limit_bytes": 2_000_000,
        "pari_stack_bytes": 268_435_456,
        "timeout_seconds": "15",
    }


def _field_replay(field: NumberField) -> dict[str, object]:
    snapshot = field.to_dict()
    polynomial = snapshot["defining_polynomial"]
    assert isinstance(polynomial, list)
    return {
        "defining_polynomial": [[coefficient, 1] for coefficient in polynomial],
        "field_id": field.field_id,
        "identity": snapshot,
        "integral_basis": snapshot["integral_basis"],
    }


def _place_replay(place: FinitePlace) -> dict[str, object]:
    return {
        "ideal_hnf": [list(row) for row in place.ideal_hnf],
        "identity": place.to_dict(),
        "place_id": place.place_id,
        "ramification_index": place.ramification_index,
        "rational_prime": place.rational_prime,
        "residue_degree": place.residue_degree,
    }


def _element_replay(element: Any) -> dict[str, object]:
    return {
        "coefficients": element.to_dict()["coefficients"],
        "element_id": element.element_id,
        "identity": element.to_dict(),
    }


def _certificate(
    operation: str,
    field: NumberField,
    payload: dict[str, object],
    arguments: dict[str, object],
) -> VerificationCertificate:
    return create_pari_verification_certificate(
        operation,
        replay={"arguments": arguments, "field": _field_replay(field)},
        expected_payload=payload,
        backend_version="2.17.4",
        request_id="sha256:" + "1" * 64,
        deterministic_seed=1,
        proof_mode="unconditional",
        limits=_limits(),
    )


@dataclass(frozen=True, slots=True)
class _Result:
    operation: str
    payload: dict[str, object]
    certificate: VerificationCertificate
    outcome: PariOutcome = PariOutcome.SUCCESS

    def proof_context(self) -> ProofContext:
        return ProofContext(
            verification_requirements=(
                VerificationRequirement.pinned_external(
                    "arbogast.backends.pari.v1",
                    "2.17.4",
                    capabilities=(self.operation,),
                ),
            ),
            completeness=Completeness.COMPLETE,
        )


class _Backend:
    def __init__(
        self,
        field: NumberField,
        place: FinitePlace,
        local_result: _Result,
    ) -> None:
        self.field = field
        self.place = place
        self.local_result = local_result
        self.calls: list[tuple[str, str, str]] = []
        self.certificates: list[VerificationCertificate] = []

    def local_squareclasses(self, *_args: object, **_kwargs: object) -> _Result:
        return self.local_result

    def quadratic_hilbert_pairing(
        self,
        field: NumberField,
        left: Any,
        right: Any,
        place: FinitePlace,
    ) -> _Result:
        assert field == self.field and place == self.place
        self.calls.append((left.element_id, right.element_id, place.place_id))
        symbol = -1 if left.element_id == right.element_id else 1
        payload = {
            "field_id": field.field_id,
            "left_element_id": left.element_id,
            "place_id": place.place_id,
            "place_kind": "finite",
            "right_element_id": right.element_id,
            "symbol": symbol,
        }
        certificate = _certificate(
            "quadratic_hilbert_pairing",
            field,
            payload,
            {
                "left": _element_replay(left),
                "place": _place_replay(place),
                "right": _element_replay(right),
            },
        )
        self.certificates.append(certificate)
        return _Result("quadratic_hilbert_pairing", payload, certificate)


def _accept_pari_certificates(monkeypatch: pytest.MonkeyPatch) -> None:
    original = default_verifiers.verify

    def verify(certificate: object, **kwargs: object) -> VerificationReport:
        if (
            isinstance(certificate, VerificationCertificate)
            and certificate.verifier == "arbogast.backends.pari.v1"
        ):
            certificate.verify_integrity()
            return VerificationReport(
                valid=True,
                verifier=certificate.verifier,
                certificate_id=certificate.certificate_id,
            )
        return original(certificate, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(default_verifiers, "verify", verify)


def _nonrational_local_space(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[LocalH1Space, _Backend]:
    field = NumberField((5, 0, 1), generator_name="u")
    place = FinitePlace(field, 2, ((2, 1), (0, 1)), 2, 1)
    basis = (
        field.element((-1, 0)),
        field.element((-1, -1)),
        field.element((-2, -4)),
        field.element((4, -4)),
    )
    payload = {
        "complete": True,
        "dimension": 4,
        "field_id": field.field_id,
        "place_id": place.place_id,
        "ramification_index": 2,
        "rational_prime": 2,
        "representatives": [
            [[-1, 1], [0, 1]],
            [[-1, 1], [-1, 1]],
            [[-2, 1], [-4, 1]],
            [[4, 1], [-4, 1]],
        ],
        "residue_degree": 1,
        "tested_candidates": 81,
    }
    local_certificate = _certificate(
        "local_squareclasses",
        field,
        payload,
        {
            "max_candidates": 4096,
            "place": _place_replay(place),
            "search_bound": 4,
        },
    )
    backend = _Backend(
        field,
        place,
        _Result("local_squareclasses", payload, local_certificate),
    )
    _accept_pari_certificates(monkeypatch)
    space = local_h1(place, backend=backend)
    assert isinstance(space, LocalH1Space)
    assert tuple(space.basis_representatives) == basis
    return space, backend


def test_nonrational_hilbert_pairing_uses_one_pinned_pari_call_per_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space, backend = _nonrational_local_space(monkeypatch)

    pairing = LocalPairing.hilbert(space, backend=backend)

    basis_ids = tuple(item.element_id for item in space.basis_representatives)
    assert backend.calls == [
        (left, right, space.place.place_id) for left in basis_ids for right in basis_ids
    ]
    assert pairing.matrix.rows == tuple(
        tuple(int(row == column) for column in range(4)) for row in range(4)
    )
    assert pairing.completeness is Completeness.COMPLETE
    assert pairing.is_perfect
    assert pairing.pairing_witness is not None
    assert tuple(pairing.pairing_witness["certificate_ids"]) == tuple(
        item.certificate_id for item in backend.certificates
    )
    assert pairing.verify().valid
    pairing.require_perfect()
    assert pairing.claim().status.value == "certified"
    assert pairing.claim().verify().verified

    rebound_payload = pairing.receipt.payload.to_dict()
    witness = rebound_payload["pairing_witness"]
    assert isinstance(witness, dict)
    certificate_ids = witness["certificate_ids"]
    assert isinstance(certificate_ids, list)
    certificate_ids.reverse()
    rebound = ArithmeticReceipt.create(
        "local-pairing",
        rebound_payload,
        context=pairing.proof_context,
        evidence=pairing.receipt.evidence,
    )
    with pytest.raises(ArithmeticVerificationError, match="rebound"):
        rebound.verify()


def test_hilbert_prefers_portable_rational_path_and_defers_p_greater_than_two() -> None:
    field = NumberField.rationals()
    place = FinitePlace(field, 2, ((2,),), 1, 1)
    space = local_h1(place)
    assert not isinstance(space, Unsupported)
    pairing = LocalPairing.hilbert(space, backend=object())
    assert pairing.verify().valid
    assert pairing.pairing_witness is not None
    assert pairing.pairing_witness["kind"] == "rational-hilbert-v1"

    unsupported = SimpleNamespace(
        prime=3,
        dimension=1,
        basis_representatives=(field.element(-1),),
        place=place,
    )
    with pytest.raises(UnsupportedArithmeticOperation, match="only for p=2"):
        LocalPairing.hilbert(unsupported)


def test_nonrational_hilbert_rejects_rebound_backend_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space, backend = _nonrational_local_space(monkeypatch)
    original = backend.quadratic_hilbert_pairing

    def rebound(*args: Any, **kwargs: Any) -> _Result:
        result = original(*args, **kwargs)
        result.payload["place_id"] = "sha256:" + "0" * 64
        return result

    monkeypatch.setattr(backend, "quadratic_hilbert_pairing", rebound)
    with pytest.raises(ArithmeticError, match="rebound"):
        LocalPairing.hilbert(space, backend=backend)
