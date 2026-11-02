---
id: FX-001
query_id: X2
type: read
intent: "External probe: determine the Codex CLI's non-interactive surface — version, JSON event stream, session persistence, hooks."
executed_at: 2026-10-30T22:38:00Z
duration_ms: 1800
parent_id: null
depth: 0
---

# FX-001 — Codex CLI 0.164.0 exposes a JSONL event stream, a hook system and session persistence

## Summary

The installed Codex CLI is `codex-cli 0.164.0` at
`/home/jesuslara/.codex/packages/standalone/releases/0.164.0-x86_64-unknown-linux-musl/bin/codex`
(symlinked from `~/.local/bin/codex`). `codex exec` **does** support `--json`
("Print events to stdout as JSONL"), which is the ingestion surface the source
document hoped for but marked unverified. Codex also ships a **hook** system
(`--dangerously-bypass-hook-trust` implies persisted hook trust), a
`--output-last-message <FILE>` flag, and an `--ephemeral` flag that suppresses
session persistence. Sessions are first-class: `resume`, `fork`, `archive`,
`delete`, `migrate-rollouts` subcommands all key on a session id or name.

No documentation ships with the standalone package (only
`codex-resources/voice/NOTICE.md`), so every claim here comes from the binary's
own `--help` output.

## Citations

- path: `~/.local/bin/codex -> ~/.codex/packages/standalone/releases/0.164.0-x86_64-unknown-linux-musl/bin/codex`
  lines: n/a
  symbol: `codex --version`
  excerpt: |
    codex-cli 0.164.0

- path: `codex exec --help`
  lines: n/a
  symbol: `--json`
  excerpt: |
          --json
              Print events to stdout as JSONL

- path: `codex exec --help`
  lines: n/a
  symbol: `--output-last-message`
  excerpt: |
      -o, --output-last-message <FILE>
              Specifies file where the last message from the agent should be written

- path: `codex exec --help`
  lines: n/a
  symbol: `--ephemeral`
  excerpt: |
          --ephemeral
              Run without persisting session files to disk
          --ignore-user-config
              Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`

- path: `codex exec --help`
  lines: n/a
  symbol: `--dangerously-bypass-hook-trust`
  excerpt: |
          --dangerously-bypass-hook-trust
              Run enabled hooks without requiring persisted hook trust for this invocation.

- path: `codex --help`
  lines: n/a
  symbol: `commands`
  excerpt: |
      exec   Run Codex non-interactively [aliases: e]
      resume Resume a previous interactive session (picker by default; use --last ...)
      fork   Fork a previous interactive session ...
      doctor Diagnose local Codex installation, config, auth, and runtime health

## Notes

Resolves the first half of spike **S3** without a live run: the JSONL stream
exists and is a documented, flagged, non-experimental surface. What `--json`
actually emits per turn is still unconfirmed — that needs one captured run and
stays inside S3.

Codex's own hook system is a second, unanticipated binding surface: the source
document assumed the Codex seat would need a wrapper to record
`session -> feat_id`. A Codex hook may do the same job the Claude Code
`SessionStart` hook does. Its trigger vocabulary is unverified.

`--ephemeral` and `--ignore-user-config` are a correctness hazard for any
ingestor that relies on session files or on `~/.codex/config.toml` being loaded.

[cross-lane: type=grep, intent=does flows/dev_loop ever pass --json or -o to codex today]
