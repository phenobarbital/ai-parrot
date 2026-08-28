# TASK-2558: Integration tests — shared `wiki.db`, create→revise→analyse, vault upgrade

**Feature**: FEAT-472 — Fireflies Meeting Registry
**Spec**: `sdd/specs/fireflies-meeting-registry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2557
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and §7 "source_id is uuid5 of the original path".
The unit tasks prove each piece; these three tests prove the load-bearing
claims of the design: that the sync registry and the vault ingest really share
one row (G5), that the full create → revise → analyse → cheap-skip cycle holds
end to end, and that an existing vault upgrades without duplicates (G8).

---

## Scope

Create `tests/integration/test_fireflies_meeting_registry.py` with:

- `test_registry_shared_with_wiki_toolkit`: `FirefliesObsidianAgent(registry_dir=tmp)`
  syncs one stubbed transcript; then `LLMWikiToolkit(pageindex_toolkit=None,
  graphindex_toolkit=None, okf=None, WikiConfig(wiki_name="meetings", storage_dir=tmp, sync_graph=False))`
  runs `ingest_obsidian_vault("meetings", str(vault/"meetings"), incremental=True)`;
  assert the single `sources` row has `external_id == "fireflies:<id>"`,
  `doc_metadata["fireflies"]`, and non-empty `pages_generated`; then
  `registry.mark_wiki_ingested()` returns 1. Repeat after a repair move
  (rename the note on disk, sync again) and assert still **one** row.
- `test_end_to_end_create_revise_analyse`: stub MCP returns v1 → created; v2 same
  id → updated in place, `analysis_status == "pending"`; `summarize_pending_transcripts`
  with a stubbed `summarize_transcript` → `done` with the v2 fingerprint; sync v2
  again → cheap skip (no transcript fetch).
- `test_existing_vault_upgrade_no_duplicates`: fixture vault with 5 notes (one
  duplicated id) and no `wiki.db` → `configure()` backfills and merges (4 files
  left, report itemised); syncing the same 4 ids creates nothing.

Mark with the project's integration marker if one exists (check
`pyproject.toml` `[tool.pytest.ini_options]` markers); otherwise plain tests. No
network, no LLM, no ArangoDB.

**NOT in scope**: new production code. If a test exposes a defect, fix it in the
owning module and note it in the Completion Note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/test_fireflies_meeting_registry.py` | CREATE | three integration tests + fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.agents.obsidian import FirefliesObsidianAgent                 # agents/obsidian.py:185
from parrot.agents.meeting_registry import MeetingRegistry                # TASK-2554
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                  # toolkit.py:54
from parrot.knowledge.wiki.models import WikiConfig                       # models.py
from parrot.knowledge.wiki.sources import SourceCollectionManager         # sources.py:96
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                                   # :54
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf, config: WikiConfig, *, agent_id=..., ...)   # :83 — READ :83-140 for the exact positional order and which planes may be None
    # sqlite: self._sources = SourceCollectionManager(config.storage_dir/"sources", db_path=config.storage_dir/"wiki.db")   # :153-156
    async def ingest_obsidian_vault(self, wiki_name, vault_path, ..., incremental: bool = False, extract_entities=...)   # :295 — incremental → loader.incremental_update(self._pi, wiki_name, self._sources)  :333-338

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiConfig(BaseModel): wiki_name: str; storage_dir: Path; storage_backend: str = "sqlite"; sync_graph: bool; ...   # used at agents/fireflies_wiki.py:376-380 with (wiki_name, storage_dir, sync_graph)

# tests/knowledge/wiki/conftest.py — existing fixtures for a tmp wiki (pageindex stub etc.); REUSE them rather than rebuilding
# tests/knowledge/wiki/test_ingest.py — shows how ingest_obsidian_vault is driven in tests without an LLM
```

### Does NOT Exist
- ~~a `tests/integration/` directory for the Fireflies agents~~ — create it (check whether `tests/integration/` exists at all and follow its conftest if so).
- ~~an `ingest_obsidian_vault` folder filter~~ — pass the `meetings` subfolder path itself (as `agents/fireflies_wiki.py:596-612` does).
- ~~`LLMWikiToolkit` running with zero planes in every configuration~~ — verify at `toolkit.py:83-140` what a retrieval-only construction needs; `tests/knowledge/wiki/test_ingest.py` shows a working minimal setup.

---

## Implementation Notes

### Key Constraints
- All three tests must run in < 10 s total and touch no network.
- Reuse the `fake_fireflies` fixture pattern from `tests/test_fireflies_obsidian_sync.py` (TASK-2556) — import or copy into a local `conftest.py`.

### References in Codebase
- `tests/knowledge/wiki/conftest.py`, `tests/knowledge/wiki/test_ingest.py`
- `tests/test_fireflies_obsidian_sync.py` (TASK-2556)

---

## Acceptance Criteria

- [ ] `pytest tests/integration/test_fireflies_meeting_registry.py -v` passes.
- [ ] After sync + ingest on one `wiki.db`: exactly one `sources` row for the id with `external_id`, `doc_metadata.fireflies`, non-empty `pages_generated`; still one row after a rename + re-sync.
- [ ] End-to-end cycle asserts create → revise (in place) → analyse (fingerprint recorded) → cheap skip.
- [ ] Vault-upgrade test: 4 files remain, merge report itemised, no new notes on re-sync.

---

## Test Specification

```python
# tests/integration/test_fireflies_meeting_registry.py
async def test_registry_shared_with_wiki_toolkit(tmp_path, fake_fireflies): ...
async def test_end_to_end_create_revise_analyse(tmp_path, fake_fireflies, monkeypatch): ...
async def test_existing_vault_upgrade_no_duplicates(tmp_path, fake_fireflies): ...
```

---

## Agent Instructions

1. Read spec §4 and §7; 2. confirm TASK-2557 completed; 3. verify contract — read `LLMWikiToolkit.__init__` before constructing it; 4. mark in-progress; 5. implement; 6. run the three tests plus the full `tests/knowledge/wiki/` suite; 7. move to completed; 8. mark done; 9. Completion Note (list any production fixes made).

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
