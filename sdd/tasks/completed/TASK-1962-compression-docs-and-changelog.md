# TASK-1962: Documentation + changelog for the compression pipeline

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1953, TASK-1954, TASK-1957
**Assigned-to**: unassigned

---

## Context

Spec §5 acceptance criteria: *"Documentation updated in `docs/` (config
format, levels, kill switch, tee recovery flow, token-estimate caveat:
percentages reliable, absolute values approximate)"* and *"changelog documents
the `result_size_bytes` semantic change (now post-compression size)"*.

The changelog entry is not optional bookkeeping: `result_size_bytes` on
`AfterToolCallEvent` silently changes meaning for every existing consumer of
that event. It is the **only semantic change of the feature**, and anyone
graphing that field will otherwise see an unexplained step change.

---

## Scope

- Write user-facing documentation covering:
  - **What it does and why** — one short section, honest about the calibration
    (§7): `MINIMAL` yields ~5–15% *token* savings even where the byte diff
    looks like 40%, because BPE tokenizers merge whitespace runs. The real
    return is `NORMAL` (columnar + dedup).
  - **The four `FilterLevel`s** and what each is allowed to do.
  - **Configuration**: the `.parrot/compressors.toml` format, the resolution
    precedence (source: project → third-party → core; match: exact → glob →
    `"*"`), and the effective-level precedence table from spec §2.
  - **The kill switch**: `PARROT_COMPRESSION_DISABLED=1` restores current
    behavior exactly.
  - **Tee recovery flow**: what `_tee` means in a result, and how the agent
    recovers the full payload with `wm_get_result` without re-running the
    tool. Include the pointer JSON shape.
  - **Extending it**: how a third-party package declares a codec via its own
    TOML manifest with zero core edits (G6).
  - **The savings report**: how to read it, and the token-estimate caveat —
    percentages reliable, absolute values approximate (`bytes/4`, no
    tokenizer).
  - **Optional Rust extension**: how to build it (`maturin develop`), what
    changes when it is absent (pure-Python fallback + large-payload
    passthrough), and the wheel-build/toolchain implication recorded by
    TASK-1955.
- Add the changelog entry for the `AfterToolCallEvent.result_size_bytes`
  semantic change, naming the new companion field
  `result_size_bytes_original` and the other new fields.
- Cross-link from the tools documentation so the feature is discoverable from
  where people already read about tools.

**NOT in scope**:
- Code changes. If writing the docs reveals a behavioral gap, record it in the
  Completion Note and raise it — do not fix it here.
- API reference generation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/tools/compression.md` | CREATE | The feature documentation (confirm the exact docs layout before choosing the path) |
| `docs/tools.md` | MODIFY | Cross-link to the new page |
| `CHANGELOG.md` | MODIFY | `result_size_bytes` semantic change + new `AfterToolCallEvent` fields (confirm the repo's changelog file/format first) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Facts to Document Accurately

```python
# parrot/core/events/lifecycle/events/tool.py:30 — @dataclass(frozen=True)
class AfterToolCallEvent(LifecycleEvent):
    tool_name: str = ""                # line 42
    duration_ms: float = 0.0           # line 43
    result_status: str = ""            # line 44 — "success" | "partial"
    result_size_bytes: int = 0         # line 45 ← SEMANTIC CHANGE: now POST-compression
    # added by TASK-1952:
    compression_codec: str = ""
    compression_level: str = ""
    result_size_bytes_original: int = 0
    compression_duration_ms: float = 0.0
    compression_teed: bool = False
```

Documented behavior that MUST match the implementation (verify each against
the merged code before writing it down):

- Zero config → global `MINIMAL`, lossless only.
- `PARROT_COMPRESSION_DISABLED=1` → today's exact behavior.
- `status != "success"` → level forced to `NONE`; the payload is teed before
  the existing `raise ValueError(result.error)`, which still raises.
- `tool.return_direct is True` → pipeline skipped entirely, tee included.
- No `WorkingMemoryToolkit` → tee disabled AND lossy levels capped to
  `MINIMAL`.
- Compression applies to **fresh executions only**; the `_compressed` marker
  makes history replay a passthrough.
- Over the size threshold without the Rust extension → **passthrough**.
- `voice_text` / `display_data` are never compressed.

Tee pointer shape (spec §2):

```json
{"_tee": {"key": "__tee__:execute_database_query:t7",
          "reason": "lossy",
          "hint": "use wm_get_result for the full payload"}}
