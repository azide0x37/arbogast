# Frobenius slopes and an ordinary projector

This journey works over \(\mathbf Q_3/3^2\) on a rank-two module.  It supplies
arithmetic Frobenius with matrix

\[
\begin{pmatrix}1&0\\0&3\end{pmatrix},
\]

so exact finite-precision Newton replay gives slopes \(0\) and \(1\), each with
multiplicity one.  The slope computation is `Certified`, but it deliberately
does not invent projectors from a Newton polygon.

The script therefore checks both ordinary-part branches:

- without a saturated projector, `ordinary_part` is `Unknown` with reason
  `missing-saturated-projector`;
- with the explicit idempotent \(\operatorname{diag}(1,0)\), the ordinary
  direct summand is `Certified` and its receipt, claim, and claim graph replay.

Run it from the repository root:

```bash
uv run python examples/padic/frobenius_slopes/run.py
```

The convention is pinned in the operator.  Arbogast does not silently convert
between arithmetic and geometric Frobenius.
