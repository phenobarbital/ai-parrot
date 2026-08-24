# TASK-2378: Scope the nightly vault ingest to the meetings folder

**Feature**: FEAT-452 — Audio Notes → Obsidian + LLM Wiki
**Spec**: `sdd/specs/audio-notes-obsidian.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec (Goal G6).

`_ingest_vault_into_wiki()` currently ingests the **whole Obsidian vault** into
the *meetings* wiki. `ingest_obsidian_vault` has **no folder-filter parameter**
— scoping is done by passing a subdirectory as `vault_path`.

Once TASK-2380 starts writing captures to `audio-notes/`, the nightly job would
sweep them into the meetings wiki, defeating the whole point of a separate
notes plane. This is also a **pre-existing latent defect**: the meetings wiki
has been absorbing every unrelated note in the vault all along.

Independent of every other task — landable on its own.

---

## Scope

- In `_ingest_vault_into_wiki()`, change the `vault_path` argument passed to
  `ingest_obsidian_vault` from `str(self.vault_path)` to
  `str(self.vault_path / self.meetings_folder)`.
- Log the effective ingest path so the narrowing is visible in operations.
- Handle the case where `<vault>/<meetings_folder>` does not exist: return the
  established `{"ingested": False, "reason": ...}` shape rather than raising.
- Add a unit test to the existing agent test module.

**NOT in scope**: retroactively pruning non-meeting pages the meetings wiki has
already absorbed (explicitly declined — see spec §8, "leave as-is"); any change
to `ingest_obsidian_vault` itself; the notes wiki (TASK-2379).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/fireflies_wiki.py` | MODIFY | Narrow the `ingest_obsidian_vault` path argument |
| `tests/test_fireflies_wiki_agent.py` | MODIFY | Add a test asserting the scoped path |

> ⚠️ `agents/` is **gitignored** (`.gitignore:287`). Commit with `git add -f agents/fireflies_wiki.py`.

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-23 against `dev`.

### Verified Imports

```python
# No new imports needed for this task.
# Already at the top of agents/fireflies_wiki.py:
from pathlib import Path                 # line 34
```

### Existing Signatures to Use

```python
# agents/fireflies_wiki.py
class FirefliesWikiAgent(FirefliesObsidianAgent):          # line 165
    wiki_name: str                                          # line 208
    _wiki: Optional[Any]                                    # line 224 — None when unavailable

    async def _ingest_vault_into_wiki(self) -> Dict[str, Any]: ...   # line 411
        # Current body (lines 419-434):
        #   if self._wiki is None:
        #       self.logger.warning("Wiki plane unavailable — skipping ingest for this run.")
        #       return {"ingested": False, "reason": "wiki toolkit unavailable"}
        #   try:
        #       result = await self._wiki.ingest_obsidian_vault(   # line 425
        #           self.wiki_name,
        #           str(self.vault_path),          # <<< line 427 — THIS is what changes
        #           incremental=True,
        #           extract_entities=_EXTRACT_ENTITIES,
        #       )
        #       self.logger.info("Wiki ingest complete for %s", self.wiki_name)
        #       return {"ingested": True, "reason": None, "report": result}
        #   except Exception as exc:  # noqa: BLE001
        #       self.logger.warning("Wiki ingest failed: %s", exc)
        #       return {"ingested": False, "reason": str(exc)}

_EXTRACT_ENTITIES: bool = _bool_env("FIREFLIES_WIKI_EXTRACT_ENTITIES", False)   # line 155

# packages/ai-parrot/src/parrot/agents/obsidian.py
class FirefliesObsidianAgent(BasicAgent):                   # line 48
    vault_path: Path                                        # lines 96-100
    meetings_folder: str                                    # line 102 — default "meetings"
    # Precedent: the parent already composes paths this way, e.g.
    #   path=f"{self.meetings_folder}/{note_title}.md"      # line 284

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                      # line 46
    async def ingest_obsidian_vault(self, wiki_name: str, vault_path: str,
                                    incremental: bool = False,
                                    extract_entities: bool = False,
                                    granularity: str = "standard") -> dict[str, Any]: ...  # line 196
```

### Does NOT Exist

- ~~`ingest_obsidian_vault(..., folder=...)`~~ / ~~`subfolder=`~~ / ~~`include=`~~ /
  ~~`exclude=`~~ — **no folder-filter parameter exists.** The verified signature
  is `(wiki_name, vault_path, incremental, extract_entities, granularity)`.
  Scoping is achieved **only** by passing a subdirectory as `vault_path`.
- ~~`self.meetings_folder` is a `Path`~~ — it is a **`str`** (`obsidian.py:102`).
  Use `self.vault_path / self.meetings_folder`, then `str(...)`.
- ~~`FirefliesWikiAgent.meetings_folder`~~ is defined on the subclass — it is
  inherited from `FirefliesObsidianAgent` (`obsidian.py:102`).
