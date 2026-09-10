# TASK-3090: SDD delegation workflow — templates, Claude commands, Codex skills and sdd-worker parity

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3083, TASK-3086
**Assigned-to**: unassigned

---

## Context

Spec §2 "Host Guards and SDD Workflow" (last block: `sdd-spec`,
`sdd-task`, `sdd-start`/`sdd-worker`, legacy TASK files), §3 Module M8,
AC12. One coordinated owner edits the SDD templates, the Claude Code
command files, the Codex skill files and the `sdd-worker` agent so both
hosts produce eligible delegation packets and enforce
**generate → bounded hunk review → apply → real acceptance tests →
normal SDD commit**. Legacy tasks (no `## Delegation Contract`) keep the
normal implementation route; delegation failure never silently invokes
another coder.

The packet grammar and eligibility rules are fixed by TASK-3083
(`## Delegation Contract` + one ```` ```json ```` block, labelled
```` ```<lang> id=<block-id> [path=<target>] ```` implementation blocks,
placeholder regexes, CREATE rule). This task documents them for authors
and wires the workflow steps; it changes no Python code.

---

## Scope

- `sdd/templates/task.md`: add an OPTIONAL section after
  `## Codebase Contract (Anti-Hallucination)` (line 43 today):
  `## Delegation Contract` with (a) a one-paragraph eligibility
  statement (design complete, every target listed, blocks contain the
  decided code, hashes verified at `/sdd-task` time and re-verified at
  execution), (b) the exact JSON packet example from TASK-3083's fixture
  (with `<sha256>` placeholders clearly marked as MUST-BE-REPLACED —
  note the validator will reject them as `invalid_packet`, which is the
  intended safety net), (c) two labelled block examples (`create` with
  `path=` and `modify`), (d) a "Remove this section entirely if the task
  is not delegation-eligible" note. Keep the rest of the template
  byte-identical. (`.gitignore` has a `templates/` rule but these files
  are already tracked — edits commit normally; do not add new files
  under `sdd/templates/`.)
- `sdd/templates/spec.md`: in `## 3. Module Breakdown` (line 72) add a
  "Delegation-eligible modules" sub-table template (`Module | Eligible?
  | Decided patterns / exact contracts | Why not (if no)`), and one
  sentence in `## 7. Implementation Notes & Constraints` (line 162)
  reminding that architecture decisions stay with the thinking model.
- `.claude/commands/sdd-spec.md` and `.agents/skills/sdd-spec/SKILL.md`:
  add a step "Identify delegation-eligible modules" mirroring the spec
  template addition (same wording in both hosts; the Codex skill is
  terser — keep parity of MEANING, tests check for shared key phrases).
- `.claude/commands/sdd-task.md` and `.agents/skills/sdd-task/SKILL.md`:
  after the Codebase Contract step (`SKILL.md:59-64` / command §3
  "CRITICAL — Codebase Contract per Task"), add "Delegation Contract
  (optional)": emit a packet ONLY when the task is complete
  (`design_complete: true` is a declaration the author signs), compute
  real sha256 for `modify` targets and references
  (`sha256sum <path>` / `python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <path>`),
  never leave placeholders, and note that hashes are re-validated at
  execution time after dependencies land (stale → the executor
  refreshes the packet in the task file FIRST, then re-runs
  `writer_generate`).
- `.claude/commands/sdd-start.md` (§7 "Begin Implementation", line 127)
  and `.agents/skills/sdd-start/SKILL.md` (step 8 "Implement", line
  ~66): add the delegation branch:
  1. If the task has `## Delegation Contract` AND the `parrot-targeted-writer`
     MCP server is available → call `writer_generate(task_path=...)`.
  2. On a contract error → fix the packet (refresh hashes / complete the
     design) or fall back to normal implementation; NEVER hand the task to
     any other coder tool.
  3. On success → read `artifacts/tool-optimizations/<id>/patch.diff`
     with `source_read` in bounded ranges; review EVERY hunk against the
     task's Codebase Contract; if any hunk is wrong → do not apply; edit
     the packet/blocks and regenerate (at most once more), else
     implement normally.
  4. Compute the reviewed hash (`sha256sum` of the patch file — it equals
     `patch_sha256` from the generate result) and call
     `writer_apply(artifact_id, reviewed_sha256)`.
  5. Run the task's real acceptance tests yourself (the writer never
     runs tests); then continue with the existing validate/commit steps.
     Model-written claims of test success are not evidence.
  6. No SDD state mutation is delegated (index/task-file edits stay with
     the thinking model).
