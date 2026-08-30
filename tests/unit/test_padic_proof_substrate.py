from __future__ import annotations

from copy import deepcopy

import pytest

import arbogast.padic._schema as padic_schema
import arbogast.padic.certificate as padic_certificate
import arbogast.padic.semantic as padic_semantic
from arbogast.cert import (
    CertificateVerificationError,
    ClaimBinding,
    ContentAddressError,
    VerificationCertificate,
    canonical_bytes,
    verify_certificate,
)
from arbogast.claims import EpistemicStatus
from arbogast.galois.proof import Completeness, VerificationRequirement
from arbogast.padic.certificate import (
    FINITE_EXACT_VERIFIER,
    KIND_VERIFIERS,
    THREE_POINT_EXACT_VERIFIER,
    PAdicReceipt,
    candidate_proof_context,
)
from arbogast.padic.errors import (
    PAdicCertificateError,
    PAdicResourceError,
    PAdicValidationError,
    PAdicVerificationError,
)
from arbogast.padic.fields import PAdicAutomorphism, PAdicField, PAdicPrecisionRing
from arbogast.padic.modules import PAdicModule, PAdicSubmodule
from arbogast.padic.results import (
    Certified,
    Partial,
    ProofObligation,
    Unknown,
    Unsupported,
    certified_result,
    partial_result,
    unknown_result,
    unsupported_result,
)


def _field_result() -> Certified[PAdicField]:
    return certified_result(PAdicField(2), "field")


def _partial_result() -> Partial:
    fragment = _field_result()
    obligation = ProofObligation(
        "supply a complete stabilization witness",
        "stabilization-witness",
        "stable-reduction",
        input_ids=(fragment.value.content_id,),
    )
    result = partial_result(
        "padic.stable_reduction",
        "stabilization remains open",
        (fragment,),
        (obligation,),
        family="three-point",
    )
    assert isinstance(result, Partial)
    return result


def test_exactly_two_verifier_families_and_all_four_factory_variants_replay() -> None:
    assert set(KIND_VERIFIERS.values()) == {
        FINITE_EXACT_VERIFIER,
        THREE_POINT_EXACT_VERIFIER,
    }

    certified = _field_result()
    partial = _partial_result()
    unknown = unknown_result(
        "padic.slopes",
        "ambiguous-newton-polygon",
        "finite precision does not separate every vertex",
        requested={"precision": 8},
        family="finite",
    )
    unsupported = unsupported_result(
        "padic.stable_reduction",
        "not-three-point",
        "the bounded API accepts normalized three-point covers only",
        requested={"branch_count": 4},
        supported=("normalized-three-point-cover",),
        family="three-point",
    )

    for result in (certified, partial, unknown, unsupported):
        assert result.verify()
        assert verify_certificate(result.certificate).valid
        assert result.claim().verify().verified
        assert result.claim_graph().verify().verified

    assert certified.proof_context.completeness is Completeness.COMPLETE
    assert certified.claim().status is EpistemicStatus.EXACT
    assert partial.claim().status is EpistemicStatus.UNKNOWN
    assert unknown.claim().status is EpistemicStatus.UNKNOWN
    assert unsupported.claim().status is EpistemicStatus.EXACT
    assert unsupported.claim().metadata["mathematical_conclusion"] is False


def test_payload_decoder_failures_are_normalized_but_resource_errors_survive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _field_result().receipt

    def malformed_payload(*_args: object) -> object:
        raise PAdicValidationError("tampered field payload")

    monkeypatch.setitem(
        padic_certificate._PAYLOAD_VERIFIERS,
        "field",
        malformed_payload,
    )
    with pytest.raises(PAdicVerificationError, match="malformed canonical data") as exc:
        receipt.verify()
    assert isinstance(exc.value.__cause__, PAdicValidationError)

    def exhausted_payload(*_args: object) -> object:
        raise PAdicResourceError("deliberate replay budget exhaustion")

    monkeypatch.setitem(
        padic_certificate._PAYLOAD_VERIFIERS,
        "field",
        exhausted_payload,
    )
    with pytest.raises(PAdicResourceError, match="deliberate replay budget exhaustion"):
        receipt.verify()


def test_assumptions_and_missing_external_requirements_do_not_promote_results() -> None:
    conditional = certified_result(PAdicField(2), "field", assumptions=("GRH",))
    assert conditional.verify()
    assert conditional.claim().status is EpistemicStatus.CONDITIONAL
    assert conditional.proof_context.completeness is Completeness.COMPLETE

    external = VerificationRequirement.pinned_external(
        "example.external.verifier",
        "1.0",
        capabilities=("local-field",),
    )
    missing = certified_result(
        PAdicField(2),
        "field",
        verification_requirements=(external,),
    )
    with pytest.raises(PAdicVerificationError, match="unsatisfied typed"):
        missing.verify()


