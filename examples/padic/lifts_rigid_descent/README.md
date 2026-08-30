# Finite lifts, fixed classes, and rigid descent

This journey starts with the certified internal rank-one datum from the
special-deformation example.  It then exhausts the roots of the pinned finite
chart

\[
T^2-1=0\quad\text{over }\mathbf F_5
\]

and evaluates two labeled model coordinates at every root.  `lift_set`
certifies exactly those two roots and deduplicates only literal labeled models;
it does not claim global Wewers lift completeness.

The positive 0.5 arithmetic-action lane is narrower still: the example binds
the resulting finite set to a completely certified **trivial** Galois quotient
and supplies one identity model-coordinate permutation for every lift.  The
same set action without those exact model maps is `Unknown` with reason
`unverified-arithmetic-model-transport`; a nontrivial complete quotient is
`Unsupported`.  Transport labels are identifiers, never evidence.

`fixed_lifts` exhausts the fixed subset while retaining
`descent_claimed == False`.  A fixed isomorphism class is not an effective
descent theorem.

The final step supplies the exact rigidity and descent witnesses required by
`effective_descent`, and checks the resulting `Certified` model in the pinned
\(\mathbf F_p\) labeled-chart category.  The result explicitly makes no
characteristic-zero, number-field, or geometric-cover descent claim.  The
script also calls the same operations without their witnesses, demonstrating
typed non-conclusions rather than treating missing data as failure of
existence.

```bash
uv run python examples/padic/lifts_rigid_descent/run.py
```
