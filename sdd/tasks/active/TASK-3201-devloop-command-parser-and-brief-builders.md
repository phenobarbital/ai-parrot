# TASK-3201: `/devloop` command parser and brief builders

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3200, TASK-3196
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Turns the slash-command text into a `DevLoopCommand` and the
command + requester + config into a validated dev-loop brief written to a temp
JSON file the headless child loads (TASK-3198 `load_headless_brief`). The
default rules for bug and feature briefs are fixed in spec §7 ("Bug defaults",
"Feature defaults", Q2, Q4). `DevRequestBrief.flow_type` / `base_branch` are
added by TASK-3196 (core lane); this task sets them only when `--base` is given,
and must not land before TASK-3196 (it would fail model validation).

---

## Scope

- `devloop/parser.py`: `USAGE` text; `parse_command(text) -> DevLoopCommand` using `shlex.split` + `argparse` (`exit_on_error=False`, `add_help=False`); bare first word `status|cancel|help` selects a subcommand (`cancel <run-id>`); otherwise `action="dispatch"` with `--type {feature,bug}` mandatory; flags `--jira KEY`, `--base {dev,staging}`, `--title "…"`, `--component NAME`, `--ac "<cmd>"`; the remainder is the prompt. `--type enhancement` (or any other value) raises `CommandSyntaxError` naming `feature|bug` (Q4). Slack caps slash text at 3000 chars — do not enforce here, just document.
- `devloop/briefs.py`: `build_bug_brief(command, requester, config, *, reporter, escalation_assignee) -> WorkBrief`; `build_feature_brief(command, config) -> DevRequestBrief`; `brief_to_file(brief, directory, run_id) -> str` (JSON via `model_dump(mode="json")`, file mode `0600`); `brief_summary_fields(brief) -> dict[str, str]` for the confirm card.
- Tests: `test_parser.py`, `test_briefs.py`.

**NOT in scope**: identity resolution (service/Slack lane), spawning, Slack blocks, `enhancement` support on Slack.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/parser.py` | CREATE | `USAGE`, `parse_command` |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/briefs.py` | CREATE | brief builders, temp file writer, summary fields |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` | MODIFY | re-export `parse_command`, `USAGE`, builders |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_parser.py` | CREATE | parser tests |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_briefs.py` | CREATE | builder tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import argparse, json, os, shlex, tempfile      # stdlib
from parrot.flows.dev_loop import WorkBrief, ShellCriterion      # verified: packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py:71,73
from parrot.flows.dev_flow.models import DevRequestBrief         # verified: packages/ai-parrot/src/parrot/flows/dev_flow/models.py:61
from parrot.integrations.devloop.models import (                 # created by TASK-3200
    CommandSyntaxError, DevLoopCommand, DevLoopIntegrationConfig, Requester, RequestType,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class ShellCriterion(_AcceptanceCriterionBase):            # line 56
    kind: Literal["shell"] = "shell"; command: str          # + name: str (required), timeout_seconds: int = 300, expected_exit_code: int = 0 (lines 40-42)
WorkKind = Literal["bug", "enhancement", "new_feature"]     # line 116
class WorkBrief(BaseModel):                                 # line 138
    kind: WorkKind = "bug"                                  # line 151
    summary: str            # min_length=10, max_length=255   line 161
    description: str = ""                                   # line 170
    affected_component: str                                 # line 178 — REQUIRED, no default
    log_sources: List[LogSource] = []                       # line 179
    acceptance_criteria: List[AcceptanceCriterion]          # line 180 — min_length=1
    escalation_assignee: str                                # line 181 — REQUIRED
    reporter: str                                           # line 185 — REQUIRED
    existing_issue_key: Optional[str] = None                # line 189
    flow_type: Optional[Literal["feature", "hotfix"]] = None   # line 219 — None ⇒ bug→hotfix
    base_branch: Optional[str] = None                       # line 226 — None ⇒ hotfix→main / feature→dev

# packages/ai-parrot/src/parrot/flows/dev_flow/models.py
DevRequestKind = Literal["enhancement", "new_feature"]
class DevRequestBrief(BaseModel):                           # line 61
    kind: DevRequestKind; title: str (min 1); description: str (min 1); context: str = ""
    jira_issue_key: str | None = None; dev_agents: ... = None; judge_panel: ... = None
    # flow_type / base_branch: ADDED BY TASK-3196 — verify they exist before setting them.

# packages/ai-parrot-integrations/src/parrot/integrations/devloop/models.py  (TASK-3200)
class DevLoopCommand(BaseModel): action; type; prompt; title; jira_issue_key; base_branch; component; acceptance_command; run_id
class DevLoopIntegrationConfig: default_component: str; default_acceptance_criteria: List[Dict[str, Any]]; socket_dir: str
class CommandSyntaxError(DevLoopError): __init__(self, message: str, usage: str = "")
```

