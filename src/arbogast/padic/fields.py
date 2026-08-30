"""Exact bounded presentations of finite local fields and their precision rings.

The portable slice deliberately supports only the rational field, monogenic
unramified extensions, and monogenic Eisenstein extensions.  Infinite p-adic
values are never represented by a finite digit string: :class:`PAdicElement`
is an exact rational-coordinate point in the pinned algebraic presentation,
while :class:`PAdicBall` is an exact coset modulo a power of the uniformizer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from itertools import islice
from math import gcd
from typing import TYPE_CHECKING, ClassVar, TypeAlias, cast

from arbogast.cert import VerificationCertificate
from arbogast.core import CanonicalJSON

from ._schema import (
    MAX_CANONICAL_INTEGER_BITS,
    MAX_EXACT_REPLAY_WORK,
    MAX_LOCAL_DEGREE,
    MAX_PRECISION,
    MAX_PRECISION_WORK,
    MAX_PRIME_BITS,
    PAdicSchemaObject,
    PAdicSemanticObject,
    strict_canonical_equal,
    strict_int,
)
from .errors import PAdicValidationError, PAdicVerificationError

if TYPE_CHECKING:
    from .certificate import PAdicPayloadReplay

RationalLike: TypeAlias = int | Fraction | tuple[int, int]
RationalVector: TypeAlias = tuple[Fraction, ...]
IntegerMatrix: TypeAlias = tuple[tuple[int, ...], ...]

MAX_PADIC_PRIME = 2_147_483_647
MAX_PADIC_DEGREE = 16
MAX_PADIC_PRECISION = 256
MAX_PADIC_INTEGER_BITS = MAX_CANONICAL_INTEGER_BITS
MAX_PADIC_WORK_BITS = 4096

# Portable construction is deliberately narrower than the transport envelope.
# The wider shared limits remain available to externally certified future modes.
MAX_PORTABLE_LOCAL_DEGREE = min(16, MAX_LOCAL_DEGREE)
MAX_PORTABLE_PRECISION = min(256, MAX_PRECISION)

ValidationError = PAdicValidationError


def _strict_int(value: object, name: str, *, minimum: int | None = None) -> int:
    result = strict_int(value, name, minimum=minimum)
    if result.bit_length() > MAX_PADIC_INTEGER_BITS:
        raise ValidationError(f"{name} exceeds the portable integer-size bound")
    return result


def _rational(value: RationalLike, name: str) -> Fraction:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an exact rational")
    if isinstance(value, Fraction):
        result = value
    elif isinstance(value, int):
        result = Fraction(value)
    elif isinstance(value, tuple) and len(value) == 2:
        numerator = _strict_int(value[0], f"{name} numerator")
        denominator = _strict_int(value[1], f"{name} denominator")
        if denominator == 0:
            raise ZeroDivisionError(f"{name} denominator cannot be zero")
        result = Fraction(numerator, denominator)
    else:
        raise TypeError(f"{name} must be an integer, Fraction, or rational pair")
    if (
        result.numerator.bit_length() > MAX_PADIC_INTEGER_BITS
        or result.denominator.bit_length() > MAX_PADIC_INTEGER_BITS
    ):
        raise ValidationError(f"{name} exceeds the portable rational-size bound")
    return result


def _rational_vector(
    values: Iterable[RationalLike],
    length: int,
    name: str,
    *,
    pad: bool = False,
) -> RationalVector:
    raw = tuple(islice(values, length + 1))
    result = tuple(_rational(value, f"{name} coordinate") for value in raw)
    if pad and len(result) <= length:
        result = (*result, *(Fraction(0) for _ in range(length - len(result))))
    if len(result) != length:
        raise ValidationError(f"{name} has length {len(result)}, expected {length}")
    return result


def _rational_payload(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def _vector_payload(values: Sequence[Fraction]) -> list[list[int]]:
    return [_rational_payload(value) for value in values]


def _raw_mapping(value: Mapping[str, object], expected: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise PAdicVerificationError(f"{name} has a foreign transport shape")
    return dict(value)


def _raw_list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise PAdicVerificationError(f"{name} must be a strict JSON array")
    return cast(list[object], value)


def _decode_rational(value: object, name: str) -> Fraction:
    pair = _raw_list(value, name)
    if len(pair) != 2 or any(type(item) is not int for item in pair):
        raise PAdicVerificationError(f"{name} must be a canonical rational pair")
    numerator, denominator = cast(tuple[int, int], tuple(pair))
    if denominator <= 0 or gcd(abs(numerator), denominator) != 1:
        raise PAdicVerificationError(f"{name} rational pair is not reduced and positive")
    return _rational((numerator, denominator), name)


def _decode_vector(value: object, length: int, name: str) -> RationalVector:
    raw = _raw_list(value, name)
    if len(raw) != length:
        raise PAdicVerificationError(f"{name} has the wrong length")
    return tuple(_decode_rational(item, f"{name}[{index}]") for index, item in enumerate(raw))


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


def _trim_mod(values: Sequence[int], prime: int) -> tuple[int, ...]:
    result = [value % prime for value in values]
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
    inverse = pow(denominator[-1], -1, prime)
    while len(work) >= len(denominator):
        shift = len(work) - len(denominator)
        coefficient = work[-1] * inverse % prime
        quotient[shift] = coefficient
        for index, value in enumerate(denominator):
            work[shift + index] = (work[shift + index] - coefficient * value) % prime
        work = list(_trim_mod(work, prime))
    return (_trim_mod(quotient, prime), tuple(work))


def _multiply_mod(
    left: Sequence[int],
    right: Sequence[int],
    modulus: Sequence[int],
    prime: int,
) -> tuple[int, ...]:
    product = [0] * max(1, len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            product[left_index + right_index] += left_value * right_value
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
    modulus = _trim_mod(polynomial, prime)
    degree = len(polynomial) - 1
    if degree <= 0 or len(modulus) != len(polynomial):
        return False
    if degree == 1:
        return True
    modulus = tuple(value * pow(modulus[-1], -1, prime) % prime for value in modulus)
    x: tuple[int, ...] = (0, 1)
    checkpoints = {degree // divisor for divisor in _prime_divisors(degree)}
    frobenius = x
    for iteration in range(1, degree + 1):
        frobenius = _power_mod(frobenius, prime, modulus, prime)
        if iteration in checkpoints:
            size = max(len(frobenius), len(x))
            difference = tuple(
                (
                    (frobenius[index] if index < len(frobenius) else 0)
                    - (x[index] if index < len(x) else 0)
                )
                % prime
                for index in range(size)
            )
            if _gcd_mod(modulus, difference, prime) != (1,):
                return False
    size = max(len(frobenius), len(x))
    final = tuple(
        ((frobenius[index] if index < len(frobenius) else 0) - (x[index] if index < len(x) else 0))
        % prime
        for index in range(size)
    )
    return not _trim_mod(final, prime)


def _determinant(rows: Sequence[Sequence[Fraction]]) -> Fraction:
    size = len(rows)
    if any(len(row) != size for row in rows):
        raise ValidationError("determinant requires a square matrix")
    work = [list(row) for row in rows]
    result = Fraction(1)
    for column in range(size):
        pivot = next((row for row in range(column, size) if work[row][column]), None)
        if pivot is None:
            return Fraction(0)
        if pivot != column:
            work[column], work[pivot] = work[pivot], work[column]
            result = -result
        pivot_value = work[column][column]
        result *= pivot_value
        for row in range(column + 1, size):
            coefficient = work[row][column] / pivot_value
            for index in range(column, size):
                work[row][index] -= coefficient * work[column][index]
    return result


def _solve_square(
    rows: Sequence[Sequence[Fraction]],
    target: Sequence[Fraction],
) -> RationalVector:
    size = len(rows)
    if len(target) != size or any(len(row) != size for row in rows):
        raise ValidationError("linear solve requires a square matrix")
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


def _reduce_polynomial(
    coefficients: Sequence[Fraction],
    defining_polynomial: Sequence[int],
) -> RationalVector:
    degree = len(defining_polynomial) - 1
    work = [*coefficients, *(Fraction(0) for _ in range(max(0, degree - len(coefficients))))]
    for exponent in range(len(work) - 1, degree - 1, -1):
        coefficient = work[exponent]
        if coefficient:
            shift = exponent - degree
            for index in range(degree):
                work[shift + index] -= coefficient * defining_polynomial[index]
        work[exponent] = Fraction(0)
    return tuple(work[:degree])


def _multiply_power_vectors(
    left: Sequence[Fraction],
    right: Sequence[Fraction],
    defining_polynomial: Sequence[int],
) -> RationalVector:
    product = [Fraction(0)] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            product[left_index + right_index] += left_value * right_value
    return _reduce_polynomial(product, defining_polynomial)


def _extended_gcd(left: int, right: int) -> tuple[int, int, int]:
    old_r, r = abs(left), abs(right)
    old_s, s = 1, 0
    old_t, t = 0, 1
    while r:
        quotient = old_r // r
        old_r, r = r, old_r - quotient * r
        old_s, s = s, old_s - quotient * s
        old_t, t = t, old_t - quotient * t
    return (
        old_r,
        old_s if left >= 0 else -old_s,
        old_t if right >= 0 else -old_t,
    )


def _column_hnf(matrix: Sequence[Sequence[int]]) -> IntegerMatrix:
    """Return the canonical upper-triangular column HNF of a square lattice."""

    size = len(matrix)
    if size == 0 or any(len(row) != size for row in matrix):
        raise ValidationError("column HNF requires a nonempty square matrix")
    work = [list(row) for row in matrix]
    for row in range(size - 1, -1, -1):
        for column in range(row):
            left = work[row][column]
            right = work[row][row]
            if left == 0:
                continue
            divisor, coefficient_left, coefficient_right = _extended_gcd(left, right)
            old_left = [work[index][column] for index in range(size)]
            old_right = [work[index][row] for index in range(size)]
            for index in range(size):
                work[index][column] = (right // divisor) * old_left[index] - (
                    left // divisor
                ) * old_right[index]
                work[index][row] = (
                    coefficient_left * old_left[index] + coefficient_right * old_right[index]
                )
        pivot = work[row][row]
        if pivot == 0:
            raise ValidationError("column HNF requires a full-rank lattice")
        if pivot < 0:
            for index in range(size):
                work[index][row] = -work[index][row]
            pivot = -pivot
        for column in range(row + 1, size):
            quotient, _ = divmod(work[row][column], pivot)
            if quotient:
                for index in range(size):
                    work[index][column] -= quotient * work[index][row]
    result = tuple(tuple(row) for row in work)
    _validate_hnf(result)
    return result


def _validate_hnf(matrix: IntegerMatrix) -> None:
    size = len(matrix)
    if size == 0 or any(len(row) != size for row in matrix):
        raise ValidationError("HNF must be a nonempty square matrix")
    for row in range(size):
        pivot = matrix[row][row]
        if pivot <= 0:
            raise ValidationError("HNF diagonal entries must be positive")
        if any(matrix[row][column] != 0 for column in range(row)):
            raise ValidationError("column HNF must be upper triangular")
        if any(not 0 <= matrix[row][column] < pivot for column in range(row + 1, size)):
            raise ValidationError("column HNF residues are not canonical")


def _reduce_hnf(vector: Sequence[int], hnf: IntegerMatrix) -> tuple[int, ...]:
    if len(vector) != len(hnf):
        raise ValidationError("HNF reduction vector has the wrong dimension")
    work = list(vector)
    for column in range(len(hnf) - 1, -1, -1):
        quotient, remainder = divmod(work[column], hnf[column][column])
        work[column] = remainder
        for row in range(column):
            work[row] -= quotient * hnf[row][column]
    return tuple(work)


def _lattice_coordinates(hnf: IntegerMatrix, vector: Sequence[int]) -> RationalVector:
    return _solve_square(
        tuple(tuple(Fraction(value) for value in row) for row in hnf),
        tuple(Fraction(value) for value in vector),
    )


def _in_lattice(hnf: IntegerMatrix, vector: Sequence[int]) -> bool:
    return all(value.denominator == 1 for value in _lattice_coordinates(hnf, vector))


def _integer_matrix_multiply(left: IntegerMatrix, right: IntegerMatrix) -> IntegerMatrix:
    size = len(left)
    if (
        any(len(row) != size for row in left)
        or len(right) != size
        or any(len(row) != size for row in right)
    ):
        raise ValidationError("integer matrix multiplication requires equal square shapes")
    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(size))
            for column in range(size)
        )
        for row in range(size)
    )


def _integer_matrix_power(matrix: IntegerMatrix, exponent: int) -> IntegerMatrix:
    size = len(matrix)
    result: IntegerMatrix = tuple(
        tuple(1 if row == column else 0 for column in range(size)) for row in range(size)
    )
    factor = matrix
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = _integer_matrix_multiply(result, factor)
        remaining >>= 1
        if remaining:
            factor = _integer_matrix_multiply(factor, factor)
    return result


def _identity_integer_matrix(size: int) -> IntegerMatrix:
    return tuple(tuple(1 if row == column else 0 for column in range(size)) for row in range(size))


def _adjugate(matrix: IntegerMatrix) -> tuple[int, IntegerMatrix]:
    """Return the signed determinant and exact integral adjugate."""

    size = len(matrix)
    rational = tuple(tuple(Fraction(value) for value in row) for row in matrix)
    determinant = _determinant(rational)
    if determinant.denominator != 1 or determinant == 0:
        raise ValidationError("p-primary saturation requires a full-rank integer lattice")
    signed_determinant = determinant.numerator
    inverse_columns = tuple(
        _solve_square(
            rational,
            tuple(Fraction(1 if row == column else 0) for row in range(size)),
        )
        for column in range(size)
    )
    rows: list[tuple[int, ...]] = []
    for row in range(size):
        entries: list[int] = []
        for column in range(size):
            value = signed_determinant * inverse_columns[column][row]
            if value.denominator != 1:
                raise PAdicVerificationError("integer lattice adjugate was not integral")
            entries.append(value.numerator)
        rows.append(tuple(entries))
    return signed_determinant, tuple(rows)


def _modular_row_kernel_basis(coefficients: Sequence[int], modulus: int) -> IntegerMatrix:
    """Return a basis for ``{x in Z^n : coefficients*x == 0 mod modulus}``."""

    size = len(coefficients)
    transform = [list(row) for row in _identity_integer_matrix(size)]
    reduced = list(coefficients)
    for column in range(1, size):
        left = reduced[0]
        right = reduced[column]
        if left == 0 and right == 0:
            continue
        divisor, coefficient_left, coefficient_right = _extended_gcd(left, right)
        old_first = [transform[row][0] for row in range(size)]
        old_column = [transform[row][column] for row in range(size)]
        for row in range(size):
            transform[row][0] = (
                coefficient_left * old_first[row] + coefficient_right * old_column[row]
            )
            transform[row][column] = (
                -(right // divisor) * old_first[row] + (left // divisor) * old_column[row]
            )
        reduced[0] = divisor
        reduced[column] = 0
    if reduced[0] < 0:
        for row in range(size):
            transform[row][0] = -transform[row][0]
        reduced[0] = -reduced[0]
    index = modulus // gcd(modulus, reduced[0])
    for row in range(size):
        transform[row][0] *= index
    return tuple(tuple(row) for row in transform)


def _p_primary_saturation(
    matrix: IntegerMatrix,
    prime: int,
    expected_valuation: int,
) -> IntegerMatrix:
    """Saturate a full-rank column lattice away from ``prime``.

    If ``A`` is the supplied basis, an integral vector ``x`` lies in the
    localized lattice precisely when ``adj(A) x`` is divisible by
    ``p^v_p(det(A))``.  Intersecting those exact congruence kernels removes
    every prime-to-``p`` index without factoring the unit part of the norm.
    """

    signed_determinant, adjugate = _adjugate(matrix)
    determinant_valuation = _vp_integer(signed_determinant, prime)
    if determinant_valuation != expected_valuation:
        raise ValidationError("uniformizer-power lattice has the wrong p-primary index")
    modulus = prime**expected_valuation
    basis = _identity_integer_matrix(len(matrix))
    for constraint in adjugate:
        coefficients = tuple(
            sum(constraint[index] * basis[index][column] for index in range(len(matrix)))
            for column in range(len(matrix))
        )
        kernel = _modular_row_kernel_basis(coefficients, modulus)
        basis = _column_hnf(_integer_matrix_multiply(basis, kernel))
    determinant = 1
    for index in range(len(matrix)):
        determinant *= basis[index][index]
    if determinant != modulus:
        raise PAdicVerificationError("p-primary saturation produced the wrong lattice index")
    for column in range(len(matrix)):
        generator = tuple(matrix[row][column] for row in range(len(matrix)))
        if not _in_lattice(basis, generator):
            raise PAdicVerificationError("p-primary saturation lost an input lattice generator")
    quotient, remainder = divmod(abs(signed_determinant), determinant)
    if remainder or quotient % prime == 0:
        raise PAdicVerificationError("p-primary saturation retained a nonlocal index factor")
    return basis


def _uniformizer_ideal_chain(field: PAdicField, precision: int) -> tuple[IntegerMatrix, ...]:
    size = field.degree
    uniformizer_matrix = field.multiplication_matrix(field.uniformizer_element)
    if any(value.denominator != 1 for row in uniformizer_matrix for value in row):
        raise ValidationError("uniformizer multiplication must be integral")
    integer_uniformizer = tuple(
        tuple(value.numerator for value in row) for row in uniformizer_matrix
    )
    entry_bits = max(
        1,
        *(abs(value).bit_length() for row in integer_uniformizer for value in row),
    )
    coefficient_bits = entry_bits + (field.prime.bit_length() * field.residue_degree * precision)
    estimated_work = size**4 * precision * coefficient_bits
    if estimated_work > MAX_EXACT_REPLAY_WORK:
        raise ValidationError("precision-ring ideal saturation exceeds the exact replay work bound")
    ideals: list[IntegerMatrix] = [_identity_integer_matrix(size)]
    for exponent in range(1, precision + 1):
        candidate = _integer_matrix_multiply(integer_uniformizer, ideals[-1])
        ideals.append(
            _p_primary_saturation(
                candidate,
                field.prime,
                field.residue_degree * exponent,
            )
        )
    return tuple(ideals)


def _vp_integer(value: int, prime: int) -> int | None:
    if value == 0:
        return None
    remaining = abs(value)
    result = 0
    while remaining % prime == 0:
        remaining //= prime
        result += 1
    return result


def _vp_fraction(value: Fraction, prime: int) -> int | None:
    if value == 0:
        return None
    numerator = cast(int, _vp_integer(value.numerator, prime))
    denominator = cast(int, _vp_integer(value.denominator, prime))
    return numerator - denominator


class PAdicPresentationKind(StrEnum):
    RATIONAL = "rational"
    UNRAMIFIED = "unramified"
    EISENSTEIN = "eisenstein"


@dataclass(frozen=True, slots=True)
class PAdicFieldWitness(PAdicSchemaObject):
    """Portable proof method for one bounded local-field presentation."""

    schema_version: ClassVar[str] = "arbogast.padic.field-witness/v1"

    kind: PAdicPresentationKind

    def __init__(self, kind: PAdicPresentationKind | str) -> None:
        try:
            normalized = PAdicPresentationKind(kind)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"unsupported p-adic presentation kind: {kind!r}") from error
        object.__setattr__(self, "kind", normalized)

    def verify(self) -> bool:
        return PAdicFieldWitness(self.kind) == self

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "kind": self.kind.value,
            "type": "arbogast.padic.field_witness",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PAdicFieldWitness:
        raw = _raw_mapping(value, {"kind", "schema", "type"}, "field witness")
        if raw["schema"] != cls.schema_version or raw["type"] != "arbogast.padic.field_witness":
            raise PAdicVerificationError("field-witness schema or type was altered")
        result = cls(cast(str, raw["kind"]))
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("field witness is not strict canonical transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class PAdicField(PAdicSemanticObject):
    """A portable monogenic presentation of a finite extension of ``Q_p``."""

    schema_version: ClassVar[str] = "arbogast.padic.field/v1"

    prime: int
    defining_polynomial: tuple[int, ...]
    integral_basis: tuple[RationalVector, ...]
    uniformizer_coordinates: RationalVector
    residue_polynomial: tuple[int, ...]
    ramification_index: int
    residue_degree: int
    witness: PAdicFieldWitness

    def __init__(
        self,
        prime: int,
        defining_polynomial: Iterable[int] = (0, 1),
        *,
        witness: PAdicFieldWitness | PAdicPresentationKind | str | None = None,
        integral_basis: Iterable[Iterable[RationalLike]] | None = None,
        uniformizer: Iterable[RationalLike] | None = None,
        residue_polynomial: Iterable[int] | None = None,
        ramification_index: int | None = None,
        residue_degree: int | None = None,
    ) -> None:
        normalized_prime = _strict_int(prime, "prime", minimum=2)
        if (
            normalized_prime > MAX_PADIC_PRIME
            or normalized_prime.bit_length() > MAX_PRIME_BITS
            or not _is_prime(normalized_prime)
        ):
            raise ValidationError("prime must be a supported prime integer")
        raw_polynomial = tuple(islice(defining_polynomial, MAX_PORTABLE_LOCAL_DEGREE + 2))
        if len(raw_polynomial) > MAX_PORTABLE_LOCAL_DEGREE + 1:
            raise ValidationError("local-field degree exceeds the portable bound")
        polynomial = tuple(
            _strict_int(value, "defining-polynomial coefficient") for value in raw_polynomial
        )
        if len(polynomial) < 2 or polynomial[-1] != 1:
            raise ValidationError("defining polynomial must be nonconstant and monic")
        degree = len(polynomial) - 1
        if degree > MAX_PORTABLE_LOCAL_DEGREE:
            raise ValidationError("local-field degree exceeds the portable bound")

        if witness is None:
            if degree == 1 and polynomial == (0, 1):
                normalized_witness = PAdicFieldWitness(PAdicPresentationKind.RATIONAL)
            elif _irreducible_mod_prime(polynomial, normalized_prime):
                normalized_witness = PAdicFieldWitness(PAdicPresentationKind.UNRAMIFIED)
            else:
                normalized_witness = PAdicFieldWitness(PAdicPresentationKind.EISENSTEIN)
        elif isinstance(witness, PAdicFieldWitness):
            normalized_witness = witness
        else:
            normalized_witness = PAdicFieldWitness(witness)

        if integral_basis is None:
            basis = tuple(
                tuple(Fraction(1 if row == column else 0) for column in range(degree))
                for row in range(degree)
            )
        else:
            raw_basis = tuple(islice(integral_basis, degree + 1))
            basis = tuple(_rational_vector(row, degree, "integral-basis row") for row in raw_basis)
            if len(basis) != degree:
                raise ValidationError("integral basis must have one row per field degree")
        determinant = _determinant(basis)
        if determinant not in (Fraction(1), Fraction(-1)) or any(
            value.denominator != 1 for row in basis for value in row
        ):
            raise ValidationError(
                "portable local presentations require a unimodular integral power-basis change"
            )

        expected_residue_polynomial: tuple[int, ...]
        default_uniformizer_power: RationalVector
        if normalized_witness.kind is PAdicPresentationKind.RATIONAL:
            if polynomial != (0, 1):
                raise ValidationError("the rational local-field witness requires polynomial x")
            expected_ramification = expected_residue = 1
            expected_residue_polynomial = (0, 1)
            default_uniformizer_power = (Fraction(normalized_prime),)
        elif normalized_witness.kind is PAdicPresentationKind.UNRAMIFIED:
            if not _irreducible_mod_prime(polynomial, normalized_prime):
                raise ValidationError("unramified polynomial is not irreducible modulo p")
            expected_ramification = 1
            expected_residue = degree
            expected_residue_polynomial = tuple(value % normalized_prime for value in polynomial)
            default_uniformizer_power = (
                Fraction(normalized_prime),
                *(Fraction(0) for _ in range(degree - 1)),
            )
        else:
            if any(value % normalized_prime for value in polynomial[:-1]):
                raise ValidationError(
                    "every nonleading Eisenstein coefficient must be divisible by p"
                )
            constant_valuation = _vp_integer(polynomial[0], normalized_prime)
            if constant_valuation != 1:
                raise ValidationError("an Eisenstein constant term must have exact p-valuation one")
            expected_ramification = degree
            expected_residue = 1
            expected_residue_polynomial = (0, 1)
            default_uniformizer_power = (
                (Fraction(-polynomial[0]),)
                if degree == 1
                else (
                    Fraction(0),
                    Fraction(1),
                    *(Fraction(0) for _ in range(degree - 2)),
                )
            )

        normalized_ramification = (
            expected_ramification
            if ramification_index is None
            else _strict_int(ramification_index, "ramification_index", minimum=1)
        )
        normalized_residue = (
            expected_residue
            if residue_degree is None
            else _strict_int(residue_degree, "residue_degree", minimum=1)
        )
        if (
            normalized_ramification != expected_ramification
            or normalized_residue != expected_residue
            or normalized_ramification * normalized_residue != degree
        ):
            raise ValidationError("ramification and residue degrees disagree with the witness")

        raw_residue = (
            expected_residue_polynomial
            if residue_polynomial is None
            else tuple(
                _strict_int(value, "residue-polynomial coefficient") % normalized_prime
                for value in islice(residue_polynomial, degree + 2)
            )
        )
        if raw_residue != expected_residue_polynomial:
            raise ValidationError("residue polynomial disagrees with the portable presentation")

        power_to_integral = tuple(tuple(value for value in row) for row in zip(*basis, strict=True))
        default_uniformizer = _solve_square(power_to_integral, default_uniformizer_power)
        normalized_uniformizer = (
            default_uniformizer
            if uniformizer is None
            else _rational_vector(uniformizer, degree, "uniformizer")
        )

        object.__setattr__(self, "prime", normalized_prime)
        object.__setattr__(self, "defining_polynomial", polynomial)
        object.__setattr__(self, "integral_basis", basis)
        object.__setattr__(self, "uniformizer_coordinates", normalized_uniformizer)
        object.__setattr__(self, "residue_polynomial", raw_residue)
        object.__setattr__(self, "ramification_index", normalized_ramification)
        object.__setattr__(self, "residue_degree", normalized_residue)
        object.__setattr__(self, "witness", normalized_witness)
        self._validate_integral_structure()
        if self.uniformizer_element.valuation != Fraction(1, self.ramification_index):
            raise ValidationError("declared uniformizer does not have normalized valuation 1/e")

    @classmethod
    def rational(cls, prime: int) -> PAdicField:
        return cls(prime, (0, 1), witness=PAdicPresentationKind.RATIONAL)

    @classmethod
    def unramified(cls, prime: int, polynomial: Iterable[int]) -> PAdicField:
        return cls(prime, polynomial, witness=PAdicPresentationKind.UNRAMIFIED)

    @classmethod
    def eisenstein(cls, prime: int, polynomial: Iterable[int]) -> PAdicField:
        return cls(prime, polynomial, witness=PAdicPresentationKind.EISENSTEIN)

    @property
    def degree(self) -> int:
        return len(self.defining_polynomial) - 1

    @property
    def field_id(self) -> str:
        return self.content_id

    @property
    def supporting_certificates(self) -> tuple[VerificationCertificate, ...]:
        return ()

    @property
    def zero(self) -> PAdicElement:
        return PAdicElement(self, (0,) * self.degree)

    @property
    def one(self) -> PAdicElement:
        return self.from_power_basis_coordinates((1,))

    @property
    def generator(self) -> PAdicElement:
        if self.degree == 1:
            return self.from_power_basis_coordinates((-self.defining_polynomial[0],))
        return self.from_power_basis_coordinates((0, 1))

    @property
    def uniformizer_element(self) -> PAdicElement:
        return PAdicElement(self, self.uniformizer_coordinates)

    def from_coordinates(self, coordinates: Iterable[RationalLike]) -> PAdicElement:
        return PAdicElement(self, coordinates)

    def from_power_basis_coordinates(self, coordinates: Iterable[RationalLike]) -> PAdicElement:
        power = _rational_vector(coordinates, self.degree, "power-basis element", pad=True)
        transform = tuple(
            tuple(value for value in row) for row in zip(*self.integral_basis, strict=True)
        )
        integral = _solve_square(transform, power)
        return PAdicElement(self, integral)

    def power_coordinates(self, coordinates: Sequence[Fraction]) -> RationalVector:
        return tuple(
            sum(
                (coordinates[row] * self.integral_basis[row][column] for row in range(self.degree)),
                start=Fraction(0),
            )
            for column in range(self.degree)
        )

    def integral_coordinates(self, power_coordinates: Sequence[Fraction]) -> RationalVector:
        transform = tuple(
            tuple(value for value in row) for row in zip(*self.integral_basis, strict=True)
        )
        return _solve_square(transform, power_coordinates)

    def multiply_coordinates(
        self,
        left: Sequence[Fraction],
        right: Sequence[Fraction],
    ) -> RationalVector:
        power_product = _multiply_power_vectors(
            self.power_coordinates(left),
            self.power_coordinates(right),
            self.defining_polynomial,
        )
        return self.integral_coordinates(power_product)

    def multiplication_matrix(self, element: PAdicElement) -> tuple[RationalVector, ...]:
        if element.field != self:
            raise ValidationError("multiplication matrix requires an element of this field")
        columns = tuple(
            self.multiply_coordinates(
                element.coordinates,
                tuple(Fraction(1 if index == column else 0) for index in range(self.degree)),
            )
            for column in range(self.degree)
        )
        return tuple(
            tuple(columns[column][row] for column in range(self.degree))
            for row in range(self.degree)
        )

    @property
    def multiplication_tensor(self) -> tuple[tuple[tuple[int, ...], ...], ...]:
        basis = tuple(
            tuple(Fraction(1 if index == column else 0) for index in range(self.degree))
            for column in range(self.degree)
        )
        return tuple(
            tuple(
                tuple(int(value) for value in self.multiply_coordinates(left, right))
                for right in basis
            )
            for left in basis
        )

    def _validate_integral_structure(self) -> None:
        for left in range(self.degree):
            for right in range(self.degree):
                product = self.multiply_coordinates(
                    tuple(Fraction(1 if index == left else 0) for index in range(self.degree)),
                    tuple(Fraction(1 if index == right else 0) for index in range(self.degree)),
                )
                if any(value.denominator != 1 for value in product):
                    raise ValidationError("integral basis is not closed under multiplication")
        if any(value.denominator != 1 for value in self.uniformizer_coordinates):
            raise ValidationError("portable uniformizer coordinates must be integral")

    def verify(self) -> bool:
        return (
            PAdicField(
                self.prime,
                self.defining_polynomial,
                witness=self.witness,
                integral_basis=self.integral_basis,
                uniformizer=self.uniformizer_coordinates,
                residue_polynomial=self.residue_polynomial,
                ramification_index=self.ramification_index,
                residue_degree=self.residue_degree,
            )
            == self
        )

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "defining_polynomial": list(self.defining_polynomial),
                "integral_basis": [_vector_payload(row) for row in self.integral_basis],
                "prime": self.prime,
                "ramification_index": self.ramification_index,
                "residue_degree": self.residue_degree,
                "residue_polynomial": list(self.residue_polynomial),
                "type": "arbogast.padic.field",
                "uniformizer": _vector_payload(self.uniformizer_coordinates),
                "witness": self.witness.to_schema_document(),
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PAdicField:
        raw = _raw_mapping(
            value,
            {
                "defining_polynomial",
                "integral_basis",
                "prime",
                "ramification_index",
                "residue_degree",
                "residue_polynomial",
                "schema",
                "type",
                "uniformizer",
                "witness",
            },
            "p-adic field",
        )
        if raw["schema"] != cls.schema_version or raw["type"] != "arbogast.padic.field":
            raise PAdicVerificationError("p-adic field schema or type was altered")
        polynomial = tuple(
            _strict_int(item, "defining-polynomial coefficient")
            for item in _raw_list(raw["defining_polynomial"], "defining polynomial")
        )
        degree = len(polynomial) - 1
        basis = tuple(
            _decode_vector(item, degree, f"integral basis[{index}]")
            for index, item in enumerate(_raw_list(raw["integral_basis"], "integral basis"))
        )
        residue = tuple(
            _strict_int(item, "residue-polynomial coefficient")
            for item in _raw_list(raw["residue_polynomial"], "residue polynomial")
        )
        witness_raw = raw["witness"]
        if type(witness_raw) is not dict:
            raise PAdicVerificationError("p-adic field witness must be a strict object")
        result = cls(
            _strict_int(raw["prime"], "prime", minimum=2),
            polynomial,
            witness=PAdicFieldWitness.from_dict(cast(dict[str, object], witness_raw)),
            integral_basis=basis,
            uniformizer=_decode_vector(raw["uniformizer"], degree, "uniformizer"),
            residue_polynomial=residue,
            ramification_index=_strict_int(
                raw["ramification_index"], "ramification_index", minimum=1
            ),
            residue_degree=_strict_int(raw["residue_degree"], "residue_degree", minimum=1),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("p-adic field is not strict canonical transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class PAdicElement(PAdicSchemaObject):
    """An exact rational-coordinate point in a pinned local presentation."""

    schema_version: ClassVar[str] = "arbogast.padic.element/v1"

    field: PAdicField
    coordinates: RationalVector

    def __init__(self, field: PAdicField, coordinates: Iterable[RationalLike]) -> None:
        if not isinstance(field, PAdicField):
            raise TypeError("field must be a PAdicField")
        normalized = _rational_vector(coordinates, field.degree, "p-adic element", pad=True)
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "coordinates", normalized)

    @property
    def element_id(self) -> str:
        return self.content_id

    @property
    def power_coordinates(self) -> RationalVector:
        return self.field.power_coordinates(self.coordinates)

    @property
    def is_zero(self) -> bool:
        return not any(self.coordinates)

    @property
    def is_integral(self) -> bool:
        return all(
            cast(int, _vp_fraction(value, self.field.prime)) >= 0
            for value in self.coordinates
            if value
        )

    @property
    def valuation(self) -> Fraction | None:
        if self.is_zero:
            return None
        determinant = _determinant(self.field.multiplication_matrix(self))
        norm_valuation = _vp_fraction(determinant, self.field.prime)
        if norm_valuation is None:
            raise ValidationError("a nonzero field element has zero multiplication determinant")
        return Fraction(norm_valuation, self.field.degree)

    def inverse(self) -> PAdicElement:
        if self.is_zero:
            raise ZeroDivisionError("zero has no multiplicative inverse")
        target = self.field.one.coordinates
        inverse_coordinates = _solve_square(self.field.multiplication_matrix(self), target)
        result = PAdicElement(self.field, inverse_coordinates)
        if self * result != self.field.one or result * self != self.field.one:
            raise ValidationError("exact inverse replay failed")
        return result

    def _coerce(self, other: PAdicElement | RationalLike) -> PAdicElement:
        if isinstance(other, PAdicElement):
            if other.field != self.field:
                raise ValidationError("p-adic element fields do not match")
            return other
        return self.field.from_power_basis_coordinates((_rational(other, "scalar"),))

    def __add__(self, other: PAdicElement | RationalLike) -> PAdicElement:
        right = self._coerce(other)
        return PAdicElement(
            self.field,
            tuple(
                left + value
                for left, value in zip(self.coordinates, right.coordinates, strict=True)
            ),
        )

    def __sub__(self, other: PAdicElement | RationalLike) -> PAdicElement:
        return self + (-self._coerce(other))

    def __neg__(self) -> PAdicElement:
        return PAdicElement(self.field, tuple(-value for value in self.coordinates))

    def __mul__(self, other: PAdicElement | RationalLike) -> PAdicElement:
        right = self._coerce(other)
        return PAdicElement(
            self.field,
            self.field.multiply_coordinates(self.coordinates, right.coordinates),
        )

    def __truediv__(self, other: PAdicElement | RationalLike) -> PAdicElement:
        return self * self._coerce(other).inverse()

    def verify(self) -> bool:
        return PAdicElement(self.field, self.coordinates) == self and self.field.verify()

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "coordinates": _vector_payload(self.coordinates),
                "field_id": self.field.field_id,
                "type": "arbogast.padic.element",
            },
        )

    @classmethod
    def from_dict(
        cls,
        field: PAdicField,
        value: Mapping[str, object],
    ) -> PAdicElement:
        raw = _raw_mapping(
            value,
            {"coordinates", "field_id", "schema", "type"},
            "p-adic element",
        )
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.element"
            or raw["field_id"] != field.field_id
        ):
            raise PAdicVerificationError("p-adic element field, schema, or type was altered")
        result = cls(field, _decode_vector(raw["coordinates"], field.degree, "coordinates"))
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("p-adic element is not strict canonical transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class PAdicPrecisionRing(PAdicSemanticObject):
    """The exact finite chain ring ``O_K / pi^N``."""

    schema_version: ClassVar[str] = "arbogast.padic.precision-ring/v1"

    field: PAdicField
    precision: int
    modulus_hnf: IntegerMatrix
    _ideal_chain: tuple[IntegerMatrix, ...]

    def __init__(self, field: PAdicField, precision: int) -> None:
        if not isinstance(field, PAdicField):
            raise TypeError("field must be a PAdicField")
        normalized_precision = _strict_int(precision, "precision", minimum=1)
        if normalized_precision > MAX_PORTABLE_PRECISION:
            raise ValidationError("precision exceeds the portable bound")
        if field.residue_degree * normalized_precision * field.prime.bit_length() > min(
            MAX_PADIC_WORK_BITS, MAX_PRECISION_WORK
        ):
            raise ValidationError("precision-ring presentation exceeds the portable work bound")
        ideal_chain = _uniformizer_ideal_chain(field, normalized_precision)
        modulus_hnf = ideal_chain[-1]
        determinant = 1
        for index in range(field.degree):
            determinant *= modulus_hnf[index][index]
        expected = field.prime ** (field.residue_degree * normalized_precision)
        if determinant != expected:
            raise ValidationError("precision-ring lattice has the wrong cardinality")
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "precision", normalized_precision)
        object.__setattr__(self, "modulus_hnf", modulus_hnf)
        object.__setattr__(self, "_ideal_chain", ideal_chain)
        self._validate_ideal_closure()

    @property
    def ring_id(self) -> str:
        return self.content_id

    @property
    def supporting_certificates(self) -> tuple[VerificationCertificate, ...]:
        return (self.field.certificate,)

    @property
    def cardinality(self) -> int:
        return int(pow(self.field.prime, self.field.residue_degree * self.precision))

    @property
    def zero(self) -> PAdicBall:
        return PAdicBall(self, (0,) * self.field.degree)

    @property
    def one(self) -> PAdicBall:
        return self.from_element(self.field.one)

    @property
    def uniformizer(self) -> PAdicBall:
        return self.from_element(self.field.uniformizer_element)

    def from_coordinates(self, coordinates: Iterable[int]) -> PAdicBall:
        return PAdicBall(self, coordinates)

    def from_element(self, element: PAdicElement) -> PAdicBall:
        if not isinstance(element, PAdicElement) or element.field != self.field:
            raise ValidationError("precision reduction requires an element of the pinned field")
        if not element.is_integral:
            raise ValidationError(
                "nonintegral p-adic elements do not define integral precision balls"
            )
        denominator = 1
        for coordinate in element.coordinates:
            denominator = (
                denominator * coordinate.denominator // gcd(denominator, coordinate.denominator)
            )
        if denominator % self.field.prime == 0:
            raise ValidationError("integral precision reduction has a non-unit denominator")
        numerator = tuple(int(coordinate * denominator) for coordinate in element.coordinates)
        inverse = pow(denominator, -1, self.field.prime**self.precision)
        return PAdicBall(self, tuple(value * inverse for value in numerator))

    def reduce(self, coordinates: Sequence[int]) -> tuple[int, ...]:
        return _reduce_hnf(coordinates, self.modulus_hnf)

    def contains_modulus(self, coordinates: Sequence[int]) -> bool:
        return _in_lattice(self.modulus_hnf, coordinates)

    def ideal_hnf(self, exponent: int) -> IntegerMatrix:
        normalized = _strict_int(exponent, "ideal exponent", minimum=0)
        if normalized > self.precision:
            raise ValidationError("ideal exponent exceeds ring precision")
        return self._ideal_chain[normalized]

    def valuation_order(self, coordinates: Sequence[int]) -> int:
        reduced = self.reduce(coordinates)
        if not any(reduced):
            return self.precision
        result = 0
        for exponent in range(1, self.precision):
            if not _in_lattice(self.ideal_hnf(exponent), reduced):
                break
            result = exponent
        return result

    def _validate_ideal_closure(self) -> None:
        generators = tuple(
            tuple(self.modulus_hnf[row][column] for row in range(self.field.degree))
            for column in range(self.field.degree)
        )
        basis = tuple(
            tuple(Fraction(1 if index == column else 0) for index in range(self.field.degree))
            for column in range(self.field.degree)
        )
        for generator in generators:
            for basis_element in basis:
                product = self.field.multiply_coordinates(
                    tuple(Fraction(value) for value in generator), basis_element
                )
                if any(value.denominator != 1 for value in product) or not _in_lattice(
                    self.modulus_hnf, tuple(value.numerator for value in product)
                ):
                    raise ValidationError("precision lattice is not an ideal of the integral order")

    def verify(self) -> bool:
        return PAdicPrecisionRing(self.field, self.precision) == self

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "cardinality": self.cardinality,
            "field_id": self.field.field_id,
            "modulus_hnf": [list(row) for row in self.modulus_hnf],
            "precision": self.precision,
            "type": "arbogast.padic.precision_ring",
            "uniformizer_power_convention": True,
        }

    @classmethod
    def from_dict(
        cls,
        field: PAdicField,
        value: Mapping[str, object],
    ) -> PAdicPrecisionRing:
        raw = _raw_mapping(
            value,
            {
                "cardinality",
                "field_id",
                "modulus_hnf",
                "precision",
                "schema",
                "type",
                "uniformizer_power_convention",
            },
            "p-adic precision ring",
        )
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.precision_ring"
            or raw["field_id"] != field.field_id
            or raw["uniformizer_power_convention"] is not True
        ):
            raise PAdicVerificationError("precision-ring field, schema, or convention was altered")
        result = cls(field, _strict_int(raw["precision"], "precision", minimum=1))
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("precision ring is not strict canonical transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class PAdicBall(PAdicSchemaObject):
    """An exact integral coset modulo ``pi^N`` in one precision ring."""

    schema_version: ClassVar[str] = "arbogast.padic.ball/v1"

    ring: PAdicPrecisionRing
    coordinates: tuple[int, ...]

    def __init__(self, ring: PAdicPrecisionRing, coordinates: Iterable[int]) -> None:
        if not isinstance(ring, PAdicPrecisionRing):
            raise TypeError("ring must be a PAdicPrecisionRing")
        normalized = tuple(
            _strict_int(value, "ball coordinate")
            for value in islice(coordinates, ring.field.degree + 1)
        )
        if len(normalized) != ring.field.degree:
            raise ValidationError("ball coordinates have the wrong local-field degree")
        reduced = ring.reduce(normalized)
        object.__setattr__(self, "ring", ring)
        object.__setattr__(self, "coordinates", reduced)

    @property
    def ball_id(self) -> str:
        return self.content_id

    @property
    def is_zero(self) -> bool:
        return not any(self.coordinates)

    @property
    def valuation_interval(self) -> tuple[Fraction, Fraction | None]:
        order = self.ring.valuation_order(self.coordinates)
        lower = Fraction(order, self.ring.field.ramification_index)
        return (lower, None if self.is_zero else lower)

    @property
    def is_unit(self) -> bool:
        return not self.is_zero and self.ring.valuation_order(self.coordinates) == 0

    def inverse(self) -> PAdicBall:
        if not self.is_unit:
            raise ZeroDivisionError("only units are invertible in a p-adic precision ring")
        field_lift = PAdicElement(
            self.ring.field, tuple(Fraction(value) for value in self.coordinates)
        )
        result = self.ring.from_element(field_lift.inverse())
        if self * result != self.ring.one or result * self != self.ring.one:
            raise ValidationError("precision-ring inverse replay failed")
        return result

    def _coerce(self, other: PAdicBall | int) -> PAdicBall:
        if isinstance(other, PAdicBall):
            if other.ring != self.ring:
                raise ValidationError("p-adic balls belong to different precision rings")
            return other
        if isinstance(other, bool) or not isinstance(other, int):
            raise TypeError("precision-ring scalar must be an integer")
        return self.ring.from_element(self.ring.field.from_power_basis_coordinates((other,)))

    def __add__(self, other: PAdicBall | int) -> PAdicBall:
        right = self._coerce(other)
        return PAdicBall(
            self.ring,
            tuple(
                left + value
                for left, value in zip(self.coordinates, right.coordinates, strict=True)
            ),
        )

    def __sub__(self, other: PAdicBall | int) -> PAdicBall:
        return self + (-self._coerce(other))

    def __neg__(self) -> PAdicBall:
        return PAdicBall(self.ring, tuple(-value for value in self.coordinates))

    def __mul__(self, other: PAdicBall | int) -> PAdicBall:
        right = self._coerce(other)
        product = self.ring.field.multiply_coordinates(
            tuple(Fraction(value) for value in self.coordinates),
            tuple(Fraction(value) for value in right.coordinates),
        )
        if any(value.denominator != 1 for value in product):
            raise ValidationError("integral precision multiplication produced a denominator")
        return PAdicBall(self.ring, tuple(value.numerator for value in product))

    def __truediv__(self, other: PAdicBall | int) -> PAdicBall:
        return self * self._coerce(other).inverse()

    def __pow__(self, exponent: int) -> PAdicBall:
        normalized = _strict_int(exponent, "exponent", minimum=0)
        result = self.ring.one
        factor = self
        remaining = normalized
        while remaining:
            if remaining & 1:
                result = result * factor
            factor = factor * factor
            remaining >>= 1
        return result

    def verify(self) -> bool:
        return PAdicBall(self.ring, self.coordinates) == self and self.ring.verify()

    def to_canonical_data(self) -> CanonicalJSON:
        lower, upper = self.valuation_interval
        return cast(
            CanonicalJSON,
            {
                "coordinates": list(self.coordinates),
                "ring_id": self.ring.ring_id,
                "type": "arbogast.padic.ball",
                "valuation_lower": _rational_payload(lower),
                "valuation_upper": None if upper is None else _rational_payload(upper),
            },
        )

    @classmethod
    def from_dict(
        cls,
        ring: PAdicPrecisionRing,
        value: Mapping[str, object],
    ) -> PAdicBall:
        raw = _raw_mapping(
            value,
            {
                "coordinates",
                "ring_id",
                "schema",
                "type",
                "valuation_lower",
                "valuation_upper",
            },
            "p-adic ball",
        )
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.ball"
            or raw["ring_id"] != ring.ring_id
        ):
            raise PAdicVerificationError("p-adic ball ring, schema, or type was altered")
        result = cls(
            ring,
            tuple(
                _strict_int(item, "ball coordinate")
                for item in _raw_list(raw["coordinates"], "ball coordinates")
            ),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("p-adic ball is not strict canonical transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class LocalFieldEmbedding(PAdicSemanticObject):
    """An exact generator-image embedding between pinned local presentations."""

    schema_version: ClassVar[str] = "arbogast.padic.local-field-embedding/v1"

    domain: PAdicField
    codomain: PAdicField
    generator_image: PAdicElement

    def __init__(
        self,
        domain: PAdicField,
        codomain: PAdicField,
        generator_image: PAdicElement,
    ) -> None:
        if not isinstance(domain, PAdicField) or not isinstance(codomain, PAdicField):
            raise TypeError("local embedding endpoints must be PAdicField objects")
        if domain.prime != codomain.prime:
            raise ValidationError("local embeddings must preserve the residue characteristic")
        if not isinstance(generator_image, PAdicElement) or generator_image.field != codomain:
            raise ValidationError("generator image must belong to the embedding codomain")
        if codomain.degree % domain.degree:
            raise ValidationError("local embedding degree does not divide the codomain degree")
        value = codomain.zero
        for coefficient in reversed(domain.defining_polynomial):
            value = value * generator_image + coefficient
        if not value.is_zero:
            raise ValidationError("local generator image does not satisfy the domain polynomial")
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "codomain", codomain)
        object.__setattr__(self, "generator_image", generator_image)
        uniformizer_image = self.apply(domain.uniformizer_element)
        if uniformizer_image.valuation != Fraction(1, domain.ramification_index):
            raise ValidationError("local embedding does not preserve normalized valuation")

    @property
    def embedding_id(self) -> str:
        return self.content_id

    @property
    def supporting_certificates(self) -> tuple[VerificationCertificate, ...]:
        domain_certificate = self.domain.certificate
        codomain_certificate = self.codomain.certificate
        certificates = {
            domain_certificate.certificate_id: domain_certificate,
            codomain_certificate.certificate_id: codomain_certificate,
        }
        return tuple(certificates[key] for key in sorted(certificates))

    def apply(self, element: PAdicElement) -> PAdicElement:
        if not isinstance(element, PAdicElement) or element.field != self.domain:
            raise ValidationError("local embedding source element belongs to a different field")
        result = self.codomain.zero
        for coordinate in reversed(element.power_coordinates):
            result = result * self.generator_image + coordinate
        return result

    __call__ = apply

    def apply_ball(self, value: PAdicBall) -> PAdicBall:
        """Apply an equal-field embedding to one finite-precision coset."""

        if not isinstance(value, PAdicBall) or value.ring.field != self.domain:
            raise ValidationError("local embedding ball belongs to a different source field")
        if self.domain != self.codomain:
            raise ValidationError(
                "finite-precision embedding transport is initially restricted to automorphisms"
            )
        exact_lift = PAdicElement(
            self.domain,
            tuple(Fraction(coordinate) for coordinate in value.coordinates),
        )
        return value.ring.from_element(self.apply(exact_lift))

    def verify(self) -> bool:
        return LocalFieldEmbedding(self.domain, self.codomain, self.generator_image) == self

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "codomain_id": self.codomain.field_id,
            "domain_id": self.domain.field_id,
            "generator_image": self.generator_image.to_schema_document(),
            "type": "arbogast.padic.local_field_embedding",
        }

    @classmethod
    def from_dict(
        cls,
        domain: PAdicField,
        codomain: PAdicField,
        value: Mapping[str, object],
    ) -> LocalFieldEmbedding:
        raw = _raw_mapping(
            value,
            {"codomain_id", "domain_id", "generator_image", "schema", "type"},
            "local-field embedding",
        )
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.local_field_embedding"
            or raw["domain_id"] != domain.field_id
            or raw["codomain_id"] != codomain.field_id
            or type(raw["generator_image"]) is not dict
        ):
            raise PAdicVerificationError("local-field embedding endpoints or type were altered")
        result = cls(
            domain,
            codomain,
            PAdicElement.from_dict(
                codomain,
                cast(dict[str, object], raw["generator_image"]),
            ),
        )
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("local-field embedding is not strict transport")
        return result


@dataclass(frozen=True, slots=True, init=False)
class PAdicAutomorphism(PAdicSemanticObject):
    """An exhaustively replayed automorphism of one finite precision ring."""

    schema_version: ClassVar[str] = "arbogast.padic.automorphism/v1"

    ring: PAdicPrecisionRing
    basis_images: tuple[PAdicBall, ...]
    inverse_images: tuple[PAdicBall, ...]

    def __init__(
        self,
        ring: PAdicPrecisionRing,
        basis_images: Iterable[PAdicBall],
        inverse_images: Iterable[PAdicBall],
    ) -> None:
        if not isinstance(ring, PAdicPrecisionRing):
            raise TypeError("automorphism ring must be a PAdicPrecisionRing")
        images = tuple(islice(basis_images, ring.field.degree + 1))
        inverses = tuple(islice(inverse_images, ring.field.degree + 1))
        if len(images) != ring.field.degree or len(inverses) != ring.field.degree:
            raise ValidationError("automorphism needs one image per integral-basis element")
        if any(
            not isinstance(value, PAdicBall) or value.ring != ring for value in (*images, *inverses)
        ):
            raise ValidationError("automorphism images must belong to the pinned precision ring")
        object.__setattr__(self, "ring", ring)
        object.__setattr__(self, "basis_images", images)
        object.__setattr__(self, "inverse_images", inverses)
        self._validate_ring_map(images)
        self._validate_ring_map(inverses)
        for index in range(ring.field.degree):
            basis = PAdicBall(
                ring,
                tuple(1 if coordinate == index else 0 for coordinate in range(ring.field.degree)),
            )
            if self._apply_images(self._apply_images(basis, images), inverses) != basis:
                raise ValidationError("automorphism inverse fails on an integral-basis element")
            if self._apply_images(self._apply_images(basis, inverses), images) != basis:
                raise ValidationError("automorphism inverse fails in the other composition order")

    @classmethod
    def identity(cls, ring: PAdicPrecisionRing) -> PAdicAutomorphism:
        images = tuple(
            PAdicBall(
                ring,
                tuple(1 if coordinate == index else 0 for coordinate in range(ring.field.degree)),
            )
            for index in range(ring.field.degree)
        )
        return cls(ring, images, images)

    @property
    def automorphism_id(self) -> str:
        return self.content_id

    @property
    def supporting_certificates(self) -> tuple[VerificationCertificate, ...]:
        return (self.ring.certificate,)

    def _apply_images(
        self,
        value: PAdicBall,
        images: Sequence[PAdicBall],
    ) -> PAdicBall:
        result = self.ring.zero
        for coordinate, image in zip(value.coordinates, images, strict=True):
            result += image * coordinate
        return result

    def apply(self, value: PAdicBall) -> PAdicBall:
        if not isinstance(value, PAdicBall) or value.ring != self.ring:
            raise ValidationError("automorphism value belongs to a different precision ring")
        return self._apply_images(value, self.basis_images)

    apply_ball = apply

    def inverse_apply(self, value: PAdicBall) -> PAdicBall:
        if not isinstance(value, PAdicBall) or value.ring != self.ring:
            raise ValidationError("automorphism value belongs to a different precision ring")
        return self._apply_images(value, self.inverse_images)

    def _validate_ring_map(self, images: Sequence[PAdicBall]) -> None:
        for column in range(self.ring.field.degree):
            relation = self.ring.zero
            for row, image in enumerate(images):
                relation += image * self.ring.modulus_hnf[row][column]
            if not relation.is_zero:
                raise ValidationError(
                    "precision-ring automorphism does not respect the modulus lattice"
                )
        if self._apply_images(self.ring.one, images) != self.ring.one:
            raise ValidationError("precision-ring automorphism does not preserve one")
        basis = tuple(
            PAdicBall(
                self.ring,
                tuple(
                    1 if coordinate == index else 0 for coordinate in range(self.ring.field.degree)
                ),
            )
            for index in range(self.ring.field.degree)
        )
        for left in basis:
            for right in basis:
                if self._apply_images(left * right, images) != (
                    self._apply_images(left, images) * self._apply_images(right, images)
                ):
                    raise ValidationError("precision-ring automorphism is not multiplicative")

    def verify(self) -> bool:
        return PAdicAutomorphism(self.ring, self.basis_images, self.inverse_images) == self

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "basis_images": [value.to_schema_document() for value in self.basis_images],
            "inverse_images": [value.to_schema_document() for value in self.inverse_images],
            "ring_id": self.ring.ring_id,
            "type": "arbogast.padic.automorphism",
        }

    @classmethod
    def from_dict(
        cls,
        ring: PAdicPrecisionRing,
        value: Mapping[str, object],
    ) -> PAdicAutomorphism:
        raw = _raw_mapping(
            value,
            {"basis_images", "inverse_images", "ring_id", "schema", "type"},
            "p-adic automorphism",
        )
        if (
            raw["schema"] != cls.schema_version
            or raw["type"] != "arbogast.padic.automorphism"
            or raw["ring_id"] != ring.ring_id
        ):
            raise PAdicVerificationError("p-adic automorphism ring, schema, or type was altered")

        def images(name: str) -> tuple[PAdicBall, ...]:
            return tuple(
                PAdicBall.from_dict(
                    ring,
                    cast(dict[str, object], item),
                )
                for item in _raw_list(raw[name], f"automorphism {name}")
                if type(item) is dict
            )

        basis = images("basis_images")
        inverse = images("inverse_images")
        if len(basis) != len(_raw_list(raw["basis_images"], "basis images")) or len(inverse) != len(
            _raw_list(raw["inverse_images"], "inverse images")
        ):
            raise PAdicVerificationError("automorphism image is not a strict object")
        result = cls(ring, basis, inverse)
        if not strict_canonical_equal(raw, result.to_schema_document()):
            raise PAdicVerificationError("p-adic automorphism is not strict canonical transport")
        return result


def _dependency_receipt(
    certificate: VerificationCertificate,
    expected_kind: str,
) -> object:
    from .certificate import PAdicReceipt

    witness = certificate.witness.to_dict()
    if set(witness) != {"padic_receipt"} or type(witness["padic_receipt"]) is not dict:
        raise PAdicVerificationError("p-adic substrate dependency is not a p-adic certificate")
    receipt = PAdicReceipt.from_dict(cast(dict[str, object], witness["padic_receipt"]))
    if receipt.kind != expected_kind or receipt.closure != "certified":
        raise PAdicVerificationError(
            f"p-adic substrate dependency is not a certified {expected_kind} receipt"
        )
    return receipt


def _dependency_document(
    certificate: VerificationCertificate,
    expected_kind: str,
) -> dict[str, object]:
    from .certificate import PAdicReceipt

    receipt = cast(PAdicReceipt, _dependency_receipt(certificate, expected_kind))
    payload = receipt.payload.to_dict()
    if set(payload) != {"result"} or type(payload["result"]) is not dict:
        raise PAdicVerificationError("p-adic substrate dependency omits its result")
    return cast(dict[str, object], payload["result"])


def _fields_from_evidence(
    evidence: Sequence[VerificationCertificate],
) -> tuple[tuple[PAdicField, VerificationCertificate], ...]:
    fields: list[tuple[PAdicField, VerificationCertificate]] = []
    for certificate in evidence:
        try:
            document = _dependency_document(certificate, "field")
        except PAdicVerificationError:
            continue
        fields.append((PAdicField.from_dict(document), certificate))
    return tuple(fields)


def _ring_from_evidence(
    evidence: Sequence[VerificationCertificate],
    ring_id: object,
) -> tuple[PAdicPrecisionRing, tuple[str, ...]]:
    from .certificate import PAdicReceipt

    candidates: list[tuple[PAdicPrecisionRing, str]] = []
    for certificate in evidence:
        try:
            receipt = cast(
                PAdicReceipt,
                _dependency_receipt(certificate, "precision-ring"),
            )
        except PAdicVerificationError:
            continue
        payload = receipt.payload.to_dict()
        if set(payload) != {"result"} or type(payload["result"]) is not dict:
            raise PAdicVerificationError("precision-ring dependency omits its result")
        document = cast(dict[str, object], payload["result"])
        fields = _fields_from_evidence(receipt.evidence)
        field_id = document.get("field_id")
        for field, field_certificate in fields:
            if field.field_id == field_id:
                ring = PAdicPrecisionRing.from_dict(field, document)
                if ring.ring_id == ring_id:
                    if field_certificate.certificate_id not in {
                        item.certificate_id for item in receipt.evidence
                    }:
                        raise PAdicVerificationError("ring field evidence was not nested")
                    candidates.append((ring, certificate.certificate_id))
    if len(candidates) != 1:
        raise PAdicVerificationError("p-adic ring dependency is missing or ambiguous")
    ring, ring_certificate_id = candidates[0]
    return ring, (ring_certificate_id,)


def _register_payload_verifiers() -> None:
    from .certificate import padic_payload_verifier, replay_schema_payload

    @padic_payload_verifier("field")
    def verify_field(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        return replay_schema_payload(
            payload,
            evidence,
            decoder=PAdicField.from_dict,
            checks=(
                "portable local-field presentation replayed",
                "ramification, residue degree, integral basis, and uniformizer checked",
            ),
        )

    @padic_payload_verifier("precision-ring")
    def verify_precision_ring(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        raw = payload.get("result")
        if type(raw) is not dict:
            raise PAdicVerificationError("precision-ring payload omits its result")
        fields = _fields_from_evidence(evidence)
        field_id = cast(dict[str, object], raw).get("field_id")
        matches = tuple(
            (field, certificate) for field, certificate in fields if field.field_id == field_id
        )
        if len(matches) != 1:
            raise PAdicVerificationError("precision-ring field dependency is missing or ambiguous")
        field, certificate = matches[0]
        return replay_schema_payload(
            payload,
            evidence,
            decoder=lambda value: PAdicPrecisionRing.from_dict(field, value),
            checks=(
                "uniformizer-power lattice reconstructed with p-primary saturation",
                "canonical HNF, ideal closure, and cardinality checked",
            ),
            evidence_ids=(certificate.certificate_id,),
        )

    @padic_payload_verifier("local-field-embedding")
    def verify_embedding(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        raw = payload.get("result")
        if type(raw) is not dict:
            raise PAdicVerificationError("embedding payload omits its result")
        result = cast(dict[str, object], raw)
        fields = _fields_from_evidence(evidence)
        domain_matches = tuple(
            (field, certificate)
            for field, certificate in fields
            if field.field_id == result.get("domain_id")
        )
        codomain_matches = tuple(
            (field, certificate)
            for field, certificate in fields
            if field.field_id == result.get("codomain_id")
        )
        if len(domain_matches) != 1 or len(codomain_matches) != 1:
            raise PAdicVerificationError("embedding field dependencies are missing or ambiguous")
        domain, domain_certificate = domain_matches[0]
        codomain, codomain_certificate = codomain_matches[0]
        evidence_ids = tuple(
            sorted(
                {
                    domain_certificate.certificate_id,
                    codomain_certificate.certificate_id,
                }
            )
        )
        return replay_schema_payload(
            payload,
            evidence,
            decoder=lambda value: LocalFieldEmbedding.from_dict(domain, codomain, value),
            checks=(
                "generator image satisfies the exact domain relation",
                "residue characteristic and normalized valuation preserved",
            ),
            evidence_ids=evidence_ids,
        )

    @padic_payload_verifier("automorphism")
    def verify_automorphism(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        raw = payload.get("result")
        if type(raw) is not dict:
            raise PAdicVerificationError("automorphism payload omits its result")
        ring, evidence_ids = _ring_from_evidence(
            evidence,
            cast(dict[str, object], raw).get("ring_id"),
        )
        return replay_schema_payload(
            payload,
            evidence,
            decoder=lambda value: PAdicAutomorphism.from_dict(ring, value),
            checks=(
                "finite-ring unit and multiplication laws replayed",
                "automorphism inverse checked in both composition orders",
            ),
            evidence_ids=evidence_ids,
        )


_register_payload_verifiers()


__all__ = [
    "LocalFieldEmbedding",
    "PAdicAutomorphism",
    "PAdicBall",
    "PAdicElement",
    "PAdicField",
    "PAdicFieldWitness",
    "PAdicPrecisionRing",
    "PAdicPresentationKind",
]
