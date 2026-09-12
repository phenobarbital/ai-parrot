# TASK-3200: Dev-loop integration models and `devloop:` config section

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and §2 Data Models. This task creates the channel-neutral
`parrot.integrations.devloop` package (G5) and its data contracts. Every other
integration-core task (TASK-3201..3204) and the Slack lane import these models,
so the shapes fixed in spec §2 are not renegotiable here. It also adds the
`devloop:` section to `SlackAgentConfig` so `integrations_bots.yaml` can enable
the feature per bot (spec §2 Configuration, Module 12 consumes it).

---

## Scope

- Create the package `packages/ai-parrot-integrations/src/parrot/integrations/devloop/` with `__init__.py` and `models.py`.
- Implement `DevLoopIntegrationConfig` (dataclass) with `from_dict(name, data)`, `{NAME}_DEVLOOP_*` env fallbacks in `__post_init__` (same pattern as `SlackAgentConfig.__post_init__`), and `validate() -> list[str]`: when `enabled`, `default_acceptance_criteria` must be non-empty and every `command` head must be in `conf.ACCEPTANCE_CRITERION_ALLOWLIST` (Q2, spec §7).
- Implement the Pydantic v2 models `DevLoopCommand`, `Requester` (+ `actor` property), `RunRecord`, `GateView`, `RunEvent`, `BridgeResult` exactly as spec §2 Data Models.
- Implement the exception hierarchy `DevLoopError`, `CommandSyntaxError` (carries `usage`), `NotRunOwnerError(owner_user_id)` (exposes `.owner_user_id` — Slack renders "This run belongs to <@owner>"), `RunNotFoundError`, `SpawnError` (carries `exit_code`, `stderr_tail`).
- Implement the public Pydantic model `PendingConfirmation` (`pending_id`, `kind`, `brief` JSON dict, `fields: dict[str, str]`, `requester`, `channel_id`, `message_ts`, `created_at`, `expires_at`) — cross-lane contract consumed by the service (TASK-3204) and the Slack handlers (TASK-3206/3207).
- Add `devloop: Optional[DevLoopIntegrationConfig] = None` to `SlackAgentConfig` and parse `data.get("devloop")` in `SlackAgentConfig.from_dict`.
- Create the test package `packages/ai-parrot-integrations/tests/integrations/devloop/` (`__init__.py`, `conftest.py` with an in-process fake Redis reused by later tasks) and `test_models.py`.

**NOT in scope**: command parsing (TASK-3201), subprocess/bridge (TASK-3202), tail/registry (TASK-3203), service (TASK-3204), Slack blocks/handlers, manager wiring, pyproject extra (Slack lane).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` | CREATE | Package init re-exporting the models and errors |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/models.py` | CREATE | Config dataclass, Pydantic contracts, exceptions |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` | MODIFY | `devloop` field on `SlackAgentConfig` + `from_dict` parsing |
| `packages/ai-parrot-integrations/tests/integrations/devloop/__init__.py` | CREATE | Empty test package marker |
| `packages/ai-parrot-integrations/tests/integrations/devloop/conftest.py` | CREATE | `FakeRedis` (streams + hash/set/expire) fixture shared by TASK-3203/3204 tests |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from dataclasses import dataclass, field          # stdlib
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field             # pydantic v2 (core dependency)
from navconfig import config                      # verified: packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py:4
from parrot import conf                           # verified: packages/ai-parrot/src/parrot/conf.py (ACCEPTANCE_CRITERION_ALLOWLIST at :851)
from parrot.integrations.slack.models import SlackAgentConfig   # verified: packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py:8
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py
@dataclass
class SlackAgentConfig:                                   # line 8
    name: str; chatbot_id: str; bot_token: Optional[str] = None; ...
    jira_redirect_uri: Optional[str] = None               # line 54 — LAST field today; add `devloop` right after it
    def __post_init__(self):                              # line 56 — env fallback pattern: config.get(f"{self.name.upper()}_SLACK_BOT_TOKEN")
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'SlackAgentConfig':   # line 93
        return cls(..., jira_redirect_uri=data.get("jira_redirect_uri"),)         # line 117 — LAST kwarg today

# packages/ai-parrot/src/parrot/conf.py
ACCEPTANCE_CRITERION_ALLOWLIST: list[str] = config.getlist("ACCEPTANCE_CRITERION_ALLOWLIST", fallback=[...])  # line 851
#   default heads: ["task", "flowtask", "pytest", "ruff", "mypy", "pylint"]

# packages/ai-parrot-integrations/src/parrot/integrations/models.py
class IntegrationBotConfig:  # line 25 — from_dict routes kind == 'slack' → SlackAgentConfig.from_dict(name, agent_data)  (line 64)
```

