# TASK-2664: Raw bundle layer — pairing, hashing, immutable moves (§13/§14/§27)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2663, TASK-2662
**Assigned-to**: unassigned

---

## Context

Spec Module 3. The deterministic provenance spine: drop fetched bundles into
`Raw/Incoming/`, pair them, hash them, move immutably to `Raw/Processed/`.

## Scope

- `nodes/raw_bundle.py`: write `transcript`/`summary`/`metadata` into `Raw/Incoming/` unchanged.
- Pair by strongest key (§13): Fireflies id → shared id in filenames → explicit refs → normalized stem+date+title; incomplete/ambiguous → `source-pairing` review item, leave raw untouched, continue.
- SHA-256 hash (reuse FEAT-472 `fingerprint`/`normalise_transcript` for the transcript; hash summary separately) — §14.2.
- Immutable move to `Raw/Processed/<Primary Client>/<Primary Project>/YYYY/MM/<source-id>/` (or `Uncategorized/` when classification is low-confidence — set by TASK-2665); verify pre/post-move hashes; never edit/overwrite/delete raw bytes.
- Duplicate route (§14.3): known id → `Raw/Processed/Duplicates/…`, `duplicate-skip` log, report skipped. **No revisions.**

**NOT in scope**: classification (TASK-2665), page compilation.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/raw_bundle.py` | CREATE | pairing + hashing + immutable moves |
| `packages/ai-parrot/tests/unit/test_wiki_kb_raw_bundle.py` | CREATE | hash-verify, pairing, dup-skip tests |

## Codebase Contract (Anti-Hallucination)
### Verified Imports
```python
from parrot.agents.meeting_registry import fingerprint, normalise_transcript  # :91 / :69
import hashlib  # stdlib — summary hash
```
### Notes
- Destination client/project come from TASK-2665's classification; default `Uncategorized/`.
- `Raw/Processed/Revisions/` does NOT exist (R3) — never create it.
### Does NOT Exist
- ~~a revision route / `revision-detected`~~ — removed (R3); a re-seen id is a skip.

## Implementation Notes
- Move via `shutil`/`pathlib` (raw files are outside Obsidian's page model). Verify hash equality after move; on mismatch, abort that bundle and report, do not proceed.

## Acceptance Criteria
- [ ] Pre/post-move hashes match; raw bytes never modified.
- [ ] Incomplete bundle → `source-pairing` review item, others continue.
- [ ] Known id → Duplicates + `duplicate-skip`; no `Revisions/` created.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_immutable_move_hash_verify(): ...
async def test_incomplete_bundle_review_item(): ...
async def test_known_id_duplicate_skip(): ...
```
