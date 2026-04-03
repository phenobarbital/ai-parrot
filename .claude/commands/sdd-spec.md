# /sdd-spec — Scaffold a Feature Specification

Scaffold a new Feature Specification for AI-Parrot using the SDD methodology.

## Usage
```
/sdd-spec <feature-name> [-- free-form description and notes]
```

## Guardrails
- Always use the official template at `sdd/templates/spec.md`.
- Do NOT write implementation code in the spec — specs are design documents.
- Feature IDs must be unique. Check existing specs before assigning.
- If a `.brainstorm.md` exists for this feature in `sdd/proposals/`, use it as input.
- **Always commit the spec file to the current branch** so worktrees can see it.

## Steps

### 1. Parse Input
- **feature-name**: slug-friendly kebab-case. If not provided, ask.
- **free-form notes**: anything after `--`, used as Problem Statement seed.

### 2. Check for Prior Exploration
Look for prior exploration documents in `sdd/proposals/`:
- `.brainstorm.md` → structured options analysis, use Recommended Option.
- `.proposal.md` → discussion output, use Motivation + Scope sections.

If found, pre-fill the spec from that document. Minimise questions to the user.

### 3. Research the Codebase & Build Codebase Contract
Before writing the spec:
- Read existing specs in `sdd/specs/` directory.
- Identify related existing components (AbstractClient, AgentCrew, BaseLoader, etc.).
- Note what can be reused vs. what must be created.

**CRITICAL — Codebase Contract Construction:**
This step prevents AI hallucinations during implementation. You MUST:

1. **If a brainstorm exists**: carry forward its entire `## Code Context` section
   into the spec's `## 6. Codebase Contract` section. Re-verify each reference
   is still accurate (code may have changed since brainstorm).
2. **For every class/module referenced in the spec**: `read` the actual source file
   and record exact class signatures, method signatures (with parameter types and
   return types), and key attributes — with file paths and line numbers.
3. **Verify all imports**: confirm that `from parrot.X import Y` resolves by
   checking `__init__.py` exports and module structure. Do not assume.
4. **Record what does NOT exist**: if you searched for a plausible module, class,
   or method and it does not exist, add it to the "Does NOT Exist" subsection.
   This is the most effective anti-hallucination measure — it explicitly tells
   implementing agents what NOT to reference.
5. **Include user-provided code**: if the user or brainstorm provided code snippets,
   preserve them as verified references in the contract.

### 4. Scaffold the Spec
1. Read the template at `sdd/templates/spec.md`.
2. Create `sdd/specs/<feature-name>.spec.md` filled in with:
   - Feature ID (check existing; increment last; start at FEAT-001 if none).
   - Today's date.
   - Answers from user (or prior exploration documents).
   - Architectural patterns from your codebase research.

**Worktree hint (new section in spec):**
Include a `## Worktree Strategy` section in the spec with:
- Default isolation unit: `per-spec` or `per-task`.
- If `per-spec`: all tasks run sequentially in one worktree.
- If mixed: list which tasks are parallelizable and why.
- Cross-feature dependencies: list any specs that must be merged first.

### 5. Commit the Spec

> **CRITICAL — Worktrees branch from the current state of the repo.**
> If the spec is not committed, any worktree created later will NOT see it,
> and the `sdd-worker` agent will fail with "no spec found".

```bash
git add sdd/specs/<feature-name>.spec.md
git commit -m "sdd: add spec for FEAT-<ID> — <feature-name>"
```

### 6. Output
```
✅ Spec created and committed: sdd/specs/<feature-name>.spec.md

   Feature ID: FEAT-<ID>
   Isolation: per-spec (sequential tasks) | mixed (some parallel tasks)

   To create a worktree for this feature after task decomposition:
     git worktree add -b feat-<FEAT-ID>-<feature-name> \
       .claude/worktrees/feat-<FEAT-ID>-<feature-name> HEAD

Next:
  1. Review the spec — check Acceptance Criteria and Architectural Design.
  2. Mark status: approved when ready.
  3. Run /sdd-task sdd/specs/<feature-name>.spec.md
```

## Reference
- Template: `sdd/templates/spec.md`
- Existing specs: `sdd/specs/`
- SDD methodology: `sdd/WORKFLOW.md`
- Worktree policy: `CLAUDE.md` (section "Worktree Policy")

## Anti-Hallucination Policy

The `## 6. Codebase Contract` section in the spec is **mandatory** for any spec
that references existing codebase components. A spec without a codebase contract
will produce tasks that hallucinate imports and attributes.

**Quality bar**: Every entry in the contract must include a file path and line number.
Entries without verification evidence must be marked as `(unverified — check before use)`.