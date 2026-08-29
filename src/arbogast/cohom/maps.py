"""Restriction and inflation maps with explicit finite homomorphism checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from .complex import (
    Cochain,
    CochainComplex,
    ComplexityLimits,
    InvalidGroupError,
    _element_index,
    _group_elements,
    _group_identity,
    _multiply,
    cochain_complex,
)
from .results import CohomologyClass, class_of


@dataclass(frozen=True, slots=True)
class _PrimeFieldSnapshot:
    characteristic: int

    @property
    def order(self) -> int:
        return self.characteristic


@dataclass(frozen=True, slots=True)
class _PulledBackModule:
    field: _PrimeFieldSnapshot
    dimension: int
    matrix_for_element: Callable[[Any], tuple[tuple[int, ...], ...]]

    def action_matrix(self, element: Any) -> tuple[tuple[int, ...], ...]:
        return self.matrix_for_element(element)


def _map_function(mapping: Any | None) -> Callable[[Any], Any]:
    if mapping is None:
        return lambda element: element
    if isinstance(mapping, Mapping):
        return lambda element: mapping[element]
    if callable(mapping):
        return cast("Callable[[Any], Any]", mapping)
    for name in ("apply", "image", "map_element"):
        if hasattr(mapping, name) and callable(getattr(mapping, name)):
            return cast("Callable[[Any], Any]", getattr(mapping, name))
    raise TypeError("group map must be callable, a mapping, or expose apply(element)")


def _source_cochain(value: Cochain | CohomologyClass) -> Cochain:
    return value.representative if isinstance(value, CohomologyClass) else value


def _mapped_indices(
    domain_elements: tuple[Any, ...],
    codomain_complex: CochainComplex,
    mapping: Callable[[Any], Any],
) -> tuple[int, ...]:
    return tuple(
        _element_index(codomain_complex.elements, mapping(element)) for element in domain_elements
    )


def _validate_homomorphism(
    domain: Any,
    codomain_complex: CochainComplex,
    mapping: Callable[[Any], Any],
    *,
    injective: bool = False,
    surjective: bool = False,
) -> tuple[tuple[Any, ...], tuple[int, ...]]:
    elements = _group_elements(domain)
    mapped = _mapped_indices(elements, codomain_complex, mapping)
    identity_index = _element_index(elements, _group_identity(domain))
    if mapped[identity_index] != codomain_complex.identity_index:
        raise InvalidGroupError("group map does not preserve the identity")
    for left_index, left in enumerate(elements):
        for right_index, right in enumerate(elements):
            product_index = _element_index(elements, _multiply(domain, left, right))
            if (
                codomain_complex.multiplication_table[mapped[left_index]][mapped[right_index]]
                != mapped[product_index]
            ):
                raise InvalidGroupError("supplied map is not a group homomorphism")
    if injective and len(set(mapped)) != len(mapped):
        raise InvalidGroupError("subgroup inclusion is not injective")
    if surjective and set(mapped) != set(range(codomain_complex.group_order)):
        raise InvalidGroupError("quotient projection is not surjective")
    return elements, mapped


def restrict(
    value: Cochain | CohomologyClass,
    subgroup: Any,
    inclusion: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> Cochain | CohomologyClass:
    """Restrict a cochain or class along an explicit subgroup inclusion.

    If subgroup elements are literally elements of the ambient group, ``inclusion`` may be
    omitted.  Otherwise it must map every subgroup element into the ambient concrete group.
    Injectivity and the homomorphism law are checked before values are transported.
    """

    source = _source_cochain(value)
    source_complex = source.complex
    include = _map_function(inclusion)
    subgroup_elements, mapped = _validate_homomorphism(
        subgroup,
        source_complex,
        include,
        injective=True,
    )

    def matrix_for_element(element: Any) -> tuple[tuple[int, ...], ...]:
        index = _element_index(subgroup_elements, element)
        return source_complex.action_matrices[mapped[index]]

    module = _PulledBackModule(
        _PrimeFieldSnapshot(source_complex.prime),
        source_complex.module_dimension,
        matrix_for_element,
    )
    target_complex = cochain_complex(subgroup, module, source.degree, limits=limits)

    def frozen_inclusion(element: Any) -> Any:
        index = _element_index(subgroup_elements, element)
        return source_complex.elements[mapped[index]]

    def restricted_value(*arguments: Any) -> tuple[int, ...]:
        return source(*(frozen_inclusion(argument) for argument in arguments))

    target = target_complex.space(source.degree).from_function(restricted_value)
    if isinstance(value, CohomologyClass):
        return class_of(target)
    return target


def _extension_parts(extension: Any) -> tuple[Any, Any]:
    group: Any | None = None
    projection: Any | None = None
    for name in ("group", "total_group", "source", "middle"):
        if hasattr(extension, name):
            group = getattr(extension, name)
            break
    for name in ("projection", "quotient_map", "map", "surjection"):
        if hasattr(extension, name):
            projection = getattr(extension, name)
            break
    if group is None or projection is None:
        raise TypeError("extension must expose its total group and quotient projection")
    return group, projection


def inflate(
    value: Cochain | CohomologyClass,
    group_or_extension: Any,
    projection: Any | None = None,
    *,
    limits: ComplexityLimits | None = None,
) -> Cochain | CohomologyClass:
    """Inflate a quotient cochain or class through a checked surjection.

    Pass ``inflate(c, group, projection)`` or an extension object exposing both its total group
    and projection.  Surjectivity and the homomorphism law are checked, and the module action is
    pulled back through precisely that map.
    """

    if projection is None:
        group, projection = _extension_parts(group_or_extension)
    else:
        group = group_or_extension
    project = _map_function(projection)
    source = _source_cochain(value)
    quotient_complex = source.complex
    group_elements, mapped = _validate_homomorphism(
        group,
        quotient_complex,
        project,
        surjective=True,
    )

    def matrix_for_element(element: Any) -> tuple[tuple[int, ...], ...]:
        index = _element_index(group_elements, element)
        return quotient_complex.action_matrices[mapped[index]]

    module = _PulledBackModule(
        _PrimeFieldSnapshot(quotient_complex.prime),
        quotient_complex.module_dimension,
        matrix_for_element,
    )
    target_complex = cochain_complex(group, module, source.degree, limits=limits)

    def frozen_projection(element: Any) -> Any:
        index = _element_index(group_elements, element)
        return quotient_complex.elements[mapped[index]]

    def inflated_value(*arguments: Any) -> tuple[int, ...]:
        return source(*(frozen_projection(argument) for argument in arguments))

    target = target_complex.space(source.degree).from_function(inflated_value)
    if isinstance(value, CohomologyClass):
        return class_of(target)
    return target


__all__ = ["inflate", "restrict"]
