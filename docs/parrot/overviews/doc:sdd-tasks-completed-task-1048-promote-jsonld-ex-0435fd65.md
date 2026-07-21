---
type: Wiki Overview
title: 'TASK-1048: Promote `jsonld_extractors` Module to `ai-parrot` Core'
id: doc:sdd-tasks-completed-task-1048-promote-jsonld-extractors-to-core-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: existing `EXTRACTOR_REGISTRY` and `JsonLdItem` from
relates_to:
- concept: mod:parrot.utils
  rel: mentions
- concept: mod:parrot.utils.jsonld_extractors
  rel: mentions
- concept: mod:parrot.utils.parsers
  rel: mentions
- concept: mod:parrot_loaders
  rel: mentions
- concept: mod:parrot_loaders.jsonld_extractors
  rel: mentions
- concept: mod:parrot_tools.scraping
  rel: mentions
---

# TASK-1048: Promote `jsonld_extractors` Module to `ai-parrot` Core

**Feature**: FEAT-154 — WebScrapingToolkit `extract_jsonld` Browser Action
**Spec**: `sdd/specs/webscrapingtoolkit-jsonld.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`ai-parrot-tools` does not depend on `ai-parrot-loaders`, so the new
`extract_jsonld` BrowserAction (TASK-1049 / TASK-1050) cannot import the
existing `EXTRACTOR_REGISTRY` and `JsonLdItem` from
`parrot_loaders.jsonld_extractors` directly. To enable cross-package reuse
without duplication or a new inter-package dependency, the spec mandates
**promoting the module into the core `ai-parrot` package** at
`parrot.utils.jsonld_extractors`. The original loader-side path is preserved
via a thin re-export shim so external importers and the existing
`WebScrapingLoader` keep working.

This task implements Modules 1 and 2 from the spec (§3 — *Shared module
promotion* and *`WebScrapingLoader` import update*) and is the foundation
for both subsequent tasks.

Reference: spec §2 *Architectural Design — Overview (1)* and §3 *Module 1*,
*Module 2*.

---

## Scope

- **Move** `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`
  to `packages/ai-parrot/src/parrot/utils/jsonld_extractors.py` **verbatim**
  (no API changes, no logic changes — pure file relocation).
- **Replace** the original `parrot_loaders/jsonld_extractors.py` with a
  short backward-compat shim (≤ 10 lines) that re-exports every public
  symbol from the new core location via `__all__`.
- **Update** `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py`
  line 52 to import `EXTRACTOR_REGISTRY` and `JsonLdItem` from
  `parrot.utils.jsonld_extractors` instead of `parrot_loaders.jsonld_extractors`.
- **Update** any other internal importers of `parrot_loaders.jsonld_extractors`
  to use the new core path. (Currently `webscraping.py` lines 52–55 and
  `tests/test_webscraping_loader.py` lines 913 and 935 — verify with grep
  before editing; leave the test imports as-is if you choose since the shim
  re-export keeps them working — but new code should use the core path.)
- **Add** two unit tests proving both import paths resolve and refer to the
  same registry/dataclass objects.
- **Verify** the existing loader test suites still pass unmodified.

**NOT in scope**:
- Adding new schema.org `@type` extractors (covered by future work, not this
  feature).
- Modifying any extractor function bodies (`faq_extractor`,
  `product_extractor`, etc.) — this is a pure file move.
- Touching `parrot_tools.scraping.*` — those changes belong to TASK-1049
  and TASK-1050.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/utils/jsonld_extractors.py` | CREATE | New canonical home — move full file content here verbatim. |
| `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py` | MODIFY (rewrite) | Replace contents with re-export shim (≤ 10 lines). |
| `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py` | MODIFY | Update import block at lines 52–55 to use the core path. |
| `packages/ai-parrot/tests/test_jsonld_extractors_promotion.py` | CREATE | Two unit tests verifying both import paths resolve to the same objects. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.

### Verified Imports

