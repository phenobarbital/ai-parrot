---
id: F009
query_id: Q015
type: tree
intent: Installed codex CLI version and exec flags (model, reasoning, schema, stdin)
executed_at: 2026-09-10T01:00:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F009 — codex-cli 0.153.4 installed; supports -m, -c model_reasoning_effort, --output-schema, -o, stdin prompt

## Summary

`codex` resolves to `~/.local/bin/codex`, version 0.153.4. `codex exec` accepts the prompt positionally or from stdin (`-`), plus `-m/--model`, `-c key=value` config overrides (e.g. reasoning effort), `-s/--sandbox`, `--output-schema <FILE>`, `-o/--output-last-message <FILE>`, `--json`, `--ephemeral`, `-p/--profile`. The operator's `~/.codex/config.toml` currently sets `model = "gpt-6-astra"` and `model_reasoning_effort = "high"`. The source's requested model, "gpt 5.6-luna", was NOT verified against the CLI's accepted model list (no query run) — it must be validated before being hard-coded anywhere.

## Citations

- path: `~/.local/bin/codex`
  lines: 0
  symbol: codex --version
  excerpt: |
    codex-cli 0.153.4

- path: `codex exec --help`
  lines: 1-18
  symbol: PROMPT argument
  excerpt: |
    Usage: codex exec [OPTIONS] [PROMPT]
           codex exec [OPTIONS] <COMMAND> [ARGS]
    Commands: resume | fork | review
    [PROMPT]  Initial instructions for the agent. If not provided as an argument (or if
              `-` is used), instructions are read from stdin.

- path: `codex exec --help`
  lines: 19-102
  symbol: options
  excerpt: |
    -c, --config <key=value>     Examples: -c model="o3"
    -m, --model <MODEL>          Model the agent should use
    -p, --profile <CONFIG_PROFILE_V2>
    -s, --sandbox <SANDBOX_MODE>
        --ephemeral
        --output-schema <FILE>   JSON Schema describing the model's final response shape
        --json
    -o, --output-last-message <FILE>

- path: `~/.codex/config.toml`
  lines: 1-2
  symbol: operator defaults
  excerpt: |
    model = "gpt-6-astra"
    model_reasoning_effort = "high"

## Notes

`--ignore-user-config` (used by the dev-loop dispatcher, F007) would *drop* the operator's high-reasoning default; a prose command that wants a thinking model must pass `-m` and `-c model_reasoning_effort=high` explicitly rather than rely on the operator's config.
