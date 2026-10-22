# TASK-4571: Atomic inbox drop, MeetingRegistry gate and sync_meetings

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4570
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5**, second half — the ingestion path. A meeting already handled is
never re-fetched (C13, via `MeetingRegistry`); each new meeting is written into the wiki
inbox **atomically** with a **dot-prefixed** temp name, which `InboxProcessor.discover()`
skips (`inbox/processor.py:167`) — the property AC2/AC5 rely on. Ingestion failures are
isolated (G6). The insight step is added after this task by TASK-4572 at the fixed
anchor line `            processed.append(meeting)`.

---

## Scope

- `_render_inbox_document(meeting) -> str`: markdown with YAML frontmatter carrying
  `fireflies_id: <id>` — because `detect_fireflies_id()` (`processor.py:119-129`) keys on
  `fireflies_id` metadata, which gives the wiki a stable external identity
  `fireflies:<id>` (S7) — plus `title`, `date`, `participants`; then `## Fireflies Summary`
  and `## Transcript` sections.
- `_inbox_filename(meeting) -> str`: `<YYYY-MM-DD>-<slug(title)>-<fireflies_id>.md`.
- `_drop_to_inbox(meeting) -> Path`: write `.<final name>.tmp` then `os.replace()` (sync;
  called via `asyncio.to_thread`).
- `sync_meetings(limit=10) -> InsightRunReport`: watermark → listing → `classify` →
  drop → `record_synced`; collect `processed`; every failure goes to `report.errors`,
  never raised (spec "Never raises into a scheduler").
- Degraded registry (`available is False`, AC8): skip a meeting whose inbox filename
  already exists, otherwise process it.

**NOT in scope**: insights / Telegram (TASK-4572 inserts them after
`processed.append(meeting)`); approvals (TASK-4574).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | MODIFY | Atomic inbox drop, MeetingRegistry gate, `sync_meetings` |
| `packages/ai-parrot/tests/bots/test_fireflies_insights.py` | MODIFY | Drop / gate / fallback tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio, os, re                                   # stdlib
from parrot.agents.meeting_registry import fingerprint   # verified: packages/ai-parrot/src/parrot/agents/meeting_registry.py:91
# FIREFLIES_SYNC_OVERLAP_DAYS already imported by TASK-4570
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/agents/meeting_registry.py
Classification = Literal["create", "skip", "revise"]                     # :57
async def suggest_from_date(self, *, overlap_days: int) -> str | None   # :370
async def classify(self, item: dict[str, Any], *, fetch: Callable[[str], Awaitable[str]],
                   fetch_summary: Callable[[str], Awaitable[str | None]] | None = None,
                   force_refetch: bool = False) -> Classified             # :253
class Classified(BaseModel):                                             # :130
    action: Classification; record: MeetingRecord | None; fetched_text: str | None
    fingerprint: str | None; summary_fingerprint: str | None
async def record_synced(self, *, fireflies_id: str, note_path: Path, title: str, meeting_date: str,
                        participants: list[str], duration_minutes: float, fingerprint: str,
                        summary_fingerprint: str | None, reset_analysis: bool) -> MeetingRecord   # :430
