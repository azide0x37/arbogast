"""Exact finite Selmer kernels with fail-closed completeness promotion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from arbogast.cert import VerificationCertificate, VerificationReport
from arbogast.claims import Claim, ClaimGraph
from arbogast.core import CanonicalJSON, CanonicalObject
from arbogast.galois.proof import Completeness, ProofContext
from arbogast.linalg import DenseMatrix, LinearSubspace, Scalar, nullspace

from ._support import (
    dimension_of,
    field_of,
    identity_of,
    mapping_values_in_order,
    matrix_of,
    place_of,
    prime_of,
    stack_matrices,
)
from .certificate import (
    ArithmeticError,
    ArithmeticReceipt,
    coerce_completeness,
    evidence_from_sources,
    matrix_payload,
    verified_complete,
)
from .certificate import (
    proof_context as merge_proof_context,
)
from .conditions import LocalCondition
from .semantic import ArithmeticSemanticResult


def _as_sequence(value: object, name: str) -> tuple[Any, ...]:
    if isinstance(value, Mapping):
        raise ArithmeticError(f"{name} mapping requires place-order resolution")
    if isinstance(value, (str, bytes)):
        raise ArithmeticError(f"{name} must be a sequence")
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


@dataclass(frozen=True, slots=True)
class _LocalizationBlock:
    place: object
    localization: object
    matrix: DenseMatrix
    condition: LocalCondition

    @property
    def place_id(self) -> str:
        return identity_of(self.place, role="place")


@dataclass(frozen=True, slots=True, init=False)
class SelmerProblem(CanonicalObject):
    """A finite global-to-local Kummer problem at a complete declared place set."""

    global_space: object
    localizations: tuple[object, ...]
    conditions: tuple[LocalCondition, ...]
    places: tuple[object, ...]
    place_set_complete: bool
    proof_context: ProofContext
    _blocks: tuple[_LocalizationBlock, ...]

    def __init__(
        self,
        global_space: object,
        localizations: object,
        conditions: object,
        *,
        places: Sequence[object] | None = None,
        place_set_complete: bool | None = None,
        completeness: Completeness | str | None = None,
        assumptions: Sequence[str] = (),
        proof_context: ProofContext | None = None,
    ) -> None:
        global_places_raw = getattr(global_space, "places", None)
        global_places = (
            tuple(global_places_raw)
            if global_places_raw is not None and not isinstance(global_places_raw, (str, bytes))
            else ()
        )
        declared_places = tuple(places) if places is not None else global_places
        if isinstance(conditions, Mapping):
            condition_values = mapping_values_in_order(
                conditions,
                declared_places if declared_places else None,
            )
        else:
            condition_values = _as_sequence(conditions, "conditions")
        if any(not isinstance(condition, LocalCondition) for condition in condition_values):
            raise ArithmeticError("conditions must contain LocalCondition values")
        normalized_conditions = tuple(condition_values)
        if not declared_places:
            declared_places = tuple(condition.place for condition in normalized_conditions)
        if isinstance(localizations, Mapping):
            localization_values = mapping_values_in_order(localizations, declared_places)
        else:
            localization_values = _as_sequence(localizations, "localizations")
        if len(localization_values) != len(normalized_conditions):
            raise ArithmeticError("localizations and local conditions must have equal length")
        if len(declared_places) != len(normalized_conditions):
            raise ArithmeticError(
                "the declared place set and local conditions must have equal length"
            )
        place_ids = tuple(identity_of(place, role="place") for place in declared_places)
        if len(set(place_ids)) != len(place_ids):
            raise ArithmeticError("the declared place set contains duplicates")

        global_field = field_of(global_space)
        global_dimension = dimension_of(global_space)
        blocks: list[_LocalizationBlock] = []
        for index, (place, localization, condition) in enumerate(
            zip(declared_places, localization_values, normalized_conditions, strict=True)
        ):
            place_id = identity_of(place, role="place")
            if identity_of(condition.place, role="place") != place_id:
                raise ArithmeticError(f"local condition {index} belongs to a different place")
            try:
                localization_place = place_of(localization)
            except ArithmeticError:
                localization_place = place
            if identity_of(localization_place, role="place") != place_id:
                raise ArithmeticError(f"localization {index} belongs to a different place")
            matrix = matrix_of(localization)
            if matrix.field != global_field or matrix.field != condition.subspace.field:
                raise ArithmeticError("localization and Selmer spaces use different fields")
            if matrix.ncols != global_dimension:
                raise ArithmeticError("localization has the wrong global domain dimension")
            if matrix.nrows != condition.ambient_dimension:
                raise ArithmeticError("localization has the wrong local codomain dimension")
            domain = getattr(localization, "domain", None)
            if domain is not None and identity_of(domain, role="global-space") != identity_of(
                global_space, role="global-space"
            ):
                raise ArithmeticError("localization is bound to a different global space")
            codomain = getattr(localization, "codomain", None)
            if codomain is not None and identity_of(codomain, role="local-h1-space") != identity_of(
                condition.space, role="local-h1-space"
            ):
                raise ArithmeticError("localization is bound to a different local H1 space")
            blocks.append(_LocalizationBlock(place, localization, matrix, condition))

        inferred_place_complete = (
            bool(global_places)
            and tuple(identity_of(place, role="place") for place in global_places) == place_ids
            and verified_complete(global_space)
            and getattr(global_space, "relevant_places_complete", False) is True
        )
        if place_set_complete is None:
            normalized_place_complete = inferred_place_complete
        elif isinstance(place_set_complete, bool):
            # A caller assertion cannot certify the relevant place set.  True
            # is accepted only when the complete Kummer receipt independently
            # binds exactly these declared places.
            normalized_place_complete = place_set_complete and inferred_place_complete
        else:
            raise ArithmeticError("place_set_complete must be a boolean or None")

        complete_inputs = (
            verified_complete(global_space)
            and normalized_place_complete
            and all(
                verified_complete(block.condition) and verified_complete(block.localization)
                for block in blocks
            )
        )
        inferred_completeness = Completeness.COMPLETE if complete_inputs else Completeness.CANDIDATE
        normalized_completeness = (
            inferred_completeness if completeness is None else coerce_completeness(completeness)
        )
        if normalized_completeness is Completeness.COMPLETE and not complete_inputs:
            raise ArithmeticError("Selmer problem completeness is not supported by all inputs")
        context_sources = (global_space, *localization_values, *normalized_conditions)
        if proof_context is not None:
            if assumptions or completeness is not None:
                raise ArithmeticError(
                    "proof_context cannot be combined with separate assumptions/completeness"
                )
            if proof_context.completeness is Completeness.COMPLETE and not complete_inputs:
                raise ArithmeticError("proof_context overstates Selmer completeness")
            context = merge_proof_context(
                *context_sources,
                proof_context,
                completeness=proof_context.completeness,
            )
        else:
            context = merge_proof_context(
                *context_sources,
                completeness=normalized_completeness,
                assumptions=assumptions,
            )
        object.__setattr__(self, "global_space", global_space)
        object.__setattr__(self, "localizations", tuple(localization_values))
        object.__setattr__(self, "conditions", normalized_conditions)
        object.__setattr__(self, "places", declared_places)
        object.__setattr__(self, "place_set_complete", normalized_place_complete)
        object.__setattr__(self, "proof_context", context)
        object.__setattr__(self, "_blocks", tuple(blocks))
        self.verify()

    @property
    def prime(self) -> int:
        return prime_of(self.global_space)

    @property
    def global_dimension(self) -> int:
        return dimension_of(self.global_space)

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def quotient_blocks(self) -> tuple[DenseMatrix, ...]:
        return tuple(block.condition.quotient_matrix @ block.matrix for block in self._blocks)

    @property
    def global_to_local_quotient(self) -> DenseMatrix:
        return stack_matrices(
            field_of(self.global_space),
            self.quotient_blocks,
            ncols=self.global_dimension,
        )

    @property
    def matrix(self) -> DenseMatrix:
        """Alias used by :func:`aim` for a zero local target."""

        return self.global_to_local_quotient

    def verify(self) -> bool:
        if self.prime != field_of(self.global_space).p:
            raise ArithmeticError("global space prime/field mismatch")
        if len(self._blocks) != len(self.places):
            raise ArithmeticError("Selmer block count differs from its place set")
        if self.global_to_local_quotient.ncols != self.global_dimension:
            raise ArithmeticError("assembled Selmer map has the wrong domain")
        if self.completeness is Completeness.COMPLETE and not self.place_set_complete:
            raise ArithmeticError("complete Selmer problem has an incomplete place set")
        return True

    def _verified_completeness(self) -> bool:
        return (
            self.place_set_complete
            and verified_complete(self.global_space)
            and all(
                verified_complete(block.condition) and verified_complete(block.localization)
                for block in self._blocks
            )
        )

    @property
    def certificate(self) -> VerificationCertificate:
        return selmer(self).certificate

    def claim(self) -> Claim:
        return selmer(self).claim()

    def claim_graph(self) -> ClaimGraph:
        return selmer(self).claim_graph()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "conditions": [condition.to_canonical_data() for condition in self.conditions],
            "global_space_id": identity_of(self.global_space, role="global-space"),
            "localization_matrices": [
                matrix.to_canonical_data() for matrix in self.quotient_blocks
            ],
            "place_ids": [identity_of(place, role="place") for place in self.places],
            "place_set_complete": self.place_set_complete,
            "proof_context": self.proof_context.to_canonical_data(),
            "type": "arbogast.selmer_problem",
        }


@dataclass(frozen=True, slots=True, init=False)
class SelmerKernel(ArithmeticSemanticResult, CanonicalObject):
    """The exact kernel for declared data, without an implicit completeness claim."""

    problem: SelmerProblem
    subspace: LinearSubspace
    constraint_matrix: DenseMatrix
    proof_context: ProofContext
    _receipt: ArithmeticReceipt

    def __init__(
        self,
        problem: SelmerProblem,
        subspace: LinearSubspace,
        constraint_matrix: DenseMatrix,
        proof_context: ProofContext,
        receipt: ArithmeticReceipt,
    ) -> None:
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "subspace", subspace)
        object.__setattr__(self, "constraint_matrix", constraint_matrix)
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
    def prime(self) -> int:
        return self.subspace.field.p

    @property
    def dimension(self) -> int:
        return self.subspace.dimension

    @property
    def basis(self) -> tuple[tuple[int, ...], ...]:
        return self.subspace.basis

    @property
    def basis_classes(self) -> tuple[object, ...]:
        return tuple(self._global_class(vector) for vector in self.basis)

    def _global_class(self, coordinates: tuple[int, ...]) -> object:
        constructor = getattr(self.problem.global_space, "from_coordinates", None)
        return constructor(coordinates) if callable(constructor) else coordinates

    def from_coordinates(self, coordinates: Sequence[object]) -> object:
        vector = self.subspace.vector(cast(Sequence[Scalar], coordinates))
        return self._global_class(vector)

    def contains(self, value: object) -> bool:
        coordinates = getattr(value, "coordinates", value)
        try:
            return self.subspace.contains(coordinates)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    def verify(self) -> VerificationReport:
        self.problem.verify()
        if self.constraint_matrix != self.problem.global_to_local_quotient:
            raise ArithmeticError("Selmer result is bound to a different local-condition map")
        expected = nullspace(self.constraint_matrix)
        if self.subspace != expected:
            raise ArithmeticError("Selmer basis is not the exact recomputed kernel")
        if isinstance(self, SelmerGroup):
            if self.completeness is not Completeness.COMPLETE:
                raise ArithmeticError("SelmerGroup lacks complete input evidence")
            if self.receipt.kind != "selmer-group":
                raise ArithmeticError("SelmerGroup carries a candidate-kernel receipt")
        else:
            if self.completeness is Completeness.COMPLETE:
                raise ArithmeticError("complete Selmer kernel was not promoted to SelmerGroup")
            if self.receipt.kind != "selmer-kernel":
                raise ArithmeticError("candidate Selmer kernel carries a group receipt")
        rebuilt = _selmer_receipt(
            self.problem,
            self.constraint_matrix,
            self.subspace,
            group=isinstance(self, SelmerGroup),
            context=self.proof_context,
        )
        if rebuilt != self.receipt:
            raise ArithmeticError("Selmer receipt is not bound to the result")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "kind": "group" if isinstance(self, SelmerGroup) else "kernel",
            "problem": self.problem.to_canonical_data(),
            "receipt_id": self.receipt.certificate_id,
            "subspace": self.subspace.to_canonical_data(),
            "type": "arbogast.selmer_result",
        }


class SelmerGroup(SelmerKernel):
    """A Selmer kernel promoted only after every completeness gate passes."""


def _selmer_receipt(
    problem: SelmerProblem,
    matrix: DenseMatrix,
    subspace: LinearSubspace,
    *,
    group: bool,
    context: ProofContext,
) -> ArithmeticReceipt:
    evidence = evidence_from_sources(
        problem.global_space,
        *problem.localizations,
        *problem.conditions,
    )
    payload: dict[str, object] = {
        **matrix_payload(matrix),
        "kernel_basis": subspace.basis,
        "global_space_id": identity_of(problem.global_space, role="global-space"),
        "place_ids": tuple(identity_of(place, role="place") for place in problem.places),
        "place_set_complete": problem.place_set_complete,
        "dimension": subspace.dimension,
        "input_evidence_ids": tuple(item.certificate_id for item in evidence),
        "global_certificate_id": _source_certificate_id(problem.global_space),
        "local_blocks": tuple(
            {
                "place_id": identity_of(block.place, role="place"),
                "localization_certificate_id": _source_certificate_id(block.localization),
                "condition_certificate_id": block.condition.certificate.certificate_id,
            }
            for block in problem._blocks
        ),
    }
    return ArithmeticReceipt.create(
        "selmer-group" if group else "selmer-kernel",
        payload,
        context=context,
        evidence=evidence,
    )


def _source_certificate_id(value: object) -> str | None:
    try:
        certificate = getattr(value, "certificate", None)
    except (ArithmeticError, ValueError):
        return None
    return certificate.certificate_id if isinstance(certificate, VerificationCertificate) else None


def selmer(
    problem: SelmerProblem | object,
    localizations: object | None = None,
    conditions: object | None = None,
    **kwargs: object,
) -> SelmerKernel:
    """Compute a Selmer kernel and promote it only after complete evidence."""

    if not isinstance(problem, SelmerProblem):
        if localizations is None or conditions is None:
            raise ArithmeticError(
                "selmer(global_space, ...) requires localizations and local conditions"
            )
        problem = SelmerProblem(
            problem,
            localizations,
            conditions,
            **kwargs,  # type: ignore[arg-type]
        )
    elif localizations is not None or conditions is not None or kwargs:
        raise ArithmeticError("a constructed SelmerProblem cannot be combined with extra inputs")
    problem.verify()
    matrix = problem.global_to_local_quotient
    kernel = nullspace(matrix)
    complete = verified_complete(problem)
    context = merge_proof_context(
        problem,
        completeness=Completeness.COMPLETE if complete else Completeness.CANDIDATE,
    )
    receipt = _selmer_receipt(problem, matrix, kernel, group=complete, context=context)
    result_type = SelmerGroup if complete else SelmerKernel
    result = result_type(problem, kernel, matrix, context, receipt)
    result.verify()
    return result


__all__ = ["SelmerGroup", "SelmerKernel", "SelmerProblem", "selmer"]
