---
type: feature
base_branch: dev
projects: []
tags: [techwiki, sdd-tooling, bugfix]
docs:
  policy: none
---

# Feature Specification: Rewrite and validate generated API reference links

**Feature ID**: FEAT-818
**Date**: 2026-11-05
**Author**: Jesus (via /sdd-fix issue:0891861cb3c1)
**Status**: approved
**Target version**: 2.1.1

---

## 1. Motivation & Business Requirements

### Problem Statement

`assemble()` in `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py` rewrites
`ref:<module>` / relative Markdown links into `[[Wiki Page]]` links, but its
rewrite loop begins with:

```python
for page in pages:
    if page.source is None:
        continue
```

`page.source is None` is exactly the marker for a **generated** page — the API
reference module pages produced by `_generated_pages()` and the reference index
page produced by `_reference_index_page()`. So every generated page is skipped
by both the rewrite **and** the dangling-link validation that shares the loop.

The generated module template emits such links: `templates/module.md.j2:45`
renders `Re-exported from [`{{ m.target }}`](ref:{{ m.target_module }}).` for
every re-export alias. Those links are published to the GitHub wiki verbatim as
`ref:parrot.a2a.client`, which GitHub renders as a dead relative link.

The failure is silent twice over:

1. `BundleReport.dangling` stays empty because generated pages are never
   validated, so `report.ok()` returns `True` and `parrot sdd techwiki bundle`
   exits 0.
2. The existing guard test `test_every_rewritten_link_resolves_in_the_manifest`
   only inspects `[[Page]]` targets, so an *unrewritten* `[x](ref:…)` link is
   invisible to it.

Confirmed at `95b65f964a` during the FEAT-801 `/sdd-done` independent review:
a full bundle reported `dangling=[]` while
`API-Reference-Reference:-parrot.a2a.md` retained literal `ref:parrot.a2a.client`
links. Ledger: `issue:0891861cb3c1` (bug, major).

### Goals

- G1: Generated pages (module pages and the reference index) go through the
  same link rewriting as authored and ADR pages, so `ref:<module>` links in
  generated bodies become `[[API-Reference-<module>]]`.
- G2: Unresolvable links in generated pages are reported in
  `BundleReport.dangling`, identified by the page's `ref:`/`index:` id, so the
  bundle fails loudly instead of publishing a dead link.
- G3: Regression coverage that fails on the current `dev` behaviour — one test
  asserting generated bodies carry no literal `ref:` target, and one asserting
  an unresolvable generated link is reported dangling.

### Non-Goals (explicitly out of scope)

- The other open FEAT-801 review issues (`issue:99a0520cffbd`,
  `issue:822353a98341`, `issue:adb6da4375c7`, `issue:046f034dd3ef`). They are
  separate ledger groups and separate fix lanes.
- Changing `rewrite_links()` in `naming.py`, the `module.md.j2` template, the
  manifest schema, or the `ref:`/`index:` id grammar.
- Changing how authored or ADR pages resolve relative `.md` targets.

---

## 2. Architectural Design

### Overview

One behavioural change, confined to the rewrite loop of `assemble()`: stop
skipping `source is None` pages, and make the per-page `resolve()` closure
source-aware instead.

The closure currently serves exactly one page shape (authored, with a source
path) and does two things: build the lookup key, and record a dangling entry.
Both need a generated-page branch:

| | authored / ADR page | generated page (`source is None`) |
|---|---|---|
| `ref:`/`index:` target | key is the target verbatim | key is the target verbatim (unchanged) |
| relative `.md` target | normalized against the page's source directory | **no source directory exists** → unresolvable, reported dangling |
| `dangling[].source` | `_source_id(root, page.source)` | `_ref_id(page)` (`ref:<module>` / `index:<name>`) |

A relative `.md` target inside a generated page cannot be resolved — a
generated page has no location in the source tree to resolve against. Today
that case would raise `AttributeError` on `page.source.parent`; after this
change it is reported as dangling, which is the honest answer and keeps the
function total.

