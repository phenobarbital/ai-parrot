---
type: feature
base_branch: dev
feature_id: FEAT-888
projects: [ai-parrot]
tags: [dev-loop, dispatchers, agy, telemetry, ledger-fix]
discovered_from: issue:339fbb135e7f
docs:
  policy: none
  pages: []
  api_modules: []
---

# Feature Specification: agy dispatcher — parse agy 1.5.8 `step_type: "tool"` steps

**Feature ID**: FEAT-888
**Date**: 2026-11-13
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:339fbb135e7f` (minor bug, discovered from `spec:FEAT-887`): `GoogleCodingDispatcher`
maps agy `step_update` events by `step_type == "tool_call"` / `"tool_response"`
(`google_coding.py:493–496` in `_publish_agy_event`, `:549` / `:564` in `_extract_agy_display`).
agy 1.5.8 never emits those step types.

Re-verified live for this spec (agy 1.5.8, `agy --print … --output-format stream-json`, 2026-11-13,
two runs in a scratch directory):

- A tool call is a `step_update` with `step_type: "tool"`, first with `state: "ACTIVE"`, then with
  `state: "DONE"`. Both carry the same `step_index`, a top-level `tool_name`, and
  `tool_info = {name, parameters}`. Only `DONE` adds `duration_seconds` and, when the tool ran,
  `tool_info.output`.
- `run_command` parameters are `{"CommandLine": "<cmd>"}`; `read_file` parameters are `{"Path": "<abs path>"}`.
- A `run_command` output is a text block:
  `Created At: …\nCompleted At: …\nCommand exited with code N.\n\nCommand output:\n<stdout+stderr>`.
  The exit code exists only as that text. The header is English. The command output follows the host
  locale (es_ES `ls` error text on the reference host).
- A `read_file` output is a summary (`"1 lines, 11 bytes"`) with no exit code.
- A command agy refused (default `request-review` permission mode) still emits `ACTIVE` then `DONE`,
  but the `DONE` step has **no** `tool_info.output`. The refusal shows up only in the final `result`
  event (`denied_actions: [{"action": "command", "display_name": "Bash"}]`).

Effect today: no agy dispatch ever publishes `dispatch.tool_use` / `dispatch.tool_result`, so
`SessionHost` never bumps `tool_use_count` (`session_state.py:1174`). The console renders no tool rows
for an agy seat, and `tool_name` / `tool_input` / `is_error` / `result_snippet` are never extracted.

FEAT-887 M8 (agy end-of-attempt replay) needs the same parsing: it records a `CommandOutcome` from each
`DONE` `run_command` step. The issue asks that whichever change lands first own a shared parser.

### Goals
- `_publish_agy_event` publishes `dispatch.tool_use` for an `ACTIVE` `tool` step and `dispatch.tool_result`
  for a `DONE` `tool` step.
- `_extract_agy_display` projects `tool_name` and `tool_input` for a `tool` step. For a `DONE` step it
  also projects `exit_code` and `is_error` (when an exit code is present) and `result_snippet`.
- One module-level, side-effect-free parser, `parse_agy_tool_step()`, returning an `AgyToolStep`, owns
  the 1.5.8 tool-step shape so FEAT-887 M8 can reuse it instead of re-parsing.
- The `tool_call` / `tool_response` branches stay for older agy builds.
- Sanitized live 1.5.8 captures are checked in as test fixtures.

### Non-Goals (explicitly out of scope)
- FEAT-887 M8 itself (`CommandOutcome`, replay, `ExperienceInterceptor`) — it consumes this parser later.
- The `init` event drift: agy 1.5.8 nests `cwd` under `event["init"]` and carries no `model` /
  `session_id`, so `_extract_agy_display`'s `init` branch reads nothing. This is a separate ledger issue,
  filed by this run.
- Mapping `result.denied_actions` to an error. A refused command keeps `is_error` unset (unknown), never
  `False`.
- Deduplicating repeated `ACTIVE` updates for one `step_index` (not observed; see §8 Q1).
- Any change to `session_state.py`, `_shared.py` or other dispatchers.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:0798eb129e8c6c785402ae38cb0669670de1718cdd1b450bedab9b3a1b6fb02b evaluation_digest=sha256:b23fd2e3659a847bf61e07a0f3e318c209afa23806c7a87de71c6730cac12ab7 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

All changes are in `dispatchers/google_coding.py` and its test module:

1. **Parser (module level).** `AgyToolStep` is a frozen Pydantic v2 model with `step_index`, `state`,
   `name`, `parameters`, `output`, `exit_code` and `command_output`. It has the read-only properties
   `command` (`parameters["CommandLine"]`), `done` (`state == "DONE"`) and `is_error` (`None` when
   `exit_code` is `None`, else `exit_code != 0`). `parse_agy_tool_step(step_update)` returns an
   `AgyToolStep` for a dict with `step_type == "tool"` and `None` for anything else; it never raises.
   - `name` comes from `tool_info.name`, falling back to the step's top-level `tool_name`.
   - `parameters` comes from `tool_info.parameters` when that is a dict, else `{}`.
   - `exit_code` comes from the first `Command exited with code (-?\d+)\.` match in `output`.
   - `command_output` is the text after the first `Command output:` marker, stripped of surrounding
     whitespace, including the `\r\n` agy emits.
2. **Event kind.** `_publish_agy_event` gains a `st == "tool"` branch. `state == "ACTIVE"` maps to
   `dispatch.tool_use` and `state == "DONE"` to `dispatch.tool_result`. Any other state stays
   `dispatch.message`, because the states are not pinned beyond these two.
3. **Display projection.** `_extract_agy_display` gains an `elif step_type == "tool":` branch built on
   the parser:
   - `tool_name` = `step.name`, when not empty.
   - `tool_input` = `summarize_tool_input(step.name, <aliased params>)`. The aliases `CommandLine → command`
     and `Path → path` let `summarize_tool_input` recognise the two verified shapes; other keys pass through
     unchanged and fall back to `"<first key>=<value>"`.
   - On `DONE`: `exit_code` and `is_error` only when an exit code was parsed (the same `exit_code` display
     key the codex dispatcher uses, `codex.py:788–790`). `result_snippet` is `command_output` when present,
     else `output`, truncated to 400 characters; it is omitted when there is neither.
4. **Legacy branches** (`tool_call` / `tool_response`) are untouched.

### Component Diagram
```
agy --output-format stream-json
   └─ step_update{step_type:"tool", state, tool_info}
        ├─ _publish_agy_event ── kind: ACTIVE→dispatch.tool_use, DONE→dispatch.tool_result
        └─ _extract_agy_display ── parse_agy_tool_step() ──→ AgyToolStep
                                    (shared with FEAT-887 M8 replay, later)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GoogleCodingDispatcher._publish_agy_event` | modifies | new `st == "tool"` branch (`google_coding.py:493`) |
| `GoogleCodingDispatcher._extract_agy_display` | modifies | new `step_type == "tool"` branch beside `:564` |
| `summarize_tool_input` (`_shared.py:205`) | uses | already imported in `google_coding.py:36` |
| `SessionHost` (`session_state.py:1174`) | consumer, unchanged | `dispatch.tool_use` bumps `tool_use_count` |

### Data Models
```python
class AgyToolStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    step_index: Optional[int] = None
    state: str = ""
    name: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    output: Optional[str] = None
    exit_code: Optional[int] = None
    command_output: Optional[str] = None
