# TASK-2227: Research agent & node factories — web, deep-research, arxiv

**Feature**: FEAT-425 — "Thales" Research Flow with Structured Citations, Decks & Final Report
**Spec**: `sdd/specs/agentcrew-tales-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2226
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-425. Builds the per-run research agents for the three v1
sources and normalizes each source's raw output (plus grounding/groundedness
metadata) into `Finding`/`SourceClaim` lists. Research agents are registered
in an ephemeral per-run `AgentRegistry` so `AgentsFlow.from_definition` can
resolve them. Spec §2 Overview ("Research nodes per angle") and §6 contract.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/thales/factories.py` with:
  - `build_web_agent(angle, config) -> WebSearchAgent` — constructed with
    `use_builtin_search=True`, `contrastive_search=True`,
    `enable_groundedness=True`.
  - `build_arxiv_agent(angle, config) -> Agent` — a `BasicAgent`/`Agent`
    carrying `ArxivTool()`, `enable_groundedness=True`.
  - `build_deep_research_caller(config)` — an async callable wrapping the
    configured client's `ask(prompt, deep_research=True)`. Cross-provider
    flag (base contract); default client Google. Bedrock logs-and-ignores
    the flag — the caller must degrade to a plain ask, never raise.
  - `build_agent_registry(angles, config) -> AgentRegistry` — ephemeral
    per-run registry holding the research agents keyed by deterministic
    names (e.g. `thales-web-<angle_id>`).
  - Normalizers: `websearch_to_findings(...)`, `arxiv_to_findings(...)`,
    `deep_research_to_findings(...)` → `list[Finding]` with `SourceClaim`s.
    Arxiv paper dict maps 1:1 (title/authors/published/pdf_url/journal_ref →
    claim fields; `source_tool="arxiv_search"`, `verification="groundedness"`
    when a GroundednessReport is present). Built-in search / deep research
    claims are labeled `verification="provider_grounding"`.
  - Extract `GroundednessReport` dumps from
    `AIMessage.metadata["guardrails"]["groundedness"]` when present.
- Cap extracted paragraphs per finding at `config.max_paragraphs_per_finding`.
- Unit tests (mocked agents/clients — no network, no real LLM).

**NOT in scope**: flow Node classes (TASK-2229/2230), FlowDefinition assembly
(TASK-2231), rendering (TASK-2228).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/thales/factories.py` | CREATE | Agent builders + output normalizers |
| `packages/ai-parrot/tests/flows/thales/test_factories.py` | CREATE | Unit tests (mocked) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-17 against `dev`.

### Verified Imports
```python
from parrot.bots.search import WebSearchAgent            # bots/search.py:45
from parrot_tools.arxiv_tool import ArxivTool            # parrot_tools/arxiv_tool.py:36
from parrot.registry.registry import AgentRegistry       # registry/registry.py
from parrot.flows.thales.models import Finding, SourceClaim, ThalesConfig  # TASK-2226
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/search.py:45
class WebSearchAgent(BasicAgent):
    def __init__(self, name='WebSearchAgent', agent_id='web_search_agent',
                 use_llm='google', llm='google:gemini-3-flash',
                 tools=None, use_builtin_search: bool = False,
                 contrastive_search: bool = False, synthesize: bool = False,
                 **kwargs): ...
    async def ask(self, question: str, **kwargs) -> AIMessage: ...
    # use_builtin_search=True → kwargs['tool_type'] = 'builtin_tools' (Gemini internal search)
    # contrastive: response.metadata['initial_search_results'] carries step-1 text

# packages/ai-parrot/src/parrot/clients/base.py — CROSS-PROVIDER flag:
#   async def ask(..., deep_research: bool = False, ...)         # L1631
#   async def ask_stream(..., deep_research: bool = False, ...)  # L1667
# Provider semantics:
#   google/client.py:2876 ask → L2914 routes to _deep_research_ask (L5015,
#     model "deep-research-pro-preview-12-2025" L5026)
#   claude.py:425 ask → L444/L470 enhanced research system prompt
#     (_get_deep_research_system_prompt L1755)
#   gpt.py:679 ask → L722 _resolve_deep_research_model (L324, o3/o4-deep-research)
#   bedrock.py:591 ask → L648 LOGS AND IGNORES deep_research/background
#   grok.py:440 / groq.py:690 accept the flag

# packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py:36
class ArxivTool(AbstractTool):
    name = "arxiv_search"
    # _format_paper returns dict keys: title, authors, published, updated,
    # summary, arxiv_id, pdf_url, categories, primary_category, comment, journal_ref
    # _execute returns {"query", "count", "papers": [...], "message"}

# packages/ai-parrot/src/parrot/bots/abstract.py:718
#   self.enable_groundedness = bool(kwargs.pop('enable_groundedness', False))
#   → pass enable_groundedness=True as a plain bot kwarg.

