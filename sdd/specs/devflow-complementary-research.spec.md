---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Complementary (Collaborative) Research for the Dev Flow

**Feature ID**: FEAT-482
**Date**: 2026-08-31
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/devflow-complementary-research.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The proactive dev-flow (`packages/ai-parrot/src/parrot/flows/dev_flow/`) turns a
natural-language development request into a committed SDD document through a
**single-model research seat**. `IdeationNode` (`nodes/ideation.py:91`) dispatches
one `sdd-ideation` subagent on `claude-sonnet-4-6` (`ideation.py:338`), and that one
agent's reading of the codebase becomes the brainstorm or proposal that every
downstream phase — spec, tasks, worktree, implementation — inherits. The same shape
holds for the ops flow's `ResearchNode` (`dev_loop/nodes/research.py:195`).

That single seat is the narrowest point in the pipeline and the one where a blind
spot is most expensive: an option never considered at ideation time does not
reappear at task time. Everything downstream faithfully implements whatever the one
researcher happened to see.

The repo already solved the analogous problem one phase later, at review time.
`ParallelPerspectiveReviewDispatcher` (`dev_loop/code_review.py:341`) runs a primary
write-enabled reviewer and a read-only adversary concurrently via `asyncio.gather`
(`code_review.py:392`) and merges their verdicts (`_merge_verdicts`,
`code_review.py:462`), with the adversarial seat selectable over `{codex, nova}`
(`catalog.py:60`, `resolve_adversarial_backend` `catalog.py:63`).

**Research has no equivalent.** And the review machinery is deliberately
*adversarial* — it exists to challenge. Research wants a **collaborator**: a second
researcher investigating the same request from its own angle, whose findings the
primary researcher reads and expands upon. The value is additive coverage, not a
contest with a winner.

FEAT-405 (`sdd/specs/novaclient-dev-loop.spec.md`) named "a pluggable research seat"
a non-goal because "a Bedrock API seat cannot invoke slash commands, so the
generalization would ship an option that could not do the job." That reasoning holds
for *replacing* the research seat and is irrelevant for *adding a collaborator beside
it*: the partner never runs a slash command, never authors the SDD document, and
never creates a worktree. This feature narrows that non-goal rather than reversing
it (see §8 Q8).

### Goals

- Add an opt-in, configurable, **read-only collaborative research partner** that
  investigates a dev request in parallel with the primary Claude seat, starting with
  Amazon Nova 2 on Bedrock with extended thinking.
- Give the partner a **genuine multi-round repo tool loop**, not a static context
  pack, so it can follow its own line of inquiry.
- Make code search **graph-backed over the existing AST/tree-sitter wiki plane**
  rather than `grep`, and extend that same capability to the primary Claude seat.
- Persist the partner's findings as an auditable `sdd/proposals/<slug>.research.md`
  and attribute merged insights by source.
- Serve **both** `IdeationNode` and `ResearchNode` through one shared mechanism.
- Ship as a **pure addition**: an operator who configures nothing sees byte-identical
  behavior.

### Non-Goals (explicitly out of scope)

- **Any change to the adversarial review path.** `code_review.py` is a pattern
  source, not a target. Generalizing reviews and research into one "perspective"
  abstraction was rejected — see brainstorm Option B.
- **Any change to telemetry rendering.** FEAT-479
  (`devflow-telemetry-accounting`) has 11 `in-progress` tasks touching
  `usage_report.py`, `runner.py`, `dev_flow/models.py` and
  `dev_loop/nodes/research.py`. This feature **emits** `ClientRoundEvent`s through
  the existing FEAT-404 client path and **modifies no reporting code**; FEAT-479's
  ledger picks the events up when it lands (§8 Q3, resolved).
- **A new node in the dev-flow graph.** Rejected as brainstorm Option D: it does
  nothing for `ResearchNode`, and the coordinator seam achieves the same result
  without touching topology.
- **Writing an AST parser or code-graph builder.** Already exists and ships —
  `wiki/languages/`, `repo_scan.py`, an 11518-page SQLite plane. This feature
  consumes it (§6).
- **The vector/embedding leg of graph search.** Lexical FTS5/BM25 only in this
  feature; conceptual-recall improvement is a follow-up (§8 Q10, resolved).
- **Partner participation in HITL resume rounds.** Round 1 only.
- **Replacing the Claude seat.** The partner never authors or commits `sdd/**`.
- **Runtime backend fallback.** If the configured partner fails, the run degrades to
  single-agent; it does not try a different backend.

---

## 2. Architectural Design

### Overview

Three new components plus two small additive changes to existing seams.

**`ReadOnlyRepoToolkit`** — an `AbstractToolkit` giving any `AbstractClient` a
cwd-confined, write-free view of a checkout across four grounding axes. Read-only
**by construction**: `apply_patch` and `run_command` are not members, mirroring
`NovaAdversarialReviewDispatcher`'s "read-only BY CONSTRUCTION" property
(`dispatchers/nova.py:240`) rather than relying on a flag.

| Axis | Tools | Backed by |
|---|---|---|
| Structural | `search_code`, `related_code` | `WikiCombinedSearch` (`wiki/search.py:32`) — the AST/tree-sitter plane |
| Static | `read_file`, `list_files`, `grep_files` (fallback) | Ported from `llm.py:662/677/691` |
| Historical | `git_log`, `git_show`, `git_blame` | New — local `git` subprocess |
| External | `web_search` | `DdgSearchTool` (`ddgsearch.py:19`), ON by default when the partner is enabled |

