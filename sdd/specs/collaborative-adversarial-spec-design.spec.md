---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Collaborative Adversarial Spec Design

**Feature ID**: FEAT-545
**Date**: 2026-09-10
**Author**: Jesus Lara
**Status**: draft
**Target version**: n/a — SDD tooling (`.claude/commands`, `sdd/templates`, `CLAUDE.md`); nothing ships in a package
**Proposal**: `sdd/proposals/collaborative-adversarial-spec-design.proposal.md` (accepted 2026-09-10; research audit at `sdd/state/FEAT-545/`)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Specs are written by thinking models (Fable, Opus) and executed by cheaper,
non-thinking models (Haiku, Sonnet) that read a `TASK-*.md` file and write
code to disk. Today two pipeline rules work against that split:

1. `/sdd-spec` and `/sdd-task` both forbid implementation code ("specs are
   design documents", "tasks are plans, not code" — `.claude/commands/sdd-spec.md:17`,
   `.claude/commands/sdd-task.md:14`). Yet `/sdd-task` §3 already states the
   consequence: "The implementing agent (often Sonnet or Haiku) WILL
   hallucinate if not given explicit, verified code anchors" (`sdd-task.md:111`).
   The Codebase Contract gives the executor *anchors*; nothing gives it the
   *code shape* it is expected to produce. Code density in current specs is
   author-dependent (0–384 fenced lines across the six newest specs) and the
   newest active task file carries one fenced line (proposal F005).
2. The spec is drafted by a single model with no independent design input.
   The repository already runs an **Adversarial Cross-Check** with the
   `codex` CLI for *code review* (`.claude/agents/code-reviewer.md:119-194`,
   `CLAUDE.md:124-175`), but nothing equivalent exists at design time, where
   a second opinion is cheapest to act on.

### Goals

- **G1 — Executor-ready task files.** Every `TASK-*.md` produced by `/sdd-task`
  carries an **Implementation Blueprint**: ordered steps, one code block per
  file the task creates or modifies that a non-thinking executor can write to
  disk nearly verbatim, a short *why* per block, and an explicit `FILL IN`
  checklist for the judgement calls deliberately left open. Not the full
  implementation (proposal U3).
- **G2 — Interface skeletons in the spec.** Every module in spec §3 carries an
  **Interface Skeleton** (signatures + docstrings + `verified:` anchors, no
  bodies), so blueprints are derived once, at task time, against a freshly
  re-verified Codebase Contract.
- **G3 — Collaborative design research at spec time.** `/sdd-spec` gains an
  optional phase that hands the *accepted* brainstorm/proposal (never the
  spec draft) to the `codex` seat running `gpt-5.6-luna` with high reasoning
  effort, receives schema-validated suggestions, and triages each one
  CONFIRM / REJECT / ESCALATE into a new spec **§9 Design Research
  Cross-Check** (proposal U1, U2).
- **G4 — Never blocks.** The Codex phase is optional: absent binary, rejected
  model, timeout, or invalid output ⇒ `/sdd-spec` records "skipped (<reason>)"
  in §9 and continues. Required because `sdd-planner` runs `/sdd-spec`
  unattended (proposal U4, F012).
- **G5 — Twins stay in sync.** Every edit to `.claude/commands/sdd-spec.md`
  and `sdd-task.md` is mirrored into `.agent/workflows/`, and a test enforces it.

### Non-Goals (explicitly out of scope)

- Writing complete implementations in specs or tasks. Blueprints stop at the
  mechanical parts; branches, edge cases and test bodies are `FILL IN` stubs.
- Any change to the Python dev-loop (`parrot/flows/dev_loop/**`): no new
  dispatcher, profile, or `conf.py` key. The phase uses the prose `codex` CLI
  path exactly like the code-review cross-check does.
- A second Codex pass at `/sdd-task` time over the task decomposition. The
  proposal §6 flagged this as a possible task (6); it was not requested and is
  deferred to a follow-up spec if wanted.
- Changes to `/sdd-brainstorm`, `/sdd-proposal`, `sdd-worker`, `/sdd-start`,
  `reserve_ids.py` or the id ledger.
- Using `agy` as the design-research seat — banned as a reviewer
  (`CLAUDE.md:130`), unchanged.

---

## 2. Architectural Design

### Overview

Two independent enrichments of the SDD prose pipeline, plus the plumbing that
keeps them honest:

**A. Blueprint-carrying tasks (G1, G2).** `sdd/templates/spec.md` §3 gains an
*Interface Skeleton* sub-block per module; `sdd/templates/task.md` gains an
*Implementation Blueprint* section between "Implementation Notes" and
"Acceptance Criteria". `/sdd-spec` §4/§5 require the skeletons; `/sdd-task` §3/§4
require the blueprint and define its rules (one block per listed file,
mechanical code complete, `# FILL IN:` markers bounded by a constraint or an
acceptance criterion, every import taken from the task's Verified Imports,
MODIFY blocks anchored to a verified line). The two no-code guardrails are
reworded accordingly. `sdd-worker` needs no change: it already reads the whole
task file and implements "EXACTLY as specified" (`.claude/agents/sdd-worker.md:211-233`).

**B. Design research phase (G3, G4).** A new `/sdd-spec` step **§3b** runs
after the §2c carry-forward summary and before §4 codebase research, so the
external opinion can shape both §2 Architectural Design and §6 Codebase
Contract while Claude has not yet drafted either (anti-ratification). It:

1. Runs only when an exploration doc with `status: accepted` exists and
   `command -v codex` succeeds; otherwise writes the skip reason and moves on.
2. Renders a **neutral brief** from `sdd/templates/design_research.prompt.md`
   filled with the exploration doc's Problem Statement, Constraints/Goals,
   Recommended Option (or proposal §3 Scope), Code Context / §2 findings
   (paths only), and unresolved questions — never Claude's reasoning or draft.
3. Executes, in the background with a 600 s cap:
   ```bash
   MODEL="${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}"
   DR="sdd/state/.design_research/<feature-name>"   # id-independent staging (FEAT-ID is reserved later, in §5)
   timeout 600 codex exec --ephemeral --sandbox read-only --cd "$REPO_ROOT" \
     -m "$MODEL" -c model_reasoning_effort=high --ignore-user-config \
     --output-schema sdd/templates/design_research.schema.json \
     -o "$DR/suggestions.json" - < "$DR/brief.md" > "$DR/codex.log" 2>&1
   ```
   `--ignore-user-config` is deliberate: the seat must not inherit the
   operator's `~/.codex/config.toml` model (proposal F009).
4. Validates `suggestions.json` against the schema; for each suggestion,
   verifies every `affected_paths` entry exists (read/grep) and records a
   disposition with a reason: **CONFIRM** (fold into §2/§3/§7 while
   drafting), **REJECT** (reason only), **ESCALATE** (becomes a `[ ]` item in
   §8). Unverifiable paths ⇒ REJECT with reason "path not found".
5. Renders spec **§9 Design Research Cross-Check** (table + model + status
   + transcript path). In §6, after `FEAT_ID` is known, moves the staging dir
   to `sdd/state/<FEAT-ID>/design_research/` and commits it with the spec.

**Resolved decisions carried from the proposal** (also echoed in §8):
model `gpt-5.6-luna` via `SDD_DESIGN_RESEARCH_MODEL`, verified against
codex-cli 0.153.4 (proposal F017) · triage table in §9 · blueprints live in
task files, skeletons in the spec · pass is optional.

### Component Diagram

```
 accepted brainstorm/proposal ──┐
                                ▼
 /sdd-spec  §2 carry-forward ─► §3b design research ──► codex exec (gpt-5.6-luna, read-only,
            │                    │  neutral brief          --output-schema) ─► suggestions.json
            │                    ▼                                                  │
            │             triage CONFIRM/REJECT/ESCALATE ◄──────────────────────────┘
            │                    │
            ▼                    ▼
        §4 codebase contract  §2/§3/§7 (CONFIRM)  §8 (ESCALATE)  §9 table (all)
            │
            ▼
        §5 spec  ── §3 modules each with Interface Skeleton ── §6 commit spec + sdd/state/<FEAT-ID>/design_research/
                                │
                                ▼
 /sdd-task  §3 decomposition ─► per task: Codebase Contract (existing) + Implementation Blueprint (new)
                                │            steps · per-file code blocks · why · FILL IN checklist
                                ▼
 sdd-worker / Haiku: writes blocks to disk, completes FILL IN, runs tests   (no change)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/commands/sdd-spec.md` | modifies | Guardrail reword (:17); new §3b; §4/§5 skeleton rules; §6 also commits `sdd/state/<FEAT-ID>/design_research/`; §7 reports dispositions |
| `.claude/commands/sdd-task.md` | modifies | Guardrail reword (:14); §3 blueprint rules; §4 template use; §7 output line |
| `sdd/templates/spec.md` | modifies | Interface Skeleton sub-block in §3; new §9 |
| `sdd/templates/task.md` | modifies | New "Implementation Blueprint" section |
| `.agent/workflows/sdd-spec.md`, `.agent/workflows/sdd-task.md` | mirrors | Body must equal the `.claude/commands/` original (frontmatter + one policy line excepted) |
| `CLAUDE.md` §Adversarial Second Opinion (:124-175) | extends | Names design research as a second use of the codex seat; documents `SDD_DESIGN_RESEARCH_MODEL` |
| `codex` CLI 0.153.4 (`~/.local/bin/codex`) | uses | `exec --ephemeral --sandbox read-only -m -c --ignore-user-config --output-schema -o`, prompt via stdin `-` |
| `.claude/agents/code-reviewer.md` §Adversarial Cross-Check | reuses pattern | Five rules copied verbatim into §3b; file itself untouched |
| `.claude/agents/sdd-planner.md` | constraint | Runs `/sdd-spec` unattended; §3b must never gate or exit non-zero |
| `tests/sdd_scripts/` | adds tests | Twin parity + schema/template tests live here (existing home of SDD script tests) |

### Data Models

