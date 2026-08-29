"""Small, exact adapter for concrete finite groups.

The adapter deliberately accepts a narrow structural protocol instead of
transporting elements into a convenient permutation group.  In particular,
two isomorphic group objects are still different concrete embeddings here.
"""

from __future__ import annotations

import hashlib
import inspect
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import ConcreteGroupMismatchError, GroupProtocolError

Element = Any


def _frame(tag: bytes, payload: bytes) -> bytes:
    """Injectively frame one canonical-key component."""

    return tag + len(payload).to_bytes(8, "big") + payload


def _call_or_value(obj: object, name: str) -> Any:
    value = getattr(obj, name)
    # Group elements (notably permutations) are often callable on points.  A
    # callable attribute is therefore not enough evidence that it is a zero-arg
    # accessor.  Only invoke actual function/method descriptors.
    return value() if inspect.ismethod(value) or inspect.isfunction(value) else value


def _stable_atom(value: Any) -> bytes:
    if isinstance(value, bytes):
        return _frame(b"b", value)
    if isinstance(value, str):
        return _frame(b"s", value.encode("utf-8"))
    if isinstance(value, bool):
        return _frame(b"t", b"1" if value else b"0")
    if isinstance(value, int):
        return _frame(b"i", str(value).encode("ascii"))
    if isinstance(value, (tuple, list)):
        items = tuple(_stable_atom(item) for item in value)
        payload = len(items).to_bytes(8, "big") + b"".join(
            len(item).to_bytes(8, "big") + item for item in items
        )
        return _frame(b"l", payload)
    raise GroupProtocolError(
        f"cannot derive a stable canonical key for element of type {type(value).__name__}; "
        "provide group.element_key(element) or element.canonical_bytes()"
    )


def _element_structural_key(group: object, element: Element) -> bytes:
    custom = getattr(group, "element_key", None)
    if callable(custom):
        return _stable_atom(custom(element))
    canonical_bytes = getattr(element, "canonical_bytes", None)
    if callable(canonical_bytes):
        value = canonical_bytes()
        if not isinstance(value, bytes):
            raise GroupProtocolError("element.canonical_bytes() must return bytes")
        return b"c:" + value
    for name in ("images", "one_line", "values", "mapping"):
        if hasattr(element, name):
            value = _call_or_value(element, name)
            if isinstance(value, dict):
                value = tuple(sorted(value.items()))
            return name.encode() + b":" + _stable_atom(value)
    return _stable_atom(element)