Package layout (verified with `ls`): `packages/ai-parrot-integrations/src/parrot/` has NO `__init__.py` (PEP 420 namespace); `parrot/integrations/__init__.py` exists; sibling packages `slack/`, `telegram/`, `core/` each have their own `__init__.py`. Tests: `packages/ai-parrot-integrations/tests/integrations/slack/__init__.py` exists (empty); `asyncio_mode = "auto"` (packages/ai-parrot-integrations/pyproject.toml:138).

### Does NOT Exist
- ~~`parrot.integrations.devloop`~~ — does not exist yet; this task creates it. Nothing may import it before this task lands.
- ~~`SlackAgentConfig.devloop`~~ — not a field today; added here.
- ~~`fakeredis`~~ — NOT a declared dependency of any package in this workspace; do not import it. Use the in-process `FakeRedis` from `conftest.py` created here.
- ~~`parrot.flows.dev_loop.ShellCriterion` in this task~~ — the config stores plain dicts; TASK-3201 converts them. Do not import dev_loop models here (keeps `models.py` import-cheap).
- ~~`examples/dev_loop/*`~~ — never importable from package code.
- ~~`DevLoopIntegrationConfig.max_concurrent_runs` default other than `None`~~ — `None` means unlimited (user decision).

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py:56-63 — env fallback in __post_init__
def __post_init__(self):
    if not self.bot_token:
        self.bot_token = config.get(f"{self.name.upper()}_SLACK_BOT_TOKEN")
