---
type: feature
base_branch: dev
projects: [ai-parrot-client-google, ai-parrot-embeddings, ai-parrot-server, ai-parrot]
tags: [google-genai, model-catalog, gemini, llm-clients, deprecation]
---

# Feature Specification: Raise the google-genai floor and refresh GoogleModel for Gemini 4.x (Argon)

**Feature ID**: FEAT-688
**Date**: 2026-10-15
**Author**: jlara@trocglobal.com
**Status**: approved
**Target version**: `google-genai>=2.31.0` *(candidate — declared only after the introspection gate in M3; see §8 Q1)*

---

## 1. Motivation & Business Requirements

### Problem Statement

Google shipped the Gemini 4.x generation. `GoogleModel` does not carry it, so the model
cannot be selected through the catalogue, is not published by the `/models` endpoint and
is not reachable through `LLMFactory`. At the same time the catalogue has drifted: four of
its identifiers no longer exist upstream.

Research (`sdd/state/FEAT-688/`, proposal `sdd/proposals/gemini-upgrade.proposal.md`)
established three constraints that shape the work:

1. **The enum is not the routing table.** Capability decisions in `GoogleGenAIClient` are
   hardcoded `startswith()` tests over the model string — `_default_combined_call_prefixes`
   (combined tools + `response_schema` in a single call), `_requires_thinking`,
   `_rejects_zero_thinking_budget`, `_is_computer_use_model`, and `_is_gemini3_model` (which
   drives Vertex AI `location="global"` and the per-loop client cache key). A `gemini-4…`
   identifier added to the enum alone is **accepted without error** and silently routed down
   the conservative two-phase reformat path.
2. **`GoogleModel` is a plain `Enum` with 19 silent aliases** — 53 names collapse onto 34
   distinct values — and it is serialized verbatim over HTTP by
   `handlers/google_generation.py`, so a catalogue edit is a public API change.
3. **The two `google-genai` floors diverge** (`>=2.23.0` in `ai-parrot-client-google`,
   `>=2.18.1` in `ai-parrot-embeddings`), and `ai-parrot-client-google/pyproject.toml`
   documents a policy that only a version actually exercised may be declared as the floor.

Live verification of the catalogue was performed on **2026-10-15** against
`generativelanguage.googleapis.com/v1beta/models` with the workspace key, and model
behaviour was probed by raw REST — the same method `_rejects_zero_thinking_budget`
documents for its own evidence. Everything asserted below about upstream comes from that
run, not from documentation or recall.

### Goals

- Add `GoogleModel.GEMINI_4_ARGON = "gemini-4-argon"`.
- Retire, **by deletion**, the four identifiers that no longer exist upstream
  (`gemini-3.7-pro`, `gemini-3.7-flash-thinking`, `gemini-3.7-flash-lite`,
  `gemini-deep-research-preview-04-2026`) together with every call site that names them.
- Whitelist `"gemini-4-argon"` in `_default_combined_call_prefixes` (verified: Argon accepts
  `tools` + `responseSchema` in one call) and drop `"gemini-3.7-pro"` from it.
- Generalize `_is_gemini3_model` to `_is_modern_gemini_model` so the Vertex `location="global"`
  rule and the client cache key cover the 4.x family as well as 3.x.
- Align both `google-genai` floors to a single version that the feature run actually exercises.
- Keep the test modules that pin the catalogue honest, and add coverage for Argon.

### Non-Goals (explicitly out of scope)

- **No `GoogleGenAIClient.deprecated_models` registry.** Operator decision (proposal §5 U2):
  retirement is pure deletion. The registry was considered and rejected; see §7 "Rejected
  alternatives" for why it would not have bought what it appears to buy.
- **No change to the client defaults.** `_default_model`, `_fallback_model`,
  `_lightweight_model` and `_default_reformat_model` stay on 3.x (U4). Argon is opt-in.
- **`VertexAIModel` is untouched** (U5), including its own `GEMINI_3_7_PRO`: absence from the
  Gemini Developer API listing is not evidence about Vertex availability (§8 Q3).
- **No `IMAGEN_*` retirement.** The listing returns *no* imagen model at all for this key, so
  their absence is inconclusive, not a sunset signal (§8 Q4).
- No catalogue expansion beyond Argon — roughly 28 further live identifiers are missing from
  the enum and are deliberately deferred (§8 Q2).
- No refactor of the prefix gates into capability metadata on the enum.
- No relocation of the Google tests into the satellite distribution (FEAT-523 leftover).
- No change to `parrot/clients/base.py` or the `LLMFactory` contract.

---

## 2. Architectural Design

### Overview

Three layers, in dependency order:

1. **Catalogue** (`models.py`) — one member added, five removed (four values, one of them
   held by two aliased names).