`rewrite_links()` already leaves an unresolved link untouched (returns the
original match when the resolver returns `None`), so a dangling generated link
is reported *and* left verbatim — same contract authored pages already have.

### Component Diagram

```
assemble()
   ├── collect_authored / collect_adrs ──→ pages (source = Path)
   ├── _generated_pages ─────────────────→ pages (source = None, module set)
   ├── _reference_index_page ────────────→ page  (source = None, module None)
   ├── manifest { ref:<module> | index:<name> | <source path> -> page name }
   └── rewrite loop  ← THIS CHANGE: now covers every page, not only source-bearing ones
          └── resolve(target, page) ──→ manifest lookup | report.dangling.append(...)
                 └── rewrite_links(page.body, resolve)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.sdd.techwiki.bundle.assemble` | modifies | the rewrite loop at `bundle.py:277-291` |
| `parrot.sdd.techwiki.bundle._ref_id` | uses | already returns `ref:<module>` / `index:<name>`; now also labels dangling rows |
| `parrot.sdd.techwiki.naming.rewrite_links` | uses unchanged | resolver contract (`str -> str | None`) is already satisfied |
| `parrot.sdd.techwiki.check` / CLI `techwiki bundle` | behaviour | a previously-silent bundle may now exit non-zero on a genuine dangling link |

### Data Models

No new models. `BundleReport.dangling` (`bundle.py:46`) keeps its
`list[dict[str, str]]` shape with the same `{"source": …, "target": …}` keys;
only the set of values `source` can take widens to include `ref:`/`index:` ids.

### New Public Interfaces

None. `assemble()` keeps its signature and return type.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: source-aware rewrite loop | yes | exact loop shape and `resolve()` branches fixed in §3 M1 below | — |
| M2: regression tests | yes | exact test names, fixture and assertions fixed in §4 | — |

### Module 1: Source-aware link rewriting in `assemble()`

- **Path**: `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py`
- **Responsibility**: rewrite and validate links on **every** assembled page,
  labelling dangling rows by source path or by `ref:`/`index:` id.
- **Depends on**: existing `_ref_id` (`bundle.py:295`), `_source_id`
  (`bundle.py:78`), `rewrite_links` (`naming.py:84`).
- **Interface Skeleton**: no signature changes. The loop at `bundle.py:277`
  becomes:

  ```python
  # packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py  (modifies bundle.py:277)
  for page in pages:

      def resolve(target: str, page: BundlePage = page) -> str | None:
          """Map a link target to a wiki page name, recording unresolved ones as dangling."""
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

  Note the `startswith` widens from `"ref:"` to `("ref:", "index:")`: `_ref_id`
  can mint an `index:<name>` key for the reference index page, and that key is
  already registered in `manifest` at `bundle.py:272-273`. Accepting it here
  costs nothing and keeps key construction symmetric with the manifest.

### Module 2: Regression coverage

- **Path**: `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py`
- **Responsibility**: two tests that fail on current `dev` and pass after M1.
- **Depends on**: the existing `api_repo` fixture
  (`test_techwiki_bundle.py:168`), which already copies
  `tests/sdd/fixtures/techwiki_pkg` — whose `samplepkg/__init__.py` re-exports
  `PublicModel` from `.core`, producing exactly the alias block that
  `module.md.j2:45` renders as a `ref:samplepkg.core` link.
- **Interface Skeleton**: plain module-level test functions, matching the
  file's existing style (see §4).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_generated_page_ref_links_are_rewritten` | M2 | The generated `samplepkg` page's re-export link becomes `[[API-Reference-samplepkg.core]]`; no literal `](ref:` survives in **any** generated page body; `report.ok()` is true. |
| `test_unresolvable_link_in_a_generated_page_is_dangling` | M2 | With an injected unresolvable `ref:` target in a generated body, `report.dangling` carries a row whose `source` is the page's `ref:<module>` id and `report.ok()` is false. |

Both tests are **appended at the end of**
`packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` (after
`test_authored_page_colliding_with_a_generated_name`, `:289`), not inserted
mid-file — see §7 R5: the unmerged branch
`fix-1f9d9ff0ec07-techwiki-markdown-links` rewrites lines 66-290 of that file,
and end-of-file placement keeps the two lanes out of each other's diff.

