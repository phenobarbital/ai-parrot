---
id: FEAT-672
title: Raise the google-genai floor and refresh GoogleModel for Gemini 4.x (Argon)
slug: gemini-upgrade
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-15
  summary_oneline: "Subir google-genai e incorporar los modelos Gemini 4.x (Argon) en GoogleModel, retirando los deprecated"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-client-google, ai-parrot-embeddings, ai-parrot-server, ai-parrot]
tags: [google-genai, model-catalog, gemini, llm-clients, deprecation]
research_state: sdd/state/FEAT-672/
created: 2026-10-15
updated: 2026-10-15
---

# FEAT-672 — Raise the google-genai floor and refresh GoogleModel for Gemini 4.x (Argon)

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-672/`](../state/FEAT-672/)
> **FEAT-ID is PROVISIONAL** — taken from `.id_ledger.json` (`next_feature_id: 672`)
> without reserving it. `/sdd-spec` allocates the real id via `reserve_ids.py`.

---

## 0. Origin

> gemini-upgrade -- con la llegada de Gemini 4.x Argon, hay que subir la version
> de google-genai e incorporar los nuevos modelos (y retirar los deprecated) de
> GoogleModel

**Initial signals** (extracted, not interpreted):
- Verbs: "subir la version", "incorporar", "retirar" → planned change, not a bug
- Named entities: `google-genai` (dependency), `GoogleModel` (symbol), "Gemini 4.x Argon"
- Components / labels: none (inline source)
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

The request reads as three line edits — bump a pin, add some enum members, delete
some others — but the research says otherwise. `GoogleModel`
(`packages/ai-parrot-client-google/src/parrot/clients/google/models.py`) is a bare
name→id map with no capability metadata, and **none of the client's behaviour is
driven by it**: `client.py` decides thinking mode, combined tools+schema and
computer-use support with hardcoded `startswith("gemini-3…")` prefix tests, so a
`gemini-4…` id added to the enum alone would be accepted and then silently routed
down the conservative two-phase path. The enum is also already carrying 19 invisible
aliases (53 names, 34 distinct values), and it is published verbatim over HTTP by
`handlers/google_generation.py`. The real shape of this work is therefore the same
three-part footprint the two previous refreshes used — **enum + prefix whitelist +
tests** — plus a dependency-floor realignment across two divergent pins. What is
missing is not analysis but data: the external query for the actual Argon ids and
the current SDK release could not run in this session.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-672/findings/`. No fabricated paths.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` | `GoogleModel` | 11-73 | the catalogue — 53 names, 34 distinct values | F001, F002 |
| 2 | `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` | `VertexAIModel` | 76-99 | Vertex subset, no aliases | F001 |
| 3 | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | `_default_combined_call_prefixes` | 144-158 | prefix whitelist for combined tools+schema | F004 |
| 4 | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | `_requires_thinking` | 270-283 | thinking-only gate, prefix-based | F004 |
| 5 | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | `_is_gemini3_model` | 230-239 | generation gate hardcoded to `gemini-3` | F004 |
| 6 | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | `_is_computer_use_model` | 374-391 | computer-use gate | F004 |
| 7 | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | `_default_model` / `_fallback_model` / `_lightweight_model` | 127-131 | defaults pinned to 3.x | F004, F010 |
| 8 | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | `_default_reformat_model` | 166-172 | reformat model, 3.5-flash | F004, F010 |
| 9 | `packages/ai-parrot-client-google/pyproject.toml` | `dependencies` | 27 | `google-genai>=2.23.0` | F003 |
| 10 | `packages/ai-parrot-embeddings/pyproject.toml` | `dependencies` | 55 | `google-genai>=2.18.1` (divergent) | F003 |
| 11 | `packages/ai-parrot/src/parrot/clients/factory.py` | `LLMFactory.list_models` | 224-253 | active/deprecated catalogue API | F005 |
| 12 | `packages/ai-parrot-client-openai/src/parrot/clients/openai/models.py` | `DEPRECATIONS` | 85-201 | in-repo precedent for retiring ids | F005 |
| 13 | `packages/ai-parrot-server/src/parrot/handlers/google_generation.py` | `list_models` | 42-44 | public HTTP surface enumerating the enum | F006 |
| 14 | `packages/ai-parrot/tests/test_google_models.py` | catalogue assertions | 7-39 | pins exact name→value pairs | F006 |
| 15 | `packages/ai-parrot/tests/clients/test_google_models.py` | computer-use assertions | 11-26 | pins computer-use members | F006 |
| 16 | `packages/ai-parrot/src/parrot/memory/compaction/budget.py` | `MODEL_WINDOWS` | 51 | bare `gemini-` prefix → 1M window | F009 |
| 17 | `packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py` | `_default_model` | 34 | second default, same 3.x id | F010 |

### 2.2 Constraints Discovered

- **The enum is not the routing table.** Every capability decision in `client.py` is
  a string-prefix test: `_is_gemini3_model` is `model.startswith("gemini-3")`,
  `_requires_thinking` enumerates `gemini-2.5-pro` / `gemini-3.7-pro` /
  `gemini-3.1-pro` / `gemini-3-pro`, and `_supports_combined_tools_and_schema`
  matches against an 8-entry prefix tuple. A `gemini-4…` id fails all of them
  **without erroring** and falls back to the legacy reformat round-trip.
  *Implication*: adding 4.x to the enum without touching the prefixes ships a
  working-but-degraded path, which is the hardest kind of regression to notice.
  *Evidence*: F004

- **19 of 53 enum names are silent aliases.** `GoogleModel` is a plain `Enum`, so
  duplicate values collapse onto the first member. Iteration yields 34 members,
  `GoogleModel(<value>)` always returns the canonical one, and `alias.name` reports
  the canonical name (`GEMINI_3_5_FLASH_COMPUTER_USE.name` → `"GEMINI_3_5_FLASH"`).
  *Implication*: a new 4.x name reusing an existing value disappears silently; and
  the alias block is the mechanism by which ids were "retired" until now.
  *Evidence*: F002

- **12 members are load-bearing by name — one of them an alias.** A sweep of the
  three live `src/` trees finds 12 `GoogleModel.<MEMBER>` references, including
  `GEMINI_3_FLASH_PREVIEW`, which is an alias of `gemini-3.5-flash`. Deleting any
  of them is an `AttributeError` at import time, not a graceful fallback.
  *Implication*: under the chosen pure-deletion policy (§5 U2) these 12 names are
  the hard floor — each one removed must have its call site edited in the same commit.
  *Evidence*: F010, F002

- **A deprecation seam exists and Google is the provider that does not use it.**
  `LLMFactory.list_models()` returns `{"active", "deprecated"}`, reading the second
  from an optional `client_class.deprecated_models`. Only `OpenAIClient` defines it.
  *Implication*: Google's `deprecated` list is `[]` today and stays `[]` under pure
  deletion; a retired id becomes an opaque `ValueError` rather than a diagnosable one.
  *Evidence*: F005

- **The enum is a public HTTP response.** `handlers/google_generation.py:42-44`
  returns `[model.value for model in GoogleModel]`.
  *Implication*: every addition and removal is a visible API change (currently 34 ids).
  *Evidence*: F006

- **Two divergent SDK floors, both `>=`.** `ai-parrot-client-google` pins `>=2.23.0`,
  `ai-parrot-embeddings` still `>=2.18.1`; core deliberately carries none (FEAT-523).
  Installed resolves to **2.24.0**. The workspace root records that
  `google-cloud-aiplatform>=1.153` is what `google-genai>=2.6` drags in.
  *Implication*: the bump is a floor raise in two files, and `google-cloud-aiplatform`
  is the coupling that decides how far it can move.
  *Evidence*: F003

- **The SDK surface is narrow.** `from google import genai` + `from google.genai import
  types` across 9 modules, `google.genai.errors` only in the reel error mapper.
  *Implication*: a minor-version floor raise has a small blast radius; the risk is in
  `types.*` shape changes, not in the client construction.
  *Evidence*: F003

- **A 4.x id inherits the 1M compaction window for free.** `MODEL_WINDOWS` has a single
  bare `"gemini-": 1_048_576` prefix entry.
  *Implication*: no edit needed if Argon's window is ≥1M; silently wrong if smaller.
  *Evidence*: F009

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched |
|--------|------|--------|---------|---------|
| `b4427bb66` | 2026-09-03 | Jesus | feat(models): add Gemini 3.8 Flash to GoogleModel and VertexAIModel enums | client.py +1, models +5, tests +6 |
| `f1dda8ffd` | 2026-08-17 | Jesus | new version of google-genai with support for 3.6 and 3.7 models | 2 pyprojects, client.py 91, catalogue 279, 2 test files |
| `70d6ea27e` | — | — | feat(computer-use-agent): TASK-1480 — GoogleModel computer-use entries | catalogue |
| `7f7f6f165` | — | — | feat(pep-420-llm-clients): TASK-2851 — satellite `ai-parrot-client-google` | relocation |

`f1dda8ffd` is this exact task performed once already: SDK floor + catalogue rewrite
+ prefix gates + tests, 6 files, 194 insertions / 213 deletions. `b4427bb66` is the
minimal single-model shape. Neither introduced a deprecation registry — the 279-line
rewrite deleted and remapped names in place, which is the precedent for the chosen
pure-deletion policy. *Evidence*: F007

---

## 3. Probable Scope

### What's New

- **Gemini 4.x (Argon) members in `GoogleModel`** — ids pending (§5 U1).
- **New prefix entries** in `_default_combined_call_prefixes`, and in
  `_requires_thinking` / `_is_gemini3_model` if the family is thinking-only
  or must be treated as "3.x-or-later" (§5 U3).

### What Changes

- **`models.py`::`GoogleModel`** — add the 4.x family; delete the deprecated members
  outright (operator decision, §5 U2). *Evidence*: F001, F002
- **`client.py`::`_default_combined_call_prefixes`** — extend so 4.x takes the
  single-call path instead of the reformat round-trip. *Evidence*: F004
- **`client.py`::`_is_gemini3_model` / `_requires_thinking`** — the generation gate
  name and its `gemini-3` prefix no longer describe reality once a 4.x family exists.
  *Evidence*: F004
- **`packages/ai-parrot-client-google/pyproject.toml:27`** — raise the floor.
  *Evidence*: F003
- **`packages/ai-parrot-embeddings/pyproject.toml:55`** — realign `>=2.18.1` to the
  same floor. *Evidence*: F003
- **`packages/ai-parrot/tests/test_google_models.py`, `tests/clients/test_google_models.py`**
  — add assertions for the new members, drop the ones for deleted members.
  *Evidence*: F006
- **Call sites of any deleted member** — each of the 12 names in F010 that is removed
  needs its reference edited in the same commit. *Evidence*: F010

### What's Untouched (Non-Goals)

- `VertexAIModel` — stays on 3.x this round (operator decision, §5 U5).
- `_default_model` / `_fallback_model` / `_lightweight_model` /
  `_default_reformat_model` — stay on 3.x (operator decision, §5 U4).
- No `GoogleGenAIClient.deprecated_models` registry (rejected in favour of pure
  deletion, §5 U2) — Google keeps reporting `deprecated: []`.
- No redesign of prefix gates into capability metadata on the enum.
- No relocation of the Google model tests into the satellite (FEAT-523 leftover).
- `parrot/clients/base.py` and the `LLMFactory` contract.
- The reel/media members (`VEO_*`, `LYRIA`, `IMAGEN_*`) — unrelated to this refresh.

### Patterns to Follow

- **The three-part footprint** from `b4427bb66`: enum member + prefix-whitelist entry
  + test assertion. Nothing else was needed to add a model. *Evidence*: F007
- **Floor raises, never ceilings** — all four existing pins are `>=`. *Evidence*: F003
- **Literal fallbacks in core** — `conf.py:446-454` deliberately holds the string
  `"gemini-flash-latest"` rather than importing the enum; keep core enum-free.
  *Evidence*: F006

### Integration Risks

- **Degraded-path regression**: 4.x in the enum but not in the prefixes → every call
  pays an extra reformat round-trip and sends no combined schema, with no error.
  *Mitigation*: make a prefix-coverage assertion part of the acceptance criteria —
  for each new member, `_supports_combined_tools_and_schema(m.value, prefixes)` must
  be explicitly True or explicitly decided False. *Evidence*: F004
- **Import-time breakage on deletion**: removing one of the 12 named members
  (F010) raises `AttributeError` at import, including the alias
  `GEMINI_3_FLASH_PREVIEW`. *Mitigation*: diff the deletion list against F010 first.
  *Evidence*: F010
- **Silent alias collapse**: a 4.x name assigned an already-present value becomes an
  invisible alias. *Mitigation*: assert `len(GoogleModel.__members__) ==
  len({m.value for m in GoogleModel}) + <expected alias count>`, or assert each new
  member's `.name` round-trips. *Evidence*: F002
- **Public catalogue change**: `/models` output shifts. *Mitigation*: note it in the
  spec as an intended API change. *Evidence*: F006
- **SDK floor vs `google-cloud-aiplatform`**: raising past a certain point drags a
  newer aiplatform. *Mitigation*: resolve with `uv` before committing the pin.
  *Evidence*: F003

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The catalogue is `models.py` in `ai-parrot-client-google` | F001 | high | direct read of the file |
| C2 | 19 of 53 names are enum aliases; 34 distinct values | F002 | high | AST count over the source |
| C3 | Capability gates are prefix-based and 3.x-hardcoded | F004 | high | direct read of all four helpers |
| C4 | A `deprecated_models` seam exists; Google does not use it | F005 | high | read of `factory.py` + workspace-wide grep |
| C5 | Floors are `>=2.23.0` / `>=2.18.1`; installed 2.24.0 | F003 | high | grep of pyprojects + `uv pip show` |
| C6 | The enum is published over HTTP and pinned by 3 test modules | F006 | high | direct read of handler and tests |
| C7 | The precedent footprint is enum + whitelist + tests | F007 | high | two commits with diffstats |
| C8 | 12 members are referenced by name; one is an alias | F010 | high | name-level grep across three `src/` trees |
| C9 | A `gemini-4` id inherits the 1M compaction window | F009 | medium | single prefix entry read; depends on Argon's real window |
| C10 | **Which ids to ADD is unknown** | F008 | low | external research unavailable this session |
| C11 | **Which ids to RETIRE is unknown** | F008 | low | same |
| C12 | **The target `google-genai` version is unknown** | F008 | low | same |

Distribution: **8** high, **1** medium, **3** low.

The three `low` claims are exactly the ones the title of this feature promises, so
overall confidence is capped at **medium** despite a high-confidence localization:
we know precisely *where* and *how*, and not yet *what*.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U2 — How should deprecated ids be retired?** — *Resolved*: **pure deletion**.
  Members come out of the enum with no `deprecated_models` registry. Consistent with
  the `f1dda8ffd` precedent and with the project's no-external-consumers stance.
  *Consequences accepted*: `/models` stops listing them, a retired id raises an opaque
  `ValueError`, Google keeps reporting `deprecated: []`, and any of the 12 names in
  F010 that is deleted must have its call site edited in the same commit.
  *Resolves claims*: C11 (policy only — the list itself is still U1)

- [x] **U4 — Do the client defaults move to 4.x?** — *Resolved*: **no, stay on 3.x**.
  `_default_model`, `_fallback_model`, `_lightweight_model` and
  `_default_reformat_model` are untouched; 4.x is added to the catalogue as opt-in.
  *Resolves claims*: C3 (scope bound)

- [x] **U5 — Does `VertexAIModel` get the 4.x family?** — *Resolved*: **no, only
  `GoogleModel`** this round. Vertex stays on 3.x pending availability confirmation.
  *Resolves claims*: C9 (scope bound)

### Unresolved (defer to spec)

- [ ] **U1 — What are the exact Gemini 4.x (Argon) model ids, which currently-listed
  ids are deprecated, and what `google-genai` version is the new floor?**
  *Owner*: operator · *Blocks claims*: C10, C11, C12
  *Why it cannot be answered here*: `WebSearch` and `WebFetch` both failed in this
  session (`claude-haiku-4-5@20251001` unavailable), and the catalogue already
  contains `gemini-3.8-flash` and `gemini-deep-research-preview-04-2026` — i.e. it
  is at or beyond the assistant's knowledge cutoff, so training data is not a
  substitute. *Plausible sources*: Google's model docs page · `genai.list_models()`
  against a live key · the SDK changelog.

- [ ] **U3 — Does the 4.x family go into `_default_combined_call_prefixes`, and is any
  4.x Pro thinking-only?** *Owner*: operator / spec · *Blocks claims*: C3
  *Plausible answers*: a) mirror 3.x — Pro is thinking-only, all of them whitelisted ·
  b) whitelist only after upstream evaluation, as the `_default_combined_call_prefixes`
  docstring describes for 3.x · c) Argon changes the contract and needs a new gate.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-672`** — *Rationale*: localization is high-confidence (C1–C8), the
