"""A deterministic claim graph whose v1 ``why`` edges remain mathematical."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, cast

from arbogast.cert.base import Certificate
from arbogast.cert.canonical import canonicalize, content_address
from arbogast.cert.registry import VerifierRegistry, default_verifiers

from .claim import (
    Claim,
    ClaimDomain,
    ClaimError,
    ClaimKind,
    ClaimVerificationError,
    ClaimVerificationReport,
)

if TYPE_CHECKING:
    from os import PathLike


class ClaimGraphError(ClaimError):
    """Base class for invalid theorem DAGs."""


class DuplicateClaimError(ClaimGraphError):
    """Raised when a claim ID is rebound to different semantics."""


class MissingClaimError(ClaimGraphError, KeyError):
    """Raised when a dependency or requested claim is absent."""


class ClaimCycleError(ClaimGraphError):
    """Raised when mathematical dependencies contain a cycle."""


class ClaimGraph:
    """Mutable builder with deterministic validation and immutable claim nodes.

    Edges are taken from mathematical claims' ``why`` fields.  Domain-qualified
    non-mathematical claims are permitted as additive leaf nodes, but cannot use
    ``why`` and cannot become logical premises of mathematical claims.  By
    default, adding a claim requires all dependencies to already exist; bulk
    construction and decoding validate after all nodes are loaded so serialized
    order does not matter.
    """

    schema_version = "arbogast.claim-graph/v1"

    def __init__(
        self,
        claims: Iterable[Claim] = (),
        *,
        graph_id: str | None = None,
    ) -> None:
        if graph_id is not None and (not isinstance(graph_id, str) or not graph_id.strip()):
            raise ClaimGraphError("graph_id must be a non-blank string or null")
        self.graph_id = graph_id
        self._claims: dict[str, Claim] = {}
        for claim in claims:
            self._insert_unchecked(claim)
        self.validate()

    def __len__(self) -> int:
        return len(self._claims)

    def __iter__(self) -> Iterator[Claim]:
        for claim_id in self.topological_ids():
            yield self._claims[claim_id]

    def __contains__(self, claim_id: object) -> bool:
        return claim_id in self._claims

    @property
    def digest(self) -> str:
        return content_address(self.to_canonical())

    @property
    def claims(self) -> tuple[Claim, ...]:
        return tuple(self)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._claims))

    def get(self, claim_id: str) -> Claim:
        try:
            return self._claims[claim_id]
        except KeyError as exc:
            raise MissingClaimError(claim_id) from exc

    def add_claim(self, claim: Claim, *, allow_unresolved: bool = False) -> Claim:
        """Add one immutable node, rejecting rebinding and (normally) missing dependencies."""

        if not allow_unresolved:
            missing = sorted(set(claim.dependency_ids) - self._claims.keys())
            if missing:
                raise MissingClaimError(
                    f"claim {claim.id} has unresolved dependencies: {', '.join(missing)}"
                )
        self._insert_unchecked(claim)
        try:
            self.validate(allow_unresolved=allow_unresolved)
        except Exception:
            if self._claims.get(claim.id) is claim:
                del self._claims[claim.id]
            raise
        return claim

    add = add_claim

    def _insert_unchecked(self, claim: Claim) -> None:
        existing = self._claims.get(claim.id)
        if existing is not None:
            if existing != claim:
                raise DuplicateClaimError(f"claim ID is already bound: {claim.id}")
            return
        self._claims[claim.id] = claim

    def validate(self, *, allow_unresolved: bool = False) -> ClaimGraph:
        """Require a complete acyclic graph with domain-safe v1 dependency edges."""

        missing_by_claim: dict[str, list[str]] = {}
        for claim in self._claims.values():
            missing = sorted(set(claim.dependency_ids) - self._claims.keys())
            if missing:
                missing_by_claim[claim.id] = missing
            if claim.domain is ClaimDomain.MATHEMATICAL:
                nonmathematical = sorted(
                    dependency_id
                    for dependency_id in claim.dependency_ids
                    if dependency_id in self._claims
                    and self._claims[dependency_id].domain is not ClaimDomain.MATHEMATICAL
                )
                if nonmathematical:
                    raise ClaimGraphError(
                        f"mathematical claim {claim.id} cannot depend on non-mathematical "
                        f"claims: {', '.join(nonmathematical)}"
                    )
        if missing_by_claim and not allow_unresolved:
            detail = "; ".join(
                f"{claim}: {','.join(missing)}"
                for claim, missing in sorted(missing_by_claim.items())
            )
            raise MissingClaimError(f"unresolved claim dependencies: {detail}")
        self._topological_ids(allow_unresolved=allow_unresolved)
        return self

    def dependencies_of(self, claim_id: str, *, transitive: bool = False) -> tuple[Claim, ...]:
        claim = self.get(claim_id)
        if not transitive:
            return tuple(self.get(item) for item in sorted(claim.dependency_ids))
        found: set[str] = set()
        pending = list(claim.dependency_ids)
        while pending:
            current = pending.pop()
            if current in found:
                continue
            dependency = self.get(current)
            found.add(current)
            pending.extend(dependency.dependency_ids)
        order = self.topological_ids()
        return tuple(self._claims[item] for item in order if item in found)

    def dependents_of(self, claim_id: str, *, transitive: bool = False) -> tuple[Claim, ...]:
        self.get(claim_id)
        direct = {claim.id for claim in self._claims.values() if claim_id in claim.dependency_ids}
        if not transitive:
            return tuple(self._claims[item] for item in sorted(direct))
        found = set(direct)
        frontier = list(direct)
        while frontier:
            current = frontier.pop()
            for claim in self._claims.values():
                if current in claim.dependency_ids and claim.id not in found:
                    found.add(claim.id)
                    frontier.append(claim.id)
        return tuple(self._claims[item] for item in self.topological_ids() if item in found)

    def topological_ids(self) -> tuple[str, ...]:
        return self._topological_ids(allow_unresolved=False)

    def _topological_ids(self, *, allow_unresolved: bool) -> tuple[str, ...]:
        indegree = {claim_id: 0 for claim_id in self._claims}
        dependents: dict[str, set[str]] = {claim_id: set() for claim_id in self._claims}
        for claim in self._claims.values():
            for dependency in claim.dependency_ids:
                if dependency not in self._claims:
                    if allow_unresolved:
                        continue
                    raise MissingClaimError(dependency)
                indegree[claim.id] += 1
                dependents[dependency].add(claim.id)
        ready = deque(sorted(claim_id for claim_id, degree in indegree.items() if degree == 0))
        order: list[str] = []
        while ready:
            current = ready.popleft()
            order.append(current)
            for dependent in sorted(dependents[current]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
            if len(ready) > 1:
                ready = deque(sorted(ready))
        if len(order) != len(self._claims):
            cyclic = sorted(claim_id for claim_id, degree in indegree.items() if degree > 0)
            raise ClaimCycleError(f"claim dependency cycle involves: {', '.join(cyclic)}")
        return tuple(order)

    def roots(self) -> tuple[Claim, ...]:
        return tuple(claim for claim in self if not claim.why)

    def leaves(self) -> tuple[Claim, ...]:
        dependency_ids = {
            dependency for claim in self._claims.values() for dependency in claim.dependency_ids
        }
        return tuple(claim for claim in self if claim.id not in dependency_ids)

    def theorem_holes(self) -> tuple[Claim, ...]:
        """Return the external trust base and open claims in dependency order."""

        return tuple(
            claim
            for claim in self
            if claim.domain is ClaimDomain.MATHEMATICAL
            and claim.kind in {ClaimKind.ASSUMED, ClaimKind.IMPORTED, ClaimKind.CONJECTURED}
        )

    def verify(
        self,
        certificates: Mapping[str, Certificate] | None = None,
        *,
        verifier_registry: VerifierRegistry = default_verifiers,
        source_registry: object | None = None,
        structural_only: bool = False,
        raise_on_failure: bool = True,
    ) -> ClaimGraphVerificationReport:
        """Verify every claim node in dependency order, across all domains.

        A structural-only check proves no claim and reports ``verified=False``.  Full verification
        replays every independent node and preserves its per-node report.  An unrelated
        non-mathematical failure therefore makes the all-node aggregate false without invalidating
        a successfully verified mathematical node or becoming its logical dependency.  Only
        explicit ``why`` edges govern theorem dependencies.  Domain-filtered exports are
        presentation projections; they do not weaken this all-node aggregate verification.
        """

        self.validate()
        if structural_only:
            return ClaimGraphVerificationReport(
                graph_digest=self.digest,
                structural_valid=True,
                verified=False,
                claims=tuple(
                    claim.verify(structural_only=True, raise_on_failure=False) for claim in self
                ),
                error="structural DAG validation does not replay claim evidence in any domain",
            )
        reports: list[ClaimVerificationReport] = []
        verified_ids: set[str] = set()
        first_error: str | None = None
        for claim in self:
            report = claim.verify(
                certificates,
                verifier_registry=verifier_registry,
                source_registry=source_registry,
                verified_dependencies=verified_ids,
                dependency_claims=self._claims,
                raise_on_failure=False,
            )
            reports.append(report)
            if report.verified:
                verified_ids.add(claim.id)
            elif first_error is None:
                first_error = f"{claim.id}: {report.error}"
        valid = len(verified_ids) == len(self)
        graph_report = ClaimGraphVerificationReport(
            graph_digest=self.digest,
            structural_valid=True,
            verified=valid,
            claims=tuple(reports),
            error=None if valid else first_error or "one or more claims were not verified",
        )
        if not valid and raise_on_failure:
            raise ClaimVerificationError(graph_report.error or "claim graph verification failed")
        return graph_report

    def subgraph(self, claim_id: str, *, include_dependencies: bool = True) -> ClaimGraph:
        selected = {claim_id}
        if include_dependencies:
            selected.update(claim.id for claim in self.dependencies_of(claim_id, transitive=True))
        return ClaimGraph(
            (self._claims[item] for item in self.topological_ids() if item in selected),
            graph_id=self.graph_id,
        )

    def to_canonical(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "claims": tuple(self._claims[item] for item in self.topological_ids()),
        }

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "claims": [self._claims[item].to_dict() for item in self.topological_ids()],
        }
        plain = canonicalize(value)
        if not isinstance(plain, dict):
            raise ClaimGraphError("claim graph canonical form must be an object")
        return cast(dict[str, object], plain)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ClaimGraph:
        allowed = {"schema_version", "graph_id", "claims"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise ClaimGraphError(f"unexpected claim graph fields: {', '.join(unexpected)}")
        schema = value.get("schema_version")
        if schema != cls.schema_version:
            raise ClaimGraphError(f"unsupported claim graph schema: {schema!r}")
        raw_claims = value.get("claims")
        if isinstance(raw_claims, (str, bytes)) or not isinstance(raw_claims, Sequence):
            raise ClaimGraphError("claim graph claims must be a sequence")
        claims: list[Claim] = []
        for item in raw_claims:
            if not isinstance(item, Mapping):
                raise ClaimGraphError("claim graph node must be a mapping")
            claims.append(Claim.from_dict(item))
        graph_id = value.get("graph_id")
        if graph_id is not None and not isinstance(graph_id, str):
            raise ClaimGraphError("claim graph_id must be a string or null")
        return cls(
            claims,
            graph_id=graph_id,
        )

    def export(
        self,
        format: str,
        destination: str | PathLike[str] | None = None,
        **options: object,
    ) -> str:
        from arbogast.export import export

        return export(self, format, destination=destination, **options)


class ClaimGraphVerificationReport:
    """Aggregate report that preserves each node's verification boundary."""

    def __init__(
        self,
        *,
        graph_digest: str,
        structural_valid: bool,
        verified: bool,
        claims: Sequence[ClaimVerificationReport],
        error: str | None = None,
    ) -> None:
        self.graph_digest = graph_digest
        self.structural_valid = structural_valid
        self.verified = verified
        self.claims = tuple(claims)
        self.error = error
        if verified and (not structural_valid or error is not None):
            raise ClaimVerificationError("verified graph report cannot carry a structural error")
        if not verified and not error:
            raise ClaimVerificationError("unverified graph report must explain the gap")

    def to_canonical(self) -> dict[str, object]:
        return {
            "graph_digest": self.graph_digest,
            "structural_valid": self.structural_valid,
            "verified": self.verified,
            "claims": self.claims,
            "error": self.error,
        }


__all__ = [
    "ClaimCycleError",
    "ClaimGraph",
    "ClaimGraphError",
    "ClaimGraphVerificationReport",
    "DuplicateClaimError",
    "MissingClaimError",
]