2. **Routing gates** (`client.py`) — the prefix whitelist and the generation predicate are
   what actually give Argon the fast path; the retirement of `gemini-3.7-pro` must come out
   of two gates in the same commit or they keep matching a dead identifier.
3. **Packaging & tests** (`pyproject.toml` ×2, `uv.lock`, three edited test modules plus
   the existing computer-use enum regression module).

### Component Diagram

```
GoogleModel (Enum, pure data)
   │  53 names / 34 values  →  49 names / 31 values
   ├── +1  GEMINI_4_ARGON = "gemini-4-argon"
   └── −5  GEMINI_3_7_PRO · GEMINI_3_7_FLASH_THINKING · GEMINI_3_7_FLASH_LITE
           GEMINI_DEEP_RESEARCH · GEMINI_DEEP_RESEARCH_PREVIEW
   │
   ├──→ handlers/google_generation.py:42  →  public /models  (34 → 31 ids)
   └──→ GoogleGenAIClient.models          →  LLMFactory.list_models("google")["active"]

GoogleGenAIClient.ask()/ask_stream()/invoke(model)
   ├── _supports_combined_tools_and_schema → _default_combined_call_prefixes
   │        +"gemini-4-argon"   −"gemini-3.7-pro"
   ├── _requires_thinking                  −"gemini-3.7-pro"   (Argon NOT added — verified)
   └── _is_modern_gemini_model (was _is_gemini3_model: gemini-3 → gemini-3 | gemini-4)
            ├── get_client()       → Vertex AI location="global"
            └── _model_class_key() → per-loop client cache key
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GoogleModel` | modifies enum | +1 member, −5 members |
| `GoogleGenAIClient._default_combined_call_prefixes` | modifies tuple | +`gemini-4-argon`, −`gemini-3.7-pro` |
| `GoogleGenAIClient._requires_thinking` | modifies predicate | −`gemini-3.7-pro`; Argon deliberately not added |
| `GoogleGenAIClient._is_gemini3_model` | renames + widens | → `_is_modern_gemini_model` (`gemini-3` or `gemini-4`) |
| `GoogleGenAIClient._model_class_key` / `get_client` | call-site update | the two consumers of that predicate |
| `handlers/google_generation.py:42-44` | consumes enum | public `/models` payload shrinks by 3 ids |
| `LLMFactory.list_models` | consumes `models` | `deprecated` stays `[]` for Google, by decision (U2) |
| `MODEL_WINDOWS` (`memory/compaction/budget.py:51`) | prefix match | `"gemini-": 1_048_576` — correct for Argon, no edit |
| `packages/ai-parrot/tests/test_google_models.py` | pins name→value | 3 assertions reference retired ids |

### Data Models

```python
# packages/ai-parrot-client-google/src/parrot/clients/google/models.py
class GoogleModel(Enum):
    """Enum for Google AI models."""

    GEMINI_FLASH_LATEST = "gemini-flash-latest"
    ...
    # Gemini 4.x series (Argon)
    GEMINI_4_ARGON = "gemini-4-argon"
    # Gemini 3.8 series
    GEMINI_3_8_FLASH = "gemini-3.8-flash"
    # Gemini 3.7 series
    GEMINI_3_7_FLASH = "gemini-3.7-flash"
    # (GEMINI_3_7_PRO / GEMINI_3_7_FLASH_THINKING / GEMINI_3_7_FLASH_LITE removed —
    #  no longer served by the Gemini API as of 2026-10-15)
```

Verified properties of `gemini-4-argon` (live `models.get`, 2026-10-15):

| Property | Value | Consequence |
|---|---|---|
| `displayName` | `Gemini 4 Argon` | — |
| `inputTokenLimit` | `1048576` | `MODEL_WINDOWS["gemini-"]` is already exact — no edit |
| `outputTokenLimit` | `32768` | above `_invoke_max_tokens = 16384`; no edit needed |
| `thinking` | `true` | thinking is *available*, not mandatory — see below |
| `supportedGenerationMethods` | `generateContent`, `countTokens`, `batchGenerateContent` | **no `createCachedContent`** → see §7 gotchas |

### New Public Interfaces

```python
# packages/ai-parrot-client-google/src/parrot/clients/google/client.py

    @staticmethod
    def _is_modern_gemini_model(model: str) -> bool:
        """Check if a model belongs to a modern Gemini generation (3.x or 4.x).

        Modern generations require location='global' on Vertex AI and are cached
        under their own client-class key. Renamed from ``_is_gemini3_model`` when
        the 4.x family landed; the predicate is private and has no external callers.
        """
        model = GoogleGenAIClient._as_model_str(model)
        return bool(model) and (model.startswith("gemini-3") or model.startswith("gemini-4"))
```

