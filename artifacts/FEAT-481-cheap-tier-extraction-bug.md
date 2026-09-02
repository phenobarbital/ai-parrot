# FEAT-481 — Meeting-page extraction fails: cheap-tier LLM returns unparseable JSON

**Owner for the fix:** Jesus (reproduce across models + apply the proper fix)
**Reported by:** Arturo + Claude (local testing against a real Obsidian vault)
**Date:** 2026-09-02
**Branch:** `feat-481-fireflies-wiki-knowledgebase-agent`
**Status:** root cause identified; a FEAT-481-scoped interim guard is in place (see §6). **The real fix is still open.**

---

## TL;DR

`run_meeting_page` (spec Module 8) extracts a `MeetingPageExtraction` via
`cheap_client.invoke(prompt, output_type=MeetingPageExtraction)`. On the
**cheap/flash tier**, the model **degenerates into a repetition loop** inside the
unconstrained free-text `purpose` field, blows the output-token budget, and returns
**truncated, invalid JSON**. `AbstractClient._parse_structured_output` cannot parse
it and returns the **raw string**, which the node then dereferences as if it were the
typed model → crash.

- **Without the interim guard:** `AttributeError: 'str' object has no attribute 'executive_summary'` (`meeting_page.py:185`).
- **With the interim guard (committed, Google-only):** a clear
  `InvokeError: … returned unparseable text even after reformat recovery.`
- **Reproduced deterministically** (temperature=0) on **every Gemini model tried** —
  `google:gemini-2.5-flash`, `google:gemini-2.5-flash-lite`, `google:gemini-3.5-flash-lite`,
  **and `google:gemini-2.5-pro`** — all producing the *same* ~25.3 KB repetition/truncation
  (parse fails at "line 3 column 24867", i.e. the `purpose` field). The reformat-recovery
  model (`gemini-3.1-flash-lite`) fails the same way.
  → **This is NOT a cheap-tier problem — the strong `gemini-2.5-pro` fails too. It is a
  SCHEMA problem** (the doc name is kept for continuity, but "cheap-tier" is a misnomer).
  Only the *small* Classification schema parses reliably; the large `MeetingPageExtraction`
  schema degenerates on every Gemini tier.

---

## Environment / repro config

- Python 3.12, uvloop 0.21.0.
- Vault: a real contract-structured Obsidian vault (`WIKI_KB_VAULT_PATH`).
- Meeting: a single real Fireflies meeting (`fireflies:01M0XNWERMQ3W57KMTVB75S227`,
  a "FieldSync / Verizon launch" project sync).
- Tiers tested:
  - Classification (Module 7, strong tier): `gemini-2.5-pro` ✅ and `gemini-3.8-flash` ✅ (small schema, parses fine).
  - Extraction (Module 8, cheap tier): `gemini-2.5-flash` ❌, `gemini-2.5-flash-lite` ❌, `gemini-3.5-flash-lite` ❌ (all identical ~25.3 KB repetition/truncation).
- Repro harness: `scratchpad/wiki_kb_run.py` (runs an intent) and
  `scratchpad/wiki_kb_capture.py` (tees the parse step to capture raw model output).

---

## Root cause — model degeneration → truncated JSON → raw string

`cheap_client.invoke(..., output_type=MeetingPageExtraction)` (meeting_page.py:137-140):

```python
result = await cheap_client.invoke(
    prompt, output_type=MeetingPageExtraction, system_prompt=_SYSTEM_PROMPT, temperature=0.0
)
extraction: MeetingPageExtraction = result.output   # <-- assumed typed; is a str
```

The flash-tier model returns **25,299 characters** that begin as valid JSON but
**loop on one sentence 165×** in `purpose`, then get **cut off mid-word** (no closing
quote/brace) when the output-token limit is hit. `_parse_structured_output`
(`clients/base.py:2269`) fails to parse the truncated JSON and **returns the raw
string** as its result. Because it is not the model, every downstream typed access
breaks (first at `meeting_page.py:185` `extraction.executive_summary`, and in
`runner.py:478/486/487/489` via `_extraction_from_meeting`).

