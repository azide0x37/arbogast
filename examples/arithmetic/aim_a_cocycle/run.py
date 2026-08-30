"""Verify both branches of the reserved ``aim_a_cocycle`` journey."""

from __future__ import annotations

from arbogast.arithmetic import AffineFamily, LeftNullspaceObstruction, aim, unique
from arbogast.claims import ClaimGraph
from arbogast.linalg import DenseMatrix, PrimeField


def main() -> int:
    field = PrimeField(2)
    localization = DenseMatrix(field, ((1, 0), (0, 0)))

    solved = aim(localization, (1, 0))
    obstructed = aim(localization, (1, 1))

    assert isinstance(solved, AffineFamily)
    assert solved.representative == (1, 0)
    assert solved.dimension == 1
    assert solved.contains((1, 0))
    assert solved.contains((1, 1))
    assert not unique(solved)
    assert solved.verify().valid

    assert isinstance(obstructed, LeftNullspaceObstruction)
    assert localization.transpose().matvec(obstructed.witness) == (0, 0)
    assert obstructed.pairing == 1
    assert not unique(obstructed)
    assert obstructed.verify().valid

    # Each computed claim carries its own central VerificationCertificate. The
    # graph verifies those certificates again in theorem-dependency order.
    graph = ClaimGraph(
        (solved.claim(), obstructed.claim()),
        graph_id="example:aim-a-cocycle",
    )
    graph_report = graph.verify()
    assert graph_report.verified

    print(f"solved representative: {solved.representative}")
    print(f"homogeneous basis: {solved.kernel.basis}")
    print(f"unique: {unique(solved)}")
    print(f"obstruction witness: {obstructed.witness}")
    print(f"separator pairing: {obstructed.pairing}")
    print(f"claim graph: {len(graph)} verified nodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
