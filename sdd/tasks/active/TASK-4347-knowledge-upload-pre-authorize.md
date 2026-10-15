# TASK-4347: Authorize knowledge uploads before downloading the file

**Feature**: FEAT-673 — Authorize knowledge uploads before downloading the file
**Spec**: `sdd/specs/fixgroup-78be66fdfe17.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: issue:3cf4d0630516

---

## Context

Ledger fix lane (`/sdd-fix`, fixgroup:78be66fdfe17). Telegram/Teams/Slack
knowledge-upload adapters download the file before the allow-list check in
`KnowledgeUploadService.submit()`, enabling memory/bandwidth DoS by
unauthorized users. Implements spec §3 M1.

---

## Scope

- Add `KnowledgeUploadService.pre_authorize(identity, target, filename, declared_size=None)`;
  factor `submit()`'s byte-independent checks into a shared `_validate` helper.
- Call `pre_authorize` before the download in the three adapters.
- Tests per spec §4; add `pre_authorize` to the adapter test fakes.

**NOT in scope**: Teams download timeout/host allow-list, staging sweep
(issue:1ac5c0eb31e5), profile caching, policy changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/service.py` | MODIFY | `pre_authorize` + `_validate` |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/knowledge_upload.py` | MODIFY | pre-authorize before download |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/knowledge_upload.py` | MODIFY | pre-authorize before download |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/knowledge_upload.py` | MODIFY | pre-authorize before download |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_service.py` | MODIFY | pre_authorize tests |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_telegram_upload.py` | MODIFY | fake + deny test |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_msteams_upload.py` | MODIFY | fake + deny test |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_slack_upload.py` | MODIFY | fake + deny test |

---

## Codebase Contract (Anti-Hallucination)

See spec §6. `authorize()` already audits the DENIED event; `pre_authorize`
must not audit it twice.

---

## Acceptance Criteria

- [ ] AC1–AC4 from the spec.
- [ ] No linting errors on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload -q`

---

## Agent Instructions

1. Work in the feature worktree
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-78be66fdfe17 --feature-id FEAT-673`).
2. Mark in-progress in `sdd/tasks/index/fixgroup-78be66fdfe17.json`, implement, validate with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src`.
3. Commit code, close with `scripts/sdd/close_task.sh TASK-4347 fixgroup-78be66fdfe17 verified`.

---

## Completion Note

*(Agent fills this in when done)*
