---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Fireflies MCP Meeting Filters & Native Summary Retrieval

**Feature ID**: FEAT-441
**Date**: 2026-08-21
**Author**: Arturo Martinez
**Status**: draft
**Target version**: (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

`FirefliesObsidianAgent.sync_fireflies_transcripts()`
(`packages/ai-parrot/src/parrot/agents/obsidian.py:172`) has two client-side
gaps against the Fireflies MCP tools it already has access to:

1. **No meeting filtering.** The method calls `fireflies_get_transcripts`
   with only `limit` — every other server-supported filter (date range,
   keyword/content search, organizer/participant emails, "mine only",
   channel/folder) is unreachable from the agent. A scheduled sync
   (`fireflies_daemon.yaml`, `scheduler.enabled: true`) or a manual run
   always pulls the *N* most recent meetings, full stop — no "only my
   1:1s," no "only last week's client calls," no "only meetings in the
   Sales channel."
2. **No native summary retrieval.** Fireflies' own AI-generated summary
   (`fireflies_get_summary` — keywords, action items, overview) is never
   called. Note: the raw transcript **is** already saved today via
   `fireflies_get_transcript` (`obsidian.py:249`) — that part is not
   broken. Only Fireflies' *native summary* is unavailable; today the only
   summary path is the separate, opt-in `summarize_transcript()` method,
   which re-derives a summary via the agent's own LLM
   (`self.client.complete(...)`, `obsidian.py:363`) instead of reading the
   one Fireflies already computed for free.

Both gaps are client-side: the underlying Fireflies MCP tools already
support this server-side (verified against the live tool schemas — see §6).

**Who is affected**: the operator running `FirefliesObsidianAgent` (today,
the repo owner via the example script `examples/agents/fireflies_obsidian_sync.py`
or the `agentd` daemon config `examples/agents/fireflies_daemon.yaml`).

### Goals
- Add structured, validated meeting filtering
  (date range, keyword/scope, organizer/participant emails, mine-only,
  channel) to `sync_fireflies_transcripts()`, via a new `FirefliesFilters`
  Pydantic model.
- Support fetching more meetings than the underlying API's 50-per-call cap
  transparently, via internal pagination — `limit` keeps its current
  meaning ("total transcripts I want"), not a page size.
- Let `FirefliesObsidianAgent`'s constructor (and therefore
  `fireflies_daemon.yaml`) declare a standing `default_filters` for
  unattended scheduled runs.
- Add opt-in retrieval of Fireflies' native per-meeting summary
  (`fireflies_get_summary`) into each synced note, clearly separated from
  the existing LLM-powered `summarize_transcript()` analysis.
- Preserve full backward compatibility: a caller that passes neither
  `filters` nor `include_summary` sees byte-for-byte the same behavior as
  today.

### Non-Goals (explicitly out of scope)
- Filtering through `fireflies_search`'s mini-grammar query string —
  rejected in brainstorm (`sdd/proposals/fireflies-mcp-improvements.brainstorm.md`,
  Option C) in favor of `fireflies_get_transcripts`'s structured kwargs.
- Using `fireflies_fetch` anywhere, for any purpose — Fireflies documents it
  as experimental/unreliable; explicit user decision to exclude it entirely,
  not merely deprioritize it.
- Resolving a human-readable channel name to a Fireflies `channelId` (via
  `fireflies_list_channels`) — caller must pass the raw ID.
- An enforced pagination ceiling — pagination continues until the
  underlying API returns an exhausted/short page, with no hard cap. This is
  an explicit, accepted risk (see §7 Known Risks), not an oversight.
- Field-level parsing of `fireflies_get_summary`'s response into discrete
  OKF attributes (keywords, action items, etc.) — its response text layout
  has not been observed live. This spec's design (§2, §7) treats the
  summary the same way the transcript is already treated: opaque text,
  saved verbatim, no field extraction. A follow-up feature can revisit this
  once a live response sample is available.
- Changing `summarize_transcript()` or `summarize_pending_transcripts()`
  in any way — the LLM-powered analysis path is untouched.

---

## 2. Architectural Design

### Overview

Two additive capabilities land in the same file/class, sequenced as one
feature:

1. **`fireflies-mcp-meeting-filters`**: a new `FirefliesFilters` Pydantic
   model, an optional `filters` parameter on `sync_fireflies_transcripts()`,
   an optional `default_filters` constructor kwarg on
   `FirefliesObsidianAgent`, and an internal pagination loop replacing
   today's single `fireflies_get_transcripts` call.
