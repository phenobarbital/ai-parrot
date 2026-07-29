"""Free-text feature intake for ``parrot devloop`` (FEAT-388, Module 2).

Turns a user's free-text feature request into a structured
:class:`FeatureDraft` (via a configurable light LLM,
``DEV_LOOP_INTAKE_LLM``), renders it as a brainstorm markdown document
under ``sdd/proposals/`` (FEAT-145 frontmatter, never overwriting an
existing file), and assembles the resulting
:class:`~parrot.flows.dev_loop.models.FeatureBrief`.

This module is CLI-side only — ``FeatureDraft`` and ``FeatureIntake`` are
NOT part of ``parrot.flows.dev_loop.models`` (spec §2). Heavy imports
(``parrot.conf``, ``parrot.clients.factory``, ``parrot.flows.dev_loop.*``)
are deferred into method bodies so importing this module (and therefore
``parrot devloop --help``) stays fast.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a heavy runtime import
    from parrot.flows.dev_loop.models import (
        DevAgentSpec,
        FeatureBrief,
        JudgePanelConfig,
    )

#: Default intake LLM when ``DEV_LOOP_INTAKE_LLM`` is unset (spec §1 G4).
DEFAULT_INTAKE_LLM = "anthropic:claude-haiku-4-5"

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9-]+")
_SLUG_WHITESPACE = re.compile(r"[\s_]+")
_SLUG_DASH_RUN = re.compile(r"-{2,}")


def _slugify(value: str) -> str:
    """Lowercase kebab-case a string, stripping anything outside ``[a-z0-9-]``.

    Args:
        value: Raw text (a title or an LLM-provided slug candidate).

    Returns:
        A kebab-case slug, or ``""`` if nothing usable remains.
    """
    candidate = _SLUG_WHITESPACE.sub("-", value.strip().lower())
    candidate = _SLUG_INVALID_CHARS.sub("", candidate)
    candidate = _SLUG_DASH_RUN.sub("-", candidate).strip("-")
    return candidate


class FeatureDraft(BaseModel):
    """Structured draft the intake LLM fills from the user's free text."""

    title: str
    slug: str = Field(
        default="",
        description="kebab-case, used for the document filename; "
        "sanitized/derived from title if empty or invalid.",
    )
    problem_statement: str
    requirements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    affected_areas: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class FeatureIntake:
    """Free text → :class:`FeatureDraft` → brainstorm document → ``FeatureBrief``.

    Attributes:
        logger: Module logger.
    """

    def __init__(
        self,
        llm: str | None = None,
        proposals_dir: Path | None = None,
    ) -> None:
        """Initialize the intake helper.

        Args:
            llm: Explicit ``"provider:model"`` spec. When ``None``,
                resolved lazily from ``DEV_LOOP_INTAKE_LLM``
                (default :data:`DEFAULT_INTAKE_LLM`).
            proposals_dir: Directory generated brainstorm documents are
                written to. Defaults to ``sdd/proposals`` (relative to
                the process cwd, matching every other SDD command).
        """
        self.logger = logging.getLogger(__name__)
        self._llm = llm
        self._proposals_dir = proposals_dir

    def _resolve_llm(self) -> str:
        """Resolve the intake LLM spec, honoring ``DEV_LOOP_INTAKE_LLM``."""
        if self._llm:
            return self._llm
        from parrot import conf

        return str(
            conf.config.get("DEV_LOOP_INTAKE_LLM", fallback=DEFAULT_INTAKE_LLM)
            or DEFAULT_INTAKE_LLM
        )

    async def generate(self, text: str) -> FeatureDraft:
        """Draft a :class:`FeatureDraft` from a user's free-text request.

        Args:
            text: The user's free-text feature request.

        Returns:
            The parsed, structured draft.

        Raises:
            ValueError: If the LLM fails to produce a valid draft twice
                in a row (one retry, per spec §3 Module 2).
        """
        return await self._invoke_draft(self._build_prompt(text))

    async def regenerate(self, text: str, guidance: str) -> FeatureDraft:
        """Re-draft the :class:`FeatureDraft`, incorporating user guidance.

        Args:
            text: The original free-text feature request.
            guidance: The user's ``redo <guidance>`` feedback on the last draft.

        Returns:
            The parsed, structured draft.

        Raises:
            ValueError: If the LLM fails to produce a valid draft twice
                in a row (one retry, per spec §3 Module 2).
        """
        prompt = (
            f"{self._build_prompt(text)}\n\n"
            "The user reviewed a previous draft and asked for changes. "
            f"Revision guidance: {guidance}"
        )
        return await self._invoke_draft(prompt)

    def _build_prompt(self, text: str) -> str:
        """Compose the structured-output prompt for the intake LLM.

        Args:
            text: The user's free-text feature request.

        Returns:
            A prompt instructing the LLM to fill every ``FeatureDraft`` field.
        """
        return (
            "You are drafting a brainstorm document for a new software "
            "feature or enhancement request. Read the user's free-text "
            "request and produce a structured draft: a short title, a "
            "kebab-case slug, a clear problem statement, a list of "
            "concrete requirements, a list of testable acceptance "
            "criteria, the affected areas/modules (if inferable), "
            "anything explicitly out of scope, and open questions worth "
            "flagging for review.\n\n"
            f"User request:\n{text}"
        )

    async def _invoke_draft(self, prompt: str) -> FeatureDraft:
        """Call the intake LLM once, retrying once on validation failure.

        Args:
            prompt: The fully composed structured-output prompt.

        Returns:
            The parsed :class:`FeatureDraft`.

        Raises:
            ValueError: If the second attempt also fails to produce a
                valid :class:`FeatureDraft`.
        """
        from parrot.clients.factory import LLMFactory

        client = LLMFactory.create(self._resolve_llm())

        try:
            result = await client.invoke(prompt, output_type=FeatureDraft)
        except ValidationError as exc:
            return await self._retry_after_failure(client, prompt, exc)

        draft = self._coerce_draft(result.output)
        if draft is not None:
            return draft

        return await self._retry_after_failure(
            client,
            prompt,
            ValueError(f"invoke() did not return a FeatureDraft: {result.output!r}"),
        )

    async def _retry_after_failure(
        self, client: Any, prompt: str, error: Exception
    ) -> FeatureDraft:
        """Retry the intake call once, appending ``error`` to the prompt.

        Args:
            client: The already-created LLM client.
            prompt: The original structured-output prompt.
            error: The validation failure from the first attempt.

        Returns:
            The parsed :class:`FeatureDraft` from the retry.

        Raises:
            ValueError: If the retry also fails to produce a valid draft.
        """
        self.logger.warning("Feature intake structured output failed once: %s", error)
        retry_prompt = (
            f"{prompt}\n\n"
            "Your previous response failed structured-output validation "
            f"with this error:\n{error}\n\n"
            "Respond again, strictly matching the required schema."
        )
        try:
            result = await client.invoke(retry_prompt, output_type=FeatureDraft)
        except ValidationError as exc:
            raise ValueError(
                f"Feature intake failed structured-output validation twice: {exc}"
            ) from exc

        draft = self._coerce_draft(result.output)
        if draft is None:
            raise ValueError(
                "Feature intake failed structured-output validation twice: "
                f"{result.output!r}"
            )
        return draft

    @staticmethod
    def _coerce_draft(output: Any) -> FeatureDraft | None:
        """Return ``output`` if it is already a :class:`FeatureDraft`, else ``None``."""
        if isinstance(output, FeatureDraft):
            return output
        return None

    def write_document(self, draft: FeatureDraft) -> Path:
        """Render ``draft`` as a brainstorm markdown document.

        Never overwrites an existing file — collides on slug append
        ``-2``, ``-3``, … suffixes.

        Args:
            draft: The structured draft to render.

        Returns:
            The path the document was written to.
        """
        proposals_dir = self._proposals_dir or Path("sdd/proposals")
        proposals_dir.mkdir(parents=True, exist_ok=True)

        slug = _slugify(draft.slug) or _slugify(draft.title) or "untitled-feature"
        path = self._next_available_path(proposals_dir, slug)
        path.write_text(self._render_markdown(draft), encoding="utf-8")
        return path

    @staticmethod
    def _next_available_path(directory: Path, slug: str) -> Path:
        """Return the first ``<slug>[-N].brainstorm.md`` path that doesn't exist.

        Args:
            directory: The target ``sdd/proposals`` directory.
            slug: The sanitized document slug.

        Returns:
            A path guaranteed not to already exist.
        """
        candidate = directory / f"{slug}.brainstorm.md"
        suffix = 2
        while candidate.exists():
            candidate = directory / f"{slug}-{suffix}.brainstorm.md"
            suffix += 1
        return candidate

    @staticmethod
    def _render_markdown(draft: FeatureDraft) -> str:
        """Render ``draft`` into brainstorm markdown with FEAT-145 frontmatter.

        Args:
            draft: The structured draft to render.

        Returns:
            The full markdown document text.
        """

        def _bullets(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in items) or "- (none captured)"

        author = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
        return (
            "---\n"
            "# SDD flow type and base branch (FEAT-145).\n"
            "type: feature\n"
            "base_branch: dev\n"
            "---\n\n"
            f"# Brainstorm: {draft.title}\n\n"
            f"**Date**: {date.today().isoformat()}\n"
            f"**Author**: {author} (via parrot devloop intake)\n"
            "**Status**: generated\n\n"
            "## Problem Statement\n"
            f"{draft.problem_statement}\n\n"
            "## Constraints & Requirements\n"
            f"{_bullets(draft.requirements)}\n\n"
            "## Acceptance Criteria\n"
            f"{_bullets(draft.acceptance_criteria)}\n\n"
            "## Affected Areas\n"
            f"{_bullets(draft.affected_areas)}\n\n"
            "## Out of Scope / Open Questions\n"
            f"{_bullets(draft.out_of_scope + draft.open_questions)}\n"
        )

    def build_brief(
        self,
        draft: FeatureDraft,
        document_path: Path,
        *,
        dev_agents: list[DevAgentSpec] | None = None,
        judge_panel: JudgePanelConfig | None = None,
    ) -> FeatureBrief:
        """Assemble the :class:`FeatureBrief` for this intake session.

        Args:
            draft: The confirmed structured draft (unused beyond
                having driven ``document_path``'s contents; kept in the
                signature for symmetry/future use).
            document_path: Path returned by :meth:`write_document`.
            dev_agents: Optional explicit dev-agent pool.
            judge_panel: Optional QA judge-panel override.

        Returns:
            A ``FeatureBrief(document_kind="brainstorm")`` ready for dispatch.
        """
        from parrot.flows.dev_loop.models import FeatureBrief

        del draft  # the document on disk is the source of truth for content
        return FeatureBrief(
            document_path=str(document_path),
            document_kind="brainstorm",
            dev_agents=dev_agents,
            judge_panel=judge_panel,
        )
