# TASK-4911: Attach Gemini CachedContent without system_instruction/tools/tool_config

**Feature**: FEAT-781 — google-client-fixes
**Spec**: `sdd/specs/google-client-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:71716068e28f`

---

## Context
Spec §1.1 / §2 M1. `ask()` sets `cached_content` on a config that still carries `system_instruction`/`tools`/`tool_config` → Gemini 400.

## Scope
- Add kw-only `system_instruction: Optional[str] = None` to `_maybe_apply_gemini_cache`; when given, cache it instead of the joined cacheable segments.
- Add `async def _attach_gemini_cache(self, final_config, model, segments) -> None`: skip (debug log) when `final_config.tools` or `final_config.tool_config`; otherwise cache the full `final_config.system_instruction`, then set `cached_content` and clear `system_instruction`. Fail-open leaves the config untouched.
- Replace the inline block at `if _pending_cache_segs:` (client.py:3593) in `ask()` with a call to the helper.
- Unit tests in `packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py` (spec §4, M1 rows).

**NOT in scope**: tools inside the CachedContent, cache reuse, `ask_stream` (no explicit cache there).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | helper + ask() wiring |
| `packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py` | CREATE | M1 tests |

## Codebase Contract
See spec §6 (anchors `async def _maybe_apply_gemini_cache(` :548, `if _pending_cache_segs:` :3593).

## Complexity Contract
```json
{"schema_version": 1, "targets": [{"path": "packages/ai-parrot-client-google/src/parrot/clients/google/client.py", "action": "MODIFY"}, {"path": "packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py", "action": "CREATE"}], "contract_symbols": ["sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._maybe_apply_gemini_cache", "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.ask"]}
```

## Acceptance Criteria
- [ ] Spec AC-1, AC-2, AC-3.
- [ ] Existing `test_prompt_caching_gemini.py` still passes.

## Validation Commands
- `pytest packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py -q`
- `pytest packages/ai-parrot/tests/test_prompt_caching_gemini.py -q`

---

## Agent Instructions
Work in `.claude/worktrees/feat-FEAT-781-google-client-fixes`; run tests with
`PYTHONPATH=packages/ai-parrot-client-google/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src`;
close with `scripts/sdd/close_task.sh TASK-4911 google-client-fixes verified`.

---

## Completion Note
*(Agent fills this in when done)*