2. **`fireflies-mcp-native-summary`**: an optional `include_summary: bool =
   False` parameter on `sync_fireflies_transcripts()` that, when set, calls
   `fireflies_get_summary` per meeting (after the existing
   `fireflies_get_transcript` call) and appends its raw text as a new
   `## Fireflies Summary` note section, plus a lightweight boolean OKF
   marker (no field-level parsing — see Non-Goals).

Both are opt-in and additive; the existing single-call, transcript-only
path remains the default when neither `filters` nor `include_summary` is
passed.

### Component Diagram
```
caller (example script / agentd daemon / MCP invoke_method)
        │  filters?, include_summary?, limit, skip_existing
        ▼
FirefliesObsidianAgent.sync_fireflies_transcripts()
        │
        ├─ merge: default_filters (agent-level) ⊕ filters (call-level;
        │         call-level field wins where both set a value)
        │
        ├─ map FirefliesFilters → fireflies_get_transcripts kwargs
        │         (from_date→fromDate, to_date→toDate, channel_id→channelId;
        │          keyword/scope/organizers/participants/mine unchanged)
        │
        ├─ pagination loop ──→ _call_fireflies_tool("fireflies_get_transcripts", …)
        │         skip=0,50,100,… until len(page) < requested
        │         or running total == limit; page failure → stop looping,
        │         keep prior pages, record error
        │         └─→ _parse_fireflies_response()  (unchanged)
        │
        └─ per accumulated transcript (skip_existing dedup unchanged):
                 ├─→ _call_fireflies_tool("fireflies_get_transcript", …)   (unchanged)
                 ├─→ [if include_summary] _call_fireflies_tool("fireflies_get_summary", …)
                 │         success → append "## Fireflies Summary" section
                 │                   + OKF has_fireflies_summary marker
                 │         failure → soft-fail, log to report["errors"],
                 │                   note still created from transcript alone
                 ├─→ _build_okf_frontmatter()   (extended with the marker above)
                 └─→ obsidian_toolkit.create_note()   (unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FirefliesObsidianAgent.sync_fireflies_transcripts()` | extends | New `filters`, `include_summary` params; pagination loop replaces the single tool call. |
| `FirefliesObsidianAgent.__init__()` | extends | New `default_filters: Optional[FirefliesFilters] = None` kwarg. |
| `FirefliesObsidianAgent._call_fireflies_tool()` | uses (unchanged) | Same call path for `fireflies_get_transcripts`, `fireflies_get_transcript`, and the new `fireflies_get_summary` call. |
| `FirefliesObsidianAgent._parse_fireflies_response()` | uses (unchanged) | Still parses only the list-tool's `[N]: - id: ...` text; not applied to the summary response. |
| `FirefliesObsidianAgent._build_okf_frontmatter()` | extends | Optional `has_fireflies_summary` field folded in when a summary was fetched. |
| `FirefliesObsidianAgent.ANALYSIS_HEADING` class constant / `_strip_analysis_section()` pattern | mirrors | New `FIREFLIES_SUMMARY_HEADING` constant follows the same naming pattern; no strip-on-resync helper needed for v1 since `skip_existing` means a synced note is never regenerated (see §7). |
| `examples/agents/fireflies_daemon.yaml` | extends | New optional `agent.kwargs.default_filters` block, documented. |
| `parrot/mcp/integration.py` (`create_fireflies_mcp_server` / `add_fireflies_mcp_server`) | none | Unaffected — this feature is entirely about the sync-time tool *call*, not MCP connection/auth. |
| `parrot/mcp/registry.py` (`fireflies` descriptor) | none | Unaffected, same reason. |

### Data Models

```python
from pydantic import BaseModel, Field, EmailStr
from typing import Literal, Optional

class FirefliesFilters(BaseModel):
    """Structured, validated filters over the fireflies_get_transcripts
    MCP tool. Field names are snake_case; sync_fireflies_transcripts()
    maps them to the tool's camelCase parameter names before the call.
    """
    from_date: Optional[str] = None     # → fromDate (ISO-8601, e.g. "2023-01-01")
    to_date: Optional[str] = None       # → toDate
    keyword: Optional[str] = Field(default=None, max_length=255)
    scope: Literal["title", "sentences", "all"] = "all"
    organizers: list[EmailStr] = Field(default_factory=list)
    participants: list[EmailStr] = Field(default_factory=list)
    mine: Optional[bool] = None
    channel_id: Optional[str] = None    # → channelId; raw ID only, no name resolution
```

- `from_date`/`to_date` are kept as plain `Optional[str]`, not a `date`
  type — the underlying tool takes an ISO-8601 *string*, and round-tripping
  through `datetime.date` would only add a formatting step with no
  validation benefit the tool doesn't already provide itself.
