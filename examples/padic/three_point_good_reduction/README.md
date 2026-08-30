# A narrow tame good-reduction lane

The exact polynomial

\[
\beta(z)=\frac{27}{4}z^2-\frac{27}{4}z^3
\]

has normalized branch fibres above \(0,1,\infty\) with ramification profiles
\((2,1),(2,1),(3)\).  The script supplies complete rational factorizations of
those fibres and of \(\beta'\); constructing the cover therefore replays its
generic degree and genus-zero Riemann--Hurwitz equality.

At \(p=5\), the public operations certify the displayed good model and the
one-component marked semistable/stable models.  The script checks the reduced
polynomial, marked ramification points, absence of nodes, stability indices,
receipts, claims, and claim graphs.

At \(p=2\), even this exact cover lies outside the sole automatic geometry
profile.  Both `good_reduction` and `semistable_reduction` return `Unsupported`
with reason `outside-beta-p5-certified-slice`.  Neither result says that the
cover has bad or potentially bad reduction.  `Unknown` is reserved for a
sufficient-check failure inside the supported beta-at-five profile.

```bash
uv run python examples/padic/three_point_good_reduction/run.py
```