```

### Key Constraints
- Pydantic v2 for the run-time contracts; a plain dataclass for the config (matches every other integration config).
- `models.py` must stay import-cheap: only stdlib, pydantic, navconfig, `parrot.conf` (lazy, inside `validate`).
- Google docstrings, type hints, `black` 120, `ruff` (TID251).
- `RunRecord` is JSON-round-trippable (`model_dump(mode="json")` / `model_validate_json`) — TASK-3203 stores it in Redis.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` — config dataclass pattern.
- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:257` — `ApprovalGate` fields that `GateView` projects.
- `packages/ai-parrot/tests/flows/dev_loop/test_streaming.py:26` (`_FakeStreamsRedis`, mirrored at `test_streaming_state_view.py:31`) — the in-process fake to COPY into `conftest.py` and extend with `hset`/`hget`/`hgetall`, `sadd`/`srem`/`smembers`, `expire` (not importable across packages).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker.

### Steps (in order)
1. Create `devloop/__init__.py` and `devloop/models.py` with the config dataclass, contracts and errors — *why*: every later task imports these names; landing them first unblocks TASK-3201/3202/3203 in parallel.
2. Add the `devloop` field and `from_dict` parsing to `SlackAgentConfig` (two MODIFY anchors, one occurrence each) — *why*: `IntegrationBotManager` reads the YAML through `SlackAgentConfig.from_dict` (models.py:64), so the section must be parsed there.
3. Create the tests package with `conftest.py` (fake Redis) and `test_models.py` — *why*: TASK-3203/3204 reuse the fake; `fakeredis` is not a dependency.
4. Run `pytest packages/ai-parrot-integrations/tests/integrations/devloop -q`, `ruff check`, `black --check --line-length 120` on the touched files.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py` (CREATE)
```python
"""Channel-neutral dev-loop kick-off integration (FEAT-555).

Transport adapters (Slack today) live next to their platform packages; this
package owns parsing, brief building, subprocess lifecycle, state tailing and
the dispatch service.
"""
from .models import (
    BridgeResult,
    CommandSyntaxError,
    DevLoopCommand,
    DevLoopError,
    DevLoopIntegrationConfig,
    GateView,
    NotRunOwnerError,
    PendingConfirmation,
    Requester,
    RequestType,
    RunEvent,
    RunNotFoundError,
    RunRecord,
    SpawnError,
)

__all__ = [
    "BridgeResult", "CommandSyntaxError", "DevLoopCommand", "DevLoopError", "DevLoopIntegrationConfig",
    "GateView", "NotRunOwnerError", "PendingConfirmation", "Requester", "RequestType", "RunEvent", "RunNotFoundError",
    "RunRecord", "SpawnError",
]
```
**Why this shape**: mirrors `slack/__init__.py`'s explicit re-export list; later tasks append their own names.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/models.py` (CREATE)
```python
"""Data contracts for the dev-loop integration (spec §2 Data Models, FEAT-555)."""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from navconfig import config
from pydantic import BaseModel, Field

RequestType = Literal["feature", "bug"]


class DevLoopError(Exception):
    """Base error for the dev-loop integration."""


class CommandSyntaxError(DevLoopError):
    """Bad ``/devloop`` text; ``usage`` carries the help text to show the user."""

    def __init__(self, message: str, usage: str = "") -> None:
        super().__init__(message)
        self.usage = usage


class NotRunOwnerError(DevLoopError):
    """The actor is not the run's initiator; ``owner_user_id`` lets Slack render "This run belongs to <@owner>"."""

    def __init__(self, owner_user_id: str) -> None:
        super().__init__(f"run belongs to {owner_user_id}")
        self.owner_user_id = owner_user_id


class RunNotFoundError(DevLoopError):
    """No run record for the given id."""


class SpawnError(DevLoopError):
    """The headless child failed before its handshake."""

    def __init__(self, message: str, *, exit_code: Optional[int] = None, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr_tail = stderr_tail


@dataclass
class DevLoopIntegrationConfig:
    """``devloop:`` section of a Slack bot entry (env fallbacks ``{NAME}_DEVLOOP_*``)."""

    name: str = ""
    enabled: bool = False
    repo_path: str = ""
    command: List[str] = field(default_factory=lambda: ["parrot", "devloop", "run"])
    redis_url: str = ""
    socket_dir: str = ""
    use_tcp: bool = False
    default_component: str = "ai-parrot"
    default_acceptance_criteria: List[Dict[str, Any]] = field(default_factory=list)
    status_card: bool = True
    max_concurrent_runs: Optional[int] = None  # None = unlimited (decision)
    run_retention_seconds: int = 86400
    handshake_timeout_seconds: float = 120.0
    cancel_grace_seconds: float = 45.0
    tail_drain_seconds: float = 5.0

    def __post_init__(self) -> None:
        """Apply ``{NAME}_DEVLOOP_REPO_PATH`` / ``_REDIS_URL`` / ``_SOCKET_DIR`` env fallbacks."""
        prefix = f"{self.name.upper()}_DEVLOOP_" if self.name else "DEVLOOP_"
        # FILL IN: for repo_path/redis_url/socket_dir: if empty, read config.get(prefix + KEY) — bounded by the
        # SlackAgentConfig.__post_init__ pattern (slack/models.py:56-63); never override an explicit value.

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "DevLoopIntegrationConfig":
        """Build from the parsed YAML mapping (unknown keys ignored)."""
        # FILL IN: pick each known key with its default — bounded by the field list above (no extra keys).
        raise NotImplementedError

    def validate(self) -> List[str]:
        """Return config errors; empty when valid (spec §7 Q2: criteria mandatory when enabled)."""
        from parrot import conf  # noqa: PLC0415 - keep module import-cheap

        errors: List[str] = []
        # FILL IN: when enabled and not default_acceptance_criteria → error; for each criterion dict the head of
        # shlex.split(command)[0] must be in conf.ACCEPTANCE_CRITERION_ALLOWLIST (conf.py:851) — bounded by AC10.
        return errors
```
**Why this shape**: the dataclass mirrors every other integration config (dataclass + `from_dict` + env fallbacks) so `IntegrationBotConfig` needs no new machinery; `validate()` imports `parrot.conf` lazily so importing the models never boots the whole config. Field names/defaults are fixed by spec §2.

