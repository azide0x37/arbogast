"""Shared content-addressing helpers for specialized Hurwitz receipts."""

from __future__ import annotations

from collections.abc import Sequence

from arbogast.cert import (
    CertificateLayer,
    ContentAddressedCertificate,
    VerificationCertificate,
)

RIGHT_HURWITZ_CONVENTION = (
    "zero-based right action sigma_i:(a,b)->(a*b*a^-1,a); inverse:(a,b)->(b,b^-1*a*b)"
)
INNER_CONJUGACY_CONVENTION = "simultaneous inner action g->h^-1*g*h"


class ExactHurwitzCertificate(ContentAddressedCertificate):
    """Content-addressed payload mixin for independently replayed finite receipts."""

    layer = CertificateLayer.VERIFICATION

    @property
    def content_id(self) -> str:
        """Alias emphasizing that identity covers payload bytes, not acceptance state."""

        return self.certificate_id

    def _semantic_certificate(
        self,
        *,
        subject: str,
        verifier: str,
        checks: Sequence[str],
        guarantees: Sequence[str],
    ) -> VerificationCertificate:
        """Wrap an already replayed specialized receipt in the semantic IR."""

        return VerificationCertificate.create(
            subject,
            verifier,
            witness={
                "specialized_certificate_id": self.certificate_id,
                "specialized_payload": self.to_canonical(),
            },
            checks=checks,
            guarantees=guarantees,
        )