- `.claude/agents/sdd-worker.md`: insert the same branch as a new
  sub-step between "### b) Verify Codebase Contract" (line 219) and
  "### c) Implement" (line ~232) named "### b2) Delegated
  implementation (only when a Delegation Contract exists)"; the
  verification checklist in "### d)" gains "□ Delegated patch hunks were
  all reviewed before writer_apply?".
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py`:
  - Parse the packet example in `sdd/templates/task.md` with
    `parse_task_file` + `extract_packet` after substituting the
    `<sha256>` placeholders with real hashes of a temp fixture → it
    validates; with placeholders left in → `invalid_packet`.
  - Key-phrase parity: for each pair (command ↔ skill) assert both
    contain `writer_generate`, `writer_apply`, `source_read`,
    "review", "never" + "another coder" (or the agreed phrase
    `never silently invokes another coder`), and that `writer_generate`
    appears BEFORE `writer_apply` in the text (review-before-apply
    ordering).
  - `sdd-worker.md` contains the b2 step and the new checklist line.
  - Legacy fallback: a TASK file without the section is reported
    `no_delegation_section` by `validate_contract` (proves the legacy
    route is the default), and the command/skill text contains the
    fallback sentence.
  - No delegated SDD mutation: grep that none of the edited docs
    instructs the writer to edit `sdd/` files.

**NOT in scope**: Python changes; docs page (TASK-3092); running an
actual delegation (TASK-3091 writer lifecycle).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/task.md` | MODIFY | Optional `## Delegation Contract` section + examples |
| `sdd/templates/spec.md` | MODIFY | Delegation-eligible modules table; §7 note |
| `.claude/commands/sdd-spec.md` | MODIFY | Eligibility step |
| `.claude/commands/sdd-task.md` | MODIFY | Packet emission rules |
| `.claude/commands/sdd-start.md` | MODIFY | generate → review → apply → test branch |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | Parity with the command |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Parity |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | Parity |
| `.claude/agents/sdd-worker.md` | MODIFY | b2 delegated step + checklist line |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py` | CREATE | Parity / ordering / example-packet tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.contracts import parse_task_file, extract_packet, validate_contract, ContractError   # TASK-3083
from parrot_tools.tool_optimizations.policy import OptimizationPolicy
```

### Existing Signatures to Use
```text
sdd/templates/task.md
  :43  "## Codebase Contract (Anti-Hallucination)"     ← insert the new optional section AFTER this section (before "## Implementation Notes", :77)
sdd/templates/spec.md
  :72  "## 3. Module Breakdown"  :77 "### Module 1: <Name>"  :162 "## 7. Implementation Notes & Constraints"
.claude/commands/sdd-start.md
  :21 "## Steps" … :127 "### 7. Begin Implementation (in the worktree)" … :169 "### 8. Mark Done (in place)"
.agents/skills/sdd-start/SKILL.md
  :58-64 "7. Verify Codebase Contract before editing" ; :65-69 "8. Implement" ; :70-76 "9. Validate"
.agents/skills/sdd-task/SKILL.md
  :59-64 "6. For every task, build a task-specific Codebase Contract" ; :65-73 "7. Reserve task IDs"
.claude/agents/sdd-worker.md
  :219 "### b) Verify Codebase Contract (MANDATORY — Anti-Hallucination)" ; "### c) Implement — EXACTLY as specified" ; "### d) Post-Implementation Verification"
.agents/skills/sdd-spec/SKILL.md
  :230 "### 4. Research the Codebase & Build Codebase Contract" ; :426 "## 6. Codebase Contract ... mandatory"
```

### Does NOT Exist
- ~~A `/sdd-delegate` command~~ — delegation is a branch inside `/sdd-start` and `sdd-worker`, not a new command.
- ~~`writer_generate` running tests or committing~~ — the SDD workflow owns validation and commits (spec).
- ~~Automatic packet generation by `/sdd-task`~~ — packets are authored deliberately for complete tasks only; the command text must say so.
- ~~`.agents/skills/sdd-worker/`~~ — Codex has no worker agent file; Codex parity is the three skills only.
- ~~New files under `sdd/templates/`~~ — the `templates/` gitignore rule would swallow them; only edit the three tracked templates.

---

## Implementation Notes