**Verified facts about the raw response** (identical across the three cheap models,
temperature=0):
- length = 25,299 chars ≈ **4,081 tokens** (tiktoken `cl100k` proxy; ~6.2 chars/token
  because the repetition tokenizes efficiently)
- ends with `"… The meeting also served to prioritize"` — **truncated mid-sentence, no `}`**
- the sentence *"The meeting also served to prioritize feature fixes and establish a roadmap
  for ongoing UX enhancements and system integration testing with Workday."* repeats **165×**.

### Truncation mechanism — it's `max_output_tokens`, NOT the context window

- `invoke()` defaults to **`max_tokens: int = 4096`** (`clients/base.py:1662`); the Google
  client maps this to Gemini's `max_output_tokens=4096` (`clients/google/client.py`, single-
  call `gen_config_kwargs`).
- **`nodes/meeting_page.py:137-138` does NOT override `max_tokens`**, so the extraction runs
  with the default 4096.
- The ~4,081-token output sits right at that 4,096 ceiling → the (already degenerate,
  repetitive) JSON is cut off mid-token → invalid JSON → `_parse_structured_output` returns
  the raw string. The context window (~1M for flash) is **not** the constraint.
- **Corollary:** simply raising `max_output_tokens` is not a fix — a repetition loop just
  rambles longer (still no valid closing JSON, just a bigger blob). The cap is where the
  truncation lands; the schema (unbounded free-text, esp. `content`) and the degeneration
  are the causes.

### Raw response sample (gemini-2.5-flash-lite, abbreviated)

```json
{
  "executive_summary": "The team is actively managing FieldSync development, focusing on
Epson field testing, UX improvements, and preparation for the October 1 Verizon launch.
Key activities include resolving form builder access issues, implementing phased UX
updates, and coordinating training materials. ...",
  "purpose": "To align on FieldSync project updates, address testing blockers, coordinate
training for the upcoming Verizon launch, and ensure clear communication and ownership
across the team. The meeting also served to prioritize feature fixes and establish a
roadmap for ongoing UX enhancements and system integration testing with Workday. The
meeting also served to prioritize feature fixes and establish a roadmap for ongoing UX
enhancements and system integration testing with Workday. The meeting also served to
prioritize feature fixes and establish a roadmap for ongoing UX enhancements and system
integration testing with Workday.
        ⟪ … the SAME sentence repeats 165× … ⟫
integration testing with Workday. The meeting also served to prioritize
```
⟶ **stream ends here** — truncated mid-sentence: no closing quote, no closing brace ⟶ **invalid JSON**.

Full raw captures are saved (uncommitted) at:
- `scratchpad/capture_gemini25-pro-flash.txt` (strong=2.5-pro, cheap=2.5-flash)
- `scratchpad/capture_userenv.txt` (strong=3.8-flash, cheap=2.5-flash-lite)
- `scratchpad/flashlite_raw.txt` (just the raw 25 KB extraction response)

---

## The schema that provokes it — `MeetingPageExtraction`

`MeetingPageExtraction(MeetingExtraction)` (`nodes/meeting_page.py:44`,
`models.py:243`) mixes **unconstrained free-text `str`** with lists:

```python
class MeetingExtraction(BaseModel):
    decisions: list[str]; requirements: list[str]; action_items: list[ActionItem]
    risks: list[str]; open_questions: list[str]; potential_contradictions: list[str]
    # (+ people/products/concepts, etc.)

class MeetingPageExtraction(MeetingExtraction):
    executive_summary: str   # unbounded free text  ← degeneration happens here / in `purpose`
    purpose: str             # unbounded free text
    filename: str
    content: str             # unbounded free text (a whole rendered page!)
    vault_path: str
```

The free-text fields have **no length/`max_length` guidance** and one (`content`) asks the
model to emit an entire rendered page. That combination (large schema + unbounded prose)
is what pushes a flash-tier model into repetition + truncation.

---

## Where the string leaks (code map)

