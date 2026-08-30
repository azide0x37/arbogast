# Internal special deformation data

This journey certifies a small synthetic rank-one tame datum over
\(\mathbf F_5(x)\).  The logarithmic unit \(u=x(x-1)\) proves the differential
is \(du/u\), hence Cartier-fixed in the implemented logarithmic slice.  The
the separate normalized signature component has exact formal triples

\[
(m,h)_0=(2,1),\qquad (m,h)_1=(2,1),\qquad
(m,h)_\infty=(1,0).
\]

The resulting `Certified` receipt covers only
`componentwise-rank-one-tame-formal-identities`: logarithmic and Cartier
identities, the tame character, and the numerical definition of a special
signature.  It explicitly records
`differential_signature_relation_claimed == False` and the scope
`componentwise-formal-identities-no-divisor-or-point-binding`.  In particular,
the labels are not bound to points or the divisor of the displayed
differential.

The script separately computes the exact stable model from the good-reduction
journey and calls `deformation_datum(stable)`.  That operation returns `Unknown`
without a geometric extraction witness.  Even an ID-bound synthetic witness
would be `Unsupported` in the 0.5 stable profile, which contains marked
components but no group action or extracted differential.  Internal
consistency is not promoted to geometric origin.

```bash
uv run python examples/padic/special_deformation_datum/run.py
```
