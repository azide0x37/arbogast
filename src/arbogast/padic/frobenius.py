"""Finite-precision Frobenius operators and certified Newton slopes.

The objects in this module describe exact computations in a pinned finite
precision ring.  A :class:`FrobeniusOperator` is therefore a coset-valued
semilinear operator, not a selected infinite p-adic operator.  Whenever the
available coefficient valuations do not determine a unique Newton polygon,
the public operation returns the shared :class:`~arbogast.padic.results.Partial`
outcome instead of guessing slopes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from itertools import islice, pairwise
from typing import TYPE_CHECKING, Any, TypeVar, cast

from arbogast.core import CanonicalJSON

from ._schema import (
    MAX_DIMENSION,
    MAX_EXACT_REPLAY_WORK,
    MAX_PRECISION_WORK,
    PAdicSchemaObject,
    strict_canonical_equal,
    strict_canonical_mapping,
    strict_int,
)
from .errors import PAdicResourceError, PAdicValidationError, PAdicVerificationError

if TYPE_CHECKING:
    from arbogast.cert import VerificationCertificate

    from .certificate import PAdicPayloadReplay
    from .fields import (
        LocalFieldEmbedding,
        PAdicAutomorphism,
        PAdicBall,
        PAdicPrecisionRing,
    )
    from .matrices import PAdicBase, PAdicMatrix, PAdicScalar, ScalarLike
    from .modules import PAdicModule, PAdicSubmodule
    from .results import PAdicResult


_T = TypeVar("_T")


def _bounded_tuple(values: Sequence[_T], maximum: int, name: str) -> tuple[_T, ...]:
    normalized = tuple(islice(values, maximum + 1))
    if len(normalized) > maximum:
        raise PAdicResourceError(f"{name} exceeds the portable aggregate bound")
    return normalized


def _fraction(value: object, name: str) -> Fraction:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an exact rational")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    raise TypeError(f"{name} must be an exact rational")


def _rational_payload(value: Fraction) -> list[CanonicalJSON]:
    return [value.numerator, value.denominator]


def _object_id(value: object, name: str) -> str:
    identifier = getattr(value, "content_id", None)
    if not isinstance(identifier, str):
        identifier = getattr(value, name, None)
    if not isinstance(identifier, str) or not identifier:
        raise PAdicValidationError(f"{type(value).__name__} has no canonical {name}")
    return identifier


def _matrix_base(matrix: object) -> PAdicBase:
    from .fields import PAdicField, PAdicPrecisionRing

    base = getattr(matrix, "base", None)
    if not isinstance(base, PAdicField | PAdicPrecisionRing):
        raise PAdicValidationError("p-adic matrix omits its coefficient base")
    return base


def _matrix_shape(matrix: object) -> tuple[int, int]:
    shape = getattr(matrix, "shape", None)
    if (
        not isinstance(shape, tuple)
        or len(shape) != 2
        or any(type(value) is not int for value in shape)
    ):
        raise PAdicValidationError("p-adic matrix has no exact shape")
    return cast(tuple[int, int], shape)


def _matrix_entries(matrix: object) -> tuple[tuple[PAdicScalar, ...], ...]:
    entries = getattr(matrix, "entries", None)
    if not isinstance(entries, tuple) or any(not isinstance(row, tuple) for row in entries):
        raise PAdicValidationError("p-adic matrix entries are not canonical tuples")
    return cast("tuple[tuple[PAdicScalar, ...], ...]", entries)


def _base_zero(base: PAdicBase) -> PAdicScalar:
    zero = getattr(base, "zero", None)
    return cast("PAdicScalar", zero() if callable(zero) else zero)


def _base_one(base: PAdicBase) -> PAdicScalar:
    one = getattr(base, "one", None)
    return cast("PAdicScalar", one() if callable(one) else one)


def _matrix_identity(base: PAdicBase, size: int) -> PAdicMatrix:
    from .matrices import PAdicMatrix

    return PAdicMatrix.identity(base, size)


def _matrix_zero(base: PAdicBase, nrows: int, ncols: int) -> PAdicMatrix:
    from .matrices import PAdicMatrix

    return PAdicMatrix.zero(base, nrows, ncols)


def _matrix_from_rows(base: PAdicBase, rows: Sequence[Sequence[ScalarLike]]) -> PAdicMatrix:
    from .matrices import PAdicMatrix

    return PAdicMatrix(base, rows)


def _apply_sigma(sigma: object, value: object) -> object:
    for name in ("apply_ball", "apply", "map_element"):
        operation = getattr(sigma, name, None)
        if callable(operation):
            try:
                return operation(value)
            except TypeError:
                continue
    if callable(sigma):
        return sigma(value)
    raise PAdicValidationError("the local-field embedding does not act on precision-ring elements")


def _sigma_matrix(sigma: object, matrix: PAdicMatrix) -> PAdicMatrix:
    mapper = getattr(matrix, "map_entries", None)
    if not callable(mapper):
        raise PAdicValidationError("p-adic matrices must expose map_entries")
    return cast("PAdicMatrix", mapper(lambda entry: _apply_sigma(sigma, entry)))


def _matrix_power_sigma(
    matrix: PAdicMatrix,
    sigma: object,
    exponent: int,
) -> PAdicMatrix:
    """Return ``A sigma(A) ... sigma^(exponent-1)(A)`` exactly."""

    rows, columns = _matrix_shape(matrix)
    if rows != columns:
        raise PAdicValidationError("a Frobenius matrix must be square")
    result = _matrix_identity(_matrix_base(matrix), rows)
    factor = matrix
    for _ in range(exponent):
        result = result @ factor
        factor = _sigma_matrix(sigma, factor)
    return result


def _is_zero(value: object, base: PAdicBase) -> bool:
    return value == _base_zero(base)


def _is_one(value: object, base: PAdicBase) -> bool:
    return value == _base_one(base)


def _charpoly_constant_first(matrix: PAdicMatrix) -> tuple[object, ...]:
    operation = getattr(matrix, "charpoly", None)
    if not callable(operation):
        raise PAdicValidationError("p-adic matrices must expose a division-free charpoly")
    raw = tuple(operation())
    size, columns = _matrix_shape(matrix)
    if size != columns or len(raw) != size + 1:
        raise PAdicVerificationError("characteristic polynomial has the wrong degree")
    base = _matrix_base(matrix)
    if _is_one(raw[-1], base):
        return raw
    if _is_one(raw[0], base):
        return tuple(reversed(raw))
    raise PAdicVerificationError("characteristic polynomial is not canonically monic")


def _valuation_interval(value: object) -> ValuationInterval:
    raw = getattr(value, "valuation_interval", None)
    endpoints = raw() if callable(raw) else raw
    if (
        not isinstance(endpoints, tuple)
        or len(endpoints) != 2
        or not isinstance(endpoints[0], Fraction)
        or (endpoints[1] is not None and not isinstance(endpoints[1], Fraction))
    ):
        raise PAdicVerificationError("coefficient has no canonical valuation interval")
    return ValuationInterval(endpoints[0], endpoints[1])


def _matrix_block(
    matrix: PAdicMatrix,
    row_start: int,
    row_stop: int,
    column_start: int,
    column_stop: int,
) -> PAdicMatrix:
    if row_start == row_stop or column_start == column_stop:
        raise PAdicValidationError("zero-dimensional matrix blocks are not represented")
    entries = _matrix_entries(matrix)
    return _matrix_from_rows(
        _matrix_base(matrix),
        tuple(tuple(row[column_start:column_stop]) for row in entries[row_start:row_stop]),
    )


class FrobeniusConvention(StrEnum):
    """The explicitly selected Frobenius convention."""

    ARITHMETIC = "arithmetic"
    GEOMETRIC = "geometric"


@dataclass(frozen=True, slots=True, init=False)
class ValuationInterval(PAdicSchemaObject):
    """An exact finite valuation or a finite-precision lower bound."""

    lower: Fraction
    upper: Fraction | None

    schema_version = "arbogast.padic.valuation-interval/v1"

    def __init__(self, lower: object, upper: object | None) -> None:
        normalized_lower = _fraction(lower, "valuation lower endpoint")
        normalized_upper = None if upper is None else _fraction(upper, "valuation upper endpoint")
        if normalized_upper is not None and normalized_upper < normalized_lower:
            raise PAdicValidationError("valuation interval endpoints are reversed")
        object.__setattr__(self, "lower", normalized_lower)
        object.__setattr__(self, "upper", normalized_upper)

    @property
    def exact(self) -> bool:
        return self.upper == self.lower

    def verify(self) -> bool:
        replay = ValuationInterval(self.lower, self.upper)
        if replay != self:
            raise PAdicVerificationError("valuation interval normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "lower": _rational_payload(self.lower),
            "normalization": "v_p(p)=1",
            "type": "arbogast.padic.valuation_interval",
            "upper": None if self.upper is None else _rational_payload(self.upper),
        }


@dataclass(frozen=True, slots=True, init=False)
class NewtonSegment(PAdicSchemaObject):
    """One exact segment of a stable lower Newton polygon."""

    left_index: int
    right_index: int
    left_valuation: Fraction
    right_valuation: Fraction
    semilinear_period: int
    geometric_slope: Fraction
    frobenius_slope: Fraction

    schema_version = "arbogast.padic.newton-segment/v1"

    def __init__(
        self,
        left_index: int,
        right_index: int,
        left_valuation: object,
        right_valuation: object,
        semilinear_period: int,
    ) -> None:
        left = strict_int(left_index, "left Newton index", minimum=0)
        right = strict_int(right_index, "right Newton index", minimum=1)
        if right <= left:
            raise PAdicValidationError("Newton segment indices are not increasing")
        period = strict_int(semilinear_period, "semilinear period", minimum=1)
        left_value = _fraction(left_valuation, "left Newton valuation")
        right_value = _fraction(right_valuation, "right Newton valuation")
        geometric = (right_value - left_value) / (right - left)
        object.__setattr__(self, "left_index", left)
        object.__setattr__(self, "right_index", right)
        object.__setattr__(self, "left_valuation", left_value)
        object.__setattr__(self, "right_valuation", right_value)
        object.__setattr__(self, "semilinear_period", period)
        object.__setattr__(self, "geometric_slope", geometric)
        object.__setattr__(self, "frobenius_slope", -geometric / period)

    @property
    def multiplicity(self) -> int:
        return self.right_index - self.left_index

    def verify(self) -> bool:
        if (
            NewtonSegment(
                self.left_index,
                self.right_index,
                self.left_valuation,
                self.right_valuation,
                self.semilinear_period,
            )
            != self
        ):
            raise PAdicVerificationError("Newton segment was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "frobenius_slope": _rational_payload(self.frobenius_slope),
            "geometric_slope": _rational_payload(self.geometric_slope),
            "left_index": self.left_index,
            "left_valuation": _rational_payload(self.left_valuation),
            "multiplicity": self.multiplicity,
            "normalization": "-newton-slope/semilinear-period",
            "right_index": self.right_index,
            "right_valuation": _rational_payload(self.right_valuation),
            "semilinear_period": self.semilinear_period,
            "type": "arbogast.padic.newton_segment",
        }


@dataclass(frozen=True, slots=True, order=True, init=False)
class SlopeMultiplicity(PAdicSchemaObject):
    """One normalized Frobenius slope and its exact multiplicity."""

    slope: Fraction
    multiplicity: int

    schema_version = "arbogast.padic.slope-multiplicity/v1"

    def __init__(self, slope: object, multiplicity: int) -> None:
        object.__setattr__(self, "slope", _fraction(slope, "Frobenius slope"))
        object.__setattr__(
            self,
            "multiplicity",
            strict_int(multiplicity, "slope multiplicity", minimum=1),
        )

    def verify(self) -> bool:
        if SlopeMultiplicity(self.slope, self.multiplicity) != self:
            raise PAdicVerificationError("slope multiplicity was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "multiplicity": self.multiplicity,
            "slope": _rational_payload(self.slope),
            "type": "arbogast.padic.slope_multiplicity",
        }


def _lower_hull(intervals: Sequence[ValuationInterval]) -> tuple[int, ...]:
    hull: list[int] = []
    for index, interval in enumerate(intervals):
        while len(hull) >= 2:
            first, second = hull[-2], hull[-1]
            cross = (second - first) * (interval.lower - intervals[first].lower) - (
                intervals[second].lower - intervals[first].lower
            ) * (index - first)
            if cross > 0:
                break
            hull.pop()
        hull.append(index)
    return tuple(hull)


def _polygon_data(
    matrix: PAdicMatrix,
    period: int,
) -> tuple[
    tuple[ValuationInterval, ...],
    tuple[NewtonSegment, ...],
    tuple[SlopeMultiplicity, ...],
    tuple[int, ...],
]:
    coefficients = _charpoly_constant_first(matrix)
    intervals = tuple(_valuation_interval(coefficient) for coefficient in coefficients)
    hull = _lower_hull(intervals)
    ambiguous = tuple(index for index in hull if not intervals[index].exact)
    if ambiguous:
        return intervals, (), (), ambiguous
    segments = tuple(
        NewtonSegment(
            left,
            right,
            intervals[left].lower,
            intervals[right].lower,
            period,
        )
        for left, right in pairwise(hull)
    )
    counts: dict[Fraction, int] = {}
    for segment in segments:
        counts[segment.frobenius_slope] = (
            counts.get(segment.frobenius_slope, 0) + segment.multiplicity
        )
    multiplicities = tuple(SlopeMultiplicity(slope, counts[slope]) for slope in sorted(counts))
    return intervals, segments, multiplicities, ()


@dataclass(frozen=True, slots=True, init=False)
class FrobeniusOperator(PAdicSchemaObject):
    """A pinned semilinear operator modulo a finite p-adic precision."""

    module: PAdicModule
    matrix: PAdicMatrix
    sigma: LocalFieldEmbedding | PAdicAutomorphism
    convention: FrobeniusConvention
    semilinear_period: int
    linearized_matrix: PAdicMatrix
    characteristic_polynomial: tuple[object, ...]
    valuation_intervals: tuple[ValuationInterval, ...]

    schema_version = "arbogast.padic.frobenius-operator/v1"

    def __init__(
        self,
        module: PAdicModule,
        matrix: PAdicMatrix,
        sigma: LocalFieldEmbedding | PAdicAutomorphism,
        convention: FrobeniusConvention | str,
        *,
        semilinear_period: int | None = None,
    ) -> None:
        from .fields import LocalFieldEmbedding, PAdicAutomorphism
        from .matrices import PAdicMatrix
        from .modules import PAdicModule

        if not isinstance(module, PAdicModule):
            raise TypeError("module must be a PAdicModule")
        if not isinstance(matrix, PAdicMatrix):
            raise TypeError("matrix must be a PAdicMatrix")
        if not isinstance(sigma, LocalFieldEmbedding | PAdicAutomorphism):
            raise TypeError("sigma must be a LocalFieldEmbedding or finite-ring PAdicAutomorphism")
        try:
            normalized_convention = FrobeniusConvention(convention)
        except (TypeError, ValueError) as error:
            raise PAdicValidationError("unsupported Frobenius convention") from error
        rank = _module_rank(module)
        if not 0 <= rank <= MAX_DIMENSION:
            raise PAdicValidationError("Frobenius module rank exceeds the portable bound")
        if _matrix_shape(matrix) != (rank, rank):
            raise PAdicValidationError("Frobenius matrix has the wrong module shape")
        module_base = _module_base(module)
        if _matrix_base(matrix) != module_base:
            raise PAdicValidationError("Frobenius matrix uses a different precision ring")
        field = getattr(module_base, "field", None)
        if isinstance(sigma, LocalFieldEmbedding):
            if sigma.domain != field or sigma.codomain != field:
                raise PAdicValidationError(
                    "Frobenius sigma is not an automorphism of the base field"
                )
        elif sigma.ring != module_base:
            raise PAdicValidationError(
                "finite-precision Frobenius sigma uses a different coefficient ring"
            )
        residue_period = _field_residue_degree(field)
        period = (
            residue_period
            if semilinear_period is None
            else strict_int(semilinear_period, "semilinear period", minimum=1)
        )
        if period != residue_period:
            raise PAdicValidationError("semilinear period must equal the pinned residue degree f")
        if period > MAX_DIMENSION:
            raise PAdicValidationError("semilinear period exceeds the portable bound")
        _check_frobenius_work(module_base, rank, period)
        _verify_residue_frobenius(module_base, sigma, normalized_convention)
        _verify_sigma_period(module_base, sigma, period)
        linearized = _matrix_power_sigma(matrix, sigma, period)
        coefficients = _charpoly_constant_first(linearized)
        intervals = tuple(_valuation_interval(coefficient) for coefficient in coefficients)
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "sigma", sigma)
        object.__setattr__(self, "convention", normalized_convention)
        object.__setattr__(self, "semilinear_period", period)
        object.__setattr__(self, "linearized_matrix", linearized)
        object.__setattr__(self, "characteristic_polynomial", coefficients)
        object.__setattr__(self, "valuation_intervals", intervals)

    @property
    def operator_id(self) -> str:
        return self.content_id

    @property
    def rank(self) -> int:
        return _module_rank(self.module)

    def verify(self) -> bool:
        replay = FrobeniusOperator(
            self.module,
            self.matrix,
            self.sigma,
            self.convention,
            semilinear_period=self.semilinear_period,
        )
        if replay.to_canonical_data() != self.to_canonical_data():
            raise PAdicVerificationError("Frobenius operator replay was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        base = _module_base(self.module)
        return {
            "action_convention": "column semilinear: F(v)=A sigma(v)",
            "characteristic_polynomial": [
                cast(Any, coefficient).to_schema_document()
                for coefficient in self.characteristic_polynomial
            ],
            "coefficient_field": base.field.to_schema_document(),
            "coefficient_field_id": _object_id(base.field, "field_id"),
            "convention": self.convention.value,
            "linearized_matrix": self.linearized_matrix.to_schema_document(),
            "linearized_power": self.semilinear_period,
            "matrix": self.matrix.to_schema_document(),
            "module": self.module.to_schema_document(),
            "module_id": _object_id(self.module, "module_id"),
            "precision_ring": base.to_schema_document(),
            "precision_ring_id": _object_id(base, "ring_id"),
            "semilinear_period": self.semilinear_period,
            "sigma_id": _object_id(self.sigma, "embedding_id"),
            "sigma": self.sigma.to_schema_document(),
            "sigma_residue_action": (
                "x -> x^p modulo uniformizer"
                if self.convention is FrobeniusConvention.ARITHMETIC
                else "sigma(x)^p -> x modulo uniformizer"
            ),
            "type": "arbogast.padic.frobenius_operator",
            "valuation_intervals": [
                interval.to_schema_document() for interval in self.valuation_intervals
            ],
        }


def _module_rank(module: object) -> int:
    value = getattr(module, "rank", getattr(module, "dimension", None))
    return strict_int(value, "p-adic module rank", minimum=0)


def _module_base(module: object) -> PAdicPrecisionRing:
    from .fields import PAdicPrecisionRing

    base = getattr(module, "ring", getattr(module, "base", None))
    if not isinstance(base, PAdicPrecisionRing):
        raise PAdicValidationError("p-adic module omits its precision ring")
    return base


def _field_residue_degree(field: object) -> int:
    value = getattr(field, "residue_degree", getattr(field, "f", None))
    return strict_int(value, "residue degree", minimum=1)


def _check_frobenius_work(base: PAdicPrecisionRing, rank: int, period: int) -> None:
    degree = base.field.degree
    precision = base.precision
    algebra_work = (period * rank**3 + rank**4) * degree * min(precision, 4)
    precision_work = rank**2 * period * degree * precision
    if algebra_work > MAX_EXACT_REPLAY_WORK:
        raise PAdicResourceError("Frobenius replay exceeds the exact algebra-work bound")
    if precision_work > MAX_PRECISION_WORK:
        raise PAdicResourceError("Frobenius replay exceeds the precision-work bound")


def _verify_residue_frobenius(
    base: PAdicPrecisionRing,
    sigma: object,
    convention: FrobeniusConvention,
) -> None:
    degree = base.field.degree
    prime = base.field.prime
    basis = tuple(
        base.from_coordinates(
            tuple(1 if coordinate == index else 0 for coordinate in range(degree))
        )
        for index in range(degree)
    )
    for element in basis:
        image = cast("PAdicBall", _apply_sigma(sigma, element))
        difference = (
            image - element**prime
            if convention is FrobeniusConvention.ARITHMETIC
            else image**prime - element
        )
        if base.valuation_order(difference.coordinates) < 1:
            if convention is FrobeniusConvention.ARITHMETIC:
                expected = "x -> x^p"
            else:
                expected = "inverse x -> x^p"
            raise PAdicValidationError(
                f"Frobenius sigma does not induce {expected} on the residue field"
            )


def _verify_sigma_period(base: object, sigma: object, period: int) -> None:
    verifier = getattr(sigma, "verify", None)
    if callable(verifier) and verifier() is False:
        raise PAdicValidationError("local-field embedding verification failed")
    degree = getattr(getattr(base, "field", None), "degree", None)
    if type(degree) is not int or degree < 1:
        raise PAdicValidationError("precision-ring field degree is invalid")
    from_coordinates = getattr(base, "from_coordinates", None)
    if not callable(from_coordinates):
        raise PAdicValidationError("precision ring omits canonical coordinate construction")
    generators = tuple(
        from_coordinates(tuple(1 if index == selected else 0 for index in range(degree)))
        for selected in range(degree)
    )
    for generator in generators:
        image = generator
        for _ in range(period):
            image = _apply_sigma(sigma, image)
        if image != generator:
            raise PAdicValidationError("sigma^f is not identity at the declared precision")


@dataclass(frozen=True, slots=True, init=False)
class SlopeProjector(PAdicSchemaObject):
    """A supplied saturated direct-summand projector for one slope."""

    operator: FrobeniusOperator
    slope: Fraction
    rank: int
    projector: PAdicMatrix
    basis_change: PAdicMatrix
    basis_change_inverse: PAdicMatrix
    submodule: PAdicSubmodule

    schema_version = "arbogast.padic.slope-projector/v1"

    def __init__(
        self,
        operator: FrobeniusOperator,
        slope: object,
        rank: int,
        projector: PAdicMatrix,
        basis_change: PAdicMatrix,
        basis_change_inverse: PAdicMatrix,
        *,
        submodule: PAdicSubmodule | None = None,
    ) -> None:
        if not isinstance(operator, FrobeniusOperator):
            raise TypeError("operator must be a FrobeniusOperator")
        normalized_rank = strict_int(rank, "slope-projector rank", minimum=0)
        normalized_slope = _fraction(slope, "projector slope")
        if normalized_rank > operator.rank:
            raise PAdicValidationError("slope-projector rank exceeds the module rank")
        if normalized_rank == 0 and normalized_slope != 0:
            raise PAdicValidationError("the canonical zero projector is reserved for slope zero")
        from .matrices import PAdicMatrix
        from .modules import PAdicSubmodule

        size = operator.rank
        base = _module_base(operator.module)
        matrices = (projector, basis_change, basis_change_inverse)
        if any(not isinstance(matrix, PAdicMatrix) for matrix in matrices):
            raise TypeError("slope projector witnesses must be PAdicMatrix objects")
        if any(_matrix_shape(matrix) != (size, size) for matrix in matrices):
            raise PAdicValidationError("slope projector matrices have the wrong shape")
        if any(_matrix_base(matrix) != base for matrix in matrices):
            raise PAdicValidationError("slope projector matrices use a foreign base")
        basis_entries = _matrix_entries(basis_change)
        expected_submodule = PAdicSubmodule(
            operator.module,
            (
                cast(
                    "tuple[PAdicBall, ...]",
                    tuple(basis_entries[row][column] for row in range(size)),
                )
                for column in range(normalized_rank)
            ),
        )
        if submodule is not None:
            if not isinstance(submodule, PAdicSubmodule):
                raise TypeError("slope submodule must be a PAdicSubmodule")
            if submodule != expected_submodule:
                raise PAdicValidationError(
                    "slope submodule is not the image of the saturated basis-change columns"
                )
        bound_submodule = expected_submodule
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "slope", normalized_slope)
        object.__setattr__(self, "rank", normalized_rank)
        object.__setattr__(self, "projector", projector)
        object.__setattr__(self, "basis_change", basis_change)
        object.__setattr__(self, "basis_change_inverse", basis_change_inverse)
        object.__setattr__(self, "submodule", bound_submodule)
        self.verify()

    def verify(self) -> bool:
        size = self.operator.rank
        base = _module_base(self.operator.module)
        matrices = (self.projector, self.basis_change, self.basis_change_inverse)
        if any(_matrix_shape(matrix) != (size, size) for matrix in matrices):
            raise PAdicVerificationError("slope projector matrices have the wrong shape")
        if any(_matrix_base(matrix) != base for matrix in matrices):
            raise PAdicVerificationError("slope projector matrices use a foreign base")
        identity = _matrix_identity(base, size)
        if (
            self.basis_change @ self.basis_change_inverse != identity
            or self.basis_change_inverse @ self.basis_change != identity
        ):
            raise PAdicVerificationError("slope basis change is not exactly invertible")
        diagonal = _matrix_from_rows(
            base,
            tuple(
                tuple(
                    _base_one(base) if row == column and row < self.rank else _base_zero(base)
                    for column in range(size)
                )
                for row in range(size)
            ),
        )
        expected = self.basis_change @ diagonal @ self.basis_change_inverse
        if self.projector != expected or self.projector @ self.projector != self.projector:
            raise PAdicVerificationError("slope projector is not the supplied direct summand")
        if self.projector @ self.operator.matrix != self.operator.matrix @ _sigma_matrix(
            self.operator.sigma,
            self.projector,
        ):
            raise PAdicVerificationError("slope projector is not semilinearly Frobenius-stable")
        transformed = (
            self.basis_change_inverse @ self.operator.linearized_matrix @ self.basis_change
        )
        if 0 < self.rank < size:
            upper_right = _matrix_block(transformed, 0, self.rank, self.rank, size)
            lower_left = _matrix_block(transformed, self.rank, size, 0, self.rank)
            if upper_right != _matrix_zero(base, self.rank, size - self.rank) or lower_left != (
                _matrix_zero(base, size - self.rank, self.rank)
            ):
                raise PAdicVerificationError("linearized Frobenius does not preserve the summand")
        if self.rank:
            restricted = _matrix_block(transformed, 0, self.rank, 0, self.rank)
            _intervals, _segments, multiplicities, ambiguous = _polygon_data(
                restricted,
                self.operator.semilinear_period,
            )
            if ambiguous or multiplicities != (SlopeMultiplicity(self.slope, self.rank),):
                raise PAdicVerificationError(
                    "projected block does not have the declared pure slope"
                )
        from .modules import PAdicSubmodule

        basis_entries = _matrix_entries(self.basis_change)
        expected_submodule = PAdicSubmodule(
            self.operator.module,
            (
                cast(
                    "tuple[PAdicBall, ...]",
                    tuple(basis_entries[row][column] for row in range(size)),
                )
                for column in range(self.rank)
            ),
        )
        if self.submodule != expected_submodule:
            raise PAdicVerificationError(
                "slope submodule is not the saturated image of its projector"
            )
        self.submodule.verify()
        if self.submodule.cardinality != base.cardinality**self.rank:
            raise PAdicVerificationError("slope submodule has the wrong direct-summand size")
        for generator in self.submodule.canonical_generators:
            if self.projector.matvec(generator) != generator:
                raise PAdicVerificationError("slope submodule contains a vector off the image")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "basis_change": self.basis_change.to_schema_document(),
            "basis_change_inverse": self.basis_change_inverse.to_schema_document(),
            "operator_id": self.operator.operator_id,
            "operator": self.operator.to_schema_document(),
            "projector": self.projector.to_schema_document(),
            "rank": self.rank,
            "slope": _rational_payload(self.slope),
            "submodule": self.submodule.to_schema_document(),
            "type": "arbogast.padic.slope_projector",
        }


def _check_decomposition_work(
    operator: FrobeniusOperator,
    projector_ranks: Sequence[int],
) -> None:
    rank = operator.rank
    count = len(projector_ranks)
    base = _module_base(operator.module)
    degree = base.field.degree
    precision = base.precision
    matrix_work = count * 4 * rank**3 + count**2 * rank**3
    polynomial_work = sum(projector_rank**4 for projector_rank in projector_ranks)
    algebra_work = (matrix_work + polynomial_work) * degree * min(precision, 4)
    precision_work = (count + count**2) * rank**2 * degree * precision
    if algebra_work > MAX_EXACT_REPLAY_WORK:
        raise PAdicResourceError("slope-projector aggregate exceeds the exact algebra-work bound")
    if precision_work > MAX_PRECISION_WORK:
        raise PAdicResourceError("slope-projector aggregate exceeds the precision-work bound")


@dataclass(frozen=True, slots=True, init=False)
class SlopeDecomposition(PAdicSchemaObject):
    """Stable Newton multiplicities and any independently checked projectors."""

    operator: FrobeniusOperator
    intervals: tuple[ValuationInterval, ...]
    segments: tuple[NewtonSegment, ...]
    multiplicities: tuple[SlopeMultiplicity, ...]
    projectors: tuple[SlopeProjector, ...]
    projectors_complete: bool

    schema_version = "arbogast.padic.slope-decomposition/v1"

    def __init__(
        self,
        operator: FrobeniusOperator,
        intervals: Sequence[ValuationInterval],
        segments: Sequence[NewtonSegment],
        multiplicities: Sequence[SlopeMultiplicity],
        projectors: Sequence[SlopeProjector] = (),
    ) -> None:
        if not isinstance(operator, FrobeniusOperator):
            raise TypeError("operator must be a FrobeniusOperator")
        normalized_intervals = _bounded_tuple(
            intervals,
            operator.rank + 1,
            "slope valuation-interval count",
        )
        normalized_segments = _bounded_tuple(
            segments,
            operator.rank,
            "Newton-segment count",
        )
        normalized_multiplicities = _bounded_tuple(
            multiplicities,
            operator.rank,
            "slope-multiplicity count",
        )
        if any(not isinstance(item, ValuationInterval) for item in normalized_intervals):
            raise TypeError("slope intervals must be ValuationInterval objects")
        if any(not isinstance(item, NewtonSegment) for item in normalized_segments):
            raise TypeError("Newton segments must be NewtonSegment objects")
        if any(not isinstance(item, SlopeMultiplicity) for item in normalized_multiplicities):
            raise TypeError("slope multiplicities must be SlopeMultiplicity objects")
        supplied_projectors = _bounded_tuple(
            projectors,
            operator.rank,
            "slope-projector count",
        )
        if any(not isinstance(item, SlopeProjector) for item in supplied_projectors):
            raise TypeError("slope projectors must be SlopeProjector objects")
        _check_decomposition_work(
            operator,
            tuple(item.rank for item in supplied_projectors),
        )
        normalized_projectors = tuple(sorted(supplied_projectors, key=lambda item: item.slope))
        expected = {item.slope: item.multiplicity for item in normalized_multiplicities}
        supplied = {item.slope: item.rank for item in normalized_projectors}
        complete = bool(expected) and supplied == expected
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "intervals", normalized_intervals)
        object.__setattr__(self, "segments", normalized_segments)
        object.__setattr__(self, "multiplicities", normalized_multiplicities)
        object.__setattr__(self, "projectors", normalized_projectors)
        object.__setattr__(self, "projectors_complete", complete)
        self.verify()

    def projector(self, slope: object) -> SlopeProjector:
        target = _fraction(slope, "requested slope")
        matches = tuple(item for item in self.projectors if item.slope == target)
        if len(matches) != 1:
            raise KeyError(target)
        return matches[0]

    def verify(self) -> bool:
        intervals, segments, multiplicities, ambiguous = _polygon_data(
            self.operator.linearized_matrix,
            self.operator.semilinear_period,
        )
        if ambiguous:
            raise PAdicVerificationError("a slope decomposition has an ambiguous Newton polygon")
        if (
            intervals != self.intervals
            or segments != self.segments
            or multiplicities != self.multiplicities
        ):
            raise PAdicVerificationError("slope decomposition polygon data was altered")
        if sum(item.multiplicity for item in self.multiplicities) != self.operator.rank:
            raise PAdicVerificationError("slope multiplicities do not exhaust the module rank")
        if tuple(sorted(set(item.slope for item in self.multiplicities))) != tuple(
            item.slope for item in self.multiplicities
        ):
            raise PAdicVerificationError("slope multiplicities are not canonical and unique")
        if len({item.slope for item in self.projectors}) != len(self.projectors):
            raise PAdicVerificationError("slope projector list contains duplicate slopes")
        expected = {item.slope: item.multiplicity for item in self.multiplicities}
        for item in self.projectors:
            if item.operator != self.operator or expected.get(item.slope) != item.rank:
                raise PAdicVerificationError("slope projector is foreign or has the wrong rank")
            item.verify()
        base = _module_base(self.operator.module)
        zero = _matrix_zero(base, self.operator.rank, self.operator.rank)
        for left_index, left in enumerate(self.projectors):
            for right_index, right in enumerate(self.projectors):
                if left_index != right_index and (
                    left.projector @ right.projector != zero
                    or right.projector @ left.projector != zero
                ):
                    raise PAdicVerificationError("slope projectors are not pairwise orthogonal")
        if self.projectors_complete:
            total = zero
            for item in self.projectors:
                total = total + item.projector
            if total != _matrix_identity(base, self.operator.rank):
                raise PAdicVerificationError("complete slope projectors do not sum to identity")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "intervals": [item.to_schema_document() for item in self.intervals],
            "multiplicities": [item.to_schema_document() for item in self.multiplicities],
            "operator_id": self.operator.operator_id,
            "operator": self.operator.to_schema_document(),
            "polygon_complete": True,
            "projectors": [item.to_schema_document() for item in self.projectors],
            "projectors_complete": self.projectors_complete,
            "segments": [item.to_schema_document() for item in self.segments],
            "type": "arbogast.padic.slope_decomposition",
        }


def _raw_object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise PAdicVerificationError(f"{name} must be a strict JSON object")
    return cast(dict[str, object], value)


def _raw_list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise PAdicVerificationError(f"{name} must be a strict JSON array")
    return cast(list[object], value)


def _document_body(
    value: Mapping[str, object],
    *,
    schema: str,
    type_tag: str,
    keys: set[str],
    name: str,
) -> dict[str, object]:
    raw = _raw_object(value, name)
    expected = {"schema", *keys}
    if set(raw) != expected:
        raise PAdicVerificationError(
            f"{name} fields mismatch; missing={sorted(expected - set(raw))}, "
            f"extra={sorted(set(raw) - expected)}"
        )
    if raw["schema"] != schema or raw.get("type") != type_tag:
        raise PAdicVerificationError(f"{name} schema or type was altered")
    strict_canonical_mapping(raw, name)
    return raw


def _decode_rational(value: object, name: str) -> Fraction:
    raw = _raw_list(value, name)
    if len(raw) != 2 or type(raw[0]) is not int or type(raw[1]) is not int or raw[1] <= 0:
        raise PAdicVerificationError(f"{name} must be a canonical rational pair")
    result = Fraction(raw[0], raw[1])
    if _rational_payload(result) != raw:
        raise PAdicVerificationError(f"{name} is not a reduced rational pair")
    return result


def _decode_module_document(ring: object, value: object) -> PAdicModule:
    from .fields import PAdicPrecisionRing
    from .modules import PAdicModule

    if not isinstance(ring, PAdicPrecisionRing):
        raise TypeError("module decoder requires a PAdicPrecisionRing")
    raw = _document_body(
        _raw_object(value, "p-adic module"),
        schema=PAdicModule.schema_version,
        type_tag="arbogast.padic.module",
        keys={
            "basis_labels",
            "coordinate_convention",
            "rank",
            "ring_id",
            "type",
        },
        name="p-adic module",
    )
    labels = _raw_list(raw["basis_labels"], "p-adic module basis labels")
    rank = strict_int(raw["rank"], "p-adic module rank", minimum=1)
    if rank > MAX_DIMENSION or len(labels) > MAX_DIMENSION:
        raise PAdicResourceError("p-adic module exceeds the portable dimension bound")
    if len(labels) != rank:
        raise PAdicVerificationError("p-adic module basis-label count does not match rank")
    if any(type(label) is not str for label in labels):
        raise PAdicVerificationError("p-adic module basis labels must be strings")
    if (
        raw["coordinate_convention"] != "component-major column vectors"
        or raw["ring_id"] != ring.ring_id
    ):
        raise PAdicVerificationError("p-adic module ring or coordinate convention was altered")
    result = PAdicModule(
        ring,
        rank,
        basis_labels=cast(list[str], labels),
    )
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("p-adic module is not strict canonical transport")
    return result


def _decode_matrix_document(ring: object, value: object, name: str) -> PAdicMatrix:
    from .fields import PAdicBall, PAdicPrecisionRing
    from .matrices import PAdicMatrix

    if not isinstance(ring, PAdicPrecisionRing):
        raise TypeError("finite Frobenius matrix decoder requires a precision ring")
    raw = _document_body(
        _raw_object(value, name),
        schema=PAdicMatrix.schema_version,
        type_tag="arbogast.padic.matrix",
        keys={"base_id", "base_kind", "column_action", "entries", "shape", "type"},
        name=name,
    )
    if (
        raw["base_id"] != ring.ring_id
        or raw["base_kind"] != "precision-ring"
        or raw["column_action"] is not True
    ):
        raise PAdicVerificationError(f"{name} base or action convention was altered")
    raw_rows = _raw_list(raw["entries"], f"{name} entries")
    if len(raw_rows) > MAX_DIMENSION:
        raise PAdicResourceError(f"{name} row count exceeds the portable bound")
    rows: list[tuple[PAdicScalar, ...]] = []
    for row_index, row in enumerate(raw_rows):
        raw_entries = _raw_list(row, f"{name} row[{row_index}]")
        if len(raw_entries) > MAX_DIMENSION:
            raise PAdicResourceError(f"{name} column count exceeds the portable bound")
        entries: list[PAdicScalar] = []
        for column_index, entry in enumerate(raw_entries):
            ball = _raw_object(entry, f"{name} entry[{row_index},{column_index}]")
            ball_document = (
                ball if "schema" in ball else {"schema": PAdicBall.schema_version, **ball}
            )
            entries.append(PAdicBall.from_dict(ring, ball_document))
        rows.append(tuple(entries))
    result = PAdicMatrix(ring, rows)
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError(f"{name} is not strict canonical transport")
    return result


def _decode_operator_document_exact(value: Mapping[str, object]) -> FrobeniusOperator:
    from .fields import (
        LocalFieldEmbedding,
        PAdicAutomorphism,
        PAdicField,
        PAdicPrecisionRing,
    )

    raw = _document_body(
        value,
        schema=FrobeniusOperator.schema_version,
        type_tag="arbogast.padic.frobenius_operator",
        keys={
            "action_convention",
            "characteristic_polynomial",
            "coefficient_field",
            "coefficient_field_id",
            "convention",
            "linearized_matrix",
            "linearized_power",
            "matrix",
            "module",
            "module_id",
            "precision_ring",
            "precision_ring_id",
            "semilinear_period",
            "sigma",
            "sigma_id",
            "sigma_residue_action",
            "type",
            "valuation_intervals",
        },
        name="Frobenius operator",
    )
    field = PAdicField.from_dict(
        _raw_object(raw["coefficient_field"], "Frobenius coefficient field")
    )
    ring = PAdicPrecisionRing.from_dict(
        field,
        _raw_object(raw["precision_ring"], "Frobenius precision ring"),
    )
    module = _decode_module_document(ring, raw["module"])
    raw_characteristic = _raw_list(
        raw["characteristic_polynomial"],
        "Frobenius characteristic polynomial",
    )
    raw_intervals = _raw_list(
        raw["valuation_intervals"],
        "Frobenius valuation intervals",
    )
    if len(raw_characteristic) > module.rank + 1 or len(raw_intervals) > module.rank + 1:
        raise PAdicResourceError("Frobenius polynomial metadata exceeds the module-rank bound")
    if len(raw_characteristic) != module.rank + 1 or len(raw_intervals) != module.rank + 1:
        raise PAdicVerificationError("Frobenius polynomial metadata has the wrong degree")
    sigma_raw = _raw_object(raw["sigma"], "Frobenius sigma")
    sigma_type = sigma_raw.get("type")
    sigma: LocalFieldEmbedding | PAdicAutomorphism
    if sigma_type == "arbogast.padic.automorphism":
        sigma = PAdicAutomorphism.from_dict(ring, sigma_raw)
    elif sigma_type == "arbogast.padic.local_field_embedding":
        sigma = LocalFieldEmbedding.from_dict(field, field, sigma_raw)
    else:
        raise PAdicVerificationError("Frobenius sigma has an unsupported type")
    matrix = _decode_matrix_document(ring, raw["matrix"], "Frobenius matrix")
    transported_linearized = _decode_matrix_document(
        ring,
        raw["linearized_matrix"],
        "linearized Frobenius matrix",
    )
    result = FrobeniusOperator(
        module,
        matrix,
        sigma,
        cast(str, raw["convention"]),
        semilinear_period=strict_int(
            raw["semilinear_period"],
            "Frobenius semilinear period",
            minimum=1,
        ),
    )
    if transported_linearized != result.linearized_matrix:
        raise PAdicVerificationError("linearized Frobenius matrix was altered")
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("Frobenius operator is not strict canonical transport")
    return result


def _decode_operator_document(value: Mapping[str, object]) -> FrobeniusOperator:
    try:
        return _decode_operator_document_exact(value)
    except PAdicVerificationError:
        raise
    except (TypeError, ValueError) as error:
        raise PAdicVerificationError(
            "Frobenius operator witness failed independent replay"
        ) from error


def _decode_interval_document(value: object) -> ValuationInterval:
    raw = _document_body(
        _raw_object(value, "valuation interval"),
        schema=ValuationInterval.schema_version,
        type_tag="arbogast.padic.valuation_interval",
        keys={"lower", "normalization", "type", "upper"},
        name="valuation interval",
    )
    if raw["normalization"] != "v_p(p)=1":
        raise PAdicVerificationError("valuation normalization was altered")
    result = ValuationInterval(
        _decode_rational(raw["lower"], "valuation lower endpoint"),
        (
            None
            if raw["upper"] is None
            else _decode_rational(raw["upper"], "valuation upper endpoint")
        ),
    )
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("valuation interval is not strict canonical transport")
    return result


def _decode_segment_document(value: object) -> NewtonSegment:
    raw = _document_body(
        _raw_object(value, "Newton segment"),
        schema=NewtonSegment.schema_version,
        type_tag="arbogast.padic.newton_segment",
        keys={
            "frobenius_slope",
            "geometric_slope",
            "left_index",
            "left_valuation",
            "multiplicity",
            "normalization",
            "right_index",
            "right_valuation",
            "semilinear_period",
            "type",
        },
        name="Newton segment",
    )
    result = NewtonSegment(
        strict_int(raw["left_index"], "left Newton index", minimum=0),
        strict_int(raw["right_index"], "right Newton index", minimum=1),
        _decode_rational(raw["left_valuation"], "left Newton valuation"),
        _decode_rational(raw["right_valuation"], "right Newton valuation"),
        strict_int(raw["semilinear_period"], "semilinear period", minimum=1),
    )
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("Newton segment is not strict canonical transport")
    return result


def _decode_multiplicity_document(value: object) -> SlopeMultiplicity:
    raw = _document_body(
        _raw_object(value, "slope multiplicity"),
        schema=SlopeMultiplicity.schema_version,
        type_tag="arbogast.padic.slope_multiplicity",
        keys={"multiplicity", "slope", "type"},
        name="slope multiplicity",
    )
    result = SlopeMultiplicity(
        _decode_rational(raw["slope"], "Frobenius slope"),
        strict_int(raw["multiplicity"], "slope multiplicity", minimum=1),
    )
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("slope multiplicity is not strict canonical transport")
    return result


def _decode_submodule_document(module: PAdicModule, value: object) -> PAdicSubmodule:
    from .modules import PAdicSubmodule

    raw = _document_body(
        _raw_object(value, "slope submodule"),
        schema=PAdicSubmodule.schema_version,
        type_tag="arbogast.padic.submodule",
        keys={"ambient_id", "cardinality", "preimage_hnf", "type"},
        name="slope submodule",
    )
    dimension = module.rank * _module_base(module).field.degree
    raw_hnf = _raw_list(raw["preimage_hnf"], "slope submodule HNF")
    if len(raw_hnf) > dimension:
        raise PAdicResourceError("slope submodule HNF exceeds the ambient dimension")
    if len(raw_hnf) != dimension:
        raise PAdicVerificationError("slope submodule HNF has the wrong row count")
    hnf_rows: list[tuple[int, ...]] = []
    for index, row in enumerate(raw_hnf):
        raw_row = _raw_list(row, f"slope submodule HNF row[{index}]")
        if len(raw_row) > dimension:
            raise PAdicResourceError("slope submodule HNF row exceeds the ambient dimension")
        if len(raw_row) != dimension:
            raise PAdicVerificationError("slope submodule HNF has the wrong column count")
        hnf_rows.append(tuple(strict_int(entry, "slope submodule HNF entry") for entry in raw_row))
    hnf = tuple(hnf_rows)
    result = PAdicSubmodule(module, preimage_hnf=hnf)
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("slope submodule is not strict canonical transport")
    return result


def _decode_projector_document_exact(
    value: Mapping[str, object],
    *,
    expected_operator: FrobeniusOperator | None = None,
) -> SlopeProjector:
    raw = _document_body(
        value,
        schema=SlopeProjector.schema_version,
        type_tag="arbogast.padic.slope_projector",
        keys={
            "basis_change",
            "basis_change_inverse",
            "operator",
            "operator_id",
            "projector",
            "rank",
            "slope",
            "submodule",
            "type",
        },
        name="slope projector",
    )
    raw_operator = _raw_object(raw["operator"], "slope-projector operator")
    if expected_operator is None:
        operator = _decode_operator_document(raw_operator)
    else:
        if raw["operator_id"] != expected_operator.operator_id or not strict_canonical_equal(
            raw_operator,
            expected_operator.to_schema_document(),
        ):
            raise PAdicVerificationError("slope projector is bound to another operator")
        operator = expected_operator
    ring = _module_base(operator.module)
    result = SlopeProjector(
        operator,
        _decode_rational(raw["slope"], "projector slope"),
        strict_int(raw["rank"], "projector rank", minimum=0),
        _decode_matrix_document(ring, raw["projector"], "slope projector matrix"),
        _decode_matrix_document(ring, raw["basis_change"], "slope basis change"),
        _decode_matrix_document(
            ring,
            raw["basis_change_inverse"],
            "slope basis-change inverse",
        ),
        submodule=_decode_submodule_document(operator.module, raw["submodule"]),
    )
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("slope projector is not strict canonical transport")
    return result


def _decode_projector_document(
    value: Mapping[str, object],
    *,
    expected_operator: FrobeniusOperator | None = None,
) -> SlopeProjector:
    try:
        return _decode_projector_document_exact(
            value,
            expected_operator=expected_operator,
        )
    except PAdicVerificationError:
        raise
    except (TypeError, ValueError) as error:
        raise PAdicVerificationError("slope projector witness failed independent replay") from error


def _decode_decomposition_document_exact(value: Mapping[str, object]) -> SlopeDecomposition:
    raw = _document_body(
        value,
        schema=SlopeDecomposition.schema_version,
        type_tag="arbogast.padic.slope_decomposition",
        keys={
            "intervals",
            "multiplicities",
            "operator",
            "operator_id",
            "polygon_complete",
            "projectors",
            "projectors_complete",
            "segments",
            "type",
        },
        name="slope decomposition",
    )
    if raw["polygon_complete"] is not True or type(raw["projectors_complete"]) is not bool:
        raise PAdicVerificationError("slope-decomposition completeness flags were altered")
    operator = _decode_operator_document(
        _raw_object(raw["operator"], "slope-decomposition operator")
    )
    raw_intervals = _raw_list(raw["intervals"], "slope intervals")
    raw_segments = _raw_list(raw["segments"], "Newton segments")
    raw_multiplicities = _raw_list(raw["multiplicities"], "slope multiplicities")
    raw_projectors = _raw_list(raw["projectors"], "slope projectors")
    if len(raw_intervals) > operator.rank + 1:
        raise PAdicResourceError("slope interval count exceeds the operator-rank bound")
    if len(raw_segments) > operator.rank:
        raise PAdicResourceError("Newton-segment count exceeds the operator-rank bound")
    if len(raw_multiplicities) > operator.rank:
        raise PAdicResourceError("slope-multiplicity count exceeds the operator-rank bound")
    if len(raw_projectors) > operator.rank:
        raise PAdicResourceError("slope-projector count exceeds the operator-rank bound")
    projector_documents = tuple(
        _raw_object(item, f"slope projector[{index}]") for index, item in enumerate(raw_projectors)
    )
    projector_ranks = tuple(
        strict_int(document.get("rank"), f"slope projector[{index}] rank", minimum=0)
        for index, document in enumerate(projector_documents)
    )
    if any(rank > operator.rank for rank in projector_ranks):
        raise PAdicVerificationError("slope-projector rank exceeds the operator rank")
    _check_decomposition_work(operator, projector_ranks)
    result = SlopeDecomposition(
        operator,
        tuple(_decode_interval_document(item) for item in raw_intervals),
        tuple(_decode_segment_document(item) for item in raw_segments),
        tuple(_decode_multiplicity_document(item) for item in raw_multiplicities),
        tuple(
            _decode_projector_document(
                document,
                expected_operator=operator,
            )
            for document in projector_documents
        ),
    )
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("slope decomposition is not strict canonical transport")
    return result


def _decode_decomposition_document(value: Mapping[str, object]) -> SlopeDecomposition:
    try:
        return _decode_decomposition_document_exact(value)
    except PAdicVerificationError:
        raise
    except (TypeError, ValueError) as error:
        raise PAdicVerificationError(
            "slope decomposition witness failed independent replay"
        ) from error


def _decode_ordinary_document(value: Mapping[str, object]) -> SlopeProjector:
    try:
        result = _decode_projector_document(value)
        if result.slope != 0:
            raise PAdicVerificationError("ordinary receipt contains a nonzero-slope projector")
        _intervals, _segments, multiplicities, ambiguous = _polygon_data(
            result.operator.linearized_matrix,
            result.operator.semilinear_period,
        )
        zero_rank = next(
            (item.multiplicity for item in multiplicities if item.slope == 0),
            0,
        )
        if ambiguous or result.rank != zero_rank:
            raise PAdicVerificationError(
                "ordinary projector does not exhaust the stable slope-zero multiplicity"
            )
        return result
    except PAdicVerificationError:
        raise
    except (TypeError, ValueError) as error:
        raise PAdicVerificationError(
            "ordinary projector witness failed independent replay"
        ) from error


def _unknown(
    operation: str,
    reason_code: str,
    reason: str,
    *,
    requested: dict[str, object],
) -> PAdicResult[Any]:
    from .results import unknown_result

    return unknown_result(
        operation,
        reason_code,
        reason,
        requested=requested,
        family="finite",
    )


def frobenius(
    module: PAdicModule,
    *,
    datum: object | None = None,
) -> PAdicResult[FrobeniusOperator]:
    """Construct a supplied finite-precision Frobenius operator.

    ``datum`` may itself be a :class:`FrobeniusOperator`, or must expose
    ``matrix``, ``sigma``, and ``convention``.  No backend discovery or
    convention conversion is implicit.
    """

    if datum is None:
        return _unknown(
            "padic.frobenius",
            "missing-semilinear-frobenius-datum",
            "a semilinear Frobenius datum was not supplied",
            requested={"module_id": _object_id(module, "module_id")},
        )
    if isinstance(datum, FrobeniusOperator):
        if datum.module != module:
            raise PAdicValidationError("Frobenius datum is bound to another module")
        datum.verify()
        operator = datum
    else:
        matrix = getattr(datum, "matrix", None)
        sigma = getattr(datum, "sigma", None)
        convention = getattr(datum, "convention", None)
        period = getattr(datum, "semilinear_period", None)
        if matrix is None or sigma is None or convention is None:
            raise PAdicValidationError("Frobenius datum must expose matrix, sigma, and convention")
        source_id = getattr(datum, "module_id", None)
        if source_id is not None and source_id != _object_id(module, "module_id"):
            raise PAdicValidationError("Frobenius datum names another module")
        operator = FrobeniusOperator(
            module,
            matrix,
            sigma,
            convention,
            semilinear_period=period,
        )
    from .results import certified_result

    return certified_result(operator, "frobenius")


def slopes(
    operator: FrobeniusOperator,
    *,
    projectors: Sequence[SlopeProjector] = (),
) -> PAdicResult[SlopeDecomposition]:
    """Certify normalized Newton slopes when finite precision determines them."""

    if not isinstance(operator, FrobeniusOperator):
        raise TypeError("operator must be a FrobeniusOperator")
    operator.verify()
    intervals, segments, multiplicities, ambiguous = _polygon_data(
        operator.linearized_matrix,
        operator.semilinear_period,
    )
    if ambiguous:
        return _unknown(
            "padic.slopes",
            "ambiguous-newton-polygon",
            "finite precision does not determine every Newton-polygon vertex",
            requested={
                "ambiguous_indices": list(ambiguous),
                "operator_id": operator.operator_id,
                "valuation_intervals": [item.to_canonical_data() for item in intervals],
            },
        )
    decomposition = SlopeDecomposition(
        operator,
        intervals,
        segments,
        multiplicities,
        projectors,
    )
    from .results import certified_result

    return certified_result(decomposition, "slope-decomposition")


def ordinary_part(
    source: FrobeniusOperator | SlopeDecomposition,
    *,
    projector: SlopeProjector | None = None,
) -> PAdicResult[SlopeProjector]:
    """Return only an explicitly checked saturated slope-zero summand."""

    if isinstance(source, FrobeniusOperator):
        source.verify()
        intervals, segments, multiplicities, ambiguous = _polygon_data(
            source.linearized_matrix,
            source.semilinear_period,
        )
        if ambiguous:
            return _unknown(
                "padic.ordinary_part",
                "ambiguous-newton-polygon",
                "finite precision does not determine the slope-zero multiplicity",
                requested={
                    "ambiguous_indices": list(ambiguous),
                    "operator_id": source.operator_id,
                },
            )
        decomposition = SlopeDecomposition(
            source,
            intervals,
            segments,
            multiplicities,
            (),
        )
    elif isinstance(source, SlopeDecomposition):
        source.verify()
        decomposition = source
    else:
        raise TypeError("source must be a FrobeniusOperator or SlopeDecomposition")
    selected = projector
    if selected is None:
        matches = tuple(item for item in decomposition.projectors if item.slope == 0)
        selected = matches[0] if len(matches) == 1 else None
    if selected is None:
        return _unknown(
            "padic.ordinary_part",
            "missing-saturated-projector",
            "Newton multiplicities do not construct a saturated ordinary summand",
            requested={"operator_id": decomposition.operator.operator_id},
        )
    if selected.operator != decomposition.operator or selected.slope != 0:
        raise PAdicValidationError("ordinary projector is foreign or has nonzero slope")
    zero_multiplicity = next(
        (item.multiplicity for item in decomposition.multiplicities if item.slope == 0),
        0,
    )
    if selected.rank != zero_multiplicity:
        raise PAdicVerificationError("ordinary projector does not exhaust slope zero")
    selected.verify()
    from .results import certified_result

    return certified_result(selected, "ordinary-part")


def _register_payload_verifiers() -> None:
    from .certificate import padic_payload_verifier, replay_schema_payload

    @padic_payload_verifier("frobenius")
    def replay_frobenius(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        return replay_schema_payload(
            payload,
            evidence,
            decoder=_decode_operator_document,
            checks=(
                "exact local field, precision ring, module, and sigma reconstructed",
                "semilinear F^f matrix and characteristic polynomial recomputed",
                "finite coefficient valuation intervals replayed",
            ),
        )

    @padic_payload_verifier("slope-decomposition")
    def replay_slopes(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        return replay_schema_payload(
            payload,
            evidence,
            decoder=_decode_decomposition_document,
            checks=(
                "linearized Frobenius Newton polygon recomputed",
                "slopes normalized by the exact semilinear period",
                "all supplied saturated projectors replayed",
            ),
        )

    @padic_payload_verifier("ordinary-part")
    def replay_ordinary(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        return replay_schema_payload(
            payload,
            evidence,
            decoder=_decode_ordinary_document,
            checks=(
                "slope-zero projector identity and Frobenius stability replayed",
                "saturated direct-summand submodule reconstructed from basis columns",
                "ordinary rank matched the complete slope-zero multiplicity",
            ),
        )


_register_payload_verifiers()


__all__ = [
    "FrobeniusConvention",
    "FrobeniusOperator",
    "NewtonSegment",
    "SlopeDecomposition",
    "SlopeMultiplicity",
    "SlopeProjector",
    "ValuationInterval",
    "frobenius",
    "ordinary_part",
    "slopes",
]
