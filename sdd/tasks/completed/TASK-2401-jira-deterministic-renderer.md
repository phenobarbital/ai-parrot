# TASK-2401: Deterministic `jira_render.py` — `JiraIssue` → markdown

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki (`issues` namespace)
**Spec**: `sdd/specs/jira-extractor-llmwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2398, TASK-2399
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** (spec §3 M3, §2 "Data Models"/M3 block, G2/G3/G4/G7).
A pure function library: `JiraIssue` → a markdown document, plus the satellite
person/project/component/label notes. No network, no LLM, no filesystem.

This is where **G2 (byte-determinism)** and **G4 (human annotations survive
every re-sync)** are won or lost. Two properties dominate the design:

- **Determinism** makes a daily cron free and diffable — identical input must
  produce identical bytes, so an unchanged ticket writes nothing.
- **The sync marker is the highest-consequence path in the whole feature.** A
  bad `split_at_marker` silently eats someone's notes. The spec calls this out
  explicitly (§7): test trailing whitespace, a missing marker, a duplicated
  marker, and a marker inside a code fence.

The renderer also produces the `[[KEY]]` wikilinks and `#tags` that
`scan_vault` later turns into graph edges and tag pages — that is how **G7**
(a navigable graph) is delivered without this feature writing a single edge
itself.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py` with:
  - `SYNC_MARKER`, `EXTRACTOR_VERSION`
  - `IssueFrontmatter`, `IssueSyncStamp` (pydantic; declaration order **is**
    emitted YAML key order)
  - `issue_filename`, `person_slug`, `group_slug`
  - `split_at_marker`
  - `html_to_markdown`
  - `render_issue_document`, `render_person_note`, `render_group_note`
- Mirror the `documents.render_frontmatter` determinism contract: fixed key
  order, sorted collections, `None` omitted.
- Convert `description_html` / `acceptance_criteria_html` with `html2text`
  under an **explicitly pinned** configuration — its defaults wrap lines,
  which would make output terminal-width dependent.
- Emit `[[KEY]]` wikilinks for every relation and `#tags` for project,
  components and labels.
- Preserve everything below `SYNC_MARKER` byte-for-byte; append the marker to
  a hand-created file that lacks one, destroying nothing.
- Write the unit tests listed below, including a **golden file**.

**NOT in scope**:
- Any file I/O. The renderer returns strings; TASK-2403 writes them.
- Any Jira call, any watermark, any orphan detection — TASK-2403.
- The `--enrich` LLM path. Out of scope for v1 beyond leaving the seam
  obvious: `render_issue_document` takes no client and must never take one.
- Emitting graph edges directly. `scan_vault` derives them from the
  wikilinks/tags this task emits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py` | CREATE | The pure renderer |
| `packages/ai-parrot/tests/knowledge/wiki/test_jira_render.py` | CREATE | Determinism, marker, wikilink, html2text tests |
| `packages/ai-parrot/tests/knowledge/wiki/conftest.py` | MODIFY | Append the `raw_issue` fixture wrapping `tests.fixtures.jira_payloads` |
| `packages/ai-parrot/tests/knowledge/wiki/fixtures/jira/NAV-9372.golden.md` | CREATE | Byte-exact golden document |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-24 at commit
> `53df566ef`. Confirm each anchor before writing code.

### Verified Imports

```python
from parrot.interfaces.jira import (          # TASK-2399
    JiraIssue, JiraIssueLink, JiraIssueLinkKind, JiraPerson,
)
from parrot.knowledge.okf import ConceptType  # okf/__init__.py:15-30; ISSUE added by TASK-2398
import html2text                              # pinned html2text==2025.4.15
import yaml                                   # PyYAML, already a dependency
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:209
def render_frontmatter(metadata: DocumentMetadata,
                       provenance: TriageProvenance | None = None) -> str: ...
