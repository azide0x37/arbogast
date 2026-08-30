"""Exact affine lifting across pinned small extensions."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeAlias

from arbogast.core import CanonicalJSON
from arbogast.formats import (
    DEFORM_CONTRACTION_CERTIFICATE_SCHEMA_V1,
    DEFORM_FIXED_LIFT_SCHEMA_V1,
    DEFORM_LIFT_DATUM_SCHEMA_V1,
    DEFORM_LIFT_ENDOMORPHISM_SCHEMA_V1,
    DEFORM_LIFT_FAMILY_SCHEMA_V1,
    DEFORM_LIFT_OBSTRUCTED_SCHEMA_V1,
    DEFORM_LIFT_UNKNOWN_SCHEMA_V1,
    DEFORM_NONUNIQUE_LIFT_SCHEMA_V1,
    DEFORM_UNIQUE_LIFT_SCHEMA_V1,
)
from arbogast.linalg import (
    DenseMatrix,
    LinearSubspace,
    PrimeField,
    QuotientSpace,
    Scalar,
    Vector,
    image,
    quotient_space,
    solve,
)

from ._schema import (
    MAX_DIMENSION,
    DeformationSemanticObject,
    _canonical_dense_matrix,
    _canonical_linear_subspace,
    _canonical_quotient_space,
    _canonical_vector,
)
from .complex import DeformationComplex
from .equivariant import InvariantDeformations
from .errors import (
    DeformationError,
    DeformationVerificationError,
    UnsupportedDeformation,
    UnsupportedDeformationOperation,
)
from .problem import (
    DeformationPresentation,
    DeformationProblem,
    ObstructionClass,
    deformation_problem,
    obstructions,
)
from .rings import SmallExtension

ProblemSource: TypeAlias = (
    DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
)


def _label(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DeformationError(f"{name} must be a non-empty string or None")
    return unicodedata.normalize("NFC", value.strip())


def _vector(
    field: PrimeField,
    values: Iterable[Scalar],
    length: int,
    name: str,
) -> Vector:
    result = tuple(field.residue(value) for value in values)
    if len(result) != length:
        raise DeformationError(f"{name} has length {len(result)}, expected {length}")
    return result


def _add(left: Vector, right: Vector, prime: int) -> Vector:
    return tuple((a + b) % prime for a, b in zip(left, right, strict=True))


def _sub(left: Vector, right: Vector, prime: int) -> Vector:
    return tuple((a - b) % prime for a, b in zip(left, right, strict=True))


def _is_canonical_vector(values: object, length: int, prime: int) -> bool:
    return (
        isinstance(values, tuple)
        and len(values) == length
        and all(type(value) is int and 0 <= value < prime for value in values)
    )


def _matrix_power(matrix: DenseMatrix, exponent: int) -> DenseMatrix:
    if isinstance(exponent, bool) or not isinstance(exponent, int):
        raise TypeError("contraction exponent must be an integer")
    if exponent < 0:
        raise DeformationError("contraction exponent must be nonnegative")
    if exponent > MAX_DIMENSION:
        raise DeformationError("contraction exponent exceeds the portable bound")
    if matrix.nrows != matrix.ncols:
        raise DeformationError("matrix powers require a square matrix")
    result = DenseMatrix.identity(matrix.field, matrix.nrows)
    base = matrix
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = result @ base
        base = base @ base
        remaining >>= 1
    return result


@dataclass(frozen=True, slots=True, init=False)
class LiftDatum(DeformationSemanticObject):
    """A complete finite affine correction equation over a small extension."""

    problem: DeformationProblem
    extension: SmallExtension
    target: Vector
    base_point: Vector
    correction_matrix: DenseMatrix
    gauge_matrix: DenseMatrix
    label: str | None

    schema_version = DEFORM_LIFT_DATUM_SCHEMA_V1

    def __init__(
        self,
        problem: ProblemSource,
        extension: SmallExtension,
        target: Iterable[Scalar],
        *,
        base_point: Iterable[Scalar] | None = None,
        correction_matrix: DenseMatrix | None = None,
        gauge_matrix: DenseMatrix | None = None,
        label: str | None = None,
    ) -> None:
        normalized_problem = deformation_problem(problem)
        if not isinstance(extension, SmallExtension):
            raise TypeError("extension must be a SmallExtension")
        extension.verify()
        if extension.domain.field != normalized_problem.field:
            raise DeformationError("small extension and deformation problem use different fields")
        if extension.kernel_dimension != 1 and (correction_matrix is None or gauge_matrix is None):
            raise UnsupportedDeformationOperation(
                "automatic correction_matrix=d1 and gauge_matrix=d0 require a "
                "one-dimensional square-zero kernel; higher-dimensional kernels need "
                "both matrices as an explicit supplied correction chart"
            )
        matrix = normalized_problem.complex.d1 if correction_matrix is None else correction_matrix
        if not isinstance(matrix, DenseMatrix):
            raise TypeError("correction_matrix must be a DenseMatrix")
        if matrix.field != normalized_problem.field:
            raise DeformationError("correction matrix uses the wrong field")
        normalized_target = _vector(
            normalized_problem.field,
            target,
            matrix.nrows,
            "lift target",
        )
        normalized_base = _vector(
            normalized_problem.field,
            (0,) * matrix.ncols if base_point is None else base_point,
            matrix.ncols,
            "base point",
        )
        if gauge_matrix is None:
            if matrix.ncols == normalized_problem.complex.degree1_dimension:
                gauge = normalized_problem.complex.d0
            else:
                gauge = DenseMatrix.zeros(normalized_problem.field, matrix.ncols, 0)
        else:
            gauge = gauge_matrix
        if not isinstance(gauge, DenseMatrix):
            raise TypeError("gauge_matrix must be a DenseMatrix")
        if gauge.field != normalized_problem.field or gauge.nrows != matrix.ncols:
            raise DeformationError("gauge matrix has the wrong field or correction dimension")
        if matrix @ gauge != DenseMatrix.zeros(
            normalized_problem.field,
            matrix.nrows,
            gauge.ncols,
        ):
            raise DeformationError("gauge corrections are not homogeneous lift directions")
        object.__setattr__(self, "problem", normalized_problem)
        object.__setattr__(self, "extension", extension)
        object.__setattr__(self, "target", normalized_target)
        object.__setattr__(self, "base_point", normalized_base)
        object.__setattr__(self, "correction_matrix", matrix)
        object.__setattr__(self, "gauge_matrix", gauge)
        object.__setattr__(self, "label", _label(label, "lift label"))
        self.verify()

    @property
    def field(self) -> PrimeField:
        return self.problem.field

    @property
    def correction_dimension(self) -> int:
        return self.correction_matrix.ncols

    def verify(self) -> bool:
        if not isinstance(self.problem, DeformationProblem):
            raise DeformationVerificationError("lift problem has the wrong type")
        if not isinstance(self.extension, SmallExtension):
            raise DeformationVerificationError("lift extension has the wrong type")
        self.problem.verify()
        self.extension.verify()
        if self.extension.domain.field != self.problem.field:
            raise DeformationVerificationError("lift extension coefficient field was altered")
        if not _canonical_dense_matrix(
            self.correction_matrix,
            field=self.problem.field,
        ):
            raise DeformationVerificationError("lift correction matrix was altered")
        if not _is_canonical_vector(
            self.target,
            self.correction_matrix.nrows,
            self.problem.field.p,
        ):
            raise DeformationVerificationError("lift target shape or residues were altered")
        if not _is_canonical_vector(
            self.base_point,
            self.correction_matrix.ncols,
            self.problem.field.p,
        ):
            raise DeformationVerificationError("lift base point shape or residues were altered")
        if (
            not _canonical_dense_matrix(
                self.gauge_matrix,
                field=self.problem.field,
            )
            or self.gauge_matrix.nrows != self.correction_matrix.ncols
        ):
            raise DeformationVerificationError("lift gauge matrix shape was altered")
        if self.correction_matrix @ self.gauge_matrix != DenseMatrix.zeros(
            self.problem.field,
            self.correction_matrix.nrows,
            self.gauge_matrix.ncols,
        ):
            raise DeformationVerificationError("lift gauge directions are not homogeneous")
        if _label(self.label, "lift label") != self.label:
            raise DeformationVerificationError("lift label normalization was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "base_point": list(self.base_point),
            "correction_matrix": self.correction_matrix.to_canonical_data(),
            "extension_id": self.extension.content_id,
            "gauge_matrix": self.gauge_matrix.to_canonical_data(),
            "label": self.label,
            "problem_id": self.problem.content_id,
            "target": list(self.target),
            "type": "arbogast.deform.lift_datum",
        }


@dataclass(frozen=True, slots=True, init=False)
class LiftFamily(DeformationSemanticObject):
    """The complete affine family of corrections, with gauge quotient."""

    datum: LiftDatum
    particular: Vector
    directions: LinearSubspace
    gauge_directions: LinearSubspace
    mod_gauge: QuotientSpace

    schema_version = DEFORM_LIFT_FAMILY_SCHEMA_V1

    def __init__(
        self,
        datum: LiftDatum,
        particular: Iterable[Scalar],
        directions: LinearSubspace,
        gauge_directions: LinearSubspace,
        mod_gauge: QuotientSpace,
    ) -> None:
        normalized = _vector(
            datum.problem.field,
            particular,
            datum.correction_dimension,
            "particular correction",
        )
        object.__setattr__(self, "datum", datum)
        object.__setattr__(self, "particular", normalized)
        object.__setattr__(self, "directions", directions)
        object.__setattr__(self, "gauge_directions", gauge_directions)
        object.__setattr__(self, "mod_gauge", mod_gauge)
        self.verify()

    @property
    def representative(self) -> Vector:
        return _add(
            self.datum.base_point,
            self.particular,
            self.datum.problem.field.p,
        )

    @property
    def dimension(self) -> int:
        return self.directions.dimension

    @property
    def mod_gauge_dimension(self) -> int:
        return self.mod_gauge.dimension

    def contains(self, point: Iterable[Scalar]) -> bool:
        normalized = _vector(
            self.datum.problem.field,
            point,
            self.datum.correction_dimension,
            "lift point",
        )
        correction = _sub(
            normalized,
            self.datum.base_point,
            self.datum.problem.field.p,
        )
        return self.datum.correction_matrix.matvec(correction) == self.datum.target

    def verify(self) -> bool:
        if not isinstance(self.datum, LiftDatum):
            raise DeformationVerificationError("lift family datum has the wrong type")
        self.datum.verify()
        field = self.datum.problem.field
        dimension = self.datum.correction_dimension
        if not _canonical_vector(field, self.particular, length=dimension):
            raise DeformationVerificationError("particular lift correction is not canonical")
        if not _canonical_linear_subspace(
            self.directions,
            field=field,
            ambient_dimension=dimension,
        ) or not _canonical_linear_subspace(
            self.gauge_directions,
            field=field,
            ambient_dimension=dimension,
        ):
            raise DeformationVerificationError("lift direction spaces are not canonical")
        if not _canonical_quotient_space(self.mod_gauge, field=field):
            raise DeformationVerificationError("lift gauge quotient is not canonical")
        solution = solve(self.datum.correction_matrix, self.datum.target)
        if not solution.consistent or solution.particular is None:
            raise DeformationVerificationError("lift family is attached to an inconsistent datum")
        expected_gauge = image(self.datum.gauge_matrix)
        expected_quotient = quotient_space(solution.kernel, expected_gauge)
        if self.particular != solution.particular:
            raise DeformationVerificationError("particular lift correction was altered")
        if self.directions != solution.kernel:
            raise DeformationVerificationError("lift direction space was altered")
        if self.gauge_directions != expected_gauge:
            raise DeformationVerificationError("lift gauge directions were altered")
        if self.mod_gauge != expected_quotient or not self.mod_gauge.verify():
            raise DeformationVerificationError("lift gauge quotient was altered")
        if not self.contains(self.representative):
            raise DeformationVerificationError("lift representative does not solve the datum")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "datum_id": self.datum.content_id,
            "directions": self.directions.to_canonical_data(),
            "gauge_directions": self.gauge_directions.to_canonical_data(),
            "mod_gauge": self.mod_gauge.to_canonical_data(),
            "particular": list(self.particular),
            "representative": list(self.representative),
            "type": "arbogast.deform.lift_family",
        }


@dataclass(frozen=True, slots=True, init=False)
class LiftObstructed(DeformationSemanticObject):
    """A literal left-nullspace separator proving the lift equation inconsistent."""

    datum: LiftDatum
    separating_witness: Vector
    obstruction_class: ObstructionClass | None

    schema_version = DEFORM_LIFT_OBSTRUCTED_SCHEMA_V1

    def __init__(
        self,
        datum: LiftDatum,
        separating_witness: Iterable[Scalar],
        obstruction_class: ObstructionClass | None,
    ) -> None:
        witness = _vector(
            datum.problem.field,
            separating_witness,
            datum.correction_matrix.nrows,
            "separating witness",
        )
        object.__setattr__(self, "datum", datum)
        object.__setattr__(self, "separating_witness", witness)
        object.__setattr__(self, "obstruction_class", obstruction_class)
        self.verify()

    def verify(self) -> bool:
        if not isinstance(self.datum, LiftDatum):
            raise DeformationVerificationError("obstructed lift datum has the wrong type")
        self.datum.verify()
        if not _canonical_vector(
            self.datum.problem.field,
            self.separating_witness,
            length=self.datum.correction_matrix.nrows,
        ):
            raise DeformationVerificationError("lift separator is not canonical")
        if self.obstruction_class is not None and not isinstance(
            self.obstruction_class,
            ObstructionClass,
        ):
            raise DeformationVerificationError("lift obstruction class has the wrong type")
        solution = solve(self.datum.correction_matrix, self.datum.target)
        if solution.consistent or solution.inconsistency_witness is None:
            raise DeformationVerificationError("obstructed result has a consistent lift equation")
        if self.separating_witness != solution.inconsistency_witness:
            raise DeformationVerificationError("lift separator was altered")
        if self.obstruction_class is not None:
            expected = obstructions(self.datum.problem).class_of(self.datum.target)
            if self.datum.correction_matrix != self.datum.problem.complex.d1:
                raise DeformationVerificationError(
                    "a nonstandard correction law cannot claim the problem obstruction class"
                )
            if self.obstruction_class != expected or expected.is_zero:
                raise DeformationVerificationError("lift obstruction class was altered or zero")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "datum_id": self.datum.content_id,
            "obstruction_class": (
                None
                if self.obstruction_class is None
                else self.obstruction_class.to_canonical_data()
            ),
            "separating_witness": list(self.separating_witness),
            "type": "arbogast.deform.lift_obstructed",
        }


@dataclass(frozen=True, slots=True, init=False)
class LiftUnknown(DeformationSemanticObject):
    """An explicit non-conclusion when required lift evidence is unavailable."""

    datum: LiftDatum | None
    reason: str

    schema_version = DEFORM_LIFT_UNKNOWN_SCHEMA_V1

    def __init__(self, datum: LiftDatum | None, reason: str) -> None:
        normalized = _label(reason, "unknown reason")
        assert normalized is not None
        object.__setattr__(self, "datum", datum)
        object.__setattr__(self, "reason", normalized)
        self.verify()

    def verify(self) -> bool:
        if self.datum is not None and not isinstance(self.datum, LiftDatum):
            raise DeformationVerificationError("unknown lift datum has the wrong type")
        if isinstance(self.datum, LiftDatum):
            self.datum.verify()
        if _label(self.reason, "unknown reason") != self.reason:
            raise DeformationVerificationError("unknown lift reason was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "datum_id": None if self.datum is None else self.datum.content_id,
            "reason": self.reason,
            "type": "arbogast.deform.lift_unknown",
        }


LiftResult: TypeAlias = LiftFamily | LiftObstructed | LiftUnknown | UnsupportedDeformation


def _lift_datum_from_call(
    source: LiftDatum | ProblemSource,
    extension: SmallExtension | None,
    *,
    target: Iterable[Scalar] | None,
    base_point: Iterable[Scalar] | None,
    correction_matrix: DenseMatrix | None,
    gauge_matrix: DenseMatrix | None,
    label: str | None,
) -> LiftDatum | UnsupportedDeformation:
    if isinstance(source, LiftDatum):
        if extension is not None or any(
            value is not None
            for value in (target, base_point, correction_matrix, gauge_matrix, label)
        ):
            raise DeformationError("a pinned LiftDatum cannot be combined with chart arguments")
        return source
    if not isinstance(
        source,
        (DeformationComplex, DeformationPresentation, DeformationProblem, InvariantDeformations),
    ):
        raise TypeError("source must be a LiftDatum or deformation problem source")
    if not isinstance(extension, SmallExtension):
        raise TypeError("extension must be supplied with a deformation problem")
    problem = deformation_problem(source)
    if target is None:
        return UnsupportedDeformation(
            "lift",
            "the deformation problem and Artin extension do not determine an object-specific "
            "correction target",
            requested={
                "extension_id": extension.content_id,
                "problem_id": problem.content_id,
            },
            supported=("explicit LiftDatum", "target plus an exact correction chart"),
        )
    try:
        return LiftDatum(
            problem,
            extension,
            target,
            base_point=base_point,
            correction_matrix=correction_matrix,
            gauge_matrix=gauge_matrix,
            label=label,
        )
    except UnsupportedDeformationOperation as exc:
        return UnsupportedDeformation(
            "lift",
            str(exc),
            requested={
                "extension_id": extension.content_id,
                "kernel_dimension": extension.kernel_dimension,
                "problem_id": problem.content_id,
            },
            supported=("explicit correction_matrix and gauge_matrix",),
        )


def lift(
    source: LiftDatum | ProblemSource,
    extension: SmallExtension | None = None,
    *,
    target: Iterable[Scalar] | None = None,
    base_point: Iterable[Scalar] | None = None,
    correction_matrix: DenseMatrix | None = None,
    gauge_matrix: DenseMatrix | None = None,
    label: str | None = None,
) -> LiftResult:
    """Solve an explicit finite correction equation exactly.

    ``lift(problem, extension)`` alone returns a typed refusal because a
    three-term complex does not determine an object-specific lift target.
    Supplying ``target`` (and, when needed, an explicit correction chart)
    constructs the corresponding :class:`LiftDatum` additively.
    """

    datum = _lift_datum_from_call(
        source,
        extension,
        target=target,
        base_point=base_point,
        correction_matrix=correction_matrix,
        gauge_matrix=gauge_matrix,
        label=label,
    )
    if isinstance(datum, UnsupportedDeformation):
        return datum
    datum.verify()
    solution = solve(datum.correction_matrix, datum.target)
    if solution.consistent:
        assert solution.particular is not None
        gauge_directions = image(datum.gauge_matrix)
        return LiftFamily(
            datum,
            solution.particular,
            solution.kernel,
            gauge_directions,
            quotient_space(solution.kernel, gauge_directions),
        )
    assert solution.inconsistency_witness is not None
    obstruction_class = None
    if datum.correction_matrix == datum.problem.complex.d1:
        obstruction_class = obstructions(datum.problem).class_of(datum.target)
    return LiftObstructed(datum, solution.inconsistency_witness, obstruction_class)


@dataclass(frozen=True, slots=True, init=False)
class UniqueLift(DeformationSemanticObject):
    """A unique lift modulo the explicitly pinned gauge directions."""

    family: LiftFamily
    representative: Vector

    schema_version = DEFORM_UNIQUE_LIFT_SCHEMA_V1

    def __init__(self, family: LiftFamily, representative: Iterable[Scalar]) -> None:
        normalized = _vector(
            family.datum.problem.field,
            representative,
            family.datum.correction_dimension,
            "unique lift representative",
        )
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "representative", normalized)
        self.verify()

    def verify(self) -> bool:
        if not isinstance(self.family, LiftFamily):
            raise DeformationVerificationError("unique lift family has the wrong type")
        self.family.verify()
        if not _canonical_vector(
            self.family.datum.problem.field,
            self.representative,
            length=self.family.datum.correction_dimension,
        ):
            raise DeformationVerificationError("unique lift representative is not canonical")
        if self.family.mod_gauge_dimension != 0:
            raise DeformationVerificationError("unique lift has nontrivial mod-gauge directions")
        if self.representative != self.family.representative:
            raise DeformationVerificationError("unique lift representative was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "family_id": self.family.content_id,
            "representative": list(self.representative),
            "type": "arbogast.deform.unique_lift",
        }


@dataclass(frozen=True, slots=True, init=False)
class NonUniqueLift(DeformationSemanticObject):
    """Two explicitly gauge-inequivalent lifts in the same affine family."""

    family: LiftFamily
    first: Vector
    second: Vector
    separating_class_coordinates: Vector

    schema_version = DEFORM_NONUNIQUE_LIFT_SCHEMA_V1

    def __init__(
        self,
        family: LiftFamily,
        first: Iterable[Scalar],
        second: Iterable[Scalar],
        separating_class_coordinates: Iterable[Scalar],
    ) -> None:
        field = family.datum.problem.field
        size = family.datum.correction_dimension
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "first", _vector(field, first, size, "first lift"))
        object.__setattr__(self, "second", _vector(field, second, size, "second lift"))
        object.__setattr__(
            self,
            "separating_class_coordinates",
            _vector(
                field,
                separating_class_coordinates,
                family.mod_gauge_dimension,
                "mod-gauge class coordinates",
            ),
        )
        self.verify()

    def verify(self) -> bool:
        if not isinstance(self.family, LiftFamily):
            raise DeformationVerificationError("nonunique lift family has the wrong type")
        self.family.verify()
        prime = self.family.datum.problem.field.p
        size = self.family.datum.correction_dimension
        if not _is_canonical_vector(self.first, size, prime) or not _is_canonical_vector(
            self.second,
            size,
            prime,
        ):
            raise DeformationVerificationError("nonunique lift vectors are not canonical")
        if not _is_canonical_vector(
            self.separating_class_coordinates,
            self.family.mod_gauge_dimension,
            prime,
        ):
            raise DeformationVerificationError("nonunique separating coordinates are not canonical")
        if self.family.mod_gauge_dimension == 0:
            raise DeformationVerificationError("nonunique lift has trivial mod-gauge directions")
        if not self.family.contains(self.first) or not self.family.contains(self.second):
            raise DeformationVerificationError("nonunique witnesses do not both solve the datum")
        difference = _sub(
            self.second,
            self.first,
            self.family.datum.problem.field.p,
        )
        coordinates = self.family.mod_gauge.class_coordinates(difference)
        if coordinates != self.separating_class_coordinates or not any(coordinates):
            raise DeformationVerificationError("nonunique lifts are not gauge-inequivalent")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "family_id": self.family.content_id,
            "first": list(self.first),
            "second": list(self.second),
            "separating_class_coordinates": list(self.separating_class_coordinates),
            "type": "arbogast.deform.nonunique_lift",
        }


UniqueLiftResult: TypeAlias = (
    UniqueLift | NonUniqueLift | LiftObstructed | LiftUnknown | UnsupportedDeformation
)


def unique_lift(
    source: LiftDatum | LiftResult | ProblemSource,
    extension: SmallExtension | None = None,
    *,
    target: Iterable[Scalar] | None = None,
    base_point: Iterable[Scalar] | None = None,
    correction_matrix: DenseMatrix | None = None,
    gauge_matrix: DenseMatrix | None = None,
    label: str | None = None,
) -> UniqueLiftResult:
    """Decide uniqueness modulo the datum's exact gauge image."""

    result: LiftResult
    if isinstance(source, (LiftFamily, LiftObstructed, LiftUnknown, UnsupportedDeformation)):
        if extension is not None or any(
            value is not None
            for value in (target, base_point, correction_matrix, gauge_matrix, label)
        ):
            raise DeformationError(
                "a completed lift result cannot be combined with chart arguments"
            )
        result = source
    else:
        result = lift(
            source,
            extension,
            target=target,
            base_point=base_point,
            correction_matrix=correction_matrix,
            gauge_matrix=gauge_matrix,
            label=label,
        )
    if isinstance(result, (LiftObstructed, LiftUnknown, UnsupportedDeformation)):
        result.verify()
        return result
    if not isinstance(result, LiftFamily):
        raise TypeError("source must be a LiftDatum or lift result")
    result.verify()
    if result.mod_gauge_dimension == 0:
        return UniqueLift(result, result.representative)
    direction = result.mod_gauge.basis[0]
    second = _add(result.representative, direction, result.datum.problem.field.p)
    return NonUniqueLift(
        result,
        result.representative,
        second,
        result.mod_gauge.class_coordinates(direction),
    )


