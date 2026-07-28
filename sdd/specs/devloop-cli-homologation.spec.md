---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: `parrot devloop` CLI Homologation — feature-mode wizard, free-text intake, multi-backend dev pool

**Feature ID**: FEAT-388
**Date**: 2026-07-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x
**Brainstorm**: `sdd/proposals/devloop-cli-homologation.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev-loop web console (`examples/dev_loop/server.py`, FEAT-378) has grown
capabilities the CLI (`parrot devloop`) does not expose:

1. **Multi-backend development dispatch** — the web form collects dev-agent
   rows (`DevAgentSpec[]`: backend + model + count) across all
   `DevAgentBackend`s (claude-code, codex, gemini, nvidia, grok, zai,
   moonshot, and the in-flight `agy`/Antigravity), rendered from the
   `llm_catalog` `/api/config` payload. The CLI bootstrap hardcodes a single
   `ClaudeCodeDispatcher` and its preflight hard-fails without the `claude`
   binary.
2. **Feature-based development** — the web console has a feature-mode form
   (`FeatureBrief`) that never asks for a Jira ticket or CloudWatch logs
   (features are not bugs). The CLI wizard is `WorkBrief`-only (bug-centric:
   reporter, escalation assignee, log sources); `FeatureBrief` is reachable
   only via `--brief <file>`.
3. **No natural-language intake** — `FeatureBrief` is document-driven
   (`document_path` to a brainstorm/proposal/spec). There is no path from
   "user types what they want" to a dispatchable brief; a light LLM with
   structured output should fill the requirements for new features or
   enhancements.

### Goals

- G1. The CLI renders backend/model pickers from the **same catalog** the
  web console uses (single source of truth, promoted into the package).
- G2. `parrot devloop` can dispatch the Development node cycle over a
  **multi-backend dev-agent pool** (wizard step + repeatable
  `--dev-agent backend[:model[:count]]` flag).
- G3. A **feature-mode wizard path** that never asks for Jira ticket or log
  sources, entered via a kind picker (`bug / enhancement / feature?`) or the
  `/feature` slash command.
- G4. **Free-text intake**: the user writes their request; a configurable
  light LLM (`DEV_LOOP_INTAKE_LLM`, default `anthropic:claude-haiku-4-5`)
  produces a structured `FeatureDraft`, rendered as a brainstorm markdown in
  `sdd/proposals/`, wrapped in a `FeatureBrief(document_kind="brainstorm")`.
- G5. Intake UX is **draft → review → confirm** (`accept / edit / redo
  <guidance> / cancel`) — never auto-dispatch, never a raw traceback.
- G6. Bootstrap builds the default development dispatcher via
  `agent_builder.build_dispatcher` (honoring `DEV_LOOP_DEVELOPMENT_AGENT`)
  and preflight is **backend-aware**.
- G7. Existing behavior is preserved: `--brief` file loading, the WorkBrief
  wizard fields, and the demo server (via a re-export shim) are unchanged.

### Non-Goals (explicitly out of scope)

- Extracting `server.py`'s form/brief builders into the package — Approach C
  was rejected in the brainstorm (follow-up candidate); only the catalog
  moves.
- CLI-side catalog duplication — Approach B rejected in brainstorm (drift).
- Interactive Q&A intake (like `/sdd-brainstorm`) — intake is one-shot
  draft + confirm/redo loop by decision.
- Feature-mode revision briefs; any change to the FEAT-378 flow topology,
  judge dispatchers, or `models.py` contracts.

---

## 2. Architectural Design

### Overview

Approach A (accepted): promote shared pieces into the package, keep the CLI
layer thin. Four components; **no changes** to
`parrot/flows/dev_loop/models.py` or the flow topologies. The CLI produces
the same `FeatureBrief` / `WorkBrief` objects the web form builders produce;
`DevelopmentNode` and `JudgePanelReviewDispatcher` already materialize
`dev_agents` / `judge_panel` via `agent_builder.build_dispatcher`
(FEAT-323/FEAT-378), so homologation happens entirely at the intake layer.

Resolved decisions embedded in this design (see §8 for the audit trail):
free-text intake produces a brainstorm document + `FeatureBrief`; pool
selection is wizard step + flags; intake UX is draft→review→confirm; intake
LLM is configurable with Haiku default; entry point is a kind picker in the
`run` wizard plus `/feature`.

### Component Diagram

```
                       ┌──────────────────────────────────────────────┐
                       │ parrot/flows/dev_loop/catalog.py  (Module 1) │
                       │ (moved verbatim from examples/dev_loop/      │
                       │  llm_catalog.py; shim re-exports back)       │
                       └───────┬──────────────────────────┬───────────┘
                               │ pickers/defaults         │ /api/config
                               ▼                          ▼
  free text ──► FeatureIntake (Module 2) ──► brainstorm .md ──► FeatureBrief
                (LLMFactory + invoke())      sdd/proposals/         │
                               ▲                                    │
                               │ /feature, kind picker              ▼
                DevLoopConsole wizard (Module 3) ────────► DevLoopRunner.run()
                (pool step, judge step, flags)                      ▲
                               │                                    │
                bootstrap (Module 4): build_dispatcher default ─────┘
                + backend-aware preflight
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `examples/dev_loop/llm_catalog.py` | moves | Becomes `parrot.flows.dev_loop.catalog`; shim re-exports for `server.py` (`import llm_catalog` at `server.py:157`) |
| `parrot.clients.factory.LLMFactory` | uses | `create(llm="provider:model")` resolves the intake client |
| `AbstractClient.invoke()` (FEAT-069) | uses | Stateless structured output against the `FeatureDraft` schema |
| `parrot.cli.wizard.PydanticWizard` | uses | `_collect_list` on `DevAgentSpec` / `JudgeSpec` rows; `WizardFieldOverride` feeds catalog choices |
| `parrot.flows.dev_loop.agent_builder.build_dispatcher` | uses | Bootstrap default dispatcher; pool materialization already exists (FEAT-323) |
| `parrot.flows.dev_loop.models.FeatureBrief` | constructs | `document_kind="brainstorm"`, `dev_agents`, `judge_panel` |
| `parrot.cli.devloop.console.DevLoopConsole` | extends | Kind picker, feature path, `/feature`, pool/judge steps |
| `parrot.cli.devloop.bootstrap` | modifies | Multi-backend default dispatcher + backend-aware preflight |
| `parrot devloop run` (click) | extends | New `--dev-agent` (repeatable) and `--text` options |

