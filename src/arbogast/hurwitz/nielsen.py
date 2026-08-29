"""Exact Nielsen tuples, inner classes, enumeration, and completeness receipts."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from typing import TYPE_CHECKING, Any, cast, overload

from arbogast.core import sha256_hex

if TYPE_CHECKING:
    from arbogast.claims import Claim, ClaimGraph

from ._cert import INNER_CONJUGACY_CONVENTION, ExactHurwitzCertificate
from ._group import ConcreteGroupContext, Element, class_members
from .errors import (
    BraidClosureError,
    CertificateVerificationError,
    ConcreteGroupMismatchError,
    InvalidConjugacyClassError,
    InvalidNielsenTupleError,
)


@dataclass(frozen=True)
class ExplicitConjugacyClass:
    """One fully materialized conjugacy orbit in a pinned concrete group."""

    group: object
    members: tuple[Element, ...]
    member_set: frozenset[Element]
    fingerprint: str
    label: str | None = None

    @classmethod
    def build(
        cls,
        context: ConcreteGroupContext,
        value: object,
        *,
        label: str | None = None,
    ) -> ExplicitConjugacyClass:
        if isinstance(value, cls):
            context.require_same_group(value.group)
            return value
        raw = class_members(value)
        if not raw:
            raise InvalidConjugacyClassError("an explicit conjugacy class cannot be empty")
        try:
            members_set = frozenset(raw)
        except TypeError as exc:
            raise InvalidConjugacyClassError("conjugacy-class members must be hashable") from exc
        if len(members_set) != len(raw):
            raise InvalidConjugacyClassError("explicit conjugacy class contains duplicates")
        for member in members_set:
            if not context.contains(member):
                raise ConcreteGroupMismatchError(
                    "conjugacy-class member is outside the pinned concrete group"
                )
        representative = min(members_set, key=context.key)
        exact_orbit = frozenset(context.conjugate(representative, by) for by in context.elements)
        if exact_orbit != members_set:
            missing = len(exact_orbit - members_set)
            extra = len(members_set - exact_orbit)
            raise InvalidConjugacyClassError(
                "explicit members are not exactly one conjugacy orbit "
                f"(missing={missing}, extra={extra})"
            )
        members = tuple(sorted(members_set, key=context.key))
        digest = hashlib.sha256()
        digest.update(b"arbogast.explicit-conjugacy-class.v1\0")
        digest.update(context.fingerprint.encode())
        for member in members:
            digest.update(context.index(member).to_bytes(8, "big"))
        return cls(context.group, members, members_set, digest.hexdigest(), label)

    def __contains__(self, element: object) -> bool:
        return element in self.member_set

    def __len__(self) -> int:
        return len(self.members)

    @property
    def representative(self) -> Element:
        return self.members[0]


def _explicit_classes(
    context: ConcreteGroupContext, classes: Sequence[object]
) -> tuple[ExplicitConjugacyClass, ...]:
    if not classes:
        raise InvalidNielsenTupleError("a Nielsen class needs at least one branch cycle")
    return tuple(ExplicitConjugacyClass.build(context, value) for value in classes)


class NielsenTuple:
    """A generating, product-one tuple in explicitly specified classes.

    Construction is strict: this type never represents a candidate that still
    needs product, generation, or class checks.
    """

    __slots__ = ("_classes", "_context", "_entries")

    _classes: tuple[ExplicitConjugacyClass, ...]
    _context: ConcreteGroupContext
    _entries: tuple[Element, ...]

    def __init__(
        self,
        group: object,
        entries: Sequence[Element],
        classes: Sequence[object],
    ) -> None:
        context = ConcreteGroupContext.build(group)
        explicit = _explicit_classes(context, classes)
        self._initialize(context, tuple(entries), explicit, validate=True)

    @classmethod
    def _from_context(
        cls,
        context: ConcreteGroupContext,
        entries: Sequence[Element],
        classes: Sequence[ExplicitConjugacyClass],
        *,
        validate: bool = True,
    ) -> NielsenTuple:
        instance = object.__new__(cls)
        instance._initialize(context, tuple(entries), tuple(classes), validate=validate)
        return instance

    def _initialize(
        self,
        context: ConcreteGroupContext,
        entries: tuple[Element, ...],
        classes: tuple[ExplicitConjugacyClass, ...],
        *,
        validate: bool,
    ) -> None:
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_entries", entries)
        object.__setattr__(self, "_classes", classes)
        if validate:
            _validate_entries(context, entries, classes)

    @property
    def group(self) -> object:
        return self._context.group

    @property
    def context(self) -> ConcreteGroupContext:
        return self._context

    @property
    def entries(self) -> tuple[Element, ...]:
        return self._entries

    @property
    def classes(self) -> tuple[ExplicitConjugacyClass, ...]:
        return self._classes

    @property
    def length(self) -> int:
        return len(self._entries)

    @property
    def product(self) -> Element:
        return self._context.product(self._entries)

    @property
    def is_product_one(self) -> bool:
        return bool(self.product == self._context.identity)

    @property
    def generates_group(self) -> bool:
        return self._context.is_generated_by(self._entries)

    @property
    def has_expected_classes(self) -> bool:
        return all(
            entry in conjugacy_class
            for entry, conjugacy_class in zip(self._entries, self._classes, strict=True)
        )

    def verify(self) -> bool:
        _validate_entries(self._context, self._entries, self._classes)
        return True

    def conjugated_by(self, element: Element) -> NielsenTuple:
        entries = self._context.simultaneous_conjugate(self._entries, element)
        return self._from_context(self._context, entries, self._classes)

    def canonical_inner(self) -> tuple[NielsenTuple, Element]:
        entries, conjugator = self._context.canonical_conjugate(self._entries)
        return self._from_context(self._context, entries, self._classes), conjugator

    def key(self) -> tuple[int, ...]:
        return self._context.tuple_key(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[Element]:
        return iter(self._entries)

    def __getitem__(self, index: int) -> Element:
        return self._entries[index]

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, NielsenTuple)
            and self.group is other.group
            and self._entries == other._entries
            and tuple(c.fingerprint for c in self._classes)
            == tuple(c.fingerprint for c in other._classes)
        )

    def __hash__(self) -> int:
        return hash((id(self.group), self._entries, tuple(c.fingerprint for c in self._classes)))

    def __repr__(self) -> str:
        return f"NielsenTuple(entries={self._entries!r})"


def _validate_entries(
    context: ConcreteGroupContext,
    entries: Sequence[Element],
    classes: Sequence[ExplicitConjugacyClass],
) -> None:
    if len(entries) != len(classes):
        raise InvalidNielsenTupleError(
            f"tuple length {len(entries)} does not match class vector length {len(classes)}"
        )
    for position, (entry, conjugacy_class) in enumerate(zip(entries, classes, strict=True)):
        context.require_same_group(conjugacy_class.group)
        if not context.contains(entry):
            raise ConcreteGroupMismatchError(
                f"entry {position} is outside the pinned concrete group"
            )
        if entry not in conjugacy_class:
            raise InvalidNielsenTupleError(
                f"entry {position} does not lie in its explicit conjugacy class"
            )
    if context.product(entries) != context.identity:
        raise InvalidNielsenTupleError("Nielsen tuple does not have product one")
    if not context.is_generated_by(entries):
        raise InvalidNielsenTupleError("Nielsen tuple does not generate the full group")


@dataclass(frozen=True)
class InnerOrbitWitness:
    """One raw valid tuple assigned to its canonical inner representative."""

    raw_key: tuple[int, ...]
    representative_key: tuple[int, ...]
    conjugator_index: int


def _portable_group_fingerprint(
    identity_index: int,
    multiplication_table: Sequence[Sequence[int]],
) -> str:
    """Derive the portable group identity from the finite table it names."""

    return sha256_hex(
        {
            "schema": "arbogast.hurwitz.portable-group.v1",
            "identity_index": identity_index,
            "multiplication_table": tuple(tuple(row) for row in multiplication_table),
        }
    )


def _portable_class_fingerprint(
    group_fingerprint: str,
    member_indices: Sequence[int],
) -> str:
    """Derive one portable conjugacy-class identity from its exact member set."""

    return sha256_hex(
        {
            "schema": "arbogast.hurwitz.portable-conjugacy-class.v1",
            "group_fingerprint": group_fingerprint,
            "member_indices": tuple(member_indices),
        }
    )


def _portable_fingerprints(
    identity_index: int,
    multiplication_table: Sequence[Sequence[int]],
    class_member_indices: Sequence[Sequence[int]],
) -> tuple[str, tuple[str, ...]]:
    group_fingerprint = _portable_group_fingerprint(identity_index, multiplication_table)
    return group_fingerprint, tuple(
        _portable_class_fingerprint(group_fingerprint, members) for members in class_member_indices
    )


@dataclass(frozen=True)
class NielsenEnumerationCertificate(ExactHurwitzCertificate):
    """Finite exhaustive receipt for a computed inner Nielsen class."""

    group: object
    group_fingerprint: str
    classes: tuple[ExplicitConjugacyClass, ...]
    candidate_count: int
    product_one_count: int
    generating_count: int
    representative_keys: tuple[tuple[int, ...], ...]
    orbit_witnesses: tuple[InnerOrbitWitness, ...]
    schema: str = "arbogast.hurwitz.nielsen-enumeration.v1"

    def to_canonical(self) -> dict[str, object]:
        """Return the portable payload covered by :attr:`certificate_id`."""

        context = ConcreteGroupContext.build(self.group)
        identity_index = context.index(context.identity)
        multiplication_table = tuple(
            tuple(context.index(context.multiply(left, right)) for right in context.elements)
            for left in context.elements
        )
        class_member_indices = tuple(
            tuple(context.index(member) for member in value.members) for value in self.classes
        )
        group_fingerprint, class_fingerprints = _portable_fingerprints(
            identity_index,
            multiplication_table,
            class_member_indices,
        )
        return {
            "schema_version": self.schema,
            "layer": self.layer.value,
            "group_fingerprint": group_fingerprint,
            "identity_index": identity_index,
            "multiplication_table": multiplication_table,
            "class_fingerprints": class_fingerprints,
            "class_member_indices": class_member_indices,
            "inner_conjugacy_convention": INNER_CONJUGACY_CONVENTION,
            "candidate_count": self.candidate_count,
            "product_one_count": self.product_one_count,
            "generating_count": self.generating_count,
            "representative_keys": self.representative_keys,
            "orbit_witnesses": tuple(
                {
                    "raw_key": witness.raw_key,
                    "representative_key": witness.representative_key,
                    "conjugator_index": witness.conjugator_index,
                }
                for witness in self.orbit_witnesses
            ),
            "claim": "complete inner Nielsen class for the ordered explicit class vector",
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
        *,
        group: object,
        classes: Sequence[object],
    ) -> NielsenEnumerationCertificate:
        """Bind a transported receipt to an explicitly supplied concrete group.

        Deserialization never discovers or transports a group embedding.  The
        supplied group and explicit classes must reproduce the payload's exact
        fingerprints, after which any advertised content address is checked.
        Mathematical acceptance still requires :meth:`verify`.
        """

        context = ConcreteGroupContext.build(group)
        explicit = _explicit_classes(context, classes)
        if payload.get("schema_version") != "arbogast.hurwitz.nielsen-enumeration.v1":
            raise CertificateVerificationError("unsupported Nielsen certificate schema")
        identity_index = context.index(context.identity)
        multiplication_table = tuple(
            tuple(context.index(context.multiply(left, right)) for right in context.elements)
            for left in context.elements
        )
        class_member_indices = tuple(
            tuple(context.index(member) for member in value.members) for value in explicit
        )
        expected_group, expected_classes = _portable_fingerprints(
            identity_index,
            multiplication_table,
            class_member_indices,
        )
        if payload.get("group_fingerprint") != expected_group:
            raise CertificateVerificationError("transported portable group fingerprint mismatch")
        raw_class_fingerprints = cast(Sequence[object], payload.get("class_fingerprints", ()))
        if tuple(raw_class_fingerprints) != expected_classes:
            raise CertificateVerificationError(
                "transported portable class-vector fingerprint mismatch"
            )
        if payload.get("inner_conjugacy_convention") != INNER_CONJUGACY_CONVENTION:
            raise CertificateVerificationError("inner-conjugacy convention mismatch")
        try:
            raw_representative_keys = cast(
                Sequence[Sequence[object]], payload["representative_keys"]
            )
            raw_witnesses = cast(Sequence[Mapping[str, Any]], payload["orbit_witnesses"])
            representative_keys = tuple(
                tuple(int(cast(Any, entry)) for entry in key) for key in raw_representative_keys
            )
            witnesses = tuple(
                InnerOrbitWitness(
                    tuple(int(entry) for entry in cast(Sequence[Any], witness["raw_key"])),
                    tuple(
                        int(entry) for entry in cast(Sequence[Any], witness["representative_key"])
                    ),
                    int(witness["conjugator_index"]),
                )
                for witness in raw_witnesses
            )
            certificate = cls(
                group,
                context.fingerprint,
                explicit,
                int(cast(Any, payload["candidate_count"])),
                int(cast(Any, payload["product_one_count"])),
                int(cast(Any, payload["generating_count"])),
                representative_keys,
                witnesses,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CertificateVerificationError(
                "malformed transported Nielsen certificate payload"
            ) from exc
        expected_id = payload.get("certificate_id")
        if expected_id is not None:
            certificate.verify_integrity(str(expected_id))
        return certificate

    def verify(self) -> bool:
        verify_nielsen_certificate_payload(self.to_canonical())
        context = ConcreteGroupContext.build(self.group)
        if context.fingerprint != self.group_fingerprint:
            raise CertificateVerificationError("certificate group fingerprint mismatch")
        for conjugacy_class in self.classes:
            context.require_same_group(conjugacy_class.group)
            ExplicitConjugacyClass.build(context, conjugacy_class)
        raw = _enumerate_raw(context, self.classes, shard_index=0, shard_count=1)
        if raw.candidate_count != self.candidate_count:
            raise CertificateVerificationError("candidate-count mismatch")
        if raw.product_one_count != self.product_one_count:
            raise CertificateVerificationError("product-one count mismatch")
        if len(raw.valid_entries) != self.generating_count:
            raise CertificateVerificationError("generating-tuple count mismatch")
        expected_witnesses: list[InnerOrbitWitness] = []
        expected_representatives: set[tuple[int, ...]] = set()
        for entries in raw.valid_entries:
            canonical, by = context.canonical_conjugate(entries)
            canonical_key = context.tuple_key(canonical)
            expected_representatives.add(canonical_key)
            expected_witnesses.append(
                InnerOrbitWitness(context.tuple_key(entries), canonical_key, context.index(by))
            )
        if tuple(sorted(expected_representatives)) != self.representative_keys:
            raise CertificateVerificationError("canonical representative list mismatch")
        if tuple(sorted(expected_witnesses, key=lambda item: item.raw_key)) != self.orbit_witnesses:
            raise CertificateVerificationError("inner-orbit partition witness mismatch")
        return True

    def verification_certificate(self) -> object:
        """Return the claim-bound generic envelope accepted by the central verifier."""

        from .claims import verification_certificate_for

        return verification_certificate_for(self)


def verify_nielsen_certificate_payload(payload: Mapping[str, object]) -> bool:
    """Independently replay a portable Nielsen payload using only finite tables."""

    try:
        if payload.get("schema_version") != "arbogast.hurwitz.nielsen-enumeration.v1":
            raise CertificateVerificationError("unsupported Nielsen certificate schema")
        if payload.get("inner_conjugacy_convention") != INNER_CONJUGACY_CONVENTION:
            raise CertificateVerificationError("inner-conjugacy convention mismatch")
        raw_table = cast(Sequence[Sequence[Any]], payload["multiplication_table"])
        table = tuple(tuple(int(entry) for entry in row) for row in raw_table)
        size = len(table)
        if size == 0 or any(len(row) != size for row in table):
            raise CertificateVerificationError("multiplication table must be nonempty and square")
        if any(entry < 0 or entry >= size for row in table for entry in row):
            raise CertificateVerificationError("multiplication table entry is out of range")
        identity = int(cast(Any, payload["identity_index"]))
        if not 0 <= identity < size:
            raise CertificateVerificationError("identity index is out of range")
        if any(
            table[identity][item] != item or table[item][identity] != item for item in range(size)
        ):
            raise CertificateVerificationError("advertised identity fails the group law")
        for left in range(size):
            for middle in range(size):
                for right in range(size):
                    if table[table[left][middle]][right] != table[left][table[middle][right]]:
                        raise CertificateVerificationError(
                            "multiplication table is not associative"
                        )
        inverses: list[int] = []
        for element in range(size):
            candidates = [
                value
                for value in range(size)
                if table[element][value] == identity and table[value][element] == identity
            ]
            if len(candidates) != 1:
                raise CertificateVerificationError("group element lacks a unique two-sided inverse")
            inverses.append(candidates[0])

        raw_classes = cast(Sequence[Sequence[Any]], payload["class_member_indices"])
        classes = tuple(tuple(int(entry) for entry in row) for row in raw_classes)
        if not classes or any(not row for row in classes):
            raise CertificateVerificationError("ordered class vector must be nonempty")
        for members in classes:
            if len(set(members)) != len(members) or any(
                member < 0 or member >= size for member in members
            ):
                raise CertificateVerificationError("invalid explicit class member indices")
            class_representative = members[0]
            orbit = {table[table[inverses[by]][class_representative]][by] for by in range(size)}
            if orbit != set(members):
                raise CertificateVerificationError("class members are not one conjugacy orbit")

        expected_group, expected_classes = _portable_fingerprints(identity, table, classes)
        if payload.get("group_fingerprint") != expected_group:
            raise CertificateVerificationError("portable group fingerprint mismatch")
        raw_class_fingerprints = payload.get("class_fingerprints")
        if isinstance(raw_class_fingerprints, (str, bytes)) or not isinstance(
            raw_class_fingerprints, Sequence
        ):
            raise CertificateVerificationError("portable class fingerprints must be a sequence")
        if tuple(raw_class_fingerprints) != expected_classes:
            raise CertificateVerificationError("portable class-vector fingerprint mismatch")

        def multiply(left: int, right: int) -> int:
            return table[left][right]

        def product_indices(entries: Sequence[int]) -> int:
            result = identity
            for entry in entries:
                result = multiply(result, entry)
            return result

        def generated(entries: Sequence[int]) -> bool:
            moves = tuple(entries) + tuple(inverses[entry] for entry in entries)
            seen = {identity}
            frontier = [identity]
            while frontier:
                current = frontier.pop()
                for move in moves:
                    candidate = multiply(current, move)
                    if candidate not in seen:
                        seen.add(candidate)
                        frontier.append(candidate)
            return len(seen) == size

        def canonical(entries: Sequence[int]) -> tuple[tuple[int, ...], int]:
            candidates = tuple(
                (
                    tuple(multiply(multiply(inverses[by], entry), by) for entry in entries),
                    by,
                )
                for by in range(size)
            )
            return min(candidates, key=lambda item: item[0])

        candidate_count = 0
        product_one_count = 0
        valid: list[tuple[int, ...]] = []
        prefix_classes = classes[:-1]
        prefixes: Iterable[tuple[int, ...]] = product(*prefix_classes) if prefix_classes else [()]
        final_class = set(classes[-1])
        for prefix in prefixes:
            candidate_count += 1
            last = inverses[product_indices(prefix)]
            if last not in final_class:
                continue
            product_one_count += 1
            entries = (*prefix, last)
            if generated(entries):
                valid.append(entries)
        valid.sort()
        expected_representatives: set[tuple[int, ...]] = set()
        expected_witnesses: list[InnerOrbitWitness] = []
        for entries in valid:
            canonical_representative, conjugator = canonical(entries)
            expected_representatives.add(canonical_representative)
            expected_witnesses.append(
                InnerOrbitWitness(entries, canonical_representative, conjugator)
            )

        if int(cast(Any, payload["candidate_count"])) != candidate_count:
            raise CertificateVerificationError("portable candidate-count mismatch")
        if int(cast(Any, payload["product_one_count"])) != product_one_count:
            raise CertificateVerificationError("portable product-one count mismatch")
        if int(cast(Any, payload["generating_count"])) != len(valid):
            raise CertificateVerificationError("portable generating-tuple count mismatch")
        raw_representatives = cast(Sequence[Sequence[Any]], payload["representative_keys"])
        advertised_representatives = tuple(
            tuple(int(entry) for entry in row) for row in raw_representatives
        )
        if advertised_representatives != tuple(sorted(expected_representatives)):
            raise CertificateVerificationError("portable representative list mismatch")
        raw_witnesses = cast(Sequence[Mapping[str, Any]], payload["orbit_witnesses"])
        advertised_witnesses = tuple(
            InnerOrbitWitness(
                tuple(int(entry) for entry in cast(Sequence[Any], witness["raw_key"])),
                tuple(int(entry) for entry in cast(Sequence[Any], witness["representative_key"])),
                int(witness["conjugator_index"]),
            )
            for witness in raw_witnesses
        )
        if advertised_witnesses != tuple(sorted(expected_witnesses, key=lambda item: item.raw_key)):
            raise CertificateVerificationError("portable inner-orbit witness mismatch")
    except CertificateVerificationError:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise CertificateVerificationError("malformed portable Nielsen certificate") from exc
    return True


@dataclass(frozen=True)
class NielsenShardSpec:
    """A deterministic residue-class shard of the prefix Cartesian product."""

    group_fingerprint: str
    class_fingerprints: tuple[str, ...]
    index: int
    count: int

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("shard count must be positive")
        if not 0 <= self.index < self.count:
            raise ValueError("shard index must satisfy 0 <= index < count")


@dataclass(frozen=True)
class NielsenShardResult:
    spec: NielsenShardSpec
    candidate_count: int
    product_one_count: int
    valid_entries: tuple[tuple[Element, ...], ...]


@dataclass(frozen=True)
class CanonicalizationWitness:
    representative_index: int
    representative: NielsenTuple
    conjugator: Element


@dataclass(frozen=True)
class ImportedNielsenBoundary:
    """Typed provenance boundary for representatives loaded without a proof of completeness."""

    source: str
    sha256: str
    schema: str
    declared_cardinality: int
    status: str = "IMPORTED"

    @property
    def completeness_certified(self) -> bool:
        return False


class NielsenClass(Sequence[NielsenTuple]):
    """Canonical inner representatives for an ordered explicit class vector."""

    def __init__(
        self,
        context: ConcreteGroupContext,
        classes: tuple[ExplicitConjugacyClass, ...],
        representatives: Sequence[NielsenTuple],
        *,
        certificate: NielsenEnumerationCertificate | None,
        imported_boundary: ImportedNielsenBoundary | None = None,
    ) -> None:
        if certificate is not None and imported_boundary is not None:
            raise ValueError("a Nielsen class cannot be both computed-complete and imported-only")
        canonical: list[NielsenTuple] = []
        seen: set[tuple[int, ...]] = set()
        for representative in representatives:
            context.require_same_group(representative.group)
            _validate_entries(context, representative.entries, classes)
            entries, _ = context.canonical_conjugate(representative.entries)
            key = context.tuple_key(entries)
            if representative.entries != entries:
                raise InvalidNielsenTupleError(
                    "NielsenClass representatives must already be inner-canonical"
                )
            if key in seen:
                raise InvalidNielsenTupleError("duplicate inner-canonical representative")
            seen.add(key)
            canonical.append(representative)
        canonical.sort(key=lambda value: value.key())
        self._context = context
        self._classes = classes
        self._representatives = tuple(canonical)
        self._index = {representative.key(): i for i, representative in enumerate(canonical)}
        self._certificate = certificate
        self._imported_boundary = imported_boundary

    @property
    def group(self) -> object:
        return self._context.group

    @property
    def context(self) -> ConcreteGroupContext:
        return self._context

    @property
    def classes(self) -> tuple[ExplicitConjugacyClass, ...]:
        return self._classes

    @property
    def representatives(self) -> tuple[NielsenTuple, ...]:
        return self._representatives

    @property
    def certificate(self) -> NielsenEnumerationCertificate | None:
        return self._certificate

    @property
    def imported_boundary(self) -> ImportedNielsenBoundary | None:
        return self._imported_boundary

    @property
    def has_completeness_certificate(self) -> bool:
        """Report receipt presence only; call :meth:`verify` for acceptance."""

        return self._certificate is not None

    @property
    def cardinality(self) -> int:
        return len(self)

    def verify(self, *, require_complete: bool = True) -> bool:
        for representative in self._representatives:
            representative.verify()
            canonical, _ = self._context.canonical_conjugate(representative.entries)
            if canonical != representative.entries:
                raise CertificateVerificationError("representative is not inner-canonical")
        if require_complete:
            if self._certificate is None:
                raise CertificateVerificationError(
                    "this Nielsen class crosses an imported boundary and has no completeness proof"
                )
            self._certificate.verify()
            if self._certificate.representative_keys != tuple(
                representative.key() for representative in self._representatives
            ):
                raise CertificateVerificationError(
                    "certificate does not bind this representative list"
                )
        return True

    def canonicalize(self, value: NielsenTuple | Sequence[Element]) -> CanonicalizationWitness:
        if isinstance(value, NielsenTuple):
            self._context.require_same_group(value.group)
            entries = value.entries
        else:
            entries = tuple(value)
        if len(entries) != len(self._classes):
            raise BraidClosureError("tuple length changed while canonicalizing braid image")
        canonical, conjugator = self._context.canonical_conjugate(entries)
        key = self._context.tuple_key(canonical)
        try:
            index = self._index[key]
        except KeyError as exc:
            raise BraidClosureError(
                "canonical image is absent from the supplied Nielsen class; "
                "the class vector or imported dataset is not closed under this operation"
            ) from exc
        return CanonicalizationWitness(index, self._representatives[index], conjugator)

    def plan(self, shards: int) -> NielsenEnumerationPlan:
        return NielsenEnumerationPlan._from_context(self._context, self._classes, shards=shards)

    def claim(self, *, claim_id: str | None = None) -> Claim:
        from .claims import claim_for

        return claim_for(self, claim_id=claim_id)

    def claim_graph(self, *, claim_id: str | None = None) -> ClaimGraph:
        from .claims import claim_graph_for

        return claim_graph_for(self, claim_id=claim_id)

    def __len__(self) -> int:
        return len(self._representatives)

    @overload
    def __getitem__(self, index: int) -> NielsenTuple: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[NielsenTuple, ...]: ...

    def __getitem__(self, index: int | slice) -> NielsenTuple | tuple[NielsenTuple, ...]:
        return self._representatives[index]

    def __iter__(self) -> Iterator[NielsenTuple]:
        return iter(self._representatives)


@dataclass(frozen=True)
class _RawEnumeration:
    candidate_count: int
    product_one_count: int
    valid_entries: tuple[tuple[Element, ...], ...]


def _enumerate_raw(
    context: ConcreteGroupContext,
    classes: Sequence[ExplicitConjugacyClass],
    *,
    shard_index: int,
    shard_count: int,
) -> _RawEnumeration:
    prefix_classes = classes[:-1]
    candidate_count = 0
    product_one_count = 0
    valid: list[tuple[Element, ...]] = []
    prefixes: Iterable[tuple[Element, ...]]
    if prefix_classes:
        prefixes = product(*(conjugacy_class.members for conjugacy_class in prefix_classes))
    else:
        prefixes = [()]
    final_class = classes[-1]
    for ordinal, prefix in enumerate(prefixes):
        if ordinal % shard_count != shard_index:
            continue
        candidate_count += 1
        last = context.inverse(context.product(prefix))
        if last not in final_class:
            continue
        product_one_count += 1
        entries = (*prefix, last)
        if context.is_generated_by(entries):
            valid.append(entries)
    valid.sort(key=context.tuple_key)
    return _RawEnumeration(candidate_count, product_one_count, tuple(valid))


class NielsenEnumerationPlan:
    """Deterministic, independently reducible Nielsen enumeration plan."""

    def __init__(self, group: object, classes: Sequence[object], *, shards: int = 1) -> None:
        context = ConcreteGroupContext.build(group)
        explicit = _explicit_classes(context, classes)
        self._initialize(context, explicit, shards)

    @classmethod
    def _from_context(
        cls,
        context: ConcreteGroupContext,
        classes: Sequence[ExplicitConjugacyClass],
        *,
        shards: int,
    ) -> NielsenEnumerationPlan:
        instance = object.__new__(cls)
        instance._initialize(context, tuple(classes), shards)
        return instance

    def _initialize(
        self,
        context: ConcreteGroupContext,
        classes: tuple[ExplicitConjugacyClass, ...],
        shards: int,
    ) -> None:
        if shards <= 0:
            raise ValueError("shards must be positive")
        self.context = context
        self.classes = classes
        self.shard_count = shards

    @property
    def candidate_count(self) -> int:
        return math.prod(len(conjugacy_class) for conjugacy_class in self.classes[:-1])

    @property
    def shard_specs(self) -> tuple[NielsenShardSpec, ...]:
        return tuple(
            NielsenShardSpec(
                self.context.fingerprint,
                tuple(conjugacy_class.fingerprint for conjugacy_class in self.classes),
                index,
                self.shard_count,
            )
            for index in range(self.shard_count)
        )

    def run(self, shard: NielsenShardSpec | int) -> NielsenShardResult:
        spec = self.shard_specs[shard] if isinstance(shard, int) else shard
        if spec not in self.shard_specs:
            raise ValueError("shard spec does not belong to this exact enumeration plan")
        raw = _enumerate_raw(
            self.context,
            self.classes,
            shard_index=spec.index,
            shard_count=spec.count,
        )
        return NielsenShardResult(
            spec, raw.candidate_count, raw.product_one_count, raw.valid_entries
        )

    def run_all(self) -> tuple[NielsenShardResult, ...]:
        return tuple(self.run(spec) for spec in self.shard_specs)

    def reduce(self, results: Iterable[NielsenShardResult]) -> NielsenClass:
        by_index: dict[int, NielsenShardResult] = {}
        expected_specs = self.shard_specs
        for result in results:
            if result.spec not in expected_specs:
                raise CertificateVerificationError("foreign shard result in Nielsen reduction")
            if result.spec.index in by_index:
                raise CertificateVerificationError("duplicate Nielsen shard result")
            by_index[result.spec.index] = result
        if set(by_index) != set(range(self.shard_count)):
            missing = sorted(set(range(self.shard_count)) - set(by_index))
            raise CertificateVerificationError(f"missing Nielsen shards: {missing}")

        candidate_count = sum(result.candidate_count for result in by_index.values())
        product_one_count = sum(result.product_one_count for result in by_index.values())
        if candidate_count != self.candidate_count:
            raise CertificateVerificationError("shards do not cover the candidate space exactly")
        valid_entries = sorted(
            (entries for result in by_index.values() for entries in result.valid_entries),
            key=self.context.tuple_key,
        )

        representative_entries: dict[tuple[int, ...], tuple[Element, ...]] = {}
        witnesses: list[InnerOrbitWitness] = []
        for entries in valid_entries:
            canonical, conjugator = self.context.canonical_conjugate(entries)
            key = self.context.tuple_key(canonical)
            representative_entries.setdefault(key, canonical)
            witnesses.append(
                InnerOrbitWitness(
                    self.context.tuple_key(entries), key, self.context.index(conjugator)
                )
            )
        representative_keys = tuple(sorted(representative_entries))
        representatives = tuple(
            NielsenTuple._from_context(
                self.context,
                representative_entries[key],
                self.classes,
                validate=True,
            )
            for key in representative_keys
        )
        certificate = NielsenEnumerationCertificate(
            self.context.group,
            self.context.fingerprint,
            self.classes,
            candidate_count,
            product_one_count,
            len(valid_entries),
            representative_keys,
            tuple(sorted(witnesses, key=lambda item: item.raw_key)),
        )
        return NielsenClass(
            self.context,
            self.classes,
            representatives,
            certificate=certificate,
        )


def plan_nielsen_class(
    group: object, classes: Sequence[object], *, shards: int
) -> NielsenEnumerationPlan:
    """Plan deterministic exact enumeration without running any shard."""

    return NielsenEnumerationPlan(group, classes, shards=shards)


def nielsen_class(
    group: object,
    classes: Sequence[object],
    *,
    shards: int = 1,
) -> NielsenClass:
    """Enumerate the complete inner Nielsen class for an ordered class vector."""

    plan = NielsenEnumerationPlan(group, classes, shards=shards)
    result = plan.reduce(plan.run_all())
    result.verify()
    return result


def nielsen_tuple(
    group: object, entries: Sequence[Element], classes: Sequence[object]
) -> NielsenTuple:
    """Construct and verify one exact Nielsen tuple."""

    return NielsenTuple(group, entries, classes)