@dataclass(frozen=True, slots=True, init=False)
class LiftEndomorphism(DeformationSemanticObject):
    """An affine self-map of one complete lift family."""

    family: LiftFamily
    linear: DenseMatrix
    translation: Vector

    schema_version = DEFORM_LIFT_ENDOMORPHISM_SCHEMA_V1

    def __init__(
        self,
        family: LiftFamily,
        linear: DenseMatrix,
        translation: Iterable[Scalar],
    ) -> None:
        if not isinstance(family, LiftFamily):
            raise TypeError("family must be a LiftFamily")
        if not isinstance(linear, DenseMatrix):
            raise TypeError("linear must be a DenseMatrix")
        size = family.datum.correction_dimension
        if linear.field != family.datum.problem.field or linear.shape != (size, size):
            raise DeformationError("lift endomorphism matrix has the wrong field or shape")
        normalized_translation = _vector(
            family.datum.problem.field,
            translation,
            size,
            "lift endomorphism translation",
        )
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "linear", linear)
        object.__setattr__(self, "translation", normalized_translation)
        self.verify()

    def apply(self, point: Iterable[Scalar]) -> Vector:
        normalized = _vector(
            self.family.datum.problem.field,
            point,
            self.family.datum.correction_dimension,
            "lift point",
        )
        return _add(
            self.linear.matvec(normalized),
            self.translation,
            self.family.datum.problem.field.p,
        )

    def verify(self) -> bool:
        if not isinstance(self.family, LiftFamily):
            raise DeformationVerificationError("lift endomorphism family has the wrong type")
        self.family.verify()
        size = self.family.datum.correction_dimension
        if not _canonical_dense_matrix(
            self.linear,
            field=self.family.datum.problem.field,
        ) or self.linear.shape != (size, size):
            raise DeformationVerificationError(
                "lift endomorphism matrix field or shape was altered"
            )
        if not _is_canonical_vector(
            self.translation,
            size,
            self.family.datum.problem.field.p,
        ):
            raise DeformationVerificationError("lift endomorphism translation is not canonical")
        if not self.family.contains(self.apply(self.family.representative)):
            raise DeformationVerificationError("endomorphism does not preserve the lift family")
        if any(
            not self.family.directions.contains(self.linear.matvec(direction))
            for direction in self.family.directions.basis
        ):
            raise DeformationVerificationError("endomorphism does not preserve lift directions")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "family_id": self.family.content_id,
            "linear": self.linear.to_canonical_data(),
            "translation": list(self.translation),
            "type": "arbogast.deform.lift_endomorphism",
        }


