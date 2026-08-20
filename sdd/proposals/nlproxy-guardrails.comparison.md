# Research: NLProxy (intellideep/nlproxy) vs the AI-Parrot Guardrails Stack

**Date**: 2026-08-20
**Author**: Jesús Lara (research conducted with Claude Code)
**Subject**: https://github.com/intellideep/nlproxy — BSL 1.1, ~14.9k LOC Python
**Question**: what, if anything, do we adopt from an offline-first LLM
proxy that does injection firewalling, entity masking, semantic
compression, and NLI response verification — and how do we run
ONNX-backed guardrails without wrecking agent latency?

> Sibling document: `sdd/proposals/pii-detection-redaction.comparison.md`
> (OpenAI Guardrails / Presidio vs FEAT-324). Several conclusions there
> apply verbatim here and are cross-referenced rather than repeated.

---

## 0. Verdict up front

| NLProxy idea | Verdict | Where it lands |
|---|---|---|
| ONNX local models + a `ModelManager` lifecycle (verify → download once → run offline) | **ADOPT** (fp32; int8 **failed**, see §3b) | New shared `parrot.security.models` loader; retrofit `PromptInjectionGuardrail` |
| NLI contradiction detection (answer vs. context/evidence) | **ADAPT** | Semantic tier on top of FEAT-398's deterministic `GroundednessGuardrail`, gated + budgeted |
| Semantic (embedding) injection detection against an attack corpus | **ADAPT** | Second tier of `PromptInjectionGuardrail`, reusing our own embeddings stack |
| FORBID/MANDATE constraint extraction + response correction | **ADAPT** (most original idea in the repo) | New OUTPUT guardrail; no equivalent exists in AI-Parrot |
| Entity masking via **spaCy NER + regex** | **REJECT** | Same architecture family we already benchmarked and rejected for hot seams (FEAT-324 §2–4) |
| Clustering-based (Ward/KMeans) prompt compression | **REJECT** | Lossy, embedding-cost-dominated; FEAT-380 already solves our actual problem (tool results) structurally and losslessly |
| Proxy/gateway deployment topology | **REJECT** | Guardrails belong at the agent seams (tool-call, tool-output, output-stream), which a gateway cannot see |
| Semantic response cache (RedisVL) | **NOTE** | We have no equivalent; out of scope here, worth its own brainstorm |
| Synchronous pipeline inside an async server | **REJECT (anti-pattern)** | See §2.2 — it is the single biggest engineering flaw in the project |

Net: NLProxy is **not** a better guardrails engine than ours. It is a
useful *catalogue of guardrail ideas* plus one genuinely instructive
demonstration of how to package offline models — and one instructive
demonstration of how **not** to run them inside an async service.

---

## 1. What NLProxy actually is (code-level)

A FastAPI gateway exposing an OpenAI-compatible `/v1/chat/completions`
that runs a fixed 6-stage pipeline around the upstream LLM call:

```
Firewall → Shield(mask) → Compress → SafetyCheck → LLM → Corrector → Verifier
```

Module map (LOC from the cloned repo):

| Module | LOC | What it does |
|---|---|---|
| `firewall/firewall.py` | 619 | Regex rule engine + optional embedding-similarity match against a hardcoded 7-prompt attack corpus (`utils/constants.py`), threshold 0.85 |
| `core/shield.py` | 1203 | Masks entities to `__PROT_{uuid8}_{rand8}` placeholders. Domain modes (legal/finance/code/general) with extra regex sets (DNI/NIE, IBAN, ISIN, CUSIP, case numbers…). Personal data via **spaCy NER** (`PER/PERSON/ORG/GPE/LOC`) + 6 regexes. Also extracts FORBID/MANDATE restrictions |
| `core/segmenter.py` | 940 | PySBD sentence splitting + MiniLM-L6-v2 embeddings, ONNX preferred (`ORTModelForFeatureExtraction`) with PyTorch fallback; `onnx_int8` flag; singleton |
| `core/compressor.py` | 888 | Low-variance filter → Ward (n<200) or MiniBatchKMeans clustering → pick cluster representatives |
| `core/safety.py` | 822 | Re-inserts sentences whose critical intent was destroyed by compression |
| `core/verifier.py` | 801 | Post-LLM: unauthorized-entity check (regex), **NLI contradiction** (`nli-distilroberta-base`, ONNX-preferred), forbidden-implication via entailment, semantic drift via cosine |
| `core/corrector.py` | 433 | Strips unauthorized entities, enforces FORBID (replace with `[PROHIBITED]`) / MANDATE (append a note), re-injects placeholders |
| `core/model_manager.py` | 153 | Singleton that verifies the 3 required model dirs exist and triggers a one-shot download; async-safe, SHA256-verifiable ZIP |
| `cache/semantic_cache.py` | 533 | RedisVL cosine-similarity response cache |

