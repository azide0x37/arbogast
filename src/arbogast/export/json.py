"""Stable JSON export for semantic artifacts."""

from __future__ import annotations

import json as _json

from arbogast.cert.canonical import canonical_json, canonicalize


def export_json(value: object, *, pretty: bool = False) -> str:
    """Render semantic data as deterministic JSON.

    Pretty output changes whitespace only; parsed content and all strings still use the same
    canonical normalization rules.  Content identities always use the compact form.
    """

    to_dict = getattr(value, "to_dict", None)
    transport = to_dict() if callable(to_dict) else value
    if not pretty:
        return canonical_json(transport)
    return (
        _json.dumps(
            canonicalize(transport),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


__all__ = ["export_json"]