### Data Models

```python
# parrot/cli/devloop/intake.py (NEW — CLI-side only, not in models.py)
class FeatureDraft(BaseModel):
    """Structured draft the intake LLM fills from the user's free text."""
    title: str
    slug: str                          # kebab-case, used for the document filename
    problem_statement: str
    requirements: list[str]
    acceptance_criteria: list[str]
    affected_areas: list[str] = []
    out_of_scope: list[str] = []
    open_questions: list[str] = []
```

### New Public Interfaces

```python
# parrot/cli/devloop/intake.py
class FeatureIntake:
    """Free text → FeatureDraft → brainstorm document → FeatureBrief."""

    async def generate(self, text: str) -> FeatureDraft: ...
    async def regenerate(self, text: str, guidance: str) -> FeatureDraft: ...
    def write_document(self, draft: FeatureDraft) -> Path: ...
    def build_brief(
        self,
        draft: FeatureDraft,
        document_path: Path,
        *,
        dev_agents: Optional[list[DevAgentSpec]] = None,
        judge_panel: Optional[JudgePanelConfig] = None,
    ) -> FeatureBrief: ...
```

CLI surface additions on `parrot devloop run`:

```
--dev-agent backend[:model[:count]]   (repeatable; colon-separated so model
                                       ids never collide with the count)
--text "<request>"                    (non-interactive feature intake;
                                       with --yes skips the confirm loop)
```

Flags merge into whatever brief is built; `--brief` files win over flags for
fields they set.

---

## 3. Module Breakdown

### Module 1: Catalog promotion
- **Path**: `parrot/flows/dev_loop/catalog.py` (new) +
  `examples/dev_loop/llm_catalog.py` (becomes shim)
- **Responsibility**: Move the catalog **verbatim** (pure data + `conf`
  resolution; no aiohttp deps). The shim re-exports every public name
  `server.py` consumes: `BACKENDS`, `JUDGE_BACKENDS`, `ADVERSARIAL_BACKEND`,
  `PRIMARY_REVIEW_BACKENDS`, `BackendInfo`, `get_backend`,
  `backends_for_role`, `effective_default_model`,
  `default_judge_panel_payload`, `catalog_payload`.