# THE DETERMINISM CONTRACT TO MIRROR (docstring :213-219 + body :234-250):
#   payload = {}
#   for field in _FRONTMATTER_FIELD_ORDER:          # fixed tuple, NOT model order
#       value = getattr(metadata, field)
#       if value is not None:                       # None OMITTED
#           payload[field] = value
#   if metadata.extra:
#       payload["extra"] = {k: metadata.extra[k] for k in sorted(metadata.extra)}
#   if not payload:
#       return ""                                   # never an empty --- --- block
#   body = yaml.safe_dump(payload, sort_keys=False,  # <-- sort_keys=False is
#                         allow_unicode=True,        #     what preserves order
#                         default_flow_style=False)
#   return f"---\n{body}---\n\n"
# documents.py:39-50 — _FRONTMATTER_FIELD_ORDER is a module-level tuple.
#   MIRROR THIS: declare an explicit _ISSUE_FRONTMATTER_FIELD_ORDER tuple.
#   Do NOT rely on pydantic's model_fields ordering — it is an implementation
#   detail and a field reorder would silently churn every document.

# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:253
def split_frontmatter(text: str) -> tuple[dict[str, Any], str]: ...
# Returns ({}, text) unchanged when there is no leading --- block, when the
# block never terminates, or when it does not parse as a YAML mapping —
# "malformed frontmatter is never a hard error". Mirror that forgiveness.

# packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py — WHAT CONSUMES
#   THIS TASK'S OUTPUT (read the module docstring, lines 16-21):
#   resolved [[wikilink]] -> edge rel "references"
#   ![[embed]]            -> edge rel "embeds"
#   note -> tag page      -> edge rel "tagged"
#   folder                -> edge rel "contains"
# vault_scan.py:183 — an UNRESOLVED wikilink is DROPPED and appended to
#   VaultScanStats.unresolved_links as a (rel_path, target) tuple.
# vault_scan.py:166 — every note page is written with category="document".
#   The `type: Issue` value therefore lives in the markdown frontmatter, NOT
#   in WikiPageRecord.category. Do not try to influence the category.
# vault_scan.py:58 — VAULT_EXCLUDE_DIRS includes ".parrot".

# packages/ai-parrot/src/parrot/knowledge/okf/ontology.py:29
class ConceptType(str, Enum): ...   # ISSUE/PERSON/PROJECT added by TASK-2398
```

**The models to implement, from the spec's §2 M3 block** (declaration order
is the emitted key order — mirror it into the explicit tuple):

```python
class IssueSyncStamp(BaseModel):
    fetched_at: str
    extractor_version: int
    unreachable_since: str | None = None   # set when the ticket stops resolving

class IssueFrontmatter(BaseModel):
    type: ConceptType = ConceptType.ISSUE
    key: str
    title: str
    status: str
    resolution: str | None = None
    category: str                   # Jira issuetype
    project: str
    priority: str | None = None
    assignee: str | None = None
    assignee_id: str | None = None
    reporter: str | None = None
    reporter_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    resolved_at: str | None = None
    labels: list[str] = []
    components: list[str] = []
    epic: str | None = None
    parent: str | None = None
    subtasks: list[str] = []
    blocks: list[str] = []
    blocked_by: list[str] = []
    relates: list[str] = []
    duplicates: list[str] = []
    repo_pages: list[str] = []      # qualified ids, e.g. "repo::file:sdd/specs/x.spec.md"
    url: str
    sync: IssueSyncStamp
```

**Function signatures from the spec (§2 "New Public Interfaces", M3):**

```python
SYNC_MARKER: str = ("<!-- jira-sync:end — everything below is yours; "
                    "the extractor never touches it -->")
EXTRACTOR_VERSION: int = 1

def issue_filename(key: str) -> str: ...                # "NAV-9372" -> "NAV-9372.md"
def person_slug(person: JiraPerson) -> str: ...         # accountId-derived, stable
def split_at_marker(text: str) -> tuple[str, str]: ...  # (generated, human_tail)
def render_issue_document(issue: JiraIssue, *, fetched_at: datetime,
                          existing: str | None = None,
                          repo_pages: list[str] | None = None) -> str: ...