```python
# parrot_loaders/webscraping.py current import block (lines 52-55) — to update:
from parrot_loaders.jsonld_extractors import (
    EXTRACTOR_REGISTRY,
    JsonLdItem,
)

# REPLACE WITH:
from parrot.utils.jsonld_extractors import (
    EXTRACTOR_REGISTRY,
    JsonLdItem,
)

# Public symbols exported by the module (from parrot_loaders/jsonld_extractors.py):
JsonLdItem                 # @dataclass at line 32
strip_html_text            # function at line 57
faq_extractor              # line 99
product_extractor          # line 149
event_extractor            # line 214
person_extractor           # line 280
place_extractor            # line 331
recipe_extractor           # line 406
article_extractor          # line 486
organization_extractor     # line 557
howto_extractor            # line 616
breadcrumb_extractor       # line 671
question_extractor         # line 723
EXTRACTOR_REGISTRY         # line 783
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py:32
@dataclass
class JsonLdItem:
    content_kind: str
    source_type: str
    page_content: str
    row_data: Dict[str, Any] = field(default_factory=dict)
    selector_name: Optional[str] = None


# packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py:783
EXTRACTOR_REGISTRY: Dict[str, Callable[[Dict[str, Any]], List[JsonLdItem]]] = {
    "FAQPage": faq_extractor,
    "Question": question_extractor,
    "Product": product_extractor,
    "IndividualProduct": product_extractor,
    "Event": event_extractor,
    "Person": person_extractor,
    "Place": place_extractor,
    "LocalBusiness": place_extractor,
    "Restaurant": place_extractor,
    "Recipe": recipe_extractor,
    "Article": article_extractor,
    "NewsArticle": article_extractor,
    "BlogPosting": article_extractor,
    "Organization": organization_extractor,
    "HowTo": howto_extractor,
    "BreadcrumbList": breadcrumb_extractor,
}


# packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:52-55  (CURRENT — UPDATE)
from parrot_loaders.jsonld_extractors import (
    EXTRACTOR_REGISTRY,
    JsonLdItem,
)


# packages/ai-parrot/src/parrot/utils/__init__.py — exists; the new module
# at packages/ai-parrot/src/parrot/utils/jsonld_extractors.py becomes
# importable as `parrot.utils.jsonld_extractors` automatically (utils is a
# regular package, no metapath finder).
```

### Does NOT Exist

- ~~`parrot.utils.jsonld`~~ — module name is `jsonld_extractors`, not `jsonld`.
- ~~`parrot.utils.parsers.jsonld_extractors`~~ — `parrot/utils/parsers/`
  hosts only the Cython TOML parser; JSON-LD lives directly under
  `parrot/utils/` to preserve module-name parity with the loader-side
  original.
- ~~`parrot_loaders.JsonLdItem` (top-level re-export)~~ — `parrot_loaders/__init__.py`
  does NOT re-export `JsonLdItem` at the package root. Existing importers
  reach it through the `jsonld_extractors` submodule, which the shim must
  preserve.
- ~~`EXTRACTOR_REGISTRY.register(...)`~~ — registry is a plain `dict`.
  No registration method.

---

## Implementation Notes

### Recommended sequence

1. Read the current file in full:
   `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`
   (≈ 800 lines).
2. `git mv` (or copy-then-write) the file to its new location:
   `packages/ai-parrot/src/parrot/utils/jsonld_extractors.py`. Make sure
   `git mv` is used so blame history is preserved.
3. Author the shim at the original path. It must re-export the entire
   public surface so `from parrot_loaders.jsonld_extractors import …`
   keeps working for any external user.
4. Update the import in `parrot_loaders/webscraping.py` (lines 52–55) to
   point at the core path.
5. Run the loader test suites — they must pass unmodified:
   `pytest packages/ai-parrot-loaders/tests/test_webscraping_loader.py -v`
   `pytest packages/ai-parrot-loaders/tests/test_jsonld_extractors.py -v`
6. Add the two new promotion tests in
   `packages/ai-parrot/tests/test_jsonld_extractors_promotion.py`.

### Backward-compat shim pattern