- **Depends on**: the in-flight `agy` dispatcher work being committed first
  (the WIP already added `agy` to `BACKENDS` and `JUDGE_BACKENDS` in
  `examples/dev_loop/llm_catalog.py:37,47,124`).

### Module 2: Free-text intake
- **Path**: `parrot/cli/devloop/intake.py` (new)
- **Responsibility**: `FeatureDraft` model; `FeatureIntake.generate()` /
  `regenerate()` via `LLMFactory.create(DEV_LOOP_INTAKE_LLM)` +
  `client.invoke(prompt, output_type=FeatureDraft)`; `write_document()`
  renders brainstorm markdown with FEAT-145 frontmatter (`type: feature`,
  `base_branch: dev`) to `sdd/proposals/<slug>.brainstorm.md` (suffix `-2`,
  `-3`, … on collision — never overwrite); `build_brief()` assembles the
  `FeatureBrief`. One retry on structured-output validation failure with the
  validation error appended to the prompt.
- **Depends on**: nothing new (Module 1 not required).

### Module 3: Console / wizard / click surface
- **Path**: `parrot/cli/devloop/console.py`, `parrot/cli/devloop/__init__.py`
- **Responsibility**: Kind picker at the top of the interactive path
  (`bug / enhancement / feature?`); `bug`/`enhancement` → existing WorkBrief
  wizard byte-identical plus optional dev-agent pool step; `feature` →
  intake path (multiline prompt → draft → Rich summary panel →
  `accept / edit <field> / redo <guidance> / cancel`); judge-panel step
  (feature path only, choices limited to the catalog's `JUDGE_BACKENDS`,
  default from `default_judge_panel_payload()`); `/feature` slash command;
  `--dev-agent` / `--text` click options with fail-fast validation against
  the catalog. Docs update in `documentation/parrot-devloop-cli.md`.
- **Depends on**: Module 1 (catalog pickers), Module 2 (intake).

### Module 4: Bootstrap homologation
- **Path**: `parrot/cli/devloop/bootstrap.py`
- **Responsibility**: Replace the hardcoded `ClaudeCodeDispatcher`
  (`bootstrap.py:164`) with `agent_builder.build_dispatcher(DevAgentSpec(
  agent=DEV_LOOP_DEVELOPMENT_AGENT or "claude-code", model=...))`;
  backend-aware preflight (the `claude` CLI check hard-fails only when
  claude-code is the selected default backend; other backends check their
  own binary — `codex`, `gemini`, `agy` — or API-key env var, from
  `BackendInfo.requires`); Redis + worktree-base checks unchanged;
  Jira/CloudWatch toolkits stay wired but soft-optional for feature-mode
  runs.
- **Depends on**: Module 1 (catalog `BackendInfo` for preflight data).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_catalog_shim_reexports` | Module 1 | Every public name in the shim is identical (same object) to the package catalog's |
| `test_feature_draft_schema` | Module 2 | `FeatureDraft` validates/rejects expected shapes |
| `test_write_document_frontmatter` | Module 2 | Generated markdown carries `type: feature` / `base_branch: dev` frontmatter |
| `test_write_document_no_overwrite` | Module 2 | Slug collision produces `-2`, `-3` suffixes |
| `test_generate_retries_on_validation` | Module 2 | One retry with validation error appended; LLM client mocked |
| `test_build_brief_assembly` | Module 2 | `FeatureBrief` has `document_kind="brainstorm"`, pool, judges |
| `test_dev_agent_flag_parsing` | Module 3 | `codex:gpt-5.5:2` → `DevAgentSpec(agent="codex", model="gpt-5.5", count=2)`; bare `agy` → defaults |
| `test_dev_agent_flag_unknown_backend` | Module 3 | Unknown backend fails fast listing catalog ids |
| `test_kind_picker_routing` | Module 3 | `feature` routes to intake; `bug` reaches the unchanged WorkBrief wizard |
| `test_feature_command` | Module 3 | `/feature` enters the intake path |
| `test_bootstrap_backend_dispatcher` | Module 4 | `DEV_LOOP_DEVELOPMENT_AGENT=codex` yields a Codex dispatcher |
| `test_preflight_backend_aware` | Module 4 | Missing `claude` binary does not fail preflight when backend=codex |

### Integration Tests

| Test | Description |
|---|---|
| `test_intake_to_dispatch_e2e` | Free text (mock LLM) → document written → `FeatureBrief` → fake-runner dispatch (extends the existing fake-flow console E2E pattern from TASK-1898) |
| `test_server_still_boots_with_shim` | Existing `tests/flows/dev_loop/test_server_repo_wiring.py` suite passes unchanged |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_intake_client():
    """AbstractClient stub whose invoke() returns a canned FeatureDraft
    (and a failing-then-passing pair for the retry test)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pytest packages/ai-parrot/tests/cli/ -v` passes (new + existing).
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes unchanged
      (catalog shim keeps the demo server suites green).
