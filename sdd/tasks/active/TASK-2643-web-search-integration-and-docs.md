# TASK-2643: web_search opt-in, integration tests, and documentation

**Feature**: FEAT-484 — ReadOnlyRepoToolkit — Safe Repo Grounding for Any Client
**Spec**: `sdd/specs/readonly-repo-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2640, TASK-2642
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 5**, plus the feature's **integration test suite**
(spec §4) and its documentation.

This task closes the feature on three fronts:

1. **The external axis, by construction.** `web_search` is the only tool that
   leaves the machine, so it is the only one with an egress question. Spec §3 is
   precise about the mechanism: when `enable_web_search=False` the method must be
   **not exposed as a tool at all** — "not merely erroring, preserving the
   by-construction property for the egress axis too". Absent, not disabled. The
   mechanism is `AbstractToolkit.exclude_tools`.

2. **The transport-agnosticism guard.** Spec §1 lists transport-agnosticism as a
   goal and §4 makes it "testable rather than aspirational" — because FEAT-482
   registers this toolkit on **two** clients: `NovaClient` (Bedrock Converse) and
   `BedrockMantleClient` (OpenAI-compatible). Spec §6 rules out a per-transport
   adapter: both are `AbstractClient` subclasses sharing one tool registry
   (`base.py:355`) and one execution path. This task proves that with a test, so a
   later change cannot quietly break FEAT-482's second consumer.

3. **The documented contract.** Three things in this feature will surprise a future
   reader and must be written down: the **bounds**, the **degradation contract**,
   and the **worktree plane behavior** (a partner sees roughly last-commit state —
   correct for research, wrong for review).

FEAT-482 depends on this feature. Spec's Worktree Strategy: "**Merge FEAT-484
before FEAT-482's Module 2.**"

---

## Scope

### Part A — `web_search` opt-in
- Add `async def web_search(query, max_results=5) -> dict[str, Any]` to
  `ReadOnlyRepoToolkit`, delegating to `DdgSearchTool`.
- Gate exposure via `AbstractToolkit.exclude_tools`: when
  `enable_web_search=False`, `"web_search"` is added to `exclude_tools` **before**
  tools are generated, so `_generate_tools()` never creates it.
- Import `DdgSearchTool` **lazily** inside the method (it lives in a separate
  distribution, `ai-parrot-tools`), and degrade to a structured error if the import
  or the search fails. Spec §2: "a blocked network reduces capability without
  raising."

### Part B — integration tests (spec §4)
- `test_toolkit_registers_on_client` — registered on a stub `AbstractClient`;
  `_execute_tool` dispatches each tool by name.
- `test_toolkit_works_on_converse_and_openai_clients` — the **transport-agnosticism
  guard**: the same toolkit instance registers and dispatches on both a
  `BedrockConverseBase`-shaped and an `OpenAIBaseClient`-shaped stub, and the
  toolkit contains no transport-specific branching.
- `test_search_then_read_flow` — a `search_code` hit's `path` feeds `read_file`
  successfully within bounds.
- `test_toolkit_against_real_plane` — **opt-in**, `pytest.mark.skipif` when
  `.parrot/wiki` is absent: a real query returns ranked hits excluding `build/`.
- `test_worktree_shares_main_plane` — real `git worktree add`; the toolkit resolves
  the main plane.

### Part C — documentation
- `docs/tools/readonly-repo-toolkit.md` covering: what it is, the four grounding
  axes, read-only-by-construction, the confinement boundary, the §8 Q1 secret
  deny-list, every bound and its default, the degradation contract (`degraded` /
  `degraded_reason`), the worktree plane behavior and its staleness tradeoff, the
  `mode` argument (§8 Q2), `enable_web_search`, and a registration example for
  **both** client transports.

**NOT in scope**:
- Any `dev_flow` / `dev_loop` wiring, or constructing/injecting the toolkit into a
  research partner — that is **FEAT-482's** job (spec §1 Non-Goals).
- Adding an embedder or a vector leg (spec §8 Q4).
- Changing any tool implemented by TASK-2637–2642, except to fix a bug the
  integration tests expose.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` | MODIFY | Add `web_search`; wire `exclude_tools` |
