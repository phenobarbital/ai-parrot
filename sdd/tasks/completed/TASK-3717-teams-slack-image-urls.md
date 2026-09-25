# TASK-3717: Teams + Slack render ParsedResponse.image_urls (M12)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3716
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 (U1) channel behaviour for the two URL-capable channels: **Teams** renders
`image_urls` as `ImageEntry`s inside the card's `ImageSection`, capped at 3 images total, and links the
overflow with labels; **Slack** renders every URL as an `image` block (Slack is uncapped and http(s)-only,
spec F020). Slack's assistant handler (`slack/assistant.py:185, 238`) reuses `wrapper._build_blocks`, so it
is covered without editing it. Implements AC14 (Teams/Slack half) and feeds AC8's channel matrix.
Depends on TASK-3716 for `ParsedResponse.image_urls`.

---

## Scope

- In `MSTeamsAgentWrapper._parsed_to_card_spec`, after the existing `parsed.images[:3]` loop, append
  `ImageEntry(url=u, alt_text=<label>, size="Large")` for `parsed.image_urls` until 3 image entries exist;
  render each remaining URL as a `TextSection` markdown link `[<label>](<url>)`.
- In `SlackAgentWrapper._build_blocks`, after the existing `parsed.images` loop, append one
  `{"type": "image", "image_url": u, "alt_text": <label>}` block per `parsed.image_urls` entry.
- Label rule: `f"Figure {n}"` (1-based over `image_urls`) — `ParsedResponse` carries URLs only.
- Tests for Teams cap/overflow, Slack blocks, and both Slack assistant call sites.

**NOT in scope**: `media_urls` rendering beyond links (Teams/Slack may ignore `media_urls` or render them
as links — choose links, see FILL IN); Telegram/WhatsApp (TASK-3718/3719); editing `slack/assistant.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | Add `image_urls` entries (cap 3) + overflow links in `_parsed_to_card_spec` |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | Add image blocks for `image_urls` in `_build_blocks` |
| `packages/ai-parrot-integrations/tests/test_media_urls_teams_slack.py` | CREATE | Teams + Slack + Slack-assistant tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.parser import ParsedResponse                     # verified: integrations/parser.py:83 (+ image_urls/media_urls from TASK-3716)
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper       # verified: msteams/wrapper.py:93
from parrot.integrations.slack.wrapper import SlackAgentWrapper           # verified: slack/wrapper.py:75
from parrot.outputs.cards import ImageEntry, ImageSection                 # verified: msteams/wrapper.py:49-54 (defined in outputs/cards/sections.py:61, 67)
# TextSection is imported by msteams/wrapper.py from parrot.outputs.cards (used at wrapper.py:1270) — defined in outputs/cards/sections.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):               # line 93
    def _parsed_to_card_spec(self, parsed: ParsedResponse) -> CardSpec:   # line 1167
        # "# Images (URLs and local paths)" at 1258; image_entries: list[ImageEntry] = [] at 1259;
        # loop over parsed.images[:3] 1260-1276 (http(s) strings → ImageEntry; others → TextSection "Image: name");
        # data:image documents → ImageEntry 1278-1302; `if image_entries:` → ImageSection(images=..., spacing="Medium", separator=True) 1304-1311

# packages/ai-parrot/src/parrot/outputs/cards/sections.py
class TextSection(CardSection): text: str; role=...; color: str | None; is_subtle: bool   # line 21
class ImageEntry(BaseModel): url: str; alt_text: str = ""; size: Literal["Auto","Stretch","Small","Medium","Large"] = "Large"   # line 61
class ImageSection(CardSection): images: list[ImageEntry] = []            # line 67

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
class SlackAgentWrapper:                                                  # line 75
    @staticmethod
    def _build_blocks(parsed: ParsedResponse) -> List[Dict[str, Any]]:    # lines 566-567; images loop 591-602; return at 605

# packages/ai-parrot-integrations/src/parrot/integrations/slack/assistant.py
blocks = self.wrapper._build_blocks(parsed)                               # lines 185 and 238 (two call sites, unchanged)
```

