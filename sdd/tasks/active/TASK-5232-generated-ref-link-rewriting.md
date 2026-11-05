# TASK-5232: Rewrite and validate links in generated API reference pages

**Feature**: FEAT-818 — Rewrite and validate generated API reference links
**Spec**: `sdd/specs/fixgroup-cdf36c115545.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:0891861cb3c1`

---

## Context

Implements spec §3 Module 1 and Module 2 in one unit.

`assemble()` (`bundle.py:211`) builds a manifest of every page id → page name,
then rewrites each page's Markdown links into `[[Wiki Page]]` links, recording
anything it cannot resolve in `BundleReport.dangling`. That rewrite loop opens
with `if page.source is None: continue` (`bundle.py:278`) — and `source is None`
is precisely the marker of a **generated** page. So the API reference module
pages and the reference index page are skipped by both the rewrite and the
validation.

The generated module template emits exactly the links that are being skipped:
`templates/module.md.j2:45` renders
``Re-exported from [`{{ m.target }}`](ref:{{ m.target_module }}).`` for every
re-export alias. Those reach the published GitHub wiki as literal
`ref:parrot.a2a.client` targets, which GitHub renders as dead links — while
`report.ok()` returns `True` and the CLI exits 0.

Confirmed at `95b65f964a` during the FEAT-801 `/sdd-done` independent review:
a full bundle reported `dangling=[]` while
`API-Reference-Reference:-parrot.a2a.md` retained literal `ref:` links.

The fix and its regression coverage are ONE task on purpose: splitting them
would land a behaviour change in `bundle.py` with no test proving it, and the
tests cannot be written against the old behaviour.

---

## Scope

- Modify the rewrite loop in `assemble()` so it covers **every** page, not only
  pages with a source path.
- Make the per-page `resolve()` closure source-aware: build the manifest key
  from `ref:`/`index:` targets verbatim; for a relative `.md` target on a page
  with no source, record it dangling instead of dereferencing `None`.
- Label dangling rows from generated pages with `_ref_id(page)`
  (`ref:<module>` / `index:<name>`), not a source path.
- Add two regression tests to `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py`.

**NOT in scope**:
- `naming.py`'s `rewrite_links()`, `templates/module.md.j2`, the manifest
  schema, `assemble()`'s signature, or the `ref:`/`index:` id grammar.
- Any other FEAT-801 review issue (`issue:99a0520cffbd`, `issue:822353a98341`,
  `issue:adb6da4375c7`, `issue:046f034dd3ef`) — separate ledger groups.
