# TASK-3083: Delegation contracts — TASK-file packet parser, labelled code blocks, scope/freshness validation

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3079, TASK-3082
**Assigned-to**: unassigned

---

## Context

Spec §2 "Delegation Packet and Writer Contract" (first half: the packet,
eligibility, references, code blocks), §3 Module M4, AC7. This module
decides, **before any model call**, whether a TASK file is eligible for
delegation. A stale or incomplete contract returns to the thinking model
with a precise error; the delegate never explores.

**Decisions fixed here:**

1. A TASK file is eligible when it contains exactly one level-2 heading
   `## Delegation Contract` whose section contains exactly one fenced
   block with info string `json` (optionally `json packet`). The block is
   strict JSON (no comments, no trailing commas) validated as
   `DelegationPacket` (TASK-3079, `extra="forbid"`).
2. Implementation blocks are fenced code blocks anywhere in the same TASK
   file whose info string is `<lang> id=<block-id>` (e.g.
   ```` ```python id=impl-models ````). `block-id` matches
   `^[a-z0-9][a-z0-9._-]{0,63}$` and must be unique in the file.
   `DelegationPacket.implementation_blocks` and `TargetFile.blocks` refer
   to these ids.
3. Placeholder detection (spec: "unresolved placeholder code") uses this
   fixed regex list applied to each implementation block:
   `^\s*\.\.\.\s*$` (bare ellipsis line), `\bTODO\b`, `\bFIXME\b`,
   `\bXXX\b`, `<[A-Za-z][A-Za-z0-9 _-]*>` (angle-bracket placeholder),
   `raise NotImplementedError`, `pass\s+#\s*implement`. Any match →
   `placeholder_code` with block id + line.
4. The packet's serialized identity is
   `packet_sha256 = sha256(compact_json(packet.model_dump(mode="json")))`
   using `policy.compact_json` from TASK-3079.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/contracts.py`:
  - `class CodeBlock(BaseModel)`: `block_id`, `language`, `text`,
    `start_line` (line of the opening fence in the TASK file).
  - `class ResolvedReference(BaseModel)`: `slice: ReferenceSlice`,
    `content: str` (the bounded text), `current_sha256: str`.
  - `class ValidatedContract(BaseModel)`: `task_path: str` (repo-relative),
    `packet: DelegationPacket`, `packet_sha256: str`,
    `blocks: dict[str, CodeBlock]` (only the referenced ones),
    `references: list[ResolvedReference]`, `targets_state: dict[str, str | None]`
    (path → current sha256 or `None` when absent), `context_bytes: int`.
  - `class ContractError(ValueError)` carrying `code: str`,
    `details: dict[str, Any]`. Codes (each one a test case):
    `task_not_found`, `task_outside_root`, `no_delegation_section`,
    `duplicate_delegation_section`, `no_packet_block`,
    `duplicate_packet_block`, `invalid_packet_json`, `invalid_packet`
    (Pydantic errors summarised; covers unknown fields, wrong
    `schema_version`, `design_complete` false), `duplicate_block_id`,
    `missing_block`, `placeholder_code`, `scope_path_invalid` (absolute,
    `..`, outside root, secret, symlink), `target_exists_for_create`,
    `target_missing_for_modify`, `stale_target` (sha mismatch),
    `stale_reference`, `reference_range_invalid`, `underspecified_create`
    (a `create` target whose blocks contain no block tagged with the
    target path — see rule below), `invalid_validation_command`
    (empty argv, non-string item, item starting with `-` as argv[0], or
    program not in the allow-list `{"pytest", "ruff", "black", "mypy", "python", "python3"}`),
    `context_budget_exceeded`, `packet_too_large`.
  - `def parse_task_file(text: str) -> tuple[str, dict[str, CodeBlock]]`:
    returns the raw packet JSON text and all labelled blocks. Fence
    parsing: lines starting with three or more backticks; track fence
    length so nested shorter fences inside a block are literal; info
    string parsed as `<lang>` + `key=value` tokens.
  - `def extract_packet(json_text: str) -> DelegationPacket`.
  - `def find_placeholders(block: CodeBlock) -> list[tuple[int, str]]`.
  - `async def validate_contract(policy: OptimizationPolicy, task_path: str, *, limits_override: WriterLimits | None = None) -> ValidatedContract`:
    1. Resolve `task_path` with `resolve_operand(policy, task_path, must_exist=True)`.
    2. Read the TASK file through `read_line_range` from TASK-3082 with a
       generous range (`1..200_000`, `max_line_bytes=policy.max_result_bytes`)
       — never `read_text()` (consistency with the reader's allocation
       rules). Size cap: TASK file > `limits.max_packet_bytes` → `packet_too_large`.
    3. Parse, extract, validate packet.
    4. For each `implementation_blocks` id and each `TargetFile.blocks`
       id: must exist (`missing_block`), no placeholders.
    5. **CREATE rule**: for `action="create"` targets, at least one of
       the target's blocks must have info-string attribute
       `path=<target path>` (e.g. ```` ```python id=impl-x path=pkg/x.py ````)
       — that block IS the file content. Otherwise `underspecified_create`.
    6. Targets: resolve each path (`must_exist=False`); `create` → must
       not exist; `modify` → must exist and
       `sha256_stream(...) == expected_sha256` (from TASK-3082 helpers).
       Fill `targets_state`.
    7. References: resolve; `sha256_stream == slice.sha256`
       (`stale_reference`); range within file and
       `end - start + 1 <= policy.max_lines` (`reference_range_invalid`);
       load content with `read_line_range`.
    8. Validation commands allow-list check (argv only; never executed here).
    9. Context accounting: `context_bytes = measure_json_bytes(packet dump) + Σ len(block.text.encode()) + Σ len(ref.content.encode())`;
       `> limits.max_context_bytes` → `context_budget_exceeded`.
       `limits = limits_override or packet.limits`.
    10. Return `ValidatedContract` with `packet_sha256`.
  - `def render_prompt_sections(contract: ValidatedContract) -> dict[str, str]`:
    deterministic strings (`packet`, `references`, `blocks`,
    `acceptance`) that TASK-3085 concatenates into the prompt. Keep the
    format stable (tests snapshot it): each section is a Markdown
    heading + fenced content; references are rendered as
    `### <path> @ <sha[:12]> lines <start>-<end> — <purpose>`.
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_contracts.py`
  with a fixture directory of TASK markdown samples generated in-test
  (`tmp_path`), including one COMPLETE valid packet reused by TASK-3085
  and TASK-3090 (`fixtures/valid_task.md` builder function `make_valid_task(repo: Path) -> Path`
  exported from `tests/tool_optimizations/fixtures.py`).

**NOT in scope**: model calls, patch handling, artifacts (TASK-3084/3085),
SDD template changes (TASK-3090).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/contracts.py` | CREATE | Parser + validator + prompt sections |
| `packages/ai-parrot-tools/tests/tool_optimizations/fixtures.py` | CREATE | `make_valid_task()`, `make_repo_with_target()` helpers |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_contracts.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.models import DelegationPacket, TargetFile, ReferenceSlice, WriterLimits   # TASK-3079
from parrot_tools.tool_optimizations.policy import OptimizationPolicy, resolve_operand, compact_json, measure_json_bytes, SymlinkRejectedError
from parrot_tools.tool_optimizations.reader import read_line_range, sha256_stream, stat_regular, LineTooLargeError, InvalidEncodingError, RangeOutOfBoundsError   # TASK-3082
from parrot.tools.repo.confinement import PathOutsideRootError, SecretFileError   # confinement.py:55, :59
```

### Existing Signatures to Use
```python
# TASK-3079 models.py (verify after it lands)
class DelegationPacket(BaseModel):   # schema_version: Literal[1]; task_id; spec_path; design_complete: Literal[True];
                                     # targets: list[TargetFile]; references: list[ReferenceSlice];
                                     # implementation_blocks: list[str]; acceptance_criteria: list[str];
                                     # validation_commands: list[list[str]]; limits: WriterLimits