def render_person_note(person: JiraPerson, issue_keys: list[str], *,
                       existing: str | None = None) -> str: ...
def render_group_note(kind: Literal["project", "component", "label"], name: str,
                      issue_keys: list[str], *, existing: str | None = None) -> str: ...
```

### Does NOT Exist

- ~~`parrot/knowledge/wiki/jira_render.py`~~ — created by this task.
- ~~An existing Jira→markdown renderer anywhere in the repo~~ — none. The only
  Jira-to-text code is `_apply_structured_output` (`jiratoolkit.py:1254`),
  which emits dicts for an LLM, not documents.
- ~~An ADF parser~~ — none. Input is already HTML (`description_html`, from
  `expand=renderedFields`). Do not write an ADF or wiki-markup parser.
- ~~`RelationType.BLOCKS` / `.DUPLICATES` / `.RELATES_TO`~~ — not in the
  vocabulary and not added by this feature. Link precision lives in the
  **frontmatter** keys (`blocks:`, `blocked_by:`, `relates:`, `duplicates:`);
  the graph edge derived from a wikilink is always `references`.
- ~~Cross-namespace edges~~ — `wikitoolkit link` refuses them: *"Both pages
  must live in the same plane — there are no cross-namespace edges"*
  (`cli.py:2665-2666`). `repo_pages` is a **frontmatter list of qualified id
  strings**, findable by `query`, openable by `page`, **not** traversable by
  `related`. Never emit a `[[repo::…]]` wikilink — it would be an unresolved
  link that `scan_vault` drops anyway (`vault_scan.py:183`).
- ~~`documents.DocumentMetadata` reused for tickets~~ — it is document-shaped
  (title/author/page_count/word_count/loader), not ticket-shaped. Mirror its
  *contract*, do not reuse the model.
- ~~`render_frontmatter` reused directly~~ — it only accepts
  `DocumentMetadata`. Write a ticket-specific renderer following the same
  algorithm.
- ~~`html2text.html2text(html)` (the module-level convenience)~~ — it uses
  **default** options, including `body_width=78` line wrapping. Always
  construct and configure an `html2text.HTML2Text()` instance.

---

## Implementation Notes

### The sync-marker contract — read this twice

`split_at_marker(text) -> (generated, human_tail)`:

- The **first** occurrence of `SYNC_MARKER` at the start of a line splits the
  document. Everything from that line onward (marker included) is the human
  tail and is returned **byte-for-byte**, trailing whitespace and all.
- No marker → `(text, "")`. The caller then appends
  `"\n" + SYNC_MARKER + "\n"` so the next sync has an anchor. Nothing in the
  original text is discarded — a hand-created file's content ends up in
  `generated`, and the *caller* must therefore preserve it: when
  `existing` had no marker, its whole body is treated as human content and
  moved **below** a freshly appended marker. This is the one case where the
  file grows a marker; it must never lose a byte.
- **Duplicated marker**: only the first splits. Any later marker is inert
  text inside the human tail. Never "clean up" a second marker.
- **Marker inside a fenced code block**: v1 accepts this false positive
  *deliberately* — splitting on the first line-anchored occurrence is the
  behaviour that can never *lose* content (the code fence ends up in the human
  tail, preserved verbatim). Document this in the docstring; do not attempt
  fence-aware parsing, which trades a harmless mis-split for a real
  content-loss risk.

Add an explicit test for each of the four cases above. The consequence of a
bug here is someone's notes, silently.

### The determinism recipe

```python
_ISSUE_FRONTMATTER_FIELD_ORDER: tuple[str, ...] = (
    "type", "key", "title", "status", "resolution", "category", "project",
    "priority", "assignee", "assignee_id", "reporter", "reporter_id",
    "created_at", "updated_at", "resolved_at", "labels", "components",
    "epic", "parent", "subtasks", "blocks", "blocked_by", "relates",
    "duplicates", "repo_pages", "url", "sync",
)
```

Rules, all testable:
- Iterate the tuple, skip `None`, `yaml.safe_dump(..., sort_keys=False,
  allow_unicode=True, default_flow_style=False)`.
- **Every list field is `sorted()`** before emission — `labels`,
  `components`, `subtasks`, `blocks`, `blocked_by`, `relates`, `duplicates`,
  `repo_pages`. TASK-2399 deliberately leaves Jira's order intact; sorting is
  *this* module's job, exactly once.
- Datetimes are formatted through one helper to a single fixed shape
  (`"%Y-%m-%dT%H:%M:%S%z"` or plain ISO — pick one, use it everywhere,
  including `sync.fetched_at`). Never let a naive/aware mismatch or a locale
  reach the output.
- `type:` must serialize as the plain string `Issue`, not
  `!!python/object/apply:...ConceptType`. Because `ConceptType` is a
  `str, Enum`, pass `.value` explicitly into the payload — do not rely on
  `safe_dump` handling the enum.
- Empty lists: omit them (treat `[]` like `None`) so a ticket with no labels
  renders no `labels:` key. Pick this rule, assert it, and keep it consistent
  — the golden file locks it in.

### `html2text` configuration (must be explicit)

```python
def _converter() -> html2text.HTML2Text:
    conv = html2text.HTML2Text()
    conv.body_width = 0            # NEVER wrap — default 78 makes output
                                   # width-dependent and non-deterministic
    conv.unicode_snob = True       # keep real unicode, don't ASCII-fold
    conv.inline_links = True       # no [1]-style reference-link footnotes
    conv.protect_links = True
    conv.ignore_images = True      # attachments are refs; no inline images
    conv.single_line_break = True
    conv.wrap_links = False
    conv.wrap_list_items = False
    conv.mark_code = True          # preserve <code>/<pre> as fenced code
    return conv
