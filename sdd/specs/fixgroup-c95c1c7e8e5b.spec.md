---
type: feature
base_branch: dev
projects: []
tags: [techwiki, sdd-tooling, bugfix]
docs:
  policy: none
---

# Feature Specification: Only link an API re-export when the target module has a page

**Feature ID**: FEAT-819
**Date**: 2026-11-05
**Author**: Jesus (via /sdd-fix issue:3ecba9ea5ffc)
**Status**: approved
**Target version**: 2.1.1

---

## 1. Motivation & Business Requirements

### Problem Statement

`templates/module.md.j2:45` renders, for every re-export alias whose
`target_module` is truthy:

```jinja
Re-exported from [`{{ m.target }}`](ref:{{ m.target_module }}).
```

The renderer works **one module at a time** and has no knowledge of the final
page set, so it emits a `ref:<module>` link whether or not `<module>` will ever
get a page. `assemble()` then cannot resolve those keys in the manifest.

FEAT-818 (`issue:0891861cb3c1`) made `assemble()` validate generated pages for
the first time, which surfaced the consequence: on this repository the full
bundle reports **300 dangling rows across 49 distinct target modules**, all from
generated pages, and the `bundle` CI check now fails.

### Correction to `issue:3ecba9ea5ffc` as filed

That issue states the cause as "re-export links point at modules **outside the
configured roots**". **That hypothesis is wrong** and must not be carried into
the implementation. `sdd/config.json` already configures `roots: ["parrot"]`
for all 24 `parrot.*` distributions (`ai-parrot-server`, `ai-parrot-integrations`
and the rest), plus `parrot_tools`, `parrot_loaders`, `parrot_pipelines`,
`navrules` and `parrot_formdesigner`. Measured at `baf4e90a2c`: **0 skipped
modules**, 3078 generated pages, and all 49 dangling targets simply **never
produced a page**. Classified on disk:

| Cause | Count | Examples | Why no page |
|---|---:|---|---|
| Package `__init__.py` | 19 | `parrot`, `parrot.mcp`, `parrot.handlers`, `parrot.integrations`, `parrot.manager` | `render_module` returns `None` for a module whose only public members are submodules (`api.py:456-461`). Their children *are* generated (2266, 47, 180, 202, 5 pages respectively). |
| Plain module, no public members | 14 | `parrot_tools.abstract`, `parrot_tools.toolkit`, `parrot.knowledge.wiki.tools`, `parrot.voice.session` | Same `render_module` → `None` path. |
| Compiled extension | 2 | `parrot.utils.types`, `parrot.utils.parsers.toml` | `.so` only — no `.py` for griffe to read statically. |
| No such module on disk | 14 | `parrot.tools.excel`, `parrot.bots.orchestration`, `parrot_tools.nextstop.base` | The alias target resolves to a dotted name with no source file. `parrot.tools.excel` is importable only through the `sys.meta_path` redirect to `parrot_tools.excel`; `parrot.bots.orchestration` was removed in FEAT-143. |

Every one of these is a module that *correctly* has no page. None of them is a
roots misconfiguration, so widening `techwiki.packages[].roots` would fix
nothing — the modules are already in scope and already walked.

### Goals

- G1: A generated page links a re-export target **only** when that target module
  actually produced a page; otherwise it renders the target as plain code text.
- G2: `report.dangling` returns to `[]` for a clean tree, so the `bundle` gate
  passes again **without** weakening the FEAT-818 validation — a genuinely
  unresolvable link in an *authored* page must still be reported.
- G3: Regression coverage that fails on `dev` today.

### Non-Goals (explicitly out of scope)

- Generating pages for packages or for modules with no public members. Whether
  `parrot.mcp` *should* have an index page is a product question, not this fix.
- Fixing the 14 stale dotted names in the source (`parrot.tools.excel` →
  `parrot_tools.excel`, the removed `parrot.bots.orchestration`). Those are
  source-level link rot; this feature only stops the bundler from emitting a
  broken wiki link for them.