Neither test may assert on link **syntax**. `rewrite_links` emits `[[Page]]` on
`dev` today and `[text](percent-encoded-name)` once that branch merges, so the
assertions check that the resolved page **name** is present and that `](ref:`
is absent — true under both forms.

The first test drives the real griffe pipeline and the real template through the
`api_repo` fixture, so it skips cleanly without the `griffe` extra and fails
loudly under `TECHWIKI_REQUIRE_GRIFFE=1`.

The second test is deliberately griffe-free: it monkeypatches
`bundle._generated_pages` (called by name inside `assemble()`, `bundle.py:240`)
to return one hand-built `BundlePage(source=None, module=...)` carrying both an
unresolvable `ref:` target and a relative `.md` target. That is the only way to
reach AC-3's relative-path branch, since the real template never emits a
relative link from a generated page. **Do not** weaken either test to assert
only on authored pages.

### Integration Tests

None. `assemble()` is already exercised end-to-end by the existing
`write_bundle` tests in the same file.

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_techwiki_bundle.py
markers: none

### Test Data / Fixtures

Existing only — `api_repo` (`test_techwiki_bundle.py:168`) and
`tests/sdd/fixtures/techwiki_pkg/`. No new fixture files.

---

## 5. Acceptance Criteria

- [ ] AC-1: `assemble()` rewrites `ref:<module>` links in generated page bodies
      to `[[<page name>]]`; no generated page body written by `write_bundle`
      contains a literal `](ref:` target when every referenced module is in the
      manifest.
- [ ] AC-2: An unresolvable link in a generated page appears in
      `BundleReport.dangling` with `source` set to that page's `ref:<module>`
      (or `index:<name>`) id, and `report.ok()` is `False`.
- [ ] AC-3: A relative `.md` target inside a generated page is reported
      dangling and never raises `AttributeError`.
- [ ] AC-4: Both new tests fail on `dev` at `de16f89a65` and pass after the fix.
- [ ] AC-5: `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` is
      green, with no pre-existing test modified to accommodate the change.
- [ ] AC-6: `ruff check` clean on both changed files.
- [ ] AC-7: No change to `naming.py`, `module.md.j2`, the manifest schema, or
      `assemble()`'s signature.
- [ ] AC-8: No assertion in either new test depends on `[[Page]]` vs `[text](Page)`
      link syntax, and both are appended after the file's last existing function.

---

## 6. Codebase Contract

> Verified against `de16f89a65` (dev tip at spec time).

### Verified Imports

```python
from parrot.sdd.techwiki.bundle import assemble, write_bundle  # verified: bundle.py:211, bundle.py:353
from parrot.sdd.techwiki.config import load_techwiki_config    # verified: config.py
from parrot.sdd.techwiki.naming import rewrite_links           # verified: naming.py:84
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py
@dataclass
class BundlePage:                                      # line 23
    source: Path | None                                # line 26 — None marks a generated page
    section: str                                       # line 27
    title: str                                         # line 28
    name: str                                          # line 29
    body: str                                          # line 30
    module: str | None = None                          # line 31 — dotted module; None for authored/ADR/index

@dataclass
class BundleReport:                                    # line 35
    dangling: list[dict[str, str]] = field(...)        # line 46
    def ok(self) -> bool: ...                          # line 48

def _source_id(root: Path, source: Path) -> str: ...   # line 78
def _reference_index_page(cfg, generated) -> BundlePage: ...  # line 163
def _manifest_entries(pages: list[BundlePage]) -> list[dict[str, str]]: ...  # line 197
def assemble(cfg, root, *, release=None, commit=None, with_api=True) -> tuple[list[BundlePage], BundleReport]: ...  # line 211
def _ref_id(page: BundlePage) -> str: ...              # line 295

# packages/ai-parrot/src/parrot/sdd/techwiki/naming.py
def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str: ...  # line 84
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `resolve()` closure | `_ref_id(page)` | function call | `bundle.py:295` |
| `resolve()` closure | `_source_id(root, page.source)` | function call | `bundle.py:78` |
| rewrite loop | `rewrite_links(page.body, resolve)` | function call | `bundle.py:291` → `naming.py:84` |
| tests | `api_repo` fixture | pytest fixture | `test_techwiki_bundle.py:168` |

### Does NOT Exist (Anti-Hallucination)

- ~~`BundlePage.path`~~ — the attribute is `source`.
- ~~`BundleReport.unresolved`~~ — the list is `dangling`.
- ~~`BundlePage.is_generated()`~~ — no such helper; `source is None` is the marker.
- ~~`rewrite_links(text, resolver, base)`~~ — `rewrite_links` takes exactly two arguments.
- ~~`_ref_id(module)`~~ — it takes a `BundlePage`, not a module string.
- ~~`parrot.sdd.techwiki.apiref`~~ — the module is `parrot.sdd.techwiki.api`.

### Edit Sites (Blueprint Anchors)

> Verified against `de16f89a65`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py` | MODIFY | `        def resolve(target: str, page: BundlePage = page) -> str | None:` | `bundle.py:281` | 1 |
| `packages/ai-parrot/tests/sdd/test_techwiki_bundle.py` | MODIFY | `def test_every_rewritten_link_resolves_in_the_manifest(api_repo: Path, tmp_path: Path) -> None:` | `test_techwiki_bundle.py:233` | 1 |

