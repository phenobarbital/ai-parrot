# FEAT-590 spike — decision record

- Date / operator: 2026-09-23 / Claude (sdd-worker orchestrator, no coder seat — per task scope)
- cactus-needle version: **3.0.4** (engine generation 3, native `libneedle.so`, base/untuned weights — no
  fine-tune supplied) · GGUF model: **Qwen/Qwen2.5-0.5B-Instruct-GGUF**, `qwen2.5-0.5b-instruct-q4_k_m.gguf`
  (≈491 MB) · llama-server build: **`ggml-org/llama.cpp` release `b11115`** (`llama-b11115-bin-ubuntu-x64`,
  CPU-only, commit `d5f66492e`, version string `0.4.1-dev`)

Both backends were run on CPU only (no functioning GPU in the spike environment — `nvidia-smi` reports no
driver). 12 CPU cores / 46 GiB RAM available; the GGUF model file and llama-server binary total ≈510 MB, well
inside disk/RAM budget.

## Cases

`sdd/state/FEAT-590/spike/cases.jsonl` — **57 cases**, drawn from the **real, live** `AbstractTool.get_schema()`
output of three ai-parrot toolkits actually instantiated in-process (not hand-written schemas):

- `WorkingMemoryToolkit` (`parrot.tools.working_memory.tool`) — 13 tools
- `QuerysourceToolkit` (`parrot_tools.querysource.toolkit`) — 7 tools
- `RSSFeedReaderToolkit` (`parrot_tools.rss.toolkit`) — 4 tools

