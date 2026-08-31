# Arbogast campaign bootstrap gate

Before mathematical discovery, campaign implementation, or subagent dispatch, complete the
Arbogast bootstrap gate.

1. Classify this job as `USE_RELEASE`, `CONTRIBUTE_CORE`, or `REPLAY`. Default to `USE_RELEASE`
   unless the user explicitly asks to modify Arbogast.

2. Read the applicable `AGENTS.md` and the pinned
   [AI agent bootstrap guide](https://github.com/azide0x37/arbogast/blob/v0.6.0/docs/agent-bootstrap.md).

3. Do not reimplement Arbogast because ambient Python is stale, the package is not installed, or
   an optional backend is unavailable.

4. Use `uv` to provision the declared Python environment. Pin an exact Arbogast release or source
   commit and preserve the resolved distribution, commit, interpreter, `uv`, and lock identities.

5. Run the diagnostic preflight and preserve its complete projection:

   ```bash
   uv run arbogast doctor --mode MODE --json > doctor-report.json
   ```

   Replace `MODE` with lower-case `campaign`, `core`, or `replay`.
   Preserve `doctor-report.json` separately. It is environment evidence, not the readiness
   certificate, the later `bootstrap-report.json` projection, or a mathematical result.

6. Construct the initial canonical campaign plan and an exact readiness profile. Resolve every
   required blocker before dispatch. Record optional missing capabilities as blocked work.

7. In a custom campaign package, explicitly register every operation and verifier in the trusted
   runtime. Serialized campaign state contains no executable callables.

8. Capture the environment, certify readiness against the exact campaign, plan, registries,
   executor, artifact store, and capability requirements, then independently replay the
   certificate. Preserve:

   - `environment-snapshot.json`;
   - `readiness-profile.json`;
   - `readiness-certificate.json`;
   - `readiness-claim.json`; and
   - `bootstrap-report.json`.

9. Record the environmental claim and activate it separately. Loading a saved campaign never
   restores runtime authorization. Dispatch only covered tasks under matching live identities.

10. Before parallel work, freeze shared schemas, operation and verifier names, implementation
    identities, file ownership, acceptance tests, checkpoint custody, and the sole authoritative
    ledger writer.

11. Preserve the distinction between operational state and mathematical outcome. `FAILED`,
    `PREEMPTED`, `BUDGET_EXHAUSTED`, missing capability, verifier absence, and solver timeout do
    not prove nonexistence. Never upgrade `TASK_LOCAL` evidence to `TARGET_GLOBAL`.

12. Do not begin expensive work until a small positive fixture, applicable checkpoint replay,
    malformed-certificate rejection, correct blocked/timeout semantics, and fresh-process
    verification all pass.

Report the selected mode, exact environment identity, diagnostic result, readiness result and
certificate ID, required and optional blockers, covered plan and task roster, and next command
before continuing.