No new public interface is added. `_is_modern_gemini_model` is private and every call site
lives in `client.py`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Catalogue refresh | yes | `models.py` only — exact add/delete list below | — |
| M2: Routing gates | yes | `client.py` only — exact line anchors below | — |
| M3: Dependency floor + tests | yes | two `pyproject.toml`, `uv.lock`, and three edited test modules; four modules validated against the measured floor and locked environment | — |

### Module 1: Catalogue refresh

- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
- **Responsibility**: add Argon; delete the four dead identifiers from `GoogleModel`.
- **Depends on**: nothing.
- **Exact edits**:
  - insert `GEMINI_4_ARGON = "gemini-4-argon"` under a new `# Gemini 4.x series (Argon)`
    comment, immediately before the `# Gemini 3.8 series` block (currently line 18).
  - delete lines 22, 23, 24 (`GEMINI_3_7_PRO`, `GEMINI_3_7_FLASH_THINKING`,
    `GEMINI_3_7_FLASH_LITE`) and lines 54, 55 (`GEMINI_DEEP_RESEARCH`,
    `GEMINI_DEEP_RESEARCH_PREVIEW`).
  - `GEMINI_3_7_FLASH = "gemini-3.7-flash"` (line 21) **stays** — still served upstream.
  - `VertexAIModel` (lines 76-99) is not touched.
- **Post-condition**: 49 names, 31 distinct values, 18 aliases.

### Module 2: Routing gates

- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
- **Responsibility**: give Argon the single-call path, stop matching a dead identifier,
  and widen the generation predicate to 4.x.
- **Depends on**: M1.
- **Exact edits**:
  1. `_default_combined_call_prefixes` (lines 148-157): add `"gemini-4-argon"` as the first
     entry; remove `"gemini-3.7-pro"` (line 151).
  2. `_requires_thinking` (lines 270-285): remove `or model.startswith("gemini-3.7-pro")`
     (line 281). **Do not add Argon** — verified by REST that `thinkingBudget: 0` returns
     `200 OK`, so Argon is not thinking-only. `_rejects_zero_thinking_budget` is a superset
     of this predicate and needs no separate edit.
  3. Rename `_is_gemini3_model` → `_is_modern_gemini_model` (def at line 230) and widen the
     match to `gemini-3` or `gemini-4`; update the two call sites (line 440 in
     `_model_class_key`, line 671 in `get_client`) and the two docstring references
     (lines 401 and 661).
  4. `_model_class_key` (lines 433-443): the returned key must distinguish generations, so
     `f"gemini3_{suffix}"` becomes a generation-derived key:
     ```python
     if self._is_modern_gemini_model(model):
         generation = "gemini4" if GoogleGenAIClient._as_model_str(model).startswith("gemini-4") else "gemini3"
         suffix = "preview" if self._is_preview_model(model) else "stable"
         return f"{generation}_{suffix}"
     return "default"
     ```
     The key is an opaque cache-invalidation token; no test and no other module asserts its
     literal value (verified by repo-wide grep).
- **Not in scope for M2**: `_is_computer_use_model` (its `gemini-3-flash-preview` prefix is
  still a live model), `_zero_thinking_config`, `_invoke_thinking_config`, and the eight
  inline `ThinkingConfig(...)` construction sites — Argon needs none of them changed.

### Module 3: Dependency floor and tests

- **Paths**: `packages/ai-parrot-client-google/pyproject.toml`,
  `packages/ai-parrot-embeddings/pyproject.toml`, `uv.lock`,
  `packages/ai-parrot/tests/test_google_models.py`,
  `packages/ai-parrot/tests/test_google_client.py`,
  `packages/ai-parrot/tests/test_llm_factory.py`