| `packages/ai-parrot/src/parrot/tools/repo/schemas.py` | MODIFY | Add `WebSearchInput` |
| `packages/ai-parrot/tests/tools/repo/test_web_search.py` | CREATE | Opt-in exposure tests |
| `packages/ai-parrot/tests/tools/repo/test_integration.py` | CREATE | Integration suite (spec §4) |
| `docs/tools/readonly-repo-toolkit.md` | CREATE | Feature documentation |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-08-31.

### Verified Imports

```python
from __future__ import annotations

from typing import Any, Optional

# LAZY — import inside web_search(). Ships from the separate `ai-parrot-tools`
# distribution, so a core-only install must not fail at module import time.
from parrot_tools.ddgsearch import DdgSearchTool        # ddgsearch.py:19
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                          # line 216
    #: Public async method names to exclude from tool generation.
    #: VERIFIED at toolkit.py:250-253 — subclasses override this to hide
    #: internal methods that should not be exposed to the LLM.
    exclude_tools: tuple[str, ...] = ()
    def get_tools(...)                                               # line 484
    def _generate_tools(self) -> None                                # line 537

# _generate_tools() skip list, VERIFIED at toolkit.py:548-553:
#     if name in ('get_tools', 'get_tools_filtered', 'get_tools_sync',
#                 'get_tool', 'list_tool_names', 'start', 'stop', 'cleanup',
#                 *self.exclude_tools):
#         continue
# ^ This is the mechanism for "absent, not disabled". `exclude_tools` must be
#   populated BEFORE the first get_tools()/_generate_tools() call.

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    self.tools: Dict[str, Union[ToolDefinition, AbstractTool]] = {}  # line 355
    async def _execute_tool(...)                                     # line 1454

# packages/ai-parrot/src/parrot/clients/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration)      # line 31
# packages/ai-parrot/src/parrot/clients/nova/mantle.py
class BedrockMantleClient(OpenAIBaseClient)                           # line 32
# ^ Both are AbstractClient subclasses. VERIFIED: they share `self.tools`
#   (base.py:355). OpenAIBaseClient has its own _execute_tool at
#   openai_base.py:421.

# packages/ai-parrot-tools/src/parrot_tools/ddgsearch.py
class DdgSearchTool(AbstractTool):                                   # line 19
# It is an AbstractTool: drive it through its PUBLIC `execute()`
# (parrot/tools/abstract.py:837), never `_execute()` (abstract.py:544).
```

### Does NOT Exist

- ~~a per-transport tool adapter being needed~~ — spec §6 rules it out explicitly.
  `BedrockConverseBase` and `OpenAIBaseClient` are both `AbstractClient`
  subclasses sharing one tool registry (`base.py:355`). **Register the toolkit;
  both transports work.** Do not write a Converse-shaped or OpenAI-shaped variant,
  and do not branch on transport inside the toolkit.
- ~~`AbstractToolkit.enable_tool()` / `.disable_tool()` / `.hide_tool()`~~ — no such
  API. The mechanism is the `exclude_tools` class/instance attribute.
- ~~raising from `web_search` when disabled being acceptable~~ — spec §3 Module 5
  requires the method be **not exposed at all**. A tool that exists and errors
  fails the acceptance criterion.
- ~~`DdgSearchTool` being importable from `parrot.tools`~~ — it lives in
  `parrot_tools` (the `ai-parrot-tools` distribution). The `sys.meta_path` finder
  in `parrot/tools/__init__.py` redirects `parrot.tools.ddgsearch` →
  `parrot_tools.ddgsearch`, but per `CLAUDE.md` **prefer the explicit
  `parrot_tools.ddgsearch` in new code**.
