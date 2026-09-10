# TASK-3097: `/sdd-spec` command — §3b Collaborative Design Research phase + Interface Skeleton rules (+ twin, + .gitignore)

**Feature**: FEAT-545 — Collaborative Adversarial Spec Design
**Spec**: `sdd/specs/collaborative-adversarial-spec-design.spec.md` (§3 Module 5, §2 Overview B)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3095, TASK-3096
**Assigned-to**: unassigned

---

## Context

This is the centre of change #2: `/sdd-spec` gains an **optional, never-blocking** phase that hands the *accepted* brainstorm/proposal to the `codex` seat (`gpt-5.6-luna`, high reasoning, read-only) and triages its suggestions CONFIRM / REJECT / ESCALATE into spec §9 (spec G3, G4; proposal U1/U2/U4). It runs **before** §4/§5 so Claude has not drafted anything yet (anti-ratification). Because the FEAT-ID is only reserved in §5, outputs are staged under an id-independent directory and moved in §6. The phase reuses the five Adversarial Cross-Check rules verbatim from `.claude/agents/code-reviewer.md:134-150`. The command also gets the Interface Skeleton rule (spec G2) and its twin must be regenerated.

---

## Scope

- `.claude/commands/sdd-spec.md`: reword guardrail (:17); insert **§3b** after §2d and before §3; add §4 item 6 (Interface Skeletons); extend §6 commit to include `sdd/state/<FEAT-ID>/design_research/`; add the `Design research:` line to §7; add `sdd/templates/design_research.*` to "## Reference".
- `.gitignore`: add `sdd/state/.design_research/`.
- Regenerate `.agent/workflows/sdd-spec.md` body.

**NOT in scope**: templates (TASK-3095/3096); CLAUDE.md policy and tests (TASK-3098); running the phase for real (TASK-3099); any Python module or dev-loop dispatcher.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | guardrail, §3b (~110 lines), §4 item 6, §6, §7, Reference |
| `.agent/workflows/sdd-spec.md` | MODIFY | body parity (frontmatter + policy line preserved) |
| `.gitignore` | MODIFY | one line: `sdd/state/.design_research/` |

---

## Codebase Contract (Anti-Hallucination)

### Anchors in `.claude/commands/sdd-spec.md` (431 lines, verified 2026-09-10)
```text
:17      - Do NOT write implementation code in the spec — specs are design documents.   ← REPLACE
:121     #### 2c. Show the user the carry-forward summary before asking anything
:133     If K is zero, proceed directly to §4 without asking anything.                  ← change "§4" to "§3b"
:135     #### 2d. Sync the Base Branch (FEAT-145, resolver added FEAT-466)
:205     Carry `TYPE` and `BASE_BRANCH` forward into the spec's frontmatter at §5.      ← §3b goes AFTER this line (+ blank)
:207     ### 3. Ask Clarifying Questions (only what is genuinely missing)
:230     ### 4. Research the Codebase & Build Codebase Contract
:251-252 5. **Include user-provided code**: ...                                          ← add item 6 after this
:353     ### 6. Commit the Spec
:363-377 fenced bash: git reset HEAD / git add sdd/specs/<feature-name>.spec.md / git diff --cached --name-only / git commit -m "sdd: add spec for FEAT-<ID> — <feature-name>"
:379     ### 7. Output   (:383 "✅ Spec created and committed: ...", :385 "Feature ID: FEAT-<ID>", :386 "Isolation: ...")
:418-422 ## Reference (- Template: `sdd/templates/spec.md` ...)
```
### Twin `.agent/workflows/sdd-spec.md` (434 lines)
```text
:1-4   frontmatter (keep);  :426  "- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`" (keep; original says `CLAUDE.md` (section "Worktree Policy"))
```
### Policy text to copy verbatim
```text
.claude/agents/code-reviewer.md:125-132  agy ban blockquote
.claude/agents/code-reviewer.md:134-150  Key Rules (5 bullets)
```
### Codex CLI (codex-cli 0.153.4 at ~/.local/bin/codex — verified `codex exec --help`)
```text
codex exec [OPTIONS] [PROMPT]        PROMPT positional, or `-` = read from stdin
  -m, --model <MODEL>                -c, --config <key=value>     e.g. -c model_reasoning_effort=high
  -s, --sandbox <MODE>               --ephemeral                  --ignore-user-config
  --output-schema <FILE>             -o, --output-last-message <FILE>
  --cd <DIR>                         (exec-level option; precede any subcommand)
