# TASK-2662: Vault access layer — own toolkit, §11 init, §25 mirror, naming, link-fixup

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2660, TASK-2661
**Assigned-to**: unassigned

---

## Context

Spec Module 4 + the Obsidian-compatibility rules (§8). All vault writes go through here.
**Additive-only**: instantiate our OWN `ObsidianToolkit`; do NOT edit `tools/obsidian.py`.

## Scope

- `vault.py`: own `ObsidianToolkit(vault_path=WIKI_KB_VAULT_PATH, allowed_operations={read,list,search,create,update,move,delete})`.
- `naming.py`: Obsidian-safe filenames (§8.2) — Title-Case project folders, canonical entity/concept names, daily `YYYY-MM-DD.md`, meeting `YYYY-MM-DD - <Title> - <short-source-id>.md` where the **date is the meeting's original-timezone date, never the download time**; sanitize `/ \ : * ? " < > |`; alternates → `aliases`.
- **§8.1 link-fixup**: after `move_note`, rewrite `[[wikilinks]]` in `affected_backlinks` (move_note does NOT rewrite them itself).
- **§11 init**: create missing control files (`Wiki/index.md`, `overview.md`, `log.md`, `Review Queue.md`, `Registry/processed-sources.md`, folder indexes) without overwriting existing content; never touch `Private/`/`.obsidian/`.
- **§25 mirror**: regenerate `Wiki/Registry/processed-sources.md` from the `MeetingRegistry` DB every ingest (R1) — grep-friendly line format per §25.

**NOT in scope**: fetch, extraction, page compilation.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/vault.py` | CREATE | own toolkit + init + mirror |
| `.../wiki_ingest/naming.py` | CREATE | Obsidian-safe filename helpers |
| `packages/ai-parrot/tests/unit/test_wiki_kb_vault.py` | CREATE | naming, link-fixup, init, mirror tests |

## Codebase Contract (Anti-Hallucination)
### Verified Imports
```python
from parrot.tools.obsidian import ObsidianToolkit          # tools/obsidian.py:78
from parrot.agents.meeting_registry import MeetingRegistry  # agents/meeting_registry.py:167
```
### Existing Signatures to Use
```python
# tools/obsidian.py
async def create_note(self, path, content, frontmatter=None)          # :439
async def update_note(self, path, content, preserve_frontmatter=True) # :471
async def move_note(self, source, destination)                       # :538 — returns affected_backlinks; does NOT rewrite links
async def read_note(self, path, include_content=True)                # :212
async def list_notes(self, folder=…, recursive=…)                    # :257
```
### Does NOT Exist
- ~~`ObsidianToolkit` auto link-rewrite on move~~ — implement link-fixup here.
- ~~a §25 markdown-mirror writer in FEAT-472~~ — new here (DB is the authority).

## Implementation Notes
- Mirror is derived: overwrite-regenerate from DB rows each ingest; never hand-edit.
- Never write outside `Wiki//Projects//Diary/`.

## Acceptance Criteria
- [ ] Unsafe punctuation stripped; meeting filename uses meeting-tz date.
- [ ] `move_note` + link-fixup leaves no broken backlink.
- [ ] §11 init is idempotent (no overwrite); §25 mirror matches the DB.
- [ ] No edit to `tools/obsidian.py`; `ruff`/`mypy` clean.

## Test Specification
```python
def test_filename_sanitization_and_meeting_tz(): ...
async def test_move_note_link_fixup(): ...
async def test_init_idempotent_and_mirror_matches_db(): ...
```
