# TASK-2349: Opt-in native Fireflies summary retrieval (`include_summary`)

**Feature**: FEAT-441 — Fireflies MCP Meeting Filters & Native Summary Retrieval
**Spec**: `sdd/specs/fireflies-mcp-improvements.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, the `fireflies-mcp-native-summary` capability. Today
`sync_fireflies_transcripts()` saves the raw transcript
(`fireflies_get_transcript`) but never calls Fireflies' own
`fireflies_get_summary` tool (AI-generated keywords/action items/overview).
The only summary path today is the separate, opt-in, LLM-powered
`summarize_transcript()` — this task adds a deterministic, no-LLM
alternative that reuses Fireflies' own computed summary instead.

This task is functionally independent of TASK-2346/2347/2348 (filters and
pagination) but is marked `parallel: false` in the per-spec index because
it modifies the same method (`sync_fireflies_transcripts()`) in the same
file — running it in a separate worktree from TASK-2348 would produce a
merge conflict, not a clean parallel merge (see spec Worktree Strategy).

---

## Scope

- Add a new class constant `FIREFLIES_SUMMARY_HEADING: str = "## Fireflies
  Summary"` on `FirefliesObsidianAgent`, alongside the existing
  `ANALYSIS_HEADING` constant (same pattern, same visibility).
- Add `include_summary: bool = False` parameter to
  `sync_fireflies_transcripts()`.