- [ ] CLI pickers and web `/api/config` render from the same
      `parrot.flows.dev_loop.catalog` module (G1).
- [ ] `parrot devloop run --dev-agent codex:gpt-5.5:2 --dev-agent agy`
      produces a brief whose `dev_agents` is
      `[DevAgentSpec(codex, gpt-5.5, 2), DevAgentSpec(agy)]` (G2).
- [ ] The feature wizard path asks for **no** Jira ticket and **no** log
      sources (G3).
- [ ] With `DEV_LOOP_INTAKE_LLM` unset, intake resolves
      `anthropic:claude-haiku-4-5`; setting it to another `provider:model`
      switches the client (G4).
- [ ] The generated document lands in `sdd/proposals/<slug>.brainstorm.md`
      with FEAT-145 frontmatter and is never overwritten on re-run (G4).
- [ ] Intake never dispatches without explicit accept; LLM/document errors
      surface as `Brief error:` messages, no tracebacks (G5).
- [ ] `DEV_LOOP_DEVELOPMENT_AGENT=codex` (no `claude` binary present) passes
      preflight and builds a Codex default dispatcher (G6).
- [ ] `parrot devloop run --brief <existing-file>` behavior is byte-identical
      to today for both WorkBrief and FeatureBrief files (G7).
- [ ] No breaking changes to existing public API; docs updated in
      `documentation/parrot-devloop-cli.md`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-07-28 on `dev` @ `abe78ae22`. NOTE: `examples/dev_loop/`
> and `parrot/flows/dev_loop/` carry **uncommitted `agy` WIP** — re-verify
> line numbers after that work lands.

### Verified Imports

