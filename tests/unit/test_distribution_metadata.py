from __future__ import annotations

import re
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_readme_is_pypi_safe_and_advertises_registry_install() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "uv add arbogast" in readme
    assert "https://pypi.org/project/arbogast/" in readme
    assert not re.findall(r"\]\((?!https?://|mailto:|#)[^)]+\)", readme)
    assert not re.findall(r'(?:src|href)="(?!https?://|mailto:|#)[^"]+"', readme)

    repository_targets = re.findall(
        r"https://github\.com/azide0x37/arbogast/(?:blob|tree)/main/([^\s)\"]+)",
        readme,
    )
    raw_targets = re.findall(
        r"https://raw\.githubusercontent\.com/azide0x37/arbogast/main/([^\s)\"]+)",
        readme,
    )
    missing = [
        target
        for target in (*repository_targets, *raw_targets)
        if not (PROJECT_ROOT / target).exists()
    ]
    assert not missing


def test_distribution_metadata_advertises_public_documentation() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["name"] == "arbogast"
    assert project["project"]["urls"]["Documentation"] == (
        "https://github.com/azide0x37/arbogast/tree/main/docs"
    )
    assert project["project"]["urls"]["Changelog"] == (
        "https://github.com/azide0x37/arbogast/blob/main/CHANGELOG.md"
    )


def test_campaign_template_pins_the_production_registry_release() -> None:
    template = tomllib.loads(
        (PROJECT_ROOT / "examples/campaigns/_template/pyproject.toml").read_text(encoding="utf-8")
    )

    assert template["project"]["dependencies"] == ["arbogast==0.6.0"]
