# Inflation--restriction

This example constructs the nonsplit extension

\[
1\longrightarrow C_2\longrightarrow C_4\longrightarrow C_2\longrightarrow 1
\]

with every group map explicitly enumerated. It builds the certified induced maps through degrees
0--2 and verifies the five-term sequence

\[
0\to H^1(C_2,M^{C_2})\to H^1(C_4,M)\to H^1(C_2,M)^{C_2}
\to H^2(C_2,M^{C_2})\to H^2(C_4,M).
\]

The exactness certificate independently recomputes every interior image and kernel, checks zero
composites, and checks transgression. The historical `restrict` and `inflate` convenience
wrappers remain available with their 0.1 signatures; this journey uses the new first-class map
objects.

Run it with:

```bash
uv run python examples/arithmetic/inflation_restriction/run.py
```

No external backend is required.