# packages/ai-parrot/src/parrot/security/groundedness/guardrail.py
#   report lands at AIMessage.metadata["guardrails"]["groundedness"] (FLAG-only)
```

### Does NOT Exist
- ~~A `DeepResearchAgent` bot class~~ — deep research is the `ask()` flag
  above; this task wraps it in a plain async callable.
- ~~Uniform `deep_research` semantics across providers~~ — see per-provider
  notes above; Bedrock ignores the flag (`bedrock.py:648`).
- ~~`ArxivTool.search()` / `.run()`~~ — the execution method is `_execute`
  (invoked through the agent's tool loop, not directly).
- ~~`WebSearchAgent(builtin_search=True)`~~ — the kwarg is
  `use_builtin_search` (verify spelling).
- ~~`AIMessage.metadata["groundedness"]`~~ at top level — the report is
  nested under `metadata["guardrails"]["groundedness"]`.

---

## Implementation Notes

### Pattern to Follow
```python
# Ephemeral registry pattern: instantiate AgentRegistry(), register the
# per-run agents, hand it to AgentsFlow.from_definition (TASK-2231 does the
# handing; this task only builds and returns the registry).
```

### Key Constraints
- Async throughout; no network in tests (mock `ask`/tool results).
- `accessed_date` = run date (ISO), injected by the caller — normalizers
  must accept it as a parameter, never call `datetime.now()` deep inside
  (testability).
- Missing publication dates stay `None` — NEVER fabricate a date.
- Paragraph cap via `ThalesConfig.max_paragraphs_per_finding`.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` — factory-module precedent.
- `packages/ai-parrot/tests/test_deep_research_mock.py` — how deep research is mocked.

---

## Acceptance Criteria

- [ ] Web agent built with `use_builtin_search=True`, `contrastive_search=True`, `enable_groundedness=True`
- [ ] Arxiv paper dict → `SourceClaim` mapping covers title/authors/published/pdf_url/journal_ref
- [ ] Deep-research caller passes `deep_research=True` to the client; a Bedrock-like client that ignores the flag still yields findings (no exception)
- [ ] Claims labeled: arxiv/tool-based → `groundedness` (report present) else `unverified`; builtin-search/deep-research → `provider_grounding`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/thales/test_factories.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/thales/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/thales/test_factories.py
import pytest
from parrot.flows.thales import factories
from parrot.flows.thales.models import ThalesConfig

def test_websearch_agent_flags():
    agent = factories.build_web_agent(angle=..., config=ThalesConfig(thesis="t"))
    assert agent.use_builtin_search is True
    assert agent.contrastive_search is True
    assert agent.enable_groundedness is True

def test_arxiv_paper_to_source_claim():
    paper = {"title": "T", "authors": ["A"], "published": "2024-01-02",
             "pdf_url": "https://arxiv.org/pdf/1", "journal_ref": None,
             "summary": "s", "arxiv_id": "1", "categories": [],
             "primary_category": "cs.AI", "updated": None, "comment": None}
    findings = factories.arxiv_to_findings(
        {"papers": [paper], "count": 1}, accessed_date="2026-08-17",
        config=ThalesConfig(thesis="t"))
    claim = findings[0].claims[0]
    assert claim.source_tool == "arxiv_search"
    assert claim.published_date == "2024-01-02"

@pytest.mark.asyncio
async def test_deep_research_flag_passthrough():
    """Caller passes deep_research=True; flag-ignoring client degrades cleanly."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2226 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code
4. **Update status** in `sdd/tasks/index/agentcrew-tales-research.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2227-thales-research-factories.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-17
**Notes**: Implemented `build_web_agent`, `build_arxiv_agent`,
`build_deep_research_caller` (LLMFactory-backed, default
`google:gemini-3-flash`, cross-provider `deep_research=True` passthrough),
`build_agent_registry` (per-angle singleton registration for `web`/`arxiv`
sources), and normalizers `websearch_to_findings`, `deep_research_to_findings`,
`arxiv_to_findings` plus `extract_groundedness_report`. 26 unit tests pass
(mocked — no network/LLM). `ruff check` reports only pre-existing `UP045`
style findings (see TASK-2226 note).

Design notes (verified against actual registry code, not guessed):
- `AgentRegistry.register()` requires a *class* factory (`issubclass` check)
  and only its sync `get_bot_instance()` reads a cached `_instance` — so
  `build_agent_registry` registers `singleton=True` per (angle, source) under
  deterministic names; eager `get_instance()` resolution is left to TASK-2231
  (`from_definition` wiring), matching FEAT-163's established eager-resolve
  pattern.
- `build_deep_research_caller` uses `LLMFactory.create(llm=...)`
  (`clients/factory.py:179`, verified) to build the configured client from a
  `"provider:model"` string — not in the task's Verified Imports list, but
  independently confirmed to exist before use, per the anti-hallucination rule.
- Websearch/deep-research normalizers extract structured per-source grounding
  data when present under common metadata keys, else fall back to one
  aggregate claim per response — the codebase does not yet expose a single
  stable parsed citation list for Gemini built-in search / Deep Research.
- Local worktree environment gap (pre-existing, unrelated to this task):
  `parrot.utils.types` / `parrot.utils.parsers.toml` compiled `.so` extensions
  were missing from this worktree; copied from the main checkout's build
  output so tests could import `parrot.bots.*` (gitignored, not committed).

**Deviations from spec**: none