```

### New Public Interfaces
```python
# parrot.flows.dev_loop.dispatchers.google_coding
class AgyToolStep(BaseModel): ...
def parse_agy_tool_step(step_update: Any) -> Optional[AgyToolStep]: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: agy tool-step parser + dispatcher mapping | yes | Parser fields, regex, aliases, kind mapping and display keys fixed in §2; fixtures are the checked-in captures | — |

### Module 1: agy tool-step parser and dispatcher mapping
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py`,
  `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py`,
  `packages/ai-parrot/tests/flows/dev_loop/fixtures/agy_1_5_8_tool_steps.jsonl`,
  `packages/ai-parrot/tests/flows/dev_loop/fixtures/agy_1_5_8_denied_command.jsonl`
- **Responsibility**: parse agy 1.5.8 tool steps once; publish tool events and display keys from them.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # google_coding.py (module level, after _SCHEMA_DIR_GITIGNORE, verified :56)
  _AGY_EXIT_CODE_RE = re.compile(r"Command exited with code (-?\d+)\.")
  _AGY_COMMAND_OUTPUT_MARKER = "Command output:"
  _AGY_PARAM_ALIASES = {"CommandLine": "command", "Path": "path"}

  class AgyToolStep(BaseModel):
      """One agy ``step_update`` tool step (``step_type: "tool"``, agy >= 1.5.8)."""
      @property
      def command(self) -> Optional[str]: ...
      @property
      def done(self) -> bool: ...
      @property
      def is_error(self) -> Optional[bool]: ...

  def parse_agy_tool_step(step_update: Any) -> Optional[AgyToolStep]:
      """Parse one agy 1.5.8 tool ``step_update``; ``None`` for any other step. Never raises."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `TestAgyToolStepParser::test_done_run_command_success` | M1 | fixture exit-0 step → `exit_code == 0`, `is_error is False`, `command == "echo hello"`, `command_output == "hello"` |
| `TestAgyToolStepParser::test_done_run_command_failure` | M1 | fixture exit-2 step → `exit_code == 2`, `is_error is True`, `command_output` holds the localized `ls` error |
| `TestAgyToolStepParser::test_active_step_has_no_output` | M1 | `ACTIVE` step → `done is False`, `output is None`, `exit_code is None` |
| `TestAgyToolStepParser::test_read_file_has_no_exit_code` | M1 | `read_file` `DONE` → `exit_code is None`, `is_error is None`, `parameters["Path"]` kept |
| `TestAgyToolStepParser::test_denied_command_done_without_output` | M1 | denied fixture `DONE` → `output is None`, `is_error is None` |
| `TestAgyToolStepParser::test_non_tool_and_malformed_return_none` | M1 | `agent_response`, `user_input`, non-dict, `tool_info` not a dict → `None` / tolerant; never raises |
| `TestAgyToolStepEvents::test_fixture_publishes_tool_use_and_result_pairs` | M1 | replaying `agy_1_5_8_tool_steps.jsonl` through `_publish_agy_event` yields 3 `dispatch.tool_use` + 3 `dispatch.tool_result` |
| `TestAgyToolStepEvents::test_fixture_folds_tool_use_count` | M1 | same replay with a bound `SessionHost` → `tool_use_count == 3` |
| `TestAgyToolStepEvents::test_display_keys_for_done_failure` | M1 | `_extract_agy_display` on the exit-2 step → `tool_name == "run_command"`, `tool_input == "ls /nonexistent_dir_xyz"`, `exit_code == 2`, `is_error is True`, `result_snippet` without the `Created At` header |
| `TestAgyToolStepEvents::test_display_keys_for_read_file` | M1 | `read_file` step → `tool_input` is the path, no `is_error`, no `exit_code` |
| `TestAgyToolStepEvents::test_unknown_tool_state_is_message` | M1 | `step_type: "tool"`, `state: "PENDING"` → `dispatch.message` |
| existing `TestAgyEventExtraction::*`, `TestAgyWireFormat::*` | M1 | unchanged; prove the legacy `tool_call` branch still works |

### Integration Tests
| Test | Description |
|---|---|
| — | none; the fixture replay through `_publish_agy_event` + `SessionHost` is the end-to-end check of the fold |

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py
markers: none

### Test Data / Fixtures

Two sanitized live captures from agy 1.5.8 (2026-11-13), one JSON object per line, as emitted:
- `fixtures/agy_1_5_8_tool_steps.jsonl` — `echo hello` (exit 0), `ls /nonexistent_dir_xyz` (exit 2, es_ES
  error text), `read_file note.txt`, then the agent reply and `result`.
- `fixtures/agy_1_5_8_denied_command.jsonl` — a refused `for … sleep` command: `ACTIVE`, then `DONE` without
  `output`; `result.denied_actions` set.

Sanitizing replaces the scratch directory path with `/work/agyprobe` and nothing else.

---

## 5. Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` passes from the
      worktree with `PYTHONPATH=packages/ai-parrot/src`.
