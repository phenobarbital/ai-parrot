---
type: feature
base_branch: dev
projects: [ai-parrot-semantic, docs, ci]
tags: [semantic-layer, examples, agents, mcp-local, governance, duckdb]
---

# Feature Specification: Example agents for the governed Semantic Layer

**Feature ID**: FEAT-769
**Date**: 2026-10-29
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.3.0
**Source**: `sdd/proposals/semantic-layer-example.proposal.md` (accepted 2026-10-29)
**Research audit**: `sdd/state/FEAT-769/`

> **ID note**: drafted as FEAT-768; that number was reserved by a concurrent session
> (`sdd-claude-native-sandbox`, `b51434f7a`) mid-run, so FEAT-769 was reserved via
> `reserve_ids.py` and the proposal renumbered. There is no FEAT-768 artifact here.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-704 shipped the governed semantic layer (`packages/ai-parrot-semantic`) with four
surfaces, ten `sl_*` tools, a PBAC gate, RLS pushdown, column masking and an audit ledger.
It has exactly **one** example — `examples/semantic/agent_semantic_example.py` — and that
example:

- lives outside `examples/agents/`, where every other agent example lives;
- exercises **2 of the 10** `sl_*` tools (`query_metrics`, `save_result_as_dataset`);
- tells one story, the guarded dataset hand-off;
- **builds an `Agent` at line 314 and discards it** — `run_demo` drives the toolkit
  directly, so no example anywhere shows an LLM actually using the semantic tools.

That last point is not cosmetic. The governed tool path fail-closes unless the
`_permission_context` kwarg equals `current_pctx()` (`toolkit.py:110-116`), and that kwarg
arrives **only** through `AbstractBot.ask(permission_context=…)`. Direct method calls bypass
`_pre_execute` entirely. So the single most failure-prone integration detail of the whole
subsystem is demonstrated nowhere, and a developer copying the existing example into an
LLM-driven agent will hit `context_required` with no worked example to compare against.

Affected: **developers** adopting the semantic layer (no template for the LLM path, the
MCP-local path, masking, or saved queries), and **reviewers** (the doc asserts behaviours —
"exercise both an explicit allow and an explicit deny" — that no runnable example performs).

### Goals

- **G1.** Consolidate semantic examples under `examples/agents/semantic/`, consistent with
  the `a2ui/`, `aws/`, `finance/`, `oauth/`, `webbrowser/` layout.
- **G2.** Ship an example in which an **LLM really drives** the `sl_*` tools through
  `agent.ask(permission_context=…)`, proving the K2 binding end to end.
- **G3.** Ship an example of the **MCP-local** surface that executes a real allow **and** a
  real deny through `create_toolkit_mcp_server`, as the documentation demands.
- **G4.** Ship an example of **column masking + saved queries** — policy features supported
  in `policy.py` but demonstrated in no YAML outside unit tests.
- **G5.** Make the compile/governance split of **cross-model joins and time grains** explicit
  and correct (see §2 Overview — this is a loud-failure teaching example, not a join demo).
- **G6.** Every example runs deterministically offline (`--smoke`, no LLM, no network) and is
  gated by a pin test in `packages/ai-parrot-semantic/tests/`, which CI already runs.

### Non-Goals (explicitly out of scope)

- **Any change under `packages/ai-parrot-semantic/src/**`.** This feature adds no library
  functionality. In particular it does **not** add qualified-member authorization (§8 Q1).
- Fixing open `issue:3c4d154c0172` (S3: `_pre_execute` static-subject fallback not
  channel-scoped; S5: `save_result_as_dataset` member recheck).
- Refactoring the relocated example's internals. M1 is a **pure move**; extracting its
  helpers into the shared module is explicitly rejected (see §2 Overview, "Why `_common.py`
  does not absorb the moved example").
- The HTTP surface (`SemanticLayerHandler`, `handlers/semantic.py:18`) — no example.
- The OSSIE import format (`ossie.py:18-31`) — remains unit-test-only.
- Editing `.github/workflows/ci.yml`. The new pin tests land in
  `packages/ai-parrot-semantic/tests/`, which `ci.yml:536` already runs wholesale.

---

## 2. Architectural Design

### Overview

Seven modules. M1 relocates; M2 builds shared scaffolding; M3–M6 are the four examples;
M7 documents them.

**The central design constraint, discovered during design research and verified
empirically (S1):** the governed path **cannot authorize a cross-model join**.
`RoleCatalog.check_query_rights` (`catalog.py:59-73`) resolves the allowed-member set from
the **root model only**, via `policy.allowed_members(roles, loaded.members)`. Qualified join
members are not in the root model's member list:

```
orders.members   = [revenue, order_count, region, order_date]      # no customers.*
SemanticQuery(model="orders", dimensions=["customers.email"])
  → SemanticAccessError("member_not_granted")
     details={'member': 'customers.email', 'suggestions': ['order_date','order_count','revenue']}
```

This holds **even when the root policy grants `metrics:"*"` and `dimensions:"*"`**, because
`allowed_members` unions only over `loaded.members`. Meanwhile `engines/native.py` compiles
the join correctly (`test_native_extensions.py:87-92` asserts the exact `INNER JOIN
dim.customers …` SQL). So the compiler and the governance gate disagree by design.

**M6 is therefore re-scoped**: it is not a "multi-model join agent". It is the example that
makes this split explicit — the governed denial is *the lesson*, demonstrating precisely the
"fails loudly on out-of-scope questions instead of inventing a figure" property that FEAT-704's
motivation claims. M6 shows (a) governed time grains on a single model, which **do** work,
(b) the governed cross-model denial asserted as a denial, and (c) the same join compiling
under an explicitly `governed: false` model, clearly labelled as the compiler surface and not
a governance bypass. §8 Q1 records the alternative (add qualified-member authorization to the
library) as a deliberate non-goal of this feature.

**Why `_common.py` does not absorb the moved example.** M2 adds shared scaffolding (PBAC
evaluator, identity factory, warehouse builder, `connection_env`) for the *new* examples only.
The relocated example keeps its own private copies. Rationale: `test_example_agent.py`
asserts on the moved file's **source text** (`:77-83` requires the literal `"_pbac.available"`
to be absent), and `ef85c503` already rewrote 173 of its 261 lines once after review
`issue:f0da823294fb`. Keeping M1 a byte-identical move makes the relocation auditable in one
glance and keeps the blast radius at two reference edits. The duplication is deliberate and
documented.