@dataclass(frozen=True)
class ConcreteGroupContext:
    """Validated operations and canonical ordering for one group instance."""

    group: object
    elements: tuple[Element, ...]
    identity: Element
    fingerprint: str
    _index: dict[Element, int]
    _multiply: Callable[[Element, Element], Element]
    _inverse: Callable[[Element], Element]

    @classmethod
    def build(cls, group: object) -> ConcreteGroupContext:
        if group is None:
            raise GroupProtocolError("a concrete finite group is required")
        if not hasattr(group, "elements"):
            raise GroupProtocolError("group must expose a finite .elements iterable")
        raw_elements = tuple(_call_or_value(group, "elements"))
        if not raw_elements:
            raise GroupProtocolError("group.elements must be nonempty")
        try:
            unique = set(raw_elements)
        except TypeError as exc:
            raise GroupProtocolError("group elements must be hashable") from exc
        if len(unique) != len(raw_elements):
            raise GroupProtocolError("group.elements contains duplicates")

        if not hasattr(group, "identity"):
            raise GroupProtocolError("group must expose .identity")
        identity = _call_or_value(group, "identity")

        mul_method = getattr(group, "multiply", None)
        if callable(mul_method):
            multiply = mul_method
        else:

            def multiply(left: Element, right: Element) -> Element:
                return left * right

        inv_method = getattr(group, "inverse", None)
        if callable(inv_method):
            inverse = inv_method
        else:

            def inverse(value: Element) -> Element:
                method = getattr(value, "inverse", None)
                if callable(method):
                    return method()
                try:
                    return value**-1
                except (TypeError, ValueError) as exc:
                    raise GroupProtocolError(
                        "group must expose inverse(element) or elements must expose inverse()"
                    ) from exc

        if identity not in unique:
            raise GroupProtocolError("group.identity is absent from group.elements")

        keyed = [(_element_structural_key(group, element), element) for element in raw_elements]
        if len({key for key, _ in keyed}) != len(keyed):
            raise GroupProtocolError("canonical element keys are not injective")
        keyed.sort(key=lambda item: item[0])
        elements = tuple(element for _, element in keyed)
        index = {element: position for position, element in enumerate(elements)}

        # Validate only the primitive operations here.  Full multiplication-table
        # validation would make every construction quadratic before useful work.
        for element in elements:
            inv = inverse(element)
            if inv not in index:
                raise GroupProtocolError("inverse operation left group.elements")
            if multiply(element, inv) != identity or multiply(inv, element) != identity:
                raise GroupProtocolError("inverse operation failed an exact identity check")
        digest = hashlib.sha256()
        digest.update(b"arbogast.concrete-group.v1\0")
        degree = getattr(group, "degree", None)
        digest.update(f"degree={degree!r};order={len(elements)}\0".encode())
        for key, _ in keyed:
            digest.update(len(key).to_bytes(8, "big"))
            digest.update(key)
        # Pin the concrete multiplication law, not merely the element set.
        for left in elements:
            for right in elements:
                product = multiply(left, right)
                if product not in index:
                    raise GroupProtocolError("multiplication left group.elements")
                digest.update(index[product].to_bytes(8, "big"))
        return cls(group, elements, identity, digest.hexdigest(), index, multiply, inverse)

    @property
    def order(self) -> int:
        return len(self.elements)

    def require_same_group(self, group: object) -> None:
        if group is not self.group:
            raise ConcreteGroupMismatchError(
                "Hurwitz objects belong to different concrete group instances; "
                "supply an explicit transport instead of relying on isomorphism"
            )

    def contains(self, element: Element) -> bool:
        return element in self._index

    def index(self, element: Element) -> int:
        try:
            return self._index[element]
        except (KeyError, TypeError) as exc:
            raise ConcreteGroupMismatchError("element is not in the concrete group") from exc

    def key(self, element: Element) -> int:
        return self.index(element)

    def tuple_key(self, entries: Sequence[Element]) -> tuple[int, ...]:
        return tuple(self.index(entry) for entry in entries)

    def multiply(self, left: Element, right: Element) -> Element:
        self.index(left)
        self.index(right)
        result = self._multiply(left, right)
        if result not in self._index:
            raise GroupProtocolError("group multiplication returned an external element")
        return result

    def inverse(self, element: Element) -> Element:
        self.index(element)
        result = self._inverse(element)
        if result not in self._index:
            raise GroupProtocolError("group inverse returned an external element")
        return result

    def product(self, entries: Iterable[Element]) -> Element:
        result = self.identity
        for entry in entries:
            result = self.multiply(result, entry)
        return result

    def conjugate(self, element: Element, by: Element) -> Element:
        """Return ``by^-1 * element * by``."""

        return self.multiply(self.multiply(self.inverse(by), element), by)

    def conjugate_left(self, element: Element, by: Element) -> Element:
        """Return ``by * element * by^-1``."""

        return self.multiply(self.multiply(by, element), self.inverse(by))

    def simultaneous_conjugate(
        self, entries: Sequence[Element], by: Element
    ) -> tuple[Element, ...]:
        return tuple(self.conjugate(entry, by) for entry in entries)

    def generated_elements(self, generators: Sequence[Element]) -> frozenset[Element]:
        for generator in generators:
            self.index(generator)
        native = getattr(self.group, "subgroup", None)
        if callable(native):
            subgroup = native(tuple(generators))
            if not hasattr(subgroup, "elements"):
                raise GroupProtocolError("group.subgroup(gens) did not expose .elements")
            values = frozenset(_call_or_value(subgroup, "elements"))
            if not values <= set(self.elements):
                raise GroupProtocolError("group.subgroup(gens) changed the concrete embedding")
            return values

        moves = tuple(generators) + tuple(self.inverse(g) for g in generators)
        seen: set[Element] = {self.identity}
        queue: deque[Element] = deque([self.identity])
        while queue:
            current = queue.popleft()
            for move in moves:
                candidate = self.multiply(current, move)
                if candidate not in seen:
                    seen.add(candidate)
                    queue.append(candidate)
        return frozenset(seen)

    def is_generated_by(self, generators: Sequence[Element]) -> bool:
        native = getattr(self.group, "is_generated_by", None)
        if callable(native):
            result = native(tuple(generators))
            if not isinstance(result, bool):
                raise GroupProtocolError("group.is_generated_by() must return bool")
            return result
        return len(self.generated_elements(generators)) == self.order

    def canonical_conjugate(
        self, entries: Sequence[Element]
    ) -> tuple[tuple[Element, ...], Element]:
        """Canonicalize a tuple under exact simultaneous inner conjugacy."""

        best_entries: tuple[Element, ...] | None = None
        best_by: Element | None = None
        best_key: tuple[int, ...] | None = None
        for by in self.elements:
            candidate = self.simultaneous_conjugate(entries, by)
            key = self.tuple_key(candidate)
            if best_key is None or key < best_key:
                best_key = key
                best_entries = candidate
                best_by = by
        assert best_entries is not None and best_by is not None
        return best_entries, best_by


def class_members(value: object) -> tuple[Element, ...]:
    """Extract members from an explicitly materialized conjugacy class."""

    if isinstance(value, (str, bytes)):
        raise GroupProtocolError(
            "class labels are not explicit conjugacy classes; resolve them in the "
            "pinned group first"
        )
    for name in ("members", "elements"):
        if hasattr(value, name):
            return tuple(_call_or_value(value, name))
    if isinstance(value, Iterable):
        return tuple(value)
    raise GroupProtocolError("conjugacy classes must be explicit finite iterables")
