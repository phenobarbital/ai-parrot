# TASK-2352: Frontmatter engine — `render_frontmatter()` + `split_frontmatter()`

**Feature**: FEAT-451 — `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter
**Spec**: `sdd/specs/wikitoolkit-ingest-documents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2351
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (§3). Two pure functions, both in
`documents.py`:

- `render_frontmatter()` — the **output** direction: turn a
  `DocumentMetadata` (+ optional `TriageProvenance`) into a deterministic
  YAML frontmatter block that gets prefixed onto every generated wiki page
  body (wired in TASK-2356).
- `split_frontmatter()` — the **input** direction: strip a leading YAML block
  off a markdown source so it becomes metadata instead of being fed to the
  triage LLM as prose (consumed by TASK-2353).

Determinism matters: these blocks land in `WikiPageRecord.body`, which is
stored, exported, and diffed. Two runs over the same input must produce
byte-identical output — the same contract `parrot.knowledge.okf.frontmatter`
already holds itself to (frontmatter.py:1-22).

---

## Scope

- ADD to `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py`:

  ```python
  def render_frontmatter(
      metadata: DocumentMetadata,
      provenance: TriageProvenance | None = None,
  ) -> str: ...

  def split_frontmatter(text: str) -> tuple[dict[str, Any], str]: ...
  ```

- `render_frontmatter` rules:
  - Opens with `---\n` and closes with `---\n\n`.
  - **Fixed field order** — declare an explicit key tuple; never iterate
    `model_dump()` insertion order implicitly, and never `sort_keys=True`
    over the whole document (that would reorder the descriptive block).
  - `None` fields are omitted entirely.
  - `extra` renders as a nested `extra:` mapping with its keys **sorted**.
  - `provenance`, when given and not fully empty, renders as a nested
    `triage:` mapping — a nested key so descriptive and audit halves can
    never collide on a name.
  - Returns `""` when metadata and provenance are both fully empty. Never
    emit an empty `---\n---\n` block.
  - Serialize with `yaml.safe_dump(..., sort_keys=False, allow_unicode=True,
    default_flow_style=False)` so titles with `:`, `#`, quotes, or newlines
    are escaped correctly.
- `split_frontmatter` rules:
  - Detect a leading `---\n ... \n---\n` block; return
    `(parsed_mapping, remaining_body)`.
  - Return `({}, text)` **unchanged** when: there is no leading `---`, the
    block never terminates, the YAML fails to parse, or it parses to
    something that is not a mapping. Malformed frontmatter is never a hard
    error — it is simply left inline.
- Write unit tests in `tests/knowledge/wiki/test_documents.py` (append to the
  file TASK-2351 created).

**NOT in scope**: calling these from `DocumentAcquirer` (TASK-2353) or from
`ingest.py` (TASK-2356). Mapping loader metadata into `DocumentMetadata`
(TASK-2353).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` | MODIFY | Add the two functions |
| `tests/knowledge/wiki/test_documents.py` | MODIFY | Append frontmatter tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import re
from typing import Any

import yaml   # PyYAML — existing core dep, already imported at
              # packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py:26

from parrot.knowledge.wiki.documents import DocumentMetadata, TriageProvenance  # TASK-2351
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py
# THE DETERMINISM CONTRACT TO MIRROR (module docstring, lines 1-22):
#   - "Pure function: same JSON node -> same YAML bytes every time."
#   - "Byte-deterministic: field order is fixed, values are verbatim from JSON."
#   - "tags are sorted alphabetically for determinism."
#   - "Optional fields (source, url) are omitted when None."
#   - "Frontmatter delimiters are ---\n (start) and ---\n (end)."
def project_frontmatter(node: dict, tree_name: str) -> str:   # line 101
def parse_frontmatter(text: str) -> ConceptFrontmatter:       # line 154
```

```python
# packages/ai-parrot-loaders/src/parrot_loaders/markdown.py:364-372
# THE REGEX PRECEDENT for split_frontmatter — copy this shape:
frontmatter_match = re.match(r'^---\n(.*?)\n---\n', md_text, re.DOTALL)
if frontmatter_match:
    frontmatter = yaml.safe_load(frontmatter_match.group(1))
    if isinstance(frontmatter, dict):
        metadata.update(frontmatter)
```

### Does NOT Exist

- ~~`parrot.knowledge.okf.frontmatter.split_frontmatter`~~ — the OKF module
  exports only `project_frontmatter` (frontmatter.py:101) and
  `parse_frontmatter` (frontmatter.py:154). **`parse_frontmatter` returns a
  `ConceptFrontmatter` model, not a `(mapping, body)` tuple, and it never
  returns the stripped body.** Write `split_frontmatter` yourself here.
- ~~reusing `ConceptFrontmatter` (frontmatter.py:35) for documents~~ — it is
  the OKF *concept* model (concept type, relates_to, source provenance), not a
  document-metadata model. Do not force `DocumentMetadata` through it.
- ~~`yaml.dump`~~ — use `yaml.safe_dump`. `safe_dump` is what the codebase uses.
- ~~a `frontmatter` PyPI package~~ — not a dependency of this repo. Do not add one.

---

## Implementation Notes

### Pattern to Follow

```python
# Explicit, fixed order — this tuple IS the determinism guarantee.
_FRONTMATTER_FIELD_ORDER: tuple[str, ...] = (
    "title", "author", "created_at", "modified_at", "page_count",
    "word_count", "language", "content_type", "source_url", "loader",
)

def render_frontmatter(metadata, provenance=None) -> str:
    payload: dict[str, Any] = {}
    for field in _FRONTMATTER_FIELD_ORDER:
        value = getattr(metadata, field)
        if value is not None:
            payload[field] = value
    if metadata.extra:
        payload["extra"] = {k: metadata.extra[k] for k in sorted(metadata.extra)}
    if provenance is not None:
        triage = {k: v for k, v in provenance.model_dump().items() if v is not None}
        if triage:
            payload["triage"] = triage
    if not payload:
        return ""
    body = yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{body}---\n\n"
```