```
Construct a **fresh instance per call** — `HTML2Text` carries mutable state
between conversions. A ticket with no rendered field must degrade to `""`,
never raise (spec §7).

### Body layout

Fixed section order, sections with no content **omitted** entirely (never
emitted empty — that is what keeps `--dry-run` diffs meaningful and keeps
determinism simple):

```markdown
---
<frontmatter>
---

# NAV-9372 — Forms lose the tenant when it is only in the URL

**Jira**: https://example.atlassian.net/browse/NAV-9372
Tags: #NAV #navigator-forms #api #multitenant #forms

## Description
<html2text output>

## Acceptance Criteria
<html2text output>

## Relations
- Epic: [[NAV-8000]]
- Parent: [[NAV-9000]]
- Subtasks: [[NAV-9373]], [[NAV-9374]]
- Blocks: [[NAV-9400]]
- Duplicated by: [[NAV-9111]]

## People
- Assignee: [[jesus-lara]]
- Reporter: [[ana-ruiz]]

## Status History
- 2026-07-02T11:00:00+0000 — priority: Medium → High
- 2026-08-20T16:02:07+0000 — status: To Do → In Progress

## Attachments
- `trace.har` (20.0 KB, application/json) — <url>

## Related Repo Pages
- `repo::file:sdd/specs/jira-extractor-llmwiki.spec.md`

<!-- jira-sync:end — everything below is yours; the extractor never touches it -->
```

The `**Jira**:` line is deliberate — it is the text-level join the repo plane
already FTS-indexes (spec §1 Non-Goals, §6 Integration Points).

### `person_slug` and `group_slug`

- `person_slug` derives from **`accountId`**, not the display name, so a rename
  never orphans the page — but the slug must stay human-readable. Recommended:
  `slugify(display_name) + "-" + short_hash(account_id)[:6]`, with the
  display-name part *stable across renames* being impossible; therefore the
  **filename must be driven by `account_id` alone**. Resolve this tension the
  way the spec's test demands: `test_person_slug_stable_from_account_id`
  asserts the slug is *unchanged by a display-name change*. So: slug =
  a deterministic transform of `account_id` only (e.g. a sanitized
  `account_id` — Jira account ids contain `:` which is not filename-safe).
  Put the display name in the note's `title`/H1, not in its filename.
- `group_slug` sanitizes project/component/label names for filenames
  (lowercase, non-alphanumerics → `-`, collapse runs, strip edges) and must be
  injective enough that two real labels don't collide; on collision, append a
  short hash. Test with a label containing `/`, a space, and an accent.

### Key Constraints

- **Pure**: no filesystem, no network, no clock. `fetched_at` is a parameter.
  A test asserts the module imports no `pathlib.Path.write_text`, `open`,
  `aiohttp`, `requests` or `jira`.
- **No LLM**: `render_issue_document` takes no client and no model config.
- Comments appear nowhere — v1 non-goal.
- Attachments are references only; nothing is downloaded.
- Google-style docstrings, strict type hints, pydantic v2.
- `logging.getLogger(__name__)`; no `print`.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:39-50, 209-250` —
  the determinism contract to mirror
