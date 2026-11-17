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
AI-Parrot's guardrails infrastructure (FEAT-396) today enforces exactly one security category with a real engine: prompt injection on user INPUT, via PromptInjectionGuardrail backed by the Wolf Defender ONNX classifier (patronus-studio/wolf-defender-prompt-injection-small, FEAT-439). For agents deployed in higher-assurance environments we need the next three guardrail categories as additional, independent security layers:

- JAILBREAK — attempts to override the agent's system instructions or bypass its operational boundaries (role-play exploits, DAN-style prompts, instruction-override framing). Today nothing classifies these distinctly: the injection model catches some, misses the rest, and there is no per-category policy or telemetry.
- PROMPT_INJECTION beyond INPUT — unintended instructions embedded in retrieved documents, tool outputs, or RAG chunks. The TOOL_OUTPUT pipeline seam exists (FEAT-396 Module 3) but only SecretsGuardrail runs there; a poisoned document reaches the agent loop unmarked.
- PROMPT_LEAKAGE — attempts to extract the system prompt or internal configuration (INPUT side), and actual reproduction of the system prompt in a response (OUTPUT side). Nothing detects either today.

Affected: every bot/agent exposed to untrusted users or untrusted retrieved content; operators who need per-category security telemetry and blocking policies.

### Constraints and goals
- Follow the existing pattern: each category is a pluggable Guardrail (FEAT-396) registered by name, configured via guardrails=[...], with the PromptInjectionGuardrail policy shape (strict_mode, block_on_threat, probability threshold) and verdict semantics (default TRANSFORM/FLAG, BLOCK opt-in via block_on_threat).
- No network on the request path: ML engines are local ONNX classifiers with the FEAT-439 resolution chain (env dir -> cached HF snapshot -> fallback -> heuristic floor) and an explicit warmup_* download function.
- ES/EN mandatory with a false-positive gate: every candidate model runs through the benchmarks/injection_guardrail_latency/ harness (extended with jailbreak/leakage corpora) and must pass a Spanish-benign FP gate before becoming a default — the Wolf Defender precedent (DeBERTa produced 7-8/10 Spanish FPs; wolf-defender 0/10).
- Hybrid engines: ML classifiers for jailbreak/injection; deterministic matching (n-grams + fuzzy) against the real system prompt for OUTPUT-side leakage — no classifier can know our prompt.
- Zero behavior change by default: bots that don't register the new guardrails behave bit-identically; TOOL_OUTPUT injection scanning is opt-in on the existing guardrail.
- Telemetry never carries content (FEAT-396 invariant): reports carry categories, scores, counts — never the offending text or the system prompt.
- Lazy imports: no ONNX/transformers import at module import time (FEAT-439 discipline); registry factories stay lazy.

### Recommended option / probable scope
Recommended Option A: Per-category plugins on a shared ONNX-engine chassis (hybrid).

Three deliverables, mirroring how PromptInjectionGuardrail is built:

1. JailbreakGuardrail (INPUT, sanitizer band): its own ONNX engine, selected by a mandatory bake-off — the same process that picked Wolf Defender for injection (compare_models.py latency + ES/EN accuracy + Spanish-benign FP gate), run over a candidate matrix BEFORE a default is pinned. The bake-off is the feature's first task; the guardrail code is engine-agnostic. Two engine shapes are in the matrix, both behind the chassis score(text) -> [0,1] protocol:
   - Classifier (softmax over logits — wolf-defender shape): Prompt Guard 2 ONNX re-exports (gravitee-io/Llama-Prompt-Guard-2-86M-onnx), mmBERT jailbreak detectors (vllm-sr/mmbert32k-jailbreak-detector-merged, apache-2.0), mDeBERTa fine-tunes (madhurjindal/Jailbreak-Detector-Large, MIT).
   - Embedding similarity (0din shape, 0dinai/jailbreak-embeddings-base-onnx — no license declared, blocker unless clarified): embed the input (mean pooling + L2 norm) and score = max cosine vs a reference corpus of known jailbreak prompts (managed, versioned data asset seeded from WildJailbreak + curated ES/EN attacks; hardening = append vectors, no retrain).
   Same resolution chain as injection and its own warmup_jailbreak_model(); heuristic keyword/pattern floor when no model is available.