**Policy side-files are per model, not per document (S2).** `loader.py:111-114` raises
`missing_policy` for **every** model name in a document. A two-model `orders.yml` therefore
requires both `orders.policy.yaml` and `customers.policy.yaml`. (The repo's own fixture dir
ships only `orders.policy.yaml`; `tests/_models.py:16-23` writes the second one at runtime.)
M2's committed fixture ships both files explicitly.

### Component Diagram

```
examples/agents/semantic/
├── agent_semantic_example.py     M1  (moved verbatim from examples/semantic/)
├── _common.py                    M2  evaluator · guard · identity · warehouse · connection_env
├── models/                       M2  committed YAML: orders.yml + orders.policy.yaml
│                                     + customers.policy.yaml  (one policy PER MODEL)
├── llm_metrics_agent.py          M3  LLM drives sl_* via ask(permission_context=…)
├── mcp_local_agent.py            M4  create_toolkit_mcp_server: real allow + real deny
├── masked_policy_agent.py        M5  masks: + saved_queries:
├── governed_joins_agent.py       M6  grains OK · governed join DENIED · ungoverned compile
└── README.md                     M7

packages/ai-parrot-semantic/tests/
├── test_example_agent.py         M1  one line: _EXAMPLE_PATH gains "agents"
├── test_example_llm_metrics.py   M3
├── test_example_mcp_local.py     M4
├── test_example_masked_policy.py M5
└── test_example_governed_joins.py M6

docs/tools/semantic-layer.md      M7  prose-only section (fences are an API — S6)
```

### Integration Points

| Integration | Contract | Evidence |
|---|---|---|
| `SemanticLayerToolkit(**kwargs)` | kwargs-only; `models_dir`, `dialect` required; `dataplane_guard` required for governed models | `toolkit.py:44-79` |
| `agent.ask(permission_context=ctx)` | the only path that populates `_permission_context` | `base.py:1083,1439-1440,2095-2096` → `manager.py:2174` → `toolkit.py:178` |
| `bind_semantic_context(ctx, identity=…)` | async context manager; must wrap the `ask()` call | `context.py:86-88` |
| `create_toolkit_mcp_server` | the supported MCP-local path, owns the toolkit | `toolkit_server.py`, used by `test_mcp_local.py:18` |
| `SemanticModelLoader(models_dir, driver=…)` | one `<model>.policy.yaml` per model, else `missing_policy` | `loader.py:111-114` |
| CI | `uv sync --all-packages --extra duckdb` + pytest on the semantic tests | `ci.yml:535-536` |

### Data Models

No new Pydantic models. The examples consume existing ones verbatim:
`SemanticQuery` (`models.py:102`, `extra="forbid"`), `TimeDimension` (`models.py:33`,
grain mandatory), `FilterGroup`/`FilterLeaf` (`models.py:79,47`), `StaticSubject`
(`bootstrap.py:23`), `SemanticRequestIdentity` (`context.py:18`), `MaskRule`
(`policy.py:36`), `SavedQuery` (`policy.py:46`).

### New Public Interfaces

None. This feature adds no importable library surface; `examples/` is not packaged
(`packages/ai-parrot-semantic/pyproject.toml:21-27` includes only `parrot*` under `src`).

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Relocate | yes | `git mv` two files; one-line edit at `test_example_agent.py:21`; one-line edit at `README.md:3` | — |
| M2: Shared scaffolding + fixtures | yes | signatures below; YAML mirrors `tests/fixtures/models/orders.yml` + one policy per model | — |
| M3: LLM-driven example | yes | `--smoke` provider-free; pin test drives `ask(permission_context=)`; denial asserted | — |
| M4: MCP-local example | yes | via `create_toolkit_mcp_server`; allow **and** deny both executed and asserted | — |
| M5: Masking + saved queries | yes | `MaskRule`/`SavedQuery` field sets fixed; assert exact masked output | — |
| M6: Grains + governed-join denial | **no** | The *behaviour* is verified, but whether M6 ships the `governed: false` compile leg is §8 Q1 | Pending the Q1 decision |
| M7: README + docs section | yes | prose-only in `docs/`; no new fenced yaml/json block | — |