- `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:253` —
  `split_frontmatter`'s forgiving style
- `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py:16-21, 160-190` —
  what consumes this output
- `packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py:101` —
  `project_frontmatter`, a second determinism precedent

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.jira_render import render_issue_document,
      render_person_note, render_group_note, split_at_marker, issue_filename,
      person_slug, SYNC_MARKER, EXTRACTOR_VERSION` works.
- [ ] **G2**: a fixed `JiraIssue` + fixed `fetched_at` renders **byte-identical**
      to the committed golden file.
- [ ] **G2**: rendering twice yields identical bytes, and re-rendering a
      document's own output changes nothing (idempotent).
- [ ] Frontmatter key order matches `_ISSUE_FRONTMATTER_FIELD_ORDER`
      exactly, every list is sorted, `None` and `[]` are omitted, and `type`
      serializes as the plain string `Issue`.
- [ ] **G4**: content below `SYNC_MARKER` survives byte-for-byte — including
      trailing whitespace, a duplicated marker, and a marker inside a code
      fence.
- [ ] A file with **no** marker gains one and loses **zero** bytes of its
      original content.
- [ ] **G7**: relations emit `[[KEY]]`; project/components/labels emit `#tags`.
- [ ] `repo_pages` renders as frontmatter + a plain-text section — **never**
      as a `[[repo::…]]` wikilink.
- [ ] `html_to_markdown` is deterministic across calls and preserves tables,
      fenced code and links; a `None`/empty input yields `""` without raising.
- [ ] `person_slug` is unchanged by a display-name change.
- [ ] The module performs no I/O and imports neither `jira` nor any HTTP
      client (asserted by a source-inspection test).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_jira_render.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_jira_render.py
import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from parrot.interfaces.jira import JiraIssue, JiraPerson, parse_issue
from parrot.knowledge.wiki import jira_render
from parrot.knowledge.wiki.jira_render import (
    EXTRACTOR_VERSION, SYNC_MARKER, issue_filename, person_slug,
    render_group_note, render_issue_document, render_person_note,
    split_at_marker,
)

GOLDEN = Path(__file__).parent / "fixtures" / "jira" / "NAV-9372.golden.md"
BASE = "https://example.atlassian.net"


@pytest.fixture
def frozen_now() -> datetime:
    """Fixed fetched_at so golden comparisons are byte-stable."""
    return datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def raw_issue() -> dict:
    # Shared payload from TASK-2399. Add these two fixtures to
    # packages/ai-parrot/tests/knowledge/wiki/conftest.py (it already exists).
    from tests.fixtures.jira_payloads import raw_issue_payload
    return raw_issue_payload()


@pytest.fixture
def issue(raw_issue) -> JiraIssue:
    return parse_issue(raw_issue, base_url=BASE, ac_field_id="customfield_10101")


