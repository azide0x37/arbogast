"""Recognize sqrt(2), then cross the separate exactification boundary."""

from __future__ import annotations

from arbogast.cert import (
    CertificateError,
    ContentAddressError,
    VerificationCertificate,
    verify_certificate,
)
from arbogast.numeric import (
    AlgebraicCandidate,
    ComplexBall,
    Dyadic,
    ExactificationResult,
    ExactPolynomial,
    NumericPoint,
    NumericUnknown,
    PolynomialSystem,
    RecognitionBounds,
    exactify,
    recognize,
)


def main() -> None:
    bounds = RecognitionBounds(2, 2)
    enclosure = ComplexBall(Dyadic(181, -7), Dyadic(1, -10))
    candidate = recognize(enclosure, bounds)
    assert isinstance(candidate, AlgebraicCandidate)
    assert candidate.minimal_polynomial == (-2, 0, 1)
    assert candidate.verify()

    polynomial = ExactPolynomial(
        1,
        {
            (0,): -2,
            (2,): 1,
        },
        variable_names=("x",),
    )
    point = NumericPoint(PolynomialSystem(1, (polynomial,)), (enclosure,))
    exact = exactify(point, candidate=candidate)
    assert isinstance(exact, ExactificationResult)
    assert exact.verify()
    assert verify_certificate(exact.certificate).valid
    graph = exact.claim_graph()
    assert graph.verify().verified

    wide = recognize(ComplexBall(Dyadic(3, -1), Dyadic(1, -1)), bounds)
    assert isinstance(wide, NumericUnknown)
    assert wide.claim_graph().verify().verified

    tampered = exact.certificate.to_dict()
    witness = tampered["witness"]
    assert isinstance(witness, dict)
    witness["tampered"] = True
    rejected = False
    try:
        VerificationCertificate.from_dict(tampered)
    except (CertificateError, ContentAddressError):
        rejected = True
    assert rejected

    print(f"recognized polynomial: {candidate.minimal_polynomial}")
    print(f"exactification verified: {exact.verify()}")
    print(f"wide enclosure: {type(wide).__name__}")
    print(f"tampered receipt rejected: {rejected}")
    print(f"verified claim nodes: {len(graph.claims)}")
    print(f"exactification certificate: {exact.certificate.certificate_id}")


if __name__ == "__main__":
    main()
