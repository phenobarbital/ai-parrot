# TASK-2243: Integration & discovery — exports, TOOL_REGISTRY, CI green

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2242
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. This task exists for a structural reason: it is the **sole
owner of every shared file** in the feature. Tasks 2235-2242 were deliberately
forbidden from touching `research/__init__.py` and `parrot_tools/__init__.py`
so that the two implementation chains could run in parallel worktrees without
merge conflicts.

It also closes a **CI-blocking gap** found in spec review: `TOOL_REGISTRY` is
auto-generated and CI runs the generator in `--check` mode, which exits 1 when
the registry is stale. Adding new toolkits without regenerating it turns the
build red.

---

## Scope

- Fill in `parrot_tools/research/__init__.py` with the public exports.
- Run `python scripts/generate_tool_registry.py` and **commit the regenerated**
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py`.
- Verify `python scripts/generate_tool_registry.py --check` exits 0.
- Write the cross-toolkit integration tests listed in spec §4.
- Run the full research test suite offline.

**NOT in scope**: changing any toolkit or router logic; documentation
(TASK-2244). If an integration test fails, fix it here only if the fix is in a
shared file — otherwise report it and open a follow-up.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/__init__.py` | MODIFY | Replace the TASK-2234 stub with real exports |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | **Regenerated** — do not hand-edit |
| `packages/ai-parrot-tools/tests/research/test_integration.py` | CREATE | Cross-toolkit integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.research.models import (
    Citation, IndicatorValue, PaperResult, DatasetResult, ResearchResult,
)
from parrot_tools.research.base import BaseResearchToolkit
from parrot_tools.research.open_data import OpenDataToolkit
from parrot_tools.research.academic import AcademicResearchToolkit
from parrot_tools.research.router import ResearchRouter, ResearchRouterArgs
from parrot.tools.manager import ToolManager
```

### Packaging & Discovery Facts (verified)

| Fact | Location |
|---|---|
| `TOOL_REGISTRY` is **auto-generated** — never hand-edit | `parrot_tools/__init__.py:7` (header comment) |
| Registry entry shape: `"arxiv": "parrot_tools.arxiv_tool.ArxivTool"` | `parrot_tools/__init__.py:34` |
| `__all__ = ["__version__", "TOOL_REGISTRY"]` | `parrot_tools/__init__.py:152` |
| Generator scans `pkg_dir.rglob("*.py")`; no decorator needed | `scripts/generate_tool_registry.py:53,72` |
| Base classes excluded from the registry | `scripts/generate_tool_registry.py:38` — `"AbstractTool", "AbstractToolkit", "ToolkitTool", "ToolResult"` |
| **CI fails when the registry is stale** | `.github/workflows/ci.yml:30` → `uv run python scripts/generate_tool_registry.py --check` |
| Generator CLI modes | `--dry-run`, `--check`, `--verbose`, `--tools-only` (`generate_tool_registry.py:9-14`) |

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def register_toolkit(...)                 # line 920
    async def execute_tool(...)               # line ~1566
        # line 1594: if result.status == "error":
        # line 1614:     raise ValueError(result.error)
```

### Does NOT Exist

- ~~A hand-maintained `TOOL_REGISTRY`~~ — it is generated; edit the source
  modules and re-run the generator
- ~~A registration decorator for satellite tools~~ — discovery is by class scan
- ~~`MarketResearchToolkit`~~ — dropped from v1; do **not** export it
- ~~`scripts/generate_tool_registry.py` inside the satellite package~~ — it
  lives at the **repo root** `scripts/`

---

## Implementation Notes

### Exports

```python
# parrot_tools/research/__init__.py
"""Research toolkits: authoritative open-data and academic sources."""
from .models import (
    Citation, IndicatorValue, PaperResult, DatasetResult, ResearchResult,
)
from .base import BaseResearchToolkit
from .open_data import OpenDataToolkit
from .academic import AcademicResearchToolkit
from .router import ResearchRouter, ResearchRouterArgs

__all__ = [
    "Citation", "IndicatorValue", "PaperResult", "DatasetResult",
    "ResearchResult", "BaseResearchToolkit", "OpenDataToolkit",
    "AcademicResearchToolkit", "ResearchRouter", "ResearchRouterArgs",
]
```

Keep these imports side-effect free — the optional third-party libraries are
already guarded by `try/except ImportError` inside each module, so importing
`parrot_tools.research` must work even without the `research` extra installed.
**Verify this explicitly** (acceptance criterion below).

