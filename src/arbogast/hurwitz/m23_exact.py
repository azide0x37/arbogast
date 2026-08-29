"""Public typed loader and exact certificate for the compact M23 Hurwitz fixture.

The finite replay itself deliberately uses only the Python standard library.  It does
not call GAP, rerun discovery, or trust a transcript.  Checked permutations, Schreier
witnesses, braid transitions, completeness accounting, and real-action witnesses are
replayed exactly before :class:`M23ExactDataset` is constructed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import ClassVar, TypeAlias, cast

from arbogast.cert import (
    CertificateLayer,
    ClaimBinding,
    ContentAddressedCertificate,
    FrozenMap,
    VerificationCertificate,
    VerifierRegistry,
    canonicalize,
    freeze_mapping,
    validate_content_address,
)
from arbogast.claims import (
    Claim,
    ClaimGraph,
    ClaimKind,
    Derivation,
    EpistemicStatus,
    FormalStatement,
    claim_boundary_hash,
)
from arbogast.core.canonical import _parse_decimal_integer

DEGREE = 23
IDENTITY = tuple(range(DEGREE))
DATASET_SCHEMA = "arbogast.example.m23-real-component.dataset/v2"
MANIFEST_SCHEMA = "arbogast.example.m23-real-component.manifest/v2"
M23_EXACT_CERTIFICATE_SCHEMA = "arbogast.hurwitz.m23-exact/v1"
M23_EXACT_VERIFIER = "hurwitz.m23_exact"
M23_GRAPH_ID = "m23_236_exact_inner_nielsen_class"

Permutation: TypeAlias = tuple[int, ...]
NielsenTuple: TypeAlias = tuple[Permutation, Permutation, Permutation, Permutation]

# GAP 4.16 MathieuGroup(23), pinned independently of fixture-controlled fields.
STANDARD_M23_GENERATORS_ONE_BASED = (
    (*tuple(range(2, 24)), 1),
    (1, 2, 17, 13, 4, 6, 9, 18, 3, 7, 12, 23, 14, 19, 20, 15, 10, 11, 5, 22, 16, 21, 8),
)
STANDARD_M23_GENERATORS = tuple(
    tuple(image - 1 for image in generator) for generator in STANDARD_M23_GENERATORS_ONE_BASED
)

EXPECTED_CLASS_CYCLES = {
    "2A": (1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2),
    "3A": (1, 1, 1, 1, 1, 3, 3, 3, 3, 3, 3),
    "6A": (1, 2, 2, 3, 3, 6, 6),
}
EXPECTED_CLASS_ORDERS = {"2A": 2, "3A": 3, "6A": 6}
EXPECTED_PASSPORT = ("2A", "3A", "6A", "2A")
EXPECTED_PURE_WORDS = (
    (1, 1),
    (-1, 2, 2, 1),
    (-1, -2, 3, 3, 2, 1),
    (2, 2),
    (-2, 3, 3, 2),
    (3, 3),
)
EXPECTED_PURE_NAMES = ("beta12", "beta13", "beta14", "beta23", "beta24", "beta34")


class M23ExactVerificationError(ValueError):
    """Raised when any exact M23 dataset invariant or witness fails."""


# Compatibility within the finite replay implementation.  The public name above is
# intentionally dataset-specific and does not suggest a generic trust wrapper.
FixtureVerificationError = M23ExactVerificationError


def load_strict_json(raw: bytes, label: str) -> object:
    """Decode JSON while rejecting duplicate object keys and non-finite numbers."""

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise FixtureVerificationError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise FixtureVerificationError(f"{label} contains non-finite number {value}")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_int=_parse_decimal_integer,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as error:
        raise FixtureVerificationError(f"{label} is not UTF-8") from error


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise FixtureVerificationError(f"{label} must be a string-keyed object")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FixtureVerificationError(f"{label} must be an array")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FixtureVerificationError(f"{label} must be an integer")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_permutation(value: object, label: str) -> Permutation:
    images = _sequence(value, label)
    if len(images) != DEGREE:
        raise FixtureVerificationError(f"{label} must have exactly {DEGREE} images")
    one_based = tuple(_integer(image, f"{label}[{index}]") for index, image in enumerate(images))
    if sorted(one_based) != list(range(1, DEGREE + 1)):
        raise FixtureVerificationError(f"{label} is not a permutation of 1..{DEGREE}")
    return tuple(image - 1 for image in one_based)


def multiply(left: Permutation, right: Permutation) -> Permutation:
    """Compose GAP right-action permutations: a point moves by left, then right."""

    return tuple(right[left[point]] for point in range(DEGREE))


def inverse(value: Permutation) -> Permutation:
    result = [0] * DEGREE
    for source, target in enumerate(value):
        result[target] = source
    return tuple(result)


def product(values: Sequence[Permutation]) -> Permutation:
    result = IDENTITY
    for value in values:
        result = multiply(result, value)
    return result


def conjugate(value: Permutation, by: Permutation) -> Permutation:
    """Return ``value^by = by^-1 * value * by`` in GAP notation."""

    return multiply(multiply(inverse(by), value), by)


def cycle_lengths(value: Permutation) -> tuple[int, ...]:
    unseen = set(range(DEGREE))
    result: list[int] = []
    while unseen:
        start = min(unseen)
        length = 0
        point = start
        while point in unseen:
            unseen.remove(point)
            length += 1
            point = value[point]
        result.append(length)
    return tuple(sorted(result))


def permutation_order(value: Permutation) -> int:
    result = 1
    for length in cycle_lengths(value):
        result = math.lcm(result, length)
    return result


def _moves(generators: Sequence[Permutation]) -> tuple[Permutation, ...]:
    return tuple(dict.fromkeys((*generators, *(inverse(item) for item in generators))))


@dataclass(frozen=True)
class SchreierLevel:
    base: int
    transversals: Mapping[int, Permutation]
    inverse_transversals: Mapping[int, Permutation]


@dataclass(frozen=True)
class SchreierChain:
    generators: tuple[Permutation, ...]
    levels: tuple[SchreierLevel, ...]
    order: int

    @property
    def orbit_sizes(self) -> tuple[int, ...]:
        return tuple(len(level.transversals) for level in self.levels)

    def contains(self, value: Permutation) -> bool:
        residue = value
        for level in self.levels:
            target = residue[level.base]
            transversal_inverse = level.inverse_transversals.get(target)
            if transversal_inverse is None:
                return False
            residue = multiply(residue, transversal_inverse)
        return residue == IDENTITY


def _point_orbit_transversals(
    base: int, generators: Sequence[Permutation]
) -> dict[int, Permutation]:
    transversals = {base: IDENTITY}
    queue = deque([base])
    while queue:
        point = queue.popleft()
        for move in _moves(generators):
            target = move[point]
            if target not in transversals:
                transversals[target] = multiply(transversals[point], move)
                queue.append(target)
    return transversals


def _point_stabilizer_generators(
    base: int, generators: Sequence[Permutation], transversals: Mapping[int, Permutation]
) -> tuple[Permutation, ...]:
    result: set[Permutation] = set()
    for point, transversal in transversals.items():
        for move in _moves(generators):
            target = move[point]
            schreier = multiply(multiply(transversal, move), inverse(transversals[target]))
            if schreier != IDENTITY:
                if schreier[base] != base:
                    raise FixtureVerificationError("Schreier point stabilizer is invalid")
                result.add(schreier)
    return tuple(sorted(result))


def schreier_chain(generators: Sequence[Permutation]) -> SchreierChain:
    original = tuple(dict.fromkeys(item for item in generators if item != IDENTITY))
    current = original
    fixed: list[int] = []
    levels: list[SchreierLevel] = []
    order = 1
    while current:
        base = next(
            (point for point in range(DEGREE) if any(item[point] != point for item in current)),
            None,
        )
        if base is None:
            break
        transversals = _point_orbit_transversals(base, current)
        order *= len(transversals)
        levels.append(
            SchreierLevel(
                base,
                transversals,
                {point: inverse(value) for point, value in transversals.items()},
            )
        )
        current = _point_stabilizer_generators(base, current, transversals)
        fixed.append(base)
        if any(any(item[point] != point for point in fixed) for item in current):
            raise FixtureVerificationError("Schreier stabilizer chain broke its fixed base")
    return SchreierChain(original, tuple(levels), order)


Action: TypeAlias = Callable[[Permutation, Permutation], Permutation]


def _action_orbit_transversals(
    start: Permutation,
    generators: Sequence[Permutation],
    action: Action,
) -> dict[Permutation, Permutation]:
    transversals = {start: IDENTITY}
    queue = deque([start])
    moves = _moves(generators)
    while queue:
        value = queue.popleft()
        for move in moves:
            target = action(value, move)
            if target not in transversals:
                transversals[target] = multiply(transversals[value], move)
                queue.append(target)
    return transversals


def _action_stabilizer_generators(
    start: Permutation,
    generators: Sequence[Permutation],
    action: Action,
    transversals: Mapping[Permutation, Permutation],
) -> tuple[Permutation, ...]:
    result: set[Permutation] = set()
    for value, transversal in transversals.items():
        for move in _moves(generators):
            target = action(value, move)
            schreier = multiply(multiply(transversal, move), inverse(transversals[target]))
            if schreier != IDENTITY:
                if action(start, schreier) != start:
                    raise FixtureVerificationError("Schreier action stabilizer is invalid")
                result.add(schreier)
    return tuple(sorted(result))


def _conjugacy_orbit_and_stabilizer(
    start: Permutation, generators: Sequence[Permutation]
) -> tuple[set[Permutation], tuple[Permutation, ...]]:
    transversals = _action_orbit_transversals(start, generators, conjugate)
    stabilizer = _action_stabilizer_generators(start, generators, conjugate, transversals)
    return set(transversals), stabilizer


def hurwitz_move(value: NielsenTuple, signed_generator: int) -> NielsenTuple:
    index = abs(signed_generator) - 1
    if index not in (0, 1, 2):
        raise FixtureVerificationError("braid generator index must be 1, 2, or 3")
    left, right = value[index], value[index + 1]
    result = list(value)
    if signed_generator > 0:
        result[index] = multiply(multiply(left, right), inverse(left))
        result[index + 1] = left
    else:
        result[index] = right
        result[index + 1] = multiply(multiply(inverse(right), left), right)
    return tuple(result)  # type: ignore[return-value]


def apply_braid_word(value: NielsenTuple, word: Sequence[int]) -> NielsenTuple:
    result = value
    for signed_generator in word:
        result = hurwitz_move(result, signed_generator)
    return result


def conjugate_tuple(value: NielsenTuple, by: Permutation) -> NielsenTuple:
    return tuple(conjugate(entry, by) for entry in value)  # type: ignore[return-value]


def straight_real_transform(value: NielsenTuple) -> NielsenTuple:
    prefix = IDENTITY
    result: list[Permutation] = []
    for entry in value:
        result.append(multiply(multiply(prefix, inverse(entry)), inverse(prefix)))
        prefix = multiply(prefix, entry)
    transformed = tuple(result)
    if product(transformed) != IDENTITY:
        raise FixtureVerificationError("straight real transform lost product one")
    return transformed  # type: ignore[return-value]


@dataclass(frozen=True)
class M23ExactVerification:
    dataset_sha256: str
    manifest_sha256: str
    group_order: int
    group_chain_orbits: tuple[int, ...]
    centralizer_order: int
    class_conjugacy_witnesses: int
    component_cardinality: int
    pure_generators: int
    directed_transitions: int
    c1_fixed: int
    inner_real_fixed: int
    forced_class6_candidates: int
    all_inner_orbits: int
    nongenerating_inner_orbits: int
    nongenerating_c1: int
    fixed_a_product_one_tuples: int
    weighted_inner_mass: str
    checks: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "group_order": self.group_order,
            "group_chain_orbits": self.group_chain_orbits,
            "centralizer_order": self.centralizer_order,
            "class_conjugacy_witnesses": self.class_conjugacy_witnesses,
            "component_cardinality": self.component_cardinality,
            "pure_generators": self.pure_generators,
            "directed_transitions": self.directed_transitions,
            "c1_fixed": self.c1_fixed,
            "inner_real_fixed": self.inner_real_fixed,
            "forced_class6_candidates": self.forced_class6_candidates,
            "all_inner_orbits": self.all_inner_orbits,
            "nongenerating_inner_orbits": self.nongenerating_inner_orbits,
            "nongenerating_c1": self.nongenerating_c1,
            "fixed_a_product_one_tuples": self.fixed_a_product_one_tuples,
            "weighted_inner_mass": self.weighted_inner_mass,
            "checks": self.checks,
        }


FixtureVerification = M23ExactVerification


_VERIFICATION_FIELDS = {
    "dataset_sha256",
    "manifest_sha256",
    "group_order",
    "group_chain_orbits",
    "centralizer_order",
    "class_conjugacy_witnesses",
    "component_cardinality",
    "pure_generators",
    "directed_transitions",
    "c1_fixed",
    "inner_real_fixed",
    "forced_class6_candidates",
    "all_inner_orbits",
    "nongenerating_inner_orbits",
    "nongenerating_c1",
    "fixed_a_product_one_tuples",
    "weighted_inner_mass",
    "checks",
}


def _sha256_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise M23ExactVerificationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    entries = _sequence(value, label)
    if any(not isinstance(entry, str) or not entry for entry in entries):
        raise M23ExactVerificationError(f"{label} must contain nonempty strings")
    return cast(tuple[str, ...], tuple(entries))


def _verification_from_dict(value: Mapping[str, object]) -> M23ExactVerification:
    if set(value) != _VERIFICATION_FIELDS:
        raise M23ExactVerificationError("M23 verification summary has noncanonical fields")
    chain_orbits = tuple(
        _integer(entry, f"group_chain_orbits[{index}]")
        for index, entry in enumerate(_sequence(value["group_chain_orbits"], "group_chain_orbits"))
    )
    weighted_mass = value["weighted_inner_mass"]
    if not isinstance(weighted_mass, str) or not weighted_mass:
        raise M23ExactVerificationError("weighted_inner_mass must be a nonempty string")
    return M23ExactVerification(
        dataset_sha256=_sha256_text(value["dataset_sha256"], "dataset_sha256"),
        manifest_sha256=_sha256_text(value["manifest_sha256"], "manifest_sha256"),
        group_order=_integer(value["group_order"], "group_order"),
        group_chain_orbits=chain_orbits,
        centralizer_order=_integer(value["centralizer_order"], "centralizer_order"),
        class_conjugacy_witnesses=_integer(
            value["class_conjugacy_witnesses"], "class_conjugacy_witnesses"
        ),
        component_cardinality=_integer(value["component_cardinality"], "component_cardinality"),
        pure_generators=_integer(value["pure_generators"], "pure_generators"),
        directed_transitions=_integer(value["directed_transitions"], "directed_transitions"),
        c1_fixed=_integer(value["c1_fixed"], "c1_fixed"),
        inner_real_fixed=_integer(value["inner_real_fixed"], "inner_real_fixed"),
        forced_class6_candidates=_integer(
            value["forced_class6_candidates"], "forced_class6_candidates"
        ),
        all_inner_orbits=_integer(value["all_inner_orbits"], "all_inner_orbits"),
        nongenerating_inner_orbits=_integer(
            value["nongenerating_inner_orbits"], "nongenerating_inner_orbits"
        ),
        nongenerating_c1=_integer(value["nongenerating_c1"], "nongenerating_c1"),
        fixed_a_product_one_tuples=_integer(
            value["fixed_a_product_one_tuples"], "fixed_a_product_one_tuples"
        ),
        weighted_inner_mass=weighted_mass,
        checks=_strings(value["checks"], "checks"),
    )


@dataclass(frozen=True)
class M23ExactCertificate(ContentAddressedCertificate):
    """Content-addressed summary emitted only after replaying the compact witnesses."""

    dataset_sha256: str
    manifest_sha256: str
    result: FrozenMap

    layer: ClassVar[CertificateLayer] = CertificateLayer.VERIFICATION
    schema_version: ClassVar[str] = M23_EXACT_CERTIFICATE_SCHEMA

    def __post_init__(self) -> None:
        _sha256_text(self.dataset_sha256, "dataset_sha256")
        _sha256_text(self.manifest_sha256, "manifest_sha256")
        object.__setattr__(self, "result", freeze_mapping(self.result))
        report = _verification_from_dict(self.result)
        if report.dataset_sha256 != self.dataset_sha256:
            raise M23ExactVerificationError("certificate dataset digest disagrees with its report")
        if report.manifest_sha256 != self.manifest_sha256:
            raise M23ExactVerificationError("certificate manifest digest disagrees with its report")

    @classmethod
    def create(cls, verification: M23ExactVerification) -> M23ExactCertificate:
        return cls(
            dataset_sha256=verification.dataset_sha256,
            manifest_sha256=verification.manifest_sha256,
            result=freeze_mapping(verification.to_dict()),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "layer": self.layer.value,
            "dataset_schema": DATASET_SCHEMA,
            "manifest_schema": MANIFEST_SCHEMA,
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> M23ExactCertificate:
        required = {
            "schema_version",
            "layer",
            "dataset_schema",
            "manifest_schema",
            "dataset_sha256",
            "manifest_sha256",
            "result",
            "certificate_id",
        }
        if set(value) != required:
            missing = sorted(required - set(value))
            unexpected = sorted(set(value) - required)
            raise M23ExactVerificationError(
                "M23 exact certificate has noncanonical fields "
                f"(missing={missing}, unexpected={unexpected})"
            )
        if value.get("schema_version") != cls.schema_version:
            raise M23ExactVerificationError("unsupported M23 exact certificate schema")
        if value.get("layer") != cls.layer.value:
            raise M23ExactVerificationError("M23 exact certificate has the wrong layer")
        if value.get("dataset_schema") != DATASET_SCHEMA:
            raise M23ExactVerificationError("M23 exact certificate dataset schema mismatch")
        if value.get("manifest_schema") != MANIFEST_SCHEMA:
            raise M23ExactVerificationError("M23 exact certificate manifest schema mismatch")
        certificate = cls(
            dataset_sha256=_sha256_text(value.get("dataset_sha256"), "dataset_sha256"),
            manifest_sha256=_sha256_text(value.get("manifest_sha256"), "manifest_sha256"),
            result=freeze_mapping(_mapping(value.get("result"), "result")),
        )
        expected_id = value["certificate_id"]
        if not isinstance(expected_id, str):
            raise M23ExactVerificationError("certificate_id must be a string")
        try:
            validate_content_address(expected_id, certificate.to_canonical())
        except ValueError as error:
            raise M23ExactVerificationError(
                "M23 exact certificate content address mismatch"
            ) from error
        return certificate

    def verify(self, dataset: M23ExactDataset) -> bool:
        """Require a fully replayed typed dataset, never merely trust this summary."""

        if not isinstance(dataset, M23ExactDataset):
            raise M23ExactVerificationError(
                "M23 exact certificate verification requires a fully replayed M23ExactDataset"
            )
        self.verify_integrity()
        return self == dataset.certificate and canonicalize(self.result) == canonicalize(
            dataset.verification.to_dict()
        )


def _load_manifest(path: Path) -> tuple[Mapping[str, object], str]:
    raw = path.read_bytes()
    document = _mapping(load_strict_json(raw, "manifest"), "manifest")
    if document.get("schema_version") != MANIFEST_SCHEMA:
        raise FixtureVerificationError("unsupported M23 fixture-manifest schema")
    artifacts = _mapping(document.get("artifacts"), "manifest.artifacts")
    artifact_root = path.parent.parent
    resolved: dict[str, Path] = {}
    for name, raw_record in artifacts.items():
        record = _mapping(raw_record, f"manifest.artifacts.{name}")
        relative = record.get("path")
        digest = record.get("sha256")
        size = record.get("bytes")
        if not isinstance(relative, str) or not relative:
            raise FixtureVerificationError(f"artifact {name} has no relative path")
        target = artifact_root / relative
        if not target.is_file():
            raise FixtureVerificationError(f"artifact {name} is missing: {relative}")
        if _sha256(target) != digest:
            raise FixtureVerificationError(f"artifact {name} SHA-256 mismatch")
        if target.stat().st_size != size:
            raise FixtureVerificationError(f"artifact {name} byte count mismatch")
        resolved[name] = target
    receipt_path = resolved.get("generation_receipt")
    if receipt_path is None:
        raise FixtureVerificationError("manifest has no generation receipt")
    receipt = _mapping(
        load_strict_json(receipt_path.read_bytes(), "generation receipt"),
        "generation receipt",
    )
    if receipt.get("schema_version") != (
        "arbogast.example.m23-real-component.generation-receipt/v2"
    ):
        raise FixtureVerificationError("unsupported generation-receipt schema")
    for name in ("dataset", "generator"):
        receipt_record = _mapping(receipt.get(name), f"generation receipt {name}")
        manifest_record = _mapping(artifacts.get(name), f"manifest artifact {name}")
        if (
            receipt_record.get("path") != manifest_record.get("path")
            or receipt_record.get("sha256") != manifest_record.get("sha256")
            or receipt_record.get("bytes") != manifest_record.get("bytes")
        ):
            raise FixtureVerificationError(
                f"generation receipt is not bound to the manifest {name} artifact"
            )
    verification = _mapping(document.get("verification"), "manifest.verification")
    public_verifier = _mapping(
        verification.get("public_verifier"),
        "manifest.verification.public_verifier",
    )
    if public_verifier.get("module") != __name__:
        raise FixtureVerificationError("manifest names a different public M23 verifier module")
    verifier_source = Path(__file__).resolve()
    if _sha256(verifier_source) != public_verifier.get("sha256"):
        raise FixtureVerificationError("public M23 verifier SHA-256 mismatch")
    if verifier_source.stat().st_size != public_verifier.get("bytes"):
        raise FixtureVerificationError("public M23 verifier byte count mismatch")
    return document, hashlib.sha256(raw).hexdigest()


def _parse_nielsen_tuple(value: object, label: str) -> NielsenTuple:
    entries = _sequence(value, label)
    if len(entries) != 4:
        raise FixtureVerificationError(f"{label} must contain four permutations")
    return tuple(parse_permutation(entry, f"{label}[{slot}]") for slot, entry in enumerate(entries))  # type: ignore[return-value]


def _replay_m23_exact_dataset(
    *,
    manifest_path: Path,
    dataset_path: Path,
) -> M23ExactVerification:
    """Replay every finite witness and return a deterministic verification summary."""

    manifest, manifest_sha256 = _load_manifest(manifest_path)
    dataset_digest = _sha256(dataset_path)
    artifacts = _mapping(manifest["artifacts"], "manifest.artifacts")
    dataset_record = _mapping(artifacts.get("dataset"), "manifest.artifacts.dataset")
    if dataset_record.get("sha256") != dataset_digest:
        raise FixtureVerificationError("selected dataset is not bound by the manifest")

    dataset = _mapping(load_strict_json(dataset_path.read_bytes(), "dataset"), "dataset")
    if dataset.get("schema_version") != DATASET_SCHEMA:
        raise FixtureVerificationError("unsupported M23 fixture dataset schema")
    if dataset.get("permutation_convention") != (
        "one-based one-line images; products act left-to-right; x^g = g^-1*x*g"
    ):
        raise FixtureVerificationError("permutation convention mismatch")

    group = _mapping(dataset.get("group"), "dataset.group")
    if (group.get("name"), group.get("degree"), group.get("order")) != (
        "M23",
        DEGREE,
        10_200_960,
    ):
        raise FixtureVerificationError("pinned M23 identity/degree/order mismatch")
    generators = tuple(
        parse_permutation(value, f"group.generators[{index}]")
        for index, value in enumerate(_sequence(group.get("generators"), "group.generators"))
    )
    if generators != STANDARD_M23_GENERATORS:
        raise FixtureVerificationError("dataset does not use the pinned standard M23 generators")
    group_chain = schreier_chain(generators)
    if group_chain.order != 10_200_960:
        raise FixtureVerificationError("Schreier chain does not verify |M23|=10200960")
    if group_chain.orbit_sizes != (23, 22, 21, 20, 16, 3):
        raise FixtureVerificationError("unexpected standard M23 Schreier orbit sizes")

    passport = tuple(str(item) for item in _sequence(dataset.get("passport"), "passport"))
    if passport != EXPECTED_PASSPORT:
        raise FixtureVerificationError("passport must be exactly (2A,3A,6A,2A)")

    raw_class_representatives = _mapping(
        group.get("class_representatives"), "group.class_representatives"
    )
    if set(raw_class_representatives) != set(EXPECTED_CLASS_ORDERS):
        raise FixtureVerificationError("class representative labels are incomplete")
    class_representatives = {
        label: parse_permutation(raw_class_representatives[label], f"class {label}")
        for label in EXPECTED_CLASS_ORDERS
    }
    for label, representative in class_representatives.items():
        if not group_chain.contains(representative):
            raise FixtureVerificationError(f"class representative {label} is outside M23")
        if permutation_order(representative) != EXPECTED_CLASS_ORDERS[label]:
            raise FixtureVerificationError(f"class representative {label} has wrong order")
        if cycle_lengths(representative) != EXPECTED_CLASS_CYCLES[label]:
            raise FixtureVerificationError(f"class representative {label} has wrong cycle type")

    pinned_2a = class_representatives["2A"]
    centralizer_generators = tuple(
        parse_permutation(value, f"centralizer_2A_generators[{index}]")
        for index, value in enumerate(
            _sequence(group.get("centralizer_2A_generators"), "centralizer_2A_generators")
        )
    )
    for generator in centralizer_generators:
        if not group_chain.contains(generator):
            raise FixtureVerificationError("2A-centralizer generator is outside M23")
        if conjugate(pinned_2a, generator) != pinned_2a:
            raise FixtureVerificationError("2A-centralizer generator does not centralize 2A")
    centralizer_chain = schreier_chain(centralizer_generators)
    conjugacy_orbit, _ = _conjugacy_orbit_and_stabilizer(pinned_2a, generators)
    expected_centralizer_order, remainder = divmod(group_chain.order, len(conjugacy_orbit))
    if remainder or expected_centralizer_order != 2688:
        raise FixtureVerificationError("2A conjugacy orbit does not certify centralizer order")
    if centralizer_chain.order != expected_centralizer_order:
        raise FixtureVerificationError("supplied 2A centralizer is not the full centralizer")

    # Exhaust the full product-one passport without enumerating the 850,080
    # elements of 6A.  Once a and b are fixed, d in 2A uniquely forces
    # c=(a*b)^-1*d.  Positive 6A membership is checked by an explicit
    # conjugator from the pinned representative; a matching cycle shape with
    # no such witness is rejected rather than silently classified.
    class2_elements = sorted(conjugacy_orbit)
    if len(class2_elements) != 3795:
        raise FixtureVerificationError("the pinned 2A conjugacy class must have size 3795")
    class3_orbit = set(
        _action_orbit_transversals(class_representatives["3A"], generators, conjugate)
    )
    if len(class3_orbit) != 56_672:
        raise FixtureVerificationError("the pinned 3A conjugacy class must have size 56672")

    remaining_b = set(class3_orbit)
    b_partitions: dict[Permutation, tuple[set[Permutation], tuple[Permutation, ...], int]] = {}
    while remaining_b:
        representative = min(remaining_b)
        orbit, residual_generators = _conjugacy_orbit_and_stabilizer(
            representative, centralizer_generators
        )
        if not orbit <= remaining_b or min(orbit) != representative:
            raise FixtureVerificationError("C_G(2A)-orbit partition on 3A is inconsistent")
        residual_order, remainder = divmod(centralizer_chain.order, len(orbit))
        if remainder or schreier_chain(residual_generators).order != residual_order:
            raise FixtureVerificationError("residual b-stabilizer order is not certified")
        b_partitions[representative] = (orbit, residual_generators, residual_order)
        remaining_b.difference_update(orbit)
    if len(b_partitions) != 35:
        raise FixtureVerificationError("expected exactly 35 C_G(2A)-orbits on 3A")

    completeness = _mapping(dataset.get("completeness"), "completeness")
    if completeness.get("method") != (
        "fix a in 2A; quotient b in 3A by C_G(a); enumerate d in 2A; "
        "force c=(a*b)^-1*d; quotient by C_C(b)"
    ):
        raise FixtureVerificationError("completeness-enumeration convention mismatch")
    if completeness.get("sorted_2A_count") != len(class2_elements):
        raise FixtureVerificationError("completeness 2A count mismatch")
    raw_b_rows = _sequence(completeness.get("b_orbits"), "completeness.b_orbits")
    if len(raw_b_rows) != len(b_partitions):
        raise FixtureVerificationError("completeness b-orbit row count mismatch")
    supplied_b_rows: dict[Permutation, Sequence[object]] = {}
    for row_index, raw_row in enumerate(raw_b_rows):
        row = _sequence(raw_row, f"completeness.b_orbits[{row_index}]")
        if len(row) != 4:
            raise FixtureVerificationError(
                "completeness b-orbit row must contain b, orbit size, D order, witnesses"
            )
        representative = parse_permutation(row[0], f"completeness b[{row_index}]")
        if representative in supplied_b_rows:
            raise FixtureVerificationError("duplicate completeness b-orbit representative")
        supplied_b_rows[representative] = row
    if set(supplied_b_rows) != set(b_partitions):
        raise FixtureVerificationError("completeness b-orbit representatives are not exhaustive")

    all_inner_representatives: set[NielsenTuple] = set()
    forced_class6_candidates = 0
    fixed_a_product_one_tuples = 0
    weighted_inner_mass = Fraction(0)
    for b in sorted(b_partitions):
        b_orbit, residual_generators, residual_order = b_partitions[b]
        row = supplied_b_rows[b]
        if _integer(row[1], "b orbit size") != len(b_orbit):
            raise FixtureVerificationError("recorded b-orbit size mismatch")
        if _integer(row[2], "residual stabilizer order") != residual_order:
            raise FixtureVerificationError("recorded residual b-stabilizer order mismatch")
        raw_accepted = _sequence(row[3], "accepted forced-c witnesses")
        accepted_by_d_index: dict[int, Permutation] = {}
        for accepted_index, raw_accepted_record in enumerate(raw_accepted):
            accepted_record = _sequence(
                raw_accepted_record, f"accepted forced-c witness {accepted_index}"
            )
            if len(accepted_record) != 2:
                raise FixtureVerificationError(
                    "forced-c witness must contain a d index and 6A conjugator"
                )
            d_index = _integer(accepted_record[0], "forced-c d index")
            if not 0 <= d_index < len(class2_elements):
                raise FixtureVerificationError("forced-c d index is out of range")
            if d_index in accepted_by_d_index:
                raise FixtureVerificationError("duplicate forced-c d index")
            accepted_by_d_index[d_index] = parse_permutation(
                accepted_record[1], "forced-c 6A conjugator"
            )

        accepted_c_to_d: dict[Permutation, Permutation] = {}
        inverse_ab = inverse(multiply(pinned_2a, b))
        for d_index, d in enumerate(class2_elements):
            c = multiply(inverse_ab, d)
            has_6a_shape = cycle_lengths(c) == EXPECTED_CLASS_CYCLES["6A"]
            witness = accepted_by_d_index.get(d_index)
            if not has_6a_shape:
                if witness is not None:
                    raise FixtureVerificationError(
                        "forced-c witness accepts a permutation outside the pinned 6A cycle shape"
                    )
                continue
            if witness is None:
                raise FixtureVerificationError(
                    "forced c has the 6A cycle shape but no class-conjugacy witness"
                )
            if not group_chain.contains(witness):
                raise FixtureVerificationError("forced-c class witness is outside M23")
            if conjugate(class_representatives["6A"], witness) != c:
                raise FixtureVerificationError(
                    "forced-c class witness does not prove 6A membership"
                )
            accepted_c_to_d[c] = d
        if len(accepted_c_to_d) != len(accepted_by_d_index):
            raise FixtureVerificationError("forced-c witness inventory contains unused records")

        forced_class6_candidates += len(accepted_c_to_d)
        fixed_a_product_one_tuples += len(b_orbit) * len(accepted_c_to_d)
        remaining_c = set(accepted_c_to_d)
        while remaining_c:
            c = min(remaining_c)
            c_orbit = set(_action_orbit_transversals(c, residual_generators, conjugate))
            if not c_orbit <= remaining_c or min(c_orbit) != c:
                raise FixtureVerificationError(
                    "C_C(b)-orbit partition on forced 6A entries is inconsistent"
                )
            stabilizer_order, remainder = divmod(residual_order, len(c_orbit))
            if remainder:
                raise FixtureVerificationError("tuple stabilizer order is not integral")
            d = accepted_c_to_d[c]
            nielsen_representative = (pinned_2a, b, c, d)
            if product(nielsen_representative) != IDENTITY:
                raise FixtureVerificationError("exhaustive representative is not product one")
            all_inner_representatives.add(nielsen_representative)
            weighted_inner_mass += Fraction(1, stabilizer_order)
            remaining_c.difference_update(c_orbit)

    if forced_class6_candidates != 12_465:
        raise FixtureVerificationError("unexpected number of forced 6A candidates")
    if fixed_a_product_one_tuples != 18_553_024:
        raise FixtureVerificationError("fixed-a product-one tuple count mismatch")
    if len(all_inner_representatives) != 7114:
        raise FixtureVerificationError("full inner product-one orbit count mismatch")
    if weighted_inner_mass != Fraction(41_413, 6):
        raise FixtureVerificationError("weighted inner-orbit mass mismatch")

    completeness_counts = _mapping(completeness.get("counts"), "completeness.counts")
    if completeness_counts != {
        "b_orbits": 35,
        "accepted_forced_c": 12_465,
        "fixed_a_product_one_tuples": 18_553_024,
        "all_inner_orbits": 7114,
        "generating_inner_orbits": 1428,
        "nongenerating_inner_orbits": 5686,
        "generating_c1": 20,
        "nongenerating_c1": 212,
        "weighted_mass_numerator": 41_413,
        "weighted_mass_denominator": 6,
    }:
        raise FixtureVerificationError("recorded completeness counts mismatch")

    raw_vertices = _sequence(dataset.get("vertices"), "vertices")
    vertices = tuple(
        _parse_nielsen_tuple(value, f"vertices[{index}]")
        for index, value in enumerate(raw_vertices)
    )
    if len(vertices) != 1428 or len(set(vertices)) != 1428:
        raise FixtureVerificationError("fixture must contain 1428 distinct canonical tuples")
    component_set = set(vertices)
    if not component_set <= all_inner_representatives:
        raise FixtureVerificationError(
            "pure-braid component contains a tuple absent from exhaustive enumeration"
        )
    nongenerating_representatives = all_inner_representatives - component_set
    if len(nongenerating_representatives) != 5686:
        raise FixtureVerificationError("exhaustive complement does not contain 5686 tuples")
    for nongenerating_representative in nongenerating_representatives:
        if len(_point_orbit_transversals(0, nongenerating_representative)) == DEGREE:
            raise FixtureVerificationError(
                "a transitive full-passport representative lies outside the generating component"
            )
    nongenerating_c1 = sum(
        straight_real_transform(representative) == representative
        for representative in nongenerating_representatives
    )
    if nongenerating_c1 != 212:
        raise FixtureVerificationError(
            "nongenerating complement must contain exactly 212 strict c=1 representatives"
        )

    raw_class_conjugators = _sequence(dataset.get("class_conjugators"), "class_conjugators")
    if len(raw_class_conjugators) != len(vertices):
        raise FixtureVerificationError("class-conjugator row count mismatch")

    canonical_cache = {
        representative: (orbit, residual_generators)
        for representative, (orbit, residual_generators, _) in b_partitions.items()
    }
    class_witness_count = 0
    for vertex_index, vertex in enumerate(vertices):
        if vertex[0] != pinned_2a:
            raise FixtureVerificationError(f"vertex {vertex_index} does not pin its first 2A entry")
        if product(vertex) != IDENTITY:
            raise FixtureVerificationError(f"vertex {vertex_index} is not product one")
        raw_row = _sequence(
            raw_class_conjugators[vertex_index],
            f"class_conjugators[{vertex_index}]",
        )
        if len(raw_row) != 4:
            raise FixtureVerificationError("every vertex needs four class-conjugacy witnesses")
        for slot, raw_witness in enumerate(raw_row):
            witness = parse_permutation(raw_witness, f"class_conjugators[{vertex_index}][{slot}]")
            if not group_chain.contains(witness):
                raise FixtureVerificationError("class-conjugacy witness is outside M23")
            if conjugate(class_representatives[passport[slot]], witness) != vertex[slot]:
                raise FixtureVerificationError(
                    f"class-conjugacy witness fails at vertex {vertex_index}, slot {slot}"
                )
            class_witness_count += 1

        second = vertex[1]
        cached = canonical_cache.get(second)
        if cached is None:
            raise FixtureVerificationError(
                "vertex second entry is absent from exhaustive partition"
            )
        second_orbit, residual_generators = cached
        if min(second_orbit) != second:
            raise FixtureVerificationError("cached second-entry canonicality failed")
        third_orbit = set(_action_orbit_transversals(vertex[2], residual_generators, conjugate))
        if min(third_orbit) != vertex[2]:
            raise FixtureVerificationError(
                f"vertex {vertex_index} third entry is not residual-canonical"
            )

    seed = _mapping(dataset.get("seed"), "seed")
    if (seed.get("discovery_seed"), seed.get("trial"), seed.get("canonical_vertex")) != (
        20260828,
        4387,
        0,
    ):
        raise FixtureVerificationError("seed provenance mismatch")
    raw_seed = _parse_nielsen_tuple(seed.get("raw_tuple"), "seed.raw_tuple")
    if tuple(permutation_order(entry) for entry in raw_seed) != (2, 3, 6, 2):
        raise FixtureVerificationError("raw seed has the wrong passport orders")
    if product(raw_seed) != IDENTITY:
        raise FixtureVerificationError("raw seed is not product one")
    if any(not group_chain.contains(entry) for entry in raw_seed):
        raise FixtureVerificationError("raw seed contains an entry outside M23")
    if schreier_chain(raw_seed).order != group_chain.order:
        raise FixtureVerificationError("raw seed does not generate the pinned M23")
    seed_conjugator = parse_permutation(
        seed.get("canonicalization_conjugator"), "seed.canonicalization_conjugator"
    )
    if not group_chain.contains(seed_conjugator):
        raise FixtureVerificationError("seed canonicalization conjugator is outside M23")
    if conjugate_tuple(raw_seed, seed_conjugator) != vertices[0]:
        raise FixtureVerificationError("raw seed does not canonicalize to vertex zero")
    if schreier_chain(vertices[0]).order != group_chain.order:
        raise FixtureVerificationError("canonical seed vertex does not generate M23")

    raw_generators = _sequence(dataset.get("pure_braid_generators"), "pure_braid_generators")
    if len(raw_generators) != 6:
        raise FixtureVerificationError("fixture must pin the six standard pure generators")
    pure_words: list[tuple[int, ...]] = []
    pure_names: list[str] = []
    for index, raw_generator in enumerate(raw_generators):
        record = _mapping(raw_generator, f"pure_braid_generators[{index}]")
        pure_names.append(str(record.get("name")))
        pure_words.append(
            tuple(
                _integer(item, f"pure_braid_generators[{index}].word")
                for item in _sequence(record.get("word"), "pure braid word")
            )
        )
    if tuple(pure_names) != EXPECTED_PURE_NAMES or tuple(pure_words) != EXPECTED_PURE_WORDS:
        raise FixtureVerificationError("pure-braid generators do not match Haefner's convention")

    raw_transitions = _sequence(dataset.get("transitions"), "transitions")
    if len(raw_transitions) != len(vertices):
        raise FixtureVerificationError("pure-transition row count mismatch")
    mappings: list[list[int]] = [[] for _ in pure_words]
    adjacency: list[list[int]] = [[] for _ in vertices]
    for vertex_index, raw_row in enumerate(raw_transitions):
        row = _sequence(raw_row, f"transitions[{vertex_index}]")
        if len(row) != len(pure_words):
            raise FixtureVerificationError("pure-transition column count mismatch")
        for generator_index, raw_transition in enumerate(row):
            transition = _sequence(
                raw_transition, f"transitions[{vertex_index}][{generator_index}]"
            )
            if len(transition) != 2:
                raise FixtureVerificationError("transition must be [target, conjugator]")
            target = _integer(transition[0], "transition target")
            if not 0 <= target < len(vertices):
                raise FixtureVerificationError("transition target is out of range")
            witness = parse_permutation(transition[1], "transition conjugator")
            if not group_chain.contains(witness):
                raise FixtureVerificationError("transition conjugator is outside M23")
            moved = apply_braid_word(vertices[vertex_index], pure_words[generator_index])
            if conjugate_tuple(moved, witness) != vertices[target]:
                raise FixtureVerificationError(
                    f"invalid braid edge at vertex {vertex_index}, generator {generator_index}"
                )
            mappings[generator_index].append(target)
            adjacency[vertex_index].append(target)

    expected_targets = list(range(len(vertices)))
    for generator_index, mapping in enumerate(mappings):
        if sorted(mapping) != expected_targets:
            raise FixtureVerificationError(
                f"pure generator {generator_index} is not a permutation of the component"
            )
    reached = {0}
    queue = deque([0])
    while queue:
        source = queue.popleft()
        for target in adjacency[source]:
            if target not in reached:
                reached.add(target)
                queue.append(target)
    if len(reached) != len(vertices):
        raise FixtureVerificationError("six pure generators are not transitive on the fixture")

    real = _mapping(dataset.get("real"), "real")
    if real.get("convention") != ("kappa_i=(g_1...g_(i-1))*g_i^-1*(g_1...g_(i-1))^-1"):
        raise FixtureVerificationError("straight-real convention mismatch")
    raw_real_transitions = _sequence(real.get("transitions"), "real.transitions")
    raw_real_mapping = _sequence(real.get("mapping"), "real.mapping")
    if len(raw_real_transitions) != len(vertices) or len(raw_real_mapping) != len(vertices):
        raise FixtureVerificationError("real-action size mismatch")
    real_mapping: list[int] = []
    recomputed_c1: list[int] = []
    for vertex_index, vertex in enumerate(vertices):
        transformed = straight_real_transform(vertex)
        if transformed == vertex:
            recomputed_c1.append(vertex_index)
        transition = _sequence(
            raw_real_transitions[vertex_index], f"real.transitions[{vertex_index}]"
        )
        if len(transition) != 2:
            raise FixtureVerificationError("real transition must be [target, conjugator]")
        target = _integer(transition[0], "real transition target")
        if target != _integer(raw_real_mapping[vertex_index], "real mapping target"):
            raise FixtureVerificationError("real transition and mapping disagree")
        if not 0 <= target < len(vertices):
            raise FixtureVerificationError("real transition target is out of range")
        witness = parse_permutation(transition[1], "real transition conjugator")
        if not group_chain.contains(witness):
            raise FixtureVerificationError("real transition conjugator is outside M23")
        if conjugate_tuple(transformed, witness) != vertices[target]:
            raise FixtureVerificationError(f"invalid real transition at vertex {vertex_index}")
        real_mapping.append(target)
    if sorted(real_mapping) != expected_targets:
        raise FixtureVerificationError("real action is not a permutation")
    if any(real_mapping[real_mapping[index]] != index for index in expected_targets):
        raise FixtureVerificationError("real action is not an involution")
    recomputed_inner_fixed = [index for index, target in enumerate(real_mapping) if index == target]
    recorded_c1 = [
        _integer(item, "real.c1_indices")
        for item in _sequence(real.get("c1_indices"), "real.c1_indices")
    ]
    recorded_inner_fixed = [
        _integer(item, "real.inner_fixed_indices")
        for item in _sequence(real.get("inner_fixed_indices"), "real.inner_fixed_indices")
    ]
    if recorded_c1 != recomputed_c1 or len(recomputed_c1) != 20:
        raise FixtureVerificationError("c=1 fixed set is not exactly the recorded 20 vertices")
    if recorded_inner_fixed != recomputed_inner_fixed or len(recomputed_inner_fixed) != 70:
        raise FixtureVerificationError("inner real fixed set is not exactly 70 vertices")

    counts = _mapping(dataset.get("counts"), "counts")
    expected_counts = {
        "vertices": len(vertices),
        "pure_generators": len(pure_words),
        "directed_transitions": len(vertices) * len(pure_words),
        "inner_real_fixed": len(recomputed_inner_fixed),
        "c1_fixed": len(recomputed_c1),
    }
    if counts != expected_counts:
        raise FixtureVerificationError("recorded counts do not match verified fixture contents")

    claims = _mapping(manifest.get("verified_claims"), "manifest.verified_claims")
    if claims != {
        "generating_inner_nielsen_cardinality": 1428,
        "pure_braid_transitive": True,
        "c1_fixed": 20,
        "inner_real_fixed": 70,
        "all_product_one_inner_orbits": 7114,
        "nongenerating_inner_orbits": 5686,
        "nongenerating_c1": 212,
    }:
        raise FixtureVerificationError("manifest verified-claim summary mismatch")
    if manifest.get("scope_exclusion") != (
        "This finite certificate proves the generating inner Nielsen class and its real action; "
        "it does not construct equations for the Hurwitz curve or prove a literature-novelty claim."
    ):
        raise FixtureVerificationError("manifest must preserve its theorem-scope exclusion")

    return M23ExactVerification(
        dataset_sha256=dataset_digest,
        manifest_sha256=manifest_sha256,
        group_order=group_chain.order,
        group_chain_orbits=group_chain.orbit_sizes,
        centralizer_order=centralizer_chain.order,
        class_conjugacy_witnesses=class_witness_count,
        component_cardinality=len(vertices),
        pure_generators=len(pure_words),
        directed_transitions=len(vertices) * len(pure_words),
        c1_fixed=len(recomputed_c1),
        inner_real_fixed=len(recomputed_inner_fixed),
        forced_class6_candidates=forced_class6_candidates,
        all_inner_orbits=len(all_inner_representatives),
        nongenerating_inner_orbits=len(nongenerating_representatives),
        nongenerating_c1=nongenerating_c1,
        fixed_a_product_one_tuples=fixed_a_product_one_tuples,
        weighted_inner_mass="41413/6",
        checks=(
            "artifact-content-addresses",
            "standard-M23-Schreier-order-and-membership",
            "pinned-class-conjugacy",
            "product-one",
            "seed-generation",
            "inner-canonicality-and-uniqueness",
            "exhaustive-full-passport-partition",
            "nongenerating-complement-intransitivity",
            "pure-braid-edge-witnesses",
            "pure-generator-closure-and-transitivity",
            "straight-real-permutation-and-involution",
            "exhaustive-c1-fixed-set-within-generating-inner-class",
        ),
    )


@dataclass(frozen=True, init=False)
class M23ExactDataset:
    """A compact fixture that has passed the full finite replay at construction."""

    manifest_path: Path
    dataset_path: Path
    verification: M23ExactVerification
    certificate: M23ExactCertificate

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("M23ExactDataset construction requires load_m23_exact_dataset()")

    @classmethod
    def _from_replay(
        cls,
        manifest_path: Path,
        dataset_path: Path,
        verification: M23ExactVerification,
        certificate: M23ExactCertificate,
    ) -> M23ExactDataset:
        value = object.__new__(cls)
        object.__setattr__(value, "manifest_path", manifest_path)
        object.__setattr__(value, "dataset_path", dataset_path)
        object.__setattr__(value, "verification", verification)
        object.__setattr__(value, "certificate", certificate)
        value.__post_init__()
        return value

    def __post_init__(self) -> None:
        if self.certificate.dataset_sha256 != self.verification.dataset_sha256:
            raise M23ExactVerificationError("typed dataset and certificate digests disagree")
        if self.certificate.manifest_sha256 != self.verification.manifest_sha256:
            raise M23ExactVerificationError("typed manifest and certificate digests disagree")
        if canonicalize(self.certificate.result) != canonicalize(self.verification.to_dict()):
            raise M23ExactVerificationError("typed dataset certificate report mismatch")
        if not self.certificate.verify(self):
            raise M23ExactVerificationError("typed dataset certificate is not canonical")


def load_m23_exact_dataset(
    manifest_path: str | Path,
    dataset_path: str | Path | None = None,
) -> M23ExactDataset:
    """Strictly load and replay the checked M23 v2 dataset.

    The returned type is proof-carrying: construction succeeds only after the full compact
    stabilizer-chain, class, completeness, braid, and real witnesses have been replayed.
    """

    manifest = Path(manifest_path).resolve()
    dataset = (
        Path(dataset_path).resolve()
        if dataset_path is not None
        else manifest.with_name("dataset.json")
    )
    verification = _replay_m23_exact_dataset(
        manifest_path=manifest,
        dataset_path=dataset,
    )
    certificate = M23ExactCertificate.create(verification)
    return M23ExactDataset._from_replay(manifest, dataset, verification, certificate)


@dataclass(frozen=True)
class _M23ClaimSpec:
    claim_id: str
    text: str
    claim_key: str
    expected_value: object
    why: tuple[str, ...]
    sources: tuple[str, ...]
    hypotheses: tuple[str, ...]


_GROUP_HYPOTHESIS = (
    "The group is the pinned degree-23 permutation embedding generated by the two standard "
    "generators in the checked dataset, and the ordered passport is (2A,3A,6A,2A)."
)
_INNER_HYPOTHESIS = (
    "Nielsen tuples are quotiented by simultaneous inner conjugacy in the pinned group."
)
_BRAID_HYPOTHESIS = (
    "Pure-braid words use the right Hurwitz action and the six displayed B4 generators."
)
_REAL_HYPOTHESIS = (
    "Real counts use the checked straight-bouquet transform; strict c=1 means literal "
    "equality before quotienting by inner conjugacy."
)

_M23_CLAIM_SPECS = (
    _M23ClaimSpec(
        "m23_236_completeness_partition",
        "The product-one inner passport (M23; 2A,3A,6A,2A) has 7114 inner orbits: "
        "1428 generating and 5686 intransitive nongenerating orbits.",
        "all_inner_orbits",
        7114,
        (),
        ("atlas-m23-identity", "atlas-m23-class-labels"),
        (_GROUP_HYPOTHESIS, _INNER_HYPOTHESIS),
    ),
    _M23ClaimSpec(
        "m23_236_inner_cardinality",
        "The generating inner Nielsen class Ni^in(M23; 2A,3A,6A,2A) has cardinality 1428.",
        "component_cardinality",
        1428,
        ("m23_236_completeness_partition",),
        ("atlas-m23-identity", "atlas-m23-class-labels"),
        (_GROUP_HYPOTHESIS, _INNER_HYPOTHESIS),
    ),
    _M23ClaimSpec(
        "m23_236_pure_braid_transitive",
        "The six standard pure-braid generators act transitively on Ni^in(M23; 2A,3A,6A,2A).",
        "pure_braid_transitive",
        True,
        ("m23_236_inner_cardinality",),
        (
            "atlas-m23-identity",
            "atlas-m23-class-labels",
            "haefner-right-hurwitz-action",
            "haefner-pure-b4-generators",
        ),
        (_GROUP_HYPOTHESIS, _INNER_HYPOTHESIS, _BRAID_HYPOTHESIS),
    ),
    _M23ClaimSpec(
        "m23_236_c1_real_count",
        "Exactly 20 classes in Ni^in(M23; 2A,3A,6A,2A) satisfy the "
        "straight-bouquet c=1 real criterion.",
        "c1_fixed",
        20,
        ("m23_236_inner_cardinality",),
        ("atlas-m23-identity", "atlas-m23-class-labels"),
        (_GROUP_HYPOTHESIS, _INNER_HYPOTHESIS, _REAL_HYPOTHESIS),
    ),
    _M23ClaimSpec(
        "m23_236_inner_real_fixed_count",
        "The straight-bouquet real involution fixes exactly 70 inner classes in "
        "Ni^in(M23; 2A,3A,6A,2A).",
        "inner_real_fixed",
        70,
        ("m23_236_inner_cardinality",),
        ("atlas-m23-identity", "atlas-m23-class-labels"),
        (_GROUP_HYPOTHESIS, _INNER_HYPOTHESIS, _REAL_HYPOTHESIS),
    ),
    _M23ClaimSpec(
        "m23_236_nongenerating_c1_guardrail",
        "The 5686 nongenerating product-one inner orbits contain exactly 212 strict c=1 "
        "representatives; they are outside the generating inner Nielsen class.",
        "nongenerating_c1",
        212,
        ("m23_236_completeness_partition",),
        ("atlas-m23-identity", "atlas-m23-class-labels"),
        (_GROUP_HYPOTHESIS, _INNER_HYPOTHESIS, _REAL_HYPOTHESIS),
    ),
)


def _report_values(verification: M23ExactVerification) -> dict[str, object]:
    return {
        "all_inner_orbits": verification.all_inner_orbits,
        "component_cardinality": verification.component_cardinality,
        "pure_braid_transitive": verification.component_cardinality == 1428,
        "c1_fixed": verification.c1_fixed,
        "inner_real_fixed": verification.inner_real_fixed,
        "nongenerating_c1": verification.nongenerating_c1,
    }


def _statement_for(spec: _M23ClaimSpec) -> FormalStatement:
    return FormalStatement.create(
        spec.text,
        parameters={
            "group": "M23",
            "passport": EXPECTED_PASSPORT,
            "claim_key": spec.claim_key,
            "verified_value": spec.expected_value,
            "dataset_schema": DATASET_SCHEMA,
        },
    )


def _claim_boundary_for(spec: _M23ClaimSpec) -> str:
    return claim_boundary_hash(
        spec.claim_id,
        _statement_for(spec),
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.CERTIFIED,
        hypotheses=spec.hypotheses,
        dependency_ids=spec.why,
    )


def _claim_binding_for(spec: _M23ClaimSpec) -> ClaimBinding:
    statement = _statement_for(spec)
    return ClaimBinding(spec.claim_id, statement.statement_hash, _claim_boundary_for(spec))


def _dependency_bindings_for(spec: _M23ClaimSpec) -> tuple[ClaimBinding, ...]:
    specs = {item.claim_id: item for item in _M23_CLAIM_SPECS}
    return tuple(_claim_binding_for(specs[dependency_id]) for dependency_id in spec.why)


def m23_verification_certificate_for(
    dataset: M23ExactDataset,
    claim_id: str,
) -> VerificationCertificate:
    """Return one independently claim-bound semantic certificate."""

    specs = {spec.claim_id: spec for spec in _M23_CLAIM_SPECS}
    try:
        spec = specs[claim_id]
    except KeyError as error:
        raise M23ExactVerificationError(f"unknown M23 exact claim: {claim_id}") from error
    actual = _report_values(dataset.verification)[spec.claim_key]
    if actual != spec.expected_value:
        raise M23ExactVerificationError(
            f"verified M23 dataset does not establish {spec.claim_key}={spec.expected_value!r}"
        )
    statement = _statement_for(spec)
    return VerificationCertificate.create(
        subject=spec.text,
        verifier=M23_EXACT_VERIFIER,
        claim_id=spec.claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=_claim_boundary_for(spec),
        claim_dependencies=_dependency_bindings_for(spec),
        witness={
            "m23_exact_certificate": dataset.certificate.to_dict(),
            "claim_key": spec.claim_key,
            "verified_value": spec.expected_value,
        },
        checks=(*dataset.verification.checks, "claim-bound-semantic-projection"),
        guarantees=(spec.text,),
    )


def m23_certificates_for(
    dataset: M23ExactDataset,
) -> dict[str, VerificationCertificate]:
    """Return the six semantic certificates keyed by their content addresses."""

    certificates = (
        m23_verification_certificate_for(dataset, spec.claim_id) for spec in _M23_CLAIM_SPECS
    )
    return {certificate.certificate_id: certificate for certificate in certificates}


def m23_claim_graph_for(
    dataset: M23ExactDataset,
    *,
    provenance_record: str | None = None,
) -> ClaimGraph:
    """Project the exact dataset into the canonical six-node public ClaimGraph."""

    certificates_by_claim = {
        certificate.claim_id: certificate for certificate in m23_certificates_for(dataset).values()
    }
    claims: list[Claim] = []
    for spec in _M23_CLAIM_SPECS:
        certificate = certificates_by_claim[spec.claim_id]
        metadata: dict[str, object] = {
            "fixture_schema": DATASET_SCHEMA,
            "specialized_certificate_id": dataset.certificate.certificate_id,
            "source_references_are_context_not_proof": True,
            "search_free_verification": True,
        }
        if provenance_record is not None:
            metadata["provenance_record"] = provenance_record
        claims.append(
            Claim(
                spec.claim_id,
                statement=_statement_for(spec),
                kind=ClaimKind.COMPUTED,
                status=EpistemicStatus.CERTIFIED,
                why=spec.why,
                how=Derivation.computation(
                    "arbogast.hurwitz.load_m23_exact_dataset",
                    method=(
                        "Fresh-process replay of the compact finite M23 permutation, "
                        "completeness, braid, and real witnesses"
                    ),
                    inputs=(
                        f"sha256:{dataset.verification.dataset_sha256}",
                        f"sha256:{dataset.verification.manifest_sha256}",
                    ),
                    artifact=dataset.certificate.certificate_id,
                    parameters={
                        "claim_key": spec.claim_key,
                        "dataset_schema": DATASET_SCHEMA,
                        "verifier": M23_EXACT_VERIFIER,
                    },
                ),
                certificate=certificate,
                source=spec.sources,
                hypotheses=spec.hypotheses,
                metadata=metadata,
            )
        )
    return ClaimGraph(claims, graph_id=M23_GRAPH_ID)


def m23_verifier_registry(dataset: M23ExactDataset) -> VerifierRegistry:
    """Bind ``hurwitz.m23_exact`` to one fully replayed typed dataset."""

    expected = {
        certificate.claim_id: certificate for certificate in m23_certificates_for(dataset).values()
    }
    registry = VerifierRegistry()

    def replay(certificate: VerificationCertificate) -> bool:
        claim_id = certificate.claim_id
        if claim_id is None or claim_id not in expected:
            return False
        raw_specialized = certificate.witness.get("m23_exact_certificate")
        if not isinstance(raw_specialized, Mapping):
            return False
        try:
            specialized = M23ExactCertificate.from_dict(raw_specialized)
        except (M23ExactVerificationError, ValueError, TypeError):
            return False
        return (
            specialized == dataset.certificate
            and specialized.verify(dataset)
            and canonicalize(certificate.to_dict()) == canonicalize(expected[claim_id].to_dict())
        )

    registry.register(M23_EXACT_VERIFIER, VerificationCertificate, replay)
    return registry


__all__ = [
    "DATASET_SCHEMA",
    "M23_EXACT_CERTIFICATE_SCHEMA",
    "M23_EXACT_VERIFIER",
    "MANIFEST_SCHEMA",
    "M23ExactCertificate",
    "M23ExactDataset",
    "M23ExactVerification",
    "M23ExactVerificationError",
    "load_m23_exact_dataset",
    "load_strict_json",
    "m23_certificates_for",
    "m23_claim_graph_for",
    "m23_verification_certificate_for",
    "m23_verifier_registry",
]
