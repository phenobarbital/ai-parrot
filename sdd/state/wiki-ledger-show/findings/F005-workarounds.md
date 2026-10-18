# F005 — Consumers that need list/show (type: grep)
Citations: .claude/commands/sdd-fix.md:25; .claude/commands/sdd-start.md:141; memory wikitoolkit-stdout-banner-breaks-json
- /sdd-fix renders groups from `ledger plan-fix --json`; there is no way to read an issue's body by id from CLI, so agents
  read events.jsonl / ledger.db directly or re-derive from plan-fix output.
- `plan-fix --json` prints navconfig banner on stdout before JSON (known gotcha) — new `--json` outputs must stay clean.
