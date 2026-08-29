"""Example orchestration around Arbogast's public exact M23 Hurwitz API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from arbogast.cert import VerificationCertificate
from arbogast.claims import ClaimGraph
from arbogast.hurwitz import (
    M23ExactDataset,
    load_m23_exact_dataset,
    m23_certificates_for,
    m23_claim_graph_for,
    m23_verifier_registry,
)
from arbogast.hurwitz.m23_exact import load_strict_json
from arbogast.sources import ProvenanceRecord, SourceRegistry

HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "expected"
MANIFEST = EXPECTED / "manifest.json"
DATASET = EXPECTED / "dataset.json"
SOURCES = EXPECTED / "sources.json"

OUTPUT_SCHEMA = "arbogast.example.m23-real-component.claim-projection/v3"
PROVENANCE_ID = "m23_236_public_exact_projection"


def require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a string-keyed object")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class M23PublicWorkflow:
    dataset: M23ExactDataset
    graph: ClaimGraph
    certificates: Mapping[str, VerificationCertificate]
    sources: SourceRegistry


def load_source_registry(path: Path = SOURCES) -> SourceRegistry:
    raw = require_mapping(load_strict_json(path.read_bytes(), "sources"), "sources")
    return SourceRegistry.from_dict(raw)


def bind_projection_provenance(
    sources: SourceRegistry,
    dataset: M23ExactDataset,
    graph: ClaimGraph,
) -> None:
    references = tuple(reference.key for reference in sources.references())
    for claim in graph:
        for reference in claim.source:
            sources.reference(reference)
    sources.register_provenance(
        ProvenanceRecord(
            id=PROVENANCE_ID,
            operation="arbogast.hurwitz.m23_claim_graph_for",
            inputs=(
                f"sha256:{dataset.verification.dataset_sha256}",
                f"sha256:{dataset.verification.manifest_sha256}",
                dataset.certificate.certificate_id,
            ),
            outputs=(*graph.ids(), graph.digest),
            source_references=references,
            artifacts=(
                f"sha256:{dataset.verification.dataset_sha256}",
                f"sha256:{dataset.verification.manifest_sha256}",
            ),
            parameters={
                "claim_count": len(graph),
                "source_boundary": (
                    "Häfner and ATLAS references supply convention and nomenclature context; "
                    "the exact finite certificate alone proves the computed conclusions."
                ),
                "verifier": "hurwitz.m23_exact",
            },
        )
    )


def build_public_workflow(
    *,
    manifest_path: Path = MANIFEST,
    dataset_path: Path = DATASET,
    sources_path: Path = SOURCES,
) -> M23PublicWorkflow:
    """Replay the typed dataset and construct its public certificate/ClaimGraph bundle."""

    dataset = load_m23_exact_dataset(manifest_path, dataset_path)
    graph = m23_claim_graph_for(dataset, provenance_record=PROVENANCE_ID)
    certificates = m23_certificates_for(dataset)
    report = graph.verify(
        certificates,
        verifier_registry=m23_verifier_registry(dataset),
    )
    if not report.verified:
        raise ValueError(report.error or "public M23 ClaimGraph verification failed")
    sources = load_source_registry(sources_path)
    bind_projection_provenance(sources, dataset, graph)
    return M23PublicWorkflow(dataset, graph, certificates, sources)


__all__ = [
    "DATASET",
    "EXPECTED",
    "HERE",
    "MANIFEST",
    "OUTPUT_SCHEMA",
    "PROVENANCE_ID",
    "SOURCES",
    "M23PublicWorkflow",
    "bind_projection_provenance",
    "build_public_workflow",
    "load_source_registry",
    "require_mapping",
]
