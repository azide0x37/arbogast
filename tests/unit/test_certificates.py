from __future__ import annotations

import json
import unicodedata

import pytest

from arbogast.cert import (
    CanonicalizationError,
    CertificateError,
    CertificateLayer,
    CertificateRef,
    DiscoveryReceipt,
    FrozenMap,
    TheoremCertificate,
    UnknownVerifierError,
    VerificationCertificate,
    VerifierRegistry,
    canonical_bytes,
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