### Module 1: Relocate the existing example
- **Path**: `examples/agents/semantic/agent_semantic_example.py`, `examples/agents/semantic/README.md`
- **Responsibility**: Move both files from `examples/semantic/` **verbatim**; fix the two live references.
- **Depends on**: nothing (must land first — M2–M7 live in the directory it creates)
- **Interface Skeleton**:
  ```python
  # examples/agents/semantic/agent_semantic_example.py  (moved from examples/semantic/, content UNCHANGED)
  # packages/ai-parrot-semantic/tests/test_example_agent.py:21  (modifies)
  _EXAMPLE_PATH = (
      Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "agent_semantic_example.py"
  )  # verified: packages/ai-parrot-semantic/tests/test_example_agent.py:21
  ```

### Module 2: Shared scaffolding and committed fixtures
- **Path**: `examples/agents/semantic/_common.py`, `examples/agents/semantic/models/{orders.yml,orders.policy.yaml,customers.policy.yaml}`
- **Responsibility**: One PBAC evaluator, guard builder, identity factory, DuckDB warehouse builder and `connection_env` shared by M3–M6; and the committed model/policy fixtures.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # examples/agents/semantic/_common.py  (new)
  MODELS_DIR: Path          # Path(__file__).parent / "models"
  CONNECTION_ENV: str       # "PARROT_SEMANTIC_CONN_SEMANTIC_EXAMPLE_DATABASE"

  class ExamplePolicyEvaluator:
      """Explicit allow-list PBAC evaluator plugged into the real DataPlanePolicyGuard."""
      def __init__(self, *, allowed_role: str = "analyst") -> None: ...
      def revoke(self) -> None: ...
      def check_access(self, eval_ctx, resource_type: str, resource: str, action: str, env) -> SimpleNamespace: ...
      def filter_resources(self, eval_ctx, resource_type: str, resources: list[str], action: str, env) -> SimpleNamespace: ...

  def build_guard(evaluator: ExamplePolicyEvaluator, rls_registry: RlsRegistry) -> DataPlanePolicyGuard:
      """Core data-plane guard around the example evaluator."""   # verified: parrot/auth DataPlanePolicyGuard

  def build_warehouse(directory: Path) -> Path:
      """Create a deterministic DuckDB warehouse with sales.orders and dim.customers."""

  @contextmanager
  def connection_env(warehouse: Path) -> Iterator[None]:
      """Bind CONNECTION_ENV for the enclosed block and restore it on exit."""

  def example_identity(user_id: str, session_id: str, program: str, *, roles: frozenset[str] = frozenset({"analyst"})) -> SemanticRequestIdentity:
      """Trusted fixture identity."""   # SemanticRequestIdentity verified: context.py:18

  def build_toolkit(warehouse: Path, *, evaluator=None, **extra) -> SemanticLayerToolkit:
      """SemanticLayerToolkit over MODELS_DIR with a real guard."""   # verified: toolkit.py:44
  ```

### Module 3: LLM-driven catalog→query agent  *(fills the G2 gap)*
- **Path**: `examples/agents/semantic/llm_metrics_agent.py`, `packages/ai-parrot-semantic/tests/test_example_llm_metrics.py`
- **Responsibility**: An `Agent` whose LLM selects and calls `sl_list_models` → `sl_get_dimensions` → `sl_query_metrics`, dispatched through `agent.ask(question, permission_context=ctx)` inside `bind_semantic_context`. `--smoke` runs the same tool sequence deterministically with **no provider initialized**.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # examples/agents/semantic/llm_metrics_agent.py  (new)
  SYSTEM_PROMPT: str

  def build_agent(toolkit: SemanticLayerToolkit) -> Agent:
      """Agent exposing only the sl_* tools."""   # Agent(name=, system_prompt=, tools=) verified: examples/agents/finance/hooba_agent.py:67-71

  async def smoke(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> dict[str, Any]:
      """Deterministic catalog->query walk with no LLM and no network."""

  async def ask_llm(agent: Agent, question: str, identity: SemanticRequestIdentity) -> Any:
      """Drive the tools through the real governed dispatch path.

      Wraps bind_semantic_context(identity.ctx, identity=identity) around
      agent.ask(question, permission_context=identity.ctx); omitting either
      raises SemanticAccessError('context_required').
      """   # verified: context.py:86-88, base.py:1083, toolkit.py:110-116

  async def main() -> None: ...   # argparse: --smoke | question ; asyncio.run(main())
  ```

