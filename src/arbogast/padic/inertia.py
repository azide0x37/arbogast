"""Bounded declared finite inertia presentations, filtrations, and actions.

Only an explicitly enumerated finite group presentation labelled as inertia
data is represented here.  Without a separate arithmetic-origin witness it is
not proof that this group or filtration comes from local inertia.  The objects
also neither present continuous inertia nor import the Nielsen-class machinery
used for branched-cover calculations.  Every group element, product, inverse,
declared filtration subgroup, and action matrix is replayed inside the finite
proof boundary.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from math import gcd
from typing import TYPE_CHECKING, Any, cast

from arbogast.core import CanonicalJSON
from arbogast.rep import Permutation, PermutationGroup

from ._schema import (
    MAX_DIMENSION,
    MAX_EXACT_REPLAY_WORK,
    MAX_GROUP_ORDER,
    MAX_PRECISION_WORK,
    MAX_PRIME_BITS,
    PAdicSchemaObject,
    canonical_label,
    strict_canonical_equal,
    strict_int,
)
from .errors import PAdicResourceError, PAdicValidationError, PAdicVerificationError
from .frobenius import (
    FrobeniusConvention,
    FrobeniusOperator,
    _decode_matrix_document,
    _decode_module_document,
    _decode_operator_document,
    _document_body,
    _matrix_base,
    _matrix_identity,
    _matrix_shape,
    _module_base,
    _module_rank,
    _object_id,
    _raw_list,
    _raw_object,
    _sigma_matrix,
)

if TYPE_CHECKING:
    from arbogast.cert import VerificationCertificate

    from .certificate import PAdicPayloadReplay
    from .matrices import PAdicMatrix
    from .modules import PAdicModule
    from .results import PAdicResult

MAX_INERTIA_PRIME = 2_147_483_647


def _is_prime(value: int) -> bool:
    if value < 2:
        return False
    if value in (2, 3):
        return True
    if value % 2 == 0 or value % 3 == 0:
        return False
    divisor = 5
    step = 2
    while divisor * divisor <= value:
        if value % divisor == 0:
            return False
        divisor += step
        step = 6 - step
    return True


def _group_lookup(group: PermutationGroup) -> dict[Permutation, int]:
    return {element: index for index, element in enumerate(group.elements)}


def _bounded_group_from_generators(
    generators: Sequence[Permutation],
    *,
    degree: int,
) -> PermutationGroup:
    """Reconstruct a concrete group only after bounded closure enumeration.

    ``PermutationGroup`` deliberately performs an unbounded breadth-first
    closure.  Receipt data are hostile input, so replay first runs the same
    elementary closure calculation with an explicit order and composition-work
    ceiling.  Only a closure already known to fit the portable envelope is
    handed to the general constructor.
    """

    if degree > MAX_DIMENSION:
        raise PAdicResourceError("finite inertia permutation degree exceeds the portable bound")
    if len(generators) > MAX_GROUP_ORDER:
        raise PAdicResourceError("finite inertia generator count exceeds the portable bound")
    identity = Permutation.identity(degree)
    moves = tuple(
        sorted(
            {element for generator in generators for element in (generator, generator.inverse())}
        )
    )
    seen = {identity}
    queue: deque[Permutation] = deque((identity,))
    work = 0
    while queue:
        current = queue.popleft()
        for move in moves:
            work += max(1, degree)
            if work > MAX_EXACT_REPLAY_WORK:
                raise PAdicResourceError(
                    "finite inertia group closure exceeds the exact replay-work bound"
                )
            candidate = current * move
            if candidate in seen:
                continue
            if len(seen) >= MAX_GROUP_ORDER:
                raise PAdicResourceError(
                    "finite inertia group closure exceeds the portable order bound"
                )
            seen.add(candidate)
            queue.append(candidate)
    return PermutationGroup(generators, degree=degree)


def _group_proof(group: PermutationGroup) -> dict[str, object]:
    proof_work = group.order**2 * max(1, group.degree)
    if proof_work > MAX_EXACT_REPLAY_WORK:
        raise PAdicResourceError("finite inertia group table exceeds the exact replay-work bound")
    lookup = _group_lookup(group)
    return {
        "composition_convention": Permutation.COMPOSITION_CONVENTION,
        "degree": group.degree,
        "elements": [list(element.images) for element in group.elements],
        "fingerprint": group.fingerprint,
        "generators": [list(generator.images) for generator in group.generators],
        "identity_index": lookup[group.identity],
        "inverse_indices": [lookup[group.inverse(element)] for element in group.elements],
        "multiplication_table": [
            [lookup[group.multiply(left, right)] for right in group.elements]
            for left in group.elements
        ],
        "order": group.order,
        "type": "arbogast.padic.finite_inertia_group_proof",
    }


def _same_quotient(left: FiniteInertiaQuotient, right: FiniteInertiaQuotient) -> bool:
    if left is right:
        return True
    return left.quotient_id == right.quotient_id


def _normalize_subgroup(
    quotient: FiniteInertiaQuotient,
    members: Sequence[Permutation],
    name: str,
) -> tuple[int, ...]:
    if isinstance(members, str | bytes):
        raise TypeError(f"{name} must be a sequence of concrete permutations")
    group = quotient.group
    lookup = _group_lookup(group)
    normalized = tuple(islice(members, quotient.order + 1))
    if len(normalized) > quotient.order:
        raise PAdicResourceError(f"{name} exceeds the finite quotient order bound")
    if any(not isinstance(element, Permutation) for element in normalized):
        raise TypeError(f"{name} entries must be Permutation objects")
    if any(element not in lookup for element in normalized):
        raise PAdicValidationError(f"{name} contains an element outside the inertia quotient")
    indices = tuple(sorted({lookup[element] for element in normalized}))
    if len(indices) != len(normalized):
        raise PAdicValidationError(f"{name} contains duplicate elements")
    return indices


def _members(group: PermutationGroup, indices: Sequence[int]) -> tuple[Permutation, ...]:
    return tuple(group.elements[index] for index in indices)


def _verify_subgroup(
    group: PermutationGroup,
    indices: tuple[int, ...],
    name: str,
    *,
    normal_in: tuple[int, ...] | None = None,
) -> None:
    lookup = _group_lookup(group)
    subset = frozenset(_members(group, indices))
    if not subset or group.identity not in subset:
        raise PAdicVerificationError(f"{name} is not a nonempty subgroup candidate")
    for left in subset:
        if group.inverse(left) not in subset:
            raise PAdicVerificationError(f"{name} is not closed under inverses")
        for right in subset:
            if group.multiply(left, right) not in subset:
                raise PAdicVerificationError(f"{name} is not closed under multiplication")
    ambient = group.elements if normal_in is None else _members(group, normal_in)
    for conjugator in ambient:
        inverse = group.inverse(conjugator)
        for element in subset:
            conjugate = group.multiply(group.multiply(conjugator, element), inverse)
            if conjugate not in subset:
                raise PAdicVerificationError(f"{name} is not normal in its declared ambient group")
    if tuple(sorted(lookup[element] for element in subset)) != indices:
        raise PAdicVerificationError(f"{name} indices are not canonical")


def _is_power(value: int, prime: int) -> bool:
    remaining = value
    while remaining > 1 and remaining % prime == 0:
        remaining //= prime
    return remaining == 1


def _power(group: PermutationGroup, element: Permutation, exponent: int) -> Permutation:
    if exponent < 0:
        return _power(group, group.inverse(element), -exponent)
    result = group.identity
    factor = element
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = group.multiply(result, factor)
        factor = group.multiply(factor, factor)
        remaining >>= 1
    return result


def _coset_generated(
    group: PermutationGroup,
    element: Permutation,
    subgroup_indices: tuple[int, ...],
    ambient_indices: tuple[int, ...],
) -> bool:
    subgroup = _members(group, subgroup_indices)
    ambient = frozenset(_members(group, ambient_indices))
    generated: set[Permutation] = set()
    power = group.identity
    coset_count = len(ambient) // len(subgroup)
    for _ in range(coset_count):
        generated.update(group.multiply(power, member) for member in subgroup)
        power = group.multiply(power, element)
    return generated == ambient


def _verify_tame_quotient(
    group: PermutationGroup,
    level_zero: tuple[int, ...],
    level_one: tuple[int, ...],
    residue_characteristic: int,
) -> None:
    if len(level_zero) % len(level_one):
        raise PAdicVerificationError("the tame filtration index is not integral")
    order = len(level_zero) // len(level_one)
    if gcd(order, residue_characteristic) != 1:
        raise PAdicVerificationError("the tame inertia quotient has residue-characteristic torsion")
    if not any(
        _coset_generated(group, element, level_one, level_zero)
        for element in _members(group, level_zero)
    ):
        raise PAdicVerificationError("the tame inertia quotient is not cyclic")


def _verify_wild_step(
    group: PermutationGroup,
    upper: tuple[int, ...],
    lower: tuple[int, ...],
    residue_characteristic: int,
    index: int,
) -> None:
    if len(upper) % len(lower):
        raise PAdicVerificationError(f"wild filtration quotient G_{index}/G_{index + 1} is invalid")
    quotient_order = len(upper) // len(lower)
    if not _is_power(quotient_order, residue_characteristic):
        raise PAdicVerificationError(
            f"wild filtration quotient G_{index}/G_{index + 1} is not a p-group"
        )
    lower_members = frozenset(_members(group, lower))
    upper_members = _members(group, upper)
    for left in upper_members:
        if _power(group, left, residue_characteristic) not in lower_members:
            raise PAdicVerificationError(
                f"wild filtration quotient G_{index}/G_{index + 1} has exponent greater than p"
            )
        for right in upper_members:
            commutator = group.multiply(
                group.multiply(group.multiply(left, right), group.inverse(left)),
                group.inverse(right),
            )
            if commutator not in lower_members:
                raise PAdicVerificationError(
                    f"wild filtration quotient G_{index}/G_{index + 1} is not abelian"
                )


@dataclass(frozen=True, slots=True, init=False)
class FiniteInertiaQuotient(PAdicSchemaObject):
    """A declared concrete finite group presentation labelled by source/place.

    The presentation is exhaustive as a finite group.  It is not, by itself,
    arithmetic evidence that the group occurs as a quotient of local inertia.
    """

    source_id: str
    place_id: str
    residue_characteristic: int
    residue_degree: int
    residue_cardinality: int
    group: PermutationGroup
    arithmetic_origin_claimed: bool

    schema_version = "arbogast.padic.finite-inertia-quotient/v1"

    def __init__(
        self,
        source_id: str,
        place_id: str,
        residue_characteristic: int,
        residue_degree: int,
        group: PermutationGroup,
    ) -> None:
        normalized_source = canonical_label(source_id, "inertia source ID")
        normalized_place = canonical_label(place_id, "inertia place ID")
        prime = strict_int(
            residue_characteristic,
            "inertia residue characteristic",
            minimum=2,
        )
        if prime.bit_length() > MAX_PRIME_BITS:
            raise PAdicResourceError("inertia residue characteristic exceeds the bit bound")
        if prime > MAX_INERTIA_PRIME:
            raise PAdicResourceError(
                "inertia residue characteristic exceeds the deterministic-prime bound"
            )
        if not _is_prime(prime):
            raise PAdicValidationError("inertia residue characteristic must be prime")
        degree = strict_int(residue_degree, "inertia residue degree", minimum=1)
        if degree > MAX_DIMENSION:
            raise PAdicValidationError("inertia residue degree exceeds the portable bound")
        if not isinstance(group, PermutationGroup):
            raise TypeError("finite inertia quotient group must be a PermutationGroup")
        if group.degree > MAX_DIMENSION:
            raise PAdicResourceError("finite inertia permutation degree exceeds the portable bound")
        if group.order > MAX_GROUP_ORDER:
            raise PAdicValidationError("finite inertia quotient exceeds the portable group bound")
        if group.order**2 * max(1, group.degree) > MAX_EXACT_REPLAY_WORK:
            raise PAdicResourceError(
                "finite inertia group table exceeds the exact replay-work bound"
            )
        object.__setattr__(self, "source_id", normalized_source)
        object.__setattr__(self, "place_id", normalized_place)
        object.__setattr__(self, "residue_characteristic", prime)
        object.__setattr__(self, "residue_degree", degree)
        object.__setattr__(self, "residue_cardinality", prime**degree)
        object.__setattr__(self, "group", group)
        object.__setattr__(self, "arithmetic_origin_claimed", False)

    @property
    def quotient_id(self) -> str:
        return self.content_id

    @property
    def order(self) -> int:
        return self.group.order

    def verify(self) -> bool:
        replay = FiniteInertiaQuotient(
            self.source_id,
            self.place_id,
            self.residue_characteristic,
            self.residue_degree,
            self.group,
        )
        if replay.to_canonical_data() != self.to_canonical_data():
            raise PAdicVerificationError("finite inertia quotient replay was altered")
        proof = _group_proof(self.group)
        if len(proof["multiplication_table"]) != self.group.order:  # type: ignore[arg-type]
            raise PAdicVerificationError("finite inertia multiplication table is incomplete")
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return cast(
            CanonicalJSON,
            {
                "arithmetic_origin_claimed": self.arithmetic_origin_claimed,
                "group": _group_proof(self.group),
                "place_id": self.place_id,
                "residue_cardinality": self.residue_cardinality,
                "residue_characteristic": self.residue_characteristic,
                "residue_degree": self.residue_degree,
                "source_id": self.source_id,
                "scope": (
                    "declared finite group presentation labelled by source and place; "
                    "no arithmetic-origin or continuous-inertia claim"
                ),
                "type": "arbogast.padic.finite_inertia_quotient",
            },
        )


@dataclass(frozen=True, slots=True, init=False)
class InertiaFiltration(PAdicSchemaObject):
    """A declared finite group-theoretic series ``G_0, G_1, ...``.

    The checks replay necessary abstract subgroup and quotient identities.  No
    local extension, valuation action, or theorem witness is present, so the
    indices are not certified as the arithmetic lower ramification numbering.
    """

    quotient: FiniteInertiaQuotient
    level_indices: tuple[tuple[int, ...], ...]
    arithmetic_lower_numbering_claimed: bool

    schema_version = "arbogast.padic.inertia-filtration/v1"

    def __init__(
        self,
        quotient: FiniteInertiaQuotient,
        levels: Sequence[Sequence[Permutation]],
    ) -> None:
        if not isinstance(quotient, FiniteInertiaQuotient):
            raise TypeError("inertia filtration requires a FiniteInertiaQuotient")
        if isinstance(levels, str | bytes):
            raise TypeError("inertia filtration levels must be finite sequences")
        raw_levels = tuple(islice(levels, MAX_GROUP_ORDER + 1))
        if len(raw_levels) > MAX_GROUP_ORDER:
            raise PAdicResourceError("inertia filtration exceeds the portable level bound")
        normalized = tuple(
            _normalize_subgroup(quotient, level, f"inertia filtration G_{index}")
            for index, level in enumerate(raw_levels)
        )
        if len(normalized) < 2:
            raise PAdicValidationError("inertia filtration must explicitly include G_0 and G_1")
        filtration_work = 4 * len(normalized) * quotient.order**2 * max(1, quotient.group.degree)
        if filtration_work > MAX_EXACT_REPLAY_WORK:
            raise PAdicResourceError("inertia filtration exceeds the exact replay-work bound")
        object.__setattr__(self, "quotient", quotient)
        object.__setattr__(self, "level_indices", normalized)
        object.__setattr__(self, "arithmetic_lower_numbering_claimed", False)
        self.verify()

    @property
    def filtration_id(self) -> str:
        return self.content_id

    @property
    def levels(self) -> tuple[tuple[Permutation, ...], ...]:
        return tuple(_members(self.quotient.group, level) for level in self.level_indices)

    @property
    def tame_order(self) -> int:
        return len(self.level_indices[0]) // len(self.level_indices[1])

    def verify(self) -> bool:
        self.quotient.verify()
        group = self.quotient.group
        all_indices = tuple(range(group.order))
        identity_index = _group_lookup(group)[group.identity]
        if self.level_indices[0] != all_indices:
            raise PAdicVerificationError("G_0 does not exhaust the finite inertia quotient")
        if self.level_indices[-1] != (identity_index,):
            raise PAdicVerificationError("the declared finite filtration does not end at identity")
        for index, level in enumerate(self.level_indices):
            _verify_subgroup(group, level, f"G_{index}", normal_in=all_indices)
            if index and not set(level).issubset(self.level_indices[index - 1]):
                raise PAdicVerificationError("declared inertia filtration is not nested")
        _verify_tame_quotient(
            group,
            self.level_indices[0],
            self.level_indices[1],
            self.quotient.residue_characteristic,
        )
        for index in range(1, len(self.level_indices) - 1):
            _verify_wild_step(
                group,
                self.level_indices[index],
                self.level_indices[index + 1],
                self.quotient.residue_characteristic,
                index,
            )
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        return {
            "arithmetic_lower_numbering_claimed": self.arithmetic_lower_numbering_claimed,
            "level_element_indices": [list(level) for level in self.level_indices],
            "numbering": "declared-indexed-series",
            "quotient_id": self.quotient.quotient_id,
            "scope": (
                "finite group-theoretic filtration identities only; no arithmetic "
                "ramification-origin or lower-numbering claim"
            ),
            "tame_quotient_order": self.tame_order,
            "type": "arbogast.padic.inertia_filtration",
            "wild_residue_characteristic": self.quotient.residue_characteristic,
        }


def _normalize_action(
    quotient: FiniteInertiaQuotient,
    action: Mapping[Permutation, PAdicMatrix] | Sequence[PAdicMatrix],
) -> tuple[PAdicMatrix, ...]:
    elements = quotient.group.elements
    if isinstance(action, Mapping):
        keys = tuple(islice(action, len(elements) + 1))
        if len(keys) != len(elements) or set(keys) != set(elements):
            raise PAdicValidationError("inertia action mapping is not the complete quotient table")
        return tuple(action[element] for element in elements)
    if isinstance(action, str | bytes):
        raise TypeError("inertia action must be a mapping or matrix sequence")
    normalized = tuple(islice(action, len(elements) + 1))
    if len(normalized) != len(elements):
        raise PAdicValidationError("inertia action sequence has the wrong group cardinality")
    return normalized


def _matrix_for(
    quotient: FiniteInertiaQuotient,
    action_matrices: tuple[PAdicMatrix, ...],
    element: Permutation,
) -> PAdicMatrix:
    return action_matrices[_group_lookup(quotient.group)[element]]


def _check_inertia_action_work(
    module: PAdicModule,
    quotient: FiniteInertiaQuotient,
) -> None:
    rank = _module_rank(module)
    base = _module_base(module)
    degree = base.field.degree
    precision = base.precision
    algebra_work = quotient.order**2 * rank**3 * degree * min(precision, 4)
    precision_work = quotient.order**2 * rank**2 * degree * precision
    if algebra_work > MAX_EXACT_REPLAY_WORK:
        raise PAdicResourceError("inertia matrix action exceeds the exact algebra-work bound")
    if precision_work > MAX_PRECISION_WORK:
        raise PAdicResourceError("inertia matrix action exceeds the precision-work bound")


@dataclass(frozen=True, slots=True, init=False)
class InertiaRepresentation(PAdicSchemaObject):
    """An exhaustively replayed matrix action of a finite inertia quotient."""

    module: PAdicModule
    quotient: FiniteInertiaQuotient
    filtration: InertiaFiltration
    action_matrices: tuple[PAdicMatrix, ...]
    frobenius_operator: FrobeniusOperator | None
    tame_generator_index: int | None

    schema_version = "arbogast.padic.inertia-representation/v1"

    def __init__(
        self,
        module: PAdicModule,
        quotient: FiniteInertiaQuotient,
        filtration: InertiaFiltration,
        action: Mapping[Permutation, PAdicMatrix] | Sequence[PAdicMatrix],
        *,
        frobenius_operator: FrobeniusOperator | None = None,
        tame_generator: Permutation | None = None,
    ) -> None:
        from .modules import PAdicModule

        if not isinstance(module, PAdicModule):
            raise TypeError("inertia representation module must be a PAdicModule")
        if not isinstance(quotient, FiniteInertiaQuotient):
            raise TypeError("inertia representation quotient must be finite and concrete")
        if not isinstance(filtration, InertiaFiltration):
            raise TypeError("inertia representation filtration must be finite and declared")
        if not _same_quotient(quotient, filtration.quotient):
            raise PAdicValidationError("inertia filtration belongs to another finite quotient")
        _check_inertia_action_work(module, quotient)
        matrices = _normalize_action(quotient, action)
        if (frobenius_operator is None) != (tame_generator is None):
            raise PAdicValidationError(
                "Frobenius compatibility requires both an operator and a tame generator"
            )
        generator_index: int | None = None
        if tame_generator is not None:
            lookup = _group_lookup(quotient.group)
            if tame_generator not in lookup:
                raise PAdicValidationError("tame generator is outside the inertia quotient")
            generator_index = lookup[tame_generator]
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "quotient", quotient)
        object.__setattr__(self, "filtration", filtration)
        object.__setattr__(self, "action_matrices", matrices)
        object.__setattr__(self, "frobenius_operator", frobenius_operator)
        object.__setattr__(self, "tame_generator_index", generator_index)
        self.verify()

    @property
    def representation_id(self) -> str:
        return self.content_id

    def matrix(self, element: Permutation) -> PAdicMatrix:
        return _matrix_for(self.quotient, self.action_matrices, element)

    def _verify_frobenius_relation(self) -> None:
        operator = self.frobenius_operator
        generator_index = self.tame_generator_index
        if operator is None or generator_index is None:
            return
        if _object_id(operator.module, "module_id") != _object_id(self.module, "module_id"):
            raise PAdicVerificationError("inertia and Frobenius actions use different modules")
        group = self.quotient.group
        generator = group.elements[generator_index]
        if not _coset_generated(
            group,
            generator,
            self.filtration.level_indices[1],
            self.filtration.level_indices[0],
        ):
            raise PAdicVerificationError("declared tame element does not generate G_0/G_1")
        tame_order = self.filtration.tame_order
        q = self.quotient.residue_cardinality
        if tame_order == 1 and generator != group.identity:
            raise PAdicVerificationError(
                "trivial tame inertia must use identity as its compatibility generator"
            )
        if operator.convention is FrobeniusConvention.ARITHMETIC:
            exponent = q
        else:
            if gcd(q, tame_order) != 1:
                raise PAdicVerificationError(
                    "geometric Frobenius exponent is not invertible tamely"
                )
            exponent = 0 if tame_order == 1 else pow(q, -1, tame_order)
        target = _power(group, generator, exponent)
        left = operator.matrix @ _sigma_matrix(operator.sigma, self.matrix(generator))
        right = self.matrix(target) @ operator.matrix
        if left != right:
            raise PAdicVerificationError(
                "Frobenius-inertia relation fails for the declared convention and tame generator"
            )

    def verify(self) -> bool:
        from .matrices import PAdicMatrix
        from .modules import PAdicModule

        if not isinstance(self.module, PAdicModule):
            raise TypeError("inertia representation module must be a PAdicModule")
        self.quotient.verify()
        self.filtration.verify()
        if not _same_quotient(self.quotient, self.filtration.quotient):
            raise PAdicVerificationError("inertia representation filtration is foreign")
        rank = _module_rank(self.module)
        base = _module_base(self.module)
        _check_inertia_action_work(self.module, self.quotient)
        if len(self.action_matrices) != self.quotient.order:
            raise PAdicVerificationError("inertia matrix table is incomplete")
        for matrix in self.action_matrices:
            if not isinstance(matrix, PAdicMatrix):
                raise TypeError("inertia action entries must be PAdicMatrix objects")
            if _matrix_shape(matrix) != (rank, rank) or _matrix_base(matrix) != base:
                raise PAdicVerificationError("inertia action matrix has a foreign shape or base")
        group = self.quotient.group
        lookup = _group_lookup(group)
        identity = _matrix_identity(base, rank)
        if self.action_matrices[lookup[group.identity]] != identity:
            raise PAdicVerificationError("inertia identity does not act as the identity matrix")
        for left in group.elements:
            for right in group.elements:
                product = group.multiply(left, right)
                if self.action_matrices[lookup[product]] != (
                    self.action_matrices[lookup[left]] @ self.action_matrices[lookup[right]]
                ):
                    raise PAdicVerificationError("inertia action table is not a homomorphism")
        if self.frobenius_operator is not None:
            self.frobenius_operator.verify()
        self._verify_frobenius_relation()
        return True

    def to_canonical_data(self) -> CanonicalJSON:
        base = _module_base(self.module)
        relation: dict[str, Any] | None = None
        if self.frobenius_operator is not None and self.tame_generator_index is not None:
            tame_order = self.filtration.tame_order
            q = self.quotient.residue_cardinality
            exponent = (
                q
                if self.frobenius_operator.convention is FrobeniusConvention.ARITHMETIC
                else (0 if tame_order == 1 else pow(q, -1, tame_order))
            )
            relation = {
                "convention": self.frobenius_operator.convention.value,
                "exponent_mod_tame_order": exponent % max(1, tame_order),
                "frobenius_operator_id": self.frobenius_operator.operator_id,
                "formula": "A sigma(rho(tau)) = rho(tau^exponent) A",
                "residue_cardinality": q,
                "tame_generator_index": self.tame_generator_index,
                "tame_quotient_order": tame_order,
            }
        return cast(
            CanonicalJSON,
            {
                "action_convention": "column action: rho(gh)=rho(g)rho(h)",
                "action_matrices": [matrix.to_schema_document() for matrix in self.action_matrices],
                "coefficient_field": base.field.to_schema_document(),
                "filtration": self.filtration.to_schema_document(),
                "filtration_id": self.filtration.filtration_id,
                "frobenius_operator": (
                    None
                    if self.frobenius_operator is None
                    else self.frobenius_operator.to_schema_document()
                ),
                "frobenius_relation": relation,
                "module": self.module.to_schema_document(),
                "module_id": _object_id(self.module, "module_id"),
                "precision_ring": base.to_schema_document(),
                "quotient": self.quotient.to_schema_document(),
                "quotient_id": self.quotient.quotient_id,
                "scope": (
                    "exact representation of a declared finite group presentation; "
                    "no arithmetic-origin or continuous-inertia claim"
                ),
                "type": "arbogast.padic.inertia_representation",
            },
        )


def _decode_quotient_document(value: Mapping[str, object]) -> FiniteInertiaQuotient:
    raw = _document_body(
        value,
        schema=FiniteInertiaQuotient.schema_version,
        type_tag="arbogast.padic.finite_inertia_quotient",
        keys={
            "arithmetic_origin_claimed",
            "group",
            "place_id",
            "residue_cardinality",
            "residue_characteristic",
            "residue_degree",
            "scope",
            "source_id",
            "type",
        },
        name="finite inertia quotient",
    )
    if raw["arithmetic_origin_claimed"] is not False:
        raise PAdicVerificationError(
            "finite inertia presentation cannot claim an arithmetic origin"
        )
    proof = _raw_object(raw["group"], "finite inertia group proof")
    expected_group_fields = {
        "composition_convention",
        "degree",
        "elements",
        "fingerprint",
        "generators",
        "identity_index",
        "inverse_indices",
        "multiplication_table",
        "order",
        "type",
    }
    if set(proof) != expected_group_fields:
        raise PAdicVerificationError("finite inertia group proof fields were altered")
    degree = strict_int(proof["degree"], "finite inertia permutation degree", minimum=0)
    if degree > MAX_DIMENSION:
        raise PAdicResourceError("finite inertia permutation degree exceeds the portable bound")
    declared_order = strict_int(proof["order"], "finite inertia group order", minimum=1)
    if declared_order > MAX_GROUP_ORDER:
        raise PAdicResourceError("finite inertia declared order exceeds the portable bound")
    raw_generators = _raw_list(proof["generators"], "finite inertia generators")
    if len(raw_generators) > MAX_GROUP_ORDER:
        raise PAdicResourceError("finite inertia generator count exceeds the portable bound")
    raw_elements = _raw_list(proof["elements"], "finite inertia elements")
    raw_inverses = _raw_list(proof["inverse_indices"], "finite inertia inverses")
    raw_table = _raw_list(proof["multiplication_table"], "finite inertia table")
    if (
        len(raw_elements) != declared_order
        or len(raw_inverses) != declared_order
        or len(raw_table) != declared_order
        or any(
            len(_raw_list(row, f"finite inertia table row[{index}]")) != declared_order
            for index, row in enumerate(raw_table)
        )
    ):
        raise PAdicVerificationError("finite inertia group proof is not a complete square table")
    generator_rows = tuple(
        _raw_list(item, f"finite inertia generator[{index}]")
        for index, item in enumerate(raw_generators)
    )
    if any(len(row) != degree for row in generator_rows):
        raise PAdicVerificationError("finite inertia generator degree was altered")
    generators = tuple(
        Permutation(
            tuple(strict_int(image, "finite inertia generator image", minimum=0) for image in row)
        )
        for row in generator_rows
    )
    if any(generator.degree != degree for generator in generators):
        raise PAdicVerificationError("finite inertia generator degree was altered")
    group = _bounded_group_from_generators(generators, degree=degree)
    if not strict_canonical_equal(proof, _group_proof(group)):
        raise PAdicVerificationError("finite inertia group table failed exhaustive replay")
    result = FiniteInertiaQuotient(
        cast(str, raw["source_id"]),
        cast(str, raw["place_id"]),
        strict_int(raw["residue_characteristic"], "residue characteristic", minimum=2),
        strict_int(raw["residue_degree"], "residue degree", minimum=1),
        group,
    )
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("finite inertia quotient is not strict canonical transport")
    return result


def _decode_filtration_document(
    quotient: FiniteInertiaQuotient,
    value: object,
) -> InertiaFiltration:
    raw = _document_body(
        _raw_object(value, "inertia filtration"),
        schema=InertiaFiltration.schema_version,
        type_tag="arbogast.padic.inertia_filtration",
        keys={
            "arithmetic_lower_numbering_claimed",
            "level_element_indices",
            "numbering",
            "quotient_id",
            "scope",
            "tame_quotient_order",
            "type",
            "wild_residue_characteristic",
        },
        name="inertia filtration",
    )
    if raw["arithmetic_lower_numbering_claimed"] is not False:
        raise PAdicVerificationError(
            "declared inertia series cannot claim arithmetic lower numbering"
        )
    raw_levels = _raw_list(raw["level_element_indices"], "inertia filtration levels")
    if len(raw_levels) > MAX_GROUP_ORDER:
        raise PAdicResourceError("inertia filtration exceeds the portable level bound")
    levels: list[tuple[Permutation, ...]] = []
    for level_number, item in enumerate(raw_levels):
        raw_indices = _raw_list(item, f"G_{level_number} element indices")
        if len(raw_indices) > quotient.order:
            raise PAdicResourceError(f"G_{level_number} exceeds the finite quotient order bound")
        indices = tuple(
            strict_int(index, f"G_{level_number} element index", minimum=0) for index in raw_indices
        )
        if any(index >= quotient.order for index in indices):
            raise PAdicVerificationError("inertia filtration element index is out of range")
        levels.append(tuple(quotient.group.elements[index] for index in indices))
    result = InertiaFiltration(quotient, levels)
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("inertia filtration is not strict canonical transport")
    return result


def _decode_representation_document_exact(
    value: Mapping[str, object],
) -> InertiaRepresentation:
    from .fields import PAdicField, PAdicPrecisionRing

    raw = _document_body(
        value,
        schema=InertiaRepresentation.schema_version,
        type_tag="arbogast.padic.inertia_representation",
        keys={
            "action_convention",
            "action_matrices",
            "coefficient_field",
            "filtration",
            "filtration_id",
            "frobenius_operator",
            "frobenius_relation",
            "module",
            "module_id",
            "precision_ring",
            "quotient",
            "quotient_id",
            "scope",
            "type",
        },
        name="inertia representation",
    )
    field = PAdicField.from_dict(_raw_object(raw["coefficient_field"], "inertia coefficient field"))
    ring = PAdicPrecisionRing.from_dict(
        field,
        _raw_object(raw["precision_ring"], "inertia precision ring"),
    )
    module = _decode_module_document(ring, raw["module"])
    quotient = _decode_quotient_document(_raw_object(raw["quotient"], "finite inertia quotient"))
    filtration = _decode_filtration_document(quotient, raw["filtration"])
    raw_matrices = _raw_list(raw["action_matrices"], "inertia action matrices")
    if len(raw_matrices) != quotient.order:
        raise PAdicVerificationError(
            "inertia action matrix list does not match the finite quotient order"
        )
    matrices = tuple(
        _decode_matrix_document(ring, item, f"inertia action matrix[{index}]")
        for index, item in enumerate(raw_matrices)
    )
    frobenius_raw = raw["frobenius_operator"]
    relation_raw = raw["frobenius_relation"]
    if frobenius_raw is None:
        if relation_raw is not None:
            raise PAdicVerificationError("inertia relation omits its Frobenius operator")
        operator = None
        generator = None
    else:
        operator = _decode_operator_document(
            _raw_object(frobenius_raw, "inertia Frobenius operator")
        )
        relation = _raw_object(relation_raw, "Frobenius-inertia relation")
        expected_relation_fields = {
            "convention",
            "exponent_mod_tame_order",
            "formula",
            "frobenius_operator_id",
            "residue_cardinality",
            "tame_generator_index",
            "tame_quotient_order",
        }
        if set(relation) != expected_relation_fields:
            raise PAdicVerificationError("Frobenius-inertia relation fields were altered")
        generator_index = strict_int(
            relation["tame_generator_index"],
            "tame generator index",
            minimum=0,
        )
        if generator_index >= quotient.order:
            raise PAdicVerificationError("tame generator index is out of range")
        generator = quotient.group.elements[generator_index]
    result = InertiaRepresentation(
        module,
        quotient,
        filtration,
        matrices,
        frobenius_operator=operator,
        tame_generator=generator,
    )
    if not strict_canonical_equal(raw, result.to_schema_document()):
        raise PAdicVerificationError("inertia representation is not strict canonical transport")
    return result


def _decode_representation_document(value: Mapping[str, object]) -> InertiaRepresentation:
    try:
        return _decode_representation_document_exact(value)
    except PAdicVerificationError:
        raise
    except (TypeError, ValueError) as error:
        raise PAdicVerificationError(
            "inertia representation witness failed independent replay"
        ) from error


def inertia_action(
    source: object,
    p: int | None = None,
    *,
    datum: object | None = None,
) -> PAdicResult[InertiaRepresentation]:
    """Replay a declared finite action without inferring arithmetic inertia."""

    if datum is None:
        from .results import unknown_result

        requested: dict[str, object] = {"source_id": _object_id(source, "source_id")}
        if p is not None:
            requested["residue_characteristic"] = strict_int(
                p, "requested residue characteristic", minimum=2
            )
        return unknown_result(
            "padic.inertia_action",
            "missing-finite-inertia-datum",
            "a complete declared finite presentation, filtration, and action table "
            "were not supplied",
            requested=requested,
            family="finite",
        )
    if isinstance(datum, InertiaRepresentation):
        result = datum
    else:
        module = getattr(datum, "module", getattr(source, "module", source))
        quotient = getattr(datum, "quotient", None)
        filtration = getattr(datum, "filtration", None)
        action = getattr(datum, "action", getattr(datum, "action_matrices", None))
        if quotient is None or filtration is None or action is None:
            raise PAdicValidationError(
                "inertia datum must expose quotient, filtration, and a complete action table"
            )
        result = InertiaRepresentation(
            cast("PAdicModule", module),
            quotient,
            filtration,
            action,
            frobenius_operator=getattr(datum, "frobenius_operator", None),
            tame_generator=getattr(datum, "tame_generator", None),
        )
    source_id = _object_id(source, "source_id")
    if result.quotient.source_id != source_id:
        raise PAdicValidationError("finite inertia datum is bound to another source")
    if p is not None:
        prime = strict_int(p, "requested residue characteristic", minimum=2)
        if result.quotient.residue_characteristic != prime:
            raise PAdicValidationError("finite inertia quotient has another residue characteristic")
    result.verify()
    from .results import certified_result

    return certified_result(result, "inertia-representation")


def _register_payload_verifier() -> None:
    from .certificate import padic_payload_verifier, replay_schema_payload

    @padic_payload_verifier("inertia-representation")
    def replay_inertia(
        payload: Mapping[str, object],
        evidence: tuple[VerificationCertificate, ...],
    ) -> PAdicPayloadReplay:
        return replay_schema_payload(
            payload,
            evidence,
            decoder=_decode_representation_document,
            checks=(
                "complete declared finite group table and filtration identities replayed",
                "all inertia matrices and representation products recomputed",
                "declared arithmetic or geometric Frobenius relation replayed",
                "arithmetic inertia origin, lower numbering, continuous inertia, "
                "and Nielsen claims excluded",
            ),
        )


_register_payload_verifier()


__all__ = [
    "FiniteInertiaQuotient",
    "InertiaFiltration",
    "InertiaRepresentation",
    "inertia_action",
]
