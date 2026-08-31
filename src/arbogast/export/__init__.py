"""Stable JSON, Markdown, LaTeX, Lean, and compact agent exports."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import cast

from ._domains import DomainFilter
from .agent import export_agent_context
from .json import export_json
from .latex import export_latex
from .lean import export_lean
from .markdown import export_markdown


class ExportFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    LATEX = "latex"
    LEAN = "lean"
    AGENT = "agent"


def export(
    value: object,
    format: str | ExportFormat,
    destination: str | os.PathLike[str] | None = None,
    **options: object,
) -> str:
    """Render a semantic artifact and optionally write exactly those UTF-8 bytes."""

    selected = ExportFormat(format)
    domains = cast(DomainFilter, options.get("domains"))
    if selected is ExportFormat.JSON:
        if "domains" in options:
            raise ValueError(
                "JSON claim exports are complete replay records and cannot be domain-filtered"
            )
        rendered = export_json(value, pretty=bool(options.get("pretty", False)))
    elif selected is ExportFormat.MARKDOWN:
        rendered = export_markdown(value, domains=domains)
    elif selected is ExportFormat.LATEX:
        rendered = export_latex(value, domains=domains)
    elif selected is ExportFormat.LEAN:
        namespace = options.get("namespace", "Arbogast.Generated")
        if not isinstance(namespace, str):
            raise TypeError("Lean namespace must be a string")
        rendered = export_lean(value, namespace=namespace, domains=domains)
    else:
        rendered = export_agent_context(
            value,
            pretty=bool(options.get("pretty", False)),
            domains=domains,
        )
    if destination is not None:
        Path(destination).write_text(rendered, encoding="utf-8", newline="")
    return rendered


render = export


__all__ = [
    "ExportFormat",
    "export",
    "export_agent_context",
    "export_json",
    "export_latex",
    "export_lean",
    "export_markdown",
    "render",
]
