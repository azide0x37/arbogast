from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from arbogast.arithmetic import LocalPairing
from arbogast.backends import PariArithmeticResult, PariBackend
from arbogast.galois import (
    FinitePlace,
    InfinitePlace,
    KummerSpace,
    LocalH1Space,
    LocalizationMap,
    NumberField,
    NumberFieldElement,
    kummer_space,
    local_h1,
    localize,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ARBOGAST_LIVE_PARI") != "1",
    reason="set ARBOGAST_LIVE_PARI=1 for the dedicated live-PARI job",
)


def test_live_pari_closed_arithmetic_and_fresh_certificate_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which("gp") is None:
        pytest.skip("live-PARI job did not provision gp")

    # This file would abort an adapter that consulted user startup state.
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    (hostile_home / ".gprc").write_text('error("hostile startup was read")\n')
    monkeypatch.setenv("HOME", str(hostile_home))

    backend = PariBackend(certification_timeout_seconds=30)
    probe = backend.probe()
    assert probe.status.available
    assert probe.normalized_version in {"2.15.5", "2.17.4"}
    assert all(probe.smoke_tests.values())

    field = NumberField((-1, -1, 1), generator_name="t")
    t = NumberFieldElement(field, (0, 1))
    invariants = backend.field_invariants(field)
    assert invariants.payload.to_dict()["discriminant"] == 5
    assert invariants.verify().valid
    primes = backend.prime_decomposition(field, 2)
    assert primes.payload.to_dict()["prime_ideals"]
    assert primes.verify().valid

    quartic_polynomial = (1, -1, 0, 0, 1)
    quartic_invariants = backend.field_invariants(quartic_polynomial)
    quartic_basis = tuple(
        tuple(Fraction(*pair) for pair in row)
        for row in quartic_invariants.payload.to_dict()["integral_basis"]
    )
    quartic = NumberField(
        quartic_polynomial,
        integral_basis=quartic_basis,
        irreducibility_witness=2,
        field_invariants_certificate=quartic_invariants.certificate,
    )
    complex_isolation = backend.complex_root_isolation(quartic, 0)
    complex_payload = complex_isolation.payload.to_dict()
    assert complex_payload["kind"] == "complex"
    assert complex_payload["root_count"] == 1
    assert complex_payload["isolation"][2][0] > 0
    assert (
        complex_isolation.require_verified_payload("complex_root_isolation", complete=True)[
            "root_count"
        ]
        == 1
    )

    norm = backend.relative_norm(field, t)
    assert norm.payload.to_dict()["norm"] == [-1, 1]
    assert norm.certificate is not None
    assert norm.verify().valid
    assert norm.claim().verify().verified
    assert (2 * t - 1) ** 2 == NumberFieldElement(field, (5,))

    q_s_units = backend.s_unit_squareclasses(NumberField.rationals(), (2,))
    assert q_s_units.assumptions == ()
    assert q_s_units.payload.to_dict()["representatives"] == [[[-1, 1]], [[2, 1]]]
    assert q_s_units.verify().valid

    # Q(sqrt(-5)) has an even S-class component for S empty.  The adapter
    # must append the actual K(S,2) lift, not substitute ordinary class-group
    # metadata or fail-open to a unit-only basis.
    class_two_field = NumberField((5, 0, 1), generator_name="u")
    s_class_kummer = backend.s_unit_squareclasses(class_two_field, ())
    s_class_payload = s_class_kummer.payload.to_dict()
    assert s_class_payload["s_class_group_cyclic_orders"] == [2]
    assert s_class_payload["s_unit_rank"] == 1
    assert len(s_class_payload["s_class_2_torsion"]) == 1
    lift = s_class_payload["s_class_2_torsion"][0]
    assert lift["s_prime_exponents"] == []
    assert s_class_payload["representatives"][-1] == lift["principalization_generator"]
    lift_element = NumberFieldElement(
        class_two_field,
        tuple(Fraction(*pair) for pair in lift["principalization_generator"]),
    )
    ideal_hnf = lift["ideal_hnf"]
    ideal_norm = ideal_hnf[0][0] * ideal_hnf[1][1]
    assert abs(lift_element.norm()) == ideal_norm**2
    assert s_class_kummer.verify().valid

    nonempty_s_class_kummer = backend.s_unit_squareclasses(class_two_field, (11,))
    nonempty_s_class_payload = nonempty_s_class_kummer.payload.to_dict()
    assert nonempty_s_class_payload["prime_ideal_hnfs"] == [[[11, 0], [0, 11]]]
    assert nonempty_s_class_payload["s_class_group_cyclic_orders"] == [2]
    nonempty_lifts = nonempty_s_class_payload["s_class_2_torsion"]
    assert isinstance(nonempty_lifts, list) and len(nonempty_lifts) == 1
    assert nonempty_lifts[0]["s_prime_exponents"] == [0]
    assert nonempty_s_class_kummer.verify().valid

    class_two = backend.class_group_2_torsion(field)
    assert class_two.payload.to_dict()["two_torsion"] == []
    assert class_two.verify().valid

    local = backend.local_squareclasses(NumberField.rationals(), 2)
    assert local.payload.to_dict()["representatives"] == [
        [[-1, 1]],
        [[2, 1]],
        [[5, 1]],
    ]
    assert local.verify().valid
    localization = backend.localization_matrix(
        NumberField.rationals(),
        ((-1,), (2,)),
        2,
    )
    assert localization.payload.to_dict()["matrix"] == [[1, 0], [0, 1], [0, 0]]
    assert localization.verify().valid
    hilbert = backend.quadratic_hilbert_pairing(NumberField.rationals(), (-1,), (-1,), 2)
    assert hilbert.payload.to_dict()["symbol"] == -1
    assert hilbert.verify().valid


