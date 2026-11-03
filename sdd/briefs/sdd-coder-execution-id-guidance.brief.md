---
kind: brief
slug: sdd-coder-execution-id-guidance
key: sdd-coder-execution-id-guidance
base_branch: dev
source:
  type: text
  ref: "user report 2026-11-03: coder_begin_execution fails first time with 'invalid tool arguments'"
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-03"
---

# Brief: sdd-coder execution_id guidance and error clarity

## Problem
sdd-worker's first call to the `parrot-sdd-coder` MCP server often fails:

```
coder_begin_execution(feature: "FEAT-184", worktree: ".../feat-FEAT-184-pbac-based-per-user-filter",
                      execution_id: "7b1c2f0e-4d3a-4e55-9a61-184pbac00001")
Error: Error in coder_begin_execution: invalid tool arguments
```

The agent then guesses, retries with a different id, and usually succeeds.

## Root cause
The agent hand-writes the `execution_id`. `7b1c2f0e-4d3a-4e55-9a61-184pbac00001` contains `p`
(not hex): a "mnemonic" UUID made from the feature slug. Three gaps combine:

1. **Prompt** — `.claude/agents/sdd-worker.md:334` (twin
   `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`) only says
   "Generate one UUID for this worker invocation". An LLM has no randomness source, so it invents one.
2. **Schema** — the MCP args schema comes from the method signature through
   `packages/ai-parrot/src/parrot/tools/toolkit.py:127-128`, which hard-codes
   `description = f"Parameter: {param_name}"`. The validating models in
   `SddCoderToolkit.arg_models` (`sdd_coder/toolkit.py:71`, e.g. `CoderPlanArgs` at
   `sdd_coder/models.py:667-672`: `execution_id: str = Field(..., min_length=1)` + `_check_uuid`)
   are never exposed to the client, so the agent sees no format, pattern, or example.
3. **Error** — `sdd_coder/toolkit.py:167` raises
   `CoderFailure("invalid_arguments", "invalid tool arguments", errors=exc.errors())`. Only the
   message reaches the agent; the pydantic field errors are lost, so the retry is blind.

## Research findings
- Canonical regex (duplicated): `checkpoint.py:74`, `background.py:75`, `evidence.py:57`:
  `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (lowercase only).
- `coder_begin_execution` reuses `CoderPlanArgs` (`toolkit.py:93`).
- Existing tests: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py:152-183`
  assert `invalid_arguments` / `execution_required` codes — must keep passing.
- `parrot/tools/toolkit.py` is shared core: do NOT change its schema generation; override in
  `SddCoderToolkit` only.

## Decisions
- One fix, two independent tasks: prompt twins (docs) and toolkit code (schema + error message).
- Schema exposure: inside `SddCoderToolkit`, override the generated tools' `args_schema` with
  the matching `arg_models` entry (or a derived model), so the JSON schema advertises
  `pattern` + `description` for `execution_id`. Add `Field(description=..., pattern=...)` to the
  `execution_id` fields of the `_Args` models in `models.py`.
- Error-code semantics stay the same (`invalid_arguments`, `execution_required`); only the
  message gains a `loc: msg` summary (bounded, e.g. first 5 errors, no input echo of secrets).

## Fix plan
- HOTFIX-sdd-coder-execution-id-guidance-1 — prompt twins: generate the UUID with a command.
- HOTFIX-sdd-coder-execution-id-guidance-2 — toolkit: advertise the UUID schema + field-level
  `invalid_arguments` message.

## Validation commands
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q`
- `diff .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`
