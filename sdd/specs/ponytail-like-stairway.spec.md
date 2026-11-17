---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, docs]
tags: [sdd-flow, necessity-ladder, least-new-code, spec-template, code-review]
docs:
  policy: required
  pages: [wiki/sdd-tooling/sdd/necessity-ladder.md]
  api_modules: []
---

# Feature Specification: Necessity Ladder — least-new-code gate in the SDD flow

**Feature ID**: FEAT-908
**Date**: 2026-11-17
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.1.4

---

## 1. Motivation & Business Requirements

### Problem Statement

The amount of code a feature produces is fixed by its spec: `/sdd-task` and the coders can only
build what the §3 Interface Skeletons name. Today nothing in `/sdd-proposal`, `/sdd-spec` or the
spec template asks whether a module has to be written at all. The command only says "Note what can
be reused vs. what must be created" (`.claude/commands/sdd-spec.md:414`) and that note has no place
in the spec, no evidence requirement and no check. The result is specs that add helpers the
repository already has, wrap what the standard library or an installed package does (in this
repository most often `asyncdb`, `navconfig`, `navigator-auth`, `navigator-eventbus`), and carry
options, abstraction layers and "for later" hooks that no goal asks for.

Ponytail (a prompt-only skill) solves the same problem for a coding agent with four pieces: read
before writing, a ladder where the agent stops at the first rung that fully solves the problem,
a list of things laziness never cuts (validation at trust boundaries, error handling that prevents
data loss, security, accessibility, anything explicitly requested), and traceable debt
(`shortcut: <limit>, <when to upgrade>` comments, a small test for non-trivial logic, a closing
note on what was skipped). This feature puts that ladder into the SDD flow at the three points
where it is cheapest to apply.

The text for the `/sdd-spec` command and the spec template was drafted outside the repository
(`artifacts/sdd-spec.md`, `artifacts/spec.md`; `artifacts/` is git-ignored). This spec adopts it,
with the two amendments listed in §2, and adds the proposal-side and implementation-side parts
that draft left open.

### Goals

- **G1 — Cut at exploration time.** `/sdd-proposal` and `/sdd-brainstorm` state, for every new
  capability they propose, what happens if it is not built; a capability with no such
  justification is listed as deferred instead of proposed.
- **G2 — Reuse analysis is mandatory in the spec.** Every §3 module has one row in a
  `#### Necessity Ladder` table: the rung where it stopped (R2–R7), the evidence, the Goal or
  criterion it serves, and an estimate of new non-test lines. A module is new code (R7) only when
  a recorded search shows nothing existing covers it.
- **G3 — The gate checks itself.** `/sdd-spec` runs a Lean Review (L1–L10) before the Consequence
  Gate. It never asks: what needs a person becomes a `[ ]` item in §8, and the spec cannot be
  marked `approved` while a check fails.
- **G4 — The table binds implementation.** `/sdd-task` copies each module's row into its task and
  refuses to decompose around a symbol, file or dependency the spec does not declare;
  `code-reviewer` reports scope beyond the table, new code around twice the estimate, and
  untracked shortcuts.
- **G5 — In-house packages are checked first.** The repository's conventions name the packages
  to look at before writing new code, and the ladder reads that list.
- **G6 — No new flag, no new command.** The ladder always runs; the existing `--budget` and
  `--no-gate` flags keep their intake-only meaning.

### Non-Goals (explicitly out of scope)

- Changing how `/sdd-start`, `sdd-worker` or `sdd-coder` implement a task. They already build only
  what the task names; the binding in G4 reaches them through the task file.
- Rewriting existing specs. A spec without the table decomposes and reviews as before.
- Deferred: a `parrot sdd spec ladder` script for the mechanical checks (L1–L5, L9) with exit
  codes like `parrot sdd spec consequences` — it is specified separately, in a follow-up spec that
  depends on this one (§8 Q1). Here the checks stay in the prompt.
- Deferred: a `--no-ladder` (or similar) opt-out flag — justified only if a class of specs is
  found where the ladder has nothing to check.
- Deferred: a deterministic comparison of `git diff --numstat` against "Est. LOC" in `/sdd-done` —
  exceeding the estimate is a review finding to explain and never blocks `/sdd-done` (§8 Q3);
  justified only if reviewers do not apply the "around twice" rule consistently.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:431c075c8c856e94eee27a0c8e8a6de6a37ca4bcd8d788ad42c254db9faa6e04 evaluation_digest=sha256:4d458027f95985fe314957e530d2c5377a98dd4309d0ee19360fc20465645c53 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Everything in this feature is prompt and template text plus one contract test. No Python module,
CLI command, schema or dependency is added.

The ladder has seven rungs. A candidate module is walked from R1 down and stops at the first rung
that fully covers it:

| Rung | Question | Where it is applied |
|---|---|---|
| R1 | Does a Goal or acceptance criterion need it? | `/sdd-proposal` (G1) and `/sdd-spec` §4c |
| R2 | Is it already in this repository? | `/sdd-spec` §4c |
| R3 | Does the standard library do it? | `/sdd-spec` §4c |
| R4 | Is it a feature of a platform already in the stack? | `/sdd-spec` §4c |
| R5 | Does an already-declared dependency do it? | `/sdd-spec` §4c |
| R6 | Can it be a single change at an existing site? | `/sdd-spec` §4c |
| R7 | None of the above: write the minimum | `/sdd-spec` §4c, proven by a §6 "Does NOT Exist" entry |

The three points of application:

1. **`/sdd-proposal` and `/sdd-brainstorm` (R1).** A brainstorm states *If not built* on every
   new capability and lists the rest under `### Deferred Capabilities`, which `/sdd-spec` carries
   into §1 Non-Goals. For proposals, the synthesis prompt asks for an `if_not_built` clause on every new
   item of an enrichment scope and moves items without one to a deferred list. The proposal
   template shows both. The synthesis lint gains one rule that enforces it.
2. **`/sdd-spec` (R1–R7).** Four additions to the command — a "Least new code" guardrail, §4c
   Necessity Ladder (seven rungs, nine rules), §5a Lean Review (ten checks), and a `Ladder:` line
   in the §7 output — and five to the template: `Deferred:` lines in §1 Non-Goals, the
   `#### Necessity Ladder` table in §3, a note in §4 that unit tests cover only new code with
   logic, a §5 criterion forbidding undeclared symbols/files/dependencies, and an optional
   `### Known Shortcuts` table in §7.
3. **`/sdd-task` and `code-reviewer` (binding).** The task carries its module's ladder row as a
   `**Ladder**:` line in `## Scope`; the reviewer has three red flags that read it.

