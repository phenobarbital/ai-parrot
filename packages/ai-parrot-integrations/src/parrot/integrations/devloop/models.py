"""Data contracts for the dev-loop integration (spec §2 Data Models, FEAT-555).

Kept import-cheap on purpose: only stdlib, pydantic and navconfig at module
level. ``parrot.conf`` (and therefore the whole config bootstrap) is only
imported lazily inside :meth:`DevLoopIntegrationConfig.validate`.
"""

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
    """The actor is not the run's initiator.

    ``owner_user_id`` lets a transport render something like "This run
    belongs to <@owner>".
    """

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
    """``devloop:`` section of a Slack bot entry in ``integrations_bots.yaml``.

    Env fallbacks use the ``{NAME}_DEVLOOP_*`` prefix, mirroring
    ``SlackAgentConfig.__post_init__``.

    Attributes:
        name: The owning bot's config name (used for env-fallback prefixes).
        enabled: Whether this bot dispatches dev-loop runs at all.
        repo_path: cwd of the headless child; falls back to ``{NAME}_DEVLOOP_REPO_PATH``.
        command: Argv used to spawn the headless child.
        redis_url: Redis URL for the tail/registry; falls back to ``{NAME}_DEVLOOP_REDIS_URL``.
        socket_dir: Directory for per-run Unix sockets/brief files; falls
            back to ``{NAME}_DEVLOOP_SOCKET_DIR``. Empty + ``use_tcp=True``
            means TCP-only.
        use_tcp: Force ``--command-port`` instead of ``--command-socket``.
        default_component: ``WorkBrief.affected_component`` default for bug runs.
        default_acceptance_criteria: ``ShellCriterion``-shaped dicts used
            when a bug run's ``--ac`` is not given. Mandatory (non-empty)
            when ``enabled``.
        status_card: Whether to render the live node-status card (M13).
        max_concurrent_runs: Soft cap on live runs; ``None`` = unlimited (decision).
        run_retention_seconds: TTL applied to a terminal run's Redis record.
        handshake_timeout_seconds: How long to await the child's handshake.
        cancel_grace_seconds: Parent-side escalation to ``terminate()`` after
            a cancel with no terminal action/exit (S7); must exceed the
            child's own ``--cancel-grace``.
        tail_drain_seconds: How long the tail may run after the child exits (S8).
    """

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
        if not self.repo_path:
            self.repo_path = config.get(f"{prefix}REPO_PATH") or ""
        if not self.redis_url:
            self.redis_url = config.get(f"{prefix}REDIS_URL") or ""
        if not self.socket_dir:
            self.socket_dir = config.get(f"{prefix}SOCKET_DIR") or ""

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "DevLoopIntegrationConfig":
        """Build from the parsed YAML mapping (unknown keys ignored).

        Args:
            name: The owning bot's config name.
            data: The ``devloop:`` mapping from ``integrations_bots.yaml``.

        Returns:
            The constructed config.
        """
        return cls(
            name=name,
            enabled=data.get("enabled", False),
            repo_path=data.get("repo_path", ""),
            command=data.get("command", ["parrot", "devloop", "run"]),
            redis_url=data.get("redis_url", ""),
            socket_dir=data.get("socket_dir", ""),
            use_tcp=data.get("use_tcp", False),
            default_component=data.get("default_component", "ai-parrot"),
            default_acceptance_criteria=data.get("default_acceptance_criteria", []),
            status_card=data.get("status_card", True),
            max_concurrent_runs=data.get("max_concurrent_runs"),
            run_retention_seconds=data.get("run_retention_seconds", 86400),
            handshake_timeout_seconds=data.get("handshake_timeout_seconds", 120.0),
            cancel_grace_seconds=data.get("cancel_grace_seconds", 45.0),
            tail_drain_seconds=data.get("tail_drain_seconds", 5.0),
        )

    def validate(self) -> List[str]:
        """Return config errors; empty when valid.

        Spec §7 Q2: ``default_acceptance_criteria`` is mandatory when
        ``enabled``, and every criterion's command head must be in
        ``conf.ACCEPTANCE_CRITERION_ALLOWLIST``.

        Returns:
            A list of human-readable error strings (empty ⇒ valid).
        """
        from parrot import conf  # noqa: PLC0415 - keep module import-cheap

        errors: List[str] = []
        if not self.enabled:
            return errors

        if not self.default_acceptance_criteria:
            errors.append("devloop.default_acceptance_criteria must be non-empty when devloop.enabled is true")
            return errors

        allowlist = set(conf.ACCEPTANCE_CRITERION_ALLOWLIST)
        for criterion in self.default_acceptance_criteria:
            command = str(criterion.get("command", ""))
            head = shlex.split(command)[0] if command.strip() else ""
            if head not in allowlist:
                errors.append(
                    f"devloop.default_acceptance_criteria command head {head!r} is not in "
                    f"ACCEPTANCE_CRITERION_ALLOWLIST ({sorted(allowlist)})"
                )
        return errors


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
    kind: Literal[
        "snapshot",
        "gate_opened",
        "gate_resolved",
        "gate_expired",
        "node_changed",
        "jira_linked",
        "run_closed",
        "run_cancelled",
        "process_exited",
    ]
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
    """A brief parked behind the confirm card (Q1, both kinds).

    Memory-only, 15 min TTL — the dispatch service (TASK-3204) owns the
    in-memory dict this is stored in.
    """

    pending_id: str
    kind: RequestType
    brief: Dict[str, Any]  # brief.model_dump(mode="json"); rebuilt via WorkBrief/DevRequestBrief(**brief)
    fields: Dict[str, str] = Field(default_factory=dict)  # brief_summary_fields() projection shown on the card
    requester: Requester
    channel_id: str
    message_ts: str = ""
    created_at: float
    expires_at: float
