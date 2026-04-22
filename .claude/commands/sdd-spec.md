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
- **NEVER re-ask a question that the brainstorm already answered.** Resolved
  answers must be carried forward verbatim, not re-opened. See §2 for the
  resolved-question convention and §3 for what you MAY ask.
- **Always commit the spec file to the current branch** so worktrees can see it.

## Steps

### 1. Parse Input
- **feature-name**: slug-friendly kebab-case. If not provided, ask.
- **free-form notes**: anything after `--`, used as Problem Statement seed.

### 2. Check for Prior Exploration (and carry it forward)

Look for prior exploration documents in `sdd/proposals/`:
- `<feature-name>.brainstorm.md` → structured options analysis with a Recommended Option.
- `<feature-name>.proposal.md` → discussion output.

If neither exists, proceed to §3.

**If a brainstorm exists, you MUST treat it as the authoritative input.**
Do the following in order before writing anything or asking the user anything:

#### 2a. Map the brainstorm into the spec

Carry each brainstorm section into the spec per this mapping. This is not
optional — every non-empty brainstorm section below has a target in the spec:

| Brainstorm section | Spec target |
|---|---|
| Problem Statement | §1 Motivation — Problem Statement (verbatim, condensed only if needed) |
| Constraints & Requirements | §1 Goals + §5 Acceptance Criteria (every hard constraint becomes a checkable criterion) |
| Recommendation + Recommended Option body | §2 Architectural Design — Overview |
| Feature Description → User-Facing Behavior | §2 Overview |
| Feature Description → Internal Behavior | §2 Component Diagram + Integration Points |
| Feature Description → Edge Cases & Error Handling | §7 Known Risks / Gotchas |
| Capabilities (New + Modified) | §3 Module Breakdown (one module per capability as a starting point) |
| Impact & Integration table | §2 Integration Points |
| Code Context (entire section) | §6 Codebase Contract (re-verify every reference — code may have shifted) |
| Libraries / Tools table | §7 External Dependencies |
| Parallelism Assessment | Worktree Strategy section |
| Open Questions (see 2b) | §8 Open Questions (with resolved/unresolved state preserved) |

Rejected options from the brainstorm are NOT carried into the spec body.
They may be referenced in one line inside §1 Non-Goals if the rejection
excludes something a reader might expect (e.g. *"Runtime fallback-on-failure
was rejected in brainstorm — see proposals/<name>.brainstorm.md Option A."*).

#### 2b. Parse the Open Questions section — resolved vs. unresolved

The brainstorm's Open Questions use this convention:

```
- [ ] Unresolved question — *Owner: name*
- [x] Resolved question — *Owner: name*: <answer text>
```

- A **`[x]`** checkbox means the user has already answered the question.
  The answer is the text after the final `:` on the same line (or the
  indented lines immediately below, if any).
- A **`[ ]`** checkbox means the question is still open.

**Rules for resolved (`[x]`) questions — this is the heart of the fix:**

1. **Do NOT re-ask the user.** Never include a resolved brainstorm question
   in the clarifying-question batch in §3.
2. **Route the answer into the spec body where the decision actually
   applies** — not just into §8. For example:
   - "Default backend when unset → sqlite" → state this in §2 Overview and
     add an acceptance criterion in §5. Do not leave it as an open question.
   - "Binary overflow path declared in `parrot/conf.py`" → add the config
     key to §6 Configuration References and mention the path in §7
     Patterns to Follow. Do not describe the design as "mingled" or any
     alternative that contradicts the resolved answer.
   - "No TTL in SQL backends" → reflect this in the schema DDL (no
     `expires_at` predicate) and in §7 Known Risks.
3. **Also echo the resolution in §8** as a resolved item so readers can
   audit the decision trail:
   ```
   - [x] <Question restated> — *Resolved in brainstorm*: <answer verbatim>
   ```
   This keeps §8 honest about what was decided and by whom.
4. **If a resolved answer conflicts with your own instinct for the spec**,
   the brainstorm wins. Do not silently override it. If you believe the
   answer is wrong, surface the conflict to the user as a *new* question
   in §3 — do not rewrite the answer.

**Rules for unresolved (`[ ]`) questions:**

- Carry them forward into §8 of the spec as `[ ]` items.
- They are fair game for §3 clarifying questions, but only if they
  genuinely block the spec (ones that can be decided during
  implementation should stay as `[ ]` in §8 and not be asked now).

#### 2c. Show the user the carry-forward summary before asking anything

Before the clarifying-question round in §3, print:

```
Loaded brainstorm: sdd/proposals/<feature-name>.brainstorm.md
  Recommended Option: <X — name>
  Resolved questions carried forward (N): <one-line list>
  Unresolved questions remaining (M): <one-line list>
  Clarifying questions I still need to ask (K): <one-line list or "none">
```

If K is zero, proceed directly to §4 without asking anything.

### 3. Ask Clarifying Questions (only what is genuinely missing)

After §2c, you may ask the user **only** for gaps the brainstorm/proposal did
not cover. Typical legitimate gaps:

- Spec-level fields that don't exist in a brainstorm (Target version, Author
  attribution if unclear, Status lifecycle preference).
