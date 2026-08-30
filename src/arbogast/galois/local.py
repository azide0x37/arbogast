"""Certified local Kummer cohomology and global-to-local maps."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, cast

from arbogast.backends.pari_results import PariArithmeticResult
from arbogast.cert import VerificationCertificate, default_verifiers
from arbogast.claims import Claim, ClaimGraph
from arbogast.cohom import ComplexityLimits, H1Result, h1
from arbogast.core import ValidationError
from arbogast.linalg import DenseMatrix, PrimeField

from ._common import (
    Vector,
    canonical_coordinates,
    canonical_matrix,
    canonical_snapshot,
    element_from_pari_coefficients,
    field_of,
    is_finite_place,
    is_infinite_place,
    is_rational_field,
    rational_value,
    snapshot_id,
)
from .certificate import LocalH1Receipt, LocalizationReceipt
from .kummer import KummerClass, KummerSpace
from .proof import Completeness, ProofContext, Unsupported, VerificationRequirement


def _snapshot_mapping(value: object, name: str) -> Mapping[str, object]:
    snapshot = canonical_snapshot(value)
    if not isinstance(snapshot, dict):
        raise TypeError(f"{name} canonical form must be an object")
    return cast(Mapping[str, object], snapshot)


def _basis_snapshot(value: object) -> object:
    return canonical_snapshot(value)


def _portable_requirement() -> VerificationRequirement:
    return VerificationRequirement.portable_python(
        "galois.local_h1.v1",
        capabilities=("local-mu2-squareclasses", "rational-local-squareclasses"),
    )


def _portable_localization_requirement() -> VerificationRequirement:
    return VerificationRequirement.portable_python(
        "galois.localization.v1",
        capabilities=(
            "rational-mu2-localization",
            "complex-mu2-zero-localization",
            "real-sign-mu2-localization",
        ),
    )


def _context(
    proof_context: ProofContext | None,
    completeness: Completeness | str | None,
    assumptions: Iterable[str],
    *,
    automatic: bool,
) -> ProofContext:
    supplied_assumptions = tuple(assumptions)
    if proof_context is not None:
        if supplied_assumptions:
            raise ValueError("assumptions must be carried by the supplied proof_context")
        if completeness is not None and proof_context.completeness is not Completeness(
            completeness
        ):
            raise ValueError("completeness disagrees with proof_context")
        return proof_context
    selected = (
        Completeness.COMPLETE
        if automatic and completeness is None
        else Completeness.CANDIDATE
        if completeness is None
        else Completeness(completeness)
    )
    return ProofContext(supplied_assumptions, (_portable_requirement(),), selected)


@dataclass(frozen=True, slots=True)
class LocalH1Space:
    """A genuine finite presentation of ``H^1(K_v, mu_p)``."""

    place: Any
    prime: int
    basis_representatives: tuple[Any, ...]
    proof_context: ProofContext
    presentation: Mapping[str, object]
    proving_certificates: tuple[VerificationCertificate, ...] = ()

    def __post_init__(self) -> None:
        from arbogast.linalg import PrimeField

        PrimeField(self.prime)
        if not (is_finite_place(self.place) or is_infinite_place(self.place)):
            raise TypeError("local H1 requires an exact finite or infinite place")
        if not isinstance(self.proof_context, ProofContext):
            raise TypeError("proof_context must be a ProofContext")
        certificates = tuple(self.proving_certificates)
        if any(not isinstance(item, VerificationCertificate) for item in certificates):
            raise TypeError("proving_certificates must contain VerificationCertificate values")
        if len({item.certificate_id for item in certificates}) != len(certificates):
            raise ValidationError("proving_certificates must be unique")
        basis = tuple(self.basis_representatives)
        basis_ids = tuple(snapshot_id(item) for item in basis)
        if len(set(basis_ids)) != len(basis_ids):
            raise ValidationError("local squareclass basis representatives must be distinct")
        place_field = field_of(self.place)
        for representative in basis:
            if field_of(representative) != place_field:
                raise ValidationError(
                    "local squareclass representative belongs to a different pinned field"
                )
            if bool(getattr(representative, "is_zero", False)):
                raise ValidationError("zero has no local squareclass")
        if self.proof_context.complete and not self.presentation:
            raise ValidationError("complete local H1 requires a presentation witness")
        object.__setattr__(self, "basis_representatives", basis)
        object.__setattr__(self, "presentation", dict(self.presentation))
        object.__setattr__(self, "proving_certificates", certificates)
        self.receipt.verify()

    @property
    def dimension(self) -> int:
        return len(self.basis_representatives)

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def basis(self) -> tuple[LocalH1Class, ...]:
        return tuple(
            self.from_coordinates(tuple(1 if row == column else 0 for row in range(self.dimension)))
            for column in range(self.dimension)
        )

    def zero(self) -> LocalH1Class:
        return self.from_coordinates((0,) * self.dimension)

    def from_coordinates(self, coordinates: Iterable[int]) -> LocalH1Class:
        return LocalH1Class(
            self,
            canonical_coordinates(coordinates, self.dimension, self.prime),
        )

    @property
    def receipt(self) -> LocalH1Receipt:
        return LocalH1Receipt(
            object_type="space",
            place=_snapshot_mapping(self.place, "place"),
            place_id=snapshot_id(self.place),
            prime=self.prime,
            basis=tuple(_basis_snapshot(item) for item in self.basis_representatives),
            basis_ids=tuple(snapshot_id(item) for item in self.basis_representatives),
            coordinates=None,
            proof_context=self.proof_context.to_dict(),
            presentation=self.presentation,
            proving_certificates=tuple(item.to_dict() for item in self.proving_certificates),
        )

    @property
    def content_id(self) -> str:
        return self.receipt.content_id

    @property
    def certificate(self) -> VerificationCertificate:
        from .semantic import verification_certificate_for

        return verification_certificate_for(self.receipt)

    def verify(self) -> bool:
        for value in (self.place, *self.basis_representatives):
            verifier = getattr(value, "verify", None)
            if callable(verifier) and verifier() is not True:
                raise ValidationError("a local-H1 substrate object failed exact verification")
        self.receipt.verify()
        default_verifiers.verify(self.certificate)
        return True

    def claim(self) -> Claim:
        from .semantic import claim_for

        return claim_for(self.receipt)

    def claim_graph(self) -> ClaimGraph:
        from .semantic import claim_graph_for

        return claim_graph_for(self.receipt)

    def to_canonical(self) -> dict[str, object]:
        return self.receipt.to_dict()


@dataclass(frozen=True, slots=True)
class LocalH1Class:
    """One local squareclass, optionally carrying its localization witness."""

    space: LocalH1Space
    coordinates: Vector
    localization: LocalizationMap | None = field(default=None, repr=False, compare=False)
    source_coordinates: Vector | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "coordinates",
            canonical_coordinates(self.coordinates, self.space.dimension, self.space.prime),
        )
        if (self.localization is None) != (self.source_coordinates is None):
            raise ValueError("localized classes require both map and source coordinates")

    @property
    def is_zero(self) -> bool:
        return not any(self.coordinates)

    @property
    def receipt(self) -> LocalH1Receipt:
        space = self.space.receipt
        return LocalH1Receipt(
            object_type="class",
            place=space.place.to_dict(),
            place_id=space.place_id,
            prime=space.prime,
            basis=space.basis,
            basis_ids=space.basis_ids,
            coordinates=self.coordinates,
            proof_context=space.proof_context.to_dict(),
            presentation=space.presentation.to_dict(),
            proving_certificates=tuple(item.to_dict() for item in space.proving_certificates),
        )

    @property
    def proving_receipt(self) -> LocalH1Receipt | LocalizationReceipt:
        if self.localization is None or self.source_coordinates is None:
            return self.receipt
        return self.localization.receipt_for_class(self.source_coordinates, self.coordinates)

    @property
    def content_id(self) -> str:
        return self.proving_receipt.content_id

    @property
    def certificate(self) -> VerificationCertificate:
        from .semantic import verification_certificate_for

        return verification_certificate_for(self.proving_receipt)

    def verify(self) -> bool:
        self.space.verify()
        self.receipt.verify()
        if self.localization is not None and self.source_coordinates is not None:
            self.localization.verify()
            expected = self.localization.matrix.matvec(self.source_coordinates)
            if expected != self.coordinates:
                raise ValidationError("localized class coordinates do not replay")
        default_verifiers.verify(self.certificate)
        return True

    def claim(self) -> Claim:
        from .semantic import claim_for

        return claim_for(self.proving_receipt)

    def claim_graph(self) -> ClaimGraph:
        from .semantic import claim_graph_for

        return claim_graph_for(self.proving_receipt)

    def __add__(self, other: LocalH1Class) -> LocalH1Class:
        if self.space.content_id != other.space.content_id:
            raise ValueError("local H1 classes belong to different spaces")
        return self.space.from_coordinates(
            (left + right) % self.space.prime
            for left, right in zip(self.coordinates, other.coordinates, strict=True)
        )

    def __rmul__(self, scalar: int) -> LocalH1Class:
        return self.space.from_coordinates(
            scalar * value % self.space.prime for value in self.coordinates
        )

    def to_canonical(self) -> dict[str, object]:
        return self.proving_receipt.to_dict()


def local_h1_class(
    space: LocalH1Space,
    coordinates: Iterable[int],
) -> LocalH1Class:
    """Construct one class in a pinned genuine local cohomology space."""

    if not isinstance(space, LocalH1Space):
        raise TypeError("local_h1_class space must be a LocalH1Space")
    return space.from_coordinates(coordinates)


@dataclass(frozen=True, slots=True)
class LocalizationMap:
    """A certified linear localization map to genuine local cohomology."""

    domain: KummerSpace
    codomain: LocalH1Space
    matrix: DenseMatrix
    proof_context: ProofContext = field(default_factory=ProofContext)
    localization_witness: Mapping[str, object] = field(default_factory=dict)
    proving_certificates: tuple[VerificationCertificate, ...] = ()

    def __post_init__(self) -> None:
        matrix = canonical_matrix(
            self.matrix.rows,
            prime=self.domain.prime,
            nrows=self.codomain.dimension,
            ncols=self.domain.dimension,
        )
        if self.domain.prime != self.codomain.prime:
            raise ValidationError("localization endpoint primes differ")
        if snapshot_id(self.codomain.place) not in {
            snapshot_id(place) for place in self.domain.places
        }:
            raise ValidationError("localization place is not in the declared Kummer place set")
        if not isinstance(self.proof_context, ProofContext):
            raise TypeError("proof_context must be a ProofContext")
        certificates = tuple(self.proving_certificates)
        if any(not isinstance(item, VerificationCertificate) for item in certificates):
            raise TypeError("proving_certificates must contain VerificationCertificate values")
        if len({item.certificate_id for item in certificates}) != len(certificates):
            raise ValidationError("proving_certificates must be unique")
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "localization_witness", dict(self.localization_witness))
        object.__setattr__(self, "proving_certificates", certificates)
        self.receipt.verify()

    @property
    def place(self) -> Any:
        return self.codomain.place

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def receipt(self) -> LocalizationReceipt:
        return LocalizationReceipt(
            domain=self.domain.receipt,
            codomain=self.codomain.receipt,
            matrix=self.matrix.rows,
            proof_context=self.proof_context.to_dict(),
            localization_witness=self.localization_witness,
            proving_certificates=tuple(item.to_dict() for item in self.proving_certificates),
        )

    def receipt_for_class(
        self,
        source_coordinates: Vector,
        image_coordinates: Vector,
    ) -> LocalizationReceipt:
        return LocalizationReceipt(
            domain=self.domain.receipt,
            codomain=self.codomain.receipt,
            matrix=self.matrix.rows,
            proof_context=self.proof_context.to_dict(),
            localization_witness=self.localization_witness,
            proving_certificates=tuple(item.to_dict() for item in self.proving_certificates),
            source_coordinates=source_coordinates,
            image_coordinates=image_coordinates,
        )

    @property
    def content_id(self) -> str:
        return self.receipt.content_id

    @property
    def certificate(self) -> VerificationCertificate:
        from .semantic import verification_certificate_for

        return verification_certificate_for(self.receipt)

    def apply(self, value: KummerClass | Iterable[int]) -> LocalH1Class:
        if isinstance(value, KummerClass):
            if value.space.content_id != self.domain.content_id:
                raise ValueError("Kummer class belongs to a different localization domain")
            coordinates = value.coordinates
        else:
            coordinates = canonical_coordinates(value, self.domain.dimension, self.domain.prime)
        image = self.matrix.matvec(coordinates)
        return LocalH1Class(self.codomain, image, self, coordinates)

    def verify(self) -> bool:
        self.domain.verify()
        self.codomain.verify()
        self.receipt.verify()
        default_verifiers.verify(self.certificate)
        return True

    def _verified_completeness(self) -> bool:
        return self.proof_context.complete and self.verify()

    def claim(self) -> Claim:
        from .semantic import claim_for

        return claim_for(self.receipt)

    def claim_graph(self) -> ClaimGraph:
        from .semantic import claim_graph_for

        return claim_graph_for(self.receipt)

    def to_canonical(self) -> dict[str, object]:
        return self.receipt.to_dict()


def _nonsquare_mod_prime(prime: int) -> int:
    return next(
        value for value in range(2, prime) if pow(value, (prime - 1) // 2, prime) == prime - 1
    )


def _automatic_local_basis(place: Any) -> tuple[tuple[Any, ...], dict[str, object]] | None:
    field = cast(Any, field_of(place))
    if field is None:
        return None
    basis: tuple[Any, ...]
    if is_infinite_place(place):
        kind = getattr(getattr(place, "kind", None), "value", getattr(place, "kind", None))
        if kind == "real":
            basis = (field.element(-1),)
            method = "portable-real-mu2-v1"
        elif kind == "complex":
            basis = ()
            method = "portable-complex-mu2-v1"
        else:
            return None
    elif is_rational_field(field):
        rational_prime = int(place.rational_prime)
        if rational_prime == 2:
            basis = (field.element(-1), field.element(2), field.element(5))
            method = "portable-q2-squareclasses-v1"
        else:
            nonsquare = _nonsquare_mod_prime(rational_prime)
            basis = (field.element(rational_prime), field.element(nonsquare))
            method = "portable-odd-qadic-squareclasses-v1"
    else:
        return None
    presentation = {
        "method": method,
        "place_id": snapshot_id(place),
        "basis_ids": tuple(snapshot_id(item) for item in basis),
        "perfect_kummer_identification": True,
    }
    return basis, presentation


def _pari_local_presentation(
    place: Any,
    *,
    backend: Any | None,
    search_bound: int,
    max_candidates: int,
) -> (
    tuple[
        tuple[Any, ...],
        ProofContext,
        dict[str, object],
        tuple[VerificationCertificate, ...],
    ]
    | Unsupported
    | PariArithmeticResult
):
    from arbogast.backends.base import BackendUnavailableError
    from arbogast.backends.pari import PariBackend
    from arbogast.backends.pari_protocol import PariBackendError
    from arbogast.backends.pari_results import PariOutcome

    field = cast(Any, field_of(place))
    adapter = PariBackend() if backend is None else backend
    try:
        result = adapter.local_squareclasses(
            field,
            place,
            search_bound=search_bound,
            max_candidates=max_candidates,
        )
    except (BackendUnavailableError, PariBackendError) as error:
        return Unsupported(
            "galois.local_h1",
            f"PARI could not certify local squareclasses: {error}",
            requested={"place_id": snapshot_id(place), "prime": 2},
            supported=("pinned PARI >=2.15.5,<2.18.0", "certified supplied presentation"),
        )
    if getattr(result, "outcome", None) is not PariOutcome.SUCCESS:
        if not isinstance(result, PariArithmeticResult):
            raise TypeError("PARI returned an invalid non-success arithmetic result")
        return result
    payload_value = getattr(result, "payload", None)
    payload_to_dict = getattr(payload_value, "to_dict", None)
    payload = payload_to_dict() if callable(payload_to_dict) else payload_value
    if not isinstance(payload, Mapping):
        raise TypeError("PARI local-squareclass payload must be a mapping")
    raw_representatives = payload.get("representatives")
    if isinstance(raw_representatives, (str, bytes)) or not isinstance(
        raw_representatives, Iterable
    ):
        raise TypeError("PARI local representatives must be iterable")
    basis = tuple(
        element_from_pari_coefficients(
            field,
            representative,
            f"PARI local representative[{index}]",
        )
        for index, representative in enumerate(raw_representatives)
    )
    context_value = result.proof_context()
    if not isinstance(context_value, ProofContext):
        raise TypeError("PARI result returned an invalid proof context")
    certificate = getattr(result, "certificate", None)
    if not isinstance(certificate, VerificationCertificate):
        raise ValueError("successful PARI local arithmetic lacks central proof evidence")
    presentation: dict[str, object] = {
        "method": "pari-local-squareclasses-v1",
        "place_id": snapshot_id(place),
        "basis_ids": tuple(snapshot_id(item) for item in basis),
        "expected_dimension": payload.get("dimension"),
    }
    return basis, context_value, presentation, (certificate,)


def local_h1(
    place: Any,
    *,
    prime: int = 2,
    basis: Iterable[Any] | None = None,
    completeness: Completeness | str | None = None,
    proof_context: ProofContext | None = None,
    presentation: Mapping[str, object] | None = None,
    assumptions: Iterable[str] = (),
    proving_certificate: VerificationCertificate | None = None,
    proving_certificates: Iterable[VerificationCertificate] = (),
    backend: Any | None = None,
    search_bound: int = 4,
    max_candidates: int = 4096,
) -> LocalH1Space | Unsupported | PariArithmeticResult:
    """Construct genuine ``H^1(K_v, mu_p)`` from a certified presentation."""

    automatic = basis is None
    if automatic and prime != 2:
        return Unsupported(
            "galois.local_h1",
            "automatic p>2 local arithmetic is deferred in Arbogast 0.2",
            requested={"prime": prime, "place_id": snapshot_id(place)},
            supported=("automatic mu2 over pinned fields", "certified presentation"),
        )
    discovered = _automatic_local_basis(place) if automatic else None
    if automatic and discovered is None and is_finite_place(place):
        supplied_assumptions = tuple(assumptions)
        supplied_certificates = tuple(proving_certificates)
        if (
            proof_context is not None
            or completeness is not None
            or supplied_assumptions
            or presentation is not None
            or proving_certificate is not None
            or supplied_certificates
        ):
            raise ValueError(
                "automatic PARI local arithmetic owns its proof context and nested evidence"
            )
        pari_discovered = _pari_local_presentation(
            place,
            backend=backend,
            search_bound=search_bound,
            max_candidates=max_candidates,
        )
        if isinstance(pari_discovered, Unsupported | PariArithmeticResult):
            return pari_discovered
        pari_basis, pari_context, pari_presentation, pari_certificates = pari_discovered
        return LocalH1Space(
            place,
            prime,
            pari_basis,
            pari_context,
            pari_presentation,
            pari_certificates,
        )
    if automatic and discovered is None:
        return Unsupported(
            "galois.local_h1",
            "this completion requires a certified local squareclass presentation",
            requested={"prime": prime, "place_id": snapshot_id(place)},
            supported=("automatic mu2 over pinned fields", "certified presentation"),
        )
    normalized_basis, normalized_presentation = (
        discovered if discovered is not None else (tuple(basis or ()), dict(presentation or {}))
    )
    context = _context(
        proof_context,
        completeness,
        assumptions,
        automatic=automatic,
    )
    nested_certificates = tuple(proving_certificates)
    if proving_certificate is not None:
        nested_certificates = (proving_certificate, *nested_certificates)
    return LocalH1Space(
        place,
        prime,
        tuple(normalized_basis),
        context,
        normalized_presentation,
        nested_certificates,
    )


def _valuation(value: int, prime: int) -> tuple[int, int]:
    exponent = 0
    remaining = abs(value)
    while remaining and remaining % prime == 0:
        exponent += 1
        remaining //= prime
    return exponent, remaining


def _q2_coordinates(value: Fraction) -> Vector:
    if value == 0:
        raise ValueError("zero has no local squareclass")
    numerator_v, odd_numerator = _valuation(value.numerator, 2)
    denominator_v, odd_denominator = _valuation(value.denominator, 2)
    unit = odd_numerator * pow(odd_denominator, -1, 8) % 8
    if value < 0:
        unit = -unit % 8
    unit_coordinates = {1: (0, 0), 7: (1, 0), 5: (0, 1), 3: (1, 1)}
    minus_one, five = unit_coordinates[unit]
    return (minus_one, (numerator_v - denominator_v) % 2, five)


def _odd_qadic_coordinates(value: Fraction, prime: int) -> Vector:
    if value == 0:
        raise ValueError("zero has no local squareclass")
    numerator_v, unit_numerator = _valuation(value.numerator, prime)
    denominator_v, unit_denominator = _valuation(value.denominator, prime)
    unit = unit_numerator * pow(unit_denominator, -1, prime) % prime
    if value < 0:
        unit = -unit % prime
    nonsquare = 0 if pow(unit, (prime - 1) // 2, prime) == 1 else 1
    return ((numerator_v - denominator_v) % 2, nonsquare)


def _polynomial_interval(
    coefficients: tuple[Fraction, ...],
    lower: Fraction,
    upper: Fraction,
) -> tuple[Fraction, Fraction]:
    interval_lower = Fraction(0)
    interval_upper = Fraction(0)
    for coefficient in reversed(coefficients):
        products = (
            interval_lower * lower,
            interval_lower * upper,
            interval_upper * lower,
            interval_upper * upper,
        )
        interval_lower = min(products) + coefficient
        interval_upper = max(products) + coefficient
    return interval_lower, interval_upper


def _real_sign_witness(
    generator: Any,
    place: Any,
    *,
    max_refinements: int = 4096,
) -> tuple[int, dict[str, object]] | None:
    from .places import _sturm_sequence, _variations_at

    coefficients = getattr(generator, "coefficients", None)
    field = cast(Any, field_of(generator))
    isolation = getattr(place, "isolation", None)
    if (
        not isinstance(coefficients, tuple)
        or not coefficients
        or not all(isinstance(value, Fraction) for value in coefficients)
        or field is None
        or field != field_of(place)
        or not isinstance(isolation, tuple)
        or len(isolation) != 2
    ):
        return None
    lower, upper = isolation
    sturm = _sturm_sequence(field.defining_polynomial)
    lower_variations = _variations_at(sturm, lower)
    upper_variations = _variations_at(sturm, upper)
    if lower_variations - upper_variations != 1:
        return None
    for _ in range(max_refinements + 1):
        value_lower, value_upper = _polynomial_interval(coefficients, lower, upper)
        if value_lower > 0 or value_upper < 0:
            sign = 1 if value_lower > 0 else -1
            return sign, {
                "generator_id": snapshot_id(generator),
                "isolation": (
                    (lower.numerator, lower.denominator),
                    (upper.numerator, upper.denominator),
                ),
                "sign": sign,
            }
        midpoint = (lower + upper) / 2
        midpoint_variations = _variations_at(sturm, midpoint)
        if lower_variations - midpoint_variations == 1:
            upper = midpoint
            upper_variations = midpoint_variations
        elif midpoint_variations - upper_variations == 1:
            lower = midpoint
            lower_variations = midpoint_variations
        else:
            return None
    return None


def _real_sign_witnesses(
    domain: KummerSpace,
    codomain: LocalH1Space,
) -> tuple[dict[str, object], ...] | None:
    place = codomain.place
    kind = getattr(getattr(place, "kind", None), "value", getattr(place, "kind", None))
    if (
        domain.prime != 2
        or kind != "real"
        or codomain.dimension != 1
        or codomain.presentation.get("method") != "portable-real-mu2-v1"
    ):
        return None
    results = tuple(_real_sign_witness(generator, place) for generator in domain.generators)
    if any(result is None for result in results):
        return None
    return tuple(cast(tuple[int, dict[str, object]], result)[1] for result in results)


def _automatic_localization_matrix(
    domain: KummerSpace,
    codomain: LocalH1Space,
) -> DenseMatrix | None:
    if domain.prime != 2:
        return None
    place = codomain.place
    if is_infinite_place(place):
        kind = getattr(getattr(place, "kind", None), "value", getattr(place, "kind", None))
        if kind == "complex":
            if codomain.dimension != 0 or codomain.basis_representatives:
                return None
            return DenseMatrix(PrimeField(2), (), ncols=domain.dimension)
        if kind == "real" and not is_rational_field(domain.field):
            witnesses = _real_sign_witnesses(domain, codomain)
            if witnesses is None:
                return None
            return DenseMatrix(
                PrimeField(2),
                (tuple(int(witness["sign"] == -1) for witness in witnesses),),
                ncols=domain.dimension,
            )
    if not is_rational_field(domain.field):
        return None
    values = tuple(rational_value(generator) for generator in domain.generators)
    if any(value is None for value in values):
        return None
    columns: list[Vector] = []
    if is_infinite_place(place):
        kind = getattr(getattr(place, "kind", None), "value", getattr(place, "kind", None))
        if kind == "complex":
            columns = [() for _ in values]
        elif kind == "real":
            columns = [(1 if cast(Fraction, value) < 0 else 0,) for value in values]
        else:
            return None
    else:
        rational_prime = int(place.rational_prime)
        if rational_prime == 2:
            columns = [_q2_coordinates(cast(Fraction, value)) for value in values]
        else:
            columns = [
                _odd_qadic_coordinates(cast(Fraction, value), rational_prime) for value in values
            ]
    return DenseMatrix.from_columns(
        PrimeField(domain.prime),
        columns,
        nrows=codomain.dimension,
    )


def _pari_localization_presentation(
    domain: KummerSpace,
    codomain: LocalH1Space,
    *,
    backend: Any | None,
    search_bound: int,
    max_candidates: int,
) -> (
    tuple[
        DenseMatrix,
        ProofContext,
        dict[str, object],
        tuple[VerificationCertificate, ...],
    ]
    | Unsupported
    | PariArithmeticResult
):
    from arbogast.backends.base import BackendUnavailableError
    from arbogast.backends.pari import PariBackend
    from arbogast.backends.pari_protocol import PariBackendError
    from arbogast.backends.pari_results import PariOutcome

    if not is_finite_place(codomain.place):
        return Unsupported(
            "galois.localize",
            "automatic non-rational localization currently requires a finite place",
            requested={"place_id": snapshot_id(codomain.place)},
            supported=("finite-place PARI localization", "certified supplied matrix"),
        )
    adapter = PariBackend() if backend is None else backend
    try:
        result = adapter.localization_matrix(
            domain.field,
            domain.generators,
            codomain.place,
            search_bound=search_bound,
            max_candidates=max_candidates,
        )
    except (BackendUnavailableError, PariBackendError) as error:
        return Unsupported(
            "galois.localize",
            f"PARI could not certify the localization matrix: {error}",
            requested={
                "domain": domain.content_id,
                "place_id": snapshot_id(codomain.place),
            },
            supported=("pinned PARI >=2.15.5,<2.18.0", "certified supplied matrix"),
        )
    if getattr(result, "outcome", None) is not PariOutcome.SUCCESS:
        if not isinstance(result, PariArithmeticResult):
            raise TypeError("PARI returned an invalid non-success arithmetic result")
        return result
    payload_value = getattr(result, "payload", None)
    payload_to_dict = getattr(payload_value, "to_dict", None)
    payload = payload_to_dict() if callable(payload_to_dict) else payload_value
    if not isinstance(payload, Mapping):
        raise TypeError("PARI localization payload must be a mapping")
    matrix = canonical_matrix(
        cast(Iterable[Iterable[int]], payload.get("matrix")),
        prime=domain.prime,
        nrows=codomain.dimension,
        ncols=domain.dimension,
    )
    context_value = result.proof_context()
    if not isinstance(context_value, ProofContext):
        raise TypeError("PARI result returned an invalid proof context")
    certificate = getattr(result, "certificate", None)
    if not isinstance(certificate, VerificationCertificate):
        raise ValueError("successful PARI localization lacks central proof evidence")
    witness: dict[str, object] = {
        "method": "pari-localization-matrix-v1",
        "domain_receipt": domain.receipt.content_id,
        "codomain_receipt": codomain.receipt.content_id,
    }
    return matrix, context_value, witness, (certificate,)


def localize(
    source: KummerSpace | KummerClass,
    target: LocalH1Space | Any,
    *,
    matrix: Iterable[Iterable[int]] | DenseMatrix | None = None,
    completeness: Completeness | str | None = None,
    proof_context: ProofContext | None = None,
    localization_witness: Mapping[str, object] | None = None,
    assumptions: Iterable[str] = (),
    proving_certificate: VerificationCertificate | None = None,
    proving_certificates: Iterable[VerificationCertificate] = (),
    backend: Any | None = None,
    search_bound: int = 4,
    max_candidates: int = 4096,
) -> LocalizationMap | LocalH1Class | Unsupported | PariArithmeticResult:
    """Build or apply localization, retaining the exact matrix witness."""

    domain = source.space if isinstance(source, KummerClass) else source
    if not isinstance(domain, KummerSpace):
        raise TypeError("source must be a KummerSpace or KummerClass")
    if isinstance(target, LocalH1Space):
        codomain: LocalH1Space | Unsupported | PariArithmeticResult = target
    else:
        codomain = local_h1(
            target,
            prime=domain.prime,
            backend=backend,
            search_bound=search_bound,
            max_candidates=max_candidates,
        )
    if isinstance(codomain, Unsupported | PariArithmeticResult):
        return codomain
    automatic = matrix is None
    pari_context: ProofContext | None = None
    pari_witness: dict[str, object] | None = None
    pari_certificates: tuple[VerificationCertificate, ...] = ()
    if automatic:
        selected_matrix = _automatic_localization_matrix(domain, codomain)
        if selected_matrix is None:
            supplied_automatic_assumptions = tuple(assumptions)
            supplied_automatic_certificates = tuple(proving_certificates)
            if (
                proof_context is not None
                or completeness is not None
                or supplied_automatic_assumptions
                or localization_witness is not None
                or proving_certificate is not None
                or supplied_automatic_certificates
            ):
                raise ValueError(
                    "automatic PARI localization owns its proof context and nested evidence"
                )
            pari_discovered = _pari_localization_presentation(
                domain,
                codomain,
                backend=backend,
                search_bound=search_bound,
                max_candidates=max_candidates,
            )
            if isinstance(pari_discovered, Unsupported | PariArithmeticResult):
                return pari_discovered
            selected_matrix, pari_context, pari_witness, pari_certificates = pari_discovered
    elif isinstance(matrix, DenseMatrix):
        selected_matrix = matrix
    else:
        assert matrix is not None
        selected_matrix = canonical_matrix(
            matrix,
            prime=domain.prime,
            nrows=codomain.dimension,
            ncols=domain.dimension,
        )
    supplied_assumptions = tuple(assumptions)
    if pari_context is not None:
        context = pari_context
    elif proof_context is not None:
        if supplied_assumptions:
            raise ValueError("assumptions must be carried by the supplied proof_context")
        if completeness is not None and proof_context.completeness is not Completeness(
            completeness
        ):
            raise ValueError("completeness disagrees with proof_context")
        context = proof_context
    else:
        selected_completeness = (
            Completeness.COMPLETE
            if automatic and completeness is None
            else Completeness.CANDIDATE
            if completeness is None
            else Completeness(completeness)
        )
        context = ProofContext(
            supplied_assumptions,
            (_portable_localization_requirement(),),
            selected_completeness,
        )
    witness: dict[str, object] = dict(localization_witness or {})
    if pari_witness is not None:
        witness = pari_witness
    elif automatic:
        place_kind = getattr(
            getattr(codomain.place, "kind", None),
            "value",
            getattr(codomain.place, "kind", None),
        )
        real_sign_witnesses = (
            _real_sign_witnesses(domain, codomain)
            if place_kind == "real" and not is_rational_field(domain.field)
            else None
        )
        portable_witness: dict[str, object] = {
            "method": (
                "portable-complex-zero-localization-v1"
                if place_kind == "complex"
                else "portable-real-sign-localization-v1"
                if real_sign_witnesses is not None
                else "portable-rational-localization-v1"
            ),
            "domain_receipt": domain.receipt.content_id,
            "codomain_receipt": codomain.receipt.content_id,
        }
        if real_sign_witnesses is not None:
            portable_witness["sign_witnesses"] = real_sign_witnesses
        if witness and witness != portable_witness:
            raise ValueError("localization_witness disagrees with automatic replay")
        witness = portable_witness
    nested_certificates = tuple(proving_certificates)
    if proving_certificate is not None:
        nested_certificates = (proving_certificate, *nested_certificates)
    if pari_certificates:
        nested_certificates = pari_certificates
    if nested_certificates and not witness:
        witness = {
            "method": "pari-localization-matrix-v1",
            "domain_receipt": domain.receipt.content_id,
            "codomain_receipt": codomain.receipt.content_id,
        }
    result = LocalizationMap(
        domain,
        codomain,
        selected_matrix,
        context,
        witness,
        nested_certificates,
    )
    return result.apply(source) if isinstance(source, KummerClass) else result


def decomposition_quotient_h1(
    group_or_module: Any,
    module: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> H1Result:
    """Compute finite ``H^1(D_v,M)`` without calling it continuous local H1."""

    if (
        module is None
        and hasattr(group_or_module, "quotient")
        and hasattr(group_or_module, "action_matrix")
    ):
        return h1(group_or_module.group, group_or_module, limits=limits)
    return h1(group_or_module, module, limits=limits)


__all__ = [
    "LocalH1Class",
    "LocalH1Space",
    "LocalizationMap",
    "decomposition_quotient_h1",
    "local_h1",
    "localize",
]