### Does NOT Exist
- ~~A cap on Slack images; `data:` image support in Slack~~ — Slack renders http(s) only, uncapped (F020).
- ~~`ParsedResponse.image_labels`~~ — no labels travel with URLs; derive `Figure N`.
- ~~A link/button section type in `parrot.outputs.cards` used by this wrapper~~ — use a `TextSection` with markdown link text.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/test_media_urls_teams_slack.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._parsed_to_card_spec",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper._build_blocks",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#ParsedResponse",
    "sym:packages/ai-parrot/src/parrot/outputs/cards/sections.py#ImageEntry",
    "sym:packages/ai-parrot/src/parrot/outputs/cards/sections.py#ImageSection",
    "sym:packages/ai-parrot/src/parrot/outputs/cards/sections.py#TextSection"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The existing http(s) branch of the Teams images loop (msteams/wrapper.py:1262-1269) and the Slack image
block dict (slack/wrapper.py:594-598). Test construction: `MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)`
with a `logger` attribute set (precedent: tests/integrations/msteams/test_voice_integration.py:29).
`_build_blocks` is a staticmethod — call it on the class.

### Key Constraints
- Worktree tests: the shared `.venv` is editable-installed against the main checkout, so run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q`.
- No new third-party dependency (spec G8, AC18).
- Google-style docstrings and strict type hints on every function/class; Pydantic v2; `self.logger` / module
  `logging.getLogger(__name__)` — never `print`.
- HTTP is `aiohttp` only — never `requests` / `httpx` (ruff TID251 fails the merge gate).
- Existing `Path` attachment behaviour (`images` / `media` / `files` / `documents`) must stay byte-for-byte
  unchanged (AC14) — URL handling is strictly additive.
- The Teams cap is **3 image entries total from `parsed.images` + `parsed.image_urls`** (spec §3 M12:
  "image_entries from parsed.images[:3] … THEN parsed.image_urls; cap 3 total"). The later `data:image`
  documents loop is existing behaviour — leave it as is.
- `msteams.wrapper` imports botbuilder / `parrot_formdesigner`; guard the test module with
  `pytest.importorskip("botbuilder")` so the file skips cleanly where the extra is absent.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the Teams URL block above `# Documents that are base64 data URIs (inline images)` — *why*: it must see the entries the Path loop already added to enforce the shared cap.
2. Insert the Slack URL loop above `return blocks or [...]` — *why*: appended after existing images so current output is a strict prefix (AC14 unchanged Path behaviour).
3. Write tests, including both `slack/assistant.py` call paths via `_build_blocks` — *why*: AC14 "all seven send paths covered".

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        # Documents that are base64 data URIs (inline images)' packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py)
# BEFORE — insert above `        # Documents that are base64 data URIs (inline images)` (verified: msteams/wrapper.py:1278),
#          i.e. right after the `for image_path in parsed.images[:3]:` loop that follows
#          `image_entries: list[ImageEntry] = []` (verified: msteams/wrapper.py:1259, occurrences: 1)
        # Remote image URLs (FEAT-601 M12): fill up to 3 entries total, link the overflow
        overflow_links: list[str] = []
        for n, url in enumerate(getattr(parsed, "image_urls", []) or [], start=1):
            label = f"Figure {n}"
            if len(image_entries) < 3:
                image_entries.append(ImageEntry(url=url, alt_text=label, size="Large"))
            else:
                overflow_links.append(f"[{label}]({url})")
        # FILL IN: media_urls → also appended to overflow_links as "[Video {n}](url)" — bounded by spec §3 M12 (URLs deliverable as-is)
        if overflow_links:
            sections.append(TextSection(text=" · ".join(overflow_links), is_subtle=True))
