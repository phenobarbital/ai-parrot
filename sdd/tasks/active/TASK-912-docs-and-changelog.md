# TASK-912: Document the new JSONB columns + factories (CHANGELOG + README snippet)

**Feature**: FEAT-133 — DB-Persisted Reranker & Parent-Searcher Config for AI Bots
**Spec**: `sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-904, TASK-905, TASK-906, TASK-907, TASK-908, TASK-910
**Assigned-to**: unassigned

---

## Context

Operators editing bot rows directly (or building a future admin UI) need to
know the JSON shape of `reranker_config` and `parent_searcher_config`, the
allowed `type` values, and the back-compat default. This task adds a short
README snippet plus a CHANGELOG entry. Implements spec section "Worktree
Strategy" item #9 (Documentation updates).

---

## Scope

- Add a CHANGELOG entry under FEAT-133 referencing:
  - Two new JSONB columns on `navigator.ai_bots`.
  - Two new factory modules (`parrot.rerankers.factory`,
    `parrot.stores.parents.factory`).
  - The `BotManager` wiring change.
  - Back-compat guarantee (empty `{}` ⇒ pre-FEAT-133 behavior).
- Add a README snippet (or extend the existing "Configuration" section in
  the package README) showing both config shapes and the load-time error
  modes (unknown type ⇒ `ConfigError`).
- Optionally: extend `examples/chatbots/att/bot.py`'s comments to point at
  the new DB-driven path (but DO NOT change the imperative bot itself —
  it remains a working example).

**NOT in scope**:
- A migration script for existing rows.
- New examples directories.
- Form-builder / UI documentation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `CHANGELOG.md` (top of file) | MODIFY | Add FEAT-133 entry |
| `packages/ai-parrot/README.md` | MODIFY | Snippet on the two new configs |
| `examples/chatbots/att/bot.py` | OPTIONAL | One-line comment pointing at DB path |

> If the project uses a different changelog file (e.g.
> `docs/CHANGELOG.md` or `packages/ai-parrot/CHANGELOG.md`), use that
> instead — verify with `find . -maxdepth 4 -iname "CHANGELOG*"` first.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
N/A — documentation task only.

### Existing Signatures to Reference (verbatim in docs)
```python
from parrot.rerankers.factory import create_reranker
from parrot.stores.parents.factory import create_parent_searcher
```

### Does NOT Exist
- ❌ `parrot.rerankers.factory.create_reranker_from_db` — there is no
  DB-aware variant; the manager passes the dict directly.
- ❌ A schema validator on the JSONB columns — only shallow `isinstance(dict)`
  validation in the handler (TASK-910).

---

## Implementation Notes

### CHANGELOG snippet
```markdown
## [Unreleased]

### Added
- **FEAT-133** — DB-persisted reranker (FEAT-126) and parent-searcher
  (FEAT-128) configuration for AI bots.
  - New JSONB columns on `navigator.ai_bots`: `reranker_config` and
    `parent_searcher_config` (both default `'{}'::JSONB`).
  - New factories: `parrot.rerankers.factory.create_reranker` and
    `parrot.stores.parents.factory.create_parent_searcher`.
  - `BotManager.create_bot` invokes the factories and forwards the
    resulting instances to the bot constructor (reranker before
    construction, parent_searcher after `bot.configure()`).
  - Empty configs preserve current behavior — no regression for existing
    rows.
  - Unknown `type` values raise `ConfigError` at bot startup (fail-loud).
```

### README snippet (under "Bot configuration")
```markdown
### Reranker config (FEAT-126, persisted)

`navigator.ai_bots.reranker_config` JSONB. Empty `{}` means "no reranker".

```jsonc
{
  "type": "local_cross_encoder",
  "model_name": "cross-encoder/ms-marco-MiniLM-L-12-v2",
  "device": "cpu",
  "rerank_oversample_factor": 4
}
```

```jsonc
{
  "type": "llm",
  "client_ref": "bot",
  "rerank_oversample_factor": 4
}
```

### Parent-searcher config (FEAT-128, persisted)

`navigator.ai_bots.parent_searcher_config` JSONB. Empty `{}` means
"no parent expansion".

```jsonc
{
  "type": "in_table",
  "expand_to_parent": true
}
```

Unknown `type` values raise `ConfigError` at bot startup.
```

### Key Constraints
- Keep the README snippet under 60 lines.
- Use the exact JSON shapes from the spec — no improvisation.
- Cross-link the spec file path so future maintainers can find the source
  of truth.

---

## Acceptance Criteria

- [ ] CHANGELOG (or equivalent) has a FEAT-133 entry summarizing the
  feature.
- [ ] `packages/ai-parrot/README.md` (or equivalent) describes both config
  shapes, the empty-dict default, and the unknown-type behavior.
- [ ] No code changes outside docs (the optional `bot.py` comment is a
  one-liner only).
- [ ] `markdownlint` clean for the modified files (if the project uses it).
- [ ] Maps to spec section "Worktree Strategy" item #9.

---

## Test Specification

> Documentation-only — verified by review.

---

## Agent Instructions

1. `find . -maxdepth 4 -iname "CHANGELOG*"` to locate the active changelog.
2. `find packages/ai-parrot -maxdepth 3 -iname "README*"` to locate the
   relevant README.
3. Confirm TASK-904, 905, 906, 907, 908, 910 are completed (the wording
   in docs assumes their landing).
4. Update `tasks/.index.json` → `"in-progress"`.
5. Add the snippets above (adjust paths to project conventions).
6. `markdownlint` (if used) on the modified files.
7. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