- Supporting compiled modules in griffe.
- The sibling FEAT-801 ledger issues (`issue:b9829d5f3a2b`,
  `issue:5af0e518b2e8`, `issue:99a0520cffbd`, `issue:822353a98341`,
  `issue:adb6da4375c7`, `issue:046f034dd3ef`) — separate groups, separate lanes.
- `assemble()`'s rewrite loop (FEAT-818) and `naming.rewrite_links`.

---

## 2. Architectural Design

### Overview

Linkability is a **global** property — "did this module produce a page?" — and
is only known once every module has been rendered. `render_module` cannot know
it, and `assemble()` learns it too late (it would have to choose between
reporting a false dangling or silently dropping a real one).

`_generate()` is the one place that holds the answer: it builds
`pages: dict[str, RenderedPage]` keyed by module name (`api.py:535`). After that
dict is complete, its key set **is** the linkable set. So add a post-pass there:
walk each rendered body and downgrade every `](ref:<module>)` alias link whose
`<module>` is not a key of `pages`.

The downgraded form is not invented — it is byte-identical to the template's
existing `{% else %}` branch (`module.md.j2:47`), already used whenever
`target_module` is falsy:

```
Re-exported from [`parrot.bots.orchestration.AgentCrew`](ref:parrot.bots.orchestration).
                               ↓  (target has no page)
Re-exported from `parrot.bots.orchestration.AgentCrew`.
```

So the change adds no new output shape, needs no template edit, and leaves
`assemble()`'s dangling validation fully intact for authored pages and for any
generated link that *does* name a real page.

### Component Diagram

```
_generate(cfg, root, release)                      api.py:532
   ├── load_packages ──→ module tree
   ├── for each module: render_module ──→ RenderedPage | None
   │                        └── module.md.j2:45 emits [`x`](ref:<target_module>)   ← unconditional today
   ├── pages: dict[module -> RenderedPage]         api.py:535   ← the linkable set
   └── NEW: _unlink_pageless_refs(pages) ──→ downgrade ](ref:M) where M not in pages
                                                   ↓
assemble()  (FEAT-818)  rewrites + validates every page, generated ones included
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `api._generate` | modifies | one call added after the render loop, before the `return` |
| `api.RenderedPage` | uses | frozen-or-not dataclass with a `body: str` field (`api.py:23-29`) |
| `templates/module.md.j2` | unchanged | the downgrade reproduces its own `{% else %}` output |
| `bundle.assemble` | unchanged | still validates; simply has nothing left to report |

### Data Models

None added. `RenderedPage` keeps its four fields.

### New Public Interfaces

None. One module-private helper, `_unlink_pageless_refs`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `_unlink_pageless_refs` + wiring | yes | helper name, signature, regex and call site fixed below | — |
| M2: regression tests | yes | names, fixture and assertions fixed in §4 | — |

### Module 1: Downgrade pageless alias links in `_generate`

- **Path**: `packages/ai-parrot/src/parrot/sdd/techwiki/api.py`
- **Responsibility**: after the render loop, rewrite every rendered body so an
  alias link whose target module produced no page becomes plain code text.
- **Depends on**: `RenderedPage` (`api.py:23`), `pages` (`api.py:535`).
- **Interface Skeleton**:

  ```python
  # packages/ai-parrot/src/parrot/sdd/techwiki/api.py  (new helper + one call in _generate)
  _ALIAS_REF_LINK = re.compile(r"\[(`[^`]+`)\]\(ref:([^)\s]+)\)")

  def _unlink_pageless_refs(pages: dict[str, RenderedPage]) -> None:
      """Downgrade ``ref:`` alias links whose target module produced no page to plain code text.

      The renderer emits one page at a time and cannot know which modules end up with a page, so
      ``module.md.j2`` links every re-export target. A target with no page has no manifest entry and
      would reach the published wiki as a literal ``ref:`` URL. The replacement is exactly the
      template's own ``{% else %}`` form, so no new output shape is introduced.

      Args:
          pages: Rendered pages keyed by module name; mutated in place.
      """
  ```

- The call site is one line in `_generate`, immediately before its `return`.

### Module 2: Regression coverage

- **Path**: `packages/ai-parrot/tests/sdd/test_techwiki_api.py`
- **Responsibility**: prove a pageless target is not linked, a paged target still
  is, and the full bundle has no dangling rows.
- **Depends on**: the `api_repo`-style fixtures already in the techwiki tests.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_alias_link_to_a_module_without_a_page_is_plain_text` | M2 | A re-export whose target module produces no page renders ``Re-exported from `x.y.Z`.`` with no `](ref:` and no `[[`. |
| `test_alias_link_to_a_paged_module_is_still_linked` | M2 | A re-export whose target module *does* produce a page keeps its `ref:` link, so the downgrade is not indiscriminate. |

