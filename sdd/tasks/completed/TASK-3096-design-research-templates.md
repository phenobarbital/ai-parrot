# TASK-3096: Design-research templates — neutral brief prompt + suggestions JSON schema

**Feature**: FEAT-545 — Collaborative Adversarial Spec Design
**Spec**: `sdd/specs/collaborative-adversarial-spec-design.spec.md` (§3 Module 4, §2 Data Models)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The `/sdd-spec` §3b phase (TASK-3097) pipes a *neutral brief* into `codex exec --output-schema <schema>` and reads back a JSON list of suggestions. Both artifacts are templates under `sdd/templates/`: the brief (`design_research.prompt.md`, with `{{placeholders}}`) and the output contract (`design_research.schema.json`). The brief must never carry the spec draft or Claude's reasoning (spec §7 Ratification risk; `.claude/agents/sdd-secondopinion.md:35-41`).

---

## Scope

- Create `sdd/templates/design_research.schema.json` exactly as spec §2 Data Models.
- Create `sdd/templates/design_research.prompt.md` with the six placeholders, the role/rules header, and the forbidden-inputs comment.

**NOT in scope**: invoking codex (TASK-3097); tests (TASK-3098).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/design_research.schema.json` | CREATE | Draft 2020-12 schema, all properties required, `additionalProperties: false` |
| `sdd/templates/design_research.prompt.md` | CREATE | Neutral brief template (~45 lines) |

---

## Codebase Contract (Anti-Hallucination)

### Directory
```text
sdd/templates/   contains today: brainstorm.md finding.md proposal.md research_plan.prompt.md spec.md synthesis.prompt.md task.md
                 → the two new files follow the existing `<name>.prompt.md` naming (cf. research_plan.prompt.md, synthesis.prompt.md)
```
### Schema validation precedent
```text
jsonschema 4.26.0 installed; declared at packages/ai-parrot/pyproject.toml:80 ("jsonschema>=4.20", Draft 2020-12 capable)
```
### Neutral-brief rule (copy the spirit, cite the source)
```text
.claude/agents/sdd-secondopinion.md:35-41  — brief = exactly the artifact, the requirements, and a question; never the primary's reasoning
.claude/agents/code-reviewer.md:136-138    — "Never feed the reviewer your reasoning or draft review."
```
### Does NOT Exist
- ~~`sdd/templates/design_research.*`~~ — created here
- ~~`sdd/templates/design_research.prompt.j2`~~ — no templating engine; `{{name}}` placeholders are replaced with `sed`/`python -c` by the command
- ~~`"kind": "perf"`~~ or other enum values — the enum is exactly `architecture | api | testing | risk | alternative`

---

## Implementation Notes

### Key Constraints
- OpenAI structured outputs require every property in `required` and `additionalProperties: false` at each object level — keep it that way or `--output-schema` is rejected.
- `maxItems: 12` keeps the triage table bounded.
- The prompt asks for **one JSON object and nothing else**; the schema is enforced by codex, but the instruction prevents prose leakage into `-o`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the schema file verbatim — *why*: it is also the fixture for TASK-3098's tests; any drift breaks them.
2. Write the prompt file — *why*: TASK-3097 renders it by replacing the six placeholders; names must match exactly.
3. `python -c "import json,jsonschema;s=json.load(open('sdd/templates/design_research.schema.json'));jsonschema.Draft202012Validator.check_schema(s);print('schema ok')"`.
4. `grep -o '{{[a-z_]*}}' sdd/templates/design_research.prompt.md | sort -u` → exactly six names.

### `sdd/templates/design_research.schema.json` (CREATE)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SDD design research suggestions (FEAT-545)",
  "type": "object",
  "required": ["summary", "suggestions"],
  "additionalProperties": false,
  "properties": {
    "summary": {
      "type": "string",
      "description": "At most three sentences: how the reviewer read the brief and what it focused on."
    },
    "suggestions": {
      "type": "array",
      "maxItems": 12,
      "items": {
        "type": "object",
        "required": ["id", "kind", "title", "rationale", "affected_paths", "risk", "confidence"],
        "additionalProperties": false,
        "properties": {
          "id":             { "type": "string", "pattern": "^S[0-9]{1,2}$" },
          "kind":           { "type": "string", "enum": ["architecture", "api", "testing", "risk", "alternative"] },
          "title":          { "type": "string", "maxLength": 120 },
          "rationale":      { "type": "string", "description": "Why this matters and what evidence in the repo supports it." },
          "affected_paths": { "type": "array", "items": { "type": "string" }, "description": "Repo-relative paths the reviewer actually opened. Unverifiable paths cause the suggestion to be rejected." },
          "risk":           { "type": "string", "enum": ["low", "medium", "high"] },
          "confidence":     { "type": "string", "enum": ["low", "medium", "high"] }
        }
      }
    }
  }
}
```
**Why this shape**: mirrors spec §2 Data Models one-to-one; `enum` entries carry `"type": "string"` so strict-mode validators accept them; `pattern` on `id` keeps the §9 table sortable.

### `sdd/templates/design_research.prompt.md` (CREATE)
````markdown
<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec §3b and piped to `codex exec … --output-schema design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders: {{problem_statement}} {{constraints_and_goals}} {{recommended_option_or_scope}}
                {{code_context_paths}} {{open_questions}} {{question}}
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
{{problem_statement}}

### Constraints and goals
{{constraints_and_goals}}

### Recommended option / probable scope
{{recommended_option_or_scope}}

### Verified code anchors (paths only — open them yourself)
{{code_context_paths}}

### Questions still open in the exploration document
{{open_questions}}

## Question
{{question}}
````
**Why this shape**: the HTML comment documents the forbidden-inputs rule *inside the artifact* so the rule travels with the file; the body is the three-part neutral brief (artifact, requirements, question) from `sdd-secondopinion.md:35-41`. Default `{{question}}` value (set by `/sdd-spec` when none is given): "Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?"

### FILL IN checklist
- [ ] none — both files are fully specified

---

## Acceptance Criteria

- [ ] Schema passes `Draft202012Validator.check_schema` (Blueprint step 3)
- [ ] `grep -o '{{[a-z_]*}}' sdd/templates/design_research.prompt.md | sort -u | wc -l` → `6`
- [ ] Prompt contains the string `FORBIDDEN INPUTS` and "exactly ONE JSON object" (spec AC-6)
- [ ] Only the two new files are added

---

## Test Specification

Automated in TASK-3098 (`test_schema_is_valid_draft_2020_12`, `test_sample_suggestions_validate`, `test_unknown_kind_rejected`, `test_prompt_has_all_placeholders`). Manual now: Blueprint steps 3–4.

---

## Agent Instructions

1. Read spec §3 Module 4 and §2 Data Models.
2. Dependencies: none (parallel-safe).
3. Implement from the blueprint; run steps 3–4; commit both files.
4. Move to completed; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Created both files verbatim from the blueprint. Schema validated with
`Draft202012Validator.check_schema`; prompt contains all 6 required placeholders,
`FORBIDDEN INPUTS`, and "exactly ONE JSON object". Both files hit the repo's global
`templates/` .gitignore rule (as new files, unlike the already-tracked `task.md`/`spec.md`), so
committed with `git add -f` per the CLAUDE.md heads-up.

**Deviations from spec**: none