@property available -> bool                                              # :228
def fingerprint(text: str) -> str                                        # :91
# packages/ai-parrot/src/parrot/agents/obsidian.py:644-668 — the closure pattern: fetch / fetch_summary callables that CACHE the texts
#   they fetch, because Classified carries fingerprints but not the summary text.
# inbox/processor.py:119-129 detect_fireflies_id: metadata key in {"fireflies","fireflies_id","fireflies-id"}
```

### Does NOT Exist
- ~~`FirefliesWikiAgent`~~ / ~~`parrot/agents/fireflies_wiki.py`~~ — not on `dev` (FEAT-481's unmerged branch only).
- ~~`FirefliesObsidianAgent` as a base class~~ — it is a `BasicAgent` reference; only its
  `@staticmethod _parse_fireflies_response` is reused.
- ~~`sync_fireflies_transcripts()` returning transcripts~~ — it returns a report dict
  (`report["synced"]`, `report["errors"]`, `report["from_date"]`); the agent owns its fetch (S2).
- ~~`SkillRegistryMixin` activating itself in `configure()`~~ — **nothing in core calls
  it automatically** (only `bots/mixins/narrative.py:127` calls `_configure_skill_registry`).
  The agent must call `_configure_skill_file_registry()` itself.
- ~~`ChatId` importable from `github_reviewer`~~ — local alias; this module defines its own (TASK-4569).
- ~~`Classified.summary`~~ — only `summary_fingerprint`; cache the summary text yourself.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/fireflies_insights.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_fireflies_insights.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/agents/meeting_registry.py#MeetingRegistry.classify",
    "sym:packages/ai-parrot/src/parrot/agents/meeting_registry.py#MeetingRegistry.record_synced",
    "sym:packages/ai-parrot/src/parrot/agents/meeting_registry.py#MeetingRegistry.suggest_from_date",
    "sym:packages/ai-parrot/src/parrot/agents/meeting_registry.py#fingerprint"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the three helpers and `sync_meetings` as methods of `FirefliesInsightsAgent` — *why*: spec §3 M5.
2. Keep the line `            processed.append(meeting)` verbatim — *why*: TASK-4572 anchors on it.
3. Tests.

### `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY — methods appended to `FirefliesInsightsAgent`)
```python
    _SLUG_RE = re.compile(r"[^a-z0-9]+")

    def _inbox_filename(self, meeting: FirefliesMeeting) -> str:
        """<YYYY-MM-DD>-<slug>-<fireflies_id>.md — the id keeps names unique."""
        slug = self._SLUG_RE.sub("-", meeting.title.lower()).strip("-")[:60] or "meeting"
        return f"{meeting.meeting_date[:10]}-{slug}-{meeting.fireflies_id}.md"

    def _render_inbox_document(self, meeting: FirefliesMeeting) -> str:
        """Markdown + YAML frontmatter with fireflies_id (the wiki's external identity, S7)."""
        # FILL IN: frontmatter keys fireflies_id, title, date, participants (YAML list; quote/escape
        #   values safely — titles may contain ':' or quotes), then "## Fireflies Summary" (omit when
        #   empty) and "## Transcript" — bounded by processor.py:119-129
        raise NotImplementedError

    def _drop_to_inbox(self, meeting: FirefliesMeeting) -> Path:
        """Write <inbox>/.<name>.tmp then os.replace() onto the final name (AC2)."""
        if self.inbox_dir is None:
            raise RuntimeError("configure() must run before _drop_to_inbox()")
        final = self.inbox_dir / self._inbox_filename(meeting)
        tmp = self.inbox_dir / f".{final.name}.tmp"   # dot prefix: InboxProcessor.discover() skips it
        tmp.write_text(self._render_inbox_document(meeting), encoding="utf-8")
        os.replace(tmp, final)
        return final

    async def sync_meetings(self, limit: int = 10) -> InsightRunReport:
        """Fetch, gate on MeetingRegistry, drop atomically. Never raises — failures land in report.errors."""
        report = InsightRunReport()
        processed: list[FirefliesMeeting] = []
        try:
            await self._ensure_fireflies_mcp()
        except Exception as exc:  # noqa: BLE001 — scheduler-safe
            report.errors.append(f"fireflies mcp: {exc}")
            return report
        from_date = None
        if self.registry.available:
            from_date = await self.registry.suggest_from_date(overlap_days=FIREFLIES_SYNC_OVERLAP_DAYS)
        listing = await self._fetch_listing(limit, from_date)
        report.fetched = len(listing)
        for item in listing:
            try:
                meeting = await self._gate_meeting(item, report)
                if meeting is None:
                    continue
                path = await asyncio.to_thread(self._drop_to_inbox, meeting)
                report.dropped_to_inbox += 1
                # FILL IN: when self.registry.available, await self.registry.record_synced(...) with
                #   note_path=path and reset_analysis=(classification == "revise")
            except Exception as exc:  # noqa: BLE001 — G6: one meeting never sinks the run
                self.logger.error("FirefliesInsights: meeting %s failed: %s", item.get("id"), exc)
                report.errors.append(f"{item.get('id')}: {exc}")
                continue
            processed.append(meeting)
        return report

    async def _gate_meeting(self, item: dict[str, Any], report: InsightRunReport) -> FirefliesMeeting | None:
        """classify() → None for skip, else a populated FirefliesMeeting."""
        # FILL IN: closures that cache transcript/summary text (packages/ai-parrot/src/parrot/agents/obsidian.py:644-668 pattern);
        #   registry available -> classified = await self.registry.classify(item, fetch=..., fetch_summary=...);
        #   action "skip" -> report.skipped += 1, return None;
        #   registry unavailable (AC8) -> skip iff (inbox_dir / self._inbox_filename(<meeting>)).exists();
        #   fingerprint = classified.fingerprint or fingerprint(transcript); remember the action for record_synced
        raise NotImplementedError
```
**Why this shape**: the `try/except` wraps the whole per-meeting body so a malformed
listing item, a write error or a registry error costs one meeting, not the run. The
`processed.append(meeting)` line stays exactly as written: TASK-4572 inserts the insight
step directly after it.

