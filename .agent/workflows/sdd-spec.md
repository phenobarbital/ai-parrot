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
- **NEVER re-ask a question that the brainstorm already answered.** Resolved
  answers must be carried forward verbatim. See §2 for the resolved-question
  convention and §3 for what you MAY ask.

## Steps

### 1. Parse Input
Extract from the user's invocation:
- **feature-name**: first token (slug-friendly, kebab-case). If not provided, ask.
- **free-form notes**: anything after `--`, used as initial Problem Statement.

### 2. Check for Existing Brainstorm / Proposal (and carry it forward)
Look for prior exploration documents in `sdd/proposals/`:
- `<feature-name>.brainstorm.md` — structured exploration with options and recommendation.
- `<feature-name>.proposal.md` — discussion-based proposal.

If neither exists, proceed to §3.

**If a brainstorm exists, treat it as the authoritative input.** Do the
following in order before writing anything or asking the user anything:

#### 2a. Map brainstorm sections into the spec

| Brainstorm section | Spec target |
|---|---|
| Problem Statement | §1 Motivation — Problem Statement |
| Constraints & Requirements | §1 Goals + §5 Acceptance Criteria (every hard constraint becomes a checkable criterion) |
| Recommendation + Recommended Option body | §2 Architectural Design — Overview |
| Feature Description → User-Facing Behavior | §2 Overview |
| Feature Description → Internal Behavior | §2 Component Diagram + Integration Points |
| Feature Description → Edge Cases & Error Handling | §7 Known Risks / Gotchas |
| Capabilities (New + Modified) | §3 Module Breakdown |
| Impact & Integration table | §2 Integration Points |
| Code Context (entire section) | §6 Codebase Contract (re-verify every reference) |
| Libraries / Tools table | §7 External Dependencies |
| Parallelism Assessment | Worktree Strategy section |
| Open Questions (see 2b) | §8 Open Questions (preserve resolved/unresolved state) |

Rejected options are NOT carried into the spec body. They may be referenced
in one line in §1 Non-Goals if a reader might otherwise expect them.

#### 2b. Parse Open Questions — resolved vs. unresolved

The brainstorm's Open Questions use this convention:

```
- [ ] Unresolved question — *Owner: name*
- [x] Resolved question — *Owner: name*: <answer text>
```

`[x]` = resolved by the user; the answer is the text after the final `:` on
the same line (or indented lines immediately below).

**Rules for resolved (`[x]`) questions:**

1. **Do NOT re-ask the user.** Never include a resolved brainstorm question
   in the clarifying-question batch in §3.
2. **Route the answer into the spec body where the decision applies** — not
   just into §8. (E.g., "default backend sqlite" goes into §2 Overview and
   §5 Acceptance Criteria, not just §8.)
3. **Also echo the resolution in §8** as a resolved item:
   ```
   - [x] <Question restated> — *Resolved in brainstorm*: <answer verbatim>
   ```
4. **If a resolved answer contradicts your instinct**, the brainstorm wins.
   Surface the conflict as a new clarifying question in §3 rather than
   silently rewriting the answer.

**Rules for unresolved (`[ ]`) questions:**

- Carry them forward into §8 as `[ ]` items.
- Only ask in §3 if the question genuinely blocks the spec; ones that can be
  decided during implementation stay as `[ ]` in §8.

#### 2c. Show the carry-forward summary before asking

```
Loaded brainstorm: sdd/proposals/<feature-name>.brainstorm.md
  Recommended Option: <X — name>
  Resolved questions carried forward (N): <one-line list>
  Unresolved questions remaining (M): <one-line list>
  Clarifying questions I still need to ask (K): <one-line list or "none">
```

If K is zero, skip §3 entirely.

### 3. Ask Clarifying Questions (only for genuine gaps)
Ask only what the brainstorm/proposal did not cover. Legitimate gaps:
- Spec-level fields not in a brainstorm (Target version, etc.).
- New open questions that genuinely block the design.
- Ambiguities discovered during codebase research.

**Forbidden:** re-asking any `[x]` resolved brainstorm question, or asking
the user to restate Problem Statement / Constraints / Recommended Option.

If there is nothing to ask, skip this step silently.

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
4. When populating §8 Open Questions, preserve the resolved/unresolved
   partition from §2b — use `[x]` with the carried-forward answer for
   resolved items, `[ ]` for unresolved.
5. Before finishing, sanity-check: for every `[x]` resolved question in the
   brainstorm, search the spec body for a passage that reflects the
   resolution. If missing, fix the spec before committing.

### 7. Output and Next Steps
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
