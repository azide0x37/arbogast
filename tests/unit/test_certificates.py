from __future__ import annotations

import json
import unicodedata

import pytest

from arbogast.cert import (
    CanonicalizationError,
    CertificateError,
    CertificateLayer,
    CertificateRef,
    ClaimBinding,
    DiscoveryReceipt,
    FrozenMap,
    TheoremCertificate,
    UnknownVerifierError,
    VerificationCertificate,
    VerifierRegistry,
    canonical_bytes,
    canonical_json,
    certificate_from_dict,
    certificate_from_json,
    content_address,
)
from arbogast.core import canonical_bytes as core_canonical_bytes


def test_common_canonical_values_match_core_and_normalize_unicode() -> None:
    decomposed = "e\N{COMBINING ACUTE ACCENT}"
    composed = unicodedata.normalize("NFC", decomposed)
    value = {decomposed: [composed, 7, None, True]}
    assert canonical_bytes(value) == core_canonical_bytes(value)
    assert content_address(value) == content_address({composed: [composed, 7, None, True]})

    with pytest.raises(CanonicalizationError, match="collide"):
        canonical_bytes({decomposed: 1, composed: 2})
    with pytest.raises(CanonicalizationError, match="floating-point"):
        canonical_bytes({"x": 0.5})
    with pytest.raises(CanonicalizationError, match="collide"):
        FrozenMap((("same", 1), ("same", 2)))


def test_certificate_layers_cannot_be_confused() -> None:
    discovery = DiscoveryReceipt.create("search", result={"candidate": 4})
    with pytest.raises(CertificateError, match="verification-layer"):
        TheoremCertificate.create(
            "claim.x",
            content_address({"statement": "x"}),
            (CertificateRef.from_certificate(discovery),),
            claim_boundary_hash=content_address({"boundary": "claim.x"}),
            verifier="tests.inference",
        )
    verification = VerificationCertificate.create("finite check", "tests.check")
    theorem_ref = CertificateRef(
        verification.certificate_id,
        CertificateLayer.THEOREM,
        verification.schema_version,
    )
    with pytest.raises(CertificateError, match="verification-layer"):
        TheoremCertificate.create(
            "claim.x",
            content_address({"statement": "x"}),
            (theorem_ref,),
            claim_boundary_hash=content_address({"boundary": "claim.x"}),
            verifier="tests.inference",
        )
    with pytest.raises(CertificateError, match="verification-layer"):
        VerificationCertificate.create(
            "circular trust",
            "tests.check",
            dependencies=(theorem_ref,),
        )


def test_verifier_registry_fails_closed_and_checks_report_binding() -> None:
    certificate = VerificationCertificate.create(
        "finite equality",
        "tests.eq",
        claim_id="claim.eq",
        statement_hash=content_address({"statement": "1=1"}),
        claim_boundary_hash=content_address({"boundary": "claim.eq"}),
        witness={"left": 1, "right": 1},
    )
    registry = VerifierRegistry()
    with pytest.raises(UnknownVerifierError):
        registry.verify(certificate)
    registry.register(
        "tests.eq",
        VerificationCertificate,
        lambda item: item.witness["left"] == item.witness["right"],
    )
    assert registry.verify(certificate).valid


def test_certificate_transport_checks_schema_layer_and_content_id() -> None:
    certificate = VerificationCertificate.create(
        "finite equality",
        "tests.eq",
        claim_id="claim.eq",
        statement_hash=content_address({"statement": "1=1"}),
        claim_boundary_hash=content_address({"boundary": "claim.eq"}),
        witness={"left": 1, "right": 1},
    )
    payload = certificate.to_dict()
    restored = certificate_from_dict(payload)
    assert restored.certificate_id == certificate.certificate_id

    wrong_layer = dict(payload)
    wrong_layer["layer"] = CertificateLayer.DISCOVERY.value
    with pytest.raises(CertificateError, match="requires layer"):
        certificate_from_dict(wrong_layer)
    unknown = dict(payload)
    unknown["schema_version"] = "unregistered/v9"
    with pytest.raises(CertificateError, match="unsupported"):
        certificate_from_dict(unknown)