### Does NOT Exist
- ~~`DevRequestBrief.flow_type` / `.base_branch` before TASK-3196 lands~~ — grep `base_branch` in `dev_flow/models.py` first; if absent, this task is blocked.
- ~~`FeatureBrief.base_branch`~~ — never added; feature-run base branch travels through the ideation document (spec M3).
- ~~`WorkBrief.affected_component` optional~~ — required string; always set it (`--component` or `config.default_component`).
- ~~`parrot.cli.devloop.intake._slugify` as a public API~~ — private helper (`intake.py:43`); copy the three regexes into `briefs.py` instead of importing.
- ~~`SlackCommandRouter` multi-word commands~~ — the router dispatches on one word; `status/cancel/help` are parsed HERE from `text`.
- ~~`click` for parsing~~ — the parser uses stdlib `argparse` only (no Click context in a Slack handler).
- ~~`parrot.flows.dev_loop.models.parse_brief` for building~~ — that is the *loader* (used by the child); builders construct the models directly.

---

## Implementation Notes

### Pattern to Follow
```python
# argparse without SystemExit — parse errors must become CommandSyntaxError for an ephemeral reply.
parser = argparse.ArgumentParser(prog="/devloop", add_help=False, exit_on_error=False)
try:
    ns, rest = parser.parse_known_args(shlex.split(text))
except argparse.ArgumentError as exc:
    raise CommandSyntaxError(str(exc), usage=USAGE) from exc
```