Probe verified 2026-09-10: codex exec --ephemeral --sandbox read-only -m gpt-5.6-luna -c model_reasoning_effort=high \
  --ignore-user-config -o <file> "Reply with exactly the single word OK."   → exit 0, file = "OK"
```
### Templates this phase consumes (created by TASK-3095/3096 — verify they exist before starting)
```text
sdd/templates/design_research.prompt.md     placeholders: {{problem_statement}} {{constraints_and_goals}} {{recommended_option_or_scope}} {{code_context_paths}} {{open_questions}} {{question}}
sdd/templates/design_research.schema.json   Draft 2020-12; jsonschema 4.26.0 installed (packages/ai-parrot/pyproject.toml:80)
sdd/templates/spec.md                       "## 9. Design Research Cross-Check" table: # | Suggestion (kind) | Disposition | Reason | Landed in
```
### Exploration-doc sections the brief is built from
```text
brainstorm (sdd/templates/brainstorm.md): ## Problem Statement (:18) · ## Constraints & Requirements (:23) · ## Recommendation (:102) · ## Code Context (:154) · ## Open Questions (:212) · **Status**: accepted (:13)
proposal   (sdd/templates/proposal.md):   ## 1. Synthesis Summary · ## 2.2 Constraints Discovered · ## 3. Probable Scope (or Hypothesis) · ## 2.1 Localization (paths) · ## 5 Open Questions (unresolved) · frontmatter status: accepted
```
### `.gitignore`
```text
:283  artifacts/          ← precedent; append the new line near the other sdd-related ignores or at the end
```
### Does NOT Exist
- ~~`### 3b.`~~ in sdd-spec.md — created here
- ~~`SDD_DESIGN_RESEARCH_MODEL`~~ anywhere — a bash `${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}` default inside the command; NOT a `parrot/conf.py` key
- ~~`codex exec design`~~, ~~`codex exec --reasoning`~~, ~~`codex exec review`~~ for this phase — plain `codex exec` with a stdin brief
- ~~`scripts/sdd/design_research.py`~~, ~~`CodexDesignResearchDispatcher`~~ — no Python helper/dispatcher
- ~~`sdd/state/.design_research/`~~ — staging dir the phase creates; add to `.gitignore` here

---

## Implementation Notes

### Pattern to Follow
- Structure §3b like §2d: numbered sub-steps, fenced bash, explicit "abort/skip" messages in the same `⚠️` style used at `:167-169` and `:193-203`.
- Skip semantics copy the review policy's fallback ("with no external reviewer available, say so and rely on a Claude subagent", `code-reviewer.md:130-132`).

### Key Constraints
- **Never exit non-zero from §3b.** Capture `rc=$?` after the codex call; every failure branch writes a `SKIP_REASON` and continues.
- `--ignore-user-config` is mandatory (proposal F009: operator config would silently swap the model).
- The brief is rendered from the exploration document only. The command text must say so in capitals, once.
- Twin regeneration exactly as TASK-3094 (frontmatter + policy line are the only deltas).

---

## Implementation Blueprint

### Steps (in order)
1. Replace the guardrail line :17 — *why*: skeletons are now required, bodies still banned.
2. Change `:133` "proceed directly to §4" → "proceed directly to §3b" — *why*: the new phase sits between 2c and 3.
3. Insert the §3b block below after line :205 (end of §2d) — *why*: it needs `TYPE`/`BASE_BRANCH`/the exploration-doc path resolved, and must run before §4/§5 drafting.
4. Add §4 item 6 — *why*: G2.
5. Extend §6's fenced bash — *why*: the transcript must be committed with the spec and visible to worktrees (`artifacts/` is gitignored).
6. Add the `Design research:` output line to §7 and the two template paths to `## Reference`.
7. Append `sdd/state/.design_research/` to `.gitignore`.
8. Regenerate the twin and diff (expect 6 differing lines).