- [ ] Replaying the 1.5.8 fixture publishes three `dispatch.tool_use` and three `dispatch.tool_result`
      events, and a bound `SessionHost` ends with `tool_use_count == 3`.
- [ ] `parse_agy_tool_step` and `AgyToolStep` are importable from
      `parrot.flows.dev_loop.dispatchers.google_coding` and never raise on malformed input.
- [ ] The `tool_call` / `tool_response` branches are still present and their existing tests pass.
- [ ] `ruff check` and `black --check` (line length 120) pass on the changed Python files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.flows.dev_loop import GoogleCodingDispatcher  # verified: test_google_coding_dispatcher.py:15-23
from parrot.flows.dev_loop.dispatchers._shared import summarize_tool_input  # verified: google_coding.py:36
from parrot.flows.dev_loop.dispatchers._shared import _SESSION_HOST_CTX  # verified: test_google_coding_dispatcher.py:315
from parrot.flows.dev_loop.session_state import SessionHost  # verified: google_coding.py:49
from pydantic import BaseModel, ValidationError  # verified: google_coding.py:21 (ConfigDict, Field added by this feature)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py
class GoogleCodingDispatcher:  # line 59
    async def _stream_stdout_events(self, stdout, *, stream_key, run_id, node_id)
        -> Tuple[Optional[Dict[str, Any]], str]  # line 424; calls _publish_agy_event at :473
    async def _publish_agy_event(self, stream_key: str, event: Dict[str, Any], run_id: str, node_id: str) -> None  # line 477
        # :491-496 step_update → kind by step_type "tool_call"/"tool_response"
    @staticmethod
    def _extract_agy_display(event: Dict[str, Any]) -> Dict[str, Any]  # line 509
        # :549 tool_call branch, :564 tool_response branch, :577 text_delta

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
def summarize_tool_input(tool_name: str, tool_input: Any, *, max_chars: int = TOOL_INPUT_MAX_CHARS) -> str  # line 205
    # recognises command/cmd and file_path/path/notebook_path; falls back to "<first key>=<value>"

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
class DispatchToolUse(_DispatchAction):  # line 620, tool_name: str = ""
class DispatchToolResult(_DispatchAction):  # line 625
# :1174-1175 dispatch tool_use → tool_use_count + 1
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `parse_agy_tool_step` | `_extract_agy_display` | new `elif step_type == "tool":` | `google_coding.py:564` |
| `st == "tool"` kind branch | `_publish_agy_event` | `kind = "dispatch.tool_use"` / `"dispatch.tool_result"` | `google_coding.py:493` |
| fixtures | test module | `Path(__file__).parent / "fixtures" / …` | new directory |