How this fits what already exists:

- **"Does NOT Exist" becomes the proof of R7.** A module can be declared new code only by citing
  an entry of that §6 section and the query that returned nothing.
- **Reuse uses the existing `verified: path:NN` anchors.** A reuse that cannot be verified does
  not hold its rung and moves down.
- **The exploration document still wins.** R1 cuts without asking only what the spec author adds
  (options, parameters, abstraction layers, "for later" hooks). A capability the brainstorm,
  proposal or intake requires, or a `[x]` answer, is kept and at most opens a §8 question.
- **`CONFIRM`s from codex (§3b) and from experts (§3c) walk the ladder too**, because they are the
  other way scope grows.

**Amendments to the drafted text** (the committed patches in `sdd/state/FEAT-908/inputs/` already
contain them):

- **A1 — L7 scan moved out of the table.** The draft wrote the L7 command inside a Markdown table
  cell with `\|` escapes. Copied as written into `grep -E`, `\|` matches a literal `|`, so the
  scan finds nothing and the check passes silently (verified: `printf 'x later\n' | grep -cE
  'future\|later'` prints `0`). The command now sits in a fenced block below the table.
- **A3 — one row added to the §2a brainstorm mapping table of `/sdd-spec`**: "Deferred
  Capabilities → §1 Non-Goals (`Deferred:` lines, verbatim)", so what a brainstorm cut at R1
  reaches the spec.
- **A2 — rule 1 of §4c points at the conventions' reuse list** (G5): "check the in-house and
  preferred packages your repository's conventions name (`sdd/CONVENTIONS.md` § Reuse first)
  before any other dependency". Package names cannot appear in the command itself because it
  ships to other repositories (`scripts/sdd/check_asset_sync.py` rejects monorepo-specific text).

### Component Diagram

```
/sdd-proposal ── R1 ──→ proposal: What's New (+ If not built) · Deferred:
                              │
/sdd-spec  §4 research ──→ §4c Necessity Ladder (R1–R7) ──→ spec §3 table + §1 Deferred:
                              │                                   │
                              └──→ §5a Lean Review (L1–L10) ──→ §5b Consequence Gate ──→ §7 "Ladder:" line
                                                                  │
/sdd-task ── copies row ──→ task ## Scope "**Ladder**:" ──→ code-reviewer red flags
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `/sdd-spec` §4 Codebase Contract ("Does NOT Exist", `verified:` anchors, Edit Sites) | uses | Evidence source for R2 and R7; no change to those sections |
| `/sdd-spec` §3b / §3c triage | extends | `CONFIRM`ed suggestions become ladder candidates |
| `/sdd-spec` §5b Consequence Gate | precedes | §5a runs before it; the gate is unchanged |
| `/sdd-proposal` §5c synthesis lint | extends | One new rule; the existing re-prompt-once behaviour applies |
| `/sdd-task` §2 / §3 | extends | Reads the table; adds one line to each task's Scope |
| `code-reviewer` Universal Red Flags | extends | Three rows, in all three copies |
| `scripts/sdd/check_asset_sync.py` | uses | `--write` regenerates `_assets/`; `--check` gates the result |
| Spec heading parsers | unaffected | See §7 "Parsers" — verified, no change needed |

### Data Models

None. No schema changes: the synthesis `enrichment` object is free-form
(`sdd/templates/state.schema.json` constrains `mode`/`phase`, not the scope body), and the task
`## Complexity Contract` JSON is not touched.

### New Public Interfaces

None in code. The new text interfaces are the headings and line formats in §3.

---

## 3. Module Breakdown

#### Necessity Ladder

<!-- This spec applies the table it introduces. Rungs: R2 already in this repo · R3 standard
     library · R4 platform feature already in the stack · R5 installed dependency · R6 single
     change at an existing site · R7 new code. "Est. LOC" counts new non-test lines of text. -->

| Module | Rung | Reuses (evidence) | Serves | New code | Est. LOC |
|---|---|---|---|---|---|
| M1: Spec template | R7 | Template structure — verified: `sdd/templates/spec.md:51`, `:106`, `:154`, `:250`, `:333`. Nothing covers it: Does NOT Exist `#### Necessity Ladder` (query: `git grep -l -F "Necessity Ladder" -- sdd/templates .claude .agent .agents` → 0 files) | G2 | 5 insertions, applied from a committed patch | ~40 |
| M2: `/sdd-spec` command and twins | R7 | §4 research, §6 "Does NOT Exist", §5b gate — verified: `.claude/commands/sdd-spec.md:22`, `:414`, `:471`, `:612`, `:714`. Nothing covers it: Does NOT Exist `### 4c. Necessity Ladder` / `### 5a. Lean Review` (query: `git grep -l -F "Lean Review"` → 0 files) | G2, G3, G6 | 6 hunks × 2 byte-identical files + a short codex summary | ~210 |
| M3: Exploration R1 (`/sdd-proposal`, `/sdd-brainstorm`) | R7 | Enrichment scope and synthesis lint — verified: `sdd/templates/synthesis.prompt.md:126`, `sdd/templates/proposal.md:141`, `:149`, `.claude/commands/sdd-proposal.md:428`, `:651`; brainstorm Capabilities — verified: `sdd/templates/brainstorm.md:140`, `:142`, `.claude/commands/sdd-brainstorm.md:188`, `:265`. Nothing covers it: Does NOT Exist `If not built` (query: `git grep -l -F "If not built"` → 0 files) | G1 | 3 template edits, 2 command edits × 2 twins per command, 2 codex lines | ~50 |
| M4: Downstream binding | R7 | Task Scope and reviewer red-flag table — verified: `.claude/commands/sdd-task.md:104`, `:119`, `sdd/templates/task.md:20`, `.claude/agents/code-reviewer.md:89`. Nothing covers it: Does NOT Exist a `**Ladder**:` task line (query: `git grep -l -F "Necessity Ladder"` → 0 files) | G4 | 2 command edits × 2 twins, 1 codex line, 1 template line, 3 table rows × 3 copies | ~40 |
| M5: Reuse-first list | R7 | Conventions files — verified: `sdd/CONVENTIONS.md:26`, `.claude/rules/codebase-conventions.md:18`; packages declared at `packages/ai-parrot/pyproject.toml:108`, `:116`, `:137`, `:201`. Nothing covers it: Does NOT Exist a `Reuse first` section (query: `git grep -l -F "Reuse first"` → 0 files) | G5 | 1 seed section + 1 table × 3 identical copies | ~35 |
| M6: Contract test, wiki page, packaged assets | R7 | Contract-test pattern — verified: `tests/sdd_scripts/test_feat801_doc_contract.py:8`; asset regeneration — verified: `scripts/sdd/check_asset_sync.py:26`. Nothing covers it: Does NOT Exist `tests/sdd_scripts/test_necessity_ladder_contract.py`, `wiki/sdd-tooling/sdd/necessity-ladder.md` (query: `ls` → no such file) | G2–G5, AC 11 | 1 wiki page; `_assets/` regenerated by the existing script | ~80 |

