# TASK-4572: Insight generation and Telegram delivery

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4571
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6** — the insight path, independent of ingestion (G6). Folds
design-research **S9** (per-meeting working-memory scope) and the `GitHubReviewer`
Telegram pattern (escaping, chunking, never raising without a wrapper). Lesson carried
from ledger issue `7d1aeb70b417`: **every send failure must name the `chat_id`**.

**Correction to the spec §3 M6 skeleton:** it declared
`@telegram_command("fireflies_sync", description=...)` with a `cmd_sync(self, text: str)`
method. The decorator's default `parse_mode` is `"keyword"`, which calls `method(**kwargs)`
— so `/fireflies_sync` with no arguments would raise `TypeError` (missing `text`).
**Use `parse_mode="raw"`**, which calls `method(raw_args)` with `""` when empty
(`integrations/telegram/wrapper.py:797-800`).

---

## Scope

- `generate_insights(transcript, summary, meta) -> MeetingInsights` via
  `self._llm.invoke(prompt, output_type=MeetingInsights, system_prompt=...)` → `.output`.
- Working-memory scope (S9): store `meeting:<id>:transcript` / `meeting:<id>:summary`
  before the call, `drop_stored` both in a `finally`.
- `_format_insights_message`, `_chunk_message`, `set_wrapper`, `_get_telegram_bot`,
  `notify_insights`, `cmd_sync`.
- Insert the insight step into `sync_meetings` right after `processed.append(meeting)`,
  in its own `try/except` (G6), marking the registry analyzed / analysis-failed.

**NOT in scope**: approval ids and the ticket footer (TASK-4574 extends `notify_insights`);
Jira; the watcher.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | MODIFY | Insights via `invoke(output_type=)`, working-memory scope, Telegram delivery, `/fireflies_sync` |
| `packages/ai-parrot/tests/bots/test_fireflies_insights.py` | MODIFY | Insight / escaping / chunking / no-wrapper tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import html                                                                 # stdlib — escaping
from parrot.integrations.telegram import telegram_command                   # LAZY PEP 562 re-export → .decorators (decorators.py:5)
from parrot.models.responses import InvokeResult                            # verified: models/responses.py:1329 (type hints only)
```

### Existing Signatures to Use
```python
# clients/base.py:1916
async def invoke(self, prompt: str, *, output_type: Optional[type] = None,
                 structured_output: Optional[StructuredOutputConfig] = None, model: Optional[str] = None,
                 system_prompt: Optional[str] = None, max_tokens: Optional[int] = None, ...) -> InvokeResult
# InvokeResult carries the parsed `output` (models/responses.py:1329-1337)
# self._llm — the agent's AbstractClient, the attribute GitHubReviewer checks (packages/ai-parrot/src/parrot/bots/github_reviewer.py:929)
# tools/working_memory/tool.py
async def store_result(self, key: str, data: Any, data_type: str = "auto", description: str = "",
                       metadata: Optional[dict] = None, turn_id: Optional[str] = None) -> dict   # :374