24 distinct real tools total, spanning working memory, DB/query (QuerySource slugs/pipelines) and HTTP-backed
RSS fetching. **`WebBrowsingToolkit` (web scraping) could not be included**: importing it through the worktree's
PYTHONPATH (no compiled extension available outside the shared `.venv`'s in-place build) raises
`ModuleNotFoundError: No module named 'parrot.utils.types'` (a Cython/C extension not rebuilt for this
worktree). This is a spike-environment limitation, not evidence about the backends; a rerun from an environment
with the compiled extension available should add scraping-toolkit cases before this record is treated as final
for that category.

Each case presents a small pool of 2–4 tools (mirroring the `delegate.max_tools` ceiling) plus one instruction.
**45 targeted cases** (one correct call each, hand-mapped to real argument shapes) + **12 abstention cases**
(instruction has no match in the presented pool, `expected: null`) = **57 cases**, clearing the ≥ 50 / ≥ 10
floors.

## Metrics (per backend)

| Backend | Cases | Exact match | Abstention P / R | p50 latency | p95 latency | Max usable input (observed) |
|---|---|---|---|---|---|---|
| **llama.cpp** (Qwen2.5-0.5B-Instruct, Q4_K_M, CPU, `json_schema` oneOf grammar) | 57 | **57.9%** | 58.3% / 58.3% | 770 ms | 1501 ms | ≥ 2535 chars still correct (confidence dropped 0.65→0.24) |
| **Needle** (base weights, `asyncio.to_thread`) | 57 | **47.4%** | 73.3% / 91.7% | 1259 ms | 2304 ms | correct up to ~1000 chars in ad-hoc checks; **wrong** on a 2535-char case |
| **Needle** (base weights, `ProcessPoolExecutor`) | 0 (SKIPPED) | — | — | — | — | see "Needle executor" below |

(1 of 57 llama.cpp calls errored on the first schema-composition attempt with an unrelated bug, fixed before
this final run — see "Implementation notes for M6" below; the *final* run above has 1/57 residual errors from
output truncation at `n_predict=256` on the one case with the largest `arguments` payload, not a backend
accuracy failure.)

## Needle executor: **thread**, not process — evidence

`asyncio.to_thread` ran all 57 cases reliably (0.22 s–4.59 s per case after a one-time ≈0.9–3.7 s cold
warm-up of the native library + base weights in-process). **`ProcessPoolExecutor` (default `fork` start
method) hung indefinitely** in this sandboxed spike environment: isolated tests (5 cases, 60 s hard timeout,
*zero* output, no exception — not even the first case returned) reproduced this twice, both with and without a
prior native-library load in the parent process, so it is not simply a fork-after-native-load hazard; something
about forking a new process from inside this specific sandbox (Bubblewrap-restricted namespaces per
`.claude/rules/worktree-management.md`) breaks the native library's own process bring-up. **This must be
re-verified in an unsandboxed / production host before trusting `ProcessPoolExecutor` there** — the hang here
may be an artifact of this dev sandbox, not of Needle or `ProcessPoolExecutor` in general. Given the ambiguity,
M7 should default to `executor="thread"` (already the interface skeleton's non-`"process"` option) and file a
follow-up to re-test `"process"` outside a Bubblewrap-style sandbox before ever defaulting to it.

## Confidence: Needle calibration · llama.cpp logprobs usable?

- **Needle**: base (untuned) weights DO report a calibrated confidence (`_calibrated=True` when untuned, per
  `needle/__init__.py`), e.g. 0.55–1.0 on the smoke cases. It is **not well separated from correctness** in this
  sample — one clearly-wrong 2-tool case ("tell me a joke about cats" → `get_weather(location='cats')") still
  scored `confidence=1.0`. A `min_confidence` gate on base weights would therefore *not* reliably reject wrong
  calls; this reinforces spec §8 Q-S8's resolution (reject unscored proposals when a threshold IS set) but adds
  a **new** finding: even *scored* base-Needle proposals cannot be trusted at face value pending fine-tuning.
- **llama.cpp logprobs**: **usable (yes)** — `/v1/chat/completions` with `logprobs: true, top_logprobs: 1`
  reliably returns per-token logprobs; the harness's simple mean-logprob → `exp()` heuristic produced
  0.50–0.70 on short correct cases (weak separation from the one wrong case at 0.50) but dropped sharply
  (0.24) on the 2535-char case that was nonetheless answered correctly — i.e. usable as a *rough* signal, but
  the naive averaging heuristic in this spike is not proven well-calibrated either. M6 should not over-promise:
  record logprob-derived confidence, but do not gate on it without further calibration work.

## Decision (spec §2 rules)

**Both backends measured below the 90% exact-match bar** (llama.cpp 57.9%, Needle 47.4%) →
**Option B: fine-tune first, no confidence gate.**

Per spec §2, this is *not* the DROP branch — DROP only fires if accuracy is *still* below 90% *after*
fine-tuning, which is explicitly out of this task's scope (`Non-Goals`: "A production fine-tuning pipeline...
training is deferred until after the spike"). M1–M5/M8 are **not** reverted or parked.

- **Fine-tuning target (recommended): Needle.** `cactus-needle` ships first-class fine-tuning support
  (`needle.FineTuneWorker`, weights-path-driven dispatch already visible in `Needle.__init__`) and Needle
  already leads on abstention recall (91.7% vs. 58.3%) — the safety-critical half of the accept gate — despite
  being both untuned and out-of-distribution for these toolkits. llama.cpp fine-tuning would need a separate
  LoRA/GGUF training pipeline with no equivalent first-class support in this stack.
- **llama.cpp ships as the immediately-usable secondary/fallback backend.** At 57.9% exact-match with real,
  non-fabricated logprob-derived confidence, it is not production-primary on its own, but it is a legitimate
  `retry_backend` hop in the delegate chain and a fine-tuning-free baseline for tasks that can tolerate a lower
  hit rate (paired with `accept_when` / schema validation to catch bad calls before dispatch — the accept gate,
  not the delegate, is the real safety net regardless of backend).
- **`min_confidence` MUST stay unset** on any delegate node targeting either backend until a fine-tuned Needle
  checkpoint is independently measured ≥ 90% exact-match (a new, separately-tracked follow-up; out of FEAT-590
  scope per the Non-Goals). This is exactly the guidance the spec's Known Risks section already gives for
  option B backends (§7 "Fine-tuned confidence is `None`").

## Consequences for TASK-3632 / TASK-3633 / TASK-3637 (and M1–M5/M8)

- **TASK-3632 (LlamaCppDelegate)**: proceed as scoped. Use `use_logprobs=True` by default (usable per above);
  do not gate `accept_when`/`min_confidence` on it without a calibration follow-up. Reuse this spike's `$defs`
  **hoisting + `$ref` rewrite** for the `oneOf` json_schema construction (see "Implementation notes for M6"
  below) — the naive nesting in the M6 skeleton will otherwise 400 on every tool with a `$ref`'d field (any
  Pydantic enum/nested-model parameter, e.g. `EntryType` here). Default `max_input_chars=4000` holds (2535
  chars still answered correctly in this spike).
- **TASK-3633 (NeedleDelegate)**: proceed as scoped, with `executor="thread"` as the *implemented* default
  (not `"process"` — see the executor finding above), and a lowered default `max_input_chars` (spec skeleton
  already defaults to 1000; this spike's one long-input probe (2535 chars) got the WRONG answer, consistent
  with keeping the 1000-char default rather than raising it).
- **TASK-3637 (`ai-parrot[needle]` extra)**: proceed. Pin `cactus-needle==3.0.4` (the version tested here).
  Base install has minimal hard deps (`huggingface_hub` only — no `jax`/`flax`, those are `train`/`gpu`/`metal`
  extras); the native `.so` and base weights are fetched lazily into `~/.cache/cactus-needle` on first use (do
  **not** vendor them; keep this lazy, `HOME`-relative fetch as-is).
- **M1–M5/M8**: unaffected. No revert, no park. The protocol/plan-language/validator/node/toolkit-wiring work is
  backend-independent by design (per spec §2), and the M0 gate result feeding into them is: implement both
  backends, ship neither with an active confidence gate yet.

## Implementation notes for M6 (schema composition bug found + fixed in the spike harness)

Nesting a tool's own `AbstractTool.get_schema()["parameters"]` (which carries its OWN top-level `$defs`, e.g.
`wm_search_stored`'s `entry_type: Optional[EntryType]`) several levels deep under
`oneOf[i].properties.arguments` breaks every `$ref: "#/$defs/X"` inside it, because JSON Schema resolves that
string against the **document root**, not the local subschema — and after nesting, the matching `$defs` no
longer live at the document root. Confirmed against llama-server b11115 with the literal error:
`cannot resolve $ref #/$defs/EntryType, $defs not found`. Fix applied in
`scripts/spikes/tool_call_delegate_spike.py::_namespace_refs`: hoist every tool's `$defs` into ONE document-root
`$defs` block with per-tool-namespaced keys (`f"{tool_name}__{def_name}"`), rewriting every `$ref` string to
match. **M6's `LlamaCppDelegate.propose_call()` must do the same** — any tool whose schema has a `$ref` (any
enum or nested Pydantic model argument) will otherwise 400 on every single call, not just some.

## Implementation notes for M7 (Needle API divergence from the proposal)

The proposal's assumed shape (`needle.Needle(tools=<json schemas>, system=, weights=)`) is **not quite right**:
`tools` must be a list of **Python callables**, each carrying a `_needle_tool` attribute (a dict shaped exactly
like `{"name","description","parameters"}` — the same shape as our `ToolSpec`). The `@needle.tool` decorator
derives that dict from the function's own signature/docstring via `needle.build_schema()`, but a plain function
with `_needle_tool` set directly (bypassing derivation) works identically — this is the path M7 must use, since
the real tool schema comes from `AbstractTool.get_schema()`, not from introspecting a Python signature. Verified:
`needle.Needle.__init__(self, tools=None, system=None, weights=None, tool_index_path=None, buffer_size=65536,
auto_date=True, generation=None)`; `.complete(text, max_new_tokens=512) -> dict` with keys `type, success, error,
error_code, reason, function_calls, suppressed_calls, reasoning, confidence, prefill_tps, decode_tps,
peak_ram_mb, validation`. `function_calls` (a list, possibly empty for abstention) replaces the proposal's
assumed single `name`/`arguments` pair — M7's `propose_call()` must take `function_calls[0]` when non-empty and
map an empty list to `ToolCallProposal(name=None, ...)`.
