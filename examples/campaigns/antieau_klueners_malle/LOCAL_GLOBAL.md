# The 0.2 local/global arithmetic campaign

The original [`run.py`](run.py) remains the published 0.1 finite teaching fixture. The 0.2
journey in [`local_global.py`](local_global.py) adds a genuine arithmetic campaign while keeping
that fixture unchanged.

The campaign asks whether −1, 2, and 11 are norms from the pinned quadratic field
\(K=\mathbf Q(t)/(t^2-t-1)\). This is a genuine cyclic local/global norm problem: for each
target \(a\), the complete local gate replays \((5,a)_v\) at the real place and every finite
place dividing \(2\cdot5\cdot a\). Places outside that support are automatically trivial in the
replayed rational Hilbert-symbol formula. Work is ordered by mathematical cost:

```text
canonical global class
        |
        v
cheap local obstruction shards, ordered by place x Kummer generator
        |
        +-- obstruction found --> TARGET_GLOBAL PROVED_IMPOSSIBLE
        |
        v
locally unobstructed candidate
        |
        v
provenance-driven global aiming follow-up
        |
        +-- checked witness ----> TARGET_GLOBAL FOUND
        +-- failed search ------> non-closing TASK_LOCAL/UNKNOWN
```

“Locally unobstructed” is only a routing fact. It is never promoted to “globally soluble.” A
failed worker, timeout, or missing PARI capability is also non-closing. The ledger records the
place and Kummer-generator shards, their deterministic order, the exact evidence that motivated
each follow-up, and the final claim dependencies.

Run both the locally obstructed and locally unobstructed branches with:

```bash
uv run python examples/campaigns/antieau_klueners_malle/local_global.py \
  --output /tmp/arbogast-local-global
```

The three branches are deliberately different: 2 has a certified local obstruction; −1 has
the exact global witness \(t\), whose norm and conjugate are replayed; and 11 passes every local
gate but remains `UNKNOWN` because the declared coefficient bound does not contain its witness.
The run is finite and portable and does not require PARI discovery.