- **Additional validation-only module**: `packages/ai-parrot/tests/clients/test_google_models.py`.
- **Depends on**: M1, M2.
- **Floor procedure** (the package's own documented policy: declare only what was run):
  1. Activate the workspace venv with `source .venv/bin/activate`, then
     `uv pip install "google-genai==<candidate>"` — candidate `2.31.0`.
     The proposal's SDK probes used `2.24.0`; the current `uv.lock` resolves `2.28.0`.
     Record the installed version separately from the locked version.
  2. Introspect the surfaces this client actually uses (`genai.Client`, `types.ThinkingConfig`,
     `types.ComputerUse`, `aio.caches.create`, `aio.live.music.connect`, `aio.aclose`,
     `google.genai.errors`) and run all four test modules below. Record the SDK version
     and test evidence under `artifacts/logs/`.
     If the candidate fails, install `google-genai==2.24.0` and repeat these checks before
     choosing it as the fallback floor. Presence in a lockfile is not test evidence.
  3. Declare that exact version as the floor in **both** packages, and extend the existing
     comment block in `ai-parrot-client-google/pyproject.toml:17-27` with the date and what
     was introspected, matching the style already there.
  4. Regenerate and commit the workspace `uv.lock` alongside the manifests using `uv lock`.
     Verify that its Google dependency metadata matches both manifests and its resolved
     SDK version satisfies the chosen floor; run `uv lock --check`.
  5. Sync the validation environment from that lock with `uv sync --frozen --all-packages`,
     then repeat the SDK introspection and all four test modules. Record the installed
     version again: it must equal the lock's resolution. If it differs from the tested
     minimum, retain evidence for both versions. The Makefile uses frozen installs, so
     a local `uv pip install` alone does not validate the shipped dependency resolution.
  - `google-genai` declares **no** `google-cloud-storage` or `google-cloud-aiplatform`
    dependency in either `2.24.0` or `2.31.0` (identical `requires_dist`), so this bump
    cannot move `google-cloud-storage`. The `<=3.1.0` caveat in
    `ai-parrot-embeddings/pyproject.toml:47-55` is about `google-cloud-aiplatform`, which this
    feature does not declare.
- **Test edits**: see §4.

---

## 4. Test Specification

### Unit Tests

| Test | File | Description |
|---|---|---|
| `test_google_model_enum_has_gemini_4_argon` | `packages/ai-parrot/tests/test_google_models.py` | `GoogleModel.GEMINI_4_ARGON.value == "gemini-4-argon"` |
| `test_google_model_lookup_by_value` (extend) | `packages/ai-parrot/tests/test_google_models.py:31-39` | add `GoogleModel("gemini-4-argon") is GoogleModel.GEMINI_4_ARGON`; **remove** line 39 (`gemini-3.7-pro`) |
| `test_google_model_enum_has_gemini_3_7_flash` (edit) | `packages/ai-parrot/tests/test_google_models.py:16-21` | keep the `gemini-3.7-flash` assertion; **remove** lines 19-20 (`GEMINI_3_7_PRO`, `GEMINI_3_7_FLASH_THINKING`) |
| `test_google_model_retired_ids_absent` | `packages/ai-parrot/tests/test_google_models.py` | each of the four retired values raises `ValueError` through `GoogleModel(...)`, and the five names are absent from `__members__` |
| `test_google_model_alias_count` | `packages/ai-parrot/tests/test_google_models.py` | `len(GoogleModel.__members__) == 49` and `len({m.value for m in GoogleModel}) == 31` — guards against a new member silently collapsing onto an existing value |
| `test_whitelisted_returns_true` (extend) | `packages/ai-parrot/tests/test_google_client.py:355-366` | add `"gemini-4-argon"` to the parametrize list |
| `test_unwhitelisted_returns_false` (edit) | `packages/ai-parrot/tests/test_google_client.py:367-378` | add `"gemini-3.7-pro"` — it must now be **False** |
| `test_argon_is_not_thinking_only` | `packages/ai-parrot/tests/test_google_client.py` | `_requires_thinking("gemini-4-argon") is False` and `_rejects_zero_thinking_budget("gemini-4-argon") is False` |
| `test_is_modern_gemini_model` | `packages/ai-parrot/tests/test_google_client.py` | True for `gemini-3.5-flash` / `gemini-4-argon`; False for `gemini-2.5-pro`, `""`, `None`; accepts a `GoogleModel` member |
| `test_model_class_key_separates_generations` | `packages/ai-parrot/tests/test_google_client.py` | `_model_class_key("gemini-4-argon") != _model_class_key("gemini-3.5-flash")`, and a 2.x model still returns `"default"` |

The docstring at `packages/ai-parrot/tests/test_google_client.py:351` names `_is_gemini3_model`
and must be updated with the rename.

### Integration Tests

| Test | Scope | Description |
|---|---|---|
| `test_llm_factory_lists_argon` | `packages/ai-parrot/tests/test_llm_factory.py` | `"gemini-4-argon" in LLMFactory.list_models("google")["active"]`; `["deprecated"] == []` for Google (asserts the U2 decision explicitly, so a future registry is a deliberate change) |
| `/models` catalogue | `packages/ai-parrot-server` | no new test — `handlers/google_generation.py` serializes the enum; covered by the enum tests. The payload shrinking from 34 to 31 ids is an intended public API change (§7) |

### Test Data / Fixtures

`GoogleGenAIClient` can be constructed with `api_key="fake"` for the gate tests — the existing
`_build_mocked_client` helper at `packages/ai-parrot/tests/test_google_client.py:469` is the
established pattern. None of the tests above performs network I/O.

Run with:

```bash
source .venv/bin/activate
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src \
  pytest packages/ai-parrot/tests/test_google_models.py \
         packages/ai-parrot/tests/clients/test_google_models.py \
         packages/ai-parrot/tests/test_google_client.py \
         packages/ai-parrot/tests/test_llm_factory.py -q
```

---

## 5. Acceptance Criteria

- [ ] `GoogleModel.GEMINI_4_ARGON.value == "gemini-4-argon"` and `GoogleModel("gemini-4-argon")`
      resolves to it.
- [ ] `GoogleModel` has 49 names and 31 distinct values; the five retired names are gone and
      each of the four retired values raises `ValueError` on lookup.
- [ ] No reference to `gemini-3.7-pro`, `gemini-3.7-flash-thinking`, `gemini-3.7-flash-lite` or
      `gemini-deep-research-preview-04-2026` remains under `packages/*/src` or `packages/*/tests`
      except inside `VertexAIModel` and the retirement regression tests specified in §4
      (negative enum lookups, absent-member checks, and rejected combined-call prefixes).
      Inspect grep matches against these explicit exceptions; no positive Google catalogue
      assertions or production routing references to retired identifiers may remain.
- [ ] `_supports_combined_tools_and_schema("gemini-4-argon", GoogleGenAIClient._default_combined_call_prefixes)`
      is `True`; the same call for `"gemini-3.7-pro"` is `False`.
- [ ] `_requires_thinking("gemini-4-argon")` and `_rejects_zero_thinking_budget("gemini-4-argon")`
      are both `False`.
- [ ] `_is_gemini3_model` no longer exists; `_is_modern_gemini_model` returns `True` for both
      `gemini-3*` and `gemini-4*` and is used by `_model_class_key` and `get_client`.
- [ ] `_model_class_key` returns distinct keys for a 3.x and a 4.x model and `"default"` for 2.x.
- [ ] Both `pyproject.toml` files declare the **same** `google-genai` floor, and that version is
      the one installed and exercised by the feature's test run; the rationale comment in
      `ai-parrot-client-google/pyproject.toml` records the date and what was introspected.
- [ ] `uv.lock` is regenerated with matching manifest metadata and an SDK resolution at or
      above the chosen floor; `uv lock --check` passes. SDK introspection and all four test
      modules pass after a frozen sync, with evidence recording the actual locked version
      separately from the tested floor when they differ.
- [ ] `LLMFactory.list_models("google")["active"]` contains `"gemini-4-argon"` and `["deprecated"]`
      is `[]`.
- [ ] All four test modules in §4 pass, including `test_llm_factory_lists_argon`, and
      `ruff check` is clean on every edited Python file.

---

## 6. Codebase Contract

> Every line number below was re-verified against the working tree on 2026-10-15 with raw
> `grep` (rtk-filtered output can shift line numbers; `rtk proxy grep` was used).

### Verified Imports

```python
from parrot.clients.google.models import GoogleModel      # models.py:11
from parrot.clients.google.client import GoogleGenAIClient  # client.py:103
from parrot.clients.factory import LLMFactory             # factory.py:224 (list_models)
from parrot.memory.compaction.budget import MODEL_WINDOWS  # budget.py:51 ("gemini-": 1_048_576)
```

### Existing Class Signatures

```python
# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):   # line 103
    models: type[Enum] = GoogleModel                                          # line 125
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value               # line 127
    _fallback_model: str = "gemini-3.1-flash-lite"                            # line 128
    _lightweight_model: str = "gemini-3.1-flash-lite"                         # line 130
    _invoke_max_tokens: int = 16384                                           # line 137
    _default_combined_call_prefixes: tuple[str, ...]                          # line 148
    @staticmethod
    def _is_gemini3_model(model: str) -> bool                                 # line 230
    @staticmethod
    def _requires_thinking(model: str) -> bool                                # line 270
    @staticmethod
    def _rejects_zero_thinking_budget(model: str) -> bool                     # line 288
    @classmethod
    def _thinking_off(cls, model: str, **kwargs) -> Optional[ThinkingConfig]  # line 321
    def _invoke_thinking_config(self, model, *, structured)                   # line 340
    @staticmethod
    def _is_computer_use_model(model: str) -> bool                            # line 374
    @staticmethod
    def _supports_combined_tools_and_schema(model, prefixes) -> bool          # line 394
    @staticmethod
    def _as_model_str(model) -> str                                           # line 420
    def _model_class_key(self, model: str) -> str                             # line 433
    async def _maybe_apply_gemini_cache(self, client, model, payload, segments)  # line 518
    async def get_client(self, model: str = None, **kwargs) -> genai.Client   # line 639
```

### Integration Points

```python
# packages/ai-parrot/src/parrot/clients/factory.py:253
"deprecated": list(getattr(client_class, "deprecated_models", None) or {}),
# → Google defines no `deprecated_models`; this stays `[]` by decision (U2).

# packages/ai-parrot-server/src/parrot/handlers/google_generation.py:42-44
return [model.value for model in GoogleModel]    # 34 ids today → 31 after M1

# packages/ai-parrot/src/parrot/conf.py:454-456
# holds the literal "gemini-flash-latest" on purpose — core must stay enum-free. Do not touch.
```

### Does NOT Exist (Anti-Hallucination)

- `GoogleGenAIClient._build_thinking_config` — **does not exist**, under any name. Thinking is
  handled by `_requires_thinking` (270), `_rejects_zero_thinking_budget` (288), `_thinking_off`
  (321), `_invoke_thinking_config` (340) plus eight inline `ThinkingConfig(...)` literals
  (lines 1185, 3419, 3428, 3784, 4228, 4234, 4554, 5266). None of them needs editing here.
- `GoogleGenAIClient._cache_key_for_model` — does not exist; the real helper is
  `_model_class_key` (line 433).
- `GoogleGenAIClient.deprecated_models` — does not exist and is **not** being added (U2).
  `DEPRECATIONS` / `DeprecationInfo` exist only in `parrot.clients.openai.models` (lines 69, 85).
- `packages/ai-parrot/tests/clients/test_google_client.py` and `.../tests/clients/test_factory.py`
  — do not exist. The real files are `packages/ai-parrot/tests/test_google_client.py`,
  `packages/ai-parrot/tests/clients/test_google_models.py` and
  `packages/ai-parrot/tests/test_llm_factory.py`.
- `GoogleModel.GEMINI_4_PRO`, `GEMINI_4_FLASH` — upstream publishes exactly one 4.x id today,
  `gemini-4-argon`.
- `types.ThinkingConfig(thinking_level=...)` as a *required* parameter for 4.x — `thinking_level`
  exists already in the installed `2.24.0` alongside `thinking_budget`, and Argon accepts both.

### Edit Sites (Blueprint Anchors)

| File | Target | Line(s) | Purpose |
|---|---|---|---|
| `…/google/models.py` | `GoogleModel` | before 18 | add `GEMINI_4_ARGON` |
| `…/google/models.py` | `GoogleModel` | 22, 23, 24 | delete the three 3.7 members |
| `…/google/models.py` | `GoogleModel` | 54, 55 | delete both deep-research members |
| `…/google/client.py` | `_default_combined_call_prefixes` | 148-157 | +`gemini-4-argon`, −`gemini-3.7-pro` (151) |
| `…/google/client.py` | `_requires_thinking` | 281 | drop the `gemini-3.7-pro` clause |
| `…/google/client.py` | `_is_gemini3_model` | 230-239 | rename + widen to `gemini-4` |
| `…/google/client.py` | `_model_class_key` | 433-443 | call-site update + generation-derived key |
| `…/google/client.py` | `get_client` | 671 | call-site update |
| `…/google/client.py` | docstrings | 401, 661 | rename references |
| `packages/ai-parrot-client-google/pyproject.toml` | `dependencies` | 17-27 | floor + rationale comment |
| `packages/ai-parrot-embeddings/pyproject.toml` | `google` extra | 47-55 | align floor; leave the aiplatform caveat intact |
| `uv.lock` | Google SDK resolution and workspace dependency metadata | generated | regenerate from manifests; validate frozen installation |
| `packages/ai-parrot/tests/test_google_models.py` | assertions | 16-21, 31-39 | drop retired ids, add Argon |
| `packages/ai-parrot/tests/test_google_client.py` | `TestSupportsCombinedToolsAndSchema` | 345-400 | parametrize updates + new gate tests |
| `packages/ai-parrot/tests/test_llm_factory.py` | new `test_llm_factory_lists_argon` | new test | verify active Argon and empty deprecated catalogue; include in validation command |

---

## 7. Implementation Notes & Constraints

### Evidence behind the catalogue decisions

Live listing of `models.list` (63 models, no pagination) diffed against the 34 enum values,
2026-10-15:

| Enum value | Upstream | Decision |
|---|---|---|
| `gemini-3.7-pro` | absent (only `gemini-3.7-flash` survives) | delete |
| `gemini-3.7-flash-thinking` | absent | delete |
| `gemini-3.7-flash-lite` | absent | delete |
| `gemini-deep-research-preview-04-2026` | renamed upstream to `deep-research-preview-04-2026` (no `gemini-` prefix) | delete — and note `client.py:5348` already hardcodes the live `deep-research-pro-preview-12-2025`, so nothing depends on the enum member |
| `imagen-3.0-generate-002`, `imagen-4.0-*` | absent — but **no** imagen model is listed at all | keep (§8 Q4) |
| everything else | present | keep |

REST probes against `gemini-4-argon` (`generateContent`, 2026-10-15):
`thinkingBudget: 0` → `200 OK`; `thinkingLevel: "LOW"` → `200 OK`; `tools` +
`responseSchema` in one request → `200 OK` with a `functionCall`, matching the behaviour of
the already-whitelisted `gemini-3.8-flash`.

### Patterns to Follow

- **The three-part footprint** of `b4427bb66` and `f1dda8ffd`: enum member + prefix-whitelist
  entry + test assertion. Nothing else was needed to add a model in either precedent.
- **Floors, never ceilings** — all four existing `google-genai` pins are `>=`.
- **Declare only what was run** — the rationale comment at
  `ai-parrot-client-google/pyproject.toml:17-27` is the contract for M3.
- **Core stays enum-free** — `conf.py:454-456` keeps a string literal on purpose.

### Known Risks / Gotchas

- **Silent alias collapse.** `GoogleModel` is a plain `Enum`: a new member whose value already
  exists becomes an invisible alias (`GEMINI_3_FLASH_PREVIEW` is one today — its value is
  `gemini-3.5-flash`). `test_google_model_alias_count` is the guard.
- **Load-bearing names.** Twelve members are referenced by name across the live `src/` trees;
  deleting one is an `AttributeError` at import, not a fallback. None of the five members
  deleted here is among them — verified: the only name-level reference among the retirement
  candidates was `GoogleModel.IMAGEN_4` (`generation.py:234`), and `IMAGEN_*` is **not** being
  deleted.
- **A dead prefix is worse than a dead member.** `gemini-3.7-pro` lives in two gates
  (`client.py:151`, `client.py:281`). Deleting the enum member without them leaves predicates
  matching an identifier the API no longer serves.
- **Public API change.** `/models` drops from 34 to 31 ids. Intended; no deprecation window
  (project stance: no external consumers, hard cuts are acceptable).
- **Argon has no context caching.** `createCachedContent` is absent from its
  `supportedGenerationMethods`. The caching path (`_maybe_apply_gemini_cache`, line 518) is
  already fail-open — it logs a WARNING and proceeds uncached — so no code change is required;
  expect that warning when cache hints are used with Argon.
- **Argon's output ceiling is 32768**, half of what the 3.x family allows. `_default_max_tokens`
  is `None` (provider default) and `_invoke_max_tokens` is 16384, so both stay within it.

### Rejected alternatives

**`GoogleGenAIClient.deprecated_models` registry** (mirroring `OpenAIClient`) — rejected by the
operator (U2), and the research shows it would not deliver the benefit usually claimed for it:
no code path resolves or redirects a model through that mapping. `factory.py:253` takes
`list(...)` of its **keys** and `studio/catalog.py:244` republishes them; nothing consults it at
call time. A retired id therefore still raises `ValueError` from `GoogleModel(...)` whether or
not the registry exists. If a registry is wanted later it should be specified as a real
resolution seam, with OpenAI's `dict[str, DeprecationInfo]` shape (`shutoff`, `alias`), not as
`dict[str, str]`.

### External Dependencies

- `google-genai` — floor raised; proposal probes used `2.24.0`, while the current lock resolves
  `2.28.0`. The proposal reports `2.30.1` and `2.31.0` available
  on PyPI. Both `2.24.0` and `2.31.0` declare the identical runtime dependency set
  (`anyio`, `google-auth`, `httpx`, `pydantic>=2.12.5`, `requests`, `tenacity<9.2.0`,
  `websockets<17.0`, `typing-extensions`, `distro`, `sniffio`) — no Google Cloud packages.
  The workspace satisfies all of them today (pydantic 2.13.5, websockets 16.1.1, tenacity 9.1.4).
- A `GOOGLE_API_KEY` is needed only to re-run the live verification in §7; none of the specified
  tests requires it.

---

## 8. Open Questions

- [x] **Q0 — FEAT-ID.** *Resolved*: reserved **FEAT-688** via `reserve_ids.py`. The provisional
      `FEAT-672` had meanwhile been reserved on `origin/dev` by `github-reviewer-local-repo-wiki`
      (`b4aeee23d`); this feature's research state moved to `sdd/state/FEAT-688/`.
- [ ] **Q1 — Which exact `google-genai` version becomes the floor?** The requirement "raise the
      floor" is settled; the number is not. M3 fixes it procedurally (install → introspect/test →
      declare → lock → frozen-sync validation), with `2.31.0` as the candidate and `2.24.0`
      as the fallback, each requiring its own measured test run. Nothing in this
      feature *needs* a version above `2.24.0`: `thinking_level` is already present there, and
      Argon answers today's installed SDK. Decide whether to take the latest or stay at the
      exercised floor. *Owner*: operator / M3.
