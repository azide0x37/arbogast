from __future__ import annotations

import pytest

from arbogast.core import (
    Artifact,
    ArtifactRef,
    ValidationError,
    VerificationError,
    canonical_json,
)


def test_artifact_is_content_addressed_and_hashable() -> None:
    first = Artifact("matrix-certificate", "1", {"rank": 2, "pivots": [0, 3]})
    reordered = Artifact("matrix-certificate", "1", {"pivots": (0, 3), "rank": 2})

    assert first == reordered
    assert hash(first) == hash(reordered)
    assert first.ref == reordered.ref
    assert first.ref.digest.startswith("sha256:")
    assert len(first.ref.digest) == len("sha256:") + 64
    assert first.verify()


def test_artifact_identity_binds_kind_and_schema() -> None:
    payload = {"value": 7}

    assert Artifact("kind-a", "1", payload).ref != Artifact("kind-b", "1", payload).ref
    assert Artifact("kind-a", "1", payload).ref != Artifact("kind-a", "2", payload).ref


def test_artifact_payload_is_not_mutable_internal_state() -> None:
    artifact = Artifact("example", "1", {"nested": [1, 2]})
    payload = artifact.payload
    assert isinstance(payload, dict)
    nested = payload["nested"]
    assert isinstance(nested, list)
    nested.append(3)

    assert artifact.payload == {"nested": [1, 2]}
    assert artifact.verify()


def test_artifact_load_requires_canonical_text_and_expected_reference() -> None:
    artifact = Artifact("example", "1", {"a": 1, "b": 2})
    loaded = Artifact.from_canonical_json(
        "example", "1", artifact.payload_json, expected_ref=artifact.ref
    )
    assert loaded == artifact

    with pytest.raises(VerificationError, match="expected reference"):
        Artifact.from_canonical_json(
            "example",
            "1",
            artifact.payload_json,
            expected_ref=Artifact("example", "1", {"a": 9}).ref,
        )


def test_artifact_verification_fails_closed_after_tampering() -> None:
    artifact = Artifact("example", "1", {"safe": True})
    object.__setattr__(artifact, "payload_json", canonical_json({"safe": False}))

    with pytest.raises(VerificationError, match="does not match"):
        artifact.verify()


@pytest.mark.parametrize(
    ("kind", "version"),
    [("", "1"), (" leading", "1"), ("trailing ", "1"), ("kind", "")],
)
def test_artifact_labels_are_validated(kind: str, version: str) -> None:
    with pytest.raises(ValidationError):
        Artifact(kind, version, {})


def test_artifact_ref_rejects_malformed_digest() -> None:
    with pytest.raises(ValidationError, match="digest"):
        ArtifactRef("kind", "1", "sha256:ABC")


def test_artifact_canonical_encoding_is_self_contained() -> None:
    artifact = Artifact("example", "1", {"value": 3})
    encoded = canonical_json(artifact)

    assert artifact.ref.digest in encoded
    assert '"payload":{"value":3}' in encoded


def test_artifact_identity_preserves_arbitrarily_large_exact_integers() -> None:
    value = -(10**5000)
    artifact = Artifact("large-integer", "1", {"value": value})

    assert artifact.payload == {"value": value}
    assert artifact.verify()
    assert (
        Artifact.from_canonical_json(
            artifact.kind,
            artifact.schema_version,
            artifact.payload_json,
            expected_ref=artifact.ref,
        )
        == artifact
    )