class TargetFile(BaseModel):         # path; action: Literal["create","modify"]; expected_sha256: str|None; planned_changes; blocks: list[str]
class ReferenceSlice(BaseModel):     # path; sha256; start_line; end_line; purpose

# TASK-3082 reader.py
def read_line_range(path: Path, start_line: int, end_line: int, *, max_line_bytes: int) -> RangeRead   # .lines .actual_end .eof
def sha256_stream(path: Path, *, deadline_seconds: float) -> str
def stat_regular(path: Path) -> FileIdentity

# sdd/templates/task.md — the file TASK-3090 will extend; today it has NO "## Delegation Contract" section (verified by grep).
# .claude/agents/sdd-worker.md:219 — "### b) Verify Codebase Contract" (where TASK-3090 inserts the delegation stage)
```

### Does NOT Exist
- ~~`## Delegation Contract` in any existing TASK file~~ — legacy tasks have none and are simply ineligible (`no_delegation_section`), never auto-converted.
- ~~A YAML packet format~~ — JSON only.
- ~~`markdown`/`mistune`/`commonmark` parsers~~ — not dependencies; write the small fence scanner by hand.
- ~~Fuzzy hash matching or "refresh hashes automatically"~~ — a stale hash is an error returned to the thinking model (spec: "refresh hashes at execution-time validation" is the SDD workflow's job, TASK-3090).
- ~~Executing `validation_commands`~~ — never here, never in the writer (spec: sdd-start/sdd-worker owns validation).

---

## Implementation Notes

### Pattern to Follow
```python
_FENCE = re.compile(r"^(?P<fence>`{3,})(?P<info>.*)$")

