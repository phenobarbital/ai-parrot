---
id: FEAT-768
title: Example agents for the governed Semantic Layer under examples/agents/semantic
slug: semantic-layer-example
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-29
  summary_oneline: "Create example agents under examples/agents/semantic that use the FEAT-704 Semantic Layer"
overall_confidence: high
base_branch: dev
projects: [ai-parrot-semantic, docs, ci]
tags: [semantic-layer, examples, agents, mcp-local, governance, duckdb]
research_state: sdd/state/FEAT-768/
created: 2026-10-29
updated: 2026-10-29
---

# FEAT-768 — Example agents for the governed Semantic Layer

> **Mode**: enrichment
> **Confidence**: high (scope resolved at the Q&A gate; evidence probe-verified at HEAD `7e6741f13`)
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-768/`](../state/FEAT-768/)

---

## 0. Origin

> `/sdd-proposal semantic-layer-example -- Vamos a crear a partir de FEAT-704 un par de
> ejemplos en /examples/agents/semantic de un par de agentes haciendo uso de Semantic Layer`

**Initial signals** (extracted, not interpreted):
- Verbs: *"crear"* → additive/enrichment, no failure language anywhere.
- Named entities: **FEAT-704**, **Semantic Layer**, **`/examples/agents/semantic`**.
- Quantity: *"un par de"* (a couple) — **superseded at the Q&A gate**, see §5/D2.
- Components / labels: none (inline source).
- Acceptance criteria provided: **no**.

---

## 1. Synthesis Summary

FEAT-704 shipped the governed semantic layer as `packages/ai-parrot-semantic`, and it already has
exactly one example — but at `examples/semantic/`, not under `examples/agents/`, and that example
tells only one story (the guarded dataset hand-off), using 2 of the 10 `sl_*` tools. The requested
directory `examples/agents/semantic/` **does not exist** (probe-confirmed). This proposal relocates
the existing example into it — a change with a blast radius of exactly two live references,
`packages/ai-parrot-semantic/tests/test_example_agent.py:21` and `examples/semantic/README.md:3` —
and adds four new example agents, each covering a surface nothing currently demonstrates. The most
valuable of these is an LLM-driven agent, because today **no example lets an LLM actually drive the
semantic tools**: the existing one builds an `Agent` at line 314 and then discards it, which means the
`ask(permission_context=…)` path required by the fail-closed gate is exercised nowhere. The
recommendation is to proceed straight to `/sdd-spec` — localization is probe-verified and no
architectural fork is in play.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-768/findings/` (15 canonical findings merged from 21
> lane findings). **No fabricated paths or symbols**: 57 citations were fact-checked by two
> `sdd-contract-probe` agents at HEAD `7e6741f13` — 54 verified, 1 signature refined, 2 resolved
> inline. Full probe log: `sdd/state/FEAT-768/citation_checks.md`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `examples/agents/semantic/` | — | — | **TARGET — confirmed ABSENT** (probe `c42`) | F001, F012 |
| 2 | `examples/semantic/agent_semantic_example.py` | `GuardedDatasetFacade` | 35-126 | the example to move; owns the guarded-hand-off story | F001, F010 |
| 3 | `examples/semantic/agent_semantic_example.py` | `connection_env` / `build_toolkits` / `build_agent` | 268, 285, 314 | reusable factories the new examples should mirror | F001 |
| 4 | `packages/ai-parrot-semantic/tests/test_example_agent.py` | `_EXAMPLE_PATH` | 21 | **the single line the move breaks** | F002 |
| 5 | `examples/semantic/README.md` | — | 3 | second and last live path reference | F002 |
| 6 | `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` | `SemanticLayerToolkit.__init__` | 44 | kwargs-only construction; 5 fail-closed paths | F008 |
| 7 | `packages/ai-parrot-semantic/src/parrot/semantic/context.py` | `bind_semantic_context` | 86 | mandatory governance binding | F013 |
| 8 | `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py` | `LocalSemanticLayerToolkit` | 60 | the MCP-local surface | F008 |
| 9 | `packages/ai-parrot-semantic/src/parrot/semantic/models.py` | `SemanticQuery` | 102-105 | `extra="forbid"` | F014 |
| 10 | `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py` | `GovernedDatasetSink` | 34 | Protocol; sink may not be a toolkit | F008 |
| 11 | `docs/tools/semantic-layer.md` | — | 123 | canonical narrative; blocks **parsed** by `test_mcp_local.py:26` | F004, F007 |
| 12 | `examples/agents/finance/hooba_agent.py` | — | 3, 5, 44, 78 | the house-style template to copy | F005, F012 |
| 13 | `.github/workflows/ci.yml` | — | 535-536 | the only CI exposure | F007 |