The only structured artifact is the Codex output, constrained by
`sdd/templates/design_research.schema.json` (Draft 2020-12; every property
required and `additionalProperties: false`, as OpenAI structured output
expects):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SDD design research suggestions",
  "type": "object",
  "required": ["summary", "suggestions"],
  "additionalProperties": false,
  "properties": {
    "summary": { "type": "string", "description": "≤3 sentences: how the reviewer read the brief" },
    "suggestions": {
      "type": "array", "maxItems": 12,
      "items": {
        "type": "object",
        "required": ["id", "kind", "title", "rationale", "affected_paths", "risk", "confidence"],
        "additionalProperties": false,
        "properties": {
          "id":             { "type": "string", "pattern": "^S[0-9]{1,2}$" },
          "kind":           { "enum": ["architecture", "api", "testing", "risk", "alternative"] },
          "title":          { "type": "string", "maxLength": 120 },
          "rationale":      { "type": "string" },
          "affected_paths": { "type": "array", "items": { "type": "string" }, "description": "repo-relative paths the reviewer actually read" },
          "risk":           { "enum": ["low", "medium", "high"] },
          "confidence":     { "enum": ["low", "medium", "high"] }
        }
      }
    }
  }
}
```

Triage is recorded next to it as `sdd/state/<FEAT-ID>/design_research/triage.md`
(the same table that lands in spec §9).

### New Public Interfaces

No Python. The new "interfaces" are document sections and one command phase.
Their exact text is the deliverable, so the skeletons below are what the tasks
write (bodies of prose are filled in by the task, structure is fixed here).

**`sdd/templates/task.md` — new section (insert after "## Implementation Notes", before "## Acceptance Criteria")**

````markdown
## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks were derived from the
> spec's Interface Skeletons and re-verified against the Codebase Contract above
> when this task was written. This is NOT the full implementation: business-logic
> branches, edge cases and test bodies are `FILL IN` stubs by design.

### Steps (in order)
1. <imperative step> — *why*: <one sentence>
2. <imperative step> — *why*: <one sentence>

### `parrot/path/to/new_file.py` (CREATE)
```python
"""<module docstring>."""
from __future__ import annotations

from parrot.module import ClassName  # verified: parrot/module/__init__.py:NN


class NewComponent(ClassName):
    """<one-line purpose>."""

    async def method(self, param: Type) -> ReturnType:
        """<what it returns and when it raises>."""
        self.logger.debug("method: %s", param)
        # FILL IN: <the exact decision left to you> — bounded by <constraint | AC-N>
        raise NotImplementedError
```
**Why this shape**: <2–4 sentences: which spec decision each block implements; what must NOT change>

### `parrot/path/to/existing.py` (MODIFY)
```python
# AFTER — insert below `<verbatim anchor line>` (verified: parrot/path/to/existing.py:NN)
<new lines>
```
**Why**: <1–2 sentences>

### FILL IN checklist
- [ ] `new_file.py::NewComponent.method` — <decision>; bounded by <constraint | AC-N>
````

**`sdd/templates/spec.md` — Interface Skeleton sub-block (inside every "### Module N" in §3)**

````markdown
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints)*:
  ```python
  # parrot/path/to/module.py  (new | modifies parrot/path/to/module.py:NN)
  class NewComponent(ExistingBase):  # ExistingBase verified: parrot/base.py:NN
      """<purpose>."""
      async def method(self, param: Type) -> ReturnType:
          """<contract>."""
  ```
````

**`sdd/templates/spec.md` — new section (after "## 8. Open Questions", before "## Revision History")**

````markdown
## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `<model>` · Status: completed | skipped (<reason>)
> · Transcript: `sdd/state/<FEAT-ID>/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | <title> (architecture) | CONFIRM | <why adopted> | §2 Overview |
| S2 | <title> (testing) | REJECT | <why not> | — |
| S3 | <title> (risk) | ESCALATE | <what the human must decide> | §8 Q<N> |

Summary: **<C>** confirmed · **<R>** rejected · **<E>** escalated.
````

**`.claude/commands/sdd-spec.md` — new step (after §2d, before §3)**

```markdown
### 3b. Collaborative Design Research (codex seat — optional, never blocking)

Runs only when §2 found an exploration doc with `status: accepted`. Skip
(recording the reason for §9) when: no exploration doc; `command -v codex`
fails; the model probe fails; the run exceeds 600 s; or the output does not
validate. NEVER abort /sdd-spec because of this step.

1. Detect + probe ...              (model = ${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna})
2. Render the neutral brief ...    (template sdd/templates/design_research.prompt.md; inputs listed; forbidden inputs listed)
3. Run codex in the background ... (exact command from §2 Overview; staging dir sdd/state/.design_research/<feature-name>/)
4. Validate + triage ...           (CONFIRM / REJECT / ESCALATE; verify every affected_path; unverifiable ⇒ REJECT)
5. Fold + record ...               (CONFIRM → §2/§3/§7 while drafting; ESCALATE → §8 `[ ]`; all → §9 table; triage.md)
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Task template — Implementation Blueprint section
- **Path**: `sdd/templates/task.md`
- **Responsibility**: Add the "## Implementation Blueprint" section (text in §2 New Public Interfaces) between "## Implementation Notes" (line 73) and "## Acceptance Criteria" (line 98). Extend "## Agent Instructions" step 5 to: "Implement — start from the Implementation Blueprint blocks, complete every `FILL IN`, never change a signature the blueprint fixes."
- **Depends on**: none
- **Interface Skeleton**: n/a (markdown section; exact structure fixed in §2)

### Module 2: `/sdd-task` command — blueprint rules
- **Path**: `.claude/commands/sdd-task.md` (+ mirror `.agent/workflows/sdd-task.md`)
- **Responsibility**:
  - Guardrail (line 14) → "Do NOT write the full implementation — but every task MUST carry an Implementation Blueprint (executor-ready per-file code blocks + why + `FILL IN` checklist). Blueprints stop at the mechanical parts."
  - §3 gains "**CRITICAL — Implementation Blueprint per Task (Executor Readiness)**" with the rules: one block per file in "Files to Create / Modify"; mechanical code complete (imports, signatures, docstrings, `self.logger` calls, registration/wiring); judgement calls as `# FILL IN: <decision> — bounded by <constraint | AC-N>`; every import copied from the task's Verified Imports; MODIFY blocks quote the verified anchor line; derive from the spec's Interface Skeletons and re-verify; no block over ~80 lines — split the task instead; the *Explain-for-executor rule*: every non-trivial decision is an imperative instruction plus its reason.
  - §4 step 4: "fill the Implementation Blueprint section for every task; a task without one is incomplete (same bar as the Codebase Contract)".
  - §7 output: add `Blueprints: <N>/<N> tasks` line.
