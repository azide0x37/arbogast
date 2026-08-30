"""Finite prime-field modules for pinned finite Galois quotients."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, ClassVar, cast

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
from arbogast.formats import GALOIS_MODULE_RECEIPT_SCHEMA, FrozenMapping
from arbogast.linalg import DenseMatrix, PrimeField
from arbogast.rep import Permutation, PermutationGroup, Representation
from arbogast.rep.representation import MatrixInput

from .groups import FiniteGaloisQuotient

GALOIS_MODULE_VERIFIER_ID = "galois.module.v1"
_GALOIS_MODULE_CHECKS = (
    "quotient snapshot and canonical identity bound",
    "complete concrete group multiplication replayed",
    "prime-field action matrices replayed",
    "identity and multiplication action laws checked",
)
_GALOIS_MODULE_GUARANTEES = (
    "The matrices form the exact declared prime-field representation.",
    "A candidate quotient is not promoted to a genuine complete Galois quotient.",
)


def _optional_name(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("module name must be a string or None")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or normalized.strip() != normalized
        or any(ord(character) < 0x20 for character in normalized)
    ):
        raise ValidationError("module name must be a nonempty, trimmed printable string")
    return normalized


@dataclass(frozen=True, slots=True, init=False)
class GaloisModuleReceipt(CanonicalObject):
    """Independently replayable finite-action receipt for a Galois module."""

    quotient_id: str
    quotient: FrozenMapping
    module_id: str
    module: FrozenMapping
    quotient_certificate_id: str | None

    schema_version: ClassVar[str] = GALOIS_MODULE_RECEIPT_SCHEMA

    def __init__(self, module: GaloisModule) -> None:
        if not isinstance(module, GaloisModule):
            raise TypeError("module receipt requires a GaloisModule")
        quotient_certificate = module.quotient.certificate
        object.__setattr__(self, "quotient_id", module.quotient.quotient_id)
        object.__setattr__(self, "quotient", FrozenMapping(module.quotient.to_dict()))
        object.__setattr__(self, "module_id", module.module_id)
        object.__setattr__(self, "module", FrozenMapping(module.to_dict()))
        object.__setattr__(
            self,
            "quotient_certificate_id",
            (quotient_certificate.certificate_id if quotient_certificate is not None else None),
        )
        self.verify()

    @property
    def receipt_id(self) -> str:
        return self.content_id

    def verify(self) -> bool:
        quotient = self.quotient.to_dict()
        module = self.module.to_dict()
        if content_address(quotient) != self.quotient_id:
            raise ValidationError("Galois-module quotient snapshot is not content-bound")
        if content_address(module) != self.module_id:
            raise ValidationError("Galois-module action snapshot is not content-bound")
        _verify_module_snapshots(quotient, module)
        proof_context = quotient.get("proof_context")
        if not isinstance(proof_context, Mapping):
            raise ValidationError("Galois-module quotient omits its proof context")
        if proof_context.get("completeness") not in {"candidate", "complete"}:
            raise ValidationError("Galois-module quotient completeness is invalid")
        if self.quotient_certificate_id is None:
            raise ValidationError("Galois-module receipt omits its quotient result certificate")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "module": self.module.to_dict(),
                "module_id": self.module_id,
                "quotient": self.quotient.to_dict(),
                "quotient_certificate_id": self.quotient_certificate_id,
                "quotient_id": self.quotient_id,
                "schema_version": self.schema_version,
                "type": "arbogast.galois_module_receipt",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> GaloisModuleReceipt:
        return _module_receipt_from_dict(value)


def _verify_module_snapshots(
    quotient: Mapping[str, object],
    module: Mapping[str, object],
) -> None:
    if (
        set(quotient)
        != {
            "base_field_id",
            "group",
            "label",
            "presentation",
            "proof_context",
            "type",
        }
        or quotient.get("type") != "arbogast.finite_galois_quotient"
    ):
        raise ValidationError("Galois-module quotient snapshot has a foreign shape")
    if (
        set(module)
        != {
            "action_convention",
            "action_matrices",
            "dimension",
            "prime",
            "quotient_id",
            "type",
        }
        or module.get("type") != "arbogast.galois_module"
    ):
        raise ValidationError("Galois-module action snapshot has a foreign shape")
    if module.get("quotient_id") != content_address(quotient):
        raise ValidationError("Galois-module action is bound to a different quotient")
    if module.get("action_convention") != Representation.ACTION_CONVENTION:
        raise ValidationError("Galois-module action convention was altered")
    prime = module.get("prime")
    dimension = module.get("dimension")
    if (
        isinstance(prime, bool)
        or not isinstance(prime, int)
        or isinstance(dimension, bool)
        or not isinstance(dimension, int)
        or dimension < 0
    ):
        raise ValidationError("Galois-module field or dimension is invalid")
    field = PrimeField(prime)
    raw_group = quotient.get("group")
    if not isinstance(raw_group, Mapping) or set(raw_group) != {
        "degree",
        "elements",
        "fingerprint",
        "order",
        "type",
    }:
        raise ValidationError("Galois-module concrete group snapshot is malformed")
    degree = raw_group.get("degree")
    raw_elements = raw_group.get("elements")
    if (
        isinstance(degree, bool)
        or not isinstance(degree, int)
        or degree < 0
        or isinstance(raw_elements, str | bytes)
        or not isinstance(raw_elements, Sequence)
    ):
        raise ValidationError("Galois-module concrete group data is invalid")
    try:
        elements = tuple(Permutation(cast(Sequence[int], item)) for item in raw_elements)
    except (TypeError, ValueError) as error:
        raise ValidationError("Galois-module group contains a malformed permutation") from error
    if any(element.degree != degree for element in elements) or len(set(elements)) != len(elements):
        raise ValidationError("Galois-module group permutations have inconsistent degrees")
    reconstructed = PermutationGroup(elements, degree=degree)
    if (
        reconstructed.elements != elements
        or raw_group.get("order") != reconstructed.order
        or raw_group.get("fingerprint") != reconstructed.fingerprint
    ):
        raise ValidationError("Galois-module group is not a complete concrete group")
    raw_matrices = module.get("action_matrices")
    if isinstance(raw_matrices, str | bytes) or not isinstance(raw_matrices, Sequence):
        raise ValidationError("Galois-module action matrix list is malformed")
    matrices: list[DenseMatrix] = []
    for raw_matrix in raw_matrices:
        if isinstance(raw_matrix, str | bytes) or not isinstance(raw_matrix, Sequence):
            raise ValidationError("Galois-module action matrix is malformed")
        rows: list[tuple[int, ...]] = []
        for raw_row in raw_matrix:
            if isinstance(raw_row, str | bytes) or not isinstance(raw_row, Sequence):
                raise ValidationError("Galois-module action row is malformed")
            row = tuple(raw_row)
            if len(row) != dimension or any(
                isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < prime
                for value in row
            ):
                raise ValidationError("Galois-module action entry is not canonical")
            rows.append(cast(tuple[int, ...], row))
        if len(rows) != dimension:
            raise ValidationError("Galois-module action matrix has the wrong dimension")
        matrices.append(DenseMatrix(field, rows, ncols=dimension))
    if len(matrices) != len(elements):
        raise ValidationError("Galois-module action does not cover every group element")
    lookup = {element: index for index, element in enumerate(elements)}
    identity_index = lookup.get(reconstructed.identity)
    if identity_index is None or matrices[identity_index] != DenseMatrix.identity(field, dimension):
        raise ValidationError("Galois-module identity does not act identically")
    for left_index, left in enumerate(elements):
        for right_index, right in enumerate(elements):
            product_index = lookup.get(left * right)
            if product_index is None or (
                matrices[left_index] @ matrices[right_index] != matrices[product_index]
            ):
                raise ValidationError("Galois-module action does not preserve multiplication")


def _module_receipt_from_dict(value: Mapping[str, object]) -> GaloisModuleReceipt:
    if set(value) != {
        "module",
        "module_id",
        "quotient",
        "quotient_certificate_id",
        "quotient_id",
        "schema_version",
        "type",
    }:
        raise ValidationError("Galois-module receipt fields were altered")
    if (
        value.get("schema_version") != GaloisModuleReceipt.schema_version
        or value.get("type") != "arbogast.galois_module_receipt"
    ):
        raise ValidationError("Galois-module receipt schema was altered")
    quotient = value.get("quotient")
    module = value.get("module")
    quotient_id = value.get("quotient_id")
    module_id = value.get("module_id")
    quotient_certificate_id = value.get("quotient_certificate_id")
    if (
        not isinstance(quotient, Mapping)
        or not isinstance(module, Mapping)
        or not isinstance(quotient_id, str)
        or not isinstance(module_id, str)
        or (quotient_certificate_id is not None and not isinstance(quotient_certificate_id, str))
    ):
        raise ValidationError("Galois-module receipt contains malformed fields")
    receipt = object.__new__(GaloisModuleReceipt)
    object.__setattr__(receipt, "quotient_id", quotient_id)
    object.__setattr__(receipt, "quotient", FrozenMapping(quotient))
    object.__setattr__(receipt, "module_id", module_id)
    object.__setattr__(receipt, "module", FrozenMapping(module))
    object.__setattr__(receipt, "quotient_certificate_id", quotient_certificate_id)
    receipt.verify()
    return receipt


@dataclass(frozen=True, slots=True, init=False)
class GaloisModule(CanonicalObject):
    """A fully enumerated prime-field action of a finite Galois quotient."""

    quotient: FiniteGaloisQuotient
    representation: Representation
    name: str | None = dataclass_field(compare=False, hash=False)

    def __init__(
        self,
        quotient: FiniteGaloisQuotient,
        representation: Representation,
        *,
        name: str | None = None,
    ) -> None:
        if not isinstance(quotient, FiniteGaloisQuotient):
            raise TypeError("quotient must be a FiniteGaloisQuotient")
        if not isinstance(representation, Representation):
            raise TypeError("representation must be an exact finite Representation")
        if representation.group != quotient.group:
            raise ValidationError(
                "Galois module representation uses a different concrete quotient group"
            )
        if tuple(representation.elements) != quotient.group.elements:
            raise ValidationError(
                "Galois module action order does not match the canonical quotient elements"
            )
        representation.validate()
        object.__setattr__(self, "quotient", quotient)
        object.__setattr__(self, "representation", representation)
        object.__setattr__(self, "name", _optional_name(name or representation.name))

    @property
    def module_id(self) -> str:
        return self.content_id

    @property
    def group(self) -> PermutationGroup:
        return self.quotient.group

    @property
    def field(self) -> PrimeField:
        return self.representation.field

    @property
    def prime(self) -> int:
        return self.field.p

    @property
    def dimension(self) -> int:
        return self.representation.dimension

    @property
    def elements(self) -> tuple[Permutation, ...]:
        return self.quotient.group.elements

    @property
    def matrices(self) -> Mapping[Any, DenseMatrix]:
        return self.representation.matrices

    def action_matrix(self, element: Permutation) -> DenseMatrix:
        return self.representation.action_matrix(element)

    def action(self, element: Permutation) -> DenseMatrix:
        return self.action_matrix(element)

    def matrix(self, element: Permutation) -> DenseMatrix:
        return self.action_matrix(element)

    def apply(self, element: Permutation, vector: tuple[int, ...]) -> tuple[int, ...]:
        return self.representation.apply(element, vector)

    def verify(self) -> bool:
        if not self.quotient.verify():
            return False
        validation = self.representation.validate()
        structurally_valid = (
            validation.group_order == self.quotient.group.order
            and validation.dimension == self.dimension
            and validation.multiplication_checks == self.quotient.group.order**2
        )
        return structurally_valid and verify_certificate(self.certificate).valid

    @property
    def receipt(self) -> GaloisModuleReceipt:
        return GaloisModuleReceipt(self)

    @property
    def certificate(self) -> VerificationCertificate:
        receipt = self.receipt
        statement = _module_statement(receipt)
        claim_id = _module_claim_id(receipt)
        quotient_certificate = self.quotient.certificate
        return VerificationCertificate.create(
            subject=f"galois-module:{receipt.receipt_id}",
            verifier=GALOIS_MODULE_VERIFIER_ID,
            claim_id=claim_id,
            statement_hash=statement.statement_hash,
            claim_boundary_hash=claim_boundary_hash(
                claim_id,
                statement,
                kind=ClaimKind.COMPUTED,
                status=EpistemicStatus.EXACT,
            ),
            witness={"module_receipt": receipt.to_dict()},
            checks=_GALOIS_MODULE_CHECKS,
            dependencies=(
                ()
                if quotient_certificate is None
                else (CertificateRef.from_certificate(quotient_certificate),)
            ),
            guarantees=_GALOIS_MODULE_GUARANTEES,
        )

    @property
    def dependency_certificates(self) -> tuple[VerificationCertificate, ...]:
        """Return the concrete quotient proof chain required by this module."""

        quotient_certificate = self.quotient.certificate
        proving = self.quotient.proving_certificate
        return (quotient_certificate,) if proving is None else (quotient_certificate, proving)

    def claim(self) -> Claim:
        receipt = self.receipt
        certificate = self.certificate
        return Claim(
            _module_claim_id(receipt),
            statement=_module_statement(receipt),
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
            how=Derivation.computation(
                "galois.galois_module",
                method="Independent replay of every finite-group action matrix",
                inputs=(self.quotient.quotient_id, self.module_id),
                artifact=certificate.certificate_id,
            ),
            certificate=certificate,
            supporting_certificates=self.dependency_certificates,
            metadata={
                "module_receipt": receipt.receipt_id,
                "quotient_completeness": self.quotient.proof_context.completeness.value,
                "structural_only_if_quotient_candidate": True,
            },
        )

    def claim_graph(self) -> ClaimGraph:
        return ClaimGraph((self.claim(),))

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "action_convention": Representation.ACTION_CONVENTION,
                "action_matrices": [
                    [list(row) for row in self.action_matrix(element).rows]
                    for element in self.elements
                ],
                "dimension": self.dimension,
                "prime": self.prime,
                "quotient_id": self.quotient.quotient_id,
                "type": "arbogast.galois_module",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())


def _module_claim_id(receipt: GaloisModuleReceipt) -> str:
    return f"galois.module.{receipt.receipt_id.split(':', 1)[1]}"


def _module_statement(receipt: GaloisModuleReceipt) -> FormalStatement:
    quotient = receipt.quotient.to_dict()
    proof_context = cast(Mapping[str, object], quotient["proof_context"])
    completeness = cast(str, proof_context["completeness"])
    qualifier = (
        "the certified finite Galois quotient"
        if completeness == "complete"
        else "the declared candidate finite quotient"
    )
    return FormalStatement.create(
        f"The displayed prime-field matrices form an exact action of {qualifier} "
        f"{receipt.quotient_id}; candidate quotient data is not promoted.",
        parameters={
            "module_id": receipt.module_id,
            "module_receipt": receipt.receipt_id,
            "quotient_completeness": completeness,
            "quotient_id": receipt.quotient_id,
        },
    )


@verifier(GALOIS_MODULE_VERIFIER_ID, certificate_type=VerificationCertificate)
def _verify_galois_module_certificate(
    certificate: VerificationCertificate,
) -> VerificationReport:
    if certificate.verifier != GALOIS_MODULE_VERIFIER_ID:
        raise CertificateVerificationError("Galois-module certificate names another verifier")
    witness = certificate.witness.to_dict()
    raw_receipt = witness.get("module_receipt")
    if set(witness) != {"module_receipt"} or not isinstance(raw_receipt, Mapping):
        raise CertificateVerificationError(
            "Galois-module certificate must contain exactly one module receipt"
        )
    try:
        receipt = GaloisModuleReceipt.from_dict(raw_receipt)
    except (TypeError, ValueError) as error:
        raise CertificateVerificationError(str(error)) from error
    statement = _module_statement(receipt)
    claim_id = _module_claim_id(receipt)
    if certificate.subject != f"galois-module:{receipt.receipt_id}":
        raise CertificateVerificationError("Galois-module certificate subject was altered")
    if certificate.claim_id != claim_id or certificate.statement_hash != statement.statement_hash:
        raise CertificateVerificationError("Galois-module certificate claim binding was altered")
    expected_boundary = claim_boundary_hash(
        claim_id,
        statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
    )
    if certificate.claim_boundary_hash != expected_boundary:
        raise CertificateVerificationError("Galois-module claim boundary was altered")
    expected_dependencies: tuple[CertificateRef, ...]
    if receipt.quotient_certificate_id is None or len(certificate.dependencies) != 1:
        raise CertificateVerificationError("Galois-module quotient evidence is missing")
    dependency = certificate.dependencies[0]
    if dependency.certificate_id != receipt.quotient_certificate_id:
        raise CertificateVerificationError("Galois-module quotient evidence was rebound")
    expected_dependencies = (dependency,)
    if certificate.dependencies != expected_dependencies or certificate.claim_dependencies:
        raise CertificateVerificationError("Galois-module certificate dependencies were altered")
    if certificate.checks != _GALOIS_MODULE_CHECKS:
        raise CertificateVerificationError("Galois-module certificate checks were altered")
    if certificate.guarantees != _GALOIS_MODULE_GUARANTEES:
        raise CertificateVerificationError("Galois-module certificate guarantees were altered")
    return VerificationReport(
        valid=True,
        verifier=GALOIS_MODULE_VERIFIER_ID,
        certificate_id=certificate.certificate_id,
        checks=_GALOIS_MODULE_CHECKS,
        details=freeze_mapping(
            {
                "module_id": receipt.module_id,
                "module_receipt": receipt.receipt_id,
                "quotient_id": receipt.quotient_id,
            }
        ),
    )


def galois_module(
    quotient: FiniteGaloisQuotient,
    representation_or_field: Representation | PrimeField | int,
    action: Mapping[Any, MatrixInput] | Callable[[Any], MatrixInput] | None = None,
    *,
    matrices: Mapping[Any, MatrixInput] | None = None,
    dimension: int | None = None,
    validate: bool = True,
    name: str | None = None,
) -> GaloisModule:
    """Construct a :class:`GaloisModule` from a representation or raw action."""

    if isinstance(representation_or_field, Representation):
        if action is not None or matrices is not None or dimension is not None:
            raise TypeError("raw action arguments cannot accompany an existing Representation")
        representation = representation_or_field
    else:
        source = matrices if matrices is not None else action
        if source is None:
            raise TypeError("a matrix mapping or action callable is required")
        if action is not None and matrices is not None:
            raise TypeError("provide action matrices through either action or matrices")
        representation = Representation(
            quotient.group,
            representation_or_field,
            source,
            dimension=dimension,
            validate=validate,
            name=name,
        )
    return GaloisModule(quotient, representation, name=name)


__all__ = [
    "GALOIS_MODULE_VERIFIER_ID",
    "GaloisModule",
    "GaloisModuleReceipt",
    "galois_module",
]
