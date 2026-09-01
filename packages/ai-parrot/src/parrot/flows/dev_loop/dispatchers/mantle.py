"""MantleAdversarialReviewDispatcher — read-only counter-reviewer on Bedrock Mantle.

FEAT-486 Module 4 (spec goal G5). The configurable adversarial review pair
defaults to Claude Opus 5 (write-enabled primary) plus ``gpt-5.6-sol`` as
the counter-reviewer — and ``gpt-5.6-sol`` **cannot** run over the Codex
CLI, so :class:`~parrot.flows.dev_loop.code_review.CodexAdversarialReviewDispatcher`
is not a usable transport for it. AWS serves it over the OpenAI-compatible
**bedrock-mantle** endpoint, which is what
:class:`~parrot.clients.nova.mantle.BedrockMantleClient` speaks.

This module is a deliberate mirror of
:class:`~parrot.flows.dev_loop.dispatchers.nova.NovaAdversarialReviewDispatcher`
(``dispatchers/nova.py:239``) — same class shape, same registration idiom,
same degrade-on-infra-error contract — differing only in the transport
(Chat Completions over Mantle rather than Converse over Nova) and the
default model. Nova's reviewer is kept for Converse-only models; this one
serves every Mantle-hosted id.

**Read-only BY CONSTRUCTION.** The security property is structural, not
procedural, in three independent layers:

1. :class:`MantleAdversarialReviewProfile` is a fresh ``BaseModel`` with no
   ``tools`` / ``allowed_commands`` / ``sandbox`` field — a tool
   configuration cannot be expressed, let alone forgotten.
2. The single client call passes ``use_tools=False`` explicitly and no
   ``tools`` kwarg.
3. The returned verdict is rewritten with ``files_modified=[]``, matching
   ``CodexAdversarialReviewDispatcher`` (``code_review.py:337``) — an
   advisory seat never claims authorship of an edit.

Findings are advisory and must be triaged (CONFIRM / REJECT / ESCALATE)
by the primary worker downstream.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from parrot import conf
from parrot.clients.nova.mantle import BedrockMantleClient
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
)
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    CodeReviewFinding,
    CodeReviewVerdict,
)
from parrot.flows.dev_loop.models.nova import effective_max_tokens
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.observability.context import usage_attribution

#: Kept byte-identical to ``conf.DEV_LOOP_MANTLE_REVIEW_MODEL``'s fallback.
#: Same rationale as ``models/nova.py``'s ``NOVA_DEFAULT_CONVERSE_MODEL``:
#: the literal is pinned equal by test rather than shared by import.
MANTLE_DEFAULT_REVIEW_MODEL: str = "gpt-5.6-sol"


class MantleAdversarialReviewProfile(BaseModel):
    """Read-only by construction: NO tools are ever passed to the model.

    Consumed by :meth:`MantleAdversarialReviewDispatcher.build_review_profile`.
    Deliberately a fresh ``BaseModel`` (not a subclass of any
    ``*DispatchProfile``) so it structurally cannot carry
    ``tools`` / ``allowed_commands`` / ``sandbox`` fields — exactly the
    argument ``NovaAdversarialReviewProfile`` makes at
    ``models/nova.py:130-139``.
    """

    model: str = Field(
        default=MANTLE_DEFAULT_REVIEW_MODEL,
        description="Bedrock Mantle model id for the counter-reviewer.",
    )
    review_scope: str = Field(
        default="uncommitted",
        description="Which diff the reviewer evaluates: uncommitted | base | commit.",
    )
    review_base: str = Field(
        default="",
        description="Base ref/branch to diff against when review_scope == 'base'.",
    )
    review_commit: str = Field(
        default="",
        description="Commit SHA to review when review_scope == 'commit'.",
    )
    max_tokens: int = Field(
        default=8192,
        ge=256,
        le=131072,
        description="Output token budget for the review verdict.",
    )
    max_diff_chars: int = Field(
        default=200_000,
        ge=1000,
        description="Deterministic truncation bound for the diff sent to the model.",
    )


@CodeReviewDispatcherFactory.register("mantle-adversarial")
class MantleAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):
    """Advisory, read-only counter-reviewer over the bedrock-mantle endpoint.

    Defaults to ``gpt-5.6-sol`` (override with
    ``DEV_LOOP_MANTLE_REVIEW_MODEL``). Like its Nova sibling there is no
    underlying ``DevLoopCodeDispatcher`` to delegate to: :meth:`review`
    drives :meth:`BedrockMantleClient.ask` directly and reproduces
    ``AbstractCodeReviewDispatcher.review()``'s degrade-on-infra-error
    contract locally — an outage (including a missing
    ``BEDROCK_MANTLE_API_KEY`` / ``AWS_NOVA_API_KEY`` bearer key) degrades
    to a *passing* verdict carrying a nit-level finding rather than
    crashing the QA node. That is a known, intentionally inherited
    property of the review contract, not a bug in this class.
    """

    agent_name = "mantle-adversarial"
    advisory = True

    def __init__(
        self,
        *,
        model: str | None = None,
        review_scope: str = "uncommitted",
        review_base: str = "",
        review_commit: str = "",
        max_diff_chars: int | None = None,
        max_tokens: int | None = None,
        client: BedrockMantleClient | None = None,
        event_registry_resolver: Any | None = None,
    ) -> None:
        """Initialise the counter-reviewer.

        Args:
            model: Mantle model id. Defaults to
                ``conf.DEV_LOOP_MANTLE_REVIEW_MODEL`` (``gpt-5.6-sol``).
                A NEW conf key — the existing
                ``DEV_LOOP_ADVERSARIAL_MODEL`` (the codex seat's) is
                deliberately NOT repointed.
            review_scope: ``"uncommitted"`` (default), ``"base"`` or
                ``"commit"``.
            review_base: Base ref, required for ``"base"`` scope.
            review_commit: Commit SHA, required for ``"commit"`` scope.
            max_diff_chars: Deterministic diff truncation bound.
            max_tokens: Output token budget. Clamped to the model's
                verified Bedrock ceiling by ``effective_max_tokens`` —
                unknown ids (``gpt-5.6-sol`` among them) pass through
                unclamped, since "unknown" is not "wrong".
            client: Pre-built client (tests / a shared per-run client).
            event_registry_resolver: FEAT-479 — optional
                ``(run_id) -> EventRegistry | None``. When supplied, the
                run's registry is bound onto the client's
                ``_events_registry`` before the call, so this seat's
                token usage reaches the run ledger exactly (the same
                documented injection point as
                ``dispatchers/llm.py:389-390``; clients otherwise
                self-create an isolated registry).
        """
        self._model = model or conf.DEV_LOOP_MANTLE_REVIEW_MODEL
        self._review_scope = review_scope
        self._review_base = review_base
        self._review_commit = review_commit
        self._max_diff_chars = max_diff_chars
        self._max_tokens = max_tokens
        self._client = client or BedrockMantleClient()
        self._event_registry_resolver = event_registry_resolver
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> MantleAdversarialReviewProfile:
        """Return this dispatcher's review profile (no tool fields exist)."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "review_scope": self._review_scope,
            "review_base": self._review_base,
            "review_commit": self._review_commit,
        }
        if self._max_diff_chars is not None:
            kwargs["max_diff_chars"] = self._max_diff_chars
        if self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens
        return MantleAdversarialReviewProfile(**kwargs)

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: SessionHost | None = None,
        round: str = "",
    ) -> CodeReviewVerdict:
        """Run the advisory review against ``BedrockMantleClient.ask()``.

        Args:
            brief: The review brief (diff context + acceptance criteria).
            run_id: The dev-loop / dev-flow run id (FEAT-479 attribution).
            node_id: The accounting seat label for the run ledger.
            cwd: Worktree the diff is collected from.
            session_host: Unused — this seat opens no gates and publishes
                no envelopes; accepted for protocol parity.
            round: Unused — accepted for protocol parity.

        Returns:
            The verdict, always with ``files_modified=[]`` and every
            finding tagged with this seat as its source. Any failure
            degrades to a passing verdict with a nit-level finding.
        """
        try:
            profile = self.build_review_profile()
            diff_text = await self._collect_diff(cwd, profile)
            prompt = self._build_prompt(brief, diff_text)
            self._bind_event_registry(run_id)
            # FEAT-479: seat-scoped attribution so this reviewer's tokens
            # land under `node_id` in the run ledger rather than unlabelled.
            with usage_attribution(run_id, seat=node_id):
                ai_message = await self._client.ask(
                    prompt,
                    model=profile.model,
                    max_tokens=effective_max_tokens(profile.model, profile.max_tokens, self.logger),
                    use_tools=False,
                    structured_output=CodeReviewVerdict,
                )
            verdict = ai_message.structured_output
            if not isinstance(verdict, CodeReviewVerdict):
                # ValueError (not TypeError) verbatim from the mirrored
                # NovaAdversarialReviewDispatcher (nova.py:328-332); it is
                # caught two lines below by the degrade-on-infra-error
                # handler, so the class is immaterial to behaviour and
                # matching the template is worth more than the lint.
                raise ValueError(  # noqa: TRY004
                    "mantle-adversarial reviewer did not return a valid "
                    f"CodeReviewVerdict (got {type(verdict).__name__})"
                )
        except Exception as exc:  # noqa: BLE001 - degrade-on-infra-error, mirrors code_review.py:145-157
            self.logger.warning("%s code-review dispatch failed: %s", self.agent_name, exc)
            return CodeReviewVerdict(
                passed=True,
                findings=[
                    CodeReviewFinding(
                        message=f"code-review could not run: {exc}",
                        severity="nit",
                    )
                ],
            )

        tagged_findings = [
            (
                finding
                if isinstance(finding, AdversarialFinding)
                else AdversarialFinding(**finding.model_dump(), source=self.agent_name)
            )
            for finding in verdict.findings
        ]
        # files_modified is FORCED empty: an advisory seat has no tools and
        # must never claim an edit, whatever the model asserts.
        return verdict.model_copy(update={"files_modified": [], "findings": tagged_findings})

    def _bind_event_registry(self, run_id: str) -> None:
        """Bind the run's ``EventRegistry`` onto the client, if resolvable.

        Args:
            run_id: The run whose registry should receive this seat's
                client events.
        """
        if self._event_registry_resolver is None:
            return
        registry = self._event_registry_resolver(run_id)
        if registry is not None and hasattr(self._client, "_events_registry"):
            self._client._events_registry = registry  # documented injection point

    async def _collect_diff(self, cwd: str, profile: MantleAdversarialReviewProfile) -> str:
        """Compute the review diff for ``profile.review_scope``.

        Mirrors ``NovaAdversarialReviewDispatcher._collect_diff`` — kept
        local rather than imported across dispatcher modules (``nova.py``
        already imports ``code_review``, so reaching back into it from
        here would couple two sibling transports for 20 lines).

        Args:
            cwd: Worktree to run git in.
            profile: The resolved review profile.

        Returns:
            The diff text, deterministically truncated.

        Raises:
            DispatchExecutionError: If git exits non-zero.
        """
        if profile.review_scope == "commit":
            argv = ["git", "show", "--patch", "--no-color", profile.review_commit]
        elif profile.review_scope == "base":
            argv = ["git", "diff", "--no-color", f"{profile.review_base}...HEAD"]
        else:  # "uncommitted" (default)
            argv = ["git", "diff", "--no-color", "HEAD"]

        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await process.communicate()
        if process.returncode != 0:
            raise DispatchExecutionError(
                f"git diff failed (exit {process.returncode}): " f"{stderr_b.decode('utf-8', errors='replace')[:2000]}"
            )
        diff_text = stdout_b.decode("utf-8", errors="replace")
        return self._truncate_diff(diff_text, profile.max_diff_chars)

    @staticmethod
    def _truncate_diff(diff_text: str, max_diff_chars: int) -> str:
        """Deterministically truncate ``diff_text``, never silently."""
        if len(diff_text) <= max_diff_chars:
            return diff_text
        return diff_text[:max_diff_chars] + f"\n\n[... diff truncated at {max_diff_chars} characters ...]"

    @staticmethod
    def _build_prompt(brief: BaseModel, diff_text: str) -> str:
        """Build the read-only review prompt (no tools are available)."""
        return (
            "You are an adversarial code reviewer. Review the diff below "
            "against the acceptance criteria in the brief. Report every "
            "genuine issue as a finding. You have NO tools and cannot "
            "modify any files — this is a read-only review.\n\n"
            f"Brief:\n{brief.model_dump_json()}\n\n"
            f"Diff:\n{diff_text}\n\n"
            "Return your verdict as the requested structured output."
        )


__all__ = [
    "MANTLE_DEFAULT_REVIEW_MODEL",
    "MantleAdversarialReviewDispatcher",
    "MantleAdversarialReviewProfile",
]