- Fixing any genuine dangling link this change may newly surface in the real
  `parrot.*` tree (see Implementation Notes → R1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py` | MODIFY | Source-aware rewrite loop in `assemble()` |
| `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` | MODIFY | Two regression tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `7929b4dee6`.

### Verified Imports

```python
# already at the top of bundle.py — do not re-add
import posixpath                                              # verified: bundle.py:8
from pathlib import Path, PurePosixPath                       # verified: bundle.py:10
from parrot.sdd.techwiki.naming import PageNameError, page_name, page_title, rewrite_links  # verified: bundle.py:16

# already at the top of test_techwiki_bundle.py — do not re-add
from parrot.sdd.techwiki.bundle import assemble, write_bundle  # verified: test_techwiki_bundle.py:13
from parrot.sdd.techwiki.config import load_techwiki_config    # verified: test_techwiki_bundle.py:14
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py
@dataclass
class BundlePage:                                      # line 23
    source: Path | None                                # line 26 — None marks a generated page
    section: str                                       # line 27
    title: str                                         # line 28
    name: str                                          # line 29
    body: str                                          # line 30
    module: str | None = None                          # line 31

@dataclass
class BundleReport:                                    # line 35
    dangling: list[dict[str, str]] = field(default_factory=list)   # line 46
    def ok(self) -> bool: ...                          # line 48

def _source_id(root: Path, source: Path) -> str: ...   # line 78
def _generated_pages(cfg, root, release) -> tuple[list[BundlePage], list[dict]]: ...  # line 149
def assemble(cfg, root, *, release=None, commit=None, with_api=True) -> tuple[list[BundlePage], BundleReport]: ...  # line 211
def _ref_id(page: BundlePage) -> str: ...              # line 295

# packages/ai-parrot/src/parrot/sdd/techwiki/naming.py
def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str: ...  # line 84
# Contract: calls resolver(base) only for targets starting "ref:" or ending ".md";
# returns the ORIGINAL match untouched when the resolver returns None.

# packages/ai-parrot/tests/sdd/test_techwiki_bundle.py
@pytest.fixture
def techwiki_repo(tmp_path: Path) -> Path: ...         # line 18 — no griffe needed
@pytest.fixture
def api_repo(techwiki_repo: Path) -> Path: ...         # line 168 — skips without the griffe extra
```

### Does NOT Exist

- ~~`BundlePage.path`~~ — the attribute is `source` (`bundle.py:26`); verified `grep -c "path:" ` on the dataclass → 0.
- ~~`BundleReport.unresolved`~~ — the list is `dangling` (`bundle.py:46`).
- ~~`BundlePage.is_generated()`~~ — verified `grep -c is_generated bundle.py` → 0. `source is None` is the only marker.
- ~~`rewrite_links(text, resolver, base)`~~ — it takes exactly two arguments (`naming.py:84`).
- ~~`_ref_id("some.module")`~~ — it takes a `BundlePage`, not a string (`bundle.py:295`).
- ~~`parrot.sdd.techwiki.apiref`~~ — verified absent; the module is `parrot.sdd.techwiki.api`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_techwiki_bundle.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#assemble",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_ref_id",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_source_id",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#_generated_pages",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#BundlePage",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py#BundleReport",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/naming.py#rewrite_links"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Keep the default-argument binding** `page: BundlePage = page` on the
  closure. It is what pins the loop variable at definition time; drop it and
  every page but the last resolves against the wrong origin.
- `rewrite_links` leaves an unresolved link verbatim, so a dangling generated
  link is both reported *and* left as-is — the same contract authored pages
  already have. Do not add a "replace with a placeholder" behaviour.
- 120-column lines, Google-style docstring on the closure, `ruff check --fix`
  on both changed files. No `print`; this change needs no new logging.

### Known Risks / Gotchas

- **R1 — the fix can turn a green bundle red.** Validating generated pages for
  the first time may surface genuine pre-existing dangling links in the real
  `parrot.*` tree (a re-export whose target module is outside the configured
  roots). That is the bug being fixed, not a regression: those links were
  already dead on the published wiki. If `parrot sdd techwiki bundle` now exits
  non-zero on this repository, record the dangling rows in the Completion Note
  and open a ledger issue for them. Do **not** suppress the validation to keep
  the exit code green, and do not widen this task to fix them.
- **R2 — the reference index page has nothing to rewrite.** `_reference_index_page`
  emits `[[...]]` links directly (`bundle.py:187`), not `[x](ref:…)`. Including
  it in the loop is harmless and keeps the rule uniform — do not special-case it out.
- **R3 — griffe gating.** `api_repo` *skips* without the griffe extra, so a green
  local run does not prove the first test ran. Confirm it is not reported as
  skipped (`-rs`), or run with `TECHWIKI_REQUIRE_GRIFFE=1`.
- **R5 — a peer branch is mid-flight in these same two files.** `fix-1f9d9ff0ec07-techwiki-markdown-links`
  (brief `1f9d9ff0ec07`, based on `dev`, pushed and awaiting `/sdd-done`) changes `rewrite_links` to emit
  `[text](percent-encoded-name)` instead of `[[Page]]`, and rewrites `test_techwiki_bundle.py` lines 66-290.
  It does **not** touch `assemble()`'s rewrite loop, so this task's `bundle.py` edit does not conflict with
  it, and its own strengthened guard still cannot catch this bug (it skips `ref:` targets as external URLs
  via `^[A-Za-z][A-Za-z0-9+.-]*:`), so this issue stays open either way. Two rules keep the lanes apart:
  **append** the new tests at end-of-file rather than mid-file, and **never assert on link syntax** — assert
  the resolved page name is present and `](ref:` is absent. Do not rebase onto that branch; base on
  `origin/dev` as usual.
- **R4 — the loop head is ambiguous.** `grep -c '^    for page in pages:' bundle.py`
  → **6**. Attach every edit to the unique `def resolve(` line, never to the loop head.

### References in Codebase

- `packages/ai-parrot/src/parrot/sdd/techwiki/naming.py:84` — the resolver contract.
- `packages/ai-parrot/src/parrot/sdd/techwiki/templates/module.md.j2:45` — the `ref:` emitter.
- `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py:192` — `test_ref_links_resolve_to_generated_pages`,
  the existing authored-page twin of the first new test; mirror its style.

---

## Implementation Blueprint

### Steps (in order)

1. Replace the rewrite loop in `bundle.py` with the block below — *why*: dropping the
   `if page.source is None: continue` guard is the whole fix; the closure must become
   source-aware in the same edit or it will dereference `None`.
2. Run `ruff check --fix` on `bundle.py` — *why*: the repo's lint gate (TID251 and style).
3. Add the two tests to `test_techwiki_bundle.py` after
   `test_every_rewritten_link_resolves_in_the_manifest` — *why*: that is the existing
   guard the bug slipped past, so the new tests belong beside it.
4. Confirm both new tests FAIL on a stash of the `bundle.py` change — *why*: AC-4; a
   regression test that passes before the fix proves nothing.
5. Run the full file green, with the griffe test not skipped — *why*: AC-5, R3.

### `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def resolve(target: str, page: BundlePage = page) -> str | None:' packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py)
# REPLACE the whole loop that currently begins at bundle.py:277 with the block below.
# Its first line is `    for page in pages:` (ambiguous — 6 occurrences), so locate the
# block by the unique `def resolve(` anchor at bundle.py:281 and extend the replacement
# outward: three lines up (to `    for page in pages:`) and down to and including
# `        page.body = rewrite_links(page.body, resolve)` at bundle.py:291.
    for page in pages:

        def resolve(target: str, page: BundlePage = page) -> str | None:
            """Return the wiki page name a link target names, recording unresolved targets as dangling.

            Args:
                target: The raw Markdown link target (``ref:<module>``, ``index:<name>`` or a relative path).
                page: The page the link appears on, bound at definition time.

            Returns:
                The resolved page name, or ``None`` when the target is not in the manifest.
            """
            origin = _source_id(root, page.source) if page.source is not None else _ref_id(page)
            if target.startswith(("ref:", "index:")):
                key = target
            elif page.source is None:
                # A generated page has no location in the source tree to resolve a relative link against.
                report.dangling.append({"source": origin, "target": target})
                return None
            else:
                key = posixpath.normpath(str(PurePosixPath(_source_id(root, page.source)).parent / target))
            resolved = manifest.get(key)
            if resolved is None:
                report.dangling.append({"source": origin, "target": target})
            return resolved

        page.body = rewrite_links(page.body, resolve)
```

**Why this shape**: the guard `if page.source is None: continue` was the defect — it
excluded generated pages from both rewriting and validation. Removing it forces the
closure to stop assuming `page.source` is a `Path`, which is what `origin` and the
`elif page.source is None` branch handle. `origin` is computed once so both dangling
sites agree on the label. The `startswith` widens to `("ref:", "index:")` because
`_ref_id` mints `index:<name>` for the reference index page and that key is already
registered in `manifest` at `bundle.py:272-273` — accepting it keeps key construction
symmetric with the manifest. Do not change `assemble()`'s signature, the `dangling`
row keys (`source`/`target`), or the default-argument binding.

### `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_authored_page_colliding_with_a_generated_name' packages/ai-parrot/tests/sdd/test_techwiki_bundle.py)
# APPEND AT END OF FILE — after the body of
# `def test_authored_page_colliding_with_a_generated_name(api_repo: Path) -> None:`
# (verified: packages/ai-parrot/tests/sdd/test_techwiki_bundle.py:289), which is the last
# function in the file (299 lines at 7929b4dee6).
# Placement is deliberate — see Known Risks R5: the unmerged branch
# fix-1f9d9ff0ec07-techwiki-markdown-links rewrites lines 66-290 of this file. Appending at
# the end keeps this task out of its diff entirely.


def test_generated_page_ref_links_are_rewritten(api_repo: Path) -> None:
    """issue:0891861cb3c1 — a generated page's ``ref:`` links are rewritten, not published verbatim."""
    cfg = load_techwiki_config(api_repo)
    pages, report = assemble(cfg, api_repo)
    init = next(p for p in pages if p.module == "samplepkg")
    # samplepkg/__init__.py re-exports PublicModel from .core, so module.md.j2:45 renders a
    # ref:samplepkg.core link into this page's body.
    # Assert on the resolved PAGE NAME, never on the link syntax: "[[Page]]" on dev today,
    # "[text](Page)" once fix-1f9d9ff0ec07-techwiki-markdown-links merges (see R5). Both
    # contain the bare name; neither contains "](ref:".
    assert "API-Reference-samplepkg.core" in init.body
    assert "](ref:" not in init.body
    # FILL IN: assert no generated page body retains a literal "](ref:" target — iterate the
    # pages whose source is None; bounded by AC-1 (the assertion must cover every generated
    # page, not only samplepkg).
    assert report.ok(), (report.collisions, report.dangling)


def test_unresolvable_links_in_a_generated_page_are_dangling(
    techwiki_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated page's unresolvable ``ref:`` and relative targets are reported, not crashed on."""
    from parrot.sdd.techwiki import bundle as bundle_module

    def fake_generated(cfg, root, release):  # type: ignore[no-untyped-def]
        page = bundle_module.BundlePage(
            source=None,
            section=cfg.reference_section,
            title="samplepkg.fake",
            name="API-Reference-samplepkg.fake",
            body="# fake\n\n[Gone](ref:samplepkg.gone) [Rel](../other.md)\n",
            module="samplepkg.fake",
        )
        return [page], []

    monkeypatch.setattr(bundle_module, "_generated_pages", fake_generated)
    cfg = load_techwiki_config(techwiki_repo)
    pages, report = assemble(cfg, techwiki_repo)
    # FILL IN: assert report.dangling contains BOTH rows, each with source == "ref:samplepkg.fake"
    # and targets "ref:samplepkg.gone" and "../other.md"; bounded by AC-2 and AC-3. The relative
    # row proves the no-source branch returns instead of dereferencing page.source.
    assert not report.ok()
```

**Why**: the first test is the true regression — it drives the real griffe pipeline and
the real template, so it fails on `dev` exactly as the published wiki does. The second
is deliberately griffe-free: monkeypatching `_generated_pages` (called by name inside
`assemble`, `bundle.py:240`) lets it run everywhere and lets it inject the relative-path
target that AC-3 needs, which the real template never emits. Use `techwiki_repo`, not
`api_repo`, for the second test — `api_repo` would make it skip without the extra.
Do not weaken either test to assert only on authored pages.

### FILL IN checklist

- [ ] `test_generated_page_ref_links_are_rewritten` — assertion that no generated page body
      retains `](ref:`; bounded by AC-1 (must cover every `source is None` page).
- [ ] `test_unresolvable_links_in_a_generated_page_are_dangling` — the two expected
      `report.dangling` rows and their `source` label; bounded by AC-2 and AC-3.

---

## Acceptance Criteria

- [ ] AC-1: `assemble()` rewrites `ref:<module>` links in generated page bodies to
      `[[<page name>]]`; no generated page body contains a literal `](ref:` target when
      every referenced module is in the manifest.
- [ ] AC-2: An unresolvable link in a generated page appears in `BundleReport.dangling`
      with `source` set to that page's `ref:<module>` (or `index:<name>`) id, and
      `report.ok()` is `False`.
- [ ] AC-3: A relative `.md` target inside a generated page is reported dangling and
      never raises `AttributeError`.
- [ ] AC-4: Both new tests fail with the `bundle.py` change reverted, and pass with it.
- [ ] AC-5: `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` is green, with no
      pre-existing test modified to accommodate the change, and the griffe-gated test not skipped.
- [ ] AC-8: No assertion in either new test depends on `[[Page]]` vs `[text](Page)` link syntax,
      and both are appended after the file's last existing function (R5).
- [ ] AC-6: `ruff check` clean on both changed files.
- [ ] AC-7: No change to `naming.py`, `module.md.j2`, the manifest schema, or `assemble()`'s signature.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py::test_generated_page_ref_links_are_rewritten -q`
- `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py::test_unresolvable_links_in_a_generated_page_are_dangling -q`

---

## Test Specification

Both tests go in `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py`, in the
"bundle + real generated API pages" section, after
`test_every_rewritten_link_resolves_in_the_manifest` (`:233`). Scaffolds are in the
Implementation Blueprint above. No new fixture files: `techwiki_repo` (`:18`) and
`api_repo` (`:168`) already exist, and `tests/sdd/fixtures/techwiki_pkg/samplepkg/__init__.py`
already re-exports `PublicModel` from `.core`, which is what makes the first test's
`ref:samplepkg.core` link appear.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug fixgroup-cdf36c115545 --feature-id FEAT-818`).
2. Run validation with `PYTHONPATH=packages/ai-parrot/src` (absolute path from the
   worktree root) — the shared venv is editable-installed against the main checkout, so
   a bare `pytest` imports the wrong branch.
3. Verify the Codebase Contract before writing code; if an anchor has drifted, fix the
   contract in this file first and say so in the Completion Note.
4. Stage only the two files this task lists. Never `git add .` / `-A`.
5. Close with `parrot sdd task close TASK-5232 fixgroup-cdf36c115545 verified`.

---

## Completion Note

*(filled in when the task is closed)*
