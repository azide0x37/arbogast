"""Portable receipts for induced maps on finite-group cohomology."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, cast

from arbogast.cert import (
    CertificateVerificationError as CentralCertificateVerificationError,
)
from arbogast.cert import (
    FrozenMap,
    VerificationCertificate,
    default_verifiers,
    freeze_mapping,
)
from arbogast.cert import (
    VerificationReport as CentralVerificationReport,
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
from arbogast.core import canonical_json, pretty_canonical_json

from ._linear import contains, matrix_vector
from .certificate import (
    CertificateVerificationError,
    CohomologyCertificate,
    VerificationReport,
)
from .complex import _bar_differential_from_snapshot

MapKind = Literal["restriction", "inflation", "corestriction"]


def _rows(value: object, name: str) -> tuple[tuple[int, ...], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence of rows")
    result: list[tuple[int, ...]] = []
    for row in value:
        if isinstance(row, (str, bytes, bytearray)) or not isinstance(row, Sequence):
            raise ValueError(f"{name} rows must be sequences")
        if any(isinstance(entry, bool) or not isinstance(entry, int) for entry in row):
            raise ValueError(f"{name} entries must be integers")
        result.append(tuple(cast("Sequence[int]", row)))
    return tuple(result)


def _integers(value: object, name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    if any(isinstance(entry, bool) or not isinstance(entry, int) for entry in value):
        raise ValueError(f"{name} entries must be integers")
    return tuple(cast("Sequence[int]", value))


def _snapshot(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    expected = {"element_ids", "identity_index", "multiplication_table"}
    if set(value) != expected:
        raise ValueError(f"{name} fields must be exactly {sorted(expected)}")
    element_ids = value["element_ids"]
    if isinstance(element_ids, (str, bytes, bytearray)) or not isinstance(element_ids, Sequence):
        raise ValueError(f"{name}.element_ids must be a sequence")
    if any(not isinstance(identifier, str) for identifier in element_ids):
        raise ValueError(f"{name}.element_ids entries must be strings")
    identity_index = value["identity_index"]
    if isinstance(identity_index, bool) or not isinstance(identity_index, int):
        raise ValueError(f"{name}.identity_index must be an integer")
    return {
        "element_ids": list(cast("Sequence[str]", element_ids)),
        "identity_index": identity_index,
        "multiplication_table": [list(row) for row in _rows(value["multiplication_table"], name)],
    }


def _cohom_snapshot(certificate: CohomologyCertificate) -> dict[str, object]:
    return {
        "element_ids": list(certificate.group_element_ids),
        "identity_index": certificate.identity_index,
        "multiplication_table": [list(row) for row in certificate.multiplication_table],
    }


def _normalized_tuples(order: int, identity: int, degree: int) -> tuple[tuple[int, ...], ...]:
    nonidentity = tuple(index for index in range(order) if index != identity)
    if degree == 0:
        return ((),)
    tuples: tuple[tuple[int, ...], ...] = ((),)
    for _ in range(degree):
        tuples = tuple((*prefix, entry) for prefix in tuples for entry in nonidentity)
    return tuples


def _cochain_value(
    values: Sequence[int],
    arguments: Sequence[int],
    *,
    order: int,
    identity: int,
    module_dimension: int,
) -> tuple[int, ...]:
    if identity in arguments:
        return (0,) * module_dimension
    basis = _normalized_tuples(order, identity, len(arguments))
    block = basis.index(tuple(arguments)) * module_dimension
    return tuple(values[block : block + module_dimension])


def _matrix_action(
    matrix: Sequence[Sequence[int]], vector: Sequence[int], prime: int
) -> tuple[int, ...]:
    return tuple(
        sum(entry * value for entry, value in zip(row, vector, strict=True)) % prime
        for row in matrix
    )


def _add(left: Sequence[int], right: Sequence[int], prime: int) -> tuple[int, ...]:
    return tuple((a + b) % prime for a, b in zip(left, right, strict=True))


def _validate_group_map(
    domain: Mapping[str, object], codomain: Mapping[str, object], images: Sequence[int]
) -> None:
    domain_table = _rows(domain["multiplication_table"], "domain multiplication_table")
    codomain_table = _rows(codomain["multiplication_table"], "codomain multiplication_table")
    domain_order = len(domain_table)
    codomain_order = len(codomain_table)
    if len(images) != domain_order or any(not 0 <= image < codomain_order for image in images):
        raise CertificateVerificationError("group-map image indices have the wrong shape")
    domain_identity = cast("int", domain["identity_index"])
    codomain_identity = cast("int", codomain["identity_index"])
    if images[domain_identity] != codomain_identity:
        raise CertificateVerificationError("group map does not preserve the identity")
    for left in range(domain_order):
        for right in range(domain_order):
            if codomain_table[images[left]][images[right]] != images[domain_table[left][right]]:
                raise CertificateVerificationError("group map does not preserve multiplication")


def _contravariant_transport(
    values: Sequence[int],
    source: CohomologyCertificate,
    target: CohomologyCertificate,
    images: Sequence[int],
    *,
    degree: int | None = None,
) -> tuple[int, ...]:
    selected_degree = source.degree if degree is None else degree
    output: list[int] = []
    for arguments in _normalized_tuples(
        len(target.multiplication_table), target.identity_index, selected_degree
    ):
        output.extend(
            _cochain_value(
                values,
                tuple(images[index] for index in arguments),
                order=len(source.multiplication_table),
                identity=source.identity_index,
                module_dimension=source.module_dimension,
            )
        )
    return tuple(output)


def _inverse(table: Sequence[Sequence[int]], identity: int, element: int) -> int:
    return next(
        candidate
        for candidate in range(len(table))
        if table[element][candidate] == identity and table[candidate][element] == identity
    )


def _validate_left_transversal(
    source: CohomologyCertificate,
    target: CohomologyCertificate,
    images: Sequence[int],
    transversal: Sequence[int],
) -> None:
    target_table = target.multiplication_table
    cosets = tuple(
        frozenset(target_table[representative][image] for image in images)
        for representative in transversal
    )
    if len(set(transversal)) != len(transversal) or len(set(cosets)) != len(cosets):
        raise CertificateVerificationError("corestriction transversal has duplicates")
    covered = frozenset().union(*cosets) if cosets else frozenset()
    if covered != frozenset(range(len(target_table))):
        raise CertificateVerificationError("corestriction transversal is not complete")
    if len(transversal) * len(source.multiplication_table) != len(target_table):
        raise CertificateVerificationError("corestriction transversal has the wrong index")


def _decompose_left(
    element: int,
    source: CohomologyCertificate,
    target: CohomologyCertificate,
    images: Sequence[int],
    transversal: Sequence[int],
) -> tuple[int, int]:
    table = target.multiplication_table
    matches = tuple(
        (representative, subgroup_index)
        for representative in transversal
        for subgroup_index, image in enumerate(images)
        if table[representative][image] == element
    )
    if len(matches) != 1:
        raise CertificateVerificationError("left-coset decomposition is not unique")
    return matches[0]


def _corestriction_transport(
    values: Sequence[int],
    source: CohomologyCertificate,
    target: CohomologyCertificate,
    images: Sequence[int],
    transversal: Sequence[int],
    *,
    degree: int | None = None,
) -> tuple[int, ...]:
    selected_degree = source.degree if degree is None else degree
    prime = source.prime
    dimension = source.module_dimension
    output: list[int] = []
    for arguments in _normalized_tuples(
        len(target.multiplication_table), target.identity_index, selected_degree
    ):
        total = (0,) * dimension
        for initial in transversal:
            current = initial
            subgroup_arguments = [source.identity_index] * selected_degree
            leading = initial
            for position in range(selected_degree - 1, -1, -1):
                product = target.multiplication_table[arguments[position]][current]
                leading, subgroup_index = _decompose_left(
                    product, source, target, images, transversal
                )
                subgroup_arguments[position] = subgroup_index
                current = leading
            value = _cochain_value(
                values,
                subgroup_arguments,
                order=len(source.multiplication_table),
                identity=source.identity_index,
                module_dimension=dimension,
            )
            total = _add(
                total, _matrix_action(target.action_matrices[leading], value, prime), prime
            )
        output.extend(total)
    return tuple(output)


def _canonical_transversal(target: CohomologyCertificate, images: Sequence[int]) -> tuple[int, ...]:
    covered: set[int] = set()
    representatives: list[int] = []
    for candidate in range(len(target.multiplication_table)):
        if candidate in covered:
            continue
        representatives.append(candidate)
        covered.update(target.multiplication_table[candidate][image] for image in images)
    return tuple(representatives)


def _transport(
    certificate: CohomologyMapCertificate,
    values: Sequence[int],
    *,
    degree: int,
    transversal: Sequence[int] | None = None,
) -> tuple[int, ...]:
    if certificate.kind in ("restriction", "inflation"):
        return _contravariant_transport(
            values,
            certificate.source,
            certificate.target,
            certificate.image_indices,
            degree=degree,
        )
    return _corestriction_transport(
        values,
        certificate.source,
        certificate.target,
        certificate.image_indices,
        certificate.transversal if transversal is None else transversal,
        degree=degree,
    )


def _expected_matrix(certificate: CohomologyMapCertificate) -> tuple[tuple[int, ...], ...]:
    source = certificate.source
    target = certificate.target
    columns: list[tuple[int, ...]] = []
    for representative in source.representative_basis:
        if certificate.kind in ("restriction", "inflation"):
            transported = _contravariant_transport(
                representative, source, target, certificate.image_indices
            )
        else:
            transported = _corestriction_transport(
                representative,
                source,
                target,
                certificate.image_indices,
                certificate.transversal,
            )
        columns.append(matrix_vector(target.quotient_projection, transported, target.prime))
    return tuple(tuple(column[row] for column in columns) for row in range(target.dimension))


@dataclass(frozen=True, slots=True)
class CohomologyMapCertificate:
    """Self-contained finite witness for an induced map through degree two."""

    schema_version: str
    kind: MapKind
    degree: int
    source: CohomologyCertificate
    target: CohomologyCertificate
    source_dimension: int
    target_dimension: int
    map_domain: FrozenMap
    map_codomain: FrozenMap
    image_indices: tuple[int, ...]
    transversal: tuple[int, ...]
    matrix: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "map_domain", freeze_mapping(self.map_domain))
        object.__setattr__(self, "map_codomain", freeze_mapping(self.map_codomain))

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "degree": self.degree,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "source_dimension": self.source_dimension,
            "target_dimension": self.target_dimension,
            "map_domain": self.map_domain.to_dict(),
            "map_codomain": self.map_codomain.to_dict(),
            "image_indices": list(self.image_indices),
            "transversal": list(self.transversal),
            "matrix": [list(row) for row in self.matrix],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return (
            canonical_json(self.to_dict())
            if indent is None
            else pretty_canonical_json(self.to_dict(), indent=indent)
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CohomologyMapCertificate:
        expected = {
            "schema_version",
            "kind",
            "degree",
            "source",
            "target",
            "source_dimension",
            "target_dimension",
            "map_domain",
            "map_codomain",
            "image_indices",
            "transversal",
            "matrix",
        }
        if set(value) != expected:
            raise ValueError("cohomology-map certificate fields mismatch")
        schema = value["schema_version"]
        kind = value["kind"]
        degree = value["degree"]
        if not isinstance(schema, str):
            raise ValueError("schema_version must be a string")
        if kind not in ("restriction", "inflation", "corestriction"):
            raise ValueError("unsupported cohomology-map kind")
        if isinstance(degree, bool) or not isinstance(degree, int):
            raise ValueError("degree must be an integer")
        source = value["source"]
        target = value["target"]
        if not isinstance(source, Mapping) or not isinstance(target, Mapping):
            raise ValueError("source and target certificates must be objects")
        source_dimension = value["source_dimension"]
        target_dimension = value["target_dimension"]
        if (
            isinstance(source_dimension, bool)
            or not isinstance(source_dimension, int)
            or isinstance(target_dimension, bool)
            or not isinstance(target_dimension, int)
        ):
            raise ValueError("map dimensions must be integers")
        return cls(
            schema,
            kind,
            degree,
            CohomologyCertificate.from_dict(source),
            CohomologyCertificate.from_dict(target),
            source_dimension,
            target_dimension,
            freeze_mapping(_snapshot(value["map_domain"], "map_domain")),
            freeze_mapping(_snapshot(value["map_codomain"], "map_codomain")),
            _integers(value["image_indices"], "image_indices"),
            _integers(value["transversal"], "transversal"),
            _rows(value["matrix"], "matrix"),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> CohomologyMapCertificate:
        decoded = json.loads(value)
        if not isinstance(decoded, Mapping):
            raise ValueError("cohomology-map certificate JSON must contain an object")
        return cls.from_dict(decoded)

    def verify(self, *, raise_on_error: bool = True) -> VerificationReport:
        checks: list[str] = []
        try:
            self._verify(checks)
        except (TypeError, ValueError, IndexError, CertificateVerificationError) as error:
            if raise_on_error:
                raise CertificateVerificationError(str(error)) from error
            return VerificationReport(False, tuple(checks), str(error))
        return VerificationReport(True, tuple(checks))

    def _verify(self, checks: list[str]) -> None:
        if self.schema_version != "arbogast.cohomology-map.v1":
            raise CertificateVerificationError("unsupported cohomology-map certificate schema")
        if self.degree not in (0, 1, 2):
            raise CertificateVerificationError("induced maps are certified only in degrees 0-2")
        if self.source.degree != self.degree or self.target.degree != self.degree:
            raise CertificateVerificationError("map degree is not bound to its endpoint receipts")
        self.source.verify()
        self.target.verify()
        checks.append("endpoint-cohomology-replayed")
        if self.source.prime != self.target.prime:
            raise CertificateVerificationError("map endpoints use different prime fields")
        if self.source.module_dimension != self.target.module_dimension:
            raise CertificateVerificationError("map endpoints use different module dimensions")
        if (
            self.source_dimension != self.source.dimension
            or self.target_dimension != self.target.dimension
        ):
            raise CertificateVerificationError("declared map dimensions do not match endpoints")
        if self.kind in ("restriction", "inflation"):
            expected_domain = _cohom_snapshot(self.target)
            expected_codomain = _cohom_snapshot(self.source)
            if self.transversal:
                raise CertificateVerificationError("only corestriction carries a transversal")
        else:
            expected_domain = _cohom_snapshot(self.source)
            expected_codomain = _cohom_snapshot(self.target)
        if (
            self.map_domain.to_dict() != expected_domain
            or self.map_codomain.to_dict() != expected_codomain
        ):
            raise CertificateVerificationError("group-map snapshots do not match map endpoints")
        _validate_group_map(self.map_domain, self.map_codomain, self.image_indices)
        if self.kind == "restriction" and len(set(self.image_indices)) != len(self.image_indices):
            raise CertificateVerificationError("restriction map is not induced by an injection")
        if self.kind == "inflation" and set(self.image_indices) != set(
            range(len(self.source.multiplication_table))
        ):
            raise CertificateVerificationError("inflation map is not induced by a surjection")
        if self.kind == "corestriction":
            if len(set(self.image_indices)) != len(self.image_indices):
                raise CertificateVerificationError("corestriction inclusion is not injective")
            _validate_left_transversal(
                self.source, self.target, self.image_indices, self.transversal
            )
        checks.extend(
            (
                "finite-group-map",
                "complete-transversal" if self.kind == "corestriction" else "cochain-pullback",
            )
        )
        if self.kind in ("restriction", "inflation"):
            for target_index, source_index in enumerate(self.image_indices):
                if (
                    self.target.action_matrices[target_index]
                    != self.source.action_matrices[source_index]
                ):
                    raise CertificateVerificationError("coefficient actions are not compatible")
        else:
            for source_index, target_index in enumerate(self.image_indices):
                if (
                    self.source.action_matrices[source_index]
                    != self.target.action_matrices[target_index]
                ):
                    raise CertificateVerificationError("coefficient actions are not compatible")
        source_differential = _bar_differential_from_snapshot(
            self.source.prime,
            self.source.multiplication_table,
            self.source.identity_index,
            self.source.action_matrices,
            self.source.module_dimension,
            self.degree,
        )
        target_differential = _bar_differential_from_snapshot(
            self.target.prime,
            self.target.multiplication_table,
            self.target.identity_index,
            self.target.action_matrices,
            self.target.module_dimension,
            self.degree,
        )
        for column in range(source_differential.ncols):
            standard = tuple(
                1 if index == column else 0 for index in range(source_differential.ncols)
            )
            left = target_differential.apply(_transport(self, standard, degree=self.degree))
            right = _transport(
                self,
                source_differential.column(column),
                degree=self.degree + 1,
            )
            if left != right:
                raise CertificateVerificationError(
                    "cochain formula does not commute with the bar differential"
                )
        checks.append("cochain-map")
        # Replay both cocycle preservation and representative independence instead of merely
        # projecting arbitrary vectors into the quotient coordinate matrix.
        for vector in self.source.representative_basis:
            transported = (
                _contravariant_transport(vector, self.source, self.target, self.image_indices)
                if self.kind in ("restriction", "inflation")
                else _corestriction_transport(
                    vector,
                    self.source,
                    self.target,
                    self.image_indices,
                    self.transversal,
                )
            )
            if not contains(self.target.cocycle_basis, transported, self.source.prime):
                raise CertificateVerificationError("map does not carry cocycles to cocycles")
        for vector in self.source.coboundary_basis:
            transported = (
                _contravariant_transport(vector, self.source, self.target, self.image_indices)
                if self.kind in ("restriction", "inflation")
                else _corestriction_transport(
                    vector,
                    self.source,
                    self.target,
                    self.image_indices,
                    self.transversal,
                )
            )
            if not contains(self.target.coboundary_basis, transported, self.source.prime):
                raise CertificateVerificationError("map does not carry boundaries to boundaries")
        expected_shape = (self.target_dimension, self.source_dimension)
        if len(self.matrix) != expected_shape[0] or any(
            len(row) != expected_shape[1] for row in self.matrix
        ):
            raise CertificateVerificationError("induced matrix has the wrong shape")
        if any(
            isinstance(entry, bool) or not 0 <= entry < self.source.prime
            for row in self.matrix
            for entry in row
        ):
            raise CertificateVerificationError("induced matrix has noncanonical residues")
        if self.matrix != _expected_matrix(self):
            raise CertificateVerificationError("induced matrix does not replay from cochains")
        if self.kind == "corestriction":
            canonical = _canonical_transversal(self.target, self.image_indices)
            canonical_certificate = replace(self, transversal=canonical)
            if self.matrix != _expected_matrix(canonical_certificate):
                raise CertificateVerificationError(
                    "corestriction class map depends on the chosen transversal"
                )
            checks.append("transversal-class-independence")
            restriction_certificate = replace(
                self,
                kind="restriction",
                source=self.target,
                target=self.source,
                source_dimension=self.target_dimension,
                target_dimension=self.source_dimension,
                transversal=(),
                matrix=tuple(() for _ in range(self.source_dimension)),
            )
            restriction_matrix = _expected_matrix(restriction_certificate)
            group_index = len(self.target.multiplication_table) // len(
                self.source.multiplication_table
            )
            composite = tuple(
                tuple(
                    sum(
                        self.matrix[row][middle] * restriction_matrix[middle][column]
                        for middle in range(self.source_dimension)
                    )
                    % self.source.prime
                    for column in range(self.target_dimension)
                )
                for row in range(self.target_dimension)
            )
            expected_transfer = tuple(
                tuple(
                    group_index % self.source.prime if row == column else 0
                    for column in range(self.target_dimension)
                )
                for row in range(self.target_dimension)
            )
            if composite != expected_transfer:
                raise CertificateVerificationError(
                    "corestriction after restriction is not multiplication by the index"
                )
            checks.append("transfer-index-identity")
        checks.extend(("representative-images", "class-map-independent"))


VERIFIER_NAME = "cohom.induced_map.v1"
VERIFICATION_CHECKS = (
    "endpoint-cohomology-replayed",
    "finite-group-map",
    "cochain-formula",
    "class-map-independent",
)
VERIFICATION_GUARANTEES = (
    "The induced coordinate matrix is recomputed from representative cocycles.",
    "Finite group maps, coefficient actions, and any transfer transversal are replayed.",
)


def _statement(certificate: CohomologyMapCertificate) -> FormalStatement:
    return FormalStatement.create(
        text=(
            f"The certified {certificate.kind} map on H^{certificate.degree} has matrix "
            f"sha256:{hashlib.sha256(canonical_json(certificate.matrix).encode()).hexdigest()}."
        ),
        parameters={
            "kind": certificate.kind,
            "cohomology_degree": certificate.degree,
            "source_dimension": certificate.source.dimension,
            "target_dimension": certificate.target.dimension,
            "map_certificate_hash": f"sha256:{certificate.content_hash}",
        },
    )


def _claim_id(certificate: CohomologyMapCertificate) -> str:
    return f"cohom.{certificate.kind}.{certificate.content_hash}"


def _verify_central(certificate: VerificationCertificate) -> CentralVerificationReport:
    payload = certificate.witness.to_dict()
    if set(payload) != {"cohomology_map_certificate"}:
        raise CentralCertificateVerificationError("map witness has unexpected fields")
    raw = payload["cohomology_map_certificate"]
    if not isinstance(raw, dict):
        raise CentralCertificateVerificationError("map witness must be an object")
    domain = CohomologyMapCertificate.from_dict(raw)
    domain.verify()
    statement = _statement(domain)
    claim_id = _claim_id(domain)
    if certificate.subject != f"cohomology-map:sha256:{domain.content_hash}":
        raise CentralCertificateVerificationError("map subject is not bound to its payload")
    if certificate.verifier != VERIFIER_NAME or certificate.claim_id != claim_id:
        raise CentralCertificateVerificationError("map verifier or claim ID was altered")
    if certificate.statement_hash != statement.statement_hash:
        raise CentralCertificateVerificationError("map statement hash was altered")
    boundary = claim_boundary_hash(
        claim_id, statement, kind=ClaimKind.COMPUTED, status=EpistemicStatus.EXACT
    )
    if certificate.claim_boundary_hash != boundary:
        raise CentralCertificateVerificationError("map claim boundary was altered")
    if (
        certificate.checks != VERIFICATION_CHECKS
        or certificate.guarantees != VERIFICATION_GUARANTEES
    ):
        raise CentralCertificateVerificationError("map verification manifest was altered")
    if certificate.claim_dependencies or certificate.dependencies:
        raise CentralCertificateVerificationError("self-contained map receipt has dependencies")
    return CentralVerificationReport(
        valid=True,
        verifier=VERIFIER_NAME,
        certificate_id=certificate.certificate_id,
        checks=VERIFICATION_CHECKS,
        details=freeze_mapping({"map_certificate": f"sha256:{domain.content_hash}"}),
    )


def _register() -> None:
    if VERIFIER_NAME not in default_verifiers.names():
        default_verifiers.register(VERIFIER_NAME, VerificationCertificate, _verify_central)


_register()


def verification_certificate(certificate: CohomologyMapCertificate) -> VerificationCertificate:
    certificate.verify()
    statement = _statement(certificate)
    claim_id = _claim_id(certificate)
    return VerificationCertificate.create(
        subject=f"cohomology-map:sha256:{certificate.content_hash}",
        verifier=VERIFIER_NAME,
        claim_id=claim_id,
        statement_hash=statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            claim_id, statement, kind=ClaimKind.COMPUTED, status=EpistemicStatus.EXACT
        ),
        witness={"cohomology_map_certificate": certificate.to_dict()},
        checks=VERIFICATION_CHECKS,
        guarantees=VERIFICATION_GUARANTEES,
    )


def claim(certificate: CohomologyMapCertificate) -> Claim:
    semantic = verification_certificate(certificate)
    return Claim(
        id=_claim_id(certificate),
        statement=_statement(certificate),
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation(
            f"cohom.{certificate.kind}_map",
            method="Finite normalized-cochain transport and quotient projection",
            inputs=(
                f"sha256:{certificate.source.content_hash}",
                f"sha256:{certificate.target.content_hash}",
            ),
            artifact=semantic.certificate_id,
            parameters={"degree": certificate.degree},
        ),
        certificate=semantic,
        metadata={"domain_certificate_hash": f"sha256:{certificate.content_hash}"},
    )


def claim_graph(certificate: CohomologyMapCertificate) -> ClaimGraph:
    return ClaimGraph((claim(certificate),))


__all__ = ["VERIFIER_NAME", "CohomologyMapCertificate", "MapKind"]
