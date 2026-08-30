# Certified arithmetic journeys

These examples are the portable 0.2 acceptance journeys. Each one is a small, finite problem
whose witnesses can be replayed without trusting how they were discovered.

| Journey | Boundary exercised |
| --- | --- |
| [`aim_a_cocycle`](aim_a_cocycle/) | Solved affine family and literal left-nullspace obstruction, with a verified claim graph |
| [`inflation_restriction`](inflation_restriction/) | Restriction, inflation, corestriction, transgression, and five-term exactness |
| [`q_kummer_selmer`](q_kummer_selmer/) | \(\mathbf Q(\{2,\infty\},2)\), genuine local \(\mu _2\)-cohomology, localization, and Selmer promotion |
| [`quadratic_field`](quadratic_field/) | Pinned field presentation, explicit embedding, norm, and square witness |
| [`nonabelian_twists`](nonabelian_twists/) | Exhaustive finite nonabelian \(H^1\) as a pointed set, without vector-space claims |

Run all five from the repository root:

```bash
uv run python examples/arithmetic/aim_a_cocycle/run.py
uv run python examples/arithmetic/inflation_restriction/run.py
uv run python examples/arithmetic/q_kummer_selmer/run.py
uv run python examples/arithmetic/quadratic_field/run.py
uv run python examples/arithmetic/nonabelian_twists/run.py
```

The examples intentionally separate discovery from proof. A machine with a supported PARI/GP
installation may reproduce discovery receipts, but no GP process is needed to replay these
checked-in finite witnesses.
