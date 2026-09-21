---
id: FEAT-585
title: Evaluate Laya for typed classification and agent model routing
slug: laya-adoption
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  file_path: sdd/proposals/laya_adoption.md
  fetched_at: 2026-09-21
  summary_oneline: Evaluate Laya before adopting it in AI-Parrot.
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-client-jev]
tags: [laya, classification, model-routing, guardrails, evaluation]
research_state: sdd/state/FEAT-585/
created: 2026-09-21
updated: 2026-09-21
---

# FEAT-585 — Evaluate Laya for typed classification and agent model routing

> Review draft. Proposal-state identity only; formal spec identity is reserved by sdd-spec.
> Audit: [research state](../state/FEAT-585/). Source preserved verbatim in source.md.

## 0. Origin

> This is an evaluation task, generating an "end-to-end" python script in artifacts/laya/

The source requests injection classification, cheaper same-provider routing in an assigned agent, and a grounded classification example. Its broader Jev, guardrail and workflow adoption ideas are motivation for evaluation. Numerical acceptance criteria are absent. [F001]

## 1. Synthesis Summary

Prepare a runnable evaluation before deciding on adoption. The available agent dispatch hook supports a script-local routing experiment, but fallback is an availability mechanism rather than a cost guarantee. Laya's typed outputs need explicit validation and cannot alone redact content. Overall confidence is medium in the evaluation approach; runtime suitability and security quality remain unmeasured. [F001–F005, F009–F011]

## 2. Codebase Findings

### 2.1 Localization

| Path | Symbol / area | Lines | Evidence |
|---|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | `_should_use_fallback` | 1155-1168 | F002 |
| `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py` | `execute_llm_call` | 171-200 | F002 |
| `packages/ai-parrot/src/parrot/bots/base.py` | `ask` | 1320-1400 | F003 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | `execute_llm_call` | 1215-1250 | F003 |
| `packages/ai-parrot/src/parrot/bots/guardrails/base.py` | `Guardrail` | 15-145 | F004 |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py` | `PromptInjectionGuardrail.check` | 700-765 | F004 |
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/secrets.py` | `SecretsGuardrail` | 39-105 | F004 |
| `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py` | `JevClient` | 1-30,125-180 | F005 |
| `packages/ai-parrot-client-jev/src/parrot/clients/jev/schema.py` | `questions_from_type` | 1-33 | F005 |
| `benchmarks/injection_guardrail_latency/README.md` | `evaluation methodology` | 1-150 | F006 |
| `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` | `mocked engine resolution` | 1-30 | F006 |
| `packages/ai-parrot/src/parrot/security/groundedness/guardrail.py` | `GroundednessGuardrail` | 1-85 | F006 |
| `packages/ai-parrot/pyproject.toml` | `optional dependencies` | 514-533,649-652,705-728 | F007 |
| `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager.register` | 935-979 | F007 |

### 2.2 Constraints discovered

- Main `ask()` dispatch does not forward `model=` in its constructed client kwargs. Propose overriding `execute_llm_call` in the evaluation subclass, injecting a request-local model and delegating to `super()` to retain budget handling. Verify the provider's actual selected model in the result. Do not mutate a shared client's default model. [F003]
- Fallback is optional and capacity-error driven; require an explicit primary/cheap pair and supplied price assumptions before reporting savings. Report requested versus actual model and provider fallback separately. [F002]
- Laya inference is synchronous. A persistent process worker can hold the chosen checkpoint; include IPC cost and worker startup separately. New async code must follow AGENTS.md. [F009, F010]
- Validate choice membership, finite probabilities/scores, missing answers and errors. For noul use its positive probability, not its confidence: a confidently negative answer must not become a threat. [F010]
- Existing guardrails have transformation and error policies. Evaluate injection detection against that behavior; PII presence classification cannot produce redacted content without a span detector/transformer. [F004, F010]
- Laya is absent from the inspected dependency declarations. Specify an isolated evaluation dependency setup and verify compatibility before any future installation; do not change the workspace lockfile during proposal work. [F007, F010]

### 2.3 Recent history

| Commit | Date | Relevance | Evidence |
|---|---|---|---|
| d454a65e0 | 2026-09-21 | Remove eager imports from client base | F008 |
| d9abaf495 | 2026-09-11 | Client budget gate | F008 |
| 577816386 | 2026-09-19 | Jev invoke telemetry | F008 |
| 5bde7aefb | 2026-09-18 | Jev timeout and answer-kind validation | F008 |

## 3. Probable Scope

### Proposed deliverable

A future callable Python evaluation script under `artifacts/laya/`, with lightweight fixtures and a usage document. These are proposed new artifacts, not existing files. This proposal creates no implementation. [F001]

1. **Prompt injection:** evaluate labeled clean, direct, paraphrased, obfuscated and framework-wrapped examples, including EN/ES if confirmed. Compare against the existing benchmark baseline on the identical corpus. Report confusion matrices, false negatives/positives and per-language results. Tune thresholds on a separate calibration set, never the held-out evaluation samples. [F004, F006]
2. **Model routing:** classify a request into primary/cheap/abstain, validate against an allowlist, then invoke the assigned agent through its script-local dispatch hook. Invalid decisions, timeouts and low confidence retain primary. Keep errors visible. Include simple versus complex requests and report routing accuracy plus downstream answer quality against a primary-only baseline. Live calls need an explicit model pair and cap. A dry run must be labeled incomplete for end-to-end evidence. [F002, F003, F009]
3. **Grounded classification:** provisional interpretation is a short supplied document with labeled categories and an unknown/insufficient-evidence outcome. Include contradictory and missing facts. If the owner instead means answer-versus-evidence entailment, adjust fixtures and expected outputs before implementation. Existing groundedness scoring is a separate output-observer contract. [F001, F006]