Three local models, all resolved from a local `models/` dir:
`all-MiniLM-L6-v2` (embeddings, 384d), `nli-distilroberta-base` (NLI),
`distilgpt2` (perplexity).

---

## 2. Honesty box — README claims vs. what the code does

These matter because the README's headline claims are exactly the ones
that made this repo interesting; two of them do not survive reading the
source.

### 2.1 "Offline-first, ONNX-quantized" is half true

ONNX is a *preferred backend with a PyTorch fallback*, chosen at runtime
by checking whether `model.onnx` exists (`verifier.py:_load_nli_model`,
`segmenter.py:_load_model`). The pinned `requirements.txt` nevertheless
installs `torch==2.12.0`, `transformers`, `sentence-transformers`,
`spacy==3.8.14`, and the **entire CUDA 12/13 wheel stack** (cuBLAS,
cuDNN, NCCL, cuSPARSE, Triton…). `verifier.py` imports `torch`
unconditionally at module scope and uses `torch.softmax` on the ONNX
path too. So: the *inference* can be ONNX; the *dependency footprint* is
a full PyTorch + spaCy install. There is no `onnx_int8` model actually
shipped — the flag exists in `SegmentationConfig`, nothing quantizes.

Also, `shield.py:_download_spacy_model()` will **pip-install a spaCy
model at runtime** if it is missing. That is a supply-chain and
cold-start hazard, and it contradicts "air-gapped ready".

Take-away for us: the `ModelManager` *pattern* (verify local dir →
one-shot download → refuse to start otherwise) is the good part. The
dependency hygiene is not; ours must be genuinely optional-extra
shaped, the way `ai-parrot[pii-native]` and `ai-parrot-embeddings` are.

### 2.2 The pipeline is synchronous inside an async server

In `server/apis/chat.py`, only compression is awaited. The firewall
(`firewall.check_prompt`), the shield, the corrector, and — worst — the
verifier are plain blocking calls on the event loop:

```python
final_response = dependencies.response_corrector.correct(response_text, shield_result)
verification   = dependencies.post_verifier.verify(final_response, shield_result)
```

And `_verify_with_nli` runs **one NLI forward pass per premise
sentence**, un-batched, in a Python `for` loop:

```python
for sentence in sentences:
    _, contradiction_score = self._nli_inference(sentence, response_text)
```

So the advertised "+30–60 ms per request (NLI enabled)" holds only for a
short prompt. A 40-sentence context is 40 sequential transformer passes
**on the event loop**, and the whole worker is frozen for the duration.
For an async-first framework this is disqualifying as an architecture —
but it is precisely the failure mode we must design against (§5).

### 2.3 The benchmark numbers are labelled estimates

`BENCHMARK.md` says "Real-world Estimates" and the SOTA comparison table
is self-assessed. There is no reproducible harness in the repo (unlike
our `benchmarks/pageindex_embedding_latency/` or
`tests/benchmarks/test_guardrails_pipeline_perf.py`). Treat every figure
(40–60% token reduction, 92% semantic recall, 78–85% NLI accuracy,
200–300 ms P95) as a claim, not a measurement.

---

## 3. Capability matrix

