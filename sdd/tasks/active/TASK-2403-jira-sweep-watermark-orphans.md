# TASK-2403: `jira_sync.py` — sweep, watermark, entity notes, orphan detection

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki (`issues` namespace)
**Spec**: `sdd/specs/jira-extractor-llmwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2400, TASK-2401
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** (spec §3 M4, §2 "Data Models" M4 block,
G3/G5/G7/G8). This is the orchestrator: resolve scope and watermark, page
through matching issues, render and write each document (preserving human
tails), accumulate satellite entity notes, detect orphans, and advance the
watermark **only** after a fully successful run.

Three invariants carry the most risk:

- **G5 — the watermark must never advance over a corpus that was not
  fetched.** Combined with the Jira Cloud silent-auth failure (200 + empty
  list + `X-Seraph-Loginreason: AUTHENTICATED_FAILED`), a naive
  "advance on completion" would permanently skip a range of tickets. The
  failure is silent and self-perpetuating — the spec calls it *"the worst
  failure mode here"*.
- **G3 — one document per ticket, updated in place.** No second copy, no
  duplicate pages, no accumulating edges.
- **G8 — off-repo storage.** The corpus root must resolve outside the
  repository working tree **even when `PARROT_HOME` is unset**. A relative
  default would write into the repo and violate G8.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py` with:
  - `JiraScopeState`, `JiraSyncState`, `SweepReport` (pydantic)
  - `jql_fingerprint`, `resolve_issues_dir`
  - `load_sync_state`, `save_sync_state`
  - `sweep_jira_issues`
- Resolve the effective JQL: caller-supplied `jql`, then the stored
  watermark as an `updated >= "<ts>"` conjunct (unless `--force`/`since`
  overrides).
- Page through issues via `JiraInterface.search_issues` with
  `expand=renderedFields,changelog`, render each with `jira_render`, and write
  only when the rendered bytes **differ** from what is on disk.
- Accumulate person / project / component / label membership across the sweep
  and emit the satellite notes once at the end.
- Detect orphans: a document on disk whose key is no longer in scope.
- Mark unreachable tickets (`sync.unreachable_since`) instead of deleting.
- Guard the output directory with the existing `wiki_write_lock`.
- Advance the watermark only on `last_run_status == "ok"`.
- Write the unit tests listed below.

**NOT in scope**:
- The CLI command and the build invocation — TASK-2404.
- Building the plane, registering the namespace — existing code, invoked by
  TASK-2404.
- Any markdown layout decision — that is TASK-2401's contract; this task
  calls it.
- Deleting orphan documents. v1 **reports** them; deletion is an operator
  action. (Silently deleting a document that carries a human tail would
  violate G4.)
