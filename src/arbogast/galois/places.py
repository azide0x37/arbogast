"""Canonical finite and infinite places of pinned number fields."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from itertools import pairwise, product
from typing import ClassVar, cast

from arbogast.backends.pari_certificate import PARI_VERIFIER_ID
from arbogast.cert import VerificationCertificate
from arbogast.core import CanonicalJSON, CanonicalObject, ValidationError
from arbogast.formats import FINITE_PLACE_SCHEMA, INFINITE_PLACE_SCHEMA, FrozenMapping

from .evidence import VerifiedPariEvidence, verified_pari_evidence
from .fields import (
    NumberField,
    RationalLike,
    RationalVector,
    _certificate_vector,
    _rational,
    _solve_square,
    rational_payload,
)
from .ideals import Ideal
from .proof import VerificationRequirement, VerifierTrust

MAX_PORTABLE_RESIDUE_CARDINALITY = 4096


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _is_prime(value: int) -> bool:
    if value < 2:
        return False
    if value in (2, 3):
        return True
    if value % 2 == 0 or value % 3 == 0:
        return False
    divisor = 5
    step = 2
    while divisor * divisor <= value:
        if value % divisor == 0:
            return False
        divisor += step
        step = 6 - step
    return True


def _trim(polynomial: Sequence[Fraction]) -> RationalVector:
    values = list(polynomial)
    while values and not values[-1]:
        values.pop()
    return tuple(values)


def _derivative(polynomial: Sequence[Fraction]) -> RationalVector:
    return _trim(tuple(index * polynomial[index] for index in range(1, len(polynomial))))


def _polynomial_remainder(
    dividend: Sequence[Fraction],
    divisor: Sequence[Fraction],
) -> RationalVector:
    denominator = _trim(divisor)
    if not denominator:
        raise ZeroDivisionError("polynomial division by zero")
    work = list(_trim(dividend))
    while len(work) >= len(denominator):
        coefficient = work[-1] / denominator[-1]
        shift = len(work) - len(denominator)
        for index, value in enumerate(denominator):
            work[shift + index] -= coefficient * value
        work = list(_trim(work))
    return tuple(work)


def _sturm_sequence(polynomial: Sequence[int]) -> tuple[RationalVector, ...]:
    first = _trim(tuple(Fraction(value) for value in polynomial))
    second = _derivative(first)
    if not second:
        raise ValidationError("defining polynomial has zero derivative")
    result = [first, second]
    while result[-1]:
        remainder = _polynomial_remainder(result[-2], result[-1])
        if not remainder:
            break
        result.append(tuple(-value for value in remainder))
    if len(result[-1]) > 1:
        raise ValidationError("defining polynomial is not squarefree")
    return tuple(result)


def _evaluate(polynomial: Sequence[Fraction], value: Fraction) -> Fraction:
    result = Fraction(0)
    for coefficient in reversed(polynomial):
        result = result * value + coefficient
    return result


def _variations(signs: Iterable[int]) -> int:
    nonzero = tuple(sign for sign in signs if sign)
    return sum(left != right for left, right in pairwise(nonzero))


def _sign(value: Fraction) -> int:
    return (value > 0) - (value < 0)


def _variations_at(sequence: Sequence[Sequence[Fraction]], value: Fraction) -> int:
    evaluations = tuple(_evaluate(polynomial, value) for polynomial in sequence)
    if not evaluations[0]:
        raise ValidationError("a real isolating endpoint lies on the defining polynomial")
    return _variations(_sign(evaluation) for evaluation in evaluations)


def _variations_at_negative_infinity(sequence: Sequence[Sequence[Fraction]]) -> int:
    signs = []
    for polynomial in sequence:
        degree = len(polynomial) - 1
        leading_sign = _sign(polynomial[-1])
        signs.append(leading_sign if degree % 2 == 0 else -leading_sign)
    return _variations(signs)


class InfinitePlaceKind(StrEnum):
    REAL = "real"
    COMPLEX = "complex"


def _pinned_external_requirement(
    requirement: VerificationRequirement | None,
    name: str,
) -> VerificationRequirement | None:
    if requirement is None:
        return None
    if not isinstance(requirement, VerificationRequirement):
        raise TypeError(f"{name} must be a VerificationRequirement")
    if requirement.trust is not VerifierTrust.PINNED_EXTERNAL:
        raise ValidationError(f"{name} must use pinned-external trust")
    return requirement


@dataclass(frozen=True, slots=True, init=False)
class FinitePlace(CanonicalObject):
    """A prime ideal in canonical column-HNF coordinates.

    ``ideal_hnf`` is stored as matrix rows; its columns generate the ideal in
    ``field.integral_basis``.  The constructor replays HNF normalization,
    norm, containment of ``p O``, and closure under the declared order.
    """

    schema_version: ClassVar[str] = FINITE_PLACE_SCHEMA

    field: NumberField
    rational_prime: int
    ideal_hnf: tuple[tuple[int, ...], ...]
    ramification_index: int
    residue_degree: int
    residue_field_witness: FrozenMapping
    verification_requirement: VerificationRequirement | None
    prime_decomposition_certificate: VerificationCertificate | None

    def __init__(
        self,
        field: NumberField,
        rational_prime: int,
        ideal_hnf: Iterable[Iterable[int]],
        ramification_index: int,
        residue_degree: int,
        *,
        verification_requirement: VerificationRequirement | None = None,
        prime_decomposition_certificate: VerificationCertificate | None = None,
    ) -> None:
        if not isinstance(field, NumberField):
            raise TypeError("field must be a NumberField")
        prime = _integer(rational_prime, "rational_prime")
        if not _is_prime(prime):
            raise ValidationError("rational_prime must be prime")
        ramification = _integer(ramification_index, "ramification_index")
        residue = _integer(residue_degree, "residue_degree")
        if ramification <= 0 or residue <= 0:
            raise ValidationError("ramification and residue degrees must be positive")
        if ramification * residue > field.degree:
            raise ValidationError("ramification_index * residue_degree exceeds field degree")
        rows = tuple(
            tuple(_integer(value, "ideal-HNF entry") for value in row) for row in ideal_hnf
        )
        if len(rows) != field.degree or any(len(row) != field.degree for row in rows):
            raise ValidationError(f"ideal_hnf must be a {field.degree}-by-{field.degree} matrix")
        for row in range(field.degree):
            if rows[row][row] <= 0:
                raise ValidationError("ideal HNF diagonal entries must be positive")
            if any(rows[row][column] != 0 for column in range(row)):
                raise ValidationError("ideal_hnf must be upper triangular column HNF")
            if any(
                not 0 <= rows[row][column] < rows[row][row]
                for column in range(row + 1, field.degree)
            ):
                raise ValidationError("ideal-HNF entries above a pivot must be canonical residues")
        norm = 1
        for index in range(field.degree):
            norm *= rows[index][index]
        if norm != prime**residue:
            raise ValidationError("ideal-HNF determinant does not equal p^residue_degree")
        requirement = _pinned_external_requirement(
            verification_requirement,
            "finite-place verification requirement",
        )
        if prime_decomposition_certificate is not None and not isinstance(
            prime_decomposition_certificate,
            VerificationCertificate,
        ):
            raise TypeError("prime_decomposition_certificate must be a VerificationCertificate")
        if field.degree > 2 and prime_decomposition_certificate is None:
            raise ValidationError(
                "higher-degree finite places need a nested prime-decomposition "
                "certificate; a bare verifier requirement is not evidence"
            )
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "rational_prime", prime)
        object.__setattr__(self, "ideal_hnf", rows)
        object.__setattr__(self, "ramification_index", ramification)
        object.__setattr__(self, "residue_degree", residue)
        object.__setattr__(self, "verification_requirement", requirement)
        object.__setattr__(
            self,
            "prime_decomposition_certificate",
            prime_decomposition_certificate,
        )
        self._validate_ideal_lattice()
        object.__setattr__(
            self,
            "residue_field_witness",
            FrozenMapping(self._build_residue_field_witness()),
        )
        self._validate_ramification_and_decomposition()

    @property
    def place_id(self) -> str:
        return self.content_id

    @property
    def norm(self) -> int:
        return int(self.rational_prime**self.residue_degree)

    @property
    def ideal(self) -> Ideal:
        """Return the standalone canonical prime ideal underlying this place."""

        return Ideal(self.field, self.ideal_hnf)

    def _lattice_coordinates(self, vector: Sequence[Fraction]) -> RationalVector:
        matrix = tuple(tuple(Fraction(value) for value in row) for row in self.ideal_hnf)
        return _solve_square(matrix, vector)

    def _validate_ideal_lattice(self) -> None:
        degree = self.field.degree
        for index in range(degree):
            rational_prime_vector = tuple(
                Fraction(self.rational_prime if row == index else 0) for row in range(degree)
            )
            if any(
                value.denominator != 1 for value in self._lattice_coordinates(rational_prime_vector)
            ):
                raise ValidationError("finite-place ideal does not contain p times the order")
        ideal_generators = tuple(
            self.field.from_integral_basis_coordinates(
                tuple(self.ideal_hnf[row][column] for row in range(degree))
            )
            for column in range(degree)
        )
        order_basis = tuple(
            self.field.from_integral_basis_coordinates(
                tuple(1 if index == row else 0 for row in range(degree))
            )
            for index in range(degree)
        )
        for ideal_generator in ideal_generators:
            for basis_element in order_basis:
                product_coordinates = (
                    ideal_generator * basis_element
                ).coordinates_in_integral_basis()
                if any(
                    value.denominator != 1
                    for value in self._lattice_coordinates(product_coordinates)
                ):
                    raise ValidationError(
                        "finite-place HNF lattice is not closed under the declared order"
                    )

    def _validate_ramification_and_decomposition(self) -> None:
        if self.field.degree == 1:
            if self.ramification_index != 1 or self.residue_degree != 1:
                raise ValidationError("the rational field has e=f=1 at every finite place")
        elif self.field.degree == 2:
            expected_ramification = 2 if self.field.discriminant % self.rational_prime == 0 else 1
            if self.ramification_index != expected_ramification:
                raise ValidationError(
                    "ramification_index disagrees with the exact quadratic discriminant"
                )

        certificate = self.prime_decomposition_certificate
        if certificate is not None:
            evidence = verified_pari_evidence(certificate, "prime_decomposition")
            self._bind_prime_decomposition_evidence(evidence)

    def _bind_prime_decomposition_evidence(self, evidence: VerifiedPariEvidence) -> None:
        replay = evidence.replay.to_dict()
        if set(replay) != {"arguments", "field"}:
            raise ValidationError("prime-decomposition replay has a foreign shape")
        arguments = replay.get("arguments")
        raw_field = replay.get("field")
        if not isinstance(arguments, dict) or arguments != {"rational_prime": self.rational_prime}:
            raise ValidationError("prime-decomposition certificate names a different prime")
        if not isinstance(raw_field, dict):
            raise ValidationError("prime-decomposition replay omits its field")
        if raw_field.get("field_id") != self.field.field_id:
            raise ValidationError("prime-decomposition certificate names a different field")
        replay_polynomial = _certificate_vector(
            raw_field.get("defining_polynomial"),
            self.field.degree + 1,
            "replayed defining polynomial",
        )
        if replay_polynomial != tuple(Fraction(value) for value in self.field.defining_polynomial):
            raise ValidationError("prime-decomposition replay has a different polynomial")

        payload = evidence.payload.to_dict()
        if set(payload) != {"field_id", "prime_ideals", "rational_prime"}:
            raise ValidationError("prime-decomposition certificate has a foreign payload shape")
        if (
            payload.get("field_id") != self.field.field_id
            or payload.get("rational_prime") != self.rational_prime
        ):
            raise ValidationError("prime-decomposition payload has a different field or prime")
        records = payload.get("prime_ideals")
        if isinstance(records, str | bytes) or not isinstance(records, Sequence):
            raise ValidationError("prime-decomposition payload omits its prime ideals")
        matches = 0
        for raw_record in records:
            if not isinstance(raw_record, dict):
                raise ValidationError("prime-decomposition record must be a mapping")
            if set(raw_record) != {
                "ideal_hnf",
                "norm",
                "place_id",
                "ramification_index",
                "residue_degree",
            }:
                raise ValidationError("prime-decomposition record has a foreign shape")
            raw_hnf = raw_record.get("ideal_hnf")
            if isinstance(raw_hnf, str | bytes) or not isinstance(raw_hnf, Sequence):
                raise ValidationError("prime-decomposition record omits its HNF")
            try:
                hnf = tuple(
                    tuple(_integer(item, "certified ideal-HNF entry") for item in row)
                    for row in raw_hnf
                )
            except TypeError as error:
                raise ValidationError("prime-decomposition record has a malformed HNF") from error
            if (
                hnf == self.ideal_hnf
                and raw_record.get("norm") == self.norm
                and raw_record.get("ramification_index") == self.ramification_index
                and raw_record.get("residue_degree") == self.residue_degree
            ):
                matches += 1
        if matches != 1:
            raise ValidationError(
                "prime-decomposition certificate does not prove this exact finite place"
            )
        requirement = self.verification_requirement
        if requirement is not None and (
            requirement.verifier.casefold() not in {"pari", PARI_VERIFIER_ID}
            or requirement.version != evidence.backend_version
        ):
            raise ValidationError(
                "finite-place verifier requirement does not match the nested PARI certificate"
            )

    def _reduce_integral_coordinates(self, vector: Sequence[int]) -> tuple[int, ...]:
        if len(vector) != self.field.degree:
            raise ValidationError("residue reduction vector has the wrong degree")
        work = list(vector)
        for column in range(self.field.degree - 1, -1, -1):
            quotient, remainder = divmod(work[column], self.ideal_hnf[column][column])
            work[column] = remainder
            for row in range(column):
                work[row] -= quotient * self.ideal_hnf[row][column]
        return tuple(work)

    def _build_residue_field_witness(self) -> dict[str, object]:
        one_coordinates = self.field.one.coordinates_in_integral_basis()
        if any(value.denominator != 1 for value in one_coordinates):
            raise ValidationError("declared integral basis does not express one integrally")
        one_representative = self._reduce_integral_coordinates(
            tuple(value.numerator for value in one_coordinates)
        )
        if self.residue_degree == 1:
            return {
                "cardinality": self.rational_prime,
                "method": "prime-order-quotient",
                "one_representative": list(one_representative),
            }
        if self.norm > MAX_PORTABLE_RESIDUE_CARDINALITY:
            certificate = self.prime_decomposition_certificate
            if certificate is None:
                raise ValidationError(
                    "large residue field needs a nested prime-decomposition certificate"
                )
            return {
                "cardinality": self.norm,
                "certificate_id": certificate.certificate_id,
                "method": "nested-pari-prime-decomposition",
            }
        representatives = tuple(
            tuple(values)
            for values in product(
                *(range(self.ideal_hnf[index][index]) for index in range(self.field.degree))
            )
        )
        representative_indices = {
            representative: index for index, representative in enumerate(representatives)
        }
        one_index = representative_indices[one_representative]
        multiplication_rows: list[list[int]] = []
        for left in representatives:
            left_element = self.field.from_integral_basis_coordinates(left)
            row: list[int] = []
            for right in representatives:
                right_element = self.field.from_integral_basis_coordinates(right)
                coordinates = (left_element * right_element).coordinates_in_integral_basis()
                if any(value.denominator != 1 for value in coordinates):
                    raise ValidationError("residue multiplication left the integral order")
                reduced = self._reduce_integral_coordinates(
                    tuple(value.numerator for value in coordinates)
                )
                row.append(representative_indices[reduced])
            multiplication_rows.append(row)
        zero_index = representative_indices[(0,) * self.field.degree]
        inverse_indices: list[int] = []
        for index in range(len(representatives)):
            if index == zero_index:
                inverse_indices.append(zero_index)
                continue
            inverse = next(
                (
                    candidate
                    for candidate in range(len(representatives))
                    if multiplication_rows[index][candidate] == one_index
                    and multiplication_rows[candidate][index] == one_index
                ),
                None,
            )
            if inverse is None:
                raise ValidationError(
                    "finite-place quotient is not a field; the HNF ideal is not prime"
                )
            inverse_indices.append(inverse)
        return {
            "cardinality": self.norm,
            "inverse_indices": inverse_indices,
            "method": "complete-quotient-table",
            "multiplication_table": multiplication_rows,
            "one_index": one_index,
            "representatives": [list(value) for value in representatives],
            "zero_index": zero_index,
        }

    def verify(self) -> bool:
        return (
            FinitePlace(
                self.field,
                self.rational_prime,
                self.ideal_hnf,
                self.ramification_index,
                self.residue_degree,
                verification_requirement=self.verification_requirement,
                prime_decomposition_certificate=self.prime_decomposition_certificate,
            )
            == self
        )

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "field_id": self.field.field_id,
                "ideal_hnf": [list(row) for row in self.ideal_hnf],
                "ramification_index": self.ramification_index,
                "rational_prime": self.rational_prime,
                "residue_degree": self.residue_degree,
                "residue_field_witness": self.residue_field_witness.to_dict(),
                "type": "arbogast.finite_place",
                "verification_requirement": (
                    self.verification_requirement.to_canonical_data()
                    if self.verification_requirement is not None
                    else None
                ),
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    def to_schema_document(self) -> dict[str, object]:
        """Return the additive, version-marked 0.2 interchange document."""

        return {**self.to_dict(), "schema": self.schema_version}


@dataclass(frozen=True, slots=True, init=False)
class InfinitePlace(CanonicalObject):
    """An archimedean place with exact rational isolating data.

    A real place carries a Sturm-verified interval containing exactly one real
    root.  Quadratic complex rectangles are verified by exact inequalities;
    higher-degree rectangles require a nested root-isolation certificate.  A
    bare verifier requirement never proves that a rectangle contains a root.
    """

    schema_version: ClassVar[str] = INFINITE_PLACE_SCHEMA

    field: NumberField
    kind: InfinitePlaceKind
    isolation: tuple[Fraction, ...]
    embedding_index: int
    verification_requirement: VerificationRequirement | None
    isolation_certificate: VerificationCertificate | None

    def __init__(
        self,
        field: NumberField,
        kind: InfinitePlaceKind | str,
        isolation: Iterable[RationalLike],
        *,
        embedding_index: int = 0,
        verification_requirement: VerificationRequirement | None = None,
        isolation_certificate: VerificationCertificate | None = None,
    ) -> None:
        if not isinstance(field, NumberField):
            raise TypeError("field must be a NumberField")
        try:
            normalized_kind = InfinitePlaceKind(kind)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"unsupported infinite-place kind: {kind!r}") from error
        index = _integer(embedding_index, "embedding_index")
        if index < 0:
            raise ValidationError("embedding_index must be nonnegative")
        values = tuple(_rational(value, "isolating datum") for value in isolation)
        requirement = _pinned_external_requirement(
            verification_requirement,
            "infinite-place verification requirement",
        )
        if isolation_certificate is not None and not isinstance(
            isolation_certificate,
            VerificationCertificate,
        ):
            raise TypeError("isolation_certificate must be a VerificationCertificate")
        expected_length = 2 if normalized_kind is InfinitePlaceKind.REAL else 4
        if len(values) != expected_length:
            raise ValidationError(
                f"{normalized_kind.value} isolation needs {expected_length} rational endpoints"
            )
        if values[0] >= values[1]:
            raise ValidationError("real isolating bounds must be strictly increasing")
        if normalized_kind is InfinitePlaceKind.REAL:
            sequence = _sturm_sequence(field.defining_polynomial)
            root_count = _variations_at(sequence, values[0]) - _variations_at(sequence, values[1])
            if root_count != 1:
                raise ValidationError(
                    "real isolating interval must contain exactly one defining-polynomial root"
                )
            roots_to_left = _variations_at_negative_infinity(sequence) - _variations_at(
                sequence, values[0]
            )
            if index != roots_to_left:
                raise ValidationError(
                    "embedding_index is not the canonical left-to-right real-root index"
                )
        else:
            imaginary_lower, imaginary_upper = values[2], values[3]
            if not 0 < imaginary_lower < imaginary_upper:
                raise ValidationError(
                    "a complex-place rectangle must select the positive-imaginary root"
                )
            if requirement is not None and isolation_certificate is None:
                raise ValidationError(
                    "a bare verifier requirement is not complex root-isolation evidence"
                )
            if field.degree == 2:
                self._validate_quadratic_complex_isolation(field, values, index)
            elif isolation_certificate is None:
                raise ValidationError(
                    "a higher-degree complex place needs a nested root-isolation certificate"
                )
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "kind", normalized_kind)
        object.__setattr__(self, "isolation", values)
        object.__setattr__(self, "embedding_index", index)
        object.__setattr__(self, "verification_requirement", requirement)
        object.__setattr__(self, "isolation_certificate", isolation_certificate)
        if normalized_kind is InfinitePlaceKind.COMPLEX and isolation_certificate is not None:
            evidence = verified_pari_evidence(
                isolation_certificate,
                "complex_root_isolation",
            )
            self._bind_complex_isolation_evidence(evidence)

    @staticmethod
    def _validate_quadratic_complex_isolation(
        field: NumberField,
        values: tuple[Fraction, ...],
        embedding_index: int,
    ) -> None:
        if embedding_index != 0:
            raise ValidationError("a quadratic field has exactly one complex place")
        constant, linear, _ = field.defining_polynomial
        discriminant = linear * linear - 4 * constant
        if discriminant >= 0:
            raise ValidationError("the quadratic defining polynomial has no complex place")
        real_lower, real_upper, imaginary_lower, imaginary_upper = values
        real_coordinate = Fraction(-linear, 2)
        if not real_lower < real_coordinate < real_upper:
            raise ValidationError("complex isolating rectangle misses the root real part")
        positive_square = -discriminant
        if not ((2 * imaginary_lower) ** 2 < positive_square < (2 * imaginary_upper) ** 2):
            raise ValidationError("complex isolating rectangle misses the root imaginary part")

    def _bind_complex_isolation_evidence(self, evidence: VerifiedPariEvidence) -> None:
        replay = evidence.replay.to_dict()
        payload = evidence.payload.to_dict()
        if set(payload) != {
            "embedding_index",
            "field_id",
            "isolation",
            "kind",
            "ordering",
            "root_count",
            "rouche_witness",
        }:
            raise ValidationError("root-isolation certificate has a foreign payload shape")
        if (
            payload.get("embedding_index") != self.embedding_index
            or payload.get("field_id") != self.field.field_id
            or payload.get("kind") != "complex"
            or payload.get("ordering") != "pari-polroots-positive-imaginary"
            or payload.get("root_count") != 1
        ):
            raise ValidationError(
                "root-isolation certificate does not prove this exact complex rectangle"
            )
        certified_isolation = _certificate_vector(
            payload.get("isolation"),
            4,
            "certified complex isolation",
        )
        if certified_isolation != self.isolation:
            raise ValidationError(
                "root-isolation certificate does not prove this exact complex rectangle"
            )
        raw_rouche = payload.get("rouche_witness")
        if not isinstance(raw_rouche, dict) or set(raw_rouche) != {
            "center",
            "inner_margin",
            "inner_radius",
            "outer_margin",
            "outer_radius",
        }:
            raise ValidationError("root-isolation certificate has a malformed Rouché witness")
        center = _certificate_vector(raw_rouche.get("center"), 2, "Rouché center")
        inner_radius = _certificate_vector(
            (raw_rouche.get("inner_radius"),),
            1,
            "Rouché inner radius",
        )[0]
        outer_radius = _certificate_vector(
            (raw_rouche.get("outer_radius"),),
            1,
            "Rouché outer radius",
        )[0]
        inner_margin = _certificate_vector(
            (raw_rouche.get("inner_margin"),),
            1,
            "Rouché inner margin",
        )[0]
        outer_margin = _certificate_vector(
            (raw_rouche.get("outer_margin"),),
            1,
            "Rouché outer margin",
        )[0]
        if (
            inner_radius <= 0
            or outer_radius != 2 * inner_radius
            or inner_margin <= 0
            or outer_margin <= 0
            or certified_isolation
            != (
                center[0] - inner_radius,
                center[0] + inner_radius,
                center[1] - inner_radius,
                center[1] + inner_radius,
            )
        ):
            raise ValidationError("root-isolation Rouché witness does not bind the rectangle")
        if set(replay) != {"arguments", "field"}:
            raise ValidationError("root-isolation replay has a foreign shape")
        arguments = replay.get("arguments")
        raw_field = replay.get("field")
        if not isinstance(arguments, dict) or set(arguments) != {
            "embedding_index",
            "max_bits",
        }:
            raise ValidationError("root-isolation replay has foreign arguments")
        max_bits = arguments.get("max_bits")
        if (
            arguments.get("embedding_index") != self.embedding_index
            or isinstance(max_bits, bool)
            or not isinstance(max_bits, int)
            or not 8 <= max_bits <= 512
        ):
            raise ValidationError("root-isolation replay names a different embedding")
        if not isinstance(raw_field, dict) or raw_field.get("field_id") != self.field.field_id:
            raise ValidationError("root-isolation certificate names a different field")
        requirement = self.verification_requirement
        if requirement is not None and (
            requirement.verifier.casefold() not in {"pari", PARI_VERIFIER_ID}
            or requirement.version != evidence.backend_version
        ):
            raise ValidationError(
                "root-isolation requirement does not match the nested PARI certificate"
            )

    @property
    def place_id(self) -> str:
        return self.content_id

    @property
    def isolating_interval(self) -> tuple[Fraction, Fraction]:
        if self.kind is not InfinitePlaceKind.REAL:
            raise AttributeError("a complex place has an isolating rectangle, not an interval")
        return (self.isolation[0], self.isolation[1])

    @property
    def isolating_rectangle(self) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        if self.kind is not InfinitePlaceKind.COMPLEX:
            raise AttributeError("a real place has an isolating interval, not a rectangle")
        return (
            self.isolation[0],
            self.isolation[1],
            self.isolation[2],
            self.isolation[3],
        )

    def verify(self) -> bool:
        return (
            InfinitePlace(
                self.field,
                self.kind,
                self.isolation,
                embedding_index=self.embedding_index,
                verification_requirement=self.verification_requirement,
                isolation_certificate=self.isolation_certificate,
            )
            == self
        )

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "embedding_index": self.embedding_index,
                "field_id": self.field.field_id,
                "isolation": [rational_payload(value) for value in self.isolation],
                "kind": self.kind.value,
                "type": "arbogast.infinite_place",
                "verification_requirement": (
                    self.verification_requirement.to_canonical_data()
                    if self.verification_requirement is not None
                    else None
                ),
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    def to_schema_document(self) -> dict[str, object]:
        """Return the additive, version-marked 0.2 interchange document."""

        return {**self.to_dict(), "schema": self.schema_version}


Place = FinitePlace | InfinitePlace


__all__ = [
    "FinitePlace",
    "InfinitePlace",
    "InfinitePlaceKind",
    "Place",
]