### `.claude/commands/sdd-spec.md` (MODIFY — line 17)
```markdown
# BEFORE
- Do NOT write implementation code in the spec — specs are design documents.
# AFTER
- Do NOT write implementation bodies in the spec — but every §3 module MUST
  carry an **Interface Skeleton** (signatures, docstrings, `verified:` anchors;
  see §4 item 6). Bodies belong to task Implementation Blueprints (`/sdd-task`).
```

### `.claude/commands/sdd-spec.md` (MODIFY — line 133)
```markdown
# BEFORE
If K is zero, proceed directly to §4 without asking anything.
# AFTER
If K is zero, proceed directly to §3b without asking anything.
```

### `.claude/commands/sdd-spec.md` (MODIFY — insert after line 205 "Carry `TYPE` and `BASE_BRANCH` forward ... at §5.")
````markdown

### 3b. Collaborative Design Research (codex seat — optional, NEVER blocking)

An independent design opinion over the **accepted exploration document**, taken
*before* you draft §2/§6 so it cannot become a ratification of your own design
(FEAT-545). This step is optional: every failure below is recorded as a skip
reason for spec §9 and the command continues. **This step must never abort
`/sdd-spec`** — `sdd-planner` runs this command unattended.

**Preconditions (any false ⇒ skip):**
- §2 found `<exploration-doc>` and its status is `accepted` (brainstorm
  `**Status**: accepted`, or proposal frontmatter `status: accepted`).
- `command -v codex` succeeds.

**Rules (identical to the Adversarial Cross-Check in `.claude/agents/code-reviewer.md`):**
- **Never feed the reviewer your reasoning, draft, or preferred conclusion.**
  The brief carries ONLY the exploration document and verified code anchors.
- **Run it in the background** — a call takes 30 s to 10 min. Do not call it
  per edit.
- **Treat the output as advisory.** Every suggestion gets a disposition:
  `CONFIRM` (fold into §2/§3/§7), `REJECT` (record why), `ESCALATE` (becomes
  a `[ ]` item in §8).
- **Never silently concede and never silently drop** a suggestion.
- **Verify the reviewer's evidence.** Every `affected_paths` entry is checked
  with `test -e`; an unverifiable path ⇒ `REJECT` "path not found".