- New `[ ]` open questions that genuinely block the design (not ones that
  can be deferred to implementation).
- Ambiguities discovered during codebase research in §4 (e.g., two plausible
  integration points — which one to use).

**Forbidden in this step:**
- Re-asking anything that already appeared in the brainstorm's Open Questions
  as `[x]` resolved.
- Re-asking Problem Statement / Constraints / Recommended Option — the
  brainstorm is authoritative on those.
- Asking the user to restate the feature goals in their own words when the
  brainstorm already states them.

Ask in a single batch so the user answers once and you proceed. If there is
nothing to ask, skip this step silently.

### 4. Research the Codebase & Build Codebase Contract
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

### 5. Scaffold the Spec
1. Read the template at `sdd/templates/spec.md`.
2. Create `sdd/specs/<feature-name>.spec.md` filled in with:
   - Feature ID (check existing; increment last; start at FEAT-001 if none).
   - Today's date.
   - Answers from user (or prior exploration documents).
   - Architectural patterns from your codebase research.
3. When populating §8 Open Questions, apply the resolved/unresolved
   partition from §2b. Resolved items use `[x]` and the carried-forward
   answer; unresolved items use `[ ]`.
4. Before finishing, sanity-check the spec against the brainstorm:
   for every `[x]` resolved question in the brainstorm, search the spec
   body for a passage that reflects the resolution. If you cannot find
   one, you have failed to carry the decision forward — fix the spec
   before committing.

**Worktree hint (new section in spec):**
Include a `## Worktree Strategy` section in the spec with:
- Default isolation unit: `per-spec` or `per-task`.
- If `per-spec`: all tasks run sequentially in one worktree.
- If mixed: list which tasks are parallelizable and why.
- Cross-feature dependencies: list any specs that must be merged first.

### 6. Commit the Spec

> **CRITICAL — Worktrees branch from the current state of the repo.**
> If the spec is not committed, any worktree created later will NOT see it,
> and the `sdd-worker` agent will fail with "no spec found".

> **CRITICAL — Only commit the spec file. NEVER commit unrelated changes.**
> Other files may be modified or unstaged in the working directory — do NOT
> touch them. Follow the exact sequence below.

```bash
# 1. Unstage everything first to ensure a clean staging area
git reset HEAD

# 2. Stage ONLY the spec file — NEVER use "git add ." or "git add -A"
git add sdd/specs/<feature-name>.spec.md

# 3. Verify ONLY the spec file is staged (nothing else)
git diff --cached --name-only
# Expected output: sdd/specs/<feature-name>.spec.md
# If ANY other files appear, run "git reset HEAD" and start over

# 4. Commit
git commit -m "sdd: add spec for FEAT-<ID> — <feature-name>"
```

### 7. Output
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