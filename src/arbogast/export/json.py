"""Stable JSON export for semantic artifacts."""

from __future__ import annotations

from arbogast.cert.canonical import canonical_json, canonicalize
from arbogast.core.canonical import pretty_canonical_json


def export_json(value: object, *, pretty: bool = False) -> str:
    """Render semantic data as deterministic JSON.

    Pretty output changes whitespace only; parsed content and all strings still use the same
    canonical normalization rules.  Content identities always use the compact form.
    """

    to_dict = getattr(value, "to_dict", None)
    transport = to_dict() if callable(to_dict) else value
    if not pretty:
        return canonical_json(transport)
    return pretty_canonical_json(canonicalize(transport), indent=2) + "\n"


__all__ = ["export_json"]
