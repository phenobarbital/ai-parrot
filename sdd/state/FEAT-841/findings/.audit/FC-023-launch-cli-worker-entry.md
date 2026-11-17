---
id: FC-023
query_id: Q038
type: read
intent: "Read the launch CLI: how `parrot sdd launch worker` builds the worker command/sandbox — where a monitor launch would hook in."
executed_at: 2026-11-07T01:26:34Z
duration_ms: 1000
parent_id: null
depth: 0
---

# FC-023 — parrot sdd launch worker|brief|fix is a thin click group over parrot.flows.dev_loop.feature_launcher; a launch-escrow subcommand would slot in the same way

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
