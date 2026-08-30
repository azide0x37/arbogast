"""Cartier duals, exact local pairings, and dual Selmer conditions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from arbogast.cert import (
    FrozenMap,
    VerificationCertificate,
    VerificationReport,
    freeze_mapping,
)
from arbogast.core import CanonicalJSON, CanonicalObject
from arbogast.galois.kummer import KummerSpace
from arbogast.galois.modules import GaloisModule
from arbogast.galois.proof import (
    Completeness,
    ProofContext,
    VerificationRequirement,
)
from arbogast.linalg import DenseMatrix, PrimeField, Scalar, inverse, nullspace, rank
from arbogast.rep import Representation

from ._support import (
    coordinates_of,
    dimension_of,
    field_of,
    identity_of,
    mapping_values_in_order,
    prime_of,
)
from .certificate import (
    ArithmeticError,
    ArithmeticReceipt,
    UnsupportedArithmeticOperation,
    coerce_completeness,
    evidence_from_sources,
    matrix_payload,
    normalized_assumptions,
    verified_complete,
)
from .certificate import (
    proof_context as merge_proof_context,
)
from .conditions import LocalCondition, local_condition
from .selmer import SelmerKernel, SelmerProblem, selmer
from .semantic import ArithmeticSemanticResult


def _action_matrices(module: object) -> tuple[DenseMatrix, ...]:
    raw = getattr(module, "matrices", getattr(module, "action_matrices", ()))
    if isinstance(raw, Mapping):
        elements = getattr(module, "elements", ())
        raw = tuple(raw[element] for element in elements) if elements else tuple(raw.values())
    field = field_of(module)
    dimension = dimension_of(module)
    result: list[DenseMatrix] = []
    for item in raw:
        if isinstance(item, DenseMatrix):
            matrix = item
        else:
            matrix = DenseMatrix(field, item, ncols=dimension)
        if matrix.shape != (dimension, dimension) or matrix.field != field:
            raise ArithmeticError("module action contains a matrix with the wrong shape or field")
        result.append(matrix)
    return tuple(result)


def _rational_value(value: object) -> Fraction:
    coefficients = getattr(value, "coefficients", None)
    if not isinstance(coefficients, Sequence) or len(coefficients) != 1:
        raise UnsupportedArithmeticOperation(
            "portable Hilbert pairing currently requires rational basis representatives"
        )
    result = coefficients[0]
    if not isinstance(result, Fraction) or result == 0:
        raise ArithmeticError("Hilbert pairing basis representatives must be nonzero rationals")
    return result


def _valuation(value: int, prime: int) -> int:
    result = 0
    while value % prime == 0:
        value //= prime
        result += 1
    return result


def _q2_hilbert_exponent(left: Fraction, right: Fraction) -> int:
    left_valuation = _valuation(abs(left.numerator), 2) - _valuation(left.denominator, 2)
    right_valuation = _valuation(abs(right.numerator), 2) - _valuation(right.denominator, 2)

    def unit_residue(value: Fraction, valuation: int) -> int:
        unit = value / 2**valuation if valuation >= 0 else value * 2 ** (-valuation)
        numerator = unit.numerator % 8
        denominator = unit.denominator % 8
        return int(numerator * pow(denominator, -1, 8) % 8)

    left_unit = unit_residue(left, left_valuation)
    right_unit = unit_residue(right, right_valuation)
    left_epsilon = ((left_unit % 4) - 1) // 2 % 2
    right_epsilon = ((right_unit % 4) - 1) // 2 % 2
    left_omega = 0 if left_unit in {1, 7} else 1
    right_omega = 0 if right_unit in {1, 7} else 1
    return (
        left_epsilon * right_epsilon + left_valuation * right_omega + right_valuation * left_omega
    ) % 2


def _rational_hilbert_witness(
    left_space: object,
    right_space: object,
    place: object,
) -> tuple[DenseMatrix, dict[str, object]]:
    if prime_of(left_space) != 2 or prime_of(right_space) != 2:
        raise UnsupportedArithmeticOperation("portable Hilbert pairing is automatic only for p=2")
    kind = getattr(getattr(place, "kind", None), "value", getattr(place, "kind", None))
    if kind == "complex":
        left_basis = tuple(getattr(left_space, "basis_representatives", ()))
        right_basis = tuple(getattr(right_space, "basis_representatives", ()))
        if (
            dimension_of(left_space) != 0
            or dimension_of(right_space) != 0
            or left_basis
            or right_basis
        ):
            raise ArithmeticError("complex local H1(mu2) must be zero-dimensional")
        return (
            DenseMatrix(PrimeField(2), (), ncols=0),
            {"kind": "complex-zero-hilbert-v1"},
        )
    left_values = tuple(
        _rational_value(item) for item in getattr(left_space, "basis_representatives", ())
    )
    right_values = tuple(
        _rational_value(item) for item in getattr(right_space, "basis_representatives", ())
    )
    if len(left_values) != dimension_of(left_space) or len(right_values) != dimension_of(
        right_space
    ):
        raise ArithmeticError("local spaces do not expose their complete pinned bases")
    rational_prime = getattr(place, "rational_prime", None)
    if rational_prime == 2:
        place_kind = "q2"
        rows = tuple(
            tuple(_q2_hilbert_exponent(left, right) for right in right_values)
            for left in left_values
        )
    elif kind == "real":
        place_kind = "real"
        rows = tuple(
            tuple(int(left < 0 and right < 0) for right in right_values) for left in left_values
        )
    else:
        raise UnsupportedArithmeticOperation(
            "portable rational Hilbert pairing currently supports Q_2 and the real place"
        )
    matrix = DenseMatrix(PrimeField(2), rows, ncols=len(right_values))
    witness: dict[str, object] = {
        "kind": "rational-hilbert-v1",
        "place_kind": place_kind,
        "left_values": tuple((value.numerator, value.denominator) for value in left_values),
        "right_values": tuple((value.numerator, value.denominator) for value in right_values),
    }
    return matrix, witness


def _pari_hilbert_witness(
    left_space: object,
    right_space: object,
    place: object,
    *,
    backend: object | None,
) -> tuple[
    DenseMatrix,
    tuple[VerificationCertificate, ...],
    tuple[str, ...],
]:
    """Discover a row-major Hilbert matrix with one closed PARI call per entry."""

    from arbogast.backends.base import BackendUnavailableError
    from arbogast.backends.pari import PariBackend
    from arbogast.backends.pari_protocol import PariBackendError
    from arbogast.backends.pari_results import PariOutcome

    if prime_of(left_space) != 2 or prime_of(right_space) != 2:
        raise UnsupportedArithmeticOperation("automatic Hilbert pairing is supported only for p=2")
    left_values = tuple(getattr(left_space, "basis_representatives", ()))
    right_values = tuple(getattr(right_space, "basis_representatives", ()))
    if len(left_values) != dimension_of(left_space) or len(right_values) != dimension_of(
        right_space
    ):
        raise ArithmeticError("local spaces do not expose their complete pinned bases")
    number_field = getattr(place, "field", None)
    field_id = getattr(number_field, "field_id", None)
    if not isinstance(field_id, str) or not field_id:
        raise ArithmeticError("PARI Hilbert pairing requires a pinned number-field place")
    for value in (*left_values, *right_values):
        if getattr(value, "field", None) != number_field:
            raise ArithmeticError("Hilbert pairing basis representatives belong to another field")
        if bool(getattr(value, "is_zero", False)):
            raise ArithmeticError("Hilbert pairing basis representatives must be nonzero")
    if not left_values or not right_values:
        raise UnsupportedArithmeticOperation(
            "automatic PARI pairing needs at least one local squareclass basis entry"
        )

    adapter = PariBackend() if backend is None else backend
    operation = getattr(adapter, "quadratic_hilbert_pairing", None)
    if not callable(operation):
        raise ArithmeticError("Hilbert-pairing backend must provide quadratic_hilbert_pairing")
    place_id = identity_of(place, role="place")
    expected_place_kind = (
        "finite"
        if getattr(place, "rational_prime", None) is not None
        else str(getattr(getattr(place, "kind", None), "value", getattr(place, "kind", "")))
    )
    rows: list[tuple[int, ...]] = []
    certificates: list[VerificationCertificate] = []
    result_contexts: list[ProofContext] = []
    for left in left_values:
        row: list[int] = []
        for right in right_values:
            try:
                result = operation(number_field, left, right, place)
            except (BackendUnavailableError, PariBackendError) as error:
                raise UnsupportedArithmeticOperation(
                    f"PARI could not certify the local Hilbert pairing: {error}"
                ) from error
            if getattr(result, "outcome", None) is not PariOutcome.SUCCESS:
                raise UnsupportedArithmeticOperation(
                    "PARI Hilbert arithmetic ended without a complete replayable result"
                )
            context_factory = getattr(result, "proof_context", None)
            if not callable(context_factory):
                raise ArithmeticError("PARI Hilbert result lacks a proof context")
            result_context = context_factory()
            if not isinstance(result_context, ProofContext) or not result_context.complete:
                raise UnsupportedArithmeticOperation(
                    "PARI Hilbert arithmetic returned only candidate evidence"
                )
            payload_value = getattr(result, "payload", None)
            payload_to_dict = getattr(payload_value, "to_dict", None)
            payload = payload_to_dict() if callable(payload_to_dict) else payload_value
            if not isinstance(payload, Mapping):
                raise ArithmeticError("PARI Hilbert payload must be a mapping")
            symbol = payload.get("symbol")
            if symbol not in {-1, 1} or isinstance(symbol, bool):
                raise ArithmeticError("PARI Hilbert payload has an invalid symbol")
            if (
                payload.get("field_id") != field_id
                or payload.get("left_element_id") != identity_of(left, role="field-element")
                or payload.get("right_element_id") != identity_of(right, role="field-element")
                or payload.get("place_id") != place_id
                or payload.get("place_kind") != expected_place_kind
            ):
                raise ArithmeticError("PARI Hilbert payload was rebound to different exact data")
            certificate = getattr(result, "certificate", None)
            if not isinstance(certificate, VerificationCertificate):
                raise ArithmeticError("successful PARI Hilbert arithmetic lacks proof evidence")
            certificate.verify_integrity()
            raw_witness = certificate.witness.to_dict()
            version = raw_witness.get("backend_version")
            if not isinstance(version, str) or not any(
                requirement.verifier == "arbogast.backends.pari.v1"
                and requirement.version == version
                and "quadratic_hilbert_pairing" in requirement.capabilities
                for requirement in result_context.verification_requirements
            ):
                raise ArithmeticError(
                    "PARI Hilbert proof context does not match its pinned certificate"
                )
            row.append(1 if symbol == -1 else 0)
            certificates.append(certificate)
            result_contexts.append(result_context)
        rows.append(tuple(row))
    return (
        DenseMatrix(PrimeField(2), tuple(rows), ncols=len(right_values)),
        tuple(certificates),
        normalized_assumptions(*result_contexts),
    )


def _matrix_rows(matrices: Sequence[DenseMatrix]) -> tuple[tuple[tuple[int, ...], ...], ...]:
    return tuple(matrix.rows for matrix in matrices)


def _cartier_payload(
    module: GaloisModule,
    dual_module: GaloisModule | None,
    matrices: Sequence[DenseMatrix],
    *,
    tate_twist: int,
    twist_character: Sequence[int] | None,
) -> dict[str, object]:
    elements = module.elements
    element_indices = {element: index for index, element in enumerate(elements)}
    multiplication_table = tuple(
        tuple(element_indices[module.group.multiply(left, right)] for right in elements)
        for left in elements
    )
    return {
        "module_id": identity_of(module, role="galois-module"),
        "dual_module_id": (
            None if dual_module is None else identity_of(dual_module, role="galois-module")
        ),
        "prime": module.prime,
        "dimension": module.dimension,
        "quotient_id": module.quotient.quotient_id,
        "action_convention": Representation.ACTION_CONVENTION,
        "group_identity": element_indices[module.group.identity],
        "group_table": multiplication_table,
        "tate_twist": tate_twist,
        "twist_character": None if twist_character is None else tuple(twist_character),
        "original_action_matrices": _matrix_rows(_action_matrices(module)),
        "dual_action_matrices": _matrix_rows(matrices),
    }


@dataclass(frozen=True, slots=True, init=False)
class CartierDual(ArithmeticSemanticResult, CanonicalObject):
    """The pinned contragredient module ``M^vee(1)``."""

    module: object
    dual_module: object | None
    tate_twist: int
    twist_character: tuple[int, ...] | None
    proof_context: ProofContext
    _matrices: tuple[DenseMatrix, ...]
    _receipt: ArithmeticReceipt

    def __init__(
        self,
        module: object,
        *,
        dual_module: object | None = None,
        tate_twist: int = 1,
        twist_character: Sequence[int] | None = None,
        assumptions: Sequence[str] = (),
    ) -> None:
        if isinstance(tate_twist, bool) or not isinstance(tate_twist, int):
            raise ArithmeticError("tate_twist must be an integer")
        if not isinstance(module, GaloisModule):
            raise ArithmeticError(
                "CartierDual requires an explicit verified finite GaloisModule action"
            )
        if not module.verify():
            raise ArithmeticError("the source Galois module did not verify")
        prime = prime_of(module)
        dimension = dimension_of(module)
        original = _action_matrices(module)
        if not original:
            raise ArithmeticError("CartierDual requires at least the identity action matrix")
        normalized_character: tuple[int, ...] | None = None
        if tate_twist and prime != 2:
            if twist_character is None:
                raise UnsupportedArithmeticOperation(
                    "automatic Tate twists for p>2 require a certified cyclotomic character"
                )
            normalized_character = tuple(
                field_of(module).residue(value) for value in twist_character
            )
            if len(normalized_character) != len(original) or any(
                value == 0 for value in normalized_character
            ):
                raise ArithmeticError("twist character has invalid values or length")
        expected = tuple(inverse(matrix).transpose() for matrix in original)
        if normalized_character is not None:
            expected = tuple(
                matrix.scale(pow(value, tate_twist, prime))
                for matrix, value in zip(expected, normalized_character, strict=True)
            )
        if dual_module is not None:
            if not isinstance(dual_module, GaloisModule) or not dual_module.verify():
                raise ArithmeticError("the supplied dual module did not verify")
            if dual_module.quotient.quotient_id != module.quotient.quotient_id:
                raise ArithmeticError("dual module factors through a different Galois quotient")
            if prime_of(dual_module) != prime or dimension_of(dual_module) != dimension:
                raise ArithmeticError("dual module has a different field or dimension")
            matrices = _action_matrices(dual_module)
            if matrices != expected:
                raise ArithmeticError("supplied dual action is not M^vee(1)")
        else:
            matrices = expected
        context = merge_proof_context(
            module.quotient,
            *((dual_module.quotient,) if dual_module is not None else ()),
            completeness=Completeness.COMPLETE,
            assumptions=assumptions,
        )
        evidence = evidence_from_sources(module, dual_module)
        receipt = ArithmeticReceipt.create(
            "cartier-dual",
            _cartier_payload(
                module,
                dual_module,
                matrices,
                tate_twist=tate_twist,
                twist_character=normalized_character,
            ),
            context=context,
            evidence=evidence,
        )
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "dual_module", dual_module)
        object.__setattr__(self, "tate_twist", tate_twist)
        object.__setattr__(self, "twist_character", normalized_character)
        object.__setattr__(self, "proof_context", context)
        object.__setattr__(self, "_matrices", matrices)
        object.__setattr__(self, "_receipt", receipt)

    @property
    def receipt(self) -> ArithmeticReceipt:
        return self._receipt

    @property
    def prime(self) -> int:
        return prime_of(self.module)

    @property
    def field(self) -> object:
        return field_of(self.module)

    @property
    def dimension(self) -> int:
        return dimension_of(self.module)

    @property
    def matrices(self) -> tuple[DenseMatrix, ...]:
        return self._matrices

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    def verify(self) -> VerificationReport:
        if not isinstance(self.module, GaloisModule) or not self.module.verify():
            raise ArithmeticError("Cartier dual source is not a verified Galois module")
        original = _action_matrices(self.module)
        expected = tuple(inverse(matrix).transpose() for matrix in original)
        if self.twist_character is not None:
            expected = tuple(
                matrix.scale(pow(value, self.tate_twist, self.prime))
                for matrix, value in zip(expected, self.twist_character, strict=True)
            )
        if self.matrices != expected:
            raise ArithmeticError("Cartier dual action is not the certified M^vee(1) action")
        if any(matrix.shape != (self.dimension, self.dimension) for matrix in self.matrices):
            raise ArithmeticError("Cartier dual action matrix has the wrong shape")
        expected_receipt = ArithmeticReceipt.create(
            "cartier-dual",
            _cartier_payload(
                self.module,
                cast(GaloisModule | None, self.dual_module),
                self.matrices,
                tate_twist=self.tate_twist,
                twist_character=self.twist_character,
            ),
            context=self.proof_context,
            evidence=evidence_from_sources(self.module, self.dual_module),
        )
        if expected_receipt != self.receipt:
            raise ArithmeticError("Cartier-dual receipt is not bound to the module")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action_matrices": [matrix.to_canonical_data() for matrix in self.matrices],
            "dimension": self.dimension,
            "module_id": identity_of(self.module, role="galois-module"),
            "prime": self.prime,
            "proof_context": self.proof_context.to_canonical_data(),
            "receipt_id": self.receipt.certificate_id,
            "tate_twist": self.tate_twist,
            "type": "arbogast.cartier_dual",
        }


@dataclass(frozen=True, slots=True, init=False)
class LocalPairing(ArithmeticSemanticResult, CanonicalObject):
    """An exact bilinear local Tate/Hilbert pairing matrix."""

    left_space: object
    right_space: object
    matrix: DenseMatrix
    place: object
    proof_context: ProofContext
    pairing_witness: FrozenMap | None
    _pari_certificates: tuple[VerificationCertificate, ...]
    _receipt: ArithmeticReceipt

    def __init__(
        self,
        left_space: object,
        right_space: object,
        matrix: DenseMatrix | Sequence[Sequence[object]],
        *,
        place: object | None = None,
        completeness: Completeness | str | None = None,
        assumptions: Sequence[str] = (),
        pari_certificates: Sequence[VerificationCertificate] = (),
        proof_context: ProofContext | None = None,
        pairing_witness: Mapping[str, object] | None = None,
        proving_certificates: Sequence[VerificationCertificate] = (),
    ) -> None:
        field = field_of(left_space)
        if field != field_of(right_space):
            raise ArithmeticError("local pairing spaces use different fields")
        left_dimension = dimension_of(left_space)
        right_dimension = dimension_of(right_space)
        exact_matrix = (
            matrix
            if isinstance(matrix, DenseMatrix)
            else DenseMatrix(
                field,
                cast(Sequence[Sequence[Scalar]], matrix),
                ncols=right_dimension,
            )
        )
        if exact_matrix.field != field or exact_matrix.shape != (
            left_dimension,
            right_dimension,
        ):
            raise ArithmeticError("local pairing matrix has the wrong field or shape")
        left_place = getattr(left_space, "place", None)
        right_place = getattr(right_space, "place", None)
        resolved_place = place if place is not None else left_place or right_place
        if resolved_place is None:
            raise ArithmeticError("local pairing requires an explicit place")
        resolved_id = identity_of(resolved_place, role="place")
        for advertised in (left_place, right_place):
            if advertised is not None and identity_of(advertised, role="place") != resolved_id:
                raise ArithmeticError("local pairing spaces belong to different places")
        pari_evidence = tuple(pari_certificates)
        supplied_evidence = tuple(proving_certificates)
        if pari_evidence and supplied_evidence:
            raise ArithmeticError("PARI and supplied pairing certificates cannot be combined")
        certificates = pari_evidence or supplied_evidence
        if any(not isinstance(item, VerificationCertificate) for item in certificates):
            raise ArithmeticError(
                "pairing certificates must contain VerificationCertificate values"
            )
        if pari_evidence and pairing_witness is not None:
            raise ArithmeticError("portable and PARI pairing witnesses cannot be combined")
        if supplied_evidence and pairing_witness is None:
            raise ArithmeticError("a supplied pairing certificate needs an exact pairing witness")
        witness: Mapping[str, object] | None = pairing_witness
        external_requirement: VerificationRequirement | None = None
        if pari_evidence:
            versions: set[str] = set()
            for certificate in certificates:
                if certificate.verifier != "arbogast.backends.pari.v1":
                    raise ArithmeticError("local pairing external evidence must be pinned PARI")
                raw_version = certificate.witness.to_dict().get("backend_version")
                if not isinstance(raw_version, str) or not raw_version:
                    raise ArithmeticError("PARI pairing certificate lacks a pinned version")
                versions.add(raw_version)
            if len(versions) != 1:
                raise ArithmeticError("PARI pairing certificates use different versions")
            version = next(iter(versions))
            external_requirement = VerificationRequirement.pinned_external(
                "arbogast.backends.pari.v1",
                version,
                capabilities=("quadratic_hilbert_pairing",),
            )
            witness = {
                "kind": "pari-hilbert-v1",
                "certificate_ids": tuple(item.certificate_id for item in certificates),
            }
        frozen_witness = None if witness is None else freeze_mapping(witness)
        complete_inputs = verified_complete(left_space) and verified_complete(right_space)
        inferred = (
            Completeness.COMPLETE
            if complete_inputs and frozen_witness is not None
            else Completeness.CANDIDATE
        )
        normalized = inferred if completeness is None else coerce_completeness(completeness)
        if normalized is Completeness.COMPLETE and not (
            complete_inputs and frozen_witness is not None
        ):
            raise ArithmeticError(
                "pairing completeness requires complete local spaces and a replayable "
                "Hilbert/Tate witness"
            )
        if proof_context is not None:
            if assumptions or completeness is not None:
                raise ArithmeticError(
                    "proof_context cannot be combined with assumptions or completeness"
                )
            if proof_context.completeness is Completeness.COMPLETE and not (
                complete_inputs and frozen_witness is not None
            ):
                raise ArithmeticError("proof_context overstates local-pairing completeness")
            base_context = merge_proof_context(
                left_space,
                right_space,
                proof_context,
                completeness=proof_context.completeness,
            )
            normalized = proof_context.completeness
        else:
            base_context = merge_proof_context(
                left_space,
                right_space,
                completeness=normalized,
                assumptions=assumptions,
            )
        context = base_context
        if external_requirement is not None:
            context = ProofContext(
                base_context.assumptions,
                (*base_context.verification_requirements, external_requirement),
                normalized,
            )
        evidence = evidence_from_sources(left_space, right_space, *certificates)
        receipt = ArithmeticReceipt.create(
            "local-pairing",
            {
                **matrix_payload(exact_matrix),
                "left_space_id": identity_of(left_space, role="local-h1-space"),
                "right_space_id": identity_of(right_space, role="local-h1-space"),
                "place_id": resolved_id,
                "pairing_witness": frozen_witness,
                "perfect": (exact_matrix.nrows == exact_matrix.ncols == rank(exact_matrix)),
            },
            context=context,
            evidence=evidence,
        )
        object.__setattr__(self, "left_space", left_space)
        object.__setattr__(self, "right_space", right_space)
        object.__setattr__(self, "matrix", exact_matrix)
        object.__setattr__(self, "place", resolved_place)
        object.__setattr__(self, "proof_context", context)
        object.__setattr__(self, "pairing_witness", frozen_witness)
        object.__setattr__(self, "_pari_certificates", certificates)
        object.__setattr__(self, "_receipt", receipt)

    @classmethod
    def hilbert(
        cls,
        left_space: object,
        right_space: object | None = None,
        *,
        place: object | None = None,
        assumptions: Sequence[str] = (),
        backend: object | None = None,
    ) -> LocalPairing:
        """Construct the exact ``mu_2`` Hilbert pairing.

        Rational ``Q_2``, real, and zero-dimensional complex pairings replay
        portably.  Other pinned number-field completions use one closed PARI
        operation per ordered basis pair and retain every pinned-PARI
        certificate in row-major order.
        """

        resolved_right = left_space if right_space is None else right_space
        resolved_place = place if place is not None else getattr(left_space, "place", None)
        if resolved_place is None:
            raise ArithmeticError("Hilbert pairing requires an exact place")
        if prime_of(left_space) != 2 or prime_of(resolved_right) != 2:
            raise UnsupportedArithmeticOperation(
                "automatic Hilbert pairing is supported only for p=2"
            )
        try:
            matrix, witness = _rational_hilbert_witness(
                left_space,
                resolved_right,
                resolved_place,
            )
        except UnsupportedArithmeticOperation:
            matrix, certificates, backend_assumptions = _pari_hilbert_witness(
                left_space,
                resolved_right,
                resolved_place,
                backend=backend,
            )
            return cls(
                left_space,
                resolved_right,
                matrix,
                place=resolved_place,
                assumptions=normalized_assumptions(assumptions, backend_assumptions),
                pari_certificates=certificates,
            )
        return cls(
            left_space,
            resolved_right,
            matrix,
            place=resolved_place,
            assumptions=assumptions,
            pairing_witness=witness,
        )

    @property
    def receipt(self) -> ArithmeticReceipt:
        return self._receipt

    @property
    def prime(self) -> int:
        return self.matrix.field.p

    @property
    def is_perfect(self) -> bool:
        return self.matrix.nrows == self.matrix.ncols == rank(self.matrix)

    @property
    def perfect(self) -> bool:
        return self.is_perfect

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    def pair(self, left: object, right: object) -> int:
        left_coordinates = coordinates_of(
            left,
            field=self.matrix.field,
            length=self.matrix.nrows,
            name="left pairing vector",
        )
        right_coordinates = coordinates_of(
            right,
            field=self.matrix.field,
            length=self.matrix.ncols,
            name="right pairing vector",
        )
        image = self.matrix.matvec(right_coordinates)
        return (
            sum(
                coefficient * value
                for coefficient, value in zip(left_coordinates, image, strict=True)
            )
            % self.prime
        )

    def require_perfect(self) -> None:
        self.verify()
        if (
            not self.is_perfect
            or self.completeness is not Completeness.COMPLETE
            or not verified_complete(self)
        ):
            raise ArithmeticError("dual Selmer requires a certified perfect local pairing")

    def right_orthogonal(self, condition: LocalCondition) -> LocalCondition:
        if identity_of(condition.space, role="local-h1-space") != identity_of(
            self.left_space, role="local-h1-space"
        ):
            raise ArithmeticError("condition is not in the left pairing space")
        self.require_perfect()
        orthogonal = nullspace(condition.subspace.basis_matrix @ self.matrix)
        completeness = (
            Completeness.COMPLETE
            if condition.completeness is Completeness.COMPLETE
            and self.completeness is Completeness.COMPLETE
            else Completeness.CANDIDATE
        )
        context = merge_proof_context(
            condition,
            self,
            completeness=completeness,
        )
        return local_condition(
            self.right_space,
            orthogonal,
            place=self.place,
            proof_context=context,
            proving_certificates=evidence_from_sources(condition, self),
        )

    def left_orthogonal(self, condition: LocalCondition) -> LocalCondition:
        if identity_of(condition.space, role="local-h1-space") != identity_of(
            self.right_space, role="local-h1-space"
        ):
            raise ArithmeticError("condition is not in the right pairing space")
        self.require_perfect()
        orthogonal = nullspace(condition.subspace.basis_matrix @ self.matrix.transpose())
        completeness = (
            Completeness.COMPLETE
            if condition.completeness is Completeness.COMPLETE
            and self.completeness is Completeness.COMPLETE
            else Completeness.CANDIDATE
        )
        context = merge_proof_context(condition, self, completeness=completeness)
        return local_condition(
            self.left_space,
            orthogonal,
            place=self.place,
            proof_context=context,
            proving_certificates=evidence_from_sources(condition, self),
        )

    def verify(self) -> VerificationReport:
        if self.matrix.shape != (
            dimension_of(self.left_space),
            dimension_of(self.right_space),
        ):
            raise ArithmeticError("pairing matrix no longer matches its spaces")
        expected = ArithmeticReceipt.create(
            "local-pairing",
            {
                **matrix_payload(self.matrix),
                "left_space_id": identity_of(self.left_space, role="local-h1-space"),
                "right_space_id": identity_of(self.right_space, role="local-h1-space"),
                "place_id": identity_of(self.place, role="place"),
                "pairing_witness": self.pairing_witness,
                "perfect": self.is_perfect,
            },
            context=self.proof_context,
            evidence=evidence_from_sources(
                self.left_space,
                self.right_space,
                *self._pari_certificates,
            ),
        )
        if expected != self.receipt:
            raise ArithmeticError("local-pairing receipt is not bound to the object")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "left_space_id": identity_of(self.left_space, role="local-h1-space"),
            "matrix": self.matrix.to_canonical_data(),
            "pairing_witness": cast(CanonicalJSON, self.pairing_witness),
            "perfect": self.is_perfect,
            "place_id": identity_of(self.place, role="place"),
            "proof_context": self.proof_context.to_canonical_data(),
            "receipt_id": self.receipt.certificate_id,
            "right_space_id": identity_of(self.right_space, role="local-h1-space"),
            "type": "arbogast.local_pairing",
        }


@dataclass(frozen=True, slots=True)
class _DualLocalization(CanonicalObject):
    domain: object
    codomain: object
    place: object
    matrix: DenseMatrix
    proof_context: ProofContext

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "codomain_id": identity_of(self.codomain, role="local-h1-space"),
            "domain_id": identity_of(self.domain, role="global-space"),
            "matrix": self.matrix.to_canonical_data(),
            "place_id": identity_of(self.place, role="place"),
            "proof_context": self.proof_context.to_canonical_data(),
            "type": "arbogast.dual_localization",
        }


@dataclass(frozen=True, slots=True, init=False)
class DualSelmerResult(ArithmeticSemanticResult, CanonicalObject):
    """A dual Selmer result after replaying local perfectness and orthogonality."""

    primal_problem: SelmerProblem
    dual_problem: SelmerProblem
    cartier_dual: CartierDual
    pairings: tuple[LocalPairing, ...]
    selmer_result: SelmerKernel
    proof_context: ProofContext
    _receipt: ArithmeticReceipt

    def __init__(
        self,
        primal_problem: SelmerProblem,
        dual_problem: SelmerProblem,
        cartier_dual: CartierDual,
        pairings: tuple[LocalPairing, ...],
        selmer_result: SelmerKernel,
        proof_context: ProofContext,
    ) -> None:
        evidence = _dual_evidence(
            primal_problem,
            dual_problem,
            cartier_dual,
            pairings,
            selmer_result,
        )
        payload = _dual_payload(
            primal_problem,
            dual_problem,
            cartier_dual,
            pairings,
            selmer_result,
            evidence_ids=tuple(item.certificate_id for item in evidence),
        )
        receipt = ArithmeticReceipt.create(
            "dual-selmer",
            payload,
            context=proof_context,
            evidence=evidence,
        )
        object.__setattr__(self, "primal_problem", primal_problem)
        object.__setattr__(self, "dual_problem", dual_problem)
        object.__setattr__(self, "cartier_dual", cartier_dual)
        object.__setattr__(self, "pairings", pairings)
        object.__setattr__(self, "selmer_result", selmer_result)
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
    def dimension(self) -> int:
        return self.selmer_result.dimension

    @property
    def basis(self) -> tuple[tuple[int, ...], ...]:
        return self.selmer_result.basis

    @property
    def group(self) -> SelmerKernel:
        return self.selmer_result

    def verify(self) -> VerificationReport:
        self.cartier_dual.verify()
        self.selmer_result.verify()
        for pairing, primal_condition, dual_condition in zip(
            self.pairings,
            self.primal_problem.conditions,
            self.dual_problem.conditions,
            strict=True,
        ):
            pairing.require_perfect()
            expected = nullspace(primal_condition.subspace.basis_matrix @ pairing.matrix)
            if dual_condition.subspace != expected:
                raise ArithmeticError("dual local condition is not the exact orthogonal")
        expected_receipt = ArithmeticReceipt.create(
            "dual-selmer",
            _dual_payload(
                self.primal_problem,
                self.dual_problem,
                self.cartier_dual,
                self.pairings,
                self.selmer_result,
                evidence_ids=tuple(
                    item.certificate_id
                    for item in _dual_evidence(
                        self.primal_problem,
                        self.dual_problem,
                        self.cartier_dual,
                        self.pairings,
                        self.selmer_result,
                    )
                ),
            ),
            context=self.proof_context,
            evidence=_dual_evidence(
                self.primal_problem,
                self.dual_problem,
                self.cartier_dual,
                self.pairings,
                self.selmer_result,
            ),
        )
        if expected_receipt != self.receipt:
            raise ArithmeticError("dual-Selmer receipt is not bound to the result")
        return self._verify_semantics()

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cartier_dual": self.cartier_dual.to_canonical_data(),
            "dual_problem": self.dual_problem.to_canonical_data(),
            "pairings": [pairing.to_canonical_data() for pairing in self.pairings],
            "receipt_id": self.receipt.certificate_id,
            "selmer": self.selmer_result.to_canonical_data(),
            "type": "arbogast.dual_selmer_result",
        }


def _dual_payload(
    primal_problem: SelmerProblem,
    dual_problem: SelmerProblem,
    cartier_dual: CartierDual,
    pairings: tuple[LocalPairing, ...],
    result: SelmerKernel,
    *,
    evidence_ids: tuple[str, ...],
) -> dict[str, object]:
    selmer_payload = result.receipt.payload
    return {
        **matrix_payload(result.constraint_matrix),
        "kernel_basis": result.basis,
        "global_space_id": identity_of(dual_problem.global_space, role="global-space"),
        "place_ids": tuple(identity_of(place, role="place") for place in dual_problem.places),
        "place_set_complete": dual_problem.place_set_complete,
        "dimension": result.dimension,
        "input_evidence_ids": evidence_ids,
        "global_certificate_id": selmer_payload["global_certificate_id"],
        "local_blocks": selmer_payload["local_blocks"],
        "cartier_certificate_id": cartier_dual.certificate.certificate_id,
        "pairing_certificate_ids": tuple(
            pairing.certificate.certificate_id for pairing in pairings
        ),
        "primal_condition_certificate_ids": tuple(
            condition.certificate.certificate_id for condition in primal_problem.conditions
        ),
        "dual_condition_certificate_ids": tuple(
            condition.certificate.certificate_id for condition in dual_problem.conditions
        ),
        "selmer_certificate_id": result.certificate.certificate_id,
        "orthogonality_checks": tuple(
            {
                "pairing": pairing.matrix.rows,
                "left_basis": primal.subspace.basis,
                "right_basis": dual.subspace.basis,
                "left_dimension": pairing.matrix.nrows,
                "right_dimension": pairing.matrix.ncols,
            }
            for pairing, primal, dual in zip(
                pairings,
                primal_problem.conditions,
                dual_problem.conditions,
                strict=True,
            )
        ),
    }


def _dual_evidence(
    primal_problem: SelmerProblem,
    dual_problem: SelmerProblem,
    cartier_dual: CartierDual,
    pairings: tuple[LocalPairing, ...],
    result: SelmerKernel,
) -> tuple[VerificationCertificate, ...]:
    return evidence_from_sources(
        primal_problem.global_space,
        *primal_problem.localizations,
        *primal_problem.conditions,
        dual_problem.global_space,
        *dual_problem.localizations,
        *dual_problem.conditions,
        cartier_dual,
        *pairings,
        result,
    )


def _pairing_sequence(
    pairings: object,
    places: Sequence[object],
) -> tuple[LocalPairing, ...]:
    if isinstance(pairings, Mapping):
        raw = mapping_values_in_order(pairings, places)
    elif isinstance(pairings, Sequence) and not isinstance(pairings, (str, bytes)):
        raw = tuple(pairings)
    else:
        raw = (pairings,)
    if any(not isinstance(pairing, LocalPairing) for pairing in raw):
        raise ArithmeticError("pairings must contain LocalPairing values")
    return tuple(raw)


def dual_selmer(
    primal_problem: SelmerProblem,
    dual_problem: SelmerProblem | object | None = None,
    pairings: object | None = None,
    *,
    cartier_dual: CartierDual | None = None,
) -> DualSelmerResult:
    """Compute dual Selmer only after perfectness and orthogonality replay."""

    if not isinstance(primal_problem, SelmerProblem):
        raise ArithmeticError("dual_selmer requires a constructed primal SelmerProblem")
    if (
        pairings is None
        and dual_problem is not None
        and not isinstance(dual_problem, SelmerProblem)
    ):
        pairings = dual_problem
        dual_problem = None
    if pairings is None:
        raise ArithmeticError("dual_selmer requires one certified pairing per place")
    normalized_pairings = _pairing_sequence(pairings, primal_problem.places)
    if len(normalized_pairings) != len(primal_problem.places):
        raise ArithmeticError("dual_selmer requires exactly one pairing per declared place")
    for place, pairing, condition in zip(
        primal_problem.places,
        normalized_pairings,
        primal_problem.conditions,
        strict=True,
    ):
        pairing.require_perfect()
        if identity_of(place, role="place") != identity_of(pairing.place, role="place"):
            raise ArithmeticError("dual Selmer pairing belongs to a foreign place")
        if identity_of(condition.space, role="local-h1-space") != identity_of(
            pairing.left_space, role="local-h1-space"
        ):
            raise ArithmeticError("dual Selmer pairing has the wrong primal local space")

    if cartier_dual is None:
        raise ArithmeticError("dual_selmer requires an explicit certified CartierDual M^vee(1)")
    dual_object = cartier_dual
    dual_object.verify()
    if dual_object.prime != primal_problem.prime or not verified_complete(dual_object):
        raise ArithmeticError("Cartier dual is not certified over the Selmer coefficient field")
    if isinstance(primal_problem.global_space, KummerSpace):
        if dual_object.dimension != 1 or dual_object.tate_twist != 1:
            if primal_problem.prime == 2:
                raise ArithmeticError(
                    "mu_2 Kummer Selmer requires the certified one-dimensional trivial Cartier dual"
                )
            raise ArithmeticError(
                "Kummer Selmer requires a certified one-dimensional Cartier dual M^vee(1)"
            )
        if primal_problem.prime == 2:
            identity = DenseMatrix.identity(PrimeField(2), 1)
            if any(matrix != identity for matrix in dual_object.matrices):
                raise ArithmeticError(
                    "mu_2 Kummer Selmer requires the certified trivial Cartier dual"
                )
        elif dual_object.twist_character is None:
            raise ArithmeticError(
                "odd-prime Kummer Selmer requires a certified cyclotomic character"
            )
    if dual_problem is None:
        dual_conditions = tuple(
            pairing.right_orthogonal(condition)
            for pairing, condition in zip(
                normalized_pairings,
                primal_problem.conditions,
                strict=True,
            )
        )
        dual_global = getattr(
            primal_problem.global_space,
            "dual_space",
            primal_problem.global_space,
        )
        dual_localization_values: list[object] = []
        for place, localization, pairing in zip(
            primal_problem.places,
            primal_problem._blocks,
            normalized_pairings,
            strict=True,
        ):
            same_domain = identity_of(dual_global, role="global-space") == identity_of(
                primal_problem.global_space,
                role="global-space",
            )
            same_codomain = identity_of(
                pairing.right_space,
                role="local-h1-space",
            ) == identity_of(localization.condition.space, role="local-h1-space")
            if same_domain and same_codomain:
                dual_localization_values.append(localization.localization)
            else:
                dual_localization_values.append(
                    _DualLocalization(
                        dual_global,
                        pairing.right_space,
                        place,
                        localization.matrix,
                        merge_proof_context(
                            localization,
                            pairing,
                            completeness=Completeness.CANDIDATE,
                        ),
                    )
                )
        dual_localizations = tuple(dual_localization_values)
        dual_problem = SelmerProblem(
            dual_global,
            dual_localizations,
            dual_conditions,
            places=primal_problem.places,
            place_set_complete=primal_problem.place_set_complete,
        )
    assert isinstance(dual_problem, SelmerProblem)
    if tuple(identity_of(place, role="place") for place in dual_problem.places) != tuple(
        identity_of(place, role="place") for place in primal_problem.places
    ):
        raise ArithmeticError("primal and dual Selmer problems use different place sets")
    for pairing, primal_condition, dual_condition in zip(
        normalized_pairings,
        primal_problem.conditions,
        dual_problem.conditions,
        strict=True,
    ):
        expected = nullspace(primal_condition.subspace.basis_matrix @ pairing.matrix)
        if dual_condition.subspace != expected:
            raise ArithmeticError("supplied dual condition is not the exact orthogonal")

    dual_result = selmer(dual_problem)
    complete = (
        verified_complete(primal_problem)
        and verified_complete(dual_problem)
        and verified_complete(dual_object)
        and verified_complete(dual_result)
        and all(verified_complete(pairing) for pairing in normalized_pairings)
    )
    context = merge_proof_context(
        primal_problem,
        dual_problem,
        dual_object,
        *normalized_pairings,
        completeness=Completeness.COMPLETE if complete else Completeness.CANDIDATE,
    )
    result = DualSelmerResult(
        primal_problem,
        dual_problem,
        dual_object,
        normalized_pairings,
        dual_result,
        context,
    )
    result.verify()
    return result


def cartier_dual(
    module: GaloisModule,
    *,
    dual_module: GaloisModule | None = None,
    tate_twist: int = 1,
    twist_character: Sequence[int] | None = None,
    assumptions: Sequence[str] = (),
) -> CartierDual:
    """Construct the certified pinned contragredient module ``M^vee(1)``."""

    return CartierDual(
        module,
        dual_module=dual_module,
        tate_twist=tate_twist,
        twist_character=twist_character,
        assumptions=assumptions,
    )


def local_pairing(
    left_space: object,
    right_space: object | None = None,
    matrix: DenseMatrix | Sequence[Sequence[object]] | None = None,
    *,
    place: object | None = None,
    completeness: Completeness | str | None = None,
    assumptions: Sequence[str] = (),
    backend: object | None = None,
    proof_context: ProofContext | None = None,
    pairing_witness: Mapping[str, object] | None = None,
    proving_certificate: VerificationCertificate | None = None,
    proving_certificates: Sequence[VerificationCertificate] = (),
) -> LocalPairing:
    """Construct an exact local pairing, using Hilbert symbols when no matrix is supplied."""

    resolved_right = left_space if right_space is None else right_space
    if matrix is None:
        if (
            completeness is not None
            or proof_context is not None
            or pairing_witness is not None
            or proving_certificate is not None
            or proving_certificates
        ):
            raise ArithmeticError("automatic local pairing completeness is inferred")
        return LocalPairing.hilbert(
            left_space,
            resolved_right,
            place=place,
            assumptions=assumptions,
            backend=backend,
        )
    if backend is not None:
        raise ArithmeticError("backend is accepted only for automatic Hilbert pairings")
    certificates = tuple(proving_certificates)
    if proving_certificate is not None:
        certificates = (proving_certificate, *certificates)
    return LocalPairing(
        left_space,
        resolved_right,
        matrix,
        place=place,
        completeness=completeness,
        assumptions=assumptions,
        proof_context=proof_context,
        pairing_witness=pairing_witness,
        proving_certificates=certificates,
    )


__all__ = [
    "CartierDual",
    "DualSelmerResult",
    "LocalPairing",
    "cartier_dual",
    "dual_selmer",
    "local_pairing",
]
