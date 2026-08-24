# TASK-2399: `parrot/interfaces/jira/` models + pure `parse_issue` projection

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki (`issues` namespace)
**Spec**: `sdd/specs/jira-extractor-llmwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

First half of **Module 1** (spec §3 M1, §2 "Data Models", G1/G9). Creates the
new `parrot/interfaces/jira/` package and the pure, network-free half of it:
the pydantic models plus `parse_issue`, the raw-Jira-JSON → `JiraIssue`
projection.

Splitting M1 in two is deliberate. `parse_issue` is a pure function with the
highest test-value-per-line in the feature (it is where the **PII boundary**
lives — G9), and it has no `jira` dependency at all. Keeping it separate from
the auth/transport work in TASK-2400 lets the renderer (TASK-2401) start
against a stable model surface, and lets the PII test be exhaustive without
any network scaffolding.

The package mirrors `parrot/interfaces/obsidian/`, whose docstring states the
same intent: *"One vault-access + parsing core reused by ObsidianToolkit, the
loaders, and wiki vault_scan."*

---

## Scope

- Create `packages/ai-parrot/src/parrot/interfaces/jira/__init__.py` exporting
  the public names (models now; `JiraInterface` is added by TASK-2400 — leave
  a clearly-marked placeholder-free `__all__` that TASK-2400 extends).
- Create `packages/ai-parrot/src/parrot/interfaces/jira/models.py` with every
  model in the spec's "Data Models" M1 block: `JiraPerson`,
  `JiraIssueLinkKind`, `JiraIssueLink`, `JiraChangeEvent`,
  `JiraAttachmentRef`, `JiraRemoteLink`, `JiraIssue`.
- Create `packages/ai-parrot/src/parrot/interfaces/jira/parse.py` with the
  pure projection functions, and re-export `parse_issue` so TASK-2400 can
  attach it as `JiraInterface.parse_issue` (a `@staticmethod`) without
  duplicating logic.
- Normalize Jira's issue-link representation into `JiraIssueLinkKind`,
  handling both the `inward`/`outward` directions Jira returns.
- **Drop `emailAddress` at the parse boundary** — it must never reach a
  model instance, so it cannot reach a document, a plane, or an OKF export.
- Write the unit tests listed below, including the `raw_issue` fixture the
  rest of the feature reuses.

**NOT in scope**:
- `JiraInterface`, auth, the lazy `jira` import, any network call — TASK-2400.
- The AC-field *resolution* (`resolve_ac_field_id`) — TASK-2400. This task
  only accepts an already-resolved field id as a parameter (see below).
- Any markdown rendering — TASK-2401.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/jira/__init__.py` | CREATE | Package docstring + model exports |
| `packages/ai-parrot/src/parrot/interfaces/jira/models.py` | CREATE | All pydantic v2 models |
| `packages/ai-parrot/src/parrot/interfaces/jira/parse.py` | CREATE | Pure `parse_issue` + helpers |
| `packages/ai-parrot/tests/interfaces/jira/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot/tests/fixtures/jira_payloads.py` | CREATE | Plain-function raw payloads, importable from any test package |
| `packages/ai-parrot/tests/interfaces/jira/conftest.py` | CREATE | Thin fixtures wrapping `jira_payloads` |
| `packages/ai-parrot/tests/interfaces/jira/test_jira_models.py` | CREATE | Model + projection + PII tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-24 at commit
> `53df566ef`. Confirm each anchor before writing code.

### Verified Imports

```python
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field
```
No `parrot.*` import is required by this task. **Do not import `jira`** —
this module must stay importable with the distribution absent.

### Existing Signatures to Use

The shape precedent — copy this style (flat pydantic models, no inheritance
gymnastics, `Path`/`set`/`list` fields with plain defaults):

```python
# packages/ai-parrot/src/parrot/interfaces/obsidian/models.py:38
class ObsidianNote(BaseModel):
    path: Path
    title: str
    content: str          # frontmatter stripped
    frontmatter: dict
    links: list[ObsidianLink]
    tags: set[str]
    aliases: list[str]
    dataview_queries: list[str]
```