### Does NOT Exist (Anti-Hallucination)
- ~~`step_type == "tool_call"` / `"tool_response"` in agy 1.5.8 stream-json~~ — 1.5.8 emits `step_type: "tool"`
  (verified live twice, 2026-11-13).
- ~~a numeric exit-code field on an agy tool step~~ — only the text `Command exited with code N.` inside
  `tool_info.output`.
- ~~`tool_info.output` on a refused command's `DONE` step~~ — absent. The refusal is only in `result.denied_actions`.
- ~~top-level `model` / `cwd` / `session_id` on the agy 1.5.8 `init` event~~ — `cwd` sits under
  `event["init"]`; out of scope here (separate ledger issue).
- ~~`import re` in `google_coding.py`~~ — added by this feature.
- ~~`packages/ai-parrot/tests/flows/dev_loop/fixtures/`~~ — created by this feature.

### Edit Sites (Blueprint Anchors)

Verified against: `041d6873a8`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `from pydantic import BaseModel, ValidationError` | `google_coding.py:21` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `_SCHEMA_DIR_GITIGNORE = ".gitignore"` | `google_coding.py:56` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `            if st == "tool_call":` | `google_coding.py:493` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `                    elif step_type == "tool_response":` | `google_coding.py:564` | 1 |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | MODIFY | `class TestAgyEventExtraction:` | `test_google_coding_dispatcher.py:356` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Telemetry never breaks a dispatch: the parser and both branches stay inside the existing
  `try/except Exception` of `_extract_agy_display`, and `parse_agy_tool_step` catches everything itself.