def test_partial_without_a_certified_fragment_becomes_unknown() -> None:
    obligation = ProofObligation(
        "supply a local field witness",
        "field-witness",
        "field",
    )
    result = partial_result(
        "padic.local_field",
        "no independently certified fragment exists",
        (),
        (obligation,),
        family="finite",
    )

    assert isinstance(result, Unknown)
    assert result.reason_code == "no-certified-fragments"
    assert result.claim().status is EpistemicStatus.UNKNOWN


def test_result_and_receipt_transport_round_trip_strictly() -> None:
    certified = _field_result()
    decoded_certified = Certified.from_dict(
        certified.to_schema_document(),
        value_decoder=PAdicField.from_dict,
    )
    assert decoded_certified == certified

    partial = _partial_result()
    decoded_partial = Partial.from_dict(
        partial.to_schema_document(),
        fragment_decoder=lambda value: Certified.from_dict(
            value,
            value_decoder=PAdicField.from_dict,
        ),
    )
    assert decoded_partial == partial

    unknown = unknown_result(
        "padic.test",
        "budget-exhausted",
        "the declared exact-work budget was exhausted",
        requested={"work_limit": 10},
        family="finite",
    )
    unsupported = unsupported_result(
        "padic.test",
        "unsupported-input",
        "this input lies outside the bounded slice",
        requested={"arity": 4},
        supported=("arity-three",),
        family="three-point",
    )
    assert Unknown.from_dict(unknown.to_schema_document()) == unknown
    assert Unsupported.from_dict(unsupported.to_schema_document()) == unsupported
    assert PAdicReceipt.from_dict(partial.receipt.to_dict()) == partial.receipt

    tuple_alias = deepcopy(partial.receipt.to_dict())
    tuple_alias["evidence"] = tuple(tuple_alias["evidence"])
    with pytest.raises(PAdicCertificateError, match="strict JSON array"):
        PAdicReceipt.from_dict(tuple_alias)

    missing_id = deepcopy(partial.receipt.to_dict())
    del missing_id["certificate_id"]
    with pytest.raises(PAdicCertificateError, match="fields do not match"):
        PAdicReceipt.from_dict(missing_id)


def test_proof_obligation_identity_and_transport_tampering_fail_closed() -> None:
    obligation = ProofObligation(
        "supply an exact projector",
        "slope-projector",
        "ordinary-part",
        input_ids=("sha256:" + "0" * 64,),
    )
    assert ProofObligation.from_dict(obligation.to_schema_document()) == obligation

    tampered = deepcopy(obligation.to_schema_document())
    tampered["obligation_id"] = "sha256:" + "1" * 64
    with pytest.raises(PAdicVerificationError, match="strict canonical transport"):
        ProofObligation.from_dict(tampered)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("certificate_id", "sha256:" + "0" * 64),
        ("claim_id", "padic.forged.fragment"),
        ("result_id", "sha256:" + "1" * 64),
        ("result_schema", "forged/v1"),
    ),
)
def test_partial_fragment_descriptor_fields_are_derived_from_proving_certificate(
    field: str,
    replacement: str,
) -> None:
    partial = _partial_result()
    payload = deepcopy(partial.receipt.payload.to_dict())
    fragments = payload["fragments"]
    assert isinstance(fragments, list)
    fragment = fragments[0]
    assert isinstance(fragment, dict)
    fragment[field] = replacement
    forged = PAdicReceipt.create(
        partial.receipt.kind,
        "partial",
        payload,
        proof_context=partial.receipt.proof_context,
        evidence=partial.receipt.evidence,
    )

    with pytest.raises(PAdicVerificationError):
        forged.verify()


def test_partial_rejects_foreign_but_valid_evidence() -> None:
    partial = _partial_result()
    foreign = unsupported_result(
        "padic.test",
        "unsupported-input",
        "foreign but valid software-boundary evidence",
        requested={},
        family="three-point",
    ).certificate
    forged = PAdicReceipt.create(
        partial.receipt.kind,
        "partial",
        partial.receipt.payload.to_dict(),
        proof_context=partial.receipt.proof_context,
        evidence=(*partial.receipt.evidence, foreign),
    )

    with pytest.raises(PAdicVerificationError, match="foreign="):
        forged.verify()