### Module 4: MCP-local allow + deny example
- **Path**: `examples/agents/semantic/mcp_local_agent.py`, `packages/ai-parrot-semantic/tests/test_example_mcp_local.py`
- **Responsibility**: Build a temporary toolkit config, start the toolkit MCP server through `create_toolkit_mcp_server`, and execute one **allow** and one **deny** against the real server factory, asserting `SemanticAccessError` on the deny.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # examples/agents/semantic/mcp_local_agent.py  (new)
  def write_toolkit_config(directory: Path, *, models: Path, policy_dir: Path, factory: str) -> Path:
      """Write a .parrot/mcp-toolkits.yaml equivalent for the local run."""

  async def run_decision(config: Path, *, allow: bool) -> Any:
      """Execute one governed call through the owned MCP toolkit.

      Returns the tool result when allowed; raises SemanticAccessError when denied.
      """   # create_toolkit_mcp_server verified: packages/ai-parrot/src/parrot/mcp/toolkit_server.py (used at test_mcp_local.py:18)

  async def smoke() -> dict[str, Any]:
      """Run both the allow and the deny decision; no LLM."""
  ```
  > `LocalSemanticLayerToolkit` requires `navigator_auth.abac.policies.{evaluator,environment}`
  > or raises `SemanticPolicyError("pbac_unavailable")` (`bootstrap.py:118-126`). Both import in
  > the workspace venv; the pin test still guards with `importorskip` (§4).

### Module 5: Masking and saved-queries example
- **Path**: `examples/agents/semantic/masked_policy_agent.py`, `packages/ai-parrot-semantic/tests/test_example_masked_policy.py`
- **Responsibility**: A policy carrying `masks:` and `saved_queries:`; run a query whose projection is masked and a `saved_query` expansion, asserting the **exact** masked output.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # examples/agents/semantic/masked_policy_agent.py  (new)
  async def run_masked_query(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> SemanticQueryResult:
      """Project a masked column and return the governed result."""   # MaskRule verified: policy.py:36-43

  async def run_saved_query(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> SemanticQueryResult:
      """Execute SemanticQuery(model=..., saved_query=...)."""
      # SavedQuery{name, query, verified_by, verified_at, description} verified: policy.py:46-52
      # saved_query is exclusive with explicit members  verified: models.py:124-127
  ```

### Module 6: Time grains and the governed-join denial  *(re-scoped — S1)*
- **Path**: `examples/agents/semantic/governed_joins_agent.py`, `packages/ai-parrot-semantic/tests/test_example_governed_joins.py`
- **Responsibility**: (a) a governed `time_dimensions` query with an explicit grain — works; (b) a governed cross-model query — **asserted to raise** `member_not_granted`; (c) the same join compiling under an explicitly `governed: false` model, labelled as the compiler surface. Not a "joins work" example.
- **Depends on**: M2; **gated on §8 Q1** for whether leg (c) ships.
- **Interface Skeleton**:
  ```python
  # examples/agents/semantic/governed_joins_agent.py  (new)
  async def run_time_grain(toolkit, identity) -> SemanticQueryResult:
      """Governed query over a time dimension with an explicit grain."""
      # TimeDimension(name=..., grain=...) — grain mandatory, verified: models.py:38-43

  async def show_governed_join_denial(toolkit, identity) -> SemanticAccessError:
      """Return the member_not_granted error a cross-model query raises.

      Raises RuntimeError if the query unexpectedly succeeds.
      """   # verified: catalog.py:59-73 (allowed set comes from the ROOT model only)

  async def compile_ungoverned_join(directory: Path) -> str:
      """Compile the same join under an explicitly governed: false model."""
      # governed:false short-circuits check_query_rights  verified: catalog.py:64-65
  ```

### Module 7: README and documentation
- **Path**: `examples/agents/semantic/README.md`, `docs/tools/semantic-layer.md`
- **Responsibility**: Per-directory README (merging the moved one, preserving its
  "For production, replace…" paragraph); plus a **prose-only** section in the doc.
- **Depends on**: M3–M6
- **Interface Skeleton**: documentation only — no code. See §7 for the exact fence prohibition.

---

## 4. Test Specification

### Unit Tests

None. Examples are integration-shaped by nature; each is covered by a pin test below.

### Integration Tests

| Test file | Module | What it pins |
|---|---|---|
| `test_example_agent.py` *(existing, 1-line edit)* | M1 | the moved path still imports and behaves identically |
| `test_example_llm_metrics.py` | M3 | `--smoke` is provider-free; `ask(permission_context=)` dispatch reaches a tool; missing/mismatched binding fails closed |
| `test_example_mcp_local.py` | M4 | a real allow returns a result **and** a real deny raises `SemanticAccessError` |
| `test_example_masked_policy.py` | M5 | the exact masked projection; `saved_query` expansion |
| `test_example_governed_joins.py` | M6 | grain query succeeds; cross-model query raises `member_not_granted`; ungoverned compile produces the join |

Every pin test: `pytest.importorskip("duckdb")`, loads the example by absolute path with
`importlib.util.spec_from_file_location` (the `test_example_agent.py:26-37` precedent), and
**asserts denials rather than logging them** (S8) — if a denial silently succeeds, the test fails.
No pin test may initialize or call an LLM provider (S3).

### Validation Contract

tests:
- packages/ai-parrot-semantic/tests/test_example_agent.py
- packages/ai-parrot-semantic/tests/test_example_llm_metrics.py
- packages/ai-parrot-semantic/tests/test_example_mcp_local.py
- packages/ai-parrot-semantic/tests/test_example_masked_policy.py
- packages/ai-parrot-semantic/tests/test_example_governed_joins.py
- packages/ai-parrot-semantic/tests/test_mcp_local.py
- packages/ai-parrot-semantic/tests/test_loader.py
- packages/ai-parrot-semantic/tests/test_catalog.py
markers: none

### Test Data / Fixtures

Committed under `examples/agents/semantic/models/` (M2), mirroring
`packages/ai-parrot-semantic/tests/fixtures/models/orders.yml`:

