# TASK-5233: Only link an API re-export when the target module has a page

**Feature**: FEAT-819 — Only link an API re-export when the target module has a page
**Spec**: `sdd/specs/fixgroup-c95c1c7e8e5b.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:3ecba9ea5ffc`

---

## Context

Implements spec §3 Module 1 and Module 2 in one unit (the fix and its regression
coverage are not separable: the tests cannot be written against the old behaviour).

`templates/module.md.j2:45` renders, for every re-export alias with a truthy
`target_module`:

```jinja
Re-exported from [`{{ m.target }}`](ref:{{ m.target_module }}).
```

`render_module` works **one module at a time** and has no knowledge of the final
page set, so it links every re-export target whether or not that module will get
a page. FEAT-818 made `assemble()` validate generated pages, which surfaced the
consequence: **300 dangling rows across 49 distinct target modules**, and the
`bundle` CI check on PR #1993 is red.

**Read spec §1's correction table before writing code.** The ledger issue as filed
blames "modules outside the configured roots" — that is **wrong**. Measured at
`baf4e90a2c`: 0 skipped modules, 3078 pages, and all 49 targets are already in
scope and already walked. They produce no page for four legitimate reasons:
packages whose only public members are submodules (19), modules with no public
members (14), compiled `.so` extensions (2), and dotted names with no source file
at all (14 — `parrot.tools.excel` is importable only via the `sys.meta_path`
redirect; `parrot.bots.orchestration` was removed in FEAT-143).

---

## Scope

- Add `_unlink_pageless_refs(pages)` to `api.py`: downgrade every `](ref:<module>)`
  alias link whose `<module>` is not a key of the rendered `pages` dict to plain
  code text.
- Call it in `_generate`, once, after the render loop and before the `return`.
- Add regression tests.

**NOT in scope**:
- Generating pages for packages or for modules with no public members.
- Fixing the 14 stale dotted names in the source — that is source-level link rot
  (spec §7 R3); open a separate ledger issue if it is worth chasing.
- `bundle.py`, `naming.py`, `module.md.j2`, or `techwiki.packages` in
  `sdd/config.json` (AC-8).
- The sibling FEAT-801 ledger issues.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` | MODIFY | `_unlink_pageless_refs` + one call in `_generate` |
| `packages/ai-parrot/tests/sdd/test_techwiki_api.py` | MODIFY | Regression tests (append at end of file) |
| `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py` | MODIFY | AC-9 only (scope amended — see Completion Note) |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `0ec5c3421f`.

### Verified Imports

```python
# ALREADY at the top of api.py — do NOT re-add:
import re                                   # verified: api.py:8
import logging                              # verified: api.py:7
from dataclasses import dataclass           # verified: api.py:9  ← NOTE: `replace` is NOT imported yet

# ALREADY at the top of test_techwiki_api.py — confirm before re-adding:
from parrot.sdd.techwiki.config import TechwikiConfig, TechwikiPackage
```

The only import this task adds is `replace` on the existing dataclasses line:
`from dataclasses import dataclass, replace`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/techwiki/api.py
@dataclass(frozen=True)                     # line 22 — FROZEN; never assign to page.body
class RenderedPage:                         # line 23
    module: str                             # line 26
    section: str                            # line 27
    title: str                              # line 28
    body: str                               # line 29

def render_module(mod, *, template, source_url, release, root=None,
                  section="API Reference") -> RenderedPage | None: ...
    # returns None when the module has no public members (api.py:456-461)

def generate(cfg: TechwikiConfig, root: Path, *, release: str | None = None
             ) -> tuple[list[RenderedPage], list[dict[str, str]]]: ...   # line 511
def _generate(cfg: TechwikiConfig, root: Path, release: str | None
              ) -> tuple[list[RenderedPage], list[dict[str, str]]]: ...  # line 532
    pages: dict[str, RenderedPage] = {}     # line 535 — THE LINKABLE SET
    # ... render loop ...
    return sorted(pages.values(), key=...), sorted(skipped, key=...)     # line 566
```

```jinja
{# templates/module.md.j2 #}
Re-exported from [`{{ m.target }}`](ref:{{ m.target_module }}).   {# line 45 — the link form #}
Re-exported from `{{ m.target }}`.                                {# line 47 — the downgrade target #}
```