def test_claim_bindings_are_complete_and_strictly_transported() -> None:
    statement_hash = content_address({"statement": "P"})
    boundary_hash = content_address({"boundary": "claim.p"})
    with pytest.raises(CertificateError, match="must be supplied together"):
        VerificationCertificate.create(
            "incomplete binding",
            "tests.binding",
            claim_id="claim.p",
            statement_hash=statement_hash,
        )

    binding = ClaimBinding("claim.p", statement_hash, boundary_hash)
    with pytest.raises(CertificateError, match="unexpected claim binding"):
        ClaimBinding.from_dict({**binding.to_dict(), "ignored": True})

    support = VerificationCertificate.create("support", "tests.support")
    theorem = TheoremCertificate.create(
        "claim.q",
        content_address({"statement": "Q"}),
        (CertificateRef.from_certificate(support),),
        claim_boundary_hash=content_address({"boundary": "claim.q"}),
        verifier="tests.inference",
        dependencies=(binding.claim_id,),
        claim_dependencies=(binding,),
    )
    payload = theorem.to_dict()
    payload.pop("certificate_id")
    payload.pop("claim_dependencies")
    with pytest.raises(CertificateError, match="missing required fields: claim_dependencies"):
        TheoremCertificate.from_dict(payload)


def test_certificate_transport_rejects_duplicate_unknown_and_coerced_fields() -> None:
    certificate = VerificationCertificate.create("finite equality", "tests.eq")
    encoded = json.dumps(certificate.to_dict(), separators=(",", ":"))
    duplicated = encoded.replace(
        '"subject":"finite equality"',
        '"subject":"forged","subject":"finite equality"',
    )
    with pytest.raises(CertificateError, match="duplicate JSON object key"):
        certificate_from_json(duplicated)

    malformed = certificate.to_dict()
    malformed.pop("certificate_id")
    malformed["subject"] = 7
    with pytest.raises(CertificateError, match="subject must be a string"):
        certificate_from_dict(malformed)

    unexpected = certificate.to_dict()
    unexpected.pop("certificate_id")
    unexpected["uncommitted_hint"] = "ignored before this regression"
    with pytest.raises(CertificateError, match="unexpected verification certificate"):
        certificate_from_dict(unexpected)


@pytest.mark.parametrize("sign", [1, -1])
def test_certificate_json_replays_arbitrarily_large_exact_integers(sign: int) -> None:
    huge = sign * (10**5000 + 12345)
    certificate = VerificationCertificate.create(
        "arbitrary integer witness",
        "tests.bigint",
        witness={"exact_integer": huge},
    )
    encoded = canonical_json(certificate.to_dict())

    restored = certificate_from_json(encoded)

    assert isinstance(restored, VerificationCertificate)
    assert restored.witness["exact_integer"] == huge
    assert restored.certificate_id == certificate.certificate_id

    tampered = certificate.to_dict()
    tampered["witness"] = {"exact_integer": huge + 1}
    with pytest.raises(ValueError, match="content address mismatch"):
        certificate_from_json(canonical_json(tampered))


def test_certificate_json_large_integer_parser_preserves_json_syntax_checks() -> None:
    huge = 10**5000
    certificate = VerificationCertificate.create(
        "arbitrary integer witness",
        "tests.bigint",
        witness={"exact_integer": huge},
    )
    encoded = canonical_json(certificate.to_dict())
    decimal = canonical_json(huge)

    for malformed_decimal in (f"0{decimal}", f"+{decimal}"):
        malformed = encoded.replace(decimal, malformed_decimal, 1)
        with pytest.raises(CertificateError, match="invalid certificate JSON"):
            certificate_from_json(malformed)

    nonexact = encoded.replace(decimal, f"{decimal}.0", 1)
    with pytest.raises(CertificateError, match="not exact certificate evidence"):
        certificate_from_json(nonexact)


@pytest.mark.parametrize(
    "certificate",
    [
        DiscoveryReceipt.create("search", result={"candidate": 4}),
        VerificationCertificate.create("finite equality", "tests.eq"),
        TheoremCertificate.create(
            "claim.x",
            content_address({"statement": "x"}),
            (
                CertificateRef.from_certificate(
                    VerificationCertificate.create("finite equality", "tests.eq")
                ),
            ),
            claim_boundary_hash=content_address({"boundary": "claim.x"}),
            verifier="tests.inference",
        ),
    ],
)
@pytest.mark.parametrize("invalid_id", ["", None])
def test_public_certificate_decoders_reject_explicit_invalid_identity(
    certificate: DiscoveryReceipt | VerificationCertificate | TheoremCertificate,
    invalid_id: object,
) -> None:
    payload = certificate.to_dict()
    payload["certificate_id"] = invalid_id

    with pytest.raises(ValueError, match=r"certificate_id|content address"):
        type(certificate).from_dict(payload)