- `organizers`/`participants` use `pydantic.EmailStr` (resolved decision —
  see §8). **This requires a new dependency**: `email-validator` is not
  currently installed (verified — `pydantic.EmailStr` raises `ImportError:
  email-validator is not installed` in the current environment). See §7
  External Dependencies.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/agents/obsidian.py

class FirefliesObsidianAgent(BasicAgent):
    def __init__(
        self,
        name: str = "FirefliesObsidianSync",
        vault_path: Optional[str | Path] = None,
        fireflies_token: Optional[str] = None,
        meetings_folder: str = "meetings",
        default_filters: Optional["FirefliesFilters"] = None,   # NEW
        **kwargs,
    ): ...

    async def sync_fireflies_transcripts(
        self,
        limit: int = 10,
        skip_existing: bool = True,
        filters: Optional["FirefliesFilters"] = None,      # NEW
        include_summary: bool = False,                      # NEW
    ) -> Dict[str, Any]: ...
```

---

## 3. Module Breakdown

### Module 1: `FirefliesFilters` model + field-name mapping
- **Path**: `packages/ai-parrot/src/parrot/agents/obsidian.py`
- **Responsibility**: Define `FirefliesFilters` (see §2 Data Models) and a
  small mapping helper (e.g. `_filters_to_tool_args(filters:
  FirefliesFilters) -> Dict[str, Any]`) that converts snake_case fields to
  the tool's camelCase parameter names and drops unset/`None`/empty-list
  fields.
- **Depends on**: `pydantic.EmailStr` → `email-validator` dependency (see
  §7).

### Module 2: Constructor `default_filters` + merge precedence
- **Path**: `packages/ai-parrot/src/parrot/agents/obsidian.py`
- **Responsibility**: New `default_filters: Optional[FirefliesFilters] =
  None` constructor kwarg, stored as `self.default_filters`. A merge helper
  (e.g. `_merge_filters(default, call) -> Optional[FirefliesFilters]`)
  combines `self.default_filters` and the per-call `filters` argument:
  per-call field wins wherever it is explicitly set; the agent default
  fills in any field the call left at its unset/default value (resolved
  decision — see §8).
- **Depends on**: Module 1.

### Module 3: Internal pagination loop
- **Path**: `packages/ai-parrot/src/parrot/agents/obsidian.py`
- **Responsibility**: Replace `sync_fireflies_transcripts()`'s single
  `_call_fireflies_tool("fireflies_get_transcripts", {"limit": limit})`
  call with a loop: merged filter args + `limit=min(50, remaining)` +
  increasing `skip` (`0, 50, 100, …`), accumulating parsed transcripts via
  the unchanged `_parse_fireflies_response()`, until either the running
  total reaches the caller's `limit` or a page returns fewer transcripts
  than requested (API exhausted). A page-fetch failure stops further
  pagination, keeps transcripts already accumulated, and appends the
  failure to `report["errors"]` — `report["status"]` stays `"ok"` (partial
  result), matching the existing per-transcript error-handling pattern.
  No hard ceiling on total pages/transcripts (explicit accepted risk).
- **Depends on**: Modules 1–2.

### Module 4: Native summary retrieval (`include_summary`)
- **Path**: `packages/ai-parrot/src/parrot/agents/obsidian.py`
- **Responsibility**: New `include_summary: bool = False` parameter. When
  `True`, immediately after the existing `fireflies_get_transcript` call
  for a meeting, additionally call `_call_fireflies_tool
  ("fireflies_get_summary", {"transcriptId": transcript_id})`. On success,
  append a new `## Fireflies Summary` section (raw response text, verbatim
  — no field parsing, per Non-Goals) via a new helper mirroring
  `_append_analysis_section()`'s pattern, and fold a boolean
  `has_fireflies_summary: true` marker into `_build_okf_frontmatter()`'s
  output. On failure, soft-fail: log to `report["errors"]`, still create
  the note from the transcript alone, still count the meeting under
  `report["synced"]`.
- **Depends on**: none of Modules 1–3 (orthogonal to filtering/pagination);
  implemented alongside them because both touch `sync_fireflies_transcripts()`.

### Module 5: `fireflies_daemon.yaml` documentation
- **Path**: `examples/agents/fireflies_daemon.yaml`
- **Responsibility**: Add a commented example `default_filters:` block
  under `agent.kwargs` (e.g. `mine: true`) so an operator scheduling the
  daemon knows the option exists. Documentation-only; no code dependency.