def test_live_pari_public_quadratic_kummer_local_h1_and_localization() -> None:
    if shutil.which("gp") is None:
        pytest.skip("live-PARI job did not provision gp")

    backend = PariBackend(certification_timeout_seconds=30)
    field = NumberField((5, 0, 1), generator_name="u")
    invariants = backend.field_invariants(field)
    invariants_payload = invariants.payload.to_dict()
    assert invariants_payload["discriminant"] == -20
    assert invariants_payload["signature"] == [0, 1]
    assert invariants.verify().valid

    def places_from(
        decomposition: PariArithmeticResult,
        rational_prime: int,
    ) -> tuple[FinitePlace, ...]:
        records = decomposition.payload.to_dict()["prime_ideals"]
        assert isinstance(records, list) and records
        requirements = decomposition.proof_context().verification_requirements
        assert len(requirements) == 1
        assert decomposition.certificate is not None
        return tuple(
            FinitePlace(
                field,
                rational_prime,
                record["ideal_hnf"],
                record["ramification_index"],
                record["residue_degree"],
                verification_requirement=requirements[0],
                prime_decomposition_certificate=decomposition.certificate,
            )
            for record in records
            if isinstance(record, dict)
        )

    at_two = places_from(backend.prime_decomposition(field, 2), 2)
    at_five = places_from(backend.prime_decomposition(field, 5), 5)
    assert len(at_two) == len(at_five) == 1
    two_adic = at_two[0]
    infinity = InfinitePlace(field, "complex", (-1, 1, 2, 3))

    global_space = kummer_space(field, (*at_two, *at_five, infinity), backend=backend)
    incomplete_global_space = kummer_space(field, (*at_two, infinity), backend=backend)
    local_space = local_h1(two_adic, backend=backend)
    assert isinstance(global_space, KummerSpace)
    assert isinstance(incomplete_global_space, KummerSpace)
    assert isinstance(local_space, LocalH1Space)
    localization = localize(global_space, local_space, backend=backend)
    assert isinstance(localization, LocalizationMap)
    pairing = LocalPairing.hilbert(local_space, backend=backend)

    assert global_space.dimension == 3
    assert global_space.relevant_places_complete
    assert not incomplete_global_space.relevant_places_complete
    assert local_space.dimension == 4
    assert localization.matrix.nrows == local_space.dimension
    assert localization.matrix.ncols == global_space.dimension
    for result in (global_space, local_space, localization):
        assert result.verify()
        assert result.claim().verify().verified
        assert result.claim_graph().verify().verified
    assert pairing.matrix.shape == (local_space.dimension, local_space.dimension)
    assert pairing.is_perfect
    assert pairing.verify().valid
    assert pairing.claim().status.value == "certified"
    assert pairing.claim().verify().verified
    assert pairing.claim_graph().verify().verified

    program = """
import json, sys
from arbogast.claims import Claim
for payload in json.load(sys.stdin):
    assert Claim.from_dict(payload).verify().verified
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps(
            [
                global_space.claim().to_dict(),
                local_space.claim().to_dict(),
                localization.claim().to_dict(),
                pairing.claim().to_dict(),
            ]
        ),
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stderr
