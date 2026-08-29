# TASK-2557: Wiki agent — `mark_wiki_ingested` stamp and Telegram `/sync` command

**Feature**: FEAT-472 — Fireflies Meeting Registry
**Spec**: `sdd/specs/fireflies-meeting-registry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2556
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, §2 "Wiki step" and "Telegram". Closes the lifecycle (G6) by
stamping `wiki_ingested_at` after the nightly ingest, and exposes
`force_refetch` (G9) through a new `/sync` command — there is no Telegram
`sync` command today, only `/note` (`agents/fireflies_wiki.py:260`).

> `agents/` is gitignored — commit with `git add -f agents/fireflies_wiki.py`.

---

## Scope

- `sync_meetings_to_wiki(self, limit=None, analysis_limit=None, force_refetch: bool = False)`:
  pass `force_refetch` to `sync_fireflies_transcripts`; after
  `_ingest_vault_into_wiki()` returns `{"ingested": True, ...}` and
  `self.registry` is available → `stamped = await self.registry.mark_wiki_ingested()`;
  `report["wiki"]["stamped"] = stamped`. Wiki `None` or ingest failed → no stamp.
- `@telegram_command("sync", description="Sync Fireflies meetings now", parse_mode="keyword")`
  `async def sync_now(self, force_refetch: str = "false", limit: str = "") -> str`:
  parse `force_refetch` (`true/1/yes`, case-insensitive) and `limit` (int or
  default), call `sync_meetings_to_wiki(...)`, reply with one line:
  `✅ synced N · revised R · skipped S · analysed A · wiki: ok/skipped` (errors count appended if any).
- Update `tests/test_fireflies_wiki_agent.py`: the ordering test asserts
  `mark_wiki_ingested` is called after ingest; add the two new tests.

**NOT in scope**: the digest jobs; `FirefliesObsidianAgent`; docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/fireflies_wiki.py` | MODIFY (`git add -f`) | stamp + `/sync` |
| `tests/test_fireflies_wiki_agent.py` | MODIFY | ordering + 2 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.decorators import telegram_command     # decorators.py:5 (already imported at agents/fireflies_wiki.py:66)
from parrot.agents.conf import FIREFLIES_WIKI_SYNC_LIMIT, FIREFLIES_WIKI_ANALYSIS_LIMIT   # conf.py:185-186 (already imported)
```

### Existing Signatures to Use
```python
# agents/fireflies_wiki.py
@register_agent(name="fireflies_wiki", at_startup=True)
class FirefliesWikiAgent(FirefliesObsidianAgent):                                   # :107
    self._wiki: Optional[Any]                                                       # :180
    self.registry: Optional[MeetingRegistry]                                        # inherited, TASK-2556
    @telegram_command("note", description="Capture the next message as a note")
    async def arm_note_mode(self, _args: str = "") -> str                           # :260-261 — pattern for a command method (returns the reply string)
    async def sync_meetings_to_wiki(self, limit=None, analysis_limit=None) -> Dict  # :519
        report = {"status","sync","analysis","wiki": {"ingested": False, "reason": None},"timestamp"}   # :549-555
        report["sync"] = await self.sync_fireflies_transcripts(limit=..., skip_existing=True)         # :556-559
        report["analysis"] = await self.summarize_pending_transcripts(granularity="standard", limit=...)   # :562-565
        report["wiki"] = await self._ingest_vault_into_wiki()                                           # :571
    async def _ingest_vault_into_wiki(self) -> Dict[str, Any]                       # :583 — {"ingested": bool, "reason": str|None, "report": ...}

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py
def telegram_command(command: str, description: str = "", parse_mode: str = "keyword") -> Callable   # :5-8
    # "keyword": `/cmd key=val key2=val2` → method(**kwargs); values are str        # :19

# packages/ai-parrot/src/parrot/agents/meeting_registry.py (TASK-2554)
async def mark_wiki_ingested(self, *, at: str | None = None) -> int