Place both at the **end** of `test_techwiki_api.py`.

### Integration Tests

| Test | Description |
|---|---|
| `test_bundle_of_the_real_repository_has_no_dangling_links` | Guarded, opt-in: asserts `report.dangling == []` for this repository's own config. Marked so it does not run in the default unit suite (a full 3372-page bundle takes ~25s). |

The repository-level assertion is the one that actually proves G2, but it must
not be a hidden cost in every run. Gate it behind an explicit marker/env opt-in
consistent with the file's existing conventions; the implementing task picks the
mechanism and records it.

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_techwiki_api.py
- packages/ai-parrot/tests/sdd/test_techwiki_bundle.py
markers: none

### Test Data / Fixtures

The existing `techwiki_pkg` fixture already contains a re-export
(`samplepkg/__init__.py` → `PublicModel` from `.core`) whose target **does**
get a page — that covers the "still linked" case directly. The "no page" case
needs a target module that renders to `None`; add it to the fixture package as a
module with no public members, or synthesize the pages dict directly in the
unit test. The implementing task picks one and records which.

---

## 5. Acceptance Criteria

- [ ] AC-1: An alias whose `target_module` produced no page renders as
      ``Re-exported from `<target>`.`` — byte-identical to the template's
      `{% else %}` branch — with no `](ref:` remaining.
- [ ] AC-2: An alias whose `target_module` produced a page keeps its `ref:` link
      and is still rewritten by `assemble()` to the wiki page.
- [ ] AC-3: A full bundle of this repository reports `report.dangling == []`
      and `report.ok()` is `True` (measured before: 300 rows / 49 targets).
- [ ] AC-4: `assemble()`'s validation is **not** weakened — an unresolvable
      `ref:` in an *authored* page is still reported dangling
      (`test_ref_links_resolve_to_generated_pages` stays green unmodified).
- [ ] AC-5: Both new unit tests fail on `dev` at `baf4e90a2c` and pass after M1.
- [ ] AC-6: `pytest test_techwiki_api.py test_techwiki_bundle.py` green, no
      pre-existing test modified to accommodate the change.
- [ ] AC-7: `ruff check` and `black --check` clean on changed files.
- [ ] AC-8: No change to `module.md.j2`, `bundle.py`, `naming.py`, or
      `techwiki.packages` in `sdd/config.json`.

---

## 6. Codebase Contract

> Verified against `baf4e90a2c` (dev tip at spec time, FEAT-818 merged).

### Verified Imports

```python
# already at the top of api.py — confirm before re-adding
import logging                                          # verified: api.py
from pathlib import Path                                # verified: api.py
from parrot.sdd.techwiki.config import TechwikiConfig   # verified: api.py

# tests
from parrot.sdd.techwiki.api import generate            # verified: api.py:511
from parrot.sdd.techwiki.bundle import assemble         # verified: bundle.py:211
from parrot.sdd.techwiki.config import load_techwiki_config
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/sdd/techwiki/api.py
@dataclass
class RenderedPage:                 # line 23
    module: str                     # line 26
    section: str                    # line 27
    title: str                      # line 28
    body: str                       # line 29

class GriffeUnavailable(RuntimeError): ...              # line 32
def is_public(obj: "griffe.Object") -> bool: ...        # line 168
def render_module(mod, *, template, source_url, release, root=None,
                  section="API Reference") -> RenderedPage | None: ...   # returns None when no public members
def generate(cfg: TechwikiConfig, root: Path, *, release: str | None = None
             ) -> tuple[list[RenderedPage], list[dict[str, str]]]: ...   # line 511
def _generate(cfg: TechwikiConfig, root: Path, release: str | None
              ) -> tuple[list[RenderedPage], list[dict[str, str]]]: ...  # line 532
    pages: dict[str, RenderedPage] = {}                 # line 535 — the linkable set
```

