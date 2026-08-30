# A pinned quadratic field

This journey uses the presentation

\[
K=\mathbf Q[t]/(t^2-t-1)
\]

without replacing it by a reduced polynomial. The symbol `t` is display-only; the defining
polynomial and pinned basis, not the generator name, determine field identity. Exact power-basis
arithmetic verifies

\[
\operatorname N_{K/\mathbf Q}(t)=-1,
\qquad (2t-1)^2=5.
\]

It also demonstrates an explicit field embedding and portable replay of the norm and square
witnesses. An optional operation-specific PARI lane discovers the same relative norm and then
fresh-replays its pinned central certificate. The discovery receipt records the PARI version;
neither a PARI handle nor GP source enters the mathematical object.

Run the portable lane with:

```bash
uv run python examples/arithmetic/quadratic_field/run.py
```

With supported PARI/GP installed, exercise the closed backend boundary as well:

```bash
uv run python examples/arithmetic/quadratic_field/run.py --with-pari
```
