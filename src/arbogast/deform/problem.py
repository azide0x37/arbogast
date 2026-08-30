"""Finite deformation problems and their exact cohomological spaces."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias, cast

from arbogast.core import CanonicalJSON, CanonicalObject
from arbogast.formats import (
    DEFORM_GAUGE_SPACE_SCHEMA_V1,
    DEFORM_NONRIGID_SCHEMA_V1,
    DEFORM_OBSTRUCTION_CLASS_SCHEMA_V1,
    DEFORM_OBSTRUCTION_SPACE_SCHEMA_V1,
    DEFORM_PRESENTATION_SCHEMA_V1,
    DEFORM_PROBLEM_SCHEMA_V1,
    DEFORM_RIGID_SCHEMA_V1,
    DEFORM_TANGENT_SPACE_SCHEMA_V1,
)
from arbogast.linalg import (
    LinearSubspace,
    PrimeField,
    QuotientSpace,
    Scalar,
    Vector,
    image,
    nullspace,
    quotient_space,
)

from ._schema import (
    DeformationSchemaObject,
    DeformationSemanticObject,
    _canonical_linear_subspace,
    _canonical_quotient_space,
    _canonical_vector,
)
from .complex import DeformationComplex
from .errors import DeformationError, DeformationVerificationError

if TYPE_CHECKING:
    from .equivariant import InvariantDeformations


def _optional_label(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DeformationError(f"{name} must be a non-empty string or None")
    return unicodedata.normalize("NFC", value.strip())


def _source_id(value: str | None, complex_: DeformationComplex) -> str:
    if value is None:
        return complex_.content_id
    normalized = _optional_label(value, "source_id")
    assert normalized is not None
    return normalized


@dataclass(frozen=True, slots=True, init=False)
class DeformationPresentation(DeformationSchemaObject):
    """A three-term complex bound to one explicitly pinned source."""

    complex: DeformationComplex
    source_id: str
    name: str | None

    schema_version = DEFORM_PRESENTATION_SCHEMA_V1

    def __init__(
        self,
        complex: DeformationComplex,
        *,
        source_id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(complex, DeformationComplex):
            raise TypeError("complex must be a DeformationComplex")
        complex.verify()
        object.__setattr__(self, "complex", complex)
        object.__setattr__(self, "source_id", _source_id(source_id, complex))
        object.__setattr__(self, "name", _optional_label(name, "presentation name"))
        self.verify()

    def verify(self) -> bool:
        if not isinstance(self.complex, DeformationComplex):
            raise DeformationVerificationError("presentation complex has the wrong type")
        self.complex.verify()
        if _source_id(self.source_id, self.complex) != self.source_id:
            raise DeformationVerificationError("presentation source binding was altered")
        if _optional_label(self.name, "presentation name") != self.name:
            raise DeformationVerificationError("presentation name was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "complex": self.complex.to_canonical_data(),
            "name": self.name,
            "source_id": self.source_id,
            "type": "arbogast.deform.presentation",
        }


@dataclass(frozen=True, slots=True, init=False)
class DeformationProblem(DeformationSemanticObject):
    """A pinned deformation presentation, optionally with exact framing."""

    presentation: DeformationPresentation
    complex: DeformationComplex
    framing: object | None

    schema_version = DEFORM_PROBLEM_SCHEMA_V1

    def __init__(
        self,
        source: DeformationComplex | DeformationPresentation,
        framing: object | None = None,
        *,
        source_id: str | None = None,
        name: str | None = None,
    ) -> None:
        if isinstance(source, DeformationComplex):
            presentation = DeformationPresentation(source, source_id=source_id, name=name)
        elif isinstance(source, DeformationPresentation):
            if source_id is not None or name is not None:
                raise DeformationError(
                    "source_id/name cannot replace a pinned DeformationPresentation"
                )
            presentation = source
        else:
            raise TypeError("source must be a DeformationComplex or DeformationPresentation")
        effective = presentation.complex
        if framing is not None:
            from .framing import Framing

            if not isinstance(framing, Framing):
                raise TypeError("framing must be a Framing")
            effective = framing.restrict(presentation.complex)
        object.__setattr__(self, "presentation", presentation)
        object.__setattr__(self, "complex", effective)
        object.__setattr__(self, "framing", framing)
        self.verify()

    @property
    def field(self) -> PrimeField:
        return self.complex.field

    @property
    def source_id(self) -> str:
        return self.presentation.source_id

    @property
    def name(self) -> str | None:
        return self.presentation.name

    def verify(self) -> bool:
        if not isinstance(self.presentation, DeformationPresentation):
            raise DeformationVerificationError("problem presentation has the wrong type")
        if not isinstance(self.complex, DeformationComplex):
            raise DeformationVerificationError("problem complex has the wrong type")
        self.presentation.verify()
        expected = self.presentation.complex
        if self.framing is not None:
            from .framing import Framing

            if not isinstance(self.framing, Framing):
                raise DeformationVerificationError("problem framing has the wrong type")
            expected = self.framing.restrict(self.presentation.complex)
        if self.complex != expected:
            raise DeformationVerificationError("effective deformation complex was altered")
        self.complex.verify()
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        framing_data: CanonicalJSON = None
        if self.framing is not None:
            framing_data = cast(CanonicalObject, self.framing).to_canonical_data()
        return {
            "effective_complex": self.complex.to_canonical_data(),
            "framing": framing_data,
            "presentation": self.presentation.to_canonical_data(),
            "type": "arbogast.deform.problem",
        }


def deformation_problem(
    source: (
        DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
    ),
    framing: object | None = None,
    *,
    source_id: str | None = None,
    name: str | None = None,
) -> DeformationProblem:
    """Normalize a pinned complex/presentation into a deformation problem."""

    from .equivariant import InvariantDeformations

    if isinstance(source, InvariantDeformations):
        source.verify()
        return deformation_problem(
            source.problem,
            framing,
            source_id=source_id,
            name=name,
        )
    if isinstance(source, DeformationProblem):
        if framing is None and source_id is None and name is None:
            source.verify()
            return source
        if source.framing is not None:
            raise DeformationError("an already framed problem cannot be framed again implicitly")
        if source_id is not None or name is not None:
            raise DeformationError("a pinned DeformationProblem cannot be rebound")
        return DeformationProblem(source.presentation, framing)
    return DeformationProblem(source, framing, source_id=source_id, name=name)


def _problem(
    source: (
        DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
    ),
) -> DeformationProblem:
    return deformation_problem(source)


@dataclass(frozen=True, slots=True, init=False)
class GaugeSpace(DeformationSemanticObject):
    """The exact infinitesimal gauge space ``H^0 = ker(d0)``."""

    problem: DeformationProblem
    space: LinearSubspace

    schema_version = DEFORM_GAUGE_SPACE_SCHEMA_V1

    def __init__(self, problem: DeformationProblem, space: LinearSubspace) -> None:
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "space", space)
        self.verify()

    @property
    def field(self) -> PrimeField:
        return self.space.field

    @property
    def dimension(self) -> int:
        return self.space.dimension

    @property
    def basis(self) -> tuple[Vector, ...]:
        return self.space.basis

    def verify(self) -> bool:
        if not isinstance(self.problem, DeformationProblem):
            raise DeformationVerificationError("gauge problem has the wrong type")
        self.problem.verify()
        if not _canonical_linear_subspace(
            self.space,
            field=self.problem.field,
            ambient_dimension=self.problem.complex.degree0_dimension,
        ):
            raise DeformationVerificationError("gauge space is not canonical")
        expected = nullspace(self.problem.complex.d0)
        if self.space != expected:
            raise DeformationVerificationError("gauge space is not ker(d0)")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "complex_id": self.problem.complex.content_id,
            "problem_id": self.problem.content_id,
            "space": self.space.to_canonical_data(),
            "type": "arbogast.deform.gauge_space",
        }


@dataclass(frozen=True, slots=True, init=False)
class TangentSpace(DeformationSemanticObject):
    """The exact tangent quotient ``H^1 = ker(d1) / im(d0)``."""

    problem: DeformationProblem
    quotient: QuotientSpace

    schema_version = DEFORM_TANGENT_SPACE_SCHEMA_V1

    def __init__(self, problem: DeformationProblem, quotient: QuotientSpace) -> None:
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "quotient", quotient)
        self.verify()

    @property
    def field(self) -> PrimeField:
        return self.quotient.field

    @property
    def dimension(self) -> int:
        return self.quotient.dimension

    @property
    def basis(self) -> tuple[Vector, ...]:
        return self.quotient.basis

    def class_coordinates(self, cocycle: Iterable[Scalar]) -> Vector:
        return self.quotient.class_coordinates(cocycle)

    def representative(self, coordinates: Iterable[Scalar]) -> Vector:
        return self.quotient.representative(coordinates)

    def verify(self) -> bool:
        if not isinstance(self.problem, DeformationProblem):
            raise DeformationVerificationError("tangent problem has the wrong type")
        self.problem.verify()
        if not _canonical_quotient_space(self.quotient, field=self.problem.field):
            raise DeformationVerificationError("tangent quotient is not canonical")
        expected = quotient_space(
            nullspace(self.problem.complex.d1),
            image(self.problem.complex.d0),
        )
        if self.quotient != expected or not self.quotient.verify():
            raise DeformationVerificationError("tangent quotient is not ker(d1)/im(d0)")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "complex_id": self.problem.complex.content_id,
            "problem_id": self.problem.content_id,
            "quotient": self.quotient.to_canonical_data(),
            "type": "arbogast.deform.tangent_space",
        }


@dataclass(frozen=True, slots=True, init=False)
class ObstructionSpace(DeformationSemanticObject):
    """The exact obstruction quotient ``H^2 = C2 / im(d1)``."""

    problem: DeformationProblem
    quotient: QuotientSpace

    schema_version = DEFORM_OBSTRUCTION_SPACE_SCHEMA_V1

    def __init__(self, problem: DeformationProblem, quotient: QuotientSpace) -> None:
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "quotient", quotient)
        self.verify()

    @property
    def field(self) -> PrimeField:
        return self.quotient.field

    @property
    def dimension(self) -> int:
        return self.quotient.dimension

    @property
    def basis(self) -> tuple[Vector, ...]:
        return self.quotient.basis

    def class_of(self, vector: Iterable[Scalar]) -> ObstructionClass:
        return ObstructionClass(self, vector)

    def verify(self) -> bool:
        if not isinstance(self.problem, DeformationProblem):
            raise DeformationVerificationError("obstruction problem has the wrong type")
        self.problem.verify()
        if not _canonical_quotient_space(self.quotient, field=self.problem.field):
            raise DeformationVerificationError("obstruction quotient is not canonical")
        complex_ = self.problem.complex
        expected = quotient_space(
            LinearSubspace.full(complex_.field, complex_.degree2_dimension),
            image(complex_.d1),
        )
        if self.quotient != expected or not self.quotient.verify():
            raise DeformationVerificationError("obstruction quotient is not coker(d1)")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "complex_id": self.problem.complex.content_id,
            "problem_id": self.problem.content_id,
            "quotient": self.quotient.to_canonical_data(),
            "type": "arbogast.deform.obstruction_space",
        }


@dataclass(frozen=True, slots=True, init=False)
class ObstructionClass(DeformationSemanticObject):
    """One exact class in a pinned obstruction quotient."""

    space: ObstructionSpace
    ambient_vector: Vector
    class_coordinates: Vector

    schema_version = DEFORM_OBSTRUCTION_CLASS_SCHEMA_V1

    def __init__(self, space: ObstructionSpace, vector: Iterable[Scalar]) -> None:
        if not isinstance(space, ObstructionSpace):
            raise TypeError("space must be an ObstructionSpace")
        raw = tuple(space.field.residue(value) for value in vector)
        if len(raw) != space.quotient.ambient_dimension:
            raise DeformationError("obstruction vector has the wrong dimension")
        coordinates = space.quotient.class_coordinates(raw)
        representative = space.quotient.representative(coordinates)
        object.__setattr__(self, "space", space)
        object.__setattr__(self, "ambient_vector", representative)
        object.__setattr__(self, "class_coordinates", coordinates)
        self.verify()

    @property
    def is_zero(self) -> bool:
        return not any(self.class_coordinates)

    def verify(self) -> bool:
        if not isinstance(self.space, ObstructionSpace):
            raise DeformationVerificationError("obstruction class space has the wrong type")
        self.space.verify()
        if not _canonical_vector(
            self.space.field,
            self.ambient_vector,
            length=self.space.quotient.ambient_dimension,
        ) or not _canonical_vector(
            self.space.field,
            self.class_coordinates,
            length=self.space.dimension,
        ):
            raise DeformationVerificationError(
                "obstruction class contains noncanonical field coordinates"
            )
        if self.space.quotient.class_coordinates(self.ambient_vector) != self.class_coordinates:
            raise DeformationVerificationError("obstruction class coordinates were altered")
        if self.space.quotient.representative(self.class_coordinates) != self.ambient_vector:
            raise DeformationVerificationError("obstruction class representative is not canonical")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "ambient_vector": list(self.ambient_vector),
            "class_coordinates": list(self.class_coordinates),
            "is_zero": self.is_zero,
            "space_id": self.space.content_id,
            "type": "arbogast.deform.obstruction_class",
        }


def gauge(
    source: (
        DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
    ),
) -> GaugeSpace:
    problem = _problem(source)
    return GaugeSpace(problem, nullspace(problem.complex.d0))


def tangent(
    source: (
        DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
    ),
) -> TangentSpace:
    problem = _problem(source)
    return TangentSpace(
        problem,
        quotient_space(nullspace(problem.complex.d1), image(problem.complex.d0)),
    )


def obstructions(
    source: (
        DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
    ),
) -> ObstructionSpace:
    problem = _problem(source)
    complex_ = problem.complex
    return ObstructionSpace(
        problem,
        quotient_space(
            LinearSubspace.full(complex_.field, complex_.degree2_dimension),
            image(complex_.d1),
        ),
    )


@dataclass(frozen=True, slots=True, init=False)
class Rigid(DeformationSemanticObject):
    """A scoped proof that the pinned problem has zero tangent space."""

    problem: DeformationProblem
    tangent_space: TangentSpace

    schema_version = DEFORM_RIGID_SCHEMA_V1

    def __init__(self, problem: DeformationProblem, tangent_space: TangentSpace) -> None:
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "tangent_space", tangent_space)
        self.verify()

    @property
    def is_rigid(self) -> bool:
        return True

    def verify(self) -> bool:
        if not isinstance(self.problem, DeformationProblem) or not isinstance(
            self.tangent_space,
            TangentSpace,
        ):
            raise DeformationVerificationError("rigid result dependencies have the wrong type")
        expected = tangent(self.problem)
        if self.tangent_space != expected or expected.dimension != 0:
            raise DeformationVerificationError("rigid result has a nonzero tangent space")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "problem_id": self.problem.content_id,
            "tangent_id": self.tangent_space.content_id,
            "type": "arbogast.deform.rigid",
        }


@dataclass(frozen=True, slots=True, init=False)
class NonRigid(DeformationSemanticObject):
    """A literal nonzero tangent class witnessing infinitesimal non-rigidity."""

    problem: DeformationProblem
    tangent_space: TangentSpace
    witness: Vector

    schema_version = DEFORM_NONRIGID_SCHEMA_V1

    def __init__(
        self,
        problem: DeformationProblem,
        tangent_space: TangentSpace,
        witness: Iterable[Scalar],
    ) -> None:
        normalized = tuple(problem.field.residue(value) for value in witness)
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "tangent_space", tangent_space)
        object.__setattr__(self, "witness", normalized)
        self.verify()

    @property
    def is_rigid(self) -> bool:
        return False

    def verify(self) -> bool:
        if not isinstance(self.problem, DeformationProblem) or not isinstance(
            self.tangent_space,
            TangentSpace,
        ):
            raise DeformationVerificationError("nonrigid result dependencies have the wrong type")
        expected = tangent(self.problem)
        if self.tangent_space != expected or expected.dimension == 0:
            raise DeformationVerificationError("nonrigid result lacks a tangent direction")
        if not (
            isinstance(self.witness, tuple)
            and len(self.witness) == self.problem.complex.degree1_dimension
            and all(
                type(value) is int and 0 <= value < self.problem.field.p for value in self.witness
            )
        ):
            raise DeformationVerificationError(
                "nonrigidity witness has the wrong dimension or noncanonical residues"
            )
        if not any(expected.class_coordinates(self.witness)):
            raise DeformationVerificationError("nonrigidity witness represents the zero class")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "problem_id": self.problem.content_id,
            "tangent_id": self.tangent_space.content_id,
            "type": "arbogast.deform.nonrigid",
            "witness": list(self.witness),
        }


RigidityResult: TypeAlias = Rigid | NonRigid


def rigid(
    source: (
        DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
    ),
) -> RigidityResult:
    problem = _problem(source)
    tangent_space = tangent(problem)
    if tangent_space.dimension == 0:
        return Rigid(problem, tangent_space)
    return NonRigid(problem, tangent_space, tangent_space.basis[0])


__all__ = [
    "DeformationPresentation",
    "DeformationProblem",
    "GaugeSpace",
    "NonRigid",
    "ObstructionClass",
    "ObstructionSpace",
    "Rigid",
    "RigidityResult",
    "TangentSpace",
    "deformation_problem",
    "gauge",
    "obstructions",
    "rigid",
    "tangent",
]
