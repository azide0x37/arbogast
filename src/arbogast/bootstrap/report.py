"""Human/agent-readable projection of the authoritative readiness theorem."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from arbogast.cert import canonicalize
from arbogast.formats import BOOTSTRAP_REPORT_SCHEMA

from .models import ObligationStatus, ReadinessVerdict
from .preflight import EnvironmentPreflightReport

if TYPE_CHECKING:
    from .readiness import ReadinessResult


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    """Non-authoritative diagnostic projection.

    The certificate and environmental claim, not this convenience object,
    authorize campaign execution.
    """

    mode: str
    status: str
    verdict: ReadinessVerdict
    ready: bool
    subject: dict[str, str]
    checks: tuple[dict[str, object], ...]
    blockers: tuple[str, ...]
    unchecked: tuple[str, ...]
    warnings: tuple[str, ...]
    environment_id: str
    profile_id: str
    certificate_id: str
    claim_id: str

    schema: ClassVar[str] = BOOTSTRAP_REPORT_SCHEMA

    @classmethod
    def from_result(
        cls,
        result: ReadinessResult,
        *,
        mode: str | None = None,
    ) -> BootstrapReport:
        selected_mode = mode or result.profile.scope.value.lower()
        blockers = tuple(
            item.id
            for item in result.receipt.obligations
            if item.required and item.status is ObligationStatus.UNSATISFIED
        )
        unchecked = tuple(
            item.id
            for item in result.receipt.obligations
            if item.required
            and item.status
            in {
                ObligationStatus.UNKNOWN,
                ObligationStatus.UNSUPPORTED,
                ObligationStatus.UNCHECKED,
            }
        )
        warnings = tuple(
            f"optional obligation {item.id} is {item.status.value}"
            for item in result.receipt.obligations
            if not item.required and item.status is not ObligationStatus.SATISFIED
        )
        if result.certificate.claim_id is None:  # construction invariant
            raise ValueError("readiness certificate is not bound to its environmental claim")
        return cls(
            mode=selected_mode,
            status=type(result).__name__,
            verdict=result.verdict,
            ready=result.verdict is ReadinessVerdict.READY,
            subject=cast(dict[str, str], result.receipt.subject.to_dict()),
            checks=tuple(item.to_dict() for item in result.receipt.obligations),
            blockers=blockers,
            unchecked=unchecked,
            warnings=warnings,
            environment_id=result.environment.environment_id,
            profile_id=result.profile.profile_id,
            certificate_id=result.certificate.certificate_id,
            claim_id=result.certificate.claim_id,
        )

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            canonicalize(
                {
                    "schema": self.schema,
                    "authoritative": False,
                    "mode": self.mode,
                    "status": self.status,
                    "verdict": self.verdict.value,
                    "ready": self.ready,
                    "subject": self.subject,
                    "checks": self.checks,
                    "blockers": self.blockers,
                    "unchecked": self.unchecked,
                    "warnings": self.warnings,
                    "environment_id": self.environment_id,
                    "profile_id": self.profile_id,
                    "certificate_id": self.certificate_id,
                    "claim_id": self.claim_id,
                    "authoritative_artifacts": {
                        "environment": "environment-snapshot.json",
                        "profile": "readiness-profile.json",
                        "certificate": "readiness-certificate.json",
                        "claim": "readiness-claim.json",
                    },
                }
            ),
        )


def environment_preflight(
    mode: str,
    *,
    project_root: str | Path | None = None,
    artifact_root: str | Path | None = None,
    probe_external: bool = True,
) -> EnvironmentPreflightReport:
    """Compatibility import path for the diagnostic-only preflight report."""

    from .preflight import environment_preflight as run_preflight

    return run_preflight(
        mode,
        project_root=project_root,
        artifact_root=artifact_root,
        probe_external=probe_external,
    )


__all__ = ["BootstrapReport", "EnvironmentPreflightReport", "environment_preflight"]