- `orders.yml` — two models: `customers` (`dim.customers`) with a `one_to_many` relationship
  to `orders`, and `orders` (`sales.orders`) with a `time` dimension `order_date`
  (`grain: month`) and metrics `revenue` (sum) / `order_count` (count).
- `orders.policy.yaml` — `governed: true`, `connection: semantic_example`, an `analyst` role,
  one duckdb RLS rule, plus the `masks:` and `saved_queries:` M5 needs.
- `customers.policy.yaml` — **required** by `loader.py:111-114`; one policy per model (S2).

The DuckDB warehouse is built at runtime by `_common.build_warehouse` into a
`tempfile.TemporaryDirectory`; nothing is written under the working directory.

---

## 5. Acceptance Criteria

- [ ] **AC1** `examples/agents/semantic/agent_semantic_example.py` is byte-identical to the
  file previously at `examples/semantic/`; `git log --follow` traces the move; `examples/semantic/` no longer exists.
- [ ] **AC2** The only edits outside `examples/agents/semantic/`, the new tests and the docs are
  `test_example_agent.py:21` and the relocated README's run command.
- [ ] **AC3** Every example runs offline with `--smoke`: no LLM call, no network, no write
  outside a temporary directory, and `CONNECTION_ENV` is restored on exit.
- [ ] **AC4** The M3 pin test drives at least one `sl_*` tool through
  `agent.ask(question, permission_context=ctx)` under `bind_semantic_context`, and asserts
  that omitting either binding raises `SemanticAccessError("context_required")`.
- [ ] **AC5** The M4 pin test executes an allow **and** a deny through `create_toolkit_mcp_server`
  and asserts `SemanticAccessError` on the deny.
- [ ] **AC6** No example or pin test initializes an LLM provider in its deterministic path.
- [ ] **AC7** Every example that demonstrates a denial fails its pin test if the denial
  silently succeeds (the `test_example_agent.py:199-215` pattern).
- [ ] **AC8** `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py` still passes after
  the M7 doc edit — i.e. no new fenced block matches a uniqueness selector.
- [ ] **AC9** `ruff check examples/agents/semantic packages/ai-parrot-semantic/tests` is clean
  (only `F401,F841,E402` are waived for examples; line-length 120).
- [ ] **AC10** No new file under `examples/` is named `test_*.py`.
- [ ] **AC11** The committed fixture loads through `SemanticModelLoader` with one policy
  side-file per model (no `missing_policy`).
- [ ] **AC12** M6 asserts the governed cross-model denial; no example presents a cross-model
  join as a working governed query, and none presents `reload()` as a way to drop an RLS rule.

---

## 6. Codebase Contract

> Verified against `86e9e37f5` (2026-10-29). 54 of 57 proposal citations were probe-verified
> at `7e6741f13`; the signatures below were re-read from source for this spec.

### Verified Imports

```python
from parrot.semantic.toolkit import SemanticLayerToolkit          # toolkit.py:38
from parrot.semantic.models import SemanticQuery, SemanticQueryResult, TimeDimension, FilterGroup, FilterLeaf, OrderBy
                                                                  # models.py:102,217,33,79,47,96
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context, require_identity, current_pctx
                                                                  # context.py:18,86,62,44
from parrot.semantic.errors import SemanticAccessError, SemanticPolicyError, SemanticResultError
from parrot.semantic.handoff import GovernedDatasetSink, ReadAuthorizer, handle_owner   # handoff.py:34,—,46
from parrot.semantic.results import ResultHandle                  # results.py:23
from parrot.semantic.bootstrap import LocalSemanticLayerToolkit, StaticSubject          # bootstrap.py:60,23
from parrot.semantic.loader import SemanticModelLoader            # loader.py
from parrot.semantic.catalog import RoleCatalog                   # catalog.py:15
from parrot.auth import DataPlanePolicyGuard, PermissionContext, RlsRegistry, UserSession
from parrot.bots import Agent
from parrot.mcp.toolkit_server import create_toolkit_mcp_server   # used at test_mcp_local.py:18
```

> `parrot.semantic.__init__` exports only `__version__, SemanticQuery, SemanticQueryResult,
> SemanticLayerToolkit` (`__init__.py:7`) — everything else **must** come from its submodule.

### Existing Class Signatures

