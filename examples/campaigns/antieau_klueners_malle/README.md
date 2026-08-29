# A local Antieau/Klüners--Malle campaign analogue

This example is a deliberately tiny analogue of the research workflow described in the supplied
Antieau interview. It is not a new claim about Antieau, Klüners, or Malle, and it does not query
the [Klüners--Malle database](https://galoisdb.math.uni-paderborn.de/) at runtime.

The arithmetic target is only a finite teaching problem: determine whether 3 is a square modulo
17. An imported prior-work claim says that a toy catalogue has no example, but absence from a
catalogue proves nothing. A deterministic local strategy therefore checks all 17 residues and an
independent verifier checks the resulting completeness witness before the campaign records
`SEARCH_EXHAUSTED`.

That small run exercises the product boundary:

```text
Campaign-owned ClaimGraph  ←  Task  ←  Campaign
          │                    │          ├── recorded plan and attempt states
          │                    └─────── canonical finite scan + capability requirement
          └──────────────── imported statement + automatically bound computed closure
```

Run it with a caller-selected state directory:

```bash
uv run python examples/campaigns/antieau_klueners_malle/run.py \
  --output /tmp/arbogast-campaign
```

The directory contains the campaign snapshot, append-only ledger, content-addressed local
artifacts, and the campaign-owned canonical claim graph. The ledger records the selected plan,
the running and terminal attempt states, a verified candidate, the observation, and its claim
binding. Re-running against the same directory reuses canonical task artifacts while replaying
the same mathematical state.

The fleet `result_ref` is an execution receipt, not proof by itself. The computed claim is bound
instead to a campaign claim-envelope certificate which replays the embedded residue-scan
certificate. The example also invokes the registered residue verifier directly, so neither the
scheduler nor the campaign's closing state is treated as proof. The candidate declares
`examples.modular-residue-table.v1` as its canonicalizer, target-local equivalence scope, and
`checked-residues` quality metric; `best_known_by_metric()` never compares unlike metrics.
The imported catalogue statement motivates the task but is not a mathematical dependency of the
exhaustive residue claim.

This example does not contact a remote scheduler, reconstruct a workstation, use a proprietary
backend, or turn the imported catalogue statement into evidence. Its only mathematical result is
the finite claim that the declared residue domain was exhausted under the stated modulus.