`search_code` is graph search, not grep: ranked pages with API outlines and
`references` edges, token-budgeted, build artifacts excluded via `git ls-files`.
`grep_files` remains for exact literal matching. Because the plane already indexes
Python via stdlib `ast` and PHP/JS/TS/Rust/Perl via tree-sitter, the toolkit is
multi-language for free.

**`AbstractResearchPartner` + `ResearchPartnerFactory`** — mirrors
`AbstractCodeReviewDispatcher` (`code_review.py:85`) and
`CodeReviewDispatcherFactory` (`code_review.py:164`), including the `advisory = True`
marker (`code_review.py:100`). Sole implementation `NovaResearchPartner` drives
`NovaClient.ask(use_tools=True, thinking_budget=N, structured_output=ResearchFindings)`
over the **existing** multi-round Converse tool loop (`bedrock.py:699`). No new
agentic loop is written.

**`ComplementaryResearchCoordinator`** — the shared seam both nodes call. Fans the
partner out concurrently with the primary seat under a deadline, writes
`sdd/proposals/<slug>.research.md`, and returns `ComplementaryFindings` — or `None`
on any failure. It never raises into a node.

**Prompt/profile changes** — `IdeationNode` and `ResearchNode` each gain one optional
constructor kwarg; `_IdeationBrief` gains two fields; the `sdd-ideation` prompt gains
a Complementary Research section. Per Q11, the primary Claude seat also gains graph
search — which requires a new optional `mcp_servers` field on
`ClaudeCodeDispatchProfile` (see Integration Points).

**Why the partner is prompted neutrally**: it receives the brief, the repo root and
the research question — never Claude's framing, hypotheses or preferred conclusion.
Same discipline `CLAUDE.md` mandates for adversarial review, same reason: supplying
conclusions produces ratification, not independent research.

### Component Diagram

```
                    ┌──────────────────────────────────────────┐
 IdeationNode ─────▶│  ComplementaryResearchCoordinator        │
 (dev_flow)         │    resolve backend → None if disabled    │
 ResearchNode ─────▶│    asyncio.gather(primary ‖ partner)     │
 (dev_loop)         │    asyncio.timeout(deadline)             │
                    └───────────────┬──────────────────────────┘
                                    │
                    ┌───────────────▼──────────────┐
                    │ ResearchPartnerFactory       │
                    │   "nova" → NovaResearchPartner│
                    └───────────────┬──────────────┘
                                    │
              NovaClient.ask(use_tools=True, thinking_budget=N)
                                    │
                    ┌───────────────▼──────────────────────────┐
                    │ BedrockConverseBase.ask()  (UNMODIFIED)  │
                    │   multi-round toolUse ⇄ toolResult       │
                    │   reasoningContent signatures preserved  │
                    │   FEAT-404 ClientRoundEvent per round    │
                    └───────────────┬──────────────────────────┘
                                    │ _execute_tool
                    ┌───────────────▼──────────────┐
                    │ ReadOnlyRepoToolkit          │
                    │  search_code / related_code ─┼──▶ WikiCombinedSearch
                    │  read_file / list_files      │     (FTS5 plane, shared
                    │  grep_files (fallback)       │      from main checkout)
                    │  git_log / git_show / blame  │
                    │  web_search (default off)    │
                    └──────────────────────────────┘

  success ──▶ sdd/proposals/<slug>.research.md  +  ComplementaryFindings
  failure ──▶ warn + partner.degraded event + None  (run continues single-agent)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BedrockConverseBase.ask()` | **uses (unmodified)** | The Converse tool loop, `thinking_budget`, reasoning-signature preservation, FEAT-404 round events. `bedrock.py:699` |
| `NovaClient` | **uses (unmodified)** | `clients/nova/client.py:31` |
| `WikiCombinedSearch` | **uses (unmodified)** | `wiki/search.py:32` — lexical FTS5 leg only |
| `WikiQueryTool` / `WikiRelatedTool` | **wraps** | `wiki/tools.py:155/225` — bind, do not reimplement |
| `IdeationNode` | **modifies** | +1 optional kwarg, +2 `_IdeationBrief` fields, coordinator call in `execute()` |
| `ResearchNode` | **modifies** | Same optional seam. ⚠️ FEAT-479 touches this file |
| `ClaudeCodeDispatchProfile` | **extends** | New `mcp_servers: Optional[dict] = None`. Required by Q11 — `strict_mcp_config` defaults `True` (`models/claude.py:33`), so filesystem `.mcp.json` is ignored and servers must be passed explicitly |
| `ClaudeCodeDispatcher._resolve_run_options()` | **modifies** | Pass `mcp_servers` into `ClaudeAgentRunOptions`. ⚠️ FEAT-479 touches this file |
| `dev_flow/factories.py` | **modifies** | Build + inject the coordinator at `factories.py:117` |
| `catalog.py` | **extends** | Research-partner selector triad mirroring `catalog.py:54/60/63` |
| `conf.py` | **extends** | Six new `DEV_FLOW_RESEARCH_PARTNER_*` keys, all defaulted off |
| `code_review.py` | **none — unmodified** | Pattern source only |
| `usage_report.py` / `run_bundle.py` | **none — unmodified** | Deliberate: FEAT-479 owns these |

### Data Models

```python
class ResearchFinding(BaseModel):
    """One discrete finding from the complementary researcher."""
    id: str                      # stable, e.g. "F1" — enables attributed merge
    title: str
    detail: str
    evidence: list[str] = []     # file:line refs or URLs the partner actually read
    confidence: Literal["high", "medium", "low"] = "medium"


class ResearchFindings(BaseModel):
    """Structured output contract for a research partner dispatch."""
    summary: str
    findings: list[ResearchFinding] = []
    options_considered: list[str] = []
    could_not_determine: list[str] = []
    sources_examined: list[str] = []


class ComplementaryFindings(BaseModel):
    """What the coordinator hands back to a node. Absent == None, never empty."""
    backend: str                 # "nova"
    model: str
    findings: ResearchFindings
    document_path: str = ""      # sdd/proposals/<slug>.research.md, "" if unwritten
    rendered: str                # markdown, already truncation-bounded
    duration_ms: float
    degraded: bool = False
```