```python
from parrot.clients.factory import LLMFactory            # factory.py:128
from parrot.models.responses import InvokeResult          # responses.py:1337
from parrot.cli.wizard import (                            # wizard.py
    PydanticWizard,        # :55
    WizardConfig,          # :48
    WizardFieldOverride,   # :40
)
from parrot.flows.dev_loop.models import (                 # models.py
    WorkBrief,             # :138
    DevAgentSpec,          # :388  (DevAgentBackend Literal at :383)
    FeatureBrief,          # :1068
    JudgeSpec,             # :1173
    JudgePanelConfig,      # :1209
    parse_brief,           # :1330
)
from parrot.flows.dev_loop.agent_builder import build_dispatcher  # agent_builder.py:100
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                          # :128
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient:  # :160
    # llm format: "provider:model" or "provider"

# packages/ai-parrot/src/parrot/clients/claude.py (every client implements this)
async def invoke(self, prompt: str, *, output_type: Optional[type] = None,
                 structured_output: Optional[StructuredOutputConfig] = None,
                 model: Optional[str] = None, system_prompt: Optional[str] = None,
                 max_tokens: int = 4096, temperature: float = 0.0,
                 use_tools: bool = False, tools: Optional[list] = None,
                 ) -> InvokeResult:                        # claude.py:1810
# StructuredOutputConfig: abstract_client.py:67
# model=None ⇒ per-client _lightweight_model default (FEAT-069)

# packages/ai-parrot/src/parrot/cli/wizard.py
class PydanticWizard:                                      # :55
    async def collect(self, *, initial: Optional[Dict[str, Any]] = None) -> BaseModel:  # :72
    async def _collect_submodel(self, name: str, model_type: Type[BaseModel]) -> BaseModel:  # :262
    async def _collect_list(...)                           # :271 (list-of-submodel rows)
    def render_summary(self, instance: BaseModel) -> None: # :412

# packages/ai-parrot/src/parrot/cli/devloop/console.py
class DevLoopConsole:                                      # :30
    async def _collect_work_brief(self, brief_file=None) -> Any:   # :106 (wizard entry)
    def _load_brief(self, path_str: str) -> Any:                   # :166 (parse_brief union)
    def _print_feature_brief_summary(self, brief: Any) -> None:    # :215
    async def _dispatch_run(self, brief: Any) -> str:              # :239
    async def _dispatch_command(self, raw: str) -> None:           # :482 (handlers dict :488)
    async def _cmd_new(self, args: str) -> None:                   # :577

# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
class DevLoopRuntime:                                      # :42 (dataclass)
async def preflight(*, console=None) -> PreflightResult:   # :55
async def build_runtime(*, console=None) -> DevLoopRuntime:# :140
# hardcoded: dispatcher = ClaudeCodeDispatcher(...)        # :164  ← Module 4 replaces

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
def build_dispatcher(spec) -> Tuple[dispatcher, profile]:  # :100 (DevAgentSpec → pair)
def parse_pool_env(config_getter) -> Optional[DevAgentPoolConfig]:  # :213
def resolve_pool_max(config_getter, *, default: int = 4) -> int:    # :244

# examples/dev_loop/llm_catalog.py (UNCOMMITTED agy WIP — moves to
# parrot/flows/dev_loop/catalog.py in Module 1)
JUDGE_BACKENDS = ("claude-code", "codex", "gemini", "agy")           # :37
ADVERSARIAL_BACKEND = "codex"                                        # :43
PRIMARY_REVIEW_BACKENDS = ("claude-code", "codex", "gemini", "agy")  # :47
class BackendInfo:                                                   # :51 (frozen dataclass)
BACKENDS: Tuple[BackendInfo, ...]                                    # :83
def get_backend(backend_id: str) -> Optional[BackendInfo]:           # :183
def backends_for_role(role: str) -> List[BackendInfo]:               # :188
def effective_default_model(backend, config_getter=None) -> str:     # :201
def default_judge_panel_payload(config_getter=None) -> List[Dict[str, str]]:  # :243
def catalog_payload(config_getter=None) -> Dict[str, Any]:           # :272
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FeatureIntake.generate` | `LLMFactory.create()` → `client.invoke()` | `output_type=FeatureDraft` | `factory.py:160`, `claude.py:1810` |
| `FeatureIntake.build_brief` | `FeatureBrief(...)` | constructor | `models.py:1068` |
| Wizard pool step | `PydanticWizard._collect_list` on `DevAgentSpec` | list-of-submodel rows | `wizard.py:271`, `models.py:388` |
| Kind picker / `/feature` | `DevLoopConsole._dispatch_command` handlers | new handler entries | `console.py:488` |
| Bootstrap dispatcher | `agent_builder.build_dispatcher` | replaces hardcode | `bootstrap.py:164`, `agent_builder.py:100` |
| Shim | `server.py` `import llm_catalog` | module-level re-exports | `server.py:157,290,483,833,872,967` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/flows/dev_loop/catalog.py`~~ — created by Module 1.
- ~~`parrot/cli/devloop/intake.py`~~, ~~`FeatureDraft`~~, ~~`FeatureIntake`~~
  — created by Module 2.
- ~~`DEV_LOOP_INTAKE_LLM`~~ config key — introduced by Module 2 (grep
  confirms zero hits today).
- ~~`/feature` slash command~~, ~~`--dev-agent`~~, ~~`--text`~~ flags — created
  by Module 3 (today's `run` options are only `--brief` / `--yes`).
- ~~Interactive FeatureBrief wizard~~ — explicitly out of scope in FEAT-374
  (`console.py:107-116` docstring); Module 3 adds the intake path instead.
- ~~`llm_catalog.ROLES` module-level constant~~ — role filtering goes through
  `backends_for_role()` (`:188`); do not reference a `ROLES` symbol.
- ~~`AbstractClient.completion()` with structured output for intake~~ — use
  `invoke()` (FEAT-069), which exists per-client (e.g. `claude.py:1810`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Deferred heavy imports** in click command bodies and console methods
  (`# noqa: PLC0415`) so `parrot devloop --help` stays fast — every existing
  method in `console.py` / `bootstrap.py` follows this.