Note: the loop head `    for page in pages:` occurs more than once in
`bundle.py` (`:269`, `:271`, `:277`). The blueprint must attach to the
`def resolve(...)` line above, which is unique, and edit outward from it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Keep the closure's default-argument binding (`page: BundlePage = page`) — it
  is what makes the late-binding loop variable safe, and removing it silently
  breaks every page but the last.
- Google-style docstring on the closure; 120-column lines; `ruff check --fix`.
- No `print`; this module logs through `logger` (`bundle.py:18`) and this change
  needs no new logging.

### Known Risks / Gotchas

- **R1 — the fix can turn a green bundle red.** Validating generated pages for
  the first time may surface genuine pre-existing dangling links in the real
  `parrot.*` tree (a re-export whose target module is outside the configured
  roots). That is the bug being fixed, not a regression: the link was already
  dead on the published wiki. If the repo's own
  `parrot sdd techwiki bundle` now exits non-zero, record the dangling rows in
  the Completion Note and open a ledger issue for them — do **not** suppress
  the validation to keep the exit code green, and do not widen this task to fix
  them.
- **R5 — peer branch in the same files.** `fix-1f9d9ff0ec07-techwiki-markdown-links`
  (brief `1f9d9ff0ec07`, based on `dev`, pushed, awaiting `/sdd-done`) changes
  `rewrite_links` to emit Markdown links and rewrites `test_techwiki_bundle.py`
  lines 66-290. It leaves `assemble()`'s rewrite loop untouched, so this
  feature's `bundle.py` edit does not conflict; and its strengthened guard still
  skips `ref:` targets as external URLs, so this bug survives it. Mitigations are
  in §4: append tests at end-of-file, never assert on link syntax. Base on
  `origin/dev` as usual — do not rebase onto that branch.
- **R2 — `_reference_index_page` bodies use `[[...]]` directly** (`bundle.py:187`),
  not `[x](ref:…)`, so the index page has nothing for the resolver to rewrite.
  Including it in the loop is harmless and keeps the rule uniform; do not
  special-case it out.
- **R3 — griffe gating.** `api_repo` skips without the `griffe` extra, so a
  local green run does not prove the new tests ran. Confirm with
  `TECHWIKI_REQUIRE_GRIFFE=1` or by asserting the tests are not reported as
  skipped.

### External Dependencies

None added.

---

## 8. Open Questions

None. The defect, its mechanism and its fix are fully determined by §2–§6.

---

## 10. Documentation

Policy: `none`. This is a behaviour fix inside an existing documented
subsystem; no authored wiki page gains or loses content. The `wiki/` page for
the techwiki bundler already describes link rewriting as applying to assembled
pages — this change makes the implementation match that description.