Measured rendered forms (verbatim, from a real bundle at `baf4e90a2c`):
```
'Re-exported from [`parrot.bots.orchestration.AgentCrew`](ref:parrot.bots.orchestration).'
'Re-exported from `navigator_eventbus.evb.Event`.'
```

```python
# packages/ai-parrot/tests/sdd/test_techwiki_api.py
@pytest.fixture
def techwiki_repo(tmp_path: Path) -> tuple[Path, TechwikiConfig]: ...   # line 48
    # returns (root, cfg) for the samplepkg fixture — NOT a bare Path.
```

### Does NOT Exist

- ~~`page.body = ...`~~ — `RenderedPage` is `@dataclass(frozen=True)` (`api.py:22`).
  Assigning raises `FrozenInstanceError`. Use `dataclasses.replace`.
- ~~`from dataclasses import replace`~~ — **not yet imported**; line 9 imports only `dataclass`.
- ~~`RenderedPage.links`~~ / ~~`RenderedPage.refs`~~ — exactly four fields.
- ~~`render_module(..., known_modules=...)`~~ — no such parameter.
- ~~`TechwikiConfig.link_unknown_modules`~~ — no such setting.
- ~~`generate()` returning 3 values~~ — it returns `(pages, skipped)`; unchanged by this task.
- ~~`techwiki_repo` returning a bare `Path`~~ in `test_techwiki_api.py` — it returns
  `tuple[Path, TechwikiConfig]` (the `test_techwiki_bundle.py` fixture of the same name
  returns a `Path`; they are different fixtures in different files).
- ~~`bundle._unlink_pageless_refs`~~ — the helper belongs in `api.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/techwiki/api.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_techwiki_api.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/api.py#RenderedPage",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/api.py#generate",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/api.py#_generate",
    "sym:packages/ai-parrot/src/parrot/sdd/techwiki/api.py#render_module"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `RenderedPage` is **frozen**: rebuild with `replace(page, body=new_body)` and
  reassign the dict entry. Do not mutate.
- Anchor the regex on the backticked form the template emits so it cannot touch
  an image (`![x](...)`) or any other link: `` \[(`[^`]+`)\]\(ref:([^)\s]+)\) ``.
- The replacement is group 1 **verbatim** (it already carries its backticks), so
  the output is byte-identical to the template's `{% else %}` branch.
- 120 columns, Google-style docstring, `ruff check --fix`, `black`.

### Known Risks / Gotchas

- **R1 — do NOT "fix" this by widening roots.** See Context: all 49 targets are
  already in scope, 0 modules were skipped. AC-8 forbids touching `sdd/config.json`.
- **R2 — do NOT weaken `assemble()`.** Making the dangling check skip generated
  pages again is exactly the FEAT-818 bug this repo just fixed. The fix belongs at
  emission time in `api.py`. AC-4 guards it: the authored-page dangling test must
  stay green, unmodified.
- **R3 — the full-bundle test is slow** (~3372 pages, ~25s). Keep it opt-in behind
  an env guard; never let it into the default unit run.
- **R5 — compiled modules** (`parrot.utils.types`, `parrot.utils.parsers.toml`)
  can never produce a page from source. They must land in the plain-text branch,
  not be treated as an error.

### References in Codebase

- `packages/ai-parrot/src/parrot/sdd/techwiki/api.py:456-461` — the
  `render_module` → `None` filter that creates pageless modules.
- `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py` — `assemble()`'s
  rewrite/validation (FEAT-818); unchanged by this task.

---

## Implementation Blueprint

### Steps (in order)

1. Extend the dataclasses import to `from dataclasses import dataclass, replace` —
   *why*: `RenderedPage` is frozen, so the body is swapped via `replace`, and
   `replace` is not imported yet.
2. Add `_ALIAS_REF_LINK` and `_unlink_pageless_refs` near the other module-private
   helpers — *why*: the knowledge of which modules produced a page lives only in
   `_generate`'s `pages` dict, so the downgrade must happen there, not in the
   template or in `bundle.py`.
3. Call it in `_generate` immediately before the `return` — *why*: the dict must be
   complete first; calling it inside the loop would downgrade links to modules that
   are rendered later.
4. Append the tests — *why*: AC-5 requires they fail on `dev` first.
5. Confirm both unit tests FAIL before step 2's helper is wired, then pass.
6. Run the opt-in full-bundle check once by hand to confirm `dangling == []` (AC-3).

