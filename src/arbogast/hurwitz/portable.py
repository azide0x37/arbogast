"""Portable, backend-neutral certificates for finite Hurwitz computations.

The discovery objects in :mod:`arbogast.hurwitz` retain convenient concrete
group backends.  This module is the transport boundary: a certificate embeds
the complete portable Nielsen receipt, finite operation inputs, and the exact
advertised output.  Verification starts only from the embedded multiplication
table and independently replays the requested operation.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, cast

from arbogast.cert import CertificateLayer, ContentAddressedCertificate
from arbogast.cert.canonical import (
    FrozenMap,
    canonicalize,
    freeze_mapping,
    validate_content_address,
)

from ._cert import INNER_CONJUGACY_CONVENTION, RIGHT_HURWITZ_CONVENTION
from .errors import CertificateVerificationError
from .nielsen import NielsenClass, verify_nielsen_certificate_payload

PORTABLE_OPERATION_SCHEMA = "arbogast.hurwitz.operation/v1"

BRAID_ACTION = "braid_action"
COMPONENTS = "components"
REAL_STRUCTURE = "real_structure"
REAL_CENSUS = "real_census"
REDUCED = "reduced"
CUSPS = "cusps"
BOUNDARY = "boundary"

PORTABLE_OPERATIONS = (
    BRAID_ACTION,
    COMPONENTS,
    REAL_STRUCTURE,
    REAL_CENSUS,
    REDUCED,
    CUSPS,
    BOUNDARY,
)


def _fail(message: str) -> CertificateVerificationError:
    return CertificateVerificationError(message)


def _exact_keys(value: Mapping[str, object], expected: set[str], *, record: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail: list[str] = []
        if missing:
            detail.append(f"missing={missing}")
        if extra:
            detail.append(f"unexpected={extra}")
        raise _fail(f"{record} has noncanonical fields ({', '.join(detail)})")


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _fail(f"{field} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, *, field: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _fail(f"{field} must be a sequence")
    return cast(Sequence[object], value)


def _integer(value: object, *, field: str, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise _fail(f"{field} must be an integer")
    result = value
    if minimum is not None and result < minimum:
        raise _fail(f"{field} must be at least {minimum}")
    return result


def _boolean(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise _fail(f"{field} must be a boolean")
    return value


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(f"{field} must be a nonempty string")
    return value


def _integer_tuple(value: object, *, field: str) -> tuple[int, ...]:
    return tuple(
        _integer(entry, field=f"{field}[{index}]", minimum=0)
        for index, entry in enumerate(_sequence(value, field=field))
    )


def _strict_nielsen_payload(value: object) -> dict[str, object]:
    """Validate the transport shape before the legacy mathematical replay.

    The original table verifier intentionally accepts ordinary JSON sequences,
    but predates the strict transport boundary and uses ``int(...)`` in a few
    places.  This front-end rejects booleans, strings, extra fields, and every
    other coercible lookalike before calling it.
    """

    raw = _mapping(value, field="nielsen_certificate")
    _exact_keys(
        raw,
        {
            "schema_version",
            "layer",
            "group_fingerprint",
            "identity_index",
            "multiplication_table",
            "class_fingerprints",
            "class_member_indices",
            "inner_conjugacy_convention",
            "candidate_count",
            "product_one_count",
            "generating_count",
            "representative_keys",
            "orbit_witnesses",
            "claim",
            "certificate_id",
        },
        record="portable Nielsen certificate",
    )
    if raw["schema_version"] != "arbogast.hurwitz.nielsen-enumeration.v1":
        raise _fail("unsupported portable Nielsen schema")
    if raw["layer"] != CertificateLayer.VERIFICATION.value:
        raise _fail("portable Nielsen certificate has the wrong layer")
    _string(raw["group_fingerprint"], field="Nielsen group_fingerprint")
    _integer(raw["identity_index"], field="Nielsen identity_index", minimum=0)
    table = _sequence(raw["multiplication_table"], field="Nielsen multiplication_table")
    for row_index, row in enumerate(table):
        _integer_tuple(row, field=f"Nielsen multiplication_table[{row_index}]")
    fingerprints = _sequence(raw["class_fingerprints"], field="Nielsen class_fingerprints")
    for index, fingerprint in enumerate(fingerprints):
        _string(fingerprint, field=f"Nielsen class_fingerprints[{index}]")
    classes = _sequence(raw["class_member_indices"], field="Nielsen class_member_indices")
    for index, members in enumerate(classes):
        _integer_tuple(members, field=f"Nielsen class_member_indices[{index}]")
    if raw["inner_conjugacy_convention"] != INNER_CONJUGACY_CONVENTION:
        raise _fail("portable Nielsen inner-conjugacy convention mismatch")
    for name in ("candidate_count", "product_one_count", "generating_count"):
        _integer(raw[name], field=f"Nielsen {name}", minimum=0)
    representatives = _sequence(raw["representative_keys"], field="Nielsen representative_keys")
    for index, key in enumerate(representatives):
        _integer_tuple(key, field=f"Nielsen representative_keys[{index}]")
    witnesses = _sequence(raw["orbit_witnesses"], field="Nielsen orbit_witnesses")
    for index, witness_value in enumerate(witnesses):
        witness = _mapping(witness_value, field=f"Nielsen orbit_witnesses[{index}]")
        _exact_keys(
            witness,
            {"raw_key", "representative_key", "conjugator_index"},
            record=f"Nielsen orbit_witnesses[{index}]",
        )
        _integer_tuple(witness["raw_key"], field=f"Nielsen witness {index} raw_key")
        _integer_tuple(
            witness["representative_key"],
            field=f"Nielsen witness {index} representative_key",
        )
        _integer(
            witness["conjugator_index"],
            field=f"Nielsen witness {index} conjugator_index",
            minimum=0,
        )
    if raw["claim"] != "complete inner Nielsen class for the ordered explicit class vector":
        raise _fail("portable Nielsen claim label mismatch")
    certificate_id = _string(raw["certificate_id"], field="Nielsen certificate_id")
    transported = dict(raw)
    del transported["certificate_id"]
    try:
        validate_content_address(certificate_id, transported)
    except ValueError as exc:
        raise _fail("portable Nielsen content address mismatch") from exc
    verify_nielsen_certificate_payload(transported)
    return dict(raw)


@dataclass(frozen=True)
class _TableContext:
    table: tuple[tuple[int, ...], ...]
    identity: int
    classes: tuple[tuple[int, ...], ...]
    representatives: tuple[tuple[int, ...], ...]
    inverses: tuple[int, ...]
    representative_index: Mapping[tuple[int, ...], int]

    @classmethod
    def from_nielsen(cls, payload: Mapping[str, object]) -> _TableContext:
        table = tuple(
            tuple(cast(int, entry) for entry in cast(Sequence[object], row))
            for row in cast(Sequence[object], payload["multiplication_table"])
        )
        identity = cast(int, payload["identity_index"])
        classes = tuple(
            tuple(cast(int, entry) for entry in cast(Sequence[object], row))
            for row in cast(Sequence[object], payload["class_member_indices"])
        )
        representatives = tuple(
            tuple(cast(int, entry) for entry in cast(Sequence[object], row))
            for row in cast(Sequence[object], payload["representative_keys"])
        )
        inverses = tuple(
            next(
                candidate
                for candidate in range(len(table))
                if table[element][candidate] == identity and table[candidate][element] == identity
            )
            for element in range(len(table))
        )
        return cls(
            table,
            identity,
            classes,
            representatives,
            inverses,
            {key: index for index, key in enumerate(representatives)},
        )

    @property
    def size(self) -> int:
        return len(self.table)

    def multiply(self, left: int, right: int) -> int:
        return self.table[left][right]

    def inverse(self, value: int) -> int:
        return self.inverses[value]

    def conjugate(self, value: int, by: int) -> int:
        return self.multiply(self.multiply(self.inverse(by), value), by)

    def conjugate_left(self, value: int, by: int) -> int:
        return self.multiply(self.multiply(by, value), self.inverse(by))

    def product(self, entries: Sequence[int]) -> int:
        result = self.identity
        for entry in entries:
            result = self.multiply(result, entry)
        return result

    def canonicalize(self, entries: Sequence[int]) -> tuple[tuple[int, ...], int, int]:
        best: tuple[int, ...] | None = None
        best_by = -1
        for by in range(self.size):
            candidate = tuple(self.conjugate(entry, by) for entry in entries)
            if best is None or candidate < best:
                best = candidate
                best_by = by
        assert best is not None
        try:
            index = self.representative_index[best]
        except KeyError as exc:
            raise _fail("operation leaves the certified Nielsen class") from exc
        return best, best_by, index

    def canonical_lower(self, entries: Sequence[int]) -> tuple[tuple[int, ...], int]:
        best: tuple[int, ...] | None = None
        best_by = -1
        for by in range(self.size):
            candidate = tuple(self.conjugate(entry, by) for entry in entries)
            if best is None or candidate < best:
                best = candidate
                best_by = by
        assert best is not None
        return best, best_by


Move = tuple[int, bool]
Generator = tuple[str, tuple[Move, ...]]


def _moves_payload(moves: Sequence[Move]) -> list[dict[str, object]]:
    return [{"index": index, "inverse": inverse} for index, inverse in moves]


def _parse_moves(value: object, *, arity: int, field: str) -> tuple[Move, ...]:
    result: list[Move] = []
    for position, raw_move in enumerate(_sequence(value, field=field)):
        move = _mapping(raw_move, field=f"{field}[{position}]")
        _exact_keys(move, {"index", "inverse"}, record=f"{field}[{position}]")
        index = _integer(move["index"], field=f"{field}[{position}].index", minimum=0)
        inverse = _boolean(move["inverse"], field=f"{field}[{position}].inverse")
        if index + 1 >= arity:
            raise _fail(f"{field}[{position}] addresses a nonexistent braid slot")
        result.append((index, inverse))
    return tuple(result)


def _parse_action(
    value: object, context: _TableContext, *, field: str
) -> tuple[str, tuple[Generator, ...]]:
    action = _mapping(value, field=field)
    _exact_keys(action, {"mode", "generators", "hurwitz_convention"}, record=field)
    mode = _string(action["mode"], field=f"{field}.mode")
    if mode not in {"full", "pure", "explicit"}:
        raise _fail(f"{field}.mode is unsupported")
    if action["hurwitz_convention"] != RIGHT_HURWITZ_CONVENTION:
        raise _fail(f"{field} Hurwitz convention mismatch")
    generators: list[Generator] = []
    for position, raw_generator in enumerate(
        _sequence(action["generators"], field=f"{field}.generators")
    ):
        generator = _mapping(raw_generator, field=f"{field}.generators[{position}]")
        _exact_keys(
            generator,
            {"name", "moves"},
            record=f"{field}.generators[{position}]",
        )
        name = _string(generator["name"], field=f"{field}.generators[{position}].name")
        moves = _parse_moves(
            generator["moves"],
            arity=len(context.classes),
            field=f"{field}.generators[{position}].moves",
        )
        generators.append((name, moves))
    if len({name for name, _ in generators}) != len(generators):
        raise _fail(f"{field} generator names are not unique")
    return mode, tuple(generators)


def _apply_move(context: _TableContext, entries: Sequence[int], move: Move) -> tuple[int, ...]:
    index, inverse = move
    result = list(entries)
    left = entries[index]
    right = entries[index + 1]
    if inverse:
        result[index] = right
        result[index + 1] = context.conjugate(left, right)
    else:
        result[index] = context.conjugate_left(right, left)
        result[index + 1] = left
    transformed = tuple(result)
    if context.product(transformed) != context.product(entries):
        raise _fail("portable Hurwitz move lost the tuple product")
    return transformed


def _apply_word(
    context: _TableContext, entries: Sequence[int], moves: Sequence[Move]
) -> tuple[int, ...]:
    result = tuple(entries)
    for move in moves:
        result = _apply_move(context, result, move)
    return result


def _inverse_word(moves: Sequence[Move]) -> tuple[Move, ...]:
    return tuple((index, not inverse) for index, inverse in reversed(moves))


@dataclass(frozen=True)
class _ActionReplay:
    generators: tuple[Generator, ...]
    forward: tuple[tuple[int, ...], ...]
    backward: tuple[tuple[int, ...], ...]
    conjugators: tuple[tuple[int, ...], ...]


def _compute_action(context: _TableContext, generators: tuple[Generator, ...]) -> _ActionReplay:
    forward: list[tuple[int, ...]] = []
    backward: list[tuple[int, ...]] = []
    conjugators: list[tuple[int, ...]] = []
    expected_vertices = list(range(len(context.representatives)))
    for name, moves in generators:
        targets: list[int] = []
        inverse_targets: list[int] = []
        by_indices: list[int] = []
        for representative in context.representatives:
            raw = _apply_word(context, representative, moves)
            _, by, target = context.canonicalize(raw)
            targets.append(target)
            by_indices.append(by)
            inverse_raw = _apply_word(context, representative, _inverse_word(moves))
            _, _, inverse_target = context.canonicalize(inverse_raw)
            inverse_targets.append(inverse_target)
        if sorted(targets) != expected_vertices or sorted(inverse_targets) != expected_vertices:
            raise _fail(f"portable braid generator {name!r} is not a permutation")
        if any(inverse_targets[target] != source for source, target in enumerate(targets)):
            raise _fail(f"portable braid generator {name!r} does not cancel its inverse")
        forward.append(tuple(targets))
        backward.append(tuple(inverse_targets))
        conjugators.append(tuple(by_indices))
    return _ActionReplay(generators, tuple(forward), tuple(backward), tuple(conjugators))


def _action_result(replay: _ActionReplay) -> dict[str, object]:
    return {
        "generators": [
            {
                "name": name,
                "forward": list(replay.forward[index]),
                "inverse": list(replay.backward[index]),
                "canonicalizing_conjugators": list(replay.conjugators[index]),
            }
            for index, (name, _) in enumerate(replay.generators)
        ]
    }


def _component_partition(replay: _ActionReplay, vertex_count: int) -> tuple[tuple[int, ...], ...]:
    unseen = set(range(vertex_count))
    result: list[tuple[int, ...]] = []
    while unseen:
        root = min(unseen)
        reached = {root}
        queue = deque((root,))
        while queue:
            source = queue.popleft()
            for generator_index in range(len(replay.generators)):
                for targets in (replay.forward[generator_index], replay.backward[generator_index]):
                    target = targets[source]
                    if target not in reached:
                        reached.add(target)
                        queue.append(target)
        unseen -= reached
        result.append(tuple(sorted(reached)))
    return tuple(result)


def _straight_transform(context: _TableContext, entries: Sequence[int]) -> tuple[int, ...]:
    prefix = context.identity
    result: list[int] = []
    for entry in entries:
        result.append(context.conjugate_left(context.inverse(entry), prefix))
        prefix = context.multiply(prefix, entry)
    transformed = tuple(result)
    if context.product(transformed) != context.identity:
        raise _fail("portable straight-real transform lost product one")
    return transformed


def _real_structure_result(
    context: _TableContext, inputs: Mapping[str, object]
) -> dict[str, object]:
    _exact_keys(
        inputs,
        {"kind", "name", "convention", "signed_slots"},
        record="real_structure inputs",
    )
    kind = _string(inputs["kind"], field="real_structure kind")
    _string(inputs["name"], field="real_structure name")
    _string(inputs["convention"], field="real_structure convention")
    slots: tuple[tuple[int, bool], ...] | None
    if kind == "straight":
        if inputs["signed_slots"] is not None:
            raise _fail("straight real structure cannot carry signed slots")
        slots = None
    elif kind == "signed_slots":
        parsed: list[tuple[int, bool]] = []
        for index, raw_slot in enumerate(
            _sequence(inputs["signed_slots"], field="real_structure signed_slots")
        ):
            slot = _sequence(raw_slot, field=f"real_structure signed_slots[{index}]")
            if len(slot) != 2:
                raise _fail("each signed real slot must contain index and inversion flag")
            parsed.append(
                (
                    _integer(slot[0], field=f"real_structure signed_slots[{index}][0]", minimum=0),
                    _boolean(slot[1], field=f"real_structure signed_slots[{index}][1]"),
                )
            )
        if len(parsed) != len(context.classes) or sorted(index for index, _ in parsed) != list(
            range(len(context.classes))
        ):
            raise _fail("signed real slots must use every tuple position exactly once")
        slots = tuple(parsed)
    else:
        raise _fail("unsupported portable real-structure transform")
    mapping: list[int] = []
    for representative in context.representatives:
        if slots is None:
            transformed = _straight_transform(context, representative)
        else:
            transformed = tuple(
                context.inverse(representative[index]) if inverse else representative[index]
                for index, inverse in slots
            )
        if context.product(transformed) != context.identity:
            raise _fail("real-structure transform does not preserve product one")
        _, _, target = context.canonicalize(transformed)
        mapping.append(target)
    if sorted(mapping) != list(range(len(mapping))):
        raise _fail("portable real structure is not a permutation")
    if any(mapping[mapping[index]] != index for index in range(len(mapping))):
        raise _fail("portable real structure is not involutive")
    return {
        "mapping": mapping,
        "fixed_indices": [index for index, target in enumerate(mapping) if index == target],
    }


def _is_real(
    context: _TableContext,
    entries: Sequence[int],
    fiber_conjugation: int,
) -> bool:
    if context.multiply(fiber_conjugation, fiber_conjugation) != context.identity:
        return False
    target = _straight_transform(context, entries)
    actual = tuple(context.conjugate_left(entry, fiber_conjugation) for entry in entries)
    return actual == target


def _real_census_result(context: _TableContext, inputs: Mapping[str, object]) -> dict[str, object]:
    _exact_keys(inputs, {"fiber_mode", "fiber_index", "up_to_inner"}, record="real_census inputs")
    mode = _string(inputs["fiber_mode"], field="real_census fiber_mode")
    up_to_inner = _boolean(inputs["up_to_inner"], field="real_census up_to_inner")
    if mode == "all_involutions":
        if inputs["fiber_index"] is not None:
            raise _fail("all-involutions census cannot carry a fixed fiber index")
        fibers = tuple(
            value
            for value in range(context.size)
            if context.multiply(value, value) == context.identity
        )
    elif mode == "fixed":
        fiber = _integer(inputs["fiber_index"], field="real_census fiber_index", minimum=0)
        if fiber >= context.size:
            raise _fail("real_census fiber index is out of range")
        if context.multiply(fiber, fiber) != context.identity:
            raise _fail("real_census fixed fiber element is not an involution")
        fibers = (fiber,)
    else:
        raise _fail("unsupported real_census fiber mode")
    tuple_conjugators = range(context.size) if up_to_inner else (context.identity,)
    witnesses: list[dict[str, object]] = []
    for representative_index, representative in enumerate(context.representatives):
        found: tuple[int, int] | None = None
        for by in tuple_conjugators:
            concrete = tuple(context.conjugate(entry, by) for entry in representative)
            for fiber in fibers:
                if _is_real(context, concrete, fiber):
                    found = (fiber, by)
                    break
            if found is not None:
                break
        if found is not None:
            witnesses.append(
                {
                    "representative_index": representative_index,
                    "fiber_conjugation_index": found[0],
                    "tuple_conjugator_index": found[1],
                }
            )
    return {"witnesses": witnesses, "count": len(witnesses)}


def _parse_component(
    value: object,
    *,
    partitions: tuple[tuple[int, ...], ...],
    field: str,
) -> tuple[int, ...]:
    vertices = _integer_tuple(value, field=field)
    if vertices != tuple(sorted(set(vertices))):
        raise _fail(f"{field} must be sorted and duplicate-free")
    if vertices not in partitions:
        raise _fail(f"{field} is not one exact component of the certified action")
    return vertices


def _reduced_result(
    context: _TableContext,
    replay: _ActionReplay,
    partitions: tuple[tuple[int, ...], ...],
    inputs: Mapping[str, object],
) -> dict[str, object]:
    _exact_keys(inputs, {"action", "component_vertices", "symmetries"}, record="reduced inputs")
    component = _parse_component(
        inputs["component_vertices"], partitions=partitions, field="reduced component_vertices"
    )
    symmetries: list[tuple[str, tuple[int, ...]]] = []
    for index, raw_symmetry in enumerate(
        _sequence(inputs["symmetries"], field="reduced symmetries")
    ):
        symmetry = _mapping(raw_symmetry, field=f"reduced symmetries[{index}]")
        _exact_keys(symmetry, {"name", "mapping"}, record=f"reduced symmetries[{index}]")
        name = _string(symmetry["name"], field=f"reduced symmetries[{index}].name")
        mapping = _integer_tuple(symmetry["mapping"], field=f"reduced symmetries[{index}].mapping")
        if len(mapping) != len(component) or sorted(mapping) != list(range(len(component))):
            raise _fail(f"reduced symmetry {name!r} is not a component permutation")
        symmetries.append((name, mapping))
    if not symmetries:
        raise _fail("reduced quotient needs at least one explicit symmetry")
    unseen = set(range(len(component)))
    blocks: list[tuple[int, ...]] = []
    for_inverse: list[tuple[int, ...]] = []
    for _, mapping in symmetries:
        inverse = [0] * len(mapping)
        for source, target in enumerate(mapping):
            inverse[target] = source
        for_inverse.append(tuple(inverse))
    while unseen:
        root = min(unseen)
        reached = {root}
        queue = deque((root,))
        while queue:
            source = queue.popleft()
            for symmetry_index, (_, mapping) in enumerate(symmetries):
                for target in (mapping[source], for_inverse[symmetry_index][source]):
                    if target not in reached:
                        reached.add(target)
                        queue.append(target)
        unseen -= reached
        blocks.append(tuple(component[local] for local in sorted(reached)))
    blocks.sort()
    block_of = {vertex: block_index for block_index, block in enumerate(blocks) for vertex in block}
    edges: set[tuple[int, str, int]] = set()
    for block_index, block in enumerate(blocks):
        for vertex in block:
            for generator_index, (name, _) in enumerate(replay.generators):
                edges.add((block_index, name, block_of[replay.forward[generator_index][vertex]]))
    return {
        "blocks": [list(block) for block in blocks],
        "quotient_edges": [list(edge) for edge in sorted(edges)],
    }


def _cusps_result(
    context: _TableContext,
    replay: _ActionReplay,
    partitions: tuple[tuple[int, ...], ...],
    inputs: Mapping[str, object],
) -> dict[str, object]:
    _exact_keys(
        inputs,
        {"action", "component_vertices", "operator_name", "operator_word"},
        record="cusps inputs",
    )
    component = _parse_component(
        inputs["component_vertices"], partitions=partitions, field="cusps component_vertices"
    )
    _string(inputs["operator_name"], field="cusps operator_name")
    moves = _parse_moves(
        inputs["operator_word"], arity=len(context.classes), field="cusps operator_word"
    )
    local_of = {vertex: index for index, vertex in enumerate(component)}
    mapping: list[int] = []
    for vertex in component:
        raw = _apply_word(context, context.representatives[vertex], moves)
        _, _, target = context.canonicalize(raw)
        if target not in local_of:
            raise _fail("cusp operator leaves the certified component")
        mapping.append(local_of[target])
    if sorted(mapping) != list(range(len(mapping))):
        raise _fail("cusp operator is not a component permutation")
    unseen = set(range(len(mapping)))
    cycles: list[dict[str, object]] = []
    while unseen:
        start = min(unseen)
        cycle: list[int] = []
        current = start
        while current not in cycle:
            cycle.append(current)
            current = mapping[current]
        if current != start:
            raise _fail("cusp walk entered a prior cycle")
        unseen -= set(cycle)
        cycles.append({"vertices": cycle, "width": len(cycle)})
    return {
        "mapping": mapping,
        "cusps": cycles,
        "widths": [cast(int, cycle["width"]) for cycle in cycles],
    }


def _parse_collisions(value: object, *, arity: int) -> tuple[tuple[int, int], ...]:
    collisions: list[tuple[int, int]] = []
    for index, raw_collision in enumerate(_sequence(value, field="boundary collisions")):
        collision = _mapping(raw_collision, field=f"boundary collisions[{index}]")
        _exact_keys(collision, {"left", "right"}, record=f"boundary collisions[{index}]")
        left = _integer(collision["left"], field=f"boundary collisions[{index}].left", minimum=0)
        right = _integer(collision["right"], field=f"boundary collisions[{index}].right", minimum=0)
        if left >= arity or right >= arity or right != (left + 1) % arity:
            raise _fail("boundary collision is not an oriented adjacent pair")
        collisions.append((left, right))
    if not collisions or len(set(collisions)) != len(collisions):
        raise _fail("boundary collisions must be nonempty and distinct")
    return tuple(collisions)


def _boundary_stratum(
    context: _TableContext,
    representative: tuple[int, ...],
    collision: tuple[int, int],
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], int]:
    left_slot, right_slot = collision
    merged = context.multiply(representative[left_slot], representative[right_slot])
    if right_slot == 0:
        lower = (*representative[1:-1], merged)
    else:
        lower = (*representative[:left_slot], merged, *representative[right_slot + 1 :])
    if context.product(lower) != context.identity:
        raise _fail("portable boundary collision lost product one")
    canonical, by = context.canonical_lower(lower)
    merged_class = tuple(sorted({context.conjugate(merged, h) for h in range(context.size)}))
    return (canonical, merged_class), by


def _stratum_payload(stratum: tuple[tuple[int, ...], tuple[int, ...]]) -> dict[str, object]:
    return {"lower_tuple_key": list(stratum[0]), "merged_class_key": list(stratum[1])}


def _boundary_result(
    context: _TableContext,
    partitions: tuple[tuple[int, ...], ...],
    inputs: Mapping[str, object],
) -> dict[str, object]:
    _exact_keys(
        inputs,
        {"action", "component_vertices", "collisions", "inner_conjugacy_convention"},
        record="boundary inputs",
    )
    if inputs["inner_conjugacy_convention"] != INNER_CONJUGACY_CONVENTION:
        raise _fail("boundary inner-conjugacy convention mismatch")
    component = _parse_component(
        inputs["component_vertices"], partitions=partitions, field="boundary component_vertices"
    )
    collisions = _parse_collisions(inputs["collisions"], arity=len(context.classes))
    raw: list[tuple[int, tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]], int]] = []
    strata_set: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()
    for collision in collisions:
        for vertex in component:
            stratum, by = _boundary_stratum(context, context.representatives[vertex], collision)
            raw.append((vertex, collision, stratum, by))
            strata_set.add(stratum)
    strata = tuple(sorted(strata_set))
    stratum_index = {stratum: index for index, stratum in enumerate(strata)}
    collision_index = {collision: index for index, collision in enumerate(collisions)}
    matrix = [[0 for _ in strata] for _ in collisions]
    witnesses: list[dict[str, object]] = []
    for vertex, collision, stratum, by in raw:
        matrix[collision_index[collision]][stratum_index[stratum]] += 1
        witnesses.append(
            {
                "source_vertex": vertex,
                "collision": {"left": collision[0], "right": collision[1]},
                "stratum": _stratum_payload(stratum),
                "conjugator_index": by,
            }
        )
    return {
        "strata": [_stratum_payload(stratum) for stratum in strata],
        "matrix": matrix,
        "witnesses": witnesses,
        "total_incidences": sum(sum(row) for row in matrix),
    }


def _expected_result(
    operation: str,
    context: _TableContext,
    inputs: Mapping[str, object],
) -> dict[str, object]:
    if operation == REAL_STRUCTURE:
        return _real_structure_result(context, inputs)
    if operation == REAL_CENSUS:
        return _real_census_result(context, inputs)
    if operation == BRAID_ACTION:
        _exact_keys(inputs, {"action"}, record="braid_action inputs")
        _, generators = _parse_action(inputs["action"], context, field="braid_action action")
        return _action_result(_compute_action(context, generators))

    if operation == COMPONENTS:
        _exact_keys(inputs, {"action", "selected_component"}, record="components inputs")
    elif operation == REDUCED:
        # Operation-specific validation below also checks all fields.
        pass
    elif operation in (CUSPS, BOUNDARY):
        pass
    else:
        raise _fail(f"unsupported portable Hurwitz operation {operation!r}")

    _, generators = _parse_action(inputs["action"], context, field=f"{operation} action")
    replay = _compute_action(context, generators)
    partitions = _component_partition(replay, len(context.representatives))
    if operation == COMPONENTS:
        selected_raw = inputs["selected_component"]
        if selected_raw is not None:
            _parse_component(
                selected_raw, partitions=partitions, field="components selected_component"
            )
        return {"components": [list(component) for component in partitions]}
    if operation == REDUCED:
        return _reduced_result(context, replay, partitions, inputs)
    if operation == CUSPS:
        return _cusps_result(context, replay, partitions, inputs)
    return _boundary_result(context, partitions, inputs)


@dataclass(frozen=True)
class HurwitzOperationCertificate(ContentAddressedCertificate):
    """Self-contained finite replay certificate for one public operation."""

    operation: str
    nielsen_certificate: FrozenMap = field(default_factory=FrozenMap)
    inputs: FrozenMap = field(default_factory=FrozenMap)
    result: FrozenMap = field(default_factory=FrozenMap)

    layer: ClassVar[CertificateLayer] = CertificateLayer.VERIFICATION
    schema_version: ClassVar[str] = PORTABLE_OPERATION_SCHEMA

    def __post_init__(self) -> None:
        if self.operation not in PORTABLE_OPERATIONS:
            raise CertificateVerificationError(
                f"unsupported portable Hurwitz operation {self.operation!r}"
            )
        object.__setattr__(self, "nielsen_certificate", freeze_mapping(self.nielsen_certificate))
        object.__setattr__(self, "inputs", freeze_mapping(self.inputs))
        object.__setattr__(self, "result", freeze_mapping(self.result))

    @classmethod
    def create(
        cls,
        operation: str,
        *,
        nielsen_certificate: Mapping[str, object],
        inputs: Mapping[str, object],
        result: Mapping[str, object],
    ) -> HurwitzOperationCertificate:
        return cls(
            operation,
            freeze_mapping(nielsen_certificate),
            freeze_mapping(inputs),
            freeze_mapping(result),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer.value,
            "operation": self.operation,
            "nielsen_certificate": self.nielsen_certificate,
            "inputs": self.inputs,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> HurwitzOperationCertificate:
        allowed = {
            "schema_version",
            "layer",
            "operation",
            "nielsen_certificate",
            "inputs",
            "result",
            "certificate_id",
        }
        if set(value) != allowed:
            missing = sorted(allowed - set(value))
            extra = sorted(set(value) - allowed)
            raise CertificateVerificationError(
                f"portable Hurwitz certificate has noncanonical fields "
                f"(missing={missing}, unexpected={extra})"
            )
        if value["schema_version"] != cls.schema_version:
            raise CertificateVerificationError("unsupported portable Hurwitz schema")
        if value["layer"] != cls.layer.value:
            raise CertificateVerificationError("portable Hurwitz certificate has wrong layer")
        certificate = cls.create(
            _string(value["operation"], field="operation"),
            nielsen_certificate=_mapping(value["nielsen_certificate"], field="nielsen_certificate"),
            inputs=_mapping(value["inputs"], field="inputs"),
            result=_mapping(value["result"], field="result"),
        )
        expected = _string(value["certificate_id"], field="certificate_id")
        try:
            certificate.verify_integrity(expected)
        except ValueError as exc:
            raise CertificateVerificationError(
                "portable Hurwitz certificate content address mismatch"
            ) from exc
        return certificate

    def verify(self) -> bool:
        return verify_hurwitz_operation_payload(self.to_canonical())


def verify_hurwitz_operation_payload(payload: Mapping[str, object]) -> bool:
    """Strictly and independently replay one canonical operation payload."""

    try:
        _exact_keys(
            payload,
            {"schema_version", "layer", "operation", "nielsen_certificate", "inputs", "result"},
            record="portable Hurwitz operation certificate",
        )
        if payload["schema_version"] != PORTABLE_OPERATION_SCHEMA:
            raise _fail("unsupported portable Hurwitz operation schema")
        if payload["layer"] != CertificateLayer.VERIFICATION.value:
            raise _fail("portable Hurwitz operation certificate has wrong layer")
        operation = _string(payload["operation"], field="operation")
        if operation not in PORTABLE_OPERATIONS:
            raise _fail(f"unsupported portable Hurwitz operation {operation!r}")
        nielsen = _strict_nielsen_payload(payload["nielsen_certificate"])
        context = _TableContext.from_nielsen(nielsen)
        inputs = _mapping(payload["inputs"], field="operation inputs")
        advertised = _mapping(payload["result"], field="operation result")
        expected = _expected_result(operation, context, inputs)
        if canonicalize(advertised) != canonicalize(expected):
            raise _fail(f"portable {operation} result does not replay exactly")
    except CertificateVerificationError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, StopIteration) as exc:
        raise CertificateVerificationError(
            "malformed portable Hurwitz operation certificate"
        ) from exc
    return True


def _nielsen_payload(nielsen_class: NielsenClass) -> dict[str, object]:
    if nielsen_class.certificate is None:
        raise CertificateVerificationError(
            "portable downstream verification requires a computed-complete Nielsen certificate"
        )
    nielsen_class.verify()
    return nielsen_class.certificate.to_dict()


def _word_from_object(word: object) -> list[dict[str, object]]:
    return [{"index": move.index, "inverse": move.inverse} for move in cast(Any, word)]


def _action_from_object(action: object) -> dict[str, object]:
    actual = cast(Any, action)
    return {
        "mode": actual.mode,
        "generators": [
            {"name": generator.name, "moves": _word_from_object(generator.word)}
            for generator in actual.generators
        ],
        "hurwitz_convention": RIGHT_HURWITZ_CONVENTION,
    }


def _action_result_from_object(action: object) -> dict[str, object]:
    actual = cast(Any, action)
    by_generator: dict[str, list[int]] = {generator.name: [] for generator in actual.generators}
    for edge in actual.edge_certificates:
        by_generator[edge.generator_name].append(edge.canonicalizing_conjugator_index)
    return {
        "generators": [
            {
                "name": generator.name,
                "forward": list(actual._forward[generator.name]),
                "inverse": list(actual._backward[generator.name]),
                "canonicalizing_conjugators": by_generator[generator.name],
            }
            for generator in actual.generators
        ]
    }


def _component_partitions_from_object(collection: object) -> list[list[int]]:
    return [list(component.vertex_indices) for component in cast(Any, collection)]


def operation_certificate_for(value: object) -> HurwitzOperationCertificate:
    """Build the portable specialized receipt for a supported public result."""

    # Local imports keep the discovery modules independent of this transport layer.
    from .boundary import BoundaryIncidence
    from .braid import BraidAction, ComponentCollection, HurwitzComponent
    from .geometry import CuspData, ReducedComponent
    from .real import RealCensus, RealStructure

    if isinstance(value, BraidAction):
        certificate = HurwitzOperationCertificate.create(
            BRAID_ACTION,
            nielsen_certificate=_nielsen_payload(value.nielsen_class),
            inputs={"action": _action_from_object(value)},
            result=_action_result_from_object(value),
        )
    elif isinstance(value, (ComponentCollection, HurwitzComponent)):
        if isinstance(value, HurwitzComponent):
            action = value.action
            collection = action.components()
            selected: object = list(value.vertex_indices)
        else:
            action = value.action
            collection = value
            selected = None
        certificate = HurwitzOperationCertificate.create(
            COMPONENTS,
            nielsen_certificate=_nielsen_payload(action.nielsen_class),
            inputs={
                "action": _action_from_object(action),
                "selected_component": selected,
            },
            result={"components": _component_partitions_from_object(collection)},
        )
    elif isinstance(value, RealStructure):
        if value.portable_transform is None:
            raise CertificateVerificationError(
                "caller-supplied real transforms are context-bound; use the straight or "
                "signed-slots constructor for portable verification"
            )
        kind, signed_slots = value.portable_transform
        certificate = HurwitzOperationCertificate.create(
            REAL_STRUCTURE,
            nielsen_certificate=_nielsen_payload(value.nielsen_class),
            inputs={
                "kind": kind,
                "name": value.name,
                "convention": value.convention,
                "signed_slots": (
                    None
                    if signed_slots is None
                    else [[index, inverse] for index, inverse in signed_slots]
                ),
            },
            result={
                "mapping": list(value.mapping),
                "fixed_indices": list(value.fixed_indices()),
            },
        )
    elif isinstance(value, RealCensus):
        certificate = HurwitzOperationCertificate.create(
            REAL_CENSUS,
            nielsen_certificate=_nielsen_payload(value.nielsen_class),
            inputs={
                "fiber_mode": value.fiber_mode,
                "fiber_index": value.fiber_index,
                "up_to_inner": value.up_to_inner,
            },
            result={
                "witnesses": [
                    {
                        "representative_index": witness.representative_index,
                        "fiber_conjugation_index": value.nielsen_class.context.index(
                            witness.fiber_conjugation
                        ),
                        "tuple_conjugator_index": value.nielsen_class.context.index(
                            witness.tuple_conjugator
                        ),
                    }
                    for witness in value.witnesses
                ],
                "count": len(value.witnesses),
            },
        )
    elif isinstance(value, ReducedComponent):
        action = value.component.action
        certificate = HurwitzOperationCertificate.create(
            REDUCED,
            nielsen_certificate=_nielsen_payload(action.nielsen_class),
            inputs={
                "action": _action_from_object(action),
                "component_vertices": list(value.component.vertex_indices),
                "symmetries": [
                    {"name": symmetry.name, "mapping": list(symmetry.mapping)}
                    for symmetry in value.certificate.symmetries
                ],
            },
            result={
                "blocks": [list(block) for block in value.blocks],
                "quotient_edges": [list(edge) for edge in value.quotient_edges],
            },
        )
    elif isinstance(value, CuspData):
        action = value.component.action
        certificate = HurwitzOperationCertificate.create(
            CUSPS,
            nielsen_certificate=_nielsen_payload(action.nielsen_class),
            inputs={
                "action": _action_from_object(action),
                "component_vertices": list(value.component.vertex_indices),
                "operator_name": value.certificate.operator_name,
                "operator_word": _word_from_object(value.certificate.operator_word),
            },
            result={
                "mapping": list(value.certificate.mapping),
                "cusps": [{"vertices": list(cusp.vertices), "width": cusp.width} for cusp in value],
                "widths": list(value.widths),
            },
        )
    elif isinstance(value, BoundaryIncidence):
        action = value.component.action
        certificate = HurwitzOperationCertificate.create(
            BOUNDARY,
            nielsen_certificate=_nielsen_payload(action.nielsen_class),
            inputs={
                "action": _action_from_object(action),
                "component_vertices": list(value.component.vertex_indices),
                "collisions": [
                    {"left": collision.left, "right": collision.right}
                    for collision in value.collisions
                ],
                "inner_conjugacy_convention": INNER_CONJUGACY_CONVENTION,
            },
            result={
                "strata": [
                    {
                        "lower_tuple_key": list(stratum.lower_tuple_key),
                        "merged_class_key": list(stratum.merged_class_key),
                    }
                    for stratum in value.strata
                ],
                "matrix": [list(row) for row in value.matrix],
                "witnesses": [
                    {
                        "source_vertex": witness.source_vertex,
                        "collision": {
                            "left": witness.collision.left,
                            "right": witness.collision.right,
                        },
                        "stratum": {
                            "lower_tuple_key": list(witness.stratum.lower_tuple_key),
                            "merged_class_key": list(witness.stratum.merged_class_key),
                        },
                        "conjugator_index": witness.conjugator_index,
                    }
                    for witness in value.witnesses
                ],
                "total_incidences": value.total_incidences,
            },
        )
    else:
        raise TypeError(f"{type(value).__qualname__} has no portable Hurwitz operation receipt")
    certificate.verify()
    return certificate


__all__ = [
    "BOUNDARY",
    "BRAID_ACTION",
    "COMPONENTS",
    "CUSPS",
    "PORTABLE_OPERATIONS",
    "PORTABLE_OPERATION_SCHEMA",
    "REAL_CENSUS",
    "REAL_STRUCTURE",
    "REDUCED",
    "HurwitzOperationCertificate",
    "operation_certificate_for",
    "verify_hurwitz_operation_payload",
]