- ~~a `prune` / `cleanup` method on `LLMWikiToolkit`~~ for removing already-ingested
  pages — out of scope regardless; do not attempt retroactive cleanup.

---

## Implementation Notes

### Key Constraints

- `_ingest_vault_into_wiki()` **must never raise** — it is called from the
  scheduled `sync_meetings_to_wiki` job. Preserve the existing
  `try/except Exception` and the `{"ingested": ..., "reason": ...}` return shape.
- Keep `extract_entities=_EXTRACT_ENTITIES` exactly as-is. Do **not** change it —
  entity extraction is an explicit non-goal of this feature (spec §1).
- Add a `self.logger.info` line naming the effective path, so an operator can
  see the narrowing took effect.
- A missing `<vault>/meetings` directory should return
  `{"ingested": False, "reason": "<something descriptive>"}`, not raise.

### References in Codebase

- `packages/ai-parrot/src/parrot/agents/obsidian.py:284` — existing `meetings_folder` path composition
- `tests/test_fireflies_wiki_agent.py` — existing test harness (see below)

---

## Acceptance Criteria

- [ ] `ingest_obsidian_vault` receives `<vault>/<meetings_folder>`, not `<vault>`
- [ ] `extract_entities=_EXTRACT_ENTITIES` is unchanged
- [ ] The method still never raises; a missing meetings folder returns
      `{"ingested": False, "reason": ...}`
- [ ] The effective ingest path is logged at INFO
- [ ] Tests pass: `pytest tests/test_fireflies_wiki_agent.py -v`
- [ ] No linting errors: `ruff check agents/fireflies_wiki.py`
- [ ] Committed with `git add -f agents/fireflies_wiki.py`

---

## Test Specification

```python
# tests/test_fireflies_wiki_agent.py  (EXTEND the existing module)
#
# The module already provides _load_agent_module() which imports the gitignored
# agents/fireflies_wiki.py BY PATH, plus a module-level skipif guard. Reuse them;
# do NOT invent a new import mechanism.

class TestVaultScoping:
    async def test_ingest_scoped_to_meetings_folder(self):
        """The nightly ingest targets <vault>/meetings, not the whole vault."""
        agent = _build_agent(vault_path="/tmp/vault", meetings_folder="meetings")
        agent._wiki = MagicMock()
        agent._wiki.ingest_obsidian_vault = AsyncMock(return_value={})

        await agent._ingest_vault_into_wiki()

        args, kwargs = agent._wiki.ingest_obsidian_vault.call_args
        assert args[1] == "/tmp/vault/meetings"      # NOT "/tmp/vault"

    async def test_extract_entities_unchanged(self):
        """Entity extraction stays at the module default (a non-goal of FEAT-452)."""

    async def test_missing_meetings_folder_reports_not_ingested(self):
        """A missing folder returns the not-ingested shape rather than raising."""
        result = await agent._ingest_vault_into_wiki()
        assert result["ingested"] is False
        assert result["reason"]

    async def test_never_raises_on_toolkit_error(self):
        """An ingest exception is swallowed into the report (existing behavior)."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 "Vault scoping (G6)", §3 Module 5
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `agents/fireflies_wiki.py:411-434`
   still matches the shape above; line numbers may have drifted
4. **Update status** in `sdd/tasks/index/audio-notes-obsidian.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2378-scope-nightly-vault-ingest-to-meetings.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: `_ingest_vault_into_wiki()` now computes
`meetings_path = self.vault_path / self.meetings_folder`, logs it at INFO
before ingesting, and passes `str(meetings_path)` to `ingest_obsidian_vault`
instead of `str(self.vault_path)`. `extract_entities=_EXTRACT_ENTITIES` is
unchanged. A missing meetings folder is checked with `meetings_path.is_dir()`
*inside* the existing `try/except Exception` block (so the method still
never raises) and returns `{"ingested": False, "reason": "meetings folder
not found: ..."}` without calling the toolkit. Updated the `agent` fixture
in `tests/test_fireflies_wiki_agent.py` to use a real `tmp_path`-backed
vault with a `meetings/` subdirectory (previously a non-existent
`/tmp/vault`), so every existing test — none of which asserted on the exact
vault path — keeps passing unchanged. Added `TestVaultScoping` (4 new
tests): scoped path, unchanged `extract_entities`, missing-folder handling,
and toolkit-exception containment. Full suite:
`pytest tests/test_fireflies_wiki_agent.py -v` → 31 passed. `ruff check
agents/fireflies_wiki.py` shows only pre-existing findings elsewhere in the
file (confirmed via diff against `dev`'s copy — zero new findings in the
touched lines). Committed with `git add -f agents/fireflies_wiki.py`.

**Deviations from spec**: none
