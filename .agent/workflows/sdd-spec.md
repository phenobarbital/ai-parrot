---
description: Scaffold a Feature Specification using SDD methodology
---

# /sdd-spec — Scaffold a Feature Specification

Create a new Feature Specification for AI-Parrot using the Spec-Driven Development methodology.
The spec becomes the Single Source of Truth (SSOT) for a feature — all requirements changes go here first.

## Guardrails
- Do NOT start implementation — this workflow only produces a specification document.
- Do NOT modify existing specs without explicit user approval.
- Always use the official template at `sdd/templates/spec.md`.

## Steps

### 1. Parse Input
Extract from the user's invocation:
- **feature-name**: first token (slug-friendly, kebab-case). If not provided, ask.
- **free-form notes**: anything after `--`, used as initial Problem Statement.

### 2. Check for Existing Brainstorm / Proposal
Look for prior exploration documents in `sdd/proposals/`:
- `<feature-name>.brainstorm.md` — structured exploration with options and recommendation.
- `<feature-name>.proposal.md` — discussion-based proposal.

If found, **pre-fill the spec** using the mapping:
- Problem Statement → Section 1 (Motivation)
- Constraints → Section 5 (Acceptance Criteria)
- Recommended Option → Section 2 (Architectural Design)
- Libraries / Tools → Section 6 (External Dependencies)
- Feature Description → Section 2 (Overview + Integration Points)
- Capabilities → Section 3 (Module Breakdown)
- Impact & Integration → Section 2 (Integration Points)
- Code Context → Section 6 (Codebase Contract) — **carries forward verified code**
- Open Questions → Section 8

Skip clarifying questions that are already answered by the brainstorm/proposal.

### 3. Ask Clarifying Questions
Ask the user for any **remaining gaps** (you may ask all at once):
- **Motivation**: What problem does this feature solve? Why now?
- **Key components**: What are the main modules/classes involved?
- **Integration points**: Which existing AI-Parrot components does this touch?
- **Acceptance criteria**: How do we know it's done?
- **Non-goals**: What is explicitly out of scope?

Use the user's answers plus any free-form notes to fill in the spec.

### 4. Assign Feature ID
- Read existing specs in `sdd/specs/` directory.
- Find the highest existing `FEAT-NNN` number and increment by 1.
- If no specs exist, start at `FEAT-001`.

### 5. Research the Codebase & Build Codebase Contract
Before writing the spec:
- Read existing specs in `sdd/specs/` directory.
- Identify related existing components (AbstractClient, AgentCrew, BaseLoader, etc.).
- Note what can be reused vs. what must be created.

**CRITICAL — Codebase Contract Construction:**
This step prevents AI hallucinations during implementation. You MUST:

1. **If a brainstorm exists**: carry forward its entire `## Code Context` section
   into the spec's `## 6. Codebase Contract` section. Re-verify each reference.
2. **For every class/module referenced**: `read` the actual source file and record
   exact class signatures, method signatures, and key attributes with file paths
   and line numbers.
3. **Verify all imports**: confirm that `from parrot.X import Y` resolves by
   checking `__init__.py` exports and module structure.
4. **Record what does NOT exist**: add plausible-sounding things that don't exist
   to the "Does NOT Exist" subsection.

### 6. Generate the Spec
1. Read the template at `sdd/templates/spec.md`.
2. Create `sdd/specs/<feature-name>.spec.md` filled in with:
   - The assigned Feature ID and today's date.
   - User's answers mapped to the template sections.
   - Suggested architectural patterns from the AI-Parrot codebase (e.g., `AbstractClient`, `AgentCrew`, `BaseLoader`).
   - **Codebase Contract** (Section 6) — verified imports, signatures, and anti-hallucination entries.
   - Module breakdown (Section 3) — these will map to tasks in `/sdd-task`.
3. Set `Status: draft`.

### 6. Output and Next Steps
Print:
```
✅ Spec created: sdd/specs/<feature-name>.spec.md
   Feature ID: FEAT-<NNN>

Next steps:
  1. Review and refine the spec
  2. Mark status: approved when ready
  3. Run /sdd-task sdd/specs/<feature-name>.spec.md
```

Remind the user:
- The spec is the SSOT — changes to requirements go here first.
- Mark `status: approved` before generating tasks.

## Reference
- Template: `sdd/templates/spec.md`
- Existing specs: `sdd/specs/`
- SDD methodology: `sdd/WORKFLOW.md`