### `packages/ai-parrot-integrations/src/parrot/integrations/devloop/models.py` (CREATE — second half, append below the dataclass)
```python
class DevLoopCommand(BaseModel):
    """Parsed ``/devloop …`` text (spec §2)."""

    action: Literal["dispatch", "status", "cancel", "help"]
    type: Optional[RequestType] = None
    prompt: str = ""
    title: Optional[str] = None
    jira_issue_key: Optional[str] = None
    base_branch: Optional[Literal["dev", "staging"]] = None
    component: Optional[str] = None
    acceptance_command: Optional[str] = None
    run_id: Optional[str] = None


class Requester(BaseModel):
    """Channel-neutral identity of the human behind a command."""

    transport: str
    tenant_id: str = ""
    user_id: str
    display_name: str = ""
    email: str = ""

    @property
    def actor(self) -> str:
        """Stable audit identity used as ``resolved_by`` / ``requested_by``."""
        return f"{self.transport}:{self.tenant_id}:{self.user_id}"


class GateView(BaseModel):
    """Transport-facing projection of ``ApprovalGate`` (session_state.py:257)."""

    gate_id: str
    kind: str
    title: str
    instructions: str = ""
    payload_ref: str = ""
    questions: List[str] = Field(default_factory=list)
    expires_at: Optional[float] = None
    status: str = "pending"
    resolved_by: str = ""
    answers: Dict[str, str] = Field(default_factory=dict)


class RunRecord(BaseModel):
    """One dispatched run; mirrored to Redis at ``devloop:runs:{run_id}`` (TASK-3203)."""

    run_id: str
    kind: RequestType
    title: str
    requester: Requester
    channel_id: str
    thread_ts: str = ""
    command_endpoint: str = ""
    command_token: str = ""
    pid: Optional[int] = None
    phase: str = "starting"
    current_node: str = ""
    pending_gate_id: str = ""
    pr_url: str = ""
    jira_issue_key: str = ""
    error: str = ""
    last_seen_seq: int = 0
    status_message_ts: str = ""
    brief_path: str = ""
    started_at: float
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None


class RunEvent(BaseModel):
    """Reduced session-state action (spec §2)."""

    run_id: str
    kind: Literal["snapshot", "gate_opened", "gate_resolved", "gate_expired", "node_changed",
                  "jira_linked", "run_closed", "run_cancelled", "process_exited"]
    seq: int = 0
    gate: Optional[GateView] = None
    node_id: str = ""
    node_status: str = ""
    state: Optional[Dict[str, Any]] = None
    exit_code: Optional[int] = None
    stderr_tail: str = ""


class BridgeResult(BaseModel):
    """Outcome of a command sent to the child (TASK-3202)."""

    ok: bool
    status: int
    reason: str = ""


class PendingConfirmation(BaseModel):
    """A brief parked behind the confirm card (Q1, both kinds); memory-only, 15 min TTL (TASK-3204 owns the dict)."""

    pending_id: str
    kind: RequestType
    brief: Dict[str, Any]              # brief.model_dump(mode="json"); rebuilt via WorkBrief/DevRequestBrief(**brief)
    fields: Dict[str, str] = Field(default_factory=dict)   # brief_summary_fields() projection shown on the card
    requester: Requester
    channel_id: str
    message_ts: str = ""
    created_at: float
    expires_at: float
```
Also add `PendingConfirmation` to the `__init__.py` import list and `__all__`.
**Why this shape**: these are the spec §2 contracts verbatim; `RunRecord.phase` is a plain `str` (values `starting|running|blocked|completed|failed|cancelled`) so a newer child can add phases without breaking a stored record. Nothing here may change without a spec revision.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` (MODIFY — field)
```python
# occurrences: 1 (verified: grep -c 'jira_redirect_uri: Optional\[str\] = None' packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py)
# AFTER — insert below `    jira_redirect_uri: Optional[str] = None` (verified: slack/models.py:54)
    # Dev-loop kick-off (FEAT-555). ``None`` ⇒ feature disabled for this bot.
    devloop: Optional["DevLoopIntegrationConfig"] = None