### `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    pages: dict\[str, RenderedPage\] = {}' packages/ai-parrot/src/parrot/sdd/techwiki/api.py)
# Part A — extend the existing import on api.py:9 (currently `from dataclasses import dataclass`):
from dataclasses import dataclass, replace

# Part B — new module-private helper. Place it immediately ABOVE `def generate(` (api.py:511).
_ALIAS_REF_LINK = re.compile(r"\[(`[^`]+`)\]\(ref:([^)\s]+)\)")


def _unlink_pageless_refs(pages: dict[str, RenderedPage]) -> None:
    """Downgrade ``ref:`` alias links whose target module produced no page to plain code text.

    ``render_module`` renders one module at a time and cannot know which modules end up with a
    page, so ``module.md.j2`` links every re-export target. A target that produced no page has no
    manifest entry, so ``assemble()`` cannot rewrite it and it would reach the published wiki as a
    literal ``ref:`` URL. The replacement is exactly the template's own ``{% else %}`` form, so no
    new output shape is introduced. ``RenderedPage`` is frozen, so entries are rebuilt in place.

    Args:
        pages: Rendered pages keyed by module name. Mutated in place.
    """
    for module, page in list(pages.items()):
        # FILL IN: substitute with a function replacement that keeps the match unchanged when
        # group(2) is in `pages`, and returns group(1) verbatim otherwise — bounded by AC-1 and
        # AC-2 (group 1 already carries its backticks, so the result matches module.md.j2:47).
        body = page.body
        if body != page.body:
            pages[module] = replace(page, body=body)

# Part C — the call site. In `_generate`, immediately BEFORE:
#   `    return sorted(pages.values(), key=lambda page: page.module), sorted(skipped, ...)`
    _unlink_pageless_refs(pages)
```

**Why this shape**: `_generate`'s `pages` dict (`api.py:535`) is keyed by module name, so its key
set *is* the set of modules that produced a page — the only place linkability is knowable. The
helper mutates in place so the call site stays one line and the `return` is untouched. The regex
is anchored on the backticked link text the template emits, so it cannot match an image or an
ordinary link. Do not change `generate()`'s or `_generate()`'s signature, and do not move this
logic into `bundle.py`.

### `packages/ai-parrot/tests/sdd/test_techwiki_api.py` (MODIFY)

```python
# APPEND AT END OF FILE (229 lines at 0ec5c3421f; last member is
# TestRenderingRules.test_init_is_merged_into_the_class). Append rather than insert so this task
# stays out of any concurrent diff in this file.


def _page(module: str, body: str) -> RenderedPage:
    """Build a minimal RenderedPage for the unlink tests."""
    return RenderedPage(module=module, section="API Reference", title=module, body=body)


def test_alias_link_to_a_module_without_a_page_is_plain_text() -> None:
    """issue:3ecba9ea5ffc — a re-export whose target produced no page is not linked."""
    pages = {"a.b": _page("a.b", "Re-exported from [`a.missing.Thing`](ref:a.missing).\n")}
    _unlink_pageless_refs(pages)
    # Byte-identical to module.md.j2:47, the template's own else-branch.
    assert pages["a.b"].body == "Re-exported from `a.missing.Thing`.\n"
    assert "](ref:" not in pages["a.b"].body


def test_alias_link_to_a_paged_module_is_still_linked() -> None:
    """The downgrade is not indiscriminate: a target that DID produce a page keeps its link."""
    body = "Re-exported from [`a.target.Thing`](ref:a.target).\n"
    pages = {"a.b": _page("a.b", body), "a.target": _page("a.target", "# a.target\n")}
    _unlink_pageless_refs(pages)
    assert pages["a.b"].body == body