### Pattern to Follow (the delegation branch, same text in both hosts)
```markdown
#### Delegated implementation (only when the task has `## Delegation Contract`)
1. Call MCP tool `writer_generate` (server `parrot-targeted-writer`) with `task_path`.
2. If it returns `status: error` with a contract code (`stale_target`, `missing_block`, `placeholder_code`, …):
   fix the packet in the task file (refresh hashes with `sha256sum`, complete the design) and retry once,
   or implement the task yourself. Never silently invoke another coder.
3. If it returns `ok`: read `data.patch_path` with `source_read` in ≤350-line ranges and review EVERY hunk
   against the Codebase Contract. Do not apply a patch you have not fully read.
4. Call `writer_apply` with `artifact_id` and `reviewed_sha256 = data.patch_sha256` (verify it equals
   `sha256sum artifacts/tool-optimizations/<id>/patch.diff`).
5. Run the task's acceptance tests yourself; the writer never runs tests and its output is not evidence.
6. Continue with the normal validate → commit → SDD state steps. SDD files are never edited by the writer.
```

### Key Constraints
- Same semantics in Claude commands and Codex skills; tests check
  shared key phrases and ordering, not identical prose.
- Keep the FEAT-466/FEAT-387 content of the command files untouched
  (only insert; do not reflow existing sections).
- The template example must be copy-pasteable and validator-rejectable
  until hashes are filled — say so explicitly.

### References in Codebase
- `sdd/specs/tool-optimizations.spec.md` §2 "Delegation Packet and Writer Contract".
- `packages/ai-parrot-tools/tests/tool_optimizations/fixtures.py` (TASK-3083) — the canonical valid packet.

---

## Acceptance Criteria

- [ ] Template packet example validates once hashes are substituted; with placeholders → `invalid_packet`.
- [ ] Parity test passes for all three command/skill pairs; ordering `writer_generate` < `writer_apply` in every edited workflow doc.
- [ ] `sdd-worker.md` has the b2 step and the checklist line.
- [ ] A legacy TASK file (e.g. `sdd/tasks/active/TASK-3079-*.md`) → `no_delegation_section`.
- [ ] `git diff --stat` shows only the ten files listed; no new files under `sdd/templates/`.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py -v`; log in `artifacts/logs/TASK-3090-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py
import hashlib, re
from pathlib import Path
import pytest
from parrot_tools.tool_optimizations.contracts import ContractError, parse_task_file, extract_packet, validate_contract
from parrot_tools.tool_optimizations.policy import OptimizationPolicy

ROOT = Path(__file__).resolve().parents[4]          # repo root
PAIRS = [(".claude/commands/sdd-spec.md", ".agents/skills/sdd-spec/SKILL.md"),
         (".claude/commands/sdd-task.md", ".agents/skills/sdd-task/SKILL.md"),
         (".claude/commands/sdd-start.md", ".agents/skills/sdd-start/SKILL.md")]

def test_template_example_rejected_until_hashes_filled():
    text = (ROOT / "sdd/templates/task.md").read_text()
    packet_json, blocks = parse_task_file(text)
    with pytest.raises(ContractError) as ei:
        extract_packet(packet_json)
    assert ei.value.code == "invalid_packet"

def test_template_example_validates_with_real_hashes(tmp_path):
    ...build tmp repo matching the template's target/reference paths, substitute "<sha256>" with real digests,
    write the task file, then: assert (await validate_contract(...)).packet.design_complete is True

@pytest.mark.parametrize("cmd,skill", PAIRS)
def test_host_parity_and_ordering(cmd, skill):
    for p in (cmd, skill):
        t = (ROOT / p).read_text()
        if "sdd-start" in p:
            for phrase in ("writer_generate", "writer_apply", "source_read", "never silently invoke"):
                assert phrase in t, (p, phrase)
            assert t.index("writer_generate") < t.index("writer_apply")
        else:
            assert "Delegation Contract" in t

def test_worker_has_delegated_step():
    t = (ROOT / ".claude/agents/sdd-worker.md").read_text()
    assert "### b2)" in t and "writer_apply" in t and "hunks were all reviewed" in t.lower().replace("□ ", "")

async def test_legacy_task_is_not_eligible():
    legacy = next((ROOT / "sdd/tasks").glob("*/TASK-3079-*.md"))
    with pytest.raises(ContractError) as ei:
        await validate_contract(OptimizationPolicy(repo_root=ROOT), legacy.relative_to(ROOT).as_posix())
    assert ei.value.code == "no_delegation_section"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3083 and TASK-3086 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3090-sdd-delegation-workflow.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