@dataclass(frozen=True, slots=True, init=False)
class ContractionCertificate(DeformationSemanticObject):
    """A checked exponent killing all differences inside a lift family."""

    endomorphism: LiftEndomorphism
    exponent: int

    schema_version = DEFORM_CONTRACTION_CERTIFICATE_SCHEMA_V1

    def __init__(self, endomorphism: LiftEndomorphism, exponent: int) -> None:
        if not isinstance(endomorphism, LiftEndomorphism):
            raise TypeError("endomorphism must be a LiftEndomorphism")
        if isinstance(exponent, bool) or not isinstance(exponent, int):
            raise TypeError("contraction exponent must be an integer")
        if exponent < 0:
            raise DeformationError("contraction exponent must be nonnegative")
        if exponent > MAX_DIMENSION:
            raise DeformationError("contraction exponent exceeds the portable bound")
        object.__setattr__(self, "endomorphism", endomorphism)
        object.__setattr__(self, "exponent", exponent)
        self.verify()

    def verify(self) -> bool:
        if not isinstance(self.endomorphism, LiftEndomorphism):
            raise DeformationVerificationError("contraction endomorphism has the wrong type")
        if type(self.exponent) is not int or self.exponent < 0 or self.exponent > MAX_DIMENSION:
            raise DeformationVerificationError("contraction exponent is outside the portable bound")
        self.endomorphism.verify()
        power = _matrix_power(self.endomorphism.linear, self.exponent)
        if any(
            any(power.matvec(direction)) for direction in self.endomorphism.family.directions.basis
        ):
            raise DeformationVerificationError(
                "claimed contraction exponent does not kill all lift differences"
            )
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "endomorphism_id": self.endomorphism.content_id,
            "exponent": self.exponent,
            "type": "arbogast.deform.contraction_certificate",
        }


