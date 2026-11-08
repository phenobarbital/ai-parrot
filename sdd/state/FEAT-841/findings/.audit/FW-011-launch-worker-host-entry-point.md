---
id: FW-011
query_id: Q007
type: wiki_query
intent: "Orient: how a worker is launched headless from the host (launch_cli, tmux, sandbox) — candidate launch point for a monitor."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 700
parent_id: null
depth: 1
---

# FW-011 — `parrot sdd launch worker` (launch_cli.worker → flows.dev_loop.feature_launcher.launch) is the single host entry point: it snapshots the env before importing parrot.flows, provisions the worktree, and starts the sandboxed console (optionally tmux --detach)

## Summary

`parrot/sdd/launch_cli.py:worker` (L27-61) is a click command `(feature, use_tmux, detach, sandbox, allowed_domains, no_upstream, no_gh_token, claude_args)`; `--detach` requires `--tmux`; it snapshots `base_env = dict(os.environ)` **before** importing `parrot.flows.dev_loop.feature_launcher` ("that import lets navconfig load the project's settings .env … none of it may reach the worker"), then calls `feature_launcher.launch(feature, tmux, detach, sandbox, allowed_domains, no_upstream, claude_args, base_env, gh_token)`. The module docstring: "`parrot sdd launch worker|brief|fix` — the three interactive entry points of an SDD cycle (FEAT-633, C30 item 5)". TASK-5123 wired the notification env (`PARROT_SDD_NOTIFY_*`) and Stop hook here. A `--escrow[=policy]` flag belongs on this command (host side, deterministic), and a monitor process could be launched by the same launcher (second tmux window) or by the Stop hook that already fires on worker completion (FW-005).

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`
  lines: 27-61
  symbol: `worker`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/sdd/launch_cli.py#worker
  score: 1.00
  excerpt: |
    def worker(ctx, feature, use_tmux, detach, sandbox, allowed_domains, no_upstream, no_gh_token, claude_args) -> None:
        if detach and not use_tmux: raise click.UsageError("--detach requires --tmux")
        base_env = dict(os.environ)   # snapshot BEFORE importing parrot.flows (navconfig loads .env)
        from parrot.flows.dev_loop import feature_launcher
        code = feature_launcher.launch(feature, tmux=use_tmux, detach=detach, sandbox=sandbox,
                                       allowed_domains=allowed_domains, no_upstream=no_upstream,
                                       claude_args=claude_args, base_env=base_env, gh_token=not no_gh_token)
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`
  lines: 1-1
  symbol: `launch`
- path: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`
  lines: 1-10
  symbol: `module docstring`
  wiki_page_id: file:packages/ai-parrot/src/parrot/sdd/launch_cli.py
  score: 0.74
- path: `sdd/tasks/completed/TASK-5123-tmux-notification-launch-wiring.md`
  lines: 1-1
  symbol: `TASK-5123 Tmux notification environment and Stop-hook wiring`
  wiki_page_id: file:sdd/tasks/completed/TASK-5123-tmux-notification-launch-wiring.md
  score: 0.09

## Notes

[cross-lane: type=read, intent=codebase lane Q038 should cite where `feature_launcher.launch` builds the claude command/sandbox and where PARROT_SDD_NOTIFY_* are exported, as the hook point for an escrow flag.]
