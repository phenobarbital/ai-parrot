---
id: FEAT-798
title: "Retire gemini-2.5-{pro,flash} before the 2026-12-01 shutdown: sweep the FEAT-796 builtins and ~25 hardcoded defaults to Gemini 4 Argon / 3.8-flash, delete the 2.5 members and prefix gates, and bump google-genai to a gate-verified 2.34.0"
slug: google-migration
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-11-04
  summary_oneline: "google-migration: upgrade google-genai, retire gemini-2.5-{pro,flash} from GoogleModel, parrot.conf defaults and pre-built parrot.bots agents; adopt Gemini 4 Argon"
overall_confidence: high
base_branch: dev
projects: [ai-parrot-client-google, ai-parrot, ai-parrot-server, ai-parrot-embeddings]
tags: [google-genai, gemini, model-catalog, deprecation, llm-defaults, migration]
research_state: sdd/state/FEAT-798/
created: 2026-11-04
updated: 2026-11-04
---

# FEAT-798 — Retire gemini-2.5-{pro,flash} and move the Google defaults to Gemini 4 Argon / 3.8-flash

> **Mode**: enrichment
> **Confidence**: high (medium before the Q&A; promoted once U1–U4 were resolved)
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-798/`](../state/FEAT-798/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at `sdd/state/FEAT-798/source.md`.

> Actualmente Google Gemini ha lanzado un deprecated de gemini-2.5-{pro,flash} para 1 de
> diciembre de 2026 (falta un mes), pero además gemini 4 argon ha sido lanzado, entonces
> necesitamos hacer un upgrade de la actual librería google-genai y a su vez hacer un retiro
> de gemini-2.5-{pro,flash} no solo del GoogleModel enum, sino como default en parrot.conf y
> en agentes pre-hechos en parrot.bots

**Initial signals** (extracted, not interpreted):
- Verbs: "upgrade", "retiro", "lanzado", "deprecated" → additive / migration (enrichment)
- Named entities: `google-genai`, `GoogleModel`, `gemini-2.5-pro`, `gemini-2.5-flash`, Gemini 4 Argon, `parrot.conf`, `parrot.bots`
- Deadline: 2026-12-01 (one month out)
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

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

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-798/findings/`. Each cites the finding ID(s) that
> justify its inclusion. 150 citations were probed at HEAD `c63e0798b3`; none of the paths below
> rests on a stale citation (see the `[citation-check]` notes in F002/F007/F020/F022/F024).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` | `GoogleModel` | 41-49, 59 | the 2.5 block: `GEMINI_2_5_FLASH` (+`_PREVIEW` alias), `_FLASH_LITE` (+alias), `_PRO`, `_FLASH_TTS`, `_PRO_TTS`, `_FLASH_IMAGE` (+alias), `GEMINI_COMPUTER_USE` | F003, F017 |
| 2 | same | `VertexAIModel` | 91-93 | `GEMINI_2_5_FLASH/_FLASH_LITE/_PRO` (untouched by FEAT-688) | F003, F022 |
| 3 | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | `_requires_thinking` | 303-314 | thinking gate still prefix-matches `gemini-2.5-pro` | F004 |
| 4 | same | `_is_computer_use_model` | 403-420 | still matches `gemini-2.5-computer-use` (id shut down 2026-07-28) | F004, F028 |
| 5 | same | fallback chains | 3370, 4253, 4792, 4935, 5227, 5330, 5636 | seven `GoogleModel.GEMINI_2_5_FLASH.value` fallbacks — AttributeError at import if the member goes first | F002 |
| 6 | same | `_default_model` / `_default_combined_call_prefixes` / `_default_reformat_model` | 128-133, 151-160, 171 | class defaults already 2.5-free; Argon leads the whitelist | F004, F010 |
| 7 | `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py` | method defaults | 64, 139, 631, 815, 914, 1075, 1130, 1185 | six `GEMINI_2_5_FLASH`, one `GEMINI_2_5_PRO`, one literal | F002, F001 |
| 8 | `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | method defaults | 405, 572, 2321 | `GEMINI_2_5_FLASH` and the speech default `GEMINI_2_5_FLASH_TTS` (dies 2026-11-17) | F002, F014, F028 |
| 9 | `packages/ai-parrot/src/parrot/llm_defaults.py` | `resolve_component_llm` | 47-59 | FEAT-796 resolver; hardcodes no model → unchanged | F009, F019 |
| 10 | `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` | `AgentHandler._create_agent` | 797-802 | AGENT builtin `google:gemini-2.5-pro` + a second literal fallback | F009, F001 |
| 11 | `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | `_CREW_BUILTIN_LLM` | 121, 135, 1834 | CREW builtin `google:gemini-2.5-pro` | F009, F006 |
| 12 | `packages/ai-parrot/src/parrot/experts/policy.py` | `DEFAULT_TIER_POLICY` | 10-14 | judgment 2.5-pro; balanced/templated 2.5-flash | F009 |
| 13 | `packages/ai-parrot/src/parrot/conf.py` | `ONTOLOGY_AQL_MODEL` | 165-166 | the only literal 2.5 fallback left in parrot.conf | F005, F024 |
| 14 | same | `DEFAULT_LLM_MODEL` / `DEFAULT_LLM` | 456-459, 250 | already `gemini-flash-latest`; `DEFAULT_LLM` unset by design | F005, F023 |
| 15 | `packages/ai-parrot/src/parrot/bots/base.py` | ask-path fallback | 487-495 | hard `gemini-2.5-flash` for Google clients | F006, F024 |
| 16 | `packages/ai-parrot/src/parrot/bots/voice.py` | text LLM | 437-438 | `gemini-2.5-flash` | F006 |
| 17 | `packages/ai-parrot/src/parrot/bots/scraper/scraper.py` | model resolution | 94-99 | last-resort `gemini-2.5-flash` | F006 |
| 18 | `packages/ai-parrot/src/parrot/bots/factory/builders/rag_builder.py`, `tool_agent_builder.py` | builder prompts | 29, 31 | LLM prompts steer generated configs to 2.5-flash | F006 |
| 19 | `packages/ai-parrot/src/parrot/loaders/abstract.py` | summary/translation defaults | 984-1103 | four `gemini-2.5-flash-lite` pins (NOT deprecated) | F001, F028 |
| 20 | `packages/ai-parrot/src/parrot/interfaces/images/plugins/classifybase.py`, `classify.py`, `analisys.py` | plugin ctors | 26, 55, 16 | `model_name` default 2.5-flash | F001 |
| 21 | `packages/ai-parrot/src/parrot/memory/episodic/reflection.py` | ctor | 94 | 2.5-flash | F001 |
| 22 | `packages/ai-parrot/src/parrot/setup/providers/google.py` | `default_model` | 16 | installer default 2.5-flash | F001 |
| 23 | `packages/ai-parrot/src/parrot/models/google.py` | `GoogleVoiceModel`; reel director | 13-28, 602 | core Live/TTS catalogue defaulting to `gemini-2.5-flash-native-audio-preview-12-2025` (dies 2026-11-17); director fallback 2.5-flash | F014, F028 |
| 24 | `packages/ai-parrot-server/src/parrot/handlers/google_generation.py` | `list_models` / `post` | 38-44, 107-115 | `/models` iterates the enum verbatim; POST default 2.5-flash | F013, F023 |
| 25 | `packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py` | deploy templates | 188-199 | generated `llm="google:gemini-2.5-flash"` | F001 |
| 26 | `packages/ai-parrot-server/src/parrot/e2e/models.py` | `LiveBudget.model` | 131 | `google:gemini-2.5-flash-lite` (not deprecated) | F001, F028 |
| 27 | `packages/ai-parrot/src/parrot/clients/factory.py` | `LLMFactory.list_models` | 231-253 | optional `deprecated_models` that the Google client does not define | F013, F016 |
| 28 | `packages/ai-parrot-client-google/pyproject.toml`, `packages/ai-parrot-embeddings/pyproject.toml`, `uv.lock` | google-genai pins | 34; 49-55; 6704-6705 | `>=2.31.0` floor, lock at exactly 2.31.0 | F007, F021 |
| 29 | `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json` | pricing rows | 3, 57-63 | stale (2026-06-10); only 2.5 *preview* rows, no Argon row | F011 |
| 30 | `docs/configuration/llm-defaults.md`, `docs/config.md` | defaults tables | 8-12; 224-225, 331 | publish the five 2.5 builtins; config.md documents a phantom `LLM_MODEL_NAME` alias | F008, F025, F005 |
| 31 | `packages/ai-parrot-server/ui/src/lib/config/regeneration-models.ts`, `.../agents/ChatInput.svelte` | `DEFAULT_MODEL`; picker options | 22-62; 203-204 | hand-maintained UI lists defaulting to 2.5-flash | F001 |
| 32 | `packages/ai-parrot/tests/clients/test_google_models.py`, `packages/ai-parrot/tests/test_google_models.py` | catalogue assertions | 11-26; 7-39, 56-59 | assert 2.5 values; `test_google_model_alias_count` pins 49/31 | F012, F003, F022, F010 |
| 33 | `packages/ai-parrot/tests/unit/test_llm_defaults.py`, `tests/experts/test_expert_llm_defaults.py`, `packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py`, `tests/bots/flows/crew/test_crew_llm_defaults.py` | FEAT-796 default tests | 21-51; 21-49; 63-134; 72-87 | assert the 2.5 builtins | F012, F019 |
| 34 | `packages/ai-parrot-client-google/tests/unit/test_unopened_client_lifecycle.py`, `packages/ai-parrot/tests/test_google_client.py` | lifecycle / gate tests | 48-100; 370-426 | use the members by name; 2.5 ids as non-whitelisted examples | F002, F012, F010 |
| 35 | `examples/orchestration/messaging.py`, `examples/crew/product_research_crew.json`, `examples/matrix_swarm/agents.yaml`, `plugins/agents/epson.py` and ~35 more | examples / plugins | — | ~75 gemini-2.5 mentions (in scope per U3) | F008 |

### 2.2 Constraints Discovered

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

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `8d5cb6ac3a` | 2026-11-04 | Jesus | feat(per-component-llm-defaults): TASK-5138 | `llm_defaults.py` (+79), `tests/unit/test_llm_defaults.py` |
| `28255feed6` | 2026-11-03 | Jesus | feat(per-component-llm-defaults): TASK-5137 | `conf.py` DEFAULT_LLM wiring |
| `aaee16b4b5` | 2026-11-01 | — | fix(unified-usage): TASK-5079 — client cache/reasoning counters | `client.py` |
| `7412fa1ccd` / `4f9d6383c3` | 2026-10-30 | phenobarbital | PR #1890 FEAT-781 — CachedContent + stream fixes | `client.py` |
| `e875799d5d` | 2026-10-22 | — | feat(model-deprecation-followups): TASK-4586 computer-use vocabulary | `client.py`, `test_computer_use_vocabulary.py` |
| `acd1dcc924` / `bf7d588bff` | 2026-10-16 | phenobarbital / Jesus | PR #1685 FEAT-688 merge; TASK-4371 align google-genai floor at 2.31.0 | both pyprojects, `uv.lock` |
| `c76b846670` | 2026-10-16 | Jesus | feat(gemini-upgrade): TASK-4370 — routing gates | `client.py`, `tests/test_google_client.py` |
| `0137c6595d` | 2026-10-16 | Jesus | feat(gemini-upgrade): TASK-4369 — Argon member | `models.py`, both catalogue test modules |

No commit in 90 days mentions a gemini-2.5 retirement or changes a Gemini default inside
`parrot.bots` (F017, F020). *Evidence*: F017–F021

---

## 3. Probable Scope  *(mode = enrichment)*

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

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | FEAT-688 (PR #1685, merged 2026-10-16) already added `GEMINI_4_ARGON`, whitelisted it and raised google-genai to `>=2.31.0`; it did not touch gemini-2.5 or any default | F022, F017, F020, F010 | high | spec Goals/Non-Goals read; git log shows merge + floor commit |
| C2 | Floor is `>=2.31.0` in both pyprojects, lock at 2.31.0; PyPI latest 2.34.0 (2026-10-29) | F007, F021, F027 | high | grep of pyprojects/uv.lock + PyPI JSON |
| C3 | `GoogleModel` carries nine 2.5 names (three aliases) + `GEMINI_COMPUTER_USE`; `VertexAIModel` three | F003 | high | line-exact read |
| C4 | Three 2.5 members are load-bearing by name (16 + 1 + 1 sites), all inside the client satellite | F002 | high | grep with file:line; re-verified by probe |
| C5 | The "parrot.conf defaults" are the FEAT-796 builtins (AGENT, CREW, EXPERT tiers) + `ONTOLOGY_AQL_MODEL`; `DEFAULT_LLM_MODEL` is already `gemini-flash-latest` | F009, F005, F025 | high | llm_defaults.py read in full; conf.py grep; docs match |
| C6 | Seven `parrot.bots` sites pin a 2.5 id; search/jira/github/a2a bots already use 3.x | F006, F026 | high | literal grep with excerpts |
| C7 | ~15 further src defaults pin 2.5-flash/pro; four pin flash-lite | F001, F014, F013 | high | grep inventory with file:line |
| C8 | Google shuts down 2.5-pro/flash on 2026-12-01 with auto-routing; flash-lite not deprecated; 2.5 TTS/native-audio shut down 2026-11-17 | F028 | high | official deprecation page, 2026-11-04 |
| C9 | `gemini-4-argon` is live but has no `createCachedContent` | F029, F022 | high | live `models.list` + FEAT-688 record agree |
| C10 | Retirement is pure deletion with no runtime remap | F016, F013, F022 | high | grep proves absence; factory read; FEAT-688 U2 |
| C11 | Deleting members changes `GET /models`; UI lists need separate edits | F013, F023, F001 | medium | handler read; UI "hand-maintained" inferred from literals |
| C12 | Eight test modules assert 2.5 values or use the members by name | F012, F002, F019 | high | grep with line numbers |
| C13 | Pricing table lacks GA 2.5 and Argon rows; cost attribution misses unless CostCalculator prefix-matches | F011 | medium | JSON keys read; matcher not read |
| C14 | Natural mapping: 2.5-pro → Argon (only pro-class 4.x id), 2.5-flash → a 3.x flash; no 4.x flash/lite exists | F010, F029, F003 | medium → resolved by U1 | single 4.x id in catalogue + live list |
| C15 | FEAT-188 is an unimplemented draft; its literal map is stale but its design rule stands | F024, F005, F006 | medium | status draft; literals survive at new lines; inferred from absence of a task index |
| C16 | "Only pro/flash" excludes flash-lite but should include TTS/native-audio defaults (earlier death) | F028, F014 | medium → resolved by U2 | deprecation page explicit; ownership was a product call |

Distribution: **11** high, **5** medium, **0** low. Overall: **high** after Q&A (the medium claims were
product choices or non-blocking; none is critical to the conclusion).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Which ids replace the retired defaults?** — *Resolved*: Argon for pro-class, `gemini-3.8-flash`
  for flash-class: AGENT, CREW, EXPERT judgment and the `analysis.py` pro site → `gemini-4-argon`; every
  flash-class default → `gemini-3.8-flash` (accepting that Argon components lose context caching).
  *Resolves claims*: C14, C9
- [x] **U2 — How much of the 2.5 family goes?** — *Resolved*: pro, flash, both TTS members, computer-use and
  the voice defaults; move `GoogleVoiceModel` + speech defaults to `gemini-3.8-live` / `gemini-3.8-flash-tts`;
  keep `gemini-2.5-flash-lite` and `gemini-2.5-flash-image`. *Resolves claims*: C16, C3
- [x] **U3 — Which surfaces are in scope?** — *Resolved*: everything, including `examples/` and `plugins/`:
  src, normative docs, admin UI lists, deploy templates, `VertexAIModel` 2.5 members and the ~75
  example/plugin/doc mentions. *Resolves claims*: C11, C3
- [x] **U4 — SDK floor?** — *Resolved*: bump to the newest gate-verified google-genai at implementation
  time (2.34.0 today) via the TASK-4371 isolated-venv introspection; both pyprojects + `uv.lock`.
  *Resolves claims*: C2

### Unresolved (defer to spec / implementation)

- [ ] **Does `CostCalculator` prefix-match model ids (so a missing `gemini-4-argon` row degrades gracefully)?** — *Owner*: tbd (spec research)
  *Blocks claims*: C13 · *Plausible answers*: a) exact-key lookup → add rows · b) prefix match → rows still desirable
- [ ] **Is `bots/search.py:71` `google:gemini-3-flash` (not a catalogue value) a pre-existing drift to fix in passing?** — *Owner*: tbd
  *Blocks claims*: — (outside this feature's 2.5 scope; F006/F026 flagged it)
- [ ] **Argon pricing figures** for `pricing/google.json` — *Owner*: operator (external input)

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-798`** — *Rationale*: localization is high-confidence with a one-month-old precedent
(FEAT-688) for the exact edit shape; the four product decisions are resolved; no architectural fork
remains. The spec should re-probe `client.py` anchors at HEAD (15 commits since FEAT-688) and sequence
tasks so the enum deletion never precedes the client-satellite call-site rewrite.

