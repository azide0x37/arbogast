# Prove without search

Discovery and verification are separate programs.

`discover.py` runs breadth-first search in a finite modular state graph. The search answers this
small reachability question:

> Starting at 1 modulo 29, can repeated applications of \(x\mapsto x+3\) and
> \(x\mapsto 2x\) reach 0?

It emits a `VerificationCertificate` containing only the problem, a concrete path, and the
guarantees being requested. It also prints the content address of a `DiscoveryReceipt`, which is
useful provenance but is deliberately not proof evidence.

```bash
uv run python examples/certificates/prove_without_search/discover.py \
  --output /tmp/arbogast-certificate.json
```

`verify.py` does not import `discover.py`, does not contain breadth-first search, and does not
trust a transcript. It parses the versioned certificate, recomputes its content address, checks
every modular transition, and requires the last state to equal the target.

```bash
uv run python examples/certificates/prove_without_search/verify.py \
  /tmp/arbogast-certificate.json
```

Try changing a state in the JSON file while leaving `certificate_id` unchanged. Verification
fails at the integrity boundary. If the ID is also recomputed, transition checking still rejects
an invalid path.

This example is intentionally tiny. A real discovery process may use GAP, a fleet, or heuristic
planning, but the same rule applies: the certificate must contain a finite witness that a smaller
program can check without rerunning or trusting the search.