### Key Constraints

- Both functions are **pure**: no I/O, no logging of content, no clock, no
  randomness. They must be safe to call twice and compare byte-for-byte.
- `split_frontmatter` must never raise on hostile input. Wrap the
  `yaml.safe_load` in `try/except yaml.YAMLError` and fall through to
  `({}, text)`.
- Handle CRLF: normalize `\r\n` before matching, or make the regex tolerant.
  A `.md` authored on Windows must not silently fail to split.
- `split_frontmatter` returning `({}, text)` for malformed input is
  load-bearing — TASK-2353 relies on "no block found" and "bad block" being
  indistinguishable at the call site.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py:1-22, 101` — determinism contract.
- `packages/ai-parrot-loaders/src/parrot_loaders/markdown.py:364-372` — the regex precedent.

---

## Acceptance Criteria

- [ ] `render_frontmatter(md)` called twice on equal input returns
      byte-identical strings.
- [ ] Field order in the output matches `_FRONTMATTER_FIELD_ORDER`, not
      alphabetical order.
- [ ] `None` fields do not appear in the output.
- [ ] `extra` keys are sorted.
- [ ] `render_frontmatter(DocumentMetadata())` returns `""` — not `"---\n---\n"`.
- [ ] `provenance` renders under a nested `triage:` key; descriptive keys are
      byte-identical with and without it.
- [ ] A title containing `:` and a newline round-trips through
      `yaml.safe_load(render_frontmatter(...))`.
- [ ] `split_frontmatter` returns `(mapping, body)` with the block removed.
- [ ] `split_frontmatter` returns `({}, text)` unchanged for: no block, an
      unterminated block, invalid YAML, and a YAML list (non-mapping).
- [ ] `split_frontmatter` never raises for any input.
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_documents.py -v`
- [ ] `ruff check` and `mypy` clean on the changed file.

---

## Test Specification

```python
# tests/knowledge/wiki/test_documents.py  (append)
import yaml

from parrot.knowledge.wiki.documents import (
    DocumentMetadata,
    TriageProvenance,
    render_frontmatter,
    split_frontmatter,
)


class TestRenderFrontmatter:
    def test_deterministic(self):
        md = DocumentMetadata(title="A", author="B", page_count=3)
        assert render_frontmatter(md) == render_frontmatter(md)

    def test_omits_none(self):
        out = render_frontmatter(DocumentMetadata(title="A"))
        assert "author" not in out

    def test_empty_returns_empty_string(self):
        assert render_frontmatter(DocumentMetadata()) == ""

    def test_extra_keys_sorted(self):
        md = DocumentMetadata(extra={"z": 1, "a": 2})
        out = render_frontmatter(md)
        assert out.index("a:") < out.index("z:")

    def test_provenance_nested_under_triage(self):
        md = DocumentMetadata(title="A")
        prov = TriageProvenance(composite_score=0.8, decision="admit")
        parsed = yaml.safe_load(render_frontmatter(md, prov).strip("-\n"))
        assert parsed["triage"]["decision"] == "admit"
        assert parsed["title"] == "A"

    def test_escapes_hostile_title(self):
        md = DocumentMetadata(title="Report: Q3\nsecond line")
        parsed = yaml.safe_load(render_frontmatter(md).strip("-\n"))
        assert parsed["title"] == "Report: Q3\nsecond line"


class TestSplitFrontmatter:
    def test_roundtrip(self):
        text = "---\ntitle: A\nauthor: B\n---\n# Body\n"
        meta, body = split_frontmatter(text)
        assert meta == {"title": "A", "author": "B"}
        assert body.startswith("# Body")
        assert "title: A" not in body

    def test_no_block_unchanged(self):
        text = "# Just a heading\n"
        assert split_frontmatter(text) == ({}, text)

    def test_unterminated_block_unchanged(self):
        text = "---\ntitle: A\n# no closing fence\n"
        assert split_frontmatter(text) == ({}, text)

    def test_invalid_yaml_unchanged(self):
        text = "---\n: : :\n---\nbody\n"
        meta, body = split_frontmatter(text)
        assert meta == {} and body == text

    def test_non_mapping_unchanged(self):
        text = "---\n- a\n- b\n---\nbody\n"
        meta, body = split_frontmatter(text)
        assert meta == {} and body == text

    def test_crlf_tolerated(self):
        text = "---\r\ntitle: A\r\n---\r\nbody\r\n"
        meta, _ = split_frontmatter(text)
        assert meta == {"title": "A"}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 New Public Interfaces, §3 Module 4).
2. **Check dependencies** — TASK-2351 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `okf/frontmatter.py` still holds
   the determinism contract quoted above before mirroring it.
4. **Update status** in `sdd/tasks/index/wikitoolkit-ingest-documents.json` → `"in-progress"`.
5. **Implement** following the scope and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2352-frontmatter-render-and-split.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Added `render_frontmatter()` and `split_frontmatter()` to
`documents.py`, following the OKF `project_frontmatter` determinism
contract (fixed field order via `_FRONTMATTER_FIELD_ORDER`, sorted `extra`
keys, `None` omitted, `yaml.safe_dump(sort_keys=False, allow_unicode=True,
default_flow_style=False)`). `split_frontmatter` uses a CRLF-tolerant regex
mirroring `MarkdownLoader._extract_metadata_from_markdown` and never raises
on malformed input. All 21 tests in `tests/knowledge/wiki/test_documents.py`
pass (12 new); `ruff check` and `mypy` clean.

**Deviations from spec**: none
