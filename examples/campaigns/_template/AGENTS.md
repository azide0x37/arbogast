# Campaign agent instructions

This directory is a separate `USE_RELEASE` campaign. It depends on the exact Arbogast release
pinned in `pyproject.toml`; it is not an Arbogast core checkout.

Before editing campaign code or spawning subagents:

1. read `README.md` and the pinned
   [Arbogast bootstrap guide](https://github.com/azide0x37/arbogast/blob/v0.6.0/docs/agent-bootstrap.md);
2. provision Python with `uv`, lock the direct release dependency, and run the campaign-mode
   diagnostic, preserving it as `doctor-report.json`;
3. construct the canonical plan and certify readiness with the live operation registry,
   verifier registry, executor, and artifact store;
4. preserve all five bootstrap artifacts; and
5. run the four focused tests in `tests/` before expensive work.

A stale Python interpreter or missing optional backend is a blocked capability, not permission
to reimplement Arbogast and not a mathematical result.

## Local guardrails

- Do not edit, vendor, or reimplement Arbogast core from this campaign.
- Keep executable registration in `src/campaign_name/runtime.py`; serialized state contains no
  callables.
- Keep discovery in `operations.py` and independent replay in `verifiers.py`.
- Preserve the sole authoritative campaign ledger and content-addressed artifact custody.
- Freeze operation names, verifier names, schemas, acceptance tests, and file ownership before
  parallel work.
- Continuation creates a successor task or attempt with typed checkpoint custody. It does not
  rewrite the parent task, attempt, receipt, or certificate.
- Missing capability, process failure, timeout, preemption, and exhausted budget do not prove
  mathematical nonexistence.
- Never promote `TASK_LOCAL` evidence to `TARGET_GLOBAL` without a replay-verified complete
  coverage argument.
- Recording a readiness claim does not activate it. Every new runtime must revalidate or
  recertify before dispatch.

Replace the valid placeholder package name `campaign_name` consistently when starting a real
campaign. Do not leave a second ledger writer or implicit runtime entry point behind.