2. Tool-output injection scanning: extend PromptInjectionGuardrail with an opt-in scan_tool_output=True policy that adds GuardrailStage.TOOL_OUTPUT to its stages. On detection in a tool/RAG result: TRANSFORM — wrap the content in the existing untrusted-content markers (_wrap_flagged_input) + FLAG report; never BLOCK the turn for one poisoned document.

3. PromptLeakageGuardrail (INPUT + OUTPUT): INPUT side detects extraction attempts with deterministic patterns (reusing the PromptInjectionDetector regex machinery style); OUTPUT side runs deterministic leak detection — normalized word n-gram shingles of the rendered system prompt matched against the response, plus a fuzzy similarity pass to catch lightly edited copies. Optional canary-token policy (operator embeds a canary in the prompt; detection is exact).

To avoid triplicating the ~500 lines of engine-resolution/warmup machinery in prompt_injection.py, the chassis (engine protocol, probe/build/resolve/warmup functions) is factored into a shared private module parametrized by env-var prefix, model id, and graph path, with two engine shapes behind the same score(text) -> [0,1] protocol: the existing classifier engine (softmax over logits) and a new embedding-similarity engine (embed -> max cosine vs a reference-corpus matrix). Both ML guardrails consume it.

Default posture mirrors prompt_injection: detections TRANSFORM (wrap as untrusted / annotate) and FLAG into AIMessage.metadata["guardrails"][<name>]; block_on_threat=True upgrades CRITICAL/HIGH detections to BLOCK with the existing canned response and selects on_error="fail_closed".

OUTPUT leakage obtains the turn's rendered system prompt from ctx.extras["system_prompt"] (new: _run_output_pipeline populates it alongside the existing ai_message extra when a leakage guardrail is registered).

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/bots/guardrails/base.py
packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py
packages/ai-parrot/src/parrot/bots/guardrails/registry.py
packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
packages/ai-parrot/src/parrot/bots/guardrails/builtin/moderation.py
packages/ai-parrot/src/parrot/bots/guardrails/builtin/secrets.py
packages/ai-parrot/src/parrot/security/prompt_injection.py
packages/ai-parrot/src/parrot/bots/abstract.py
packages/ai-parrot/src/parrot/tools/abstract.py
packages/ai-parrot/pyproject.toml
benchmarks/injection_guardrail_latency/compare_models.py
benchmarks/injection_guardrail_latency/corpus.py
benchmarks/injection_guardrail_latency/detectors.py
benchmarks/injection_guardrail_latency/export.py

### Questions still open in the exploration document
- Jailbreak bake-off (feature's first task, hard gate): run the candidate matrix through the extended compare_models.py — latency, ES/EN accuracy, Spanish-benign FP gate — and pin the winner as default. Licenses re-verified per candidate at that point.
- 0din-specific caveat if it competes: trained/evaluated only for duplicate detection among attacks (55-pair eval, "directional") — its benign-vs-attack FP behavior is exactly what the gate must establish.
- Reference attack corpus (only if an embedding engine wins): sourcing (WildJailbreak license for derived embeddings? curated internal set?), size budget, where it ships (package data vs HF dataset vs env dir), and update cadence.
- Fuzzy matcher for leakage: add rapidfuzz to core deps (touches test_dependency_boundary.py) vs stdlib difflib.SequenceMatcher (slower, zero deps)?
- Which system-prompt artifact does OUTPUT leakage compare against: the static template (system_prompt property) or the per-turn rendered prompt (incl. skills/tenant layers)? Rendered is more correct but needs a per-turn cache or re-render at OUTPUT time.
- Streaming leakage: accept v1 limitation (final-message check only — leaked chunks already streamed) or invest in a StreamingGuardrail withholding adapter?
- Confirm scan_tool_output default-off (opt-in) for the compat invariant, and whether per-tool opt-out is needed (e.g. skip scanning trusted internal tools).
- Canary-token support in v1 (canary policy key, operator-managed) or follow-up? Auto-injection into the prompt is explicitly out of scope either way.
- INPUT-side leakage (extraction attempts): heuristics-only in v1, or also consult the jailbreak model's score (extraction attempts often classify as jailbreak)?
- Priority ordering within the sanitizer band (injection 10 -> jailbreak 11 -> leakage 12): confirm, and decide whether a combined "security" convenience preset (guardrails=["security"]) is worth adding.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