- **Depends on**: Module 1

### Module 3: Spec template — Interface Skeletons + §9
- **Path**: `sdd/templates/spec.md`
- **Responsibility**: Add the Interface Skeleton sub-block to Module 1/Module 2 examples in §3 (lines 77-86); add "## 9. Design Research Cross-Check" (text in §2) between §8 (line 182-187) and "## Revision History" (line 191); add `design_research.prompt.md` / `.schema.json` to no other place (templates are self-contained).
- **Depends on**: none

### Module 4: Design-research templates
- **Path**: `sdd/templates/design_research.prompt.md`, `sdd/templates/design_research.schema.json`
- **Responsibility**:
  - `design_research.schema.json`: exactly the schema in §2 Data Models.
  - `design_research.prompt.md`: the neutral brief. Fixed header (role: independent design reviewer for an async-first Python agent framework; read-only; cite only paths you opened; propose ≤12 suggestions; output ONE JSON object per the schema, no prose) + placeholders `{{problem_statement}}`, `{{constraints_and_goals}}`, `{{recommended_option_or_scope}}`, `{{code_context_paths}}`, `{{open_questions}}`, `{{question}}` + the forbidden-inputs comment ("never paste the spec draft, Claude's reasoning, or a preferred conclusion"). Default `{{question}}`: "Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?"
- **Depends on**: none

### Module 5: `/sdd-spec` command — §3b phase + skeleton rules
- **Path**: `.claude/commands/sdd-spec.md` (+ mirror `.agent/workflows/sdd-spec.md`)
- **Responsibility**:
  - Guardrail (line 17) → "Do NOT write implementation bodies in the spec — but every §3 module MUST carry an Interface Skeleton (signatures, docstrings, `verified:` anchors). Bodies belong to task blueprints (/sdd-task)."
  - Insert **§3b** (structure in §2) after §2d (line ~205) and before §3 (line 207), with the five sub-steps fully written: detection/probe (`codex exec --ephemeral --sandbox read-only -m "$MODEL" -c model_reasoning_effort=high --ignore-user-config "Reply with exactly the single word OK."`), brief rendering (inputs/forbidden inputs), background run (exact command, `timeout 600`, staging dir `sdd/state/.design_research/<feature-name>/`), validation + triage (`python -c` with `jsonschema` against the schema; path verification; dispositions), fold + record (§2/§3/§7, §8, §9, `triage.md`). Copy the five Adversarial Cross-Check rules and the `agy` ban verbatim from `.claude/agents/code-reviewer.md:125-150`.
  - §4: item 6 "**Interface Skeletons**: for every §3 module write signatures + docstrings with `verified:` anchors; no bodies."
  - §6 commit: also `mkdir -p sdd/state/$FEAT_ID/design_research && mv sdd/state/.design_research/<feature-name>/* there` and `git add` that directory with the spec (only when the phase ran).
  - §7 output: add `Design research: <N> suggestions — <C> confirmed / <R> rejected / <E> escalated` or `Design research: skipped (<reason>)`.
  - Add `sdd/state/.design_research/` to `.gitignore` (staging only; committed copies live under `sdd/state/<FEAT-ID>/`).
- **Depends on**: Module 3, Module 4

### Module 6: Policy, twin parity test, schema/template tests
- **Path**: `CLAUDE.md`, `tests/sdd_scripts/test_command_twin_parity.py`, `tests/sdd_scripts/test_design_research_templates.py`
- **Responsibility**:
  - `CLAUDE.md` §Adversarial Second Opinion (124-175): add a "Design research (FEAT-545)" paragraph naming the second use of the codex seat, the `SDD_DESIGN_RESEARCH_MODEL` variable (default `gpt-5.6-luna`), the optional/non-blocking rule, and the §9 table.
  - `test_command_twin_parity.py`: for `sdd-spec` and `sdd-task`, strip a leading YAML frontmatter block from `.agent/workflows/<name>.md`, drop lines starting with `- Worktree policy:` from both, assert the remaining text is identical (pattern: `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py:44-66`).
  - `test_design_research_templates.py`: schema loads and is a valid Draft 2020-12 schema (`jsonschema.Draft202012Validator.check_schema`); a sample suggestion document validates; a sample with an unknown `kind` fails; `design_research.prompt.md` contains every `{{placeholder}}` listed in Module 4; `sdd/templates/task.md` contains `## Implementation Blueprint` and `### FILL IN checklist`; `sdd/templates/spec.md` contains `## 9. Design Research Cross-Check` and `Interface Skeleton`.