```python
# packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py
"""Backward-compat re-export. Canonical home is parrot.utils.jsonld_extractors."""
from parrot.utils.jsonld_extractors import (  # noqa: F401
    EXTRACTOR_REGISTRY,
    JsonLdItem,
    strip_html_text,
    faq_extractor,
    product_extractor,
    event_extractor,
    person_extractor,
    place_extractor,
    recipe_extractor,
    article_extractor,
    organization_extractor,
    howto_extractor,
    breadcrumb_extractor,
    question_extractor,
)

__all__ = (
    "EXTRACTOR_REGISTRY", "JsonLdItem", "strip_html_text",
    "faq_extractor", "product_extractor", "event_extractor",
    "person_extractor", "place_extractor", "recipe_extractor",
    "article_extractor", "organization_extractor", "howto_extractor",
    "breadcrumb_extractor", "question_extractor",
)
```

### Key Constraints

- The moved file's content must be **byte-for-byte identical** to the
  original (no re-formatting, no import re-ordering). Reviewers will diff
  the original against the new location to confirm parity.
- The shim file must be the ONLY content at the original path. No mixed
  re-export + extractor logic.
- The two new tests must use `is` identity comparison (not equality) so
  any future accidental duplication of the registry surfaces immediately.

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py` —
  source file to relocate.
- `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py:52-55,
  605-697` — the only known internal consumer of the registry.
- `packages/ai-parrot/src/parrot/utils/__init__.py` — exposes
  `cPrint`, `SafeDict`, `parse_toml_config`. Adding `jsonld_extractors`
  as a submodule does NOT require changes to this `__init__.py` because
  callers will use the explicit dotted import.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/utils/jsonld_extractors.py` exists with
      content identical to the pre-move
      `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`.
- [ ] `packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`
      contains only the re-export shim (≤ 25 lines including blank lines
      and `__all__`).
- [ ] `packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py`
      imports `EXTRACTOR_REGISTRY` and `JsonLdItem` from
      `parrot.utils.jsonld_extractors`.
- [ ] `from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem`
      succeeds.
- [ ] `from parrot_loaders.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem`
      still succeeds (shim works).
- [ ] Both import paths return the **same object** (`is` comparison passes).
- [ ] Existing loader tests pass unmodified:
      `pytest packages/ai-parrot-loaders/tests/test_webscraping_loader.py
      packages/ai-parrot-loaders/tests/test_jsonld_extractors.py -v`.
- [ ] New promotion tests pass:
      `pytest packages/ai-parrot/tests/test_jsonld_extractors_promotion.py -v`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/utils/jsonld_extractors.py
      packages/ai-parrot-loaders/src/parrot_loaders/jsonld_extractors.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jsonld_extractors_promotion.py

"""Verify the JSON-LD extractor module promotion (FEAT-154 / TASK-1048)."""


def test_jsonld_extractors_promoted_import() -> None:
    """The canonical module import resolves and exposes the registry + dataclass."""
    from parrot.utils.jsonld_extractors import EXTRACTOR_REGISTRY, JsonLdItem

    assert isinstance(EXTRACTOR_REGISTRY, dict)
    assert "Product" in EXTRACTOR_REGISTRY
    assert "FAQPage" in EXTRACTOR_REGISTRY
    # JsonLdItem is a dataclass with the documented field set
    item = JsonLdItem(
        content_kind="test", source_type="test", page_content="x",
    )
    assert item.row_data == {}
    assert item.selector_name is None


def test_jsonld_extractors_backcompat_shim() -> None:
    """The old loader-side import path still works and refers to the same objects."""
    from parrot.utils.jsonld_extractors import (
        EXTRACTOR_REGISTRY as core_registry,
        JsonLdItem as CoreItem,
    )
    from parrot_loaders.jsonld_extractors import (
        EXTRACTOR_REGISTRY as shim_registry,
        JsonLdItem as ShimItem,
    )

    assert core_registry is shim_registry, (
        "Registry must be the same object — duplicate dicts cause silent drift"
    )
    assert CoreItem is ShimItem, (
        "JsonLdItem class must be identical between paths"
    )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/webscrapingtoolkit-jsonld.spec.md` for full context.
2. **Verify the Codebase Contract** — confirm every line number is still accurate
   by reading the source files. Update the contract if the code has shifted.
3. **Update status** in `sdd/tasks/index/webscrapingtoolkit-jsonld.json` → `"in-progress"`.
4. **Implement** following the recommended sequence above.
5. **Verify** all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/TASK-1048-promote-jsonld-extractors-to-core.md`.
7. **Update index** → `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
