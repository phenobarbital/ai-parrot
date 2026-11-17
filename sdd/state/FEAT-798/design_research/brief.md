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
framework for AI agents (aiohttp, Pydantic v2).
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
Actualmente Google Gemini ha lanzado un deprecated de gemini-2.5-{pro,flash} para 1 de
diciembre de 2026 (falta un mes), pero además gemini 4 argon ha sido lanzado, entonces
necesitamos hacer un upgrade de la actual librería google-genai y a su vez hacer un retiro
de gemini-2.5-{pro,flash} no solo del GoogleModel enum, sino como default en parrot.conf y
en agentes pre-hechos en parrot.bots

Half of the request has already shipped: FEAT-688 (PR #1685, merged 2026-10-16) added
`GoogleModel.GEMINI_4_ARGON`, whitelisted it in the client's combined-call prefixes and raised
the `google-genai` floor to `>=2.31.0`, while explicitly leaving gemini-2.5 and every default
untouched. What remains is the retirement itself. The "defaults in parrot.conf" the request names
are, in practice, the FEAT-796 `builtin=` strings merged two days ago (AGENT and CREW on
`google:gemini-2.5-pro`, the EXPERT tiers on 2.5-pro/2.5-flash, resolved by
`packages/ai-parrot/src/parrot/llm_defaults.py`) plus one literal left in
`packages/ai-parrot/src/parrot/conf.py` (`ONTOLOGY_AQL_MODEL`); the global `DEFAULT_LLM_MODEL`
is already `gemini-flash-latest`. Around those sit seven `parrot.bots` sites, ~15 further src
defaults (handlers, image plugins, episodic reflection, the installer, the video-reel director,
deploy templates), the 2.5 block of the catalogue in
`packages/ai-parrot-client-google/src/parrot/clients/google/models.py` with 18 by-name
references inside the Google client satellite, two prefix gates in `client.py`, the public
`GET /models` payload, the hand-maintained admin UI lists, eight test modules and two normative
docs. Google's own schedule reshapes the scope: the 2.5 TTS and native-audio previews die on
2026-11-17 (two weeks earlier), the 2.5 computer-use id died in July, `gemini-2.5-flash-lite` is
not deprecated, and Google's recommended replacements are 3.x models — choosing Argon is a
product decision, now taken (U1), with the known cost that Argon has no context caching. The
recommendation is `/sdd-spec FEAT-798` following the FEAT-688 edit shape, with a gate-verified
`google-genai` bump (2.34.0 today) as the SDK half.

### Constraints and goals
- **Plain `Enum` alias collapse.** Duplicate values are silent aliases; `test_google_model_alias_count`
  pins 49 names / 31 values. *Implication*: every deletion updates that test in the same task; three
  of the 2.5 names vanish with their canonical member. *Evidence*: F003, F022
- **Load-bearing names.** `GEMINI_2_5_FLASH` ×16 (client.py, analysis.py, generation.py),
  `GEMINI_2_5_PRO` ×1, `GEMINI_2_5_FLASH_TTS` ×1. *Implication*: rewrite the call sites in the same
  commit as (or before) the deletion, or `client.py` fails at import. *Evidence*: F002
- **Routing is by string prefix, not enum membership.** `_requires_thinking`, `_is_computer_use_model`,
  `_default_combined_call_prefixes`, `_model_class_key`. *Implication*: drop the `gemini-2.5-pro` and
  `gemini-2.5-computer-use` prefixes with the members (FEAT-688: "a dead prefix is worse than a dead
  member"); unknown ids silently take the legacy two-phase path. *Evidence*: F004, F022
- **Retirement is pure deletion.** No `deprecated_models` registry (FEAT-688 U2); nothing remaps a
  retired id at runtime. *Implication*: a caller still passing `gemini-2.5-flash` is not redirected by
  parrot — Google auto-routes it after 2026-12-01. *Evidence*: F016, F022, F013
- **`GET /models` publishes `[m.value for m in GoogleModel]`.** *Implication*: a public payload change;
  the admin UI lists are not generated from it. *Evidence*: F013, F023, F001
- **Argon has no `createCachedContent`** (live `models.list` and the FEAT-688 spec agree); FEAT-781
  (PR #1890) made the Gemini cache path fail-open. *Implication*: components moved to Argon lose
  context caching silently; the spec must assert the fail-open path. *Evidence*: F029, F022, F020
- **Google's schedule ≠ the request's scope.** 2.5-pro → `gemini-3.8-flash`, 2.5-flash →
  `gemini-3.5-flash-lite`; `gemini-2.5-flash-lite` not deprecated; 2.5 TTS / native-audio previews shut
  down 2026-11-17; 2.5 computer-use shut down 2026-07-28; flash-image lives to 2027-03-15.
  *Implication*: flash-lite pins stay; the voice/TTS defaults are the more urgent cut. *Evidence*: F028, F029
- **Floor policy: declare only an exercised version.** TASK-4371's isolated-venv introspection gate;
  PyPI latest 2.34.0 vs declared/locked 2.31.0, weekly cadence. *Evidence*: F007, F021, F027
- **The 2.5 builtins are two days old** (FEAT-796, PR #1949) and four test modules assert them.
  *Implication*: three string edits + docs table + tests move together. *Evidence*: F009, F019, F012
- **`client.py` is hot** (15 commits / 90 days, four lanes); `conf.py` 15 commits / 60 days.
  *Implication*: FEAT-688 anchors are stale; the spec's Codebase Contract must be re-probed at HEAD.
  *Evidence*: F018, F019
- **A zero-code mitigation exists**: `DEFAULT_LLM`, `AGENT_LLM`, `CREW_LLM`, `EXPERT_*_LLM` override every
  builtin today. *Evidence*: F025, F009
- **The pricing table has no GA 2.5 rows and no Argon row** and is already flagged stale by
  `CostCalculator`. *Evidence*: F011

### Recommended option / probable scope
### What's New

- **Pricing rows** for `gemini-4-argon` (and `gemini-3.8-flash` if missing) in
  `observability/cost/pricing/google.json` — Argon pricing is an external input. *Evidence*: F011
- **A regression guard test** asserting no `gemini-2.5-pro` / `gemini-2.5-flash` literal survives under
  `packages/*/src` (flash-lite and flash-image excluded). *Evidence*: F001, F028
- **A gate-verified `google-genai` floor bump** (2.31.0 → 2.34.0 candidate) reusing the TASK-4371
  blueprint, both pyprojects + `uv.lock`, operator `uv sync` after merge. *Evidence*: F007, F021, F027

### What Changes

Replacement mapping (U1): **pro-class → `gemini-4-argon`**, **flash-class → `gemini-3.8-flash`**.

- **`models.py`::`GoogleModel` / `VertexAIModel`** — delete `GEMINI_2_5_PRO`, `GEMINI_2_5_FLASH`
  (+`_PREVIEW`), `GEMINI_2_5_FLASH_TTS`, `GEMINI_2_5_PRO_TTS`, `GEMINI_COMPUTER_USE`, and the three
  Vertex 2.5 members (U2/U3); keep `_FLASH_LITE` (+alias) and `_FLASH_IMAGE` (+alias). *Evidence*: F003, F028
- **`client.py`** — drop the `gemini-2.5-pro` and `gemini-2.5-computer-use` prefixes; replace the seven
  `GEMINI_2_5_FLASH.value` fallbacks with `self._default_model` or `gemini-3.8-flash`; refresh the
  2.5-pro docstrings (110-117, 164, 569, 1819, 1857, 3507). *Evidence*: F004, F002
- **`analysis.py` / `generation.py`** — flash sites → 3.8-flash, `analysis.py:815` → Argon, speech default
  → `gemini-3.8-flash-tts`. *Evidence*: F002, F014, F028
- **`handlers/agents/abstract.py`::`_create_agent`**, **`crew.py`::`_CREW_BUILTIN_LLM`**,
  **`experts/policy.py`::`DEFAULT_TIER_POLICY`** — AGENT/CREW/judgment → `google:gemini-4-argon`;
  balanced/templated → `google:gemini-3.8-flash`. *Evidence*: F009
- **`conf.py`::`ONTOLOGY_AQL_MODEL`** — fallback → `gemini-3.8-flash` (or `DEFAULT_LLM_MODEL`). *Evidence*: F005, F024
- **`bots/base.py`, `voice.py`, `scraper.py`, the two builder prompts, `abstract.py` /
  `model_switching.py` docstrings** — 2.5-flash → 3.8-flash / `DEFAULT_LLM_MODEL`. *Evidence*: F006, F024
- **Image plugins ×3, `memory/episodic/reflection.py:94`, `setup/providers/google.py:16`,
  `models/google.py:602`** — 2.5-flash → 3.8-flash. *Evidence*: F001, F014
- **`models/google.py`::`GoogleVoiceModel`** — `DEFAULT` and the 2.5 native-audio/TTS members →
  `gemini-3.8-live` / `gemini-3.8-flash-tts` (U2: this feature owns it; the ids die 2026-11-17). *Evidence*: F014, F028, F029
- **`handlers/google_generation.py`::`post`**, **`autonomous/deploy/templates.py`** — defaults → 3.8-flash;
  `/models` shrinks automatically. *Evidence*: F013, F001
- **Both pyprojects + `uv.lock`** — floor bump. *Evidence*: F007, F021, F027
- **`docs/configuration/llm-defaults.md`, `docs/config.md`** — rewrite the builtin rows; drop the phantom
  `LLM_MODEL_NAME` alias. *Evidence*: F025, F008, F005
- **`regeneration-models.ts`, `ChatInput.svelte`** — UI lists and default → successor ids (U3). *Evidence*: F001
- **`examples/`, `plugins/agents/epson.py`** — ~75 mentions swept (U3). *Evidence*: F008
- **Tests** — both catalogue modules (re-pin alias count), `test_llm_factory.py`, `test_google_client.py`
  (negative cases may switch to 2.0 ids), `test_unopened_client_lifecycle.py`, the four FEAT-796 default
  tests. *Evidence*: F012, F002, F017

### What's Untouched (Non-Goals)

- `parrot/llm_defaults.py` resolver logic and the `<COMPONENT>_LLM` → `DEFAULT_LLM` cascade. *Evidence*: F009
- `GoogleGenAIClient` class defaults (`_default_model`, `_fallback_model`, `_lightweight_model`,
  `_default_reformat_model`) — already 3.x / flash-latest. *Evidence*: F004
- `ai-parrot-embeddings`, `-loaders`, `-tools`, `-integrations` src — no 2.5 ids. *Evidence*: F015
- `gemini-2.5-flash-lite` pins (`loaders/abstract.py` ×4, `e2e/models.py:131`) and `gemini-2.5-flash-image`. *Evidence*: F028, F001
- `parrot/clients/base.py` and the prefix-gate architecture (no capability-metadata refactor). *Evidence*: F022
- A `deprecated_models` registry — rejected by FEAT-688 U2. *Evidence*: F016, F022

### Patterns to Follow

- **FEAT-688 shape**: enum edit + prefix-gate edit + both catalogue test modules in one stroke, verified
  against a live `models.list` before deciding what is dead (`0137c6595d`, `c76b846670`). *Evidence*: F017, F018, F022
- **TASK-4371 floor blueprint**: isolated-venv introspection one-liner, declare only the exercised version,
  `uv lock --upgrade-package`, operator `uv sync` after merge. *Evidence*: F007, F021
- **FEAT-188 design rule**: runtime fallbacks read `conf.DEFAULT_LLM_MODEL`, client-internal defaults read
  `GEMINI_FLASH_LATEST.value` — replacing literals with the alias avoids the next sweep. *Evidence*: F024, F005
- **FEAT-796 builtins** are the single place a component's shipped default lives; the docs table mirrors them. *Evidence*: F009, F025

### Integration Risks

- **Argon lacks context caching**: AGENT/CREW/judgment lose the FEAT-781 cache path (fail-open, so no
  crash; silent cost/latency change). Mitigation: assert the fail-open branch in the spec's tests; document
  `AGENT_LLM=google:gemini-3.8-flash` as the caching-preserving override. *Evidence*: F029, F022
- **Alias-count test** fails on every catalogue edit; **load-bearing names** (18 sites) break import if
  task order is wrong. Mitigation: one task owns enum + client satellite call sites. *Evidence*: F003, F002, F022
- **Voice/TTS ids die 2026-11-17**: leaving `GoogleVoiceModel.DEFAULT` for a follow-up means two weeks of
  broken voice defaults. Mitigation: in scope (U2). *Evidence*: F014, F028
- **Over-counting**: stale `build/lib*` artifacts and docs inflate the sweep; the guard test scopes to `src/`. *Evidence*: F001, F008
- **Pricing**: no Argon row → usage/cost dashboards under-report the new default. *Evidence*: F011
- **Silent auto-routing after 2026-12-01**: any pin missed by the sweep keeps working but changes model and
  bill. Mitigation: the regression guard. *Evidence*: F028

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-client-google/src/parrot/clients/google/models.py
packages/ai-parrot-client-google/src/parrot/clients/google/client.py
packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py
packages/ai-parrot-client-google/src/parrot/clients/google/generation.py
packages/ai-parrot/src/parrot/llm_defaults.py
packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py
packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
packages/ai-parrot/src/parrot/experts/policy.py
packages/ai-parrot/src/parrot/conf.py
packages/ai-parrot/src/parrot/bots/base.py
packages/ai-parrot/src/parrot/bots/voice.py
packages/ai-parrot/src/parrot/bots/scraper/scraper.py
packages/ai-parrot/src/parrot/bots/factory/builders/rag_builder.py
packages/ai-parrot/src/parrot/loaders/abstract.py
packages/ai-parrot/src/parrot/interfaces/images/plugins/classifybase.py
packages/ai-parrot/src/parrot/memory/episodic/reflection.py
packages/ai-parrot/src/parrot/setup/providers/google.py
packages/ai-parrot/src/parrot/models/google.py
packages/ai-parrot-server/src/parrot/handlers/google_generation.py
packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py
packages/ai-parrot-server/src/parrot/e2e/models.py
packages/ai-parrot/src/parrot/clients/factory.py
packages/ai-parrot-client-google/pyproject.toml
packages/ai-parrot-embeddings/pyproject.toml
packages/ai-parrot/src/parrot/observability/cost/pricing/google.json
docs/configuration/llm-defaults.md
docs/config.md
packages/ai-parrot-server/ui/src/lib/config/regeneration-models.ts
.../agents/ChatInput.svelte
packages/ai-parrot/tests/clients/test_google_models.py
packages/ai-parrot/tests/test_google_models.py
packages/ai-parrot/tests/unit/test_llm_defaults.py
tests/experts/test_expert_llm_defaults.py
packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py
tests/bots/flows/crew/test_crew_llm_defaults.py
packages/ai-parrot-client-google/tests/unit/test_unopened_client_lifecycle.py
packages/ai-parrot/tests/test_google_client.py
examples/orchestration/messaging.py
examples/crew/product_research_crew.json
examples/matrix_swarm/agents.yaml
plugins/agents/epson.py

### Questions still open in the exploration document
- [ ] **Does `CostCalculator` prefix-match model ids (so a missing `gemini-4-argon` row degrades gracefully)?** — *Owner*: tbd (spec research)
- [ ] **Is `bots/search.py:71` `google:gemini-3-flash` (not a catalogue value) a pre-existing drift to fix in passing?** — *Owner*: tbd
- [ ] **Argon pricing figures** for `pricing/google.json` — *Owner*: operator (external input)

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