class TestGoldenAndDeterminism:
    def test_golden(self, issue, frozen_now):
        """G2: byte-identical to the committed golden document."""
        rendered = render_issue_document(issue, fetched_at=frozen_now)
        if not GOLDEN.exists():          # first run: write, then COMMIT it
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(rendered, encoding="utf-8")
            pytest.fail("golden written — inspect and commit it, then re-run")
        assert rendered == GOLDEN.read_text(encoding="utf-8")

    def test_render_twice_identical(self, issue, frozen_now):
        a = render_issue_document(issue, fetched_at=frozen_now)
        b = render_issue_document(issue, fetched_at=frozen_now)
        assert a == b

    def test_idempotent_over_own_output(self, issue, frozen_now):
        once = render_issue_document(issue, fetched_at=frozen_now)
        twice = render_issue_document(issue, fetched_at=frozen_now, existing=once)
        assert twice == once


class TestFrontmatterContract:
    def _fm(self, text) -> dict:
        assert text.startswith("---\n")
        block = text.split("---\n", 2)[1]
        return yaml.safe_load(block)

    def test_key_order_matches_declared_tuple(self, issue, frozen_now):
        text = render_issue_document(issue, fetched_at=frozen_now)
        block = text.split("---\n", 2)[1]
        emitted = [ln.split(":", 1)[0] for ln in block.splitlines()
                   if ln and not ln.startswith((" ", "-"))]
        order = list(jira_render._ISSUE_FRONTMATTER_FIELD_ORDER)
        assert emitted == [k for k in order if k in emitted]

    def test_type_is_plain_string(self, issue, frozen_now):
        fm = self._fm(render_issue_document(issue, fetched_at=frozen_now))
        assert fm["type"] == "Issue"

    def test_lists_sorted(self, issue, frozen_now):
        fm = self._fm(render_issue_document(issue, fetched_at=frozen_now))
        for key in ("labels", "components", "subtasks"):
            if key in fm:
                assert fm[key] == sorted(fm[key]), key

    def test_none_and_empty_omitted(self, issue, frozen_now):
        fm = self._fm(render_issue_document(issue, fetched_at=frozen_now))
        assert "resolution" not in fm      # None in the fixture
        assert "resolved_at" not in fm
        assert all(v != [] for v in fm.values())

    def test_sync_stamp_present(self, issue, frozen_now):
        fm = self._fm(render_issue_document(issue, fetched_at=frozen_now))
        assert fm["sync"]["extractor_version"] == EXTRACTOR_VERSION
        assert fm["sync"]["fetched_at"]
        assert "unreachable_since" not in fm["sync"]


class TestSyncMarkerPreservation:
    """G4 — the highest-consequence path. A bug here eats someone's notes."""

    def test_preserves_human_tail_verbatim(self, issue, frozen_now):
        tail = f"{SYNC_MARKER}\n\n## My notes\n\nThis matters.\n\n   \t\n"
        existing = "---\nkey: NAV-9372\n---\n\nstale\n" + tail
        out = render_issue_document(issue, fetched_at=frozen_now,
                                    existing=existing)
        assert out.endswith(tail)

    def test_trailing_whitespace_survives(self, issue, frozen_now):
        tail = f"{SYNC_MARKER}\n\nnote with trailing spaces   \n\n\n"
        out = render_issue_document(issue, fetched_at=frozen_now,
                                    existing="old\n" + tail)
        assert out.endswith(tail)

    def test_missing_marker_is_appended_and_nothing_lost(self, issue, frozen_now):
        handmade = "# Hand written\n\nSomeone's irreplaceable note.\n"
        out = render_issue_document(issue, fetched_at=frozen_now,
                                    existing=handmade)
        assert SYNC_MARKER in out
        assert "Someone's irreplaceable note." in out

    def test_duplicated_marker_only_first_splits(self):
        text = f"gen\n{SYNC_MARKER}\nhuman a\n{SYNC_MARKER}\nhuman b\n"
        generated, tail = split_at_marker(text)
        assert generated == "gen\n"
        assert tail.count(SYNC_MARKER) == 2
        assert "human a" in tail and "human b" in tail

    def test_marker_inside_code_fence_splits_conservatively(self):
        """Documented v1 behaviour: first line-anchored match wins, and the
        fence lands (preserved) in the human tail. Never loses content."""
        text = f"gen\n```\n{SYNC_MARKER}\n```\ntail\n"
        generated, tail = split_at_marker(text)
        assert generated.startswith("gen")
        assert SYNC_MARKER in tail and "```" in tail

    def test_no_marker_returns_empty_tail(self):
        generated, tail = split_at_marker("just a document\n")
        assert generated == "just a document\n" and tail == ""


