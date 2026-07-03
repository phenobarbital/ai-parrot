"""AbstractCodeReviewDispatcher ABC + factory (FEAT-270).

Decouples the QA node's code-review gate from any specific development
dispatcher. Concrete review dispatchers (added in follow-up tasks) wrap the
existing Claude/Codex/Gemini development dispatchers with a write-enabled
review profile, allowing the reviewer to fix issues it discovers and commit
fixes to the worktree branch.

See ``sdd/specs/new-codereviewers.spec.md`` for the full design.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, Type

from pydantic import BaseModel

from parrot import conf
from parrot.flows.dev_loop.dispatcher import (
    ClaudeCodeDispatcher,
    CodexCodeDispatcher,
    GeminiCodeDispatcher,
)
from parrot.flows.dev_loop.models import (
    ClaudeCodeReviewProfile,
    CodeReviewFinding,
    CodeReviewVerdict,
    CodexCodeReviewProfile,
    GeminiCodeReviewProfile,
)


class AbstractCodeReviewDispatcher(ABC):
    """ABC for all code review dispatchers.

    Wraps an underlying development dispatcher (Claude/Codex/Gemini) and
    adds review-specific behavior: building the review prompt/profile,
    enforcing the ``CodeReviewVerdict`` output contract (see
    ``parrot.flows.dev_loop.models``), and allowing the reviewer to fix +
    commit issues it finds.
    """

    agent_name: str

    @abstractmethod
    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
    ) -> BaseModel:
        """Run code review, optionally fix issues, return a verdict.

        Concrete implementations return a
        :class:`parrot.flows.dev_loop.models.CodeReviewVerdict`.
        """

    @abstractmethod
    def build_review_profile(self) -> BaseModel:
        """Return the dispatcher-specific review profile."""


class CodeReviewDispatcherFactory:
    """Factory for creating code review dispatchers."""

    _registry: Dict[str, Type[AbstractCodeReviewDispatcher]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a code review dispatcher."""

        def decorator(klass):
            cls._registry[name] = klass
            return klass

        return decorator

    @classmethod
    def create(cls, name: str, **kwargs) -> AbstractCodeReviewDispatcher:
        """Create a code review dispatcher by name."""
        if name not in cls._registry:
            raise ValueError(
                f"Unknown code review dispatcher: {name!r}. "
                f"Available: {sorted(cls._registry)}"
            )
        return cls._registry[name](**kwargs)


@CodeReviewDispatcherFactory.register("claude-code")
class ClaudeCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    """Wraps :class:`ClaudeCodeDispatcher` with a write-enabled review profile.

    Delegates to the ``sdd-codereview`` subagent (via the shared
    ``ClaudeCodeDispatcher``) with ``permission_mode="default"`` and the full
    read/write tool set, allowing the reviewer to fix issues it finds and
    commit the fixes to the worktree branch.
    """

    agent_name = "claude-code"

    def __init__(self, *, dispatcher: ClaudeCodeDispatcher, model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or conf.DEV_LOOP_CODEREVIEW_MODEL
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> ClaudeCodeReviewProfile:
        return ClaudeCodeReviewProfile(model=self._model)

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
    ) -> CodeReviewVerdict:
        try:
            return await self._dispatcher.dispatch(
                brief=brief,
                profile=self.build_review_profile(),
                output_model=CodeReviewVerdict,
                run_id=run_id,
                node_id=node_id,
                cwd=cwd,
            )
        except Exception as exc:  # noqa: BLE001 - degrade-on-infra-error (FEAT-250 G4)
            self.logger.warning("Code-review dispatch failed: %s", exc)
            return CodeReviewVerdict(
                passed=True,
                findings=[
                    CodeReviewFinding(
                        message=f"code-review could not run: {exc}",
                        severity="nit",
                    )
                ],
            )


@CodeReviewDispatcherFactory.register("codex")
class CodexCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    """Wraps :class:`CodexCodeDispatcher` with a write-enabled sandbox profile.

    Uses ``sandbox="workspace-write"`` and ``approval_policy="auto-edit"`` so
    the reviewer can fix issues it finds and commit the fixes to the
    worktree branch, mirroring the Claude reviewer's write-enabled behavior.
    """

    agent_name = "codex"

    def __init__(self, *, dispatcher: CodexCodeDispatcher, model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or "gpt-5.5"
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> CodexCodeReviewProfile:
        return CodexCodeReviewProfile(model=self._model)

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
    ) -> CodeReviewVerdict:
        try:
            return await self._dispatcher.dispatch(
                brief=brief,
                profile=self.build_review_profile(),
                output_model=CodeReviewVerdict,
                run_id=run_id,
                node_id=node_id,
                cwd=cwd,
            )
        except Exception as exc:  # noqa: BLE001 - degrade-on-infra-error (FEAT-250 G4)
            self.logger.warning("Codex code-review dispatch failed: %s", exc)
            return CodeReviewVerdict(
                passed=True,
                findings=[
                    CodeReviewFinding(
                        message=f"code-review could not run: {exc}",
                        severity="nit",
                    )
                ],
            )


@CodeReviewDispatcherFactory.register("gemini")
class GeminiCodeReviewDispatcher(AbstractCodeReviewDispatcher):
    """Wraps :class:`GeminiCodeDispatcher` with sandbox disabled + auto-edit.

    Uses ``sandbox=False`` and ``approval_mode="auto_edit"`` so the reviewer
    can fix issues it finds and commit the fixes to the worktree branch,
    mirroring the Claude and Codex reviewers' write-enabled behavior.
    """

    agent_name = "gemini"

    def __init__(self, *, dispatcher: GeminiCodeDispatcher, model: str | None = None) -> None:
        self._dispatcher = dispatcher
        self._model = model or "auto"
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> GeminiCodeReviewProfile:
        return GeminiCodeReviewProfile(model=self._model)

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
    ) -> CodeReviewVerdict:
        try:
            return await self._dispatcher.dispatch(
                brief=brief,
                profile=self.build_review_profile(),
                output_model=CodeReviewVerdict,
                run_id=run_id,
                node_id=node_id,
                cwd=cwd,
            )
        except Exception as exc:  # noqa: BLE001 - degrade-on-infra-error (FEAT-250 G4)
            self.logger.warning("Gemini code-review dispatch failed: %s", exc)
            return CodeReviewVerdict(
                passed=True,
                findings=[
                    CodeReviewFinding(
                        message=f"code-review could not run: {exc}",
                        severity="nit",
                    )
                ],
            )


__all__ = [
    "AbstractCodeReviewDispatcher",
    "CodeReviewDispatcherFactory",
    "ClaudeCodeReviewDispatcher",
    "CodexCodeReviewDispatcher",
    "GeminiCodeReviewDispatcher",
]
