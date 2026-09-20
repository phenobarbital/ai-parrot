# TASK-3494: Decision read tools, `DecisionToolkit`, and MCP registration

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3490
**Assigned-to**: unassigned

---

## Context

Module 6's agent-facing half. Thin adapters over one `DecisionService`,
following the `structural/` package exactly (`structural/tools.py`,
`structural/toolkit.py`) — that is the sibling feature this one is modelled on.

The gate that matters (spec §2 Module 6): **review is never an agent tool.**

> `wiki_decisions_for_symbol` and `wiki_decision_why` always registered with the
> existing read-store routing. `wiki_decision_generate` is registered only when
> `generation_enabled` and a local writable project are available. Review remains
> a maintainer CLI action, not an autonomous agent tool.

This task also takes ownership of `decisions/__init__.py`, replacing the
docstring-only placeholder TASK-3479 created with the full public surface.

---

## Scope

- Implement `WikiDecisionsForSymbolTool` and `WikiDecisionWhyTool` (always
  registered) and `WikiDecisionGenerateTool` (conditionally registered).
- Implement `create_decision_tools(store, root, config)` with namespace-aware
  service resolution, rejecting `--ns all` with `ADR_INVALID_ARGUMENT`.
- Implement `DecisionToolkit(AbstractToolkit)` with `tool_prefix='decision'`,
  exposing `for_symbol` and `why`; generation is explicit opt-in.
- Register the read tools in `mcp_server.py`.
- Replace `decisions/__init__.py` with the full re-export surface.
- Test registration gating, namespace rejection, and the absence of any review
  tool.

