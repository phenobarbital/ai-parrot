"""LLMCodeDispatcher — local coding-agent loop for OpenAI-compatible clients.

CLI-backed dispatchers (Claude, Codex, Gemini) delegate filesystem and
command execution to their external runtime. This dispatcher keeps that
runtime in-process: the model drives a local tool loop (read/write/edit/
run_command) against ``cwd`` via any OpenAI-compatible ``AbstractClient``
resolved through :class:`parrot.clients.factory.LLMFactory`. Backend-
specific dispatchers (Grok, Z.ai, Moonshot) subclass this to reuse the
loop, Redis event streaming, cwd-safety guard, and output validation.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
import shlex
import shutil
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple, Type

from pydantic import BaseModel, ValidationError

from parrot import conf
from parrot.clients.factory import LLMFactory
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.flows.dev_loop.dispatchers._shared import (
    T,
    _SESSION_HOST_CTX,
    _apply_to_session_host,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import DispatchEvent, LLMCodeDispatchProfile
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.models.basic import CompletionUsage
from parrot.observability.context import usage_attribution

if TYPE_CHECKING:
    from parrot.core.events.lifecycle import EventRegistry


class LLMCodeDispatcher:
    """Local coding-agent loop for OpenAI-compatible LLM clients.

    CLI-backed dispatchers delegate filesystem and command execution to their
    external runtime. This dispatcher keeps that runtime in-process: the model
    receives a small OpenAI-style tool surface, every tool is cwd-confined, and
    the final payload is validated against the requested Pydantic model.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
        client_factory: Callable[..., Any] = LLMFactory.create,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.logger = logging.getLogger(__name__)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._redis_url = redis_url
        self.stream_ttl_seconds = stream_ttl_seconds
        self._client_factory = client_factory
        self._redis: Any = None
        # FEAT-479 M5: resolves run_id -> the run's per-run EventRegistry, so
        # constructed clients emit on it (exactness) instead of degrading to
        # fire-and-forget on a lazily self-created registry. None (default)
        # when no owner (e.g. DevLoopRunner) has wired one in — see
        # set_event_registry_resolver.
        self._event_registry_resolver: Optional[Callable[[str], Optional["EventRegistry"]]] = None

    def set_event_registry_resolver(self, resolver: Callable[[str], Optional["EventRegistry"]]) -> None:
        """Wire a ``run_id -> EventRegistry`` lookup (FEAT-479 M5).

        Called once by the owning :class:`DevLoopRunner` so
        :meth:`_create_client` can inject the run's per-run registry into
        every client it builds for that run, instead of letting the client
        lazily self-create an isolated one (which would degrade delivery to
        fire-and-forget — see spec §2 Exactness).

        Args:
            resolver: A callable returning the live :class:`EventRegistry`
                for a given ``run_id``, or ``None`` if that run has no
                tracked registry (e.g. never wired, or already closed).
        """
        self._event_registry_resolver = resolver

    @property
    def event_registry_resolver(self) -> Optional[Callable[[str], Optional["EventRegistry"]]]:
        """The wired ``run_id -> EventRegistry`` lookup, if any.

        Public so an owner that was handed ONE wired dispatcher can pass
        the same lookup on to dispatchers it did not build itself — the
        dev-agent pool's workers, which ``agent_builder.build_dispatcher``
        constructs with no knowledge of the run.

        Returns:
            The resolver, or ``None`` when none was wired.
        """
        return self._event_registry_resolver

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: LLMCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        stream_key = f"flow:{run_id}:dispatch:{node_id}"
        # FEAT-322 TASK-1852: see module-level _SESSION_HOST_CTX docstring —
        # the try/except below covers the narrow pre-semaphore window (an
        # early raise here still resets the var); the try/except/finally
        # inside the semaphore block below resets it on every OTHER exit
        # path (the success return or one of the re-raising excepts).
        _host_token = _SESSION_HOST_CTX.set(session_host)
        try:
            self._enforce_cwd_under_worktree_base(cwd)

            await self._publish_event(
                stream_key,
                kind="dispatch.queued",
                run_id=run_id,
                node_id=node_id,
                payload={
                    "profile": profile.model_dump(mode="json"),
                    # The run bundle's "Dispatcher" column reads this key
                    # (session_state.DispatchQueued.dispatcher) and showed
                    # `n/a` for every node because nobody ever set it.
                    # Every subclass funnels through here with
                    # `llm="<backend>:<model>"`.
                    "dispatcher": profile.llm.split(":", 1)[0] or profile.llm,
                },
            )
        except Exception:
            _SESSION_HOST_CTX.reset(_host_token)
            raise

        async with self._semaphore:
            await self._publish_event(
                stream_key,
                kind="dispatch.started",
                run_id=run_id,
                node_id=node_id,
                payload={
                    "cwd": cwd,
                    "subagent": profile.subagent,
                    "llm": profile.llm,
                    "sandbox": profile.sandbox,
                },
            )
            try:
                async with asyncio.timeout(profile.timeout_seconds):
                    return await self._dispatch_loop(
                        brief=brief,
                        profile=profile,
                        output_model=output_model,
                        run_id=run_id,
                        node_id=node_id,
                        stream_key=stream_key,
                        cwd=cwd,
                    )
            except TimeoutError as exc:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.failed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "error_class": "TimeoutError",
                        "error_message": (f"dispatch exceeded {profile.timeout_seconds}s " "wall-clock cap"),
                    },
                )
                raise DispatchExecutionError(f"Dispatch exceeded {profile.timeout_seconds}s wall-clock cap") from exc
            except DispatchOutputValidationError as exc:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.output_invalid",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "raw_payload": exc.raw_payload[:8000],
                        "error_message": str(exc),
                    },
                )
                raise
            except DispatchExecutionError as exc:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.failed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "error_class": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                raise
            except Exception as exc:
                await self._publish_event(
                    stream_key,
                    kind="dispatch.failed",
                    run_id=run_id,
                    node_id=node_id,
                    payload={
                        "error_class": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                raise DispatchExecutionError(f"LLM code dispatch failed: {exc}") from exc
            finally:
                _SESSION_HOST_CTX.reset(_host_token)

    @staticmethod
    def _log_id(node_id: str, brief: BaseModel) -> str:
        """Build the log label for one dispatch: seat, plus task when known.

        Args:
            node_id: The dispatch seat, e.g. ``"development.w1"``.
            brief: The dispatch brief; a ``TaskScopedBrief`` in pool mode.

        Returns:
            ``"development.w1 [TASK-1901]"`` when the brief is task-scoped,
            otherwise ``node_id`` unchanged.
        """
        task_id = getattr(brief, "task_id", "")
        return f"{node_id} [{task_id}]" if task_id else node_id

    async def _dispatch_loop(
        self,
        *,
        brief: BaseModel,
        profile: LLMCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        stream_key: str,
        cwd: str,
    ) -> T:
        # FEAT-479 M5: bind run/seat attribution for the whole dispatch —
        # UsageRecordingSubscriber._on_client_after reads these ContextVars
        # when the per-run registry's emit() invokes it synchronously.
        # `node_id` IS the seat here: DevAgentPool already passes
        # "development.w1"-style worker ids as `node_id` (agent_pool.py).
        with usage_attribution(run_id, node_id):
            # In pool mode `node_id` is the SEAT ("development.w1"), which
            # by itself never says which task the seat is chewing on. The
            # brief already carries it (TaskScopedBrief.task_id), so the
            # per-turn lines below can name it without any signature
            # change; single-agent briefs have no task_id and keep the
            # bare seat label.
            log_id = self._log_id(node_id, brief)
            client = self._create_client(profile, run_id=run_id)
            await self._ensure_client_ready(client)
            model = self._resolve_model(profile, client)
            messages = self._initial_messages(profile, brief, output_model, cwd=cwd)
            tools = self._tool_schemas(output_model)
            args = self._completion_args(profile, tools)

            # FEAT-405 Module 6: drive the same FEAT-397 emitter trio every
            # client's own ask() loop uses. This loop never calls ask(), so
            # without this, per-round usage/telemetry never reaches the
            # dev-loop dispatch path for ANY backend (nvidia/zai/moonshot/grok/
            # nova all report None tokens otherwise). Underscore-private
            # methods — a deliberate, documented choice at the same level of
            # intimacy this loop already has with client._chat_completion
            # below. Per-round events are still one-per-round and are NOT
            # summed for that purpose. FEAT-479 additionally accumulates a
            # per-call total here (via ``CompletionUsage.__add__``) solely to
            # populate the awaited ``AfterClientCallEvent`` — see
            # sdd/specs/devflow-telemetry-accounting.spec.md §3 Module 3 for
            # why FEAT-405 R4 is deliberately overridden on this path.
            tc = self._safe_emit_before_call(client, model=model, has_tools=bool(tools))
            loop_t0 = time.perf_counter()
            accumulated: Optional[CompletionUsage] = None  # LOCAL, never self.*
            # Remaining-turn counts at which the model gets told how much
            # budget is left; consumed head-first. See _budget_nudge.
            budget_marks = self._budget_marks(profile.max_turns)
            self.logger.info(
                "%s dispatching %s on %s (budget: %d turns, %ds wall-clock)",
                log_id,
                profile.subagent,
                model,
                profile.max_turns,
                profile.timeout_seconds,
            )
            try:
                for turn_index in range(profile.max_turns):
                    round_t0 = time.perf_counter()
                    response = await self._chat_completion(
                        client=client,
                        model=model,
                        messages=messages,
                        args=args,
                    )
                    round_duration_ms = (time.perf_counter() - round_t0) * 1000
                    message = self._response_message(response)
                    content = self._message_content(message)
                    tool_calls = self._message_tool_calls(message)
                    finish_reason = self._finish_reason(response)
                    if finish_reason == "length":
                        # The round was cut off at `max_tokens`. Whatever
                        # comes out of it is partial by construction — say
                        # so once, here, so the operator does not have to
                        # infer it from a downstream JSON parse error.
                        self.logger.warning(
                            "%s turn %d: response hit the output-token limit "
                            "(max_tokens=%d) and was truncated",
                            log_id,
                            turn_index + 1,
                            profile.max_tokens,
                        )
                    usage, raw_usage = self._extract_usage(response)
                    if usage is not None:
                        accumulated = usage if accumulated is None else accumulated + usage
                    self._safe_emit_round_event(
                        client,
                        tc,
                        model=model,
                        round_number=turn_index + 1,
                        usage=usage,
                        raw_usage=raw_usage,
                        tool_calls=[self._tool_call_name(call) for call in tool_calls],
                        duration_ms=round_duration_ms,
                    )
                    # This loop used to log NOTHING per turn: every detail
                    # went to the Redis stream, so an operator watching the
                    # server saw a node start and then half an hour of
                    # silence, indistinguishable from a hang. One line per
                    # turn is the cheapest way to tell "working" from
                    # "stuck", and makes a budget being burned on repeated
                    # tool failures visible while it happens.
                    self.logger.info(
                        "%s turn %d/%d: %s (%.1fs)",
                        log_id,
                        turn_index + 1,
                        profile.max_turns,
                        ", ".join(self._tool_call_name(call) for call in tool_calls) or "no tool call",
                        round_duration_ms / 1000,
                    )

                    if content:
                        await self._publish_event(
                            stream_key,
                            kind="dispatch.message",
                            run_id=run_id,
                            node_id=node_id,
                            payload={"turn": turn_index, "text": content[:4000]},
                        )

                    if not tool_calls:
                        result = self._validate_text_output(content, output_model)
                        await self._publish_event(
                            stream_key,
                            kind="dispatch.completed",
                            run_id=run_id,
                            node_id=node_id,
                            payload={
                                "output_model": output_model.__name__,
                                "usage": self._completion_usage_payload(
                                    accumulated,
                                    turns=turn_index + 1,
                                    started_at=loop_t0,
                                ),
                            },
                        )
                        return result

                    # Parse BEFORE echoing the assistant turn: the echo
                    # itself used to re-parse (and therefore re-raise) —
                    # so an unreadable payload killed the dispatch before
                    # any feedback could be produced.
                    parsed_calls = [(call, *self._parse_tool_arguments(call)) for call in tool_calls]

                    messages.append(
                        {
                            "role": "assistant",
                            "content": content,
                            "tool_calls": [
                                self._tool_call_to_openai_dict(
                                    call,
                                    parsed if parsed is not None else {"_discarded": arg_error},
                                )
                                for call, parsed, arg_error in parsed_calls
                            ],
                        }
                    )

                    for call, parsed_args, arg_error in parsed_calls:
                        tool_call_id = self._tool_call_id(call)
                        tool_name = self._tool_call_name(call)
                        if parsed_args is None:
                            # Recoverable: hand the model the reason and
                            # the way out, spend the turn, keep the seat.
                            feedback = self._truncated_call_feedback(
                                tool_name=tool_name,
                                reason=arg_error,
                                finish_reason=finish_reason,
                                max_tokens=profile.max_tokens,
                            )
                            self.logger.warning(
                                "%s turn %d: %s call discarded - %s",
                                log_id,
                                turn_index + 1,
                                tool_name or "<unnamed>",
                                arg_error,
                            )
                            truncated_result = {
                                "ok": False,
                                "error_class": "TruncatedToolCall",
                                "error": feedback,
                            }
                            await self._publish_event(
                                stream_key,
                                kind="dispatch.tool_result",
                                run_id=run_id,
                                node_id=node_id,
                                payload={
                                    "tool_call_id": tool_call_id,
                                    "tool_name": tool_name,
                                    "result": truncated_result,
                                },
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "name": tool_name,
                                    "content": json.dumps(truncated_result, ensure_ascii=False),
                                }
                            )
                            continue
                        tool_args = parsed_args
                        await self._publish_event(
                            stream_key,
                            kind="dispatch.tool_use",
                            run_id=run_id,
                            node_id=node_id,
                            payload={
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                                "arguments": tool_args,
                            },
                        )

                        if tool_name == "final_output":
                            result = self._validate_final_tool(tool_args, output_model)
                            await self._publish_event(
                                stream_key,
                                kind="dispatch.tool_result",
                                run_id=run_id,
                                node_id=node_id,
                                payload={
                                    "tool_call_id": tool_call_id,
                                    "tool_name": tool_name,
                                    "result": {"ok": True},
                                },
                            )
                            await self._publish_event(
                                stream_key,
                                kind="dispatch.completed",
                                run_id=run_id,
                                node_id=node_id,
                                payload={
                                    "output_model": output_model.__name__,
                                    "usage": self._completion_usage_payload(
                                        accumulated,
                                        turns=turn_index + 1,
                                        started_at=loop_t0,
                                    ),
                                },
                            )
                            return result

                        tool_result = await self._run_tool(
                            tool_name=tool_name,
                            tool_args=tool_args,
                            cwd=cwd,
                            profile=profile,
                        )
                        if tool_result.get("ok") is False:
                            self.logger.warning(
                                "%s turn %d: %s failed: %s",
                                log_id,
                                turn_index + 1,
                                tool_name,
                                str(
                                    tool_result.get("error")
                                    or tool_result.get("stderr")
                                    or ""
                                ).strip()[:200],
                            )
                        await self._publish_event(
                            stream_key,
                            kind="dispatch.tool_result",
                            run_id=run_id,
                            node_id=node_id,
                            payload={
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                                "result": tool_result,
                            },
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "name": tool_name,
                                "content": json.dumps(tool_result, ensure_ascii=False),
                            }
                        )

                    remaining = profile.max_turns - (turn_index + 1)
                    if budget_marks and remaining <= budget_marks[0]:
                        budget_marks.pop(0)
                        messages.append(
                            {
                                "role": "user",
                                "content": self._budget_nudge(
                                    used=turn_index + 1,
                                    total=profile.max_turns,
                                ),
                            }
                        )
                        self.logger.info(
                            "%s budget warning issued: %d/%d turns used",
                            log_id,
                            turn_index + 1,
                            profile.max_turns,
                        )

                # The turn budget is spent, but the dispatch is not
                # necessarily wasted: the common failure of a chat model
                # driven through this loop is one that patched, ran the
                # tests and committed, then kept exploring instead of
                # calling `final_output`. Spend ONE more round with the
                # tool choice FORCED to `final_output` to close the books
                # on the work already done, rather than discarding a whole
                # task (and, in pool mode, burning the single retry).
                salvaged, salvage_usage, salvage_error = await self._salvage_final_output(
                    client=client,
                    model=model,
                    messages=messages,
                    args=args,
                    output_model=output_model,
                    profile=profile,
                    run_id=run_id,
                    node_id=node_id,
                    stream_key=stream_key,
                    tc=tc,
                )
                if salvage_usage is not None:
                    accumulated = salvage_usage if accumulated is None else accumulated + salvage_usage
                if salvaged is not None:
                    return salvaged
                raise DispatchExecutionError(
                    f"LLM code dispatch exceeded max_turns={profile.max_turns}; "
                    f"the forced final_output turn did not recover a result ({salvage_error})"
                )
            finally:
                await self._safe_emit_after_call(
                    client,
                    tc,
                    model=model,
                    duration_ms=(time.perf_counter() - loop_t0) * 1000,
                    input_tokens=accumulated.prompt_tokens if accumulated else None,
                    output_tokens=accumulated.completion_tokens if accumulated else None,
                )

    @staticmethod
    def _completion_usage_payload(
        accumulated: Optional[CompletionUsage],
        *,
        turns: int,
        started_at: float,
    ) -> Dict[str, Any]:
        """Shape the loop's totals the way ``dispatch.completed`` reports them.

        ``session_state.action_from_dispatch_event`` reads token/turn/
        duration figures out of a ``dispatch.completed`` payload's
        ``usage`` object; this loop published only the output-model name,
        so a node driven by an in-process LLM backend showed ``n/a``
        tokens in the run bundle's Agents table even when it had reported
        usage on every round. No ``total_cost_usd``: this loop has no
        price table, and a fabricated zero would read as "free".

        Args:
            accumulated: The per-call usage total, or ``None`` when no
                round reported usage.
            turns: Rounds actually spent.
            started_at: ``time.perf_counter()`` at loop start.

        Returns:
            A ``usage`` payload dict; token keys are omitted entirely
            when unreported, never zero-filled.
        """
        usage: Dict[str, Any] = {
            "num_turns": turns,
            "duration_ms": int((time.perf_counter() - started_at) * 1000),
        }
        if accumulated is not None:
            usage["input_tokens"] = accumulated.prompt_tokens
            usage["output_tokens"] = accumulated.completion_tokens
        return usage

    @staticmethod
    def _budget_marks(max_turns: int) -> List[int]:
        """Remaining-turn counts at which to warn the model, head-first.

        Two warnings: one with a quarter of the budget left (still time to
        change plan) and one with a tenth left (time only to land and
        report). Deduplicated and descending, so a tiny ``max_turns``
        yields one mark rather than two on the same turn.

        Args:
            max_turns: The dispatch's turn budget.

        Returns:
            Descending remaining-turn thresholds, e.g. ``[15, 6]`` for 60.
        """
        marks = {max(1, int(max_turns * ratio)) for ratio in (0.25, 0.10)}
        return sorted(marks, reverse=True)

    @staticmethod
    def _budget_nudge(*, used: int, total: int) -> str:
        """Build the mid-loop reminder that the turn budget is finite.

        Nothing in the prompt told the model a budget existed, so it had no
        way to triage: observed seats were still opening files to "check
        one more thing" on turn 59 of 60, and the work they had done was
        recovered only by the forced-``final_output`` salvage — or lost.
        Telling it the count converts a cliff into a deadline.

        Args:
            used: Turns spent so far.
            total: The full turn budget.

        Returns:
            The nudge text, sent as a user turn.
        """
        remaining = total - used
        return (
            f"Budget check: {used} of {total} turns used, {remaining} left. "
            "One turn is one assistant message, however many tools it calls "
            "— so batch independent reads and searches into a single turn "
            "instead of one per turn.\n\n"
            "Stop exploring now. Land the change you are on: edit, run its "
            "test, commit, then call `final_output`. If it will not fit in "
            f"{remaining} turns, commit whatever already works and report "
            "the rest honestly in `incomplete_tasks` — a partial result you "
            "declare is worth more than a complete one you never return."
        )

    def _salvage_nudge(self, output_model: Type[BaseModel]) -> str:
        """Build the final user turn sent when the budget is exhausted.

        Covers BOTH ways a backend can answer, in one round. Forcing
        ``tool_choice`` is a request, not a guarantee: a Bedrock Mantle
        seat (zai.glm-5) answered a forced ``final_output`` with prose,
        and the salvage failed with "Could not locate a JSON object in the
        assistant output" — the model had the answer and no accepted way
        to give it. Naming the raw-JSON fallback costs nothing (the caller
        already tries ``_validate_text_output`` on the text) and turns
        that dead end into a recovery.

        Deliberately instructs the model to be HONEST about partial work:
        a salvaged output naming its own task in ``incomplete_tasks`` is
        treated as a failure by ``DevAgentPool._dispatch_one``, so claiming
        completion buys nothing.

        Args:
            output_model: The structured output model to describe.

        Returns:
            The nudge text.
        """
        fields_block, required_block = self._output_field_blocks(output_model)
        return (
            "Your turn budget is exhausted. Stop working now: do not read, patch "
            "or run anything else. Report the result of the work you have ALREADY "
            "completed — the files you changed and the commits you actually made.\n\n"
            "Call `final_output`. If you cannot call a tool on this turn, reply "
            f"with ONLY a raw JSON object matching the `{output_model.__name__}` "
            "schema — no prose, no explanation, no markdown fences around it. "
            "Use these EXACT field names:\n"
            f"{fields_block}\n\n"
            f"Required fields: {required_block}.\n\n"
            "If the task is not fully finished, say so plainly in `summary` and "
            "list its TASK id in `incomplete_tasks`; do not claim work you did "
            "not do."
        )

    async def _salvage_final_output(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
        output_model: Type[T],
        profile: LLMCodeDispatchProfile,
        run_id: str,
        node_id: str,
        stream_key: str,
        tc: Any,
    ) -> Tuple[Optional[T], Optional[CompletionUsage], str]:
        """Spend one extra round with ``tool_choice`` forced to ``final_output``.

        Called only once, after the turn loop is exhausted. Never raises:
        a provider that rejects a forced tool choice, a malformed payload
        or an unparsable answer all come back as a reason string, so the
        caller still reports the ``max_turns`` failure — with the salvage
        outcome attached — instead of masking it with a second error.

        Args:
            client: The live SDK client the loop has been using.
            model: Resolved model id.
            messages: The conversation so far (copied, never mutated).
            args: The loop's completion args (copied, never mutated).
            output_model: Structured output model to validate against.
            profile: The dispatch profile (read for ``max_turns`` only).
            run_id: Flow run id, for the published events.
            node_id: Seat id, for the published events.
            stream_key: Redis stream the dispatch events go to.
            tc: Trace context from ``_safe_emit_before_call``.

        Returns:
            ``(result, usage, error)``. ``result`` is ``None`` when nothing
            could be recovered, in which case ``error`` says why; ``usage``
            is whatever the round reported, so the caller can still bill it.
        """
        salvage_messages = [*messages, {"role": "user", "content": self._salvage_nudge(output_model)}]
        salvage_args = dict(args)
        salvage_args["tool_choice"] = {
            "type": "function",
            "function": {"name": "final_output"},
        }

        round_t0 = time.perf_counter()
        try:
            response = await self._chat_completion(
                client=client,
                model=model,
                messages=salvage_messages,
                args=salvage_args,
            )
        except Exception as exc:  # noqa: BLE001 - a failed salvage is not a new failure mode
            self.logger.warning(
                "Forced final_output turn failed for %s after max_turns=%d: %s",
                node_id,
                profile.max_turns,
                exc,
            )
            return None, None, f"{type(exc).__name__}: {exc}"
        round_duration_ms = (time.perf_counter() - round_t0) * 1000

        message = self._response_message(response)
        content = self._message_content(message)
        tool_calls = self._message_tool_calls(message)
        usage, raw_usage = self._extract_usage(response)
        self._safe_emit_round_event(
            client,
            tc,
            model=model,
            round_number=profile.max_turns + 1,
            usage=usage,
            raw_usage=raw_usage,
            tool_calls=[self._tool_call_name(call) for call in tool_calls],
            duration_ms=round_duration_ms,
        )

        result: Optional[T] = None
        error = "model returned no final_output payload"
        for call in tool_calls:
            if self._tool_call_name(call) != "final_output":
                continue
            salvage_args_obj, arg_error = self._parse_tool_arguments(call)
            if salvage_args_obj is None:
                # A truncated salvage payload is the same failure the loop
                # now survives mid-run; here there is no next turn to
                # recover in, so it just becomes the reported reason
                # instead of an uncaught DispatchExecutionError.
                error = f"final_output arguments were unreadable: {arg_error}"
                break
            try:
                result = self._validate_final_tool(salvage_args_obj, output_model)
            except DispatchOutputValidationError as exc:
                error = f"final_output failed validation: {exc}"
            except (TypeError, ValueError) as exc:
                error = f"final_output arguments were unreadable: {exc}"
            break
        if result is None and content:
            # Some backends answer a forced tool choice with plain text.
            try:
                result = self._validate_text_output(content, output_model)
            except DispatchOutputValidationError as exc:
                error = f"assistant text was not a valid {output_model.__name__}: {exc}"

        if result is None:
            # No `dispatch.salvage_failed` kind: the caller raises, and
            # `dispatch()`'s handler already publishes `dispatch.failed`
            # carrying this reason in its message. One event, one story.
            return None, usage, error

        self.logger.warning(
            "Recovered %s from %s by forcing final_output after max_turns=%d — "
            "the task ran out of turns before closing on its own; treat its "
            "output as unverified.",
            output_model.__name__,
            node_id,
            profile.max_turns,
        )
        # Marked on the ordinary completion event rather than as a new
        # `DispatchEvent.kind`: a new kind would have to be threaded through
        # the session-state projection, the CLI renderer and both consoles
        # to earn its keep, and `salvaged` on the payload is already visible
        # in the run bundle.
        await self._publish_event(
            stream_key,
            kind="dispatch.completed",
            run_id=run_id,
            node_id=node_id,
            payload={
                "output_model": output_model.__name__,
                "salvaged": True,
                "max_turns": profile.max_turns,
                "incomplete_tasks": list(getattr(result, "incomplete_tasks", []) or []),
            },
        )
        return result, usage, ""

    def _create_client(self, profile: LLMCodeDispatchProfile, *, run_id: Optional[str] = None) -> Any:
        model_args = {
            "temperature": profile.temperature,
            "max_tokens": profile.max_tokens,
        }
        client = self._client_factory(profile.llm, model_args=model_args)
        # FEAT-479 M5: thread the run's per-run EventRegistry into the
        # constructed client so its `await self.events.emit(...)` calls
        # (clients/base.py:630) reach the run's ledger subscriber
        # synchronously (exactness) instead of the client lazily
        # self-creating its own isolated registry (mixin.py:113), which
        # would degrade delivery to fire-and-forget. §8 open question,
        # resolved: LLMFactory.create / _client_factory does NOT propagate
        # any registry — verified by reading factory.py's signature and
        # AbstractClient.__init__ (clients/base.py:372), which
        # unconditionally calls `self._init_events(forward_to_global=False)`,
        # always constructing a fresh, isolated registry. Threading it
        # explicitly here, post-construction, is therefore required.
        if run_id is not None and self._event_registry_resolver is not None:
            registry = self._event_registry_resolver(run_id)
            if registry is not None and hasattr(client, "_events_registry"):
                client._events_registry = registry  # the documented injection point
        return client

    @staticmethod
    async def _ensure_client_ready(client: Any) -> None:
        if getattr(client, "client", None) is not None:
            return
        ensure = getattr(client, "_ensure_client", None)
        if callable(ensure):
            await ensure()

    @staticmethod
    def _resolve_model(profile: LLMCodeDispatchProfile, client: Any) -> str:
        _provider, model = LLMFactory.parse_llm_string(profile.llm)
        resolved = (
            model
            or getattr(client, "model", None)
            or getattr(client, "default_model", None)
            or getattr(client, "_default_model", None)
        )
        if resolved is None:
            raise DispatchExecutionError(f"Could not resolve a model from llm={profile.llm!r}")
        return str(resolved)

    def _initial_messages(
        self,
        profile: LLMCodeDispatchProfile,
        brief: BaseModel,
        output_model: Type[BaseModel],
        *,
        cwd: str = "",
    ) -> List[Dict[str, Any]]:
        body = load_subagent_definition(profile.subagent)
        return [
            {
                "role": "system",
                "content": (
                    f"You are the `{profile.subagent}` dev-loop coding "
                    "subagent. Use the provided tools to inspect and update "
                    "only the current repository. Finish by calling "
                    "`final_output` with the exact structured result.\n\n"
                    # The loop's economics, stated once. Every line here
                    # answers a specific way observed seats burned their
                    # budget: one tool per turn, `cat > f` and `cd x && y`
                    # against a shell-less argv, and paths copied from the
                    # main repo instead of the worktree.
                    "How this loop works — it decides whether you finish:\n"
                    f"- Your budget is {profile.max_turns} turns. One turn is "
                    "one assistant message, no matter how many tools it "
                    "calls, so put every independent read/search of a step "
                    "in ONE message. Reading five files one per turn spends "
                    "five turns for nothing.\n"
                    "- `run_command` execs a bare argv: there is NO shell, so "
                    "no pipes, no `>` redirection, no `&&`, no `cd` — to run "
                    "in a subdirectory pass its `cwd` argument. Create "
                    "files with `write_file` and change them with "
                    "`edit_file` — not `cat >`, `sed -i` or `python -c`, and "
                    "not a unified diff unless nothing else fits.\n"
                    + (
                        f"- You are working in {cwd} — every tool path "
                        "resolves there. The brief may also name a "
                        "`repo_path`: that is a DIFFERENT checkout your "
                        "tools cannot see. Use worktree-relative paths.\n"
                        if cwd
                        else "- Every path is relative to the worktree you "
                        "are in; absolute paths into another checkout are "
                        "not visible to your tools.\n"
                    ) +
                    f"- `run_command` only runs: "
                    f"{', '.join(profile.allowed_commands)}.\n\n"
                    f"Subagent instructions:\n{body}"
                ),
            },
            {
                "role": "user",
                "content": self._build_prompt(brief, output_model),
            },
        ]

    def _completion_args(
        self,
        profile: LLMCodeDispatchProfile,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        args: Dict[str, Any] = {
            "tools": tools,
            "tool_choice": "auto",
            # Read from the profile (default True): one turn per tool call
            # is what made whole tasks die against `max_turns`.
            "parallel_tool_calls": getattr(profile, "parallel_tool_calls", True),
            "max_tokens": profile.max_tokens,
        }
        if profile.temperature is not None:
            args["temperature"] = profile.temperature
        if profile.enable_thinking:
            args["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": True,
                    "clear_thinking": profile.clear_thinking,
                }
            }
        return args

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        method = getattr(client, "_chat_completion", None)
        if not callable(method):
            raise DispatchExecutionError(f"Client {type(client).__name__} does not expose chat completion")
        return await method(
            model=model,
            messages=messages,
            use_tools=True,
            **args,
        )

    # ------------------------------------------------------------------
    # FEAT-405 Module 6: per-round telemetry — the FEAT-397 emitter trio,
    # driven from this loop instead of a client's ask(). Every "_safe_"
    # method here tolerates a client that lacks the emitter methods (a
    # test double, a non-AbstractClient) — dispatch must keep working
    # either way, in the same spirit as the `_chat_completion` guard
    # above. NO accumulation anywhere in this file — one event per round.
    # ------------------------------------------------------------------

    @staticmethod
    def _client_display_name(client: Any) -> str:
        """Best-effort provider identifier for the emitted events."""
        return str(getattr(client, "client_name", None) or getattr(client, "client_type", None) or "unknown")

    def _safe_emit_before_call(self, client: Any, *, model: str, has_tools: bool) -> Any:
        """Call ``client._emit_before_call`` if the client exposes it.

        Returns the ``TraceContext`` it returns, or ``None`` when the
        client has no emitter methods — every other ``_safe_emit_*``
        method below treats ``None`` as "nothing to do".
        """
        method = getattr(client, "_emit_before_call", None)
        if not callable(method):
            return None
        return method(
            client_name=self._client_display_name(client),
            model=model,
            has_tools=has_tools,
        )

    def _safe_emit_round_event(
        self,
        client: Any,
        tc: Any,
        *,
        model: str,
        round_number: int,
        usage: Optional[CompletionUsage],
        raw_usage: Optional[Dict[str, Any]],
        tool_calls: List[str],
        duration_ms: float,
    ) -> None:
        """Call ``client._emit_round_event`` for one turn of the loop.

        ``round_number`` is 1-indexed. ``usage``/``raw_usage`` may be
        ``None`` — legal per the trio's own contract. No-op when ``tc`` is
        ``None`` (client had no emitter methods) or the client lacks
        ``_emit_round_event`` specifically.
        """
        if tc is None:
            return
        method = getattr(client, "_emit_round_event", None)
        if not callable(method):
            return
        method(
            tc,
            client_name=self._client_display_name(client),
            model=model,
            round_number=round_number,
            usage=usage,
            raw_usage=raw_usage,
            tool_calls=tool_calls,
            duration_ms=duration_ms,
        )

    async def _safe_emit_after_call(
        self,
        client: Any,
        tc: Any,
        *,
        model: str,
        duration_ms: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> None:
        """Call ``client._emit_after_call`` once, at the end of the dispatch.

        ``input_tokens``/``output_tokens`` (FEAT-479) carry the per-call
        total accumulated across the turn loop via
        ``CompletionUsage.__add__`` — see the accumulation comment at the
        top of :meth:`_dispatch_loop`. ``None`` means no round reported
        usage; never fabricate ``0``.
        """
        if tc is None:
            return
        method = getattr(client, "_emit_after_call", None)
        if not callable(method):
            return
        await method(
            tc,
            client_name=self._client_display_name(client),
            model=model,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @staticmethod
    def _extract_usage(response: Any) -> tuple[Optional[CompletionUsage], Optional[Dict[str, Any]]]:
        """Extract this turn's usage from an OpenAI-shaped completion response.

        Defensive: providers differ in whether/how they report usage on
        each turn. Returns ``(None, None)`` when absent — legal per
        ``_emit_round_event``'s contract, never raises.
        """
        usage_obj = getattr(response, "usage", None)
        if usage_obj is None:
            return None, None
        if hasattr(usage_obj, "model_dump"):
            raw_usage: Dict[str, Any] = usage_obj.model_dump()
        elif isinstance(usage_obj, dict):
            raw_usage = dict(usage_obj)
        else:
            raw_usage = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
                "completion_tokens": getattr(usage_obj, "completion_tokens", None),
                "total_tokens": getattr(usage_obj, "total_tokens", None),
            }
        try:
            # ``CompletionUsage.from_openai`` reads ATTRIBUTES. A backend
            # that reports usage as a plain dict (some OpenAI-compatible
            # gateways do) would otherwise yield a silently zeroed usage —
            # tokens reported as 0 rather than as unreported. Adapt the
            # already-normalized ``raw_usage`` mapping to attributes.
            source: Any = usage_obj
            if isinstance(usage_obj, dict):
                source = SimpleNamespace(**raw_usage)
            usage = CompletionUsage.from_openai(source)
        except Exception:  # noqa: BLE001 - usage extraction must never break dispatch
            usage = None
        return usage, raw_usage

    def _tool_schemas(self, output_model: Type[BaseModel]) -> List[Dict[str, Any]]:
        return [
            self._function_tool(
                "read_file",
                "Read a UTF-8 text file under the current repository.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer", "minimum": 1},
                        "max_lines": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 400,
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "list_files",
                "List files under a repository directory.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 500,
                            "default": 100,
                        },
                    },
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "search_files",
                "Search repository text files for a literal string.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "file_glob": {"type": "string"},
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 200,
                            "default": 50,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "write_file",
                "Create or overwrite a UTF-8 text file under the current "
                "repository, creating parent directories as needed. Prefer "
                "this over `apply_patch` for a brand-new file or a rewrite: "
                "`run_command` runs a bare argv with NO shell, so `cat > f`, "
                "redirection and pipes do not work there. A file bigger than "
                "roughly 150 lines MUST be written in several calls — one "
                'overwrite followed by `mode="append"` calls — because a '
                "single call carrying the whole file runs past the "
                "output-token limit and is discarded unread.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": ["overwrite", "append"],
                            "default": "overwrite",
                            "description": (
                                "'overwrite' replaces the file (default); "
                                "'append' adds to the end, for writing a "
                                "large file across several calls."
                            ),
                        },
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "edit_file",
                "Replace an exact string in an existing file. PREFER THIS for "
                "editing: it needs no line numbers, no hunk headers and no "
                "context lines, so it cannot be 'corrupt' the way a diff can. "
                "`old_string` must match the file byte-for-byte and appear "
                "exactly once unless `replace_all` is true — include a few "
                "surrounding lines to make it unique.",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                        "replace_all": {"type": "boolean", "default": False},
                    },
                    "required": ["path", "old_string", "new_string"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "apply_patch",
                "Apply a git unified diff. Last resort — use `edit_file` for "
                "an edit and `write_file` for a new file; both avoid the "
                "hunk-header arithmetic that makes diffs fail.",
                {
                    "type": "object",
                    "properties": {"patch": {"type": "string"}},
                    "required": ["patch"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "run_command",
                "Run an allow-listed argv command in the repository. There is "
                "NO shell: `argv` is exec'd directly, so pipes, redirection, "
                "`&&` and `cd` do not work. To run somewhere other than the "
                "repository root, pass `cwd` instead of prefixing `cd`.",
                {
                    "type": "object",
                    "properties": {
                        "argv": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                        "cwd": {
                            "type": "string",
                            "description": (
                                "Directory to run in, relative to the "
                                "repository root. Replaces `cd <dir> && ...`."
                            ),
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 3600,
                        },
                    },
                    "required": ["argv"],
                    "additionalProperties": False,
                },
            ),
            self._function_tool(
                "final_output",
                "Return the final structured DevelopmentOutput payload.",
                output_model.model_json_schema(),
            ),
        ]

    @staticmethod
    def _function_tool(
        name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

    async def _run_tool(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        cwd: str,
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
        try:
            if tool_name == "read_file":
                return self._tool_read_file(cwd, tool_args)
            if tool_name == "list_files":
                return self._tool_list_files(cwd, tool_args)
            if tool_name == "search_files":
                return await self._tool_search_files(cwd, tool_args)
            if tool_name == "write_file":
                return self._tool_write_file(cwd, tool_args, profile)
            if tool_name == "edit_file":
                return self._tool_edit_file(cwd, tool_args, profile)
            if tool_name == "apply_patch":
                return await self._tool_apply_patch(cwd, tool_args, profile)
            if tool_name == "run_command":
                return await self._tool_run_command(cwd, tool_args, profile)
            return {"ok": False, "error": f"unknown tool {tool_name!r}"}
        except Exception as exc:  # tool failures are returned to the model
            return {
                "ok": False,
                "error_class": type(exc).__name__,
                "error": str(exc),
            }

    def _tool_read_file(self, cwd: str, args: Dict[str, Any]) -> Dict[str, Any]:
        path = self._resolve_repo_path(cwd, str(args["path"]))
        if not os.path.isfile(path):
            # The brief names a task by id, never by filename, and the
            # subagent instructions only show the SHAPE
            # `TASK-<NNN>-<slug>.md` — so a seat's very first turn was a
            # guess at <slug> (it reaches for the feature slug; the real
            # one is per-task), and it then spent more turns hunting.
            # Listing the actual neighbours turns that into one turn.
            return {
                "ok": False,
                "error_class": "FileNotFoundError",
                "error": f"{os.path.relpath(path, cwd)} does not exist",
                "did_you_mean": self._suggest_siblings(path),
            }
        start_line = int(args.get("start_line") or 1)
        max_lines = min(int(args.get("max_lines") or 400), 1000)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        return {
            "ok": True,
            "path": os.path.relpath(path, cwd),
            "start_line": start_line,
            "line_count": len(selected),
            "content": "".join(selected)[:20000],
        }

    @staticmethod
    def _suggest_siblings(path: str, limit: int = 5) -> List[str]:
        """Name the files that the missing one was probably meant to be.

        Prefix matches first (``TASK-2684-`` finds the one task file whose
        slug the caller could not know), then fuzzy matches for a typo.

        Args:
            path: The absolute path that did not exist.
            limit: Maximum number of suggestions.

        Returns:
            Sibling basenames, best first; empty when the parent directory
            does not exist or holds nothing similar.
        """
        parent = os.path.dirname(path)
        wanted = os.path.basename(path)
        try:
            entries = sorted(os.listdir(parent))
        except OSError:
            return []

        # Score by shared prefix and keep only the BEST scorers: a flat
        # threshold would return every `TASK-*.md` in the directory, which
        # is noise, not an answer. `TASK-2684-<wrong-slug>.md` scores 10
        # against its real sibling and 6 against any other task.
        scored = [
            (len(os.path.commonprefix([entry, wanted])), entry)
            for entry in entries
        ]
        best = max((score for score, _ in scored), default=0)
        if best >= 5:
            return [entry for score, entry in scored if score == best][:limit]
        return difflib.get_close_matches(wanted, entries, n=limit, cutoff=0.6)

    def _tool_list_files(self, cwd: str, args: Dict[str, Any]) -> Dict[str, Any]:
        root = self._resolve_repo_path(cwd, str(args.get("path") or "."))
        max_results = min(int(args.get("max_results") or 100), 500)
        if not os.path.isdir(root):
            raise ValueError(f"{args.get('path')!r} is not a directory")
        results: List[str] = []
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in sorted(dirnames) if name not in {".git", ".venv", "__pycache__"}]
            for filename in sorted(filenames):
                results.append(os.path.relpath(os.path.join(current_root, filename), cwd))
                if len(results) >= max_results:
                    return {"ok": True, "files": results, "truncated": True}
        return {"ok": True, "files": results, "truncated": False}

    async def _tool_search_files(
        self,
        cwd: str,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Search the repository, preferring ripgrep and falling back to git.

        A host without ``rg`` installed used to fail EVERY search with the
        bare ``[Errno 2] No such file or directory`` that
        :meth:`_run_argv` returns for a missing binary. To the model that
        reads as a wrong *path*, not a missing *tool*: observed seats
        re-ran the same search against invented paths, then fell back to
        ``grep`` (not allow-listed at the time), and spent a fifth of a
        60-turn budget discovering that their only search tool was dead.
        ``git grep`` is on every host this dispatcher can run on — the
        worktree is a git repo by construction — so the fallback is free,
        and when neither backend exists the error now names the cause.
        """
        query = str(args["query"])
        if not query:
            raise ValueError("query must not be empty")
        path = self._resolve_repo_path(cwd, str(args.get("path") or "."))
        max_results = min(int(args.get("max_results") or 50), 200)
        file_glob = args.get("file_glob")

        command, backend = self._search_command(
            query=query,
            rel_path=os.path.relpath(path, cwd),
            file_glob=str(file_glob) if file_glob else None,
        )
        if command is None:
            return {
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": (
                    "no search backend available: neither 'rg' (ripgrep) nor "
                    "'git' is installed on this host. This is NOT a bad path "
                    "— use read_file/list_files instead of retrying."
                ),
            }
        result = await self._run_argv(command, cwd=cwd, timeout=30)
        lines = result["stdout"].splitlines()
        if result["exit_code"] not in {0, 1}:
            return {**result, "ok": False, "backend": backend}
        return {
            "ok": True,
            "backend": backend,
            "matches": lines[:max_results],
            "truncated": len(lines) > max_results,
        }

    @staticmethod
    def _search_command(
        *,
        query: str,
        rel_path: str,
        file_glob: Optional[str],
    ) -> Tuple[Optional[List[str]], str]:
        """Build the argv for the best available search backend.

        Both backends exit 0 on a match and 1 on no match, so
        :meth:`_tool_search_files` treats the two uniformly.

        Args:
            query: Literal (non-regex) string to search for.
            rel_path: Search root, relative to ``cwd``.
            file_glob: Optional filename glob to restrict the search.

        Returns:
            ``(argv, backend_name)``, or ``(None, "")`` when no backend is
            installed.
        """
        if shutil.which("rg"):
            command = [
                "rg",
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "--fixed-strings",
            ]
            if file_glob:
                command.extend(["--glob", file_glob])
            command.extend([query, rel_path])
            return command, "rg"
        if shutil.which("git"):
            # `--untracked` so a file the seat just wrote is searchable;
            # `-e` so a query starting with '-' is not read as a flag.
            pathspec = os.path.normpath(rel_path)
            if file_glob:
                pathspec = f":(glob){os.path.join(pathspec, '**', file_glob)}"
            return (
                [
                    "git",
                    "grep",
                    "--line-number",
                    "--no-color",
                    "--fixed-strings",
                    "--untracked",
                    "-e",
                    query,
                    "--",
                    pathspec,
                ],
                "git-grep",
            )
        return None, ""

    #: `git apply` retry ladder, strictest first. Each rung fixes a
    #: failure mode LLM-authored diffs actually hit: `--recount` ignores
    #: the hunk-header line counts (models mis-add them constantly) and
    #: `-C1` relaxes context matching when the surrounding lines drifted.
    #: A diff that survives none of these is not worth another turn — the
    #: tool result says to use edit_file instead.
    _PATCH_FLAG_LADDER: Tuple[Tuple[str, ...], ...] = (
        (),
        ("--recount",),
        ("--recount", "-C1"),
    )

    def _tool_edit_file(
        self,
        cwd: str,
        args: Dict[str, Any],
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
        """Replace an exact string in a file — the reliable edit primitive.

        ``apply_patch`` was the only way to change an existing file, and a
        unified diff is the one edit format a model has to get arithmetic
        right for: observed seats lost turns to "corrupt patch at line N"
        over and over. An exact string replacement has no line numbers, no
        hunk headers and no context arithmetic, so it either matches or
        reports precisely why it did not.

        Args:
            cwd: Worktree root; ``path`` may not escape it.
            args: ``{"path", "old_string", "new_string", "replace_all"?}``.
            profile: Dispatch profile, read for its sandbox mode.

        Returns:
            A tool-result dict; ``ok`` is False (never an exception) when
            the match is missing or ambiguous, so the model gets the count
            back and can widen ``old_string``.

        Raises:
            ValueError: If the sandbox is read-only, the arguments are not
                strings, or ``path`` escapes ``cwd``.
        """
        if profile.sandbox != "workspace-write":
            raise ValueError("edit_file requires workspace-write sandbox")
        old_string = args.get("old_string")
        new_string = args.get("new_string")
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            raise ValueError("old_string and new_string must be strings")
        if not old_string:
            raise ValueError("old_string must not be empty; use write_file to create a file")
        path = self._resolve_repo_path(cwd, str(args["path"]))
        rel_path = os.path.relpath(path, cwd)
        if not os.path.isfile(path):
            return {
                "ok": False,
                "path": rel_path,
                "error": f"{rel_path} does not exist; use write_file to create it",
                "did_you_mean": self._suggest_siblings(path),
            }

        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        occurrences = content.count(old_string)
        if occurrences == 0:
            return {
                "ok": False,
                "path": rel_path,
                "error": (
                    "old_string not found. It must match the file "
                    "byte-for-byte, including indentation — read the file "
                    "and copy the exact text."
                ),
            }
        replace_all = bool(args.get("replace_all"))
        if occurrences > 1 and not replace_all:
            return {
                "ok": False,
                "path": rel_path,
                "occurrences": occurrences,
                "error": (
                    f"old_string matches {occurrences} places. Add "
                    "surrounding lines to make it unique, or pass "
                    "replace_all=true."
                ),
            }

        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content.replace(old_string, new_string))
        return {
            "ok": True,
            "path": rel_path,
            "replacements": occurrences if replace_all else 1,
        }

    def _tool_write_file(
        self,
        cwd: str,
        args: Dict[str, Any],
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
        """Write a whole file, cwd-confined.

        The loop shipped without this, leaving ``apply_patch`` as the only
        way to create a file — and a unified diff a model has to get
        byte-exact is the wrong instrument for "write this new module".
        Observed seats worked around it with `cat > path` (impossible:
        ``run_command`` execs an argv with no shell), in-place `sed`
        line-insert incantations,
        and `python -c` scripts embedding the whole file as a string
        literal — each attempt costing a turn, and the `python -c` ones
        also spending the output-token budget twice on the same content.

        ``mode="append"`` exists because one call cannot carry an
        arbitrarily large file: past ``max_tokens`` the provider truncates
        the tool call and the whole payload is unparseable and lost. A
        file written in several appends costs a few extra turns and always
        lands.

        Args:
            cwd: Worktree root; ``path`` may not escape it.
            args: ``{"path": str, "content": str, "mode": "overwrite"|"append"}``.
            profile: Dispatch profile, read for its sandbox mode.

        Returns:
            A tool-result dict with the relative path, the mode used, the
            bytes written by THIS call and the file's resulting size.

        Raises:
            ValueError: If the sandbox is read-only, ``content`` is not a
                string, ``mode`` is unknown, or ``path`` escapes ``cwd``.
        """
        if profile.sandbox != "workspace-write":
            raise ValueError("write_file requires workspace-write sandbox")
        content = args.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        mode = str(args.get("mode") or "overwrite")
        if mode not in ("overwrite", "append"):
            raise ValueError("mode must be 'overwrite' or 'append'")
        path = self._resolve_repo_path(cwd, str(args["path"]))
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        existed = os.path.exists(path)
        with open(path, "a" if mode == "append" else "w", encoding="utf-8") as fh:
            fh.write(content)
        written = len(content.encode("utf-8"))
        return {
            "ok": True,
            "path": os.path.relpath(path, cwd),
            "mode": mode,
            "created": not existed,
            "bytes_written": written,
            "file_bytes": os.path.getsize(path),
        }

    async def _tool_apply_patch(
        self,
        cwd: str,
        args: Dict[str, Any],
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
        if profile.sandbox != "workspace-write":
            raise ValueError("apply_patch requires workspace-write sandbox")
        patch = str(args["patch"])
        self._validate_patch_paths(cwd, patch)
        if not patch.endswith("\n"):
            # `git apply` reports "corrupt patch at line N" for a diff whose
            # last line has no newline — a pure serialisation artifact of a
            # model emitting the patch as a JSON string.
            patch += "\n"

        last: Dict[str, Any] = {}
        for flags in self._PATCH_FLAG_LADDER:
            check = await self._run_argv(
                ["git", "apply", "--check", *flags, "-"],
                cwd=cwd,
                timeout=profile.command_timeout_seconds,
                stdin=patch,
            )
            last = check
            if check["exit_code"] != 0:
                continue
            applied = await self._run_argv(
                ["git", "apply", *flags, "-"],
                cwd=cwd,
                timeout=profile.command_timeout_seconds,
                stdin=patch,
            )
            return {
                **applied,
                "ok": applied["exit_code"] == 0,
                "flags": list(flags),
            }

        return {
            **last,
            "ok": False,
            "hint": (
                "The diff did not apply, with or without --recount/-C1. Do "
                "NOT retry another diff — read the file and use `edit_file` "
                "(exact string replacement), or `write_file` to rewrite it."
            ),
        }

    async def _tool_run_command(
        self,
        cwd: str,
        args: Dict[str, Any],
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
        argv = args.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv):
            raise ValueError("argv must be a non-empty list of strings")
        command = os.path.basename(argv[0])
        if command not in set(profile.allowed_commands):
            return {
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": f"command {command!r} is not allow-listed",
                # A bare "not allow-listed" told the model nothing about
                # what to do next, and `cd` in particular is not a missing
                # permission at all — it is a shell builtin that can never
                # work through an exec'd argv, so a seat could burn turns
                # re-trying `cd x && pytest` forever.
                "hint": self._rejected_command_hint(command, profile),
            }
        path_error = self._validate_command_paths(cwd, argv, profile)
        if path_error is not None:
            return {
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": path_error,
                "hint": (
                    "Your tools and commands only reach this worktree. Use "
                    "worktree-relative paths, or run_command's `cwd` "
                    "argument to work in a subdirectory."
                ),
            }
        run_cwd = cwd
        if args.get("cwd"):
            run_cwd = self._resolve_repo_path(cwd, str(args["cwd"]))
            if not os.path.isdir(run_cwd):
                return {
                    "ok": False,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": f"cwd {args['cwd']!r} is not a directory",
                }
        timeout = min(
            int(args.get("timeout_seconds") or profile.command_timeout_seconds),
            profile.command_timeout_seconds,
        )
        result = await self._run_argv(argv, cwd=run_cwd, timeout=timeout)
        return {**result, "ok": result["exit_code"] == 0}

    #: A token is treated as a path when it starts one of these ways.
    #: Anything else (a `-k` expression, a module name, a git ref) is left
    #: alone — the guard must not reject legitimate non-path arguments.
    _PATH_TOKEN_PREFIXES: Tuple[str, ...] = ("/", "./", "../", "~/")

    #: Absolute paths embedded in an inline script (`python -c "..."`).
    #: Deliberately conservative: a bare `/`-rooted, path-shaped run of
    #: characters, not every string containing a slash.
    _ABS_PATH_IN_TEXT = re.compile(r"(?<![\w/])(/(?:[\w.@+-]+/)*[\w.@+-]+)")

    #: Flags whose VALUE is an inline program rather than a path.
    _INLINE_CODE_FLAGS: frozenset = frozenset({"-c", "--command"})

    def _validate_command_paths(
        self,
        cwd: str,
        argv: Sequence[str],
        profile: LLMCodeDispatchProfile,
    ) -> Optional[str]:
        """Reject an argv that reaches outside the worktree.

        ``run_command`` was the one tool with no path checking at all: every
        other tool resolves through :meth:`_resolve_repo_path`, but a seat
        could run ``pytest /home/user/repo/...`` against the MAIN clone, or
        ``python -c "open('/home/user/repo/x.py','w')..."`` and write there
        — which is how stray files appear outside a worktree.

        This is a guard-rail, not a jail. The command still runs as this
        process's user, and a script can build a path at runtime that no
        static check can see. It closes the accidental route, which is the
        one observed in practice; real isolation needs a container.

        Args:
            cwd: The worktree every command is confined to.
            argv: The command as the model wrote it.
            profile: Dispatch profile; ``restrict_command_paths`` disables
                this check.

        Returns:
            An error message naming the offending argument, or ``None``
            when every path argument stays inside ``cwd``.
        """
        if not getattr(profile, "restrict_command_paths", True):
            return None
        base = os.path.abspath(cwd)
        previous = ""
        for index, token in enumerate(argv):
            # argv[0] is the executable: already checked by basename against
            # the allow-list, and legitimately lives in /usr/bin or .venv.
            if index == 0:
                previous = token
                continue
            for candidate in self._path_candidates(token, previous):
                resolved = os.path.abspath(
                    os.path.expanduser(candidate)
                    if candidate.startswith("~")
                    else os.path.join(base, candidate)
                )
                if not self._is_within(base, resolved):
                    return (
                        f"argument {candidate!r} points outside the worktree "
                        f"({base}); commands may only touch it"
                    )
            previous = token
        return None

    @classmethod
    def _path_candidates(cls, token: str, previous: str) -> List[str]:
        """Extract the path-shaped parts of one argv token.

        Args:
            token: The argument to inspect.
            previous: The argument before it, so ``-c``'s value is read as
                inline code rather than as a path.

        Returns:
            Path-shaped strings found in ``token``; possibly empty.
        """
        if previous in cls._INLINE_CODE_FLAGS:
            return cls._ABS_PATH_IN_TEXT.findall(token)

        value = token
        # `--rootdir=/x`, `-C/x`: the path is the value half.
        if value.startswith("-") and "=" in value:
            value = value.split("=", 1)[1]
        elif value.startswith("-"):
            return []
        # `pytest path/test_x.py::TestCase::test_y` — strip the node id.
        value = value.split("::", 1)[0]
        if not value or not value.startswith(cls._PATH_TOKEN_PREFIXES):
            return []
        return [value]

    @staticmethod
    def _rejected_command_hint(
        command: str,
        profile: LLMCodeDispatchProfile,
    ) -> str:
        """Say what to do instead of the command that was just rejected.

        Args:
            command: The rejected executable name.
            profile: Dispatch profile, read for its allow-list.

        Returns:
            A one-line, actionable hint.
        """
        shell_builtins = {
            "cd": "pass `cwd` to run_command instead of `cd <dir> && ...`",
            "export": "environment changes do not persist between calls",
            "source": "there is no shell to source into",
            ".": "there is no shell to source into",
        }
        if command in shell_builtins:
            return (
                f"`{command}` is a shell builtin, not a program: this loop "
                f"execs a bare argv with no shell. {shell_builtins[command]}."
            )
        return (
            "run_command only runs: "
            f"{', '.join(profile.allowed_commands)}. Use read_file / "
            "search_files / write_file / edit_file for file work."
        )

    async def _run_argv(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout: int,
        stdin: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not argv:
            raise ValueError("argv must not be empty")
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=8 * 1024 * 1024,
            )
        except FileNotFoundError as exc:
            return {
                "exit_code": 127,
                "stdout": "",
                "stderr": str(exc),
            }
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(stdin.encode("utf-8") if stdin is not None else None),
                timeout=timeout,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return {
                "exit_code": None,
                "stdout": "",
                "stderr": f"command timed out after {timeout}s",
            }
        stdout = stdout_b.decode("utf-8", errors="replace")[-20000:]
        stderr = stderr_b.decode("utf-8", errors="replace")[-20000:]
        return {
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    def _validate_patch_paths(self, cwd: str, patch: str) -> None:
        for raw in patch.splitlines():
            path: Optional[str] = None
            if raw.startswith("diff --git "):
                parts = shlex.split(raw)
                for token in parts[2:4]:
                    if token.startswith(("a/", "b/")):
                        path = token[2:]
                        self._resolve_repo_path(cwd, path)
            elif raw.startswith(("--- ", "+++ ")):
                token = raw[4:].strip().split("\t", 1)[0]
                if token == "/dev/null":
                    continue
                if token.startswith(("a/", "b/")):
                    path = token[2:]
                else:
                    path = token
                self._resolve_repo_path(cwd, path)

    def _resolve_repo_path(self, cwd: str, path: str) -> str:
        """Resolve a tool path against ``cwd``, confined to it.

        An ABSOLUTE path pointing at the same file in a different checkout
        is re-anchored onto ``cwd`` when the equivalent path exists there.
        The brief handed to the model carries both ``repo_path`` (the main
        clone) and ``worktree_path``, and the seat works in the worktree —
        so a model that reasonably composes
        ``<repo_path>/sdd/tasks/active/TASK-2681-....md`` used to lose a
        whole turn to "escapes cwd" and, worse, sometimes never read its
        own task file. Re-anchoring is not a hole in the sandbox: the
        result is still under ``cwd``, and the tool result echoes the
        relative path actually used, so the model sees what it got.

        Relative traversal (``../outside``) stays a hard error — that is a
        genuine escape attempt, not a checkout mix-up.

        Args:
            cwd: The worktree root every tool is confined to.
            path: Path as the model wrote it.

        Returns:
            An absolute path inside ``cwd``.

        Raises:
            ValueError: If the path escapes ``cwd`` and cannot be
                re-anchored.
        """
        base = os.path.abspath(cwd)
        if os.path.isabs(path):
            target = os.path.abspath(path)
        else:
            target = os.path.abspath(os.path.join(base, path))
        if self._is_within(base, target):
            return target

        if os.path.isabs(path):
            remapped = self._reanchor_into_cwd(base, target)
            if remapped is not None:
                self.logger.warning(
                    "re-anchored %r onto the worktree as %r — the brief's "
                    "repo_path is NOT what the tools see",
                    path,
                    os.path.relpath(remapped, base),
                )
                return remapped

        raise ValueError(
            f"path {path!r} escapes cwd={base!r}. Your tools only see that "
            "worktree; the brief's repo_path is a different checkout. Retry "
            "with a path relative to the worktree."
        )

    @staticmethod
    def _is_within(base: str, target: str) -> bool:
        """Whether ``target`` is ``base`` or lives under it."""
        try:
            return os.path.commonpath([base, target]) == base
        except ValueError:  # different drives / unrelated roots
            return False

    @staticmethod
    def _reanchor_into_cwd(base: str, target: str) -> Optional[str]:
        """Find the longest tail of ``target`` that resolves inside ``base``.

        Longest-first so a deep path keeps its structure: it stops at the
        first tail whose parent directory exists under ``base``, which
        prevents ``/a/b/c/deep/file.py`` from collapsing onto
        ``<base>/file.py``.

        Args:
            base: Absolute worktree root.
            target: Absolute path from another checkout.

        Returns:
            The re-anchored absolute path, or ``None`` when no tail fits.
        """
        parts = [part for part in target.split(os.sep) if part]
        for start in range(1, len(parts)):
            tail = parts[start:]
            candidate = os.path.join(base, *tail)
            if os.path.exists(candidate):
                return candidate
            # A directory match only counts for a multi-segment tail: a
            # bare filename always "matches" (its parent is `base`), which
            # would turn /etc/passwd into <base>/passwd and let write_file
            # scatter stray files at the worktree root.
            if len(tail) >= 2 and os.path.isdir(os.path.dirname(candidate)):
                return candidate
        return None

    def _validate_final_tool(
        self,
        payload: Dict[str, Any],
        output_model: Type[T],
    ) -> T:
        try:
            return output_model.model_validate(payload)
        except ValidationError as exc:
            raise DispatchOutputValidationError(
                f"Output failed {output_model.__name__} validation: {exc}",
                raw_payload=json.dumps(payload, default=str),
            ) from exc

    def _validate_text_output(self, text: str, output_model: Type[T]) -> T:
        if not text.strip():
            raise DispatchOutputValidationError(
                "No assistant text found in dispatch result.",
                raw_payload="",
            )
        json_text = ClaudeCodeDispatcher._extract_last_json_object(text)
        if json_text is None:
            raise DispatchOutputValidationError(
                "Could not locate a JSON object in the assistant output.",
                raw_payload=text,
            )
        try:
            return output_model.model_validate_json(json_text)
        except ValidationError as exc:
            raise DispatchOutputValidationError(
                f"Output failed {output_model.__name__} validation: {exc}",
                raw_payload=json_text,
            ) from exc

    def _enforce_cwd_under_worktree_base(self, cwd: str) -> None:
        base = os.path.abspath(conf.WORKTREE_BASE_PATH)
        target = os.path.abspath(cwd)
        try:
            common = os.path.commonpath([base, target])
        except ValueError:
            common = ""
        if common != base:
            raise DispatchExecutionError(f"cwd {cwd!r} is not under WORKTREE_BASE_PATH={base!r}")

    @staticmethod
    def _response_message(response: Any) -> Any:
        choices = getattr(response, "choices", None)
        if not choices:
            raise DispatchExecutionError("LLM response did not include choices")
        return choices[0].message

    @staticmethod
    def _message_content(message: Any) -> str:
        content = getattr(message, "content", "")
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return json.dumps(content, default=str)

    @staticmethod
    def _message_tool_calls(message: Any) -> List[Any]:
        return list(getattr(message, "tool_calls", None) or [])

    @staticmethod
    def _tool_call_id(call: Any) -> str:
        return str(getattr(call, "id", "") or "")

    @staticmethod
    def _tool_call_name(call: Any) -> str:
        function = getattr(call, "function", None)
        if isinstance(call, dict):
            function = call.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return str(getattr(function, "name", "") or "")

    @classmethod
    def _parse_tool_arguments(cls, call: Any) -> Tuple[Optional[Dict[str, Any]], str]:
        """Parse one tool call's arguments WITHOUT raising.

        A model that runs past ``max_tokens`` mid-tool-call returns a
        syntactically truncated ``arguments`` string (observed while
        writing a whole ~1000-line test file through ``write_file``). That
        is a recoverable model mistake, not a broken dispatch: the caller
        feeds the failure back as a tool result — exactly like an
        ``apply_patch`` that did not apply — instead of throwing away a
        seat that has already spent 30 turns of real work.

        Args:
            call: The provider's tool-call object (or dict).

        Returns:
            ``(arguments, "")`` on success, or ``(None, reason)`` when the
            arguments are unusable. ``reason`` is operator/model-readable
            and never contains the (possibly enormous) payload itself —
            only its size.
        """
        function = getattr(call, "function", None)
        if isinstance(call, dict):
            function = call.get("function")
        raw_args: Any
        if isinstance(function, dict):
            raw_args = function.get("arguments") or "{}"
        else:
            raw_args = getattr(function, "arguments", "{}")
        if isinstance(raw_args, dict):
            return raw_args, ""
        if not isinstance(raw_args, str):
            return None, f"tool arguments must be a JSON object, got {type(raw_args).__name__}"
        try:
            parsed = json.loads(raw_args)
        except ValueError as exc:
            return None, (
                f"arguments are not valid JSON ({exc}); "
                f"{len(raw_args)} characters were received"
            )
        if not isinstance(parsed, dict):
            return None, "tool arguments JSON must be an object"
        return parsed, ""

    @classmethod
    def _tool_call_arguments(cls, call: Any) -> Dict[str, Any]:
        """Raising wrapper around :meth:`_parse_tool_arguments`.

        Kept for the call sites where a bad payload genuinely is fatal.

        Args:
            call: The provider's tool-call object (or dict).

        Returns:
            The parsed arguments object.

        Raises:
            DispatchExecutionError: If the arguments are missing, not
                JSON, or not a JSON object.
        """
        parsed, error = cls._parse_tool_arguments(call)
        if parsed is None:
            raise DispatchExecutionError(f"Could not parse tool arguments: {error}")
        return parsed

    def _tool_call_to_openai_dict(
        self,
        call: Any,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Render a tool call for the assistant turn appended to ``messages``.

        Args:
            call: The provider's tool-call object (or dict).
            arguments: Pre-parsed arguments, when the caller already
                parsed them. ``None`` means "parse here"; a call whose
                arguments cannot be parsed is echoed back as a short
                marker object rather than re-injecting a truncated
                multi-kilobyte string into the context for the rest of
                the loop.

        Returns:
            An OpenAI-shaped ``tool_calls`` entry.
        """
        if arguments is None:
            arguments, error = self._parse_tool_arguments(call)
            if arguments is None:
                arguments = {"_discarded": error}
        return {
            "id": self._tool_call_id(call),
            "type": "function",
            "function": {
                "name": self._tool_call_name(call),
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        }

    @staticmethod
    def _finish_reason(response: Any) -> str:
        """Best-effort ``finish_reason`` of the first choice.

        Args:
            response: The raw chat-completion response.

        Returns:
            e.g. ``"stop"``, ``"tool_calls"``, ``"length"``; ``""`` when
            the backend does not report one.
        """
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        return str(getattr(choices[0], "finish_reason", "") or "")

    def _truncated_call_feedback(
        self,
        *,
        tool_name: str,
        reason: str,
        finish_reason: str,
        max_tokens: int,
    ) -> str:
        """Build the tool-result text handed back for an unusable call.

        Says what happened, why (the output-token ceiling), and the ONE
        concrete way out — chunked ``write_file`` appends — so the model
        does not simply resend the same oversized call and burn the rest
        of its budget.

        Args:
            tool_name: The tool whose arguments could not be read.
            reason: From :meth:`_parse_tool_arguments`.
            finish_reason: The round's finish reason, when reported.
            max_tokens: The profile's per-response output ceiling.

        Returns:
            The tool-result ``error`` string.
        """
        cut_off = finish_reason == "length"
        parts = [
            f"{tool_name}: {reason}.",
            (
                f"Your reply hit the output-token limit (max_tokens={max_tokens}) "
                "and was cut off mid-call."
                if cut_off
                else f"The call arrived incomplete (max_tokens={max_tokens})."
            ),
            "The call was DISCARDED - nothing was written. Do not resend it unchanged.",
        ]
        if tool_name in ("write_file", "apply_patch"):
            parts.append(
                "Write the file in pieces instead: call write_file with the "
                'first ~150 lines, then call write_file again with mode="append" '
                "for each following piece. To change an existing file, use "
                "edit_file on the one region that changes rather than "
                "rewriting the whole file."
            )
        else:
            parts.append("Retry with a smaller payload.")
        return " ".join(parts)

    @staticmethod
    def _output_field_blocks(output_model: Type[BaseModel]) -> Tuple[str, str]:
        """Render an output model's fields for a prompt.

        Shared by the opening prompt and the salvage nudge so the two can
        never describe the same model differently.

        Args:
            output_model: The structured output model.

        Returns:
            ``(fields_block, required_block)`` — an indented per-field
            listing, and a comma-separated list of the required names.
        """
        schema = output_model.model_json_schema()
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        field_lines: List[str] = []
        for fname, fmeta in properties.items():
            ftype = fmeta.get("type") or fmeta.get("$ref", "").rsplit("/", 1)[-1] or "any"
            fdesc = (fmeta.get("description") or "").strip()
            mandatory = " (required)" if fname in required else ""
            line = f"  - {fname}: {ftype}{mandatory}"
            if fdesc:
                line += f" — {fdesc}"
            field_lines.append(line)
        return (
            "\n".join(field_lines) or "  (no fields)",
            ", ".join(required) if required else "(none)",
        )

    def _build_prompt(
        self,
        brief: BaseModel,
        output_model: Type[BaseModel],
    ) -> str:
        brief_json = brief.model_dump_json()
        fields_block, required_block = self._output_field_blocks(output_model)
        return (
            f"Input brief:\n{brief_json}\n\n"
            f"Use tools to inspect and edit files as needed. When the work is "
            f"complete, call `final_output` with a JSON object matching the "
            f"`{output_model.__name__}` schema. Use these EXACT field names:\n"
            f"{fields_block}\n\n"
            f"Required fields: {required_block}."
        )

    async def _ensure_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    async def _publish_event(
        self,
        stream_key: str,
        *,
        kind: str,
        run_id: str,
        node_id: str,
        payload: Dict[str, Any],
    ) -> None:
        event = DispatchEvent(
            kind=kind,  # type: ignore[arg-type]
            ts=time.time(),
            run_id=run_id,
            node_id=node_id,
            payload=payload,
        )
        # FEAT-322 TASK-1852: dual-publish shim (see module-level docstring).
        _apply_to_session_host(event)
        try:
            redis_client = await self._ensure_redis()
        except Exception as exc:  # pragma: no cover - dev-mode fallback
            self.logger.warning(
                "Redis unavailable (%s); dropping event %s for %s",
                exc,
                kind,
                stream_key,
            )
            return
        maxlen = max(1, self.stream_ttl_seconds // 60)
        fields = {"event": event.model_dump_json()}
        try:
            await redis_client.xadd(stream_key, fields, maxlen=maxlen, approximate=True)
        except Exception as exc:  # pragma: no cover - best-effort publish
            self.logger.warning("Failed to XADD %s to %s: %s", kind, stream_key, exc)
