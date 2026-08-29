"""Mathematical claims as five-question semantic records."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from arbogast.cert.base import Certificate, CertificateLayer, CertificateRef
from arbogast.cert.canonical import (
    FrozenMap,
    canonicalize,
    content_address,
    freeze_mapping,
    validate_content_address,
)
from arbogast.cert.registry import (
    CertificateVerificationError,
    VerifierRegistry,
    default_verifiers,
    verify_certificate,
)
from arbogast.cert.theorem import TheoremCertificate
from arbogast.cert.verification import VerificationCertificate

from .derivation import Derivation
from .novelty import NoveltyRecord
from .statement import FormalStatement
from .status import EpistemicStatus, EpistemicValue

if TYPE_CHECKING:
    from os import PathLike

    from arbogast.proof.gap import ProofGap


class ClaimError(ValueError):
    """Raised when a claim crosses or obscures a theorem boundary."""


class ClaimVerificationError(ClaimError):
    """Raised when structural validity cannot be promoted to mathematical verification."""


class ClaimKind(StrEnum):
    ASSUMED = "assumed"
    IMPORTED = "imported"
    COMPUTED = "computed"
    DERIVED = "derived"
    CONJECTURED = "conjectured"


class EvidenceKind(StrEnum):
    CERTIFICATE = "certificate"
    ARTIFACT = "artifact"
    WITNESS = "witness"
    DATASET = "dataset"


@dataclass(frozen=True)
class ClaimRef:
    claim_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.claim_id, field="claim reference")

    def to_canonical(self) -> str:
        return self.claim_id


@dataclass(frozen=True)
class EvidenceRef:
    """Typed evidence reference; certificate layers remain visible."""

    ref: str
    kind: EvidenceKind = EvidenceKind.ARTIFACT
    certificate_layer: CertificateLayer | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str):
            raise ClaimError("evidence reference must be a string")
        if not self.ref.strip():
            raise ClaimError("evidence reference cannot be blank")
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", EvidenceKind(self.kind))
        if isinstance(self.certificate_layer, str):
            object.__setattr__(self, "certificate_layer", CertificateLayer(self.certificate_layer))
        if self.kind is EvidenceKind.CERTIFICATE:
            validate_content_address(self.ref)
            if self.certificate_layer is None:
                raise ClaimError("certificate evidence must identify its semantic layer")
        elif self.certificate_layer is not None:
            raise ClaimError("certificate_layer is only valid for certificate evidence")
        if self.description is not None and (
            not isinstance(self.description, str) or not self.description.strip()
        ):
            raise ClaimError("evidence description must be a non-blank string")

    @classmethod
    def certificate(cls, certificate: Certificate | CertificateRef) -> EvidenceRef:
        if isinstance(certificate, CertificateRef):
            ref = certificate
        else:
            ref = CertificateRef.from_certificate(certificate)
        return cls(ref.certificate_id, EvidenceKind.CERTIFICATE, ref.layer)

    def to_canonical(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "kind": self.kind.value,
            "certificate_layer": (
                self.certificate_layer.value if self.certificate_layer is not None else None
            ),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvidenceRef:
        allowed = {"ref", "kind", "certificate_layer", "description"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ClaimError(f"unexpected evidence reference fields: {', '.join(unexpected)}")
        raw_ref = value.get("ref")
        raw_kind = value.get("kind", EvidenceKind.ARTIFACT.value)
        raw_layer = value.get("certificate_layer")
        description = value.get("description")
        if not isinstance(raw_ref, str):
            raise ClaimError("evidence ref must be a string")
        if not isinstance(raw_kind, str):
            raise ClaimError("evidence kind must be a string")
        if raw_layer is not None and not isinstance(raw_layer, str):
            raise ClaimError("certificate_layer must be a string or null")
        if description is not None and not isinstance(description, str):
            raise ClaimError("evidence description must be a string or null")
        return cls(
            ref=raw_ref,
            kind=EvidenceKind(raw_kind),
            certificate_layer=(CertificateLayer(raw_layer) if raw_layer is not None else None),
            description=description,
        )


@dataclass(frozen=True, init=False)
class Claim:
    """A mathematical claim answering what, why, how, evidence, and source."""

    id: str
    what: FormalStatement
    kind: ClaimKind
    status: EpistemicStatus
    why: tuple[ClaimRef, ...]
    how: Derivation | None
    evidence: tuple[EvidenceRef, ...]
    source: tuple[str, ...]
    hypotheses: tuple[FormalStatement, ...]
    novelty: NoveltyRecord | None
    formalization: ProofGap | None
    metadata: FrozenMap
    _attached_certificates: tuple[Certificate, ...] = field(
        default=(), repr=False, compare=False, hash=False
    )

    schema_version = "arbogast.claim/v1"

    def __init__(
        self,
        id: str,
        what: FormalStatement | str | None = None,
        *,
        statement: FormalStatement | str | None = None,
        conclusion: FormalStatement | str | None = None,
        kind: ClaimKind | str,
        status: EpistemicStatus | str | EpistemicValue[Any],
        why: Sequence[ClaimRef | str] = (),
        how: Derivation | None = None,
        derivation: Derivation | None = None,
        evidence: Sequence[EvidenceRef | Certificate | CertificateRef | str] = (),
        certificate: Certificate | CertificateRef | str | None = None,
        source: str | Sequence[str] = (),
        hypotheses: Sequence[FormalStatement | str] = (),
        novelty: NoveltyRecord | None = None,
        formalization: ProofGap | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        from arbogast.proof.gap import ProofGap

        _validate_identifier(id, field="claim id")
        candidates = [
            candidate for candidate in (what, statement, conclusion) if candidate is not None
        ]
        if len(candidates) != 1:
            raise ClaimError("provide exactly one of what, statement, or conclusion")
        formal = _statement(candidates[0])
        claim_kind = ClaimKind(kind)
        if isinstance(status, EpistemicValue):
            claim_status = status.status
        else:
            claim_status = EpistemicStatus(status)
        if how is not None and derivation is not None and how != derivation:
            raise ClaimError("how and derivation disagree")
        method = how or derivation
        dependencies = tuple(_claim_ref(item) for item in why)
        attached = tuple(item for item in evidence if isinstance(item, Certificate))
        refs = [_evidence_ref(item) for item in evidence]
        if certificate is not None:
            refs.append(_certificate_evidence(certificate))
            if isinstance(certificate, Certificate) and not isinstance(certificate, CertificateRef):
                attached += (certificate,)
        sources = (source,) if isinstance(source, str) else tuple(source)
        hypothesis_records = tuple(_statement(item) for item in hypotheses)
        if formalization is not None and not isinstance(formalization, ProofGap):
            raise ClaimError("formalization must be a ProofGap or null")
        if formalization is not None and formalization.claim_id != id:
            raise ClaimError("formalization proof gap is bound to a different claim")

        object.__setattr__(self, "id", id)
        object.__setattr__(self, "what", formal)
        object.__setattr__(self, "kind", claim_kind)
        object.__setattr__(self, "status", claim_status)
        object.__setattr__(self, "why", dependencies)
        object.__setattr__(self, "how", method)
        object.__setattr__(self, "evidence", tuple(refs))
        object.__setattr__(self, "source", sources)
        object.__setattr__(self, "hypotheses", hypothesis_records)
        object.__setattr__(self, "novelty", novelty)
        object.__setattr__(self, "formalization", formalization)
        object.__setattr__(self, "metadata", freeze_mapping(metadata))
        object.__setattr__(self, "_attached_certificates", attached)
        self._validate_boundaries()

    @property
    def statement(self) -> FormalStatement:
        return self.what

    @property
    def conclusion(self) -> FormalStatement:
        return self.what

    @property
    def claim_id(self) -> str:
        return self.id

    @property
    def digest(self) -> str:
        return content_address(self.to_canonical())

    @property
    def dependency_ids(self) -> tuple[str, ...]:
        return tuple(ref.claim_id for ref in self.why)

    def _validate_boundaries(self) -> None:
        if any(not source.strip() for source in self.source):
            raise ClaimError("source references cannot be blank")
        if len(set(self.dependency_ids)) != len(self.dependency_ids):
            raise ClaimError("claim dependencies in why must be unique")
        if self.kind is ClaimKind.DERIVED and not self.why:
            raise ClaimError("derived claims require explicit claim dependencies in why")
        if self.kind is ClaimKind.DERIVED and (
            self.how is None or self.how.kind.value != "inference"
        ):
            raise ClaimError("derived claims require an explicit inference derivation in how")
        if self.kind is ClaimKind.DERIVED and not self.evidence:
            raise ClaimError(
                "derived claims require replayable certificate evidence for the inference"
            )
        if self.kind is ClaimKind.DERIVED and not any(
            ref.kind is EvidenceKind.CERTIFICATE
            and ref.certificate_layer is CertificateLayer.THEOREM
            for ref in self.evidence
        ):
            raise ClaimError("derived claims require theorem-layer evidence binding the inference")
        if self.kind is ClaimKind.IMPORTED and not self.source:
            raise ClaimError("imported claims require theorem-level source references")
        if self.kind is ClaimKind.COMPUTED:
            if self.how is None or self.how.kind.value != "computation" or not self.how.operation:
                raise ClaimError(
                    "computed claims require a computation derivation with a named operation"
                )
            if not self.evidence:
                raise ClaimError("computed claims require explicit evidence")
        if self.kind is ClaimKind.ASSUMED and self.status not in {
            EpistemicStatus.CONDITIONAL,
            EpistemicStatus.UNKNOWN,
        }:
            raise ClaimError("assumptions must remain conditional or unknown")
        if self.kind is ClaimKind.CONJECTURED and self.status in {
            EpistemicStatus.EXACT,
            EpistemicStatus.CERTIFIED,
        }:
            raise ClaimError("conjectures cannot be marked exact or certified")
        if self.status is EpistemicStatus.CERTIFIED:
            proving_layers = {
                ref.certificate_layer
                for ref in self.evidence
                if ref.kind is EvidenceKind.CERTIFICATE
            }
            if not proving_layers.intersection(
                {CertificateLayer.VERIFICATION, CertificateLayer.THEOREM}
            ):
                raise ClaimError(
                    "certified claims require verification- or theorem-layer certificate evidence"
                )
        if self.novelty is not None and self.novelty.claim_id != self.id:
            raise ClaimError("novelty record is bound to a different claim")
        if self.formalization is not None and self.formalization.claim_id != self.id:
            raise ClaimError("formalization proof gap is bound to a different claim")

    def verify(
        self,
        certificates: Mapping[str, Certificate] | None = None,
        *,
        verifier_registry: VerifierRegistry = default_verifiers,
        source_registry: object | None = None,
        verified_dependencies: Collection[str] = (),
        dependency_claims: Mapping[str, Claim] | None = None,
        structural_only: bool = False,
        raise_on_failure: bool = True,
    ) -> ClaimVerificationReport:
        """Verify this claim without conflating structural validity with theorem validity.

        Attached certificate objects enable zero-argument replay.  Bare certificate references
        must be resolved through ``certificates``.  ``structural_only`` is deliberately reported
        as not theorem-verified.
        """

        self._validate_boundaries()
        if structural_only:
            return ClaimVerificationReport(
                claim_id=self.id,
                structural_valid=True,
                verified=False,
                checks=("claim-boundaries",),
                error="structural validation does not verify mathematical evidence",
            )
        try:
            checks = ["claim-boundaries"]
            if self.kind is ClaimKind.ASSUMED:
                raise ClaimVerificationError("assumptions are hypotheses, not verified claims")
            if self.kind is ClaimKind.CONJECTURED:
                raise ClaimVerificationError("conjectures cannot be reported as verified")
            if self.kind is ClaimKind.IMPORTED:
                _verify_sources(self, source_registry)
                checks.append("source-references-resolved")
            elif self.kind is ClaimKind.COMPUTED:
                resolved = self._resolve_certificates(certificates)
                _verify_computed_evidence(
                    self,
                    resolved,
                    verifier_registry=verifier_registry,
                )
                checks.extend(("certificate-addresses", "certificate-replay"))
            elif self.kind is ClaimKind.DERIVED:
                missing = sorted(set(self.dependency_ids) - set(verified_dependencies))
                if missing:
                    raise ClaimVerificationError(
                        f"derived claim has unverified dependencies: {', '.join(missing)}"
                    )
                if dependency_claims is None:
                    raise ClaimVerificationError(
                        "derived claim verification requires its dependency claim records"
                    )
                _verify_dependency_boundaries(self, dependency_claims)
                resolved = self._resolve_certificates(certificates)
                _verify_computed_evidence(
                    self,
                    resolved,
                    verifier_registry=verifier_registry,
                )
                checks.extend(("dependencies-verified", "derivation-certificate-replay"))
            if self.status is EpistemicStatus.CERTIFIED and self.kind is ClaimKind.IMPORTED:
                resolved = self._resolve_certificates(certificates)
                _verify_computed_evidence(
                    self,
                    resolved,
                    verifier_registry=verifier_registry,
                )
                checks.extend(("certified-status-binding", "certificate-replay"))
            return ClaimVerificationReport(
                claim_id=self.id,
                structural_valid=True,
                verified=True,
                checks=tuple(checks),
            )
        except (ClaimVerificationError, CertificateVerificationError, LookupError) as exc:
            report = ClaimVerificationReport(
                claim_id=self.id,
                structural_valid=True,
                verified=False,
                checks=("claim-boundaries",),
                error=str(exc),
            )
            if raise_on_failure:
                raise ClaimVerificationError(str(exc)) from exc
            return report

    def _resolve_certificates(
        self, supplied: Mapping[str, Certificate] | None
    ) -> dict[str, Certificate]:
        resolved = {
            certificate.certificate_id: certificate for certificate in self._attached_certificates
        }
        if supplied is not None:
            for key, certificate in supplied.items():
                certificate_id = certificate.certificate_id
                if key != certificate_id:
                    raise ClaimVerificationError(
                        f"certificate resolver key {key} does not match content {certificate_id}"
                    )
                existing = resolved.get(key)
                if existing is not None and existing != certificate:
                    raise ClaimVerificationError(f"conflicting certificate content for {key}")
                resolved[key] = certificate
        return resolved

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "what": self.what,
            "kind": self.kind.value,
            "status": self.status.value,
            "why": self.why,
            "how": self.how,
            "evidence": self.evidence,
            "source": self.source,
            "hypotheses": self.hypotheses,
            "novelty": self.novelty,
            "formalization": self.formalization,
            "metadata": self.metadata,
        }

    def to_dict(self) -> dict[str, object]:
        plain = canonicalize(self.to_canonical())
        if not isinstance(plain, dict):
            raise ClaimError("claim canonical form must be an object")
        if self._attached_certificates:
            plain["attached_certificates"] = canonicalize(
                tuple(certificate.to_dict() for certificate in self._attached_certificates)
            )
        return cast(dict[str, object], plain)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Claim:
        allowed = {
            "schema_version",
            "id",
            "what",
            "statement",
            "kind",
            "status",
            "why",
            "how",
            "evidence",
            "source",
            "hypotheses",
            "novelty",
            "formalization",
            "metadata",
            "attached_certificates",
        }
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ClaimError(f"unexpected claim fields: {', '.join(unexpected)}")
        schema = value.get("schema_version")
        if schema != cls.schema_version:
            raise ClaimError(
                f"unsupported or missing claim schema: expected {cls.schema_version}, "
                f"got {schema!r}"
            )
        statement_fields = [name for name in ("what", "statement") if name in value]
        if len(statement_fields) != 1:
            raise ClaimError("claim transport must contain exactly one of what or statement")
        what_raw = value[statement_fields[0]]
        if isinstance(what_raw, Mapping):
            what = FormalStatement.from_dict(what_raw)
        elif isinstance(what_raw, str):
            what = FormalStatement(what_raw)
        else:
            raise ClaimError("claim what/statement must be a statement object or string")
        why_raw = _sequence(value.get("why", ()), "why")
        evidence_raw = _sequence(value.get("evidence", ()), "evidence")
        hypotheses_raw = _sequence(value.get("hypotheses", ()), "hypotheses")
        derivation_raw = value.get("how")
        novelty_raw = value.get("novelty")
        formalization_raw = value.get("formalization")
        metadata_raw = value.get("metadata")
        raw_id = value.get("id")
        if not isinstance(raw_id, str):
            raise ClaimError("claim id must be a string")
        if derivation_raw is not None and not isinstance(derivation_raw, Mapping):
            raise ClaimError("claim how must be a derivation object or null")
        if novelty_raw is not None and not isinstance(novelty_raw, Mapping):
            raise ClaimError("claim novelty must be an object or null")
        if formalization_raw is not None and not isinstance(formalization_raw, Mapping):
            raise ClaimError("claim formalization must be a proof-gap object or null")
        if metadata_raw is not None and not isinstance(metadata_raw, Mapping):
            raise ClaimError("claim metadata must be a mapping")
        sources = _sequence(value.get("source", ()), "source")
        if any(not isinstance(item, str) for item in sources):
            raise ClaimError("claim source entries must be strings")
        claim = cls(
            id=raw_id,
            what=what,
            kind=_required_claim_kind(value),
            status=_required_claim_status(value),
            why=tuple(_claim_ref_from_raw(item) for item in why_raw),
            how=(
                Derivation.from_dict(derivation_raw)
                if isinstance(derivation_raw, Mapping)
                else None
            ),
            evidence=tuple(_evidence_from_raw(item) for item in evidence_raw),
            source=tuple(cast(Sequence[str], sources)),
            hypotheses=tuple(_statement_from_raw(item) for item in hypotheses_raw),
            novelty=(
                NoveltyRecord.from_dict(novelty_raw) if isinstance(novelty_raw, Mapping) else None
            ),
            formalization=_formalization_from_raw(formalization_raw),
            metadata=metadata_raw,
        )
        attached_raw = value.get("attached_certificates", ())
        attached_sequence = _sequence(attached_raw, "attached_certificates")
        if attached_sequence:
            from arbogast.cert.io import certificate_from_dict

            attached: list[Certificate] = []
            evidence_ids = {item.ref for item in claim.evidence}
            for item in attached_sequence:
                if not isinstance(item, Mapping):
                    raise ClaimError("attached certificate must be a mapping")
                certificate = certificate_from_dict(item)
                if certificate.certificate_id not in evidence_ids:
                    raise ClaimError(
                        "attached certificate is not committed by the claim evidence list"
                    )
                attached.append(certificate)
            attached_ids = tuple(item.certificate_id for item in attached)
            if len(set(attached_ids)) != len(attached_ids):
                raise ClaimError("attached certificates must have unique content IDs")
            object.__setattr__(claim, "_attached_certificates", tuple(attached))
        return claim

    def export(
        self,
        format: str,
        destination: str | PathLike[str] | None = None,
        **options: object,
    ) -> str:
        """Render this claim through the stable export surface."""

        from arbogast.export import export

        return export(self, format, destination=destination, **options)


@dataclass(frozen=True)
class ClaimVerificationReport:
    """Separate structural validity from successful mathematical replay."""

    claim_id: str
    structural_valid: bool
    verified: bool
    checks: tuple[str, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))
        if self.verified and (not self.structural_valid or self.error is not None):
            raise ClaimVerificationError(
                "verified report must be structurally valid and error-free"
            )
        if not self.verified and not self.error:
            raise ClaimVerificationError("unverified report must explain the verification gap")

    def to_canonical(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "structural_valid": self.structural_valid,
            "verified": self.verified,
            "checks": self.checks,
            "error": self.error,
        }


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")


def _validate_identifier(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ClaimError(
            f"{field} must start alphanumerically and contain only A-Z, a-z, 0-9, ._:/-"
        )


def _statement(value: FormalStatement | str) -> FormalStatement:
    return value if isinstance(value, FormalStatement) else FormalStatement(value)


def _claim_ref(value: ClaimRef | str) -> ClaimRef:
    return value if isinstance(value, ClaimRef) else ClaimRef(value)


def _evidence_ref(value: EvidenceRef | Certificate | CertificateRef | str) -> EvidenceRef:
    if isinstance(value, EvidenceRef):
        return value
    if isinstance(value, CertificateRef):
        return EvidenceRef.certificate(value)
    if isinstance(value, Certificate):
        return EvidenceRef.certificate(value)
    return EvidenceRef(value, EvidenceKind.ARTIFACT)


def _certificate_evidence(value: Certificate | CertificateRef | str) -> EvidenceRef:
    if isinstance(value, str):
        validate_content_address(value)
        return EvidenceRef(value, EvidenceKind.CERTIFICATE, CertificateLayer.VERIFICATION)
    return EvidenceRef.certificate(value)


def _sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ClaimError(f"claim {field} must be a sequence")
    return value


def _claim_ref_from_raw(value: object) -> ClaimRef:
    if isinstance(value, str):
        return ClaimRef(value)
    if isinstance(value, Mapping):
        allowed = {"claim_id", "id"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ClaimError(f"unexpected claim reference fields: {', '.join(unexpected)}")
        fields = [name for name in ("claim_id", "id") if name in value]
        if len(fields) != 1 or not isinstance(value[fields[0]], str):
            raise ClaimError("claim dependency object requires one string claim_id or id")
        return ClaimRef(cast(str, value[fields[0]]))
    raise ClaimError("claim dependency must be a string or mapping")


def _evidence_from_raw(value: object) -> EvidenceRef:
    if isinstance(value, str):
        return EvidenceRef(value)
    if isinstance(value, Mapping):
        return EvidenceRef.from_dict(value)
    raise ClaimError("claim evidence must be a string or mapping")


def _statement_from_raw(value: object) -> FormalStatement:
    if isinstance(value, str):
        return FormalStatement(value)
    if isinstance(value, Mapping):
        return FormalStatement.from_dict(value)
    raise ClaimError("claim hypothesis must be a string or mapping")


def _formalization_from_raw(value: object) -> ProofGap | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ClaimError("claim formalization must be a proof-gap object or null")
    from arbogast.proof.gap import ProofGap

    try:
        return ProofGap.from_dict(value)
    except ValueError as exc:
        raise ClaimError(f"invalid claim formalization: {exc}") from exc


def _required_claim_kind(value: Mapping[str, object]) -> ClaimKind:
    if "kind" not in value:
        raise ClaimError("claim kind is required; it cannot default to computed")
    raw = value["kind"]
    if not isinstance(raw, str):
        raise ClaimError("claim kind must be a string")
    try:
        return ClaimKind(raw)
    except ValueError as exc:
        raise ClaimError(f"invalid claim kind: {value['kind']!r}") from exc


def _required_claim_status(value: Mapping[str, object]) -> EpistemicStatus:
    if "status" not in value:
        raise ClaimError("claim epistemic status is required")
    raw = value["status"]
    if not isinstance(raw, str):
        raise ClaimError("claim epistemic status must be a string")
    try:
        return EpistemicStatus(raw)
    except ValueError as exc:
        raise ClaimError(f"invalid epistemic status: {value['status']!r}") from exc


def _verify_sources(claim: Claim, source_registry: object | None) -> None:
    if source_registry is None:
        raise ClaimVerificationError("imported claim requires a source registry for replay")
    lookup = getattr(source_registry, "reference", None)
    if not callable(lookup):
        raise ClaimVerificationError("source registry does not expose reference(key)")
    for source_id in claim.source:
        try:
            reference = lookup(source_id)
        except Exception as exc:
            raise ClaimVerificationError(f"unresolved source reference: {source_id}") from exc
        statement = getattr(reference, "statement", None)
        statement_hash = getattr(statement, "statement_hash", None)
        if statement_hash != claim.what.statement_hash:
            raise ClaimVerificationError(
                f"source reference {source_id} states a different proposition"
            )
        imported_as = getattr(reference, "imported_as", ())
        if imported_as and claim.id not in imported_as:
            raise ClaimVerificationError(
                f"source reference {source_id} is not bound to claim {claim.id}"
            )


def _verify_dependency_boundaries(
    claim: Claim,
    dependencies: Mapping[str, Claim],
) -> None:
    """Reject epistemic promotion across the theorem DAG."""

    expected = set(claim.dependency_ids)
    missing = sorted(expected - dependencies.keys())
    if missing:
        raise ClaimVerificationError(
            f"derived claim is missing dependency records: {', '.join(missing)}"
        )
    for dependency_id in claim.dependency_ids:
        dependency = dependencies[dependency_id]
        if dependency.id != dependency_id:
            raise ClaimVerificationError(
                f"dependency resolver key {dependency_id} names claim {dependency.id}"
            )
        if dependency.status is EpistemicStatus.CONDITIONAL and claim.status not in {
            EpistemicStatus.CONDITIONAL,
            EpistemicStatus.UNKNOWN,
        }:
            raise ClaimVerificationError(
                f"derived claim cannot erase the conditional status of {dependency_id}"
            )
        if (
            dependency.status is EpistemicStatus.UNKNOWN
            and claim.status is not EpistemicStatus.UNKNOWN
        ):
            raise ClaimVerificationError(
                f"derived claim cannot erase the unknown status of {dependency_id}"
            )
        if dependency.status in {
            EpistemicStatus.NUMERICAL,
            EpistemicStatus.HEURISTIC,
        } and claim.status in {
            EpistemicStatus.EXACT,
            EpistemicStatus.CERTIFIED,
        }:
            raise ClaimVerificationError(
                f"derived claim cannot promote the {dependency.status.value} status of "
                f"{dependency_id} to {claim.status.value}"
            )


def _verify_computed_evidence(
    claim: Claim,
    certificates: Mapping[str, Certificate],
    *,
    verifier_registry: VerifierRegistry,
) -> None:
    certificate_refs = [ref for ref in claim.evidence if ref.kind is EvidenceKind.CERTIFICATE]
    if not certificate_refs:
        raise ClaimVerificationError(
            "computed claim has no verification/theorem certificate to replay"
        )
    replayed = False
    replayed_verification: set[str] = set()
    for evidence in certificate_refs:
        evidence_layer = evidence.certificate_layer
        if evidence_layer is None:
            raise ClaimVerificationError(
                f"certificate evidence has no declared layer: {evidence.ref}"
            )
        if evidence_layer is CertificateLayer.DISCOVERY:
            continue
        certificate = certificates.get(evidence.ref)
        if certificate is None:
            raise ClaimVerificationError(f"unresolved certificate evidence: {evidence.ref}")
        if certificate.certificate_id != evidence.ref:
            raise ClaimVerificationError(f"tampered certificate evidence: {evidence.ref}")
        if certificate.layer is not evidence_layer:
            raise ClaimVerificationError(
                f"certificate evidence layer mismatch for {evidence.ref}: declared "
                f"{evidence_layer.value}, resolved {certificate.layer.value}"
            )
        integrity = getattr(certificate, "verify_integrity", None)
        if not callable(integrity):
            raise ClaimVerificationError(
                f"certificate does not support integrity verification: {evidence.ref}"
            )
        integrity(evidence.ref)
        if isinstance(certificate, VerificationCertificate):
            if claim.kind is ClaimKind.DERIVED:
                # Verification-layer records may be bundled as theorem support, but they cannot
                # themselves establish an inference between ClaimGraph nodes.
                continue
            if certificate.claim_id != claim.id:
                raise ClaimVerificationError(
                    "verification certificate is not bound to this claim ID"
                )
            if certificate.statement_hash != claim.what.statement_hash:
                raise ClaimVerificationError("verification certificate statement hash mismatch")
            _replay_verification_certificate(
                certificate,
                certificates,
                verifier_registry=verifier_registry,
                replayed=replayed_verification,
                active=set(),
            )
            replayed = True
        elif isinstance(certificate, TheoremCertificate):
            if certificate.claim_id != claim.id:
                raise ClaimVerificationError("theorem certificate is bound to a different claim")
            if certificate.statement_hash != claim.what.statement_hash:
                raise ClaimVerificationError("theorem certificate statement hash mismatch")
            if set(certificate.dependencies) != set(claim.dependency_ids):
                raise ClaimVerificationError(
                    "theorem certificate dependency IDs do not match the claim dependency graph"
                )
            for dependency in certificate.verification_certificates:
                supporting = certificates.get(dependency.certificate_id)
                if supporting is None:
                    raise ClaimVerificationError(
                        f"unresolved theorem certificate dependency: {dependency.certificate_id}"
                    )
                _validate_certificate_ref(dependency, supporting)
                if supporting.layer is not CertificateLayer.VERIFICATION:
                    raise ClaimVerificationError(
                        "theorem certificate dependency is not verification-layer evidence"
                    )
                if isinstance(supporting, VerificationCertificate):
                    _replay_verification_certificate(
                        supporting,
                        certificates,
                        verifier_registry=verifier_registry,
                        replayed=replayed_verification,
                        active=set(),
                    )
                else:
                    verify_certificate(supporting, registry=verifier_registry)
            verify_certificate(certificate, registry=verifier_registry)
            replayed = True
    if not replayed:
        raise ClaimVerificationError("no verification- or theorem-layer evidence was replayed")


def _validate_certificate_ref(reference: CertificateRef, certificate: Certificate) -> None:
    if certificate.certificate_id != reference.certificate_id:
        raise ClaimVerificationError("tampered certificate dependency")
    if certificate.layer is not reference.layer:
        raise ClaimVerificationError(
            f"certificate dependency layer mismatch for {reference.certificate_id}"
        )
    schema = getattr(certificate, "schema_version", None)
    if reference.schema_version is not None and schema != reference.schema_version:
        raise ClaimVerificationError(
            f"certificate dependency schema mismatch for {reference.certificate_id}"
        )
    integrity = getattr(certificate, "verify_integrity", None)
    if not callable(integrity):
        raise ClaimVerificationError(
            f"certificate dependency is not content-addressed: {reference.certificate_id}"
        )
    integrity(reference.certificate_id)


def _replay_verification_certificate(
    certificate: VerificationCertificate,
    certificates: Mapping[str, Certificate],
    *,
    verifier_registry: VerifierRegistry,
    replayed: set[str],
    active: set[str],
) -> None:
    certificate_id = certificate.certificate_id
    if certificate_id in replayed:
        return
    if certificate_id in active:
        raise ClaimVerificationError(
            f"verification certificate dependency cycle at {certificate_id}"
        )
    active.add(certificate_id)
    try:
        for reference in certificate.dependencies:
            supporting = certificates.get(reference.certificate_id)
            if supporting is None:
                raise ClaimVerificationError(
                    f"unresolved verification certificate dependency: {reference.certificate_id}"
                )
            _validate_certificate_ref(reference, supporting)
            if isinstance(supporting, VerificationCertificate):
                _replay_verification_certificate(
                    supporting,
                    certificates,
                    verifier_registry=verifier_registry,
                    replayed=replayed,
                    active=active,
                )
            else:
                verify_certificate(supporting, registry=verifier_registry)
        verify_certificate(certificate, registry=verifier_registry)
        replayed.add(certificate_id)
    finally:
        active.remove(certificate_id)


__all__ = [
    "Claim",
    "ClaimError",
    "ClaimKind",
    "ClaimRef",
    "ClaimVerificationError",
    "ClaimVerificationReport",
    "EvidenceKind",
    "EvidenceRef",
]
