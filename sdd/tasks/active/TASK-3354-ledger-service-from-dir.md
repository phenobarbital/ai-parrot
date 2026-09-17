# TASK-3354: `LedgerService.from_dir()` — ledger without a git root (M2c)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (ledger part), AC6, design research S7. `LedgerService.from_root()`
resolves `find_shared_root()` (a git main checkout) and reads that root's
`.parrot/wiki.json`. The remote server has no checkout: it is configured with
an explicit `ledger_dir` per wiki (`WikiServerEntry.ledger_dir`). This task adds
`from_dir()` so the same `LedgerStore` / `LedgerLog` / `LedgerIndex` trio opens
from a directory. Ledger storage stays SQLite on the server host (brainstorm
decision; ArangoDB port is the follow-up `wikitoolkit-ledger-arangodb`).

---

## Scope

- `LedgerService.from_dir(ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> LedgerService`: `mkdir(parents=True, exist_ok=True)`, open `LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)`, `LedgerLog(str(ledger_dir / "events.jsonl"))`, `LedgerIndex(store, log)`, `shared_root = ledger_dir.parent.parent`.
- Document that `merge_blockers()` returns `[]` when no per-spec index exists under `shared_root` (already tolerant — verify by test, do not change it).
- Unit tests.

**NOT in scope**: changing `from_root()`, ArangoDB ledger, server wiring (TASK-3358/3361).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | add `from_dir()` classmethod; import `SQLitePragmaPolicy` |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_from_dir.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.service import LedgerService                    # service.py:96
from parrot.knowledge.wiki.ledger.store import LedgerStore                        # store.py:24 — already imported in service.py:28
from parrot.knowledge.wiki.ledger.log import LedgerLog                            # already imported in service.py:27
from parrot.knowledge.wiki.ledger.index import LedgerIndex                        # already imported in service.py:26
from parrot.knowledge.wiki.store import WikiStoreBusy, estimate_tokens            # service.py:34 (anchor, 1 occurrence) — extend with SQLitePragmaPolicy
from parrot.knowledge.wiki.store import SQLitePragmaPolicy                        # store.py:243
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:                                                                       # :96
    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None   # :99
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService":                     # :114-141
        shared_root = find_shared_root(root) or (root or Path.cwd()).resolve()
        config = load_effective_config(shared_root).config
        ledger_dir = config.ledger_path(shared_root); ledger_dir.mkdir(parents=True, exist_ok=True)
        policy = sqlite_policy_from_config(config)
        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)
        log = LedgerLog(str(ledger_dir / "events.jsonl"))
        index = LedgerIndex(store, log)
        return cls(index, store, log, shared_root)                                       # :141 (anchor, 1 occurrence)
    async def open_issue(...) :166 · ready_work(kind=None) :199 · claim(issue_id, actor) :209 · close_issue(issue_id, reason, actor) :235
    async def get_context(file_paths, max_tokens=3000) -> str :247 · merge_blockers(feature_id) :280 (reads sdd/tasks/index under shared_root via _feature_task_ids :311)
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
class LedgerStore(SQLiteWikiStore): __init__(self, db_path: str, wiki_name: str = "", *, read_only=False, sqlite_policy=None, persistent_writer=False)   # :24-51
```

### Does NOT Exist
- ~~`LedgerService.from_dir`~~ — created here.
- ~~`LedgerService(ledger_dir=...)`~~ — the constructor takes the four collaborators only; do not change it.
- ~~`LedgerStore` on ArangoDB~~ — SQLite only; out of scope.
- ~~`LedgerService.shared_root` being optional~~ — keep it a `Path` (use `ledger_dir.parent.parent`, mirroring `<root>/.parrot/ledger`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_from_dir.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Mirror `from_root()` line by line for the store/log/index construction — never introduce ledger-specific SQLite settings (the FEAT-566 spec forbids it).
- `sqlite_policy=None` is valid for `LedgerStore` (defaults apply); the server passes `sqlite_policy_from_config(cfg)`.
- No `find_shared_root()` call anywhere in `from_dir()`.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the `store` import with `SQLitePragmaPolicy` — *why*: needed for the type hint; keep one import line.
2. Add `from_dir()` right after `from_root()` — *why*: the two factories read side by side.
3. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.store import WikiStoreBusy, estimate_tokens' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py)
# REPLACE (service.py:34) with:
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy, estimate_tokens

# occurrences: 1 (verified: grep -c '        return cls(index, store, log, shared_root)' service.py)
# AFTER — insert below `        return cls(index, store, log, shared_root)` (verified: service.py:141), dedented to class level:

    @classmethod
    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> "LedgerService":
        """Open (creating if needed) a ledger at an explicit directory — no git root required (FEAT-569).

        Used by ``wikitoolkit serve``: the server host has no checkout, so the
        ledger location is configuration, not discovery. ``shared_root`` is
        derived as ``ledger_dir.parent.parent`` (mirroring ``<root>/.parrot/ledger``);
        :meth:`merge_blockers` therefore finds no per-spec index there and
        returns ``[]`` — the merge gate keeps running on the shared checkout.

        Args:
            ledger_dir: Directory holding ``ledger.db`` and ``events.jsonl``.
            sqlite_policy: Connection policy for the ledger's SQLite plane.

        Returns:
            A ready-to-use ``LedgerService``.
        """
        ledger_dir = ledger_dir.resolve()
        ledger_dir.mkdir(parents=True, exist_ok=True)
        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=sqlite_policy)
        log = LedgerLog(str(ledger_dir / "events.jsonl"))
        index = LedgerIndex(store, log)
        return cls(index, store, log, ledger_dir.parent.parent)
```
**Why**: identical construction to `from_root()` (:135-140) so both factories yield indistinguishable services; the only differences are the origin of `ledger_dir` and of `shared_root`.