- `_extract_agy_display` stays a `@staticmethod`; the parser is module-level so FEAT-887 M8 can import it
  without a dispatcher instance.
- `black` line length 120; Google-style docstrings; strict type hints.

### Known Risks / Gotchas
- In a worktree the shared venv imports the main checkout; run pytest with `PYTHONPATH=packages/ai-parrot/src`.
- `command_output` keeps agy's locale-dependent text. Never assert on it beyond substring checks that hold
  for the captured fixture.
- An `ACTIVE` step has no `output`. Never derive `is_error` from it.

### External Dependencies
None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:0798eb129e8c6c785402ae38cb0669670de1718cdd1b450bedab9b3a1b6fb02b evaluation_digest=sha256:b23fd2e3659a847bf61e07a0f3e318c209afa23806c7a87de71c6730cac12ab7 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/fb851031-71db-44e8-b8ad-30e30e3b7ada/scratchpad/dev-clone/sdd/specs/dispatchers-google-coding-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, dev-loop, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: agy, dispatchers, ledger-fix, telemetry
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
      "dev-loop",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "agy",
      "dispatchers",
      "ledger-fix",
      "telemetry"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/fb851031-71db-44e8-b8ad-30e30e3b7ada/scratchpad/dev-clone/sdd/specs/dispatchers-google-coding-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:b23fd2e3659a847bf61e07a0f3e318c209afa23806c7a87de71c6730cac12ab7",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:0798eb129e8c6c785402ae38cb0669670de1718cdd1b450bedab9b3a1b6fb02b",
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

- [ ] Q1. Can one tool step emit several `ACTIVE` updates (for example progress on a long-running command)?
  If so, `tool_use_count` would over-count. — *Unverified*: the long-running probe was refused by agy's
  permission mode, and running it with `--dangerously-skip-permissions` was not authorized in this session.
  The implementation does not deduplicate. Revisit if agy seat counts look inflated.
- [x] Q2. Fix in the FEAT-887 spec or a new feature? — *Resolved (/sdd-fix plan)*: new feature. FEAT-887 has
  no task index (`open: false`); its M8 will import `parse_agy_tool_step` from here.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `none` — dispatcher telemetry fix; the new helper is documented by its docstrings, and no
  wiki page describes agy stream parsing.
- **Pages**: none.
- **API modules**: none.

---

## Worktree Strategy

One feature worktree `feat-FEAT-888-dispatchers-google-coding-fixes` off `origin/dev`.

- Module graph: one module, no edges.
- Shared files: none.
- Exclusive resources: none.
- Cross-feature: FEAT-887 M8 later modifies the same file next to `:564` and should import
  `parse_agy_tool_step` rather than re-parse.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-13 | Jesus Lara | Created by /sdd-fix from `issue:339fbb135e7f` (fixgroup:08e4293dd899) |
