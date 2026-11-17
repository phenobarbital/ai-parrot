---
id: F023
query_id: Q038
type: read
intent: "Read the launch CLI: how `parrot sdd launch worker` builds the worker command/sandbox — where a monitor launch would hook in."
executed_at: 2026-11-07T01:26:34Z
duration_ms: 1000
parent_id: null
depth: 1
merged_from: [FC-023, FW-011]
---

# F023 — parrot sdd launch worker|brief|fix is a thin click group over parrot.flows.dev_loop.feature_launcher; a launch-escrow subcommand would slot in the same way

## Summary

`packages/ai-parrot/src/parrot/sdd/launch_cli.py` (91 lines, FEAT-633 C30) defines the click group `launch` with `worker FEATURE [--tmux] [--detach] [--sandbox required|preferred|off|legacy] [--sandbox-allow-domain HOST]* [--no-upstream] [--no-gh-token] [claude_args...]`, which snapshots `os.environ` **before** importing `parrot.flows` (so navconfig secrets never reach the worker) and calls `feature_launcher.launch(feature, tmux=, detach=, sandbox=, allowed_domains=, no_upstream=, claude_args=, base_env=, gh_token=)`. `brief` and `fix` exec an interactive Claude session in the primary checkout with a slash command as first prompt via `feature_launcher.launch_session(prompt, cwd, base_env)`. There is no option to attach a monitor or to pass a flag like `--escrow` into the worker today; the launcher is the host-side point that already knows the feature id, worktree and launch_id (FC-004's `configure_notification` runs here), so it is the natural place to (a) record `escrow.enabled` and (b) start a sibling verdict session.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`
  lines: 1-1
  symbol: null
  excerpt: |
    """`parrot sdd launch worker|brief|fix` — the three interactive entry points of an SDD cycle (FEAT-633, C30 item 5)."""

- path: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`
  lines: 17-25
  symbol: `worker`
  excerpt: |
    @launch.command("worker", context_settings={"ignore_unknown_options": True})
    @click.argument("feature")
    @click.option("--tmux", "use_tmux", is_flag=True, default=False)
    @click.option("--detach", is_flag=True, default=False)
    @click.option("--sandbox", type=click.Choice(["required", "preferred", "off", "legacy"]), default=None)
    @click.option("--sandbox-allow-domain", "allowed_domains", multiple=True, metavar="HOST")
    @click.option("--no-upstream", is_flag=True, default=False)
    @click.option("--no-gh-token", is_flag=True, default=False, help="Do not resolve GH_TOKEN from the host's gh.")

- path: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`
  lines: 41-57
  symbol: `worker`
  excerpt: |
        base_env = dict(os.environ)
        from parrot.flows.dev_loop import feature_launcher  # noqa: PLC0415
        try:
            code = feature_launcher.launch(
                feature,
                tmux=use_tmux,
                detach=detach,
                sandbox=sandbox,
                allowed_domains=allowed_domains,
                no_upstream=no_upstream,
                claude_args=claude_args,
                base_env=base_env,
                gh_token=not no_gh_token,

- path: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`
  lines: 64-74
  symbol: `_session`
  excerpt: |
    def _session(ctx: click.Context, prompt_words: list[str]) -> None:
        """Exec an interactive Claude session in the primary checkout with the slash command as first prompt."""
            cwd = feature_launcher.resolve_primary_checkout(feature_launcher._invocation_dir())
        ctx.exit(feature_launcher.launch_session(" ".join(prompt_words), cwd=cwd, base_env=base_env))

## Notes

- [cross-lane: type=wiki_page, intent=parrot.flows.dev_loop.feature_launcher.launch — where configure_notification / sandbox / Stop hook are wired]


---

<!-- merged from FW-011 -->

# F023 — `parrot sdd launch worker` (launch_cli.worker → flows.dev_loop.feature_launcher.launch) is the single host entry point: it snapshots the env before importing parrot.flows, provisions the worktree, and starts the sandboxed console (optionally tmux --detach)

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
