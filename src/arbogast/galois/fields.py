"""Pinned exact number-field presentations and explicit field embeddings.

Coefficient vectors are always in ascending power order: index ``i`` is the
coefficient of the pinned generator to the power ``i``.  No polynomial
reduction, generator renaming, or implicit field isomorphism is performed at a
backend boundary.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from fractions import Fraction
from math import gcd
from typing import ClassVar, TypeAlias, cast

from arbogast.backends.pari_certificate import PARI_VERIFIER_ID
from arbogast.cert import VerificationCertificate
from arbogast.core import CanonicalJSON, CanonicalObject, ValidationError
from arbogast.formats import (
    FIELD_EMBEDDING_SCHEMA,
    NUMBER_FIELD_ELEMENT_SCHEMA,
    NUMBER_FIELD_SCHEMA,
)

from .evidence import VerifiedPariEvidence, verified_pari_evidence
from .proof import VerificationRequirement, VerifierTrust

RationalLike: TypeAlias = int | Fraction | tuple[int, int]
RationalVector: TypeAlias = tuple[Fraction, ...]


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _rational(value: object, name: str) -> Fraction:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an exact rational")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, tuple) and len(value) == 2:
        numerator = _integer(value[0], f"{name} numerator")
        denominator = _integer(value[1], f"{name} denominator")
        if denominator == 0:
            raise ZeroDivisionError(f"{name} denominator cannot be zero")
        return Fraction(numerator, denominator)
    raise TypeError(f"{name} must be an integer, Fraction, or (numerator, denominator) pair")


def _rational_vector(
    values: Iterable[RationalLike],
    length: int,
    name: str,
    *,
    pad: bool,
) -> RationalVector:
    normalized = tuple(_rational(value, f"{name} coefficient") for value in values)
    if pad and len(normalized) <= length:
        normalized = (*normalized, *(Fraction(0) for _ in range(length - len(normalized))))
    if len(normalized) != length:
        raise ValidationError(f"{name} has length {len(normalized)}, expected {length}")
    return normalized


def rational_payload(value: Fraction) -> list[int]:
    """Return the portable exact encoding used throughout arithmetic schemas."""

    return [value.numerator, value.denominator]


def rational_vector_payload(vector: Sequence[Fraction]) -> list[list[int]]:
    return [rational_payload(value) for value in vector]


def _determinant(rows: Sequence[Sequence[Fraction]]) -> Fraction:
    size = len(rows)
    if any(len(row) != size for row in rows):
        raise ValidationError("determinant requires a square matrix")
    work = [list(row) for row in rows]
    determinant = Fraction(1)
    for column in range(size):
        pivot = next((row for row in range(column, size) if work[row][column]), None)
        if pivot is None:
            return Fraction(0)
        if pivot != column:
            work[column], work[pivot] = work[pivot], work[column]
            determinant = -determinant
        pivot_value = work[column][column]
        determinant *= pivot_value
        for row in range(column + 1, size):
            if not work[row][column]:
                continue
            coefficient = work[row][column] / pivot_value
            for index in range(column, size):
                work[row][index] -= coefficient * work[column][index]
    return determinant


def _solve_square(
    rows: Sequence[Sequence[Fraction]],
    target: Sequence[Fraction],
) -> RationalVector:
    size = len(rows)
    if len(target) != size or any(len(row) != size for row in rows):
        raise ValidationError("linear solve requires a square matrix and matching target")
    work = [[*row, target[index]] for index, row in enumerate(rows)]
    for column in range(size):
        pivot = next((row for row in range(column, size) if work[row][column]), None)
        if pivot is None:
            raise ZeroDivisionError("exact linear system is singular")
        work[column], work[pivot] = work[pivot], work[column]
        pivot_value = work[column][column]
        work[column] = [value / pivot_value for value in work[column]]
        for row in range(size):
            if row == column:
                continue
            coefficient = work[row][column]
            if coefficient:
                work[row] = [
                    left - coefficient * right
                    for left, right in zip(work[row], work[column], strict=True)
                ]
    return tuple(work[index][-1] for index in range(size))


def _transpose(rows: Sequence[Sequence[Fraction]]) -> tuple[RationalVector, ...]:
    return tuple(
        tuple(rows[row][column] for row in range(len(rows))) for column in range(len(rows))
    )


def _reduce_polynomial(
    coefficients: Iterable[Fraction],
    defining_polynomial: Sequence[int],
) -> RationalVector:
    degree = len(defining_polynomial) - 1
    work = list(coefficients)
    if len(work) < degree:
        work.extend(Fraction(0) for _ in range(degree - len(work)))
    leading = Fraction(defining_polynomial[-1])
    for exponent in range(len(work) - 1, degree - 1, -1):
        coefficient = work[exponent]
        if coefficient:
            shift = exponent - degree
            for index in range(degree):
                work[shift + index] -= coefficient * defining_polynomial[index] / leading
        work[exponent] = Fraction(0)
    return tuple(work[:degree])


def _multiply_vectors(
    left: Sequence[Fraction],
    right: Sequence[Fraction],
    defining_polynomial: Sequence[int],
) -> RationalVector:
    product = [Fraction(0)] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            product[left_index + right_index] += left_value * right_value
    return _reduce_polynomial(product, defining_polynomial)


def _is_prime_integer(value: int) -> bool:
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


def _trim_mod(polynomial: Sequence[int], prime: int) -> tuple[int, ...]:
    result = [value % prime for value in polynomial]
    while result and result[-1] == 0:
        result.pop()
    return tuple(result)


def _divmod_mod(
    dividend: Sequence[int],
    divisor: Sequence[int],
    prime: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    denominator = _trim_mod(divisor, prime)
    if not denominator:
        raise ZeroDivisionError("polynomial division by zero")
    work = list(_trim_mod(dividend, prime))
    quotient = [0] * max(1, len(work) - len(denominator) + 1)
    inverse_leading = pow(denominator[-1], -1, prime)
    while len(work) >= len(denominator):
        shift = len(work) - len(denominator)
        coefficient = work[-1] * inverse_leading % prime
        quotient[shift] = coefficient
        for index, value in enumerate(denominator):
            work[shift + index] = (work[shift + index] - coefficient * value) % prime
        work = list(_trim_mod(work, prime))
    return (_trim_mod(quotient, prime), tuple(work))


def _gcd_mod(left: Sequence[int], right: Sequence[int], prime: int) -> tuple[int, ...]:
    first = _trim_mod(left, prime)
    second = _trim_mod(right, prime)
    while second:
        _, remainder = _divmod_mod(first, second, prime)
        first, second = second, remainder
    if not first:
        return ()
    inverse = pow(first[-1], -1, prime)
    return tuple(value * inverse % prime for value in first)


def _multiply_mod(
    left: Sequence[int],
    right: Sequence[int],
    modulus: Sequence[int],
    prime: int,
) -> tuple[int, ...]:
    product = [0] * max(1, len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            product[left_index + right_index] = (
                product[left_index + right_index] + left_value * right_value
            ) % prime
    _, remainder = _divmod_mod(product, modulus, prime)
    return remainder


def _power_mod(
    base: Sequence[int],
    exponent: int,
    modulus: Sequence[int],
    prime: int,
) -> tuple[int, ...]:
    result: tuple[int, ...] = (1,)
    factor = _trim_mod(base, prime)
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = _multiply_mod(result, factor, modulus, prime)
        factor = _multiply_mod(factor, factor, modulus, prime)
        remaining >>= 1
    return result


def _prime_divisors(value: int) -> tuple[int, ...]:
    result: list[int] = []
    remaining = value
    candidate = 2
    while candidate * candidate <= remaining:
        if remaining % candidate == 0:
            result.append(candidate)
            while remaining % candidate == 0:
                remaining //= candidate
        candidate += 1
    if remaining > 1:
        result.append(remaining)
    return tuple(result)


def _irreducible_mod_prime(polynomial: Sequence[int], prime: int) -> bool:
    if not _is_prime_integer(prime):
        return False
    modulus = _trim_mod(polynomial, prime)
    degree = len(polynomial) - 1
    if len(modulus) != len(polynomial) or degree <= 0:
        return False
    inverse_leading = pow(modulus[-1], -1, prime)
    modulus = tuple(value * inverse_leading % prime for value in modulus)
    x: tuple[int, ...] = (0, 1)
    checkpoints = {degree // divisor for divisor in _prime_divisors(degree)}
    frobenius = x
    for iteration in range(1, degree + 1):
        frobenius = _power_mod(frobenius, prime, modulus, prime)
        if iteration in checkpoints:
            difference = tuple(
                (
                    (frobenius[index] if index < len(frobenius) else 0)
                    - (x[index] if index < len(x) else 0)
                )
                % prime
                for index in range(max(len(frobenius), len(x)))
            )
            if _gcd_mod(modulus, difference, prime) != (1,):
                return False
    final_difference = tuple(
        ((frobenius[index] if index < len(frobenius) else 0) - (x[index] if index < len(x) else 0))
        % prime
        for index in range(max(len(frobenius), len(x)))
    )
    return not _trim_mod(final_difference, prime)


def _has_rational_root(polynomial: Sequence[int]) -> bool:
    constant = polynomial[0]
    if constant == 0:
        return True
    magnitude = abs(constant)
    divisors: set[int] = set()
    candidate = 1
    while candidate * candidate <= magnitude:
        if magnitude % candidate == 0:
            divisors.add(candidate)
            divisors.add(magnitude // candidate)
        candidate += 1
    for root in (*sorted(divisors), *(-value for value in sorted(divisors))):
        value = 0
        for coefficient in reversed(polynomial):
            value = value * root + coefficient
        if value == 0:
            return True
    return False


def _squarefree_part(value: int) -> int:
    """Return the signed squarefree part of a nonzero integer."""

    if value == 0:
        raise ValidationError("a number-field discriminant cannot be zero")
    sign = -1 if value < 0 else 1
    remaining = abs(value)
    result = 1
    prime = 2
    while prime * prime <= remaining:
        exponent = 0
        while remaining % prime == 0:
            remaining //= prime
            exponent += 1
        if exponent % 2:
            result *= prime
        prime += 1
    if remaining > 1:
        result *= remaining
    return sign * result


def _quadratic_field_discriminant(polynomial: Sequence[int]) -> int:
    """Compute the exact field discriminant of a monic quadratic presentation."""

    if len(polynomial) != 3:
        raise ValidationError("quadratic discriminant requires a degree-two polynomial")
    polynomial_discriminant = polynomial[1] * polynomial[1] - 4 * polynomial[0]
    radicand = _squarefree_part(polynomial_discriminant)
    return radicand if radicand % 4 == 1 else 4 * radicand


def _quadratic_order_discriminant(
    polynomial: Sequence[int],
    basis: Sequence[Sequence[Fraction]],
) -> Fraction:
    polynomial_discriminant = polynomial[1] * polynomial[1] - 4 * polynomial[0]
    return _determinant(basis) ** 2 * polynomial_discriminant


def _certificate_rational(value: object, name: str) -> Fraction:
    if (
        not isinstance(value, list | tuple)
        or len(value) != 2
        or isinstance(value[0], bool)
        or not isinstance(value[0], int)
        or isinstance(value[1], bool)
        or not isinstance(value[1], int)
        or value[1] <= 0
    ):
        raise ValidationError(f"{name} must be a canonical rational pair")
    return Fraction(value[0], value[1])


def _certificate_vector(value: object, length: int, name: str) -> RationalVector:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ValidationError(f"{name} must be a sequence")
    result = tuple(_certificate_rational(item, name) for item in value)
    if len(result) != length:
        raise ValidationError(f"{name} has length {len(result)}, expected {length}")
    return result


@dataclass(frozen=True, slots=True)
class ModularIrreducibilityWitness(CanonicalObject):
    """A portable witness that the defining polynomial stays irreducible mod ``p``."""

    prime: int

    def __post_init__(self) -> None:
        if isinstance(self.prime, bool) or not isinstance(self.prime, int):
            raise TypeError("irreducibility witness prime must be an integer")
        if not _is_prime_integer(self.prime):
            raise ValidationError("irreducibility witness modulus must be prime")

    def verify(self, polynomial: Sequence[int]) -> bool:
        if not _irreducible_mod_prime(polynomial, self.prime):
            raise ValidationError("defining polynomial is not irreducible modulo the witness prime")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "prime": self.prime,
            "type": "arbogast.modular_irreducibility_witness",
        }

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())


@dataclass(frozen=True, slots=True, init=False)
class NumberField(CanonicalObject):
    """A number field with a pinned generator and proven maximal-order basis.

    ``defining_polynomial`` is a monic primitive irreducible integer polynomial
    in ascending order.  Degree one and quadratic maximality are replayed
    portably from discriminants.  Higher-degree presentations require a nested
    central PARI field-invariants certificate; naming PARI in a
    :class:`VerificationRequirement` is never treated as proof.
    """

    schema_version: ClassVar[str] = NUMBER_FIELD_SCHEMA

    defining_polynomial: tuple[int, ...]
    integral_basis: tuple[RationalVector, ...]
    generator_name: str = dataclass_field(compare=False, hash=False)
    irreducibility_witness: ModularIrreducibilityWitness | None
    irreducibility_requirement: VerificationRequirement | None
    field_invariants_certificate: VerificationCertificate | None = dataclass_field(
        compare=False,
        hash=False,
        repr=False,
    )

    def __init__(
        self,
        defining_polynomial: Iterable[int],
        *,
        integral_basis: Iterable[Iterable[RationalLike]] | None = None,
        generator_name: str = "a",
        irreducibility_witness: ModularIrreducibilityWitness | int | None = None,
        irreducibility_requirement: VerificationRequirement | None = None,
        field_invariants_certificate: VerificationCertificate | None = None,
    ) -> None:
        polynomial = tuple(
            _integer(coefficient, "defining-polynomial coefficient")
            for coefficient in defining_polynomial
        )
        if len(polynomial) < 2:
            raise ValidationError("a defining polynomial must have positive degree")
        if polynomial[-1] != 1:
            raise ValidationError("a number-field defining polynomial must be monic")
        coefficient_gcd = 0
        for coefficient in polynomial:
            coefficient_gcd = gcd(coefficient_gcd, abs(coefficient))
        if coefficient_gcd != 1:
            raise ValidationError("a defining polynomial must be primitive over the integers")
        degree = len(polynomial) - 1
        witness = (
            ModularIrreducibilityWitness(irreducibility_witness)
            if isinstance(irreducibility_witness, int)
            and not isinstance(irreducibility_witness, bool)
            else irreducibility_witness
        )
        if witness is not None and not isinstance(witness, ModularIrreducibilityWitness):
            raise TypeError(
                "irreducibility_witness must be a ModularIrreducibilityWitness or prime integer"
            )
        if irreducibility_requirement is not None:
            if not isinstance(irreducibility_requirement, VerificationRequirement):
                raise TypeError("irreducibility_requirement must be a VerificationRequirement")
            if irreducibility_requirement.trust is not VerifierTrust.PINNED_EXTERNAL:
                raise ValidationError(
                    "an external irreducibility requirement must use pinned-external trust"
                )
        if degree in (2, 3) and _has_rational_root(polynomial):
            raise ValidationError("number-field defining polynomial is reducible over Q")
        if witness is not None:
            witness.verify(polynomial)
        if field_invariants_certificate is not None and not isinstance(
            field_invariants_certificate, VerificationCertificate
        ):
            raise TypeError("field_invariants_certificate must be a VerificationCertificate")
        if degree >= 4 and witness is None and field_invariants_certificate is None:
            raise ValidationError(
                "degree >= 4 needs a modular irreducibility witness or a nested "
                "field-invariants certificate; a bare verifier requirement is not evidence"
            )
        if not isinstance(generator_name, str):
            raise TypeError("generator_name must be a string")
        normalized_name = unicodedata.normalize("NFC", generator_name)
        if (
            not normalized_name
            or normalized_name.strip() != normalized_name
            or any(ord(character) < 0x20 for character in normalized_name)
        ):
            raise ValidationError("generator_name must be a nonempty, trimmed printable string")
        if integral_basis is None:
            basis = tuple(
                tuple(Fraction(1 if row == column else 0) for column in range(degree))
                for row in range(degree)
            )
        else:
            raw_basis = tuple(tuple(row) for row in integral_basis)
            if len(raw_basis) != degree:
                raise ValidationError(
                    f"integral_basis has {len(raw_basis)} rows, expected {degree}"
                )
            basis = tuple(
                _rational_vector(row, degree, "integral-basis row", pad=False) for row in raw_basis
            )
        if _determinant(basis) == 0:
            raise ValidationError("integral_basis must be a rational basis of the field")
        object.__setattr__(self, "defining_polynomial", polynomial)
        object.__setattr__(self, "integral_basis", basis)
        object.__setattr__(self, "generator_name", normalized_name)
        object.__setattr__(self, "irreducibility_witness", witness)
        object.__setattr__(
            self,
            "irreducibility_requirement",
            irreducibility_requirement,
        )
        object.__setattr__(
            self,
            "field_invariants_certificate",
            field_invariants_certificate,
        )
        self._validate_integral_order()
        self._validate_maximal_order()

    @classmethod
    def rationals(cls) -> NumberField:
        """Return the pinned presentation ``Q[x]/(x)``."""

        return cls((0, 1), generator_name="0")

    rational_field = rationals

    @property
    def degree(self) -> int:
        return len(self.defining_polynomial) - 1

    @property
    def field_id(self) -> str:
        return self.content_id

    @property
    def zero(self) -> NumberFieldElement:
        return NumberFieldElement(self, ())

    @property
    def one(self) -> NumberFieldElement:
        return NumberFieldElement(self, (1,))

    @property
    def generator(self) -> NumberFieldElement:
        return NumberFieldElement(self, (0, 1))

    def element(
        self,
        coefficients: RationalLike | Iterable[RationalLike] | NumberFieldElement,
    ) -> NumberFieldElement:
        if isinstance(coefficients, NumberFieldElement):
            if coefficients.field != self:
                raise ValidationError("cannot coerce an element from a different pinned field")
            return coefficients
        if isinstance(coefficients, (int, Fraction)):
            return NumberFieldElement(self, (coefficients,))
        if (
            isinstance(coefficients, tuple)
            and len(coefficients) == 2
            and all(
                isinstance(value, int) and not isinstance(value, bool) for value in coefficients
            )
            and self.degree != 2
        ):
            # A two-tuple is a coefficient vector when the field has degree two;
            # elsewhere it retains the convenient rational-pair interpretation.
            return NumberFieldElement(
                self,
                (
                    Fraction(
                        cast(int, coefficients[0]),
                        cast(int, coefficients[1]),
                    ),
                ),
            )
        return NumberFieldElement(self, coefficients)

    def __call__(
        self,
        coefficients: RationalLike | Iterable[RationalLike] | NumberFieldElement,
    ) -> NumberFieldElement:
        return self.element(coefficients)

    def from_integral_basis_coordinates(
        self,
        coordinates: Iterable[RationalLike],
    ) -> NumberFieldElement:
        values = _rational_vector(
            coordinates,
            self.degree,
            "integral-basis coordinates",
            pad=False,
        )
        power = tuple(
            sum(values[row] * self.integral_basis[row][column] for row in range(self.degree))
            for column in range(self.degree)
        )
        return NumberFieldElement(self, power)

    def _validate_integral_order(self) -> None:
        one_coordinates = self.one.coordinates_in_integral_basis()
        if any(value.denominator != 1 for value in one_coordinates):
            raise ValidationError("integral_basis does not contain the multiplicative identity")
        basis_elements = tuple(NumberFieldElement(self, row) for row in self.integral_basis)
        for left in basis_elements:
            for right in basis_elements:
                coordinates = (left * right).coordinates_in_integral_basis()
                if any(value.denominator != 1 for value in coordinates):
                    raise ValidationError("integral_basis is not closed under field multiplication")

    @property
    def discriminant(self) -> int:
        """Return the proven field discriminant when replay is portable.

        For higher-degree externally certified fields the exact value remains
        available in the nested field-invariants certificate rather than as an
        unverified cached attribute.
        """

        if self.degree == 1:
            return 1
        if self.degree == 2:
            return _quadratic_field_discriminant(self.defining_polynomial)
        if self.field_invariants_certificate is None:
            raise AttributeError("higher-degree field discriminant needs nested evidence")
        evidence = verified_pari_evidence(
            self.field_invariants_certificate,
            "field_invariants",
        )
        value = evidence.payload.to_dict().get("discriminant")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError("field-invariants certificate has an invalid discriminant")
        return value

    def _validate_maximal_order(self) -> None:
        certificate = self.field_invariants_certificate
        if self.degree == 1:
            if _determinant(self.integral_basis) ** 2 != 1:
                raise ValidationError("integral_basis is not the maximal order of Q")
        elif self.degree == 2:
            order_discriminant = _quadratic_order_discriminant(
                self.defining_polynomial,
                self.integral_basis,
            )
            if order_discriminant != _quadratic_field_discriminant(self.defining_polynomial):
                raise ValidationError("integral_basis is a nonmaximal quadratic order")
        elif certificate is None:
            raise ValidationError(
                "higher-degree integral_basis maximality needs a nested "
                "field-invariants certificate; a bare verifier requirement is not evidence"
            )

        if certificate is not None:
            evidence = verified_pari_evidence(certificate, "field_invariants")
            self._bind_field_invariants_evidence(evidence)

    def _bind_field_invariants_evidence(self, evidence: VerifiedPariEvidence) -> None:
        replay = evidence.replay.to_dict()
        if set(replay) != {"arguments", "field"} or replay.get("arguments") != {}:
            raise ValidationError("field-invariants replay has foreign arguments")
        raw_field = replay.get("field")
        if not isinstance(raw_field, dict):
            raise ValidationError("field-invariants replay omits its field presentation")
        expected_replay_keys = {
            "defining_polynomial",
            "field_id",
            "identity",
            "integral_basis",
        }
        if set(raw_field) != expected_replay_keys:
            raise ValidationError("field-invariants replay has a foreign field shape")
        replay_polynomial = _certificate_vector(
            raw_field.get("defining_polynomial"),
            self.degree + 1,
            "replayed defining polynomial",
        )
        if replay_polynomial != tuple(Fraction(value) for value in self.defining_polynomial):
            raise ValidationError("field-invariants certificate names a different polynomial")
        replay_basis = raw_field.get("integral_basis")
        if replay_basis is not None:
            if isinstance(replay_basis, str | bytes) or not isinstance(replay_basis, Sequence):
                raise ValidationError("replayed integral basis must be a matrix")
            normalized_replay_basis = tuple(
                _certificate_vector(row, self.degree, "replayed integral-basis row")
                for row in replay_basis
            )
            if normalized_replay_basis != self.integral_basis:
                raise ValidationError("field-invariants replay names a different basis")

        payload = evidence.payload.to_dict()
        expected_payload_keys = {
            "degree",
            "discriminant",
            "field_id",
            "index",
            "integral_basis",
            "signature",
        }
        if set(payload) != expected_payload_keys:
            raise ValidationError("field-invariants certificate has a foreign payload shape")
        if payload.get("degree") != self.degree:
            raise ValidationError("field-invariants certificate has the wrong degree")
        if payload.get("field_id") != raw_field.get("field_id"):
            raise ValidationError("field-invariants payload and replay field IDs disagree")
        discriminant = payload.get("discriminant")
        index = payload.get("index")
        if (
            isinstance(discriminant, bool)
            or not isinstance(discriminant, int)
            or isinstance(index, bool)
            or not isinstance(index, int)
            or index <= 0
        ):
            raise ValidationError("field-invariants certificate has invalid exact invariants")
        raw_signature = payload.get("signature")
        if (
            isinstance(raw_signature, str | bytes)
            or not isinstance(raw_signature, Sequence)
            or len(raw_signature) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in raw_signature)
            or raw_signature[0] + 2 * raw_signature[1] != self.degree
        ):
            raise ValidationError("field-invariants certificate has an invalid signature")
        raw_basis = payload.get("integral_basis")
        if isinstance(raw_basis, str | bytes) or not isinstance(raw_basis, Sequence):
            raise ValidationError("field-invariants certificate omits its integral basis")
        certified_basis = tuple(
            _certificate_vector(row, self.degree, "certified integral-basis row")
            for row in raw_basis
        )
        if certified_basis != self.integral_basis:
            raise ValidationError("field-invariants certificate proves a different integral basis")
        requirement = self.irreducibility_requirement
        if requirement is not None and (
            requirement.verifier.casefold() not in {"pari", PARI_VERIFIER_ID}
            or requirement.version != evidence.backend_version
        ):
            raise ValidationError(
                "field verifier requirement does not match the nested PARI certificate"
            )

    def verify(self) -> bool:
        return (
            NumberField(
                self.defining_polynomial,
                integral_basis=self.integral_basis,
                generator_name=self.generator_name,
                irreducibility_witness=self.irreducibility_witness,
                irreducibility_requirement=self.irreducibility_requirement,
                field_invariants_certificate=self.field_invariants_certificate,
            )
            == self
        )

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "defining_polynomial": list(self.defining_polynomial),
                "integral_basis": [rational_vector_payload(row) for row in self.integral_basis],
                "irreducibility_requirement": (
                    self.irreducibility_requirement.to_canonical_data()
                    if self.irreducibility_requirement is not None
                    else None
                ),
                "irreducibility_witness": (
                    self.irreducibility_witness.to_canonical_data()
                    if self.irreducibility_witness is not None
                    else None
                ),
                "type": "arbogast.number_field",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    def to_schema_document(self) -> dict[str, object]:
        """Return the additive, version-marked 0.2 interchange document."""

        return {**self.to_dict(), "schema": self.schema_version}


@dataclass(frozen=True, slots=True, init=False)
class NumberFieldElement(CanonicalObject):
    """One exact element in the pinned power basis of a :class:`NumberField`."""

    schema_version: ClassVar[str] = NUMBER_FIELD_ELEMENT_SCHEMA

    field: NumberField
    coefficients: RationalVector

    def __init__(
        self,
        field: NumberField,
        coefficients: Iterable[RationalLike],
    ) -> None:
        if not isinstance(field, NumberField):
            raise TypeError("field must be a NumberField")
        raw = tuple(_rational(value, "element coefficient") for value in coefficients)
        reduced = _reduce_polynomial(raw, field.defining_polynomial)
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "coefficients", reduced)

    @property
    def element_id(self) -> str:
        return self.content_id

    @property
    def is_zero(self) -> bool:
        return not any(self.coefficients)

    def _coerce(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        if isinstance(other, NumberFieldElement):
            if other.field != self.field:
                raise ValidationError("number-field elements use different pinned fields")
            return other
        return NumberFieldElement(self.field, (_rational(other, "scalar"),))

    def __add__(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        right = self._coerce(other)
        return NumberFieldElement(
            self.field,
            tuple(
                left + value
                for left, value in zip(self.coefficients, right.coefficients, strict=True)
            ),
        )

    def __radd__(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        return self + other

    def __sub__(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        right = self._coerce(other)
        return NumberFieldElement(
            self.field,
            tuple(
                left - value
                for left, value in zip(self.coefficients, right.coefficients, strict=True)
            ),
        )

    def __rsub__(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        return self._coerce(other) - self

    def __neg__(self) -> NumberFieldElement:
        return NumberFieldElement(self.field, tuple(-value for value in self.coefficients))

    def __mul__(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        right = self._coerce(other)
        return NumberFieldElement(
            self.field,
            _multiply_vectors(
                self.coefficients,
                right.coefficients,
                self.field.defining_polynomial,
            ),
        )

    def __rmul__(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        return self * other

    def __pow__(self, exponent: int) -> NumberFieldElement:
        exponent = _integer(exponent, "exponent")
        if exponent < 0:
            return self.inverse() ** (-exponent)
        result = self.field.one
        factor = self
        remaining = exponent
        while remaining:
            if remaining & 1:
                result = result * factor
            factor = factor * factor
            remaining >>= 1
        return result

    def multiplication_matrix(self) -> tuple[RationalVector, ...]:
        """Return columns of multiplication by this element in the power basis."""

        basis = tuple(
            NumberFieldElement(
                self.field,
                tuple(1 if index == exponent else 0 for index in range(self.field.degree)),
            )
            for exponent in range(self.field.degree)
        )
        columns = tuple((self * basis_element).coefficients for basis_element in basis)
        return tuple(
            tuple(columns[column][row] for column in range(self.field.degree))
            for row in range(self.field.degree)
        )

    def inverse(self) -> NumberFieldElement:
        if self.is_zero:
            raise ZeroDivisionError("zero has no multiplicative inverse")
        matrix = self.multiplication_matrix()
        target = (Fraction(1), *(Fraction(0) for _ in range(self.field.degree - 1)))
        try:
            solution = _solve_square(matrix, target)
        except ZeroDivisionError as error:
            raise ZeroDivisionError(
                "element is a zero divisor in the supplied polynomial presentation"
            ) from error
        result = NumberFieldElement(self.field, solution)
        if self * result != self.field.one:
            raise ArithmeticError("exact inverse replay failed")
        return result

    def __truediv__(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        return self * self._coerce(other).inverse()

    def __rtruediv__(self, other: RationalLike | NumberFieldElement) -> NumberFieldElement:
        return self._coerce(other) * self.inverse()

    def norm(self) -> Fraction:
        return _determinant(self.multiplication_matrix())

    def trace(self) -> Fraction:
        matrix = self.multiplication_matrix()
        return sum((matrix[index][index] for index in range(self.field.degree)), Fraction(0))

    def coordinates_in_integral_basis(self) -> RationalVector:
        return _solve_square(
            _transpose(self.field.integral_basis),
            self.coefficients,
        )

    @property
    def is_integral(self) -> bool:
        return all(
            coordinate.denominator == 1 for coordinate in self.coordinates_in_integral_basis()
        )

    def verify(self) -> bool:
        return NumberFieldElement(self.field, self.coefficients) == self

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "coefficients": rational_vector_payload(self.coefficients),
                "field_id": self.field.field_id,
                "type": "arbogast.number_field_element",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    def to_schema_document(self) -> dict[str, object]:
        """Return the additive, version-marked 0.2 interchange document."""

        return {**self.to_dict(), "schema": self.schema_version}


@dataclass(frozen=True, slots=True)
class FieldEmbedding(CanonicalObject):
    """An explicit embedding determined by the image of the pinned generator."""

    schema_version: ClassVar[str] = FIELD_EMBEDDING_SCHEMA

    domain: NumberField
    codomain: NumberField
    generator_image: NumberFieldElement

    def __post_init__(self) -> None:
        if not isinstance(self.domain, NumberField) or not isinstance(self.codomain, NumberField):
            raise TypeError("embedding domain and codomain must be NumberField values")
        if not isinstance(self.generator_image, NumberFieldElement):
            raise TypeError("generator_image must be a NumberFieldElement")
        if self.generator_image.field != self.codomain:
            raise ValidationError("generator_image does not belong to the embedding codomain")
        value = self.codomain.zero
        for coefficient in reversed(self.domain.defining_polynomial):
            value = value * self.generator_image + coefficient
        if not value.is_zero:
            raise ValidationError(
                "the proposed generator image does not satisfy the domain polynomial"
            )

    @property
    def embedding_id(self) -> str:
        return self.content_id

    def apply(self, element: NumberFieldElement) -> NumberFieldElement:
        if not isinstance(element, NumberFieldElement) or element.field != self.domain:
            raise ValidationError("embedding input does not belong to its pinned domain")
        value = self.codomain.zero
        for coefficient in reversed(element.coefficients):
            value = value * self.generator_image + coefficient
        return value

    def __call__(self, element: NumberFieldElement) -> NumberFieldElement:
        return self.apply(element)

    def verify(self) -> bool:
        FieldEmbedding(self.domain, self.codomain, self.generator_image)
        return self(self.domain.one) == self.codomain.one

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "codomain_id": self.codomain.field_id,
                "domain_id": self.domain.field_id,
                "generator_image": rational_vector_payload(self.generator_image.coefficients),
                "type": "arbogast.field_embedding",
            },
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], self.to_canonical_data())

    def to_schema_document(self) -> dict[str, object]:
        """Return the additive, version-marked 0.2 interchange document."""

        return {**self.to_dict(), "schema": self.schema_version}


__all__ = [
    "FieldEmbedding",
    "ModularIrreducibilityWitness",
    "NumberField",
    "NumberFieldElement",
    "RationalLike",
    "RationalVector",
    "rational_payload",
    "rational_vector_payload",
]