- **Depends on**: Module 2.

---

## 4. Test Specification

> Existing test file: `packages/ai-parrot/tests/agents/test_obsidian.py`
> (class-based, `pytest.mark.asyncio`, `agent`/`vault_path` fixtures,
> `AsyncMock` on `agent._call_fireflies_tool` / `agent.obsidian_toolkit`) —
> new tests follow these conventions, not new fixtures.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_filters_valid_construction` | 1 | `FirefliesFilters(...)` with valid fields constructs without error. |
| `test_filters_rejects_bad_scope` | 1 | `scope="invalid"` raises `pydantic.ValidationError`. |
| `test_filters_rejects_malformed_email` | 1 | `organizers=["not-an-email"]` raises `pydantic.ValidationError` (EmailStr). |
| `test_filters_map_to_tool_args` | 1 | Field-mapping helper produces exactly `fromDate`/`toDate`/`channelId` for `from_date`/`to_date`/`channel_id`; unset fields are absent from the resulting dict. |
| `test_default_filters_fill_unset_fields` | 2 | `default_filters=FirefliesFilters(channel_id="X")`, per-call `filters=FirefliesFilters(mine=True)` → merged args carry both `channelId="X"` and `mine=True`. |
| `test_call_filters_override_default_on_same_field` | 2 | `default_filters=FirefliesFilters(mine=False)`, per-call `filters=FirefliesFilters(mine=True)` → merged `mine` is `True`. |
| `test_sync_paginates_beyond_50` | 3 | `_call_fireflies_tool` mocked to return 2 pages (50 + 20 transcripts) for `limit=70`; assert both pages requested (`skip=0`, `skip=50`) and `report["synced"] == 70`. |
| `test_sync_stops_on_short_page` | 3 | First page returns fewer transcripts than requested → loop stops without a second call. |
| `test_sync_limit_caps_total_not_page_size` | 3 | `limit=10` with filters set → single page request has `limit=10`, not 50. |
| `test_pagination_partial_failure_keeps_prior_pages` | 3 | Page 1 succeeds (50 transcripts), page 2's `_call_fireflies_tool` raises → `report["errors"]` contains the failure, `report["synced"]` reflects only page 1's (deduped) transcripts, `report["status"] == "ok"`. |
| `test_include_summary_appends_section` | 4 | `include_summary=True`, `fireflies_get_summary` mocked to succeed → created note content contains `"## Fireflies Summary"`; OKF frontmatter carries `has_fireflies_summary: True`. |
| `test_include_summary_default_off_no_extra_call` | 4 | `include_summary` omitted → `_call_fireflies_tool` is never called with `"fireflies_get_summary"`. |
| `test_include_summary_soft_fails_on_summary_error` | 4 | `fireflies_get_summary` call raises → note is still created (transcript only, no summary section), `report["synced"]` still counts it, `report["errors"]` records the failure. |
| `test_sync_no_filters_unchanged_behavior` (regression) | 1–3 | No `filters`, no `include_summary` → identical `_call_fireflies_tool` args and note content to pre-feature behavior (guards backward compatibility). |

### Integration Tests
| Test | Description |
|---|---|
| `test_sync_with_filters_and_summary_end_to_end` | Full `sync_fireflies_transcripts(limit=..., filters=..., include_summary=True)` against mocked `_call_fireflies_tool`/`obsidian_toolkit`, asserting the final `report` shape and note frontmatter/content together. |

### Test Data / Fixtures
```python
# Reuses existing fixtures from test_obsidian.py — no new fixtures needed.
@pytest.fixture
def vault_path(tmp_path):
    vault = tmp_path / "test_vault"
    vault.mkdir()
    (vault / "meetings").mkdir()
    return vault