- The `--enrich` LLM path.
- Fetching comments.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py` | CREATE | The sweep |
| `packages/ai-parrot/tests/knowledge/wiki/test_jira_sync.py` | CREATE | Watermark, orphan, idempotence, dry-run tests |
| `packages/ai-parrot/tests/knowledge/wiki/conftest.py` | MODIFY | Add `fake_jira_interface`, `issues_dir`, `frozen_now` fixtures |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-24 at commit
> `53df566ef`. Confirm each anchor before writing code.

### Verified Imports

```python
from parrot.interfaces.jira import JiraInterface, JiraIssue, JiraAuthError  # TASK-2400
from parrot.knowledge.wiki.jira_render import (                            # TASK-2401
    EXTRACTOR_VERSION, SYNC_MARKER, issue_filename, group_slug, person_slug,
    render_group_note, render_issue_document, render_person_note,
)
from parrot.knowledge.wiki.locks import wiki_write_lock   # VERIFY the module path first
```

**`wiki_write_lock` — resolve its real home before importing.** It is used in
`cli.py` at lines 77 (import), 1105, 1306 and 1713. Run:
```bash
grep -rn "def wiki_write_lock" packages/ai-parrot/src/parrot/knowledge/wiki/
sed -n '70,85p' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
```
and import from wherever it is actually defined.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1105 — the lock idiom
with wiki_write_lock(config.storage_path(root)) as _acquired:
    if not _acquired:
        click.echo("Another wiki writer is in progress (build or upsert) — "
                   "refusing to run two writers against the same store. Wait "
                   "for it to finish, then retry.")
        raise SystemExit(1)
# cli.py:1306 — the timeout variant:
with wiki_write_lock(config.storage_path(root),
                     timeout=UPSERT_LOCK_WAIT_SECONDS) as _acquired:
# This task's sweep guards the ISSUES DIRECTORY, not a repo store — pass the
# issues dir (or its .parrot/) so two crons cannot interleave file writes.

# packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py:58
VAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {".obsidian", ".trash", ".git", ".hg", ".svn", ".parrot"})
# ^ ".parrot" is already excluded, so <issues-dir>/.parrot/jira_sync.json is
#   NEVER re-ingested as a note. This is why the state file lives there.

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:381-388
def storage_path(self, root: Path) -> Path: ...   # absolute passthrough, else root/storage_dir
def db_path(self, root: Path) -> Path: ...        # -> <storage>/wiki.db
def load_project_config(root: Path) -> WikiProjectConfig: ...   # :514
#   Returns DEFAULTS when no .parrot/wiki.json exists (:538) — so `build`
#   works on a bare issues dir with no pre-created config. Raises
#   WikiConfigError only when a config file exists AND is invalid.

# packages/ai-parrot/src/parrot/interfaces/jira/client.py (TASK-2400)
async def search_issues(self, jql, *, fields=None, expand=None,
                        page_size=100) -> AsyncIterator[dict[str, Any]]: ...
async def get_issue(self, key, *, fields=None, expand=None) -> dict[str, Any]: ...
async def get_changelog(self, key, page_size=100) -> list[dict[str, Any]]: ...
async def get_remote_links(self, key) -> list[dict[str, Any]]: ...
async def resolve_ac_field_id(self) -> str | None: ...
async def verify_auth(self) -> dict[str, Any]: ...
@staticmethod
def parse_issue(raw, *, base_url, ac_field_id=None) -> JiraIssue: ...
```

**The models to implement, from the spec's §2 M4 block:**

```python
class JiraScopeState(BaseModel):
    jql: str
    jql_fingerprint: str            # sha256 of the normalized JQL
    last_watermark: str | None = None   # ISO-8601 `updated` high-water mark
    extractor_version: int
    last_run_at: str | None = None
    last_run_status: Literal["ok", "partial", "failed"] = "ok"

class JiraSyncState(BaseModel):
    """Persisted at <issues-dir>/.parrot/jira_sync.json."""
    version: int = 1
    scopes: dict[str, JiraScopeState] = {}   # keyed by jql_fingerprint

class SweepReport(BaseModel):
    fetched: int = 0
    written: int = 0
    unchanged: int = 0
    skipped: int = 0
    orphaned: int = 0
    entity_notes: int = 0
    unresolved_link_keys: list[str] = []
    watermark_advanced: bool = False
    errors: list[str] = []
```

**Public function signature (spec §2 "New Public Interfaces", M4):**

```python
async def sweep_jira_issues(
    interface: JiraInterface,
    issues_dir: Path,
    *,
    jql: str,
    since: datetime | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> SweepReport: ...

def load_sync_state(issues_dir: Path) -> JiraSyncState: ...
def save_sync_state(issues_dir: Path, state: JiraSyncState) -> None: ...
```

### Does NOT Exist

- ~~`parrot/knowledge/wiki/jira_sync.py`~~ — created by this task.
- ~~`SourceCollectionManager.add_source(uri: str)`~~ — the parameter is
  `path: Path` (`sources.py:177`). The `sources` table is **filesystem-shaped**;
  it is NOT where the watermark goes. Use
  `<issues-dir>/.parrot/jira_sync.json`.
- ~~`DocumentAcquirer` / `resolve_sources` handling a record or API source~~ —
  `resolve_sources` (`documents.py:154`) yields `DocumentRef`s from paths and
  URLs only, and `_acquire_via_loader` (`:632`) calls a file loader. Do not
  route Jira through it.
- ~~Cross-namespace edges~~ — `wikitoolkit link` refuses them
  (`cli.py:2665-2666`). This task writes **no edges at all**; `scan_vault`
  derives them from the wikilinks TASK-2401 emitted.
