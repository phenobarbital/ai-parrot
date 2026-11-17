---
id: FC-010
query_id: Q025
type: read
intent: "Read the closeout hooks config/builtins: how a new built-in gate is registered and how fail-open/fail-closed is decided."
executed_at: 2026-11-07T01:23:30Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FC-010 — Builtins are a plain name→function dict; four exist (jira.transition, telegram.send, push.send, webhook.post); unknown builtin → fail result

## Summary

`packages/ai-parrot/src/parrot/sdd/scripts/closeout_builtins.py` (317 lines) registers builtin hook actions in `BUILTINS: dict[str, BuiltinFn]` (300-305). `run_builtin()` (308-314) looks the name up and converts any exception into a `fail` HookResult ("never a crash"); an unknown name is a `fail`, so a misconfigured builtin fails closed when the hook is `blocking`. `telegram.send` and `push.send` (ntfy/gotify) already give /sdd-done a one-way notification channel to a human, usable to announce "AWAITING_VERDICT" or "ESCALATE_HITL" without new transport code. Adding an `escrow.verify` builtin is a one-line dict entry plus a function with signature `(HookSpec, HookContext, Path) -> HookResult`.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/closeout_builtins.py`
  lines: 1-1
  symbol: null
  excerpt: |
    """Builtin closeout-hook actions for /sdd-done (FEAT-764)."""

- path: `packages/ai-parrot/src/parrot/sdd/scripts/closeout_builtins.py`
  lines: 17-19
  symbol: `BuiltinFn`
  excerpt: |
    from parrot.sdd.scripts.closeout_hooks_config import Defaulting, HookContext, HookKind, HookResult, HookSpec, PUSH_PROVIDERS
    BuiltinFn = Callable[[HookSpec, HookContext, Path], HookResult]

- path: `packages/ai-parrot/src/parrot/sdd/scripts/closeout_builtins.py`
  lines: 166-166
  symbol: `telegram_send`
  excerpt: |
    def telegram_send(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:

- path: `packages/ai-parrot/src/parrot/sdd/scripts/closeout_builtins.py`
  lines: 252-252
  symbol: `push_send`
  excerpt: |
    def push_send(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:

- path: `packages/ai-parrot/src/parrot/sdd/scripts/closeout_builtins.py`
  lines: 300-314
  symbol: `BUILTINS`
  excerpt: |
    BUILTINS: dict[str, BuiltinFn] = {
        "jira.transition": jira_transition,
        "telegram.send": telegram_send,
        "push.send": push_send,
        "webhook.post": webhook_post,
    }
    def run_builtin(hook: HookSpec, ctx: HookContext, artifact_dir: Path) -> HookResult:
        """Run ``hook.builtin``; any unexpected exception becomes a ``fail`` result, never a crash."""
            fn = BUILTINS.get(hook.builtin)
                return _result(hook, "fail", f"Unknown builtin: {hook.builtin}", started)

## Notes

- `HookContext` fields (from FC-002's `write_hook_context`): feat_id, spec_path, branch, base_branch, worktree, pr_url, merge_sha, test_report_md, e2e_gate, abort_reason, dry_run — no head SHA field today; an escrow builtin would resolve HEAD from `worktree` itself.