```
**Why**: the dataclass field must be declared before `__post_init__`; a string annotation avoids importing the devloop package at module import (add `from parrot.integrations.devloop.models import DevLoopIntegrationConfig` inside `from_dict` only).

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` (MODIFY — from_dict)
```python
# occurrences: 1 (verified: grep -c '            jira_redirect_uri=data.get("jira_redirect_uri"),' packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py)
# AFTER — insert below `            jira_redirect_uri=data.get("jira_redirect_uri"),` (verified: slack/models.py:117)
            # FEAT-555
            devloop=_parse_devloop(name, data.get("devloop")),
```
plus, at module level (below the imports, before `class SlackAgentConfig`):
```python
def _parse_devloop(name: str, raw: Optional[Dict[str, Any]]) -> Optional["DevLoopIntegrationConfig"]:
    """Parse the optional ``devloop:`` mapping; ``None``/empty ⇒ disabled."""
    if not raw:
        return None
    from parrot.integrations.devloop.models import DevLoopIntegrationConfig  # noqa: PLC0415

    return DevLoopIntegrationConfig.from_dict(name, dict(raw))
```
**Why**: `from_dict` is the single YAML entry point (`integrations/models.py:64`); a helper keeps the `cls(...)` call one-line-per-field like the rest.

### `packages/ai-parrot-integrations/tests/integrations/devloop/conftest.py` (CREATE)
```python
"""Shared fixtures for the dev-loop integration tests (FEAT-555)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest


class FakeRedis:
    """In-process stand-in for ``redis.asyncio.Redis`` (decode_responses=True).

    Supports the subset used by TASK-3203/3204: streams (``xadd``/``xread``/``xrange``),
    hashes (``hset``/``hgetall``/``delete``), sets (``sadd``/``srem``/``smembers``) and
    ``expire``. Mirrors packages/ai-parrot/tests/flows/dev_loop/test_streaming_state_view.py.
    """

    def __init__(self) -> None:
        self._streams: Dict[str, List[Tuple[str, Dict[str, str]]]] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._sets: Dict[str, set[str]] = {}
        self.expirations: Dict[str, int] = {}
        self._counter = 0

    async def xadd(self, key: str, fields: Dict[str, str], **_kw: Any) -> str:
        self._counter += 1
        entry_id = f"{1_700_000_000_000 + self._counter}-0"
        self._streams.setdefault(key, []).append((entry_id, fields))
        return entry_id

    # FILL IN: xrange(key, min="-", max="+"), xread(streams: dict, block=None, count=None) returning
    # [(key, [(id, fields), ...])] for ids > cursor ("$" = only new), keys(pattern), hset/hgetall/delete,
    # sadd/srem/smembers, expire(key, seconds) recording into self.expirations, ping() — bounded by what
    # FlowStreamMultiplexer (streaming.py:159-260, 291-460) and RunRegistry (TASK-3203) call.


@pytest.fixture
def fake_redis() -> FakeRedis:
    """Fresh fake Redis per test."""
    return FakeRedis()
```
**Why this shape**: `fakeredis` is not installed anywhere in the workspace; the core dev_loop tests already use an in-process fake, and one shared fixture keeps TASK-3203/3204 tests independent of infrastructure.