- **Depends on**: Modules 1–5
- **Interface Skeleton**:
  ```python
  # tests/sdd_scripts/test_command_twin_parity.py  (new)
  _REPO_ROOT = Path(__file__).resolve().parents[2]          # tests/sdd_scripts/ -> repo root
  _TWINNED = ("sdd-spec", "sdd-task")

  def _strip_frontmatter(text: str) -> str:
      """Drop a leading '---\\n...\\n---\\n' YAML block if present."""

  def _normalize(text: str) -> str:
      """Remove lines starting with '- Worktree policy:' (the one allowed delta)."""

  @pytest.mark.parametrize("name", _TWINNED)
  def test_command_twin_parity(name: str) -> None:
      """`.agent/workflows/<name>.md` body == `.claude/commands/<name>.md` body."""
  ```
  ```python
  # tests/sdd_scripts/test_design_research_templates.py  (new)
  def test_schema_is_valid_draft_2020_12() -> None: ...
  def test_sample_suggestions_validate() -> None: ...
  def test_unknown_kind_rejected() -> None: ...
  def test_prompt_has_all_placeholders() -> None: ...
  def test_task_template_has_blueprint_section() -> None: ...
  def test_spec_template_has_skeleton_and_section_9() -> None: ...
  ```

### Module 7: Acceptance dry run
- **Path**: `sdd/state/FEAT-545/design_research/` (artifact), `artifacts/logs/feat-545-dry-run.md` (evidence, untracked)
- **Responsibility**: Execute the new §3b end-to-end against this feature's own accepted proposal (`sdd/proposals/collaborative-adversarial-spec-design.proposal.md`): brief rendered, `codex exec` with `gpt-5.6-luna` returns a schema-valid `suggestions.json`, triage table produced, and the result committed under `sdd/state/FEAT-545/design_research/`. Then run the new `/sdd-task` rules on this spec and verify every generated task has a non-empty Implementation Blueprint. Record timings and disposition counts in the Completion Note. If codex is unavailable in the worktree, record `skipped (<reason>)` — that path is itself an acceptance criterion (AC-9).
- **Depends on**: Modules 1–6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_command_twin_parity[sdd-spec]` | 6 | `.agent/workflows/sdd-spec.md` body equals `.claude/commands/sdd-spec.md` after frontmatter strip + policy-line normalization |
| `test_command_twin_parity[sdd-task]` | 6 | same for `sdd-task` |
| `test_schema_is_valid_draft_2020_12` | 6 | `Draft202012Validator.check_schema` passes on `design_research.schema.json` |
| `test_sample_suggestions_validate` | 6 | a 2-suggestion sample validates |
| `test_unknown_kind_rejected` | 6 | `kind: "perf"` raises `ValidationError` |
| `test_prompt_has_all_placeholders` | 6 | six `{{…}}` placeholders present in `design_research.prompt.md` |
| `test_task_template_has_blueprint_section` | 6 | `## Implementation Blueprint`, `### Steps (in order)`, `### FILL IN checklist` present in `task.md` |
| `test_spec_template_has_skeleton_and_section_9` | 6 | `Interface Skeleton` and `## 9. Design Research Cross-Check` present in `spec.md` |

### Integration Tests

| Test | Description |
|---|---|
| Dry run (Module 7, manual, evidenced) | `/sdd-spec` §3b over this proposal produces a schema-valid `suggestions.json`, a `triage.md`, and a §9 table; `/sdd-task` over this spec yields tasks whose Implementation Blueprint sections are non-empty |
| Skip path (Module 7) | With `PATH` lacking `codex` (or `SDD_DESIGN_RESEARCH_MODEL=does-not-exist`), §3b records `skipped (<reason>)` and `/sdd-spec` completes normally |

### Test Data / Fixtures