### New Public Interfaces

```python
class AbstractResearchPartner(ABC):
    """Read-only, advisory collaborative researcher."""
    partner_name: str
    advisory: bool = True

    @abstractmethod
    async def research(
        self, *, brief: BaseModel, question: str, cwd: str,
        run_id: str, node_id: str, session_host: Optional[SessionHost] = None,
    ) -> ResearchFindings: ...


class ResearchPartnerFactory:
    @classmethod
    def register(cls, name: str): ...
    @classmethod
    def create(cls, name: str, **kwargs) -> AbstractResearchPartner: ...


class ComplementaryResearchCoordinator:
    async def research(
        self, *, brief: BaseModel, question: str, cwd: str, slug: str,
        run_id: str, node_id: str, session_host: Optional[SessionHost] = None,
    ) -> Optional[ComplementaryFindings]:
        """Returns None when disabled or on ANY failure. Never raises."""


class ReadOnlyRepoToolkit(AbstractToolkit):
    def __init__(
        self, *, repo_root: Path, wiki_store: Optional[object] = None,
        wiki_name: str = "parrot", enable_web_search: bool = False,
        max_result_bytes: int = 64_000, command_timeout: float = 20.0,
    ) -> None: ...
```

---

## 3. Module Breakdown

> **Modules 1–2 of the original draft (`ReadOnlyRepoToolkit` and its graph-backed
> `search_code`) were split into their own spec — `sdd/specs/readonly-repo-toolkit.spec.md`
> (FEAT-484) — per §8 Q2. This feature CONSUMES that toolkit and does not implement
> it. FEAT-484 must merge before Module 2 below.**