| Layer | File:line | Behaviour |
|---|---|---|
| Parse | `clients/base.py:2269` `_parse_structured_output` | Returns the **raw str** when JSON parse fails (recovery is the caller's job). |
| Google `invoke()` | `clients/google/client.py:5576-…` | **Interim guard added** (this branch): on a raw-str parse, calls `_reformat_to_structured`; if still a str, raises `InvokeError`. Previously returned the str. |
| Claude `invoke()` | `clients/claude.py:1936-1945` | **Still leaks** — `output = _parse_structured_output(...)` → `_build_invoke_result(output, …)` with no str recovery. |
| OpenAI `invoke()` | `clients/openai_base.py:1129-1134` | **Still leaks** — same pattern as Claude. |
| Shared result | `clients/base.py:1863` `_build_invoke_result` | Wraps `output` as-is; does not enforce that a structured request yields the model. |
| Consumer | `nodes/meeting_page.py:140,185` (+ `runner.py:478/486/487/489`) | Assumes `result.output` is the typed model. **Every `wiki_ingest` node does this** (classify, entities, daily, concepts, project_reconcile, indexes, query). |

---

## Interim guard applied on this branch (FEAT-481-scoped, Google-only)

Commit `45ad4ba17` (`fix(clients/google): invoke() recovers structured-output str via reformat`)
makes `GoogleGenAIClient.invoke()` mirror the recovery the streaming/tool path already had:
on a raw-string parse it reformats, and if that still fails it **raises `InvokeError`
instead of leaking the string**. Tests: `packages/ai-parrot/tests/test_google_invoke_recovery.py`.

**Why this is not the real fix:** recovery cannot make a model satisfy a schema it
structurally can't. Here the reformat model (`gemini-3.1-flash-lite`) degenerates the
same way, so the guard just converts silent corruption (`AttributeError`) into a clear,
attributable failure (`InvokeError`). Extraction still does not succeed on the flash tier.
Per the team decision, the broader model-agnostic change (a shared guard in
`_build_invoke_result`, and/or reformat recovery for Claude/OpenAI) was **left out of
scope** — it's a client-layer decision for Jesus.

---

## For Jesus — reproduce and choose a proper fix

### Cross-model probe — `artifacts/feat481_extraction_model_probe.py`

A standalone, provider-agnostic probe (no Fireflies / no vault) that runs the **real**
`MeetingPageExtraction` call (same schema, `_SYSTEM_PROMPT`, `_build_prompt`) against a
list of models and prints a verdict per model:

```
source .venv/bin/activate
python artifacts/feat481_extraction_model_probe.py \
    --models google:gemini-2.5-flash,google:gemini-2.5-pro,anthropic:claude-sonnet-4-5,openai:gpt-4.1-mini \
    --meeting-dir /path/to/Raw/Processed/.../<fireflies_id>   # a real bundle: summary.md [+ transcript.md]
    # omit --meeting-dir to use a built-in short synthetic meeting
    # --transcript to include the transcript; --max-tokens N to test the output cap
```

Verdicts: `OK` (parsed the model) · `STR-LEAK` (raw str returned — provider without the
guard) · `INVOKE-ERROR` (invoke raised, e.g. Google's guard after reformat also failed) ·
`ERROR` (usually missing credentials / unknown model). Each provider needs its own key
(`GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`).

**Observed results (this repo, temperature=0):**

| Meeting | Model | Verdict | Note |
|---|---|---|---|
| built-in synthetic (358 chars) | `gemini-2.5-flash` | ✅ OK | 338 output tokens — short input, no degeneration |
| built-in synthetic (358 chars) | `gemini-2.5-pro` | ✅ OK | 338 output tokens |
| **real** (`01M0…227`, summary 14.9 KB) | `gemini-2.5-flash` | ❌ INVOKE-ERROR | ~25.3 KB repetition → truncated JSON |
| **real** (`01M0…227`, summary 14.9 KB) | `gemini-2.5-flash-lite` | ❌ INVOKE-ERROR | same |
| **real** (`01M0…227`, summary 14.9 KB) | **`gemini-2.5-pro`** | ❌ **INVOKE-ERROR** | **strong tier fails too** — schema-level, not tier-level |

→ Jesus: run the same probe with `anthropic:…` / `openai:…` models to see whether
non-Gemini providers escape the degeneration (their `invoke()` still lacks the recovery,
so a non-Gemini failure would show as `STR-LEAK` rather than `INVOKE-ERROR`).

### Deeper capture — `scratchpad/wiki_kb_capture.py`
Tees `AbstractClient._parse_structured_output` and runs a real
`ingest(limit=1, force_refetch=True)` end-to-end. Point the tiers at any model via
`env/.env` (`WIKI_KB_LLM_STRONG` / `WIKI_KB_LLM_CHEAP`, always `provider:model`). The
capture file records, per call: client, model, `output_type`, whether the parse
`returned_str`, and the full raw response.

**Prerequisites to run outside the parrot server** (both required, or ingest fails early):
1. `uvloop.install()` **before** `asyncio.run` (parrot swaps in uvloop's loop policy; a
   loop created first makes the stdio Fireflies MCP subprocess spawn raise
   `NotImplementedError` from `get_child_watcher`).
2. Open the tier clients: `async with agent.strong_client, agent.cheap_client:` —
   `configure()` builds them but does not enter their async context, and the nodes call
   `.invoke()`/`.ask()` (no auto-enter), so you'd otherwise get
   *"GoogleGenAIClient not initialised. Use async context manager."*

### Open questions to answer while reproducing
- **Every Gemini tier tried fails** on `MeetingPageExtraction` (flash-lite … **pro**).
  Does **any** non-Gemini model (`claude-*`, `gpt-*`) satisfy the schema unchanged? None
  observed succeeding yet — only the small Classification schema parses reliably.
- Do **Claude/OpenAI** leak the raw string (their `invoke()` still lacks recovery) or do
  they degrade differently? (Probe shows `STR-LEAK` vs `INVOKE-ERROR` accordingly.)

### Candidate proper fixes (not mutually exclusive)
1. **Constrain the schema** — the strongest lever. Add `max_length`/description caps to
   `executive_summary`/`purpose`, and reconsider `content` (asking the extractor to emit a
   full rendered page in the same structured call is what triggers the runaway). Rendering
   the page from typed fields, rather than extracting a `content` blob, likely removes the
   trigger entirely.
2. **Node robustness** — in `run_meeting_page`, validate `result.output` is a
   `MeetingPageExtraction`; on failure, route to a review item / retry, not an opaque crash.
3. **Client robustness (model-agnostic)** — a shared guard in `_build_invoke_result`
   (raise if a structured request yields a str) + reformat recovery for Claude/OpenAI, so
   no provider silently leaks a string. (Deferred here by team decision.)
4. **Generation controls** — raise `max_tokens` for this call and/or add
   frequency/repetition penalties or a stop condition so a repetition loop is cut before
   it truncates the JSON.
5. **Model tiering** — if only a stronger model reliably satisfies the schema, make the
   meeting-page extraction use the strong tier (or a dedicated tier) rather than cheap.

---

## Secondary issue (non-fatal) — derived graph plane "Tree does not exist"

During the post-ingest derived-plane rebuild (`graph.rebuild_graph_index` →
`LLMWikiToolkit.ingest_obsidian_vault("fireflies_wiki_kb", …)`), every file logs
`Failed to sync <path>: "Tree 'fireflies_wiki_kb' does not exist"`. It is non-fatal by
design (a derived-plane failure never blocks ingest), but it means the `query()`
retrieval plane isn't populated — the `fireflies_wiki_kb` graph namespace is never
created before the loader syncs into it. Likely a first-run bootstrap/ordering gap.

---

## Vault state note

The test vault was `git init`-ed for reversible testing; partial artifacts from failed
runs (`.wiki_kb/`, `Raw/` bundle, control-page edits) are parked in the vault's
`git stash` entries. No successful compile wrote content pages.
