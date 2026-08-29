"""Backend-independent formal mathematical statements."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from arbogast.cert.canonical import FrozenMap, content_address, freeze_mapping


class StatementError(ValueError):
    """Raised for ambiguous or malformed statement records."""


@dataclass(frozen=True)
class FormalStatement:
    """A mathematical assertion with optional language-specific renderings.

    ``text`` is always required and is the backend-independent semantic fallback.  A Lean
    exporter may use ``renderings["lean"]`` only when explicitly supplied; it never guesses a
    formal proposition from prose.
    """

    text: str
    language: str = "mathematics"
    renderings: FrozenMap = field(default_factory=FrozenMap)
    parameters: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise StatementError("formal statement text must be a string")
        if not self.text.strip():
            raise StatementError("formal statement text cannot be blank")
        if not isinstance(self.language, str):
            raise StatementError("formal statement language must be a string")
        if not self.language.strip():
            raise StatementError("formal statement language cannot be blank")
        object.__setattr__(self, "renderings", freeze_mapping(self.renderings))
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))
        if any(
            not isinstance(value, str) or not value.strip() for value in self.renderings.values()
        ):
            raise StatementError("statement renderings must be non-empty strings")

    @classmethod
    def create(
        cls,
        text: str,
        *,
        language: str = "mathematics",
        renderings: Mapping[str, object] | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> FormalStatement:
        return cls(
            text=text,
            language=language,
            renderings=freeze_mapping(renderings),
            parameters=freeze_mapping(parameters),
        )

    @property
    def statement_hash(self) -> str:
        return content_address(self.to_canonical())

    def render(self, language: str, *, fallback: bool = True) -> str:
        rendered = self.renderings.get(language)
        if isinstance(rendered, str):
            return rendered
        if fallback:
            return self.text
        raise StatementError(f"no {language!r} rendering is available")

    def to_canonical(self) -> dict[str, object]:
        return {
            "text": self.text,
            "language": self.language,
            "renderings": self.renderings,
            "parameters": self.parameters,
        }

    def to_dict(self) -> dict[str, object]:
        return self.to_canonical()

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> FormalStatement:
        allowed = {"text", "language", "renderings", "parameters"}
        unexpected = sorted(set(value) - allowed)
        if unexpected:
            raise StatementError(f"unexpected statement fields: {', '.join(unexpected)}")
        text = value.get("text")
        language = value.get("language", "mathematics")
        if not isinstance(text, str):
            raise StatementError("statement text must be a string")
        if not isinstance(language, str):
            raise StatementError("statement language must be a string")
        renderings = value.get("renderings")
        parameters = value.get("parameters")
        return cls.create(
            text=text,
            language=language,
            renderings=_mapping_or_none(renderings),
            parameters=_mapping_or_none(parameters),
        )


Hypothesis = FormalStatement
Conclusion = FormalStatement


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise StatementError("statement metadata must be a string-keyed mapping")
    return value


__all__ = ["Conclusion", "FormalStatement", "Hypothesis", "StatementError"]
