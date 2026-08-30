# Recognize and exactify sqrt(2)

This journey encloses the positive root of \(x^2-2\) in an exact dyadic ball. `recognize` returns
a bounded algebraic candidate compatible with that enclosure. `exactify` then performs the
separate exact step: it binds the candidate to the pinned polynomial system and replays the exact
substitution.

The script also exercises an enclosure too wide to isolate the requested candidate and keeps that
branch as `NumericUnknown`. Finally it tampers with the portable receipt and confirms that central
verification rejects it.

Run it from the repository root:

```bash
uv run python examples/numeric/sqrt2_exactification/run.py
```

No external algebra backend is used.
