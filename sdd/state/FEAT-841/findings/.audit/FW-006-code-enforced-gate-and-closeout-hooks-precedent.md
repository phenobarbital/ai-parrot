---
id: FW-006
query_id: Q014
type: wiki_query
intent: "Read decisions/lessons recorded about the ledger and closeout gate (wiki remember entries) to inherit constraints."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 1300
parent_id: null
depth: 1
---

# FW-006 — Two in-tree precedents for "the gate is code, the exit code is the contract": FEAT-703 check_e2e_closeout (takes no --force) and FEAT-764 closeout hooks (events pre_pr/post_pr/on_failure, blocking non-force-able, exit 0/1/2/3)

## Summary

FEAT-703 (`sdd/specs/fixgroup-603217cacd87.spec.md`, approved) promoted the E2E decision table into `scripts/sdd/check_e2e_closeout.py` because "the production path is prose … an agent that misreads, truncates or skips it proceeds to stamp, push, PR, merge and clean up"; design rule: "the gate takes no force parameter, so there is nothing to bypass"; explicit non-goal: "Enforcing any other /sdd-done gate (task state, lint, merge blockers) … remain prose-level — this feature does not set a precedent obligation". FEAT-764 then added a declarative hook registry `.parrot/sdd_hooks.toml` (`closeout_hooks_config.py`: `EVENTS = (pre_pr, post_pr, on_failure)`, `HookKind = command|agent|builtin`, `KNOWN_BUILTINS = {jira.transition, telegram.send, push.send, webhook.post}`, `blocking` only on `pre_pr`) dispatched by `run_closeout_hooks.py` ("Exit: 0 ok · 1 blocking failure · 2 config/usage · 3 agents pending"; `record`/`finalize` turn unrecorded agent hooks into failures). An escrow guard can be (a) a new standalone `check_*.py`-style gate, or (b) a `pre_pr` blocking builtin — both inherit the non-force-able convention; (b) also gives `telegram.send`/`push.send` for notifying.

## Citations

- path: `sdd/specs/fixgroup-603217cacd87.spec.md`
  lines: 1-80
  symbol: `FEAT-703 Goals / Non-Goals`
  wiki_page_id: file:sdd/specs/fixgroup-603217cacd87.spec.md
  score: 1.00
  excerpt: |
    Make the closeout E2E gate a **code invariant**: one script whose exit code decides whether closeout may mutate anything
    Preserve the structural guarantee that `--force` cannot reach the gate: the gate takes no force parameter
    Non-Goal: Enforcing any *other* `/sdd-done` gate (task state, lint, merge blockers). Those remain prose-level
- path: `packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py`
  lines: 1-1
  symbol: `check_e2e_closeout`
  wiki_page_id: file:packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py
  score: 0.02
- path: `packages/ai-parrot/src/parrot/sdd/scripts/closeout_hooks_config.py`
  lines: 1-60
  symbol: `EVENTS`
  wiki_page_id: file:packages/ai-parrot/src/parrot/sdd/scripts/closeout_hooks_config.py
  excerpt: |
    CONFIG_PATH: str = ".parrot/sdd_hooks.toml"
    EVENTS: tuple[str, ...] = ("pre_pr", "post_pr", "on_failure")
    NON_BLOCKING_EVENTS: frozenset[str] = frozenset({"post_pr", "on_failure"})
    KNOWN_BUILTINS: frozenset[str] = frozenset({"jira.transition", "telegram.send", "push.send", "webhook.post"})
    class HookKind(str, Enum): COMMAND = "command"; AGENT = "agent"; BUILTIN = "builtin"
    class HookSpec(BaseModel): name, kind, run, agent, prompt, builtin, with_, blocking: bool = False, timeout_s=600, artifacts, enabled
- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  lines: 1-60
  symbol: `run_event`
  wiki_page_id: file:packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py
  excerpt: |
    """Dispatch /sdd-done closeout hooks (FEAT-764). Exit: 0 ok · 1 blocking failure · 2 config/usage · 3 agents pending."""
    EXIT_OK, EXIT_BLOCKING, EXIT_USAGE, EXIT_PENDING = 0, 1, 2, 3
    class EventOutcome(BaseModel): event, feat_id, results: list[HookResult]
    def run_event(event, ctx, cfg, ctx_path): Run every enabled hook for ``event`` in declaration order.
    def record(event, feat_id, name, status, summary, root): Record a host-dispatched agent hook's outcome.
    def finalize(event, feat_id, root): Turn unrecorded pending hooks into failures and recompute blocking_failed (AC6).
- path: `packages/ai-parrot/src/parrot/sdd/scripts/closeout_builtins.py`
  lines: 1-1
  symbol: `run_builtin`
  excerpt: |
    from parrot.sdd.scripts.closeout_builtins import run_builtin
- path: `sdd/proposals/sdd-done-closeout-hooks.proposal.md`
  lines: 1-60
  symbol: `FEAT-764 §2.2 Constraints`
  wiki_page_id: file:sdd/proposals/sdd-done-closeout-hooks.proposal.md
  excerpt: |
    The hook logic should be **code, not prose**. Following FEAT-703, the dispatcher is a script and the exit code is the contract.
    Both twins (Claude and Codex) must call the same script.
    A blocking hook must never be bypassable by a generic `--force`.

## Notes

`kind = "agent"` hooks are "host-dispatched": the script marks them pending (exit 3) and the host agent must `record` the outcome — that is the exact shape of an LLM verdict agent run from `/sdd-done`, but it would make the worker-adjacent host session the one launching the judge (separation-of-powers question for the synthesis). [cross-lane: type=read, intent=codebase lane Q024/Q025 should cite the agent-hook pending/record flow line ranges.]
