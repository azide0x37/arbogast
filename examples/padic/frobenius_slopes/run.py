"""Certify finite-precision Frobenius slopes and an explicit ordinary part."""

from __future__ import annotations

from fractions import Fraction

from arbogast.cert import verify_certificate
from arbogast.padic import (
    Certified,
    FrobeniusConvention,
    FrobeniusOperator,
    PAdicAutomorphism,
    PAdicField,
    PAdicMatrix,
    PAdicModule,
    PAdicPrecisionRing,
    SlopeProjector,
    Unknown,
    frobenius,
    ordinary_part,
    slopes,
)


def main() -> int:
    field = PAdicField.rational(3)
    ring = PAdicPrecisionRing(field, 2)
    module = PAdicModule(ring, 2, basis_labels=("unit", "positive-slope"))
    matrix = PAdicMatrix(ring, ((1, 0), (0, 3)))
    sigma = PAdicAutomorphism.identity(ring)
    datum = FrobeniusOperator(
        module,
        matrix,
        sigma,
        FrobeniusConvention.ARITHMETIC,
    )

    operator_result = frobenius(module, datum=datum)
    assert isinstance(operator_result, Certified)
    assert operator_result.verify()

    slope_result = slopes(operator_result.value)
    assert isinstance(slope_result, Certified)
    assert slope_result.verify()
    assert tuple(
        (entry.slope, entry.multiplicity) for entry in slope_result.value.multiplicities
    ) == ((Fraction(0), 1), (Fraction(1), 1))
    assert not slope_result.value.projectors_complete

    missing = ordinary_part(slope_result.value)
    assert isinstance(missing, Unknown)
    assert missing.reason_code == "missing-saturated-projector"
    assert missing.verify()

    identity = PAdicMatrix.identity(ring, 2)
    projector = SlopeProjector(
        operator_result.value,
        0,
        1,
        PAdicMatrix(ring, ((1, 0), (0, 0))),
        identity,
        identity,
    )
    ordinary = ordinary_part(slope_result.value, projector=projector)
    assert isinstance(ordinary, Certified)
    assert ordinary.value.rank == 1
    assert ordinary.verify()
    assert verify_certificate(ordinary.certificate).valid
    assert ordinary.claim().status.value == "exact"
    assert ordinary.claim_graph().verify().verified

    print("Frobenius convention:", operator_result.value.convention.value)
    print(
        "Newton slopes:",
        tuple(
            (str(entry.slope), entry.multiplicity) for entry in slope_result.value.multiplicities
        ),
    )
    print("ordinary part without projector:", type(missing).__name__, missing.reason_code)
    print("ordinary part with projector:", type(ordinary).__name__, ordinary.value.rank)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