Record package/checkpoint revision, runtime versions, hardware and actual device, dataset identity, seed, question schema, threshold, cold load, warm p50/p95, peak RSS, per-sample decisions, errors and downstream usage. Include warmup and repeat counts; capture context-length effects and do not silently truncate evidence. Persist report data under the evaluation directory and test logs under `artifacts/logs/`. Treat tiny synthetic examples as smoke tests, not production accuracy estimates. [F006, F009–F011]

### Proposed completion evidence

- All three scenarios execute with real Laya inference; live routing demonstrates actual selected-model execution when configured.
- A repeatable report distinguishes cold/warm time, routing overhead, model usage and classifier quality. Missing backends or credentials appear as skipped/incomplete, not success.
- Local regression checks exercise confidently-negative noul, invalid answers, timeout/abstention, model isolation across requests, and no unintended default-model mutation.
- Numeric adoption gates are supplied by the owner or the result remains exploratory; no production replacement conclusion is inferred.

### Boundaries and risks

Production Jev replacement, shared client changes, ToolManager integration, workflow routing, fine-tuning and PII redaction are later decisions. Jev provides a typed-schema pattern but interchangeability needs explicit compatibility tests. [F005, F007]

Laya's upstream router chooses its own checkpoint; our evaluation must make a separate downstream model decision. The typed specialist is English and domain-limited, with overconfidence warnings; its Jev comparison is not head-to-head. Measure checkpoints deliberately. The community ONNX artifact could not be verified and is deferred rather than assumed compatible. [F009, F011, F012]

Upstream references: [router source](https://raw.githubusercontent.com/NandhaKishorM/laya/main/laya/router.py), [runtime source](https://raw.githubusercontent.com/NandhaKishorM/laya/main/laya/agent.py), [package metadata](https://raw.githubusercontent.com/NandhaKishorM/laya/main/pyproject.toml), [typed-decisions model card](https://huggingface.co/convaiinnovations/laya-typed-decisions). Inspected on 2026-09-21; moving upstream branches are not reproducible pins. [F009–F011]

## 4. Confidence Map

| ID | Claim | Evidence | Confidence |
|---|---|---|---|
| C1 | Evaluation scope is explicitly requested. | F001 | high |
| C2 | Fallback selection does not guarantee a cheaper model. | F002 | high |
| C3 | A script-local dispatch-hook override is a plausible routing seam; runtime verification is still required. | F003 | medium |
| C4 | Typed decisions cannot substitute for content redaction without a separate transformer. | F004, F010 | high |
| C5 | Existing Jev schema offers a compatibility pattern, not proven replacement parity. | F005 | medium |
| C6 | Existing injection benchmark provides a reusable, limited synthetic baseline. | F006 | high |
| C7 | Laya installation and runtime compatibility have not been verified. | F007, F010 | high |
| C8 | Laya checkpoint selection is distinct from downstream LLM selection. | F009 | high |
| C9 | Adoption quality and local speed remain unproven. | F011 | low |

Distribution: 6 high, 2 medium, 1 low. Low confidence concerns adoption suitability; the evaluation is intended to resolve it.

## 5. Open Questions

- **U1** Which target hardware and languages should the evaluation cover? Owner: requester. Options: CPU with EN/ES; GPU with EN/ES and additional languages.
- **U2** Which provider, primary model and cheaper model should the live routing scenario use, and what call budget applies? Owner: requester. Options: Explicit same-provider pair and capped live calls; Routing-only mode until a pair is supplied.
- **U3** What accuracy/false-negative, latency and cost thresholds define success; is an exploratory report sufficient initially? Owner: requester. Options: Exploratory report with no production adoption claim; Specify numerical acceptance gates.
- **U4** Does grounded classification mean document-based categorization, or answer-versus-evidence entailment? Owner: requester. Options: Classify a supplied document with known labels; Judge an answer against supplied evidence; Include both small examples.

No user answers or acceptance have been inferred. Review choice: proceed, refine research, refine synthesis, or abort.

## 6. Recommended Next Step

Resolve the four material choices, using `$sdd-brainstorm laya-adoption` if design exploration is needed. Once scope is settled, `$sdd-spec laya-adoption` should specify the evaluation only. Do not jump to implementation tasks or production replacement. [F001, F003, F011]

## 7. Research Audit

Source, plan, twelve compact findings, synthesis and resumable state are in [sdd/state/FEAT-585/](../state/FEAT-585/). The local work plan is `artifacts/plan_laya_adoption.md` and is excluded from the skill's eventual commit scope.

Research counters: {'files_read': 19, 'grep_calls': 13, 'git_calls': 2, 'wall_seconds': 142.44}. Default caps: 40 files, 25 grep/tree queries, 10 git-history calls, depth 2, 300 seconds. Counters cover focused research, excluding setup/templates, free wiki orientation and rendering. No inference, installation or provider calls were executed. Upstream ONNX retrieval failed; this is a documented evidence gap.

## 8. Provenance

Generated using sdd-proposal, parrot-wiki, repository source and upstream primary sources. State and research-plan schema version 1.0. Review gate is pending; this draft is not accepted or committed. Research-plan schema lacks wiki/web query types, so those steps are recorded in plan metadata.