Totals: 6 modules — reuse 0 · stdlib/platform 0 · dependency 0 · single change 0 · new 6 · deferred 3 · est. new LOC ~455 (text; 0 lines of runtime code)

- This table is binding downstream. A task that needs a file or a dependency that is not here
  goes back to the spec; it is not added during implementation.
- No row is R2–R6 because every module is text that exists nowhere yet; the reuse is in the
  mechanisms each one leans on (existing sections, the existing lint, the existing asset script).

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Spec template | yes | Apply `sdd/state/FEAT-908/inputs/spec.template.patch` verbatim | — |
| M2: `/sdd-spec` command and twins | yes | Apply `sdd/state/FEAT-908/inputs/sdd-spec.command.patch` to both full twins; codex text fixed below | — |
| M3: Exploration R1 | yes | Exact text and anchors fixed below | — |
| M4: Downstream binding | yes | Exact text and anchors fixed below | — |
| M5: Reuse-first list | yes | Exact text and anchors fixed below | — |
| M6: Contract test, wiki page, packaged assets | yes | Test names in §4; page sections from `sdd/templates/techwiki-page.md` | — |

### Module 1: Spec template

- **Path**: `sdd/templates/spec.md`
- **Responsibility**: Give the ladder a place in every spec.
- **Depends on**: nothing.
- **Interface Skeleton** *(exact text is the committed patch; the headings and line formats below are fixed)*:
  ```text
  # sdd/templates/spec.md — apply: git apply sdd/state/FEAT-908/inputs/spec.template.patch
  §1, after "- Non-goal 1"                       # verified: sdd/templates/spec.md:51-52
      - Deferred: <thing not built> — <what would justify building it>
  §3, before "#### Delegation-eligible modules"  # verified: sdd/templates/spec.md:106
      #### Necessity Ladder
      | Module | Rung | Reuses (evidence) | Serves | New code | Est. LOC |
      Totals: <M> modules — reuse <a> · stdlib/platform <b> · dependency <c> · single change <d> · new <e> · deferred <k> · est. new LOC <n>
  §4, before "### Integration Tests"             # verified: sdd/templates/spec.md:154
      > One row per behaviour with logic in NEW code (ladder R7) …
  §5, after "- [ ] No breaking changes to existing public API"   # verified: sdd/templates/spec.md:250
      - [ ] No public symbol, file or dependency beyond §3 Interface Skeletons, §6 Edit Sites
            and §7 External Dependencies (the §3 Necessity Ladder holds)
  §7, after the "### External Dependencies" table # verified: sdd/templates/spec.md:333
      ### Known Shortcuts
      | Module | Shortcut | Limit | Upgrade when |
  ```

### Module 2: `/sdd-spec` command and twins