@dataclass(frozen=True, slots=True, init=False)
class FixedLift(DeformationSemanticObject):
    """The explicit fixed point obtained from a contracting affine action."""

    family: LiftFamily
    endomorphism: LiftEndomorphism
    contraction: ContractionCertificate
    representative: Vector

    schema_version = DEFORM_FIXED_LIFT_SCHEMA_V1

    def __init__(
        self,
        family: LiftFamily,
        endomorphism: LiftEndomorphism,
        contraction: ContractionCertificate,
        representative: Iterable[Scalar],
    ) -> None:
        normalized = _vector(
            family.datum.problem.field,
            representative,
            family.datum.correction_dimension,
            "fixed lift",
        )
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "endomorphism", endomorphism)
        object.__setattr__(self, "contraction", contraction)
        object.__setattr__(self, "representative", normalized)
        self.verify()

    def verify(self) -> bool:
        if not isinstance(self.family, LiftFamily):
            raise DeformationVerificationError("fixed lift family has the wrong type")
        if not isinstance(self.endomorphism, LiftEndomorphism):
            raise DeformationVerificationError("fixed lift endomorphism has the wrong type")
        if not isinstance(self.contraction, ContractionCertificate):
            raise DeformationVerificationError("fixed lift contraction has the wrong type")
        self.family.verify()
        self.endomorphism.verify()
        self.contraction.verify()
        if self.endomorphism.family != self.family:
            raise DeformationVerificationError("fixed endomorphism belongs to another family")
        if self.contraction.endomorphism != self.endomorphism:
            raise DeformationVerificationError("fixed lift uses a different contraction")
        if not _canonical_vector(
            self.family.datum.problem.field,
            self.representative,
            length=self.family.datum.correction_dimension,
        ):
            raise DeformationVerificationError("fixed lift representative is not canonical")
        expected = self.family.representative
        for _ in range(self.contraction.exponent):
            expected = self.endomorphism.apply(expected)
        if self.representative != expected:
            raise DeformationVerificationError("fixed lift is not the contracted iterate")
        if not self.family.contains(self.representative):
            raise DeformationVerificationError("fixed lift is outside the affine family")
        if self.endomorphism.apply(self.representative) != self.representative:
            raise DeformationVerificationError("claimed fixed lift is not fixed")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "contraction_id": self.contraction.content_id,
            "endomorphism_id": self.endomorphism.content_id,
            "family_id": self.family.content_id,
            "representative": list(self.representative),
            "type": "arbogast.deform.fixed_lift",
        }