def parse_task_file(text: str) -> tuple[str, dict[str, CodeBlock]]:
    packet_json: list[str] = []; blocks: dict[str, CodeBlock] = {}
    in_block = None; fence_len = 0; buf: list[str] = []; section_count = 0; in_section = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if in_block is None and line.startswith("## "):
            in_section = line.strip() == "## Delegation Contract"
            if in_section: section_count += 1
            continue
        m = _FENCE.match(line)
        if in_block is None and m:
            in_block = _parse_info(m.group("info")); fence_len = len(m.group("fence")); buf = []; in_block["start"] = lineno
            in_block["in_section"] = in_section; continue
        if in_block is not None and m and len(m.group("fence")) >= fence_len and not m.group("info").strip():
            _close_block(in_block, buf, packet_json, blocks); in_block = None; continue
        if in_block is not None: buf.append(line)
    if section_count == 0: raise ContractError("no_delegation_section")
    if section_count > 1: raise ContractError("duplicate_delegation_section")
    if len(packet_json) == 0: raise ContractError("no_packet_block")
    if len(packet_json) > 1: raise ContractError("duplicate_packet_block")
    return packet_json[0], blocks
```

### Example of a COMPLETE eligible TASK excerpt (also the test fixture)
````markdown
## Delegation Contract

```json
{
  "schema_version": 1,
  "task_id": "TASK-9999",
  "spec_path": "sdd/specs/example.spec.md",
  "design_complete": true,
  "targets": [
    {"path": "pkg/greeter.py", "action": "create", "expected_sha256": null,
     "planned_changes": "New module with greet()", "blocks": ["impl-greeter"]},
    {"path": "pkg/__init__.py", "action": "modify", "expected_sha256": "<sha of current file>",
     "planned_changes": "Export greet", "blocks": ["impl-init"]}
  ],
  "references": [
    {"path": "pkg/__init__.py", "sha256": "<same sha>", "start_line": 1, "end_line": 3, "purpose": "existing exports"}
  ],
  "implementation_blocks": ["impl-greeter", "impl-init"],
  "acceptance_criteria": ["pytest tests/test_greeter.py passes"],
  "validation_commands": [["pytest", "tests/test_greeter.py", "-q"]]
}
```

```python id=impl-greeter path=pkg/greeter.py
def greet(name: str) -> str:
    """Return a greeting."""
    return f"hello {name}"
```

```python id=impl-init
# Apply to pkg/__init__.py: add after the existing imports
from .greeter import greet
__all__ = [*__all__, "greet"]
```
````

### Key Constraints
- Everything here is deterministic and offline; no network, no model.
- Error messages must tell the thinking model exactly what to fix
  (`details` carries block ids, paths, expected vs current sha).
- Keep `validate_contract` async only for the `asyncio.to_thread` file
  work; parsing is pure.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/code_toolkit.py:30-40` — `CodingTask.files_in_scope`/`constraints` (conceptual precedent for scope; NOT reused).
- `packages/ai-parrot-tools/src/parrot_tools/code_toolkit.py` `parse_frontmatter` (exported, see `tests/test_code_toolkit.py:1-11`) — precedent for a hand-written markdown scanner.

---

## Acceptance Criteria

- [ ] Every `ContractError` code listed in Scope has a test that triggers exactly it.
- [ ] Valid fixture validates: `packet_sha256` is stable across two runs; `context_bytes` equals the documented formula.
- [ ] A nested shorter fence inside an implementation block is preserved literally.
- [ ] Placeholder rule: a block with a bare `...` line fails; a block containing the string `"..."` inside a normal expression (e.g. `x = "..."`) passes (the regex is line-anchored).
- [ ] `create` target without a `path=`-tagged block → `underspecified_create`; existing file → `target_exists_for_create`.
- [ ] Modified target after packet creation → `stale_target` with `expected` and `current` in details; same for references.
- [ ] `validation_commands: [["rm", "-rf", "/"]]` → `invalid_validation_command`; nothing is executed (monkeypatch `subprocess`/`asyncio.create_subprocess_exec` to assert no call).
- [ ] `context_budget_exceeded` triggers before any expensive work when blocks alone exceed `max_context_bytes`.
- [ ] `render_prompt_sections` snapshot test passes.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_contracts.py -v`; lint clean; log in `artifacts/logs/TASK-3083-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_contracts.py
import hashlib, json
from pathlib import Path
import pytest
from parrot_tools.tool_optimizations.contracts import ContractError, parse_task_file, validate_contract
from parrot_tools.tool_optimizations.policy import OptimizationPolicy
from .fixtures import make_valid_task, make_repo_with_target