### FILL IN checklist
- [ ] none mechanical; confirm `LedgerStore(db_path: str, ...)` accepts a `Path` (store.py:27 — `from_root` already passes `ledger_dir / "ledger.db"`, so it does).

---

## Acceptance Criteria

- [ ] `LedgerService.from_dir(tmp_path / "srv" / ".parrot" / "ledger")` creates the directory and both files on first write; `open_issue` → `ready_work` → `claim` → `close_issue` round-trip works with no `.git` anywhere under `tmp_path`.
- [ ] `service.shared_root == (tmp_path / "srv").resolve()`.
- [ ] `await service.merge_blockers("FEAT-999")` returns `[]` (no index under `shared_root`).
- [ ] `from_root()` behaviour unchanged (existing ledger tests pass).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_from_dir.py -q`
- `pytest tests/knowledge/wiki/test_ledger_service.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_ledger_from_dir.py
import pytest
from parrot.knowledge.wiki.ledger.service import LedgerService


async def test_from_dir_roundtrip_without_git(tmp_path):
    ledger_dir = tmp_path / "srv" / ".parrot" / "ledger"
    svc = LedgerService.from_dir(ledger_dir)
    assert svc.shared_root == (tmp_path / "srv").resolve()
    issue_id = await svc.open_issue(title="t", body="b", kind="bug", severity="minor",
                                    discovered_from="spec:FEAT-569", about=[], actor="human:test")
    assert any(i["issue_id"] == issue_id for i in await svc.ready_work())   # FILL IN: exact key name from _issue_dict (service.py:78-93)
    assert await svc.claim(issue_id, "agent:test") is True
    assert await svc.close_issue(issue_id, "done", "agent:test") is True
    assert (ledger_dir / "ledger.db").exists() and (ledger_dir / "events.jsonl").exists()


async def test_merge_blockers_empty_without_index(tmp_path):
    svc = LedgerService.from_dir(tmp_path / ".parrot" / "ledger")
    assert await svc.merge_blockers("FEAT-999") == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `from_root()` still ends with `return cls(index, store, log, shared_root)`
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
