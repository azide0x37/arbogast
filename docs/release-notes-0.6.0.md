# Arbogast 0.6.0 release notes

Arbogast 0.6.0 adds certified campaign readiness to the immutable finite-exact, arithmetic,
deformation, validated-numeric, and bounded p-adic layers from 0.1 through 0.5.

## The zeroth theorem

Before a campaign dispatches work, it can now prove a finite environmental proposition:

> A named environment snapshot satisfies a named readiness profile for this campaign and this
> canonical plan.

The readiness subject binds the Python interpreter, Arbogast distribution or source identity,
project lock, exact campaign and task roster, executable operation registry, verifier registry,
required capabilities, executor semantics, and artifact custody checks. Changing any bound
identity creates a new subject. It does not falsify the historical certificate, and the old
certificate does not authorize the new runtime.

For every plan strategy that verifies reduced results, the operation contract declares the exact
central certificate verifiers that may close a target. Readiness derives `V` from those contracts;
explicit verifier arguments can add requirements but cannot omit or substitute for a derived
closure verifier. Harvest also rejects a certificate outside the active profile's certified
required `V` roster.

Readiness is an execution precondition. It proves neither the campaign's mathematical target nor
that discovery will succeed.

## Proof-bearing readiness results

Readiness uses five result states with deliberately different theorem boundaries:

- `CertifiedReady` proves that every required obligation in the complete profile is satisfied;
- `CertifiedBlocked` proves at least one exact required failure for the displayed conjunction;
- `Partial` preserves certified fragments while naming unfinished or indeterminate obligations;
- `Unknown` records an inconclusive probe, crash, timeout, or unavailable evidence without a
  negative theorem; and
- `Unsupported` certifies only that the requested probe or profile lies outside the implemented
  software surface.

Each substantial result exposes `verify()`, `.certificate`, `.claim()`, and `.claim_graph()`.
The authoritative bootstrap bundle contains `environment-snapshot.json`,
`readiness-profile.json`, `readiness-certificate.json`, `readiness-claim.json`, and a diagnostic
`bootstrap-report.json` projection. The strict readiness receipt is nested inside the existing
central `VerificationCertificate`; Arbogast does not introduce a parallel evidence layer.

## Domain-bound claims without legacy drift

Claim v2 records explicitly bind one of five domains: `MATHEMATICAL`, `ENVIRONMENTAL`, `SOFTWARE`,
`EXECUTION`, or `DATA`. The domain participates in the v2 claim boundary and therefore cannot be
changed without invalidating its certificate.

Claim v1 remains implicitly mathematical and is decoded, serialized, hashed, and verified exactly
as published. Every existing caller that omits `domain=` stays on v1. Exporters display the domain;
non-mathematical claims are never emitted as Lean axioms or paper-style mathematical
propositions.

Environmental readiness claims remain independent nodes in the campaign graph. Initial v0.6
dispatch provenance binds their identities without placing them in the logical `why` boundary of
a portable mathematical result. Typed heterogeneous graph relations remain a future schema
migration.

## Runtime-only activation and safe dispatch

Recording an environmental claim preserves history. Activating it separately grants authority to
the current runtime after live identity checks. Campaign persistence never serializes that active
authority, so loading a campaign always requires an explicit fresh activation.

For byte-for-byte and behavioral compatibility with 0.1--0.5 callers, the existing `Campaign`
constructor retains `strict_readiness=False`. New and scaffolded campaigns opt in explicitly with
`strict_readiness=True`; only that mode makes readiness a mandatory dispatch gate in 0.6.

Dispatch checks the exact certified plan and task roster before it starts a ledger task or records
an attempt, observation, candidate, or mathematical claim. Missing or stale readiness raises a
typed `CampaignReadinessError`. Operational refusal is not represented as mathematical failure.

Executable-operation and verifier readiness manifests bind implementation identities, not only
registry names or Python object addresses. Persisted JSON never supplies module paths, entry
points, pickles, source text, or another executable representation. Campaign-specific operations
and verifiers are injected by an explicitly selected campaign runtime.

## Doctor is evidence, not the theorem

