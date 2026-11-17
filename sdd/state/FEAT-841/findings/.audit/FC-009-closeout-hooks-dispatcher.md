---
id: FC-009
query_id: Q024
type: read
intent: "Read the code-enforced closeout hooks runner (FEAT-703/764 precedent for a deterministic /sdd-done gate)."
executed_at: 2026-11-07T01:23:30Z
duration_ms: 2500
parent_id: null
depth: 0
---

# FC-009 — run_closeout_hooks is the code-enforced gate dispatcher: exit 0/1/2/3, blocking pre_pr hooks abort, agent hooks go pending→record→finalize

## Summary

`packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py` (333 lines) implements `parrot sdd closeout run`. Contract in the module docstring: exit 0 ok · 1 blocking failure · 2 config/usage (fail closed) · 3 agents pending. `run_event()` (168-236) runs hooks from `.parrot/sdd_hooks.toml` in order, short-circuits after a blocking `pre_pr` failure, and marks `agent` hooks as `pending` with a dispatch entry the host must launch; `record()` (238-255) and `finalize()` (257-269) close the loop ("unrecorded pending hooks become failures"). Outcomes persist durably at `<artifact_root>/<FEAT-ID>/<event>.json`. This is the generic "host launches an agent, deterministic code records the outcome and decides the exit code" machinery an escrow verdict could plug into as a blocking `pre_pr` hook — but hooks are repo-config-declared (TOML) and the escrow policy must be enforced regardless of whether a repo declares the hook.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  lines: 1-1
  symbol: null
  excerpt: |
    """Dispatch /sdd-done closeout hooks (FEAT-764). Exit: 0 ok · 1 blocking failure · 2 config/usage · 3 agents pending."""

- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  lines: 34-41
  symbol: `EventOutcome`
  excerpt: |
    class EventOutcome(BaseModel):
        """Persisted result of one event run."""
        event: str
        pending_agents: list[dict[str, Any]] = Field(default_factory=list)
        blocking_failed: bool = False

- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  lines: 168-174
  symbol: `run_event`
  excerpt: |
    def run_event(event: str, ctx: HookContext, cfg: HooksConfig, ctx_path: Path) -> EventOutcome:
        """Run every enabled hook for ``event`` in declaration order.
        Short-circuits after a blocking ``pre_pr`` failure: remaining hooks are

- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  lines: 216-233
  symbol: `run_event`
  excerpt: |
                    status="pending",
                    blocking=hook.blocking,
                    summary="Agent hook pending",
                outcome.pending_agents.append(
        if event == "pre_pr" and result.blocking and result.status in {"fail", "timeout"}:
        _recompute_blocking_failed(outcome)

- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  lines: 257-258
  symbol: `finalize`
  excerpt: |
    def finalize(event: str, feat_id: str, root: Path) -> EventOutcome:
        """Turn unrecorded pending hooks into failures and recompute blocking_failed (AC6)."""

- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  lines: 280-286
  symbol: `exit_code`
  excerpt: |
    def exit_code(outcome: EventOutcome) -> int:
        """Map an outcome to the CLI contract."""
        if outcome.pending_agents and any(result.status == "pending" for result in outcome.results):
            return EXIT_PENDING
        if outcome.event == "pre_pr" and outcome.blocking_failed:
            return EXIT_BLOCKING
        return EXIT_OK

- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  lines: 324-327
  symbol: `main`
  excerpt: |
        except (HooksConfigError, OSError, ValidationError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_USAGE

## Notes

- The pending→record→finalize cycle exists because "agent hooks cannot run in Python": the host (Claude) launches the subagent. An escrow verdict agent launched the same way would still be launched by the same host session that runs /sdd-done — adequate separation from the *worker*, not from the *operator*.
