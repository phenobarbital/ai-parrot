# TASK-2360: Namespaced id helpers (`ns::id`) and ns-aware `_ID_PREFIX_RE` (`context.py`)

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (id half). Foreign pages are addressed as `<ns>::<id>` (decision 1, U3: local
ids stay unprefixed). `context.py` already owns id-prefix parsing (`_ID_PREFIX_RE`, line 30, used
at 124 to elide a redundant title in stub lines) and `pack_results`. The federation layer
(TASK-2362), the CLI (2363/2364) and the tools (2365) all need one canonical split/qualify pair,
and stub rendering must keep working for qualified ids.

---

## Scope

- Add to `context.py`: `NS_SEPARATOR: str = "::"`,
  `split_namespaced_id(page_id: str) -> tuple[Optional[str], str]` (split on the **first** `::`;
  no separator → `(None, page_id)`; an empty namespace part → `(None, page_id)` untouched), and
  `qualify_id(namespace: Optional[str], page_id: str) -> str` (`None`/`""` → unchanged; never
  double-qualifies an already qualified id with the same namespace).
- Make `_ID_PREFIX_RE` tolerate an optional leading `<ns>::` so the title-elision check at line
  124 works for `asyncdb::file:README.md` exactly as for `file:README.md`. Keep the inner-colon
  guarantee documented in the comment at 27-29 (`file:docs/summaries/mod:parrot.skills.md`).
- Unit tests in `tests/knowledge/wiki/test_context.py` (extend the existing file).

**NOT in scope**: any store/CLI/tool change; `cli.py:417-420` prune checks (local plane only,
untouched by design — see TASK-2366 for prune scoping).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/context.py` | MODIFY | helpers + regex |
| `tests/knowledge/wiki/test_context.py` | MODIFY | add tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, PackedContext, pack_results, truncate_to_tokens, first_sentence  # context.py:40,131
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/context.py
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s")                                    # 25
#: Leading ``<kind>:`` namespace of a page id.  Matched non-greedily and only at the start ...   # 27-29
_ID_PREFIX_RE = re.compile(r"^(?:file|dir|mod|pkg|doc|func|class|concept|page):")  # 30
_NOISE_LEADS = frozenset({"---", "...", "-"})                                      # 34
class PackedContext(BaseModel): text, stubs, tokens_used, results_packed, total_available, truncated   # 40
# stub line builder (≈100-130):
rid = result.get("concept_id") or result.get("node_id") or result.get("page_id") or "?"   # 107
title = str(result.get("title") or "").strip()                                              # 109
lead = first_sentence(str(result.get("snippet") or result.get("summary") or ""))            # 110
if title and title.rstrip("/") not in (rid, _ID_PREFIX_RE.sub("", rid, count=1)):          # 124
    body += f" {title}"
def pack_results(results: Iterable[Any], budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> PackedContext   # 131 — dedups ids (139)
```

### Does NOT Exist
- ~~`NS_SEPARATOR`~~, ~~`split_namespaced_id`~~, ~~`qualify_id`~~ — you create them (in `context.py`,
  not in a new module; keep `context.py` dependency-light — it is imported by `tools.py` and the CLI).
- ~~`parrot.knowledge.wiki.namespaces`~~ module — does not exist; do not create one.
- Other parsers of id prefixes: only `context.py:124` and `cli.py:417-420` exist (verified by grep).

---

## Implementation Notes

### Pattern to Follow
```python
# Keep the regex anchored and non-greedy; the namespace group must not consume a single ':'.
_NS_PREFIX_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9_.:-]*?)::")
def split_namespaced_id(page_id: str) -> tuple[Optional[str], str]:
    head, sep, tail = page_id.partition("::")
    if not sep or not head or not tail:
        return None, page_id
    return head, tail
```
`_ID_PREFIX_RE.sub("", rid, count=1)` at line 124 must strip `asyncdb::file:` from
`asyncdb::file:README.md` → `README.md`. Simplest: prepend an optional namespace group to the
existing pattern: `^(?:[^:]+(?::[^:]+)*::)?(?:file|dir|...):` — verify with the tests below.

### Key Constraints
- Pure functions, no I/O, typed, docstrings.
- Do not change `pack_results` semantics (ranked order, dedup by id, budget stop).

---

## Acceptance Criteria

- [ ] `split_namespaced_id("asyncdb::file:a/b.py") == ("asyncdb", "file:a/b.py")`
- [ ] `split_namespaced_id("file:docs/mod:parrot.skills.md") == (None, "file:docs/mod:parrot.skills.md")`
- [ ] `split_namespaced_id("legal:civil::concept:x") == ("legal:civil", "concept:x")`
- [ ] `qualify_id(None, "file:x") == "file:x"`; `qualify_id("ns", "file:x") == "ns::file:x"`; `qualify_id("ns", "ns::file:x") == "ns::file:x"`
- [ ] `pack_results([{"concept_id": "asyncdb::file:README.md", "title": "README.md", "summary": "..."}])` stub line does not repeat the title
- [ ] `pytest tests/knowledge/wiki/test_context.py -v` passes; `ruff check .../context.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_context.py (append)
from parrot.knowledge.wiki.context import NS_SEPARATOR, pack_results, qualify_id, split_namespaced_id

@pytest.mark.parametrize("pid,expected", [
    ("asyncdb::file:a/b.py", ("asyncdb", "file:a/b.py")),
    ("file:docs/summaries/mod:parrot.skills.md", (None, "file:docs/summaries/mod:parrot.skills.md")),
    ("legal:civil::concept:x", ("legal:civil", "concept:x")),
    ("::file:x", (None, "::file:x")),
])
def test_split(pid, expected): assert split_namespaced_id(pid) == expected

def test_qualify_idempotent():
    assert qualify_id("ns", "file:x") == "ns" + NS_SEPARATOR + "file:x"
    assert qualify_id("ns", "ns::file:x") == "ns::file:x"
    assert qualify_id(None, "file:x") == "file:x"

def test_stub_elides_title_for_qualified_id():
    packed = pack_results([{"concept_id": "asyncdb::file:README.md", "title": "README.md", "summary": "Readme."}])
    assert packed.text.count("README.md") == 1
```

---

## Agent Instructions

1. Read spec §2 New Public Interfaces, §3 Module 2, §6 (`context.py` block), §7 gotchas.
2. Verify the contract; implement; run `pytest tests/knowledge/wiki/test_context.py -v`.
3. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (main session)
**Date**: 2026-08-23
**Notes**: NS_SEPARATOR, split_namespaced_id, qualify_id in context.py; _ID_PREFIX_RE now tolerates an optional leading <ns>:: so stub title elision works for qualified ids. 11 new tests in test_context.py.

**Deviations from spec**: split_namespaced_id additionally rejects a head that is itself a <kind>: prefix (e.g. 'file:a::b.py'), so a local path containing '::' is never mis-split. Ran ruff --fix on context.py (UP035/UP045 pre-existed).
