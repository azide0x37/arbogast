# M23: exact finite theorem, open p-adic frontier

This journey replays the public exact M23 Hurwitz dataset and then asks the
p-adic `reduction_frontier` what that finite result proves locally at \(p=23\).
The answer is `Unsupported`: the dataset is a complete four-point finite
Nielsen-class calculation, but it contains no pinned cover equation, local
model, stable reduction, Wewers datum, lift, or descent witness.  The typed
refusal is not a claim that such a model does not exist.

For contrast, the script separately certifies the beta zero-fibre reduction

\[
z^2-z^3=22z^2(z-1)\quad\text{over }\mathbf F_{23}.
\]

Passing that genuine local fragment to the same frontier returns `Partial`.
The fragment remains independently certified, while four explicit proof
obligations require exact cover/special-fibre binding, stable reduction, a
fixed lift set, and effective descent.  Even a complete mod-\(p\) factorization
is not promoted to a local or global model.

```bash
uv run python examples/padic/m23_local_frontier/run.py
```

The full M23 replay is intentionally reused rather than replaced by copied
counts or a digest-only assertion.