async def drop_stored(self, key: str) -> dict                                                     # :408
# packages/ai-parrot/src/parrot/bots/github_reviewer.py
def set_wrapper(self, wrapper) -> None                                       # :882
def _get_telegram_bot(self): return getattr(self._wrapper, "bot", None)      # :1958
async def _notify_telegram_alert(...) -> Dict[str, Any]                      # :1925 — {"sent": 0, "reason": ...}, never raises
def _format_alert_message(...) -> str                                        # :1963 — every interpolation escaped
_TELEGRAM_MAX_MESSAGE = 4096                                                 # :2926
_TELEGRAM_PART_RESERVE = 32                                                  # :2929
def _chunk_digest_messages(self, entries: List[str], *, header: str) -> List[Tuple[str, int]]   # :2940 — pattern
#   bot.send_message(chat_id=..., text=..., parse_mode="HTML", disable_web_page_preview=True)
# integrations/telegram/decorators.py:5
def telegram_command(command: str, description: str = "", parse_mode: str = "keyword") -> Callable
# packages/ai-parrot/src/parrot/agents/meeting_registry.py: async def mark_analyzed(self, fireflies_id: str, fingerprint: str) -> None          # :526
#       async def mark_analysis_failed(self, fireflies_id: str, error: str) -> None         # :545
```

### Does NOT Exist
- ~~`self.llm.invoke`~~ / ~~`self.client.invoke`~~ on this agent — use `self._llm` and
  fail with a clear `RuntimeError` when it is `None`.
- ~~`GitHubReviewer._chunk_message`~~ — the reviewer's method is `_chunk_digest_messages`;
  this task writes its own `_chunk_message` following that pattern.
- ~~a Telegram user id in command context~~ — only the chat id is scoped
  (`telegram_chat_scope`, wrapper.py:789).

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
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._chunk_digest_messages",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._notify_telegram_alert",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/tool.py#WorkingMemoryToolkit.store_result",
    "sym:packages/ai-parrot/src/parrot/agents/meeting_registry.py#MeetingRegistry.mark_analyzed"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `import html` and the two imports — *why*: Verified Imports only.
2. Add the methods below to `FirefliesInsightsAgent`.
3. Insert the insight step after `processed.append(meeting)` — *why*: G6 isolation.
4. Tests.

### `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY — methods appended to `FirefliesInsightsAgent`)
```python
    _TELEGRAM_MAX_MESSAGE = 4096
    _TELEGRAM_PART_RESERVE = 32
    _INSIGHTS_SYSTEM_PROMPT = (
        "You extract decisions, risks/blockers and action items from a meeting. "
        "Quote evidence verbatim from the transcript. Never invent owners or dates."
    )

    async def generate_insights(self, transcript: str, summary: str, meta: dict[str, Any]) -> MeetingInsights:
        """Validated MeetingInsights via invoke(output_type=…); raises ValueError on bad output."""
        if self._llm is None:
            raise RuntimeError("FirefliesInsightsAgent has no LLM client configured")
        meeting_id = str(meta["fireflies_id"])
        keys = (f"meeting:{meeting_id}:transcript", f"meeting:{meeting_id}:summary")
        try:
            # FILL IN: if self.working_memory: store_result(keys[0], transcript) / store_result(keys[1], summary);
            #   build the prompt (title, date, summary, transcript); result = await self._llm.invoke(
            #   prompt, output_type=MeetingInsights, system_prompt=self._INSIGHTS_SYSTEM_PROMPT);
            #   not isinstance(result.output, MeetingInsights) -> raise ValueError  — bounded by AC10, S9
            raise NotImplementedError
        finally:
            if self.working_memory is not None:
                for key in keys:
                    await self.working_memory.drop_stored(key)

    def _format_insights_message(self, insights: MeetingInsights) -> str:
        """Telegram HTML; EVERY interpolation goes through html.escape."""
        # FILL IN: <b>title</b> · date, then <b>Decisions</b>, <b>Risks</b>, <b>Action items</b>
        #   (numbered; owner/due when present); omit empty sections — bounded by AC10
        raise NotImplementedError

    def _chunk_message(self, text: str) -> list[str]:
        """Split on line boundaries under 4096 − 32; label parts "(part n/m)" when > 1."""
        # FILL IN: follow packages/ai-parrot/src/parrot/bots/github_reviewer.py:2940-2990; a single over-long line is hard-split — bounded by AC10
        raise NotImplementedError

    def set_wrapper(self, wrapper: Any) -> None:
        """Called by TelegramAgentWrapper (integrations/telegram/wrapper.py:217)."""
        self._wrapper = wrapper

    def _get_telegram_bot(self) -> Any:
        """The wrapper's aiogram bot, or None."""
        return getattr(self._wrapper, "bot", None) if self._wrapper is not None else None

    async def notify_insights(self, insights: MeetingInsights) -> dict[str, Any]:
        """Send to public_channel_id; returns {"sent": n, ...} and NEVER raises (AC11)."""
        bot = self._get_telegram_bot()
        if bot is None:
            return {"sent": 0, "reason": "no telegram wrapper"}
        if not self.public_channel_id:
            return {"sent": 0, "reason": "no public_channel_id configured"}
        text = self._format_insights_message(insights)
        sent, errors = 0, []
        for chunk in self._chunk_message(text):
            try:
                await bot.send_message(chat_id=self.public_channel_id, text=chunk, parse_mode="HTML",
                                       disable_web_page_preview=True)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("FirefliesInsights: send to chat %s failed: %s", self.public_channel_id, exc)
                errors.append(f"{self.public_channel_id}: {exc}")
        return {"sent": sent, "errors": errors, "chat_id": self.public_channel_id}

    @telegram_command("fireflies_sync", description="Fetch and report the latest meetings", parse_mode="raw")
    async def cmd_sync(self, text: str = "") -> str:
        """On-demand run (C12, AC18); `/fireflies_sync 25` fetches up to 25."""
        limit = int(text) if text.strip().isdigit() else 10
        report = await self.sync_meetings(limit=limit)
        return (f"Fireflies: fetched={report.fetched} skipped={report.skipped} "
                f"dropped={report.dropped_to_inbox} sent={report.insights_sent} errors={len(report.errors)}")
```