- In the per-meeting loop, immediately after the existing
  `_call_fireflies_tool("fireflies_get_transcript", {"transcriptId":
  transcript_id})` call: when `include_summary` is `True`, additionally
  call `_call_fireflies_tool("fireflies_get_summary", {"transcriptId":
  transcript_id})`.
  - On success (`tool_result.success` truthy): extract the raw response
    text (same `hasattr(result, "result")` pattern already used for the
    transcript) and append it as a new section using a new helper
    (`_append_fireflies_summary_section` or similar, modeled directly on
    `_append_analysis_section()`'s shape — `@staticmethod`, plain
    str-in/str-out) under `FIREFLIES_SUMMARY_HEADING`. **Do not parse the
    response into fields** — append the raw text verbatim (spec Non-Goals:
    field-level parsing of `fireflies_get_summary` is explicitly out of
    scope; its response layout is unverified).
  - On success, also set a boolean marker in the OKF metadata:
    `has_fireflies_summary: True`. Fold this into the dict already built
    by `_build_okf_frontmatter()` (or extend that function's return value)
    — do not change `_build_okf_frontmatter()`'s existing parameters or
    other output fields.
  - On failure (exception, or falsy `tool_result.success`): soft-fail —
    log via `self.logger`, append a message to `report["errors"]`, and
    continue exactly as if `include_summary` were `False` for this one
    meeting (no `## Fireflies Summary` section, no OKF marker, but the note
    IS still created from the transcript and still counts under
    `report["synced"]`).
- Write unit tests: `include_summary` omitted → zero
  `fireflies_get_summary` calls; `include_summary=True` success → section
  present + OKF marker set; `include_summary=True` failure → soft-fail
  behavior as specified.

**NOT in scope**:
- Any change to `summarize_transcript()` or `summarize_pending_transcripts()`
  — the LLM-powered path is untouched (spec Non-Goals).
- Any field-level parsing of the `fireflies_get_summary` response.
- A strip-on-resync helper for the new section — `skip_existing` means an
  already-synced note is never regenerated in this feature, so there is no
  "re-run with `include_summary=True` on an existing note" path to handle
  (spec §7 Known Risks — explicitly deferred).
- `fireflies_fetch` — never call it, for any reason (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/agents/obsidian.py` | MODIFY | `FIREFLIES_SUMMARY_HEADING` constant, `include_summary` param, summary call + section helper, OKF marker. |
| `packages/ai-parrot/tests/agents/test_obsidian.py` | MODIFY | Add tests for opt-in behavior, success path, soft-fail path. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports needed for this task beyond what already exists in obsidian.py.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/agents/obsidian.py:74
ANALYSIS_HEADING: str = "## Analysis"   # pattern to follow for FIREFLIES_SUMMARY_HEADING

# packages/ai-parrot/src/parrot/agents/obsidian.py:172-303 (sync_fireflies_transcripts —
# specifically the per-transcript block, lines ~248-291)
# Fetch full transcript (UNCHANGED — this task calls fireflies_get_summary
# right after this, not instead of it):
transcript_result = await self._call_fireflies_tool(
    "fireflies_get_transcript", {"transcriptId": transcript_id}
)
transcript_text = (
    transcript_result.result
    if hasattr(transcript_result, "result")
    else str(transcript_result)
)
# ... metadata dict, then:
okf_metadata = self._build_okf_frontmatter(
    fireflies_id=transcript_id, title=title, date=date,
    participants=transcript.get("participants", []),
    duration=transcript.get("duration", 0),
)
merged_metadata = {**metadata, **okf_metadata}
await self.obsidian_toolkit.create_note(
    path=f"{self.meetings_folder}/{note_title}.md",
    content=transcript_text,
    frontmatter=merged_metadata,
)

# packages/ai-parrot/src/parrot/agents/obsidian.py:520
@staticmethod
def _build_okf_frontmatter(
    fireflies_id: str, title: str, date: str,
    participants: List[str], duration: float,
) -> Dict[str, Any]: ...
    # Returns a dict with an 'okf' key (or {} on internal failure) — this
    # task's marker is a SIBLING key in the frontmatter dict this function's
    # caller builds (merged_metadata), NOT necessarily inside the 'okf'
    # sub-dict itself. Verify project_okf_block()'s node schema (imported
    # from parrot.interfaces.obsidian.okf) before deciding whether
    # has_fireflies_summary belongs inside the okf node's own fields or as
    # a plain top-level frontmatter key — prefer top-level (merged_metadata)
    # unless the OKF schema has an established place for arbitrary boolean
    # flags, to avoid fighting project_okf_block()'s own validation.

# packages/ai-parrot/src/parrot/agents/obsidian.py:666
async def _call_fireflies_tool(self, tool_name: str, args: Dict[str, Any]) -> Any: ...
    # Same call path — pass "fireflies_get_summary" as tool_name.

# packages/ai-parrot/src/parrot/agents/obsidian.py:841 — pattern reference
@staticmethod
def _append_analysis_section(
    transcript: str, summary: str,
    follow_ups: List[str], insights: List[str],
) -> str: ...
    # Model the new helper's shape on this (@staticmethod, str in/out) but
    # with different parameters — this task's helper only needs the raw
    # summary text, not summary/follow_ups/insights.
```

### Does NOT Exist
- ~~A `FIREFLIES_SUMMARY_HEADING` class constant~~ — does not exist yet.
- ~~An `include_summary` parameter on `sync_fireflies_transcripts()`~~ — does not exist yet.
- ~~Any call to `fireflies_get_summary` or `fireflies_fetch` anywhere in `obsidian.py`~~ — confirmed absent today.
- ~~A `has_fireflies_summary` field anywhere in `_build_okf_frontmatter()`'s output or `merged_metadata`~~ — does not exist yet.
- ~~Field-level parsing of `fireflies_get_summary`'s response (keywords, action_items, etc.)~~ — explicitly not to be added; the response is treated as opaque text (spec Non-Goals, §7).
- ~~A strip-on-resync helper for the Fireflies Summary section~~ — not needed for v1; do not add one speculatively.

---

## Implementation Notes

### Pattern to Follow
```python
class FirefliesObsidianAgent(BasicAgent):
    ANALYSIS_HEADING: str = "## Analysis"
    FIREFLIES_SUMMARY_HEADING: str = "## Fireflies Summary"   # NEW

    @staticmethod
    def _append_fireflies_summary_section(transcript: str, summary_text: str) -> str:
        """Append Fireflies' native summary as a distinct, unparsed section.

        Kept separate from _append_analysis_section()'s "## Analysis"
        block — this is Fireflies' own computed summary, not the agent's
        LLM-derived one.
        """
        return f"""{transcript}

---

{FirefliesObsidianAgent.FIREFLIES_SUMMARY_HEADING}

{summary_text}
"""
```
In the per-meeting loop, after the existing transcript fetch:
```python
has_summary = False
if include_summary:
    try:
        summary_result = await self._call_fireflies_tool(
            "fireflies_get_summary", {"transcriptId": transcript_id}
        )
        if summary_result and getattr(summary_result, "success", False):
            summary_text = (
                summary_result.result
                if hasattr(summary_result, "result")
                else str(summary_result)
            )
            transcript_text = self._append_fireflies_summary_section(
                transcript_text, summary_text
            )
            has_summary = True
        else:
            report["errors"].append(
                f"Fireflies summary unavailable for {transcript_id}"
            )
    except Exception as e:
        report["errors"].append(
            f"Failed to fetch Fireflies summary for {transcript_id}: {e}"
        )
# ... existing metadata/okf_metadata build ...
if has_summary:
    merged_metadata["has_fireflies_summary"] = True
```

### Key Constraints
- Never parse `fireflies_get_summary`'s response — verbatim text only.
- Never call `fireflies_fetch` as a shortcut.
- `include_summary` defaults to `False` — zero behavior/API-call change
  for every existing caller.
- A summary failure must NEVER prevent the note from being created from
  the transcript, and must NEVER remove the meeting from `report["synced"]`.
- Comprehensive logging via `self.logger` for both the success and failure
  paths (existing convention in this class).

### References in Codebase
- `sdd/specs/fireflies-mcp-improvements.spec.md` §2 Component Diagram, §3 Module 4, §7 Known Risks (summary response shape unverified — by-design mitigation).
- `packages/ai-parrot/src/parrot/agents/obsidian.py:841` `_append_analysis_section()` — direct pattern reference.

---

## Acceptance Criteria

- [ ] `FIREFLIES_SUMMARY_HEADING` class constant exists with value `"## Fireflies Summary"`.
- [ ] `include_summary` omitted (default `False`) → `_call_fireflies_tool` is never called with `"fireflies_get_summary"`.
- [ ] `include_summary=True` with a successful summary call → created note content contains `"## Fireflies Summary"` and the raw summary text; `merged_metadata`/frontmatter contains `has_fireflies_summary: True`.
- [ ] `include_summary=True` with a failing summary call → note still created from transcript alone, no summary section, no OKF marker, meeting still counted in `report["synced"]`, failure recorded in `report["errors"]`.
- [ ] No parsing of the summary response into discrete fields anywhere in the implementation.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/agents/test_obsidian.py -v -k Summary`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/agents/obsidian.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/agents/test_obsidian.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestIncludeSummary:
    @pytest.mark.asyncio
    async def test_default_off_no_summary_call(self, agent):
        agent._ensure_fireflies_mcp = AsyncMock()
        agent.obsidian_toolkit = AsyncMock()
        agent._get_existing_meeting_titles = AsyncMock(return_value=set())
        agent._call_fireflies_tool = AsyncMock(side_effect=[
            MagicMock(success=True, result='  - id: "id1"'),
            MagicMock(success=True, result="transcript text"),
        ])
        await agent.sync_fireflies_transcripts(limit=1)
        called_tools = [c.args[0] for c in agent._call_fireflies_tool.call_args_list]
        assert "fireflies_get_summary" not in called_tools

    @pytest.mark.asyncio
    async def test_include_summary_appends_section(self, agent):
        agent._ensure_fireflies_mcp = AsyncMock()
        agent.obsidian_toolkit = AsyncMock()
        agent._get_existing_meeting_titles = AsyncMock(return_value=set())
        agent._call_fireflies_tool = AsyncMock(side_effect=[
            MagicMock(success=True, result='  - id: "id1"'),
            MagicMock(success=True, result="transcript text"),
            MagicMock(success=True, result="native summary text"),
        ])
        await agent.sync_fireflies_transcripts(limit=1, include_summary=True)
        create_call = agent.obsidian_toolkit.create_note.call_args
        assert "## Fireflies Summary" in create_call.kwargs["content"]
        assert create_call.kwargs["frontmatter"].get("has_fireflies_summary") is True

    @pytest.mark.asyncio
    async def test_include_summary_soft_fails(self, agent):
        agent._ensure_fireflies_mcp = AsyncMock()
        agent.obsidian_toolkit = AsyncMock()
        agent._get_existing_meeting_titles = AsyncMock(return_value=set())
        agent._call_fireflies_tool = AsyncMock(side_effect=[
            MagicMock(success=True, result='  - id: "id1"'),
            MagicMock(success=True, result="transcript text"),
            Exception("summary fetch failed"),
        ])
        report = await agent.sync_fireflies_transcripts(limit=1, include_summary=True)
        assert report["synced"] == 1
        assert any("summary" in e.lower() for e in report["errors"])
        create_call = agent.obsidian_toolkit.create_note.call_args
        assert "## Fireflies Summary" not in create_call.kwargs["content"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fireflies-mcp-improvements.spec.md` for full context.
2. **Check dependencies** — none, but confirm whether TASK-2348 has already
   landed on your branch/worktree (same file, same method) — if so, base
   your edit on its current state and re-verify line numbers rather than
   the pre-TASK-2348 excerpt above.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `_append_analysis_section()`'s exact current signature.
   - Confirm `_build_okf_frontmatter()`'s current return shape.
4. **Update status** in the per-spec index → `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2349-native-summary-retrieval.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