`arbogast doctor --mode {campaign,core,replay} --json` provides a bounded environment-preflight
projection. It reports exact required, optional, and informational checks; probe exceptions remain
`UNKNOWN`; optional backend absence does not block a portable replay profile. The command never
loads arbitrary campaign callables and never reports a mathematical outcome.

Doctor output is useful evidence and troubleshooting context, but it is not the authoritative
readiness theorem. Custom campaigns construct live registries in their own runtime and call
`certify_campaign_readiness` with the exact environment, profile, campaign, plan, executor, and
artifact store.

## Cold-start surfaces and blank campaign template

The release adds a thin root `AGENTS.md`, the canonical `docs/agent-bootstrap.md` guide, a
paste-ready `prompts/campaign-bootstrap.md`, and a copyable
`examples/campaigns/_template/` project pinned to v0.6.0. The template registers one deterministic
custom operation and an independent verifier, certifies readiness, persists authoritative
campaign and ledger state, and exercises positive, blocked, malformed-certificate, and
fresh-process replay paths.

The operational guardrail is literal:

> A stale Python interpreter or missing optional backend is a blocked capability, not permission
> to reimplement Arbogast and not a mathematical result.

Arbogast supports Python 3.11 through 3.14. The public campaign quickstart uses Python 3.13 as a
conservative default for optional binary and solver compatibility; an explicit backend requirement
may justify another supported interpreter.

## Release integrity and compatibility

The newly frozen 0.5.0 fixture is re-derived under CPython 3.11 from the exact published tag. It
binds the source commit, GitHub release identity, all three public asset hashes and sizes, API and
CLI contracts, every published schema document, and representative central certificate IDs.

The release checker and artifact qualifier require the readiness package, bootstrap documents,
prompt, campaign template, template tests, and current release notes in the appropriate wheel,
sdist, and Git source archive surfaces. The template tests are invoked explicitly because root
pytest intentionally discovers only `tests/`.

CI pins uv and the direct PEP 517 build backend to reduce tool drift, then preserves and qualifies
one exact candidate trio. That is an artifact-custody guarantee, not a claim that later rebuilds
are bit-for-bit reproducible: publication approval and public verification bind the selected
wheel, sdist, and Git source archive by their actual SHA-256 digests and sizes.

## Explicit deferrals

Arbogast 0.6 does not infer arbitrary custom callables from serialized campaign data, prove
machine or backend availability from passive PATH discovery, persist runtime activation across
hosts, treat local solubility as global solubility, or make readiness a logical hypothesis of a
portable mathematical theorem. Automatic provisioning of external algebra systems, remote
licenses, schedulers, cloud workers, and the separate arbogast.eigenslur.com website remain
outside this package release.

Lease-scoped readiness is a per-lease pre-execution gate, not a transaction across an entire
multi-shard dispatch. A shard that completed before later environmental drift is not rolled back,
and Arbogast cannot undo external side effects performed by an operation.

Every passing worker-lease refresh now produces a content-addressed operational
`DispatchReadinessReceipt` before operation execution. After the campaign refresh, the scheduler
rechecks the exact worker/backend declarations, dispatch identity, lease custody, and current time,
and performs a lease/profile-bound artifact write/read probe. The receipt retains the probe payload
and `ArtifactRef`, explicit completed write/read outcomes, and exact returned canonical bytes for
replay, without binding them as mathematical or discovery evidence. The full readiness certificate
and canonical environmental claim are embedded so offline reconstruction independently replays the
theorem and exact E,R,C,P,G,V,X,A/task boundary rather than accepting authority IDs alone. Cache
rechecks, checkpoint validation, and resume-runner selection all precede the final launch barrier;
the operation call follows it immediately.
The attempt ledger retains every receipt; `Campaign.status()` exposes all concurrent current lease
authorizations as well as historical terminal or expired provenance. These receipts create no
mathematical observation or claim edge and are not added to the five release-level bootstrap
artifacts.

The gate does not prove dynamic scratch availability, license reachability, or network reachability
unless a certified operation-specific probe represents that condition. Retry and resume lineage
remains authoritative in fleet lease, attempt, checkpoint, and interruption records. The final
launch boundary is per lease and is not a transaction across sibling shards or external operation
side effects.
