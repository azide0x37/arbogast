"""Bounded elementary Kummer descent with literal three-way outcomes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from arbogast.cert import VerificationCertificate, VerificationReport
from arbogast.claims import Claim, ClaimGraph
from arbogast.core import CanonicalJSON, CanonicalObject
from arbogast.galois.kummer import KummerClass
from arbogast.galois.proof import Completeness, ProofContext
from arbogast.linalg import DenseMatrix

from ._support import coordinates_of, identity_of
from .aiming import AffineFamily, LeftNullspaceObstruction, aim
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


@dataclass(frozen=True, slots=True, init=False)
class KummerDescentProblem(CanonicalObject):
    """A bounded exact aiming problem plus an explicit realization boundary."""

    system: object
    matrix: DenseMatrix
    target: tuple[int, ...]
    witness: tuple[int, ...] | None
    witness_source: object | None
    linear_realization: bool
    search_complete: bool
    unknown_reason: str | None
    proof_context: ProofContext

    def __init__(
        self,
        system: object,
        target: object | None = None,
        *,
        witness: object | None = None,
        linear_realization: bool | None = None,
        search_complete: bool = False,
        unknown_reason: str | None = None,
        assumptions: Sequence[str] = (),
    ) -> None:
        assembled = getattr(system, "global_to_local_quotient", None)
        raw_matrix = assembled if assembled is not None else getattr(system, "matrix", system)
        if not isinstance(raw_matrix, DenseMatrix):
            raise ArithmeticError("Kummer descent requires an exact prime-field aiming matrix")
        target_coordinates = (
            (0,) * raw_matrix.nrows
            if target is None
            else coordinates_of(
                target,
                field=raw_matrix.field,
                length=raw_matrix.nrows,
                name="descent target",
            )
        )
        witness_coordinates = (
            None
            if witness is None
            else coordinates_of(
                witness,
                field=raw_matrix.field,
                length=raw_matrix.ncols,
                name="descent witness",
            )
        )
        if not isinstance(search_complete, bool):
            raise ArithmeticError("search_complete must be a boolean")
        bare_linear_system = isinstance(system, DenseMatrix)
        if linear_realization is None:
            # A bare matrix defines a genuinely linear realization problem.
            # Selmer/local-condition objects do not: local solubility alone is
            # never promoted to a global point.
            normalized_linear = bare_linear_system
        elif isinstance(linear_realization, bool):
            if linear_realization and not bare_linear_system:
                raise ArithmeticError(
                    "linear_realization=True is valid only for a bare finite linear problem"
                )
            normalized_linear = linear_realization
        else:
            raise ArithmeticError("linear_realization must be a boolean or None")
        witness_source = None if witness is None or bare_linear_system else witness
        if witness_source is not None:
            if not isinstance(witness_source, KummerClass):
                raise ArithmeticError(
                    "arithmetic descent requires a certified global witness KummerClass"
                )
            verifier = getattr(witness_source, "verify", None)
            certificate = getattr(witness_source, "certificate", None)
            if not callable(verifier) or not isinstance(certificate, VerificationCertificate):
                raise ArithmeticError(
                    "arithmetic descent requires a certified global witness object"
                )
            outcome = verifier()
            if outcome is False or getattr(outcome, "valid", True) is False:
                raise ArithmeticError("the supplied global realization witness did not verify")
            global_space = getattr(system, "global_space", None)
            witness_space = witness_source.space
            if global_space is None or identity_of(
                global_space, role="global-space"
            ) != identity_of(witness_space, role="global-space"):
                raise ArithmeticError("global witness belongs to a different descent space")
        if unknown_reason is not None and (
            not isinstance(unknown_reason, str) or not unknown_reason.strip()
        ):
            raise ArithmeticError("unknown_reason must be a non-blank string or None")
        context = merge_proof_context(system, assumptions=assumptions)
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "matrix", raw_matrix)
        object.__setattr__(self, "target", target_coordinates)
        object.__setattr__(self, "witness", witness_coordinates)
        object.__setattr__(self, "witness_source", witness_source)
        object.__setattr__(self, "linear_realization", normalized_linear)
        object.__setattr__(self, "search_complete", search_complete)
        object.__setattr__(self, "unknown_reason", unknown_reason)
        object.__setattr__(self, "proof_context", context)
        self.verify()

    @property
    def problem_id(self) -> str:
        return self.content_id

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    def verify(self) -> bool:
        if len(self.target) != self.matrix.nrows:
            raise ArithmeticError("descent target has the wrong dimension")
        if self.witness is not None and self.matrix.matvec(self.witness) != self.target:
            raise ArithmeticError("supplied descent witness does not realize the target")
        if self.witness_source is not None:
            verifier = getattr(self.witness_source, "verify", None)
            if not callable(verifier):
                raise ArithmeticError("global realization witness lost its verifier")
            outcome = verifier()
            if outcome is False or getattr(outcome, "valid", True) is False:
                raise ArithmeticError("global realization witness no longer verifies")
        return True

    @property
    def certificate(self) -> VerificationCertificate:
        return elementary_descent(self).certificate

    def claim(self) -> Claim:
        return elementary_descent(self).claim()

    def claim_graph(self) -> ClaimGraph:
        return elementary_descent(self).claim_graph()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "linear_realization": self.linear_realization,
            "matrix": self.matrix.to_canonical_data(),
            "proof_context": self.proof_context.to_canonical_data(),
            "search_complete": self.search_complete,
            "system_id": identity_of(self.system, role="descent-system"),
            "target": list(self.target),
            "type": "arbogast.kummer_descent_problem",
            "unknown_reason": self.unknown_reason,
            "witness": None if self.witness is None else list(self.witness),
            "witness_source_id": (
                None
                if self.witness_source is None
                else identity_of(self.witness_source, role="global-realization-witness")
            ),
        }


@dataclass(frozen=True, slots=True, init=False)
class Realized(ArithmeticSemanticResult, CanonicalObject):
    """A descent problem with an explicitly checked global witness."""

    problem: KummerDescentProblem
    witness: tuple[int, ...]
    proof_context: ProofContext
    _receipt: ArithmeticReceipt

    def __init__(self, problem: KummerDescentProblem, witness: tuple[int, ...]) -> None:
        if not problem.linear_realization and (
            problem.witness_source is None or problem.witness != witness
        ):
            raise ArithmeticError(
                "arithmetic descent realization requires the problem's certified global witness"
            )
        evidence = evidence_from_sources(problem.system, problem.witness_source)
        witness_certificate = getattr(problem.witness_source, "certificate", None)
        if witness_certificate is not None and not isinstance(
            witness_certificate,
            VerificationCertificate,
        ):
            raise ArithmeticError("global realization witness has an invalid certificate")
        global_space = getattr(problem.system, "global_space", None)
        receipt = ArithmeticReceipt.create(
            "descent-realized",
            {
                "problem_id": problem.problem_id,
                **matrix_payload(problem.matrix),
                "target": problem.target,
                "witness": witness,
                "input_evidence_ids": tuple(item.certificate_id for item in evidence),
                "realization_kind": (
                    "finite-linear" if problem.linear_realization else "certified-kummer-class"
                ),
                "global_space_id": (
                    None if global_space is None else identity_of(global_space, role="global-space")
                ),
                "linear_system_id": (
                    identity_of(problem.system, role="descent-system")
                    if problem.linear_realization
                    else None
                ),
                "witness_source_id": (
                    None
                    if problem.witness_source is None
                    else identity_of(
                        problem.witness_source,
                        role="global-realization-witness",
                    )
                ),
                "witness_certificate_id": (
                    None if witness_certificate is None else witness_certificate.certificate_id
                ),
            },
            context=problem.proof_context,
            evidence=evidence,
        )
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "witness", witness)
        object.__setattr__(self, "proof_context", problem.proof_context)
        object.__setattr__(self, "_receipt", receipt)

    @property
    def receipt(self) -> ArithmeticReceipt:
        return self._receipt

    def verify(self) -> VerificationReport:
        self.problem.verify()
        if self.problem.matrix.matvec(self.witness) != self.problem.target:
            raise ArithmeticError("descent realization witness no longer solves the target")
        expected = Realized(self.problem, self.witness).receipt
        if expected != self.receipt:
            raise ArithmeticError("realized descent receipt is not bound to the problem")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "problem_id": self.problem.problem_id,
            "receipt_id": self.receipt.certificate_id,
            "type": "arbogast.descent_realized",
            "witness": list(self.witness),
        }


@dataclass(frozen=True, slots=True, init=False)
class Obstructed(ArithmeticSemanticResult, CanonicalObject):
    """A descent problem with a literal left-nullspace obstruction."""

    problem: KummerDescentProblem
    obstruction: LeftNullspaceObstruction
    proof_context: ProofContext
    _receipt: ArithmeticReceipt

    def __init__(
        self,
        problem: KummerDescentProblem,
        obstruction: LeftNullspaceObstruction,
    ) -> None:
        evidence = evidence_from_sources(problem.system, obstruction)
        receipt = ArithmeticReceipt.create(
            "descent-obstructed",
            {
                "problem_id": problem.problem_id,
                **matrix_payload(problem.matrix),
                "target": problem.target,
                "witness": obstruction.witness,
            },
            context=problem.proof_context,
            evidence=evidence,
        )
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "obstruction", obstruction)
        object.__setattr__(self, "proof_context", problem.proof_context)
        object.__setattr__(self, "_receipt", receipt)

    @property
    def receipt(self) -> ArithmeticReceipt:
        return self._receipt

    @property
    def witness(self) -> tuple[int, ...]:
        return self.obstruction.witness

    @property
    def obstruction_certificate(self) -> VerificationCertificate:
        return self.obstruction.certificate

    def verify(self) -> VerificationReport:
        self.problem.verify()
        self.obstruction.verify()
        if (
            self.obstruction.matrix != self.problem.matrix
            or self.obstruction.target != self.problem.target
        ):
            raise ArithmeticError("descent obstruction belongs to a different aiming problem")
        expected = Obstructed(self.problem, self.obstruction).receipt
        if expected != self.receipt:
            raise ArithmeticError("obstructed descent receipt is not bound to the problem")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "obstruction": self.obstruction.to_canonical_data(),
            "problem_id": self.problem.problem_id,
            "receipt_id": self.receipt.certificate_id,
            "type": "arbogast.descent_obstructed",
        }


@dataclass(frozen=True, slots=True, init=False)
class Unknown(ArithmeticSemanticResult, CanonicalObject):
    """An explicit non-closing result: neither realized nor obstructed."""

    problem: KummerDescentProblem
    reason: str
    proof_context: ProofContext
    _receipt: ArithmeticReceipt

    def __init__(self, problem: KummerDescentProblem, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ArithmeticError("Unknown requires a non-blank reason")
        evidence = evidence_from_sources(problem.system)
        receipt = ArithmeticReceipt.create(
            "descent-unknown",
            {"problem_id": problem.problem_id, "reason": reason},
            context=problem.proof_context,
            evidence=evidence,
        )
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "proof_context", problem.proof_context)
        object.__setattr__(self, "_receipt", receipt)

    @property
    def receipt(self) -> ArithmeticReceipt:
        return self._receipt

    def verify(self) -> VerificationReport:
        self.problem.verify()
        expected = Unknown(self.problem, self.reason).receipt
        if expected != self.receipt:
            raise ArithmeticError("Unknown descent receipt is not bound to the problem")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "problem_id": self.problem.problem_id,
            "reason": self.reason,
            "receipt_id": self.receipt.certificate_id,
            "type": "arbogast.descent_unknown",
        }


DescentOutcome = Realized | Obstructed | Unknown


def elementary_descent(problem: KummerDescentProblem) -> DescentOutcome:
    """Run the bounded descent without turning failed search into a theorem."""

    if not isinstance(problem, KummerDescentProblem):
        raise ArithmeticError("elementary_descent requires a KummerDescentProblem")
    problem.verify()
    aimed = aim(problem.system, problem.target, assumptions=problem.assumptions)
    if isinstance(aimed, LeftNullspaceObstruction):
        outcome: DescentOutcome = Obstructed(problem, aimed)
    elif problem.witness is not None:
        outcome = Realized(problem, problem.witness)
    elif problem.linear_realization:
        assert isinstance(aimed, AffineFamily)
        outcome = Realized(problem, aimed.representative)
    else:
        reason = problem.unknown_reason or (
            "local/Kummer conditions are consistent, but no checked global realization "
            "witness was supplied"
        )
        outcome = Unknown(problem, reason)
    outcome.verify()
    return outcome


__all__ = [
    "DescentOutcome",
    "KummerDescentProblem",
    "Obstructed",
    "Realized",
    "Unknown",
    "elementary_descent",
]