footprint is a known shape executed twice before (C7), and three of the five design
questions are already resolved. What remains is one operator data drop (U1) and one
capability decision (U3), both of which belong in a spec rather than another
exploration round. There is no architectural fork to brainstorm.

**Do not start the spec before U1 is answered** — the task is defined by the model
list, and a spec written without it would invent ids.

### Alternatives

- **`/sdd-task FEAT-672`** — only if U1 and U3 arrive together and the change really
  is "add N members + N prefixes + N assertions". The `b4427bb66` precedent shows
  that shape is a 3-file commit; the `f1dda8ffd` precedent shows it usually is not.
- **`/sdd-brainstorm FEAT-672`** — only if U3 turns out to be option (c) and Argon
  changes the capability contract, which would make the prefix-gate design itself
  the subject.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-672/state.json` |
| Source (raw) | `sdd/state/FEAT-672/source.md` |
| Research plan | `sdd/state/FEAT-672/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-672/findings/F001-*.md` … `F010-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-672/synthesis.json` |

**Budget consumed**:
- Files read: 9 / 40
- Grep calls: 15 / 25
- Git calls: 3 / 10
- Truncated: **no**
- Failed queries: **Q014** (external web research — host tooling unavailable, see F008)

**Mode determination**: `auto` → resolved to `enrichment` (planned change; verbs
"subir" / "incorporar" / "retirar", no negation or failure report in the source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jlara@trocglobal.com |