### `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY — insight step inside `sync_meetings`)
```python
# occurrences: 1 (verified at task time: grep -cF '            processed.append(meeting)' packages/ai-parrot/src/parrot/bots/fireflies_insights.py — written by TASK-4571)
# AFTER — insert directly below `            processed.append(meeting)`
            try:
                insights = await self.generate_insights(
                    meeting.transcript, meeting.summary,
                    {"fireflies_id": meeting.fireflies_id, "title": meeting.title, "date": meeting.meeting_date},
                )
                delivery = await self.notify_insights(insights)
                report.insights_sent += int(delivery.get("sent", 0) > 0)
                if self.registry.available:
                    await self.registry.mark_analyzed(meeting.fireflies_id, meeting.fingerprint)
            except Exception as exc:  # noqa: BLE001 — G6: insights never block ingestion
                self.logger.error("FirefliesInsights: insights for %s failed: %s", meeting.fireflies_id, exc)
                report.errors.append(f"insights {meeting.fireflies_id}: {exc}")
                if self.registry.available:
                    await self.registry.mark_analysis_failed(meeting.fireflies_id, str(exc))
```
**Why**: the insight step runs only after the drop succeeded and is isolated in its own
`try`, so a malformed LLM answer never removes a meeting from the wiki (G6) and is never
sent to the channel (spec Edge Cases: "insights unavailable").

### FILL IN checklist
- [ ] `generate_insights` body; bounded by S9, AC10.
- [ ] `_format_insights_message`; bounded by AC10.
- [ ] `_chunk_message`; bounded by AC10.
- [ ] `packages/ai-parrot/tests/bots/test_fireflies_insights.py` tests below.

---

## Acceptance Criteria

- [ ] **AC10** A title like `<b>Q3 & "risks"</b>` is escaped; no chunk exceeds 4096 chars.
- [ ] **AC11** Without a wrapper `notify_insights` returns `{"sent": 0, "reason": "no telegram wrapper"}`.
- [ ] **AC18** `/fireflies_sync` and a scheduled call both reach `sync_meetings()`.
- [ ] **AC28** Two meetings in one run never see each other's working-memory keys (both dropped in `finally`).
- [ ] A send failure is logged with the chat id.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_fireflies_insights.py  (append)
def test_format_escapes_hostile_title(): ...
def test_chunk_never_exceeds_telegram_limit(): ...       # 10_000-char message
async def test_notify_without_wrapper_does_not_raise(): ...
async def test_generate_insights_drops_working_memory_keys(monkeypatch): ...   # fake _llm + fake WM
async def test_cmd_sync_with_empty_text_reaches_sync_meetings(monkeypatch): ...
async def test_bad_llm_output_is_reported_not_sent(monkeypatch): ...
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
   `feat(fireflies-insights-agent): TASK-4572 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4572 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
