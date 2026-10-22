# TASK-4589: OpenAIClient: drop o3/o3-pro Responses-only and gpt-5-nano max_tokens exception (after 2026-12-11)

**Feature**: FEAT-719 — Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)
**Spec**: `sdd/specs/model-deprecation-followups.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

> **Prerequisite**: branch `fix/model-deprecations-2026-10` (the 2026-10-22 deprecation sweep) must be merged into `dev` before this task starts — every anchor below was verified against `origin/dev` 63442566b + that sweep. Re-run each `grep -c` before editing.

---

## Context

Implements spec §3 Module 8. `o3`/`o3-pro` and the `gpt-5-nano` snapshot shut down 2026-12-11. Until then removing the special cases would break those still-live models.

---

## Scope

- Remove `"o3"` and `"o3-pro"` from `RESPONSES_ONLY_MODELS` (delete the set and its uses if it becomes empty — check the uses first).
- Remove the `if model_str != "gpt-5-nano":` exception so `max_tokens` is always resolved.
- Tests.

**NOT in scope**: the deep-research / search-preview branches (left untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py` | MODIFY | remove two special cases |
| `packages/ai-parrot-client-openai/tests/unit/openai/test_deprecations.py` | MODIFY | tests |

---

## Codebase Contract (Anti-Hallucination)

> Use these exact imports and signatures. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.clients.openai import client as gpt_mod  # verified: test_deprecations.py uses this import
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py
RESPONSES_ONLY_MODELS = {"o3", "o3-pro"}                                 # line 54
if model_str != "gpt-5-nano":                                              # line 867
    args["max_tokens"] = self._resolve_max_tokens(max_tokens)
```

### Does NOT Exist
- ~~other gpt-5-nano special cases~~ — grep before assuming; only :867 was found

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-openai/tests/unit/openai/test_deprecations.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py#OpenAIClient"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` (never `print`); Pydantic v2; aiohttp only.
- Hard cut — no deprecation shims (no external consumers).
- **Do not merge before 2026-12-11** (spec AC-10).

---

## Implementation Blueprint

### Steps (in order)
1. grep every use of `RESPONSES_ONLY_MODELS` — *why*: an empty set may leave dead branches.
2. Remove the entries / dead branch — *why*: models shut down.
3. Remove the nano exception — *why*: same.
4. Tests.

### `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'RESPONSES_ONLY_MODELS = {' client.py) — :54
# FILL IN: remove "o3", "o3-pro"; if the set becomes empty, remove it and its uses — bounded by grep of its uses
```
```python
# occurrences: 1 (verified: grep -c '        if model_str != "gpt-5-nano":' client.py) — :867
        args["max_tokens"] = self._resolve_max_tokens(max_tokens)
```

### FILL IN checklist
- [ ] RESPONSES_ONLY_MODELS uses — bounded by grep

---

## Acceptance Criteria

- [ ] no `o3`/`o3-pro`/`gpt-5-nano` special case remains
- [ ] merged on or after 2026-12-11

---

## Validation Commands

- `pytest packages/ai-parrot-client-openai/tests/unit/openai/test_deprecations.py -q`

---

## Test Specification

```python
def test_openai_cleanups():
    from parrot.clients.openai import client as gpt_mod
    assert "o3" not in getattr(gpt_mod, "RESPONSES_ONLY_MODELS", set())
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug model-deprecation-followups --feature-id FEAT-719`)
2. **Read the spec** at `sdd/specs/model-deprecation-followups.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/model-deprecation-followups.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` in the blueprint; a changed count means the
   anchor moved (re-locate it), a `0` means drift (stop and report)
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed
   signature or path
7. **Verify** — run the Validation Commands with `PYTHONPATH` pointing at the worktree's `packages/*/src`
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4589 model-deprecation-followups verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

Implemented on separate branch `feat-FEAT-719-o3-nano-cleanup` (re-applied from the reverted seat delivery, with out-of-scope ruff edits removed). `RESPONSES_ONLY_MODELS` and the `OpenAIClient._is_responses_model` override are removed (the base always returns False); the gpt-5-nano max_tokens exception is removed. test_deprecations.py: 41 passed.

**DO NOT MERGE BEFORE 2026-12-11** (spec AC-10): o3/o3-pro/gpt-5-nano snapshots stay live until then. Residue left deliberately out of scope: stale comment in tests/unit/test_openai_multiround_usage.py mentioning RESPONSES_ONLY_MODELS; dead `if use_responses:` branches in client.py.
