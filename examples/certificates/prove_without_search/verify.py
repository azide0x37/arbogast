"""Verify a modular-reachability certificate without importing or rerunning search."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from arbogast.cert import (
    CertificateVerificationError,
    VerificationCertificate,
    VerificationReport,
    certificate_from_json,
    verifier,
    verify_certificate,
)

VERIFIER = "examples.modular_reachability.v1"
ALLOWED_OPERATIONS = ("add_3", "double")


def require_integer(value: object, name: str) -> int:
    """Reject booleans and non-integers at the certificate boundary."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise CertificateVerificationError(f"{name} must be an integer")
    return value


def apply_move(state: int, operation: str, modulus: int) -> int:
    """Evaluate one allowed move; this is checking, not path search."""

    if operation == "add_3":
        return (state + 3) % modulus
    if operation == "double":
        return (2 * state) % modulus
    raise CertificateVerificationError(f"operation is not allowed: {operation!r}")


@verifier(VERIFIER, certificate_type=VerificationCertificate)
def verify_modular_reachability(
    certificate: VerificationCertificate,
) -> VerificationReport:
    """Check the complete path witness using only certificate data."""

    witness = certificate.witness.to_dict()
    modulus = require_integer(witness.get("modulus"), "modulus")
    start = require_integer(witness.get("start"), "start")
    target = require_integer(witness.get("target"), "target")
    operations = witness.get("operations")
    path = witness.get("path")

    if modulus <= 1:
        raise CertificateVerificationError("modulus must exceed one")
    if not 0 <= start < modulus or not 0 <= target < modulus:
        raise CertificateVerificationError("start and target must be canonical residues")
    if operations != list(ALLOWED_OPERATIONS):
        raise CertificateVerificationError("certificate operation set is not the contract")
    if not isinstance(path, list):
        raise CertificateVerificationError("path must be a list")

    current = start
    for index, raw_step in enumerate(path):
        if not isinstance(raw_step, Mapping):
            raise CertificateVerificationError(f"path step {index} must be an object")
        previous = require_integer(raw_step.get("from"), f"path[{index}].from")
        following = require_integer(raw_step.get("to"), f"path[{index}].to")
        operation = raw_step.get("operation")
        if not isinstance(operation, str):
            raise CertificateVerificationError(f"path[{index}].operation must be a string")
        if previous != current:
            raise CertificateVerificationError(f"path step {index} is not contiguous")
        expected = apply_move(current, operation, modulus)
        if following != expected:
            raise CertificateVerificationError(f"path step {index} is not a valid transition")
        current = following

    if current != target:
        raise CertificateVerificationError("path does not reach the stated target")

    return VerificationReport(
        valid=True,
        verifier=VERIFIER,
        certificate_id=certificate.certificate_id,
        checks=("well_formed_problem", "valid_transitions", "target_reached"),
        details={"modulus": modulus, "path_length": len(path)},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("certificate", type=Path, help="certificate emitted by discover.py")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        loaded = certificate_from_json(args.certificate.read_bytes())
        if not isinstance(loaded, VerificationCertificate):
            raise CertificateVerificationError("expected a verification-layer certificate")
        report = verify_certificate(loaded)
    except (OSError, ValueError, LookupError) as error:
        print(f"verification failed: {error}", file=sys.stderr)
        return 1

    print(f"verified: {report.certificate_id}")
    print(f"checks: {', '.join(report.checks)}")
    print(f"path length: {report.details['path_length']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
