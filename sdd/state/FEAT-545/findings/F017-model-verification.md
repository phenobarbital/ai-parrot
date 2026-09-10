---
id: F017
query_id: Q023
type: tree
intent: Verify the user-requested Codex model name against the installed CLI (resolves U1 / C12)
executed_at: 2026-09-10T01:20:00Z
duration_ms: 20000
parent_id: F009
depth: 1
---

# F017 — `gpt-5.6-luna` is accepted by codex-cli 0.153.4 with `model_reasoning_effort=high`

## Summary

A one-shot probe `codex exec --ephemeral --sandbox read-only -m gpt-5.6-luna -c model_reasoning_effort=high --ignore-user-config -o <file> "Reply with exactly the single word OK."` exited 0 and wrote `OK` to the output file (4742 tokens used). The model name the user requested is therefore valid for the installed CLI and can be the verified default of the design-research seat. `--ignore-user-config` was passed so the result does not depend on the operator's `~/.codex/config.toml`.

## Citations

- path: `~/.local/bin/codex`
  lines: 0
  symbol: codex exec -m gpt-5.6-luna (exit 0)
  excerpt: |
    OK
    tokens used
    4742