The `__init__.py` precedent (module docstring naming every consumer, explicit
`__all__` tuple, factory function last):

```python
# packages/ai-parrot/src/parrot/interfaces/obsidian/__init__.py
"""Shared Obsidian vault interface (FEAT-392 + shared-interface work).

One vault-access + parsing core reused by:
* ``parrot.tools.obsidian.ObsidianToolkit`` — agent-facing tools
...
"""
from .abstract import ObsidianVaultInterface, VaultAccessError
from .models import (CANVAS_SUFFIX, ..., VaultSearchHit)
__all__ = ("CANVAS_SUFFIX", ...)
def create_vault_backend(backend: Literal["local", "rest"] = "local", **kwargs) -> ...
```

**The models to implement, verbatim from the spec (§2 "Data Models", M1):**

```python
class JiraPerson(BaseModel):
    """A Jira user. NO email field — G9."""
    account_id: str
    display_name: str

class JiraIssueLinkKind(str, Enum):
    BLOCKS = "blocks"; BLOCKED_BY = "blocked_by"; RELATES = "relates"
    DUPLICATES = "duplicates"; DUPLICATED_BY = "duplicated_by"
    CLONES = "clones"; CLONED_BY = "cloned_by"

class JiraIssueLink(BaseModel):
    kind: JiraIssueLinkKind
    target_key: str

class JiraChangeEvent(BaseModel):
    at: datetime
    field: str
    from_value: str | None = None
    to_value: str | None = None
    author: JiraPerson | None = None

class JiraAttachmentRef(BaseModel):
    """Reference only — never downloaded (Non-Goal)."""
    filename: str
    size_bytes: int | None = None
    mime_type: str | None = None
    url: str

class JiraRemoteLink(BaseModel):
    title: str
    url: str

class JiraIssue(BaseModel):
    key: str
    issue_id: str
    project_key: str
    issue_type: str                      # -> frontmatter `category`
    status: str
    resolution: str | None = None
    priority: str | None = None
    summary: str                         # -> frontmatter `title`
    description_html: str | None = None  # from expand=renderedFields
    acceptance_criteria_html: str | None = None
    assignee: JiraPerson | None = None
    reporter: JiraPerson | None = None
    labels: list[str] = []
    components: list[str] = []
    epic_key: str | None = None
    parent_key: str | None = None
    subtask_keys: list[str] = []
    links: list[JiraIssueLink] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    history: list[JiraChangeEvent] = []
    attachments: list[JiraAttachmentRef] = []
    remote_links: list[JiraRemoteLink] = []
    url: str                             # browse URL
```

**Signature this task ships** (note the added `ac_field_id` parameter — the
spec's §2 signature predates the resolved AC-field decision; TASK-2400
resolves the id and passes it in, so `parse` itself stays pure):

```python
def parse_issue(
    raw: dict[str, Any],
    *,
    base_url: str,
    ac_field_id: str | None = None,
) -> JiraIssue: ...
```

### Does NOT Exist

- ~~`parrot/interfaces/jira/`~~ — created by this task. Confirm with
  `ls packages/ai-parrot/src/parrot/interfaces/` (today: `file/`, `images/`,
  `obsidian/`, plus flat modules — **no `jira`**).
- ~~`parrot/knowledge/wiki/sources/jira.py`~~ — **cannot exist.**
  `parrot/knowledge/wiki/sources.py` is already a *module*
  (`SourceCollectionManager`); a `sources/` package beside it would shadow it
  and break `from .sources import SourceCollectionManager`.
- ~~An ADF (Atlassian Document Format) parser anywhere in the repo~~ — none.
  No `jira2markdown`, no `atlassian_doc`. Do not write one: `description_html`
  is populated from `expand=renderedFields`, and HTML→markdown is TASK-2401's
  job via `html2text`.
- ~~An existing Jira→markdown or Jira→model projection~~ — none. The only
  Jira-to-text code is `JiraToolkit._issue_to_dict` (`jiratoolkit.py:1134`)
  and `_apply_structured_output` (`:1254`), which emit LLM-shaped dicts, not
  documents. Read `_issue_to_dict` for the field-access idioms Jira raw JSON
  requires, but do **not** import from or depend on `parrot_tools`.
