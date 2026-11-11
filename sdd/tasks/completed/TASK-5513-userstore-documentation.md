# TASK-5513: Documentation — user-stores, db-storage, documentdb_interface, crew-definition-storage

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5495, TASK-5496, TASK-5497, TASK-5508, TASK-5509, TASK-5510, TASK-5511
**Assigned-to**: unassigned

---

## Context

Spec §10 (docs policy `required`, FEAT-801). FEAT-878 changes a default that operators depend on (DocumentDB →
Redis) and adds a startup guard that stops DocumentDB installations until they declare `PARROT_USER_STORE`.
The wiki must explain the switches, the guard and its two fixes, Redis durability requirements, the copy CLI,
rotation targets, and the crew-result default — before the release ships.

---

## Scope

- Create `wiki/stores/user-stores.md` from `sdd/templates/techwiki-page.md`.
- Update `wiki/bots/agentstudio/db-storage.md`, `wiki/stores/documentdb_interface.md`,
  `wiki/bots/orchestration/crew-definition-storage.md`.
- Add a docs test that pins the facts operators rely on (setting names, the guard fixes, the CLI name).

**NOT in scope**: code changes; README/release notes (release tooling).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/stores/user-stores.md` | CREATE | main page |
| `wiki/bots/agentstudio/db-storage.md` | MODIFY | phase-2 switches accept `redis`; default via `PARROT_USER_STORE`; vault `postgres` fails closed |
| `wiki/stores/documentdb_interface.md` | MODIFY | DocumentDB no longer the default for user stores; link |
| `wiki/bots/orchestration/crew-definition-storage.md` | MODIFY | unset `CREW_RESULT_STORAGE` follows `PARROT_USER_STORE` |
| `packages/ai-parrot/tests/userstore/test_user_stores_docs.py` | CREATE | docs facts test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.userstore import SWITCHES, GLOBAL_SWITCH   # TASK-5495 — the docs test checks every switch name appears in the page
```

### Existing Signatures to Use
```text
sdd/templates/techwiki-page.md — frontmatter (title, summary) + sections: Purpose, Public API, Configuration & Parameters,
  Usage Examples, Gotchas, Related.
wiki/bots/agentstudio/db-storage.md — section "### Phase 2 — secrets stores (default: DocumentDB, unchanged behaviour)" with the
  BYOK_STORE / VAULT_STORE / TOOLKIT_OVERRIDES_STORE table (values `documentdb | postgres`).
wiki/stores/documentdb_interface.md — "DocumentDB Interface Guide" (DocumentDb usage).
wiki/bots/orchestration/crew-definition-storage.md — mentions CREW_RESULT_STORAGE.
```