**Verified `sl_*` surface** (`toolkit.py`, `tool_prefix = "sl"` at :41) — all ten probe-confirmed:

| Tool | Line | Signature |
|---|---|---|
| `sl_list_models` | 123 | `async def list_models(self) -> list[dict]` |
| `sl_list_metrics` | 138 | `async def list_metrics(self, model: str) -> list[dict]` |
| `sl_get_dimensions` | 147 | `async def get_dimensions(self, model: str, metrics: list[str] \| None = None) -> list[dict]` |
| `sl_get_dimension_values` | 158 | `async def get_dimension_values(self, model, dimension, metrics=None, limit: int = 50) -> SemanticQueryResult` |
| `sl_search_data_model` | 165 | `async def search_data_model(self, text: str, model: str \| None = None) -> list[dict]` |
| `sl_list_saved_queries` | 183 | `async def list_saved_queries(self, model: str) -> list[dict]` |
| `sl_compile_query` | 195 | `async def compile_query(self, query: SemanticQuery) -> dict` |
| `sl_query_metrics` | 200 | `async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult` |
| `sl_run_sql` | 451 | `async def run_sql(self, model: str, sql: str) -> SemanticQueryResult` *(hidden unless `allow_raw_sql=True`)* |
| `sl_save_result_as_dataset` | 546 | `async def save_result_as_dataset(self, result_id, name, description=None) -> dict` *(hidden without a `dataset_manager_factory`)* |

### 2.2 Constraints Discovered

- **K1 — Construction is kwargs-only and fails closed five ways.** `def __init__(self, **kwargs: Any) -> None`
  (`toolkit.py:44`). `static_subject` raises `static_subject_forbidden` (:67); a governed model with no
  `dataplane_guard` raises `guard_required` (:79); `allow_raw_sql` must be a bool (:69-70); an invalid
  sink factory is rejected; `sl_run_sql`/`sl_save_result_as_dataset` are simply **not exposed** unless
  opted in. *Implication*: every example must pass a real guard. *Evidence*: F008