- Catalog moves **verbatim** — no renames, no "improvements" — so the shim
  is a pure re-export and `server.py` diffs stay zero.
- Generated brainstorm documents carry the FEAT-145 frontmatter block
  exactly as `sdd/templates/`-produced ones do (`type: feature`,
  `base_branch: dev`).
- Error surfacing follows the existing `Brief error:` pattern
  (`console.py:86`) — friendly message + exit code 1, never a traceback.
- Google-style docstrings, strict type hints, Pydantic models, `self.logger`.

### Known Risks / Gotchas

- **`agy` WIP dependency**: the uncommitted dispatcher work
  (`models.py`, `dispatcher.py`, `agent_builder.py`, `code_review.py`,
  `llm_catalog.py`, `test_agy_dispatcher.py`) must land before Module 1
  moves the catalog, or the move must strip the `agy` entry. Line numbers in
  §6 shift when it lands — re-verify.
- **Shim completeness**: `server.py` does `import llm_catalog` (module
  attribute access, `server.py:157`) — the shim must define every name at
  module level; a missing one fails at runtime, not import time, for
  attribute access. The `test_catalog_shim_reexports` test guards this.
- **Wizard list UX**: `_collect_list` on `DevAgentSpec` prompts field-by-field
  per row; catalog choices must be injected via `WizardFieldOverride` prompts
  (the engine has no native "choices from function" hook — keep the override
  text short or extend `WizardFieldOverride` minimally).
- **Intake default requires Anthropic credentials**: `invoke()` with the
  Haiku default needs `ANTHROPIC_API_KEY`; preflight should surface a clear
  hint when the intake path is selected without it (soft check — `--brief`
  runs don't need it).
- **`--dev-agent` colon parsing**: split on `:` max 2 — backend ids and
  count are colon-free; model ids in the catalog contain `/` and `.` but no
  `:` (verified against `BACKENDS` model lists).
- **Never stage unrelated files**: the working tree may carry WIP; all SDD
  commits stage explicit paths only.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none new) | — | `click`, `rich`, `prompt_toolkit`, `pyyaml`, Pydantic v2 already ship with the CLI |

---

## 8. Open Questions

> All brainstorm questions were resolved interactively before this spec.

- [x] Free-text intake target — *Resolved in brainstorm*: light LLM drafts a
      brainstorm markdown saved under `sdd/proposals/`, wrapped in a
      `FeatureBrief(document_kind="brainstorm")`; full FEAT-378 topology,
      zero model changes.
- [x] Dev-agent pool selection — *Resolved in brainstorm*: wizard step +
      repeatable `--dev-agent backend[:model[:count]]` flag; brief files
      keep working.
- [x] Intake UX — *Resolved in brainstorm*: draft → review → confirm
      (`accept / edit / redo <guidance> / cancel`); no auto-dispatch.
- [x] Intake LLM — *Resolved in brainstorm*: configurable
      `DEV_LOOP_INTAKE_LLM`, default `anthropic:claude-haiku-4-5`, resolved
      via `LLMFactory` with structured output.
- [x] Entry point — *Resolved in brainstorm*: kind picker
      (`bug / enhancement / feature?`) in the `run` wizard + `/feature`
      slash command; `--brief` unchanged.
- [x] Implementation approach — *Resolved in brainstorm*: Approach A
      (promote catalog into the package, thin CLI layer); B (duplication)
      and C (full form-builder extraction) rejected.

---

## Worktree Strategy

- **Default isolation unit**: per-spec — one worktree, tasks sequential.
- Modules 2 (intake) and 1 (catalog) are independent of each other, but
  Modules 3 and 4 both depend on Module 1 and all four touch the same small
  package (`parrot/cli/devloop/`); parallel worktrees would conflict on
  `console.py` / `__init__.py`. Sequential order: M1 → M2 → M3 → M4 (M2 may
  swap with M1).
- **Cross-feature dependencies**: the uncommitted `agy` dispatcher work must
  merge to `dev` before this feature's worktree is created (Module 1 moves
  the catalog file that WIP modifies — creating the worktree earlier would
  fork that file's history).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-28 | Jesus Lara | Initial draft from approved brainstorm |