```python
# tests/sdd_scripts/test_design_research_templates.py
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "sdd" / "templates" / "design_research.schema.json"


@pytest.fixture
def schema() -> dict:
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture
def sample_suggestions() -> dict:
    return {
        "summary": "Two suggestions on the accepted design.",
        "suggestions": [
            {"id": "S1", "kind": "architecture", "title": "Stage output under sdd/state",
             "rationale": "artifacts/ is gitignored.", "affected_paths": [".gitignore"],
             "risk": "low", "confidence": "high"},
            {"id": "S2", "kind": "testing", "title": "Add twin parity test",
             "rationale": "Twins drift silently.", "affected_paths": [".agent/workflows/sdd-spec.md"],
             "risk": "medium", "confidence": "medium"},
        ],
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1** `pytest tests/sdd_scripts/test_command_twin_parity.py tests/sdd_scripts/test_design_research_templates.py -v` passes (8 tests).
- [ ] **AC-2** `sdd/templates/task.md` contains the "## Implementation Blueprint" section with "### Steps (in order)", one CREATE and one MODIFY example block, "**Why this shape**", and "### FILL IN checklist", placed before "## Acceptance Criteria".
- [ ] **AC-3** `sdd/templates/spec.md` shows an "Interface Skeleton" sub-block in the §3 module examples and contains "## 9. Design Research Cross-Check" with the disposition table.
- [ ] **AC-4** `.claude/commands/sdd-task.md` line 14 no longer reads "tasks are plans, not code"; §3 contains the blueprint rules (one block per listed file, `# FILL IN:` bounded by constraint/AC, imports from Verified Imports, MODIFY anchor line, ~80-line cap, explain-for-executor rule); §7 output prints a `Blueprints:` line.
- [ ] **AC-5** `.claude/commands/sdd-spec.md` line 17 no longer forbids all implementation code; §3b exists between §2d and §3 with the five sub-steps, the exact `codex exec` command (`--ephemeral --sandbox read-only -m "$MODEL" -c model_reasoning_effort=high --ignore-user-config --output-schema … -o … -`), `timeout 600`, and the skip rules; §6 commits `sdd/state/<FEAT-ID>/design_research/` with the spec; §7 prints the `Design research:` line.
- [ ] **AC-6** `sdd/templates/design_research.schema.json` equals the §2 Data Models schema (all properties required, `additionalProperties: false`, `kind` enum of five values, `maxItems: 12`); `sdd/templates/design_research.prompt.md` contains the six placeholders and the forbidden-inputs comment.
- [ ] **AC-7** `.agent/workflows/sdd-spec.md` and `.agent/workflows/sdd-task.md` mirror their `.claude/commands/` originals (AC-1's parity tests are the check).
- [ ] **AC-8** `CLAUDE.md` §Adversarial Second Opinion documents design research, `SDD_DESIGN_RESEARCH_MODEL` (default `gpt-5.6-luna`), and the optional rule; the `agy` ban is untouched.
- [ ] **AC-9** Skip path verified: running §3b with `SDD_DESIGN_RESEARCH_MODEL=does-not-exist` (or `codex` off `PATH`) yields a §9 block reading `Status: skipped (<reason>)` and `/sdd-spec` completes with exit 0.
- [ ] **AC-10** Dry run committed: `sdd/state/FEAT-545/design_research/{brief.md,suggestions.json,triage.md,codex.log}` exist, `suggestions.json` validates against the schema, and this spec's §9 is filled from `triage.md`.
- [ ] **AC-11** `sdd/state/.design_research/` is gitignored; no file under it is tracked.
- [ ] **AC-12** No file under `packages/ai-parrot/src/parrot/flows/dev_loop/` is modified (non-goal), and `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` still passes.
- [ ] **AC-13** No breaking change for existing specs/tasks: files written with the old templates still parse for `/sdd-status`, `/sdd-next`, `/sdd-done` (the new sections are additive; no existing heading renamed).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All anchors re-verified on `dev` at `30972ef75` (2026-09-10).

### Verified Imports
```python
from jsonschema import Draft202012Validator, ValidationError  # verified: jsonschema 4.26.0 installed; packages/ai-parrot/pyproject.toml:80 "jsonschema>=4.20"
from importlib import resources                              # stdlib — used by the parity-test precedent
from pathlib import Path                                     # stdlib
import pytest                                                # test dependency, used throughout tests/sdd_scripts/
```

### Existing File Anchors (markdown targets — line numbers are edit anchors)
```text
# .claude/commands/sdd-spec.md  (431 lines)
:15-31   ## Guardrails            — line 17: "- Do NOT write implementation code in the spec — specs are design documents."
:39      ### 2. Check for Prior Exploration
:121-133 #### 2c. carry-forward summary ("If K is zero, proceed directly to §4")
:135-205 #### 2d. Sync the Base Branch  → §3b is inserted AFTER this block
:207     ### 3. Ask Clarifying Questions
:230-252 ### 4. Research the Codebase & Build Codebase Contract (items 1-5; add item 6 Interface Skeletons)
:254-345 ### 5. Scaffold the Spec
:353-377 ### 6. Commit the Spec  (git reset HEAD / git add sdd/specs/<name>.spec.md / git diff --cached --name-only / git commit)
:379-416 ### 7. Output
:424-431 ## Anti-Hallucination Policy

# .claude/commands/sdd-task.md  (292 lines)
:10-15   ## Guardrails            — line 14: "- Do NOT write implementation code — tasks are plans, not code."
:84-88   ### 3. Plan Task Decomposition
:96-112  CRITICAL — Codebase Contract per Task  — line 111: "The implementing agent (often Sonnet or Haiku) WILL hallucinate ..."
:114-159 ### 4. Generate Tasks (step 2 reads sdd/templates/task.md; step 4 creates sdd/tasks/active/<id>-<slug>.md)
:271-287 ### 7. Output

# sdd/templates/spec.md  (195 lines)
:72-86   ## 3. Module Breakdown  (### Module 1 :77-81, ### Module 2 :83-86 — Path / Responsibility / Depends on)
:125-158 ## 6. Codebase Contract
:162-179 ## 7. Implementation Notes & Constraints
:182-187 ## 8. Open Questions
:191-195 ## Revision History   → §9 is inserted BEFORE this heading

# sdd/templates/task.md  (175 lines)
:43-70   ## Codebase Contract (Anti-Hallucination)
:73-94   ## Implementation Notes  (### Pattern to Follow :77-84, ### Key Constraints :86-90, ### References in Codebase :92-94)
:98-104  ## Acceptance Criteria    → Implementation Blueprint is inserted BEFORE this heading
:108-143 ## Test Specification
:147-163 ## Agent Instructions  (step 5 "**Implement** following the scope, codebase contract, and notes above" :159)

# .agent/workflows/sdd-spec.md (434 lines) / .agent/workflows/sdd-task.md (296 lines)
:1-4     YAML frontmatter `description:` (twin-only)
:426     "- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`"  (original: "- Worktree policy: `CLAUDE.md` (section \"Worktree Policy\")")
         → the ONLY allowed deltas; every other line must match the .claude/commands original

# CLAUDE.md
:124     ### Adversarial Second Opinion
:130     > **`agy` (Google Gemini / Antigravity) MUST NOT be used as a reviewer.**
:144     - Never feed the reviewer your reasoning, justification, or preferred conclusion.
:168-180 #### codex commands  (:175 "codex exec --sandbox read-only -o <scratch-file> \"<neutral brief>\"")

# .claude/agents/code-reviewer.md
:119-194 ## Adversarial Cross-Check  (:134-150 Key Rules — copy verbatim; :125-132 agy ban; :185-194 report table format)

# .claude/agents/sdd-secondopinion.md
:35-41   neutral brief = exactly three things (diff, criteria, question); never the primary's reasoning
:73-76   one JSON object conforming to the dispatcher-supplied schema

# .claude/agents/sdd-planner.md
:45-53   runs /sdd-spec then /sdd-task unattended; :93-99 any non-zero step aborts planning

# .claude/agents/sdd-worker.md
:211-233 Execution Loop a) read full task file → b) verify Codebase Contract → c) implement EXACTLY as specified