- ~~`JiraPerson.email` / `.email_address` / `.emailAddress`~~ — must not
  exist, in any spelling. G9.
- ~~`ConceptType.ISSUE`~~ — added by TASK-2398. This task does not reference
  it (models are OKF-agnostic; the enum is used by the renderer).

---

## Implementation Notes

### Pattern to Follow — issue-link direction normalization

Jira returns each link once, from the perspective of the issue you fetched,
under `fields.issuelinks[]`. An entry carries **either** `inwardIssue` **or**
`outwardIssue`, plus a `type` object with `name`, `inward` and `outward`
description strings:

```python
# Raw shape (verify against the fixture, not from memory):
{"type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
 "outwardIssue": {"key": "NAV-9400"}}     # -> BLOCKS,      target NAV-9400
{"type": {"name": "Blocks", ...},
 "inwardIssue":  {"key": "NAV-9300"}}     # -> BLOCKED_BY,  target NAV-9300
```

Map on `(type.name.lower(), direction)`:

| `type.name` | outward → | inward → |
|---|---|---|
| `Blocks` | `BLOCKS` | `BLOCKED_BY` |
| `Duplicate` | `DUPLICATES` | `DUPLICATED_BY` |
| `Cloners` | `CLONES` | `CLONED_BY` |
| `Relates` | `RELATES` | `RELATES` (symmetric) |

An **unknown** link type must degrade to `RELATES`, never raise — a Jira admin
can add link types at any time and a sweep must not die on one. Log at
`debug`. Keep the mapping table a module-level dict so it is testable and so
adding a type is a one-line change.

### Key Constraints

- **Pure**: no network, no filesystem, no LLM, no clock. `parse_issue` must be
  a deterministic function of `(raw, base_url, ac_field_id)`.
- **PII at the boundary**: build `JiraPerson` through a single
  `_person(raw_user: dict | None) -> JiraPerson | None` helper that reads
  *only* `accountId` and `displayName`. Never `**raw_user`, never
  `model_validate(raw_user)` — either would carry `emailAddress` through on a
  model with `extra` permitted, and would be a silent G9 violation the moment
  someone relaxes `model_config`.
- **Defensive field access**: raw Jira JSON omits keys freely. Every nested
  read goes through `.get()` chains; a missing `fields` dict yields a model
  with defaults, not a `KeyError`. `key`, `issue_id`, `project_key`,
  `issue_type`, `status`, `summary` and `url` are required — raise a clear
  `ValueError` naming the missing field if one is absent.
- **Datetime parsing**: Jira emits ISO-8601 with a `+0000`-style offset (no
  colon). `datetime.fromisoformat` handles this on Python 3.11+; the repo
  targets 3.11/3.12 (see the `.pyc` tags under `tests/__pycache__/`).
  Write a `_dt(value: str | None) -> datetime | None` helper that returns
  `None` on an unparseable value rather than raising.
- **History ordering**: sort `history` ascending by `at`, then by `field`, so
  the projection is stable when two changes share a timestamp. Determinism
  (G2) depends on this.
- **Collections**: leave `labels`/`components` in Jira's order here; the
  *renderer* sorts them (that is where the determinism contract lives).
  Document this split in the docstring so nobody sorts twice.
- Pydantic v2, Google-style docstrings, strict type hints. Use
  `Field(default_factory=list)` for the list fields rather than a bare `[]`
  literal shared across instances.
- `logging.getLogger(__name__)` at module level; no `print`.

### References in Codebase

- `packages/ai-parrot/src/parrot/interfaces/obsidian/models.py` — model style
- `packages/ai-parrot/src/parrot/interfaces/obsidian/__init__.py` — export style
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1134` —
  `_issue_to_dict`, for raw-JSON field-access idioms (read only; do not import)
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1291` —
  `_extract_field_history`, for the changelog shape

---

## Acceptance Criteria

