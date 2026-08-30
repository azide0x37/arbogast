"""Canonical maps and short exact sequences of concrete finite groups.

The runtime group objects are deliberately kept outside the serialized identity.  A map is
identified by complete multiplication-table snapshots and an image index for every domain
element.  Thus a callable is consulted exactly once during construction and never crosses a
certificate or backend boundary.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, cast

from arbogast.cert import FrozenMap, freeze_mapping
from arbogast.core import (
    CanonicalJSON,
    CanonicalObject,
    canonical_data,
    canonical_json,
    sha256_hex,
)


def _call_or_value(value: Any) -> Any:
    return (
        value()
        if inspect.ismethod(value) or inspect.isfunction(value) or inspect.isbuiltin(value)
        else value
    )


def _read(value: Any, names: Sequence[str]) -> Any:
    for name in names:
        if hasattr(value, name):
            return _call_or_value(getattr(value, name))
    raise TypeError(f"object must expose one of {', '.join(names)}")


def _element_data(value: Any) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, bytes):
        return {"$arbogast_type": "bytes", "hex": value.hex()}
    if isinstance(value, (tuple, list)):
        return [_element_data(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical group-element mapping keys must be strings")
        return {key: _element_data(item) for key, item in value.items()}
    for name in ("to_canonical_data", "to_canonical"):
        method = getattr(value, name, None)
        if callable(method):
            return _element_data(method())
    if hasattr(value, "canonical_bytes"):
        encoded = _call_or_value(value.canonical_bytes)
        return {"$arbogast_type": "canonical_bytes", "hex": bytes(encoded).hex()}
    if is_dataclass(value):
        return _element_data(asdict(value))  # type: ignore[arg-type]
    if hasattr(value, "images"):
        return {"images": _element_data(_call_or_value(value.images))}
    raise TypeError("finite group elements need an exact canonical encoding")


def _element_id(group: Any, element: Any) -> str:
    for name in ("canonical_element_bytes", "encode_element", "element_encoding"):
        operation = getattr(group, name, None)
        if callable(operation):
            return canonical_json(_element_data(operation(element)))
    return canonical_json(_element_data(element))


def _elements(group: Any) -> tuple[Any, ...]:
    raw = tuple(_read(group, ("elements", "enumerate_elements")))
    if not raw:
        raise ValueError("a finite group must contain its identity")
    keyed = tuple((_element_id(group, element), element) for element in raw)
    if len({identifier for identifier, _ in keyed}) != len(keyed):
        raise ValueError("canonical finite-group element encodings are not unique")
    return tuple(element for _, element in sorted(keyed, key=lambda pair: pair[0]))


def _identity(group: Any) -> Any:
    return _read(group, ("identity", "one", "identity_element"))


def _multiply(group: Any, left: Any, right: Any) -> Any:
    for name in ("multiply", "mul", "product"):
        operation = getattr(group, name, None)
        if callable(operation):
            return operation(left, right)
    return left * right


def _index(elements: Sequence[Any], element: Any) -> int:
    matches = tuple(index for index, candidate in enumerate(elements) if candidate == element)
    if len(matches) != 1:
        raise ValueError("a group operation returned an unknown or ambiguous element")
    return matches[0]


def _snapshot(group: Any) -> tuple[tuple[Any, ...], dict[str, object]]:
    elements = _elements(group)
    identifiers = tuple(_element_id(group, element) for element in elements)
    identity_index = _index(elements, _identity(group))
    table = tuple(
        tuple(_index(elements, _multiply(group, left, right)) for right in elements)
        for left in elements
    )
    order = len(elements)
    for index in range(order):
        if table[identity_index][index] != index or table[index][identity_index] != index:
            raise ValueError("finite group identity law failed")
    for left in range(order):
        for middle in range(order):
            for right in range(order):
                if table[table[left][middle]][right] != table[left][table[middle][right]]:
                    raise ValueError("finite group associativity failed")
        if not any(
            table[left][candidate] == identity_index and table[candidate][left] == identity_index
            for candidate in range(order)
        ):
            raise ValueError("finite group element has no two-sided inverse")
    return elements, {
        "element_ids": list(identifiers),
        "identity_index": identity_index,
        "multiplication_table": [list(row) for row in table],
    }


def _map_callable(mapping: Any) -> Callable[[Any], Any]:
    if isinstance(mapping, Mapping):
        return lambda element: mapping[element]
    if callable(mapping):
        return cast("Callable[[Any], Any]", mapping)
    for name in ("apply", "image", "map_element"):
        operation = getattr(mapping, name, None)
        if callable(operation):
            return cast("Callable[[Any], Any]", operation)
    raise TypeError("finite group map must be callable, a mapping, or expose apply(element)")


@dataclass(frozen=True, slots=True)
class FiniteGroupMap(CanonicalObject):
    """A fully enumerated homomorphism between pinned concrete finite groups."""

    domain: Any = field(repr=False, compare=False, hash=False)
    codomain: Any = field(repr=False, compare=False, hash=False)
    domain_elements: tuple[Any, ...] = field(repr=False, compare=False, hash=False)
    codomain_elements: tuple[Any, ...] = field(repr=False, compare=False, hash=False)
    domain_snapshot: FrozenMap
    codomain_snapshot: FrozenMap
    image_indices: tuple[int, ...]
    injective: bool
    surjective: bool

    def __init__(
        self,
        domain: Any,
        codomain: Any,
        mapping: Any,
        *,
        require_injective: bool = False,
        require_surjective: bool = False,
    ) -> None:
        domain_elements, domain_snapshot = _snapshot(domain)
        codomain_elements, codomain_snapshot = _snapshot(codomain)
        operation = _map_callable(mapping)
        # Freeze a possibly stateful callable after exactly one call per domain element.
        images = tuple(operation(element) for element in domain_elements)
        image_indices = tuple(_index(codomain_elements, image) for image in images)
        domain_table = cast("list[list[int]]", domain_snapshot["multiplication_table"])
        codomain_table = cast("list[list[int]]", codomain_snapshot["multiplication_table"])
        domain_identity = cast("int", domain_snapshot["identity_index"])
        codomain_identity = cast("int", codomain_snapshot["identity_index"])
        if image_indices[domain_identity] != codomain_identity:
            raise ValueError("finite group map does not preserve the identity")
        for left in range(len(domain_elements)):
            for right in range(len(domain_elements)):
                if (
                    codomain_table[image_indices[left]][image_indices[right]]
                    != image_indices[domain_table[left][right]]
                ):
                    raise ValueError("finite group map does not preserve multiplication")
        injective = len(set(image_indices)) == len(image_indices)
        surjective = set(image_indices) == set(range(len(codomain_elements)))
        if require_injective and not injective:
            raise ValueError("finite group map is not injective")
        if require_surjective and not surjective:
            raise ValueError("finite group map is not surjective")
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "codomain", codomain)
        object.__setattr__(self, "domain_elements", domain_elements)
        object.__setattr__(self, "codomain_elements", codomain_elements)
        object.__setattr__(self, "domain_snapshot", freeze_mapping(domain_snapshot))
        object.__setattr__(self, "codomain_snapshot", freeze_mapping(codomain_snapshot))
        object.__setattr__(self, "image_indices", image_indices)
        object.__setattr__(self, "injective", injective)
        object.__setattr__(self, "surjective", surjective)

    def apply(self, element: Any) -> Any:
        index = _index(self.domain_elements, element)
        return self.codomain_elements[self.image_indices[index]]

    __call__ = apply

    @property
    def images(self) -> tuple[Any, ...]:
        return tuple(self.codomain_elements[index] for index in self.image_indices)

    @property
    def content_hash(self) -> str:
        return sha256_hex(self)

    def to_canonical_data(self) -> CanonicalJSON:
        return canonical_data(
            {
                "schema_version": "arbogast.finite-group-map.v1",
                "domain": self.domain_snapshot.to_dict(),
                "codomain": self.codomain_snapshot.to_dict(),
                "image_indices": list(self.image_indices),
            }
        )

    def verify(self) -> bool:
        rebuilt = FiniteGroupMap(self.domain, self.codomain, self.apply)
        if rebuilt.to_canonical_data() != self.to_canonical_data():
            raise ValueError("finite group map snapshot does not match its runtime groups")
        return True


@dataclass(frozen=True, slots=True)
class FiniteGroupExtension(CanonicalObject):
    """A canonical short exact sequence ``1 -> N -> G -> Q -> 1``."""

    kernel: Any = field(repr=False, compare=False, hash=False)
    group: Any = field(repr=False, compare=False, hash=False)
    quotient: Any = field(repr=False, compare=False, hash=False)
    inclusion: FiniteGroupMap
    projection: FiniteGroupMap
    section_indices: tuple[int, ...]

    def __init__(
        self,
        kernel: Any,
        group: Any,
        quotient: Any,
        inclusion: FiniteGroupMap | Any,
        projection: FiniteGroupMap | Any,
        *,
        section: Any | None = None,
    ) -> None:
        include = (
            inclusion
            if isinstance(inclusion, FiniteGroupMap)
            else FiniteGroupMap(kernel, group, inclusion, require_injective=True)
        )
        project = (
            projection
            if isinstance(projection, FiniteGroupMap)
            else FiniteGroupMap(group, quotient, projection, require_surjective=True)
        )
        if include.domain_snapshot != freeze_mapping(
            _snapshot(kernel)[1]
        ) or include.codomain_snapshot != freeze_mapping(_snapshot(group)[1]):
            raise ValueError("extension inclusion is bound to different finite groups")
        if project.domain_snapshot != freeze_mapping(
            _snapshot(group)[1]
        ) or project.codomain_snapshot != freeze_mapping(_snapshot(quotient)[1]):
            raise ValueError("extension projection is bound to different finite groups")
        if not include.injective:
            raise ValueError("extension inclusion must be injective")
        if not project.surjective:
            raise ValueError("extension projection must be surjective")
        quotient_identity = cast("int", project.codomain_snapshot["identity_index"])
        projection_kernel = {
            index for index, image in enumerate(project.image_indices) if image == quotient_identity
        }
        if set(include.image_indices) != projection_kernel:
            raise ValueError("extension is not exact at the total group")
        if section is None:
            total_identity = cast("int", project.domain_snapshot["identity_index"])
            quotient_identity = cast("int", project.codomain_snapshot["identity_index"])
            section_indices = tuple(
                total_identity
                if quotient_index == quotient_identity
                else next(
                    index
                    for index, image_index in enumerate(project.image_indices)
                    if image_index == quotient_index
                )
                for quotient_index in range(len(project.codomain_elements))
            )
        else:
            if isinstance(section, Mapping):
                values = tuple(section[element] for element in project.codomain_elements)
            elif callable(section):
                values = tuple(section(element) for element in project.codomain_elements)
            else:
                values = tuple(section)
                if len(values) != len(project.codomain_elements):
                    raise ValueError("extension section has the wrong length")
            section_indices = tuple(_index(project.domain_elements, value) for value in values)
        if tuple(project.image_indices[index] for index in section_indices) != tuple(
            range(len(project.codomain_elements))
        ):
            raise ValueError("extension section is not a right inverse to the projection")
        if section_indices[cast("int", project.codomain_snapshot["identity_index"])] != cast(
            "int", project.domain_snapshot["identity_index"]
        ):
            raise ValueError("extension section must be normalized at the identity")
        object.__setattr__(self, "kernel", kernel)
        object.__setattr__(self, "group", group)
        object.__setattr__(self, "quotient", quotient)
        object.__setattr__(self, "inclusion", include)
        object.__setattr__(self, "projection", project)
        object.__setattr__(self, "section_indices", section_indices)

    @property
    def total_group(self) -> Any:
        return self.group

    @property
    def total(self) -> Any:
        return self.group

    @property
    def quotient_map(self) -> FiniteGroupMap:
        return self.projection

    @property
    def content_hash(self) -> str:
        return sha256_hex(self)

    def right_transversal(self) -> tuple[Any, ...]:
        """Return one deterministic representative for every fiber of ``G -> Q``."""

        return self.section

    @property
    def section(self) -> tuple[Any, ...]:
        return tuple(self.projection.domain_elements[index] for index in self.section_indices)

    @property
    def transversal(self) -> tuple[Any, ...]:
        return self.section

    @property
    def is_split(self) -> bool:
        """Return whether the pinned normalized section is a group homomorphism."""

        quotient_table = self.projection.codomain_snapshot["multiplication_table"]
        group_table = self.projection.domain_snapshot["multiplication_table"]
        return all(
            group_table[self.section_indices[left]][self.section_indices[right]]
            == self.section_indices[quotient_table[left][right]]
            for left in range(len(self.section_indices))
            for right in range(len(self.section_indices))
        )

    complete_transversal = right_transversal

    def to_canonical_data(self) -> CanonicalJSON:
        return canonical_data(
            {
                "schema_version": "arbogast.finite-group-extension.v1",
                "inclusion": self.inclusion.to_canonical_data(),
                "projection": self.projection.to_canonical_data(),
                "section_indices": list(self.section_indices),
            }
        )

    def verify(self) -> bool:
        self.inclusion.verify()
        self.projection.verify()
        rebuilt = FiniteGroupExtension(
            self.kernel,
            self.group,
            self.quotient,
            self.inclusion,
            self.projection,
            section=self.section,
        )
        if rebuilt.to_canonical_data() != self.to_canonical_data():
            raise ValueError("finite group extension snapshot failed exact replay")
        return True


__all__ = ["FiniteGroupExtension", "FiniteGroupMap"]