```python
# packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py
class SemanticLayerToolkit(AbstractToolkit):              # :38
    tool_prefix = "sl"                                    # :41
    exclude_tools = ("reload",)                           # :42
    def __init__(self, **kwargs: Any) -> None: ...        # :44  kwargs-only
    # pops: models_dir, dialect, dataplane_guard, rls_registry, database_toolkit, signer,
    #       audit_storage, static_subject, result_ttl_s=900, result_store_max=256,
    #       allowed_functions=(), audit_required=None, allow_raw_sql=False,
    #       dataset_manager_factory
    # raises: static_subject_forbidden :67 · invalid_allow_raw_sql :70 ·
    #         invalid_sink_factory :72 · guard_required :79
    async def list_models(self) -> list[dict]: ...                                           # :123
    async def list_metrics(self, model: str) -> list[dict]: ...                              # :138
    async def get_dimensions(self, model: str, metrics: list[str] | None = None) -> list[dict]: ...  # :147
    async def get_dimension_values(self, model: str, dimension: str,
                                   metrics: list[str] | None = None, limit: int = 50) -> SemanticQueryResult: ...  # :158
    async def search_data_model(self, text: str, model: str | None = None) -> list[dict]: ...  # :165
    async def list_saved_queries(self, model: str) -> list[dict]: ...                        # :183
    async def compile_query(self, query: SemanticQuery) -> dict: ...                         # :195  PRE-RLS SQL
    async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult: ...          # :200
    async def run_sql(self, model: str, sql: str) -> SemanticQueryResult: ...                # :451  hidden unless allow_raw_sql
    async def save_result_as_dataset(self, result_id: str, name: str,
                                     description: str | None = None) -> dict: ...            # :546  hidden without a sink factory
    async def _pre_execute(self, tool_name, /, **kwargs) -> None: ...                        # :105  fail-closed

# packages/ai-parrot-semantic/src/parrot/semantic/context.py
class SemanticRequestIdentity(BaseModel, frozen=True):    # :18   fields: ctx, channel, agent_id, session_id
def current_pctx() -> PermissionContext | None: ...       # :44
def require_identity() -> SemanticRequestIdentity: ...    # :62
async def bind_semantic_context(ctx: PermissionContext, *,
    identity: SemanticRequestIdentity | None = None) -> AsyncIterator[None]: ...   # :86  @asynccontextmanager

# packages/ai-parrot-semantic/src/parrot/semantic/models.py
class SemanticQuery(BaseModel):                           # :102   model_config = ConfigDict(extra="forbid")  :105
    model: str; metrics: list[str]; dimensions: list[str]; time_dimensions: list[TimeDimension]
    filters: FilterGroup | None; order_by: list[OrderBy]; limit: int | None; offset: int
    timezone: str | None; saved_query: str | None
class TimeDimension(BaseModel):                           # :33    name, grain, date_range; grain MANDATORY :38-43

# packages/ai-parrot-semantic/src/parrot/semantic/policy.py
class RoleGrant(BaseModel):   metrics / dimensions / usage: list[str] | Literal["*"]    # :26-35
class MaskRule(BaseModel):    strategy: Literal["null","hash","partial"]; projection_roles; usage_roles  # :36-43
class SavedQuery(BaseModel):  name; query: SemanticQuery; verified_by; verified_at: date; description    # :46-52
class ModelPolicy(BaseModel): governed, connection, limits, roles, masks, rls, saved_queries, allowed_functions  # :57-69

# packages/ai-parrot-semantic/src/parrot/semantic/catalog.py
class RoleCatalog:                                        # :15
    def visible_members(self, model, roles, *, authorized: bool) -> list[ModelMember]: ...   # :26
    def check_query_rights(self, query: SemanticQuery, roles: frozenset[str]) -> None: ...   # :50
        # allowed set comes from the ROOT model only (:66) — qualified join members are never granted

# packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py
class StaticSubject(BaseModel): user_id; tenant_id; roles: list[str]; metadata                # :23
class LocalSemanticLayerToolkit(SemanticLayerToolkit):                                          # :60
    def __init__(self, *, static_subject, agent_id: str, guard_factory: str,
                 guard_factory_kwargs: dict | None = None, **kwargs) -> None: ...               # :65-72
    # _require_evaluator_modules() raises pbac_unavailable without navigator_auth.abac.policies.*  :118-126

# packages/ai-parrot/src/parrot/bots/base.py
async def ask(self, question: str, ..., permission_context: Optional[Any] = None, ...) -> AIMessage: ...  # :1069-1093
```

### Integration Points

- `base.py:1439-1440` and `:2095-2096` set `client._permission_context` from `ask(permission_context=…)`.
- `manager.py:2174` sets `exec_kwargs["_permission_context"]`.
- `toolkit.py:178` injects it into the `_pre_execute` hook kwargs.
- `toolkit.py:110-116` compares it to `current_pctx()` and raises `context_required` on mismatch.
- `loader.py:111-114` requires `<model>.policy.yaml` per model.
- `test_mcp_local.py:38-47,66,81,88-90,97-98` parse `docs/tools/semantic-layer.md`'s fences.

### Does NOT Exist (Anti-Hallucination)

- **`examples/agents/semantic/`** — the target directory (probe `c42`).
- **Qualified-member authorization.** There is no policy key, no `RoleGrant` field and no
  catalog path that grants `customers.email` to a query rooted at `orders`. Do **not** invent
  `qualified_members:`, `joined_members:`, or a `models:` list in `RoleGrant` — `RoleGrant` is
  `extra="forbid"` (`policy.py:28`).
- **`customers.policy.yaml` in the committed fixture dir** — only `orders.yml` and
  `orders.policy.yaml` exist today; `tests/_models.py:16-23` writes the second at runtime.
- **An `unregister`/`remove` API on `RlsRegistry`** — `reload()` cannot drop a rule.
- **A `Chatbot`/`Agent` kwarg named `semantic_toolkit`** — tools are passed via `tools=[...]`.
- **`parrot.semantic.SemanticRequestIdentity`** — not exported from the package root.
- No example, fixture or test named `test_*.py` under `examples/`.

### Edit Sites (Blueprint Anchors)

