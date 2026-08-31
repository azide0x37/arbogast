"""Domain selection shared by human- and agent-facing claim projections."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import TypeAlias

from arbogast.claims import Claim, ClaimDomain

DomainFilter: TypeAlias = ClaimDomain | str | Collection[ClaimDomain | str] | None


def normalize_domains(domains: DomainFilter) -> frozenset[ClaimDomain] | None:
    """Normalize an optional closed claim-domain filter.

    A single string is one domain rather than a collection of characters.
    Empty collections are valid and intentionally select no claims.
    """

    if domains is None:
        return None
    if isinstance(domains, (ClaimDomain, str)):
        values: Iterable[ClaimDomain | str] = (domains,)
    elif isinstance(domains, Collection):
        values = domains
    else:
        raise TypeError("domains must be a claim domain, a collection of domains, or null")
    return frozenset(ClaimDomain(value) for value in values)


def select_claims(
    claims: Iterable[Claim],
    domains: frozenset[ClaimDomain] | None,
) -> tuple[Claim, ...]:
    if domains is None:
        return tuple(claims)
    return tuple(claim for claim in claims if claim.domain in domains)


def domain_label(domains: frozenset[ClaimDomain]) -> str:
    return ", ".join(sorted(domain.value for domain in domains)) or "none"


__all__ = ["DomainFilter", "domain_label", "normalize_domains", "select_claims"]