```jinja
{# packages/ai-parrot/src/parrot/sdd/techwiki/templates/module.md.j2 #}
{% if m.target_module %}
Re-exported from [`{{ m.target }}`](ref:{{ m.target_module }}).    {# line 45 #}
{% else %}
Re-exported from `{{ m.target }}`.                                 {# line 47 — the downgrade target #}
{% endif %}
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_unlink_pageless_refs` | `pages` dict | in-place mutation | `api.py:535` |
| call site | `_generate`'s `return` | one statement before it | `api.py:566` |

### Does NOT Exist (Anti-Hallucination)

- ~~`RenderedPage.links`~~ / ~~`RenderedPage.refs`~~ — the dataclass has exactly
  four fields: `module`, `section`, `title`, `body`.
- ~~`render_module(..., known_modules=...)`~~ — no such parameter; the renderer
  is single-module by design and must stay so.
- ~~`TechwikiConfig.link_unknown_modules`~~ — no such setting.
- ~~`generate()` returning three values~~ — it returns `(pages, skipped)`;
  this feature does **not** change that signature.
- ~~`parrot.sdd.techwiki.apiref`~~ — the module is `parrot.sdd.techwiki.api`.
- ~~`bundle._unlink_...`~~ — the helper belongs in `api.py`, not `bundle.py`.

### Edit Sites (Blueprint Anchors)

> Verified against `baf4e90a2c`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/api.py` | MODIFY | `    pages: dict[str, RenderedPage] = {}` | `api.py:535` | 1 |
| `packages/ai-parrot/tests/sdd/test_techwiki_api.py` | MODIFY | *(append at end of file)* | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `RenderedPage` is a `@dataclass`; if it is frozen, rebuild entries with
  `dataclasses.replace(page, body=...)` rather than assigning to `body`.
  **Check before writing** — do not assume either way.
- The regex must not touch an image (`![x](...)`) or a non-alias link. Anchor it
  on the backticked-text form the template emits: `` \[(`[^`]+`)\]\(ref:([^)\s]+)\) ``.
- Google-style docstrings, 120 columns, `ruff check --fix`, `black`.

### Known Risks / Gotchas

- **R1 — do not "fix" this by widening roots.** The §1 correction table is the
  evidence: all 49 targets are already in scope and already walked; 0 modules
  were skipped. Widening `techwiki.packages[].roots` changes nothing and is
  explicitly out of scope (AC-8).
- **R2 — do not weaken `assemble()`.** It would be trivial to make the dangling
  check ignore generated pages again; that is precisely the FEAT-818 bug. The
  fix belongs at emission time, in `api.py`. AC-4 guards this.
- **R3 — the 14 absent modules are real link rot** (`parrot.tools.excel`,
  `parrot.bots.orchestration`, `parrot_tools.nextstop.base`, …). This feature
  renders them as plain text, which is correct for the wiki, but it also removes
  the only signal that they are stale. If a follow-up is wanted, open a separate
  ledger issue — do not widen this feature (§1 Non-Goals).
- **R4 — the repo-level test is slow.** A full bundle is ~3372 pages / ~25s.
  Keep it opt-in; never let it into the default unit run.
- **R5 — `parrot.utils.types` and `parrot.utils.parsers.toml` are compiled.**
  They can never produce a page from source, so they must land in the
  plain-text branch, not be treated as an error.

### External Dependencies

None added.

---

## 8. Open Questions

None. The diagnosis in §1 is measured, and the fix location follows from it.

---

## 10. Documentation

Policy: `none`. Behaviour fix inside an existing documented subsystem.
