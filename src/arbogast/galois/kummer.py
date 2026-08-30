"""Finite certified S-Kummer spaces over pinned number fields."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from arbogast.backends.pari_results import PariArithmeticResult
from arbogast.cert import VerificationCertificate, default_verifiers
from arbogast.claims import Claim, ClaimGraph
from arbogast.core import ValidationError

from ._common import (
    Vector,
    canonical_coordinates,
    canonical_snapshot,
    element_from_pari_coefficients,
    field_of,
    is_finite_place,
    is_infinite_place,
    is_rational_field,
    snapshot_id,
    strict_integer,
)
from .certificate import KummerReceipt
from .proof import (
    Completeness,
    ProofContext,
    Unsupported,
    VerificationRequirement,
)


def _portable_requirement() -> VerificationRequirement:
    return VerificationRequirement.portable_python(
        "galois.kummer.v1",
        capabilities=("finite-s-kummer-presentation", "rational-s-kummer"),
    )


def _proof_context(
    proof_context: ProofContext | None,
    completeness: Completeness | str | None,
    assumptions: Iterable[str],
    *,
    automatic_complete: bool,
) -> ProofContext:
    supplied_assumptions = tuple(assumptions)
    if proof_context is not None:
        if not isinstance(proof_context, ProofContext):
            raise TypeError("proof_context must be a ProofContext")
        if supplied_assumptions:
            raise ValueError("assumptions must be carried by the supplied proof_context")
        if completeness is not None and proof_context.completeness is not Completeness(
            completeness
        ):
            raise ValueError("completeness disagrees with proof_context")
        return proof_context
    selected = (
        Completeness.COMPLETE
        if automatic_complete and completeness is None
        else Completeness.CANDIDATE
        if completeness is None
        else Completeness(completeness)
    )
    return ProofContext(
        supplied_assumptions,
        (_portable_requirement(),),
        selected,
    )


def _snapshot_mapping(value: object, name: str) -> Mapping[str, object]:
    snapshot = canonical_snapshot(value)
    if not isinstance(snapshot, dict):
        raise TypeError(f"{name} canonical form must be an object")
    return cast(Mapping[str, object], snapshot)


@dataclass(frozen=True, slots=True)
class KummerSpace:
    """A finite prime-field presentation of ``K(S,p)``.

    The ordered ``generators`` are a certified basis, not merely a spanning
    family.  In 0.2 automatic arithmetic is intentionally restricted to
    ``p=2``; callers may supply an already-certified finite presentation for
    any prime.
    """

    field: Any
    places: tuple[Any, ...]
    prime: int
    generators: tuple[Any, ...]
    proof_context: ProofContext
    completeness_witness: Mapping[str, object]
    proving_certificates: tuple[VerificationCertificate, ...] = ()

    def __post_init__(self) -> None:
        from arbogast.linalg import PrimeField

        PrimeField(self.prime)
        if not isinstance(self.proof_context, ProofContext):
            raise TypeError("proof_context must be a ProofContext")
        if not hasattr(self.field, "field_id") or not hasattr(self.field, "element"):
            raise TypeError("field must be a pinned NumberField presentation")
        normalized_places = tuple(sorted(self.places, key=snapshot_id))
        if len({snapshot_id(place) for place in normalized_places}) != len(normalized_places):
            raise ValidationError("Kummer place set contains duplicates")
        for place in normalized_places:
            if field_of(place) != self.field:
                raise ValidationError("Kummer place belongs to a different pinned field")
        normalized_generators = tuple(self.generators)
        if len({snapshot_id(item) for item in normalized_generators}) != len(normalized_generators):
            raise ValidationError("Kummer basis generators must be distinct")
        for generator in normalized_generators:
            if field_of(generator) != self.field:
                raise ValidationError("Kummer generator belongs to a different pinned field")
            if bool(getattr(generator, "is_zero", False)):
                raise ValidationError("zero has no Kummer class")
        witness = dict(self.completeness_witness)
        certificates = tuple(self.proving_certificates)
        if any(not isinstance(item, VerificationCertificate) for item in certificates):
            raise TypeError("proving_certificates must contain VerificationCertificate values")
        if len({item.certificate_id for item in certificates}) != len(certificates):
            raise ValidationError("proving_certificates must be unique")
        if self.proof_context.complete and not witness:
            raise ValidationError("complete Kummer spaces require a completeness witness")
        object.__setattr__(self, "places", normalized_places)
        object.__setattr__(self, "generators", normalized_generators)
        object.__setattr__(self, "completeness_witness", witness)
        object.__setattr__(self, "proving_certificates", certificates)
        self.receipt.verify()

    @property
    def dimension(self) -> int:
        return len(self.generators)

    @property
    def completeness(self) -> Completeness:
        return self.proof_context.completeness

    @property
    def assumptions(self) -> tuple[str, ...]:
        return self.proof_context.assumptions

    @property
    def relevant_places_complete(self) -> bool:
        """Whether the declared places form a replayably complete Selmer set.

        This is deliberately stronger than completeness of the finite
        ``K(S,p)`` presentation.  In particular, a perfectly complete
        ``K({infinity},2)`` over the rationals still omits the dyadic place and
        therefore cannot close a 2-Selmer computation.
        """

        from .certificate import relevant_places_complete

        return relevant_places_complete(self.receipt)

    @property
    def relevant_place_set_complete(self) -> bool:
        """Compatibility spelling for :attr:`relevant_places_complete`."""

        return self.relevant_places_complete

    @property
    def basis(self) -> tuple[KummerClass, ...]:
        return tuple(
            self.from_coordinates(tuple(1 if row == column else 0 for row in range(self.dimension)))
            for column in range(self.dimension)
        )

    def zero(self) -> KummerClass:
        return self.from_coordinates((0,) * self.dimension)

    def from_coordinates(self, coordinates: Iterable[int]) -> KummerClass:
        return KummerClass(self, canonical_coordinates(coordinates, self.dimension, self.prime))

    @property
    def receipt(self) -> KummerReceipt:
        return KummerReceipt(
            object_type="space",
            field=_snapshot_mapping(self.field, "field"),
            field_id=snapshot_id(self.field),
            prime=self.prime,
            places=tuple(_snapshot_mapping(place, "place") for place in self.places),
            place_ids=tuple(snapshot_id(place) for place in self.places),
            generators=tuple(
                _snapshot_mapping(generator, "generator") for generator in self.generators
            ),
            generator_ids=tuple(snapshot_id(generator) for generator in self.generators),
            coordinates=None,
            proof_context=self.proof_context.to_dict(),
            completeness_witness=self.completeness_witness,
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
        for value in (self.field, *self.places, *self.generators):
            verifier = getattr(value, "verify", None)
            if callable(verifier) and verifier() is not True:
                raise ValidationError("a Kummer substrate object failed exact verification")
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
class KummerClass:
    """One class in a finite S-Kummer vector space."""

    space: KummerSpace
    coordinates: Vector

    def __post_init__(self) -> None:
        normalized = canonical_coordinates(
            self.coordinates,
            self.space.dimension,
            self.space.prime,
        )
        object.__setattr__(self, "coordinates", normalized)

    @property
    def is_zero(self) -> bool:
        return not any(self.coordinates)

    @property
    def representative(self) -> Any:
        result = self.space.field.one
        for generator, exponent in zip(
            self.space.generators,
            self.coordinates,
            strict=True,
        ):
            result = result * (generator**exponent)
        return result

    @property
    def receipt(self) -> KummerReceipt:
        space = self.space.receipt
        return KummerReceipt(
            object_type="class",
            field=space.field.to_dict(),
            field_id=space.field_id,
            prime=space.prime,
            places=tuple(item.to_dict() for item in space.places),
            place_ids=space.place_ids,
            generators=tuple(item.to_dict() for item in space.generators),
            generator_ids=space.generator_ids,
            coordinates=self.coordinates,
            proof_context=space.proof_context.to_dict(),
            completeness_witness=space.completeness_witness.to_dict(),
            proving_certificates=tuple(item.to_dict() for item in space.proving_certificates),
        )

    @property
    def content_id(self) -> str:
        return self.receipt.content_id

    @property
    def certificate(self) -> VerificationCertificate:
        from .semantic import verification_certificate_for

        return verification_certificate_for(self.receipt)

    def verify(self) -> bool:
        self.space.verify()
        self.receipt.verify()
        default_verifiers.verify(self.certificate)
        return True

    def claim(self) -> Claim:
        from .semantic import claim_for

        return claim_for(self.receipt)

    def claim_graph(self) -> ClaimGraph:
        from .semantic import claim_graph_for

        return claim_graph_for(self.receipt)

    def __add__(self, other: KummerClass) -> KummerClass:
        if self.space.content_id != other.space.content_id:
            raise ValueError("Kummer classes belong to different spaces")
        return self.space.from_coordinates(
            (left + right) % self.space.prime
            for left, right in zip(self.coordinates, other.coordinates, strict=True)
        )

    def __rmul__(self, scalar: int) -> KummerClass:
        return self.space.from_coordinates(
            scalar * value % self.space.prime for value in self.coordinates
        )

    def to_canonical(self) -> dict[str, object]:
        return self.receipt.to_dict()


def _rational_automatic_generators(field: Any, places: tuple[Any, ...]) -> tuple[Any, ...]:
    finite_primes = tuple(
        sorted({int(place.rational_prime) for place in places if is_finite_place(place)})
    )
    return (field.element(-1), *(field.element(prime) for prime in finite_primes))


def _rational_completeness_witness(
    places: tuple[Any, ...],
    generators: tuple[Any, ...],
) -> dict[str, object]:
    place_ids = tuple(snapshot_id(place) for place in places)
    archimedean_place_ids = tuple(
        snapshot_id(place) for place in places if is_infinite_place(place)
    )
    dyadic_place_ids = tuple(
        snapshot_id(place)
        for place in places
        if is_finite_place(place) and int(place.rational_prime) == 2
    )
    ramified_place_ids = tuple(
        snapshot_id(place)
        for place in places
        if is_finite_place(place) and int(place.ramification_index) > 1
    )
    return {
        "method": "portable-rational-s-kummer-v1",
        "place_ids": place_ids,
        "s_unit_generators": tuple(snapshot_id(generator) for generator in generators),
        "class_group_p_torsion": (),
        "principalization_witnesses": (),
        "relevant_place_set": {
            "schema": "arbogast.galois.relevant-place-set/v1",
            "method": "portable-rational-mu2-relevant-places-v1",
            "prime": 2,
            "place_ids": place_ids,
            "archimedean_place_ids": archimedean_place_ids,
            "discriminant_place_ids": (),
            "ramified_place_ids": ramified_place_ids,
            "dyadic_place_ids": dyadic_place_ids,
            "complete": len(archimedean_place_ids) == 1
            and len(dyadic_place_ids) == 1
            and not ramified_place_ids,
            "evidence": None,
        },
    }


def _declared_relevant_place_witness(
    places: tuple[Any, ...],
    *,
    prime: int,
) -> dict[str, object]:
    """Record the declared categories without claiming they are exhaustive."""

    return {
        "schema": "arbogast.galois.relevant-place-set/v1",
        "method": "declared-place-set-only-v1",
        "prime": prime,
        "place_ids": tuple(snapshot_id(place) for place in places),
        "archimedean_place_ids": tuple(
            snapshot_id(place) for place in places if is_infinite_place(place)
        ),
        "discriminant_place_ids": (),
        "ramified_place_ids": tuple(
            snapshot_id(place)
            for place in places
            if is_finite_place(place) and int(place.ramification_index) > 1
        ),
        "dyadic_place_ids": tuple(
            snapshot_id(place)
            for place in places
            if is_finite_place(place) and int(place.rational_prime) == prime
        ),
        "complete": False,
        "evidence": None,
    }


def _prime_factorization(value: int) -> tuple[tuple[int, int], ...] | None:
    remaining = abs(value)
    if remaining == 0:
        return None
    if remaining <= 1:
        return ()
    result: list[tuple[int, int]] = []
    divisor = 2
    trials = 0
    while divisor * divisor <= remaining:
        trials += 1
        if trials > 1_000_000:
            return None
        if remaining % divisor == 0:
            exponent = 0
            while remaining % divisor == 0:
                remaining //= divisor
                exponent += 1
            result.append((divisor, exponent))
        divisor = 3 if divisor == 2 else divisor + 2
    if remaining > 1:
        result.append((remaining, 1))
    return tuple(result)


def _pari_result_payload(
    result: object,
    operation: str,
) -> tuple[Mapping[str, object], VerificationCertificate] | None:
    from arbogast.backends.pari_results import PariOutcome

    if getattr(result, "outcome", None) is not PariOutcome.SUCCESS:
        return None
    payload_value = getattr(result, "payload", None)
    payload_to_dict = getattr(payload_value, "to_dict", None)
    payload = payload_to_dict() if callable(payload_to_dict) else payload_value
    certificate = getattr(result, "certificate", None)
    if not isinstance(payload, Mapping) or not isinstance(certificate, VerificationCertificate):
        return None
    if certificate.witness.get("operation") != operation:
        return None
    if certificate.witness.get("completeness") != "COMPLETE":
        return None
    return cast(Mapping[str, object], payload), certificate


def _place_record_key(value: object) -> tuple[object, int, int]:
    if isinstance(value, Mapping):
        hnf = value.get("ideal_hnf")
        ramification = value.get("ramification_index")
        residue = value.get("residue_degree")
    else:
        hnf = getattr(value, "ideal_hnf", None)
        ramification = getattr(value, "ramification_index", None)
        residue = getattr(value, "residue_degree", None)
    return (
        canonical_snapshot(hnf),
        strict_integer(ramification, "ramification index"),
        strict_integer(residue, "residue degree"),
    )


def _pari_relevant_place_witness(
    field: Any,
    places: tuple[Any, ...],
    adapter: Any,
) -> tuple[dict[str, object], tuple[VerificationCertificate, ...]]:
    """Try to close the independent relevant-place-set proof boundary."""

    from arbogast.backends.base import BackendUnavailableError
    from arbogast.backends.pari_protocol import PariBackendError

    declared = _declared_relevant_place_witness(places, prime=2)
    field_invariants = getattr(adapter, "field_invariants", None)
    prime_decomposition = getattr(adapter, "prime_decomposition", None)
    if not callable(field_invariants) or not callable(prime_decomposition):
        return declared, ()
    try:
        invariants_result = field_invariants(field)
    except (BackendUnavailableError, PariBackendError):
        return declared, ()
    invariants = _pari_result_payload(invariants_result, "field_invariants")
    if invariants is None:
        return declared, ()
    invariants_payload, invariants_certificate = invariants
    try:
        discriminant = strict_integer(
            invariants_payload.get("discriminant"),
            "PARI field discriminant",
        )
        raw_signature = invariants_payload.get("signature")
        if isinstance(raw_signature, (str, bytes)) or not isinstance(raw_signature, Iterable):
            return declared, ()
        signature = tuple(strict_integer(value, "PARI signature entry") for value in raw_signature)
    except (TypeError, ValueError):
        return declared, ()
    field_snapshot = _snapshot_mapping(field, "field")
    if (
        len(signature) != 2
        or signature[0] < 0
        or signature[1] < 0
        or invariants_payload.get("field_id") != snapshot_id(field)
        or invariants_payload.get("degree") != int(field.degree)
        or canonical_snapshot(invariants_payload.get("integral_basis"))
        != canonical_snapshot(field_snapshot.get("integral_basis"))
    ):
        return declared, ()

    infinite_places = tuple(place for place in places if is_infinite_place(place))
    real_indices = tuple(
        sorted(int(place.embedding_index) for place in infinite_places if str(place.kind) == "real")
    )
    complex_indices = tuple(
        sorted(
            int(place.embedding_index) for place in infinite_places if str(place.kind) == "complex"
        )
    )
    if real_indices != tuple(range(signature[0])) or complex_indices != tuple(range(signature[1])):
        return declared, ()
    complex_isolation_evidence: list[dict[str, object]] = []
    complex_isolation_certificates: list[VerificationCertificate] = []
    if int(field.degree) > 2:
        for place in (
            place for place in infinite_places if str(getattr(place, "kind", "")) == "complex"
        ):
            certificate = getattr(place, "isolation_certificate", None)
            if not isinstance(certificate, VerificationCertificate):
                return declared, ()
            if certificate.witness.get("operation") != "complex_root_isolation":
                return declared, ()
            complex_isolation_evidence.append(
                {
                    "certificate_id": certificate.certificate_id,
                    "place_id": snapshot_id(place),
                }
            )
            complex_isolation_certificates.append(certificate)

    discriminant_factorization = _prime_factorization(discriminant)
    if discriminant_factorization is None:
        return declared, ()
    discriminant_primes = tuple(prime for prime, _ in discriminant_factorization)
    rational_primes = tuple(sorted({2, *discriminant_primes}))
    decomposition_evidence: list[dict[str, object]] = []
    decomposition_certificates: list[VerificationCertificate] = []
    finite_places = tuple(place for place in places if is_finite_place(place))
    try:
        for rational_prime in rational_primes:
            result = prime_decomposition(field, rational_prime)
            decoded = _pari_result_payload(result, "prime_decomposition")
            if decoded is None:
                return declared, ()
            payload, certificate = decoded
            if (
                payload.get("field_id") != snapshot_id(field)
                or payload.get("rational_prime") != rational_prime
            ):
                return declared, ()
            raw_records = payload.get("prime_ideals")
            if isinstance(raw_records, (str, bytes)) or not isinstance(raw_records, Iterable):
                return declared, ()
            records = tuple(raw_records)
            supplied = tuple(
                place for place in finite_places if int(place.rational_prime) == rational_prime
            )
            if sorted(_place_record_key(item) for item in records) != sorted(
                _place_record_key(item) for item in supplied
            ):
                return declared, ()
            decomposition_evidence.append(
                {
                    "certificate_id": certificate.certificate_id,
                    "rational_prime": rational_prime,
                }
            )
            decomposition_certificates.append(certificate)
    except (BackendUnavailableError, PariBackendError, TypeError, ValueError):
        return declared, ()

    place_ids = tuple(snapshot_id(place) for place in places)
    ramified_primes = set(discriminant_primes)
    witness = {
        "schema": "arbogast.galois.relevant-place-set/v1",
        "method": "pari-field-and-prime-decomposition-v1",
        "prime": 2,
        "place_ids": place_ids,
        "archimedean_place_ids": tuple(
            snapshot_id(place) for place in places if is_infinite_place(place)
        ),
        "discriminant_place_ids": tuple(
            snapshot_id(place)
            for place in finite_places
            if int(place.rational_prime) in ramified_primes
        ),
        "ramified_place_ids": tuple(
            snapshot_id(place) for place in finite_places if int(place.ramification_index) > 1
        ),
        "dyadic_place_ids": tuple(
            snapshot_id(place) for place in finite_places if int(place.rational_prime) == 2
        ),
        "complete": True,
        "evidence": {
            "complex_isolation_certificates": tuple(complex_isolation_evidence),
            "discriminant": discriminant,
            "discriminant_factorization": discriminant_factorization,
            "field_invariants_certificate_id": invariants_certificate.certificate_id,
            "prime_decomposition_certificates": tuple(decomposition_evidence),
            "signature": signature,
        },
    }
    return witness, (
        invariants_certificate,
        *complex_isolation_certificates,
        *decomposition_certificates,
    )


def _pari_kummer_context(
    base: ProofContext,
    certificates: tuple[VerificationCertificate, ...],
) -> ProofContext:
    by_version: dict[str, set[str]] = {}
    for certificate in certificates:
        version = certificate.witness.get("backend_version")
        operation = certificate.witness.get("operation")
        if not isinstance(version, str) or not isinstance(operation, str):
            raise ValueError("nested PARI evidence lacks a pinned version or operation")
        by_version.setdefault(version, set()).add(operation)
    if len(by_version) != 1:
        raise ValueError("one Kummer proof bundle cannot mix pinned PARI versions")
    requirements = tuple(
        VerificationRequirement.pinned_external(
            "arbogast.backends.pari.v1",
            version,
            capabilities=tuple(sorted(operations)),
        )
        for version, operations in sorted(by_version.items())
    )
    return ProofContext(base.assumptions, requirements, base.completeness)


def _pari_kummer_presentation(
    field: Any,
    places: tuple[Any, ...],
    *,
    backend: Any | None,
    allow_grh: bool,
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

    adapter = PariBackend() if backend is None else backend
    finite_places = tuple(place for place in places if is_finite_place(place))
    try:
        result = adapter.s_unit_squareclasses(
            field,
            finite_places,
            allow_grh=allow_grh,
        )
    except (BackendUnavailableError, PariBackendError) as error:
        return Unsupported(
            "galois.kummer_space",
            f"PARI could not certify this S-Kummer presentation: {error}",
            requested={
                "field_id": snapshot_id(field),
                "place_ids": tuple(snapshot_id(place) for place in places),
            },
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
        raise TypeError("PARI S-Kummer payload must be a mapping")
    raw_representatives = payload.get("representatives")
    if isinstance(raw_representatives, (str, bytes)) or not isinstance(
        raw_representatives, Iterable
    ):
        raise TypeError("PARI S-Kummer representatives must be iterable")
    generators = tuple(
        element_from_pari_coefficients(
            field,
            representative,
            f"PARI S-Kummer representative[{index}]",
        )
        for index, representative in enumerate(raw_representatives)
    )
    s_unit_rank = strict_integer(payload.get("s_unit_rank"), "PARI S-unit rank")
    if not 0 <= s_unit_rank <= len(generators):
        raise ValueError("PARI S-unit rank is incompatible with its representatives")
    raw_torsion = payload.get("s_class_2_torsion")
    if isinstance(raw_torsion, (str, bytes)) or not isinstance(raw_torsion, Iterable):
        raise TypeError("PARI S-class 2-torsion records must be iterable")
    torsion_records: list[Mapping[str, object]] = []
    for index, record in enumerate(raw_torsion):
        if not isinstance(record, Mapping):
            raise TypeError(f"PARI S-class record[{index}] must be a mapping")
        torsion_records.append(cast(Mapping[str, object], record))
    if len(generators) != s_unit_rank + len(torsion_records):
        raise ValueError("PARI S-class lifts do not match the Kummer representatives")
    generator_ids = tuple(snapshot_id(item) for item in generators)
    lift_ids = generator_ids[s_unit_rank:]
    class_witnesses = tuple(
        {
            "cyclic_order": record.get("cyclic_order"),
            "ideal_hnf": record.get("ideal_hnf"),
            "s_prime_exponents": record.get("s_prime_exponents"),
        }
        for record in torsion_records
    )
    principalizations = tuple(
        {
            "ideal_hnf": record.get("ideal_hnf"),
            "principalization_generator_id": identifier,
            "s_prime_exponents": record.get("s_prime_exponents"),
        }
        for record, identifier in zip(torsion_records, lift_ids, strict=True)
    )
    context_value = result.proof_context()
    if not isinstance(context_value, ProofContext):
        raise TypeError("PARI result returned an invalid proof context")
    certificate = getattr(result, "certificate", None)
    if not isinstance(certificate, VerificationCertificate):
        raise ValueError("successful PARI S-Kummer arithmetic lacks central proof evidence")
    relevant_witness, relevant_certificates = _pari_relevant_place_witness(
        field,
        places,
        adapter,
    )
    certificates = (certificate, *relevant_certificates)
    context_value = _pari_kummer_context(context_value, certificates)
    witness: dict[str, object] = {
        "method": "pari-s-kummer-v1",
        "field_id": snapshot_id(field),
        "place_ids": tuple(snapshot_id(place) for place in places),
        "generator_ids": generator_ids,
        "s_unit_generators": generator_ids[:s_unit_rank],
        "class_group_p_torsion": class_witnesses,
        "principalization_witnesses": principalizations,
        # The S-unit computation proves K(S,2); the separately replayed witness
        # proves that the declared set also exhausts the archimedean, dyadic,
        # and discriminant-prime places needed for Selmer promotion.
        "relevant_place_set": relevant_witness,
    }
    return generators, context_value, witness, certificates


def kummer_space(
    field: Any,
    places: Iterable[Any],
    *,
    prime: int = 2,
    generators: Iterable[Any] | None = None,
    completeness: Completeness | str | None = None,
    proof_context: ProofContext | None = None,
    completeness_witness: Mapping[str, object] | None = None,
    assumptions: Iterable[str] = (),
    proving_certificate: VerificationCertificate | None = None,
    proving_certificates: Iterable[VerificationCertificate] = (),
    backend: Any | None = None,
    allow_grh: bool = False,
) -> KummerSpace | Unsupported | PariArithmeticResult:
    """Construct a finite ``K(S,p)`` presentation.

    Omitting ``generators`` requests automatic arithmetic.  Version 0.2
    implements that request for ``p=2`` portably over the pinned rational
    field and through the narrow certified PARI adapter for other pinned
    number fields.
    """

    normalized_places = tuple(sorted(tuple(places), key=snapshot_id))
    automatic = generators is None
    if automatic and prime != 2:
        return Unsupported(
            "galois.kummer_space",
            "automatic p>2 Kummer arithmetic is deferred in Arbogast 0.2",
            requested={"prime": prime, "field_id": snapshot_id(field)},
            supported=("automatic p=2 arithmetic", "certified supplied prime-p presentation"),
        )
    if automatic and not any(is_infinite_place(place) for place in normalized_places):
        return Unsupported(
            "galois.kummer_space",
            "automatic arithmetic requires the archimedean place set explicitly",
            requested={"place_ids": tuple(snapshot_id(place) for place in normalized_places)},
            supported=("explicit finite, ramified, p-adic, and archimedean place sets",),
        )
    if automatic and not is_rational_field(field):
        supplied_assumptions = tuple(assumptions)
        supplied_certificates = tuple(proving_certificates)
        if (
            proof_context is not None
            or completeness is not None
            or supplied_assumptions
            or completeness_witness is not None
            or proving_certificate is not None
            or supplied_certificates
        ):
            raise ValueError(
                "automatic PARI Kummer arithmetic owns its proof context and nested evidence"
            )
        discovered = _pari_kummer_presentation(
            field,
            normalized_places,
            backend=backend,
            allow_grh=allow_grh,
        )
        if isinstance(discovered, Unsupported | PariArithmeticResult):
            return discovered
        generators_from_pari, context, witness, certificates = discovered
        return KummerSpace(
            field,
            normalized_places,
            prime,
            generators_from_pari,
            context,
            witness,
            certificates,
        )
    normalized_generators = (
        _rational_automatic_generators(field, normalized_places)
        if automatic
        else tuple(generators or ())
    )
    context = _proof_context(
        proof_context,
        completeness,
        assumptions,
        automatic_complete=automatic,
    )
    witness = (
        _rational_completeness_witness(normalized_places, normalized_generators)
        if automatic
        else dict(completeness_witness or {})
    )
    nested_certificates = tuple(proving_certificates)
    if proving_certificate is not None:
        nested_certificates = (proving_certificate, *nested_certificates)
    return KummerSpace(
        field,
        normalized_places,
        prime,
        normalized_generators,
        context,
        witness,
        nested_certificates,
    )


def kummer_class(space: KummerSpace, coordinates: Iterable[int]) -> KummerClass:
    """Return the canonical class with the supplied prime-field coordinates."""

    if not isinstance(space, KummerSpace):
        raise TypeError("space must be a KummerSpace")
    return space.from_coordinates(coordinates)


__all__ = ["KummerClass", "KummerSpace", "kummer_class", "kummer_space"]