- **Path**: `.claude/commands/sdd-spec.md`, `.agent/workflows/sdd-spec.md`, `.agents/skills/sdd-spec/SKILL.md`
- **Responsibility**: Build the table (§4c), check it (§5a), report it (§7).
- **Depends on**: nothing (it names M1's headings, which the patch fixes; no shared file).
- **Interface Skeleton**:
  ```text
  # .claude/commands/sdd-spec.md — apply: git apply sdd/state/FEAT-908/inputs/sdd-spec.command.patch
  # .agent/workflows/sdd-spec.md — apply: patch -p1 .agent/workflows/sdd-spec.md < sdd/state/FEAT-908/inputs/sdd-spec.command.patch
  #   (the two bodies are byte-identical below the google frontmatter; hunks land 4 lines lower)
  Guardrails, after the "Do NOT write implementation bodies" bullet   # verified: .claude/commands/sdd-spec.md:22
      - **Least new code**: …
  §4, replaces "- Note what can be reused vs. what must be created."  # verified: .claude/commands/sdd-spec.md:414
  New section before "### 5. Scaffold the Spec"                       # verified: .claude/commands/sdd-spec.md:471
      ### 4c. Necessity Ladder (least-new-code gate)      — rungs R1–R7, rules 1–9
  New section before "### 5b. Consequence Gate"                       # verified: .claude/commands/sdd-spec.md:612
      ### 5a. Lean Review (checks the Necessity Ladder — never asks)  — checks L1–L10 + the L7 scan block
  §7 Output, after the "Module graph:" line                           # verified: .claude/commands/sdd-spec.md:714
         Ladder: reuse <a> · stdlib/platform <b> · dependency <c> · single change <d> · new <e> · deferred <k> · est. new LOC <n>

  # .agents/skills/sdd-spec/SKILL.md — condensed twin; add exactly:
  under "## Guardrails"                                               # verified: .agents/skills/sdd-spec/SKILL.md:27
      - Least new code: every §3 module passes the Necessity Ladder (R1–R7) and has one row in the
        spec's `#### Necessity Ladder` table; a module is new code only when a recorded search shows
        nothing existing covers it. Never cut validation at trust boundaries, error handling that
        prevents data loss, security, accessibility or anything explicitly requested.
  in step "8. Research codebase:", as its last bullet                 # verified: .agents/skills/sdd-spec/SKILL.md:102
      - Build the Necessity Ladder (full procedure §4c): walk each candidate module R1–R7 and stop
        at the first rung that fully covers it.
  in step "10. Write the spec:", as its last bullet                   # verified: .agents/skills/sdd-spec/SKILL.md:136
      - Run the Lean Review (full procedure §5a, checks L1–L10) before the consequence gate; never
        set `**Status**: approved` while a check fails. Print the `Ladder:` line in the output.
  ```

### Module 3: Exploration R1 (`/sdd-proposal`, `/sdd-brainstorm`)

- **Path**: `sdd/templates/synthesis.prompt.md`, `sdd/templates/proposal.md`, `.claude/commands/sdd-proposal.md`, `.agent/workflows/sdd-proposal.md`, `.agents/skills/sdd-proposal/SKILL.md`, `sdd/templates/brainstorm.md`, `.claude/commands/sdd-brainstorm.md`, `.agent/workflows/sdd-brainstorm.md`, `.agents/skills/sdd-brainstorm/SKILL.md`
- **Responsibility**: Make every proposed capability state what happens without it; list the rest as deferred. The two commands share no file, so they may be two tasks.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```text
  # sdd/templates/synthesis.prompt.md — replace the line                # verified: sdd/templates/synthesis.prompt.md:126
  #   "- what would be NEW (modules, functions, endpoints)"  with:
  - what would be NEW (modules, functions, endpoints) — each item with an `if_not_built`
    clause: the requirement of the source it serves and what breaks or stays manual without it
  - what is DEFERRED — any NEW candidate whose honest `if_not_built` is "nothing the source asks
    for": list it with what would justify building it later, and leave it out of NEW

  # sdd/templates/proposal.md
  under "### What's New", replace the bullet                            # verified: sdd/templates/proposal.md:141-143
  - **<New module / function / endpoint>** — <one-line role>. *If not built*: <requirement left unmet>
  under "### What's Untouched (Non-Goals)", after "- <thing 2>"         # verified: sdd/templates/proposal.md:149-153
  - Deferred: <capability considered and not proposed> — <what would justify building it>

  # .claude/commands/sdd-proposal.md and .agent/workflows/sdd-proposal.md (same lines in both)
  "#### 5c. Lint the synthesis", new rule after rule 5                  # verified: .claude/commands/sdd-proposal.md:428-438
  6. In enrichment mode, every NEW item has a non-empty `if_not_built`; an item without one is
     moved to the deferred list, never kept as NEW.
  consumption table, new row after "§3 Hypothesis / Scope"              # verified: .claude/commands/sdd-proposal.md:651
  | §3 What's Untouched — `Deferred:` lines | Spec §1 Non-Goals (`Deferred:` lines, verbatim) |

  # .agents/skills/sdd-proposal/SKILL.md — one bullet in its synthesis step, before "- Lint the synthesis:"
  #   verified: .agents/skills/sdd-proposal/SKILL.md:119
  - Enrichment scope: every new item states what happens if it is not built; items without that
    justification are listed as `Deferred:` under Non-Goals.

  # sdd/templates/brainstorm.md
  under "### New Capabilities", replace the bullet                      # verified: sdd/templates/brainstorm.md:140
  - `<name>`: <brief description>. *If not built*: <requirement left unmet>
  new subsection after the "### Modified Capabilities" block, before the "---" rule   # verified: sdd/templates/brainstorm.md:142-146
  ### Deferred Capabilities
  <!-- Capabilities considered and not proposed because nothing in the Problem Statement or the
       Constraints needs them. `/sdd-spec` carries each line into the spec's §1 Non-Goals. -->
  - Deferred: `<name>` — <what would justify building it>

  # .claude/commands/sdd-brainstorm.md and .agent/workflows/sdd-brainstorm.md (same lines in both)
  replace the "- **Capabilities**:" bullet                              # verified: .claude/commands/sdd-brainstorm.md:188
  - **Capabilities**: new and modified (kebab-case identifiers). Every new capability states what
    happens if it is not built; one that nothing in the Problem Statement or the Constraints needs
    goes under "Deferred Capabilities" instead.
  new line after "- **Capabilities** → Spec Section 3 (Module Breakdown)"   # verified: .claude/commands/sdd-brainstorm.md:265
  - **Deferred Capabilities** → Spec Section 1 (Non-Goals, `Deferred:` lines)

  # .agents/skills/sdd-brainstorm/SKILL.md — one bullet under "## Guardrails"   # verified: .agents/skills/sdd-brainstorm/SKILL.md:33
  - Every new capability states what happens if it is not built; capabilities without that
    justification are listed under "Deferred Capabilities", not proposed.
  ```

### Module 4: Downstream binding

- **Path**: `.claude/commands/sdd-task.md`, `.agent/workflows/sdd-task.md`, `.agents/skills/sdd-task/SKILL.md`, `sdd/templates/task.md`, `.claude/agents/code-reviewer.md`, `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/code-reviewer.md`, `.agents/agents/code-reviewer/agent.md`
- **Responsibility**: Carry the table into tasks and into review.
- **Depends on**: nothing (it names M1's heading; no shared file).
- **Interface Skeleton**:
  ```text
  # .claude/commands/sdd-task.md and .agent/workflows/sdd-task.md (same lines in both)
  §2, replace the "- Extract:" bullet                                   # verified: .claude/commands/sdd-task.md:104
  - Extract: Feature ID, title, module breakdown, acceptance criteria, dependencies, and the §3
    `#### Necessity Ladder` table when the spec has one.
  §3, new paragraph after the "- Aim for tasks completable in 1–4 hours each." bullet   # verified: .claude/commands/sdd-task.md:119-121
  **Necessity Ladder is binding (FEAT-908).** When the spec has a §3 `#### Necessity Ladder`
  table, each task's `## Scope` opens with its module's row as
  `**Ladder**: <rung> · reuses <evidence> · est. <n> LOC`. A task never adds a public symbol, a
  file or a dependency that the spec's Interface Skeletons, §6 Edit Sites and §7 External
  Dependencies do not declare: stop and report it in the §6 output as a spec gap instead of
  decomposing around it. A module at R2–R6 gets no CREATE row in "Files to Create / Modify".
  A spec without the table decomposes as before.

  # .agents/skills/sdd-task/SKILL.md — one bullet under "## Guardrails"  # verified: .agents/skills/sdd-task/SKILL.md:32
  - When the spec has a §3 `#### Necessity Ladder` table it is binding: copy each module's row
    into its task's `## Scope` as a `**Ladder**:` line and never add a public symbol, file or
    dependency the spec does not declare — report the gap instead.

  # sdd/templates/task.md — first line of the "## Scope" body, after its blockquote   # verified: sdd/templates/task.md:20-23
  **Ladder**: <rung> · reuses <evidence> · est. <n> LOC   <!-- the module's row in the spec's §3 Necessity Ladder; omit when the spec has no table -->

  # code-reviewer (three copies, same three rows appended to "## Universal Red Flags")
  #   after "| Unsanitized user input in templates | XSS vulnerability |"
  #   verified: .claude/agents/code-reviewer.md:89
  #   verified: packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/code-reviewer.md:89
  #   verified: .agents/agents/code-reviewer/agent.md:100
  | Public symbol, file or dependency the spec's Necessity Ladder does not declare | Scope grew during implementation — it goes back to the spec |
  | New non-test lines around twice the task's `**Ladder**` estimate | More code than the spec justified — ask for the explanation (a finding, not a failure) |
  | `# shortcut:` comment without a Known Shortcuts row in the spec, or the reverse | Untracked debt |
  ```

### Module 5: Reuse-first list

- **Path**: `sdd/CONVENTIONS.md`, `.claude/rules/codebase-conventions.md`, `.agent/rules/codebase-conventions.md`, `packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md`
- **Responsibility**: Name the packages the ladder checks first (R5), per repository.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```text
  # sdd/CONVENTIONS.md (the seed shipped to other repositories — placeholders only)
  new section before "## Style"                                         # verified: sdd/CONVENTIONS.md:29
  ## Reuse first
  <!-- In-house and preferred packages to check BEFORE writing new code or adding a dependency,
       one line each with what it covers (for example `<package>: database access`). `/sdd-spec`
       reads this list when it builds a spec's Necessity Ladder. -->

  # codebase-conventions.md — the three copies stay byte-identical
  new section before "## Repository layout"                            # verified: .claude/rules/codebase-conventions.md:30
  #   packages verified: packages/ai-parrot/pyproject.toml:137 (asyncdb), :108 (navconfig),
  #   :116 (navigator-auth), :201 (navigator-eventbus)
  ## Reuse first — check these before writing new code
  | Need | Already in the stack |
  |---|---|
  | Database access and drivers | `asyncdb` |
  | Settings, environment and configuration | `navconfig` |
  | Authentication, authorization and sessions | `navigator-auth` |
  | Events and pub/sub between components | `navigator-eventbus` |

  Then the repository's own helpers, the standard library and any other declared dependency. A new
  package is added only when none of these covers the need and the code it replaces is substantial.
  ```

### Module 6: Contract test, wiki page, packaged assets

- **Path**: `tests/sdd_scripts/test_necessity_ladder_contract.py`, `wiki/sdd-tooling/sdd/necessity-ladder.md`, `packages/ai-parrot/src/parrot/sdd/_assets/` (regenerated, never hand-edited except the reviewer copy in M4)
- **Responsibility**: Pin the text contracts, document the ladder, and bring the packaged copies in line.
- **Depends on**: M1, M2, M3, M4, M5 (the test asserts their text; `_assets/` is copied from their final content).
- **Interface Skeleton**:
  ```python
  # tests/sdd_scripts/test_necessity_ladder_contract.py  (new)
  # pattern verified: tests/sdd_scripts/test_feat801_doc_contract.py:1-8
  """FEAT-908 contract: the Necessity Ladder in the spec template, the SDD commands and review."""
  from pathlib import Path

  REPO_ROOT = Path(__file__).resolve().parents[2]


  class TestNecessityLadderContract:
      def test_spec_template_has_ladder_sections(self) -> None:
          """Template carries the ladder table, Totals line, Deferred line, Known Shortcuts and the §5 criterion."""

      def test_sdd_spec_twins_carry_the_gate(self) -> None:
          """The claude and google twins carry the guardrail, §4c, §5a and the `Ladder:` line, and stay byte-identical below the frontmatter; the codex skill names the ladder and the Lean Review."""

      def test_l7_scan_is_not_table_escaped(self) -> None:
          """No sdd-spec twin contains the `\\|`-escaped scan; each contains the plain alternation in a fenced block."""

      def test_proposal_states_if_not_built(self) -> None:
          """Synthesis prompt, proposal and brainstorm templates, and the sdd-proposal and sdd-brainstorm twins carry the if-not-built clause and the deferred list."""

      def test_task_and_reviewer_bind_the_ladder(self) -> None:
          """sdd-task twins and the task template carry the `**Ladder**:` line; the three code-reviewer copies carry the three red flags."""

      def test_conventions_name_reuse_first(self) -> None:
          """The seed has an empty `## Reuse first` section; the three codebase-conventions copies name the four packages and are identical."""

      def test_wiki_page_documents_the_ladder(self) -> None:
          """The wiki page exists and names the rungs R1–R7, the Lean Review and the binding rule."""
  ```
  ```text
  # wiki/sdd-tooling/sdd/necessity-ladder.md  (new, from sdd/templates/techwiki-page.md)
  #   sections: Purpose · Public API (the headings and line formats of §3) · Configuration
  #   (`sdd/CONVENTIONS.md` § Reuse first) · Usage Examples (one filled table) · Gotchas · Related
  # packaged assets: python scripts/sdd/check_asset_sync.py --write   # verified: scripts/sdd/check_asset_sync.py:26
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_spec_template_has_ladder_sections` | M1 | The five template additions are present |
| `test_sdd_spec_twins_carry_the_gate` | M2 | Guardrail, §4c, §5a and the `Ladder:` line in every twin; full twins identical |
| `test_l7_scan_is_not_table_escaped` | M2 | Amendment A1 holds |
| `test_proposal_states_if_not_built` | M3 | If-not-built clause and deferred list in the prompt, both exploration templates and their command twins |
| `test_task_and_reviewer_bind_the_ladder` | M4 | `**Ladder**:` line and the three red flags in every copy |
| `test_conventions_name_reuse_first` | M5 | Seed section empty of package names; three copies identical and complete |
| `test_wiki_page_documents_the_ladder` | M6 | Wiki page content |

> One row per behaviour with logic in NEW code. This feature adds text, not logic, so each row is
> a content contract in the style the repository already uses for command and template changes.

### Integration Tests

| Test | Description |
|---|---|
| `tests/sdd_scripts/test_check_asset_sync.py` | `_assets/` matches its sources after regeneration; no monorepo-specific text ships |
| `tests/sdd_scripts/test_spec_validation_contract_template.py` | The template's Validation Contract still parses with the new sections around it |
| `tests/sdd_scripts/test_command_contracts.py` | Shipped commands keep their existing contracts (no inline Python, worktree rules) |
| `packages/ai-parrot/tests/flows/test_conventions.py` | The conventions copies stay consistent |

### Validation Contract

> The new file plus every existing test that reads the files this feature modifies.

tests:
- tests/sdd_scripts/test_necessity_ladder_contract.py
- tests/sdd_scripts/test_check_asset_sync.py
- tests/sdd_scripts/test_spec_validation_contract_template.py
- tests/sdd_scripts/test_command_contracts.py
- tests/sdd_scripts/test_feat801_doc_contract.py
- tests/sdd_scripts/test_sdd_spec_intake_contract.py
- tests/sdd_scripts/test_sdd_spec_hotfix_removed_contract.py
- tests/sdd_scripts/test_e2e_spec_contract.py
- tests/sdd_scripts/test_decision_audit_entry_points.py
- packages/ai-parrot/tests/sdd/test_consult_step_twins.py
- packages/ai-parrot/tests/flows/test_conventions.py
markers: none

### Test Data / Fixtures

None. Every test reads tracked files from `REPO_ROOT`.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC 1 — `sdd/templates/spec.md` contains `#### Necessity Ladder` (before `#### Delegation-eligible modules`), a `Totals:` line, a `- Deferred:` line under Non-Goals, `### Known Shortcuts` under §7, and the §5 criterion "No public symbol, file or dependency beyond …".
- [ ] AC 2 — `.claude/commands/sdd-spec.md` contains the "Least new code" guardrail, `### 4c. Necessity Ladder` between §4b and §5, `### 5a. Lean Review` before `### 5b. Consequence Gate`, and the `Ladder:` output line.
- [ ] AC 3 — `.agent/workflows/sdd-spec.md` is byte-identical to `.claude/commands/sdd-spec.md` below its frontmatter; `.agents/skills/sdd-spec/SKILL.md` names the Necessity Ladder and the Lean Review.
- [ ] AC 4 — No `/sdd-spec` twin contains the string `future\|later`; each contains `grep -niE 'future|later|extensib|pluggable|generic|just in case'` inside a fenced block (A1).
- [ ] AC 5 — `/sdd-spec` gains no new flag: its `## Usage` line is unchanged.
- [ ] AC 6 — `sdd/templates/synthesis.prompt.md` asks for `if_not_built` on every NEW item and for a DEFERRED list; `sdd/templates/proposal.md` shows `*If not built*:` and `- Deferred:`; both `/sdd-proposal` full twins carry lint rule 6 and the `Deferred:` consumption row; `sdd/templates/brainstorm.md` shows `*If not built*:` and `### Deferred Capabilities`, and both `/sdd-brainstorm` full twins carry the two matching lines.
- [ ] AC 7 — Both `/sdd-task` full twins carry the "Necessity Ladder is binding" paragraph; `sdd/templates/task.md` carries the `**Ladder**:` line in `## Scope`; the task `## Complexity Contract` JSON is unchanged.
- [ ] AC 8 — The three `code-reviewer` copies carry the three new red-flag rows, and `.claude/agents/code-reviewer.md` stays byte-identical to its packaged copy.
- [ ] AC 9 — `sdd/CONVENTIONS.md` has a `## Reuse first` section with no package name in it; the three `codebase-conventions.md` copies are byte-identical and name `asyncdb`, `navconfig`, `navigator-auth` and `navigator-eventbus`.
- [ ] AC 10 — `python scripts/sdd/check_asset_sync.py --check` exits 0.
- [ ] AC 11 — Every test in the §4 Validation Contract passes.
- [ ] AC 12 — `wiki/sdd-tooling/sdd/necessity-ladder.md` exists (`parrot sdd techwiki check`).
- [ ] AC 13 — No file, public symbol or dependency beyond §3 and §6 Edit Sites: no `.py` file other than the test is created or modified, and no manifest changes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from pathlib import Path  # the only import the contract test needs (pattern: tests/sdd_scripts/test_feat801_doc_contract.py:3)
```

### Existing Class Signatures

No classes are used. Existing facts the modules rely on:

```text
# scripts/sdd/check_asset_sync.py
ASSETS_DIR = Path("packages/ai-parrot/src/parrot/sdd/_assets")           # line 26
ASSET_SOURCES includes ".claude/commands/sdd-*.md", ".agents/skills/sdd-*/SKILL.md",
  ".agent/workflows/sdd-*.md", ".agents/agents/code-reviewer/agent.md", "sdd/templates/*",
  "sdd/CONVENTIONS.md"                                                    # lines 34-54
PACKAGED_ONLY includes (".claude/agents/code-reviewer.md", "claude/agents/code-reviewer.md", ("claude",))
  — the packaged reviewer is hand-maintained; `--write` never copies over it  # lines 58-63
SEED_TARGETS = {"sdd/CONVENTIONS.md"}                                     # line 74
Modes: --write regenerates _assets/ + manifest.json; --check exits 1 on divergence and reports
  monorepo-specific text in shipped lines                                 # module docstring, lines 1-11

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py
_SPEC_CONTRACT_RE = re.compile(r"^### Validation Contract\s*$", re.M)     # line 37
_SPEC_NEXT_RE = re.compile(r"^#{2,3} ", re.M)                             # line 38
def parse_spec_contract(spec_md: str, *, registry: "RunnerRegistry | None" = None) -> TestContract | None  # line 448

# twins
.agent/workflows/sdd-spec.md == .claude/commands/sdd-spec.md below the 5-line google frontmatter
  (diff of `tail -n +2` vs `tail -n +6` is empty at the verified commit)
.claude/agents/code-reviewer.md == packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/code-reviewer.md (254 lines, no diff)
.claude/rules/codebase-conventions.md == .agent/rules/codebase-conventions.md
  == packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md

# committed inputs
sdd/state/FEAT-908/inputs/sdd-spec.command.patch   — `git apply --check` passes; `patch --dry-run -p1 .agent/workflows/sdd-spec.md` passes (offset 4)
sdd/state/FEAT-908/inputs/spec.template.patch      — `git apply --check` passes
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| §4c Necessity Ladder | §4 Codebase Contract research | reads "Does NOT Exist", `verified:` anchors, Edit Sites | `.claude/commands/sdd-spec.md:410-458` |
| §5a Lean Review | §5b Consequence Gate | runs immediately before it | `.claude/commands/sdd-spec.md:612` |
| Lint rule 6 | synthesis lint re-prompt | same failure path as rules 1–5 | `.claude/commands/sdd-proposal.md:428-443` |
| `**Ladder**:` task line | task `## Scope` | first body line | `sdd/templates/task.md:20` |
| Reviewer red flags | `## Universal Red Flags` table | appended rows | `.claude/agents/code-reviewer.md:75-89` |

### Does NOT Exist (Anti-Hallucination)

- ~~`#### Necessity Ladder`, `### Known Shortcuts`, `### 4c.`, `### 5a. Lean Review`, "Least new code"~~ — absent from every tracked command, twin, template and packaged asset (`git grep -l -F` over `.claude .agent .agents sdd/templates sdd/CONVENTIONS.md packages/ai-parrot/src/parrot/sdd docs/sdd wiki/sdd-tooling` → 0 files for each)
- ~~`If not built` / `if_not_built` / `Deferred Capabilities` in the proposal or brainstorm templates, their commands, or the synthesis prompt~~ — absent (same query → 0 files)
- ~~`## Reuse first` in `sdd/CONVENTIONS.md` or any `codebase-conventions.md`~~ — absent (same query → 0 files)
- ~~`# shortcut:` convention anywhere in the SDD assets~~ — absent (same query → 0 files)
- ~~`parrot sdd spec ladder`~~ — not a command (`parrot sdd spec --help` lists `consequences`, no `ladder`); this feature does not add it
- ~~A flag that turns the ladder off~~ — none exists and none is added
- ~~`tests/sdd_scripts/test_necessity_ladder_contract.py`~~, ~~`wiki/sdd-tooling/sdd/necessity-ladder.md`~~ — created by M6
- ~~A schema for the synthesis `enrichment` object~~ — `sdd/templates/state.schema.json` does not constrain it; do not add one
- ~~`.agents/rules/codebase-conventions.md`~~ — there are exactly three copies, listed in M5
- ~~`artifacts/sdd-spec.md`, `artifacts/spec.md` inside a worktree~~ — `artifacts/` is git-ignored; use the patches in `sdd/state/FEAT-908/inputs/`

### Edit Sites (Blueprint Anchors)

Verified against: `6c2c601490`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `sdd/templates/spec.md` | MODIFY | `#### Delegation-eligible modules` (first of 5 hunks; apply the patch) | `spec.md:106` | 1 |
| `.claude/commands/sdd-spec.md` | MODIFY | `### 5. Scaffold the Spec` (one of 6 hunks; apply the patch) | `sdd-spec.md:471` | 1 |
| `.agent/workflows/sdd-spec.md` | MODIFY | `### 5. Scaffold the Spec` (same patch, offset 4) | `sdd-spec.md:475` | 1 |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | `## Guardrails` | `SKILL.md:27` | 1 |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | `8. Research codebase:` | `SKILL.md:102` | 1 |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | `10. Write the spec:` | `SKILL.md:136` | 1 |
| `sdd/templates/synthesis.prompt.md` | MODIFY | `- what would be NEW (modules, functions, endpoints)` | `synthesis.prompt.md:126` | 1 |
| `sdd/templates/proposal.md` | MODIFY | `### What's New` | `proposal.md:141` | 1 |
| `sdd/templates/proposal.md` | MODIFY | `### What's Untouched (Non-Goals)` | `proposal.md:149` | 1 |
| `.claude/commands/sdd-proposal.md` | MODIFY | `#### 5c. Lint the synthesis` | `sdd-proposal.md:428` | 1 |
| `.claude/commands/sdd-proposal.md` | MODIFY | `\| §3 Hypothesis / Scope         \| Spec §2 Architectural Design           \|` | `sdd-proposal.md:651` | 1 |
| `.agent/workflows/sdd-proposal.md` | MODIFY | `#### 5c. Lint the synthesis` | `sdd-proposal.md:428` | 1 |
| `.agent/workflows/sdd-proposal.md` | MODIFY | `\| §3 Hypothesis / Scope         \| Spec §2 Architectural Design           \|` | `sdd-proposal.md:651` | 1 |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | `   - Lint the synthesis:` | `SKILL.md:119` | 1 |
| `sdd/templates/brainstorm.md` | MODIFY | ``- `<name>`: <brief description>`` | `brainstorm.md:140` | 1 |
| `sdd/templates/brainstorm.md` | MODIFY | `### Modified Capabilities` | `brainstorm.md:142` | 1 |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | `- **Capabilities**: new and modified (kebab-case identifiers).` | `sdd-brainstorm.md:188` | 1 |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | `- **Capabilities** → Spec Section 3 (Module Breakdown)` | `sdd-brainstorm.md:265` | 1 |
| `.agent/workflows/sdd-brainstorm.md` | MODIFY | `- **Capabilities**: new and modified (kebab-case identifiers).` | `sdd-brainstorm.md:188` | 1 |
| `.agent/workflows/sdd-brainstorm.md` | MODIFY | `- **Capabilities** → Spec Section 3 (Module Breakdown)` | `sdd-brainstorm.md:265` | 1 |
| `.agents/skills/sdd-brainstorm/SKILL.md` | MODIFY | `## Guardrails` | `SKILL.md:33` | 1 |
| `.claude/commands/sdd-task.md` | MODIFY | `- Extract: Feature ID, title, module breakdown, acceptance criteria, dependencies.` | `sdd-task.md:104` | 1 |
| `.claude/commands/sdd-task.md` | MODIFY | `- One task per module, class, or distinct deliverable.` | `sdd-task.md:119` | 1 |
| `.agent/workflows/sdd-task.md` | MODIFY | `- Extract: Feature ID, title, module breakdown, acceptance criteria, dependencies.` | `sdd-task.md:100` | 1 |
| `.agent/workflows/sdd-task.md` | MODIFY | `- One task per module, class, or distinct deliverable.` | `sdd-task.md:115` | 1 |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | `## Guardrails` | `SKILL.md:32` | 1 |
| `sdd/templates/task.md` | MODIFY | `## Scope` | `task.md:20` | 1 |
| `.claude/agents/code-reviewer.md` | MODIFY | `\| Unsanitized user input in templates \| XSS vulnerability \|` | `code-reviewer.md:89` | 1 |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/code-reviewer.md` | MODIFY | `\| Unsanitized user input in templates \| XSS vulnerability \|` | `code-reviewer.md:89` | 1 |
| `.agents/agents/code-reviewer/agent.md` | MODIFY | `\| Unsanitized user input in templates \| XSS vulnerability \|` | `agent.md:100` | 1 |
| `sdd/CONVENTIONS.md` | MODIFY | `## Style` | `CONVENTIONS.md:29` | 1 |
| `.claude/rules/codebase-conventions.md` | MODIFY | `## Repository layout` | `codebase-conventions.md:30` | 1 |
| `.agent/rules/codebase-conventions.md` | MODIFY | `## Repository layout` | `codebase-conventions.md:30` | 1 |
| `packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md` | MODIFY | `## Repository layout` | `codebase-conventions.md:30` | 1 |
| `tests/sdd_scripts/test_necessity_ladder_contract.py` | CREATE | — | — | — |
| `wiki/sdd-tooling/sdd/necessity-ladder.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/_assets/**` + `manifest.json` | MODIFY | regenerated by `python scripts/sdd/check_asset_sync.py --write` — never by hand | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Twins.** A full command exists twice with the same body (`.claude/commands/` and
  `.agent/workflows/`, the latter with a 5-line frontmatter) and once condensed
  (`.agents/skills/<name>/SKILL.md`, which points at the full procedure). Edit all three in the
  same task; keep the two full bodies byte-identical.
- **Shipped text is repository-neutral.** Commands, skills, workflows and templates are copied to
  other repositories. No ai-parrot path or package name goes into them — that is why the package
  list lives in `codebase-conventions.md` (never shipped) and the seed only has a placeholder.
- **Packaged assets are regenerated, not edited** — `python scripts/sdd/check_asset_sync.py
  --write`, then `--check`. The one exception is the packaged `code-reviewer.md`, which is
  hand-maintained and must be edited in M4 to stay identical to the repository copy.
- **Contract tests** follow `tests/sdd_scripts/test_feat801_doc_contract.py`: read the tracked
  file from `REPO_ROOT`, assert on exact strings.
- **Apply the patches, do not retype them.** M1 and M2 are `git apply` / `patch -p1` of the two
  committed patch files.

### Known Risks / Gotchas

- **Parsers (checked, no change needed).** The only heading-based reader of a spec's body is
  `parse_spec_contract`, which starts at `### Validation Contract` and stops at the next `##` or
  `###` heading. `#### Necessity Ladder` sits in §3, before it; `### Known Shortcuts` sits in §7,
  after it. `GitHubReviewer._parse_spec_sections` splits on level-two headings only. The
  consequence gate reads `## Decisions`, `## Governing Decisions` and `## Consequences`. The other
  heading regexes in `parrot/sdd/` and `parrot/flows/dev_loop/` read task files
  (`## Files to Create / Modify`, `## Acceptance Criteria`, `## Validation Commands`,
  `## Completion Note`), none of which this feature touches. The `**Ladder**:` line goes inside
  `## Scope`, which no parser reads.
- **Prose inside `### Validation Contract` must be `>`-quoted.** The new §4 note in the template
  is placed before `### Integration Tests`, outside that subsection, and is a blockquote anyway.
- **`.claude/agents/` is write-protected for sandboxed native workers.** The M4 edit to
  `.claude/agents/code-reviewer.md` may be refused inside a worker sandbox. Do not lift the guard:
  that one file is edited from the host (or by a seat whose changes are committed through
  `coder_merge`), and the task says so.
- **The conventions file is read on every coder turn.** Keep the new section to the table and the
  two closing lines; `packages/ai-parrot/tests/flows/test_conventions.py` must stay green.
- **The ladder can under-build.** Rule 6 of §4c ("Never cut") and check L8 exist for that; L10
  catches a capability the exploration document required and the spec lost.
- **`Est. LOC` invites gaming.** It is stated as a reference for review, not a quota; the reviewer
  flag asks for an explanation and is not a failing criterion.
- **Unattended runs.** `sdd-planner` runs `/sdd-spec` with no one to ask. §4c and §5a never ask:
  anything needing a person becomes a `[ ]` in §8.
- **Asset regeneration is an exclusive step.** `--write` rewrites `manifest.json`; run it once,
  last, after M1–M5 are merged into the feature branch.

### External Dependencies

None. No package is added or upgraded.

---

## Consequences

<!-- decision-audit: input_digest=sha256:431c075c8c856e94eee27a0c8e8a6de6a37ca4bcd8d788ad42c254db9faa6e04 evaluation_digest=sha256:4d458027f95985fe314957e530d2c5377a98dd4309d0ee19360fc20465645c53 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/ponytail-like-stairway.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: code-review, least-new-code, necessity-ladder, sdd-flow, spec-template
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "code-review",
      "least-new-code",
      "necessity-ladder",
      "sdd-flow",
      "spec-template"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/ponytail-like-stairway.spec.md"
    }
  ],
  "evaluation_digest": "sha256:4d458027f95985fe314957e530d2c5377a98dd4309d0ee19360fc20465645c53",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:431c075c8c856e94eee27a0c8e8a6de6a37ca4bcd8d788ad42c254db9faa6e04",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Q1 — Should the mechanical Lean Review checks (L1–L5, L9) become a `parrot sdd spec ladder`
  command with exit codes like `consequences`? — *Resolved by Jesus Lara (2026-11-17)*: yes, in a
  separate spec written now that depends on this one. FEAT-908 stays text-only and keeps the
  checks in the prompt.