### Module 1: `AbstractResearchPartner` + factory + config selector
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py`;
  selector triad in `dev_loop/catalog.py`; keys in `conf.py`
- **Responsibility**: the ABC, the registry, `RESEARCH_PARTNER_BACKEND` /
  `_RESEARCH_PARTNER_CHOICES` / `resolve_research_partner_backend()` mirroring
  `catalog.py:54/60/63`, and the six `DEV_FLOW_RESEARCH_PARTNER_*` conf keys. Unset
  config ⇒ disabled ⇒ byte-identical behavior.
- **Depends on**: none (pure contracts).

### Module 2: `NovaResearchPartner`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py`
- **Responsibility**: register `ReadOnlyRepoToolkit` on a `NovaClient`; issue one
  `ask(..., use_tools=True, thinking_budget=N, structured_output=ResearchFindings,
  max_tokens=…)`; build the **neutral** prompt (brief + repo root + question, never
  Claude's framing); return validated `ResearchFindings`.
- **Depends on**: **FEAT-484** (`ReadOnlyRepoToolkit`), Module 1.

### Module 3: `ComplementaryResearchCoordinator`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/complementary_research.py`
- **Responsibility**: resolve backend (→ `None` if disabled); run the partner under
  `asyncio.timeout`; render + commit `sdd/proposals/<slug>.research.md` staging
  **only that path**; emit `partner.started` / `partner.completed` /
  `partner.degraded`; return `ComplementaryFindings` or `None`. Catch
  `Exception` broadly — this is the soft-degradation boundary.
- **Depends on**: Modules 1, 2.

### Module 4: `IdeationNode` + `ResearchNode` seams
- **Path**: `dev_flow/nodes/ideation.py`, `dev_loop/nodes/research.py`,
  `dev_flow/factories.py`
- **Responsibility**: one optional `coordinator` kwarg each; two new
  `_IdeationBrief` fields (`partner_findings`, `partner_findings_path`); call the
  coordinator before the first dispatch on **round 1 only**; wire in
  `build_dev_flow_node_factories` (`factories.py:117`).
- **Depends on**: Module 3. ⚠️ Coordinate with FEAT-479 on `research.py`.

### Module 5: Graph search for the primary Claude seat (Q11)
- **Path**: `dev_loop/models/claude.py`, `dev_loop/dispatchers/claude.py`,
  `dev_flow/nodes/ideation.py`
- **Responsibility**: add optional `mcp_servers: Optional[Dict[str, Any]] = None` to
  `ClaudeCodeDispatchProfile`; pass it into `ClaudeAgentRunOptions` in
  `_resolve_run_options()` (`claude.py:440-451`); in `IdeationNode._dispatch`,
  register the `wikitoolkit` stdio server and extend `allowed_tools`
  (`ideation.py:331`) with `mcp__wikitoolkit__wiki_query` / `wiki_page` /
  `wiki_related`. **Keep `strict_mcp_config=True`** — the field docstring warns that
  inheriting filesystem `.mcp.json` makes non-interactive runs exit with empty error
  results. Default `None` ⇒ unchanged behavior.
- **Depends on**: none technically; ships with Module 6. ⚠️ FEAT-479 touches
  `dispatchers/claude.py`.

### Module 6: Prompt + documentation
- **Path**: `dev_flow/_subagent_data/sdd-ideation.md`, mirrored to
  `.claude/agents/sdd-ideation.md`; `docs/`
- **Responsibility**: Complementary Research prompt section — read the partner's
  findings, expand rather than rebut, attribute insights by finding `id`, state
  disagreements explicitly (disagreement is data), never let absence change process.
  Plus graph-search guidance for the new MCP tools, and operator docs for the six
  config keys.
- **Depends on**: Modules 3, 5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_resolve_research_partner_backend_default_disabled` | 1 | Unset config ⇒ disabled |
| `test_resolve_research_partner_backend_rejects_unknown` | 1 | Invalid value raises naming valid options |
| `test_nova_partner_passes_thinking_budget` | 2 | `ask()` receives `thinking_budget` and `use_tools=True` |
| `test_nova_partner_prompt_excludes_primary_reasoning` | 2 | Prompt contains brief/question but no Claude framing — neutrality guard |
| `test_coordinator_returns_none_when_disabled` | 3 | No partner constructed, no work performed |
| `test_coordinator_soft_degrades_on_timeout` | 3 | Returns `None`, emits `partner.degraded`, does not raise |
| `test_coordinator_soft_degrades_on_parse_failure` | 3 | Invalid structured output ⇒ `None` (NOT a passing-verdict analogue) |
| `test_coordinator_writes_research_md` | 3 | `.research.md` written and committed with only that path staged |
| `test_coordinator_empty_findings_treated_as_absent` | 3 | Trivial findings ⇒ no file, no empty section |
| `test_ideation_passes_partner_findings_to_dispatch` | 4 | `_IdeationBrief.partner_findings` populated on round 1 |
| `test_ideation_resume_round_skips_partner` | 4 | Round 2+ does not re-run the partner (D8) |
| `test_ideation_unchanged_when_coordinator_none` | 4 | Byte-identical dispatch payload to pre-feature behavior |
| `test_profile_mcp_servers_defaults_none` | 5 | Omitted ⇒ `ClaudeAgentRunOptions.mcp_servers` is `None` |
| `test_strict_mcp_config_remains_true` | 5 | Explicit guard: the ideation profile does not flip it to `False` |

### Integration Tests

| Test | Description |
|---|---|
| `test_complementary_research_end_to_end` | Fake partner + real coordinator: findings reach the dispatch payload, `.research.md` is committed, attribution ids survive |
| `test_run_unchanged_with_partner_disabled` | Full dev-flow ideation with config unset produces the same artifacts as pre-feature |
| `test_partner_outage_does_not_fail_run` | Partner raises on every call; run completes single-agent with `partner.degraded` |
| `test_nova_partner_live` | **Opt-in**, skipped without AWS credentials (mirror `tests/flows/dev_loop/test_nova_integration.py`) |

### Test Data / Fixtures

```python
# NOTE: the temp_repo / confinement fixtures live in FEAT-484's suite
# (packages/ai-parrot/tests/tools/repo/), not here.

@pytest.fixture
def fake_partner() -> AbstractResearchPartner:
    """Deterministic ResearchFindings; variants that raise, hang, and
    return unparseable output."""

@pytest.fixture
def stub_toolkit() -> ReadOnlyRepoToolkit:
    """A FEAT-484 toolkit over a tmp repo — this suite asserts the partner
    REGISTERS and USES it, never re-tests its confinement."""
```

New test files under `packages/ai-parrot/tests/flows/dev_flow/`:
`test_research_partner.py`, `test_complementary_research.py`,
`test_ideation_partner_seam.py`. (Toolkit tests live in FEAT-484's
`packages/ai-parrot/tests/tools/repo/`.)

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/flows/dev_flow/ -v`)
- [ ] All integration tests pass (`pytest packages/ai-parrot/tests/flows/dev_loop/integration/ -v`)
- [ ] `ruff check` and `mypy` clean on all changed files
- [ ] **Pure addition**: with every `DEV_FLOW_RESEARCH_PARTNER_*` key unset, the
      ideation dispatch payload and produced artifacts are byte-identical to
      pre-feature behavior (asserted, not assumed)
- [ ] **Soft-degradation**: partner timeout, credential failure, Bedrock outage, and
      structured-output parse failure each leave the run completing normally
- [ ] **FEAT-484 is merged** and its `ReadOnlyRepoToolkit` is the partner's only
      repo-access surface (no bespoke file/search/git tool is defined in this feature)
- [ ] **The partner is given no write capability**: the registered toolkit is
      FEAT-484's, constructed without any write tool — asserted at the registration site
- [ ] Claude keeps sole authorship: no code path lets the partner write under `sdd/`
- [ ] `.research.md` is committed staging **only** that path
- [ ] Merged document attributes partner insights by finding `id`
- [ ] Partner runs on round 1 only
- [ ] **No file owned by FEAT-479's telemetry work is modified**
      (`usage_report.py`, `run_bundle.py`)
- [ ] `strict_mcp_config` remains `True` for the ideation dispatch
- [ ] No new required dependency; feature degrades cleanly without AWS credentials
- [ ] Documentation updated in `docs/` for the six config keys

---

## 6. Codebase Contract

