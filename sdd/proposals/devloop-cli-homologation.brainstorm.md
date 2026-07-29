---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: `parrot devloop` CLI Homologation — feature-mode wizard, free-text intake, multi-backend dev pool

**Date**: 2026-07-28
**Author**: Jesus Lara (design session with Claude)
**Status**: approved design (interactive brainstorm, all decisions resolved)
**Recommended Option**: Approach A (accepted by user)

---

## Problem Statement

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
   "user types what they want" to a dispatchable brief in either UI; the CLI
   is where it should land first.

Goal: homologate `parrot devloop` with the web console using the same
catalog, models, and dispatcher builders — plus a free-text intake where a
light LLM with structured output fills the requirements for new features or
enhancements.

## Decisions (resolved interactively)

| Question | Decision |
|---|---|
| Free-text intake target | Light LLM drafts a **brainstorm markdown** from the free text, saved under `sdd/proposals/`, wrapped in a `FeatureBrief(document_kind="brainstorm")` — full FEAT-378 feature topology, zero model changes |
| Dev-agent pool selection | **Wizard step + repeatable `--dev-agent backend[:model[:count]]` flag**; brief files keep working |
| Intake UX | **Draft → review → confirm**: one-shot LLM draft, Rich summary panel, then `accept / edit / redo <guidance> / cancel` |
| Intake LLM | **Configurable** — `DEV_LOOP_INTAKE_LLM` (default `anthropic:claude-haiku-4-5`) resolved via `LLMFactory` with structured output |
| Entry point | **Kind picker in the `run` wizard** (`bug / enhancement / feature?`) + `/feature` slash command; `--brief` unchanged |
| Implementation approach | **A** — promote shared pieces into the package, thin CLI layer (catalog moves into `parrot/flows/dev_loop/`; server form-builders stay put as a possible follow-up) |

Approaches considered and rejected:

- **B — CLI-side catalog duplication**: fastest, but two catalogs drift
  immediately (e.g. the `agy` backend would need adding twice).
- **C — full extraction including `server.py` form/brief builders**:
  cleanest long-term, but refactors a working demo server that already has
  uncommitted FEAT-378 changes in flight. Deferred as follow-up.

## Design

### 1. Architecture

Four components; no changes to `parrot/flows/dev_loop/models.py` or the flow
topologies. The CLI produces the same `FeatureBrief` / `WorkBrief` objects
the web form builders produce; `DevelopmentNode` and
`JudgePanelReviewDispatcher` already materialize `dev_agents` /
`judge_panel` via `agent_builder.build_dispatcher` (FEAT-323/FEAT-378), so
homologation is entirely at the intake layer.

```
parrot/flows/dev_loop/catalog.py      ← promoted from examples/dev_loop/llm_catalog.py
parrot/cli/devloop/intake.py          ← NEW: free text → FeatureDraft → brainstorm doc → FeatureBrief
parrot/cli/devloop/console.py         ← kind picker, feature wizard, pool/judge steps, /feature
parrot/cli/devloop/bootstrap.py       ← multi-backend default dispatcher, backend-aware preflight
```

### 2. Catalog promotion

- Move `examples/dev_loop/llm_catalog.py` → `parrot/flows/dev_loop/catalog.py`
  **verbatim** (pure data + `conf` resolution; no aiohttp dependencies).
- `examples/dev_loop/llm_catalog.py` becomes a re-export shim (explicit
  names `server.py` imports), so the demo server and its tests keep working
  unchanged.
- The CLI renders pickers and defaults from `backends_for_role("development"
  / "judge")`, `effective_default_model()`, and
  `default_judge_panel_payload()` — the same data the web `<select>`s
  render from.

### 3. Free-text intake (`parrot/cli/devloop/intake.py`)

- **`FeatureDraft`** (new Pydantic model, CLI-side only): `title`, `slug`,
  `problem_statement`, `requirements: list[str]`,
  `acceptance_criteria: list[str]`, `affected_areas: list[str]`,
  `out_of_scope: list[str]`, `open_questions: list[str]`.
- **`FeatureIntake.generate(text) -> FeatureDraft`**: resolves
  `DEV_LOOP_INTAKE_LLM` (default `"anthropic:claude-haiku-4-5"`) through
  `LLMFactory` (`parrot/clients/factory.py`) and requests structured output
  against the `FeatureDraft` schema. `regenerate(text, guidance)` appends
  user feedback for the redo loop.
- **`FeatureIntake.write_document(draft) -> Path`**: renders the draft as a
  brainstorm markdown with FEAT-145 frontmatter (`type: feature`,
  `base_branch: dev`) into `sdd/proposals/<slug>.brainstorm.md`. On name
  collision, suffix `-2`, `-3`, … — never overwrite.
- Returns `FeatureBrief(document_path=..., document_kind="brainstorm",
  dev_agents=..., judge_panel=...)`. PlannerNode then runs `/sdd-spec` →
  `/sdd-task` exactly as for a hand-written brainstorm.

