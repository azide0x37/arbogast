"""Shared lifting of proof-bearing results to their semantic claim graph."""

from __future__ import annotations

from arbogast.claims import ClaimGraph

_ADDITIVE_SEMANTIC_MODULE_PREFIXES = (
    "arbogast.arithmetic.",
    "arbogast.deform.",
    "arbogast.galois.",
    "arbogast.numeric.",
    "arbogast.padic.",
    "arbogast.cohom.five_term",
    "arbogast.cohom.maps",
    "arbogast.rep.maps",
)


def claim_graph_for_export(value: object) -> ClaimGraph | None:
    """Return the claim graph exposed by a proof-bearing result, if any.

    Exporters intentionally preserve their established direct ``Claim`` and
    ``ClaimGraph`` contracts.  This helper handles only the additive duck-typed
    result surface: a public object that advertises ``claim_graph()`` must
    return an actual central :class:`ClaimGraph` rather than silently falling
    back to unrelated structural data.
    """

    module = type(value).__module__
    if module.startswith("arbogast.") and not module.startswith(_ADDITIVE_SEMANTIC_MODULE_PREFIXES):
        # Existing 0.1 semantic objects retain their established structural
        # JSON/Markdown/agent transport.  Claim-graph lifting is an additive
        # contract for the new 0.2 result modules, not a global reinterpretation.
        return None
    provider = getattr(value, "claim_graph", None)
    if provider is None:
        return None
    if not callable(provider):
        raise TypeError(
            f"{type(value).__qualname__}.claim_graph must be callable for semantic export"
        )
    graph = provider()
    if not isinstance(graph, ClaimGraph):
        raise TypeError(
            f"{type(value).__qualname__}.claim_graph() must return ClaimGraph, "
            f"not {type(graph).__qualname__}"
        )
    return graph


__all__ = ["claim_graph_for_export"]