```

Columnar output shape (spec §2):

```json
{"columns": ["store_id", "revenue", "region", "active"],
 "rows": [["TCTX", 801467.93, "south", true]],
 "constants": {"region": "south", "active": true}}
```

### Does NOT Exist

- ~~A tokenizer~~ — never present token figures as exact. `bytes/4`.
- ~~LLM-based summarization in this pipeline~~ — G4 forbids any codec invoking
  a model. Do not describe the feature as "AI summarization".
- ~~`rtk` as a dependency~~ — RTK inspired the architecture; no code and no
  binary is vendored. Do not tell users to install it.
- ~~Disk persistence of tee entries~~ — v1 is in-memory working memory only.
- ~~`docs/tools/compression.md`~~ — does not exist yet. **Confirm the actual
  `docs/` structure and the changelog file name/format before creating
  files**; the paths in the table above are proposals, not verified anchors.

---

## Implementation Notes

### Key Constraints

- **Document what shipped, not what the spec proposed.** Read the merged code
  for each behavior above and correct the doc where they differ; note any
  divergence in the Completion Note.
- Be honest about savings. The spec explicitly warns against overselling
  `MINIMAL`. A doc that promises 40% token savings will generate bug reports.
- The changelog entry must be findable by someone debugging a graph, so name
  the field and the direction of the change explicitly, e.g.:
  `AfterToolCallEvent.result_size_bytes now reports the POST-compression size;
  the pre-compression size moved to result_size_bytes_original.`
- Include a copy-pasteable TOML example that actually validates against the
  shipped schema — test it.

### References in Codebase

- `docs/tools.md` and `docs/tools-quick.md` — existing tool documentation
  style and structure.
- `sdd/specs/tool-result-compression.spec.md` §2, §5, §7 — the source
  material.

---

## Acceptance Criteria

- [ ] Documentation covers: levels, TOML config format + both precedence
      orders, kill switch, tee recovery flow, extending via third-party
      manifest, savings report, Rust extension build + fallback.
- [ ] The token-estimate caveat is stated: percentages reliable, absolute
      values approximate.
- [ ] The `MINIMAL` calibration (5–15% tokens, not 40%) is stated honestly.
- [ ] Changelog documents the `result_size_bytes` semantic change and names
      `result_size_bytes_original`.
- [ ] Every documented behavior was verified against the merged code, not
      copied from the spec.
- [ ] The example TOML validates against the shipped Pydantic schema (assert
      it in a doc test or verify manually and note it).
- [ ] Cross-link added from the existing tools documentation.

---

## Test Specification

```python
# Optional but recommended: a doc-example validation test
# packages/ai-parrot/tests/tools/compression/test_docs_examples.py
import re
from pathlib import Path
import tomllib
from parrot.tools.compression.config import CompressorConfig


def test_doc_toml_example_validates():
    """The copy-pasteable example in the docs must actually parse."""
    doc = Path("docs/tools/compression.md").read_text()
    block = re.search(r"```toml\n(.*?)```", doc, re.S).group(1)
    CompressorConfig(**tomllib.loads(block))
```

---

## Agent Instructions

1. **Read the spec** (§2, §5, §7) AND the merged implementation.
2. **Check dependencies** — TASK-1953, TASK-1954, TASK-1957 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm the `docs/` layout and the
   changelog file/format BEFORE creating files; adjust the paths in the table
   above to match reality.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Write** the documentation, verifying each behavior against the code.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** — list any place where the shipped behavior
   diverged from the spec.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-07-28
**Notes**:

- **Docs layout confirmed before creating files** (per the task's own
  instruction): `docs/tools.md` is a single flat reference file (NOT a
  directory) — but `docs/toolkits/`, `docs/events/`, and `docs/executors/`
  are all existing precedents for a `docs/<topic>/<feature>.md` deep-dive
  page alongside a flat top-level index. Created `docs/tools/compression.md`
  (a NEW `docs/tools/` directory, consistent with that established
  pattern) rather than assuming the task's proposed path blindly.
  `CHANGELOG.md` confirmed as the repo's actual changelog file/format
  (`## [Unreleased] — FEAT-<NNN>: <Title>` sections, newest first) —
  matched it exactly.