# packages/ai-parrot/src/parrot/agents/obsidian.py (TASK-2556)
async def sync_fireflies_transcripts(self, ..., force_refetch: bool = False) -> Dict   # report has synced/revised/skipped/errors
```

### Does NOT Exist
- ~~a `/sync` command~~ — this task creates it.
- ~~`sync_meetings_to_wiki(force_refetch=…)`~~ — this task adds it.
- ~~`report["wiki"]["stamped"]`~~ — this task adds it.
- ~~`telegram_command` passing typed args~~ — keyword values arrive as `str`.

---

## Implementation Notes

### Pattern to Follow
`arm_note_mode` (`:260-300`) for a command method: docstring, return a short string, never raise. `tests/test_fireflies_wiki_agent.py` for the `_schedule_config`/ordering assertion style.

### Key Constraints
- Stamp only when ingest reported success; never raise.
- Reply must be a single line (Telegram menu context).

---

## Acceptance Criteria

- [ ] `pytest tests/test_fireflies_wiki_agent.py -v` passes; `ruff check agents/fireflies_wiki.py`.
- [ ] Ordering: sync → summarize → ingest → `mark_wiki_ingested`.
- [ ] `self._wiki is None` or ingest failed → `mark_wiki_ingested` not called; run still `status == "ok"`.
- [ ] `sync_now(force_refetch="true", limit="5")` → `sync_meetings_to_wiki(limit=5, force_refetch=True)`; reply is one line.
- [ ] `sync_now._telegram_command["command"] == "sync"` (decorator metadata present).
- [ ] Committed with `git add -f agents/fireflies_wiki.py`.

---

## Test Specification

```python
# tests/test_fireflies_wiki_agent.py (additions/changes)
async def test_sync_meetings_to_wiki_marks_ingested(agent, monkeypatch): ...   # ordering incl. mark_wiki_ingested
async def test_sync_meetings_to_wiki_no_wiki_no_mark(agent, monkeypatch): ...
async def test_telegram_sync_command_parses_flags(agent, monkeypatch): ...
def test_sync_command_metadata(): ...
```

---

## Agent Instructions

1. Read spec §2 Wiki step / Telegram; 2. confirm TASK-2556 completed; 3. verify contract; 4. mark in-progress; 5. implement; 6. tests; 7. move to completed; 8. mark done; 9. Completion Note. Remember `git add -f`.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-29
**Notes**: `sync_meetings_to_wiki` gained `force_refetch: bool = False`
(forwarded to `sync_fireflies_transcripts`) and a fourth step after a
successful ingest: when `self.registry is not None and self.registry.available`,
`stamped = await self.registry.mark_wiki_ingested()` and
`report["wiki"]["stamped"] = stamped` (key absent entirely when the stamp
never ran — no wiki plane, ingest failed, or registry unavailable). Added
`@telegram_command("sync", description="Sync Fireflies meetings now",
parse_mode="keyword") async def sync_now(self, force_refetch: str = "false",
limit: str = "")`: parses `force_refetch` case-insensitively
(`true`/`1`/`yes`), parses `limit` as an int falling back to `None` (→
`sync_meetings_to_wiki`'s own `FIREFLIES_WIKI_SYNC_LIMIT` default) on an
empty or unparsable value, calls `sync_meetings_to_wiki(limit=..., force_refetch=...)`,
and replies with one line: `✅ synced N · revised R · skipped S · analysed A
· wiki: ok/skipped` with `· errors N` appended when sync+analysis errors are
non-zero. Updated the ordering test to also assert `mark_wiki_ingested` runs
LAST (after ingest) and stamps the report; added
`test_sync_meetings_to_wiki_no_wiki_no_mark`,
`test_sync_meetings_to_wiki_registry_unavailable_no_mark`,
`test_sync_meetings_to_wiki_forwards_force_refetch`, and a
`TestSyncNowCommand` class (flag parsing, defaults, error-count reporting,
unparsable-limit fallback, and `_telegram_command`/`discover_telegram_commands`
metadata). Also added `inst.registry = None` to the shared `agent` fixture
so `sync_meetings_to_wiki` doesn't need a registry attribute to exist by
default. 68 tests in `tests/test_fireflies_wiki_agent.py` (all, including
pre-existing) pass; `ruff check` on the diff introduces exactly one new
finding (`UP045 Optional[int]` in the new `sync_now` body), matching this
file's own dominant `Optional[X]` convention used throughout every other
signature — left as-is for consistency, not a regression in kind.
Committed with `git add -f agents/fireflies_wiki.py` (gitignored path).

**Deviations from spec**: none.