<!-- Verified against: 86e9e37f5 -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-semantic/tests/test_example_agent.py` | MODIFY | `_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "semantic" / "agent_semantic_example.py"` | `test_example_agent.py:21` | 1 |
| `examples/semantic/agent_semantic_example.py` | MOVE | — (content unchanged) | — | — |
| `examples/semantic/README.md` | MOVE+MODIFY | ``Run `python examples/semantic/agent_semantic_example.py` with the DuckDB extra.`` | `README.md:3` | 1 |
| `docs/tools/semantic-layer.md` | MODIFY | `## MCP-local configuration` | `semantic-layer.md:114` | 1 |
| `examples/agents/semantic/_common.py` | CREATE | — | — | — |
| `examples/agents/semantic/models/orders.yml` | CREATE | — | — | — |
| `examples/agents/semantic/models/orders.policy.yaml` | CREATE | — | — | — |
| `examples/agents/semantic/models/customers.policy.yaml` | CREATE | — | — | — |
| `examples/agents/semantic/llm_metrics_agent.py` | CREATE | — | — | — |
| `examples/agents/semantic/mcp_local_agent.py` | CREATE | — | — | — |
| `examples/agents/semantic/masked_policy_agent.py` | CREATE | — | — | — |
| `examples/agents/semantic/governed_joins_agent.py` | CREATE | — | — | — |
| `examples/agents/semantic/README.md` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/test_example_llm_metrics.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/test_example_mcp_local.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/test_example_masked_policy.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/test_example_governed_joins.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`examples/agents/finance/hooba_agent.py` is the template**: `Usage::` docstring (`:3-6`),
  module-level `SYSTEM_PROMPT` (`:22`), `build_*` factories (`:28`), `argparse` with `--smoke`
  (`:44`), `asyncio.run(main())` (`:78`). Not `examples/basic_agent.py` (bare `print`).
- **Quality bar of the relocated example**: full type hints, Google-style docstrings,
  `logging` via a module `LOGGER`, no `print` except a final result summary.
- Reuse `connection_env()` rather than mutating `os.environ` — `test_build_toolkits_does_not_mutate_environment`
  pins that the environment is restored.
- Load examples in tests by absolute path with `importlib.util.spec_from_file_location`
  (`test_example_agent.py:26-37`), registering and popping `sys.modules[spec.name]`.

### Known Risks / Gotchas

- **The documentation's fences are an API (S6).** `test_mcp_local.py` asserts **exactly one**
  yaml block with top-level key `toolkits`, **exactly one** starting `# orders.yml`, and
  **exactly one** starting `# orders.policy.yaml`; and every ```json block must parse with the
  `mcpServers` list equal to exactly one entry. The M7 section must therefore add **no** yaml
  or json fence — prose, plus a ```bash fence if needed (bash is unconstrained).
- **`examples/` is pytest-collected.** No `testpaths`/`norecursedirs` in `pytest.ini`, no root
  `collect_ignore`; five `test_*.py` files already sit in `examples/agents/`. Never use that prefix.
- **ruff bites examples.** Only `F401,F841,E402` are waived (`ruff.toml:152`); `TID251`, `B`,
  `ASYNC`, `PIE`, `C4`, `LOG` apply at line-length 120.
- **`compile_query` returns PRE-RLS SQL** (closed `issue:22fbd14d96a9`). Never label it
  "the SQL as executed"; governed SQL lives only in the audit record.
- **`reload()` cannot drop an RLS rule** (S9, closed `issue:e3ff9bfb4a83`). Use a fresh toolkit
  instance for a changed policy snapshot.
- **Usage rights are narrower than the moved example implies** (closed `issue:9a4e4c35b032`):
  they restrict only masked / `sensitive: true` members. Do not copy its broad `usage:` list as "required".
- **`issue:f0da823294fb` regression classes.** Four new examples are four new chances to
  re-introduce a placeholder PBAC guard, an env leak, a weak owner check, or a denial that is
  logged rather than asserted. AC6/AC7 exist to catch exactly these.
- **Importing `navigator_auth` emits Navigator DEBUG output and reads `settings/`** — expected
  noise in the M4 example; do not "fix" it by stubbing the evaluator modules.
- **`SemanticQuery` and `RoleGrant`/`MaskRule`/`SavedQuery` are all `extra="forbid"`.** A guessed
  field name is a hard validation error, not a warning.

### External Dependencies

| Dependency | Why | Already present? |
|---|---|---|
| `duckdb>=1.0` | the examples' warehouse | yes — `packages/ai-parrot-semantic/pyproject.toml:15`, installed by `ci.yml:535` |
| `navigator-auth` | `LocalSemanticLayerToolkit` evaluator modules (M4) | yes — importable in the workspace venv |

No new dependency is added.

---

## 8. Open Questions

- [ ] **Q1 — Should M6 ship the `governed: false` compile leg, or stop at the denial?**
  *Owner*: Jesus Lara. Design research S1 (verified) proved the governed path cannot authorize
  a cross-model join. Options: **a)** show grains + the governed denial only; **b)** also show
  the same join compiling under an explicitly `governed: false` model, labelled as the compiler
  surface; **c)** drop M6 and file a ledger issue proposing qualified-member authorization in
  the library. §2 currently assumes (b). Adding qualified-member authorization is a §1 non-goal
  either way.
