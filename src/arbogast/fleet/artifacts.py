"""A filesystem content-addressed store with a small resumability index."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arbogast.formats import JSONValue, canonical_bytes, canonical_dumps, loads

from .models import ArtifactRef, EvidenceState

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESULT_PREFIX = "fleet:result:"


def _result_task_hash(key: str) -> str | None:
    if not key.startswith(_RESULT_PREFIX):
        return None
    candidate = key.removeprefix(_RESULT_PREFIX).split(":", 1)[0]
    if not _SHA256_RE.fullmatch(candidate):
        raise ArtifactIntegrityError("fleet result binding has an invalid task hash")
    return candidate


class ArtifactStoreError(RuntimeError):
    """Base class for content-store failures."""


class ArtifactNotFoundError(ArtifactStoreError, FileNotFoundError):
    """Raised when an artifact reference is absent."""


class ArtifactIntegrityError(ArtifactStoreError):
    """Raised when bytes do not match their reference."""


class ArtifactConflictError(ArtifactStoreError):
    """Raised when a resumability key is rebound to different content."""


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    """A cache key bound to content and a local operation-verifier receipt."""

    key: str
    artifact: ArtifactRef
    state: EvidenceState
    verification: ArtifactRef | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "artifact": self.artifact.to_dict(),
            "key": self.key,
            "state": self.state.value,
            "verification": (None if self.verification is None else self.verification.to_dict()),
        }


class ArtifactStore:
    """Store immutable bytes by SHA-256 and resume keys by verified metadata.

    The object store is content addressed.  The ``bindings`` directory is an
    index only: it maps deterministic execution keys to artifact references and
    never claims that mutable scheduler state itself is content-addressed.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects" / "sha256"
        self.bindings = self.root / "bindings"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.bindings.mkdir(parents=True, exist_ok=True)

    def _object_path(self, digest: str) -> Path:
        return self.objects / digest[:2] / digest[2:]

    def _binding_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.bindings / digest[:2] / f"{digest[2:]}.json"

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def put_bytes(
        self,
        data: bytes | bytearray | memoryview,
        *,
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef:
        payload = bytes(data)
        digest = hashlib.sha256(payload).hexdigest()
        reference = ArtifactRef(digest=digest, size=len(payload), media_type=media_type)
        path = self._object_path(digest)
        if path.exists():
            existing = path.read_bytes()
            if existing != payload:
                raise ArtifactIntegrityError(f"artifact collision or corruption at {reference.uri}")
        else:
            self._atomic_write(path, payload)
        return reference

    def put_json(self, value: Any) -> ArtifactRef:
        return self.put_bytes(canonical_bytes(value), media_type="application/json")

    def exists(self, reference: ArtifactRef, *, verify: bool = False) -> bool:
        path = self._object_path(reference.digest)
        if not path.is_file():
            return False
        if verify:
            try:
                self.get_bytes(reference)
            except ArtifactIntegrityError:
                return False
        return True

    def get_bytes(self, reference: ArtifactRef) -> bytes:
        path = self._object_path(reference.digest)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as error:
            raise ArtifactNotFoundError(reference.uri) from error
        digest = hashlib.sha256(payload).hexdigest()
        if digest != reference.digest or len(payload) != reference.size:
            raise ArtifactIntegrityError(f"artifact failed integrity check: {reference.uri}")
        return payload

    def get_json(self, reference: ArtifactRef) -> JSONValue:
        if reference.media_type != "application/json":
            raise ArtifactStoreError(f"artifact is not JSON: {reference.uri}")
        return loads(self.get_bytes(reference))

    def _write_binding(self, binding: ArtifactBinding) -> ArtifactBinding:
        path = self._binding_path(binding.key)
        self._atomic_write(path, canonical_dumps(binding.to_dict()).encode("utf-8"))
        return binding

    def _create_binding(self, binding: ArtifactBinding) -> ArtifactBinding:
        """Publish an initial binding exactly once without a check/write race."""

        path = self._binding_path(binding.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_dumps(binding.to_dict()).encode("utf-8")
        handle, temporary_name = tempfile.mkstemp(prefix=".binding-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # A hard link is an atomic create-if-absent within this directory.
            # Exactly one concurrent writer can publish a deterministic key.
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return binding

    def bind(
        self,
        key: str,
        artifact: ArtifactRef,
        state: EvidenceState = EvidenceState.DISCOVERY,
    ) -> ArtifactBinding:
        """Bind discovered content to an execution key.

        Verified state requires :meth:`verify_and_promote`, which invokes the
        verifier and creates a separate content-addressed local receipt.
        """

        if not key.strip():
            raise ArtifactStoreError("binding key must not be empty")
        if state is not EvidenceState.DISCOVERY:
            raise ArtifactStoreError(
                "bind() only records discovery state; use verify_and_promote()"
            )
        # Verify content before publishing an index entry.
        self.get_bytes(artifact)
        current = self.resolve(key)
        if current is not None:
            if current.artifact != artifact:
                raise ArtifactConflictError(
                    f"deterministic key {key!r} already refers to {current.artifact.uri}, "
                    f"not {artifact.uri}"
                )
            return current
        candidate = ArtifactBinding(
            key=key,
            artifact=artifact,
            state=EvidenceState.DISCOVERY,
        )
        try:
            return self._create_binding(candidate)
        except FileExistsError:
            # Another process won the atomic publication race.  Re-read and
            # enforce the same deterministic-content invariant.
            winner = self.resolve(key)
            if winner is None:  # pragma: no cover - link/create filesystem anomaly
                raise ArtifactIntegrityError("binding appeared then disappeared") from None
            if winner.artifact != artifact:
                raise ArtifactConflictError(
                    f"deterministic key {key!r} already refers to {winner.artifact.uri}, "
                    f"not {artifact.uri}"
                ) from None
            return winner

    def _promote_verified(
        self,
        key: str,
        artifact: ArtifactRef,
        verification: ArtifactRef,
    ) -> ArtifactBinding:
        """Promote a discovery binding using subject-bound verification evidence."""

        current = self.resolve(key)
        if current is None:
            raise ArtifactStoreError("verified promotion requires an existing discovery binding")
        if current.artifact != artifact:
            raise ArtifactConflictError("verification evidence is bound to different content")
        receipt = self.get_json(verification)
        if not isinstance(receipt, Mapping):
            raise ArtifactIntegrityError("verification receipt must be a JSON object")
        if receipt.get("schema") != "arbogast.fleet.verification-receipt.v1":
            raise ArtifactIntegrityError("verification receipt has an unsupported schema")
        if receipt.get("binding_key") != key:
            raise ArtifactIntegrityError("verification receipt is bound to a different key")
        if receipt.get("valid") is not True:
            raise ArtifactIntegrityError("verification receipt does not contain literal valid=true")
        if receipt.get("subject") != artifact.uri:
            raise ArtifactIntegrityError("verification receipt is bound to a different subject")
        verifier = receipt.get("verifier")
        if not isinstance(verifier, str) or not verifier:
            raise ArtifactIntegrityError("verification receipt must name its verifier")
        receipt_task_hash = receipt.get("task_hash")
        if not isinstance(receipt_task_hash, str) or not _SHA256_RE.fullmatch(receipt_task_hash):
            raise ArtifactIntegrityError("verification receipt must name its task hash")
        bound_task_hash = _result_task_hash(key)
        if bound_task_hash is not None and receipt_task_hash != bound_task_hash:
            raise ArtifactIntegrityError("verification receipt names a different task hash")
        return self._write_binding(
            ArtifactBinding(
                key=key,
                artifact=artifact,
                state=EvidenceState.VERIFICATION,
                verification=verification,
            )
        )

    def verify_and_promote(
        self,
        key: str,
        artifact: ArtifactRef,
        verifier: Callable[[JSONValue], bool],
        *,
        verifier_name: str,
        task_hash: str,
    ) -> ArtifactBinding:
        """Run a named local verifier and bind its content-addressed receipt.

        The resulting state is suitable for deterministic cache resumption.  A
        claim or campaign must still require its own verification certificate;
        it must never infer a mathematical outcome from this cache flag alone.
        """

        if not verifier_name.strip() or not task_hash:
            raise ArtifactStoreError("verification requires verifier_name and task_hash")
        if not _SHA256_RE.fullmatch(task_hash):
            raise ArtifactStoreError("verification task_hash must be canonical SHA-256")
        bound_task_hash = _result_task_hash(key)
        if bound_task_hash is not None and bound_task_hash != task_hash:
            raise ArtifactStoreError("verification task_hash does not match result binding")
        value = self.get_json(artifact)
        verdict = verifier(value)
        if verdict is not True:
            raise ArtifactIntegrityError("verification function did not return literal true")
        receipt = self.put_json(
            {
                "binding_key": key,
                "schema": "arbogast.fleet.verification-receipt.v1",
                "subject": artifact.uri,
                "task_hash": task_hash,
                "valid": True,
                "verifier": verifier_name,
            }
        )
        return self._promote_verified(key, artifact, receipt)

    def resolve(
        self,
        key: str,
        *,
        required_state: EvidenceState | None = None,
    ) -> ArtifactBinding | None:
        path = self._binding_path(key)
        try:
            value = loads(path.read_bytes())
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise ArtifactIntegrityError(f"binding {key!r} is not a JSON object")
        if value.get("key") != key:
            raise ArtifactIntegrityError(f"binding hash collision or corruption for {key!r}")
        artifact_value = value.get("artifact")
        if not isinstance(artifact_value, Mapping):
            raise ArtifactIntegrityError(f"binding {key!r} has no artifact reference")
        verification_value = value.get("verification")
        state_value = value.get("state")
        if not isinstance(state_value, str):
            raise ArtifactIntegrityError(f"binding {key!r} state must be a string")
        try:
            artifact = ArtifactRef.from_dict(artifact_value)
            state = EvidenceState(state_value)
        except (KeyError, TypeError, ValueError) as error:
            raise ArtifactIntegrityError(f"invalid binding {key!r}") from error
        self.get_bytes(artifact)
        verification: ArtifactRef | None = None
        if state is EvidenceState.VERIFICATION:
            if not isinstance(verification_value, Mapping):
                raise ArtifactIntegrityError(
                    f"verified binding {key!r} has no content-addressed verification receipt"
                )
            verification = ArtifactRef.from_dict(verification_value)
            receipt = self.get_json(verification)
            if not isinstance(receipt, Mapping):
                raise ArtifactIntegrityError("verification receipt must be a JSON object")
            if receipt.get("schema") != "arbogast.fleet.verification-receipt.v1":
                raise ArtifactIntegrityError("verification receipt has an unsupported schema")
            if receipt.get("binding_key") != key:
                raise ArtifactIntegrityError("verification receipt is bound to a different key")
            if receipt.get("valid") is not True or receipt.get("subject") != artifact.uri:
                raise ArtifactIntegrityError("verification receipt does not verify bound content")
            if not isinstance(receipt.get("verifier"), str) or not receipt["verifier"]:
                raise ArtifactIntegrityError("verification receipt does not name a verifier")
            receipt_task_hash = receipt.get("task_hash")
            if not isinstance(receipt_task_hash, str) or not _SHA256_RE.fullmatch(
                receipt_task_hash
            ):
                raise ArtifactIntegrityError("verification receipt does not name a task hash")
            bound_task_hash = _result_task_hash(key)
            if bound_task_hash is not None and receipt_task_hash != bound_task_hash:
                raise ArtifactIntegrityError("verification receipt names a different task hash")
        elif verification_value is not None:
            raise ArtifactIntegrityError("discovery binding cannot carry verification evidence")
        binding = ArtifactBinding(
            key=key,
            artifact=artifact,
            state=state,
            verification=verification,
        )
        if required_state is not None and not state.satisfies(required_state):
            return None
        return binding

    def verify(self, reference: ArtifactRef) -> bool:
        """Return whether an artifact is present and matches its content hash."""

        return self.exists(reference, verify=True)