```
**Why**: cap-3-then-link is fixed by spec §3 M12; appended after the Path loop so existing card output for
Path-only responses is unchanged.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'return blocks or [{"type": "section", "text": {"type": "mrkdwn", "text": "No content."}}]' .../slack/wrapper.py)
# BEFORE — insert above `        return blocks or [{"type": "section", "text": {"type": "mrkdwn", "text": "No content."}}]` (verified: slack/wrapper.py:605)
        # Remote image URLs (FEAT-601 M12) — one image block each, uncapped like Path images
        for n, url in enumerate(getattr(parsed, "image_urls", []) or [], start=1):
            blocks.append({"type": "image", "image_url": url, "alt_text": f"Figure {n}"})
        # FILL IN: media_urls → one context block with "<url|Video n>" mrkdwn links — bounded by spec §3 M12
```
**Why**: Slack renders http(s) image blocks natively (F020); `getattr` default keeps any foreign
`ParsedResponse`-like object working.

### `packages/ai-parrot-integrations/tests/test_media_urls_teams_slack.py` (CREATE)
```python
"""FEAT-601 M12 — Teams/Slack render ParsedResponse.image_urls (TASK-3717)."""
from __future__ import annotations

import logging

import pytest

from parrot.integrations.parser import ParsedResponse
from parrot.integrations.slack.wrapper import SlackAgentWrapper

URLS = [f"https://cdn.example/fig{i}.png" for i in range(1, 5)]


def test_slack_renders_image_urls() -> None:
    """One image block per URL, after any Path image blocks."""
    blocks = SlackAgentWrapper._build_blocks(ParsedResponse(text="t", image_urls=URLS))
    # FILL IN: exactly 4 {"type": "image"} blocks with image_url == URLS[i]


def test_slack_path_only_output_unchanged() -> None:
    # FILL IN: ParsedResponse without URLs yields the same blocks as before (no extra blocks)
    pass


def test_slack_assistant_paths_render_url() -> None:
    """slack/assistant.py:185 and :238 both call wrapper._build_blocks — assert a URL survives that call."""
    # FILL IN: build a fake wrapper exposing _build_blocks = SlackAgentWrapper._build_blocks and assert image block


def test_teams_renders_image_urls_cap3_with_overflow_links() -> None:
    """4 URLs ⇒ 3 ImageEntry in the ImageSection + 1 labelled link TextSection."""
    pytest.importorskip("botbuilder")
    from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

    wrapper = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    wrapper.logger = logging.getLogger("test")
    # FILL IN: spec = wrapper._parsed_to_card_spec(ParsedResponse(text="t", image_urls=URLS)); assert one
    #          ImageSection with 3 images; a TextSection containing "[Figure 4](https://cdn.example/fig4.png)"
```

### FILL IN checklist
- [ ] Teams `media_urls` overflow links — bounded by spec §3 M12
- [ ] Slack `media_urls` context links — bounded by spec §3 M12
- [ ] test bodies; any extra attributes `_parsed_to_card_spec` reads on `self` verified before stubbing

---

## Acceptance Criteria

- [ ] Teams: 4 URLs ⇒ 3 `ImageEntry` + 1 labelled overflow link; Path-only cards unchanged
- [ ] Slack: one image block per URL; Path-only blocks unchanged; both assistant call sites render URLs
- [ ] `ruff check` clean on both wrappers
- [ ] All tests pass (see Validation Commands)

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_media_urls_teams_slack.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_teams_renders_image_urls_cap3_with_overflow_links` | spec §4 M12: 4 URLs ⇒ 3 images + 1 link with label |
| `test_slack_renders_image_urls` | spec §4 M12: one image block per URL |
| `test_slack_path_only_output_unchanged` | AC14 unchanged Path behaviour |
| `test_slack_assistant_paths_render_url` | `assistant.py:185/238` covered via `_build_blocks` |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3717
- Feature: training-agent
- Implementation SHA: b377a2c68d8392568dbf6fc816b02079ca58a69b
- Closed at (UTC): 2026-09-25T14:16:50+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
| supplementary_test_evidence | 6 passed, 0 failed (scoped direct pytest over test_media_urls_teams_slack.py) |