| Capability | NLProxy | AI-Parrot today | Notes |
|---|---|---|---|
| Pluggable guardrail abstraction | ✗ (fixed 6-stage pipeline, hardcoded in the handler) | ✓ `Guardrail` ABC, 5 stages, 4 verdicts, priority bands, per-guardrail `on_error`, telemetry (FEAT-396) | Ours is strictly more general |
| Stages covered | prompt-in, response-out | INPUT, **TOOL_CALL**, **TOOL_OUTPUT**, OUTPUT, **OUTPUT_STREAM** | A gateway structurally cannot see tool-call/tool-output |
| Prompt injection — patterns | 619-LOC rule engine, MITRE-ATLAS-inspired | `PromptInjectionDetector` (4 CRITICAL / 5 HIGH / 2 MEDIUM patterns) + framework allowlist | **Theirs is richer**; ours is deliberately small but has the allowlist concept they lack |
| Prompt injection — model | optional embedding similarity vs 7 attack prompts, cosine ≥ 0.85 | `pytector` deBERTa classifier, prob > 0.98, process-wide singleton | Ours is a real classifier; theirs is cheaper and explainable. Complementary |
| Prompt injection — mitigation | block or rewrite | block **or wrap in `<potentially_unsafe_input>` + `<security_note>`** | Ours is better: preserves the user's literal request |
| Secrets redaction | not a first-class concern | `OutputScrubber` + `SecretsGuardrail`, reason taxonomy (env_dump, secret_kv, dsn, jwt, cloud_key, net_topology), recursive `scrub()` for non-string tool payloads, idempotent | Ours wins outright |
| PII detection | spaCy NER + 6 regexes, mask to opaque UUID placeholders | **Not implemented.** FEAT-324 specced (YAML catalog, Rust `pii-rs`, Python fallback, per-agent policy, reversible pseudonymization, streaming filter); `"pii"`/`"pseudonymize"` are reserved names in the registry | This is our real gap — and NLProxy does not close it |
| Reversible masking | ✓ (placeholder map, re-injected post-LLM) | specced in FEAT-324 (pseudonym store, per-conversation restore) | Same idea, ours better specified |
| Output-stage masking | ✓ | specced (FEAT-324 primary use case) | Note: OpenAI Guardrails *cannot* do this — see sibling doc |
| Streaming guardrails | ✗ | `StreamingGuardrail` ABC with the "streaming ≡ non-streaming" invariant; **no concrete implementation yet** | Contract exists, no plugin uses it |
| Groundedness / hallucination | NLI contradiction (semantic), entity authorization, cosine drift | `GroundednessGuardrail` (FEAT-398): deterministic atom extraction (money/percent/number/date/identifier), precision-aware numeric tolerance, `supported`/`contradicted`/`unsupported`, FLAG-only, ~stdlib, zero model cost | **Different axes.** Ours catches wrong *numbers*; theirs catches wrong *statements* |
| Constraint enforcement (FORBID/MANDATE) | ✓ extraction + enforcement | ✗ | Genuinely absent from our stack |
| Tool-call authorization | ✗ | `PBACToolCallGuardrail` (FEAT-406) at TOOL_CALL stage | Not comparable — they have no tools |
| Context compression | semantic clustering of the *prompt* | FEAT-380 `tool-result-compression`: codec registry, `FilterLevel`, `BudgetRouter` + `CircuitBreaker`, Rust codec path | Different problem, ours is lossless-by-construction |
| Latency governance | none (fixed pipeline, blocking) | `BudgetRouter`/`CircuitBreaker` per codec, rolling p99, half-open re-arm | **Our biggest structural advantage — and the key to §5** |
| Telemetry | Prometheus at the HTTP layer | `GuardrailActionEvent` per guardrail (name/stage/action/duration), never content, via FEAT-176 observers | Ours is per-guardrail |
| Semantic response cache | ✓ RedisVL | ✗ | Real gap, separate feature |
| License | BSL 1.1 (commercial licence ≥ $1M revenue) | — | **We cannot vendor or copy their code.** Ideas and public papers only |

> **Licensing constraint, stated plainly**: BSL 1.1 is not open source for
> our purposes. Nothing in this document proposes copying NLProxy code.
> Every "adopt" below is an independent implementation of a published
> technique (SNLI/MultiNLI NLI, Sentence-BERT cosine, ONNX Runtime), not
> a port.

---

## 3b. Measured baseline (2026-08-20)

Everything below is measured, not projected. Harness:
`benchmarks/injection_guardrail_latency/` (96-sample EN/ES corpus, 10
timed passes, one process per tier, ORT/torch capped to 2 threads,
BLAS/OMP pinned to 1). Full tables in
`benchmarks/injection_guardrail_latency/results/report.md`.

### Cost