### FILL IN checklist
- [ ] `_render_inbox_document` — safe YAML; bounded by processor.py:119-129.
- [ ] `sync_meetings` — `record_synced` call.
- [ ] `_gate_meeting` — caching closures, skip, degraded fallback (AC7, AC8).
- [ ] `packages/ai-parrot/tests/bots/test_fireflies_insights.py` tests below.

---

## Acceptance Criteria

- [ ] **AC1** One document per new meeting lands in `inbox_dir`, frontmatter carries `fireflies_id`.
- [ ] **AC2** No `.tmp` file survives a successful run.
- [ ] **AC7** A meeting the registry classifies `skip` is not re-fetched or re-dropped.
- [ ] **AC8** With `registry.available = False` the run completes, skipping existing filenames.
- [ ] A write failure on one meeting is recorded in `report.errors`; the next meeting is still processed.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_fireflies_insights.py  (append)
async def test_drop_is_atomic_and_leaves_no_tmp(tmp_path): ...
async def test_rendered_document_has_fireflies_id_frontmatter(tmp_path): ...
async def test_skip_classification_is_not_redropped(tmp_path, monkeypatch): ...  # fake registry
async def test_degraded_registry_skips_existing_file(tmp_path, monkeypatch): ...
async def test_one_failing_meeting_does_not_sink_the_run(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fireflies-insights-agent --feature-id FEAT-715`).
2. **Read the spec** `sdd/specs/fireflies-insights-agent.spec.md` — §3 (the module this task implements) and §6.
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/fireflies-insights-agent.json`.
4. **Verify the Codebase Contract** before writing code. Anchors were verified at
   `f6a4dbfca`; re-run every `grep -c` in the blueprint and use the fresh count.
   A count of `0` means the anchor moved — stop and report, never invent one.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker; never change a signature, class name or path the blueprint fixes.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (plus `packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`
   when the task imports them) — the shared venv is installed against the main
   checkout. Then `ruff check --fix` on every file you touched.
8. **Commit** only the files this task lists (never `git add .` / `-A`):
   `feat(fireflies-insights-agent): TASK-4571 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4571 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker; coder seat gpt-5.6-sol (codex, attempt 1, 193.9s)
**Date**: 2026-10-22
**Notes**: Added ingestion path: _ingest_meeting builds FirefliesMeeting from fetched data, writes to inbox, logs via MeetingRegistry. 90 passed merge-tier validation. No review fixes needed.

**Deviations from spec**: none