- **K2 — An LLM-driven example needs BOTH bindings.** `_pre_execute` fail-closes unless the
  `_permission_context` kwarg **equals** `current_pctx()`, and that kwarg arrives only via
  `AbstractBot.ask(permission_context=…)`. So an LLM example needs
  `async with bind_semantic_context(ctx, identity=…)` **and** `await agent.ask(q, permission_context=ctx)`.
  Direct method calls (what today's example does) bypass `_pre_execute` entirely.
  *Implication*: this is the one constraint the current example cannot teach. *Evidence*: F013

- **K3 — `SemanticQuery` is `ConfigDict(extra="forbid")`** (`models.py:105`). Any guessed field name is a
  hard validation error. *Implication*: field names get copied from the model, never invented. *Evidence*: F014

- **K4 — A `GovernedDatasetSink` may NOT be an `AbstractToolkit`/`DatasetManager`/`DataFrame`** —
  `_validate_sink` rejects by MRO. The existing example works around this with a `_FacadeSink`
  composition wrapper. *Implication*: reuse that wrapper; don't rediscover it. *Evidence*: F008, F001

- **K5 — Never name a new example file `test_*.py`.** `pytest.ini` sets no `testpaths`/`norecursedirs`
  and there is no root `collect_ignore`, so `examples/` **is** collected — `examples/agents/` already
  holds five `test_*.py` files with pytest `__pycache__`. *Evidence*: F007 *(re-verified inline after a
  mis-scoped probe)*

- **K6 — `examples/**/*.py` waives only `F401, F841, E402`** (`ruff.toml:152`). `TID251` (banned imports,
  incl. `sidemantic`), `B`, `ASYNC`, `PIE`, `C4`, `LOG` all still bite, at line-length 120 (`ruff.toml:68`).
  *Implication*: examples are lint-gated like shipped code. *Evidence*: F007

- **K7 — CI's only semantic exposure** is `ci.yml:535-536`: `uv sync --all-packages --extra duckdb` then
  `uv run pytest packages/ai-parrot-semantic/tests -q --tb=short`, with no
  `--continue-on-collection-errors`. *Implication*: new examples are DuckDB-only or `importorskip`-guarded.
  *Evidence*: F007

- **K8 — `compile_query` returns PRE-RLS SQL** (closed `issue:22fbd14d96a9`); governed SQL lives only in
  the audit record. *Implication*: an example printing it must not call it "the SQL as executed". *Evidence*: F006

- **K9 — `issue:f0da823294fb` (major, closed) already forced one rewrite.** It required the real
  `DataPlanePolicyGuard`, `connection_env()`, an owner pre-check and a **failing** denial demo. Re-introducing
  a placeholder guard, env leak, weak owner check or missing denial in a NEW example is a **known regression**.
  *Evidence*: F006, F010

- **K10 — `docs/tools/semantic-layer.md`'s fenced blocks are parsed** by
  `packages/ai-parrot-semantic/tests/test_mcp_local.py:26` (`_DOC_PATH`). *Implication*: per D5 we are editing
  that doc, so this is a **test-affecting change**. *Evidence*: F004, F007

- **K11 — Usage rights restrict only masked / `sensitive: true` members** (closed `issue:9a4e4c35b032`). The
  current example's `usage:` list is broader than required and must not be copied as "required".
  *Evidence*: F006 · *confidence: medium (inferred from the issue body)*

- **K12 — A policy model covers only its own table, relationship-reachable tables, and tables its own
  masks/rls name** (closed `issue:bd477252b8f3`). A multi-model example **must** declare the relationship or
  qualification fails. *Evidence*: F006, F003

- **K13 — `RlsRegistry` has no unregister API** (closed `issue:e3ff9bfb4a83`): `reload()` never drops an RLS
  rule. No example may present `reload()` as a way to remove one. *Evidence*: F006

- **K14 — `parrot.semantic.__init__` exports only four names** (`:7`): `__version__`, `SemanticQuery`,
  `SemanticQueryResult`, `SemanticLayerToolkit`. Everything else imports from its submodule. *Evidence*: F008

- **K15 — Surface frozen since 2026-10-26, but that day landed four behavioural fixes**
  (`c3e2049d`, `32a7762e`, `0ac26316`, `ae7e21f1`). Examples must target post-`c3e2049d` semantics.
  *Evidence*: F009

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched |
|--------|------|---------|---------|
| `07adb66f` | 2026-10-28 | `fix(semantic-layer): unpin version and update CI sync assertion in packaging test` | tests only |
| `9a953146` | 2026-10-27 | `fix(semantic-layer): test the doc's own YAML/JSON blocks and align its model format (issue:d01c24f18770)` | `docs/tools/semantic-layer.md`, `test_mcp_local.py` |
| `ef85c503` | 2026-10-27 | `fix(semantic-layer): wire real PBAC guard in agent example, scope env and owner checks (issue:f0da823294fb)` | **rewrote 173 of the example's 261 lines**, +186 test |
| `c3e2049d` | 2026-10-26 | metric-only column masks, exact truncation, read-time usage recheck | 5 of 8 public modules |
| `32a7762e` | 2026-10-26 | return pre-RLS SQL to callers, governed SQL in audit only | `src/parrot/semantic/` |
| `0ac26316` | 2026-10-26 | refuse to override foreign RLS rules | `src/parrot/semantic/` |
| `ae7e21f1` | 2026-10-26 | read-only governed DuckDB connections | `src/parrot/semantic/` |
| `9b2f099c` | 2026-10-26 | `feat(semantic-layer): TASK-4702` — **added** `examples/semantic/*` (+261) | the example |

**Nothing to salvage.** `origin/feat-FEAT-704-semantic-layer` is **0 commits ahead of `origin/dev`** and
carries no `examples/` delta; `origin/fix-semantic-packaging-test` is likewise empty. No prior attempt at
`examples/agents/semantic/` exists anywhere. *Evidence*: F011

`examples/agents/` itself is domain-foldered (`a2ui/`, `aws/`, `finance/`, `oauth/`, `webbrowser/`), last
touched 2026-10-02; commit convention `feat(<slug>): TASK-<NNN> — <title>`. *Evidence*: F012

---

## 3. Probable Scope

### What's New

- **`examples/agents/semantic/llm_metrics_agent.py`** — an Agent that **really calls the LLM** and lets it
  drive `sl_list_models` → `sl_get_dimensions` → `sl_query_metrics`. The only example exercising K2
  (`ask(permission_context=…)`). *Fills the single largest gap.*
- **`examples/agents/semantic/mcp_local_agent.py`** — the `LocalSemanticLayerToolkit` surface behind
  `parrot mcp-local semantic-layer`, executing **both an explicit allow and an explicit deny** against the
  real server factory — which `docs/tools/semantic-layer.md:148-157` demands but nothing currently runs.
- **`examples/agents/semantic/masked_policy_agent.py`** — a policy demo exercising `masks:` and
  `saved_queries:` (`policy.py:67,69`), supported but demonstrated in no YAML outside unit tests.
- **`examples/agents/semantic/multimodel_joins_agent.py`** — two models with a declared `one_to_many`
  relationship, `DATE_TRUNC` time grains, and the **fan-out rejection** that makes the layer fail loudly.
- **`examples/agents/semantic/models/`** — one shared, committed model + policy YAML pair the examples load
  (per D5), rather than each writing YAML into a tempdir.
- **`examples/agents/semantic/README.md`** — the per-subdirectory README, following the `aws/` + `a2ui/`
  precedent.
- **Four pin tests** in `packages/ai-parrot-semantic/tests/`, one per new example (per D4).
- **A new section in `docs/tools/semantic-layer.md`** (per D5) — ⚠️ test-affecting, see K10.

### What Changes

- **`examples/semantic/agent_semantic_example.py` → `examples/agents/semantic/agent_semantic_example.py`**
  — relocation only, no content change. *Evidence*: F001, F002
- **`examples/semantic/README.md` → `examples/agents/semantic/README.md`** — merged into the new README;
  its "For production, replace…" paragraph is worth preserving. *Evidence*: F001
- **`packages/ai-parrot-semantic/tests/test_example_agent.py:21`** — insert `"agents"` into `_EXAMPLE_PATH`.
  **One line.** *Evidence*: F002
- **`examples/semantic/README.md:3`** — the run command. *Evidence*: F002

### What's Untouched (Non-Goals)

- Any change under `packages/ai-parrot-semantic/src/**` — this feature adds **no library functionality**.
- Fixing open `issue:3c4d154c0172` (S3: `_pre_execute` static-subject fallback not channel-scoped; S5:
  `save_result_as_dataset` member recheck). The MCP-local example must simply not *imply* S3 is fixed.
- The HTTP surface (`SemanticLayerHandler`, `handlers/semantic.py:18`) — no example proposed for it.
- The OSSIE import format (`ossie.py:18-31`) — exercised only by unit tests; left that way.
- Any `.so`/native work, any `uv sync` inside a worktree.

### Patterns to Follow

- **`examples/agents/finance/hooba_agent.py`** is the template: `Usage::` docstring block (:3), module-level
  `SYSTEM_PROMPT`, `build_*` factories, `argparse` (:44), a deterministic `--smoke` no-LLM mode (:5,44,64),
  `asyncio.run(main())` (:78). *Evidence*: F005, F012
- **Not** `examples/basic_agent.py` / `examples/db_tool_usage.py` — bare `print()`, explicitly not the bar.
- The existing example's quality bar: fully type-hinted, Google-style docstrings, `logging` only.
- Reuse `connection_env()` (:268) rather than mutating `os.environ` — it restores on exit, and
  `test_build_toolkits_does_not_mutate_environment` pins that behaviour.

### Integration Risks

- **R1 — The pin test asserts on the example's SOURCE TEXT**, not just its behaviour:
  `test_pbac_is_wired_through_a_real_guard` asserts the literal string `"_pbac.available"` does **not**
  appear in the example's source. A new pin test modelled on it inherits that coupling. *Mitigation*: copy
  the assertion style deliberately, not by accident. *Evidence*: F002
- **R2 — Editing `docs/tools/semantic-layer.md` can break `test_mcp_local.py`**, which parses its fenced
  YAML/JSON blocks. *Mitigation*: add prose + a *new* block only if the test's parser tolerates it; run
  `pytest packages/ai-parrot-semantic/tests/test_mcp_local.py` before committing. *Evidence*: F004, F007 (K10)
- **R3 — Four examples is 2× the originally requested "un par".** *Mitigation*: see D2 — sequence them so
  the move + example #1 can land independently.
- **R4 — Examples are pytest-collected.** A file named `test_*.py` under `examples/agents/semantic/` would be
  collected by unrelated suites. *Mitigation*: K5 — never use that prefix. *Evidence*: F007
- **R5 — `issue:f0da823294fb` regression classes.** Four new examples are four new chances to re-introduce a
  placeholder guard, env leak, weak owner check or missing denial. *Mitigation*: make "shows a real denial
  that would fail if it silently succeeded" an acceptance criterion for every example. *Evidence*: F006, F010

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `examples/agents/semantic/` does not exist | F001, F012 | high | probe `c42`: path missing |
| C2 | The move breaks **exactly two** live references | F002 | high | probes `c31`,`c34` + exhaustive grep; nothing in any pyproject/ruff/pytest/CI/mkdocs mentions `examples/` |
| C3 | All ten `sl_*` signatures + the construction kwargs are as listed | F008 | high | probes `c0`–`c14`, every signature read from source |
| C4 | LLM-driven use needs `ask(permission_context=)` **and** the binding | F013 | high | full call-chain trace: `bots/base.py` → `tools/manager.py` → `tools/toolkit.py` → `_pre_execute` |
| C5 | No example currently lets an LLM drive the semantic tools | F001 | high | `build_agent` at :314 constructs an Agent that `run_demo` never uses |
| C6 | `examples/` is pytest-collected; never name a file `test_*.py` | F007 | high | re-verified inline after a mis-scoped probe; five such files already exist with pytest `__pycache__` |
| C7 | No unmerged branch already does this work | F011 | high | `git rev-list --count origin/dev..origin/feat-FEAT-704-semantic-layer` → `0` |
| C8 | Six closed ledger issues constrain the narrative | F006 | medium | inferred from issue bodies, not from re-reading each fix |
| C9 | Usage rights are narrower than the current example implies (K11) | F006 | medium | inferred from a closed issue body |
| C10 | The surface is stable enough to write examples against | F009 | medium | frozen 3 days — short baseline, and four behavioural fixes landed on the freeze day itself |

Distribution: **7** high, **3** medium, **0** low.

> The three `medium` claims (C8, C9, C10) are advisory constraints, not load-bearing for the
> recommendation. The decision to proceed rests on C1–C7, all high.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Where do the new examples live, given `examples/semantic/` already exists?** — *Resolved*:
  **Move + extend** — relocate the existing example into `examples/agents/semantic/` and add the new ones
  beside it, updating the pinning test's path. *(D1)* · *Resolves*: C2

- [x] **U1 — Which examples?** — *Resolved*: **all four** candidates selected — LLM-driven catalog→query,
  MCP-local allow+deny, masking/`saved_queries`, and multi-model joins + time grains. *(D2)*
  ⚠️ This supersedes the source's *"un par"* (a couple): scope is **four new examples**, five files counting
  the relocated one. · *Resolves*: scope, H3

- [x] **U2/U3 — Runnability and gating?** — *Resolved*: **deterministic `--smoke` default** (the
  `hooba_agent.py` pattern) with the LLM path opt-in, **plus a pin test per example** in
  `packages/ai-parrot-semantic/tests/` so CI covers them. DuckDB-only. *(D3, D4)* · *Resolves*: K7

- [x] **U4/U5 — Docs placement and YAML location?** — *Resolved*: **a section in
  `docs/tools/semantic-layer.md` as well as** `examples/agents/semantic/README.md`, and **one shared
  committed model+policy YAML pair** under the example directory. *(D5)* · *Resolves*: K10, K12

### Unresolved (defer to spec / implementation)

- [ ] **Does `test_mcp_local.py`'s doc-block parser tolerate an added fenced block in
  `docs/tools/semantic-layer.md`, or must the new section be prose-only?** — *Owner*: spec author
  *Blocks*: R2 · *Plausible answers*: a) parser keys on specific block content and tolerates extras ·
  b) it enumerates all blocks and a new one breaks it · c) add prose only and keep code in the README