# .gitignore
:283     artifacts/      (artifacts are untracked — reason design_research output goes under sdd/state/)

# packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py
:44-66   test_prompt_parity — byte-equality pattern to mirror for command twins

# sdd/specs/formdesigner-field-uid.spec.md
:853     "## 9. Implementation Blueprints (per module)" — prior art for blueprint naming/tone (before/after code, "adapt mechanically, MUST NOT redesign")
```

### Codex CLI Contract (verified on this machine)
```text
codex --version                → codex-cli 0.153.4   (~/.local/bin/codex)
codex exec [OPTIONS] [PROMPT]  → PROMPT positional, or `-` = read from stdin
  -m, --model <MODEL>          -c, --config <key=value>   (e.g. -c model_reasoning_effort=high)
  -s, --sandbox <MODE>         --ephemeral                --ignore-user-config
  --output-schema <FILE>       -o, --output-last-message <FILE>     --json
Probe (2026-09-10): codex exec --ephemeral --sandbox read-only -m gpt-5.6-luna -c model_reasoning_effort=high \
  --ignore-user-config -o <file> "Reply with exactly the single word OK."  → exit 0, file contains "OK"  (proposal F017)
Dev-loop precedent for flag order: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:240-282 (_build_command)
  and :298-343 (_build_adversarial_review_command: --cd/--sandbox/--model precede subcommands; resume ignores --sandbox)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `/sdd-spec` §3b | `codex exec` | bash, stdin brief, `--output-schema` | `codex exec --help`; F017 probe |
| `/sdd-spec` §3b output | spec §9 + `sdd/state/<FEAT-ID>/design_research/` | §6 commit step | `.claude/commands/sdd-spec.md:353-377` |
| `/sdd-task` §3 blueprint rules | `sdd/templates/task.md` new section | §4 step 2 "Read the task template" | `.claude/commands/sdd-task.md:116` |
| Task blueprints | `sdd-worker` | reads full task file, implements as specified | `.claude/agents/sdd-worker.md:211-233` |
| Twin parity test | `.agent/workflows/*.md` | `Path` reads from repo root | `tests/sdd_scripts/` (existing dir) |

### Does NOT Exist (Anti-Hallucination)
- ~~`sdd/templates/design_research.prompt.md`~~, ~~`sdd/templates/design_research.schema.json`~~ — created by Module 4
- ~~`SDD_DESIGN_RESEARCH_MODEL`~~ — no such variable anywhere yet (bash `${VAR:-default}` in the command; NOT a `conf.py` key)
- ~~`sdd/state/.design_research/`~~ — staging dir created by §3b; not in `.gitignore` yet
- ~~`## Implementation Blueprint`~~ in `sdd/templates/task.md`, ~~`Interface Skeleton`~~ and ~~`## 9. Design Research Cross-Check`~~ in `sdd/templates/spec.md` — all new
- ~~`### 3b.`~~ in `.claude/commands/sdd-spec.md` — new
- ~~`tests/sdd_scripts/test_command_twin_parity.py`~~, ~~`tests/sdd_scripts/test_design_research_templates.py`~~ — new
- ~~`CodexDesignResearchDispatcher`~~, ~~`CodexDesignResearchProfile`~~, ~~`conf.SDD_DESIGN_RESEARCH_MODEL`~~ — do NOT create; the dev-loop is out of scope
- ~~`codex exec design`~~, ~~`codex exec --reasoning`~~ — no such subcommand/flag; reasoning is `-c model_reasoning_effort=high`
- ~~`codex exec review`~~ for this phase — that subcommand reviews a diff; design research uses plain `codex exec` with a stdin brief
- ~~`scripts/sdd/design_research.py`~~ — no Python helper; the phase is bash inside the command (a `python -c` one-liner with `jsonschema` is allowed for validation)
- ~~`artifacts/reviews/…`~~ as the output location — gitignored (`.gitignore:283`); use `sdd/state/`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Neutral brief** (`.claude/agents/sdd-secondopinion.md:35-41`): artifact + requirements + question. The brief carries the exploration doc; it never carries the spec draft, Claude's reasoning, or a preferred conclusion.
- **Five cross-check rules** (`.claude/agents/code-reviewer.md:134-150`): copy verbatim into §3b — neutral brief; background session; advisory + CONFIRM/REJECT/ESCALATE; never silently concede or drop; verify the reviewer's evidence.
- **Anchored code** (`sdd/templates/spec.md:125-158`): every skeleton and blueprint line that references existing code carries `# verified: path:NN`.
- **Prior art for tone**: `sdd/specs/formdesigner-field-uid.spec.md:853-860` — "Agents adapt mechanically (imports, docstrings) but MUST NOT redesign."
- **Commit discipline** (`.claude/commands/sdd-spec.md:363-377`): `git reset HEAD`, stage explicit paths only, verify with `git diff --cached --name-only`.
- **Twin edits**: change `.claude/commands/<name>.md`, then copy the body over `.agent/workflows/<name>.md` keeping its 4-line frontmatter and its `AGENTS.md` policy line; run AC-1.