- [ ] `from parrot.interfaces.jira import JiraIssue, JiraPerson, JiraIssueLink,
      JiraIssueLinkKind, JiraChangeEvent, JiraAttachmentRef, JiraRemoteLink,
      parse_issue` works.
- [ ] `import parrot.interfaces.jira` succeeds with the `jira` distribution
      **absent** (proven by a test that blocks `jira` in `sys.modules`).
- [ ] `parse_issue` is pure: called twice on the same input it returns equal
      models, and it performs no I/O.
- [ ] **G9**: no email address appears anywhere in
      `JiraIssue.model_dump_json()` for a raw payload that carries
      `emailAddress` on assignee, reporter *and* every changelog author; and
      `"email" not in JiraPerson.model_fields`.
- [ ] Issue links normalize correctly in both directions, and an unknown link
      type degrades to `RELATES` without raising.
- [ ] Epic, parent, subtasks, attachments (as refs), remote links and an
      ordered changelog all project correctly.
- [ ] A raw payload missing `fields` entirely raises a `ValueError` naming the
      missing required field — not a `KeyError`/`AttributeError`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/interfaces/jira/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/interfaces/jira/`
- [ ] No attachment is downloaded and no network call is made (no `aiohttp`,
      `requests`, `httpx` or `jira` import in the module).

---

## Test Specification

> **IMPORTANT — the payload must be importable, not conftest-local.**
> TASK-2401 and TASK-2403 test modules live under
> `tests/knowledge/wiki/`, and a `conftest.py` under
> `tests/interfaces/jira/` is **not** visible there. So the payload is a
> plain function in `tests/fixtures/jira_payloads.py`, and each test package's
> `conftest.py` wraps it in a one-line fixture. `tests/fixtures/` already
> holds shared test data (`bot_rows`, `websearchagent_crew.json`, …).

```python
# packages/ai-parrot/tests/fixtures/jira_payloads.py
"""Shared raw-Jira payloads for the FEAT-454 test suites.

Plain functions, not pytest fixtures, so any test package can import them:
``from tests.fixtures.jira_payloads import raw_issue_payload``. Each package's
conftest wraps them in fixtures.
"""
from typing import Any


def raw_issue_payload() -> dict[str, Any]:
    """Raw Jira JSON for NAV-9372 with expand=renderedFields,changelog.

    Deliberately exercises every projection branch AND carries
    ``emailAddress`` on assignee, reporter and a changelog author so the
    G9 boundary is provable. Shared with TASK-2400/2401/2403.
    """
    return {
        "id": "184220",
        "key": "NAV-9372",
        "self": "https://example.atlassian.net/rest/api/2/issue/184220",
        "fields": {
            "project": {"key": "NAV", "name": "Navigator"},
            "issuetype": {"name": "Bug"},
            "status": {"name": "In Progress"},
            "resolution": None,
            "priority": {"name": "High"},
            "summary": "Forms lose the tenant when it is only in the URL",
            "assignee": {
                "accountId": "5f8a:abc-123",
                "displayName": "Jesus Lara",
                "emailAddress": "jlara@example.com",   # MUST be dropped
            },
            "reporter": {
                "accountId": "5f8a:def-456",
                "displayName": "Ana Ruiz",
                "emailAddress": "aruiz@example.com",   # MUST be dropped
            },
            "labels": ["multitenant", "forms"],
            "components": [{"name": "navigator-forms"}, {"name": "api"}],
            "parent": {"key": "NAV-9000"},
            "customfield_10014": "NAV-8000",           # epic link
            "subtasks": [{"key": "NAV-9373"}, {"key": "NAV-9374"}],
            "issuelinks": [
                {"type": {"name": "Blocks", "inward": "is blocked by",
                          "outward": "blocks"},
                 "outwardIssue": {"key": "NAV-9400"}},
                {"type": {"name": "Duplicate", "inward": "is duplicated by",
                          "outward": "duplicates"},
                 "inwardIssue": {"key": "NAV-9111"}},
                {"type": {"name": "Mitigates", "inward": "is mitigated by",
                          "outward": "mitigates"},          # UNKNOWN type
                 "outwardIssue": {"key": "NAV-9500"}},
            ],
            "created": "2026-07-01T09:14:22.000+0000",
            "updated": "2026-08-20T16:02:07.000+0000",
            "resolutiondate": None,
            "attachment": [
                {"filename": "trace.har", "size": 20481,
                 "mimeType": "application/json",
                 "content": "https://example.atlassian.net/secure/attachment/1/trace.har"},
            ],
            "customfield_10101": "Given a tenant in the URL, when the form "
                                 "posts, then the tenant is preserved.",
        },
        "renderedFields": {
            "description": "<p>The form <code>POST</code> drops "
                           "<strong>tenant</strong>.</p>",
            "customfield_10101": "<p>Given a tenant in the URL...</p>",
        },
        "changelog": {
            "histories": [
                {"created": "2026-08-20T16:02:07.000+0000",
                 "author": {"accountId": "5f8a:abc-123",
                            "displayName": "Jesus Lara",
                            "emailAddress": "jlara@example.com"},
                 "items": [{"field": "status", "fromString": "To Do",
                            "toString": "In Progress"}]},
                {"created": "2026-07-02T11:00:00.000+0000",
                 "author": {"accountId": "5f8a:def-456",
                            "displayName": "Ana Ruiz"},
                 "items": [{"field": "priority", "fromString": "Medium",
                            "toString": "High"}]},
            ]
        },
    }


