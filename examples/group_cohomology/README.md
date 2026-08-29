# Cyclic action and \(H^1\)

[`cyclic_action_h1.py`](cyclic_action_h1.py) is Arbogast's finite exact hello world. It builds
the regular concrete cyclic group \(C_5\), the prime field \(\mathbf F_{11}\), and a
three-dimensional representation whose distinguished generator acts by

\[
\rho(g)=\operatorname{diag}(1,3,4).
\]

Both 3 and 4 have order 5 in \(\mathbf F_{11}^{\times}\), so the action is valid and splits
into three one-dimensional weight spaces. The example then constructs the normalized bar
complex, computes

\[
H^1(C_5,M)=Z^1(C_5,M)/B^1(C_5,M),
\]

prints exact cocycle and coboundary dimensions, and replays the independent quotient
certificate.

```bash
uv run python examples/group_cohomology/cyclic_action_h1.py
```

The result is \(H^1=0\). That is not an uninteresting accident: because 5 is invertible in
\(\mathbf F_{11}\), Maschke averaging forces positive-degree cohomology of this finite group to
vanish. Arbogast still computes the cocycle and coboundary spaces explicitly and verifies that
they coincide. In this example they both have dimension 2, while the trivial weight contributes
no crossed homomorphism.

The certificate verifier does not trust those printed dimensions. It reconstructs the finite
multiplication table and left action, rebuilds the normalized-bar differentials, checks
\(d^2=0\), recomputes kernels and images, and checks the quotient projection and section.

To see a nonzero modular \(H^1\), one would work in characteristic dividing the group order; that
is a different example and loses the semisimple weight-space argument used here.
