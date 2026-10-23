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
parrot-formdesigner validates every form submission on two paths: a deterministic
validator (FormValidator) and an optional LLM answer-plausibility checker. The audit
trail of what was validated has two holes.

1. The deterministic result is not stored. Only the fact that it passed (is_valid) is
   saved. Which rules ran and what they checked is never written down. For a billing
   dispute that reads as "it passed validation", not "it passed these 14 checks".

2. The model can end up unidentified. LLMValidationConfig.model is `str | None`, and
   when it is None the client's default model is used -- so report.model ends up null.
   At that point the record does not say which model answered. For a finance team that
   is exactly the hole they anticipate.

### Constraints and goals
- Async-first Python, aiohttp, Pydantic v2, uv workspace under packages/.
- The deterministic trace must be collected additively: the return signature of
  FormValidator.validate_field (list[str]) must not change and its callers must not
  break. An explicitly passed optional collector, never an implicit ContextVar.
- Every channel (HTTP, A2UI, MS Teams, Telegram, audio) must inherit the trace by
  construction, taken from the ValidationResult the shared SubmissionPipeline already
  produces -- not re-implemented per channel.
- A 200-field form at roughly 8 checks per field must not overflow the stored row:
  a hard size cap with an explicit truncation marker is required.
- The trace must be reconstructable: a reader must be able to re-derive which checks
  those were, and against which exact ruleset version.
- This is a follow-on to FEAT-728 (LLM plausibility enforcement policy), which is
  already merged and closed.

### Recommended option / probable scope
Four decisions are already fixed by the product owner and are constraints, not options:

1. Granularity: a per-form configuration block with three levels. "summary" (default):
   a header, a schema fingerprint, per field the list of names of the checks that ran,
   and failures in full. "full" (opt-in): every check with its bound and its PASS/FAIL
   outcome. "off": today's behaviour. The schema fingerprint is a canonical sha256 over
   the validation-relevant subset of the FormSchema (constraints, required, options,
   rules, types).

2. Persistence: in context["validation"] as JSONB, symmetric with the existing
   context["llm_validation"]. No migration, no new column.

3. Model identity: do NOT change the meaning of PlausibilityReport.model (it stays the
   value requested in config, and is already documented). Add resolved_model, provider
   and usage read off the response AIMessage. A report with status="ok" must never lack
   an identified effective model; status="skipped"/"blocked" legitimately has none.

4. Exposure: the trace is NOT returned in the 200 of submit, nor in the validate
   response. It is read by submission_id through an authenticated, RBAC-permissioned
   read, so public form clients never see constraints or check names.

Scope: the deterministic checks to trace are _detect_circular_dependencies and
validate_rules (form level, early returns), the RuleEvaluator resolution of effective
visible/required (which is what RELAXES a required), required, _validate_relation_shape,
_coerce_value, the FieldConstraints bounds (min_length/max_length/min_value/max_value/
pattern/min_items/max_items/allowed_mime_types), _validate_by_type, the SELECT/
MULTI_SELECT option set, _run_cross_field_validation, _run_async_validator,
_validate_remote_response and _validate_rest_field.

### Verified code anchors (paths only — open them yourself)
packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/rbac.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py
packages/ai-parrot/src/parrot/models/responses.py
docs/formdesigner-llm-validation-enforcement.md

### Questions still open in the exploration document
none

## Question
Given this design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