### Does NOT Exist
- ~~`wiki/stores/user-stores.md`~~ — created by this task.
- ~~A warning-only upgrade path~~ — the guard stops startup (spec §8 Q1).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/stores/user-stores.md", "action": "CREATE"},
    {"path": "wiki/bots/agentstudio/db-storage.md", "action": "MODIFY"},
    {"path": "wiki/stores/documentdb_interface.md", "action": "MODIFY"},
    {"path": "wiki/bots/orchestration/crew-definition-storage.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/userstore/test_user_stores_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write `user-stores.md` — *why*: the one page the startup guard error and release notes point to.
2. Update the three existing pages (short, factual edits; keep their structure) — *why*: they currently state DocumentDB is the default.
3. Write the docs test; run `parrot sdd techwiki check`.

### `wiki/stores/user-stores.md` (CREATE)
```markdown
---
title: User stores (Redis by default)
summary: Where ai-parrot keeps per-user credentials, BYOK keys, overrides, MCP configs, OAuth connections and dashboards — and how to switch.
---

# User stores (Redis by default)

## Purpose
<!-- FILL IN: the 8 collections table (spec §1), why Redis is the default (no MongoDB for local/simple installs). -->

## Configuration & Parameters
<!-- FILL IN: precedence (per-store → PARROT_USER_STORE → redis); table of the 7 switches with allowed values
     (postgres only for VAULT_STORE / BYOK_STORE / TOOLKIT_OVERRIDES_STORE); PARROT_USER_STORE_REDIS_URL,
     PARROT_USER_STORE_REDIS_DB (6), PARROT_USER_STORE_REDIS_PREFIX (parrot:us); CREW_RESULT_STORAGE default rule. -->

## Upgrading an installation that uses MongoDB
<!-- FILL IN: the startup guard (DOCUMENTDB_HOSTNAME/DBNAME set + nothing declared → UserStoreMisconfigured);
     fix A `PARROT_USER_STORE=documentdb`; fix B `python -m parrot.userstore.copy --dry-run`, then without --dry-run,
     then `PARROT_USER_STORE=redis`; --overwrite semantics; Studio Postgres switches unchanged. -->

## Redis requirements
<!-- FILL IN: no TTL, maxmemory-policy must not be allkeys-*, enable AOF or RDB; db 6; Redis Cluster → set the URL;
     the startup diagnostics and what each warning means. -->

## Usage Examples
<!-- FILL IN: .env snippets for local dev (nothing), keep-Mongo production, mixed (VAULT_STORE=postgres + redis rest). -->

## Gotchas
<!-- FILL IN: crew results in Redis expire after 7 days (CREW_RESULT_STORAGE_REDIS_TTL); rotation entry points need a
     package metadata refresh; quarantine keeps the latest copy per identity. -->

## Related
- [Agent Studio database storage](../bots/agentstudio/db-storage.md) · [DocumentDB interface](documentdb_interface.md) · spec `sdd/specs/redis-user-stores.spec.md` (FEAT-878)
```

### `packages/ai-parrot/tests/userstore/test_user_stores_docs.py` (CREATE)
```python
"""FEAT-878 docs facts: the page operators are pointed to names every switch and both guard fixes."""
from pathlib import Path

from parrot.userstore import GLOBAL_SWITCH, SWITCHES

REPO = Path(__file__).resolve().parents[4]
PAGE = REPO / "wiki" / "stores" / "user-stores.md"


def test_page_names_every_switch():
    text = PAGE.read_text(encoding="utf-8")
    for name in [GLOBAL_SWITCH, *SWITCHES, "PARROT_USER_STORE_REDIS_URL", "CREW_RESULT_STORAGE"]:
        assert name in text, name


def test_page_names_guard_fixes_and_cli():
    text = PAGE.read_text(encoding="utf-8")
    assert "PARROT_USER_STORE=documentdb" in text and "PARROT_USER_STORE=redis" in text
    assert "python -m parrot.userstore.copy" in text
```

### FILL IN checklist
- [ ] every `<!-- FILL IN -->` section of user-stores.md
- [ ] the three page updates

---

## Acceptance Criteria

- [ ] `parrot sdd techwiki check --spec sdd/specs/redis-user-stores.spec.md --root .` passes (AC16)
- [ ] No page still says DocumentDB is the default for user stores
- [ ] Docs test passes
- [ ] Every setting name in the pages matches the code (`parrot.userstore.SWITCHES`)

---

## Validation Commands
- `pytest packages/ai-parrot/tests/userstore/test_user_stores_docs.py -q`

---

## Test Specification

See the docs test block above.

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2, §7, §8, §10)
3. **Check dependencies** — all listed tasks must be `done` (the pages document their symbols)
4. **Verify** setting names against `parrot/userstore/settings.py` before writing
5. **Update status** → `"in-progress"`, commit only the index file
6. **Write** the pages from the blueprint, complete every `FILL IN`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, then `parrot sdd techwiki check --spec sdd/specs/redis-user-stores.spec.md --root .` (AC16)
8. **Commit** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5513 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note


- Task: TASK-5513
- Feature: redis-user-stores
- Implementation SHA: da59e54d120eac6390f353024473cc4209fcaa13
- Closed at (UTC): 2026-11-11T02:21:03+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: kimi · Backend: nova · Model: moonshotai.kimi-k2.5 · Attempts: 1 · Duration: 107s · Tokens: 643029/4528 |