> All anchors below were re-verified on 2026-08-31 **after** merging 19 commits from
> `origin/dev` (including FEAT-480, PR #1280). Line numbers are current as of commit
> `6db6af76e`+.

### Verified Imports

```python
from parrot.clients.nova.client import NovaClient                    # nova/client.py:31
from parrot.clients.bedrock import BedrockConverseBase               # bedrock.py:114
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,                                    # code_review.py:85
    CodeReviewDispatcherFactory,                                     # code_review.py:164
    ParallelPerspectiveReviewDispatcher,                             # code_review.py:341
)
from parrot.flows.dev_loop.catalog import resolve_adversarial_backend  # catalog.py:63
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch      # wiki_search.py:26
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher   # used ideation.py:56
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile, FeatureBrief
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_flow._subagent_defs import load_subagent_definition
from parrot.knowledge.wiki.tools import (                            # wiki/tools.py
    WikiQueryTool, WikiPageTool, WikiRelatedTool, WikiStatusTool,    # :155/:190/:225/:409
    create_wiki_tools,                                               # :541
)
from parrot.knowledge.wiki.search import WikiCombinedSearch          # wiki/search.py:32
from parrot.knowledge.wiki.context import pack_results               # used wiki_search.py:112
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.ddgsearch import DdgSearchTool                     # ddgsearch.py:19
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/bedrock.py
class BedrockConverseBase(AbstractClient):                           # line 114
    def _prepare_tools(self, filter_names: Optional[List[str]] = None
                       ) -> List[Dict[str, Any]]:                    # line 531
    async def ask(                                                   # line 699
        ..., thinking_budget: Optional[int] = None,                  # line 715
    )
    # thinking applied: additional_fields["thinking"] =
    #   {"type": "enabled", "budget_tokens": thinking_budget}        # lines 831-835
    # multi-round Converse loop: toolUse -> _execute_tool -> toolResult  # 930-990
    # FEAT-404 ClientRoundEvent emitted per round                    # lines 971-981
    # assistant turn preserved verbatim -> reasoningContent
    #   signatures survive across rounds                             # lines 986-988

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    self.tools: Dict[str, Union[ToolDefinition, AbstractTool]] = {}  # line 355
    async def _execute_tool(...)                                     # line 1454

# packages/ai-parrot/src/parrot/clients/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):    # line 31
    _default_model: str = "nova-2-lite"                              # line 65
    _fallback_model: str = "nova-lite"                               # line 66

# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):                             # line 85
    advisory: bool = False                                           # line 100
class CodeReviewDispatcherFactory:                                   # line 164
    @classmethod
    def register(cls, name: str)                                     # line 170
class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):# line 267
    advisory = True                                                  # line 278
class ParallelPerspectiveReviewDispatcher(AbstractCodeReviewDispatcher):  # line 341
    primary_result, adversary_result = await asyncio.gather(...)     # line 392
    def _resolve_side(self, result, source) -> CodeReviewVerdict     # line 436
    def _merge_verdicts(self, primary, adversary)                    # line 462

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py
class NovaCodeDispatcher(LLMCodeDispatcher):                         # line 61
class NovaAdversarialReviewDispatcher(AbstractCodeReviewDispatcher): # line 240
    agent_name = "nova-adversarial"                                  # line 267
    advisory = True                                                  # line 268

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:                                             # line 40
    def _tool_read_file(self, cwd, args) -> Dict[str, Any]           # line 662  <- PORT
    def _tool_list_files(self, cwd, args) -> Dict[str, Any]          # line 677  <- PORT
    async def _tool_search_files(...)                                # line 691  <- PORT
    async def _tool_apply_patch(...)                                 # line 723  (EXCLUDE)
    async def _tool_run_command(...)                                 # line 749  (EXCLUDE)

# packages/ai-parrot/src/parrot/flows/dev_loop/models/claude.py
class ClaudeCodeDispatchProfile(BaseModel):                          # line 10
    subagent: Optional[...]                                          # line 18
    system_prompt_override: Optional[str] = None                     # line 28
    allowed_tools: List[str] = Field(default_factory=list)           # line 29
    permission_mode: Literal[...] = "default"                        # line 30
    setting_sources: List[...] = Field(default=lambda: ["project"])  # line 31
    strict_mcp_config: bool = Field(default=True, ...)               # line 32-44
    allow_project_root_cwd: bool = Field(...)                        # line 45
    # NOTE: there is NO mcp_servers field today — Module 5 adds it.

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
    return ClaudeAgentRunOptions(                                    # line 440
        cwd=..., permission_mode=profile.permission_mode,
        allowed_tools=list(profile.allowed_tools) or None,           # line 443
        setting_sources=...,                                         # line 445
        strict_mcp_config=profile.strict_mcp_config,                 # line 446
        ...)                                                         # ends line 451

# packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py
class _IdeationBrief(BaseModel):                                     # line 69
    mode, title, description, context, graph_context, answers,
    document_path, round                     # exactly these 8 fields
@register_dev_loop_node("dev_flow.ideation")                         # line 90
class IdeationNode(DevLoopNode):                                     # line 91
    def __init__(self, *, dispatcher, ideation_max_rounds=None, ...) # line 105
    async def execute(...)                                           # line 122
    async def _dispatch(...)                                         # line 286
        permission_mode="acceptEdits"                                # line 329
        allowed_tools=["Read","Grep","Glob","Bash","Write","Edit"]   # line 331
        allow_project_root_cwd=True                                  # line 336
        model="claude-sonnet-4-6"                                    # line 338

# packages/ai-parrot/src/parrot/flows/dev_flow/models.py
class DevRequestBrief(BaseModel):                                    # line 47
class IdeationOutput(BaseModel):                                     # line 157
    document_path:167  document_kind:175  slug:183
    resumed_existing:184  open_questions:192  summary:200  committed:204

# packages/ai-parrot/src/parrot/flows/dev_flow/factories.py
def build_dev_flow_node_factories(..., dispatcher, ...)              # line 41
    IdeationNode(dispatcher=dispatcher, ...)                         # line 117

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
class ResearchNode(DevLoopNode):                                     # line 195
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher, ...)     # line 218

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
ADVERSARIAL_BACKEND: str = "codex"                                   # line 54
_ADVERSARIAL_BACKEND_CHOICES: Tuple[str, ...] = ("codex", "nova")    # line 60
def resolve_adversarial_backend(config_getter=None) -> str           # line 63
    BackendInfo(id="nova", ...)                                      # line 230

# packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py
class DevLoopWikiSearch:                                             # line 26
    def from_project(...)                                            # line 38
    async def build_research_context(self, query, budget_tokens
        ) -> Optional[str]                                           # line 91
    # best-effort: returns None on ANY internal error, never raises
```

### The code-graph subsystem (consumed, not built)

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py
class LanguageOutline(BaseModel): summary; outline; imports
class LanguageScanner(ABC):
    name: ClassVar[str]; suffixes: ClassVar[frozenset[str]]
    def outline(self, source, rel_path) -> LanguageOutline
    def build_reference_index(...); def resolve_import(...); def mode(self) -> str

# packages/ai-parrot/src/parrot/knowledge/wiki/languages/python.py
class PythonScanner(LanguageScanner):                                # line 30
    tree = ast.parse(source, filename=rel_path or "<unknown>")       # line 49
    # walks Import / ImportFrom / ClassDef / FunctionDef / AsyncFunctionDef  # 63-78

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
def discover_repo_files(...)                                         # line 355
def _git_ls_files(root) -> list[str] | None                          # line 398 (gitignore-aware)
def build_file_slice(...)          # 556      def build_dir_pages(...)      # 645
def build_import_edges(...)        # 718      def scan_repository(...)      # 776

# packages/ai-parrot/src/parrot/knowledge/wiki/search.py
class WikiCombinedSearch:                                            # line 32
    async def search(self, query, mode=..., top_k=..., tree_name=...)# line 91
    # modes: lexical (FTS5/BM25) | vector (needs embedder) | combined
    # default weights lexical .6 / vector .4                         # line 174
    # vector leg SKIPPED when embedder is None                       # line 202

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(...)         # line 117
async def search_fts(self, query, category=None, limit=10)           # line 1147
async def search_vector(self, embedding, limit=10)                   # line 1195

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")           # line 402
    def storage_path(self, root: Path) -> Path                       # line 457
    # ":74 — storage_dir may be absolute, so two repositories can share one"
    #   -> the worktree plane-sharing mechanism (Q9, resolved)
```

Live plane verified 2026-08-31 via `wikitoolkit status`: sqlite backend, 11518
pages / 18844 edges, 548 MB at `.parrot/wiki`, 10442 sources tracked,
`Languages: {python: ast, php|javascript|rust|perl: tree-sitter}`.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `NovaResearchPartner` | `NovaClient.ask()` | `use_tools=True, thinking_budget=N` | `bedrock.py:699,715` |
| `ReadOnlyRepoToolkit` | `AbstractClient._execute_tool` | tool registration on the client | `base.py:355,1454` |
| `search_code` | `WikiCombinedSearch.search()` | lexical mode, `pack_results` | `search.py:32,91` |
| `related_code` | `WikiRelatedTool` | delegation | `wiki/tools.py:225` |
| `ComplementaryResearchCoordinator` | `asyncio.gather` + `asyncio.timeout` | same pattern as the review composite | `code_review.py:392` |
| `ResearchPartnerFactory` | `CodeReviewDispatcherFactory` shape | mirrored registry | `code_review.py:164,170` |
| `resolve_research_partner_backend` | `resolve_adversarial_backend` shape | mirrored triad | `catalog.py:54,60,63` |
| `IdeationNode` | `ComplementaryResearchCoordinator.research()` | optional kwarg, round-1 call | `ideation.py:105,122` |
| Module 5 `mcp_servers` | `ClaudeAgentRunOptions(...)` | new kwarg passthrough | `claude.py:440-451` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AdversarialCodeReviewDispatcher`~~ — the composite parallel reviewer is
  **`ParallelPerspectiveReviewDispatcher`** (`code_review.py:341`).
- ~~a `research` node in the dev-flow graph~~ — `dev_flow/definition.py` lists
  `research` among nodes "deliberately absent". The dev-flow research seat is
  `IdeationNode`.
- ~~`ClaudeCodeDispatchProfile.mcp_servers`~~ — **does not exist today**; Module 5
  adds it. `_resolve_run_options()` (`claude.py:440-451`) currently passes no MCP
  servers, and `strict_mcp_config` defaults `True` (`models/claude.py:33`), so the
  filesystem `.mcp.json` is **ignored** by dispatched runs. Allow-listing
  `mcp__wikitoolkit__*` alone will NOT work.
- ~~`ReadOnlyRepoToolkit`~~ / ~~`RepoBrowseToolkit`~~ — no read-only repo toolkit
  exists. The cwd-confined readers are **private methods** on `LLMCodeDispatcher`
  (`llm.py:662/677/691`), not reusable as-is.
- ~~a local-git toolkit~~ — `parrot_tools/gittoolkit.py` is a **GitHub API** toolkit
  (`RepositoryCredential:48`, `CreatePullRequestInput:267`, `SearchRepoCodeInput:438`).
  No `git log`/`show`/`blame` over a local checkout. Must be built.
- ~~`parrot_tools.code_toolkit.CodeToolkit` as a repo browser~~ — exists
  (`code_toolkit.py:266`) but is a coding-agent-delegation toolkit
  (`implement_spec`, `fix_bug`, `review_diff`, …).
- ~~`GraphIndexToolkit` as the code-search backend~~ — exists
  (`parrot_tools/graphindex/toolkit.py:72`) but needs a prebuilt
  `rustworkx.PyDiGraph` + `faiss.Index` + node maps (`:116`). **Not** the subsystem
  behind `wikitoolkit` code search; that is `parrot/knowledge/wiki/` over SQLite FTS5.
- ~~a need to write an AST parser or code-graph builder~~ — already exists and runs
  (see the code-graph subsystem above).
- ~~a `wiki_query` AbstractTool being absent~~ — **it exists**: `WikiQueryTool`
  (`wiki/tools.py:155`) and five siblings plus `create_wiki_tools()` (`:541`), and
  `LLMWikiToolkit(AbstractToolkit)` (`wiki/toolkit.py:54`). An earlier brainstorm
  revision wrongly listed this as missing; corrected there and here. **Bind these;
  do not write new wiki tools.**
- ~~a Chat Completions endpoint for `us.amazon.nova-*` / `us.anthropic.*` on
  Bedrock~~ — does not exist (`dispatchers/nova.py` module docstring;
  `catalog.py:246-251`). `NovaCodeDispatcher`/bedrock-mantle therefore **cannot**
  serve Nova 2, and `LLMCodeDispatcher`'s OpenAI-shaped loop cannot be reused for it.
- ~~code that writes `sdd/proposals/*.research.md`~~ —
  `agents-flow-refactor.research.md` is hand-written; there is no generator.
- ~~`partner`/`collaborator` fields on `_IdeationBrief`~~ — it has exactly 8 fields
  (`ideation.py:69`); Module 6 adds two.
- ~~`sdd-research` / `sdd-secondopinion` in `dev_flow._subagent_defs`~~ —
  `_VALID_NAMES` is `frozenset({"sdd-ideation"})` (`_subagent_defs.py:33`).
- ~~`FileReaderTool` as a safe repo reader~~ — exists (`file_reader.py:31`) but is
  **not** confined to a repo root.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `AbstractCodeReviewDispatcher` / `CodeReviewDispatcherFactory`
  (`code_review.py:85,164`) for the partner ABC + registry, including `advisory`.
- Mirror the `catalog.py:54/60/63` triad for the backend selector — module constant,
  choices tuple, `resolve_*()` raising `ValueError` naming valid options.
- Mirror `ParallelPerspectiveReviewDispatcher`'s `asyncio.gather` composition
  (`code_review.py:392`) for the coordinator fan-out.
- Mirror `DevLoopWikiSearch.build_research_context`'s best-effort contract
  (`wiki_search.py:91`) — return `None` on any internal error, never raise.
- Read-only by **construction** (`dispatchers/nova.py:240`), not by flag.
- Async-first throughout; `aiohttp`, never `requests`/`httpx`; subprocesses via
  `asyncio.create_subprocess_exec`, never blocking `subprocess.run`.
- Google-style docstrings, strict type hints, Pydantic for all structured data,
  `self.logger` — never `print`.
- Commit `.research.md` staging **only** that path (SDD auto-commit rule).

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| **Path confinement is the real security surface** — a hosted model gets read access to a checkout | Resolve-then-contain with symlink checks; deny-by-default; byte and time bounds. This module gets the adversarial-review budget |
| Concurrent edits with FEAT-479 on `research.py`, `dispatchers/claude.py` | 11 tasks `in-progress`. Keep changes additive and minimal; coordinate before merge |
| `strict_mcp_config=False` looks like an easy path for Q11 | **Do not.** The field docstring records that inheriting the operator's connectors makes non-interactive runs exit with empty error results. Pass servers explicitly instead |
| Cancellation leaking subprocesses | `git`/grep children must be terminated on `asyncio.timeout`, verified by test |
| Structured-output parse failure degrading to a *passing* result | Deliberately **not** the `NovaAdversarialReviewDispatcher` pattern — there is no verdict here, so absence is absence: return `None` |
| Plane staleness inside a worktree | Accepted: the partner researches the codebase, not a diff. `git_*`/`read_file` cover uncommitted edits |
| Attribution drift (prompt-enforced) | `.research.md` sidecar is the structural backstop; finding `id`s make citation checkable |
| Findings too large for the dispatch payload | Truncate with an explicit marker; full text stays in `.research.md`, prompt points at the file |
| Nova 2 Lite may underperform on deep research | Model is config-driven (`DEV_FLOW_RESEARCH_PARTNER_MODEL`); §8 Q4 tracks the empirical comparison |
| Web search egress | **ON by default when the partner is enabled** (§8 Q5). Brief content reaches a third party — operators who cannot accept that set `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH=false`. Inert while the partner itself is disabled, so the pure-addition guarantee holds |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `boto3` / `aiobotocore` | existing | Bedrock Converse transport via `BedrockConverseBase` — no new dep |
| `pydantic` | existing | All contracts |
| `parrot.knowledge.wiki` | in-repo | Graph-backed `search_code` over the FTS5 plane |
| `ddgs` (via `parrot_tools.ddgsearch`) | existing | Keyless web search, default off |
| `tree-sitter*`, `ast` | existing / stdlib | Consumed transitively via the wiki plane; **not** direct deps |

**No new required dependency.** Feature is inert without AWS credentials.

### Configuration

| Key | Default | Purpose |
|---|---|---|
| `DEV_FLOW_RESEARCH_PARTNER` | `""` (disabled) | Backend selector; `"nova"` initially |
| `DEV_FLOW_RESEARCH_PARTNER_MODEL` | `us.amazon.nova-2-lite-v1:0` | Mirrors `DEV_LOOP_NOVA_REVIEW_MODEL` (`conf.py:1069`) |
| `DEV_FLOW_RESEARCH_PARTNER_THINKING_BUDGET` | `4096` | Converse `thinking_budget` (`bedrock.py:715`) |
| `DEV_FLOW_RESEARCH_PARTNER_TIMEOUT` | `600` | Hard deadline (seconds) |
| `DEV_FLOW_RESEARCH_PARTNER_MAX_TOKENS` | `16384` | Cost ceiling |
| `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH` | `true` | External egress; ON when the partner is enabled, independently switchable (§8 Q5) |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: after the FEAT-484 split this spec is six tightly-coupled modules —
  the partner contracts, the Nova implementation, the coordinator, and the two node
  seams all share the `ComplementaryFindings` contract. Splitting further would trade
  a short sequence for cross-worktree contract coordination. FEAT-484 already absorbed
  the one genuinely separable piece.
- **Cross-feature dependencies**:
  - **FEAT-484** (`readonly-repo-toolkit`) — **hard dependency**. Module 2
    (`NovaResearchPartner`) registers its toolkit. **FEAT-484 must merge first.**
    Modules 1, 5 and 6 do not depend on it and can proceed in parallel.
  - **FEAT-480** (`dev-flow-node-caching`) — **merged** (PR #1280, 7/7 done). No
    longer a constraint.
  - **FEAT-479** (`devflow-telemetry-accounting`) — **in progress**. Not a hard
    blocker (this spec touches no telemetry rendering), but Modules 4 and 5 edit two
    files FEAT-479 also edits (`nodes/research.py`, `dispatchers/claude.py`). Keep
    those edits strictly additive; **prefer merging after FEAT-479**.

```bash
git worktree add -b feat-482-devflow-complementary-research \
  .claude/worktrees/feat-482-devflow-complementary-research origin/dev
```

---

## 8. Open Questions

- [x] **Q1 — Where does `ReadOnlyRepoToolkit` live?** — *Resolved*: core
  `parrot/tools/repo/`. Core already owns `parrot.knowledge.wiki`, so there is no new
  cross-distribution dependency; a service-free reusable toolkit qualifies as base
  machinery. Reflected in §3 Module 1.
- [x] **Q3 — Sequencing against FEAT-479** — *Resolved*: emit `ClientRoundEvent`s
  only; modify no telemetry rendering. FEAT-479's ledger picks them up. Reflected in
  §1 Non-Goals, §2 Integration Points, §5.
- [x] **Q9 — Worktree plane strategy** — *Resolved*: share the main checkout's plane
  via absolute `storage_dir` (`wiki/project.py:74`); no per-worktree build. Partner
  sees ~last-commit state; `git_*`/`read_file` cover uncommitted edits. Reflected in
  §3 Module 2, §5, §7.
- [x] **Q10 — Vector leg?** — *Resolved*: lexical FTS5/BM25 only in this feature;
  conceptual-recall improvement is a follow-up. Measured basis: symbol/topic queries
  score 0.8–1.0, conceptual scored 0.06/0.00 with no embedder. Reflected in §1
  Non-Goals, §3 Module 2.
- [x] **Q11 — Graph search for the primary Claude seat too?** — *Resolved*: yes, both
  seats. Requires the new optional `mcp_servers` profile field (Module 5) because
  `strict_mcp_config` defaults `True` and there is no such field today.
- [x] **Q2 — Should the toolkit be its own capability/spec?** — *Resolved*: **yes**.
  Split into `sdd/specs/readonly-repo-toolkit.spec.md` (**FEAT-484**). It is
  independently valuable, independently reviewable, and carries this initiative's
  security weight. Reflected throughout §3 (Modules 1–2 removed, remaining modules
  renumbered), §4, §5 and Worktree Strategy.
- [x] **Q4 — `nova-2-lite` or Nova 2 Pro as the default model?** — *Resolved*: start
  on `us.amazon.nova-2-lite-v1:0`, **configurable** via
  `DEV_FLOW_RESEARCH_PARTNER_MODEL`. Note the basis for Lite is availability (the
  `us.anthropic.*` Bedrock use-case form), not measured sufficiency — re-evaluate
  against Pro after the first real runs.
- [x] **Q5 — Should `web_search` default on when the partner is enabled?** —
  *Resolved*: **yes, and configurable**. `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH`
  defaults to `true`; set `false` to disable. External prior art is the axis the
  Claude seat is weakest on, so a complementary researcher without it loses much of
  its point. Consequence accepted and documented in §7: brief content — which may
  describe unreleased work — reaches a third-party search provider. The key is inert
  while the partner itself is disabled, so the pure-addition guarantee is unaffected.
- [x] **Q6 — Should the partner ever see the human's HITL answers?** — *Resolved*:
  **no**. Round 1 only, confirming D8. If a human answer materially reframes the
  problem, Claude alone absorbs the reframing and the partner's findings stand as
  written. Reflected in §1 Non-Goals, §3 Module 4, §5.
- [x] **Q7 — Make attribution structural rather than prompt-enforced?** — *Resolved*:
  **prompt-enforced**. `ResearchFinding.id` (§2) keeps citation *checkable* and the
  `.research.md` sidecar remains the structural backstop, but the merged document is
  not machine-validated against finding ids. Reflected in §3 Module 6, §7.
- [x] **Q8 — Annotate `sdd/specs/novaclient-dev-loop.spec.md` (FEAT-405)?** —
  *Resolved*: **yes**. Its "pluggable research seat" non-goal gains a note recording
  the contribute-to vs. replace narrowing, so the two specs do not read as
  contradictory.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-31 | Jesus Lara | Initial draft from `devflow-complementary-research.brainstorm.md` (D1–D9 carried forward; Q1/Q9/Q10/Q11 resolved during scaffolding; Q3 decided against in-flight FEAT-479) |
| 0.2 | 2026-08-31 | Jesus Lara | All remaining open questions resolved. Q2: toolkit split out to FEAT-484 (`readonly-repo-toolkit`) — Modules 1–2 removed, 3–8 renumbered 1–6, toolkit tests and acceptance criteria moved. Q5: `web_search` now defaults ON when the partner is enabled. Q4/Q6/Q7/Q8 confirmed as specified. |
