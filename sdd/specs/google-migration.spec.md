---
type: feature
base_branch: dev
projects: [ai-parrot-client-google, ai-parrot, ai-parrot-server, ai-parrot-embeddings]
tags: [google-genai, gemini, model-catalog, deprecation, llm-defaults, migration]
---

# Feature Specification: Retire gemini-2.5-{pro,flash} — move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai

**Feature ID**: FEAT-798
**Date**: 2026-11-04
**Author**: jlara@trocglobal.com
**Status**: approved
**Target version**: next minor release — M4 (voice/TTS) must ship before **2026-11-17**, everything else before **2026-12-01**

---

## 1. Motivation & Business Requirements

### Problem Statement

Google shuts down `gemini-2.5-pro` and `gemini-2.5-flash` on **2026-12-01**; API requests are then
auto-routed to `gemini-3.8-flash` / `gemini-3.5-flash-lite` and billed at the new model's rate. The
2.5 TTS and native-audio previews die earlier, on **2026-11-17**, and `gemini-2.5-computer-use-preview`
already died on 2026-07-28 (proposal F028). AI-Parrot still ships 2.5 ids as **defaults**: the
FEAT-796 component builtins merged on 2026-11-03 (`AGENT`/`CREW` → `google:gemini-2.5-pro`, the EXPERT
tiers → 2.5-pro/2.5-flash), one literal in `conf.py` (`ONTOLOGY_AQL_MODEL`), seven `parrot.bots`
sites, ~15 further src defaults (handlers, image plugins, episodic reflection, installer, video-reel
director, deploy templates), the Live/TTS catalogue `GoogleVoiceModel.DEFAULT`, the `GoogleModel`
2.5 block with 18 by-name references inside the Google client satellite, and the admin UI model lists.
FEAT-688 (PR #1685, merged 2026-10-16) already added `GEMINI_4_ARGON` and raised the `google-genai`
floor to `>=2.31.0`, but deliberately left every 2.5 id and every default untouched (proposal F022).
Nothing in the repo remaps a retired id at runtime (no `deprecated_models`, FEAT-688 U2), so every
missed pin keeps working after 12-01 while silently changing model and bill.

Research: `sdd/proposals/google-migration.proposal.md` (accepted), audit `sdd/state/FEAT-798/`.

### Goals

- **G1 — Defaults off 2.5.** Pro-class defaults (AGENT, CREW, EXPERT judgment, `analysis.py:815`)
  become `gemini-4-argon`; every flash-class default becomes `gemini-3.8-flash` (proposal U1).
- **G2 — Catalogue retirement by deletion.** Delete `GEMINI_2_5_PRO`, `GEMINI_2_5_FLASH`
  (+`_PREVIEW` alias), `GEMINI_2_5_FLASH_TTS`, `GEMINI_2_5_PRO_TTS`, `GEMINI_COMPUTER_USE` from
  `GoogleModel` and `GEMINI_2_5_FLASH` / `GEMINI_2_5_PRO` from `VertexAIModel`; keep every
  `flash-lite` and `flash-image` member (not deprecated / shut down 2027-03-15) (U2, U3).
- **G3 — Dead prefixes go with dead members.** `_requires_thinking` stops matching `gemini-2.5-pro`
  and `_is_computer_use_model` stops matching `gemini-2.5-computer-use` (FEAT-688 rule).
- **G4 — Voice/TTS before 11-17.** `GoogleVoiceModel` loses its 2.5 native-audio/TTS members and
  defaults to `gemini-3.8-live`; `generate_speech` defaults to `gemini-3.8-flash-tts` (U2).
- **G5 — Every surface.** Normative docs, admin UI lists, deploy templates, `examples/`, `plugins/`
  and the Google pricing table follow the code (U3); a regression guard keeps `src/` clean.
- **G6 — SDK floor.** `google-genai` floor raised from `>=2.31.0` to the newest version that passes the
  TASK-4371 introspection gate (2.34.0 on 2026-11-04), declared in both pyprojects and `uv.lock` (U4).
- **G7 — Precedent shape.** Enum + gates + both catalogue test modules move together, verified against
  a live `models.list`, exactly as FEAT-688 did.

### Non-Goals (explicitly out of scope)

- **No change to `GoogleGenAIClient` class defaults** — `_default_model` (`gemini-flash-latest`),
  `_fallback_model` / `_lightweight_model` (`gemini-3.1-flash-lite`), `_default_reformat_model`
  (`gemini-3.5-flash`) are already 2.5-free and stay (FEAT-688 U4).
- **No `deprecated_models` registry, no runtime alias/redirect** of a retired id (FEAT-688 U2; nothing
  consults that mapping — `factory.py:253` only lists its keys).
- **No refactor of the prefix gates into capability metadata** on the enum (FEAT-688 non-goal).
- **`gemini-2.5-flash-lite` and `gemini-2.5-flash-image` stay** everywhere they are pinned
  (`loaders/abstract.py` ×4, `e2e/models.py:131`, the four `*_LITE*`/`*_IMAGE*` members).
- **No change to `parrot/llm_defaults.py`** — the resolver hardcodes no model.
- **`bots/search.py:71` (`google:gemini-3-flash`, not a catalogue value)** is a pre-existing drift
  outside the 2.5 scope — see §8 Q2.
- **`parrot/clients/base.py`** is untouched (two docstring mentions of 2.5-pro at :373 and :2143 are
  historical commentary, not defaults).
- **No new 4.x members beyond `GEMINI_4_ARGON`** — Google serves no 4.x flash/lite tier (F029).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:d9e004e29c0379f8051d0bbddfd54558385d2f37364c21258725094118c67f6d evaluation_digest=sha256:f820c92f8ea48c6d460db9d509683f5675c2d62d0e32554fa3187b4539e9ce92 rules_version=1 status=pass -->

No eligible decisions govern subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, server, skills, tools

## 2. Architectural Design

### Overview

This is a **sweep with a fixed replacement table**, not a design change. The replacement mapping
(U1) is applied uniformly:

| Retired id / member | Class | Replacement | Where it is used |
|---|---|---|---|
| `gemini-2.5-pro` / `GEMINI_2_5_PRO` | pro | `gemini-4-argon` / `GoogleModel.GEMINI_4_ARGON` | AGENT, CREW, EXPERT judgment builtins; `analysis.py:815`; handler literal; UI "Gemini 2.5 Pro" |
| `gemini-2.5-flash` / `GEMINI_2_5_FLASH` (+`_PREVIEW`) | flash | `gemini-3.8-flash` / `GoogleModel.GEMINI_3_8_FLASH` | EXPERT balanced/templated; `ONTOLOGY_AQL_MODEL`; bots; image plugins; reflection; installer; reel director; handler POST; deploy templates; 7 client fallbacks; 7 method defaults; UI |
| `gemini-2.5-flash-preview-tts` / `GEMINI_2_5_FLASH_TTS`, `GEMINI_2_5_PRO_TTS` | tts | `gemini-3.8-flash-tts` / `GoogleModel.GEMINI_3_8_FLASH_TTS` (new) | `generate_speech` default; `GoogleVoiceModel.GEMINI_2_5_FLASH_PREVIEW_TTS` |
| `gemini-2.5-flash-native-audio-preview-*` (3 members) | live | `gemini-3.8-live` / `GoogleVoiceModel.GEMINI_3_8_LIVE` (new) → `GoogleVoiceModel.DEFAULT` | `GeminiLiveClient._default_model` (reads `DEFAULT`) |
| `gemini-2.5-computer-use-preview-10-2025` / `GEMINI_COMPUTER_USE` | computer-use | deleted; `_is_computer_use_model` keeps only `gemini-3-flash-preview` | computer-use gate; two catalogue tests; vocabulary test |

Three ordering rules make the sweep safe:

1. **Add before delete.** M1 adds `GEMINI_3_8_FLASH_TTS` / `GEMINI_3_8_LIVE` (and the voice members in
   M4); M2 rewrites the 18 by-name call sites in the client satellite; only then does M5 delete the 2.5
   members. A deletion that precedes the rewrite is an `AttributeError` at `import parrot.clients.google.client`.
2. **Dead prefix with dead member.** M2 drops the `gemini-2.5-pro` and `gemini-2.5-computer-use`
   prefixes in the same stroke as the fallbacks; an unknown id is never rejected by the client, it just
   takes the legacy two-phase path (`client.py:117`).
3. **Argon loses caching, by decision.** `gemini-4-argon` has no `createCachedContent` (F029, FEAT-688
   spec §131-158). `_maybe_apply_gemini_cache` (`client.py:548`) is fail-open (logs WARNING, returns the
   payload unchanged), so the components moved to Argon lose context caching without crashing. The
   caching-preserving operator escape is `AGENT_LLM=google:gemini-3.8-flash` (documented in M3's docs).

**Fallback policy (one rule, codex S3).** Inside the client satellite every *method default* and every
*fallback chain* that named `GEMINI_2_5_FLASH` names `GoogleModel.GEMINI_3_8_FLASH` — never
`self._default_model`. The instance-level `_default_model` (`gemini-flash-latest`, `client.py:130`) is a
FEAT-688 non-goal and stays; it only applies when a caller constructs the client without a model. So
`ask`, `ask_stream`, batch, `question` and every `analysis.py` path agree on `gemini-3.8-flash` once the
literals are replaced, and `test_no_retired_gemini_literal_in_src` plus AC-4 keep them aligned.

Everything else is literal replacement plus the tests and docs that pin the literals. Operators keep
the zero-code escape they already have (`DEFAULT_LLM`, `AGENT_LLM`, `CREW_LLM`, `EXPERT_*_LLM`); the
voice default has no env override, which is why M4 carries the earlier deadline.

### Component Diagram

```
                 M1 GoogleModel additions ──────────┐
                 (GEMINI_3_8_FLASH_TTS, _3_8_LIVE)   │
                            │                        │
                            ▼                        ▼
 M2 client satellite rewrite + gates        M4 GoogleVoiceModel (core models/google.py)
 (client.py, analysis.py, generation.py)    (3.8-live DEFAULT, reel director default)
                            │                        │
 M3 component defaults ─────┼────────────────────────┤      M6 google-genai floor (exclusive: uv.lock)
 (FEAT-796 builtins, conf,  │                        │
  bots, handlers, plugins,  │                        │      M7 non-Python surfaces
  docs llm-defaults/config) │                        │      (UI lists, pricing JSON, docs, examples, plugins)
                            ▼                        ▼                       │
                 M5 catalogue deletion + alias-count tests + regression guard ◄┘
                 (models.py 2.5 block, VertexAIModel, both catalogue tests, guard test)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GoogleModel` / `VertexAIModel` (`clients/google/models.py`) | modifies | +2 members (M1), −6/−2 members (M5) |
| `GoogleGenAIClient` gates + fallbacks (`clients/google/client.py`) | modifies | prefix tuples at :313 and :420; seven `GEMINI_2_5_FLASH.value` fallbacks; `question()` default :5636; docstrings |
| `GoogleAnalysis` / `GoogleGeneration` mixins (`analysis.py`, `generation.py`) | modifies | method defaults; `generate_speech` → `GEMINI_3_8_FLASH_TTS` |
| `resolve_component_llm` (`parrot/llm_defaults.py:47`) | uses (unchanged) | the three `builtin=` strings at its call sites change, not the resolver |
| `AgentHandler._create_agent` (`handlers/agents/abstract.py:797-802`) | modifies | AGENT builtin + literal fallback |
| `_CREW_BUILTIN_LLM` (`bots/flows/crew/crew.py:121`) | modifies | CREW builtin |
| `DEFAULT_TIER_POLICY` (`experts/policy.py:10-14`) | modifies | EXPERT tier builtins |
| `GoogleVoiceModel` (`parrot/models/google.py:13`) → `GeminiLiveClient._default_model` (`live.py:376`) | modifies enum; client unchanged | `live.py` reads `GoogleVoiceModel.DEFAULT.value` — flipping `DEFAULT` is the whole change |
| `GoogleGenerationHandler.list_models` (`handlers/google_generation.py:44`) | affected (no edit) | publishes `[m.value for m in GoogleModel]` — payload shrinks by five values |
| `CostCalculator` (`observability/cost/calculator.py:301`) | data change | exact-key `provider_pricing.get(model)` — no prefix match, so `google.json` needs a `gemini-4-argon` row |
| `LLMFactory.list_models` (`clients/factory.py:247-253`) | affected (no edit) | `active` shrinks; `deprecated` stays empty |

### Data Models

No new data models. Enum deltas only (see Module 1, 4 and 5 skeletons).

### New Public Interfaces

No new classes or functions. Two new enum members on `GoogleModel`
(`GEMINI_3_8_FLASH_TTS`, `GEMINI_3_8_LIVE`) and two on `GoogleVoiceModel`
(`GEMINI_3_8_LIVE`, `GEMINI_3_8_FLASH_TTS`); one new test module (the regression guard).

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: GoogleModel additions | yes | `models.py` only — two members, exact values and insertion anchors below | — |
| M2: Client satellite rewrite + gates | yes | exact `path:NN` for all 18 by-name sites, both prefix tuples, `question()` default, docstrings | — |
| M3: Component defaults sweep | yes | replacement table in §2 + exact anchors; FEAT-796 tests re-asserted on the new literals | — |
| M4: Voice/TTS catalogue | yes | `GoogleVoiceModel` end state below; `live.py` untouched | — |
| M5: Catalogue deletion + guard | yes | exact member lines, post-condition 45 names / 28 values, guard test contract | — |
| M6: google-genai floor | yes | TASK-4371 blueprint verbatim (introspection → declare → `uv lock --upgrade-package`) | — |
| M7: Non-Python surfaces | partial | UI/docs/examples/plugins are literal swaps; **the Argon pricing numbers are an external input** the coder must fetch from Google's pricing page and record in the Completion Note | price values not derivable from the repo |

### Module 1: GoogleModel additions

- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
- **Responsibility**: add the two 3.8 ids the sweep points at, so M2/M4 can reference them by name.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-client-google/src/parrot/clients/google/models.py:37-39
  class GoogleModel(Enum):                                        # verified: models.py:11
      GEMINI_3_1_FLASH_TTS_PREVIEW = "gemini-3.1-flash-tts-preview"  # verified: models.py:37 (anchor, unchanged)
      GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"            # verified: models.py:38 (unchanged)
      GEMINI_3_8_FLASH_TTS = "gemini-3.8-flash-tts"                  # NEW — live id (proposal F029)
      GEMINI_3_1_FLASH_LIVE_PREVIEW = "gemini-3.1-flash-live-preview" # verified: models.py:39 (unchanged)
      GEMINI_3_8_LIVE = "gemini-3.8-live"                            # NEW — live id (proposal F029)
  ```
- **Post-condition**: 51 names / 33 values (49/31 + 2/+2). `test_google_model_alias_count` is updated
  **once**, in M5, to the final 45/28 — M1's task must not touch it (M1 and M5 land in the same feature
  branch; the intermediate count is covered by M5's acceptance, see §7 Known Risks).

### Module 2: Client satellite rewrite + routing gates

- **Paths**: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`, `analysis.py`,
  `generation.py`; tests `packages/ai-parrot/tests/test_google_client.py`,
  `packages/ai-parrot-client-google/tests/unit/test_unopened_client_lifecycle.py`,
  `packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py`
- **Responsibility**: remove every by-name and prefix reference to a retired id inside the Google
  client satellite, so M5's deletion is safe.
- **Depends on**: M1 (uses `GEMINI_3_8_FLASH_TTS`).
- **Interface Skeleton** (public signatures whose *defaults* change; no bodies):
  ```python
  # modifies packages/ai-parrot-client-google/src/parrot/clients/google/client.py
  class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):   # verified: client.py:106
      @staticmethod
      def _requires_thinking(model: str) -> bool:                             # verified: client.py:303
          """Thinking-only models: Gemini 3.x Pro and computer-use. (2.5-pro removed.)"""
          # prefix tuple becomes ("gemini-3.1-pro", "gemini-3-pro")           # verified: client.py:313
      @staticmethod
      def _is_computer_use_model(model: str) -> bool:                         # verified: client.py:403
          # prefix tuple becomes ("gemini-3-flash-preview",)                  # verified: client.py:420
      async def question(self, prompt: str,
                         model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_8_FLASH,  # verified: client.py:5636 (was GEMINI_2_5_FLASH)
                         ...) -> ...: ...
      # seven fallback chains `self.model or GoogleModel.GEMINI_2_5_FLASH.value`
      # → `self.model or GoogleModel.GEMINI_3_8_FLASH.value`                  # verified: client.py:3370,4253,4792,4935,5227,5330
      # docstrings/comments naming gemini-2.5-pro as an example               # verified: client.py:110,117,164,569,1857,3507

  # modifies packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py
  class GoogleAnalysis:
      def analyze_sentiment(self, text: str,
                            model: Union[GoogleModel, str] = GoogleModel.GEMINI_3_8_FLASH, ...)  # verified: analysis.py:64
      # same default swap at analysis.py:139, 631, 1075, 1130, 1185 (GEMINI_2_5_FLASH → GEMINI_3_8_FLASH)
      # analysis.py:815  GEMINI_2_5_PRO → GEMINI_4_ARGON   (pro-class, U1)
      # analysis.py:914  model="gemini-2.5-flash" → GoogleModel.GEMINI_3_8_FLASH.value (503 retry path)

  # modifies packages/ai-parrot-client-google/src/parrot/clients/google/generation.py
  class GoogleGeneration:
      async def create_conversation_script(self, report_data: ConversationalScriptConfig,
                                           model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_8_FLASH, ...)  # verified: generation.py:405
      async def generate_speech(self, prompt_data: SpeechGenerationPrompt,
                                model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_8_FLASH_TTS, ...)      # verified: generation.py:572
      # generation.py:2321 docstring mention → "GoogleModel.GEMINI_3_8_FLASH"
  ```
- **Tests**: `test_google_client.py:370-376` negative whitelist examples switch from 2.5 ids to
  `gemini-2.0-flash`-class ids (the gates do not consult the enum, but reviewers must not read a
  retired id as "still supported"); `:408` parametrize and `:422` `_model_class_key("gemini-2.5-pro") == "default"`
  switch to `gemini-2.0-flash`; add `test_requires_thinking_excludes_2_5_pro` and
  `test_computer_use_gate_excludes_2_5` (both predicates return `False` for the retired ids).
  `test_unopened_client_lifecycle.py:48,75-79,96-100` → `GEMINI_3_8_FLASH` / `GEMINI_4_ARGON`.
  `test_computer_use_vocabulary.py:25` keeps the literal string (vocabulary selection is string-based) but
  its expectation must be re-derived: with the `gemini-2.5-computer-use` prefix gone the id is no longer
  computer-use, so `_computer_use_vocabulary` returns `"v3_8"` for it (`client.py:300`).
  `packages/ai-parrot/tests/clients/test_google_computer_use.py` flips the assertions that pin the dead
  prefixes: `:20-23` (`_is_computer_use_model(2.5 computer-use) is True` → `False`), `:44-47`
  (`_requires_thinking(2.5 computer-use) is True` → `False`), `:52-53` (`_requires_thinking("gemini-2.5-pro")
  is True` → `False`), `:229` (drop `gemini-2.5-pro` from the `_rejects_zero_thinking_budget` loop, keep
  `gemini-3.1-pro-preview`), `:236` (`gemini-2.5-flash` → `gemini-3.8-flash`). Add
  `test_maybe_apply_gemini_cache_fail_open_for_argon` to `packages/ai-parrot/tests/test_prompt_caching_gemini.py`
  (codex S2): with `model="gemini-4-argon"` and `caches.create` raising, the payload is returned unchanged
  and `system_instruction` survives in it.

### Module 3: Component defaults sweep (Python src + normative docs)

- **Paths** (all MODIFY): `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py`,
  `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`, `packages/ai-parrot/src/parrot/experts/policy.py`,
  `packages/ai-parrot/src/parrot/conf.py`, `packages/ai-parrot/src/parrot/bots/base.py`, `bots/voice.py`,
  `bots/scraper/scraper.py`, `bots/factory/builders/rag_builder.py`, `bots/factory/builders/tool_agent_builder.py`,
  `bots/mixins/model_switching.py`, `bots/abstract.py`, `interfaces/images/plugins/{classifybase,classify,analisys}.py`,
  `memory/episodic/reflection.py`, `setup/providers/google.py`, `knowledge/bookstore/_llm.py`,
  `packages/ai-parrot-server/src/parrot/handlers/google_generation.py`,
  `packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py`,
  `docs/configuration/llm-defaults.md`, `docs/config.md`;
  tests `packages/ai-parrot/tests/unit/test_llm_defaults.py`, `tests/experts/test_expert_llm_defaults.py`,
  `tests/bots/flows/crew/test_crew_llm_defaults.py`, `packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py`
- **Responsibility**: every shipped default outside the client satellite stops naming a 2.5 id.
- **Depends on**: nothing (string literals only; `GoogleModel.GEMINI_3_8_FLASH` / `GEMINI_4_ARGON` already exist).
- **Interface Skeleton** (end state of each default):
  ```python
  # handlers/agents/abstract.py
  _use_model: Optional[str] = None  # None -> AGENT_LLM / DEFAULT_LLM / google:gemini-4-argon (FEAT-796)   # verified: abstract.py:182
  resolved = resolve_component_llm("AGENT", builtin="google:gemini-4-argon")                               # verified: abstract.py:797
  model = self._use_model or ("gemini-4-argon" if llm == "google" else None)                               # verified: abstract.py:802
  # bots/flows/crew/crew.py
  _CREW_BUILTIN_LLM = "google:gemini-4-argon"                                                              # verified: crew.py:121
  # experts/policy.py
  DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]] = {                                         # verified: policy.py:10
      ExpertTier.JUDGMENT:  {"provider": "google", "model": "gemini-4-argon",   "temperature": 0.2},
      ExpertTier.BALANCED:  {"provider": "google", "model": "gemini-3.8-flash", "temperature": 0.1},
      ExpertTier.TEMPLATED: {"provider": "google", "model": "gemini-3.8-flash", "temperature": 0.0},
  }
  # conf.py
  ONTOLOGY_AQL_MODEL = config.get("ONTOLOGY_AQL_MODEL", fallback="gemini-3.8-flash")                       # verified: conf.py:166
  # bots/base.py:493,495 · bots/voice.py:438 · bots/scraper/scraper.py:98 · images/plugins/*.py:26,55,16
  # memory/episodic/reflection.py:94 · setup/providers/google.py:16 · handlers/google_generation.py:115
  # autonomous/deploy/templates.py:188,199        → "gemini-3.8-flash" (flash-class)
  # bots/abstract.py:968 (docstring example)      → "gemini-4-argon" (pro-class example)
  # builders rag_builder.py:29 / tool_agent_builder.py:31 (LLM prompt text) → model=`gemini-3.8-flash`
  # bots/mixins/model_switching.py:30 · knowledge/bookstore/_llm.py:6 (doc examples) → google:gemini-3.8-flash
  ```
- **Docs**: **CREATE `docs/migration/gemini-2-5-retirement.md`** (codex S6/S9): the deleted members and
  values, the §2 replacement table, the breaking contract (`GoogleModel("gemini-2.5-pro")` raises `ValueError`,
  `/models` no longer lists the ids), the statement that explicit overrides (`DEFAULT_LLM`, `<COMPONENT>_LLM`,
  `LLM_MODEL`, persisted bot configs) are **preserved, not rewritten** — Google auto-routes them after
  2026-12-01 — and the Argon-has-no-caching note. `docs/configuration/llm-defaults.md:8-12` rows → `google:gemini-4-argon` (AGENT, CREW,
  EXPERT_JUDGMENT) and `google:gemini-3.8-flash` (BALANCED, TEMPLATED); add one sentence under the table:
  Argon has no context caching, `AGENT_LLM=google:gemini-3.8-flash` keeps it. `docs/config.md:224`
  `DEFAULT_LLM_MODEL` default → `gemini-flash-latest` (the real `conf.py:458` value), **delete** line 225
  (`LLM_MODEL_NAME` does not exist in `conf.py`), `:331` → `DEFAULT_LLM_MODEL=gemini-flash-latest`.
- **Tests**: re-pin the literals — `test_llm_defaults.py:21-22,29,47-51`, `test_expert_llm_defaults.py:21-23,49`
  (and the `ModelConfig(provider="google", model="gemini-2.5-flash")` fixtures at :95,:129 →
  `gemini-3.8-flash`), `test_agent_handler_llm_defaults.py:63,77-92,129-134`, `test_crew_llm_defaults.py:72,87`. Add
  `test_explicit_override_preserves_retired_id` to `test_llm_defaults.py` (codex S9): `CREW_LLM=google:gemini-2.5-pro`
  resolves to that exact id with `source="component"` — the resolver never remaps.

### Module 4: Voice / TTS catalogue (core)

- **Path**: `packages/ai-parrot/src/parrot/models/google.py`; test `packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py`
- **Responsibility**: the Live API default and the TTS member stop naming ids that die on 2026-11-17;
  the video-reel director default stops naming 2.5-flash.
- **Depends on**: nothing (`GeminiLiveClient` reads `GoogleVoiceModel.DEFAULT.value` at `live.py:376`
  and accepts any `GoogleVoiceModel` at `:426` — no client edit).
- **Interface Skeleton** (end state of the enum):
  ```python
  # modifies packages/ai-parrot/src/parrot/models/google.py:13-28
  class GoogleVoiceModel(str, Enum):                                   # verified: models/google.py:13
      """Available models for Gemini Live API."""
      # Latest Native Audio / Live models
      GEMINI_3_8_LIVE = "gemini-3.8-live"                              # NEW (replaces the three 2.5 native-audio members, lines 22-24)
      GEMINI_3_8_FLASH_TTS = "gemini-3.8-flash-tts"                    # NEW (replaces GEMINI_2_5_FLASH_PREVIEW_TTS, line 25)
      GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"              # verified: models/google.py:26 (unchanged)
      # Aliases
      DEFAULT = "gemini-3.8-live"                                      # verified: models/google.py:28 (was 2.5 native-audio 12-2025)
      @classmethod
      def all_models(cls) -> List[str]: ...                            # verified: models/google.py:31 (unchanged)

  # VideoReelRequest (same file)
  director_model: Optional[str] = Field(None, description="... None resolves to the default director model ('gemini-3.8-flash').")  # verified: models/google.py:452-456
  def effective_director_model(self) -> str:                           # verified: models/google.py:600
      return self.director_model or "gemini-3.8-flash"                 # verified: models/google.py:602
  ```
- **Note**: `DEFAULT` is a plain-Enum alias of `GEMINI_3_8_LIVE` (same value) — `all_models()` already
  filters `DEFAULT` by name (`:33`), so the listing stays alias-free.
- **Tests**: `test_voicebot_provider_switch.py:90` literal → `gemini-3.8-live`; add
  `test_google_voice_model_default_is_3_8_live` and `test_google_voice_model_has_no_2_5_members`
  (in `packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py` or a new
  `packages/ai-parrot/tests/models/test_google_voice_model.py` — the task picks one).

### Module 5: Catalogue deletion, alias-count tests and the regression guard

- **Paths**: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`;
  tests `packages/ai-parrot/tests/test_google_models.py`, `packages/ai-parrot/tests/clients/test_google_models.py`,
  `tests/unit/test_google_document_understanding.py` (re-grep), `packages/ai-parrot/tests/test_llm_factory.py`;
  **new** `packages/ai-parrot/tests/test_no_retired_gemini_defaults.py`
- **Responsibility**: delete the retired members and make the retirement un-regressable.
- **Depends on**: M1, M2, M3, M4, M7 (the guard scans `src/` after every sweep landed).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-client-google/src/parrot/clients/google/models.py
  class GoogleModel(Enum):
      # DELETE: GEMINI_2_5_FLASH (41), GEMINI_2_5_FLASH_PREVIEW (42), GEMINI_2_5_PRO (45),
      #         GEMINI_2_5_FLASH_TTS (46), GEMINI_2_5_PRO_TTS (47), GEMINI_COMPUTER_USE (49)
      # KEEP:   GEMINI_2_5_FLASH_LITE (43), GEMINI_2_5_FLASH_LITE_PREVIEW (44), GEMINI_2_5_FLASH_IMAGE (48),
      #         GEMINI_2_5_FLASH_IMAGE_PREVIEW (59), GEMINI_3_FLASH_COMPUTER_USE (50), GEMINI_3_5_FLASH_COMPUTER_USE (51)
  class VertexAIModel(Enum):
      # DELETE: GEMINI_2_5_FLASH (91), GEMINI_2_5_PRO (93)   KEEP: GEMINI_2_5_FLASH_LITE (92)

  # packages/ai-parrot/tests/test_no_retired_gemini_defaults.py  (new)
  RETIRED_LITERALS: tuple[str, ...] = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-preview-tts",
                                       "gemini-2.5-pro-preview-tts", "gemini-2.5-flash-native-audio",
                                       "gemini-2.5-computer-use")
  def test_no_retired_gemini_literal_in_src() -> None:
      """Scan packages/*/src for RETIRED_LITERALS as whole ids (``gemini-2.5-flash`` must NOT match
      ``gemini-2.5-flash-lite`` / ``-image``); skip build/, node_modules/ and the reviewed exclusion list
      GUARD_EXCLUDED = ("packages/ai-parrot/src/parrot/clients/base.py",)  # two historical comments (:373, :2143); file is a non-goal
      ; fail with a path:line list (codex S7)."""
  ```
- **Post-condition**: `GoogleModel` has **45 names / 28 values**; `GoogleModel("gemini-2.5-pro")`,
  `GoogleModel("gemini-2.5-flash")`, `GoogleModel("gemini-2.5-computer-use-preview-10-2025")` raise `ValueError`.
- **Tests**: `test_google_models.py:41-53` extend `RETIRED_VALUES` / `RETIRED_NAMES` with the six names
  and five values; `:76-77` → `== 45` / `== 28`; add `test_google_model_enum_has_3_8_tts_and_live`.
  `tests/clients/test_google_models.py` (whole file, 26 lines): drop `test_gemini_computer_use_exists`
  / `_value` (:10-14) and the two 2.5 asserts at `:25-26`; keep `:16-20` and `:24`; add the negative
  `GEMINI_COMPUTER_USE not in __members__`. `test_llm_factory.py`: add
  `test_list_models_google_excludes_2_5` (`"gemini-2.5-pro" not in models["active"]`).
  `tests/unit/test_google_document_understanding.py:396` (`model=GoogleModel.GEMINI_2_5_FLASH,`) →
  `GoogleModel.GEMINI_3_8_FLASH` (verified).

### Module 6: google-genai floor

- **Paths**: `packages/ai-parrot-client-google/pyproject.toml`, `packages/ai-parrot-embeddings/pyproject.toml`,
  `uv.lock`, `packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py`
- **Responsibility**: raise the floor from `>=2.31.0` to the newest gate-verified release (U4).
- **Depends on**: nothing. **Exclusive** (rewrites the shared lockfile).
- **Procedure** (TASK-4371 blueprint, `sdd/tasks/completed/TASK-4371-google-genai-floor.md:126-151`):
  1. Candidate = PyPI latest at implementation time (`curl -s https://pypi.org/pypi/google-genai/json`;
     2.34.0 on 2026-11-04). Introspect it in an isolated venv (`uv venv` + `uv pip install
     "google-genai==<candidate>"`), importing `genai.Client`, `types.ThinkingConfig`, `types.ComputerUse`,
     `aio.caches.create`, `aio.live.music.connect`, `aio.aclose`, `google.genai.errors`; print `ALL OK`.
     If it fails, step down one release and repeat; never declare a version that did not print `ALL OK`.
  2. Declare `"google-genai>=<verified>"` at `ai-parrot-client-google/pyproject.toml:34` and
     `ai-parrot-embeddings/pyproject.toml:55`; extend the policy comment block above `:34` with the date.
  3. `uv lock --upgrade-package google-genai`; verify `uv.lock` resolves `== <verified>` (`uv.lock:6704-6705`
     today) and `uv lock --check` passes. Never `uv sync` inside a worktree.
  4. Record "operator must `uv sync` in the main checkout after merge" in the Completion Note.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py
  class TestInstalledSdkFloor:                                               # verified: test_reel_sdk_contract.py:32
      """The installed SDK meets the declared >=<verified> floor."""          # was >=2.23.0 (:33, stale since FEAT-688)
      def test_installed_version_meets_declared_floor(self) -> None:          # verified: :35
          # assert installed >= Version("<verified>")                         # verified: :39-42 (literal 2.23.0 → <verified>)
  ```

### Module 7: Non-Python surfaces

- **Paths**: `packages/ai-parrot-server/ui/src/lib/config/regeneration-models.ts`,
  `packages/ai-parrot-server/ui/src/lib/components/agents/ChatInput.svelte`,
  `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json`,
  `docs/` (15 files), `examples/` (26 files), `plugins/agents/epson.py` (full list: proposal F008 and
  `grep -rl 'gemini-2\.5' docs examples plugins`)
- **Responsibility**: every non-src surface stops presenting a retired id as current (U3).
- **Depends on**: nothing (M5's guard does not scan these paths; M5 depends on M7 only for ordering).
- **Interface Skeleton**:
  ```ts
  // packages/ai-parrot-server/ui/src/lib/config/regeneration-models.ts
  { value: "google:gemini-3.8-flash", label: "Gemini 3.8 Flash", provider: "Google", enabled: true }, // verified: :21-26 (was 2.5 Flash)
  export const DEFAULT_MODEL = "google:gemini-3.8-flash";                                              // verified: :62
  // ChatInput.svelte supportedModels
  { value: "google:gemini-4-argon", label: "Gemini 4 Argon" },   // verified: :204 (replaces "Gemini 2.5 Pro")
  { value: "google:gemini-3.8-flash", label: "Gemini 3.8 Flash" }, // verified: :203 (replaces "Gemini 2.5 Flash")
  { value: "google:gemini-3.1-pro-preview", label: "Gemini 3.1 Pro" }, // verified: :206 `google:gemini-3-pro-preview` is not a catalogue value (codex S8)
  ```
  ```jsonc
  // observability/cost/pricing/google.json — add, same shape as the "gemini-3.8-flash" row (:103-115)
  "gemini-4-argon": { "input_per_1m": <from Google pricing page>, "output_per_1m": <…>, "valid_from": "<release date>" }
  // and bump "last_updated" (:3) to the edit date; keep the two dated 2.5 *preview* rows (:57-68) — they price history.
  ```
- **Pricing tests** (codex S5): add `test_gemini_4_argon_priced` to
  `packages/ai-parrot/tests/unit/observability/test_cost_calculator.py` — `cost_usd(provider="gemini", model="gemini-4-argon", …)`
  returns a priced value and `revision_for("gemini", "gemini-4-argon")` is not `(None, None)` (pattern: `:187-199`).
- **Docs/examples rule**: literal swap per the §2 table; a doc that *describes* the deprecation (none
  today) may keep the old id in prose. `examples/matrix_swarm/.env.example` follows the same table.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_google_model_enum_has_3_8_tts_and_live` | M1/M5 | new members reachable by name and by value |
| `test_requires_thinking_excludes_2_5_pro` | M2 | `_requires_thinking("gemini-2.5-pro") is False`; `gemini-3.1-pro-preview` still True |
| `test_computer_use_gate_excludes_2_5` | M2 | `_is_computer_use_model("gemini-2.5-computer-use-preview-10-2025") is False`; `gemini-3-flash-preview` still True |
| `test_question_default_model_is_3_8_flash` | M2 | `inspect.signature(GoogleGenAIClient.question).parameters["model"].default is GoogleModel.GEMINI_3_8_FLASH` |
| `test_generate_speech_default_is_3_8_tts` | M2 | same pattern on `GoogleGeneration.generate_speech` |
| `test_resolve_builtin_when_unset` (re-pinned) | M3 | AGENT/CREW builtin resolves to `google:gemini-4-argon` |
| `test_expert_tier_defaults` (re-pinned) | M3 | judgment → argon, balanced/templated → 3.8-flash |
| `test_agent_handler_builtin_default` (re-pinned) | M3 | `agent.kwargs["model"] == "gemini-4-argon"` |
| `test_google_voice_model_default_is_3_8_live` | M4 | `GoogleVoiceModel.DEFAULT.value == "gemini-3.8-live"`; `all_models()` has no `2.5` id |
| `test_google_model_retired_values_raise` (extended) | M5 | the five 2.5 values raise `ValueError` |
| `test_google_model_alias_count` (re-pinned) | M5 | 45 names / 28 values |
| `test_list_models_google_excludes_2_5` | M5 | factory `active` has no retired id |
| `test_no_retired_gemini_literal_in_src` | M5 | regression guard over `packages/*/src` |
| `test_installed_version_meets_declared_floor` (re-pinned) | M6 | installed SDK ≥ the new floor |
| `test_maybe_apply_gemini_cache_fail_open_for_argon` | M2 | Argon + `caches.create` raising → payload unchanged, `system_instruction` intact (codex S2) |
| `test_explicit_override_preserves_retired_id` | M3 | `CREW_LLM=google:gemini-2.5-pro` resolves unchanged, `source="component"` (codex S9) |
| `test_gemini_4_argon_priced` | M7 | exact-key pricing row present; `revision_for` populated (codex S5) |

### Integration Tests

| Test | Description |
|---|---|
| `test_maybe_apply_gemini_cache_*` (`packages/ai-parrot/tests/test_prompt_caching_gemini.py`, existing) | fail-open cache path keeps passing — proves Argon-as-default cannot crash a caching call site |
| `test_crew_sequential_default_model` (existing) | Google-family CREW builtin still forwarded to agents with the new id |
| Live (opt-in, `PARROT_TEST_REAL_LLM=1`): `models.get("gemini-4-argon")`, `("gemini-3.8-flash")`, `("gemini-3.8-flash-tts")`, `("gemini-3.8-live")` | the four replacement ids resolve at implementation time (FEAT-688 precedent; evidence to `artifacts/logs/`) |

### Validation Contract

tests:
- packages/ai-parrot/tests/test_google_models.py
- packages/ai-parrot/tests/clients/test_google_models.py
- packages/ai-parrot/tests/test_google_client.py
- packages/ai-parrot/tests/test_llm_factory.py
- packages/ai-parrot/tests/test_prompt_caching_gemini.py
- packages/ai-parrot/tests/unit/test_llm_defaults.py
- packages/ai-parrot/tests/experts/test_expert_llm_defaults.py
- packages/ai-parrot/tests/bots/flows/crew/test_crew_llm_defaults.py
- packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py
- packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py
- packages/ai-parrot-client-google/tests/unit/test_unopened_client_lifecycle.py
- packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py
- packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py
- packages/ai-parrot/tests/clients/test_google_computer_use.py
- packages/ai-parrot/tests/unit/observability/test_cost_calculator.py
- tests/unit/test_google_document_understanding.py
markers: none

### Test Data / Fixtures

```python
# Retired ids every negative test shares (M2, M5)
RETIRED_2_5 = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-preview-tts",
               "gemini-2.5-pro-preview-tts", "gemini-2.5-computer-use-preview-10-2025")
# Kept ids the guard must NOT flag
KEPT_2_5 = ("gemini-2.5-flash-lite", "gemini-2.5-flash-image")
```

Worktree runs need `PYTHONPATH=/abs/path/packages/ai-parrot/src:/abs/path/packages/ai-parrot-client-google/src:/abs/path/packages/ai-parrot-server/src`
(absolute; the shared venv is editable-installed against the main checkout).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1 `grep -rn 'gemini-2\.5-\(pro\|flash\)\b\|preview-tts\|native-audio\|2\.5-computer-use' packages/*/src --include=*.py --include=*.ts --include=*.svelte | grep -v 'build/\|clients/base.py'` returns only `flash-lite` / `flash-image` lines (and nothing else; `clients/base.py:373,2143` are the reviewed comment-only exclusions); `test_no_retired_gemini_literal_in_src` passes.
- [ ] AC-2 `resolve_component_llm("AGENT"|"CREW", builtin=…)` call sites and `DEFAULT_TIER_POLICY` carry `gemini-4-argon` (pro) / `gemini-3.8-flash` (flash); `docs/configuration/llm-defaults.md` matches them.
- [ ] AC-3 `GoogleModel.__members__` has no `GEMINI_2_5_FLASH`, `GEMINI_2_5_FLASH_PREVIEW`, `GEMINI_2_5_PRO`, `GEMINI_2_5_FLASH_TTS`, `GEMINI_2_5_PRO_TTS`, `GEMINI_COMPUTER_USE`; has `GEMINI_3_8_FLASH_TTS`, `GEMINI_3_8_LIVE`; `len(__members__) == 45`, 28 distinct values; `VertexAIModel` keeps only `GEMINI_2_5_FLASH_LITE` of its 2.5 members.
- [ ] AC-4 `GoogleGenAIClient._requires_thinking("gemini-2.5-pro") is False` and `_is_computer_use_model("gemini-2.5-computer-use-preview-10-2025") is False`; `grep -c 'GoogleModel.GEMINI_2_5' client.py analysis.py generation.py` == 0.
- [ ] AC-5 `GoogleVoiceModel.DEFAULT.value == "gemini-3.8-live"`, no 2.5 member on the enum; `GeminiLiveClient._default_model == "gemini-3.8-live"` without any edit to `live.py`.
- [ ] AC-6 `generate_speech` default is `GoogleModel.GEMINI_3_8_FLASH_TTS`; `question` and all `analysis.py` flash defaults are `GEMINI_3_8_FLASH`; `analysis.py:815` is `GEMINI_4_ARGON`.
- [ ] AC-7 Both pyprojects declare `google-genai>=<verified>` with `<verified>` > 2.31.0 and an `ALL OK` introspection log under `artifacts/logs/`; `uv.lock` resolves that exact version; `uv lock --check` passes; `test_reel_sdk_contract.py` asserts the new floor.
- [ ] AC-8 `observability/cost/pricing/google.json` has a `gemini-4-argon` row and a bumped `last_updated`; `CostCalculator.calculate("google", "gemini-4-argon", …)` returns a priced cost (not `_warn_unknown`).
- [ ] AC-9 Admin UI lists (`regeneration-models.ts`, `ChatInput.svelte`) and `deploy/templates.py` name no 2.5 id; `DEFAULT_MODEL == "google:gemini-3.8-flash"`.
- [ ] AC-10 `grep -rl 'gemini-2\.5-\(pro\|flash\)\b' docs examples plugins` is empty (flash-lite/flash-image mentions may remain).
- [ ] AC-11 Every test in the Validation Contract passes with worktree `PYTHONPATH`; `test_prompt_caching_gemini.py` is green (fail-open path intact).
- [ ] AC-12 **Blocking live gate before M4/M5 merge** (codex S1): `models.get` evidence in `artifacts/logs/` for `gemini-4-argon`, `gemini-3.8-flash`, `gemini-3.8-flash-tts`, `gemini-3.8-live` (all four resolved on 2026-11-04, proposal F029; re-run at implementation time with `GOOGLE_API_KEY`). A failing id blocks the deletion of its 2.5 predecessor, not the whole feature.
- [ ] AC-15 `docs/migration/gemini-2-5-retirement.md` exists and states the deleted ids, the replacement table and that explicit overrides are preserved (codex S6/S9); `ChatInput.svelte` no longer offers `google:gemini-3-pro-preview` (codex S8).
- [ ] AC-13 No edit to `parrot/llm_defaults.py`, `clients/google/live.py`, `clients/base.py`, or the `GoogleGenAIClient` class defaults (`client.py:130-133,171`).
- [ ] AC-14 `ruff check` clean on every touched Python file; `pnpm build` clean for the UI package.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `63e72545ce` (dev, 2026-11-04) with 150 probe checks (`sdd/state/FEAT-798/`).

### Verified Imports
```python
from parrot.clients.google.models import GoogleModel, VertexAIModel   # verified: models.py:99 (__all__); used at handlers/google_generation.py:42, tests/test_google_models.py:5
from parrot.clients.google import GoogleGenAIClient                    # verified: handlers/google_generation.py:110 (lazy import pattern — core never imports it at module scope, FEAT-523 AC-3)
from parrot.llm_defaults import resolve_component_llm, ComponentLLM   # verified: llm_defaults.py:47, :17
from parrot.models.google import GoogleVoiceModel                      # verified: models/google.py:13; consumed at clients/google/live.py:58 (relative import)
from parrot.clients.factory import LLMFactory                          # verified: factory.py:231-253 (list_models)
from parrot.experts.models import ExpertTier                           # verified: experts/policy.py:7
```

### Existing Class Signatures
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/models.py
class GoogleModel(Enum):                                   # line 11 — plain Enum: duplicate values are silent aliases
    GEMINI_FLASH_LATEST = "gemini-flash-latest"            # line 14
    GEMINI_4_ARGON = "gemini-4-argon"                      # line 19
    GEMINI_3_8_FLASH = "gemini-3.8-flash"                  # line 21
    GEMINI_3_1_FLASH_TTS_PREVIEW = "gemini-3.1-flash-tts-preview"  # line 37
    GEMINI_3_1_FLASH_LIVE_PREVIEW = "gemini-3.1-flash-live-preview"  # line 39
    GEMINI_2_5_FLASH … GEMINI_COMPUTER_USE                 # lines 41-49 (see M5)
    GEMINI_2_5_FLASH_IMAGE_PREVIEW = "gemini-2.5-flash-image"  # line 59 (KEEP)
class VertexAIModel(Enum):                                 # line 73
    GEMINI_2_5_FLASH / _FLASH_LITE / _PRO                  # lines 91-93

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):   # line 106
    models: type[Enum] = GoogleModel                                          # line 128
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value               # line 130 (UNCHANGED)
    _fallback_model: str = "gemini-3.1-flash-lite"                            # line 131 (UNCHANGED)
    _default_combined_call_prefixes: tuple[str, ...] = ("gemini-4-argon", "gemini-3.8-flash", …)  # lines 151-160 (UNCHANGED)
    _default_reformat_model: str = GoogleModel.GEMINI_3_5_FLASH.value         # line 171 (UNCHANGED)
    @staticmethod
    def _is_modern_gemini_model(model: str) -> bool                           # line 233 → startswith(("gemini-3", "gemini-4")) :243
    def _computer_use_vocabulary(self, model) -> str                          # … returns "legacy" if _is_computer_use_model else "v3_8"  :300
    @staticmethod
    def _requires_thinking(model: str) -> bool                                # line 303; prefixes :312-314
    @staticmethod
    def _rejects_zero_thinking_budget(model: str) -> bool                     # line 317 (superset; no edit)
    @staticmethod
    def _is_computer_use_model(model: str) -> bool                            # line 403; prefixes :420
    def _model_class_key(self, model: str) -> str                             # line 462 (no edit)
    async def _maybe_apply_gemini_cache(self, client, model, payload, segments, *, system_instruction=None) -> dict  # line 548 — fail-open
    async def question(self, prompt: str, model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH, …)  # line 5633-5636

# packages/ai-parrot-client-google/src/parrot/clients/google/live.py
class GeminiLiveClient(AbstractClient):
    _default_model: str = GoogleVoiceModel.DEFAULT.value                      # line 376
    # __init__ resolves model=None → self._default_model, GoogleVoiceModel → .value   # lines 424-427

# packages/ai-parrot/src/parrot/llm_defaults.py
class ComponentLLM(BaseModel): provider: str; model: str; source: Literal["component","global","builtin"]  # line 17
def resolve_component_llm(component: str, *, builtin: str) -> ComponentLLM    # line 47 — `<COMPONENT>_LLM` → conf.DEFAULT_LLM → builtin

# packages/ai-parrot/src/parrot/experts/policy.py
DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]]                   # lines 10-14
def tier_policy(tier: ExpertTier) -> dict[str, Any]                           # line 19 — resolves EXPERT_<TIER> via resolve_component_llm :24