async def test_valid_task_validates(tmp_path):
    repo = make_repo_with_target(tmp_path)          # pkg/__init__.py exists with known sha
    task = make_valid_task(repo)                    # writes sdd/tasks/active/TASK-9999-x.md with real shas
    contract = await validate_contract(OptimizationPolicy(repo_root=repo), task.relative_to(repo).as_posix())
    assert contract.packet.task_id == "TASK-9999" and set(contract.blocks) == {"impl-greeter", "impl-init"}
    assert contract.targets_state["pkg/greeter.py"] is None

@pytest.mark.parametrize("mutator,code", [
    (lambda t: t.replace("## Delegation Contract", "## Something"), "no_delegation_section"),
    (lambda t: t + "\n## Delegation Contract\n", "duplicate_delegation_section"),
    (lambda t: t.replace('"schema_version": 1', '"schema_version": 2'), "invalid_packet"),
    (lambda t: t.replace('"design_complete": true', '"design_complete": true, "extra": 1'), "invalid_packet"),
    (lambda t: t.replace('"impl-init"]', '"impl-missing"]'), "missing_block"),
    (lambda t: t.replace("return f\"hello {name}\"", "..."), "placeholder_code"),
    (lambda t: t.replace('["pytest", "tests/test_greeter.py", "-q"]', '["rm", "-rf", "/"]'), "invalid_validation_command"),
])
async def test_error_codes(tmp_path, mutator, code):
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    task.write_text(mutator(task.read_text()))
    with pytest.raises(ContractError) as ei:
        await validate_contract(OptimizationPolicy(repo_root=repo), task.relative_to(repo).as_posix())
    assert ei.value.code == code

async def test_stale_target_and_reference(tmp_path):
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    (repo / "pkg" / "__init__.py").write_text("changed\n")
    with pytest.raises(ContractError) as ei:
        await validate_contract(OptimizationPolicy(repo_root=repo), task.relative_to(repo).as_posix())
    assert ei.value.code in {"stale_target", "stale_reference"} and "current" in ei.value.details

async def test_no_subprocess_ever(tmp_path, monkeypatch):
    import asyncio, subprocess
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: pytest.fail("spawned"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned"))
    repo = make_repo_with_target(tmp_path); task = make_valid_task(repo)
    await validate_contract(OptimizationPolicy(repo_root=repo), task.relative_to(repo).as_posix())
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3079 and TASK-3082 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3083-delegation-contracts.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5, session_01G9NM1TzdkFLd5foNDmh72K)
**Date**: 2026-09-10
**Notes**:

Created `contracts.py` (hand-written fence scanner, packet extraction,
placeholder detection, scope/freshness validation, prompt rendering) plus
`tests/tool_optimizations/fixtures.py` with the canonical
`make_valid_task()` / `make_repo_with_target()` builders that TASK-3085 and
TASK-3090 reuse. 28 tests in `test_contracts.py`, 149 across the feature
suite.

Every `ContractError` code in the task's Scope list has a test that
triggers exactly it — including the pairs that are easy to conflate
(`invalid_packet_json` vs `invalid_packet`, `no_packet_block` vs
`duplicate_packet_block`, `target_exists_for_create` vs
`target_missing_for_modify`).

Design points worth carrying forward:

- **The fixture computes real digests from the repo it just built**, so it
  can never rot into a permanently-stale packet. `stale_target` is then
  provoked by actually editing the file, which is what makes that test
  meaningful.
- **Ordering is deliberate: cheap structural checks first.** Command
  allow-list and block/placeholder resolution run before any hashing, and
  the packet+blocks context check runs before reference loading — so
  `context_budget_exceeded` is raised without doing the expensive work, as
  the acceptance criteria require.
- **`test_no_subprocess_ever` monkeypatches four spawn entry points**
  (`asyncio.create_subprocess_exec`/`_shell`, `subprocess.run`/`Popen`) and
  still validates a packet whose `validation_commands` name pytest. This is
  the guarantee that `validation_commands` is data, never an execution path.
- The nested-fence test proves a ```` ```python ```` block inside a
  ````` ````markdown ````` block is preserved literally, which is why the
  scanner tracks fence length instead of matching the first closing fence.
- The placeholder regexes are line-anchored where it matters: a bare `...`
  line fails, while `x = "..."` inside an expression passes.

Two small implementation choices, both covered by tests:

1. Labelled blocks are collected from anywhere in the TASK file, while the
   packet block is only recognized *inside* the `## Delegation Contract`
   section. A `json` block carrying an `id=` is treated as an
   implementation block, not as a second packet.
2. `render_prompt_sections` emits a blank line between the acceptance
   heading and its list, matching the other three sections (the only change
   made to the renderer after the snapshot test was written).

**Testing**: 149 tests pass; ruff and black clean. Log at
`artifacts/logs/TASK-3083-pytest.log`.

**Deviations from spec**: none.