- ~~`ai-parrot-tools` being guaranteed installed~~ — it is a sibling distribution.
  Import lazily and degrade on `ImportError`.
- ~~`DdgSearchTool._execute` being the entry point~~ — it is private. Use the
  public `execute()` (`abstract.py:837`), which returns a `ToolResult`.
- ~~a network call being acceptable in a default test run~~ — mock
  `DdgSearchTool`. Only the explicitly opt-in real-plane test may touch real
  resources, and it touches the local plane, not the network.
- ~~`.parrot/wiki` existing in CI~~ — it may not. The real-plane test must
  `skipif` on its absence, per spec §4 ("**Opt-in**, skipped when `.parrot/wiki` is
  absent").

---

## Implementation Notes

### Pattern to Follow — absent, not disabled

`exclude_tools` must be set on the **instance**, before any tool generation:

```python
    def __init__(self, *, enable_web_search: bool = False, **kwargs: Any) -> None:
        # ... existing __init__ body from TASK-2638 ...
        if not enable_web_search:
            # Shadow the class attribute with an instance one. _generate_tools()
            # (toolkit.py:548) reads self.exclude_tools, so `web_search` is never
            # turned into a tool — spec §3 Module 5: absent, not disabled.
            self.exclude_tools = tuple(self.exclude_tools) + ("web_search",)
```

Verify your ordering: if `super().__init__()` generates tools eagerly, set
`exclude_tools` **before** calling it. Read `AbstractToolkit.__init__` and
`get_tools` to confirm when `_generate_tools()` first runs, and place the
assignment accordingly. A test asserts the tool is genuinely absent.

### Pattern to Follow — lazy, degrading delegation

```python
    @tool_schema(WebSearchInput)
    async def web_search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        """Search the public web. Use only for information outside this
        repository — library documentation, error messages, upstream changes.

        For anything about this codebase, use `search_code` instead.

        Args:
            query: What to search the web for.
            max_results: Maximum results to return.

        Returns:
            Mapping with a ``results`` list, or an ``error`` key when web
            search is unavailable.
        """
        try:
            from parrot_tools.ddgsearch import DdgSearchTool
        except ImportError as exc:
            self.logger.warning("web_search unavailable: %s", exc)
            return {"error": "web_search_unavailable", "detail": str(exc),
                    "results": []}
        try:
            tool = DdgSearchTool()
            result = await tool.execute(query=query, max_results=max_results)
            return {"results": getattr(result, "result", result)}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("web_search failed: %s", exc)
            return {"error": "web_search_failed", "detail": str(exc),
                    "results": []}
```

Check `DdgSearchTool`'s actual `args_schema` before finalising the `execute()`
kwargs — the parameter names may differ from `query`/`max_results`.

### Pattern to Follow — the transport-agnosticism guard

The point is that **one** toolkit instance serves both client shapes with no
branching. Keep the stubs minimal and shaped like the real registries:

```python
class _StubClient:
    """Minimal AbstractClient-shaped stub: one tool registry, one dispatch."""

    def __init__(self, transport: str):
        self.transport = transport
        self.tools: dict[str, Any] = {}

    def register(self, toolkit) -> None:
        for tool in toolkit.get_tools():
            self.tools[tool.name] = tool

    async def _execute_tool(self, name: str, **kwargs):
        return await self.tools[name].execute(**kwargs)
```

Then assert the **same** toolkit instance produces identical tool names and
identical dispatch results on both, and grep the package for transport names.

### Key Constraints

- No network in the default test run — mock `DdgSearchTool`.
- No `dev_flow` / `dev_loop` import anywhere in `parrot/tools/repo/`.
- No new required dependency (spec §7). `ddgs` is already available via
  `parrot_tools.ddgsearch`, and reaching it is optional.
- The docs must state the worktree staleness tradeoff explicitly — spec §2 flags
  that it is right for research and **wrong for a reviewer**. A future reader
  reusing this toolkit for review needs that warning.
- Google-style docstrings, strict type hints, `self.logger`.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/toolkit.py:250,537` — `exclude_tools` and
  the generation skip list.
- `packages/ai-parrot/src/parrot/clients/base.py:355,1454` — the shared registry
  and dispatch that make transport-agnosticism true.
- `packages/ai-parrot/src/parrot/clients/nova/client.py:31`,
  `nova/mantle.py:32` — the two real consumers to shape stubs after.
- `packages/ai-parrot-tools/src/parrot_tools/ddgsearch.py:19` — the delegate.
- `packages/ai-parrot/tests/tools/test_bedrock_tool_format.py` — existing example
  of asserting tool wiring across client formats.

---

## Acceptance Criteria

### Part A — web_search
- [ ] **Absent when disabled**: with `enable_web_search=False` (the default),
      `"web_search"` is **not** in `{t.name for t in get_tools()}`
- [ ] **Present when enabled**: with `enable_web_search=True` it is present and
      delegates to `DdgSearchTool`
- [ ] Degrades on `ImportError` and on a search exception — returns a structured
      error dict, never raises
- [ ] The write-shaped-tool assertion still passes with `enable_web_search=True`

### Part B — integration
- [ ] `test_toolkit_registers_on_client` passes: every tool dispatches by name
      through a stub client's `_execute_tool`
- [ ] **Transport-agnosticism**: the same toolkit instance yields identical tool
      names and identical dispatch results on a Converse-shaped and an
      OpenAI-shaped stub client
- [ ] **No transport branching in the toolkit**:
      `grep -rniE "converse|openai|bedrock|nova|mantle" packages/ai-parrot/src/parrot/tools/repo/`
      returns nothing
- [ ] `test_search_then_read_flow` passes: a `search_code` hit's path reads
      successfully within bounds
- [ ] `test_toolkit_against_real_plane` is `skipif`-guarded on `.parrot/wiki`
      absence and, when it runs, returns ranked hits with **no** `build/` paths
- [ ] `test_worktree_shares_main_plane` passes against a real `git worktree add`
- [ ] Full suite green: `pytest packages/ai-parrot/tests/tools/repo/ -v`

### Part C — docs and feature close-out
- [ ] `docs/tools/readonly-repo-toolkit.md` exists and documents: the four axes,
      read-only-by-construction, confinement, the secret deny-list (§8 Q1), **every
      bound with its default**, the degradation contract, the worktree plane
      behavior **including the staleness tradeoff and the research-vs-review
      caveat**, the `mode` argument (§8 Q2), and `enable_web_search`
- [ ] Docs include a registration example for **both** transports
- [ ] Clean: `ruff check` + `mypy` on `packages/ai-parrot/src/parrot/tools/repo/`
- [ ] Every spec §5 acceptance criterion is satisfied by the finished feature —
      walk the list and confirm each one
- [ ] No new required dependency added to any `pyproject.toml`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/repo/test_web_search.py
import pytest
from pathlib import Path

from parrot.tools.repo import ReadOnlyRepoToolkit


class TestWebSearchExposure:
    def test_absent_when_disabled(self, temp_repo: Path):
        """Spec §3 Module 5: absent, not merely erroring."""
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo)
        assert "web_search" not in {t.name for t in tk.get_tools()}

    def test_present_when_enabled(self, temp_repo: Path):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, enable_web_search=True)
        assert "web_search" in {t.name for t in tk.get_tools()}

    async def test_degrades_on_import_error(self, temp_repo, monkeypatch):
        import builtins
        real = builtins.__import__

        def _fail(name, *a, **k):
            if "ddgsearch" in name:
                raise ImportError("no ddgs")
            return real(name, *a, **k)
        monkeypatch.setattr(builtins, "__import__", _fail)

        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, enable_web_search=True)
        out = await tk.web_search("anything")
        assert out["error"] == "web_search_unavailable"
        assert out["results"] == []
```

```python
# packages/ai-parrot/tests/tools/repo/test_integration.py
import re
import pathlib
import pytest
from pathlib import Path

from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.models import RepoReadResult, RepoSearchResult

PKG = pathlib.Path("packages/ai-parrot/src/parrot/tools/repo")


class _StubClient:
    """Minimal AbstractClient-shaped stub (base.py:355 + :1454)."""

    def __init__(self, transport: str):
        self.transport = transport
        self.tools: dict = {}

    def register(self, toolkit) -> None:
        for tool in toolkit.get_tools():
            self.tools[tool.name] = tool

    async def _execute_tool(self, name: str, **kwargs):
        return await self.tools[name].execute(**kwargs)


class TestClientRegistration:
    async def test_registers_and_dispatches(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)
        client = _StubClient("generic")
        client.register(tk)
        assert client.tools
        out = await client._execute_tool("read_file", path="pkg/sub/mod.py")
        assert out is not None


class TestTransportAgnosticism:
    """Spec §4 guard: FEAT-482 registers this on NovaClient (Converse) AND
    BedrockMantleClient (OpenAI-compatible)."""

    async def test_same_toolkit_on_both_transports(self, temp_repo,
                                                   stub_wiki_store):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)
        converse = _StubClient("converse")
        openai = _StubClient("openai")
        converse.register(tk)
        openai.register(tk)

        assert set(converse.tools) == set(openai.tools)

        a = await converse._execute_tool("read_file", path="pkg/sub/mod.py")
        b = await openai._execute_tool("read_file", path="pkg/sub/mod.py")
        assert str(a) == str(b)

    def test_no_transport_branching_in_package(self):
        banned = re.compile(r"converse|openai|bedrock|nova|mantle", re.I)
        for f in PKG.rglob("*.py"):
            assert not banned.search(f.read_text()), f


class TestSearchThenRead:
    async def test_flow(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)
        found = await tk.search_code("alpha")
        assert found.hits
        path = found.hits[0].path
        read = await tk.read_file(path)
        assert isinstance(read, RepoReadResult)


class TestRealPlane:
    """Opt-in (spec §4) — skipped when the local plane is absent."""

    @pytest.mark.skipif(
        not pathlib.Path(".parrot/wiki/wiki.db").exists(),
        reason="no local wiki plane built",
    )
    async def test_real_query_excludes_build_artifacts(self):
        tk = ReadOnlyRepoToolkit(repo_root=Path.cwd())
        out = await tk.search_code("ReadOnlyRepoToolkit AbstractToolkit")
        assert out.degraded is False, out.degraded_reason
        assert not any("build/lib" in h.path for h in out.hits)


class TestWorktreeSharesPlane:
    async def test_worktree_resolves_main_plane(self, temp_repo, temp_worktree):
        from parrot.tools.repo.graph_search import resolve_plane_root
        assert await resolve_plane_root(temp_worktree) == temp_repo.resolve()
```

---

## Agent Instructions

1. **Read the spec** in full — this task's acceptance includes walking **every**
   §5 criterion for the finished feature, not just this task's own.
2. **Check dependencies** — TASK-2640 and TASK-2642 must both be in
   `sdd/tasks/completed/`. The integration tests exercise every prior task.
3. **Verify the Codebase Contract**, especially the `exclude_tools` mechanism and
   `DdgSearchTool`'s real `args_schema`.
4. Update the index → `"in-progress"`.
5. **Implement** Parts A, B and C. If an integration test exposes a bug in an
   earlier task, fix it here and record which task it belonged to.
6. **Verify** every acceptance criterion, then walk spec §5 end to end.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"` and set `completed_at` on the index header.
9. **Fill in the Completion Note**, and note that FEAT-482's Module 2 is now
   unblocked (spec Worktree Strategy: merge FEAT-484 first).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