- [ ] **Should the four examples land as one feature or be sequenced?** — *Owner*: tbd
  *Blocks*: R3 · *Plausible answers*: a) one spec, four tasks, one PR · b) move + example #1 first,
  the other three as a follow-up feature · c) one spec, four tasks, merged incrementally

- [ ] **Does the shared committed YAML need a second connection** (so the multi-model example can show
  cross-connection refusal), or does one DuckDB connection cover all four? — *Owner*: spec author
  *Blocks*: K12 · *Plausible answers*: a) one connection suffices · b) two, to demonstrate the boundary

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-768`** — *Rationale*: localization is probe-verified at HEAD (C1–C3, C6), the change is
additive with a two-line blast radius into existing code (C2), no prior attempt exists to reconcile (C7),
and all five scoping unknowns were resolved at the Q&A gate. There is no architectural fork to explore —
what remains is decomposition, plus three implementation-detail questions that belong in a spec's Open
Questions section.

### Alternatives

- **`/sdd-brainstorm FEAT-768`** — unnecessary: no competing architectures are in play; the only "options"
  were which surfaces to demonstrate, and that is now decided.
- **`/sdd-task`** — **not** suitable. Four examples + four pin tests + a committed YAML pair + a
  test-affecting doc edit is not a single trivial task.
- **Manual review** — not indicated; research completed without truncation.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-768/state.json` |
| Source (raw) | `sdd/state/FEAT-768/source.md` |
| Research plan | `sdd/state/FEAT-768/research_plan.json` |
| Findings (canonical) | `sdd/state/FEAT-768/findings/F001-*.md` … `F015-*.md` |
| Findings (lane originals) | `sdd/state/FEAT-768/findings/.audit/` (21 files: `FC-*`, `FG-*`, `FW-*`) |
| Citation probe sheet | `sdd/state/FEAT-768/probe_sheet.json` |
| Citation probe results | `sdd/state/FEAT-768/citation_checks.md` |
| Synthesis (JSON) | `sdd/state/FEAT-768/synthesis.json` |

**Budget consumed** (profile: `loose`):
- Files read: 39 / 100
- Grep calls: 17 / 60
- Git calls: 17 / 20
- Wall time: ~330 s / 900 s
- Truncated: **no**

**Execution**: Phase 2 ran **in parallel** across three lanes (codebase `FC`, git `FG`, wiki `FW`), merged
to 15 canonical findings (6 merged away), then fact-checked by two `sdd-contract-probe` agents.

**Mode determination**: `auto` → resolved to **`enrichment`** (no negation or failure language; the request
is additive against a shipped subsystem).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Probe HEAD | `7e6741f13` |
| Operator | Jesus Lara (`jlara@trocglobal.com`) |