class TestWikilinksAndTags:
    def test_relations_emit_wikilinks(self, issue, frozen_now):
        out = render_issue_document(issue, fetched_at=frozen_now)
        for key in ("NAV-8000", "NAV-9000", "NAV-9373", "NAV-9400", "NAV-9111"):
            assert f"[[{key}]]" in out

    def test_tags_emitted_for_project_components_labels(self, issue, frozen_now):
        out = render_issue_document(issue, fetched_at=frozen_now)
        for tag in ("#NAV", "#navigator-forms", "#multitenant"):
            assert tag in out

    def test_repo_pages_are_never_wikilinks(self, issue, frozen_now):
        """Cross-namespace edges do not exist (cli.py:2665-2666)."""
        out = render_issue_document(
            issue, fetched_at=frozen_now,
            repo_pages=["repo::file:sdd/specs/jira-extractor-llmwiki.spec.md"])
        assert "[[repo::" not in out
        assert "repo::file:sdd/specs/jira-extractor-llmwiki.spec.md" in out

    def test_jira_url_line_present_for_fts_join(self, issue, frozen_now):
        out = render_issue_document(issue, fetched_at=frozen_now)
        assert "**Jira**:" in out and "/browse/NAV-9372" in out


class TestHtmlConversion:
    def test_deterministic(self):
        html = "<p>a <code>b</code></p><table><tr><td>x</td></tr></table>"
        first = jira_render.html_to_markdown(html)
        assert first == jira_render.html_to_markdown(html)

    def test_no_line_wrapping(self):
        html = "<p>" + ("word " * 200).strip() + "</p>"
        out = jira_render.html_to_markdown(html)
        assert max(len(l) for l in out.splitlines()) > 100, \
            "body_width must be 0 — default 78 wrapping is non-deterministic"

    def test_empty_and_none_degrade(self):
        assert jira_render.html_to_markdown(None) == ""
        assert jira_render.html_to_markdown("") == ""

    def test_links_and_code_survive(self):
        out = jira_render.html_to_markdown(
            '<p><a href="https://x/y">y</a> <pre>code()</pre></p>')
        assert "https://x/y" in out and "code()" in out


class TestSlugsAndFilenames:
    def test_issue_filename(self):
        assert issue_filename("NAV-9372") == "NAV-9372.md"

    def test_person_slug_stable_across_rename(self):
        a = person_slug(JiraPerson(account_id="5f8a:abc-123",
                                   display_name="Jesus Lara"))
        b = person_slug(JiraPerson(account_id="5f8a:abc-123",
                                   display_name="J. Lara Gonzalez"))
        assert a == b

    def test_person_slug_is_filename_safe(self):
        slug = person_slug(JiraPerson(account_id="5f8a:abc/123",
                                      display_name="X"))
        assert not set(slug) & set('/\\:*?"<>| ')

    @pytest.mark.parametrize("name", ["navigator/forms", "multi tenant", "café"])
    def test_group_slug_filename_safe(self, name):
        slug = jira_render.group_slug(name)
        assert slug and not set(slug) & set('/\\:*?"<>| ')