# packages/ai-parrot/src/parrot/models/google.py
class GoogleVoiceModel(str, Enum)                                             # line 13; members 22-26; DEFAULT alias 28; all_models() 31-33
class VideoReelRequest(BaseModel): director_model: Optional[str]              # line 452; effective_director_model() 600-602

# packages/ai-parrot/src/parrot/observability/cost/calculator.py
#   provider_pricing.get(model)  — exact key lookup, no prefix match            # line 301 (also :326 revision_for)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GoogleModel.GEMINI_3_8_FLASH_TTS` (M1) | `GoogleGeneration.generate_speech` default | enum member default | `generation.py:572` |
| `GoogleVoiceModel.DEFAULT = "gemini-3.8-live"` (M4) | `GeminiLiveClient._default_model` | class attribute reads `.value` at import | `live.py:376` |
| AGENT/CREW/EXPERT builtins (M3) | `resolve_component_llm(…, builtin=…)` | string argument | `abstract.py:797`, `crew.py:135,1834`, `policy.py:24` |
| `pricing/google.json` `gemini-4-argon` row (M7) | `CostCalculator` | exact key | `calculator.py:301` |
| regression guard (M5) | `packages/*/src` tree | filesystem scan | new test |

### Does NOT Exist (Anti-Hallucination)
- ~~`GoogleGenAIClient.deprecated_models`~~ — never defined on the Google client (`factory.py:253` getattr-defaults to `{}`); do not add one (FEAT-688 U2).
- ~~`GoogleModel.GEMINI_4_FLASH` / `GEMINI_4_ARGON_FLASH` / any 4.x flash or lite member~~ — Google serves no such id.
- ~~`GoogleModel.GEMINI_3_8_FLASH_TTS`, `GoogleModel.GEMINI_3_8_LIVE`~~ — do not exist until M1 lands (M2 depends on M1).
- ~~`GoogleVoiceModel.GEMINI_3_8_LIVE`, `GoogleVoiceModel.GEMINI_3_8_FLASH_TTS`~~ — do not exist until M4 lands.
- ~~`GoogleGenAIClient._is_gemini3_model`~~ — renamed to `_is_modern_gemini_model` by FEAT-688 (`client.py:233`).
- ~~`conf.LLM_MODEL_NAME`~~ — documented in `docs/config.md:225` but absent from `conf.py` (M3 deletes the doc line).
- ~~`conf.DEFAULT_LLM_MODEL_NAME`~~ — only in stale `build/lib*/` artifacts, not in `src/`.
- ~~`CostCalculator` prefix matching~~ — lookup is exact (`calculator.py:301`); a missing `gemini-4-argon` row is an unpriced call.
- ~~`GoogleVoiceModel` consumers other than `live.py` and two comments in `bots/voice.py:259-262`~~ — `wikitoolkit symbols blast` and grep show none.
- ~~a `vitest` test for `regeneration-models.ts`~~ — none found; UI validation is `pnpm build` (AC-14).