- ~~`ns add --vault` on a plain directory~~ — the option requires
  `.obsidian/` (`cli.py:1864`, `is_obsidian_vault` at `vault_scan.py:62`).
  The issues plane registers with `--store <dir>/.parrot/wiki`. Only **`build`**
  has a `--vault` *flag* that forces vault mode without the marker dir. (That
  is TASK-2404's concern; do not create a fake `.obsidian/` here.)
- ~~Writing into the repository's own plane~~ — hard non-goal. This module
  must never touch the repo's `.parrot/wiki`, and never call `scan_repository`
  or `repo_scan`.
- ~~A scheduler~~ — the runbook documents cron; no scheduling code ships.

---

## Implementation Notes

### `resolve_issues_dir` and G8

```python
def resolve_issues_dir(explicit: Path | str | None = None) -> Path:
    """Resolve the corpus root, guaranteed outside the repo working tree.

    Precedence: explicit argument, then ``JIRA_WIKI_ISSUES_DIR``, then
    ``${PARROT_HOME}/wikis/issues``. When ``PARROT_HOME`` is unset the
    fallback is an ABSOLUTE user-scoped path (``~/.parrot/wikis/issues``) —
    never a relative one, which would write into the current working
    directory and violate G8.
    """
```
Add a test that asserts the resolved default is absolute and is **not**
inside the repo root, with `PARROT_HOME` deleted from the environment.
Check whether the repo already has a `PARROT_HOME` resolver
(`grep -rn "PARROT_HOME" packages/ai-parrot/src/`) and reuse it if so.

### The watermark protocol — the G5 core

```
1. fp    = jql_fingerprint(jql)                # sha256 of normalized JQL
2. scope = state.scopes.get(fp)                # independent per JQL
3. effective_jql:
     force or since        -> use `jql` (+ `updated >= since` when since given)
     scope.extractor_version < EXTRACTOR_VERSION -> use `jql` (full re-render)
     scope.last_watermark  -> f'{jql} AND updated >= "{watermark}"'
     otherwise             -> `jql`             # first run = full backfill
4. Set scope.last_run_status = "partial" and SAVE, BEFORE fetching.
5. Sweep. Track max(updated) seen. On ANY error: append to report.errors,
   leave last_watermark UNTOUCHED, keep status "partial", save, return.
6. Only on a clean pass: last_watermark = max_updated_seen,
   last_run_status = "ok", extractor_version = EXTRACTOR_VERSION,
   watermark_advanced = True. Save.
```

Step 4 is what makes a crash safe: a process killed mid-sweep leaves
`"partial"` on disk, so the next run does not trust the old watermark's
completeness. Order the writes so this holds even on `SIGKILL`.

Normalize the JQL before fingerprinting (collapse whitespace, lowercase
keywords) so cosmetic edits do not orphan a watermark — but **document** that
a semantic change to the JQL intentionally starts a fresh scope.

Never derive the watermark from the local clock. It is
`max(issue.updated_at)` **as reported by Jira**, so clock skew between the
runner and Jira cannot skip tickets. Subtract nothing; Jira's `updated >=` is
inclusive, so the boundary ticket is re-fetched (cheap) rather than skipped
(silent loss).

### Unchanged detection (G3, and what makes the cron free)

```python
new_text = render_issue_document(issue, fetched_at=now,
                                 existing=existing_text, repo_pages=None)
if existing_text is not None and new_text == existing_text:
    report.unchanged += 1        # do NOT write — leaves mtime untouched
else:
    path.write_text(new_text, encoding="utf-8")
    report.written += 1
```
`test_unchanged_issue_not_rewritten` asserts the mtime is untouched, so the
comparison must happen **before** any write, and the write must not be a
truncate-then-write of identical bytes.

### The empty-result auth probe (§7's worst failure mode)

`JiraInterface.search_issues` already probes on an empty first page
(TASK-2400). This module must additionally treat a `JiraAuthError` from the
iterator as **fatal**: record it, keep `"partial"`, do not advance. Add
`test_empty_result_set_probes_auth` proving a failing probe raises rather than
advancing the watermark.

### Orphan detection

An orphan is a `*.md` at the corpus root whose key is not in the current
scope's fetched set. **Only meaningful on a full (`force`/first) sweep** — an
incremental run legitimately fetches almost nothing, so every document would
look orphaned. Gate it: detect orphans only when the effective JQL had no
`updated >=` conjunct, and say so in the report. Getting this wrong turns a
routine daily run into a scary "3000 orphans" line.

Scan only the corpus root (not `people/`, `projects/`, `components/`,
`labels/`, `.parrot/`). Report; never delete.

### Unreachable tickets

A 404/403 on a *known* ticket (one with a document on disk) sets
`sync.unreachable_since` in that document's frontmatter and keeps the file.
Re-render through `render_issue_document` so the human tail survives — do not
hand-edit the YAML. If the ticket resolves again later, clear the field.

### Entity notes

Accumulate in-memory during the sweep:
```python
people:     dict[str, tuple[JiraPerson, set[str]]]   # slug -> (person, keys)
projects:   dict[str, set[str]]
components: dict[str, set[str]]
labels:     dict[str, set[str]]
```
Emit once at the end, each into its subdirectory, each through the
`existing=`-aware renderer so human tails survive. **On an incremental
sweep, merge with the keys already listed in the note on disk** — otherwise a
daily run would rewrite `people/xxx.md` down to the one ticket that changed
that day. Parse the existing key list out of the note's generated region; that
is the one place this module reads back its own output.

### Key Constraints

- **Async-first**: `sweep_jira_issues` is async; file writes go through
  `asyncio.to_thread` (or are accepted as fast local I/O — pick one and be
  consistent; do not mix).
- **`dry_run=True` writes nothing at all** — not the documents, not the entity
  notes, not the state file. Assert byte-identity of the whole directory tree.
- **Never delete a file.** Not orphans, not unreachable tickets, not stale
  entity notes.
- `wiki_write_lock` guards the corpus dir; a second concurrent sweep must
  refuse, not interleave.
- No LLM call on the default path — `sweep_jira_issues` takes no client and no
  model config.
- `self.logger` / `logging.getLogger(__name__)`; no `print`.
- Google-style docstrings, strict type hints, pydantic v2.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1105, 1306` — the
  `wiki_write_lock` usage idiom
- `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py:58` — why
  `.parrot/` is the right home for the state file
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:514-557` —
  `load_project_config` / `save_project_config`, the JSON-state precedent
- `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:68-300` —
  `SourceCollectionManager`, for the *style* of incremental bookkeeping
  (read only; it is Path-shaped and not usable here)

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.jira_sync import sweep_jira_issues,
      load_sync_state, save_sync_state, JiraSyncState, JiraScopeState,
      SweepReport, resolve_issues_dir` works, with `jira` **absent**.
- [ ] **G5**: a clean run advances `last_watermark` to the max Jira-reported
      `updated`; a mid-sweep failure leaves it untouched with
      `last_run_status="partial"`.
- [ ] **G5**: a second run with no Jira changes fetches 0 issues and writes 0
      documents.
- [ ] Two different JQLs keep independent watermarks (keyed by fingerprint);
      neither reuses the other's.
- [ ] A higher `EXTRACTOR_VERSION` forces a re-render even when `updated` is
      unchanged.
- [ ] **G3**: re-sweeping a changed ticket leaves exactly one document; a
      byte-identical render counts as `unchanged` and leaves the file mtime
      untouched.
- [ ] **G4**: a human tail below `SYNC_MARKER` survives a re-sweep that
      changes the generated region — in ticket documents **and** entity notes.
- [ ] A zero-result page triggers the auth probe; a failed probe records an
      error and does **not** advance the watermark.
- [ ] Orphans are reported (never deleted), and orphan detection is skipped on
      an incremental sweep.
- [ ] A 404/403 on a known ticket sets `sync.unreachable_since` and keeps the
      document.
- [ ] `dry_run=True` leaves the directory tree byte-identical (including the
      state file) and still reports accurate counts.
- [ ] **G8**: with `PARROT_HOME` unset, `resolve_issues_dir()` returns an
      absolute path outside the repository working tree.
- [ ] Entity notes merge (not replace) their key lists on an incremental sweep.
- [ ] A concurrent sweep against the same directory is refused by the lock.
- [ ] No LLM call is possible: `sweep_jira_issues` accepts no client, and a
      raising client factory installed in the environment is never invoked.
- [ ] The repository's own `.parrot/wiki` is unmodified by a sweep.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_jira_sync.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_jira_sync.py
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot.interfaces.jira import JiraAuthError, JiraIssue, parse_issue
from parrot.knowledge.wiki.jira_render import SYNC_MARKER
from parrot.knowledge.wiki.jira_sync import (
    JiraScopeState, JiraSyncState, SweepReport, jql_fingerprint,
    load_sync_state, resolve_issues_dir, save_sync_state, sweep_jira_issues,
)

BASE = "https://example.atlassian.net"
JQL = "project = NAV"


# --- fixtures (add to tests/knowledge/wiki/conftest.py) --------------------

class FakeJiraInterface:
    """In-memory JiraInterface stand-in: no network, scriptable pages,
    plus a failure-injection hook for the partial-sweep tests."""

    def __init__(self, raw_issues, *, fail_after=None, unreachable=(),
                 probe_error=None, base_url=BASE):
        self.raw_issues = list(raw_issues)
        self.fail_after = fail_after
        self.unreachable = set(unreachable)
        self.probe_error = probe_error
        self.base_url = base_url
        self.searched: list[str] = []

    async def search_issues(self, jql, *, fields=None, expand=None,
                            page_size=100):
        self.searched.append(jql)
        if not self.raw_issues and self.probe_error is not None:
            raise self.probe_error
        for i, raw in enumerate(self.raw_issues):
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("injected mid-sweep failure")
            yield raw

    async def resolve_ac_field_id(self):
        return "customfield_10101"

    async def get_remote_links(self, key):
        return []

    async def verify_auth(self):
        if self.probe_error is not None:
            raise self.probe_error
        return {"accountId": "x"}

    @staticmethod
    def parse_issue(raw, *, base_url=BASE, ac_field_id=None):
        return parse_issue(raw, base_url=base_url, ac_field_id=ac_field_id)


@pytest.fixture
def issues_dir(tmp_path) -> Path:
    """Empty corpus root; assertions run against rendered bytes on disk."""
    d = tmp_path / "issues"
    d.mkdir()
    return d


def _sweep(iface, d, **kw) -> SweepReport:
    return asyncio.run(sweep_jira_issues(iface, d, jql=JQL, **kw))


def _tree(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes()
            for p in sorted(d.rglob("*")) if p.is_file()}


# --- tests ----------------------------------------------------------------

class TestWatermark:
    def test_advances_on_success(self, raw_issue, issues_dir):
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        state = load_sync_state(issues_dir)
        scope = state.scopes[jql_fingerprint(JQL)]
        assert report.watermark_advanced is True
        assert scope.last_run_status == "ok"
        assert scope.last_watermark.startswith("2026-08-20")

    def test_not_advanced_on_partial(self, raw_issue, issues_dir):
        iface = FakeJiraInterface([raw_issue, raw_issue], fail_after=1)
        report = _sweep(iface, issues_dir)
        scope = load_sync_state(issues_dir).scopes[jql_fingerprint(JQL)]
        assert report.errors and report.watermark_advanced is False
        assert scope.last_watermark is None
        assert scope.last_run_status == "partial"

    def test_partial_written_before_fetch(self, raw_issue, issues_dir):
        """A SIGKILL mid-sweep must leave 'partial' on disk."""
        iface = FakeJiraInterface([raw_issue], fail_after=0)
        _sweep(iface, issues_dir)
        raw = json.loads((issues_dir / ".parrot" / "jira_sync.json")
                         .read_text())
        fp = jql_fingerprint(JQL)
        assert raw["scopes"][fp]["last_run_status"] == "partial"

    def test_second_run_fetches_nothing(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        second = _sweep(FakeJiraInterface([]), issues_dir)
        assert second.fetched == 0 and second.written == 0

    def test_watermark_added_as_jql_conjunct(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        iface = FakeJiraInterface([])
        _sweep(iface, issues_dir)
        assert any("updated >=" in q for q in iface.searched)

    def test_scopes_keyed_by_fingerprint(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        asyncio.run(sweep_jira_issues(FakeJiraInterface([raw_issue]),
                                      issues_dir, jql="project = OTHER"))
        state = load_sync_state(issues_dir)
        assert len(state.scopes) == 2
        assert jql_fingerprint(JQL) != jql_fingerprint("project = OTHER")

    def test_force_ignores_watermark(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        iface = FakeJiraInterface([raw_issue])
        _sweep(iface, issues_dir, force=True)
        assert all("updated >=" not in q for q in iface.searched)

    def test_extractor_version_bump_forces_rerender(self, raw_issue,
                                                    issues_dir, monkeypatch):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        import parrot.knowledge.wiki.jira_sync as sync_mod
        monkeypatch.setattr(sync_mod, "EXTRACTOR_VERSION", 99)
        iface = FakeJiraInterface([raw_issue])
        report = _sweep(iface, issues_dir)
        assert all("updated >=" not in q for q in iface.searched)
        assert report.written >= 1

    def test_watermark_comes_from_jira_not_local_clock(self, raw_issue,
                                                      issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        scope = load_sync_state(issues_dir).scopes[jql_fingerprint(JQL)]
        assert "2026-08-20" in scope.last_watermark   # the fixture's `updated`


class TestAuthProbe:
    def test_empty_result_probes_and_does_not_advance(self, issues_dir):
        """The AUTHENTICATED_FAILED trap — the worst failure mode (§7)."""
        iface = FakeJiraInterface(
            [], probe_error=JiraAuthError("AUTHENTICATED_FAILED"))
        report = _sweep(iface, issues_dir)
        assert report.errors and report.watermark_advanced is False
        state = load_sync_state(issues_dir)
        assert state.scopes[jql_fingerprint(JQL)].last_watermark is None


class TestIdempotenceAndInPlaceUpdate:
    def test_one_document_per_ticket(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert len(list(issues_dir.glob("NAV-*.md"))) == 1

    def test_unchanged_issue_not_rewritten(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        path = issues_dir / "NAV-9372.md"
        before = path.stat().st_mtime_ns
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert report.unchanged >= 1 and report.written == 0
        assert path.stat().st_mtime_ns == before

    def test_changed_status_updates_in_place(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        changed = json.loads(json.dumps(raw_issue))
        changed["fields"]["status"]["name"] = "Done"
        changed["fields"]["updated"] = "2026-08-25T10:00:00.000+0000"
        report = _sweep(FakeJiraInterface([changed]), issues_dir, force=True)
        assert report.written == 1
        assert "Done" in (issues_dir / "NAV-9372.md").read_text()

    def test_human_tail_survives_resync(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        path = issues_dir / "NAV-9372.md"
        path.write_text(path.read_text() + "\n## My note\n\nkeep me\n")
        changed = json.loads(json.dumps(raw_issue))
        changed["fields"]["status"]["name"] = "Done"
        changed["fields"]["updated"] = "2026-08-25T10:00:00.000+0000"
        _sweep(FakeJiraInterface([changed]), issues_dir, force=True)
        text = path.read_text()
        assert "keep me" in text and "Done" in text


class TestEntityNotes:
    def test_notes_emitted(self, raw_issue, issues_dir):
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        assert report.entity_notes > 0
        assert list((issues_dir / "people").glob("*.md"))
        assert (issues_dir / "projects" / "NAV.md").exists()
        assert list((issues_dir / "components").glob("*.md"))
        assert list((issues_dir / "labels").glob("*.md"))

    def test_incremental_sweep_merges_keys(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        second = json.loads(json.dumps(raw_issue))
        second["key"] = "NAV-9999"
        second["id"] = "184221"
        second["fields"]["updated"] = "2026-08-25T10:00:00.000+0000"
        _sweep(FakeJiraInterface([second]), issues_dir)
        project_note = (issues_dir / "projects" / "NAV.md").read_text()
        assert "NAV-9372" in project_note and "NAV-9999" in project_note

    def test_entity_note_human_tail_survives(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        note = issues_dir / "projects" / "NAV.md"
        note.write_text(note.read_text() + "\nproject owner: Ana\n")
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert "project owner: Ana" in note.read_text()

    def test_no_email_in_any_generated_file(self, raw_issue, issues_dir):
        """G9 over the whole corpus."""
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        for path in issues_dir.rglob("*.md"):
            text = path.read_text()
            assert "jlara@example.com" not in text
            assert "aruiz@example.com" not in text


class TestOrphansAndUnreachable:
    def test_orphan_reported_on_full_sweep(self, raw_issue, issues_dir):
        (issues_dir / "NAV-0001.md").write_text("---\nkey: NAV-0001\n---\n")
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert report.orphaned == 1
        assert (issues_dir / "NAV-0001.md").exists(), "orphans are NEVER deleted"

    def test_orphans_skipped_on_incremental_sweep(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        report = _sweep(FakeJiraInterface([]), issues_dir)
        assert report.orphaned == 0, \
            "an incremental sweep must not call every document an orphan"

    def test_entity_dirs_not_scanned_for_orphans(self, raw_issue, issues_dir):
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert report.orphaned == 0

    def test_unreachable_marked_not_deleted(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        iface = FakeJiraInterface([], unreachable={"NAV-9372"})
        _sweep(iface, issues_dir, force=True)
        path = issues_dir / "NAV-9372.md"
        assert path.exists()
        assert "unreachable_since" in path.read_text()


class TestDryRun:
    def test_writes_nothing(self, raw_issue, issues_dir):
        before = _tree(issues_dir)
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir,
                        dry_run=True)
        assert _tree(issues_dir) == before
        assert report.fetched == 1

    def test_dry_run_does_not_write_state(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, dry_run=True)
        assert not (issues_dir / ".parrot" / "jira_sync.json").exists()


class TestStorageLocation:
    def test_default_is_absolute_and_outside_repo(self, monkeypatch, tmp_path):
        """G8 — a relative default would write into the working tree."""
        monkeypatch.delenv("PARROT_HOME", raising=False)
        monkeypatch.delenv("JIRA_WIKI_ISSUES_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        resolved = resolve_issues_dir()
        assert resolved.is_absolute()
        assert tmp_path not in resolved.parents and resolved != tmp_path

    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_WIKI_ISSUES_DIR", str(tmp_path / "custom"))
        assert resolve_issues_dir() == tmp_path / "custom"

    def test_state_file_lives_under_dot_parrot(self, raw_issue, issues_dir):
        """.parrot is in VAULT_EXCLUDE_DIRS, so it is never re-ingested."""
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        assert (issues_dir / ".parrot" / "jira_sync.json").exists()


class TestNoLLM:
    def test_sweep_accepts_no_client(self):
        import inspect
        params = set(inspect.signature(sweep_jira_issues).parameters)
        assert not params & {"client", "llm", "model", "enrich"}

    def test_no_llm_import_in_module(self):
        import inspect
        import parrot.knowledge.wiki.jira_sync as mod
        src = inspect.getsource(mod)
        for banned in ("AbstractClient", "get_client", "completion("):
            assert banned not in src, banned


class TestConcurrency:
    def test_second_writer_refused(self, raw_issue, issues_dir):
        """wiki_write_lock — two crons must not interleave writes."""
        ...   # acquire the lock manually, then assert the sweep refuses
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-extractor-llmwiki.spec.md` (§2 "Data Models" M4 + "New Public Interfaces", §3 M4, §7 "Known Risks", G3/G4/G5/G8) for full context
2. **Check dependencies** — TASK-2400 and TASK-2401 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - `grep -rn "def wiki_write_lock" packages/ai-parrot/src/parrot/knowledge/wiki/`
     and read its real signature + semantics
   - `grep -rn "PARROT_HOME" packages/ai-parrot/src/` — reuse an existing
     resolver if one exists rather than writing a second one
   - Read `cli.py:1100-1115` and `:1300-1315` for the lock idiom
   - Confirm TASK-2401's exported names match what you import
4. **Update status** in `sdd/tasks/index/jira-extractor-llmwiki.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above.
   Write the watermark protocol first and get its tests green before adding
   entity notes or orphan detection — it is the part whose failure is silent.
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2403-jira-sweep-watermark-orphans.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