- [ ] **Q2 — Do the other ~28 live identifiers join the catalogue?** `models.list` returns ids the
      enum lacks, including `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts`, `gemini-3.8-live`,
      `gemini-3.8-live-extended-thinking`, `gemini-3.5-transcribe(-live)`,
      `gemini-3.5-live-translate-preview`, `gemini-3.1-flash-image-preview`,
      `gemini-3.1-flash-lite-preview`, `gemini-3-pro-image-preview`, `gemini-nano-banana-2.1`,
      `gemini-omni-flash-preview`, `gemini-omni-1.1-flash`, `gemini-robotics-er-2(-streaming)-preview`,
      `gemini-embedding-001`, `gemini-embedding-2(-preview)`, `gemini-flash-lite-latest`,
      `gemini-pro-latest`, `gemini-2.5-flash-native-audio-*`, the three `deep-research-*` ids,
      `lyria-3.5`, `lyria-realtime-exp`, `gemma-4-26b-a4b-it`, `gemma-4-31b-it`. Deliberately out of
      scope: each one may carry its own routing gate. *Owner*: operator — likely its own feature.
- [ ] **Q3 — `VertexAIModel.GEMINI_3_7_PRO`.** Dead on the Gemini Developer API, unknown on Vertex.
      Verify against the Vertex `publishers/google/models` listing before retiring it; untouched here
      by decision U5. *Owner*: operator (needs a Vertex project).
