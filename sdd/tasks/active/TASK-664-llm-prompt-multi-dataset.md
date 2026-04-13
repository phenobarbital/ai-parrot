# TASK-664: LLM Prompt Update for Multi-Dataset Responses

**Feature**: datasetmanager-more-data
**Spec**: `sdd/specs/datasetmanager-more-data.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-662
**Assigned-to**: unassigned

---

## Context

The LLM needs to know when and how to use the new `data_variables` field. Without
prompt guidance, the model will continue using only `data_variable` (singular) and
multi-dataset responses will never trigger.

Implements **Module 3** from the spec.

---

## Scope

- Update `PANDAS_SYSTEM_PROMPT` in `data.py` to add instructions about `data_variables`
- Add a section explaining when to use `data_variables` (plural) vs `data_variable` (singular)
- Add an example showing a multi-dataset query and the expected structured output
- Update the `PandasAgentResponse.data_variables` field description to be clear for LLMs

**NOT in scope**:
- Model changes (TASK-662)
- Injection logic (TASK-663)
- Serialization (TASK-665)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | Update `PANDAS_SYSTEM_PROMPT` and `data_variables` field description |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports needed for this task
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py

# PANDAS_SYSTEM_PROMPT starts at line 208, is a multi-line string template
PANDAS_SYSTEM_PROMPT = """
You are $name Agent.
<system_instructions>
...
"""  # ends ~line 327 (verify exact end line before editing)

# PandasAgentResponse.data_variables — ADDED BY TASK-662
# Located after data_variable (line 175)
data_variables: Optional[List[str]]  # added by TASK-662

# Existing fields that the prompt references:
# data_variable: Optional[str]  # line 175
# data: Optional[PandasTable]  # line 163
```

### Does NOT Exist
- ~~`MULTI_DATASET_PROMPT`~~ — no separate prompt constant, add to `PANDAS_SYSTEM_PROMPT`
- ~~`PandasAgentResponse.datasets`~~ — field is called `data_variables`, not `datasets`

---

## Implementation Notes

### Prompt Addition
Add the following section to `PANDAS_SYSTEM_PROMPT`, after the "DATA PROCESSING PROTOCOL" section (~line 314):

```
## MULTI-DATASET RESPONSES:
When your answer involves data from MULTIPLE datasets (e.g., "show users by Q3
AND their completed tasks"), you must return ALL relevant datasets to the caller:

1. **Single dataset** → set `data_variable` to the variable name (existing behavior).
2. **Multiple datasets** → set `data_variables` (plural) to a list of ALL variable
   names that contain result data. Example:
   ```json
   {
     "explanation": "Here are the Q3 users and their completed tasks...",
     "data_variables": ["users_q3", "tasks_completed"],
     "data_variable": null,
     "data": null
   }
   ```

**Rules:**
- Use `data_variables` (plural, a list) when 2+ datasets are involved.
- Use `data_variable` (singular, a string) when only 1 dataset is involved.
- Do NOT set both `data_variable` and `data_variables` — use one or the other.
- Each variable name in `data_variables` must be a Python variable available in
  the `python_repl_pandas` execution context.
```

### Key Constraints
- Keep the prompt addition concise — LLMs perform worse with overly long prompts
- Use JSON examples the LLM can pattern-match against
- Clearly distinguish `data_variable` (singular/string) from `data_variables` (plural/list)
- Do NOT change the `$variable` template substitutions — those are processed by `string.Template`

---

## Acceptance Criteria

- [ ] `PANDAS_SYSTEM_PROMPT` contains instructions about `data_variables` (plural)
- [ ] Prompt clearly explains when to use singular vs plural form
- [ ] Prompt includes a JSON example of multi-dataset output
- [ ] No `$` characters used outside of existing template variables (would break `string.Template`)
- [ ] No linting errors

---

## Test Specification

No automated tests for prompt content — this is a text change. Manual verification:
1. Read `PANDAS_SYSTEM_PROMPT` after modification
2. Confirm `data_variables` section is present
3. Confirm no `string.Template` substitution errors (`$` not followed by known variables)

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-more-data.spec.md` for full context
2. **Check dependencies** — verify TASK-662 is in `tasks/completed/`
3. **Verify the Codebase Contract**:
   - Read `PANDAS_SYSTEM_PROMPT` to find its exact start/end lines
   - Confirm `data_variables` field was added to `PandasAgentResponse` by TASK-662
   - Check for any `$` template variables to avoid conflicts
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-664-llm-prompt-multi-dataset.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
