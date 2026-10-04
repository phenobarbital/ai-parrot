# TASK-3726: Spike harness: figures, video, tips, media reports (M0)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3713, TASK-3717, TASK-3718, TASK-3719
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 0**, goal **G9 (validation-first)** and **AC1**. The brainstorm's four spikes
become repeatable, reported measurements over an owner-supplied corpus
(`MANUALS_SPIKE_CORPUS` directory with `expected.json` hand counts), invoked later by
`parrot manuals spike {figures,media,video,tips}` (TASK-3727). Reports are serialized under
`artifacts/logs/FEAT-601/`. Thresholds (fixed by spec M0): figures ≥ 90 % of steps in order
with no missing required step and ≥ 80 % correct primary figure on captioned figures; video
≥ 70 % of steps get a segment containing the demonstrated action; tips 3/3 re-link outcomes
exactly as expected; media one figure delivered on Teams, WhatsApp and Telegram.

This task builds the **harness** and its tests over fakes. Running the spikes on the real
corpus and signing AC1 is human-in-the-loop (spec: "M0 not delegation-eligible — needs the
owner's corpus and hand counts").

Parallelism: spike_figures/video drive ManualLibrary from TASK-3713 (manuals/library.py);
spike_media drives the channel senders from TASK-3717/3718/3719 (msteams, telegram, whatsapp
wrappers).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py` with `SpikeReport`,
  `THRESHOLDS`, `spike_figures`, `spike_video`, `spike_tips`, `spike_media`, `write_report`,
  `corpus_dir_from_env`, and a channel-sender registry (`ChannelSender` protocol,
  `register_channel_sender`, `CHANNEL_SENDERS`) — signatures of the four spikes are fixed by
  spec §3 M0.
- `spike_figures`: per manual in the corpus, run M6 extraction + M5 pass 2 through the library
  flow (`ManualLibrary.add_manual` with the given adapter), compare against `expected.json`
  (`{"<file>": {"steps": [...ordered texts or ids...], "required": [...], "primary_figures": {"<step order>": "<label>"}}}`);
  measurements `steps_in_order_ratio`, `missing_required`, `primary_figure_accuracy`.
- `spike_video`: run `align_video` per `(manual, transcript)` pair listed in `expected.json`
  (`"video": {"<manual>": {"transcript": "<file.json>", "segments": {"<step order>": [t0, t1]}}}`);
  a step counts when the aligned `[t_start, t_end]` overlaps the expected window; measure
  `coverage`, `precision`, and the same two restricted to the deterministic pass (so the judged
  tail's precision loss is visible — AC1).
- `spike_tips`: publish rev A, add three tips, publish rev B (one renumbered, one reworded, one
  removed — the `manual_pdf`/`manual_pdf_rev_b` shape), assert outcomes
  `{source_identity|unchanged, content_hash|candidate, orphaned}` exactly per `expected`; measurement
  `expected_outcomes_matched` out of 3.
- `spike_media`: presigned figure URLs from `answer.media`/image URLs sent through each named
  channel via the registered sender; record `sent`/`error` per channel; pass = all three of
  `msteams`, `whatsapp`, `telegram` succeeded.
- `write_report(report, *, root=Path("artifacts/logs/FEAT-601"))` writes
  `spike-<name>-<UTC timestamp>.json` and returns the path.
- Write `packages/ai-parrot/tests/knowledge/manuals/test_spikes.py` over fakes.

**NOT in scope**: running on the real corpus; the CLI command (TASK-3727); changing any
threshold; the design switch described in AC1 when figures fail (that is a human decision
recorded in the spec, not code).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py` | CREATE | spike harness + report writer |
| `packages/ai-parrot/tests/knowledge/manuals/test_spikes.py` | CREATE | threshold logic + harness over fakes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Created by earlier FEAT-601 tasks (spec §3 skeletons) — not yet in the tree:
from parrot.knowledge.manuals.library import ManualLibrary, IngestResult          # TASK-3713
from parrot.knowledge.manuals.catalog import ManualCatalogStore                   # TASK-3702
from parrot.knowledge.manuals.graph_loader import ManualGraphLoader               # TASK-3712
from parrot.knowledge.manuals.tips import add_tip, RelinkReport                   # TASK-3710
from parrot.knowledge.manuals.video import align_video, AlignmentReport, JudgementLog  # TASK-3709
from parrot.knowledge.manuals.models import ProcedureAnswer                       # TASK-3700
# Integrations are an optional satellite — import lazily inside default sender factories only:
from parrot.integrations.parser import ParsedResponse  # verified: packages/ai-parrot-integrations/src/parrot/integrations/parser.py:83 (image_urls added by TASK-3716)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/parser.py:83-95
@dataclass class ParsedResponse: text: str; images: List[Path]; documents: List[Path]; media: List[Path]; charts: List[ChartData]
# + image_urls / media_urls: List[str] (TASK-3716)

# Channel send paths the default senders wrap (lazy import; names verified now):
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:93   class MSTeamsAgentWrapper; :1167 def _parsed_to_card_spec(self, parsed) -> CardSpec; :1334 async def _send_parsed_response(
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:69  class TelegramAgentWrapper; :2960 async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None
# packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py:37  class WhatsAppAgentWrapper; :246 async def _send_parsed_response(
```

### Does NOT Exist
- ~~`parrot.knowledge.manuals.spikes`~~ — this task creates it.
- ~~A `spike` CLI subcommand~~ — TASK-3727 adds it; this module only exposes coroutines.
- ~~A spike corpus in the repo~~ — owner-supplied via `MANUALS_SPIKE_CORPUS`; tests build a tiny one in `tmp_path`.
- ~~Top-level imports of `parrot.integrations` in `spikes.py`~~ — core must not hard-require the integrations satellite; lazy-import inside sender factories.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_spikes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#ParsedResponse"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- Ontology imports (if any) from submodules only (AC17). No new dependency. Google docstrings, strict hints, Pydantic v2, `logger` not `print`.
- `spike_figures(corpus_dir, *, adapter, expected)` needs a library: accept an optional keyword-only
  `library: ManualLibrary | None = None` **appended last**; when `None`, build one over `tempfile` roots,
  an in-process catalog and the given adapter. A trailing optional kwarg keeps the fixed contract intact.
- `spike_media`'s senders: a `ChannelSender` is `async (channel: str, parsed: ParsedResponse) -> None`
  raising on failure. The CLI (TASK-3727) registers live senders built from configured wrappers;
  tests register fakes. Unknown/unregistered channel ⇒ recorded as error, not raised.
- Threshold comparison is `>=` on ratios and `== 0` on `missing_required`; `passed` is the AND.
- Reports must be JSON-serializable (`model_dump(mode="json")`), keys sorted.
- Tests: fixtures `manual_pdf`, `manual_pdf_rev_b`, `fake_adapter`, `fake_graph_store`,
  `fake_file_manager` from `tests/knowledge/manuals/conftest.py` (TASK-3698); catalog double
  from `_support/catalog.py` (TASK-3702). Pass `root=tmp_path` to `write_report` — never write
  to the real `artifacts/` in tests.

### References in Codebase
- Spec §3 M0 thresholds; §5 AC1.

---

## Implementation Blueprint

### Steps (in order)
1. Define `SpikeReport` + `THRESHOLDS` + `_evaluate(name, measurements)` — *why*: pass/fail must be computed one way for all four spikes.
2. Implement `write_report` and `corpus_dir_from_env` — *why*: AC1 requires reports under `artifacts/logs/FEAT-601/`.
3. Implement the sender registry — *why*: `spike_media`'s fixed signature takes only channel names.
4. Implement the four spikes — *why*: each maps one brainstorm spike to measured numbers.
5. Write tests over fakes — *why*: the harness itself is testable without the corpus.

### `packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py` (CREATE)
```python
"""Spike harness for FEAT-601's validation gate (M0 / AC1).

Measures figure pairing, video alignment, tip survival and media delivery
over an owner-supplied corpus and writes one JSON report per run.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Sequence

from pydantic import BaseModel, Field

from .catalog import ManualCatalogStore
from .models import ProcedureAnswer

logger = logging.getLogger(__name__)

SPIKE_CORPUS_ENV = "MANUALS_SPIKE_CORPUS"
REPORT_ROOT = Path("artifacts/logs/FEAT-601")
REQUIRED_MEDIA_CHANNELS: tuple[str, ...] = ("msteams", "whatsapp", "telegram")
THRESHOLDS: dict[str, dict[str, float]] = {
    "figures": {"steps_in_order_ratio": 0.90, "missing_required": 0.0, "primary_figure_accuracy": 0.80},
    "video": {"coverage": 0.70},
    "tips": {"expected_outcomes_matched": 3.0},
    "media": {"channels_delivered": float(len(REQUIRED_MEDIA_CHANNELS))},
}
ChannelSender = Callable[[str, Any], Awaitable[None]]
CHANNEL_SENDERS: dict[str, ChannelSender] = {}


class SpikeReport(BaseModel):
    """One spike's measured numbers, thresholds and pass/fail; serialised under artifacts/logs/."""

    name: Literal["figures", "media", "video", "tips"]
    measurements: dict[str, float]
    thresholds: dict[str, float]
    passed: bool
    notes: list[str] = Field(default_factory=list)


def _evaluate(name: str, measurements: dict[str, float], notes: list[str]) -> SpikeReport:
    """Apply THRESHOLDS[name]: ratios/counts use >=, 'missing_required' must be 0."""
    # FILL IN: missing measurement ⇒ passed=False + note — bounded by AC1 thresholds (never relax)
    raise NotImplementedError


def register_channel_sender(channel: str, sender: ChannelSender) -> None:
    """Register the live or fake sender used by spike_media for ``channel``."""
    CHANNEL_SENDERS[channel] = sender


def corpus_dir_from_env() -> Path:
    """Resolve MANUALS_SPIKE_CORPUS; missing/nonexistent ⇒ FileNotFoundError with a clear hint."""
    raise NotImplementedError


def write_report(report: SpikeReport, *, root: Path = REPORT_ROOT) -> Path:
    """Write spike-<name>-<UTC ts>.json (sorted keys) under ``root``; return the path."""
    raise NotImplementedError


async def spike_figures(corpus_dir: Path, *, adapter: Any, expected: dict[str, Any], library: Any | None = None) -> SpikeReport:
    """Run M6 extraction + M5 pass 2 over each manual; compare against expected.json hand counts."""
    # FILL IN: ingest each expected file; order check = longest-common-subsequence of expected vs extracted steps / len(expected)
    raise NotImplementedError


async def spike_video(corpus_dir: Path, *, adapter: Any, expected: dict[str, Any]) -> SpikeReport:
    """Run M7 alignment; score t_start/t_end precision and coverage per step (deterministic pass reported separately)."""
    raise NotImplementedError


async def spike_tips(graph_store: Any, catalog: ManualCatalogStore, *, revisions: tuple[Path, Path]) -> SpikeReport:
    """Publish rev A, add three tips, publish rev B (one renumbered, one reworded, one removed); assert relink outcomes."""
    # FILL IN: build ManualLibrary + ManualGraphLoader over graph_store/catalog; expected outcomes fixed by the rev B fixture shape
    raise NotImplementedError


async def spike_media(answer: ProcedureAnswer, *, channels: Sequence[str]) -> SpikeReport:
    """Deliver one presigned figure through the named channel wrappers; record render/send outcome per channel."""
    # FILL IN: lazy-import ParsedResponse; parsed.image_urls = first released figure URL; unregistered channel ⇒ error note
    raise NotImplementedError
```
**Why this shape**: the four spike signatures are the spec skeleton; the only additions are a
trailing optional `library` kwarg on `spike_figures` (documented in Notes) and module-level
helpers that do not alter them.

### `packages/ai-parrot/tests/knowledge/manuals/test_spikes.py` (CREATE)
```python
"""Spike harness over fakes (FEAT-601 M0)."""
from __future__ import annotations

import json

import pytest

from parrot.knowledge.manuals import spikes


def test_evaluate_thresholds_pass_and_fail() -> None:
    """Exactly-at-threshold passes; missing_required=1 fails; missing measurement fails with a note."""


def test_write_report_under_root(tmp_path) -> None:
    """spike-<name>-*.json written with sorted keys and round-trips to SpikeReport."""


def test_corpus_dir_from_env_missing(monkeypatch) -> None:
    """Unset or nonexistent MANUALS_SPIKE_CORPUS ⇒ FileNotFoundError."""


@pytest.mark.asyncio
async def test_spike_media_records_per_channel(monkeypatch) -> None:
    """Fake senders: two succeed, one raises ⇒ passed=False, note names the failing channel."""


@pytest.mark.asyncio
async def test_spike_tips_expected_outcomes(manual_pdf, manual_pdf_rev_b, fake_graph_store, fake_adapter, fake_file_manager) -> None:
    """In-process spike 4: 3/3 expected relink outcomes ⇒ passed."""
```

### FILL IN checklist
- [ ] `_evaluate` threshold semantics; bounded by AC1
- [ ] `corpus_dir_from_env`, `write_report`
- [ ] `spike_figures` order/primary scoring
- [ ] `spike_video` overlap scoring + deterministic-only split
- [ ] `spike_tips` rev A/B flow
- [ ] `spike_media` sender dispatch
- [ ] five tests (media sender fakes cleaned from `CHANNEL_SENDERS` after each test)

---

## Acceptance Criteria

- [ ] `SpikeReport` + four spike coroutines with the spec signatures exist; thresholds equal spec M0.
- [ ] Reports are written as JSON under `artifacts/logs/FEAT-601/` (configurable root).
- [ ] `spikes.py` imports no integrations module at top level.
- [ ] Harness tests pass over fakes; AC1 sign-off on the real corpus is left to the owner (note it in the Completion Note).
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_spikes.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_spikes.py
def test_evaluate_thresholds_pass_and_fail(): ...
def test_write_report_under_root(): ...
def test_corpus_dir_from_env_missing(): ...
async def test_spike_media_records_per_channel(): ...
async def test_spike_tips_expected_outcomes(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3726-manuals-spikes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (resumed session, execution 981de749-8a38-47ed-a033-752eb90afb12)
**Date**: 2026-09-25
**Notes**: Code was implemented and merged into `feat-FEAT-601-training-agent` by an earlier
orchestrator run (merge commit `3b6ba4ce5`, engine lint-autofix `aa8a30701`), but the SDD
close (index status + active→completed move) never happened before that session ended,
leaving the index stuck at `in-progress` and blocking every downstream task
(TASK-3727..3730 depend transitively on this one). This session verified the delivered
`packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py` (543 lines) +
`packages/ai-parrot/tests/knowledge/manuals/test_spikes.py` against the task's own
Validation Command directly:
`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest packages/ai-parrot/tests/knowledge/manuals/test_spikes.py -q` → `5 passed`
(`artifacts/logs/verify-TASK-3726.log`). AC1 sign-off on the real owner corpus remains
human-in-the-loop per spec (unchanged — this task only ships the harness).
The declared `coder_run_validation(tier="merge")` sweep was also run but FAILED overall —
not from this task's code: it aborted the whole `ai-parrot` distribution before
`test_spikes.py` could even run ("Interrupted: 26 errors during collection" — unrelated
pre-existing fixture/module issues in test_notification.py, test_chat_storage.py,
test_expense_approval.py, etc.), plus unrelated pre-existing failures elsewhere. Filed as
`issue:1e9c207bd223` (ledger) rather than blocking this task's closure on infrastructure
outside its scope. Closed via `scripts/sdd/close_task.sh` directly (the primitive
`finalize_task` wraps), since no execution-owned attempt branch remained for this new
execution to run `coder_merge`/`finalize_task` against (the merge had already happened in
the prior session).

**Deviations from spec**: none.
