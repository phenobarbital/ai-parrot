"""Closeout-hook registry for /sdd-done (FEAT-764): models + `.parrot/sdd_hooks.toml` loader."""

from __future__ import annotations

import re
import tomllib
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_PATH: str = ".parrot/sdd_hooks.toml"
EVENTS: tuple[str, ...] = ("pre_pr", "post_pr", "on_failure")
NON_BLOCKING_EVENTS: frozenset[str] = frozenset({"post_pr", "on_failure"})
KNOWN_BUILTINS: frozenset[str] = frozenset({"jira.transition", "telegram.send", "push.send", "webhook.post"})
PUSH_PROVIDERS: frozenset[str] = frozenset({"ntfy", "gotify"})
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class HooksConfigError(ValueError):
    """Raised when .parrot/sdd_hooks.toml is malformed."""


class HookKind(str, Enum):
    """How a hook is executed."""

    COMMAND = "command"
    AGENT = "agent"
    BUILTIN = "builtin"


class HookSpec(BaseModel):
    """One subscribed hook."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    kind: HookKind
    run: str | None = None
    agent: str | None = None
    prompt: str | None = None
    builtin: str | None = None
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")
    blocking: bool = False
    timeout_s: int = Field(default=600, gt=0)
    artifacts: str | None = None
    enabled: bool = True


class HooksConfig(BaseModel):
    """Hooks grouped by closeout event."""

    pre_pr: list[HookSpec] = Field(default_factory=list)
    post_pr: list[HookSpec] = Field(default_factory=list)
    on_failure: list[HookSpec] = Field(default_factory=list)

    def for_event(self, event: str) -> list[HookSpec]:
        """Return the enabled hooks for ``event`` in declaration order."""
        return [hook for hook in getattr(self, event) if hook.enabled]


class HookContext(BaseModel):
    """Context handed to every hook (JSON file + env vars)."""

    feat_id: str
    spec_path: str
    branch: str
    base_branch: str
    worktree: str
    pr_url: str | None = None
    merge_sha: str | None = None
    test_report_md: str | None = None
    e2e_gate: dict[str, Any] | None = None
    abort_reason: str | None = None
    dry_run: bool = False


class HookResult(BaseModel):
    """Outcome of one hook."""

    name: str
    kind: HookKind
    status: Literal["pass", "fail", "skipped", "pending", "timeout"]
    blocking: bool
    duration_s: float = 0.0
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)


def _validate_hook(event: str, hook: HookSpec) -> None:
    """Raise HooksConfigError for any per-hook rule violation (spec §3 M1)."""
    if not _NAME_RE.fullmatch(hook.name):
        raise HooksConfigError(f"{CONFIG_PATH}: invalid hook name {hook.name!r}")
    if hook.kind is HookKind.COMMAND and hook.run is None:
        raise HooksConfigError(f"{CONFIG_PATH}: command hook {hook.name!r} requires run")
    if hook.kind is HookKind.AGENT and (hook.agent is None or hook.prompt is None):
        raise HooksConfigError(f"{CONFIG_PATH}: agent hook {hook.name!r} requires agent and prompt")
    if hook.kind is HookKind.BUILTIN:
        if hook.builtin is None:
            raise HooksConfigError(f"{CONFIG_PATH}: builtin hook {hook.name!r} requires builtin")
        if hook.builtin not in KNOWN_BUILTINS:
            raise HooksConfigError(f"{CONFIG_PATH}: unknown builtin {hook.builtin!r}")
        if hook.builtin == "push.send":
            provider = hook.with_.get("provider", "ntfy")
            if provider not in PUSH_PROVIDERS:
                raise HooksConfigError(f"{CONFIG_PATH}: unknown push provider {provider!r}")
    if event in NON_BLOCKING_EVENTS and hook.blocking:
        raise HooksConfigError(f"{CONFIG_PATH}: {event} hook {hook.name!r} cannot be blocking")


def load_hooks(root: Path) -> HooksConfig:
    """Load and validate hooks; return an empty HooksConfig when the file is absent.

    Raises:
        HooksConfigError: invalid TOML or schema violation (never a silent default).
    """
    path = Path(root) / CONFIG_PATH
    if not path.is_file():
        return HooksConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise HooksConfigError(f"{path}: {exc}") from exc

    if set(data) - {"hooks"}:
        raise HooksConfigError(f"{CONFIG_PATH}: only [hooks] is allowed")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HooksConfigError(f"{CONFIG_PATH}: [hooks] must be a table")
    unknown_events = set(hooks) - set(EVENTS)
    if unknown_events:
        raise HooksConfigError(f"{CONFIG_PATH}: unknown hook events: {', '.join(sorted(unknown_events))}")

    try:
        config = HooksConfig.model_validate(hooks)
    except ValidationError as exc:
        raise HooksConfigError(f"{CONFIG_PATH}: invalid hooks configuration: {exc}") from exc

    for event in EVENTS:
        names: set[str] = set()
        for hook in getattr(config, event):
            if hook.name in names:
                raise HooksConfigError(f"{CONFIG_PATH}: duplicate hook name {hook.name!r} in {event}")
            names.add(hook.name)
            _validate_hook(event, hook)
    return config