- [ ] **Q2 — Sequencing (S10).** Ship M1+M2+M3+M4 as one PR and M5+M6 as a follow-up, or all
  seven at once? *Owner*: tbd. M6 is the only module gated on Q1, so a split keeps the first PR unblocked.
- [ ] **Q3 — Does the committed fixture need a second connection** so M6 can also show a
  cross-connection refusal, or does one DuckDB connection cover all four examples? *Owner*: spec author.

### Resolved

- [x] **Where do the examples live?** — *Resolved in proposal*: **move + extend** — relocate
  `examples/semantic/*` into `examples/agents/semantic/` and add the new examples beside it.
- [x] **Which examples?** — *Resolved in proposal*: all four — LLM-driven catalog→query,
  MCP-local allow+deny, masking/`saved_queries`, multi-model joins + grains (the last
  re-scoped by S1, see Q1).
- [x] **Runnability and gating?** — *Resolved in proposal*: deterministic `--smoke` default with
  the LLM path opt-in, plus a pin test per example in `packages/ai-parrot-semantic/tests/`; DuckDB-only.
- [x] **Docs placement and YAML location?** — *Resolved in proposal*: a section in
  `docs/tools/semantic-layer.md` **and** an `examples/agents/semantic/README.md`; one committed
  model+policy fixture set. *Refined here*: the docs section must be **prose-only** (S6), and the
  fixture needs **one policy file per model** (S2), not a single pair.
- [x] **Does `test_mcp_local.py`'s parser tolerate an added fenced block?** — *Resolved during
  this spec's research*: **no** for yaml/json matching a uniqueness selector; see §7. This was
  the proposal's first unresolved question.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted proposal** (never over
> this spec). Model: `gpt-5.6-luna` · codex-cli 0.164.0 · Status: **completed** · Transcript:
> `sdd/state/FEAT-769/design_research/`
> Every `affected_paths` entry passed containment + `test -e`. S1 and S2 were re-verified
> empirically before adoption.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Re-scope the multi-model example or add qualified-member authorization (architecture) | CONFIRM | Verified empirically: `orders.members` excludes qualified join members, so `check_query_rights` denies `customers.email` **even under `"*"` grants**, while `native.py` compiles the join | §2 Overview, §3 M6, §7, §8 Q1 |
| S2 | Provide a policy side-file for every model (architecture) | CONFIRM | `loader.py:111-114` raises `missing_policy` per model; reviewer's fixture detail imprecise — `tests/_models.py:16-23` writes it at runtime | §3 M2, §4, §6 |
| S3 | Make the LLM path opt-in, smoke provider-free (testing) | CONFIRM | `ci.yml:535-536` supplies no LLM credentials | §3 M3, §5 AC6 |
| S4 | Pin the real `ask(permission_context=...)` dispatch (testing) | CONFIRM | Chain verified `base.py:1083` → `manager.py:2174` → `toolkit.py:178` → `_pre_execute` | §3 M3, §5 AC4 |
| S5 | Build the MCP example through the real server factory (api) | CONFIRM | `create_toolkit_mcp_server` is what `test_mcp_local.py:18` drives | §3 M4, §5 AC5 |
| S6 | Treat the documentation fences as an API (risk) | CONFIRM (refined) | Verified the exact selectors and the json `mcpServers` equality assertion | §3 M7, §7, §5 AC8 |
| S7 | Validate mask and saved-query fixtures through the real loader (api) | CONFIRM | `MaskRule`/`SavedQuery` are `extra="forbid"`; `TimeDimension` requires a grain | §3 M5, §4, §6 |
| S8 | Require observable denial assertions in every example pin (testing) | CONFIRM | Matches `test_example_agent.py:199-215` | §4, §5 AC7 |
| S9 | Do not demonstrate RLS removal through `reload()` (risk) | CONFIRM | Independently known (closed `issue:e3ff9bfb4a83`) | §7 |
| S10 | Sequence the deliverable around the join blocker (alternative) | CONFIRM | Answers the proposal's sequencing question | §3 ordering, §8 Q2 |

Summary: **10** confirmed · **0** rejected · **1** escalated to §8 (the M6 re-scope, from S1).

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-769 (`feat-FEAT-769-semantic-layer-example`,
  from `origin/dev`). The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - `M2 → M1` — M2's files live in the directory M1 creates.
  - `M3, M4, M5, M6 → M2` — all four import `_common` and load `models/`.
  - `M7 → M3, M4, M5, M6` — the README documents all four.
  - **M3, M4, M5 and M6 have no edges between them and are expected to run concurrently.**
- **Shared files**: `examples/agents/semantic/_common.py` and `models/` are written once by M2
  and read-only thereafter. `examples/agents/semantic/README.md` is written only by M7.
  No two of M3–M6 touch the same file.
- **Exclusive resources**: M7 modifies `docs/tools/semantic-layer.md`, which
  `test_mcp_local.py` parses — its task is `parallel: false`. M1 modifies
  `test_example_agent.py` and must complete before any other task runs.
- **Cross-feature dependencies**: none. `origin/feat-FEAT-704-semantic-layer` is 0 commits
  ahead of `origin/dev` and carries no `examples/` delta.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-29 | Jesus Lara | Initial draft from the accepted FEAT-769 proposal; M6 re-scoped after design-research S1 was verified empirically |