@pytest.fixture
def agent(vault_path):
    return FirefliesObsidianAgent(
        name="TestFirefliesAgent",
        vault_path=str(vault_path),
        fireflies_token="test-token-12345",
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `FirefliesFilters` Pydantic model exists with fields `from_date`,
      `to_date`, `keyword`, `scope`, `organizers`, `participants`, `mine`,
      `channel_id`, matching the types in §2 Data Models.
- [ ] `sync_fireflies_transcripts(filters=None)` (i.e. omitted) produces
      identical `_call_fireflies_tool` arguments and note output to today's
      behavior — no regression for existing callers.
- [ ] Passing `filters=FirefliesFilters(...)` maps to the correct
      camelCase `fireflies_get_transcripts` arguments, dropping unset
      fields.
- [ ] `FirefliesObsidianAgent(default_filters=...)` merges with a per-call
      `filters` such that per-call fields win and default fields fill in
      what the call left unset.
- [ ] A `limit` greater than 50 transparently triggers multiple
      `fireflies_get_transcripts` calls (`skip=0,50,…`) until either
      `limit` is reached or the API returns a short/empty page.
- [ ] A page-fetch failure mid-pagination preserves transcripts from prior
      successful pages, records the failure in `report["errors"]`, and
      leaves `report["status"] == "ok"`.
- [ ] `sync_fireflies_transcripts()`'s docstring documents that pagination
      has no enforced ceiling (accepted risk, not a bug).
- [ ] `include_summary=False` (default) issues zero
      `fireflies_get_summary` calls.
- [ ] `include_summary=True` appends a `## Fireflies Summary` section
      (raw text, unparsed) to the note and sets `has_fireflies_summary:
      true` in the note's OKF frontmatter, on a successful summary call.
- [ ] A failed `fireflies_get_summary` call under `include_summary=True`
      soft-fails: the note is still created from the transcript, the
      meeting still counts under `report["synced"]`, and the failure is
      recorded in `report["errors"]`.
- [ ] `fireflies_fetch` is not referenced anywhere in the implementation.
- [ ] `email-validator` is added to `packages/ai-parrot/pyproject.toml`
      dependencies (required for `pydantic.EmailStr`).
- [ ] `examples/agents/fireflies_daemon.yaml` documents the
      `default_filters` constructor option.
- [ ] All unit tests pass:
      `pytest packages/ai-parrot/tests/agents/test_obsidian.py -v`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references below verified by `read`/`grep` on branch `dev` on
> 2026-08-21. Line numbers differ from the brainstorm document (which was
> verified against `main` — `dev`'s `obsidian.py` has since grown from 656
> to 867 lines with unrelated features: `configure()`, batch
> `summarize_pending_transcripts()`, `_strip_analysis_section()`, etc.).
> The references below supersede the brainstorm's line numbers.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/agents/obsidian.py:11-22 (already present)
import os
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path, PurePosixPath
import logging
from navconfig import config
from parrot.bots.agent import BasicAgent
from parrot.tools.obsidian import ObsidianToolkit
from parrot.models.responses import AIMessage
from parrot.interfaces.obsidian.okf import project_okf_block
from parrot.knowledge.okf.ontology import ConceptType, RelationType

# NEW for this feature — not yet imported in obsidian.py:
from pydantic import BaseModel, Field, EmailStr
from typing import Literal
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/agents/obsidian.py:48
class FirefliesObsidianAgent(BasicAgent):
    ANALYSIS_HEADING: str = "## Analysis"                     # line 74

    def __init__(                                             # line 76
        self,
        name: str = "FirefliesObsidianSync",
        vault_path: Optional[str | Path] = None,
        fireflies_token: Optional[str] = None,
        meetings_folder: str = "meetings",
        **kwargs,
    ):
        # vault_path falls back to OBSIDIAN_VAULT_PATH (navconfig/env),
        # then ~/vaults/notes if omitted (lines 95-100).
        ...

    async def configure(self, app=None) -> None:               # line 120
        # Eagerly calls self._ensure_fireflies_mcp() at agent boot
        # (warning-only on failure) — unaffected by this feature.
        ...

    async def _ensure_fireflies_mcp(self) -> None: ...          # line 148

    async def sync_fireflies_transcripts(                      # line 172
        self,
        limit: int = 10,
        skip_existing: bool = True,
    ) -> Dict[str, Any]:
        # report dict now includes a "notes": [] key (list of synced note
        # titles, line 199) — NOT present in the brainstorm's main-branch
        # reference. This feature's pagination changes MUST preserve this
        # key; summarize_pending_transcripts() (line 392) depends on it.
        # Current single call (line 211-214):
        #   await self._call_fireflies_tool(
        #       "fireflies_get_transcripts", {"limit": limit}
        #   )
        ...

    async def summarize_transcript(self, note_title: str, granularity: str = "standard") -> Dict[str, Any]: ...  # line 305
    async def summarize_pending_transcripts(                   # line 392
        self,
        note_titles: Optional[List[str]] = None,
        granularity: str = "standard",
        limit: Optional[int] = None,
        force: bool = False,
    ) -> Dict[str, Any]: ...
        # Batch-wraps summarize_transcript() over report['notes'] or the
        # whole vault. Unrelated to this feature — do not confuse with
        # Module 4's native-summary retrieval (this is the LLM path).

    @classmethod
    def _strip_analysis_section(cls, content: str) -> str: ...  # line 476
        # Pattern reference for Module 4 IF a strip-on-resync helper is
        # ever needed — not required for v1 (see §7).

    async def _has_analysis(self, note_title: str) -> bool: ...  # line 496

    @staticmethod
    def _build_okf_frontmatter(                                 # line 520
        fireflies_id: str, title: str, date: str,
        participants: List[str], duration: float,
    ) -> Dict[str, Any]: ...
        # Module 4 extends this (or wraps its output) with an optional
        # has_fireflies_summary marker.

    @staticmethod
    def _parse_fireflies_response(response_text: str) -> List[Dict[str, Any]]: ...  # line 582
        # Parses ONLY fireflies_get_transcripts' "[N]: - id: ..." text.
        # NOT applied to fireflies_get_transcript or fireflies_get_summary
        # responses (both saved/appended as opaque text).

    async def _call_fireflies_tool(                             # line 666
        self, tool_name: str, args: Dict[str, Any],
    ) -> Any:
        # full_name = f"mcp_fireflies_{tool_name}"
        # tool = self.tool_manager.get_tool(full_name)
        # result = await tool.execute(**args)
        ...

    async def _get_existing_meeting_titles(self) -> set[str]: ...  # line 692

    @staticmethod
    def _make_note_title(date: str, meeting_title: str) -> str: ...  # line 728

    @staticmethod
    def _build_analysis_prompt(transcript_text: str, granularity: str = "standard") -> str: ...  # line 758

    @staticmethod
    def _parse_analysis_response(llm_response: AIMessage) -> Dict[str, Any]: ...  # line 805

    @staticmethod
    def _append_analysis_section(                                # line 841
        transcript: str, summary: str,
        follow_ups: List[str], insights: List[str],
    ) -> str:
        # Pattern reference for Module 4's new "## Fireflies Summary"
        # section-append helper — same shape (staticmethod, str in, str
        # out), different heading constant.
        ...

# Total file length: 867 lines (verified 2026-08-21 on dev).
```

### Fireflies MCP Tool Parameters — `fireflies_get_transcripts` (verified against the live tool schema)
- `channelId: str` — channel/folder ID (no name resolution in this feature).
- `date: number` — **deprecated**, do not use.
- `fromDate: str` / `toDate: str` — ISO-8601 dates.
- `keyword: str` (max 255 chars).
- `limit: number` — **max 50 per call** (why Module 3's pagination loop is required for any `limit > 50`).
- `mine: boolean`.
- `organizers: string[]` / `participants: string[]` — email format.
- `scope: "title" | "sentences" | "all"`.
- `skip: number` — pagination offset.
- `format: "toon" | "json" | "text"` — response shape; existing code relies on the tool's default (`"toon"`), matching `_parse_fireflies_response()`. Not part of `FirefliesFilters`.

### Fireflies MCP Tool Parameters — `fireflies_get_summary` (verified against the live tool schema)
- `transcriptId: str` (required) — the only parameter.
- Description: "Fetches meeting summary by ID... Returns summary data
  (keywords, action items, overview, etc.) and basic metadata, but excludes
  transcript content."
- **Response text layout unverified live** — this feature's design
  therefore treats the response as opaque text (see Non-Goals, §7),
  avoiding any dependency on an unconfirmed field layout.

### Fireflies MCP Tool — `fireflies_fetch` (exists; intentionally excluded)
- Schema: `id: str` (required) → combined transcript + summary + metadata.
- Documented by Fireflies as experimental/unreliable. Explicit user decision
  to exclude entirely — **must not** be used as a shortcut for Module 3 or
  Module 4.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FirefliesFilters` (new) | `fireflies_get_transcripts` tool args | field-name mapping helper | `obsidian.py:211-214` (call site to be modified) |
| `default_filters` kwarg (new) | `FirefliesFilters` | constructor field | `obsidian.py:76-83` (constructor to be extended) |
| pagination loop (new) | `_call_fireflies_tool` / `_parse_fireflies_response` | repeated calls, accumulate | `obsidian.py:666`, `obsidian.py:582` |
| `include_summary` path (new) | `_call_fireflies_tool("fireflies_get_summary", ...)` | same call path, new tool name | `obsidian.py:666` |
| Fireflies-summary section helper (new) | note content | modeled on `_append_analysis_section()` | `obsidian.py:841` |
| OKF marker (new) | `_build_okf_frontmatter()` output | dict merge | `obsidian.py:520-579` |

### Does NOT Exist (Anti-Hallucination)
- ~~A `filters` / `FirefliesFilters` parameter on `sync_fireflies_transcripts()`~~ — does not exist; current signature is exactly `(limit: int = 10, skip_existing: bool = True)` (`obsidian.py:172-176`).
- ~~A `default_filters` constructor kwarg on `FirefliesObsidianAgent`~~ — does not exist (`obsidian.py:76-83`).
- ~~Any pagination logic in `sync_fireflies_transcripts()`~~ — does not exist; today makes exactly one `fireflies_get_transcripts` call and never inspects `skip`.
- ~~A call to `fireflies_get_summary` or `fireflies_fetch` anywhere in `obsidian.py`~~ — does not exist today.
- ~~An `include_summary` parameter~~ — does not exist yet.
- ~~A `"## Fireflies Summary"` section, a `FIREFLIES_SUMMARY_HEADING` constant, or a `has_fireflies_summary` OKF field~~ — none exist yet; `_build_okf_frontmatter()` today only derives fields from transcript-list metadata (title, date, participants, duration).
- ~~A `fireflies_list_channels`-based name→ID resolver~~ — does not exist; explicitly out of scope.
- ~~`email-validator` / `pydantic.EmailStr` working in the current environment~~ — `EmailStr` currently raises `ImportError: email-validator is not installed` (verified 2026-08-21); it is not yet a project dependency.
- ~~A shared response parser between `fireflies_get_transcripts`, `fireflies_get_transcript`, and `fireflies_get_summary`~~ — `_parse_fireflies_response()` is written against `fireflies_get_transcripts`'s text layout only; the other two tools' responses are always treated as opaque text in this design.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `FirefliesFilters` as a `pydantic.BaseModel` (project convention:
  Pydantic for all structured data).
- Field-name mapping (`from_date`→`fromDate`, etc.) as a small pure
  function, not inlined in `sync_fireflies_transcripts()` — keeps the
  mapping independently testable (per Test Specification).
- Model the new summary-section helper directly on
  `_append_analysis_section()`'s shape (`@staticmethod`, plain str in/out)
  and add a `FIREFLIES_SUMMARY_HEADING` class constant alongside the
  existing `ANALYSIS_HEADING`, for the same reason that constant exists
  (a single place other code/tests can check for the heading).
- Reuse `_call_fireflies_tool()` unchanged for the new `fireflies_get_summary`
  call — no new call path needed.
- Comprehensive logging via `self.logger` (already established in this
  class) for both new failure modes (page-fetch failure, summary-fetch
  failure).

### Known Risks / Gotchas
- **Unbounded pagination** (explicit accepted risk, not a bug): a
  broad/unfiltered `limit` against a large Fireflies account can issue many
  sequential `fireflies_get_transcripts` calls in one
  `sync_fireflies_transcripts()` invocation. Mitigation: document this
  plainly in the method's docstring (acceptance criterion above) so a
  caller can self-limit via filters/`limit`; no enforced ceiling is added.
- **`fireflies_get_summary`'s response shape is unverified live.** This
  spec's design sidesteps the risk by never parsing it — the raw text is
  appended as-is to the `## Fireflies Summary` section. If a future feature
  wants structured OKF fields (keywords, action items) from it, that
  requires first capturing a live response sample and adding a dedicated
  parser — explicitly out of scope here.
- **No strip-on-resync for the Fireflies Summary section**: unlike
  `summarize_transcript()` (which re-reads and can re-run against an
  existing note, hence needs `_strip_analysis_section()` to avoid
  duplicate blocks), `sync_fireflies_transcripts()`'s `skip_existing`
  means an already-synced note is never regenerated — so there is no
  "re-run with `include_summary=True` on an already-synced note" path in
  this feature. If that capability is wanted later, it needs its own
  strip-on-resync helper, deliberately deferred.
- **`email-validator` is a new dependency** (see External Dependencies) —
  must be added to `packages/ai-parrot/pyproject.toml`, not assumed present.
- **Merge precedence is field-by-field, not whole-object**: `default_filters`
  and per-call `filters` merge per individual field, not "one object wins
  entirely" — implementers must not shortcut this with `filters or
  default_filters`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `==2.12.5` (existing, no change) | `FirefliesFilters` model. Already pinned in `packages/ai-parrot/pyproject.toml:51`. |
| `email-validator` | latest compatible with `pydantic==2.12.5` | **New dependency.** Required for `pydantic.EmailStr` on `FirefliesFilters.organizers`/`.participants`. Verified NOT currently installed — `EmailStr` raises `ImportError` today. Add via `uv add email-validator` (or the `pydantic[email]` extra) per project convention (`CLAUDE.md`: "Manage all dependencies via pyproject.toml"). |

---

## 8. Open Questions

> Questions carried forward from the brainstorm, with resolution state
> preserved. `[x]` items were already answered (in the brainstorm or during
> this spec's own clarifying round) and are reflected in the design above.

- [x] Which underlying Fireflies MCP tool to filter through — *Resolved in
      brainstorm*: `fireflies_get_transcripts` (structured kwargs), not
      `fireflies_search`.
- [x] Filter dimensions to support — *Resolved in brainstorm*: date range,
      keyword/scope, organizer/participant emails, mine-only/channel — all
      four.
- [x] API shape for the filters — *Resolved in brainstorm*: a
      `FirefliesFilters` Pydantic model, optional `filters` arg.
- [x] Agent/daemon-level default filters — *Resolved in brainstorm*: yes,
      `default_filters` constructor kwarg, settable from
      `fireflies_daemon.yaml`.
- [x] Client-side validation strictness — *Resolved in brainstorm*:
      validate obvious shape errors only (types/enums); the API is the
      final authority on semantic rejection.
- [x] Pagination strategy — *Resolved in brainstorm*: auto-paginate
      internally; `limit` means "total transcripts across all pages."
- [x] Pagination safety ceiling — *Resolved in brainstorm*: no hard cap
      (accepted risk, documented in §7).
- [x] Partial-pagination-failure behavior — *Resolved in brainstorm*: keep
      transcripts from prior successful pages, record the error,
      `status="ok"` with a partial result.
- [x] Channel-name resolution convenience — *Resolved in brainstorm*: out
      of scope; caller passes the raw `channel_id`.
- [x] Whether to use `fireflies_fetch` — *Resolved in brainstorm*: no,
      excluded entirely (experimental/unreliable per Fireflies).
- [x] Native summary retrieval: opt-in vs. default-on — *Resolved in
      brainstorm*: opt-in, default off (`include_summary: bool = False`).
- [x] Where the native summary lives relative to the LLM analysis section —
      *Resolved in brainstorm*: separate `## Fireflies Summary` section +
      OKF marker, never conflated with `## Analysis`.
- [x] Summary-call failure behavior — *Resolved in brainstorm*: soft-fail,
      note still created from the transcript, meeting still counted synced.
- [x] Merge precedence when `default_filters` and per-call `filters` set
      the *same* field differently — *Resolved during `/sdd-spec`
      clarifying round (2026-08-21)*: per-call field wins; agent default
      fills in fields the call left unset.
- [x] Whether `organizers`/`participants` should validate as well-formed
      emails client-side — *Resolved during `/sdd-spec` clarifying round
      (2026-08-21)*: yes, `pydantic.EmailStr` (which introduces the new
      `email-validator` dependency documented in §7 — this consequence was
      not spelled out at decision time and is surfaced here for visibility).
- [x] `fireflies_get_summary`'s exact response text layout — *Resolved by
      design during `/sdd-spec` (2026-08-21)*: rather than blocking on a
      live sample, this spec avoids the dependency entirely — the response
      is always treated as opaque text (see §2, §7, Non-Goals). Revisit
      only if a future feature wants structured OKF fields from it.

---

## Worktree Strategy

- **Isolation unit**: `per-spec`. All five modules touch the same file
  (`packages/ai-parrot/src/parrot/agents/obsidian.py`) plus its test file
  and one YAML doc — there is no natural seam (no separate toolkits, no
  unrelated endpoints) to split across worktrees.
- **Task sequencing** (all within one worktree, one branch off `dev`):
  1. Module 1 (`FirefliesFilters` + mapping) — also adds the
     `email-validator` dependency.
  2. Module 2 (`default_filters` + merge precedence) — depends on 1.
  3. Module 3 (pagination loop) — depends on 1–2.
  4. Module 4 (native summary retrieval) — independent of 1–3, but
     implemented in the same pass since it touches the same method.
  5. Module 5 (`fireflies_daemon.yaml` docs) — depends on 2.
- **Cross-feature dependencies**: none. The only related prior spec,
  `sdd/specs/integrate-mcp-fireflies.spec.md` (FEAT-237), touches
  `parrot/mcp/integration.py` and `parrot/mcp/registry.py` — files this
  feature does not touch.
- **Worktree creation** (after `/sdd-task`):
  ```bash
  git worktree add -b feat-441-fireflies-mcp-improvements \
    .claude/worktrees/feat-441-fireflies-mcp-improvements HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-21 | Arturo Martinez | Initial draft, from `sdd/proposals/fireflies-mcp-improvements.brainstorm.md` (Options A + D). |