```

**Why**: driving `_unlink_pageless_refs` directly keeps the two assertions exact and needs no
griffe and no fixture change — the shared `techwiki_pkg` fixture also feeds the golden test, so
adding a module to it risks a golden mismatch outside this task's scope. The paired
"still linked" test is what proves the regex is not over-broad; without it a `return group(1)`
that ignores `pages` would pass the first test. Import `RenderedPage` and `_unlink_pageless_refs`
from `parrot.sdd.techwiki.api` at the top of the file alongside the existing imports.

### FILL IN checklist

- [ ] `_unlink_pageless_refs` — the `_ALIAS_REF_LINK.sub(...)` function replacement: keep the match
      when `group(2) in pages`, else return `group(1)`; bounded by AC-1 and AC-2.
- [ ] The opt-in full-bundle assertion for AC-3 — env-guarded (e.g. `TECHWIKI_FULL_BUNDLE=1`),
      skipped by default; bounded by R3 (must not run in the default unit suite).

---

## Acceptance Criteria

- [ ] AC-1: An alias whose `target_module` produced no page renders as
      ``Re-exported from `<target>`.`` — byte-identical to `module.md.j2:47` — with no `](ref:`.
- [ ] AC-2: An alias whose `target_module` produced a page keeps its `ref:` link and is still
      rewritten by `assemble()` to the wiki page.
- [ ] AC-3: A full bundle of this repository reports `report.dangling == []` and `report.ok()`
      is `True` (measured before the fix: 300 rows / 49 targets).
- [ ] AC-4: `assemble()`'s validation is NOT weakened — an unresolvable `ref:` in an *authored*
      page is still dangling (`test_ref_links_resolve_to_generated_pages` green, unmodified).
- [ ] AC-5: Both new unit tests fail on `dev` at `0ec5c3421f` and pass after the fix.
- [ ] AC-6: `pytest test_techwiki_api.py test_techwiki_bundle.py` green, no pre-existing test
      modified to accommodate the change.
- [ ] AC-7: `ruff check` and `black --check` clean on both changed files.
- [ ] AC-8 *(amended)*: No change to `module.md.j2`, `naming.py`, or `techwiki.packages`.
      One narrowly-scoped `bundle.py` change is in scope, for AC-9 only.
- [ ] AC-9 *(added)*: A generated page's link to an already-final page name ending in `.md`
      is left alone, not reported dangling.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_api.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_techwiki_bundle.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_techwiki_api.py::test_alias_link_to_a_module_without_a_page_is_plain_text -q`

---

## Test Specification

Both unit tests are appended at the end of
`packages/ai-parrot/tests/sdd/test_techwiki_api.py`; scaffolds are in the Implementation
Blueprint. No new fixture files, and the shared `techwiki_pkg` fixture is deliberately NOT
modified (it also feeds `fixtures/techwiki_golden/`).

AC-3 is proven by an opt-in, env-guarded test that bundles this repository and asserts
`report.dangling == []`. It must be skipped in the default run (R3) and is additionally run once
by hand during implementation, with the result recorded in the Completion Note.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug fixgroup-c95c1c7e8e5b --feature-id FEAT-819`).
2. Run validation with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src` — the shared
   venv is editable-installed against the main checkout.
3. Verify the Codebase Contract before writing code; `RenderedPage` being frozen is the single
   most likely thing to trip you.
4. Stage only the two files this task lists. Never `git add .` / `-A`.
5. Close with `parrot sdd task close TASK-5233 fixgroup-c95c1c7e8e5b verified`.

---

## Completion Note

**Closed**: 2026-11-05 · verification=verified · commits `ff8756f8df`, `916b500f2c`

### Decisive evidence — the real CI gate

The `bundle` job of `.github/workflows/techwiki.yml` runs
`parrot sdd techwiki bundle --json --strict --dry-run`. That exact command on this branch:

```json
{"skipped_modules": [], "adrs": 9, "authored": 285, "collisions": [], "commit": "916b500f2c",
 "dangling": [], "generated": 3077, "release": "v2.1.0"}
```
exit 0.  Before: **300 dangling rows / 49 distinct targets**, and the job red on PR #1993.

### What changed

**Part 1 — `api.py` (`ff8756f8df`), the issue as filed.** `_unlink_pageless_refs(pages)` runs once
in `_generate` after the render loop, where the completed `pages` dict *is* the linkable set. A
`](ref:<module>)` alias link whose target is not a key is downgraded to plain code text —
byte-identical to `module.md.j2`'s own `{% else %}` branch, so no new output shape exists.
`RenderedPage` is `frozen=True`, so entries are rebuilt via `dataclasses.replace`.

**Part 2 — `bundle.py` (`916b500f2c`), AC-9, a scope amendment.** See below.

### The ledger issue's stated cause was wrong

`issue:3ecba9ea5ffc` blamed "modules **outside the configured roots**". Measured: **0 skipped
modules**, 3078 pages, and all 49 targets already in scope and already walked. Widening
`techwiki.packages[].roots` would have fixed nothing. The real cause is that `render_module`
returns `None` for a module with no public members, and the renderer — working one module at a
time — links every re-export target regardless. Breakdown: 19 packages whose only public members
are submodules (their children *do* get pages), 14 modules with no public members, 2 compiled
`.so`, and 14 dotted names with no source file (`parrot.tools.excel` resolves only through the
`sys.meta_path` redirect; `parrot.bots.orchestration` was removed in FEAT-143). The spec's §1
correction table carries the full evidence.

### Scope amendment (AC-8 → AC-9) — stated, not silent

AC-8 originally forbade touching `bundle.py`. After Part 1, **one** dangling row remained:
`{'source': 'index:API-Reference', 'target': 'API-Reference-parrot.loaders.splitters.md'}`.

`parrot/loaders/splitters/md.py` is a module literally named `md`, so its page name ends in
`.md`. `naming.rewrite_links` (`naming.py:133`) resolves any target ending `.md` as a relative
path, and `_reference_index_page` (`bundle.py:188`) emits already-final page links. Before
FEAT-818 the index page was never validated, so this never surfaced — it is a consequence of
FEAT-818, not of this feature's own change.

Leaving it would have kept the bundle gate red, which is the entire purpose of this work, so the
fix was folded in rather than deferred: `resolve()` returns `None` **without** reporting dangling
when `unquote(target)` is a known page name and the page has no source. `urllib.parse.unquote` is
imported because the index percent-encodes hrefs. Nothing else in `bundle.py` changed and the
dangling check is **not** weakened for any other case — AC-4 holds (see below).

### Test evidence

- **AC-5**: with the `_unlink_pageless_refs(pages)` call site removed, `2 failed, 3 passed`
  (the end-to-end wiring test and the full-bundle test). Restored: all pass.
- **Mid-task correction**: the first two unit tests drove `_unlink_pageless_refs` directly, so
  they passed with the helper present but *unwired* — they did not prove the wiring. Added
  `test_generate_links_only_re_exports_whose_target_has_a_page`, which goes through `generate()`
  on a tmp package where `pkgx.real` has a page and `pkgx.nosuch` does not. That is the test that
  actually fails without the call site.
- **Full techwiki suite**: `85 passed`, 0 failed (`test_techwiki_api.py`, `test_techwiki_bundle.py`,
  `test_techwiki_naming.py`, `test_techwiki_check.py`), with `TECHWIKI_FULL_BUNDLE=1` so the
  repo-level bundle assertion ran.
- **AC-4** (validation not weakened): `test_ref_links_resolve_to_generated_pages` and the FEAT-818
  tests are green and unmodified — an unresolvable `ref:` in an *authored* page is still dangling.
- **AC-7**: `ruff check` → "All checks passed!"; `black` clean on all three changed files.

### Tests added

| Test | Proves |
|---|---|
| `test_alias_link_to_a_module_without_a_page_is_plain_text` | AC-1, helper level |
| `test_alias_link_to_a_paged_module_is_still_linked` | AC-2 — the downgrade is not indiscriminate |
| `test_unlink_leaves_images_and_ordinary_links_alone` | the regex is anchored, not greedy |
| `test_generate_links_only_re_exports_whose_target_has_a_page` | **the wiring**, end-to-end |
| `test_generated_page_link_to_a_page_named_like_a_markdown_file_is_not_dangling` | AC-9 |
| `test_full_repository_bundle_has_no_dangling_links` | AC-3 (opt-in: `TECHWIKI_FULL_BUNDLE=1`, ~20s) |

### Known follow-up, deliberately NOT done here

The 14 dotted names with no source file are real link rot (`parrot.tools.excel` should be
`parrot_tools.excel`; `parrot.bots.orchestration` is gone). This feature renders them as plain
text, which is correct for the wiki, but that also removes the only signal that they are stale.
Spec §7 R3 — open a separate ledger issue if it is worth chasing.

### Coordination

Session `ai-parrot-e1` is fixing `issue:6b80e9a6474b` (`parrot.auth` gets no page) in the same
file. Settled by cross-session message: FEAT-819 lands first, they rebase onto post-merge `dev`.
Their change targets the `is_public`/`render_module` member filter (~`api.py` L168-192, L430-484),
disjoint from this task's region. Their fix is purely additive to this one — once those packages
get pages, `_unlink_pageless_refs` simply leaves those refs linked.
