"""Certified local-condition subspaces."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from arbogast.cert import VerificationCertificate, VerificationReport
from arbogast.core import CanonicalJSON, CanonicalObject
from arbogast.galois.proof import Completeness, ProofContext
from arbogast.linalg import DenseMatrix, LinearSubspace, nullspace

from ._support import (
    completeness_of,
    dimension_of,
    field_of,
    identity_of,
    place_of,
    subspace_of,
)
from .certificate import (
    ArithmeticError,
    ArithmeticReceipt,
    coerce_completeness,
    evidence_from_sources,
    verified_complete,
)
from .certificate import (
    proof_context as merge_proof_context,
)
from .semantic import ArithmeticSemanticResult


@dataclass(frozen=True, slots=True, init=False)
class LocalCondition(ArithmeticSemanticResult, CanonicalObject):
    """A pinned linear subspace of one certified local ``H^1`` space."""

    space: object
    subspace: LinearSubspace
    place: object
    proof_context: ProofContext
    _proving_certificates: tuple[VerificationCertificate, ...]
    _receipt: ArithmeticReceipt

    def __init__(
        self,
        space: object,
        basis: LinearSubspace | Iterable[Iterable[object]] = (),
        *,
        subspace: LinearSubspace | Iterable[Iterable[object]] | None = None,
        place: object | None = None,
        completeness: Completeness | str | None = None,
        assumptions: Sequence[str] = (),
        proof_context: ProofContext | None = None,
        proving_certificates: Sequence[VerificationCertificate] = (),
    ) -> None:
        if subspace is not None:
            if isinstance(basis, LinearSubspace) or tuple(basis):
                raise ArithmeticError("supply either basis or subspace, not both")
            basis = subspace
        local_subspace = subspace_of(space, basis)
        try:
            resolved_place = place_of(space, fallback=place)
        except ArithmeticError:
            if place is None:
                raise
            resolved_place = place
        if place is not None and identity_of(resolved_place, role="place") != identity_of(
            place, role="place"
        ):
            raise ArithmeticError("explicit place differs from the local space place")
        source_completeness = completeness_of(space)
        normalized_completeness = (
            source_completeness if completeness is None else coerce_completeness(completeness)
        )
        if normalized_completeness is Completeness.COMPLETE and (
            source_completeness is not Completeness.COMPLETE or not verified_complete(space)
        ):
            raise ArithmeticError(
                "a condition cannot be COMPLETE when its ambient local H1 space is not complete"
            )
        if proof_context is not None:
            if assumptions or completeness is not None:
                raise ArithmeticError(
                    "proof_context cannot be combined with separate assumptions/completeness"
                )
            if proof_context.completeness is Completeness.COMPLETE and (
                source_completeness is not Completeness.COMPLETE or not verified_complete(space)
            ):
                raise ArithmeticError("proof_context overstates local-space completeness")
            context = merge_proof_context(
                space,
                proof_context,
                completeness=proof_context.completeness,
            )
        else:
            context = merge_proof_context(
                space,
                completeness=normalized_completeness,
                assumptions=assumptions,
            )
        certificates = tuple(proving_certificates)
        if any(not isinstance(item, VerificationCertificate) for item in certificates):
            raise ArithmeticError(
                "proving_certificates must contain VerificationCertificate values"
            )
        evidence = evidence_from_sources(space, *certificates)
        payload = {
            "prime": local_subspace.field.p,
            "ambient_dimension": local_subspace.ambient_dimension,
            "basis": local_subspace.basis,
            "place_id": identity_of(resolved_place, role="place"),
            "space_id": identity_of(space, role="local-h1-space"),
            "input_evidence_ids": tuple(item.certificate_id for item in evidence),
        }
        receipt = ArithmeticReceipt.create(
            "local-condition",
            payload,
            context=context,
            evidence=evidence,
        )
        object.__setattr__(self, "space", space)
        object.__setattr__(self, "subspace", local_subspace)
        object.__setattr__(self, "place", resolved_place)
        object.__setattr__(self, "proof_context", context)
        object.__setattr__(self, "_proving_certificates", certificates)
        object.__setattr__(self, "_receipt", receipt)
        self.verify()

    @property
    def receipt(self) -> ArithmeticReceipt:
        return self._receipt

    @property
    def prime(self) -> int:
        return self.subspace.field.p

    @property
    def dimension(self) -> int:
        return self.subspace.dimension

    @property
    def ambient_dimension(self) -> int:
        return self.subspace.ambient_dimension

    @property
    def codimension(self) -> int:
        return self.ambient_dimension - self.dimension

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def quotient_matrix(self) -> DenseMatrix:
        """Return a canonical map whose kernel is exactly this condition."""

        return nullspace(self.subspace.basis_matrix).basis_matrix

    def contains(self, value: object) -> bool:
        coordinates = getattr(value, "coordinates", value)
        if isinstance(coordinates, (str, bytes)):
            return False
        try:
            return self.subspace.contains(coordinates)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    def verify(self) -> VerificationReport:
        if self.subspace.field != field_of(self.space):
            raise ArithmeticError("local condition uses a different coefficient field")
        if self.subspace.ambient_dimension != dimension_of(self.space):
            raise ArithmeticError("local condition has the wrong ambient dimension")
        payload = self.receipt.payload
        expected = {
            "prime": self.prime,
            "ambient_dimension": self.ambient_dimension,
            "basis": self.subspace.basis,
            "place_id": identity_of(self.place, role="place"),
            "space_id": identity_of(self.space, role="local-h1-space"),
            "input_evidence_ids": tuple(
                item.certificate_id
                for item in evidence_from_sources(
                    self.space,
                    *self._proving_certificates,
                )
            ),
        }
        if payload.to_dict() != {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in expected.items()
        }:
            # FrozenMap recursively thaws tuples, so compare canonical receipts
            # instead of relying on tuple/list identity.
            rebuilt = ArithmeticReceipt.create(
                "local-condition",
                expected,
                context=self.proof_context,
                evidence=evidence_from_sources(
                    self.space,
                    *self._proving_certificates,
                ),
            )
            if rebuilt != self.receipt:
                raise ArithmeticError("local-condition receipt is not bound to the object")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "proof_context": self.proof_context.to_canonical_data(),
            "receipt_id": self.receipt.certificate_id,
            "subspace": self.subspace.to_canonical_data(),
            "type": "arbogast.local_condition",
        }


def local_condition(
    space: object,
    basis: LinearSubspace | Iterable[Iterable[object]] = (),
    **kwargs: object,
) -> LocalCondition:
    """Construct and independently replay a certified local condition."""

    return LocalCondition(space, basis, **kwargs)  # type: ignore[arg-type]


__all__ = ["LocalCondition", "local_condition"]
