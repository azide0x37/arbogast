"""Exact finite actions, invariant subcomplexes, and supplied decompositions."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from inspect import Signature, signature
from typing import Any, TypeAlias

from arbogast.core import CanonicalJSON
from arbogast.formats import (
    DEFORM_ACTION_SCHEMA_V1,
    DEFORM_EQUIVARIANT_COMPONENT_SCHEMA_V1,
    DEFORM_EQUIVARIANT_DECOMPOSITION_SCHEMA_V1,
    DEFORM_EQUIVARIANT_SCHEMA_V1,
    DEFORM_INVARIANT_DEFORMATIONS_SCHEMA_V1,
)
from arbogast.linalg import DenseMatrix, LinearSubspace, PrimeField, image
from arbogast.rep import Representation

from ._schema import (
    MAX_DIMENSION,
    MAX_GROUP_ORDER,
    DeformationSchemaObject,
    DeformationSemanticObject,
    _canonical_dense_matrix,
    _canonical_linear_subspace,
)
from .complex import DeformationComplex
from .errors import (
    DeformationError,
    DeformationVerificationError,
    UnsupportedDeformation,
)
from .problem import (
    DeformationPresentation,
    DeformationProblem,
    deformation_problem,
)

ProjectorTriple: TypeAlias = tuple[DenseMatrix, DenseMatrix, DenseMatrix]
MAX_EQUIVARIANT_COMPONENTS = 3 * MAX_DIMENSION


def _identity(group: object) -> Any:
    value = getattr(group, "identity", None)
    if not callable(value):
        return value
    descriptor = getattr(type(group), "identity", None)
    if isinstance(descriptor, property):
        return value
    try:
        callable_signature: Signature = signature(value)
        callable_signature.bind()
    except (TypeError, ValueError):
        return value
    return value()


def _multiply(group: object, left: Any, right: Any) -> Any:
    operation = getattr(group, "multiply", None)
    return operation(left, right) if callable(operation) else left * right


def _label(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeformationError("equivariant component label must be a non-empty string")
    return unicodedata.normalize("NFC", value.strip())


def _validate_group_table(
    table: tuple[tuple[int, ...], ...],
    identity_index: int,
) -> None:
    order = len(table)
    if order == 0 or order > MAX_GROUP_ORDER:
        raise DeformationError(f"action group order must lie between 1 and {MAX_GROUP_ORDER}")
    if type(identity_index) is not int:
        raise DeformationError("action group identity index must be an exact integer")
    if not 0 <= identity_index < order:
        raise DeformationError("action group identity index is outside the table")
    if not isinstance(table, tuple) or any(
        not isinstance(row, tuple) or len(row) != order for row in table
    ):
        raise DeformationError("action multiplication table is not square")
    if any(type(value) is not int or not 0 <= value < order for row in table for value in row):
        raise DeformationError("action multiplication left the enumerated group")
    for element in range(order):
        if table[identity_index][element] != element or table[element][identity_index] != element:
            raise DeformationError("action multiplication table has no two-sided identity")
        if not any(
            table[element][candidate] == identity_index
            and table[candidate][element] == identity_index
            for candidate in range(order)
        ):
            raise DeformationError("action multiplication table has an element without an inverse")
    for left in range(order):
        for middle in range(order):
            for right in range(order):
                if table[table[left][middle]][right] != table[left][table[middle][right]]:
                    raise DeformationError("action multiplication table is not associative")


def _restriction_matrix(
    differential: DenseMatrix,
    domain: LinearSubspace,
    codomain: LinearSubspace,
) -> DenseMatrix:
    columns: list[tuple[int, ...]] = []
    for vector in domain.basis:
        image_vector = differential.matvec(vector)
        if not codomain.contains(image_vector):
            raise DeformationError("differential does not preserve the supplied subspaces")
        columns.append(codomain.coordinates(image_vector))
    return DenseMatrix.from_columns(
        differential.field,
        columns,
        nrows=codomain.dimension,
    )


def _component_complex(
    complex_: DeformationComplex,
    subspaces: tuple[LinearSubspace, LinearSubspace, LinearSubspace],
    *,
    label: str,
) -> DeformationComplex:
    degree0, degree1, degree2 = subspaces
    return DeformationComplex(
        complex_.field,
        _restriction_matrix(complex_.d0, degree0, degree1),
        _restriction_matrix(complex_.d1, degree1, degree2),
        name=label,
    )


@dataclass(frozen=True, slots=True, init=False)
class DeformationAction(DeformationSemanticObject):
    """A finite group action on every degree, commuting with both differentials.

    The canonical boundary pins the complete abstract multiplication table in
    the representation's exact element order and every corresponding matrix.
    It does not infer an isomorphism to another concrete group embedding.
    """

    complex: DeformationComplex
    degree0: Representation
    degree1: Representation
    degree2: Representation
    elements: tuple[Any, ...]
    identity_index: int
    multiplication_table: tuple[tuple[int, ...], ...]

    schema_version = DEFORM_ACTION_SCHEMA_V1

    def __init__(
        self,
        complex: DeformationComplex,
        degree0: Representation,
        degree1: Representation,
        degree2: Representation,
    ) -> None:
        if not isinstance(complex, DeformationComplex):
            raise TypeError("complex must be a DeformationComplex")
        representations = (degree0, degree1, degree2)
        if any(not isinstance(item, Representation) for item in representations):
            raise TypeError("degree actions must be Representation values")
        group = degree0.group
        if any(item.group is not group for item in representations[1:]):
            raise DeformationError("degree actions use different concrete group objects")
        elements = degree0.elements
        if not 1 <= len(elements) <= MAX_GROUP_ORDER:
            raise DeformationError(f"action group order must lie between 1 and {MAX_GROUP_ORDER}")
        if any(item.elements != elements for item in representations[1:]):
            raise DeformationError("degree actions enumerate different group elements")
        try:
            indices = {element: index for index, element in enumerate(elements)}
        except TypeError as exc:
            raise DeformationError("action group elements must be hashable") from exc
        identity = _identity(group)
        if identity not in indices:
            raise DeformationError("action group identity is absent from its enumeration")
        try:
            table = tuple(
                tuple(indices[_multiply(group, left, right)] for right in elements)
                for left in elements
            )
        except (KeyError, TypeError) as exc:
            raise DeformationError("action multiplication left the group enumeration") from exc
        _validate_group_table(table, indices[identity])
        object.__setattr__(self, "complex", complex)
        object.__setattr__(self, "degree0", degree0)
        object.__setattr__(self, "degree1", degree1)
        object.__setattr__(self, "degree2", degree2)
        object.__setattr__(self, "elements", elements)
        object.__setattr__(self, "identity_index", indices[identity])
        object.__setattr__(self, "multiplication_table", table)
        self.verify()

    @property
    def field(self) -> PrimeField:
        return self.complex.field

    @property
    def group(self) -> object:
        return self.degree0.group

    @property
    def representations(self) -> tuple[Representation, Representation, Representation]:
        return (self.degree0, self.degree1, self.degree2)

    @property
    def group_order(self) -> int:
        return len(self.elements)

    def verify(self) -> bool:
        self.complex.verify()
        if not 1 <= len(self.elements) <= MAX_GROUP_ORDER:
            raise DeformationVerificationError("action group order exceeds the portable boundary")
        expected_dimensions = self.complex.dimensions
        for degree, (representation, expected_dimension) in enumerate(
            zip(self.representations, expected_dimensions, strict=True)
        ):
            if representation.group is not self.group:
                raise DeformationVerificationError("degree actions use different groups")
            if representation.field != self.field or representation.dimension != expected_dimension:
                raise DeformationVerificationError(
                    f"degree-{degree} action has the wrong field or dimension"
                )
            representation.validate()
            if representation.elements != self.elements:
                raise DeformationVerificationError("action element ordering was altered")
            if any(
                not _canonical_dense_matrix(
                    representation.action_matrix(element),
                    field=self.field,
                )
                for element in self.elements
            ):
                raise DeformationVerificationError(
                    f"degree-{degree} action matrices are not canonical"
                )
        indices = {element: index for index, element in enumerate(self.elements)}
        expected_identity = indices.get(_identity(self.group))
        if expected_identity != self.identity_index:
            raise DeformationVerificationError("action identity index was altered")
        expected_table = tuple(
            tuple(indices[_multiply(self.group, left, right)] for right in self.elements)
            for left in self.elements
        )
        if expected_table != self.multiplication_table:
            raise DeformationVerificationError("action multiplication table was altered")
        try:
            _validate_group_table(self.multiplication_table, self.identity_index)
        except DeformationError as exc:
            raise DeformationVerificationError(str(exc)) from exc
        for element in self.elements:
            if self.complex.d0 @ self.degree0.action_matrix(element) != (
                self.degree1.action_matrix(element) @ self.complex.d0
            ):
                raise DeformationVerificationError("d0 is not equivariant")
            if self.complex.d1 @ self.degree1.action_matrix(element) != (
                self.degree2.action_matrix(element) @ self.complex.d1
            ):
                raise DeformationVerificationError("d1 is not equivariant")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "complex_id": self.complex.content_id,
            "degree_matrices": [
                [
                    representation.action_matrix(element).to_canonical_data()
                    for element in self.elements
                ]
                for representation in self.representations
            ],
            "group_order": self.group_order,
            "identity_index": self.identity_index,
            "multiplication_table": [list(row) for row in self.multiplication_table],
            "type": "arbogast.deform.deformation_action",
        }


@dataclass(frozen=True, slots=True, init=False)
class EquivariantDeformation(DeformationSemanticObject):
    """A deformation problem with a fully checked chain action."""

    problem: DeformationProblem
    action: DeformationAction

    schema_version = DEFORM_EQUIVARIANT_SCHEMA_V1

    def __init__(self, problem: DeformationProblem, action: DeformationAction) -> None:
        object.__setattr__(self, "problem", problem)
        object.__setattr__(self, "action", action)
        self.verify()

    @property
    def complex(self) -> DeformationComplex:
        return self.problem.complex

    def verify(self) -> bool:
        self.problem.verify()
        self.action.verify()
        if self.action.complex != self.problem.complex:
            raise DeformationVerificationError("action is bound to a different complex")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "action": self.action.to_canonical_data(),
            "problem_id": self.problem.content_id,
            "type": "arbogast.deform.equivariant_deformation",
        }


def equivariant(
    source: (
        DeformationComplex | DeformationPresentation | DeformationProblem | InvariantDeformations
    ),
    action: DeformationAction,
) -> EquivariantDeformation:
    """Bind a checked chain action to a normalized deformation problem."""

    if not isinstance(action, DeformationAction):
        raise TypeError("action must be a DeformationAction")
    return EquivariantDeformation(deformation_problem(source), action)


@dataclass(frozen=True, slots=True, init=False)
class InvariantDeformations(DeformationSemanticObject):
    """The invariant subcomplex, without an unsafe invariant-cohomology claim."""

    equivariant_deformation: EquivariantDeformation
    problem: DeformationProblem

    schema_version = DEFORM_INVARIANT_DEFORMATIONS_SCHEMA_V1

    def __init__(
        self,
        equivariant_deformation: EquivariantDeformation,
        problem: DeformationProblem,
    ) -> None:
        object.__setattr__(self, "equivariant_deformation", equivariant_deformation)
        object.__setattr__(self, "problem", problem)
        self.verify()

    @property
    def complex(self) -> DeformationComplex:
        return self.problem.complex

    @property
    def identifies_invariant_cohomology(self) -> bool:
        """Never silently identify ``H(C^G)`` with ``H(C)^G``."""

        return False

    def verify(self) -> bool:
        self.equivariant_deformation.verify()
        action = self.equivariant_deformation.action
        raw_subspaces = tuple(
            representation.invariant_space() for representation in action.representations
        )
        subspaces = (raw_subspaces[0], raw_subspaces[1], raw_subspaces[2])
        expected_complex = _component_complex(
            action.complex,
            subspaces,
            label="invariant subcomplex",
        )
        expected_problem = deformation_problem(
            expected_complex,
            source_id=self.equivariant_deformation.content_id,
            name="invariant subcomplex",
        )
        if self.problem != expected_problem:
            raise DeformationVerificationError("invariant problem presentation was altered")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "equivariant_id": self.equivariant_deformation.content_id,
            "identifies_invariant_cohomology": False,
            "problem": self.problem.to_canonical_data(),
            "type": "arbogast.deform.invariant_deformations",
        }


def invariant_deformations(source: EquivariantDeformation) -> InvariantDeformations:
    """Construct the exact invariant subcomplex in all three degrees."""

    if not isinstance(source, EquivariantDeformation):
        raise TypeError("source must be an EquivariantDeformation")
    source.verify()
    raw_subspaces = tuple(
        representation.invariant_space() for representation in source.action.representations
    )
    subspaces = (raw_subspaces[0], raw_subspaces[1], raw_subspaces[2])
    complex_ = _component_complex(
        source.complex,
        subspaces,
        label="invariant subcomplex",
    )
    problem = deformation_problem(
        complex_,
        source_id=source.content_id,
        name="invariant subcomplex",
    )
    return InvariantDeformations(source, problem)


@dataclass(frozen=True, slots=True, init=False)
class EquivariantComponent(DeformationSchemaObject):
    """One supplied direct summand of an equivariant deformation complex."""

    label: str
    ambient: DeformationComplex
    projectors: ProjectorTriple
    subspaces: tuple[LinearSubspace, LinearSubspace, LinearSubspace]
    complex: DeformationComplex

    schema_version = DEFORM_EQUIVARIANT_COMPONENT_SCHEMA_V1

    def __init__(
        self,
        label: str,
        projectors: Sequence[DenseMatrix],
        complex: DeformationComplex,
    ) -> None:
        normalized_projectors = tuple(projectors)
        if len(normalized_projectors) != 3 or any(
            not isinstance(projector, DenseMatrix) for projector in normalized_projectors
        ):
            raise DeformationError("an equivariant component needs three projector matrices")
        triple = (
            normalized_projectors[0],
            normalized_projectors[1],
            normalized_projectors[2],
        )
        raw_subspaces = tuple(image(projector) for projector in triple)
        subspaces = (raw_subspaces[0], raw_subspaces[1], raw_subspaces[2])
        component_complex = _component_complex(
            complex,
            subspaces,
            label=_label(label),
        )
        object.__setattr__(self, "label", _label(label))
        object.__setattr__(self, "ambient", complex)
        object.__setattr__(self, "projectors", triple)
        object.__setattr__(self, "subspaces", subspaces)
        object.__setattr__(self, "complex", component_complex)
        self.verify_against(complex)

    def verify_against(self, ambient: DeformationComplex) -> bool:
        ambient.verify()
        if ambient != self.ambient:
            raise DeformationVerificationError("component ambient complex binding was altered")
        if _label(self.label) != self.label:
            raise DeformationVerificationError("component label normalization was altered")
        for degree, (projector, dimension, subspace) in enumerate(
            zip(self.projectors, ambient.dimensions, self.subspaces, strict=True)
        ):
            if not _canonical_dense_matrix(projector, field=ambient.field):
                raise DeformationVerificationError(
                    f"degree-{degree} component projector is not canonical"
                )
            if projector.shape != (dimension, dimension):
                raise DeformationVerificationError(
                    f"degree-{degree} component projector has the wrong field or shape"
                )
            if not _canonical_linear_subspace(
                subspace,
                field=ambient.field,
                ambient_dimension=dimension,
            ):
                raise DeformationVerificationError(
                    f"degree-{degree} component subspace is not canonical"
                )
            if projector @ projector != projector:
                raise DeformationVerificationError("component projector is not idempotent")
            if image(projector) != subspace:
                raise DeformationVerificationError("component projector image was altered")
        if ambient.d0 @ self.projectors[0] != self.projectors[1] @ ambient.d0:
            raise DeformationVerificationError("component projectors do not commute with d0")
        if ambient.d1 @ self.projectors[1] != self.projectors[2] @ ambient.d1:
            raise DeformationVerificationError("component projectors do not commute with d1")
        expected = _component_complex(ambient, self.subspaces, label=self.label)
        if self.complex != expected:
            raise DeformationVerificationError("equivariant component complex was altered")
        return True

    def verify(self) -> bool:
        return self.verify_against(self.ambient)

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "ambient_id": self.ambient.content_id,
            "complex": self.complex.to_canonical_data(),
            "label": self.label,
            "projectors": [projector.to_canonical_data() for projector in self.projectors],
            "subspaces": [subspace.to_canonical_data() for subspace in self.subspaces],
            "type": "arbogast.deform.equivariant_component",
        }


@dataclass(frozen=True, slots=True, init=False)
class EquivariantDecomposition(DeformationSemanticObject):
    """A complete exact projector decomposition compatible with the chain action."""

    equivariant_deformation: EquivariantDeformation
    components: tuple[EquivariantComponent, ...]

    schema_version = DEFORM_EQUIVARIANT_DECOMPOSITION_SCHEMA_V1

    def __init__(
        self,
        equivariant_deformation: EquivariantDeformation,
        components: Sequence[EquivariantComponent],
    ) -> None:
        normalized_components = tuple(components)
        if any(
            not isinstance(component, EquivariantComponent) for component in normalized_components
        ):
            raise TypeError("decomposition components must be EquivariantComponent values")
        object.__setattr__(self, "equivariant_deformation", equivariant_deformation)
        object.__setattr__(
            self,
            "components",
            tuple(sorted(normalized_components, key=lambda component: component.label)),
        )
        self.verify()

    @property
    def complete(self) -> bool:
        return True

    def __iter__(self) -> Iterator[EquivariantComponent]:
        return iter(self.components)

    def verify(self) -> bool:
        self.equivariant_deformation.verify()
        ambient = self.equivariant_deformation.complex
        action = self.equivariant_deformation.action
        if len(self.components) > MAX_EQUIVARIANT_COMPONENTS:
            raise DeformationVerificationError(
                "decomposition has too many components for portable replay"
            )
        labels = tuple(component.label for component in self.components)
        if labels != tuple(sorted(set(labels))):
            raise DeformationVerificationError(
                "decomposition component labels are not canonical and unique"
            )
        for component in self.components:
            component.verify_against(ambient)
            if not any(subspace.dimension for subspace in component.subspaces):
                raise DeformationVerificationError("decomposition contains an all-zero component")
            for projector, representation in zip(
                component.projectors,
                action.representations,
                strict=True,
            ):
                if any(
                    projector @ representation.action_matrix(element)
                    != representation.action_matrix(element) @ projector
                    for element in action.elements
                ):
                    raise DeformationVerificationError(
                        "component projector does not commute with the group action"
                    )
        for degree, dimension in enumerate(ambient.dimensions):
            zero = DenseMatrix.zeros(ambient.field, dimension, dimension)
            total = zero
            for left_index, left in enumerate(self.components):
                total = total + left.projectors[degree]
                for right_index, right in enumerate(self.components):
                    if left_index != right_index and (
                        left.projectors[degree] @ right.projectors[degree] != zero
                        or right.projectors[degree] @ left.projectors[degree] != zero
                    ):
                        raise DeformationVerificationError(
                            "decomposition projectors are not pairwise orthogonal"
                        )
            if total != DenseMatrix.identity(ambient.field, dimension):
                raise DeformationVerificationError("decomposition projectors are not complete")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "complete": True,
            "components": [component.to_canonical_data() for component in self.components],
            "equivariant_id": self.equivariant_deformation.content_id,
            "type": "arbogast.deform.equivariant_decomposition",
        }


def equivariant_decomposition(
    source: EquivariantDeformation,
    projectors: Mapping[str, Sequence[DenseMatrix]] | None = None,
) -> EquivariantDecomposition | UnsupportedDeformation:
    """Certify a supplied complete projector decomposition.

    Automatic character-table discovery is deliberately deferred.  Omitting
    projectors therefore returns a typed refusal, never a guessed splitting.
    """

    if not isinstance(source, EquivariantDeformation):
        raise TypeError("source must be an EquivariantDeformation")
    source.verify()
    if projectors is None:
        return UnsupportedDeformation(
            "equivariant_decomposition",
            "automatic finite-field character/projector discovery is deferred",
            requested={"equivariant_id": source.content_id},
            supported=("supplied complete orthogonal chain projectors",),
        )
    if len(projectors) > MAX_EQUIVARIANT_COMPONENTS:
        raise DeformationError("decomposition has too many components for portable replay")
    normalized_projectors = {_label(label): value for label, value in projectors.items()}
    if len(normalized_projectors) != len(projectors):
        raise DeformationError("decomposition labels collide after normalization")
    if any(label != _label(label) for label in projectors):
        raise DeformationError("decomposition labels must already be normalized")
    labels = tuple(sorted(normalized_projectors))
    components = tuple(
        EquivariantComponent(label, normalized_projectors[label], source.complex)
        for label in labels
    )
    return EquivariantDecomposition(source, components)


__all__ = [
    "DeformationAction",
    "EquivariantComponent",
    "EquivariantDecomposition",
    "EquivariantDeformation",
    "InvariantDeformations",
    "equivariant",
    "equivariant_decomposition",
    "invariant_deformations",
]
