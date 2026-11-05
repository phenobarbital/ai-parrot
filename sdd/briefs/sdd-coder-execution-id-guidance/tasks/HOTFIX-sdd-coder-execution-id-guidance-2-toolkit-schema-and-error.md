# HOTFIX-sdd-coder-execution-id-guidance-2: SddCoderToolkit — advertise UUID schema + field-level invalid_arguments

**Feature**: sdd-coder-execution-id-guidance (brief)
**Spec**: sdd/briefs/sdd-coder-execution-id-guidance.brief.md
**Status**: done
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
The MCP schema shows `"description": "Parameter: execution_id"` (generic, from
`parrot/tools/toolkit.py:127-128`), and a validation failure returns only
`"invalid tool arguments"`. See brief § Root cause (2) and (3).

## Scope
1. **Schema**: in `models.py`, give every `execution_id` field of the `_Args` subclasses a
   `Field(..., description="Canonical lowercase UUID4 identifying this worker execution; generate it with uuid.uuid4(), never hand-write it. Reuse the same id for every call.", pattern=<canonical regex>)`
   (define the regex constant once in `models.py`). In `SddCoderToolkit`, after tools are
   generated, set each tool's `args_schema` to its `arg_models` entry so the advertised JSON
   schema carries the description/pattern. Verify the attribute the MCP adapter reads before
   editing (start from `ToolkitTool` in `parrot/tools/toolkit.py` and the MCP server adapter).
2. **Error**: at `toolkit.py:167`, build the message from `exc.errors()`:
   `"invalid tool arguments: execution_id: must be a canonical UUID (got non-hex value); ..."` —
   `loc` joined by `.` plus `msg`, at most 5 entries, never echo `input` values longer than 64 chars.
   Keep `code="invalid_arguments"` and `errors=` unchanged; keep the `execution_required` branch.

**NOT in scope**: changing `parrot/tools/toolkit.py` (shared core); de-duplicating the regexes in
`checkpoint.py`/`background.py`/`evidence.py`; the prompt (task 1).

## Files to Create / Modify
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` (new tests)

## Codebase Contract
### Existing anchors
- `sdd_coder/toolkit.py:71` `arg_models: Dict[str, type[BaseModel]] = {`
- `sdd_coder/toolkit.py:167` `raise CoderFailure("invalid_arguments", "invalid tool arguments", errors=exc.errors()) from exc`
- `sdd_coder/models.py:667-672` `class CoderPlanArgs(_Args)` with `execution_id: str = Field(..., min_length=1)` and `_exec = field_validator("execution_id")(_check_uuid)`
- `parrot/tools/toolkit.py:127` `description = f"Parameter: {param_name}"`
### Does NOT Exist
- No `args_schema` override in `SddCoderToolkit` today.

## Acceptance Criteria
- [ ] The JSON schema of `coder_begin_execution` (and every tool taking `execution_id`) has a
      non-generic description and the canonical `pattern` for `execution_id`.
- [ ] Calling with `execution_id="7b1c2f0e-4d3a-4e55-9a61-184pbac00001"` raises `invalid_arguments`
      whose message names `execution_id`.
- [ ] Existing `test_toolkit.py` tests (152-183) still pass; missing id still → `execution_required`.

## Validation Commands
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q`
- `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`

## Completion Note

Verified in 67da154d37: `coder_begin_execution` test suite passes (38 passed, test_toolkit.py); both .claude/agents/sdd-worker.md twins identical; diff covers the change described in this task.