class TestSatelliteNotes:
    def test_person_note(self):
        person = JiraPerson(account_id="5f8a:abc-123", display_name="Jesus Lara")
        out = render_person_note(person, ["NAV-9372", "NAV-9000"])
        assert "Jesus Lara" in out
        assert "[[NAV-9372]]" in out and "[[NAV-9000]]" in out
        assert "Person" in out
        assert "@" not in out            # G9

    def test_person_note_keys_sorted(self):
        person = JiraPerson(account_id="a", display_name="A")
        out = render_person_note(person, ["NAV-3", "NAV-1", "NAV-2"])
        assert out.index("NAV-1") < out.index("NAV-2") < out.index("NAV-3")

    @pytest.mark.parametrize("kind", ["project", "component", "label"])
    def test_group_note(self, kind):
        out = render_group_note(kind, "navigator-forms", ["NAV-9372"])
        assert "[[NAV-9372]]" in out and "navigator-forms" in out

    def test_satellite_notes_preserve_human_tail(self):
        person = JiraPerson(account_id="a", display_name="A")
        tail = f"{SYNC_MARKER}\n\nmy note\n"
        out = render_person_note(person, ["NAV-1"], existing="old\n" + tail)
        assert out.endswith(tail)


class TestPurity:
    def test_no_io_or_network_imports(self):
        src = inspect.getsource(jira_render)
        for banned in ("import aiohttp", "import requests", "import httpx",
                       "import jira", "from jira ", "open(", ".write_text("):
            assert banned not in src, banned

    def test_render_takes_no_client(self):
        params = inspect.signature(render_issue_document).parameters
        assert not {"client", "llm", "model"} & set(params)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-extractor-llmwiki.spec.md` (§2 "Data Models" M3 block + "New Public Interfaces", §3 M3, §7 "Patterns"/"Known Risks", G2/G3/G4/G7) for full context
2. **Check dependencies** — TASK-2398 and TASK-2399 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `documents.py:39-50` and `:209-250` in full — the determinism
     algorithm is copied from there, not from this task file's summary
   - Read `vault_scan.py` lines 16-21 and 160-195 to confirm what your
     wikilinks/tags become
   - Confirm `ConceptType.ISSUE` exists (TASK-2398 landed)
   - Confirm the installed html2text option names:
     `source .venv/bin/activate && python -c "import html2text;
     print([a for a in dir(html2text.HTML2Text()) if not a.startswith('_')])"`
4. **Update status** in `sdd/tasks/index/jira-extractor-llmwiki.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Generate the golden file, then READ IT before committing it.** A golden
   test that locks in wrong output is worse than no golden test.
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2401-jira-deterministic-renderer.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude session 2026-08-24)
**Date**: 2026-08-24
**Notes**: Implemented `jira_render.py` with `IssueFrontmatter`/`IssueSyncStamp`,
`_ISSUE_FRONTMATTER_FIELD_ORDER` (mirroring `documents.py`'s determinism
contract exactly), `issue_filename`, `person_slug`/`group_slug`
(account-id-derived, filename-safe, collision-hash fallback),
`split_at_marker` (all four documented cases: verbatim preservation,
duplicated marker, code-fence false-positive, no-marker), a
freshly-instantiated-per-call `html2text.HTML2Text()` converter with every
option pinned explicitly, and `render_issue_document`/`render_person_note`/
`render_group_note`. Appended `raw_issue`/`remote_links` fixtures to the
existing `tests/knowledge/wiki/conftest.py` per scope, wrapping TASK-2399's
`tests/fixtures/jira_payloads.py`. Generated the golden file, inspected it
line-by-line before committing (confirmed correct frontmatter key order,
sorted lists, wikilinks, tags, and marker placement), then committed it.

All 36 tests pass (including the golden byte-comparison and all five
sync-marker edge cases); full re-run across all four completed tasks'
suites (76 tests) shows no regressions. `ruff check` clean on all
touched/created files (two auto-fixable style findings in the
task-specified test file — import order, `datetime.UTC` alias — applied
via `ruff check --fix`, no semantic change).

**Deviations from spec**: `JiraIssueLinkKind.CLONES`/`.CLONED_BY` have no
dedicated `IssueFrontmatter` field (the model only defines `blocks`/
`blocked_by`/`relates`/`duplicates`, per the spec's own M3 data model) —
mapped them into the `relates` frontmatter list, while the body's
`## Relations` section still renders their own specific labels ("Clones"/
"Cloned by") from the full link-kind set. Not explicitly specified either
way; no test exercises clones/cloned_by, so this is a reasonable additive
choice, not a spec contradiction.
