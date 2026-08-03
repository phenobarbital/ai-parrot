"""Codex dispatch/review profiles for the dev-loop flow (FEAT-129/270/375)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CodexCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``CodexCodeDispatcher.dispatch()``.

    The v1 Codex integration is intentionally scoped to Development. The
    profile still keeps ``subagent`` explicit so the dispatcher can load the
    same SDD subagent prompt body used by the Claude Code path.
    """

    subagent: Literal["sdd-worker", "sdd-secondopinion"] = "sdd-worker"
    model: str = "gpt-5.5"
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    approval_policy: Literal["untrusted", "on-request", "never"] = "never"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    ignore_user_config: bool = Field(
        default=True,
        description=(
            "When True, pass --ignore-user-config so server-side dispatches do "
            "not inherit an operator's interactive Codex settings."
        ),
    )
    ignore_rules: bool = Field(
        default=False,
        description=(
            "When True, pass --ignore-rules. Defaults to False so repository "
            "AGENTS.md / rules still guide the coding agent."
        ),
    )



class CodexCodeReviewProfile(CodexCodeDispatchProfile):
    """Review profile for the Codex code review dispatcher (FEAT-270).

    Inherits ``CodexCodeDispatchProfile`` so it carries the ``ignore_user_config``
    and ``ignore_rules`` fields that ``CodexCodeDispatcher._build_command()`` accesses.
    Overrides defaults for the write-enabled review use case.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    model: str = "gpt-5.5"
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    approval_policy: Literal["untrusted", "on-request", "never"] = "on-request"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class CodexAdversarialReviewProfile(CodexCodeDispatchProfile):
    """Advisory review profile for the Codex adversarial second-opinion (FEAT-375).

    Read-only, neutral-brief, no-writes profile: the dispatcher runs
    ``codex exec review`` (or ``codex exec resume --last``) in a read-only
    sandbox with the ``sdd-secondopinion`` subagent brief, which by
    construction never receives the primary agent's reasoning.
    """

    subagent: Literal["sdd-secondopinion"] = "sdd-secondopinion"
    sandbox: Literal["read-only"] = "read-only"
    approval_policy: Literal["never"] = "never"
    review_scope: Literal["uncommitted", "base", "commit"] = "uncommitted"
    review_base: str = ""
    review_commit: str = ""
    resume_last: bool = Field(
        default=False,
        description="G6: use `codex exec resume --last` to continue the existing review session.",
    )
    # A read-only diff review needs minutes, not half an hour: the reviewer
    # cannot run tests (nothing is writable in the read-only sandbox, not
    # even /tmp), so a long timeout only pays for retry spirals when the
    # model attempts a command anyway.
    timeout_seconds: int = Field(default=600, ge=60, le=7200)
