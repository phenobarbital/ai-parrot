# TASK-2663: Fetch-gate + scheduling (reuse FEAT-472, additive)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2660
**Assigned-to**: unassigned

---

## Context

Spec Module 2 + G2/G10. The agent's OWN participant-filtered fetch loop and the
dedup gate (never re-download a processed meeting). No edits to `agents/obsidian.py`.

## Scope

- `nodes/fetch_gate.py`: own fetch loop — inherit `add_fireflies_mcp_server` (`MCPEnabledMixin`), import `FirefliesFilters` (participant allowlist from `WIKI_KB_PARTICIPANTS`), own small `_call_fireflies_tool` helper.
- Gate: `MeetingRegistry.suggest_from_date(overlap_days=FIREFLIES_SYNC_OVERLAP_DAYS)` watermark + `MeetingRegistry.classify(...)` (∪ scan of `Raw/` ids) → fetch only unknown meetings. **No revisions** — known id is a permanent skip.
- Overrides: `force_refetch`, `since`, `lookback_days` for wide-window catch-up (bounded by `WIKI_KB_MAX_CATCHUP_DAYS`).
- Register the hourly cron (`WIKI_KB_INGEST_CRON`, default `"0 * * * *"`) on the agent.

**NOT in scope**: writing Raw bundles (TASK-2664), compilation.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/fetch_gate.py` | CREATE | fetch loop + dedup gate |
| `packages/ai-parrot/tests/unit/test_wiki_kb_fetch_gate.py` | CREATE | gate + watermark + catch-up tests |

## Codebase Contract (Anti-Hallucination)
### Verified Imports
```python
from parrot.agents.obsidian import FirefliesFilters          # agents/obsidian.py:50 (import only, no edit)
from parrot.agents.meeting_registry import MeetingRegistry    # agents/meeting_registry.py:167
from parrot.mcp.integration import MCPEnabledMixin            # mcp/integration.py:1341; add_fireflies_mcp_server:1447 (inherited via BasicAgent)
```
### Existing Signatures to Use
```python
# agents/meeting_registry.py
async def classify(self, item, *, fetch, fetch_summary, force_refetch=False) -> Classified  # :253
async def suggest_from_date(self, *, overlap_days: int) -> str | None                         # :370
# FirefliesFilters fields: from_date/to_date, keyword, organizers, participants, mine, channel_id  # :50
```
### Does NOT Exist
- ~~server-side "exclude processed" on `fireflies_get_transcripts`~~ — dedup is client-side.
- do NOT call or modify `FirefliesObsidianAgent.sync_fireflies_transcripts`.

## Implementation Notes
- Chronological handoff: emit fetched items so the orchestrator (TASK-2672) can sort oldest→newest.
- Small per-run batch via watermark; large batch only after downtime / manual override.

## Acceptance Criteria
- [ ] A processed `source_id` is skipped without an MCP transcript fetch.
- [ ] `from_date` derives from `suggest_from_date()`; `lookback_days`/`force_refetch` widen the window.
- [ ] Participant allowlist applied via `FirefliesFilters`.
- [ ] No edit to `agents/obsidian.py`; `ruff`/`mypy` clean.

## Test Specification
```python
async def test_skips_known_id_without_fetch(): ...
async def test_watermark_and_catchup_window(): ...
```

### Completion Note

`nodes/fetch_gate.py`: `run_fetch_gate(agent, *, registry, raw_processed_root=None, limit, force_refetch, since, lookback_days, api_key)` — own fetch loop (`_ensure_fireflies_mcp` lazily inherits `add_fireflies_mcp_server`; own `_call_fireflies_tool`; own `_parse_fireflies_listing`, which — unlike `FirefliesObsidianAgent._parse_fireflies_response` — preserves the full ISO `dateString` as `meeting_date_iso` so Module 8 can render the meeting's original-tz filename). Gate = `MeetingRegistry.classify()` ∪ `_scan_raw_processed_ids()` (walks `Raw/Processed/**/transcript.*`); `_resolve_from_date()` implements the `since` > `lookback_days` > `suggest_from_date()` precedence, every path clamped to `WIKI_KB_MAX_CATCHUP_DAYS` (G10 large-backlog guard — including an explicit `since`, per this task's own "bounded by WIKI_KB_MAX_CATCHUP_DAYS" wording). A `classify()` "revise" outcome (content changed for a known id) is mapped to `duplicate-skip`, never fetched/treated as an update (R3 — no revision workflow). `GatedMeeting` is this module's own result contract (not `models.py` — Module 5 is frozen; the fetch gate has no frontmatter/page-type shape).

No edit to `agents/obsidian.py` — only `FirefliesFilters` import reused (for participant-email validation).

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_fetch_gate.py` (9 passed — known-id skip without fetch, raw-scan skip without a `classify()` call, watermark precedence + max-catchup clamp, revise→duplicate-skip, create→transcript+summary fetch+hash, participant allowlist forwarded); `ruff check` clean; `mypy` clean on the new file.
