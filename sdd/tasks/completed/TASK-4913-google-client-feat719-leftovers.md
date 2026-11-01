# TASK-4913: Type _computer_use_vocabulary as Literal; stop making up ISO codes in the Whisper backend

**Feature**: FEAT-781 — google-client-fixes
**Spec**: `sdd/specs/google-client-fixes.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4912
**Assigned-to**: unassigned

**Discovered-from**: `issue:461ceca67d43`

---

## Context
Spec §1.3 / §2 M3. Two FEAT-719 leftovers split out of `issue:e25a0e2aaae1`.

## Scope
- client.py: add `Literal` to the typing import, define module-level `ComputerUseVocabulary = Literal["legacy", "v3_8"]`, annotate `_computer_use_vocabulary` with it.
- openai_backend.py: add `_iso_language(value: Optional[str]) -> Optional[str]` (map name → ISO; accept `^[a-z]{2}([-_][a-z0-9]+)*$` → first two letters; else None). Use it for the payload language and the `language_hint`. Extend `_LANGUAGE_NAMES` (malay ms, welsh cy, indonesian id, vietnamese vi, thai th, hungarian hu).
- Tests: `test_vocabulary_alias` in `test_google_client_fixes.py`; new `packages/ai-parrot-integrations/tests/voice/transcriber/test_openai_language_codes.py`.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | Literal alias |
| `packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py` | MODIFY | _iso_language |
| `packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py` | MODIFY | alias test |
| `packages/ai-parrot-integrations/tests/voice/transcriber/test_openai_language_codes.py` | CREATE | language tests |

## Codebase Contract
See spec §6 (anchors client.py:2, :295; openai_backend.py:315).

## Complexity Contract
```json
{"schema_version": 1, "targets": [{"path": "packages/ai-parrot-client-google/src/parrot/clients/google/client.py", "action": "MODIFY"}, {"path": "packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py", "action": "MODIFY"}, {"path": "packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py", "action": "MODIFY"}, {"path": "packages/ai-parrot-integrations/tests/voice/transcriber/test_openai_language_codes.py", "action": "CREATE"}], "contract_symbols": ["sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._computer_use_vocabulary", "sym:packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py#OpenAIWhisperBackend._parse_result"]}
```

## Acceptance Criteria
- [ ] Spec AC-6, AC-7.

## Validation Commands
- `pytest packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py -q`
- `pytest packages/ai-parrot-integrations/tests/voice/transcriber/test_openai_language_codes.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_openai_whisper_backend.py -q`

---

## Agent Instructions
Work in `.claude/worktrees/feat-FEAT-781-google-client-fixes`; run tests with
`PYTHONPATH=packages/ai-parrot-client-google/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src`;
close with `scripts/sdd/close_task.sh TASK-4913 google-client-fixes verified`.

---

## Completion Note
**Completed by**: agent:sdd-fix (Claude Opus 5.5)
**Date**: 2026-10-30
**Notes**: Added the `ComputerUseVocabulary` alias and annotation. Added `_iso_language` plus six new map entries in the
Whisper backend. 14 new tests; the full Validation Contract (76 tests) passes. Ruff findings in both source files are unchanged from base.
**Deviations from spec**: none. Side effect: a 3-letter code such as `"eng"` no longer becomes `"en"` (it is
not ISO 639-1); it falls back to the hint, then `"en"`. Resolves `issue:461ceca67d43`.