def test_readdressed_central_claim_binding_tamper_is_rejected() -> None:
    certificate = _partial_result().certificate
    fragment = _partial_result().receipt.evidence[0]
    assert fragment.claim_id is not None
    assert fragment.statement_hash is not None
    assert fragment.claim_boundary_hash is not None
    forged_binding = ClaimBinding(
        fragment.claim_id,
        fragment.statement_hash,
        fragment.claim_boundary_hash,
    )
    forged = VerificationCertificate.create(
        subject=certificate.subject,
        verifier=certificate.verifier,
        claim_id=certificate.claim_id,
        statement_hash=certificate.statement_hash,
        claim_boundary_hash=certificate.claim_boundary_hash,
        claim_dependencies=(forged_binding,),
        witness=certificate.witness.to_dict(),
        checks=certificate.checks,
        dependencies=certificate.dependencies,
        guarantees=certificate.guarantees,
    )

    with pytest.raises(CertificateVerificationError, match="claim dependency bindings"):
        verify_certificate(forged)


def test_nested_semantic_prerequisites_form_complete_claim_graph_chains() -> None:
    field = PAdicField(2)
    ring = PAdicPrecisionRing(field, 2)
    automorphism = PAdicAutomorphism.identity(ring)
    module = PAdicModule(ring, 1)
    submodule = PAdicSubmodule.whole(module)

    for result in (field, ring, automorphism, module, submodule):
        claim = result.claim()
        assert claim.dependency_ids == ()
        assert claim.verify().verified
        graph = result.claim_graph()
        assert len(graph) == 1
        assert graph.verify().verified


def test_semantic_claim_cycle_guard_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRef:
        def __init__(self, certificate_id: str) -> None:
            self.certificate_id = certificate_id

    class FakeCertificate:
        def __init__(self, certificate_id: str) -> None:
            self.certificate_id = certificate_id
            self.dependencies: tuple[FakeRef, ...] = ()

    class FakeReceipt:
        def __init__(self, evidence: tuple[FakeCertificate, ...]) -> None:
            self.evidence = evidence

    first = FakeCertificate("sha256:" + "a" * 64)
    second = FakeCertificate("sha256:" + "b" * 64)
    first.dependencies = (FakeRef(second.certificate_id),)
    second.dependencies = (FakeRef(first.certificate_id),)
    nested = {
        first.certificate_id: FakeReceipt((second,)),
        second.certificate_id: FakeReceipt((first,)),
    }
    monkeypatch.setattr(
        padic_semantic,
        "_embedded_receipt",
        lambda candidate: nested[candidate.certificate_id],
    )

    with pytest.raises(PAdicCertificateError, match="cycle"):
        padic_semantic._supporting_certificate_closure(FakeReceipt((first,)))


def test_closure_completeness_backend_and_resource_tampering_fail_closed() -> None:
    with pytest.raises(PAdicCertificateError, match="incompatible completeness"):
        PAdicReceipt.create(
            "finite-unknown",
            "unknown",
            {
                "operation": "padic.test",
                "reason": "unknown",
                "reason_code": "unknown",
                "requested": {},
            },
            proof_context=candidate_proof_context("finite-unknown").__class__(
                verification_requirements=(
                    *candidate_proof_context("finite-unknown").verification_requirements,
                ),
                completeness=Completeness.COMPLETE,
            ),
        )

    with pytest.raises(PAdicValidationError, match="backend-local"):
        unknown_result(
            "padic.test",
            "budget-exhausted",
            "unknown",
            requested={"session_handle": 7},
            family="finite",
        )


def test_runtime_and_receipt_share_the_aggregate_byte_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = unknown_result(
        "padic.test",
        "budget-exhausted",
        "unknown",
        requested={"text": "x" * 100},
        family="finite",
    )
    exact_size = len(canonical_bytes(result.to_schema_document()))
    monkeypatch.setattr(padic_schema, "MAX_CANONICAL_BYTES", exact_size)
    assert result.verify()

    monkeypatch.setattr(padic_schema, "MAX_CANONICAL_BYTES", exact_size - 1)
    with pytest.raises(PAdicResourceError, match="byte bound"):
        result.verify()
    with pytest.raises(PAdicResourceError, match="byte bound"):
        _ = result.certificate

    with pytest.raises(PAdicResourceError, match="oversized integer"):
        unknown_result(
            "padic.test",
            "budget-exhausted",
            "unknown",
            requested={"work": 1 << 4096},
            family="finite",
        )


def test_receipt_content_identity_binds_every_axis() -> None:
    receipt = _field_result().receipt
    tampered = deepcopy(receipt.to_dict())
    tampered["closure"] = "unknown"

    with pytest.raises((ContentAddressError, PAdicCertificateError)):
        PAdicReceipt.from_dict(tampered)

    assumption_tamper = deepcopy(receipt.to_dict())
    proof_context = assumption_tamper["proof_context"]
    assert isinstance(proof_context, dict)
    proof_context["assumptions"] = [" GRH "]
    with pytest.raises(ValueError, match="trimmed"):
        PAdicReceipt.from_dict(assumption_tamper)