- [x] Q2 — Should `/sdd-brainstorm` get the same R1 cut on its "Capabilities" section? —
  *Resolved by Jesus Lara (2026-11-17)*: yes, included in M3 (and amendment A3 carries the
  deferred capabilities into the spec's Non-Goals).
- [x] Q3 — Does new code around twice the estimate block `/sdd-done`? — *Resolved by Jesus Lara
  (2026-11-17)*: no. It is a review finding to explain; the estimate is a reference, not a quota.
- [x] Is a new flag needed? — *Resolved in the request*: no; `--budget` and `--no-gate` already
  exist for intake, so the ladder always runs.
- [x] Do the template parsers break on `#### Necessity Ladder` (§3) or `### Known Shortcuts` (§7)?
  — *Resolved by research*: no; see §7 "Parsers".
- [x] Is the implementation side bound to the table? — *Resolved in this spec*: yes, through M4
  (`/sdd-task` and `code-reviewer`).

---

## 9. Design Research Cross-Check

> Status: skipped (no accepted exploration document — the spec was written from request notes, and
> intake mode did not run). Expert consultation (§3c) was skipped for the same reason: it needs a
> source brainstorm or proposal.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for the spec; `sdd-coder` gives each task its own
  sub-worktree inside it.
- **Module dependency graph**: M6 → M1, M2, M3, M4, M5 (its test asserts the text each of them
  adds, and `_assets/` is copied from their final content). There is no edge among M1–M5: they
  modify disjoint files and none reads another's output, so they run concurrently.
- **Shared files**: none between modules. Within M2, M3 and M4 the twins of one command belong to
  the same task.
- **Exclusive resources**: `python scripts/sdd/check_asset_sync.py --write` rewrites
  `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` — the M6 task is `parallel: false`.
  The `.claude/agents/code-reviewer.md` edit in M4 needs a host-side (non-sandboxed) write.
- **Cross-feature dependencies**: none. Any open branch that edits the same command twins will
  conflict textually; rebase this feature last if one lands first.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/sdd-tooling/sdd/necessity-ladder.md` — create: what the ladder is, the seven rungs and
    their evidence, the Lean Review checks, how the table binds tasks and review, and the
    `# shortcut:` convention.
- **API modules**: none (no Python API is added).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-17 | Jesus Lara (with Claude) | Initial draft |
| 0.2 | 2026-11-17 | Jesus Lara (with Claude) | Open questions resolved: `/sdd-brainstorm` added to M3 (A3), the ladder script moved to a follow-up spec, LOC rule confirmed as non-blocking |
