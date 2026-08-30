"""Nested arithmetic evidence accepted by canonical Galois objects.

A :class:`~arbogast.galois.proof.VerificationRequirement` says which verifier
would be needed; it is not evidence that the verifier ran.  Constructors in
the exact substrate therefore accept only a central verification certificate,
replay it through the registry, and then bind the complete reproduced payload
to the mathematical object being constructed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from arbogast.backends.pari_certificate import PARI_VERIFIER_ID, PARI_WITNESS_SCHEMA
from arbogast.cert import (
    FrozenMap,
    VerificationCertificate,
    content_address,
    freeze_mapping,
    verify_certificate,
)
from arbogast.core import ValidationError

_PARI_WITNESS_KEYS = {
    "backend_version",
    "completeness",
    "deterministic_seed",
    "expected_payload",
    "expected_payload_id",
    "limits",
    "operation",
    "proof_mode",
    "protocol",
    "replay",
    "request_id",
    "schema",
    "supported_range",
    "template",
}


@dataclass(frozen=True, slots=True)
class VerifiedPariEvidence:
    """The exact payload and replay data recovered from one verified receipt."""

    certificate_id: str
    operation: str
    backend_version: str
    payload: FrozenMap
    replay: FrozenMap


def verified_pari_evidence(
    certificate: VerificationCertificate,
    operation: str,
) -> VerifiedPariEvidence:
    """Replay and decode an unconditional, payload-bound PARI certificate.

    This deliberately does not accept a discovery receipt or a bare verifier
    name.  The central registry performs the independent fresh-process replay;
    the checks below then fail closed if the nested schema or payload binding
    is not the one understood by the exact substrate.
    """

    if not isinstance(certificate, VerificationCertificate):
        raise TypeError("proving certificate must be a VerificationCertificate")
    if certificate.verifier != PARI_VERIFIER_ID:
        raise ValidationError("proving certificate must use the pinned PARI verifier")
    report = verify_certificate(certificate).require_valid()
    if report.verifier != PARI_VERIFIER_ID or report.certificate_id != certificate.certificate_id:
        raise ValidationError("central certificate report does not bind the supplied certificate")

    witness = certificate.witness.to_dict()
    if set(witness) != _PARI_WITNESS_KEYS or witness.get("schema") != PARI_WITNESS_SCHEMA:
        raise ValidationError("proving certificate has an unsupported PARI witness schema")
    if witness.get("operation") != operation:
        raise ValidationError(f"proving certificate does not certify {operation}")
    if witness.get("proof_mode") != "unconditional":
        raise ValidationError("exact substrate objects require unconditional proving evidence")
    if witness.get("completeness") != "COMPLETE":
        raise ValidationError("exact substrate objects require complete proving evidence")

    payload = _mapping(witness.get("expected_payload"), "PARI expected payload")
    replay = _mapping(witness.get("replay"), "PARI replay")
    expected_payload_id = witness.get("expected_payload_id")
    if not isinstance(expected_payload_id, str) or content_address(payload) != expected_payload_id:
        raise ValidationError("PARI proving certificate payload ID does not match its payload")
    if certificate.subject != f"pari:{operation}:{expected_payload_id}":
        raise ValidationError("PARI proving certificate subject is not payload-bound")
    backend_version = witness.get("backend_version")
    if not isinstance(backend_version, str) or not backend_version:
        raise ValidationError("PARI proving certificate omits its pinned backend version")
    return VerifiedPariEvidence(
        certificate.certificate_id,
        operation,
        backend_version,
        freeze_mapping(payload),
        freeze_mapping(replay),
    )


def _mapping(value: object, name: str) -> dict[str, object]:
    if isinstance(value, FrozenMap):
        return value.to_dict()
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValidationError(f"{name} must be a string-keyed mapping")
    return dict(value)


__all__ = ["VerifiedPariEvidence", "verified_pari_evidence"]