### Key Constraints
- Defaults (spec §7 "Bug defaults"): `summary` = first line of the prompt clipped to 255; if shorter than 10 chars, prefix `"bug: "` and pad from the description; `description` = prompt; `affected_component` = `--component` or `config.default_component`; `acceptance_criteria` = `[ShellCriterion(name="slack-ac", command=--ac)]` when `--ac` given, else `[ShellCriterion(**d) for d in config.default_acceptance_criteria]`; `existing_issue_key` = `--jira`; `flow_type="feature"` + `base_branch=--base` only when `--base` given.
- Defaults (spec §7 "Feature defaults"): `kind="new_feature"`; `title` = `--title` or the prompt's first sentence (split on `.`/`\n`, ≤80 chars, ≥1 char); `description` = prompt; `jira_issue_key` = `--jira`; `base_branch=--base` + `flow_type="feature"` only when given.
- `brief_to_file` writes `<directory>/<run_id>.brief.json` with `os.open(..., 0o600)`; JSON keeps the `kind` discriminator so `load_headless_brief` routes correctly.
- Never raise `SystemExit`; every user-facing failure is `CommandSyntaxError` or `pydantic.ValidationError` (the service turns both into an ephemeral message).

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/devloop/intake.py:43` — slugify regexes to copy.
- `examples/dev_loop/server_dev.py:266-339` — `_build_dev_brief_from_form` (precedent for feature-brief field mapping; NOT importable).

---

## Implementation Blueprint

### Steps (in order)
1. Verify `grep -n "base_branch" packages/ai-parrot/src/parrot/flows/dev_flow/models.py` shows the TASK-3196 fields — *why*: `build_feature_brief` sets them; without them Pydantic drops/rejects the keys.
2. Write `parser.py` — *why*: pure function, no I/O; test it exhaustively first.
3. Write `briefs.py` — *why*: builders depend only on models + parser output.
4. Extend `devloop/__init__.py` exports; run tests, `ruff`, `black`.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/parser.py` (CREATE)
```python
"""``/devloop`` text → :class:`DevLoopCommand` (spec §3 Module 5, FEAT-555)."""
from __future__ import annotations

import argparse
import shlex

from parrot.integrations.devloop.models import CommandSyntaxError, DevLoopCommand

USAGE = """*Usage*
`/devloop --type feature|bug [--jira KEY] [--base dev|staging] [--title "…"] [--component NAME] [--ac "<cmd>"] <prompt>`
`/devloop status` · `/devloop cancel <run-id>` · `/devloop help`
Types: `feature` (brainstorm + Open Questions) and `bug` (log-driven triage). `enhancement` is not available on Slack yet."""

_SUBCOMMANDS = ("status", "cancel", "help")
_TYPES = ("feature", "bug")


def _build_parser() -> argparse.ArgumentParser:
    """Flag-only parser; positionals are collected as the prompt via parse_known_args."""
    parser = argparse.ArgumentParser(prog="/devloop", add_help=False, exit_on_error=False)
    parser.add_argument("--type", dest="type_", default=None)
    parser.add_argument("--jira", default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--component", default=None)
    parser.add_argument("--ac", default=None)
    return parser


def parse_command(text: str) -> DevLoopCommand:
    """Parse the slash-command text.

    Raises:
        CommandSyntaxError: empty text, unknown flag, bad ``--type``/``--base`` value, missing prompt
            or missing ``--type`` for a dispatch, ``cancel`` without a run id.
    """
    try:
        tokens = shlex.split(text or "")
    except ValueError as exc:  # unbalanced quotes
        raise CommandSyntaxError(f"could not parse command: {exc}", usage=USAGE) from exc
    if not tokens:
        raise CommandSyntaxError("empty command", usage=USAGE)
    if tokens[0].lower() in _SUBCOMMANDS:
        # FILL IN: help → DevLoopCommand(action="help"); status → action="status";
        # cancel → require tokens[1] as run_id else CommandSyntaxError — bounded by AC12.
        raise NotImplementedError
    try:
        ns, rest = _build_parser().parse_known_args(tokens)
    except argparse.ArgumentError as exc:
        raise CommandSyntaxError(str(exc), usage=USAGE) from exc
    # FILL IN: reject any leftover token starting with "--" (unknown flag); validate ns.type_ in _TYPES
    # (message must name `feature|bug`, Q4) and ns.base in (None, "dev", "staging"); prompt = " ".join(rest)
    # non-empty — bounded by spec §7 and AC6/AC10.
    return DevLoopCommand(
        action="dispatch", type=ns.type_, prompt=" ".join(rest).strip(), title=ns.title,
        jira_issue_key=ns.jira, base_branch=ns.base, component=ns.component, acceptance_command=ns.ac,
    )
```
**Why this shape**: `parse_known_args` lets the free-text prompt sit anywhere around the flags; `exit_on_error=False` turns argparse errors into `CommandSyntaxError` instead of `SystemExit` (which would kill the aiohttp handler). The subcommand words are checked before argparse so `/devloop status` never needs `--type`.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/briefs.py` (CREATE)
```python
"""Command + requester + config → validated dev-loop brief (spec §3 Module 5, §7 defaults)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel

from parrot.flows.dev_flow.models import DevRequestBrief  # verified: dev_flow/models.py:61 (+ TASK-3196 fields)
from parrot.flows.dev_loop import ShellCriterion, WorkBrief  # verified: dev_loop/__init__.py:71,73
from parrot.integrations.devloop.models import DevLoopCommand, DevLoopIntegrationConfig, Requester

_SUMMARY_MAX = 255
_SUMMARY_MIN = 10
_TITLE_MAX = 80
_SENTENCE_SPLIT = re.compile(r"[.\n]")


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def build_bug_brief(
    command: DevLoopCommand, requester: Requester, config: DevLoopIntegrationConfig, *, reporter: str, escalation_assignee: str
) -> WorkBrief:
    """Build a ``WorkBrief(kind="bug")`` with the spec §7 defaults (Q2: configured criteria, ``--ac`` overrides)."""
    summary = _first_line(command.prompt)[:_SUMMARY_MAX]
    # FILL IN: if len(summary) < _SUMMARY_MIN → prefix "bug: " and pad from the description; keep ≤255 — bounded by
    # WorkBrief.summary min 10 / max 255 (models/base.py:161).
    criteria = (
        [ShellCriterion(name="slack-ac", command=command.acceptance_command)]
        if command.acceptance_command
        else [ShellCriterion(**d) for d in config.default_acceptance_criteria]
    )
    payload: Dict[str, Any] = {
        "kind": "bug", "summary": summary, "description": command.prompt,
        "affected_component": command.component or config.default_component,
        "acceptance_criteria": criteria, "escalation_assignee": escalation_assignee, "reporter": reporter,
        "existing_issue_key": command.jira_issue_key,
    }
    if command.base_branch:
        payload.update(flow_type="feature", base_branch=command.base_branch)
    return WorkBrief(**payload)


def build_feature_brief(command: DevLoopCommand, config: DevLoopIntegrationConfig) -> DevRequestBrief:
    """Build a ``DevRequestBrief(kind="new_feature")``; title = ``--title`` or the first sentence (≤80 chars)."""
    title = (command.title or "").strip()
    if not title:
        # FILL IN: first sentence of prompt via _SENTENCE_SPLIT, stripped, clipped to _TITLE_MAX, ≥1 char — bounded by
        # DevRequestBrief.title min_length=1 (dev_flow/models.py:61).
        raise NotImplementedError
    payload: Dict[str, Any] = {"kind": "new_feature", "title": title, "description": command.prompt,
                               "jira_issue_key": command.jira_issue_key}
    if command.base_branch:
        payload.update(flow_type="feature", base_branch=command.base_branch)  # TASK-3196 fields
    return DevRequestBrief(**payload)


def brief_to_file(brief: BaseModel, directory: str, run_id: str) -> str:
    """Write ``<directory>/<run_id>.brief.json`` (mode 0600); returns the path."""
    Path(directory).mkdir(parents=True, exist_ok=True, mode=0o700)
    path = os.path.join(directory, f"{run_id}.brief.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(brief.model_dump(mode="json"), fh)
    return path


def brief_summary_fields(brief: BaseModel) -> Dict[str, str]:
    """Display projection for the confirm card (kind, summary/title, component, criteria, jira, base)."""
    # FILL IN: WorkBrief → kind/summary/component/criteria names/jira/base; DevRequestBrief → kind/title/description
    # (first 200 chars)/jira/base — bounded by spec §7 "Confirm card for both kinds".
    raise NotImplementedError
```
**Why this shape**: builders are pure and raise Pydantic errors for the caller to render; `flow_type`/`base_branch` are only set when `--base` is present so `WorkBrief`'s kind-derived default (`bug ⇒ hotfix/main`) is preserved (spec §7). The JSON file keeps `kind` so `load_headless_brief` (TASK-3198) routes on it.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3200: grep -c '^__all__ = \[' packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py)
# BEFORE — insert above `__all__ = [` the imports; then append the names to __all__:
from .briefs import brief_summary_fields, brief_to_file, build_bug_brief, build_feature_brief
from .parser import USAGE, parse_command
```
**Why**: keeps `from parrot.integrations.devloop import parse_command` working for the Slack lane. Re-run the grep after TASK-3200 lands; if `__all__` is split over lines, quote the opening line.

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_parser.py` (CREATE)
```python
"""Tests for parrot.integrations.devloop.parser (TASK-3201)."""
import pytest

from parrot.integrations.devloop.models import CommandSyntaxError
from parrot.integrations.devloop.parser import USAGE, parse_command


def test_dispatch_feature_with_flags() -> None:
    cmd = parse_command('--type feature --jira NAV-1 --base staging --title "Slack card" Ship the status card')
    assert cmd.action == "dispatch" and cmd.type == "feature" and cmd.jira_issue_key == "NAV-1"
    assert cmd.base_branch == "staging" and cmd.title == "Slack card" and cmd.prompt == "Ship the status card"


@pytest.mark.parametrize("text", ["status", "help", "cancel run-abc12345"])
def test_subcommands(text: str) -> None:
    assert parse_command(text).action == text.split()[0]


def test_cancel_requires_run_id() -> None:
    with pytest.raises(CommandSyntaxError):
        parse_command("cancel")


def test_missing_type_is_error() -> None:
    with pytest.raises(CommandSyntaxError) as exc:
        parse_command("just a prompt")
    assert exc.value.usage == USAGE


def test_enhancement_rejected_naming_supported_types() -> None:
    with pytest.raises(CommandSyntaxError, match="feature|bug"):
        parse_command("--type enhancement do it")


# FILL IN: unknown flag → CommandSyntaxError; bad --base → CommandSyntaxError; prompt after flags; empty text.
```

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_briefs.py` (CREATE)
```python
"""Tests for parrot.integrations.devloop.briefs (TASK-3201)."""
import json

from parrot.integrations.devloop.briefs import brief_to_file, build_bug_brief, build_feature_brief
from parrot.integrations.devloop.models import DevLoopCommand, DevLoopIntegrationConfig, Requester

_CFG = DevLoopIntegrationConfig(name="b", enabled=True, default_acceptance_criteria=[
    {"kind": "shell", "name": "unit", "command": "pytest -q"}])
_REQ = Requester(transport="slack", tenant_id="T", user_id="U")


def test_bug_defaults_and_ac_override() -> None:
    cmd = DevLoopCommand(action="dispatch", type="bug", prompt="Sync drops last row\nwhen CSV ends with newline",
                         acceptance_command="pytest packages -q")
    brief = build_bug_brief(cmd, _REQ, _CFG, reporter="r@x", escalation_assignee="e@x")
    assert brief.summary == "Sync drops last row" and brief.affected_component == "ai-parrot"
    assert brief.acceptance_criteria[0].command == "pytest packages -q" and brief.base_branch is None


def test_bug_base_sets_flow_type() -> None:
    cmd = DevLoopCommand(action="dispatch", type="bug", prompt="A long enough bug summary", base_branch="staging")
    brief = build_bug_brief(cmd, _REQ, _CFG, reporter="r", escalation_assignee="e")
    assert brief.flow_type == "feature" and brief.base_branch == "staging"


def test_feature_title_derivation_and_base(tmp_path) -> None:
    cmd = DevLoopCommand(action="dispatch", type="feature", prompt="Add a token budget. Details follow", base_branch="dev")
    brief = build_feature_brief(cmd, _CFG)
    assert brief.title == "Add a token budget" and brief.kind == "new_feature" and brief.base_branch == "dev"
    path = brief_to_file(brief, str(tmp_path), "run-1")
    assert json.load(open(path))["kind"] == "new_feature" and (tmp_path / "run-1.brief.json").stat().st_mode & 0o777 == 0o600


# FILL IN: short summary padding (<10 chars); --title wins; brief_summary_fields for both kinds.
```

### FILL IN checklist
- [ ] `parser.py::parse_command` — subcommand branch, unknown-flag rejection, `--type`/`--base` validation, non-empty prompt; bounded by spec §7 / AC6 / AC10 / AC12.
- [ ] `briefs.py::build_bug_brief` — summary padding rule; bounded by `WorkBrief.summary` (10..255).
- [ ] `briefs.py::build_feature_brief` — first-sentence title; bounded by `DevRequestBrief.title` min 1 / ≤80.
- [ ] `briefs.py::brief_summary_fields` — projection for both kinds; bounded by spec §7 confirm card.
- [ ] Stubbed tests in both test files.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/devloop/test_parser.py packages/ai-parrot-integrations/tests/integrations/devloop/test_briefs.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/devloop`
- [ ] Imports work: `from parrot.integrations.devloop import parse_command, build_bug_brief, build_feature_brief`
- [ ] Spec AC10 defaults hold (bug and feature); AC11 bug half (`--base staging` ⇒ `WorkBrief.base_branch="staging"`, `flow_type="feature"`); `--type enhancement` rejected (Q4)

---

## Test Specification

See the two test blueprints above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/dev-loop-slack.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3201-devloop-command-parser-and-brief-builders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
