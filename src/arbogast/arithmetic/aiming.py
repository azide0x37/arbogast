"""Cocycle aiming as a proof-carrying finite linear problem."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from arbogast.cert import VerificationCertificate, VerificationReport
from arbogast.core import CanonicalJSON, CanonicalObject
from arbogast.galois.proof import Completeness, ProofContext
from arbogast.linalg import DenseMatrix, LinearSubspace, Scalar, solve

from ._support import completeness_of, coordinates_of, matrix_of
from .certificate import (
    ArithmeticError,
    ArithmeticReceipt,
    evidence_from_sources,
    matrix_payload,
)
from .certificate import (
    proof_context as merge_proof_context,
)
from .semantic import ArithmeticSemanticResult


def _aim_matrix(value: object) -> DenseMatrix:
    assembled = getattr(value, "global_to_local_quotient", None)
    return matrix_of(assembled if assembled is not None else value)


def _aim_context(value: object, assumptions: Sequence[str]) -> ProofContext:
    completeness = completeness_of(value, default=Completeness.CANDIDATE)
    return merge_proof_context(
        value,
        completeness=completeness,
        assumptions=assumptions,
    )


@dataclass(frozen=True, slots=True, init=False)
class AffineFamily(ArithmeticSemanticResult, CanonicalObject):
    """A checked representative plus the complete homogeneous solution space."""

    matrix: DenseMatrix
    target: tuple[int, ...]
    representative: tuple[int, ...]
    kernel: LinearSubspace
    proof_context: ProofContext
    domain_space: object | None
    _receipt: ArithmeticReceipt

    def __init__(
        self,
        matrix: DenseMatrix,
        target: tuple[int, ...],
        representative: tuple[int, ...],
        kernel: LinearSubspace,
        proof_context: ProofContext,
        *,
        domain_space: object | None = None,
        evidence: Sequence[VerificationCertificate] = (),
    ) -> None:
        payload = {
            **matrix_payload(matrix),
            "target": target,
            "representative": representative,
            "kernel_basis": kernel.basis,
        }
        receipt = ArithmeticReceipt.create(
            "aim-affine",
            payload,
            context=proof_context,
            evidence=evidence,
        )
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "representative", representative)
        object.__setattr__(self, "kernel", kernel)
        object.__setattr__(self, "proof_context", proof_context)
        object.__setattr__(self, "domain_space", domain_space)
        object.__setattr__(self, "_receipt", receipt)

    @property
    def receipt(self) -> ArithmeticReceipt:
        return self._receipt

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def dimension(self) -> int:
        return self.kernel.dimension

    @property
    def is_unique(self) -> bool:
        return self.kernel.dimension == 0

    @property
    def uniqueness_dimension(self) -> int:
        return self.kernel.dimension

    @property
    def checked_representative(self) -> object:
        constructor = getattr(self.domain_space, "from_coordinates", None)
        return constructor(self.representative) if callable(constructor) else self.representative

    def at(self, parameters: Sequence[object]) -> tuple[int, ...]:
        displacement = self.kernel.vector(cast(Sequence[Scalar], parameters))
        return tuple(
            (left + right) % self.matrix.field.p
            for left, right in zip(self.representative, displacement, strict=True)
        )

    def contains(self, vector: object) -> bool:
        try:
            coordinates = coordinates_of(
                vector,
                field=self.matrix.field,
                length=self.matrix.ncols,
                name="candidate solution",
            )
        except ArithmeticError:
            return False
        difference = tuple(
            (left - right) % self.matrix.field.p
            for left, right in zip(coordinates, self.representative, strict=True)
        )
        return self.kernel.contains(difference) and self.matrix.matvec(coordinates) == self.target

    def verify(self) -> VerificationReport:
        replay = solve(self.matrix, self.target)
        if not replay.consistent:
            raise ArithmeticError("affine family is attached to an inconsistent system")
        if replay.particular != self.representative or replay.kernel != self.kernel:
            raise ArithmeticError("affine family differs from exact deterministic replay")
        expected = ArithmeticReceipt.create(
            "aim-affine",
            {
                **matrix_payload(self.matrix),
                "target": self.target,
                "representative": self.representative,
                "kernel_basis": self.kernel.basis,
            },
            context=self.proof_context,
            evidence=self.receipt.evidence,
        )
        if expected != self.receipt:
            raise ArithmeticError("aiming receipt is not bound to the affine family")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "kernel": self.kernel.to_canonical_data(),
            "matrix": self.matrix.to_canonical_data(),
            "proof_context": self.proof_context.to_canonical_data(),
            "receipt_id": self.receipt.certificate_id,
            "representative": list(self.representative),
            "target": list(self.target),
            "type": "arbogast.affine_aiming_family",
        }


@dataclass(frozen=True, slots=True, init=False)
class LeftNullspaceObstruction(ArithmeticSemanticResult, CanonicalObject):
    """A literal separator ``y`` with ``y A = 0`` and ``y b != 0``."""

    matrix: DenseMatrix
    target: tuple[int, ...]
    witness: tuple[int, ...]
    kernel: LinearSubspace
    proof_context: ProofContext
    _receipt: ArithmeticReceipt

    def __init__(
        self,
        matrix: DenseMatrix,
        target: tuple[int, ...],
        witness: tuple[int, ...],
        kernel: LinearSubspace,
        proof_context: ProofContext,
        *,
        evidence: Sequence[VerificationCertificate] = (),
    ) -> None:
        payload = {
            **matrix_payload(matrix),
            "target": target,
            "witness": witness,
            "kernel_basis": kernel.basis,
        }
        receipt = ArithmeticReceipt.create(
            "aim-obstruction",
            payload,
            context=proof_context,
            evidence=evidence,
        )
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "witness", witness)
        object.__setattr__(self, "kernel", kernel)
        object.__setattr__(self, "proof_context", proof_context)
        object.__setattr__(self, "_receipt", receipt)

    @property
    def receipt(self) -> ArithmeticReceipt:
        return self._receipt

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def pairing(self) -> int:
        return (
            sum(left * right for left, right in zip(self.witness, self.target, strict=True))
            % self.matrix.field.p
        )

    def verify(self) -> VerificationReport:
        replay = solve(self.matrix, self.target)
        if replay.consistent or replay.inconsistency_witness != self.witness:
            raise ArithmeticError("left-nullspace obstruction differs from exact replay")
        if replay.kernel != self.kernel:
            raise ArithmeticError("obstruction stores the wrong homogeneous kernel")
        if self.matrix.transpose().matvec(self.witness) != (0,) * self.matrix.ncols:
            raise ArithmeticError("obstruction witness is not in the left nullspace")
        if self.pairing == 0:
            raise ArithmeticError("obstruction witness does not separate the target")
        expected = ArithmeticReceipt.create(
            "aim-obstruction",
            {
                **matrix_payload(self.matrix),
                "target": self.target,
                "witness": self.witness,
                "kernel_basis": self.kernel.basis,
            },
            context=self.proof_context,
            evidence=self.receipt.evidence,
        )
        if expected != self.receipt:
            raise ArithmeticError("aiming receipt is not bound to the obstruction")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "kernel": self.kernel.to_canonical_data(),
            "matrix": self.matrix.to_canonical_data(),
            "proof_context": self.proof_context.to_canonical_data(),
            "receipt_id": self.receipt.certificate_id,
            "target": list(self.target),
            "type": "arbogast.left_nullspace_obstruction",
            "witness": list(self.witness),
        }


AimResult = AffineFamily | LeftNullspaceObstruction


def aim(
    system: object,
    target: object | None = None,
    *,
    assumptions: Sequence[str] = (),
) -> AimResult:
    """Aim at a local/cocycle target and return complete finite evidence."""

    matrix = _aim_matrix(system)
    if target is None:
        target_coordinates = (0,) * matrix.nrows
    else:
        target_coordinates = coordinates_of(
            target,
            field=matrix.field,
            length=matrix.nrows,
            name="aiming target",
        )
    context = _aim_context(system, assumptions)
    replay = solve(matrix, target_coordinates)
    evidence = evidence_from_sources(system)
    domain_space = getattr(system, "global_space", getattr(system, "domain", None))
    if replay.consistent:
        assert replay.particular is not None
        result: AimResult = AffineFamily(
            matrix,
            target_coordinates,
            replay.particular,
            replay.kernel,
            context,
            domain_space=domain_space,
            evidence=evidence,
        )
    else:
        assert replay.inconsistency_witness is not None
        result = LeftNullspaceObstruction(
            matrix,
            target_coordinates,
            replay.inconsistency_witness,
            replay.kernel,
            context,
            evidence=evidence,
        )
    result.verify()
    return result


def unique(result: AimResult | object, target: object | None = None) -> bool:
    """Return whether aiming has exactly one solution (never hide obstruction)."""

    if isinstance(result, AffineFamily):
        if target is not None:
            raise ArithmeticError("target is not accepted with an existing aiming result")
        result.verify()
        return result.is_unique
    if isinstance(result, LeftNullspaceObstruction):
        if target is not None:
            raise ArithmeticError("target is not accepted with an existing aiming result")
        result.verify()
        return False
    aimed = aim(result, target)
    return isinstance(aimed, AffineFamily) and aimed.is_unique


__all__ = [
    "AffineFamily",
    "AimResult",
    "LeftNullspaceObstruction",
    "aim",
    "unique",
]
