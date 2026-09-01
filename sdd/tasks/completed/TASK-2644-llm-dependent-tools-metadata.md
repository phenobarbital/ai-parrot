# TASK-2644: `llm_dependent_tools` metadata attribute on AbstractToolkit + WebScrapingToolkit tagging

**Feature**: FEAT-485 — Expose Toolkits as Local MCP
**Spec**: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The local MCP runner (TASK-2646) must drop LLM-dependent
tools when a served toolkit has no `llm:` configured. The identification
mechanism decided in the spec is a **toolkit metadata attribute** —
`llm_dependent_tools: frozenset` — mirroring the existing
`confirming_tools` pattern (class-level frozenset, pure metadata, no
machinery change inside `AbstractToolkit` itself).

---

## Scope

- Add `llm_dependent_tools: frozenset = frozenset()` class attribute to
  `AbstractToolkit`, documented with a Google-style docstring comment block
  in the same style as `confirming_tools` (toolkit.py:279-285).
- Tag `WebScrapingToolkit.llm_dependent_tools = frozenset({"plan_create"})`.
  Do NOT tag `scrape`: it uses the LLM only as a plan-inference fallback
  (toolkit.py:820) and already degrades with an informative `RuntimeError`
  from `_get_llm_client()` (toolkit.py:378-383) that the MCP adapter maps
  to a tool error result.
- Write unit tests.

**NOT in scope**: any filtering logic that CONSUMES the attribute (that is
TASK-2646); changes to `WebBrowsingToolkit` (inherits the tagging);
changes to `get_tools()`/`_generate_tools()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | add documented `llm_dependent_tools` class attribute |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` | MODIFY | set `llm_dependent_tools = frozenset({"plan_create"})` |
| `tests/tools/test_llm_dependent_tools.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit        # verified: packages/ai-parrot/src/parrot/tools/toolkit.py
from parrot_tools.scraping.toolkit import WebScrapingToolkit  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:274
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    #: documented example block for confirming_tools at line 279
    confirming_tools: frozenset = frozenset()  # line 285  ← mirror THIS pattern
    # line 676-678: methods named in confirming_tools get
    #   tool.routing_meta["requires_confirmation"] = True
    # (do NOT add equivalent routing_meta wiring for llm_dependent_tools —
    #  it stays pure metadata read by the MCP runner)

# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py
class WebScrapingToolkit(AbstractToolkit):  # line 274
    def __init__(self, ..., llm_client: Optional[Any] = None, **kwargs):  # line 300/318
    def _get_llm_client(self) -> Any:  # line 378 — raises RuntimeError when None (line 383)
    async def plan_create(...)  # line 487 — calls _get_llm_client() at line 539 (ALWAYS needs LLM)
    async def scrape(...)       # line 698 — conditional _get_llm_client() at line 820 (fallback only)
```

### Does NOT Exist
- ~~`AbstractToolkit.llm_dependent_tools`~~ — this task creates it.
- ~~routing_meta["llm_dependent"]~~ — no such routing_meta key; do not add one.
- ~~`WebScrapingToolkit.plan_infer`~~ — not a method name; the LLM tool is `plan_create`.

---

## Implementation Notes

### Pattern to Follow
Copy the `confirming_tools` declaration style exactly (attribute + `#:`
doc comment at toolkit.py:279-285), placing `llm_dependent_tools`
immediately after it.

### Key Constraints
- Metadata only — zero behavior change in this package.
- Subclasses inherit; `WebBrowsingToolkit` inherits scraping's tagging
  automatically (correct: its inherited `plan_create` still needs the LLM).

---

## Acceptance Criteria

- [ ] `AbstractToolkit.llm_dependent_tools` exists, defaults to empty frozenset
- [ ] `WebScrapingToolkit.llm_dependent_tools == frozenset({"plan_create"})`
- [ ] `WebBrowsingToolkit.llm_dependent_tools` inherits the same value
- [ ] `scrape` is NOT tagged
- [ ] Tests pass: `pytest tests/tools/test_llm_dependent_tools.py -v`
- [ ] `ruff check` clean on touched files

---

## Test Specification

```python
# tests/tools/test_llm_dependent_tools.py
from parrot.tools.toolkit import AbstractToolkit


def test_default_empty():
    assert AbstractToolkit.llm_dependent_tools == frozenset()


def test_scraping_tags_plan_create():
    pytest.importorskip("parrot_tools.scraping.toolkit")
    from parrot_tools.scraping.toolkit import WebScrapingToolkit
    assert WebScrapingToolkit.llm_dependent_tools == frozenset({"plan_create"})
    assert "scrape" not in WebScrapingToolkit.llm_dependent_tools


def test_browsing_inherits():
    pytest.importorskip("parrot_tools.browsing.toolkit")
    from parrot_tools.browsing.toolkit import WebBrowsingToolkit
    assert "plan_create" in WebBrowsingToolkit.llm_dependent_tools
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/expose-toolkits-as-local-mcp.json` → `"in-progress"`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index** → `"done"`, **fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