### Alternatives

- **`/sdd-brainstorm FEAT-798`** — only if the Argon-without-caching trade-off (C9) should be revisited
  as an architectural question (e.g. a capability-metadata refactor of the prefix gates, which FEAT-688
  explicitly deferred).
- **`/sdd-task FEAT-798`** — not suitable: the sweep spans four distributions, a public HTTP surface,
  the UI and an SDK bump.
- **Interim mitigation (no code)** — set `DEFAULT_LLM=google:gemini-4-argon` (or per-component vars) in
  deployments that cannot wait for the release; voice defaults have no env override and die 2026-11-17.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-798/state.json` |
| Source (raw) | `sdd/state/FEAT-798/source.md` |
| Research plan | `sdd/state/FEAT-798/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-798/findings/F001-*.md` … `F029-*.md` (lane originals in `findings/.audit/`) |
| Synthesis (JSON) | `sdd/state/FEAT-798/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed** (default profile, three parallel lanes + merge):
- Files read: 25 / 40
- Grep calls: 20 / 25
- Git calls: 5 / 10
- Wall time: ~390s / 300s research window (lanes finished inside their 255s slice; merge + probe ran after)
- Truncated: **no**
- Citation probe: 150 checks, 4 `sdd-contract-probe` agents, HEAD `c63e0798b3`; 19 misses, all sheet artifacts or
  explicitly historical citations (tagged in F002/F007/F020/F022/F024)
- External sources (F027–F029): PyPI JSON, Google's deprecation page, live `v1beta/models` — cited for facts, never for codebase paths

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs: "upgrade", "retiro"; no negation).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` (FEAT-708 parallel lanes + citation probe) |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jlara@trocglobal.com |