### `packages/ai-parrot-integrations/tests/integrations/devloop/test_models.py` (CREATE)
```python
"""Unit tests for parrot.integrations.devloop.models (TASK-3200)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from parrot.integrations.devloop.models import DevLoopIntegrationConfig, Requester, RunRecord
from parrot.integrations.slack.models import SlackAgentConfig


def test_config_from_dict_defaults() -> None:
    cfg = DevLoopIntegrationConfig.from_dict("devbot", {"enabled": True, "repo_path": "/srv/x"})
    assert cfg.enabled and cfg.repo_path == "/srv/x" and cfg.max_concurrent_runs is None


def test_config_env_fallback() -> None:
    # FILL IN: patch navconfig `config.get` to return "/env/repo" for DEVBOT_DEVLOOP_REPO_PATH — bounded by the
    # SlackAgentConfig env pattern (slack/models.py:56-63).
    pass


def test_validate_requires_criteria_when_enabled() -> None:
    cfg = DevLoopIntegrationConfig(name="b", enabled=True)
    assert any("default_acceptance_criteria" in e for e in cfg.validate())


def test_validate_rejects_disallowed_head() -> None:
    # FILL IN: criterion {"kind": "shell", "name": "x", "command": "rm -rf /"} → error naming the allowlist — AC10.
    pass


def test_requester_actor() -> None:
    assert Requester(transport="slack", tenant_id="T1", user_id="U1").actor == "slack:T1:U1"


def test_run_record_json_roundtrip() -> None:
    # FILL IN: build a RunRecord, model_dump_json → RunRecord.model_validate_json equals original.
    pass


def test_slack_config_parses_devloop_section() -> None:
    cfg = SlackAgentConfig.from_dict("devbot", {"chatbot_id": "a", "bot_token": "xoxb", "devloop": {"enabled": True}})
    assert cfg.devloop is not None and cfg.devloop.enabled


def test_slack_config_without_devloop_is_none() -> None:
    assert SlackAgentConfig.from_dict("b", {"chatbot_id": "a", "bot_token": "xoxb"}).devloop is None
```
**Why this shape**: covers the §5 AC19 "no behaviour change without `devloop.enabled`" boundary and the Q2 validation rule.

### FILL IN checklist
- [ ] `models.py::DevLoopIntegrationConfig.__post_init__` — env fallbacks for `repo_path`, `redis_url`, `socket_dir`; bounded by the `SlackAgentConfig.__post_init__` pattern.
- [ ] `models.py::DevLoopIntegrationConfig.from_dict` — map known keys only; bounded by the field list.
- [ ] `models.py::DevLoopIntegrationConfig.validate` — criteria non-empty + allowlisted heads; bounded by AC10 / `conf.ACCEPTANCE_CRITERION_ALLOWLIST`.
- [ ] `conftest.py::FakeRedis` — streams/hash/set/expire subset; bounded by `FlowStreamMultiplexer` + `RunRegistry` call surface.
- [ ] `test_models.py` — the four stubbed test bodies.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/devloop/test_models.py -v`
- [ ] Existing Slack config tests still pass: `pytest packages/ai-parrot-integrations/tests/integrations/slack -q`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/devloop packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py`
- [ ] Imports work: `from parrot.integrations.devloop import DevLoopIntegrationConfig, RunRecord, RunEvent`
- [ ] `importlib.import_module("parrot.integrations.devloop.models")` does not import `parrot.flows` or boot `parrot.conf`
- [ ] Spec AC19 (no behaviour change when the section is absent) and the Q2 validation rule (AC10) hold

---

## Test Specification

See the `test_models.py` blueprint above (8 tests, 4 stubbed).

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
7. **Move this file** to `sdd/tasks/completed/TASK-3200-devloop-integration-models-and-config.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-12
**Notes**: Created `parrot.integrations.devloop` (`__init__.py` + `models.py`)
with the config dataclass (`DevLoopIntegrationConfig` — env fallbacks,
`from_dict`, `validate()` gated on `enabled`/criteria/allowlist), the six
Pydantic contracts verbatim from spec §2, the five-error exception
hierarchy, and `PendingConfirmation`. Added `SlackAgentConfig.devloop`
(via a `TYPE_CHECKING`-only forward ref, kept `parrot.integrations.devloop`
out of the module's real import graph) and `_parse_devloop()` wired into
`from_dict`. Created the test package with `conftest.py::FakeRedis`
(streams/hash/set/expire, extending the core dev-loop tests'
`_FakeStreamsRedis` pattern for TASK-3203/3204 reuse) and `test_models.py`
(11 tests, all six blueprint FILL INs completed). Verified
`parrot.integrations.devloop.models` imports without pulling in
`parrot.flows` or booting `parrot.conf` (checked via `sys.modules`).
`pytest packages/ai-parrot-integrations/tests/integrations/devloop
packages/ai-parrot-integrations/tests/integrations/slack -q`: 68 passed.
`ruff check` and `black --check` clean on all touched/created files.

**Deviations from spec**: none.