def remote_links_payload() -> list[dict[str, Any]]:
    """Raw /remotelink payload (fetched separately by TASK-2400)."""
    return [{"object": {"title": "Runbook", "url": "https://wiki/runbook"}}]
```

```python
# packages/ai-parrot/tests/interfaces/jira/conftest.py
import pytest

from tests.fixtures.jira_payloads import raw_issue_payload, remote_links_payload


@pytest.fixture
def raw_issue() -> dict:
    return raw_issue_payload()


@pytest.fixture
def remote_links() -> list[dict]:
    return remote_links_payload()
```

Add the identical two-fixture conftest under
`packages/ai-parrot/tests/knowledge/wiki/` as part of TASK-2401 — or, if that
package already has a `conftest.py` (it does), append the fixtures to it.
Verify the `tests.fixtures` import path resolves under this repo's pytest
config (`rootdir`/`pythonpath`) before relying on it; if it does not, import
by relative path the way neighbouring suites already do.

```python
# packages/ai-parrot/tests/interfaces/jira/test_jira_models.py
import json
import sys

import pytest

from parrot.interfaces.jira import (
    JiraAttachmentRef, JiraChangeEvent, JiraIssue, JiraIssueLink,
    JiraIssueLinkKind, JiraPerson, JiraRemoteLink, parse_issue,
)

BASE = "https://example.atlassian.net"


@pytest.fixture
def issue(raw_issue) -> JiraIssue:
    return parse_issue(raw_issue, base_url=BASE, ac_field_id="customfield_10101")


class TestParseIssueProjection:
    def test_core_fields(self, issue):
        assert issue.key == "NAV-9372"
        assert issue.issue_id == "184220"
        assert issue.project_key == "NAV"
        assert issue.issue_type == "Bug"
        assert issue.status == "In Progress"
        assert issue.priority == "High"
        assert issue.resolution is None
        assert issue.url == f"{BASE}/browse/NAV-9372"

    def test_hierarchy(self, issue):
        assert issue.parent_key == "NAV-9000"
        assert issue.epic_key == "NAV-8000"
        assert issue.subtask_keys == ["NAV-9373", "NAV-9374"]

    def test_links_normalized_both_directions(self, issue):
        by_target = {l.target_key: l.kind for l in issue.links}
        assert by_target["NAV-9400"] is JiraIssueLinkKind.BLOCKS
        assert by_target["NAV-9111"] is JiraIssueLinkKind.DUPLICATED_BY

    def test_unknown_link_type_degrades_to_relates(self, issue):
        by_target = {l.target_key: l.kind for l in issue.links}
        assert by_target["NAV-9500"] is JiraIssueLinkKind.RELATES

    def test_attachments_are_references_only(self, issue):
        (att,) = issue.attachments
        assert isinstance(att, JiraAttachmentRef)
        assert att.filename == "trace.har"
        assert att.size_bytes == 20481
        assert att.url.endswith("trace.har")

    def test_rendered_description_and_ac_captured_as_html(self, issue):
        assert "<strong>tenant</strong>" in issue.description_html
        assert issue.acceptance_criteria_html is not None

    def test_ac_omitted_when_field_id_not_given(self, raw_issue):
        parsed = parse_issue(raw_issue, base_url=BASE, ac_field_id=None)
        assert parsed.acceptance_criteria_html is None

    def test_history_sorted_ascending(self, issue):
        assert [e.field for e in issue.history] == ["priority", "status"]
        assert issue.history[0].at < issue.history[1].at
        assert issue.history[1].from_value == "To Do"
        assert issue.history[1].to_value == "In Progress"

    def test_labels_and_components(self, issue):
        assert set(issue.labels) == {"multitenant", "forms"}
        assert set(issue.components) == {"navigator-forms", "api"}


