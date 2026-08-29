from __future__ import annotations

import json
import subprocess
import sys

from arbogast.cert import VerifierRegistry
from arbogast.claims import ClaimGraph


def test_cohomology_and_hurwitz_publish_central_claim_graph_adapters() -> None:
    from arbogast.cohom.semantic import claim_graph_for_result
    from arbogast.hurwitz import claim_graph_for

    assert callable(claim_graph_for_result)
    assert callable(claim_graph_for)
    assert ClaimGraph.schema_version == "arbogast.claim-graph/v1"
    assert isinstance(VerifierRegistry(), VerifierRegistry)


class _PrimeField:
    characteristic = 2
    order = 2


class _CyclicTwo:
    order = 2
    elements = (0, 1)
    identity = 0

    @staticmethod
    def multiply(left: int, right: int) -> int:
        return (left + right) % 2


class _TrivialModule:
    field = _PrimeField()
    dimension = 1

    @staticmethod
    def action_matrix(element: int) -> tuple[tuple[int, ...], ...]:
        return ((1,),)


def test_cohomology_claim_json_replays_in_fresh_python_process() -> None:
    from arbogast.cohom import h1

    encoded = h1(_CyclicTwo(), _TrivialModule()).claim().export("json")
    program = """
import json, sys
from arbogast.claims import Claim
claim = Claim.from_dict(json.load(sys.stdin))
assert claim.verify().verified
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=encoded,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_self_contained_theorem_graph_replays_in_fresh_python_process() -> None:
    from arbogast.cert import CertificateRef, TheoremCertificate, VerificationCertificate
    from arbogast.claims import (
        Claim,
        ClaimKind,
        Derivation,
        DerivationKind,
        EpistemicStatus,
        FormalStatement,
        claim_boundary_hash,
    )

    premise_statement = FormalStatement("P")
    premise_certificate = VerificationCertificate.create(
        "premise",
        "tests.fresh.premise",
        claim_id="claim.premise",
        statement_hash=premise_statement.statement_hash,
        claim_boundary_hash=claim_boundary_hash(
            "claim.premise",
            premise_statement,
            kind=ClaimKind.COMPUTED,
            status=EpistemicStatus.EXACT,
        ),
        witness={"valid": True},
    )
    premise = Claim(
        "claim.premise",
        statement=premise_statement,
        kind=ClaimKind.COMPUTED,
        status=EpistemicStatus.EXACT,
        how=Derivation.computation("tests.fresh.premise"),
        certificate=premise_certificate,
    )
    conclusion_statement = FormalStatement("Q")
    theorem_certificate = TheoremCertificate.create(
        "claim.conclusion",
        conclusion_statement.statement_hash,
        (CertificateRef.from_certificate(premise_certificate),),
        claim_boundary_hash=claim_boundary_hash(
            "claim.conclusion",
            conclusion_statement,
            kind=ClaimKind.DERIVED,
            status=EpistemicStatus.EXACT,
            dependency_ids=(premise.id,),
        ),
        verifier="tests.fresh.inference",
        dependencies=(premise.id,),
        claim_dependencies=(premise.binding,),
        conclusion={"text": "Q"},
    )
    conclusion = Claim(
        "claim.conclusion",
        statement=conclusion_statement,
        kind=ClaimKind.DERIVED,
        status=EpistemicStatus.EXACT,
        why=(premise.id,),
        how=Derivation(DerivationKind.INFERENCE, "P implies Q"),
        evidence=(premise_certificate,),
        certificate=theorem_certificate,
    )
    encoded = json.dumps(ClaimGraph((premise, conclusion)).to_dict())
    program = """
import json, sys
from arbogast.cert import TheoremCertificate, VerificationCertificate, default_verifiers
from arbogast.claims import ClaimGraph
default_verifiers.register(
    "tests.fresh.premise",
    VerificationCertificate,
    lambda item: item.witness["valid"] is True,
)
default_verifiers.register(
    "tests.fresh.inference",
    TheoremCertificate,
    lambda item: item.dependencies == ("claim.premise",) and item.conclusion["text"] == "Q",
)
graph = ClaimGraph.from_dict(json.load(sys.stdin))
assert graph.verify().verified
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=encoded,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