FixedLiftResult: TypeAlias = FixedLift | LiftObstructed | LiftUnknown | UnsupportedDeformation


def fixed_lift(
    source: LiftDatum | LiftResult,
    endomorphism: LiftEndomorphism | None = None,
    *,
    contraction: ContractionCertificate | None = None,
    exponent: int | None = None,
) -> FixedLiftResult:
    """Return the checked contracting fixed lift, or an explicit non-conclusion."""

    result = lift(source) if isinstance(source, LiftDatum) else source
    if isinstance(result, (LiftObstructed, LiftUnknown, UnsupportedDeformation)):
        result.verify()
        return result
    if not isinstance(result, LiftFamily):
        raise TypeError("source must be a LiftDatum or lift result")
    if endomorphism is None:
        return LiftUnknown(result.datum, "no lift-family endomorphism was supplied")
    if endomorphism.family != result:
        raise DeformationError("endomorphism is bound to a different lift family")
    if contraction is not None and exponent is not None:
        raise DeformationError("supply a contraction certificate or exponent, not both")
    if contraction is None:
        if exponent is None:
            return LiftUnknown(result.datum, "no contraction exponent was supplied")
        contraction = ContractionCertificate(endomorphism, exponent)
    elif contraction.endomorphism != endomorphism:
        raise DeformationError("contraction is bound to a different endomorphism")
    representative = result.representative
    for _ in range(contraction.exponent):
        representative = endomorphism.apply(representative)
    return FixedLift(result, endomorphism, contraction, representative)


__all__ = [
    "ContractionCertificate",
    "FixedLift",
    "FixedLiftResult",
    "LiftDatum",
    "LiftEndomorphism",
    "LiftFamily",
    "LiftObstructed",
    "LiftResult",
    "LiftUnknown",
    "NonUniqueLift",
    "UniqueLift",
    "UniqueLiftResult",
    "fixed_lift",
    "lift",
    "unique_lift",
]