class TestPIIBoundary:
    """G9 — no personal email ever enters the plane."""

    def test_person_model_has_no_email_field(self):
        assert "email" not in JiraPerson.model_fields
        assert not any("email" in f.lower() for f in JiraPerson.model_fields)

    def test_no_email_anywhere_in_dump(self, issue):
        dumped = issue.model_dump_json()
        assert "@" not in dumped.replace("@example.atlassian.net", "") or \
            "jlara@example.com" not in dumped
        assert "jlara@example.com" not in dumped
        assert "aruiz@example.com" not in dumped
        assert "emailAddress" not in dumped

    def test_changelog_author_email_dropped(self, issue):
        for event in issue.history:
            if event.author is not None:
                assert "email" not in json.dumps(event.author.model_dump()).lower()


class TestPurityAndOptionalDependency:
    def test_importable_without_jira_installed(self, monkeypatch):
        """The package must not import `jira` at module load."""
        monkeypatch.setitem(sys.modules, "jira", None)
        import importlib
        import parrot.interfaces.jira as mod
        importlib.reload(mod)
        assert mod.JiraIssue is not None

    def test_parse_is_deterministic(self, raw_issue):
        a = parse_issue(raw_issue, base_url=BASE, ac_field_id="customfield_10101")
        b = parse_issue(raw_issue, base_url=BASE, ac_field_id="customfield_10101")
        assert a.model_dump_json() == b.model_dump_json()


class TestDefensiveParsing:
    def test_missing_fields_dict_raises_valueerror(self):
        with pytest.raises(ValueError, match="fields"):
            parse_issue({"id": "1", "key": "NAV-1"}, base_url=BASE)

    def test_sparse_issue_yields_defaults_not_keyerror(self):
        raw = {"id": "1", "key": "NAV-1", "fields": {
            "project": {"key": "NAV"}, "issuetype": {"name": "Task"},
            "status": {"name": "To Do"}, "summary": "s"}}
        parsed = parse_issue(raw, base_url=BASE)
        assert parsed.labels == [] and parsed.links == []
        assert parsed.assignee is None and parsed.description_html is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-extractor-llmwiki.spec.md` (§2 "Data Models", §3 M1, G1/G9) for full context
2. **Check dependencies** — none; this task is a leaf and may start immediately
3. **Verify the Codebase Contract** — before writing ANY code:
   - `ls packages/ai-parrot/src/parrot/interfaces/` — confirm no `jira/` yet
   - Read `packages/ai-parrot/src/parrot/interfaces/obsidian/models.py` and
     `__init__.py` for the style you must match
   - Read `jiratoolkit.py:1134` (`_issue_to_dict`) and `:1291`
     (`_extract_field_history`) for raw-JSON field-access idioms — **read
     only, do not import from `parrot_tools`**
   - Validate the `raw_issue` fixture against those idioms; if a field path
     is wrong, fix the fixture in this task file FIRST
4. **Update status** in `sdd/tasks/index/jira-extractor-llmwiki.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2399-jira-interface-models-and-parse.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