### Known Risks / Gotchas
- **Ratification.** If the brief leaks the draft, Codex agrees with it. Mitigation: §3b runs before §4/§5; the prompt template's forbidden-inputs comment; the brief is rendered from the exploration doc only.
- **Hallucinated paths from Codex.** Mitigation: every `affected_paths` entry is checked with `test -e` / grep before a CONFIRM; unverifiable ⇒ REJECT "path not found". Same rule as the code-review policy.
- **Unattended planner.** Any failure in §3b must degrade to `skipped (<reason>)` with exit 0. Never `set -e` the codex call; capture `$?` explicitly.
- **FEAT-ID unknown at §3b time.** Ids are reserved in §5, after research. Hence the id-independent staging dir `sdd/state/.design_research/<feature-name>/`, moved in §6. Add the staging dir to `.gitignore` (AC-11).
- **`--ephemeral` + `-o` + stdin + `--output-schema` together** were only partially exercised (F017 used `--ephemeral`/`-o` with a positional prompt). Module 7's dry run is the verification; if stdin `-` misbehaves, fall back to passing the brief as the positional argument (`"$(cat "$DR/brief.md")"`).
- **Model catalog drift.** `gpt-5.6-luna` is verified today; the probe step catches future removals and turns them into a skip, not a failure.
- **Blueprint staleness / bloat.** Blueprints are written at task time (last step before the worktree exists), carry anchors, cap at ~80 lines per block, and `sdd-worker` still re-verifies the contract. Judgement calls stay `FILL IN`.
- **Concurrent dev writers.** Other sessions commit to `dev` concurrently (observed during this spec: ledger reservations landed mid-run). Commit only explicit paths; reconcile with plain merge, never rebase.
- **Line anchors shift.** Every `:NN` in §6 is for `dev@30972ef75`; tasks must re-grep the heading text, not trust the number.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `codex` CLI (OpenAI) | 0.153.4 on this machine | design-research seat; optional at runtime |
| `jsonschema` | `>=4.20` (4.26.0 installed) | validate `suggestions.json` in §3b and in tests; already a project dependency |
| `timeout` (coreutils) | any | 600 s cap on the codex call |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] **Which Codex model/reasoning, and where configured?** — *Resolved in proposal (U1)*: `gpt-5.6-luna`, confirmed against the installed CLI (probe F017); `SDD_DESIGN_RESEARCH_MODEL` env var with that default, passed as `-m` plus `-c model_reasoning_effort=high`, never relying on `~/.codex/config.toml`.
- [x] **How do Codex suggestions enter the spec?** — *Resolved in proposal (U2)*: explicit CONFIRM / REJECT / ESCALATE table in §9; CONFIRMed items folded into §2/§3/§7; raw transcript under `sdd/state/<FEAT-ID>/design_research/`.
- [x] **How much code is "usable code + explanations"?** — *Resolved in proposal (U3)*: not the full implementation; Implementation Blueprints in each TASK file (per-file code Haiku can write nearly verbatim + why + `FILL IN` list); interface skeletons only in the spec.
- [x] **Mandatory or optional pass?** — *Resolved in proposal (U4)*: optional; skip with a recorded reason when codex is absent/fails/times out.
- [x] **Codex at spec time only, or also at task time?** — *Resolved by acceptance of proposal §6 assumption*: spec time only over the accepted exploration doc; a task-time pass is a possible follow-up spec, not part of FEAT-545.
- [ ] **Should the ~80-line blueprint-block cap be enforced by a lint (`scripts/sdd/lint_new.py`-style) or stay a written rule?** — *Owner: Jesus Lara* — decide during Module 2; default: written rule only.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: **pending — this
> section is filled by Module 7's dry run, the first execution of the phase this
> spec introduces** · Transcript: `sdd/state/FEAT-545/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | *(filled by Module 7)* | | | |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree (`feat-FEAT-545-collaborative-adversarial-spec-design`).
- **Ordering**: M1 → M2 (task template before task command), M3 → M4 → M5
  (spec template + design-research templates before the spec command), M6
  (policy + tests) after M1–M5, M7 (dry run) last. M1/M2 and M3/M4/M5 touch
  disjoint files and *could* run in parallel worktrees, but the whole feature is
  ~7 small markdown/test tasks; the merge overhead is not worth it.
- **Cross-feature dependencies**: none. Note that `.claude/commands/sdd-spec.md`
  and `sdd-task.md` are edited by other features occasionally (FEAT-387,
  FEAT-466 history) — rebase-free plain merge on `/sdd-done`.
- **Runtime dependency**: Module 7 needs the `codex` binary and network access
  inside the worktree; if unavailable, the skip path (AC-9) is exercised and
  AC-10 is recorded as blocked in the Completion Note.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-10 | Jesus Lara (with Claude Fable 5.1) | Initial draft from accepted proposal FEAT-545 (ex-provisional FEAT-564); all four proposal unknowns carried as resolved |