### Registry regeneration

```bash
source .venv/bin/activate
python scripts/generate_tool_registry.py --dry-run --verbose   # inspect first
python scripts/generate_tool_registry.py                        # write
python scripts/generate_tool_registry.py --check                # must exit 0
git diff --stat packages/ai-parrot-tools/src/parrot_tools/__init__.py
```
Review the diff before committing — it should add entries for the new
toolkits/router and change nothing else.

### Key Constraints

- Do not hand-edit the generated registry.
- Do not modify toolkit or router logic in this task.
- The integration tests must run fully offline.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/__init__.py` — current registry shape
- `.github/workflows/ci.yml:30` — the gate this task must satisfy

---

## Acceptance Criteria

- [ ] `from parrot_tools.research import OpenDataToolkit,
      AcademicResearchToolkit, ResearchRouter` resolves.
- [ ] All five models are importable from `parrot_tools.research`.
- [ ] **Importing `parrot_tools.research` succeeds with the `research` extra
      NOT installed** (guarded optional imports) — asserted by test.
- [ ] `TOOL_REGISTRY` contains entries for the new toolkits and the router.
- [ ] **`python scripts/generate_tool_registry.py --check` exits 0.**
- [ ] The registry diff touches only the expected new entries.
- [ ] `MarketResearchToolkit` appears nowhere in exports or the registry.
- [ ] Each toolkit's `get_tools()` returns exactly its 5 expected tool names.
- [ ] **Contract test**: with every network dependency mocked to fail, every
      toolkit method returns a `ResearchResult` and `ToolManager.execute_tool()`
      completes without raising.
- [ ] Every `status="success"` result across both toolkits carries a complete
      `Citation`.
- [ ] `pytest packages/ai-parrot-tools/tests/research/ -v` passes offline
      (whole suite, all tasks' tests).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/research/` clean.

---

## Test Specification

```python
import subprocess, sys
import pytest


class TestExports:
    def test_public_exports(self):
        from parrot_tools.research import (
            OpenDataToolkit, AcademicResearchToolkit, ResearchRouter,
            Citation, ResearchResult,
        )

    def test_import_without_research_extra(self, hide_optional_libs):
        """Optional deps are guarded — the package must still import."""
        import importlib
        importlib.reload(importlib.import_module("parrot_tools.research"))

    def test_market_toolkit_absent(self):
        import parrot_tools.research as r
        assert not hasattr(r, "MarketResearchToolkit")


class TestRegistry:
    def test_registry_not_stale(self):
        p = subprocess.run(
            [sys.executable, "scripts/generate_tool_registry.py", "--check"],
            capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr

    def test_registry_contains_new_toolkits(self):
        from parrot_tools import TOOL_REGISTRY
        joined = " ".join(TOOL_REGISTRY.values())
        assert "OpenDataToolkit" in joined
        assert "AcademicResearchToolkit" in joined
        assert "ResearchRouter" in joined


class TestToolSurface:
    @pytest.mark.parametrize("cls,expected", [
        ("OpenDataToolkit", {"search_world_bank", "get_world_bank_indicator",
                             "search_eu_open_data", "search_oecd_data",
                             "get_oecd_indicator"}),
        ("AcademicResearchToolkit", {"search_crossref", "search_pubmed",
                                     "search_semantic_scholar", "search_arxiv",
                                     "get_paper_details"}),
    ])
    def test_expected_tools(self, cls, expected):
        import parrot_tools.research as r
        assert {t.name for t in getattr(r, cls)().get_tools()} == expected


class TestErrorContract:
    async def test_no_method_raises_into_agent_loop(self, all_network_fails):
        """G7 contract test across every toolkit method."""
        import parrot_tools.research as r
        for tk in (r.OpenDataToolkit(), r.AcademicResearchToolkit()):
            for tool in tk.get_tools():
                out = await tool.execute(**minimal_args_for(tool))
                assert out.status != "error", f"{tool.name} would make ToolManager raise"
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 5, §6 "Packaging & Discovery Facts", §9 item B5.
2. **Check** TASK-2242 is in `sdd/tasks/completed/` (and, transitively, all
   of 2234-2241).
3. **Verify the Codebase Contract** before writing code.
4. Update the index → `"in-progress"`.
5. **Implement**: exports → regenerate registry → integration tests.
6. **Run `--check` and confirm exit 0 before finishing** — this is the CI gate.
7. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