### Edit Sites (Blueprint Anchors)

Verified against: `63e72545ce`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` | MODIFY (M1) | `GEMINI_3_1_FLASH_LIVE_PREVIEW = "gemini-3.1-flash-live-preview"` | `models.py:39` | 1 |
| same | MODIFY (M5) | `GEMINI_2_5_FLASH = "gemini-2.5-flash"` — **2 occurrences**: `:41` is inside `class GoogleModel` directly after `# Gemini 2.5 series` (`:40`); `:91` is inside `class VertexAIModel` after `GEMINI_3_1_FLASH_LITE_IMAGE` (`:90`) | `models.py:41`, `:91` | 2 |
| same | MODIFY (M5) | `GEMINI_2_5_PRO = "gemini-2.5-pro"` — **2 occurrences**: `:45` (GoogleModel, between `_FLASH_LITE_PREVIEW` `:44` and `_FLASH_TTS` `:46`), `:93` (VertexAIModel, before `IMAGEN_3` `:94`) | `models.py:45`, `:93` | 2 |
| same | MODIFY (M5) | `GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"` | `models.py:49` | 1 |
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY (M2) | `("gemini-2.5-pro", "gemini-3.1-pro", "gemini-3-pro")` | `client.py:313` | 1 |
| same | MODIFY (M2) | `return model.startswith(("gemini-2.5-computer-use", "gemini-3-flash-preview"))` | `client.py:420` | 1 |
| same | MODIFY (M2) | `model = self.model or GoogleModel.GEMINI_2_5_FLASH.value` — **2 occurrences** (`:3370` in the `ask` path after `_use_tools = …` `:3368`; `:5330`) | `client.py:3370`, `:5330` | 2 |
| same | MODIFY (M2) | `self.model or GoogleModel.GEMINI_2_5_FLASH.value` (bare, continuation line) | `client.py:4253` | 1 (+ the 2 above as substrings — match the full line) |
| same | MODIFY (M2) | `model = req.get("model") or self.model or GoogleModel.GEMINI_2_5_FLASH.value` — **2 occurrences** (`:4792`, `:5227`) | `client.py:4792`, `:5227` | 2 |
| same | MODIFY (M2) | `batch_model = first_req.get("model") or self.model or GoogleModel.GEMINI_2_5_FLASH.value` | `client.py:4935` | 1 |
| same | MODIFY (M2) | `model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,` (in `question`) | `client.py:5636` | 1 |
| same | MODIFY (M2, docstrings) | `Only Gemini-2.5-pro works well with multi-turn function calling.` | `client.py:110` | 1 |
| same | MODIFY (M2, docstrings) | lines containing `gemini-2.5-pro` / `gemini-2.5-flash` in comments | `client.py:117,164,569,1857,3507` | 1 each |
| `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py` | MODIFY (M2) | `model: Union[GoogleModel, str] = GoogleModel.GEMINI_2_5_FLASH,` | `analysis.py:64` | 1 |
| same | MODIFY (M2) | `model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,` — **5 occurrences** (`:139,631,1075,1130,1185`; each is the `model` kwarg of a different public method — anchor on the `def` line above it) | `analysis.py:139,631,1075,1130,1185` | 5 |
| same | MODIFY (M2) | `model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_PRO,` | `analysis.py:815` | 1 |
| same | MODIFY (M2) | `model="gemini-2.5-flash",` (503 retry) | `analysis.py:914` | 1 |
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY (M2) | `model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,` | `generation.py:405` | 1 |
| same | MODIFY (M2) | `model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_TTS,` | `generation.py:572` | 1 |
| same | MODIFY (M2, docstring) | `hardcoded to ``GoogleModel.GEMINI_2_5_FLASH``; now forwarded` | `generation.py:2321` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` | MODIFY (M3) | `resolved = resolve_component_llm("AGENT", builtin="google:gemini-2.5-pro")` | `abstract.py:797` | 1 |
| same | MODIFY (M3) | `model = self._use_model or ("gemini-2.5-pro" if llm == "google" else None)` | `abstract.py:802` | 1 |
| same | MODIFY (M3) | `_use_model: Optional[str] = None  # None -> AGENT_LLM / DEFAULT_LLM / google:gemini-2.5-pro (FEAT-796)` | `abstract.py:182` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY (M3) | `_CREW_BUILTIN_LLM = "google:gemini-2.5-pro"` | `crew.py:121` | 1 |
| `packages/ai-parrot/src/parrot/experts/policy.py` | MODIFY (M3) | `ExpertTier.JUDGMENT: {"provider": "google", "model": "gemini-2.5-pro", "temperature": 0.2},` | `policy.py:11` (block 10-14) | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY (M3) | `ONTOLOGY_AQL_MODEL = config.get("ONTOLOGY_AQL_MODEL", fallback="gemini-2.5-flash")` | `conf.py:166` | 1 |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY (M3) | `kwargs["model"] = "gemini-2.5-flash"` — **2 occurrences** (`:493` under `elif llm.client_type == "google":`, `:495` under `except Exception:`) | `base.py:493`, `:495` | 2 |
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY (M3) | `model=kwargs.get("model", "gemini-2.5-flash"),` | `voice.py:438` | 1 |
| `packages/ai-parrot/src/parrot/bots/scraper/scraper.py` | MODIFY (M3) | `or "gemini-2.5-flash"` | `scraper.py:98` | 1 |
| `packages/ai-parrot/src/parrot/bots/factory/builders/rag_builder.py` | MODIFY (M3) | ``- Default model: provider=`google`, model=`gemini-2.5-flash`,`` | `rag_builder.py:29` | 1 |
| `packages/ai-parrot/src/parrot/bots/factory/builders/tool_agent_builder.py` | MODIFY (M3) | ``5. Default model: provider=`google`, model=`gemini-2.5-flash`,`` | `tool_agent_builder.py:31` | 1 |
| `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py` | MODIFY (M3) | `llm="google:gemini-2.5-flash",` | `model_switching.py:30` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY (M3) | `"model": "gemini-2.5-pro",` | `abstract.py:968` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/images/plugins/classifybase.py` | MODIFY (M3) | `self._model_name: str = kwargs.get("model_name", "gemini-2.5-flash")` | `classifybase.py:26` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/images/plugins/classify.py` | MODIFY (M3) | same line | `classify.py:55` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/images/plugins/analisys.py` | MODIFY (M3) | same line | `analisys.py:16` | 1 |
| `packages/ai-parrot/src/parrot/memory/episodic/reflection.py` | MODIFY (M3) | `model: str = "gemini-2.5-flash",` | `reflection.py:94` | 1 |
| `packages/ai-parrot/src/parrot/setup/providers/google.py` | MODIFY (M3) | `default_model: str = "gemini-2.5-flash"` | `google.py:16` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py` | MODIFY (M3) | ``- ``PARROT_BOOKSTORE_LLM`` — heavy model, e.g. ``"google:gemini-2.5-flash"`` `` | `_llm.py:6` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/google_generation.py` | MODIFY (M3) | `client = GoogleGenAIClient(model=data.get("model", "gemini-2.5-flash"))` | `google_generation.py:115` | 1 |
| `packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py` | MODIFY (M3) | `llm="google:gemini-2.5-flash",` — **2 occurrences** (`:188` under `name="Assistant",`, `:199` under `name="DataAnalyst",`) | `templates.py:188`, `:199` | 2 |
| `docs/configuration/llm-defaults.md` | MODIFY (M3) | ``| `AGENT_LLM` | Agent | `google:gemini-2.5-pro` |`` (rows 8-12) | `llm-defaults.md:8` | 1 |
| `docs/config.md` | MODIFY (M3) | ``- **`DEFAULT_LLM_MODEL`**: Default model across the application (default: `gemini-2.5-flash`)`` | `config.md:224` (+ `:225` delete, `:331`) | 1 |
| `packages/ai-parrot/src/parrot/models/google.py` | MODIFY (M4) | `GEMINI_2_5_FLASH_NATIVE_AUDIO_LATEST = "gemini-2.5-flash-native-audio-preview-12-2025"` (block 22-25) | `models/google.py:22` | 1 |
| same | MODIFY (M4) | `DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"` | `models/google.py:28` | 1 |
| same | MODIFY (M4) | `return self.director_model or "gemini-2.5-flash"` | `models/google.py:602` | 1 |
| same | MODIFY (M4) | `"None resolves to the default director model ('gemini-2.5-flash')."` | `models/google.py:456` | 1 |
| `packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py` | MODIFY (M4) | `bot.voice_config.model = "gemini-2.5-flash-native-audio-preview-12-2025"` | `:90` | 1 |
| `packages/ai-parrot/tests/test_google_models.py` | MODIFY (M5) | `RETIRED_VALUES = (` / `RETIRED_NAMES = (` / `assert len(GoogleModel.__members__) == 49` | `:41`, `:47`, `:76-77` | 1 each |
| `packages/ai-parrot/tests/clients/test_google_models.py` | MODIFY (M5) | `assert GoogleModel.GEMINI_2_5_PRO.value == "gemini-2.5-pro"` | `:25` (whole file 26 lines) | 1 |
| `packages/ai-parrot/tests/test_llm_factory.py` | MODIFY (M5) | `def test_list_models_google_includes_argon():` (append after) | `:118` | 1 |
| `packages/ai-parrot/tests/test_no_retired_gemini_defaults.py` | CREATE (M5) | — | — | — |
| `tests/unit/test_google_document_understanding.py` | MODIFY (M5) | `model=GoogleModel.GEMINI_2_5_FLASH,` | `:396` | 1 |
| `packages/ai-parrot/tests/clients/test_google_computer_use.py` | MODIFY (M2) | `assert GoogleGenAIClient._requires_thinking("gemini-2.5-pro") is True` | `:53` (+ `:20-23,44-47,229,236`) | 1 |
| `packages/ai-parrot/tests/test_prompt_caching_gemini.py` | MODIFY (M2, append) | `async def test_maybe_apply_gemini_cache_creates_cached_content(self):` | `:103` | 1 |
| `packages/ai-parrot/tests/unit/observability/test_cost_calculator.py` | MODIFY (M7, append) | `def test_gemini_provider_resolved_via_google_file() -> None:` | `:187` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatInput.svelte` | MODIFY (M7) | `{ value: "google:gemini-3-pro-preview", label: "Gemini 3 Pro" },` | `:206` | 1 |
| `docs/migration/gemini-2-5-retirement.md` | CREATE (M3) | — | — | — |
| `packages/ai-parrot/tests/test_google_client.py` | MODIFY (M2) | `"gemini-2.5-pro",` — **6 occurrences** (`:373` in the negative-whitelist list after `"gemini-2.5-flash",`? no: `:373` precedes `:374 "gemini-2.5-flash",`; `:408` parametrize; `:758,:764,:1063,:1070` `model="gemini-2.5-pro",` kwargs) | `:373,408,422,758,764,1063,1070` | 6 |
| `packages/ai-parrot-client-google/tests/unit/test_unopened_client_lifecycle.py` | MODIFY (M2) | `instance = GoogleGenAIClient(api_key="fake_key", model=GoogleModel.GEMINI_2_5_FLASH.value)` | `:48` (+ `:75,78,79,96,100`) | 1 |
| `packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py` | MODIFY (M2) | `assert client._computer_use_vocabulary("gemini-2.5-computer-use-preview-10-2025") == "legacy"` | `:25` | 1 |
| `packages/ai-parrot/tests/unit/test_llm_defaults.py` | MODIFY (M3) | `assert ld.resolve_component_llm("CREW", builtin="google:gemini-2.5-pro") == ld.ComponentLLM(` | `:21` (+ `:22,29,47,51`) | 1 |
| `packages/ai-parrot/tests/experts/test_expert_llm_defaults.py` | MODIFY (M3) | `ExpertTier.JUDGMENT: {"provider": "google", "model": "gemini-2.5-pro", "temperature": 0.2},` | `:21` (+ `:22-23,49,95,129`) | 1 |
| `packages/ai-parrot-server/tests/handlers/test_agent_handler_llm_defaults.py` | MODIFY (M3) | `assert agent.kwargs["model"] == "gemini-2.5-pro"` | `:63` (+ `:77-92,129-134`) | 1 |
| `packages/ai-parrot/tests/bots/flows/crew/test_crew_llm_defaults.py` | MODIFY (M3) | `env["CREW_LLM"] = "google:gemini-2.5-flash"` | `:72` (+ `:87`) | 1 |
| `packages/ai-parrot-client-google/pyproject.toml` | MODIFY (M6) | `"google-genai>=2.31.0",` | `:34` | 1 |
| `packages/ai-parrot-embeddings/pyproject.toml` | MODIFY (M6) | `"google-genai>=2.31.0",` | `:55` | 1 |
| `uv.lock` | MODIFY (M6, generated) | `name = "google-genai"` followed by `version = "2.31.0"` | `:6704-6705` | 1 (7 `name =` hits; the package block is the one followed by `version`) |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py` | MODIFY (M6) | `assert installed >= Version("2.23.0"), (` | `:39` (+ `:18,33,41-42`) | 1 |
| `packages/ai-parrot-server/ui/src/lib/config/regeneration-models.ts` | MODIFY (M7) | `value: "google:gemini-2.5-flash",` | `:22` (+ `:62` `DEFAULT_MODEL`, `:66-67` comment) | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatInput.svelte` | MODIFY (M7) | `{ value: "google:gemini-2.5-flash", label: "Gemini 2.5 Flash" },` | `:203` (+ `:204`) | 1 |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json` | MODIFY (M7) | `"gemini-3.8-flash": [` (insert the Argon row before it) · `"last_updated": "2026-06-10",` | `:103` · `:3` | 1 each |
| `docs/**`, `examples/**`, `plugins/agents/epson.py` (41 files, 77 mentions) | MODIFY (M7) | per-file `grep -n 'gemini-2\.5'` at task time | proposal F008 | — |

- No `(unverified — check before use)` entries remain: every row above was grepped at `63e72545ce`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **FEAT-688 shape** (`0137c6595d`, `c76b846670`): enum edit + prefix-gate edit + both catalogue test
  modules in one feature; verify every replacement id against a live `models.list` before merge.
- **TASK-4371 floor blueprint**: introspect in an isolated venv, declare only the exercised version,
  `uv lock --upgrade-package`, never `uv sync` inside a worktree, operator `uv sync` after merge.
- **FEAT-796 builtins** are the single place a component's shipped default lives; the docs table in
  `docs/configuration/llm-defaults.md` mirrors them line for line.
- **Enum members over strings** inside the client satellite (`GoogleModel.GEMINI_3_8_FLASH.value`), plain
  strings in core (`conf.py` cannot import the client — circular import, `conf.py:448-457`).
- Stage only task files; one task = one code commit + one SDD-state commit.

### Known Risks / Gotchas
- **Import-time `AttributeError`** if M5 precedes M2 — enforced by the dependency graph; the M5 task
  must start with `grep -rn 'GoogleModel.GEMINI_2_5_\(FLASH\b\|FLASH_PREVIEW\|PRO\b\|FLASH_TTS\|PRO_TTS\)\|GEMINI_COMPUTER_USE' packages/*/src` returning nothing.
- **Alias-count test** (`test_google_models.py:74-77`) fails between M1 and M5 — M1 does not touch it;
  the M1 task's validation runs the catalogue tests *except* `test_google_model_alias_count`
  (`-k "not alias_count"`), and M5 re-pins 45/28. State this in both task files.
- **Silent alias collapse**: `GEMINI_2_5_FLASH_PREVIEW` is an alias of `GEMINI_2_5_FLASH`; deleting the
  canonical without the alias would just re-canonicalise it. M5 deletes both lines.
- **Argon has no `createCachedContent`**: cache-using call sites fall through `_maybe_apply_gemini_cache`'s
  fail-open branch (WARNING log, payload unchanged). `test_prompt_caching_gemini.py` stays in the
  Validation Contract so a later change cannot make that path raise.
- **`_computer_use_vocabulary` expectation flips** for the 2.5 id once the prefix is gone (`"legacy"` →
  `"v3_8"`); update `test_computer_use_vocabulary.py:25` deliberately, do not keep the dead id "legacy".
- **Exact-key pricing**: without the `gemini-4-argon` row every Argon call is an unpriced
  `_warn_unknown`; the row's numbers come from Google's pricing page at implementation time (M7).
- **Google auto-routes after 12-01**: any pin the guard does not cover (docs, examples, tests) keeps
  working with a different model and bill — hence the broad U3 sweep.
- **`client.py` is hot** (15 commits / 90 days): `/sdd-task` must re-run `grep -c` on every M2 anchor.
- **Stale `build/lib*/` copies** contain 2.5 ids; the guard and AC-1 exclude `build/`.
- **Voice deadline**: M4 ships before 2026-11-17 even if the rest slips; it has no cross-module dependency.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `google-genai` | `>=<gate-verified>` (candidate 2.34.0, was 2.31.0) | SDK half of the request (M6) |
| `packaging` | existing | `Version` compare in `test_reel_sdk_contract.py` |

---

## Decisions

```yaml
schema_version: 1
document_id: google-migration
entries:
  - id: pro-class-default-is-argon
    statement: Google pro-class component defaults (AGENT, CREW, EXPERT judgment, analysis pro sites) are gemini-4-argon, accepting the loss of Gemini context caching on those paths.
    relation: constrains
    about: [clients]
    targets: [file:packages/ai-parrot/src/parrot/experts/policy.py, file:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py, file:packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py]
    contradicts: []
    supersedes: []
    rationale: "Operator decision (proposal U1, 2026-11-04); Argon is the only pro-class 4.x id; gemini-4-argon has no createCachedContent (live models.list) and _maybe_apply_gemini_cache is fail-open."
    rejected_alternatives: ["Google's recommended gemini-3.8-flash for pro sites", "gemini-4-argon everywhere"]
  - id: flash-class-default-is-3-8-flash
    statement: Every flash-class Google default that previously named gemini-2.5-flash names gemini-3.8-flash; gemini-2.5-flash-lite and gemini-2.5-flash-image pins are not touched.
    relation: constrains
    about: [clients]
    targets: [file:packages/ai-parrot-client-google/src/parrot/clients/google/client.py, file:packages/ai-parrot/src/parrot/conf.py]
    contradicts: []
    supersedes: []
    rationale: "Operator decision (proposal U1/U2); gemini-2.5-flash-lite is not deprecated per Google's schedule."
    rejected_alternatives: ["gemini-3.5-flash-lite (Google's auto-route target)", "the gemini-flash-latest alias"]
  - id: retired-gemini-ids-are-deleted
    statement: Retired Gemini ids are deleted from GoogleModel and VertexAIModel together with the prefix-gate clauses that named them; no deprecated_models registry and no runtime remap is introduced.
    relation: forbids
    about: [clients]
    targets: [file:packages/ai-parrot-client-google/src/parrot/clients/google/models.py]
    contradicts: []
    supersedes: []
    rationale: "Continues FEAT-688 U2 (pure deletion) and its 'a dead prefix is worse than a dead member' rule."
    rejected_alternatives: ["deprecated_models mapping surfaced by LLMFactory.list_models"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:d9e004e29c0379f8051d0bbddfd54558385d2f37364c21258725094118c67f6d evaluation_digest=sha256:f820c92f8ea48c6d460db9d509683f5675c2d62d0e32554fa3187b4539e9ce92 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: deprecation, gemini, google-genai, llm-defaults, migration, model-catalog
- Targets resolved: 6/6
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 6,
    "targets_total": 6,
    "unmapped_tags": [
      "deprecation",
      "gemini",
      "google-genai",
      "llm-defaults",
      "migration",
      "model-catalog"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:f820c92f8ea48c6d460db9d509683f5675c2d62d0e32554fa3187b4539e9ce92",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:d9e004e29c0379f8051d0bbddfd54558385d2f37364c21258725094118c67f6d",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:8e4ca23b4588de25ba0dca1cbfc1048c7d33c2b397511bc2648e7da84a9e0f53",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] **U1 — Which ids replace the retired defaults?** — *Resolved in proposal*: Argon for pro-class, `gemini-3.8-flash` for flash-class: AGENT, CREW, EXPERT judgment and the `analysis.py` pro site → `gemini-4-argon`; every flash-class default → `gemini-3.8-flash` (accepting that Argon components lose context caching).
- [x] **U2 — How much of the 2.5 family goes?** — *Resolved in proposal*: pro, flash, both TTS members, computer-use and the voice defaults; move `GoogleVoiceModel` + speech defaults to `gemini-3.8-live` / `gemini-3.8-flash-tts`; keep `gemini-2.5-flash-lite` and `gemini-2.5-flash-image`.
- [x] **U3 — Which surfaces are in scope?** — *Resolved in proposal*: everything, including `examples/` and `plugins/`: src, normative docs, admin UI lists, deploy templates, `VertexAIModel` 2.5 members and the ~75 example/plugin/doc mentions.
- [x] **U4 — SDK floor?** — *Resolved in proposal*: bump to the newest gate-verified google-genai at implementation time (2.34.0 today) via the TASK-4371 isolated-venv introspection; both pyprojects + `uv.lock`.
- [x] **Does `CostCalculator` prefix-match model ids?** — *Resolved during spec research*: no — `calculator.py:301` is an exact `provider_pricing.get(model)`; M7 adds the `gemini-4-argon` row (AC-8).
- [ ] **Q1 — Argon pricing figures** for `pricing/google.json` (`input_per_1m`, `output_per_1m`, `valid_from`) — *Owner: implementer of M7, from Google's pricing page at implementation time; record the source URL and date in the Completion Note.*
- [ ] **Q2 — `bots/search.py:71` `google:gemini-3-flash` is not a catalogue value** (the enum has `gemini-3-flash-preview` as a computer-use alias and `gemini-3.5-flash`); outside the 2.5 scope — *Owner: jlara — open a ledger issue or fold into M3 if desired.*: fix with a real model
- [ ] **Q3 — Should `VertexAIModel` also gain `GEMINI_4_ARGON`?** Argon's availability on Vertex was not probed (FEAT-688 Q3 left Vertex alone). — *Owner: jlara; default: no (non-goal).*: non-goal

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.166.0) · Status: completed
> · Transcript: `sdd/state/FEAT-798/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Verify voice replacements against the live API before deleting the old ids (risk) | CONFIRM | `gemini-3.8-live` / `gemini-3.8-flash-tts` were in no checked-in catalogue; both resolved live on 2026-11-04 (F029), and the check is now a blocking gate per id | §5 AC-12, M4 tests |
| S2 | Treat Argon cache loss as an explicit product contract (risk) | CONFIRM | existing fail-open tests use a 2.5 string; an Argon-specific test proves the new default cannot drop `system_instruction` | M2 tests, §4, §7 |
| S3 | Resolve the `gemini-flash-latest` vs `gemini-3.8-flash` fallback policy (architecture) | CONFIRM | one rule: method defaults and fallback chains name `GEMINI_3_8_FLASH`; `_default_model` stays (FEAT-688 U4) | §2 Overview "Fallback policy" |
| S4 | Keep string routing for the 2.5 computer-use id while removing catalogue publication (risk) | REJECT | Google shut `gemini-2.5-computer-use-preview-10-2025` down on 2026-07-28 (F028); routing an unreachable id contradicts the FEAT-688 dead-prefix rule. The behavioural flip is made deliberate by updating `test_google_computer_use.py` and `test_computer_use_vocabulary.py` in M2 | — |
| S5 | Exact pricing coverage for Argon with `cost_usd` + `revision_for` tests (risk) | CONFIRM | `calculator.py:301` is exact-key; row + test added | M7, §4, AC-8 |
| S6 | Make the public enum deletion policy explicit with negative tests and a documented breaking contract (api) | CONFIRM | negative tests already in M5; a migration doc now states the breaking contract | M3 docs (`docs/migration/gemini-2-5-retirement.md`), AC-15 |
| S7 | Make the retirement guard token-aware and consistent with non-goals (testing) | CONFIRM | whole-id matching already specified; `clients/base.py` comment mentions added as a reviewed exclusion so the non-goal and the guard agree | M5 skeleton, AC-1 |
| S8 | Validate hand-maintained UI lists against the backend catalogue (api) | CONFIRM (partial) | `google:gemini-3-pro-preview` is not a catalogue value → fixed in M7; a cross-language consistency test is rejected as out of scope (no vitest for this file, UI gate is `pnpm build`) | M7 skeleton |
| S9 | Operational migration contract for explicit overrides (risk) | CONFIRM | overrides are preserved by design; documented + `test_explicit_override_preserves_retired_id` | M3 docs/tests, §4 |
| S10 | Keep the SDK floor bump independently gate-verifiable (testing) | CONFIRM | M6 is its own exclusive task with the TASK-4371 gate | M6 |
| S11 | Resolve the pre-existing `google:gemini-3-flash` drift explicitly (alternative) | ESCALATE | outside the 2.5 scope; the operator decides whether to fold it into M3 | §8 Q2 |

Summary: **9** confirmed (one partial) · **1** rejected · **1** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-04 | jlara@trocglobal.com | Initial draft from the accepted FEAT-798 proposal (U1–U4 carried forward) |
