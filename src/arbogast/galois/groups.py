"""Pinned finite Galois quotients and canonical group-map re-exports."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from fractions import Fraction
from typing import ClassVar, cast

from arbogast.cert import (
    CertificateRef,
    CertificateVerificationError,
    VerificationCertificate,
    VerificationReport,
    content_address,
    freeze_mapping,
    verifier,
    verify_certificate,
)
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
    claim_boundary_hash,
)
from arbogast.core import CanonicalJSON, CanonicalObject, ValidationError
from arbogast.formats import (
    FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA,
    FrozenMapping,
)
from arbogast.rep import (
    FiniteGroupExtension,
    FiniteGroupMap,
    Permutation,
    PermutationGroup,
)

from .fields import NumberField
from .proof import ProofContext

FINITE_QUOTIENT_VERIFIER_ID = "galois.finite_quotient.v1"
GALOIS_QUOTIENT_PRESENTATION_VERIFIER_ID = "galois.quotient_presentation.v1"
_TRIVIAL_QUOTIENT_METHOD = "portable-trivial-quotient-v1"
_FINITE_QUOTIENT_CHECKS = (
    "base field canonical identity replayed",
    "finite group elements, generators, table, and inverses replayed",
    "trivial absolute-Galois quotient action replayed",
    "arithmetic presentation bound exactly",
)
_FINITE_QUOTIENT_GUARANTEES = (
    "The complete claim is limited to the canonical trivial Galois quotient.",
    "No nontrivial field extension or Galois realization is inferred.",
)
_QUOTIENT_PRESENTATION_CHECKS = (
    "base field and concrete finite group presentation bound",
    "candidate versus complete boundary replayed",
    "nested arithmetic quotient evidence bound when complete",
    "candidate presentation not promoted to arithmetic realization",
)
_QUOTIENT_PRESENTATION_GUARANTEES = (
    "A candidate certificate proves only the exact declared presentation.",
    "A complete claim remains dependent on its separately replayable quotient proof.",
)


def _label(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or normalized.strip() != normalized
        or any(ord(character) < 0x20 for character in normalized)
    ):
        raise ValidationError(f"{name} must be a nonempty, trimmed printable string")
    return normalized


def group_payload(group: PermutationGroup) -> dict[str, object]:
    """Return a complete concrete-group payload independent of generators."""

    if not isinstance(group, PermutationGroup):
        raise TypeError("finite arithmetic groups must be concrete PermutationGroup values")
    return {
        "degree": group.degree,
        "elements": [list(element.images) for element in group.elements],
        "fingerprint": group.fingerprint,
        "order": group.order,
        "type": "arbogast.finite_permutation_group",
    }


def _group_proof_payload(group: PermutationGroup) -> dict[str, object]:
    elements = group.elements
    lookup = {element: index for index, element in enumerate(elements)}
    return {
        **group_payload(group),
        "generators": [list(generator.images) for generator in group.generators],
        "identity_index": lookup[group.identity],
        "inverse_indices": [lookup[group.inverse(element)] for element in elements],
        "multiplication_table": [
            [lookup[group.multiply(left, right)] for right in elements] for left in elements
        ],
        "type": "arbogast.finite_permutation_group_proof/v1",
    }


@dataclass(frozen=True, slots=True, init=False)
class FiniteGaloisQuotientReceipt(CanonicalObject):
    """Portable v1 proof receipt for the bounded trivial-quotient case."""

    base_field_id: str
    base_field: FrozenMapping
    group: FrozenMapping
    label: str
    presentation: FrozenMapping
    arithmetic_witness: FrozenMapping

    schema_version: ClassVar[str] = FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA

    def __init__(
        self,
        base_field: NumberField,
        group: PermutationGroup,
        *,
        label: str,
        presentation: Mapping[str, object],
    ) -> None:
        if not isinstance(base_field, NumberField):
            raise TypeError("base_field must be a NumberField")
        if not isinstance(group, PermutationGroup):
            raise TypeError("group must be a concrete PermutationGroup")
        expected_presentation = {
            "arithmetic_action": "trivial",
            "method": _TRIVIAL_QUOTIENT_METHOD,
        }
        if dict(presentation) != expected_presentation:
            raise ValidationError(
                "portable complete quotient evidence supports only the exact trivial presentation"
            )
        if base_field.degree > 2 or not base_field.verify():
            raise ValidationError(
                "portable trivial-quotient evidence needs a portably verified degree <= 2 field"
            )
        if group.order != 1:
            raise ValidationError(
                "nontrivial finite Galois quotients need external arithmetic proving evidence"
            )
        object.__setattr__(self, "base_field_id", base_field.field_id)
        object.__setattr__(self, "base_field", FrozenMapping(base_field.to_dict()))
        object.__setattr__(self, "group", FrozenMapping(_group_proof_payload(group)))
        object.__setattr__(self, "label", _label(label, "Galois quotient label"))
        object.__setattr__(self, "presentation", FrozenMapping(expected_presentation))
        object.__setattr__(
            self,
            "arithmetic_witness",
            FrozenMapping(
                {
                    "homomorphism_image_indices": [0],
                    "method": _TRIVIAL_QUOTIENT_METHOD,
                    "surjective": True,
                }
            ),
        )

    @property
    def receipt_id(self) -> str:
        return self.content_id

    def verify(self) -> bool:
        _verify_portable_field_snapshot(self.base_field_id, self.base_field.to_dict())
        group = self.group.to_dict()
        if set(group) != {
            "degree",
            "elements",
            "fingerprint",
            "generators",
            "identity_index",
            "inverse_indices",
            "multiplication_table",
            "order",
            "type",
        }:
            raise ValidationError("finite-quotient group proof fields were altered")
        degree = group.get("degree")
        if isinstance(degree, bool) or not isinstance(degree, int) or degree < 0:
            raise ValidationError("finite-quotient group degree is invalid")
        reconstructed = PermutationGroup.trivial(degree)
        if group != _group_proof_payload(reconstructed):
            raise ValidationError("finite-quotient group is not the canonical trivial group")
        if self.presentation.to_dict() != {
            "arithmetic_action": "trivial",
            "method": _TRIVIAL_QUOTIENT_METHOD,
        }:
            raise ValidationError("finite-quotient arithmetic presentation was altered")
        if self.arithmetic_witness.to_dict() != {
            "homomorphism_image_indices": [0],
            "method": _TRIVIAL_QUOTIENT_METHOD,
            "surjective": True,
        }:
            raise ValidationError("finite-quotient arithmetic witness was altered")
        _label(self.label, "Galois quotient label")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "arithmetic_witness": self.arithmetic_witness.to_dict(),
                "base_field": self.base_field.to_dict(),
                "base_field_id": self.base_field_id,
                "group": self.group.to_dict(),
                "label": self.label,
                "presentation": self.presentation.to_dict(),
                "schema_version": self.schema_version,
                "type": "arbogast.finite_galois_quotient_receipt",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
    ) -> FiniteGaloisQuotientReceipt:
        """Decode and independently replay a serialized quotient receipt."""

        return _finite_quotient_receipt_from_dict(value)


def finite_galois_quotient_certificate(
    base_field: NumberField,
    group: PermutationGroup,
    *,
    label: str,
    presentation: Mapping[str, object],
) -> VerificationCertificate:
    """Certify the portable trivial quotient; fail closed for nontrivial claims."""

    receipt = FiniteGaloisQuotientReceipt(
        base_field,
        group,
        label=label,
        presentation=presentation,
    )
    return VerificationCertificate.create(
        subject=f"galois-quotient:{receipt.receipt_id}",
        verifier=FINITE_QUOTIENT_VERIFIER_ID,
        witness={"quotient_receipt": receipt.to_dict()},
        checks=_FINITE_QUOTIENT_CHECKS,
        guarantees=_FINITE_QUOTIENT_GUARANTEES,
    )


def _verify_portable_field_snapshot(field_id: str, snapshot: Mapping[str, object]) -> None:
    if content_address(snapshot) != field_id:
        raise ValidationError("finite-quotient field snapshot is not content-bound")
    if (
        set(snapshot)
        != {
            "defining_polynomial",
            "integral_basis",
            "irreducibility_requirement",
            "irreducibility_witness",
            "type",
        }
        or snapshot.get("type") != "arbogast.number_field"
    ):
        raise ValidationError("finite-quotient field snapshot has a foreign shape")
    if (
        snapshot.get("irreducibility_requirement") is not None
        or snapshot.get("irreducibility_witness") is not None
    ):
        raise ValidationError("portable quotient receipt contains external field metadata")
    polynomial = snapshot.get("defining_polynomial")
    basis = snapshot.get("integral_basis")
    if isinstance(polynomial, str | bytes) or not isinstance(polynomial, Sequence):
        raise ValidationError("finite-quotient field polynomial is malformed")
    if isinstance(basis, str | bytes) or not isinstance(basis, Sequence):
        raise ValidationError("finite-quotient integral basis is malformed")
    exact_basis: list[tuple[Fraction, ...]] = []
    for row in basis:
        if isinstance(row, str | bytes) or not isinstance(row, Sequence):
            raise ValidationError("finite-quotient integral-basis row is malformed")
        exact_row: list[Fraction] = []
        for pair in row:
            if (
                isinstance(pair, str | bytes)
                or not isinstance(pair, Sequence)
                or len(pair) != 2
                or isinstance(pair[0], bool)
                or not isinstance(pair[0], int)
                or isinstance(pair[1], bool)
                or not isinstance(pair[1], int)
                or pair[1] <= 0
            ):
                raise ValidationError("finite-quotient basis has a malformed rational")
            exact_row.append(Fraction(pair[0], pair[1]))
        exact_basis.append(tuple(exact_row))
    reconstructed = NumberField(
        tuple(cast(Sequence[int], polynomial)),
        integral_basis=tuple(exact_basis),
    )
    if reconstructed.field_id != field_id:
        raise ValidationError("finite-quotient field replay changed the field identity")


def _finite_quotient_receipt_from_dict(
    value: Mapping[str, object],
) -> FiniteGaloisQuotientReceipt:
    if set(value) != {
        "arithmetic_witness",
        "base_field",
        "base_field_id",
        "group",
        "label",
        "presentation",
        "schema_version",
        "type",
    }:
        raise ValidationError("finite-quotient receipt fields were altered")
    if (
        value.get("schema_version") != FiniteGaloisQuotientReceipt.schema_version
        or value.get("type") != "arbogast.finite_galois_quotient_receipt"
    ):
        raise ValidationError("finite-quotient receipt schema was altered")
    base_field_id = value.get("base_field_id")
    label = value.get("label")
    mappings = {
        name: value.get(name)
        for name in ("arithmetic_witness", "base_field", "group", "presentation")
    }
    if (
        not isinstance(base_field_id, str)
        or not isinstance(label, str)
        or any(not isinstance(item, Mapping) for item in mappings.values())
    ):
        raise ValidationError("finite-quotient receipt has malformed fields")
    receipt = object.__new__(FiniteGaloisQuotientReceipt)
    object.__setattr__(receipt, "base_field_id", base_field_id)
    object.__setattr__(
        receipt,
        "base_field",
        FrozenMapping(cast(Mapping[str, object], mappings["base_field"])),
    )
    object.__setattr__(
        receipt,
        "group",
        FrozenMapping(cast(Mapping[str, object], mappings["group"])),
    )
    object.__setattr__(receipt, "label", label)
    object.__setattr__(
        receipt,
        "presentation",
        FrozenMapping(cast(Mapping[str, object], mappings["presentation"])),
    )
    object.__setattr__(
        receipt,
        "arithmetic_witness",
        FrozenMapping(cast(Mapping[str, object], mappings["arithmetic_witness"])),
    )
    receipt.verify()
    return receipt


@verifier(FINITE_QUOTIENT_VERIFIER_ID, certificate_type=VerificationCertificate)
def _verify_finite_quotient_certificate(
    certificate: VerificationCertificate,
) -> VerificationReport:
    if certificate.verifier != FINITE_QUOTIENT_VERIFIER_ID:
        raise CertificateVerificationError("finite-quotient certificate names another verifier")
    witness = certificate.witness.to_dict()
    raw_receipt = witness.get("quotient_receipt")
    if set(witness) != {"quotient_receipt"} or not isinstance(raw_receipt, Mapping):
        raise CertificateVerificationError(
            "finite-quotient certificate must contain exactly one receipt"
        )
    try:
        receipt = _finite_quotient_receipt_from_dict(raw_receipt)
    except (TypeError, ValueError) as error:
        raise CertificateVerificationError(str(error)) from error
    if certificate.subject != f"galois-quotient:{receipt.receipt_id}":
        raise CertificateVerificationError("finite-quotient certificate subject was altered")
    if certificate.checks != _FINITE_QUOTIENT_CHECKS:
        raise CertificateVerificationError("finite-quotient certificate checks were altered")
    if certificate.guarantees != _FINITE_QUOTIENT_GUARANTEES:
        raise CertificateVerificationError("finite-quotient certificate guarantees were altered")
    if certificate.dependencies or certificate.claim_dependencies:
        raise CertificateVerificationError("finite-quotient certificate has foreign dependencies")
    return VerificationReport(
        valid=True,
        verifier=FINITE_QUOTIENT_VERIFIER_ID,
        certificate_id=certificate.certificate_id,
        checks=_FINITE_QUOTIENT_CHECKS,
        details=freeze_mapping(
            {
                "base_field_id": receipt.base_field_id,
                "quotient_receipt": receipt.receipt_id,
            }
        ),
    )


@dataclass(frozen=True, slots=True, init=False)
class FiniteGaloisQuotient(CanonicalObject):
    """A named concrete finite quotient through which a Galois action factors.

    The label and optional exact ``presentation`` are part of the identity:
    abstractly isomorphic quotients are never identified implicitly.
    """

    base_field: NumberField
    group: PermutationGroup
    label: str
    presentation: FrozenMapping
    proof_context: ProofContext
    quotient_certificate: VerificationCertificate | None = dataclass_field(
        compare=False,
        hash=False,
        repr=False,
    )

    def __init__(
        self,
        base_field: NumberField,
        group: PermutationGroup,
        *,
        label: str,
        presentation: Mapping[str, object] | None = None,
        proof_context: ProofContext | None = None,
        quotient_certificate: VerificationCertificate | None = None,
    ) -> None:
        if not isinstance(base_field, NumberField):
            raise TypeError("base_field must be a NumberField")
        if not isinstance(group, PermutationGroup):
            raise TypeError("group must be a concrete PermutationGroup")
        context = ProofContext() if proof_context is None else proof_context
        if not isinstance(context, ProofContext):
            raise TypeError("proof_context must be a ProofContext")
        if quotient_certificate is not None and not isinstance(
            quotient_certificate,
            VerificationCertificate,
        ):
            raise TypeError("quotient_certificate must be a VerificationCertificate")
        if context.complete and quotient_certificate is None:
            raise ValidationError(
                "a COMPLETE finite Galois quotient needs a nested proving certificate; "
                "a complete ProofContext is not evidence"
            )
        if not context.complete and quotient_certificate is not None:
            raise ValidationError(
                "quotient proving evidence must be paired with an explicit COMPLETE context"
            )
        object.__setattr__(self, "base_field", base_field)
        object.__setattr__(self, "group", group)
        object.__setattr__(self, "label", _label(label, "Galois quotient label"))
        object.__setattr__(self, "presentation", FrozenMapping(presentation))
        object.__setattr__(self, "proof_context", context)
        object.__setattr__(self, "quotient_certificate", quotient_certificate)
        if quotient_certificate is not None:
            self._validate_quotient_certificate(quotient_certificate)

    @property
    def quotient_id(self) -> str:
        return self.content_id

    @property
    def elements(self) -> tuple[Permutation, ...]:
        return self.group.elements

    @property
    def identity(self) -> Permutation:
        return self.group.identity

    @property
    def order(self) -> int:
        return self.group.order

    def multiply(self, left: Permutation, right: Permutation) -> Permutation:
        return self.group.multiply(left, right)

    def inverse(self, element: Permutation) -> Permutation:
        return self.group.inverse(element)

    @property
    def proving_certificate(self) -> VerificationCertificate | None:
        """Return nested realization evidence, absent for a candidate quotient."""

        return self.quotient_certificate

    @property
    def certificate(self) -> VerificationCertificate:
        """Certify this result with its candidate/complete boundary explicit."""

        snapshot = self.to_dict()
        statement = _quotient_statement(snapshot, self.quotient_id)
        claim_id = _quotient_claim_id(self.quotient_id)
        status = _quotient_status(snapshot)
        proving = self.quotient_certificate
        return VerificationCertificate.create(
            subject=f"galois-quotient-presentation:{self.quotient_id}",
            verifier=GALOIS_QUOTIENT_PRESENTATION_VERIFIER_ID,
            claim_id=claim_id,
            statement_hash=statement.statement_hash,
            claim_boundary_hash=claim_boundary_hash(
                claim_id,
                statement,
                kind=ClaimKind.COMPUTED,
                status=status,
                hypotheses=_quotient_hypotheses(snapshot),
            ),
            witness={
                "proving_certificate_id": (None if proving is None else proving.certificate_id),
                "quotient": snapshot,
                "quotient_id": self.quotient_id,
                "schema": "arbogast.galois.quotient-presentation-witness/v1",
            },
            checks=_QUOTIENT_PRESENTATION_CHECKS,
            dependencies=(() if proving is None else (CertificateRef.from_certificate(proving),)),
            guarantees=_QUOTIENT_PRESENTATION_GUARANTEES,
        )

    def claim(self) -> Claim:
        snapshot = self.to_dict()
        certificate = self.certificate
        proving = self.proving_certificate
        return Claim(
            _quotient_claim_id(self.quotient_id),
            statement=_quotient_statement(snapshot, self.quotient_id),
            kind=ClaimKind.COMPUTED,
            status=_quotient_status(snapshot),
            hypotheses=_quotient_hypotheses(snapshot),
            how=Derivation.computation(
                "galois.finite_galois_quotient",
                method="Replay of the exact finite presentation and its evidence boundary",
                inputs=(self.base_field.field_id, self.group.fingerprint),
                artifact=certificate.certificate_id,
            ),
            certificate=certificate,
            supporting_certificates=(() if proving is None else (proving,)),
            metadata={
                "arithmetic_realization_claimed": self.proof_context.complete,
                "quotient_completeness": self.proof_context.completeness.value,
            },
        )

    def claim_graph(self) -> ClaimGraph:
        return ClaimGraph((self.claim(),))

    def _validate_quotient_certificate(
        self,
        certificate: VerificationCertificate,
    ) -> None:
        if certificate.verifier != FINITE_QUOTIENT_VERIFIER_ID:
            raise ValidationError(
                "this release accepts only the portable finite-quotient receipt verifier"
            )
        report = verify_certificate(certificate).require_valid()
        if report.certificate_id != certificate.certificate_id:
            raise ValidationError("Galois-quotient proof report names a different certificate")
        witness = certificate.witness.to_dict()
        raw_receipt = witness.get("quotient_receipt")
        if set(witness) != {"quotient_receipt"} or not isinstance(raw_receipt, Mapping):
            raise ValidationError("Galois-quotient certificate omits its exact receipt")
        receipt = _finite_quotient_receipt_from_dict(raw_receipt)
        if (
            receipt.base_field_id != self.base_field.field_id
            or receipt.base_field.to_dict() != self.base_field.to_dict()
            or receipt.group.to_dict() != _group_proof_payload(self.group)
            or receipt.label != self.label
            or receipt.presentation.to_dict() != self.presentation.to_dict()
        ):
            raise ValidationError(
                "Galois-quotient certificate is not bound to the exact field, "
                "group, and presentation"
            )
        if certificate.subject != f"galois-quotient:{receipt.receipt_id}":
            raise ValidationError("Galois-quotient certificate subject is not payload-bound")

    def verify(self) -> bool:
        if not self.base_field.verify() or not self.group.generation_certificate().verify():
            return False
        structurally_valid = (
            FiniteGaloisQuotient(
                self.base_field,
                self.group,
                label=self.label,
                presentation=self.presentation.to_dict(),
                proof_context=self.proof_context,
                quotient_certificate=self.quotient_certificate,
            )
            == self
        )
        return structurally_valid and verify_certificate(self.certificate).valid

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "base_field_id": self.base_field.field_id,
                "group": group_payload(self.group),
                "label": self.label,
                "presentation": self.presentation.to_dict(),
                "proof_context": self.proof_context.to_canonical_data(),
                "type": "arbogast.finite_galois_quotient",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())


def finite_galois_quotient(
    base_field: NumberField,
    group: PermutationGroup,
    *,
    label: str,
    presentation: Mapping[str, object] | None = None,
    proof_context: ProofContext | None = None,
    quotient_certificate: VerificationCertificate | None = None,
) -> FiniteGaloisQuotient:
    """Construct a pinned finite Galois quotient without implicit identifications."""

    return FiniteGaloisQuotient(
        base_field,
        group,
        label=label,
        presentation=presentation,
        proof_context=proof_context,
        quotient_certificate=quotient_certificate,
    )


def _verify_quotient_snapshot(snapshot: Mapping[str, object], quotient_id: str) -> str:
    if content_address(snapshot) != quotient_id:
        raise ValidationError("finite-quotient presentation is not content-bound")
    if (
        set(snapshot)
        != {
            "base_field_id",
            "group",
            "label",
            "presentation",
            "proof_context",
            "type",
        }
        or snapshot.get("type") != "arbogast.finite_galois_quotient"
    ):
        raise ValidationError("finite-quotient presentation has a foreign shape")
    if not isinstance(snapshot.get("base_field_id"), str):
        raise ValidationError("finite-quotient presentation omits its base field")
    _label(snapshot.get("label"), "Galois quotient label")
    if not isinstance(snapshot.get("presentation"), Mapping):
        raise ValidationError("finite-quotient arithmetic presentation is malformed")
    raw_group = snapshot.get("group")
    if not isinstance(raw_group, Mapping) or set(raw_group) != {
        "degree",
        "elements",
        "fingerprint",
        "order",
        "type",
    }:
        raise ValidationError("finite-quotient concrete group snapshot is malformed")
    degree = raw_group.get("degree")
    raw_elements = raw_group.get("elements")
    if (
        isinstance(degree, bool)
        or not isinstance(degree, int)
        or degree < 0
        or isinstance(raw_elements, str | bytes)
        or not isinstance(raw_elements, Sequence)
    ):
        raise ValidationError("finite-quotient concrete group data is invalid")
    try:
        elements = tuple(Permutation(cast(Sequence[int], item)) for item in raw_elements)
    except (TypeError, ValueError) as error:
        raise ValidationError("finite-quotient group has a malformed permutation") from error
    reconstructed = PermutationGroup(elements, degree=degree)
    if group_payload(reconstructed) != dict(raw_group):
        raise ValidationError("finite-quotient group is not completely enumerated")
    context = snapshot.get("proof_context")
    if (
        not isinstance(context, Mapping)
        or set(context)
        != {
            "assumptions",
            "completeness",
            "type",
            "verification_requirements",
        }
        or context.get("type") != "arbogast.proof_context"
    ):
        raise ValidationError("finite-quotient proof context is malformed")
    completeness = context.get("completeness")
    if completeness not in {"candidate", "complete"}:
        raise ValidationError("finite-quotient completeness is invalid")
    assumptions = context.get("assumptions")
    requirements = context.get("verification_requirements")
    if (
        isinstance(assumptions, str | bytes)
        or not isinstance(assumptions, Sequence)
        or any(not isinstance(item, str) or not item for item in assumptions)
        or isinstance(requirements, str | bytes)
        or not isinstance(requirements, Sequence)
    ):
        raise ValidationError("finite-quotient proof axes are malformed")
    return cast(str, completeness)


def _quotient_claim_id(quotient_id: str) -> str:
    return f"galois.quotient.{quotient_id.split(':', 1)[1]}"


def _quotient_hypotheses(snapshot: Mapping[str, object]) -> tuple[FormalStatement, ...]:
    context = cast(Mapping[str, object], snapshot["proof_context"])
    assumptions = cast(Sequence[str], context["assumptions"])
    return tuple(FormalStatement(f"Assumption: {item}.") for item in assumptions)


def _quotient_status(snapshot: Mapping[str, object]) -> EpistemicStatus:
    context = cast(Mapping[str, object], snapshot["proof_context"])
    if context["completeness"] != "complete":
        return EpistemicStatus.UNKNOWN
    if cast(Sequence[object], context["assumptions"]):
        return EpistemicStatus.CONDITIONAL
    return EpistemicStatus.EXACT


def _quotient_statement(
    snapshot: Mapping[str, object],
    quotient_id: str,
) -> FormalStatement:
    context = cast(Mapping[str, object], snapshot["proof_context"])
    complete = context["completeness"] == "complete"
    if complete:
        text = (
            f"The exact declared finite presentation {quotient_id} is realized as the stated "
            "finite Galois quotient, subject to its nested proving certificate."
        )
    else:
        text = (
            f"The exact finite presentation {quotient_id} is a candidate quotient only; no "
            "arithmetic realization as a Galois quotient is claimed."
        )
    return FormalStatement.create(
        text,
        parameters={
            "arithmetic_realization_claimed": complete,
            "base_field_id": snapshot["base_field_id"],
            "group": snapshot["group"],
            "presentation": snapshot["presentation"],
            "quotient_completeness": context["completeness"],
            "quotient_id": quotient_id,
        },
    )


@verifier(
    GALOIS_QUOTIENT_PRESENTATION_VERIFIER_ID,
    certificate_type=VerificationCertificate,
)
def _verify_quotient_presentation_certificate(
    certificate: VerificationCertificate,
) -> VerificationReport:
    if certificate.verifier != GALOIS_QUOTIENT_PRESENTATION_VERIFIER_ID:
        raise CertificateVerificationError("quotient certificate names another verifier")
    witness = certificate.witness.to_dict()
    if (
        set(witness)
        != {
            "proving_certificate_id",
            "quotient",
            "quotient_id",
            "schema",
        }
        or witness.get("schema") != "arbogast.galois.quotient-presentation-witness/v1"
    ):
        raise CertificateVerificationError("quotient certificate witness was altered")
    snapshot = witness.get("quotient")
    quotient_id = witness.get("quotient_id")
    if not isinstance(snapshot, Mapping) or not isinstance(quotient_id, str):
        raise CertificateVerificationError("quotient certificate payload is malformed")
    try:
        completeness = _verify_quotient_snapshot(snapshot, quotient_id)
    except (TypeError, ValueError) as error:
        raise CertificateVerificationError(str(error)) from error
    proving_id = witness.get("proving_certificate_id")
    if completeness == "candidate":
        if proving_id is not None or certificate.dependencies:
            raise CertificateVerificationError("candidate quotient has foreign proving evidence")
    else:
        if not isinstance(proving_id, str) or len(certificate.dependencies) != 1:
            raise CertificateVerificationError("complete quotient is missing proving evidence")
        if certificate.dependencies[0].certificate_id != proving_id:
            raise CertificateVerificationError("complete quotient proving evidence was rebound")
    statement = _quotient_statement(snapshot, quotient_id)
    claim_id = _quotient_claim_id(quotient_id)
    status = _quotient_status(snapshot)
    if certificate.subject != f"galois-quotient-presentation:{quotient_id}":
        raise CertificateVerificationError("quotient certificate subject binding was altered")
    if certificate.claim_id != claim_id or certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError("quotient certificate claim binding was altered")
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=status,
        hypotheses=_quotient_hypotheses(snapshot),
    )
    if certificate.claim_boundary_hash != expected_boundary:
        raise CertificateVerificationError("quotient certificate claim boundary was altered")
    if certificate.claim_dependencies:
        raise CertificateVerificationError("quotient certificate has foreign claim dependencies")
    if certificate.checks != _QUOTIENT_PRESENTATION_CHECKS:
        raise CertificateVerificationError("quotient certificate checks were altered")
    if certificate.guarantees != _QUOTIENT_PRESENTATION_GUARANTEES:
        raise CertificateVerificationError("quotient certificate guarantees were altered")
    return VerificationReport(
        valid=True,
        verifier=GALOIS_QUOTIENT_PRESENTATION_VERIFIER_ID,
        certificate_id=certificate.certificate_id,
        checks=_QUOTIENT_PRESENTATION_CHECKS,
        details=freeze_mapping(
            {
                "arithmetic_realization_claimed": completeness == "complete",
                "quotient_id": quotient_id,
            }
        ),
    )


__all__ = [
    "FINITE_QUOTIENT_VERIFIER_ID",
    "GALOIS_QUOTIENT_PRESENTATION_VERIFIER_ID",
    "FiniteGaloisQuotient",
    "FiniteGaloisQuotientReceipt",
    "FiniteGroupExtension",
    "FiniteGroupMap",
    "finite_galois_quotient_certificate",
    "group_payload",
]
