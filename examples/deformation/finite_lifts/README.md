# Finite lifts and fixed points

This portable journey uses the dual-number extension

\[
\mathbf F_3[\varepsilon]/(\varepsilon^2)\longrightarrow \mathbf F_3
\]

and a pinned two-variable correction equation. It checks all of the result boundaries separately:

1. a consistent equation with a one-dimensional affine lift family;
2. an inconsistent equation with a literal left-nullspace separator and nonzero obstruction
   class;
3. a different consistent equation whose solution is unique;
4. two gauge-inequivalent lifts witnessing non-uniqueness; and
5. a fixed lift for an affine endomorphism whose linear part is killed by an exact contraction
   exponent.

Existence, uniqueness, and fixedness are distinct certificates. No search budget, apparent
stabilization, or external backend is involved.

Run it with:

```bash
uv run python examples/deformation/finite_lifts/run.py
```

The example writes no files.