- [ ] **Q4 — `IMAGEN_*` members.** No imagen model appears in the Developer API listing at all, so
      absence proves nothing — imagen is served through a different surface. Verify on that surface
      (or on Vertex) before any retirement. *Owner*: operator.
- [ ] **Q5 — Should the alias-count guard be a permanent invariant?** `test_google_model_alias_count`
      pins 49/31 and will fail on every future catalogue edit — which is the point, but it makes the
      test a maintenance tax. Confirm that trade-off, or weaken it to "no new value collides with an
      existing one". *Owner*: reviewer.

---

## 9. Design Research Cross-Check

| Source | Finding | Status in this spec |
|---|---|---|
| F001 | `GoogleModel`/`VertexAIModel` in `clients/google/models.py`, pure data, 53 + 17 members | M1 anchors |
| F002 | 19 silent aliases, 53 names → 34 values | alias-count guard (§4), post-condition 18/49/31 |
| F004 | Capability gates are string prefixes; a `gemini-4…` id degrades silently | M2 — the core of the feature |
| F005 | `deprecated_models` seam exists; only OpenAI uses it | rejected alternative (§7), with the extra finding that nothing resolves through it |
| F006 | Enum published over HTTP; three test modules pin it | §2 integration points, §4 |
| F007 | Precedents `f1dda8ffd` / `b4427bb66` — enum + whitelist + tests | §7 patterns |
| F008 | External research failed during the proposal phase | **superseded** — resolved 2026-10-15 by live `models.list` + REST probes + PyPI metadata (§7) |
| F009 | `MODEL_WINDOWS["gemini-"] = 1_048_576` | confirmed exact for Argon — no edit |
| F010 | 12 load-bearing member names | checked against the retirement list; no intersection |

Decisions carried over from the proposal: **U2** pure deletion, **U4** defaults stay 3.x,
**U5** `GoogleModel` only. **U1** (model ids, retirement list) is now resolved by measurement;
its dependency-floor half survives as Q1. **U3** is resolved: Argon joins
`_default_combined_call_prefixes` (probe-verified) and is *not* thinking-only (probe-verified).

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-10-15 | jlara@trocglobal.com | Initial draft |
| 2026-10-15 | jlara@trocglobal.com | Full rewrite. Restored U2 (pure deletion) — removed the `deprecated_models` goal, module, AC and tests. Replaced the unverified `thinking_level`-replaces-`thinking_budget` premise and the `google-cloud-storage` conflict premise with measured evidence. Fixed the Codebase Contract: `_build_thinking_config` and `_cache_key_for_model` do not exist; corrected the class/`get_client` line numbers and the test file paths. Added the retirement list (four ids) from a live `models.list` diff, plus §7, §8 and §9, which the first draft omitted. |
| 2026-10-15 | jlara@trocglobal.com | Approved. FEAT-ID reserved as FEAT-688 (provisional FEAT-672 was taken upstream by `github-reviewer-local-repo-wiki`); Q0 closed. |