> **`agy` (Google Gemini / Antigravity) MUST NOT be used for this seat** — same
> ban and same reason as for code review (`CLAUDE.md`, "Adversarial Second
> Opinion"). With no `codex`, skip; do not substitute another external CLI.

#### 3b.1 Detect and probe
```bash
MODEL="${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}"
DR="sdd/state/.design_research/<feature-name>"      # id-independent staging: FEAT-ID is reserved only in §5
mkdir -p "$DR"; SKIP_REASON=""
if ! command -v codex >/dev/null 2>&1; then SKIP_REASON="codex CLI not installed"; fi
if [ -z "$SKIP_REASON" ]; then
  timeout 120 codex exec --ephemeral --sandbox read-only -m "$MODEL" \
    -c model_reasoning_effort=high --ignore-user-config \
    -o "$DR/probe.txt" "Reply with exactly the single word OK." >/dev/null 2>&1 \
    || SKIP_REASON="model probe failed for $MODEL (rc=$?)"
fi
```

#### 3b.2 Render the neutral brief
Fill `sdd/templates/design_research.prompt.md` → `$DR/brief.md`, replacing:
- `{{problem_statement}}` ← brainstorm "## Problem Statement" | proposal "## 1. Synthesis Summary" + §0 Origin quote
- `{{constraints_and_goals}}` ← brainstorm "## Constraints & Requirements" | proposal "### 2.2 Constraints Discovered"
- `{{recommended_option_or_scope}}` ← brainstorm "## Recommendation" + Recommended Option body | proposal "## 3. Probable Scope" (or "## 3. Hypothesis")
- `{{code_context_paths}}` ← the **paths only** (one per line) from brainstorm "## Code Context" | proposal "### 2.1 Localization"
- `{{open_questions}}` ← the `[ ]` items of the exploration doc (or "none")
- `{{question}}` ← "Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?"

FORBIDDEN in the brief: anything you have written for this spec, your
reasoning, this command's text, or a preferred answer. If in doubt, leave it out.

#### 3b.3 Run codex (background, capped)
```bash
if [ -z "$SKIP_REASON" ]; then
  timeout 600 codex exec --ephemeral --sandbox read-only --cd "$REPO_ROOT" \
    -m "$MODEL" -c model_reasoning_effort=high --ignore-user-config \
    --output-schema sdd/templates/design_research.schema.json \
    -o "$DR/suggestions.json" - < "$DR/brief.md" > "$DR/codex.log" 2>&1
  rc=$?
  [ "$rc" -eq 124 ] && SKIP_REASON="codex timed out after 600s"
  [ "$rc" -ne 0 ] && [ -z "$SKIP_REASON" ] && SKIP_REASON="codex exited $rc (see $DR/codex.log)"
fi
```
Run this in the background and continue reading the codebase for §4 while it
works; join before §5.

#### 3b.4 Validate and triage
```bash
if [ -z "$SKIP_REASON" ]; then
  python -c "
import json, sys, jsonschema
s = json.load(open('sdd/templates/design_research.schema.json'))
d = json.load(open('$DR/suggestions.json'))
jsonschema.Draft202012Validator(s).validate(d)
print(len(d['suggestions']), 'suggestions')" || SKIP_REASON="suggestions.json failed schema validation"
fi
```
For each suggestion (when not skipped): verify every `affected_paths` entry
(`test -e <path>`); read the cited spots; decide **CONFIRM / REJECT /
ESCALATE** with a one-sentence reason; write `$DR/triage.md` using the §9
table shape from `sdd/templates/spec.md`. A suggestion with any unverifiable
path is `REJECT — path not found`.

#### 3b.5 Fold and record
- `CONFIRM` → apply while drafting §2 Overview / §3 modules / §7 notes; the
  §9 row's "Landed in" names the section.
- `ESCALATE` → add a `[ ]` question to §8 (owner: the user); "Landed in" = `§8 Q<N>`.
- `REJECT` → row only.
- Fill spec **§9 Design Research Cross-Check** from `$DR/triage.md`, with
  `Model: <MODEL>` and `Status: completed` — or, when skipped, a single
  line `Status: skipped (<SKIP_REASON>)` and an empty table.
- §6 moves `$DR` to `sdd/state/<FEAT-ID>/design_research/` and commits it
  with the spec.

````

### `.claude/commands/sdd-spec.md` (MODIFY — §4, append after item 5 at :251-252)
```markdown
6. **Interface Skeletons (FEAT-545)**: for every §3 module write the public
   signatures and docstrings of what the module adds or changes — no bodies —
   each line that touches existing code carrying `# verified: path:NN`. These
   skeletons are what `/sdd-task` turns into per-task Implementation Blueprints,
   so a name fixed here is not renegotiable later.
```

### `.claude/commands/sdd-spec.md` (MODIFY — §6 fenced bash, replace the block at :363-377)
```bash
# 1. Unstage everything first to ensure a clean staging area
git reset HEAD

# 2. Stage ONLY the spec file (+ the design-research transcript when §3b ran) — NEVER "git add ." / "-A"
git add sdd/specs/<feature-name>.spec.md
if [ -d "sdd/state/.design_research/<feature-name>" ]; then
  mkdir -p "sdd/state/<FEAT-ID>/design_research"
  mv sdd/state/.design_research/<feature-name>/* "sdd/state/<FEAT-ID>/design_research/"
  rmdir "sdd/state/.design_research/<feature-name>"
  git add "sdd/state/<FEAT-ID>/design_research/"
fi

# 3. Verify ONLY those paths are staged
git diff --cached --name-only
# Expected: sdd/specs/<feature-name>.spec.md [+ sdd/state/<FEAT-ID>/design_research/*]
# If ANY other files appear, run "git reset HEAD" and start over

# 4. Commit
git commit -m "sdd: add spec for FEAT-<ID> — <feature-name>"
```
**Why**: `artifacts/` is gitignored; the transcript must land in a tracked, id-keyed location so §9's pointer resolves in every worktree.

### `.claude/commands/sdd-spec.md` (MODIFY — §7 Output, feature block, after the "Isolation:" line)
```markdown
   Design research: <N> suggestions — <C> confirmed / <R> rejected / <E> escalated   (model <MODEL>)
   # or:  Design research: skipped (<SKIP_REASON>)
```

### `.claude/commands/sdd-spec.md` (MODIFY — `## Reference`, add two bullets)
```markdown
- Design-research brief: `sdd/templates/design_research.prompt.md` (FEAT-545)
- Design-research schema: `sdd/templates/design_research.schema.json` (FEAT-545)
```

### `.gitignore` (MODIFY — append)
```gitignore
# FEAT-545: id-independent staging for /sdd-spec §3b; committed copies live under sdd/state/<FEAT-ID>/design_research/
sdd/state/.design_research/
```

### `.agent/workflows/sdd-spec.md` (MODIFY — regenerate body)
```bash
head -n 4 .agent/workflows/sdd-spec.md > /tmp/twin.md
tail -n +5 .claude/commands/sdd-spec.md | \
  sed 's|^- Worktree policy: `CLAUDE.md` (section "Worktree Policy")$|- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`|' >> /tmp/twin.md
mv /tmp/twin.md .agent/workflows/sdd-spec.md
diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'    # expect 6
```

### FILL IN checklist
- [ ] `3b.2` — decide the exact `sed`/`python -c` used to fill the six placeholders (a heredoc-free `python - <<'PY' … PY` replacing `{{name}}` from variables is acceptable); keep it in the command text so Haiku can copy it.
- [ ] Confirm `--cd "$REPO_ROOT"` is accepted together with `-` stdin on codex-cli 0.153.4 (documented as exec-level in `dispatchers/codex.py:312-316`); if not, drop `--cd` and run from the repo root.

---

## Acceptance Criteria

- [ ] `grep -n "specs are design documents" .claude/commands/sdd-spec.md` → no match (spec AC-5)
- [ ] `grep -n "^### 3b\." .claude/commands/sdd-spec.md` → one line, located after `#### 2d.` and before `### 3.`
- [ ] §3b contains the exact codex command with `--ephemeral --sandbox read-only -m "$MODEL" -c model_reasoning_effort=high --ignore-user-config --output-schema sdd/templates/design_research.schema.json -o "$DR/suggestions.json" -` and `timeout 600`
- [ ] §3b contains all five rules and the `agy` ban; contains the word `SKIP_REASON` in every failure branch; contains no `exit 1`
- [ ] §4 item 6 "Interface Skeletons" present; §6 block stages `sdd/state/<FEAT-ID>/design_research/`; §7 prints `Design research:`; Reference lists both templates
- [ ] `.gitignore` contains `sdd/state/.design_research/` (spec AC-11)
- [ ] `diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'` → `6` (spec AC-7)

---

## Test Specification

Manual until TASK-3098 (`test_command_twin_parity[sdd-spec]`) and TASK-3099 (dry run + skip path):
```bash
grep -n "^### \|^#### 3b" .claude/commands/sdd-spec.md      # 3b between 2d and 3
bash -n <(sed -n '/^#### 3b.1/,/^#### 3b.5/p' .claude/commands/sdd-spec.md | awk '/^```bash/{f=1;next}/^```/{f=0}f')   # shell syntax of the fenced blocks
git check-ignore -q sdd/state/.design_research/x && echo IGNORED
```

---

## Agent Instructions

1. Read spec §2 Overview (B), §3 Module 5, §7 risks.
2. Dependencies: TASK-3095 and TASK-3096 in `sdd/tasks/completed/`; confirm both template files exist.
3. Re-grep every anchor; implement from the blueprint; run the Test Specification checks.
4. Commit the three files together; move to completed; index → `"done"`; Completion Note (record the two FILL IN decisions).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