- Wrote `docs/tools/compression.md` covering every required section:
  levels table, TOML config format + BOTH precedence orders (source and
  match), the effective-level precedence table (including the G3 capping
  rule, which isn't in the original spec's 5-rule list but IS real
  shipped behavior), kill switch, tee recovery flow (with the pointer
  JSON shape), extending via third-party manifest, savings report (with
  the token-estimate caveat stated twice — inline in `render()`'s own
  output AND in the docs prose), and the optional Rust extension (build
  command, what changes present vs. absent, and the explicit "does NOT
  make the core wheel depend on Rust" clarification per TASK-1955's
  Completion Note).
- **Every documented behavior was re-verified against the merged code**
  (not copied from the spec) — re-read `stage.py`'s `_effective_level()`,
  `budget.py`'s calibrated defaults (TASK-1959's NEW values: 1,500 rows /
  3.0ms / 5.0ms, not the spec's original 5,000 / 1.0ms / 0.3ms),
  `registry.py`'s resolution precedence, `tee.py`'s pointer shape, and
  `report.py`'s caveat string, live, to write this page.
- **"Document what shipped, not what the spec proposed" — the honest
  parts**: added an explicit "Known limitations" section documenting TWO
  real gaps discovered during earlier tasks that the spec's narrative
  text doesn't surface on its own: (1) the live voice route restores
  permissions/broker/redaction/events but NOT compression itself
  (TASK-1956's documented architectural constraint); (2)
  `AfterToolCallEvent`'s new fields are not populated on the literal
  event instance a subscriber observes — only in `ToolResult.metadata`
  (TASK-1952's documented gap). Also noted `CompressionReport` has no
  automatic `ToolManager` listener yet (TASK-1957's scope boundary). None
  of these are code changes for THIS task — flagged, not fixed, per the
  "NOT in scope: Code changes" instruction.
- Also documented the `AGGRESSIVE` level honestly: no built-in codec
  currently implements `AGGRESSIVE`-specific behavior beyond what
  `NORMAL` already does — rather than describe a feature that doesn't
  exist.
- **Copy-pasteable TOML example validated for real**, not just eyeballed:
  wrote `test_docs_examples.py` (the task's own "optional but
  recommended" test) which regex-extracts the fenced ```toml block from
  the doc and round-trips it through `tomllib.loads()` +
  `CompressorConfig(**parsed)` — passes.
- Changelog entry: led with the ONE semantic change
  (`result_size_bytes` now post-compression, `result_size_bytes_original`
  added) exactly as instructed ("name the field and the direction of the
  change explicitly"), plus a second, smaller behavior-change bullet for
  the Google client's truncation logging (new, previously-silent warning
  on two of its three truncation paths — TASK-1961). Cross-linked to the
  new docs page from the changelog entry itself.
- Cross-linked from `docs/tools.md` in TWO places: a new "Tool-Result
  Compression" subsection right after the `ToolManager` section (since
  that's exactly where the pipeline runs), and an "Additional Resources"
  bullet at the bottom for a second discovery path.
- Verification: full compression suite 135/135 green (6 benchmarks
  correctly skipped); `ruff check` clean on the new test file; the TOML
  example validates programmatically; both cross-links use correct
  relative paths (verified `docs/tools.md` -> `tools/compression.md` and
  `docs/tools/compression.md` -> `../tools.md`).

**Deviations from spec**: none in the documentation itself — this task
faithfully documents what shipped. The "Known limitations" section above
IS the honest divergence record the task asked for (live.py compression
gap; event-field population gap; savings-report auto-wiring gap) — all
three were already flagged in their respective originating tasks'
Completion Notes; this task's job was to surface them to USERS, not
introduce new ones.