**NOT in scope**: managed-page protection on the *existing* wiki tools
(TASK-3495), the CLI (TASK-3496), service internals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py` | CREATE | Three `AbstractTool` wrappers + `create_decision_tools` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py` | CREATE | `DecisionToolkit(AbstractToolkit)` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py` | MODIFY | Replace the placeholder with the public surface |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | Register the decision tools |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_tools.py` | CREATE | Gating, namespaces, no-review-tool |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.abstract import AbstractTool, ToolResult      # tools/abstract.py:281, :250
from parrot.tools.toolkit import AbstractToolkit                # tools/toolkit.py:206
from parrot.knowledge.wiki.context import truncate_to_tokens    # context.py:273
from parrot.knowledge.wiki.project import (                     # project.py
    WikiProjectConfig, find_project_root, load_effective_config, sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store
from parrot.knowledge.wiki.structural.service import StructuralService   # structural/service.py:117
from parrot.knowledge.wiki.tools import _scoped_store, _unknown_namespace_error  # tools.py:25, :108
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                     # line 250
    success: bool = True; status: str = "success"; result: Any
    error: Optional[str] = None; metadata: Dict[str, Any]
class AbstractTool(EventEmitterMixin, ABC):                      # line 281
    name: str = None; description: str = None                    # lines 296-297
    args_schema: Type[BaseModel] = AbstractToolArgsSchema         # line 298
    async def _execute(self, **kwargs) -> Any: ...                # line 579

# packages/ai-parrot/src/parrot/tools/toolkit.py:206
class AbstractToolkit(ABC):
    tool_prefix: str | None = None                                # line 257
    def get_tools_sync(...): ...                                  # line 602

# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
def _scoped_store(store: BaseWikiStore, namespace: str | None) -> BaseWikiStore: ...   # line 25
def _unknown_namespace_error(store: BaseWikiStore, namespace: str) -> str: ...         # line 108
def create_wiki_tools(store, root=None, config=None, ledger_service=None) -> list[AbstractTool]: ...  # line 741

# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
tools = create_wiki_tools(read_store, root=root, config=config, ledger_service=ledger_service)   # line 202
from parrot.knowledge.wiki.structural import create_structural_tools                             # line 207
tools = tools + create_structural_tools(read_store, root, config)                                # line 209  <- ANCHOR
```

**Follow `structural/tools.py` and `structural/toolkit.py` as the template** —
same `ServiceFactory` pattern, same `_NAMESPACE_DESC` wording, same
`_render_text` shape, same `get_tools_sync()` toolkit construction.

### Does NOT Exist

- ~~a review or accept MCP tool~~ — and this task must not create one. Spec §2:
  "Review remains a maintainer CLI action, not an autonomous agent tool" and
  "No model invocation or MCP tool automatically accepts a candidate" (AC11).
- ~~`_scoped_store` supporting `'all'` for ADR~~ — it is the generic wiki helper.
  ADR reads target **one** namespace; `'all'` must be rejected with
  `ADR_INVALID_ARGUMENT` before it reaches the store (spec §2 Module 6).
- ~~`StructuralService(store, None, config)`~~ — `root` is a required `Path`
  (`structural/service.py:127`). With no local root, pass `structural=None` to
  `DecisionService` instead.
- ~~an existing `decisions` entry in `mcp_server.py`~~ — line 209 is the last
  tool-list extension before the Obsidian block; the anchor is unique.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_tools.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#ToolResult",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#create_wiki_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py#DecisionService"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)

1. Read `structural/tools.py` end to end — *why*: this task is that file's twin,
   and divergence in the namespace argument or result shape would be a
   gratuitous inconsistency in one MCP server's tool set.
2. Write the two read tools, then the gated generate tool — *why*: gating is the
   AC11 boundary and deserves to be written deliberately, not copied.
3. Write the toolkit, then `__init__.py`, then the `mcp_server.py` line.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py` (CREATE)

```python
"""Decision-plane ``AbstractTool`` wrappers (FEAT-578 Module 6).

Mirrors :mod:`parrot.knowledge.wiki.structural.tools` so the decision tools
register alongside the other wiki tools on one ``StdioMCPServer``
(``wiki_decisions_for_symbol``, ``wiki_decision_why``, and — only when
explicitly enabled — ``wiki_decision_generate``).

There is deliberately NO review tool: accepting a candidate is a maintainer
CLI action, never something an agent does on its own (spec §2, AC11).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.context import truncate_to_tokens
from parrot.knowledge.wiki.decisions.models import ADR_INVALID_ARGUMENT, DecisionDossier, DecisionError
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS, render_dossier_text
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.tools.abstract import AbstractTool, ToolResult

#: Same wording as ``structural.tools._NAMESPACE_DESC``, minus 'all' — ADR
#: reads target exactly one namespace in v1 (spec §2 Module 6).
_NAMESPACE_DESC = (
    "Federated namespace to read: a namespace name, or 'local' for this "
    "repo's own wiki. 'all' is not supported for decisions."
)

ServiceFactory = Callable[[str | None], DecisionService]


class DecisionsForSymbolInput(BaseModel):
    """Arguments for ``wiki_decisions_for_symbol`` / ``decision_for_symbol``."""

    symbol: str = Field(..., description="A sym:<rel>#<qualname> id, or an exact symbol name")
    include_history: bool = Field(default=False, description="Include rejected/deprecated/superseded records")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum hits across both groups")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, ge=256, description="Estimated output budget")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class DecisionWhyInput(BaseModel):
    """Arguments for ``wiki_decision_why`` / ``decision_why``."""

    question: str = Field(..., description="Natural-language question, optionally naming a symbol")
    include_history: bool = Field(default=False, description="Include rejected/deprecated/superseded records")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum hits across both groups")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, ge=256, description="Estimated output budget")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class DecisionGenerateInput(BaseModel):
    """Arguments for ``wiki_decision_generate``."""

    target: str = Field(..., description="One sym: id or one repository-relative file path")


def _dossier_result(dossier: DecisionDossier, budget_tokens: int) -> ToolResult:
    """Render a dossier as a ToolResult, labels intact.

    The text body always carries the origin/status/freshness labels and the
    candidate group heading, so a model reading only the text cannot mistake
    a candidate for documented history (AC3, AC9).
    """
    # FILL IN: text, _ = truncate_to_tokens(render_dossier_text(dossier) + "\n\n"
    # + json.dumps(dossier.model_dump(mode="json")), budget_tokens); return
    # ToolResult(result=text, metadata={"status": dossier.status,
    # "truncated": dossier.truncated}). Bounded by AC9.
    raise NotImplementedError


def _error_result(exc: DecisionError) -> ToolResult:
    """Render a DecisionError as a failed ToolResult with its stable code."""
    return ToolResult(success=False, status="error", result=None, error=f"{exc.code}: {exc.message}")


class WikiDecisionsForSymbolTool(AbstractTool):
    """Find the architectural decisions that apply to a symbol, with citations.
    Returns documented ADRs and, separately, labeled inferred candidates."""

    name = "wiki_decisions_for_symbol"
    description = (
        "Find architectural decisions (ADRs) that apply to a function, class "
        "or method, with source citations. Documented decisions and inferred "
        "candidates are returned as separate, explicitly labeled groups — a "
        "candidate is a hypothesis, not accepted history."
    )
    args_schema = DecisionsForSymbolInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(self, symbol: str, include_history: bool = False, limit: int = 10,
                       budget_tokens: int = DEFAULT_BUDGET_TOKENS, namespace: str | None = None) -> ToolResult:
        # FILL IN: resolve the service via self._service_factory(namespace),
        # catching ValueError from an unknown namespace into an error
        # ToolResult; call for_symbol(...); wrap with _dossier_result; map
        # DecisionError through _error_result. Bounded by spec §2's transport
        # paragraph ("MCP returns the same data ... with failures marked as
        # errors").
        raise NotImplementedError


class WikiDecisionWhyTool(AbstractTool):
    """Answer "why is this built this way?" with cited decision excerpts."""

    name = "wiki_decision_why"
    description = (
        "Answer a 'why' question about the codebase with cited decision "
        "excerpts and supporting code. Documented decisions rank above "
        "inferred candidates, which are returned in their own labeled group."
    )
    args_schema = DecisionWhyInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(self, question: str, include_history: bool = False, limit: int = 10,
                       budget_tokens: int = DEFAULT_BUDGET_TOKENS, namespace: str | None = None) -> ToolResult:
        # FILL IN: same shape as WikiDecisionsForSymbolTool._execute, calling why()
        raise NotImplementedError


class WikiDecisionGenerateTool(AbstractTool):
    """Generate labeled candidate rationale for an undocumented symbol or file.

    Registered ONLY when generation is enabled and a local writable project is
    available. It creates UNREVIEWED candidates — it cannot accept anything.
    """

    name = "wiki_decision_generate"
    description = (
        "Generate explicitly labeled CANDIDATE rationale for a symbol or file "
        "that has no documented decision. Candidates are inferred, unreviewed "
        "hypotheses and are never accepted history; a maintainer accepts them "
        "separately through the CLI."
    )
    args_schema = DecisionGenerateInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(self, target: str) -> ToolResult:
        # FILL IN: call generate(target) on the LOCAL service (namespace=None)
        # and return its GenerationResult; map DecisionError via _error_result
        raise NotImplementedError


def create_decision_tools(
    store: BaseWikiStore,
    root: Path | None,
    config: WikiProjectConfig,
) -> list[AbstractTool]:
    """Create namespace-aware read tools and explicitly enabled generation tools.

    The two read tools are always returned. ``wiki_decision_generate`` is
    appended ONLY when ``config.decisions.generation_enabled`` is true AND a
    local writable ``root`` exists (spec §2 Module 6). No review tool is ever
    created (AC11).
    """
    # FILL IN: build a ServiceFactory closure that
    #   - raises ValueError(_unknown_namespace_error(store, ns)) for an unknown
    #     namespace, matching structural/tools.py's contract
    #   - raises DecisionError(ADR_INVALID_ARGUMENT, ...) for namespace == "all"
    #   - otherwise builds DecisionService(_scoped_store(store, ns), root,
    #     config.decisions, structural=StructuralService(...) when root is not
    #     None else None)
    # then return [WikiDecisionsForSymbolTool(f), WikiDecisionWhyTool(f)] plus
    # the generate tool under the gate above.
    raise NotImplementedError
```

**Why this shape**: the `ServiceFactory` indirection is copied from
`structural/tools.py` because the tool is constructed once at server start but
the namespace arrives per call. Rejecting `'all'` inside the factory — before
`_scoped_store` sees it — is what keeps the generic helper's broadcast semantics
from leaking into a surface the spec says is single-namespace. `create_decision_tools`
having no branch that can produce a review tool is the structural form of AC11:
there is nothing to disable, because nothing exists.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py` (CREATE)

```python
"""``DecisionToolkit`` — agent-facing surface over ``DecisionService``.

Mirrors :class:`~parrot.knowledge.wiki.structural.toolkit.CodeStructuralToolkit`:
resolve (or accept) a root, config and store, then expose public async
methods that ``AbstractToolkit`` converts into tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.project import WikiProjectConfig, find_project_root, load_effective_config
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.tools.toolkit import AbstractToolkit


class DecisionToolkit(AbstractToolkit):
    """Query the codebase's architectural decisions: symbol lookup and cited why.

    Tool prefix: ``"decision"`` — methods are exposed as
    ``decision_for_symbol`` and ``decision_why``. Candidate generation is
    explicit opt-in via ``include_generation=True`` and still requires
    ``generation_enabled`` in the project config. Review is never exposed
    (spec §2, AC11).
    """

    tool_prefix: str = "decision"

    def __init__(
        self,
        root: Path | None = None,
        store: BaseWikiStore | None = None,
        config: WikiProjectConfig | None = None,
        include_generation: bool = False,
        **kwargs: Any,
    ) -> None:
        """Resolve root/config/store, then build one shared service."""
        # FILL IN: mirror CodeStructuralToolkit.__init__ (structural/toolkit.py:
        # ~66-110) — resolve root via find_project_root, raise ValueError with
        # the same style of message when absent, load_effective_config, build
        # the store when not given, then build one DecisionService.
        raise NotImplementedError

    async def for_symbol(self, symbol: str, include_history: bool = False, limit: int = 10) -> dict[str, Any]:
        """Find the architectural decisions that apply to a symbol.

        Returns two separate groups: ``documented`` (real ADRs, with their
        declared lifecycle status) and ``candidates`` (INFERRED hypotheses
        that no maintainer has accepted). Every hit carries its origin,
        status, freshness and at least one source citation.

        Args:
            symbol: A ``sym:<rel>#<qualname>`` id, or an exact symbol name.
                An ambiguous name returns ``status='ambiguous'`` with the
                candidate ids rather than guessing.
            include_history: Also return rejected, deprecated and superseded
                records.
            limit: Maximum hits across both groups.

        Returns:
            A ``DecisionDossier`` as a JSON-safe dict.

        Raises:
            DecisionError: With a stable ``ADR_*`` code.
        """
        # FILL IN: return (await self._service.for_symbol(...)).model_dump(mode="json")
        raise NotImplementedError

    async def why(self, question: str, include_history: bool = False, limit: int = 10) -> dict[str, Any]:
        """Answer a 'why is it built this way' question with cited decisions.

        Documented decisions rank above inferred candidates and the two
        groups are never merged. Citations prove what the code does; a
        candidate's ``hypotheses`` are reasoning, not history.

        Args:
            question: Natural language; it need not name a symbol.
            include_history: Also return rejected/deprecated/superseded records.
            limit: Maximum hits across both groups.

        Returns:
            A ``DecisionDossier`` as a JSON-safe dict.

        Raises:
            DecisionError: With a stable ``ADR_*`` code.
        """
        # FILL IN: return (await self._service.why(...)).model_dump(mode="json")
        raise NotImplementedError
```

**Why**: the docstrings are the LLM-facing descriptions (`AbstractToolkit`
derives tool descriptions from them), so they must state the provenance
distinction explicitly — spec §2 Module 6: "All tool methods document return
groups, provenance, and errors."

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py` (MODIFY)

Replace the whole file (TASK-3479 left a docstring-only placeholder) with the
public surface, mirroring `structural/__init__.py`:

```python
"""ADR extraction and decision retrieval (FEAT-578).

Re-exports the service, its Pydantic contracts, the ``AbstractTool``
wrappers and :class:`DecisionToolkit`.
"""

from __future__ import annotations

from parrot.knowledge.wiki.decisions.models import (
    CandidateEdit, DecisionConfig, DecisionDossier, DecisionError, DecisionHit,
    DecisionRecord, EvidenceRef, GenerationResult, ReviewRequest, SyncResult,
)
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.decisions.toolkit import DecisionToolkit
from parrot.knowledge.wiki.decisions.tools import (
    WikiDecisionGenerateTool, WikiDecisionsForSymbolTool, WikiDecisionWhyTool, create_decision_tools,
)

__all__ = [
    "CandidateEdit", "DecisionConfig", "DecisionDossier", "DecisionError",
    "DecisionHit", "DecisionRecord", "DecisionService", "DecisionToolkit",
    "EvidenceRef", "GenerationResult", "ReviewRequest", "SyncResult",
    "WikiDecisionGenerateTool", "WikiDecisionWhyTool", "WikiDecisionsForSymbolTool",
    "create_decision_tools",
]
```

**Why**: `review.py` is **not** re-exported — keeping it off the package surface
makes "review is a CLI action" visible in the API shape itself.

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    tools = tools + create_structural_tools(read_store, root, config)' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py)
# AFTER — insert directly below `    tools = tools + create_structural_tools(read_store, root, config)`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:209):

    # FEAT-578: decision-plane tools (wiki_decisions_for_symbol,
    # wiki_decision_why) share the same read_store, so they honour the same
    # federated namespaces. wiki_decision_generate is added by the factory
    # only when generation is enabled AND a local project is available; there
    # is no review tool — acceptance is a maintainer CLI action (AC11).
    from parrot.knowledge.wiki.decisions import create_decision_tools

    tools = tools + create_decision_tools(read_store, root, config)
```

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_tools.py` (CREATE)

```python
"""Tool registration, gating and namespace policy (FEAT-578 M6, AC9/AC11)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions import create_decision_tools
from parrot.knowledge.wiki.decisions.models import DecisionError
from parrot.knowledge.wiki.project import WikiProjectConfig


def _config(generation_enabled: bool = False) -> WikiProjectConfig:
    config = WikiProjectConfig()
    config.decisions.generation_enabled = generation_enabled
    return config


class TestRegistration:
    def test_read_tools_are_always_registered(self, adr_store, tmp_path):
        names = {t.name for t in create_decision_tools(adr_store, tmp_path, _config())}
        assert {"wiki_decisions_for_symbol", "wiki_decision_why"} <= names

    def test_generate_is_absent_by_default(self, adr_store, tmp_path):
        """AC5: the shipped default cannot invoke a model."""
        names = {t.name for t in create_decision_tools(adr_store, tmp_path, _config())}
        assert "wiki_decision_generate" not in names

    def test_generate_appears_only_when_enabled_and_local(self, adr_store, tmp_path):
        with_local = {t.name for t in create_decision_tools(adr_store, tmp_path, _config(True))}
        assert "wiki_decision_generate" in with_local
        # FILL IN: assert it is ABSENT when root is None even with
        # generation_enabled=True — spec §2 "a local writable project"
        raise NotImplementedError

    def test_no_review_or_accept_tool_exists(self, adr_store, tmp_path):
        """AC11: an agent can never accept a candidate."""
        names = {t.name for t in create_decision_tools(adr_store, tmp_path, _config(True))}
        assert not any("review" in n or "accept" in n for n in names)

    def test_mcp_server_registers_the_read_tools(self, tmp_path):
        # FILL IN: build the wiki MCP server for a temp project the way
        # packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py does and
        # assert both read tool names are registered
        raise NotImplementedError


class TestNamespacePolicy:
    async def test_all_namespace_is_rejected(self, adr_store, tmp_path):
        """spec §2 Module 6: 'all' is ADR_INVALID_ARGUMENT in v1."""
        tool = next(t for t in create_decision_tools(adr_store, tmp_path, _config())
                    if t.name == "wiki_decision_why")
        result = await tool._execute(question="why", namespace="all")
        assert result.success is False
        assert "ADR_INVALID_ARGUMENT" in (result.error or "")

    async def test_unknown_namespace_is_a_structured_error(self, adr_store, tmp_path):
        # FILL IN: assert an unknown namespace yields success=False with a
        # readable message, not an escaping exception
        raise NotImplementedError


class TestOutputLabels:
    async def test_candidates_are_labeled_in_the_text_body(self, adr_store, tmp_path):
        """AC9: labels survive the tool's own output budget."""
        # FILL IN: seed one inferred record; call wiki_decision_why with a small
        # budget_tokens; assert "INFERRED" appears in result.result
        raise NotImplementedError


class TestToolkit:
    def test_tool_prefix_and_methods(self, adr_store, tmp_path):
        from parrot.knowledge.wiki.decisions import DecisionToolkit

        toolkit = DecisionToolkit(root=tmp_path, store=adr_store)
        assert toolkit.tool_prefix == "decision"
        names = {t.name for t in toolkit.get_tools_sync()}
        assert names == {"decision_for_symbol", "decision_why"}

    def test_toolkit_never_exposes_review(self, adr_store, tmp_path):
        from parrot.knowledge.wiki.decisions import DecisionToolkit

        toolkit = DecisionToolkit(root=tmp_path, store=adr_store, include_generation=True)
        assert not any("review" in t.name for t in toolkit.get_tools_sync())
```

### FILL IN checklist

- [ ] `tools.py::_dossier_result` — budgeted text + JSON tail; bounded by AC9
- [ ] `tools.py` — three `_execute` bodies; bounded by spec §2 transport
- [ ] `tools.py::create_decision_tools` — factory closure, `'all'` rejection, generate gate; bounded by spec §2 Module 6 / AC11
- [ ] `toolkit.py::__init__` — mirror `CodeStructuralToolkit`; bounded by `structural/toolkit.py:66-110`
- [ ] `toolkit.py::for_symbol` / `::why` — one-line delegations
- [ ] `test_tools.py` — five test bodies

---

## Acceptance Criteria

- [ ] `wiki_decisions_for_symbol` and `wiki_decision_why` are always registered
- [ ] `wiki_decision_generate` appears only with `generation_enabled` **and** a local root (spec §2 Module 6)
- [ ] **No** review/accept tool exists on any surface (AC11)
- [ ] `namespace='all'` yields `ADR_INVALID_ARGUMENT`; an unknown namespace yields a structured error, not an exception
- [ ] Tool text output keeps the origin/status/freshness labels and the candidate heading under budget (AC9)
- [ ] `DecisionToolkit.tool_prefix == 'decision'` and exposes exactly `decision_for_symbol` / `decision_why`
- [ ] `decisions/__init__.py` exports the public surface and does **not** export `review`
- [ ] `mcp_server.py` registers the tools via one added block after line 209
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -q` still passes (AC10)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py -q`

---

## Agent Instructions

1. **Read the spec** §2 Module 6 and AC9/AC11.
2. **Read `structural/tools.py` and `structural/toolkit.py` in full** before writing — this task is their twin.
3. **Verify the Codebase Contract** — confirm `mcp_server.py:209` and `tools.py:25`, `:108`.
4. **Implement** from the blueprint; complete every `# FILL IN:`.
5. **Verify** all three Validation Commands pass.
6. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
7. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
