---
id: FC-008
query_id: Q024
type: read
intent: "Read the Claude Code settings for this repo: which hooks are registered and whether telemetry env vars are set."
executed_at: 2026-10-30T22:52:00Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-008 — One hook registered, no telemetry env var set — but parrot already owns a Claude Code hook installer and hook runtime

## Summary

`.claude/settings.json` registers **exactly one hook**: a `PreToolUse` entry with matcher
`Grep|Glob|Read|Bash` running `.venv/bin/wikitoolkit claude-hook`. The only `env` key is
`CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`. **`CLAUDE_CODE_ENABLE_TELEMETRY` is not set
anywhere**, and no OTLP exporter variables exist — so the source's statement that Claude
Code usage "leaves through the Claude Code OpenTelemetry plugin straight to Grafana" is
**not true of this repository as configured**; nothing is being exported today. Four shell
hooks exist as files under `.claude/hooks/` (`sdd-worker-format.sh`,
`dangerous-actions-blocker.sh`, `e2e-teardown.sh`, `e2e-exploration-write-guard.sh`) but
none is registered in the shared `settings.json`, and none concerns usage.

The cost of the source's "Lane 2" is lower than it assumes, because parrot already **owns
the hook plumbing**: `knowledge/wiki/claude_code/installer.py` (56 KB) merges a hook entry
into `.claude/settings.json` idempotently — it upgrades an existing entry in place when the
matcher or command changed and strips its own duplicates while preserving foreign hooks —
and `knowledge/wiki/claude_code/hook.py` is a working stdin-JSON hook runtime shipped as
`wikitoolkit claude-hook`. Both are currently **hardcoded to `PreToolUse`**
(`hook.py:182` rejects any other `hook_event_name`; `installer.py:191-249` only ever
touches `hooks.PreToolUse`), so adding `SessionStart`/`SubagentStop` is a generalization of
existing, tested code rather than new infrastructure.

## Citations

- path: `.claude/settings.json`
  lines: n/a
  symbol: `hooks + env`
  excerpt: |
    top-level keys: enabledPlugins, env, extraKnownMarketplaces, hooks
    hooks: {"PreToolUse": 1 entry}
      PreToolUse | matcher = "Grep|Glob|Read|Bash"
                 | command = "<repo>/.venv/bin/wikitoolkit claude-hook"
    env: {"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1"}
    -- no CLAUDE_CODE_ENABLE_TELEMETRY, no OTEL_* keys

- path: `.claude/hooks/`
  lines: n/a
  symbol: `hook script inventory`
  excerpt: |
    sdd-worker-format.sh
    dangerous-actions-blocker.sh
    e2e-teardown.sh
    e2e-exploration-write-guard.sh
    (none registered in .claude/settings.json; none usage-related)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/__init__.py`
  lines: 1-12
  symbol: `module docstring`
  excerpt: |
    """Claude Code integration for the LLM Wiki (FEAT-260 follow-up).

    Installs the repository knowledge graph as coding-assistant
    infrastructure, graphify-style:

    - ``parrot claude install`` — writes a managed CLAUDE.md section, a
      PreToolUse nudge hook, the ``/parrotwiki`` slash command, and an
      optional git ``post-commit`` auto-upsert hook;
    - ``wikitoolkit claude-hook`` — the PreToolUse hook runtime

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py`
  lines: 182
  symbol: `hook event guard`
  excerpt: |
    if payload.get("hook_event_name") not in (None, "PreToolUse"):

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`
  lines: 191-204
  symbol: `_merge_hook`
  excerpt: |
    """Merge the PreToolUse nudge hook into .claude/settings.json."""
    path = root / ".claude" / "settings.json"
    hooks = settings.get("hooks")
    if hooks is None:
        hooks = settings["hooks"] = {}
    pre = hooks.get("PreToolUse")
    if pre is None:
        pre = hooks["PreToolUse"] = []
    elif not isinstance(pre, list):
        raise RuntimeError(f"{path}: 'hooks.PreToolUse' is not a list")

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`
  lines: 211-233
  symbol: `_merge_hook` (idempotent upgrade)
  excerpt: |
    # Upgrade an older install in place when the matcher or command
    if existing.get("matcher") != assets.HOOK_MATCHER:
        existing["matcher"] = assets.HOOK_MATCHER
    ...
    foreign = [h for h in dup.get("hooks", []) if not _is_our_command(h.get("command"))]

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/`
  lines: n/a
  symbol: `package inventory`
  excerpt: |
    __init__.py  assets.py (18.4K)  bookstore.py  bookstore_assets.py
    cli.py (9.2K)  compaction.py (13.4K)  hook.py (9.5K)  installer.py (56.4K)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/codex/`
  lines: n/a
  symbol: `package inventory`
  excerpt: |
    __init__.py  assets.py (6.4K)  bookstore.py  bookstore_assets.py
    cli.py (6.5K)  installer.py (17.6K)
    """Codex integration for the repository LLM Wiki."""
    exports: install_codex_integration, integration_status, uninstall_codex_integration

## Notes

- Since no telemetry is exported today, the source's Option A ("tag every seat with
  `OTEL_RESOURCE_ATTRIBUTES=sdd.feat=…` and build the panels in Grafana") is not a
  "smallest change" on top of a working pipeline — the Claude Code pipeline itself has to
  be turned on first.
- A parallel `codex/installer.py` (17.6 KB) already exists for the Codex seat, so whatever
  per-seat install story a usage feature needs has a precedent on both sides.
- `installer.py:842` resolves `git_dir / "hooks" / hook_name`, i.e. the installer already
  handles git hooks as well as Claude Code hooks.