### 4. Console / wizard changes

- **Kind picker first**: `run` without `--brief` asks
  `bug / enhancement / feature?`.
  - `bug` / `enhancement` → today's WorkBrief wizard, byte-identical, plus
    the new optional dev-agent pool step.
  - `feature` → intake path: multiline free-text prompt → LLM draft → Rich
    panel showing the draft + generated document path →
    `accept / edit <field> / redo <guidance> / cancel` loop (same panel
    style as `_print_feature_brief_summary`).
- **Dev-agent pool step** (both paths, optional; default = single backend
  from `DEV_LOOP_DEVELOPMENT_AGENT` or `claude-code`): rows of
  backend/model/count using the wizard engine's existing list-of-submodel
  collection (`PydanticWizard._collect_list` on `DevAgentSpec`), choices and
  default models fed from the catalog via `WizardFieldOverride`.
- **Judge-panel step** (feature path only, optional): same row pattern on
  `JudgeSpec`; default panel from `default_judge_panel_payload()`; only
  `JUDGE_BACKENDS` (claude-code, codex, gemini) offered.
- **`/feature` slash command**: jumps straight into feature intake (same as
  picking `feature` in `/new`).
- **Flags on `run`**:
  - repeatable `--dev-agent backend[:model[:count]]`
    (e.g. `--dev-agent codex:gpt-5.5:2 --dev-agent agy`) — colon-separated
    so model ids never collide with the count suffix;
  - `--text "<request>"` for non-interactive feature intake (`--yes` skips
    the confirm loop).
  - Flags merge into whatever brief is built; `--brief` files win over
    flags for fields they set.

### 5. Bootstrap homologation

- Default development dispatcher built via
  `agent_builder.build_dispatcher(DevAgentSpec(agent=DEV_LOOP_DEVELOPMENT_AGENT
  or "claude-code", model=...))` instead of the hardcoded
  `ClaudeCodeDispatcher` — same env contract as the server.
- **Backend-aware preflight**: the `claude` CLI check hard-fails only when
  claude-code is the selected default backend; other backends check their
  own binary (`codex`, `gemini`, `agy`) or API-key env var, reported in the
  same Rich table. Redis + worktree-base checks unchanged.
- Jira/CloudWatch toolkits stay wired but are soft-optional for
  feature-mode runs (feature mode never creates Jira issues).

### 6. Error handling

- Intake LLM failure (missing key, timeout, schema mismatch): friendly
  message; offer retry or fall back to the manual `--brief` file path —
  never a raw traceback (matches the existing `Brief error:` pattern in
  `console.py`).
- Structured-output validation retries once with the validation error
  appended to the prompt before surfacing.
- Document write failures (missing `sdd/proposals/`, permissions) surface
  as `Brief error:` with the offending path.
- Unknown backend in `--dev-agent` fails fast at flag-parse time, listing
  valid backends from the catalog.

### 7. Testing

- `tests/cli/devloop/test_intake.py`: `FeatureDraft` schema, document
  rendering (frontmatter, slug collision), `FeatureBrief` assembly — LLM
  client mocked.
- `tests/cli/devloop/test_pool_flags.py`: `--dev-agent` parsing →
  `DevAgentSpec[]`; invalid backend errors.
- `tests/cli/test_devloop_feature_brief.py` extended: kind-picker routing,
  `/feature` command (fake session driving the wizard — existing pattern).
- Catalog move: existing server tests keep passing via the shim; one test
  asserts the shim's re-exports match the package catalog.
- Run `pytest packages/ai-parrot/tests/cli/` and
  `packages/ai-parrot/tests/flows/dev_loop/` after each change.

## Dependencies & Risks

- **Depends on the in-flight `agy` dispatcher work** (uncommitted changes
  to `models.py`, `dispatcher.py`, `agent_builder.py`,
  `code_review.py` + `test_agy_dispatcher.py`). The design treats `agy` as
  just another catalog entry, so it lands cleanly whether or not that work
  merges first — but the catalog entry for `agy` must only ship once its
  dispatcher does.
- Catalog shim risk is low: re-export must cover every name `server.py`
  imports (`catalog_payload`, `get_backend`, `backends_for_role`,
  `effective_default_model`, `default_judge_panel_payload`, `BackendInfo`,
  constants).
- The intake default model id (`claude-haiku-4-5`) is a config default,
  not a hardcode — deployments override via `DEV_LOOP_INTAKE_LLM`.

## Out of Scope

- Extracting `server.py`'s form/brief builders into the package
  (Approach C) — follow-up candidate.
- An interactive Q&A intake (like `/sdd-brainstorm`) — the intake is
  one-shot draft + confirm/redo loop by decision.
- Feature-mode revision briefs, and any change to the FEAT-378 flow
  topology, judge dispatchers, or `models.py` contracts.
