# TASK-2124: `sdd-ideation` subagent definition (dual-mode) + loader

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2121
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. The ideation phase is executed by a dispatched subagent
(same mechanism as `sdd-planner`). ONE definition with a `mode` field in the
dispatch payload — `"brainstorm"` (intent `new_feature`) writes a full
`.brainstorm.md` with options analysis; `"proposal"` (intent `enhancement`)
writes a light `.proposal.md` (scope, rationale, impact — no options
analysis). Resolved decisions (spec §8): resume/extend an existing target
document, never overwrite or suffix.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md`:
  system prompt instructing the subagent to
  1. consume the NL request (title/description/context), optional wiki
     context, and prior-round `answers`;
  2. write/update `sdd/proposals/<slug>.{brainstorm|proposal}.md` per
     `mode`, with FEAT-145 frontmatter (`type: feature`,
     `base_branch: dev`) and the Open-Questions convention
     `- [ ] question — *Owner: ...*` / `- [x] question — *Resolved*: <answer>`;
  3. if the target file already exists: read it, RESUME/EXTEND in place
     (`resumed_existing=true`); if its Problem Statement clearly does not
     match the request, do NOT extend — surface the mismatch as an open
     question instead;
  4. commit the document to the base branch staging ONLY that path (never
     `git add -A`);
  5. emit ONE final JSON object matching `IdeationOutput` — no prose, no
     markdown fences.
- Mirror the definition in `.claude/agents/sdd-ideation.md` (frontmatter
  format of the existing `.claude/agents/*.md`).
- Create `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py`
  with `load_subagent_definition(name)` for the dev_flow package (same
  contract as `dev_loop/_subagent_defs.py:86` — reads from the package's
  own `_subagent_data/`).
- Unit test: loader returns the body; prompt contains the `IdeationOutput`
  field names and both mode markers.

**NOT in scope**: the `IdeationNode` that dispatches it (TASK-2126), models
(TASK-2121).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` | CREATE | Dual-mode system prompt |
| `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py` | CREATE | Loader (dev_loop:86 contract) |
| `.claude/agents/sdd-ideation.md` | CREATE | Mirror for interactive use |
| `packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py` | CREATE | Loader + prompt-content tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py:86
def load_subagent_definition(name: str) -> str:
    """Return the system-prompt body of an SDD subagent. ..."""
# Reads markdown bodies from dev_loop/_subagent_data/; strip frontmatter.
# Existing definitions to use as FORMAT REFERENCE (verified 2026-08-05):
#   dev_loop/_subagent_data/sdd-planner.md   (4.2K — JSON-contract style)
#   dev_loop/_subagent_data/sdd-feedback.md  (3.4K — advisory JSON emitter)
```

```python
# IdeationOutput (created by TASK-2121 — parrot/flows/dev_flow/models.py)
class IdeationOutput(BaseModel):
    document_path: str
    document_kind: Literal["brainstorm", "proposal"]
    slug: str
    resumed_existing: bool = False
    open_questions: List[str] = []
    summary: str = ""
    committed: bool = False
```

### Does NOT Exist
- ~~`sdd-ideation` / `sdd-brainstorm` in any `_subagent_data/`~~ — today the
  dev_loop set is exactly: sdd-autopilot, sdd-codereview, sdd-feedback,
  sdd-planner, sdd-qa, sdd-research, sdd-secondopinion, sdd-worker.
- ~~`dev_flow/_subagent_defs.py`~~ — this task creates it; do NOT extend
  the dev_loop loader's name Literal instead (the dev_flow package owns its
  own prompts, spec §3 Module 3).
- ~~TWO prompt files (one per mode)~~ — explicitly one dual-mode definition
  (spec §8 resolution).

---

## Implementation Notes

### Key Constraints
- The prompt must mandate: final message is EXACTLY one JSON object
  (`IdeationOutput` shape) — mirror sdd-planner/sdd-feedback wording.
- Open-Questions convention must match what `/sdd-spec` §2b parses
  (`- [x] <q> — *Resolved*: <answer>` / `- [ ] <q> — *Owner: ...*`).
- Commit message convention: `sdd: <action> for <feature-name>`.
- The `.claude/agents/` mirror carries the standard agent frontmatter
  (name, description, tools) — copy the structure from an existing
  `.claude/agents/sdd-*.md`.

### References in Codebase
- `dev_loop/_subagent_data/sdd-planner.md` — closest analog (generates SDD
  artifacts + emits JSON)
- `dev_loop/_subagent_defs.py` — loader implementation to mirror

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_flow._subagent_defs import load_subagent_definition` works and returns the sdd-ideation body
- [ ] Prompt covers both modes, resume/extend policy, FEAT-145 frontmatter, Open-Questions convention, explicit-path commit, JSON-only output
- [ ] `.claude/agents/sdd-ideation.md` mirror exists with valid frontmatter
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py
def test_loader_returns_ideation_body(): ...
def test_loader_unknown_name_raises(): ...
def test_prompt_mentions_both_modes_and_output_fields(): ...
def test_prompt_mandates_resume_extend_policy(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2121 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

Created the dual-mode `sdd-ideation` definition (320 lines), the dev_flow
loader, and the byte-identical `.claude/agents/` mirror.

**Prompt structure** — input table (`mode`, `title`, `description`,
`context`, `graph_context`, `answers`, `document_path`, `round`) → 4 steps
(slug/path resolution → existing-document policy → write → commit) →
cardinal rules → output contract → failure handling. Both mode formats are
spelled out as literal section skeletons so the two outputs stay uniform for
`/sdd-spec` and `PlannerNode`:

- `mode="brainstorm"` — Problem Statement, Constraints, **Options Explored
  (A/B/C) + Recommendation**, Feature Description, Impact, Code Context,
  Open Questions.
- `mode="proposal"` — Origin, Scope (What Changes / What's New / Non-Goals),
  Rationale, Impact, Code Context, Open Questions. Explicitly disclaims the
  deep `/sdd-proposal` artifact ("no confidence maps, no hypothesis blocks,
  no research audit") per spec §1 Non-Goals.

**Three-way existing-document policy** (spec §8 + §7 Known Risks): absent →
create; exists and matches → `Edit` in place with `resumed_existing=true`;
exists but the Problem Statement is about something else → **touch nothing**,
return ONE open question naming the collision, `committed=false`. Overwriting
and `-2`-suffixed copies are called out as "absolutely forbidden" — the human
resolves slug collisions.

**Open-Questions convention verified against the real parser**, not just the
task text. `/sdd-spec` §2b (`.claude/commands/sdd-spec.md:70-90`) documents
`- [x] q — *Owner: name*: <answer>` and defines the answer as *"the text
after the final `:` on the same line"*. The spec's mandated
`- [x] q — *Resolved*: <answer>` satisfies that same rule, so the two are
compatible; I used the spec's form and made the "answer follows the final
`:`" rule explicit in the prompt. The prompt also requires **folding a
resolved answer into the document body**, not just flipping the checkbox
(mirrors §2b rule 2), and forbids deleting or rephrasing unanswered
questions.

**`open_questions` strings must match the document text exactly** — the
prompt states this, because the flow uses them as dictionary keys when
collecting the human's `answers`.

17 tests. The content assertions are behavioral (each guards an instruction
whose loss would break the flow) rather than cosmetic, plus loader-contract
tests, `_strip_frontmatter` edge cases (including the malformed-frontmatter
no-truncation path), and a byte-parity test against the `.claude/agents/`
twin modelled on `dev_loop`'s `test_subagent_parity.py`.

Full `dev_flow` suite: 31 passed. `ruff`: 0 findings on both new files.

**Deviations from spec**: one, forced and additive.

- **`packages/ai-parrot/pyproject.toml` modified** (not in this task's file
  table): added
  `"parrot.flows.dev_flow" = ["_subagent_data/*.md"]` to
  `[tool.setuptools.package-data]`, mirroring the existing
  `parrot.flows.dev_loop` entry. Without it the prompt is **not shipped in
  the wheel**, and since `load_subagent_definition` reads it through
  `importlib.resources` (deliberately, so dispatch works outside a repo
  checkout), the loader would raise `FileNotFoundError` for every installed
  deployment — i.e. this task's first acceptance criterion would hold only in
  a source checkout. One line + comment; no other packaging metadata touched.

Note for reviewers: `.claude/` is gitignored, so the mirror was added with
`git add -f`, the same grandfathered-path pattern CLAUDE.md documents for
`sdd/templates/*.md`. The other 10 files under `.claude/agents/` are tracked
the same way.
