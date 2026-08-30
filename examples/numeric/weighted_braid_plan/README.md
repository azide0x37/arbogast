# Weighted exact braid planning

This journey constructs a small exact finite braid action with two competing routes. The chosen
route uses more edges but has lower total declared cost. `weighted_braid_plan` returns the exact
word and vertex path and replays them to the requested target.

A separate continuation request deliberately omits its required tube witness and remains
`NumericUnknown`. The exact finite-action word does not authorize a numerical endpoint, and even a
validated endpoint would not become the exact target merely because the words agree.

Run it from the repository root:

```bash
uv run python examples/numeric/weighted_braid_plan/run.py
```

No external algebra backend is used, and the existing `arbogast.hurwitz.weighted_braid_path`
function is not changed.
