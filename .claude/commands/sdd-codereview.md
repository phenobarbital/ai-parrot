# /sdd-codereview — Code Review a Completed SDD Task

Reads the task file from `sdd/tasks/completed/`, loads every referenced file, applies the
`code-reviewer` rule, and runs an adversarial cross-check (agy or codex) before
producing a structured review report.

## Usage
```
/sdd-codereview sdd/tasks/completed/TASK-001-music-generation-model.md
/sdd-codereview TASK-001
/sdd-codereview music-generation-model
```

If nothing is provided, list the files in `sdd/tasks/completed/` and ask the user to pick one.

## Steps

### 1. Resolve the Task File
1. If the user passes a full path, use it directly.
2. Otherwise, scan `sdd/tasks/completed/` for a filename matching `TASK-<NNN>*` or `*<slug>*`.
3. If still ambiguous, list matches and ask.

### 2. Load Context
Read the task file and extract:
- **Spec file** path → read it.
- **Files created/modified** (from "Scope" or "Files" section) → read each one.
- **Acceptance criteria** → used to validate correctness.
- **Completion Note** → understand what was actually done.

### 3. Apply Code Review Criteria

Evaluate the implementation across these dimensions:

#### Correctness & Logic
- Does the code satisfy the task's acceptance criteria?
- Are there edge cases or error paths not handled?
- Verify the chain of thought: are assumptions documented and verifiable?

#### Code Quality
- **DRY**: Is there duplicated logic that should be extracted?
- **SOLID**: Does the code respect single responsibility, open/closed, etc.?
- **Abstraction level**: Are abstractions appropriate, or over/under-engineered?

#### Performance
- Any N+1 query patterns or unnecessary loops?
- Blocking I/O in async contexts?
- Obvious algorithmic inefficiencies?

#### Security
- Input validation and sanitisation present?
- SQL/NoSQL injection risks?
- XSS/CSRF exposure (if applicable)?
- Hardcoded secrets or credentials?

#### Documentation
- Public APIs and classes have docstrings?
- Complex logic has inline comments?
- Type hints applied consistently?

#### Testing
- Do the tests cover the acceptance criteria?
- Are edge cases and failure modes tested?
- Test quality: meaningful assertions vs. trivial checks?

### 4. Run Adversarial Cross-Check

Use an external CLI agent as an independent second-opinion reviewer. **Prefer
`agy` (Google Gemini)** when available; fall back to `codex` (OpenAI)
otherwise.

Rules:
- Never feed the reviewer your reasoning, draft review, justification, or
  preferred conclusion. Give it only the requirement/task context, the diff or
  commit, and the neutral review question.
- Run the reviewer in the background. Each call is a full agent session and may
  take 30 seconds to 2 minutes; do not call it per edit or from hooks.
- Treat reviewer output as advisory. For each substantive finding, decide:
  `CONFIRM` (adopt), `REJECT` (with reason), or `ESCALATE`.
- Never silently concede to the reviewer and never silently drop a finding.

Detection:
```bash
if command -v agy &>/dev/null; then REVIEWER="agy"
elif command -v codex &>/dev/null; then REVIEWER="codex"
fi
```

agy commands (preferred):
```bash
# If reviewing current uncommitted work
agy --sandbox --print "Review the uncommitted changes (run git diff). \
  Focus on correctness, security, async patterns, and project conventions. \
  Output findings with file:line references."

# If reviewing a task branch against the integration branch
agy --sandbox --print "Review changes between current branch and dev \
  (run git diff dev...HEAD). List findings with file:line references."

# If reviewing a specific task commit
agy --sandbox --print "Review commit <sha> (run git show <sha>). \
  List findings with file:line references."

# If a design opinion or cross-check is needed
agy --sandbox --print "<neutral brief with task, acceptance criteria, \
  changed files, and question>" > artifacts/reviews/<task>-review.txt

# Follow-up in the same agy session
agy --continue --print "<neutral follow-up question>"
```

codex commands (fallback):
```bash
# If reviewing current uncommitted work
codex exec review --uncommitted

# If reviewing a task branch against the integration branch
codex exec review --base dev

# If reviewing a specific task commit
codex exec review --commit <sha>

# If a design opinion or cross-check is needed
codex exec --sandbox read-only -o artifacts/reviews/<task>-codex.txt \
  "<neutral brief with task, acceptance criteria, changed files, and question>"

# Follow-up in the same Codex session
codex exec resume --last "<neutral follow-up question>"
```

For a parallel perspective, invoke one Claude review agent and one background
reviewer session (agy or codex) with the same neutral brief, then synthesize
agreements and disagreements in the final report.

### 5. Produce the Review Report
Output a structured markdown report:

```markdown
# Code Review: TASK-<NNN> — <title>

**Spec**: sdd/specs/<feature>.spec.md
**Reviewed files**: <list>
**Overall verdict**: ✅ Approved | ⚠ Approved with notes | ❌ Needs changes

---

## Summary
<2–3 sentence overall assessment>

## Findings

### 🔴 Critical (must fix before merge)
- **[file:line]** <description of issue>

### 🟡 Major (should fix)
- **[file:line]** <description>

### 🟢 Minor / Suggestions
- **[file:line]** <description>

## Acceptance Criteria Check
| Criterion | Status | Notes |
|-----------|--------|-------|
| <criterion> | ✅ / ❌ | <notes> |

## Adversarial Cross-Check
| Finding | Disposition | Reason |
|---------|-------------|--------|
| <Reviewer or Claude subagent finding> | CONFIRM / REJECT / ESCALATE | <why> |

## Positive Highlights
- <what was done well>
```

### 6. Save the Report (Optional)
If the user confirms, save the report to:
`sdd/reviews/TASK-<NNN>-review.md`

## Reference
- Completed tasks: `sdd/tasks/completed/`
- Per-spec task index: `sdd/tasks/index/<feature-slug>.json`
- SDD methodology: `sdd/WORKFLOW.md`
