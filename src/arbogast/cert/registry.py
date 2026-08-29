"""Fail-closed registry for independent certificate verifiers."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeAlias, TypeVar, cast

from .base import Certificate, CertificateError
from .canonical import FrozenMap, freeze_mapping


class UnknownVerifierError(LookupError):
    """Raised when no explicitly registered verifier can check a certificate."""


class CertificateVerificationError(CertificateError):
    """Raised when a verifier rejects or cannot completely check evidence."""


@dataclass(frozen=True)
class VerificationReport:
    """Machine-readable outcome of independent certificate verification."""

    valid: bool
    verifier: str
    certificate_id: str
    checks: tuple[str, ...] = ()
    details: FrozenMap = field(default_factory=FrozenMap)
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.verifier.strip():
            raise CertificateVerificationError("report verifier cannot be blank")
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "details", freeze_mapping(self.details))
        if self.valid and self.error is not None:
            raise CertificateVerificationError("a valid report cannot carry an error")
        if not self.valid and not self.error:
            raise CertificateVerificationError("an invalid report must explain the failure")

    def require_valid(self) -> VerificationReport:
        if not self.valid:
            raise CertificateVerificationError(self.error or "certificate verification failed")
        return self

    def to_canonical(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "verifier": self.verifier,
            "certificate_id": self.certificate_id,
            "checks": self.checks,
            "details": self.details,
            "error": self.error,
        }


VerifierReturn: TypeAlias = VerificationReport | bool
Verifier: TypeAlias = Callable[[Certificate], VerifierReturn]
C = TypeVar("C", bound=Certificate)


@dataclass(frozen=True)
class _RegisteredVerifier:
    name: str
    certificate_type: type[Any]
    function: Verifier


class VerifierRegistry:
    """Explicit verifier dispatch with no permissive fallback."""

    def __init__(self) -> None:
        self._verifiers: dict[str, _RegisteredVerifier] = {}

    def register(
        self,
        name: str,
        certificate_type: type[C],
        function: Callable[[C], VerifierReturn],
    ) -> None:
        if not name.strip():
            raise ValueError("verifier name cannot be blank")
        existing = self._verifiers.get(name)
        erased = cast(Verifier, function)
        candidate = _RegisteredVerifier(name, certificate_type, erased)
        if existing is not None and existing != candidate:
            raise ValueError(f"verifier already registered: {name}")
        self._verifiers[name] = candidate

    def unregister(self, name: str) -> None:
        if name not in self._verifiers:
            raise UnknownVerifierError(name)
        del self._verifiers[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._verifiers))

    def describe(self, name: str) -> dict[str, str]:
        registered = self._verifiers.get(name)
        if registered is None and self is default_verifiers:
            module_name = _BUILTIN_VERIFIER_MODULES.get(name)
            if module_name is not None:
                importlib.import_module(module_name)
                registered = self._verifiers.get(name)
        if registered is None:
            raise UnknownVerifierError(name)
        certificate_type = registered.certificate_type
        return {
            "name": name,
            "certificate_type": f"{certificate_type.__module__}.{certificate_type.__qualname__}",
            "callable": (
                f"{registered.function.__module__}."
                f"{getattr(registered.function, '__qualname__', registered.function.__name__)}"
            ),
        }

    def verify(
        self,
        certificate: Certificate,
        *,
        verifier_name: str | None = None,
        raise_on_failure: bool = True,
    ) -> VerificationReport:
        certificate.verify_integrity() if hasattr(certificate, "verify_integrity") else None
        name = verifier_name or getattr(certificate, "verifier", None)
        if not isinstance(name, str) or not name:
            raise UnknownVerifierError("certificate has no verifier name; select one explicitly")
        registered = self._verifiers.get(name)
        if registered is None and self is default_verifiers:
            module_name = _BUILTIN_VERIFIER_MODULES.get(name)
            if module_name is not None:
                importlib.import_module(module_name)
                registered = self._verifiers.get(name)
        if registered is None:
            raise UnknownVerifierError(name)
        if not isinstance(certificate, registered.certificate_type):
            raise CertificateVerificationError(
                f"verifier {name} expects {registered.certificate_type.__qualname__}, "
                f"got {type(certificate).__qualname__}"
            )
        try:
            raw = registered.function(certificate)
        except CertificateVerificationError:
            raise
        except Exception as exc:
            raise CertificateVerificationError(
                f"verifier {name} raised {type(exc).__name__}: {exc}"
            ) from exc
        if isinstance(raw, bool):
            report = VerificationReport(
                valid=raw,
                verifier=name,
                certificate_id=certificate.certificate_id,
                error=None if raw else f"verifier {name} rejected the certificate",
            )
        elif isinstance(raw, VerificationReport):
            if raw.certificate_id != certificate.certificate_id:
                raise CertificateVerificationError(
                    "verifier report is bound to a different certificate"
                )
            if raw.verifier != name:
                raise CertificateVerificationError("verifier report names a different verifier")
            report = raw
        else:
            raise CertificateVerificationError(
                f"verifier {name} returned unsupported result {type(raw).__qualname__}"
            )
        if raise_on_failure:
            report.require_valid()
        return report


default_verifiers = VerifierRegistry()

_BUILTIN_VERIFIER_MODULES = {
    "campaign.claim-closure.v1": "arbogast.campaign.claims",
    "cohom.normalized_bar.v1": "arbogast.cohom.semantic",
    "hurwitz.nielsen_class": "arbogast.hurwitz.claims",
    "hurwitz.braid_action": "arbogast.hurwitz.claims",
    "hurwitz.components": "arbogast.hurwitz.claims",
    "hurwitz.real_structure": "arbogast.hurwitz.claims",
    "hurwitz.real_census": "arbogast.hurwitz.claims",
    "hurwitz.reduced": "arbogast.hurwitz.claims",
    "hurwitz.cusps": "arbogast.hurwitz.claims",
    "hurwitz.boundary": "arbogast.hurwitz.claims",
}


def verifier(
    name: str,
    *,
    certificate_type: type[C],
    registry: VerifierRegistry = default_verifiers,
) -> Callable[[Callable[[C], VerifierReturn]], Callable[[C], VerifierReturn]]:
    """Register a typed verifier function."""

    def decorate(function: Callable[[C], VerifierReturn]) -> Callable[[C], VerifierReturn]:
        registry.register(name, certificate_type, function)
        return function

    return decorate


def verify_certificate(
    certificate: Certificate,
    *,
    verifier_name: str | None = None,
    registry: VerifierRegistry = default_verifiers,
    raise_on_failure: bool = True,
) -> VerificationReport:
    """Verify a certificate through an explicitly registered independent checker."""

    return registry.verify(
        certificate,
        verifier_name=verifier_name,
        raise_on_failure=raise_on_failure,
    )


__all__ = [
    "CertificateVerificationError",
    "UnknownVerifierError",
    "VerificationReport",
    "VerifierRegistry",
    "default_verifiers",
    "verifier",
    "verify_certificate",
]
