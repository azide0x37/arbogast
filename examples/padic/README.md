# Bounded p-adic proof journeys

These examples exercise Arbogast's finite-precision p-adic layer.  Every
journey prints and checks its typed result boundary; none treats a failed
search, insufficient precision, or an unsupported operation as a negative
mathematical theorem.

| Journey | What it certifies | Boundary it keeps visible |
| --- | --- | --- |
| [`frobenius_slopes`](frobenius_slopes/) | A supplied semilinear Frobenius operator, its finite-precision Newton slopes, and an explicit ordinary projector | Newton multiplicities do not construct a slope submodule |
| [`three_point_good_reduction`](three_point_good_reduction/) | Good, semistable, and stable reduction for one exact tame polynomial cover at \(p=5\) | Other primes and presentations are `Unsupported`, not bad reduction |
| [`special_deformation_datum`](special_deformation_datum/) | Internal logarithmic, Cartier, character, and special-signature identities | A stable marked model alone does not prove geometric Wewers extraction |
| [`lifts_rigid_descent`](lifts_rigid_descent/) | Finite lift enumeration, a trivial arithmetic action, fixed lifts, and witnessed descent in the pinned \(\mathbf F_p\) chart | Nontrivial actions and characteristic-zero/geometric descent remain outside the positive lane |
| [`m23_local_frontier`](m23_local_frontier/) | Reuse of the exact finite M23 Hurwitz certificate as provenance | Finite Nielsen-class completeness does not construct a p-adic model, lift, or descent |

Run a journey from the repository root, for example:

```bash
uv run python examples/padic/frobenius_slopes/run.py
```

See [`docs/padic.md`](../../docs/padic.md) for conventions and the complete
0.5 theorem boundary.
