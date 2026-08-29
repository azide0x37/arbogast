"""Compatibility wrapper for Arbogast's public exact M23 Hurwitz loader."""

from __future__ import annotations

from pathlib import Path

from arbogast.hurwitz.m23_exact import (
    DATASET_SCHEMA,
    MANIFEST_SCHEMA,
    M23ExactVerification,
    M23ExactVerificationError,
    load_m23_exact_dataset,
    load_strict_json,
)

HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "expected"
DATASET = EXPECTED / "dataset.json"
MANIFEST = EXPECTED / "manifest.json"

FixtureVerification = M23ExactVerification
FixtureVerificationError = M23ExactVerificationError


def verify_fixture(
    *,
    manifest_path: Path = MANIFEST,
    dataset_path: Path = DATASET,
) -> M23ExactVerification:
    """Replay the fixture through the installed public typed API."""

    return load_m23_exact_dataset(manifest_path, dataset_path).verification


__all__ = [
    "DATASET",
    "DATASET_SCHEMA",
    "MANIFEST",
    "MANIFEST_SCHEMA",
    "FixtureVerification",
    "FixtureVerificationError",
    "load_strict_json",
    "verify_fixture",
]