| Tier | load (s) | RSS Δ (MB) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|
| `regex` (today) | 0.00 | 0.0 | **0.01** | 0.02 | 0.02 |
| `embed-cosine` (proposed, torch) | 26.8 | 2365 | 7.78 | 8.56 | 9.48 |
| `clf-torch` (**today's production path**) | 7.27 | 1503 | **118.99** | 145.83 | 158.18 |
| `clf-onnx` (fp32) | 5.59 | 1911 | **32.96** | 59.85 | 65.97 |
| `clf-onnx-int8` | 5.06 | 1393 | 21.08 | 41.15 | 42.62 |

**The headline is the third row.** Every turn through a bot with
`injection_detection` enabled pays ~119 ms p50 / ~146 ms p95 of deBERTa
inference — synchronously, on the event loop, before the LLM call even
starts. That is the same architectural mistake this document criticises
NLProxy for in §2.2, and we are making it today.

### Quality

| Tier | thr | precision | recall | F1 | best-F1 thr | best F1 |
|---|---|---|---|---|---|---|
| `regex` | 0.90 | 0.92 | 0.24 | 0.38 | 0.60 | 0.43 |
| `embed-cosine` | **0.85** (NLProxy's) | 1.00 | **0.02** | 0.04 | **0.40** | **0.87** |
| `clf-torch` / `clf-onnx` | 0.98 | 0.90 | 0.70 | 0.79 | 0.98 | 0.79 |
| `clf-onnx-int8` | 0.98 | 0.00 | 0.00 | 0.00 | 0.50 | 0.04 |

### Blind spots (flag rate per bucket)

| Tier | attack_direct | attack_paraphrase | attack_obfuscated | clean (FP) | clean_framework (FP) |
|---|---|---|---|---|---|
| `regex` | 55% | **0%** | 10% | 2.9% | 0% |
| `embed-cosine` @0.85 | 0% | 5% | 0% | 0% | 0% |
| `clf-onnx` @0.98 | 75% | 50% | **100%** | **11.8%** | 0% |

Four findings that change the plan:

1. **ONNX fp32 is a free 3.6× win.** Same weights, `max|Δ| = 0.000`,
   zero flipped verdicts against the PyTorch reference — 119 ms → 33 ms
   p50 with *identical* answers. Take it.
2. **Dynamic int8 destroys this model.** `max|Δ| = 1.000`, 39/96 verdicts
   flipped (40.6%), every attack bucket at 0% recall. DeBERTa-v3's
   disentangled attention leaves most attention MatMuls unquantizable
   ("Ignore MatMul due to non constant B" on all 12 layers), and the
   numerics collapse. The 21 ms is real; the model is not. Static
   quantization with a calibration corpus, or a different architecture,
   would have to be tried and re-gated. The harness now enforces a
   parity gate so this can never be reported as a speed-up again.
3. **NLProxy's 0.85 cosine threshold is worthless on a disjoint corpus** —
   recall 0.02. Retuned to 0.40 the same tier scores **F1 0.87**, beating
   the classifier's 0.79 at 1/15th the latency. Their threshold only
   works against a corpus containing near-duplicates of its own seed set;
   ours is held disjoint (`assert_seed_disjoint()`), which is why the
   number collapses. Adopt the technique, discard the constant.
4. **Our 0.98 threshold has a false-positive problem, not a
   false-negative one.** The classifier flags 11.8% of ordinary business
   prompts — 4 of 34 clean samples — while catching only 50% of
   paraphrases. It *does* earn its keep on obfuscation (100% vs the regex
   tier's 10%). So the answer to "is the classifier pulling its weight at
   0.98?" is: **yes, but only for obfuscated input, and it is expensive
   and noisy for everything else.** That is precisely the profile of a
   tier that should run rarely, not always.

### Composed pipeline

`regex` → `embed-cosine` → `clf-torch` @ 0.98, band-swept:

| cosine band | escalation | precision | recall | F1 | effective p50 |
|---|---|---|---|---|---|
| (0.20, 0.45) | 46.9% | 0.90 | 0.90 | **0.90** | 63.6 ms |
| (0.30, 0.55) | 42.7% | 0.89 | 0.80 | 0.84 | 58.6 ms |
| (0.35, 0.60) | 35.4% | 0.90 | 0.76 | 0.83 | 49.9 ms |

The composed pipeline is **better than any tier alone** (F1 0.90 vs the
classifier's 0.79) *and* roughly half the latency, because the cheap tier
covers exactly the bucket the classifier is weakest on (paraphrase) while
the classifier covers the one it is strongest on (obfuscation).

Caveat on the effective-latency column: it is still dominated by the
7.8 ms torch encode in the middle tier. Moving that tier to ONNX (the
FEAT-237 `backend="onnx"` kwarg already exists) should cut it several-fold
and is the next measurement to take — the escalation rate, not the
classifier, is no longer the binding constraint.

---

## 4. Adopt / adapt / reject, with reasoning

### 4.1 ADOPT — offline model lifecycle + ONNX int8 for the injection classifier

**What they do.** `ModelManager` is a singleton with a
`REQUIRED_MODELS` registry, `verify_all()`, an async-safe
`ensure_ready()` that triggers a one-shot download, and optional SHA256
verification of the model archive. Models resolve from
`NLPROXY_MODELS_DIR`; nothing hits the network at inference time.

**Why it matters to us.** Our `PromptInjectionGuardrail` currently does
this (`builtin/prompt_injection.py`):

```python
_SHARED_INJECTION_DETECTOR = _PytectorDetector(
    model_name_or_url="deberta", enable_keyword_blocking=True,
)
```

That is a full deBERTa under PyTorch, resolved by `pytector` (which
pulls `transformers` + `torch`, and per our own module docstring drags
in TensorFlow), loaded **eagerly inside `__init__`** the first time any
bot registers the guardrail. We already did the right things — one
process-wide singleton, a module lock, `find_spec` gating — but the
model itself is the heavy, network-resolved, non-quantized path.

**Proposal.**

1. A shared `parrot.security.models` module: a `LocalModelRegistry` with
   `(name, dir, files, sha256, kind)` entries, `PARROT_MODELS_DIR`,
   `ensure_ready()`, and a hard failure (not a silent download) when a
   model is missing and `PARROT_MODELS_OFFLINE=1`.
2. An ONNX-int8 injection classifier as an alternative backend behind
   the *existing* `PromptInjectionGuardrail` interface — the guardrail
   contract does not change, only which engine answers. Keep pytector as
   a fallback, keep the regex engine as the always-available floor.
   Backend order: `regex` (always) → `onnx-int8` (if models present) →
   `pytector/torch` (if installed) — decided once at construction.
3. Reuse the ONNX session discipline we already learned the hard way in
   `voice/tts/supertonic_inference.py:462-472`:

   ```python
   opts = ort.SessionOptions()
   opts.intra_op_num_threads = _env_int("SUPERTONIC_ORT_INTRA_OP_THREADS", 2)
   opts.inter_op_num_threads = _env_int("SUPERTONIC_ORT_INTER_OP_THREADS", 1)
   ```

   The comment there — "by default ORT spawns an intra-op pool sized to
   ALL physical cores PER graph … that pegs every core at 100% and
   starves the aiohttp event loop (the avatar made the whole server feel
   frozen)" — is the single most valuable piece of prior art we own for
   this work. Any guardrail ONNX session must be capped the same way.

We also already have the embeddings-side plumbing: `EmbeddingModelEntry.
backend: "torch" | "onnx" | "openvino"` and `file_name` (e.g.
`model_quantized.onnx`) landed in FEAT-237, `onnxruntime>=1.16` is
already an `ai-parrot-embeddings` extra, and
`benchmarks/pageindex_embedding_latency/` is a working torch-vs-onnx
harness. This is an increment, not a new capability.

### 4.2 ADAPT — NLI contradiction detection as a *second tier* under FEAT-398

**The gap it fills.** `GroundednessScorer` is excellent at what it does
and blind to everything else. It extracts money/percent/number/date/
identifier atoms and matches them against tool-call evidence with a
precision-aware tolerance. If a tool returns `{"status": "cancelled"}`
and the agent says "your order is on its way", the report is
`no_factual_content=True, score=1.0`. Zero atoms, perfect score, wrong
answer. That is exactly the "las tool-calls contradicen lo que el agente
respondió" case.

**What to build.** A `SemanticGroundednessGuardrail` (OUTPUT, observer
band, FLAG-only — same non-mutating contract as FEAT-398, which is what
makes it safe to run speculatively):

- Premise = tool-result evidence spans; hypothesis = answer sentence.
  Note this is the **inverse** of NLProxy's orientation (they use the
  *prompt* as premise and the whole response as hypothesis, which
  conflates "contradicts the user's question" with "contradicts the
  facts"). For an agent, the tool result is the ground truth.
- Score `P(contradiction | evidence, claim)`; FLAG above threshold, with
  the offending (claim, evidence) pair in the report.
- Reuse `EvidenceIndex.from_tool_calls()` and the `max_evidence_bytes`
  cap that already exist.

**What to do differently from them** (all four are cheap and they do
none of them):

1. **Batch.** One tokenizer call, one forward pass over N (premise,
   hypothesis) pairs — not a Python loop over sentences.
2. **Gate.** Only run NLI on claim sentences that the deterministic pass
   already finds interesting (contain an atom, or overlap evidence
   lexically above a floor). Cheap-filter-then-expensive-model is the
   whole game.
3. **Cap.** Hard limit on pairs per turn (e.g. 16); log what was
   dropped, never silently truncate.
4. **Budget + breaker.** See §5.

### 4.3 ADAPT — semantic injection detection (cheap tier)

Their firewall's second layer is: embed the prompt, cosine against a
small corpus of attack prompts, flag ≥ 0.85. That is ~40 lines and one
embedding call. It catches paraphrases that regexes miss without the
cost of a classifier, and unlike a classifier it is *explainable* ("this
resembles attack pattern #3, sim=0.91").

For us it is nearly free: we already have the embeddings stack, and the
attack corpus is data, not code — it belongs in a YAML catalog next to
FEAT-324's PII catalog so security can extend it without a release.
Their 7-prompt hardcoded corpus is a toy; ours should ship a real one.

Position it as the **middle tier**: regex (µs) → embedding similarity
(~1 ms, one encode) → classifier (10–50 ms, only if the middle tier is
ambiguous). That tiering is what makes an expensive model affordable.

### 4.4 ADAPT — FORBID/MANDATE constraint enforcement (their most original idea)

`shield.py` extracts constraints from the prompt ("do NOT use Python",
"use Java") into `Restriction(type=FORBID|MANDATE, entity=...)`, and
`corrector.py` enforces them on the response: FORBID → replace
occurrences with `[PROHIBITED]`; MANDATE → append
`[Note: required entity missing: X]`. `verifier.py` additionally scores
`P(entailment | response, "contains F")` to catch *implied* violations.

We have nothing like it. The naive implementation is bad (blind
find-and-replace mangles code blocks and legitimate mentions —
"[PROHIBITED] is not supported here" is worse than the original), and
their MANDATE handling is frankly a hack. But the *detection* half is
sound and fits our observer band perfectly: extract constraints from the
system prompt and user turn, FLAG violations in
`AIMessage.metadata["guardrails"]`, and let the caller decide. A
regeneration loop ("retry once with the violation quoted back") is the
natural enforcement mode for an agent framework — NLProxy actually does
this (`chat.py:289`), and it is the right shape.

Candidate scope for a `ConstraintGuardrail` brainstorm, not a
copy-paste.

### 4.5 REJECT — spaCy NER for PII

`shield.py:_anonymize_personal_data` = spaCy NER (`PER/ORG/GPE/LOC`) +
6 regexes. This is architecturally the same family as Presidio, which
`pii-detection-redaction.comparison.md` already measured and rejected
for our seams:

- 1 KB PII-dense: Presidio 20.7 ms p50 / 36.6 ms p99 vs our Python
  prototype 0.14 / 0.23 ms — **~150×**.
- Peak RSS 147 MB (with a *blank* model) vs 10.4 MB.
- Cold init 2.85 s.

And spaCy NER is strictly heavier than what was measured there (that run
had NER disabled). The argument stands unchanged: the budget is consumed
*per seam invocation*, and invocations compose — N tool calls + final
response + a rescan every ≥32 chars of a streaming window. A 20–50 ms
engine in that loop is seconds of added latency; 0.1–1.7 ms is
imperceptible. Nothing in NLProxy changes the FEAT-324 plan.

One idea worth stealing from them regardless: their **domain modes**
(legal/finance/code/general) each activate a different regex set —
DNI/NIE for legal-ES, IBAN/ISIN/CUSIP for finance. FEAT-324's YAML
catalog should ship entity *bundles* along exactly those lines, and its
existing `PIIPolicy.allow_entities` already expresses the per-agent
override.

### 4.6 REJECT — clustering-based prompt compression

Ward/KMeans over sentence embeddings, keep one representative per
cluster. Three problems for us:

1. **It is lossy in an unbounded way.** They needed an 822-LOC
   `SafetyChecker` to detect that compression destroyed a critical
   intent and re-insert the sentence. That is a strong signal the
   primitive is wrong for the job.
2. **Cost.** Compression requires embedding every sentence — the 50–120
   ms CPU figure is embedding-dominated. Our FEAT-380 codecs are
   structural (columnar, json_compact) and budgeted at 3–5 ms inline.
3. **Wrong target.** Our token problem is fat *tool results*
   (`QueryResult` with 5000 rows), not chatty prompts. FEAT-380 already
   addresses that, losslessly, with a size estimate taken before
   compressing.

Their `SEMANTIC_STOPWORDS` set (bilingual EN/ES pleasantries and
connectors) is a cute deterministic trick, but it belongs to prompt
hygiene, not to a guardrail.

### 4.7 REJECT — the proxy topology itself

An HTTP gateway sees `messages[]` in and `choices[]` out. It cannot see
which tool the agent is about to call (our TOOL_CALL/PBAC stage), what a
tool returned before the LLM reads it (TOOL_OUTPUT), or a stream chunk
mid-flight with a secret straddling the boundary (OUTPUT_STREAM). All
three are where agent-specific leaks actually happen. Our in-process
guardrail seams are the correct placement; the gateway is a deployment
convenience, and one that adds a network hop to every guardrail.

---

## 5. The actual engineering question: offline models without wrecking latency

This is the part worth the most. NLProxy demonstrates the failure mode;
our existing FEAT-380 machinery already contains most of the fix.

### 5.1 Why ONNX makes async-safe guardrails possible at all

`onnxruntime`'s Python binding **releases the GIL for the duration of
`InferenceSession.Run()`**. That single fact is what separates an ONNX
guardrail from a pure-Python one:

> "Without `py.allow_threads()` the GIL is still held, so
> `run_in_executor` buys no real parallelism — it is theater."
> — `tools/compression/budget.py:9-12`

For pure-Python codecs that reasoning forced the `PASSTHROUGH` route.
For ONNX it inverts: `loop.run_in_executor(pool, session.run, ...)` is
**genuinely** off-loop, the event loop keeps serving other turns, and
the EXECUTOR route becomes the correct default for any model-backed
guardrail. Same for a Rust `pii-rs` with `allow_threads()` (FEAT-324
already plans this).

Caveat, and it is the one we already got burned by: ORT's default
intra-op pool is sized to *all* physical cores *per session*. Un-capped,
"off-loop" still starves the loop by pegging every core (see
`supertonic_inference.py:462`). Cap `intra_op_num_threads` (1–2) and
`inter_op_num_threads` (1), and size the executor pool explicitly.

### 5.2 Generalize `BudgetRouter`/`CircuitBreaker` from codecs to guardrails

`parrot/tools/compression/budget.py` already implements, tested and
calibrated:

- `Route.{INLINE, EXECUTOR, PASSTHROUGH}` decided from a cheap size
  estimate taken **before** doing the expensive thing;
- a per-codec `CircuitBreaker` — rolling window of 100 calls or 60 s,
  3 consecutive over-budget windows → degrade to passthrough + warn,
  half-open probe after a 5-minute cooldown;
- `p99(codec_name)` for reporting.

Every word of that applies to a model-backed guardrail with `codec_name`
→ `guardrail_name`. A `SemanticGroundednessGuardrail` whose p99 blows
its budget for three windows should silently degrade to the
deterministic FEAT-398 scorer and log it — not slow every turn down.
This is a *generalization* task (lift `budget.py` to
`parrot.core.budget`, keep the compression defaults), not a new
subsystem.

### 5.3 Proposed latency contract

| Tier | Guardrail | Stage | Route | Budget (p99) |
|---|---|---|---|---|
| 0 | regex injection, secrets scrub, atom groundedness | INPUT / TOOL_OUTPUT / OUTPUT | INLINE | ≤ 1 ms |
| 1 | PII regex/Rust scan | TOOL_OUTPUT / OUTPUT / STREAM | INLINE | ≤ 1 ms @ 10 KB (FEAT-324 gate) |
| 2 | embedding-similarity injection | INPUT | INLINE if ONNX; EXECUTOR under torch (measured 8.6 ms p95) | ≤ 5 ms |
| 3 | ONNX injection classifier (fp32) | INPUT | EXECUTOR | ≤ 70 ms p99 (measured 66), breaker-guarded |
| 4 | NLI contradiction (batched, gated, capped) | OUTPUT | EXECUTOR, **or fully detached** | ≤ 60 ms, breaker-guarded |

Tier 3+ only runs when the cheaper tier is ambiguous. The existing
priority bands already express the ordering (sanitizers 0–99,
transformers 100–199, observers 200+), and `GuardrailPipeline` already
short-circuits an empty pipeline at zero cost.

### 5.4 The detached-observer idea

Worth its own decision: a FLAG-only guardrail **cannot change the
response by contract** (FEAT-398 §5: "byte-identical whether scoring is
enabled or not"). Therefore it does not have to run before the response
is returned. Options:

- **(a) Blocking observer** — current model. Simple; costs the user its
  full latency.
- **(b) Detached observer** — return the answer, run the observer as a
  background task, emit the FLAG via `GuardrailActionEvent`/FEAT-176
  observers and persist to the report. Cost to the user: ~0. Cost to us:
  the report is not in `AIMessage.metadata["guardrails"]` at return
  time, so any consumer reading it synchronously breaks.
- **(c) Per-guardrail choice** — `execution: "blocking" | "detached"` on
  the guardrail, defaulting to blocking; observers may opt in.

(c) is almost certainly right, and it is what makes an NLI tier viable
at all for interactive agents. Needs a spec decision on whether a
detached FLAG can still be surfaced to the caller (probably: yes, via
the event stream and the audit ledger, not via the returned message).

### 5.5 Warm-up, not lazy-load

Today the deBERTa singleton loads inside the *first* guardrail
`__init__`, i.e. inside the first bot construction — sometimes on the
first user turn. NLProxy's `ensure_ready()` at server startup is the
better shape. Add an explicit async warm-up hook (load session + run one
dummy inference to JIT the graph) called from the bot manager's startup,
so the first real turn never pays cold-start.

---

## 6. Recommended next steps

Ordered by value-per-effort. Each is a `/sdd-brainstorm` candidate, not
a green light.

| # | Proposal | Rationale | Effort |
|---|---|---|---|
| 0 | **Swap the classifier backend to ONNX fp32** — nothing else | **119 ms → 33 ms p50, byte-identical verdicts** (§3b). The cheapest win in this document: no interface change, no threshold change, no quality trade-off | S |
| 1 | **Lift `BudgetRouter`/`CircuitBreaker` to `parrot.core.budget`** and wire it into `GuardrailPipeline` | Prerequisite for *every* model-backed guardrail; the code already exists and is calibrated. At a measured 146 ms p95 the classifier is far past any inline budget — it needs the EXECUTOR route today, not eventually | S–M |
| 2 | **`parrot.security.models` — offline model registry + ONNX session discipline** | Prerequisite for #3/#4/#5; encodes the supertonic thread-cap lesson once | M |
| 3 | **Tiered `PromptInjectionGuardrail`**: regex → embedding-similarity (YAML attack catalogue, threshold ~0.40) → ONNX fp32 classifier | Measured composed F1 **0.90 vs 0.79** for the classifier alone, at roughly half the latency (§3b). Also fixes the 11.8% false-positive rate on ordinary business prompts | M |
| 3b | **Investigate static int8 quantization** (calibration corpus) or a non-DeBERTa classifier | Dynamic int8 flipped 40.6% of verdicts — the parity gate in `benchmarks/injection_guardrail_latency/` must stay green before any quantized graph ships | M |
| 4 | **`SemanticGroundednessGuardrail`** — batched, gated, capped NLI over tool evidence, detached-observer capable | Closes the real blind spot in FEAT-398: contradictions with no numbers in them | L |
| 5 | **Unblock FEAT-324 (PII)** — unchanged plan, plus domain entity *bundles* from their mode idea | Our largest actual gap; the `"pii"`/`"pseudonymize"` registry names are still `NotImplementedError` | L |
| 6 | **First concrete `StreamingGuardrail`** (falls out of #5's sliding-window filter) | The ABC has existed since FEAT-396 with zero implementations | M |
| 7 | `ConstraintGuardrail` (FORBID/MANDATE detection + optional regeneration) | Novel capability, no equivalent anywhere in our stack | M |
| 8 | Semantic response cache | Real gap; unrelated to guardrails; separate track | L |

---

## 7. Open questions

1. **Detached observers** — can a FLAG report that lands after the
   response is returned still be considered "delivered"? Which consumers
   read `AIMessage.metadata["guardrails"]` synchronously today?
2. **Where do model weights live?** A `parrot-models` extra package, a
   download-on-first-use cache, or a required operator step? NLProxy's
   runtime `pip install` of spaCy models is the answer we must *not*
   copy.
3. **Which NLI model?** `nli-distilroberta-base` is their choice and it
   is old. A modern small cross-encoder likely beats it on accuracy and
   size — reuse `benchmarks/injection_guardrail_latency/` (its corpus,
   metrics, and parity gate all generalise). Note §3b's warning: do
   **not** assume an int8 export of a DeBERTa-family NLI model is usable
   without re-running the parity gate.
6. **Which embedder for the cosine tier?** The measured 7.8 ms p50 is a
   torch `paraphrase-multilingual-MiniLM-L12-v2`. Under ONNX
   (`backend="onnx"`, FEAT-237) it should drop several-fold — and the
   effective-latency column in §3b is currently dominated by this tier,
   not by the classifier. Measure before designing around it.
7. **Is 0.98 the right classifier threshold?** Measured: it is
   simultaneously too loose (11.8% FP on clean prompts) and too tight
   (50% recall on paraphrase). Retuning alone does not fix it — the
   best-F1 threshold *is* 0.98. The fix is the tier in front of it.
4. **Executor pool policy** — one shared thread pool for all model-backed
   guardrails, or one per guardrail? Interacts with ORT thread caps and
   with FEAT-380's future Rust codec path.
5. **Do we want an optional gateway at all?** Not for guardrails (§4.7),
   but a thin OpenAI-compatible front door has independent value for
   non-Python clients. Separate question, separate spec.

---

## References

- NLProxy — https://github.com/intellideep/nlproxy (BSL 1.1). Read at
  commit fetched 2026-08-20; file/line citations above refer to that
  clone.
- `sdd/proposals/pii-detection-redaction.comparison.md` — Presidio/spaCy
  latency measurements, reused here.
- `sdd/specs/guardrails-infrastructure.spec.md` (FEAT-396)
- `sdd/specs/deterministic-groundedness-scoring.spec.md` (FEAT-398)
- `sdd/specs/pii-detection-redaction.spec.md` (FEAT-324)
- `sdd/specs/tool-result-compression.spec.md` (FEAT-380) — `budget.py`
- `sdd/specs/pbac-guardrails.spec.md` (FEAT-406) — TOOL_CALL stage
- `benchmarks/injection_guardrail_latency/` — the harness behind §3b
  (corpus, tiers, parity gate, report); results in `results/report.md`
- `tests/benchmarks/test_injection_guardrail_metrics.py` — unit tests for
  its metric and parity logic
- `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py:450-485`
  — ONNX Runtime thread-cap prior art
- Bowman et al. (2015), SNLI — arXiv:1508.05326
- Williams et al. (2018), MultiNLI — NAACL-HLT
- Reimers & Gurevych (2019), Sentence-BERT — EMNLP-IJCNLP
