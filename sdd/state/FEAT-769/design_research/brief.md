<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
examples/semantic/agent_semantic_example.py
examples/semantic/README.md
examples/agents/finance/hooba_agent.py
packages/ai-parrot-semantic/tests/test_example_agent.py
packages/ai-parrot-semantic/tests/test_mcp_local.py
packages/ai-parrot-semantic/tests/fixtures/models/orders.yml
packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml
packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py
packages/ai-parrot-semantic/src/parrot/semantic/context.py
packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py
packages/ai-parrot-semantic/src/parrot/semantic/handoff.py
packages/ai-parrot-semantic/src/parrot/semantic/models.py
packages/ai-parrot-semantic/src/parrot/semantic/policy.py
packages/ai-parrot-semantic/src/parrot/semantic/results.py
docs/tools/semantic-layer.md
ruff.toml
pytest.ini
.github/workflows/ci.yml

### Questions still open in the exploration document
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

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
