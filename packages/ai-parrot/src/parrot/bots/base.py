"""
BaseBot - Concrete implementation of AbstractBot.

This module provides BaseBot, a concrete implementation of the AbstractBot
abstract base class. It implements all required abstract methods.
"""
from typing import Optional, Union, Type, AsyncIterator, Any, List
from collections.abc import Callable
import inspect
import logging
import uuid
import asyncio
import time
import warnings
from pydantic import BaseModel
from ..memory import (
    ConversationTurn
)
from ..models import AIMessage, CompletionUsage, StructuredOutputConfig
from ..models.outputs import OutputMode
from ..outputs.a2ui.emission import finalize_a2ui_response  # FEAT-273 (TASK-1738)
from ..utils.helpers import RequestContext, _current_ctx
from ..security import PromptInjectionException
from ..security.redaction import OutputScrubber, ScrubPolicy  # FEAT-252 (TASK-1612)
from .prompts import (
    OUTPUT_SYSTEM_PROMPT
)
from .abstract import AbstractBot
from ..models.status import AgentStatus


def _get_interactive_result_class() -> Optional[type]:
    """Lazy import of ``InteractiveRenderResult`` (avoids circular deps)."""
    try:
        from ..models.interactive import InteractiveRenderResult as _cls
        return _cls
    except ImportError:
        return None


def _get_infographic_result_class() -> Optional[type]:
    """Lazy import of ``InfographicRenderResult`` (avoids circular deps)."""
    try:
        from ..tools.infographic_toolkit import InfographicRenderResult as _cls
        return _cls
    except ImportError:
        return None
# FEAT-176: Lifecycle Events
# FEAT-317: TraceContext moved to navigator_eventbus.lifecycle; imported here
# via the parrot.core.events.lifecycle re-export facade.
from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent,
    AfterInvokeEvent,
    InvokeFailedEvent,
)
# FEAT-228: Per-agent cost & usage metrics — bind agent identity around each invocation
from parrot.observability.context import current_agent_name

# FEAT-252 (TASK-1612): module-level egress scrubber singleton for channel delivery
_BOT_EGRESS_SCRUBBER: OutputScrubber = OutputScrubber(ScrubPolicy())


class BaseBot(AbstractBot):
    """
    Base Bot implementation providing concrete implementations of
    abstract methods defined in AbstractBot.

    This is the recommended base class for creating custom bots. It provides
    full implementations of ask, ask_stream, invoke, and conversation methods
    with support for:
    - Vector store context retrieval
    - Knowledge base integration
    - Conversation history management
    - Tool usage (agentic mode)
    - Multiple output formats
    - Security and prompt injection detection

    Subclasses can override these methods to customize behavior or use them
    as-is for standard bot functionality.
    """

    def _resolve_metric_type(self, metric_type: Optional[str]) -> str:
        """Resolve which vector-search metric to use.

        Precedence: explicit call argument → vector_store_config.metric_type
        (from BD via the bot config) → self._metric_type → 'COSINE'.

        Without this, the hardcoded ``metric_type='EUCLIDEAN_DISTANCE'``
        defaults on ask/conversation/ask_stream would silently override
        whatever the agent's vector_store_config declared.
        """
        if metric_type:
            return metric_type
        cfg = getattr(self, '_vector_store', None) or {}
        if isinstance(cfg, dict) and cfg.get('metric_type'):
            return cfg['metric_type']
        return getattr(self, '_metric_type', None) or 'COSINE'

    def _debug_prompt_dump(
        self,
        method: str,
        system_prompt: str,
        prompt_for_llm: str,
        vector_context: str = "",
        kb_context: str = "",
        user_context: str = "",
        conversation_context: str = "",
        memory_context: str = "",
        vector_metadata: Optional[dict] = None,
    ) -> None:
        """Dump the assembled system prompt and context sizes when DEBUG is on.

        Zero-cost when the bot's logger is not at DEBUG level. Intended for
        diagnosing RAG/grounding issues — e.g. confirming that
        `rag_grounding`/`knowledge_scope` layers are present and that
        `vector_context` actually carries retrieved chunks before the call
        to ``client.ask(...)``.
        """
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        layer_names: list[str] = []
        if self._prompt_builder is not None:
            layer_names = self._prompt_builder.layer_names

        vec_meta = (vector_metadata or {}).get('vector', {}) or {}
        search_results = vec_meta.get('search_results_count', 0)
        sources = vec_meta.get('sources', [])

        # self.logger.debug(
        #     "[%s] %s() prompt builder layers: %s",
        #     self.name, method, layer_names,
        # )
        # self.logger.debug(
        #     "[%s] %s() context sizes: system_prompt=%d, prompt=%d, "
        #     "vector=%d (chunks=%d, sources=%d), kb=%d, user=%d, "
        #     "history=%d, memory=%d",
        #     self.name, method,
        #     len(system_prompt or ""),
        #     len(prompt_for_llm or ""),
        #     len(vector_context or ""), search_results, len(sources),
        #     len(kb_context or ""),
        #     len(user_context or ""),
        #     len(conversation_context or ""),
        #     len(memory_context or ""),
        # )

    async def conversation(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: Optional[str] = None,
        use_vector_context: bool = True,
        use_conversation_history: bool = True,
        return_sources: bool = True,
        return_context: bool = False,
        memory: Optional[Callable] = None,
        ensemble_config: dict = None,
        mode: str = "adaptive",
        ctx: Optional[RequestContext] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        format_kwargs: dict = None,
        system_prompt: Optional[str] = None,
        trace_context=None,
        **kwargs
    ) -> AIMessage:
        """
        Conversation method with vector store and history integration.

        .. deprecated::
            ``conversation()`` is deprecated and will be removed in a future
            release. Use :meth:`ask` instead — it provides the same retrieval
            pipeline plus tool support, prompt-injection sanitization, and
            long-term memory hooks.

        Args:
            question: The user's question
            session_id: Session identifier for conversation history
            user_id: User identifier
            search_type: Type of search to perform ('similarity', 'mmr', 'ensemble')
            search_kwargs: Additional search parameters
            metric_type: Metric type for vector search (e.g., 'EUCLIDEAN_DISTANCE', 'EUCLIDEAN')
            limit: Maximum number of context items to retrieve
            score_threshold: Minimum score for context relevance
            use_vector_context: Whether to retrieve context from vector store
            use_conversation_history: Whether to use conversation history
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage: The response from the LLM
        """
        # FEAT-228: bind agent identity for per-agent cost/usage attribution.
        # Token-based set/reset is nested-safe (inner agents restore outer value).
        _agent_token = current_agent_name.set(self.name)
        try:
            return await self._conversation_body(
                question=question,
                session_id=session_id,
                user_id=user_id,
                search_type=search_type,
                search_kwargs=search_kwargs,
                metric_type=metric_type,
                use_vector_context=use_vector_context,
                use_conversation_history=use_conversation_history,
                return_sources=return_sources,
                return_context=return_context,
                memory=memory,
                ensemble_config=ensemble_config,
                mode=mode,
                ctx=ctx,
                output_mode=output_mode,
                format_kwargs=format_kwargs,
                system_prompt=system_prompt,
                trace_context=trace_context,
                **kwargs,
            )
        finally:
            current_agent_name.reset(_agent_token)

    async def _conversation_body(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: Optional[str] = None,
        use_vector_context: bool = True,
        use_conversation_history: bool = True,
        return_sources: bool = True,
        return_context: bool = False,
        memory: Optional[Callable] = None,
        ensemble_config: dict = None,
        mode: str = "adaptive",
        ctx: Optional[RequestContext] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        format_kwargs: dict = None,
        system_prompt: Optional[str] = None,
        trace_context=None,
        **kwargs
    ) -> AIMessage:
        """Internal implementation of conversation(); called inside agent_identity scope."""
        if ctx is None:
            ctx = _current_ctx.get()
        # FEAT-224: pre-LLM output-mode routing. Runs once, and only when the
        # caller did not specify a mode (precedence: explicit > router > default).
        # No-op unless a routing mixin (IntentRouterMixin) is present.
        if output_mode == OutputMode.DEFAULT:
            _resolved_mode = await self._resolve_output_mode(question, ctx)
            if _resolved_mode is not None:
                output_mode = _resolved_mode
                if ctx is not None:
                    ctx.output_mode = _resolved_mode
        warnings.warn(
            "BaseBot.conversation() is deprecated and will be removed in a "
            "future release. Use BaseBot.ask() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        user_id = user_id or "anonymous"
        turn_id = str(uuid.uuid4())

        # FEAT-176: resolve trace context and emit BeforeInvokeEvent.
        _trace_ctx_conv = trace_context or TraceContext.new_root()
        self._current_trace_context = _trace_ctx_conv
        _conv_started_ms = time.perf_counter()
        await self.events.emit(BeforeInvokeEvent(
            trace_context=_trace_ctx_conv,
            agent_name=self.name,
            method="conversation",
            question=question[:512],
            user_id=user_id,
            session_id=session_id,
            source_type="agent",
            source_name=self.name,
        ))

        limit = kwargs.get(
            'limit',
            self.context_search_limit
        )
        score_threshold = kwargs.get(
            'score_threshold', self.context_score_threshold
        )
        metric_type = self._resolve_metric_type(metric_type)
        self.logger.debug(
            "[%s] conversation() resolved metric_type=%s, score_threshold=%s",
            self.name, metric_type, score_threshold,
        )

        # ── Intent Router: pop routing kwargs before any downstream processing ──
        injected_context = kwargs.pop("injected_context", None)
        routing_decision = kwargs.pop("routing_decision", None)
        routing_trace = kwargs.pop("routing_trace", None)

        try:
            # Get conversation history using unified memory
            conversation_history = None
            conversation_context = ""

            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await memory.get_history(
                    user_id, session_id
                ) or await memory.create_history(
                    user_id, session_id
                )  # noqa
                conversation_context = self.build_conversation_context(conversation_history)

            # Build context from different sources
            vector_metadata = {'activated_kbs': []}

            if injected_context:
                # IntentRouterMixin pre-fetched context — skip RAG retrieval.
                vector_context = injected_context
                vector_meta = {}
            else:
                # Get vector context (method handles use_vectors check internally)
                vector_context, vector_meta = await self._build_vector_context(
                    question,
                    use_vectors=use_vector_context,
                    search_type=search_type,
                    search_kwargs=search_kwargs,
                    ensemble_config=ensemble_config,
                    metric_type=metric_type,
                    limit=limit,
                    score_threshold=score_threshold,
                    return_sources=return_sources,
                )
            if vector_meta:
                vector_metadata['vector'] = vector_meta

            # Get user-specific context
            user_context = await self._build_user_context(
                user_id=user_id,
                session_id=session_id,
            )

            # Get knowledge base context
            kb_context, kb_meta = await self._build_kb_context(
                question,
                user_id=user_id,
                session_id=session_id,
                ctx=ctx,
            )
            if kb_meta.get('activated_kbs'):
                vector_metadata['activated_kbs'] = kb_meta['activated_kbs']

            # Determine if tools should be used
            use_tools = self._use_tools(question)
            if mode == "adaptive":
                effective_mode = "agentic" if use_tools else "conversational"
            elif mode == "agentic":
                use_tools = True
                effective_mode = "agentic"
            else:  # conversational
                use_tools = False
                effective_mode = "conversational"

            # Log tool usage decision
            self.logger.info(
                f"Tool usage decision: use_tools={use_tools}, mode={mode}, "
                f"effective_mode={effective_mode}, available_tools={self.tool_manager.tool_count()}"
            )

            # Handle output mode in system prompt
            _mode = output_mode if isinstance(output_mode, str) else output_mode.value
            if output_mode != OutputMode.DEFAULT:
                # Append output mode system prompt
                if system_prompt_addon := self.formatter.get_system_prompt(output_mode):
                    if 'system_prompt' in kwargs:
                        kwargs['system_prompt'] += f"\n\n{system_prompt_addon}"
                    else:
                        # added to the user_context
                        user_context += system_prompt_addon
                else:
                    # Using default Output prompt:
                    user_context += OUTPUT_SYSTEM_PROMPT.format(
                        output_mode=_mode
                    )
            # Create system prompt
            system_prompt_addition = system_prompt
            system_prompt = await self.create_system_prompt(
                kb_context=kb_context,
                vector_context=vector_context,
                conversation_context=conversation_context,
                metadata=vector_metadata,
                user_context=user_context,
                user_id=user_id,
                session_id=session_id,
                **kwargs
            ) + (system_prompt_addition or '')

            self._debug_prompt_dump(
                method="conversation",
                system_prompt=system_prompt,
                prompt_for_llm=question,
                vector_context=vector_context,
                kb_context=kb_context,
                user_context=user_context,
                conversation_context=conversation_context,
                vector_metadata=vector_metadata,
            )

            # Configure LLM if needed
            llm = self._llm
            if (new_llm := kwargs.pop('llm', None)):
                llm = self.configure_llm(
                    llm=new_llm,
                    model=kwargs.get('model', None),
                    **kwargs.pop('llm_config', {})
                )

            # Ensure model is set, falling back to client default if needed
            try:
                if not kwargs.get('model'):
                    if hasattr(llm, 'default_model') and llm.default_model:
                        kwargs['model'] = llm.default_model
                    elif llm.client_type == 'google':
                        kwargs['model'] = 'gemini-2.5-flash'
            except Exception:
                kwargs['model'] = 'gemini-2.5-flash'
            # Make the LLM call — retries and fallback are handled at the client level
            try:
                async with llm as client:
                    llm_kwargs = {
                        "prompt": question,
                        "system_prompt": system_prompt,
                        "temperature": kwargs.get('temperature', None),
                        "user_id": user_id,
                        "session_id": session_id,
                        "use_tools": use_tools,
                    }

                    if (_model := kwargs.get('model', None)):
                        llm_kwargs["model"] = _model

                    max_tokens = kwargs.get('max_tokens', self._llm_kwargs.get('max_tokens'))
                    if max_tokens is not None:
                        llm_kwargs["max_tokens"] = max_tokens

                    response = await client.ask(**llm_kwargs)

                    # Extract the vector-specific metadata
                    vector_info = vector_metadata.get('vector', {})
                    response.set_vector_context_info(
                        used=bool(vector_context),
                        context_length=len(vector_context) if vector_context else 0,
                        search_results_count=vector_info.get('search_results_count', 0),
                        search_type=vector_info.get('search_type', search_type) if vector_context else None,
                        score_threshold=vector_info.get('score_threshold', score_threshold),
                        sources=vector_info.get('sources', []),
                        source_documents=vector_info.get('source_documents', [])
                    )
                    response.set_conversation_context_info(
                        used=bool(conversation_context),
                        context_length=len(conversation_context) if conversation_context else 0
                    )

                    # Set additional metadata
                    response.session_id = session_id
                    response.turn_id = turn_id

                    # ── Intent Router: attach routing trace/decision to metadata ──
                    if routing_trace is not None:
                        if response.metadata is None:
                            response.metadata = {}
                        response.metadata["routing_trace"] = routing_trace.model_dump()
                    if routing_decision is not None:
                        if response.metadata is None:
                            response.metadata = {}
                        response.metadata["routing_decision"] = routing_decision.model_dump()

                    # Determine output mode
                    format_kwargs = format_kwargs or {}
                    if output_mode == OutputMode.A2UI:
                        # FEAT-273: A2UI envelopes bypass the legacy formatter entirely.
                        finalize_a2ui_response(response)
                    elif output_mode != OutputMode.DEFAULT:
                        # Check if data is empty and try to extract it from output
                        extracted_data = None
                        if not response.data:
                            extracted_data = self.formatter.extract_data(response)

                        content, wrapped = await self.formatter.format(
                            output_mode, response, **format_kwargs
                        )
                        response.output = content
                        response.response = wrapped
                        response.output_mode = output_mode

                        # Assign extracted data if we found any
                        if extracted_data and not response.data:
                            response.data = extracted_data

                    # Save conversation turn
                    if use_conversation_history and memory:
                        turn = ConversationTurn(
                            turn_id=response.turn_id or str(uuid.uuid4()),
                            user_id=user_id,
                            user_message=question,
                            assistant_response=response.content,
                            context_used=vector_context if use_vector_context else None,
                            tools_used=[t.name for t in response.tool_calls] if response.tool_calls else [],
                            metadata={
                                'response_time': response.response_time,
                                'model': response.model,
                                'usage': response.usage,
                                'finish_reason': response.finish_reason
                            }
                        )
                        await memory.add_turn(user_id, session_id, turn)

                    # FEAT-176: emit AfterInvokeEvent on success.
                    _conv_duration_ms = (time.perf_counter() - _conv_started_ms) * 1000
                    await self.events.emit(AfterInvokeEvent(
                        trace_context=_trace_ctx_conv,
                        agent_name=self.name,
                        method="conversation",
                        duration_ms=_conv_duration_ms,
                        source_type="agent",
                        source_name=self.name,
                    ))
                    # return the response Object:
                    return self.get_response(
                        response,
                        return_sources,
                        return_context
                    )
            finally:
                await self._llm.close()

        except asyncio.CancelledError:
            self.logger.info("Conversation task was cancelled.")
            # FEAT-176: emit InvokeFailedEvent on cancellation.
            _conv_duration_ms = (time.perf_counter() - _conv_started_ms) * 1000
            await self.events.emit(InvokeFailedEvent(
                trace_context=_trace_ctx_conv,
                agent_name=self.name,
                method="conversation",
                duration_ms=_conv_duration_ms,
                error_type="CancelledError",
                error_message="Cancelled",
                source_type="agent",
                source_name=self.name,
            ))
            raise
        except Exception as e:
            self.logger.error(
                f"Error in conversation: {e}"
            )
            # FEAT-176: emit InvokeFailedEvent on exception.
            _conv_duration_ms = (time.perf_counter() - _conv_started_ms) * 1000
            await self.events.emit(InvokeFailedEvent(
                trace_context=_trace_ctx_conv,
                agent_name=self.name,
                method="conversation",
                duration_ms=_conv_duration_ms,
                error_type=type(e).__name__,
                error_message=str(e),
                source_type="agent",
                source_name=self.name,
            ))
            raise
        finally:
            self._current_trace_context = None

    # Alias for conversation method
    async def chat(self, *args, **kwargs) -> AIMessage:
        """Alias for conversation method for backward compatibility."""
        return await self.conversation(*args, **kwargs)

    async def invoke(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        use_conversation_history: bool = True,
        memory: Optional[Callable] = None,
        ctx: Optional[RequestContext] = None,
        response_model: Optional[Type[BaseModel]] = None,
        **kwargs
    ) -> AIMessage:
        """
        Simplified conversation method with adaptive mode and conversation history.

        Args:
            question: The user's question
            session_id: Session identifier for conversation history
            user_id: User identifier
            use_conversation_history: Whether to use conversation history
            memory: Optional memory callable override
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage: The response from the LLM
        """
        # FEAT-228: bind agent identity for per-agent cost/usage attribution.
        _agent_token = current_agent_name.set(self.name)
        try:
            if ctx is None:
                ctx = _current_ctx.get()
            # Generate session ID if not provided
            session_id = session_id or str(uuid.uuid4())
            user_id = user_id or "anonymous"
            turn_id = str(uuid.uuid4())
            _trusted_source = kwargs.pop("_trusted_source", False)

            # SECURITY: Sanitize question. The wrap is for the LLM call ONLY —
            # do NOT rebind ``question`` here, otherwise the security wrapper
            # leaks into events, conversation memory and downstream agents.
            try:
                prompt_for_llm = await self._sanitize_question(
                    question=question,
                    user_id=user_id,
                    session_id=session_id,
                    context={'method': 'invoke'},
                    _trusted_source=_trusted_source,
                )
            except PromptInjectionException:
                return AIMessage(
                    content="Your request could not be processed due to security concerns.",
                    metadata={'error': 'security_block'}
                )

            # Apply prompt pipeline (also LLM-call-only; preserves the canonical
            # ``question`` for events/memory).
            if self.prompt_pipeline and self._prompt_pipeline.has_middlewares:
                prompt_for_llm = await self._prompt_pipeline.apply(
                    prompt_for_llm,
                    context={
                        'agent_name': self.name,
                        'user_id': user_id,
                        'session_id': session_id,
                        'method': 'ask',
                    }
                )

            # Update status and trigger start event
            self.status = AgentStatus.WORKING
            self._trigger_event(
                self.EVENT_TASK_STARTED,
                agent_name=self.name,
                task=question,
                session_id=session_id
            )

            # Get conversation history using unified memory
            conversation_history = None
            conversation_context = ""

            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await memory.get_history(user_id, session_id) or await memory.create_history(user_id, session_id)  # noqa
                conversation_context = self.build_conversation_context(conversation_history)

            # Create system prompt (no vector context)
            system_prompt = await self.create_system_prompt(
                conversation_context=conversation_context,
                user_id=user_id,
                session_id=session_id,
                **kwargs
            )

            # Configure LLM if needed
            llm = self._llm
            if (new_llm := kwargs.pop('llm', None)):
                llm = self.configure_llm(
                    llm=new_llm,
                    model=kwargs.get('model', None),
                    **kwargs.pop('llm_config', {})
                )

            # Make the LLM call using the Claude client
            async with llm as client:
                llm_kwargs = {
                    "prompt": prompt_for_llm,
                    "system_prompt": system_prompt,
                    "temperature": kwargs.get('temperature', None),
                    "user_id": user_id,
                    "session_id": session_id,
                }

                if 'tool_type' in kwargs:
                    llm_kwargs['tool_type'] = kwargs['tool_type']

                max_tokens = kwargs.get('max_tokens', self._llm_kwargs.get('max_tokens'))
                if max_tokens is not None:
                    llm_kwargs["max_tokens"] = max_tokens

                if response_model:
                    llm_kwargs["structured_output"] = StructuredOutputConfig(
                        output_type=response_model
                    )

                response = await client.ask(**llm_kwargs)

                # Set conversation context info
                response.set_conversation_context_info(
                    used=bool(conversation_context),
                    context_length=len(conversation_context) if conversation_context else 0
                )

                # Set additional metadata
                response.session_id = session_id
                response.turn_id = turn_id

                if response_model:
                    return response  # return structured response directly

                # Return the response
                # Save conversation turn
                if use_conversation_history and memory:
                    turn = ConversationTurn(
                        turn_id=response.turn_id or str(uuid.uuid4()),
                        user_id=user_id,
                        user_message=question,
                        assistant_response=response.content,
                        context_used=None, # invoke does not use vector context usually
                        tools_used=[t.name for t in response.tool_calls] if response.tool_calls else [],
                        metadata={
                            'response_time': response.response_time,
                            'model': response.model,
                            'usage': response.usage,
                            'finish_reason': response.finish_reason
                        }
                    )
                    await memory.add_turn(user_id, session_id, turn)

                self._trigger_event(
                    self.EVENT_TASK_COMPLETED,
                    agent_name=self.name,
                    session_id=session_id,
                    result=response.output
                )

                return self.get_response(
                    response,
                    return_sources=False,
                    return_context=False
                )

        except asyncio.CancelledError:
            self.logger.info("Conversation task was cancelled.")
            self.status = AgentStatus.FAILED
            self._trigger_event(
                self.EVENT_TASK_FAILED,
                agent_name=self.name,
                error="Cancelled",
                session_id=session_id
            )
            raise
        except Exception as e:
            self.logger.error(f"Error in conversation: {e}")
            self.status = AgentStatus.FAILED
            self._trigger_event(
                self.EVENT_TASK_FAILED,
                agent_name=self.name,
                error=str(e),
                session_id=session_id
            )
            raise
        finally:
            self.status = AgentStatus.IDLE
            current_agent_name.reset(_agent_token)  # FEAT-228

    # ── ask() lifecycle hooks (overridden by mixins) ──

    async def _on_pre_ask(
        self,
        question: str,
        user_id: str | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> str:
        """Hook called before the LLM call in ask().

        Override in mixins (e.g. EpisodicMemoryMixin) to inject additional
        context into the system prompt.

        Returns:
            Additional context string to append to the system prompt,
            or empty string.
        """
        return ""

    async def _on_post_ask(
        self,
        question: str,
        response: "AIMessage",
        user_id: str | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> None:
        """Hook called after ask() produces a successful response.

        Override in mixins (e.g. EpisodicMemoryMixin) to record episodes
        or perform other post-response processing. Called fire-and-forget.
        """

    def _extract_last_interactive_result(
        self, tool_calls: Optional[List[Any]],
    ) -> Optional[Any]:
        """Return the last ``InteractiveRenderResult`` from the tool calls list."""
        if not tool_calls:
            return None
        cls = _get_interactive_result_class()
        if cls is None:
            return None
        for tc in reversed(tool_calls):
            result = getattr(tc, "result", None)
            if isinstance(result, cls):
                return result
        return None

    def _finalize_interactive_response(
        self, response: Any, envelope: Any,
    ) -> Optional[str]:
        """Apply an ``InteractiveRenderResult`` to the agent response in place.

        Sets ``OutputMode.HTML`` (there is no ``interactive`` renderer — the
        ``interactive_*`` tools produce the artifact) and records
        ``libraries_used`` in metadata.
        """
        explanation = getattr(response, "response", None)
        if not explanation and isinstance(response.output, str):
            explanation = response.output

        response.output = envelope.html_inline or envelope.html_url
        response.output_mode = OutputMode.HTML
        response.artifact_id = envelope.artifact_id
        if explanation:
            response.response = explanation

        meta = dict(getattr(response, "metadata", None) or {})
        meta.update({
            "html_url": envelope.html_url,
            "html_inline_omitted": envelope.html_inline is None,
            "enhanced": envelope.enhanced,
            "template_name": envelope.template_name,
            "theme": envelope.theme,
            "libraries_used": getattr(envelope, "libraries_used", []),
            "explanation": explanation,
        })
        if hasattr(response, "metadata"):
            response.metadata = meta

        return explanation

    def _extract_last_infographic_result(
        self, tool_calls: Optional[List[Any]],
    ) -> Optional[Any]:
        """Return the last ``InfographicRenderResult`` from the tool calls list.

        Generalises FEAT-197 beyond ``PandasAgent``: any agent whose
        ``infographic_render`` / ``infographic_render_template`` tool produced an
        ``InfographicRenderResult`` can have it finalized to an HTML artifact.
        When multiple render calls occurred in the same turn, only the LAST one
        is returned.
        """
        if not tool_calls:
            return None
        cls = _get_infographic_result_class()
        if cls is None:
            return None
        for tc in reversed(tool_calls):
            result = getattr(tc, "result", None)
            if isinstance(result, cls):
                return result
        return None

    def _finalize_infographic_response(
        self, response: Any, envelope: Any,
    ) -> Optional[str]:
        """Apply an ``InfographicRenderResult`` to the agent response in place.

        Mirrors ``PandasAgent._finalize_infographic_response`` (FEAT-197): the
        natural-language explanation is preserved on ``response.response`` (the
        chat bubble) while ``response.output`` carries the infographic HTML
        (inline when small, otherwise the signed URL). The explanation MUST be
        captured before ``response.output`` is overwritten, because
        ``AIMessage.content`` aliases ``output``.
        """
        explanation = getattr(response, "response", None)
        if not explanation and isinstance(response.output, str):
            explanation = response.output

        response.output = envelope.html_inline or envelope.html_url
        response.output_mode = OutputMode.INFOGRAPHIC
        response.artifact_id = envelope.artifact_id
        if explanation:
            response.response = explanation

        meta = dict(getattr(response, "metadata", None) or {})
        meta.update({
            "html_url": envelope.html_url,
            "html_inline_omitted": envelope.html_inline is None,
            "enhanced": envelope.enhanced,
            "template_name": envelope.template_name,
            "theme": envelope.theme,
            "explanation": explanation,
        })
        if hasattr(response, "metadata"):
            response.metadata = meta

        return explanation

    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: Optional[str] = None,
        use_vector_context: bool = True,
        use_conversation_history: bool = True,
        return_sources: bool = True,
        memory: Optional[Callable] = None,
        ensemble_config: dict = None,
        ctx: Optional[RequestContext] = None,
        permission_context: Optional[Any] = None,
        structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,
        system_prompt: Optional[str] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        format_kwargs: dict = None,
        use_tools: bool = True,
        trace_context=None,
        **kwargs
    ) -> AIMessage:
        """
        Ask method with tools always enabled and output formatting support.

        Args:
            question: The user's question
            session_id: Session identifier for conversation history
            user_id: User identifier
            search_type: Type of search to perform ('similarity', 'mmr', 'ensemble')
            search_kwargs: Additional search parameters
            system_prompt: System prompt to append to the generated system prompt
            metric_type: Metric type for vector search
            use_vector_context: Whether to retrieve context from vector store
            use_conversation_history: Whether to use conversation history
            return_sources: Whether to return sources in response
            memory: Optional memory handler
            ensemble_config: Configuration for ensemble search
            ctx: Request context
            output_mode: Output formatting mode ('default', 'terminal', 'html', 'json')
            structured_output: Structured output configuration or model
            format_kwargs: Additional kwargs for formatter (show_metadata, show_sources, etc.)
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage or formatted output based on output_mode
        """
        # FEAT-228: bind agent identity for per-agent cost/usage attribution.
        _agent_token = current_agent_name.set(self.name)
        try:
            if ctx is None:
                ctx = _current_ctx.get()
            # FEAT-224: pre-LLM output-mode routing. Runs once, and only when the
            # caller did not specify a mode (precedence: explicit > router > default).
            # No-op unless a routing mixin (IntentRouterMixin) is present.
            if output_mode == OutputMode.DEFAULT:
                _resolved_mode = await self._resolve_output_mode(question, ctx)
                if _resolved_mode is not None:
                    output_mode = _resolved_mode
                    if ctx is not None:
                        ctx.output_mode = _resolved_mode
            # Generate session ID if not provided
            session_id = session_id or str(uuid.uuid4())
            user_id = user_id or "anonymous"
            turn_id = str(uuid.uuid4())
            _trusted_source = kwargs.pop("_trusted_source", False)

            # Security: sanitize the user's question. The wrap is for the LLM
            # call ONLY — keep ``question`` clean so events, conversation memory,
            # vector retrieval and downstream agents see the canonical input.
            try:
                prompt_for_llm = await self._sanitize_question(
                    question=question,
                    user_id=user_id,
                    session_id=session_id,
                    context={'method': 'ask'},
                    _trusted_source=_trusted_source,
                )
            except PromptInjectionException as e:
                # Return error response instead of crashing
                return AIMessage(
                    content="Your request could not be processed due to security concerns. Please rephrase your question.",
                    metadata={
                        'error': 'security_block',
                        'threats_detected': len(e.threats)
                    }
                )

            # Apply prompt pipeline (LLM-call-only; canonical ``question`` stays
            # untouched).
            if self.prompt_pipeline and self._prompt_pipeline.has_middlewares:
                prompt_for_llm = await self._prompt_pipeline.apply(
                    prompt_for_llm,
                    context={
                        'agent_name': self.name,
                        'user_id': user_id,
                        'session_id': session_id,
                        'method': 'ask',
                    }
                )

            # FEAT-176: resolve trace context and emit BeforeInvokeEvent.
            _trace_ctx = trace_context or TraceContext.new_root()
            self._current_trace_context = _trace_ctx
            _ask_started_ms = time.perf_counter()
            await self.events.emit(BeforeInvokeEvent(
                trace_context=_trace_ctx,
                agent_name=self.name,
                method="ask",
                question=question[:512],
                user_id=user_id,
                session_id=session_id,
                source_type="agent",
                source_name=self.name,
            ))

            # Update status and trigger start event
            self.status = AgentStatus.WORKING
            self._trigger_event(
                self.EVENT_TASK_STARTED,
                agent_name=self.name,
                task=question,
                session_id=session_id
            )

            # Set max_tokens using bot default when provided
            default_max_tokens = self._llm_kwargs.get('max_tokens', None)
            max_tokens = kwargs.get('max_tokens', default_max_tokens)
            limit = kwargs.get('limit', self.context_search_limit)
            if limit <= 5:
                self.logger.warning(
                    f"Context search limit is set to {limit}, which may result in insufficient context for the LLM. Consider increasing the limit for better responses."
                )
                limit = 10  # enforce a minimum limit to ensure some context is retrieved
            score_threshold = kwargs.get('score_threshold', self.context_score_threshold)
            metric_type = self._resolve_metric_type(metric_type)
            self.logger.debug(
                "[%s] ask() resolved metric_type=%s, score_threshold=%s, limit=%s",
                self.name, metric_type, score_threshold, limit,
            )
            ask_started = time.perf_counter()

            # Get conversation history
            conversation_history = None
            conversation_context = ""
            memory = memory or self.conversation_memory

            phase_started = time.perf_counter()
            if use_conversation_history and memory:
                conversation_history = await memory.get_history(
                    user_id, session_id
                ) or await memory.create_history(
                    user_id, session_id
                )  # noqa
                conversation_context = self.build_conversation_context(conversation_history)
            self.logger.debug(
                "[%s] ask timing: conversation_history_ms=%.1f",
                self.name,
                (time.perf_counter() - phase_started) * 1000,
            )

            # Build context from different sources
            vector_metadata = {'activated_kbs': []}

            # Get vector context (method handles use_vectors check internally)
            phase_started = time.perf_counter()
            vector_context, vector_meta = await self._build_vector_context(
                question,
                use_vectors=use_vector_context,
                search_type=search_type,
                search_kwargs=search_kwargs,
                ensemble_config=ensemble_config,
                metric_type=metric_type,
                limit=limit,
                score_threshold=score_threshold,
                return_sources=return_sources,
            )
            if vector_meta:
                vector_metadata['vector'] = vector_meta
            self.logger.debug(
                "[%s] ask timing: vector_context_ms=%.1f context_chars=%d",
                self.name,
                (time.perf_counter() - phase_started) * 1000,
                len(vector_context or ""),
            )

            # Get user-specific context
            phase_started = time.perf_counter()
            user_context = await self._build_user_context(
                user_id=user_id,
                session_id=session_id,
            )
            self.logger.debug(
                "[%s] ask timing: user_context_ms=%.1f context_chars=%d",
                self.name,
                (time.perf_counter() - phase_started) * 1000,
                len(user_context or ""),
            )

            # Get knowledge base context
            phase_started = time.perf_counter()
            kb_context, kb_meta = await self._build_kb_context(
                question,
                user_id=user_id,
                session_id=session_id,
                ctx=ctx,
            )
            if kb_meta.get('activated_kbs'):
                vector_metadata['activated_kbs'] = kb_meta['activated_kbs']
            self.logger.debug(
                "[%s] ask timing: kb_context_ms=%.1f context_chars=%d",
                self.name,
                (time.perf_counter() - phase_started) * 1000,
                len(kb_context or ""),
            )

            # Pre-LLM: retrieve long-term memory context if mixin is active
            memory_context = ""
            phase_started = time.perf_counter()
            if (
                hasattr(self, 'get_memory_context')
                and hasattr(self, '_memory_manager')
                and self._memory_manager
            ):
                try:
                    memory_context = await self.get_memory_context(
                        question, user_id, session_id
                    )
                except Exception as _mem_exc:
                    self.logger.warning(
                        "Failed to get long-term memory context: %s", _mem_exc
                    )
                    memory_context = ""
            self.logger.debug(
                "[%s] ask timing: long_term_memory_ms=%.1f context_chars=%d",
                self.name,
                (time.perf_counter() - phase_started) * 1000,
                len(memory_context or ""),
            )

            # Pre-LLM: episodic / mixin-provided context
            episodic_context = ""
            phase_started = time.perf_counter()
            try:
                episodic_context = await self._on_pre_ask(
                    question,
                    user_id=user_id,
                    session_id=session_id,
                )
            except Exception as _pre_exc:
                self.logger.debug(
                    "_on_pre_ask hook failed: %s", _pre_exc
                )

            if episodic_context:
                memory_context = (
                    f"{memory_context}\n\n{episodic_context}"
                    if memory_context else episodic_context
                )
            self.logger.debug(
                "[%s] ask timing: pre_ask_hook_ms=%.1f episodic_chars=%d",
                self.name,
                (time.perf_counter() - phase_started) * 1000,
                len(episodic_context or ""),
            )

            _mode = output_mode if isinstance(output_mode, str) else output_mode.value

            # Handle output mode in system prompt
            if output_mode != OutputMode.DEFAULT:
                # Append output mode system prompt
                if system_prompt_addon := self.formatter.get_system_prompt(output_mode):
                    if 'system_prompt' in kwargs:
                        kwargs['system_prompt'] += f"\n\n{system_prompt_addon}"
                    else:
                        # added to the user_context
                        user_context += system_prompt_addon
                else:
                    # Using default Output prompt:
                    user_context += OUTPUT_SYSTEM_PROMPT.format(
                        output_mode=_mode
                    )
            # Create system prompt
            system_prompt_addition = system_prompt
            phase_started = time.perf_counter()
            system_prompt = await self.create_system_prompt(
                kb_context=kb_context,
                vector_context=vector_context,
                conversation_context=conversation_context,
                metadata=vector_metadata,
                user_context=user_context,
                memory_context=memory_context or None,
                user_id=user_id,
                session_id=session_id,
                **kwargs
            ) + (system_prompt_addition or '')
            self.logger.debug(
                "[%s] ask timing: create_system_prompt_ms=%.1f system_prompt_chars=%d",
                self.name,
                (time.perf_counter() - phase_started) * 1000,
                len(system_prompt or ""),
            )

            self._debug_prompt_dump(
                method="ask",
                system_prompt=system_prompt,
                prompt_for_llm=prompt_for_llm,
                vector_context=vector_context,
                kb_context=kb_context,
                user_context=user_context,
                conversation_context=conversation_context,
                memory_context=memory_context,
                vector_metadata=vector_metadata,
            )

            # Configure LLM if needed
            llm = self._llm
            if (new_llm := kwargs.pop('llm', None)):
                llm = self.configure_llm(
                    llm=new_llm,
                    model=kwargs.get('model', None),
                    **kwargs.pop('llm_config', {})
                )

            # Make the LLM call — retries and fallback are handled at the client level
            async with llm as client:
                self.logger.debug(
                    "[%s] ask timing: pre_llm_total_ms=%.1f prompt_chars=%d",
                    self.name,
                    (time.perf_counter() - ask_started) * 1000,
                    len(prompt_for_llm or ""),
                )
                # Forward caller identity to the tool manager so per-user
                # credential resolvers (e.g. Jira OAuth2 3LO) can look up
                # the right token. Attached as an instance attribute so it
                # survives across tool-loop iterations inside the client.
                if permission_context is not None:
                    client._permission_context = permission_context

                llm_kwargs = {
                    "prompt": prompt_for_llm,
                    "system_prompt": system_prompt,
                    "temperature": kwargs.get('temperature', None),
                    "user_id": user_id,
                    "session_id": session_id,
                    "use_tools": use_tools,
                }

                if 'tool_type' in kwargs:
                    llm_kwargs['tool_type'] = kwargs['tool_type']

                if max_tokens is not None:
                    llm_kwargs["max_tokens"] = max_tokens

                # Forward max_iterations only when the active LLM client
                # advertises it (currently only the Google client). Other
                # backends (OpenAI, Groq, etc.) have no max_iterations param
                # on ask(), so blindly forwarding would raise TypeError.
                # FEAT-182: this is the primary enforcement path for the
                # GitHubReviewer tool-call cap (max_review_tool_calls).
                if 'max_iterations' in kwargs:
                    try:
                        ask_params = inspect.signature(client.ask).parameters
                    except (TypeError, ValueError):
                        ask_params = {}
                    if 'max_iterations' in ask_params:
                        llm_kwargs["max_iterations"] = kwargs['max_iterations']

                if structured_output:
                    if isinstance(structured_output, type) and issubclass(structured_output, BaseModel):
                        llm_kwargs["structured_output"] = StructuredOutputConfig(
                            output_type=structured_output
                        )
                    elif isinstance(structured_output, StructuredOutputConfig):
                        llm_kwargs["structured_output"] = structured_output

                phase_started = time.perf_counter()
                response = await client.ask(**llm_kwargs)
                self.logger.info(
                    "[%s] ask timing: client.ask_ms=%.1f model=%s use_tools=%s",
                    self.name,
                    (time.perf_counter() - phase_started) * 1000,
                    getattr(response, "model", None),
                    use_tools,
                )

                # Save conversation turn
                phase_started = time.perf_counter()
                if use_conversation_history and memory:
                    turn = ConversationTurn(
                        turn_id=response.turn_id or str(uuid.uuid4()),
                        user_id=user_id,
                        user_message=question,
                        assistant_response=response.content,
                        context_used=vector_context if use_vector_context else None,
                        tools_used=[t.name for t in response.tool_calls] if response.tool_calls else [],
                        metadata={
                            'response_time': response.response_time,
                            'model': response.model,
                            'usage': response.usage,
                            'finish_reason': response.finish_reason
                        }
                    )
                    await memory.add_turn(user_id, session_id, turn)
                self.logger.debug(
                    "[%s] ask timing: memory_add_turn_ms=%.1f",
                    self.name,
                    (time.perf_counter() - phase_started) * 1000,
                )

                # Enhance response with metadata
                vector_info = vector_metadata.get('vector', {})
                response.set_vector_context_info(
                    used=bool(vector_context),
                    context_length=len(vector_context) if vector_context else 0,
                    search_results_count=vector_info.get('search_results_count', 0),
                    search_type=vector_info.get('search_type', search_type) if vector_context else None,
                    score_threshold=vector_info.get('score_threshold', score_threshold),
                    sources=vector_info.get('sources', []),
                    source_documents=vector_info.get('source_documents', [])
                )

                response.set_conversation_context_info(
                    used=bool(conversation_context),
                    context_length=len(conversation_context) if conversation_context else 0
                )

                if return_sources and vector_info.get('source_documents'):
                    response.source_documents = vector_info['source_documents']
                    response.context_sources = vector_info.get('context_sources', [])

                response.session_id = session_id
                response.turn_id = turn_id

                # Extract data from last tool execution if response.data is None
                # and tools were executed
                if response.data is None and response.has_tools and return_sources:
                    # Get the last tool call that has a result
                    for tool_call in reversed(response.tool_calls):
                        if tool_call.result is not None and tool_call.error is None:
                            # Sanitize the result for JSON serialization
                            response.data = self._sanitize_tool_data(tool_call.result)
                            break

                # Tool-driven interactive HTML artifact: when the agent's
                # ``interactive_render`` tool produced an InteractiveRenderResult,
                # finalize it to an HTML artifact and bypass the renderer dispatch
                # entirely. There is NO ``interactive`` renderer — the mode is a
                # request-side signal handled by the ``interactive_*`` tools.
                interactive_envelope = self._extract_last_interactive_result(
                    getattr(response, "tool_calls", None)
                )
                if interactive_envelope is not None:
                    self._finalize_interactive_response(response, interactive_envelope)
                    self.logger.info(
                        "InteractiveRenderResult detected — bypassing formatter: "
                        "artifact_id=%s enhanced=%s",
                        interactive_envelope.artifact_id,
                        interactive_envelope.enhanced,
                    )
                elif output_mode == OutputMode.INTERACTIVE:
                    # Interactive mode was requested but no artifact was produced
                    # (toolkit not registered, or the LLM answered in prose).
                    # Downgrade to DEFAULT so we don't dispatch to a renderer
                    # that doesn't exist.
                    self.logger.warning(
                        "output_mode=interactive requested but no interactive "
                        "artifact was produced; falling back to plain response."
                    )
                    output_mode = OutputMode.DEFAULT
                    response.output_mode = OutputMode.DEFAULT

                # Tool-driven infographic HTML artifact (FEAT-197, generalized):
                # when any agent's ``infographic_render`` /
                # ``infographic_render_template`` tool produced an
                # ``InfographicRenderResult``, finalize it to an HTML artifact and
                # bypass the formatter — the same contract ``PandasAgent`` uses,
                # now available to every ``Agent``.
                infographic_envelope = self._extract_last_infographic_result(
                    getattr(response, "tool_calls", None)
                )
                if infographic_envelope is not None:
                    self._finalize_infographic_response(response, infographic_envelope)
                    self.logger.info(
                        "InfographicRenderResult detected — bypassing formatter: "
                        "artifact_id=%s",
                        infographic_envelope.artifact_id,
                    )
                elif output_mode == OutputMode.INFOGRAPHIC:
                    self.logger.warning(
                        "output_mode=infographic requested but no infographic "
                        "artifact was produced; falling back to plain response."
                    )
                    output_mode = OutputMode.DEFAULT
                    response.output_mode = OutputMode.DEFAULT

                # Determine output mode
                format_kwargs = format_kwargs or {}
                if interactive_envelope is not None or infographic_envelope is not None:
                    pass  # already finalized above — skip the formatter
                elif output_mode in [
                    OutputMode.TELEGRAM,
                    OutputMode.MSTEAMS,
                    OutputMode.SLACK,
                    OutputMode.WHATSAPP,
                ]:
                    # FEAT-252 (TASK-1612): scrub at channel egress before delivery
                    if isinstance(response.output, str):
                        response.output = _BOT_EGRESS_SCRUBBER.scrub(
                            response.output, tool_name=self.name
                        )
                    response.output_mode = output_mode

                elif output_mode == OutputMode.A2UI:
                    # FEAT-273: A2UI envelopes bypass the legacy formatter entirely.
                    finalize_a2ui_response(response)

                elif output_mode != OutputMode.DEFAULT:
                    # Check if data is empty and try to extract it from output
                    extracted_data = None
                    if not response.data:
                        extracted_data = self.formatter.extract_data(response)

                    content, wrapped = await self.formatter.format(
                        output_mode, response, **format_kwargs
                    )
                    response.output = content
                    response.response = wrapped
                    response.output_mode = output_mode

                    # Assign extracted data if we found any
                    if extracted_data and not response.data:
                        response.data = extracted_data

                self._trigger_event(
                    self.EVENT_TASK_COMPLETED,
                    agent_name=self.name,
                    session_id=session_id,
                    result=response.output
                )

                # Post-response: fire-and-forget long-term memory recording
                if (
                    hasattr(self, '_post_response_memory_hook')
                    and hasattr(self, '_memory_manager')
                    and self._memory_manager
                ):
                    _resp = response
                    _q, _uid, _sid = question, user_id, session_id

                    async def _fire_memory_hook() -> None:
                        try:
                            await self._post_response_memory_hook(
                                _q, _resp, _uid, _sid
                            )
                        except Exception as _hook_exc:
                            self.logger.warning(
                                "post_response_memory_hook failed: %s",
                                _hook_exc,
                            )

                    asyncio.create_task(_fire_memory_hook())

                # Post-response: episodic / mixin-provided hook
                _post_q, _post_resp = question, response
                _post_uid, _post_sid = user_id, session_id

                async def _fire_post_ask() -> None:
                    try:
                        await self._on_post_ask(
                            _post_q, _post_resp,
                            user_id=_post_uid,
                            session_id=_post_sid,
                        )
                    except Exception as _post_exc:
                        self.logger.debug(
                            "_on_post_ask hook failed: %s", _post_exc
                        )

                asyncio.create_task(_fire_post_ask())

                self.logger.debug(
                    "[%s] ask timing: total_ms=%.1f",
                    self.name,
                    (time.perf_counter() - ask_started) * 1000,
                )
                # FEAT-176: emit AfterInvokeEvent on success.
                _ask_duration_ms = (time.perf_counter() - _ask_started_ms) * 1000
                _usage = getattr(response, 'usage', None)
                await self.events.emit(AfterInvokeEvent(
                    trace_context=_trace_ctx,
                    agent_name=self.name,
                    method="ask",
                    duration_ms=_ask_duration_ms,
                    input_tokens=getattr(_usage, 'prompt_tokens', None) if _usage else None,
                    output_tokens=getattr(_usage, 'completion_tokens', None) if _usage else None,
                    source_type="agent",
                    source_name=self.name,
                ))
                return response

        except asyncio.CancelledError:
            self.logger.info("Ask task was cancelled.")
            # FEAT-176: emit InvokeFailedEvent on cancellation.
            _ask_duration_ms = (time.perf_counter() - _ask_started_ms) * 1000
            await self.events.emit(InvokeFailedEvent(
                trace_context=_trace_ctx,
                agent_name=self.name,
                method="ask",
                duration_ms=_ask_duration_ms,
                error_type="CancelledError",
                error_message="Cancelled",
                source_type="agent",
                source_name=self.name,
            ))
            self.status = AgentStatus.FAILED
            self._trigger_event(
                self.EVENT_TASK_FAILED,
                agent_name=self.name,
                error="Cancelled",
                session_id=session_id
            )
            raise
        except Exception as e:
            self.logger.error(f"Error in ask: {e}")
            # FEAT-176: emit InvokeFailedEvent on exception.
            _ask_duration_ms = (time.perf_counter() - _ask_started_ms) * 1000
            await self.events.emit(InvokeFailedEvent(
                trace_context=_trace_ctx,
                agent_name=self.name,
                method="ask",
                duration_ms=_ask_duration_ms,
                error_type=type(e).__name__,
                error_message=str(e),
                source_type="agent",
                source_name=self.name,
            ))
            self.status = AgentStatus.FAILED
            self._trigger_event(
                self.EVENT_TASK_FAILED,
                agent_name=self.name,
                error=str(e),
                session_id=session_id
            )
            raise
        finally:
            self.status = AgentStatus.IDLE
            self._current_trace_context = None
            current_agent_name.reset(_agent_token)  # FEAT-228

    async def ask_stream(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: Optional[str] = None,
        use_vector_context: bool = True,
        use_conversation_history: bool = True,
        return_sources: bool = True,
        memory: Optional[Callable] = None,
        ensemble_config: dict = None,
        ctx: Optional[RequestContext] = None,
        permission_context: Optional[Any] = None,
        structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        system_prompt: Optional[str] = None,
        trace_context=None,
        **kwargs
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Stream responses using the same preparation logic as :meth:`ask`."""
        # FEAT-228: bind agent identity for per-agent cost/usage attribution.
        _agent_token = current_agent_name.set(self.name)
        try:
            if ctx is None:
                ctx = _current_ctx.get()
            session_id = session_id or str(uuid.uuid4())
            user_id = user_id or "anonymous"
            # Maintain turn identifier generation for parity with ask()
            _turn_id = str(uuid.uuid4())
            _trusted_source = kwargs.pop("_trusted_source", False)

            # FEAT-176: resolve trace context and emit BeforeInvokeEvent.
            _trace_ctx_stream = trace_context or TraceContext.new_root()
            self._current_trace_context = _trace_ctx_stream
            _stream_started_ms = time.perf_counter()
            await self.events.emit(BeforeInvokeEvent(
                trace_context=_trace_ctx_stream,
                agent_name=self.name,
                method="ask_stream",
                question=question[:512],
                user_id=user_id,
                session_id=session_id,
                source_type="agent",
                source_name=self.name,
            ))

            try:
                # The wrap is for the LLM call ONLY; keep ``question`` clean.
                prompt_for_llm = await self._sanitize_question(
                    question=question,
                    user_id=user_id,
                    session_id=session_id,
                    context={'method': 'ask_stream'},
                    _trusted_source=_trusted_source,
                )
            except PromptInjectionException:
                yield (
                    "Your request could not be processed due to security concerns. "
                    "Please rephrase your question."
                )
                return

            # Apply prompt pipeline (LLM-call-only; ``question`` stays untouched).
            if self.prompt_pipeline and self._prompt_pipeline.has_middlewares:
                prompt_for_llm = await self._prompt_pipeline.apply(
                    prompt_for_llm,
                    context={
                        'agent_name': self.name,
                        'user_id': user_id,
                        'session_id': session_id,
                        'method': 'ask',
                    }
                )

            default_max_tokens = self._llm_kwargs.get('max_tokens', None)
            max_tokens = kwargs.get('max_tokens', default_max_tokens)
            limit = kwargs.get('limit', self.context_search_limit)
            score_threshold = kwargs.get('score_threshold', self.context_score_threshold)
            metric_type = self._resolve_metric_type(metric_type)
            self.logger.debug(
                "[%s] ask_stream() resolved metric_type=%s, score_threshold=%s",
                self.name, metric_type, score_threshold,
            )

            search_kwargs = search_kwargs or {}

            conversation_context = ""
            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await memory.get_history(user_id, session_id) or await memory.create_history(user_id, session_id)  # noqa
                conversation_context = self.build_conversation_context(conversation_history)

            # Build context from different sources
            vector_metadata = {'activated_kbs': []}

            # Get vector context (method handles use_vectors check internally)
            vector_context, vector_meta = await self._build_vector_context(
                question,
                use_vectors=use_vector_context,
                search_type=search_type,
                search_kwargs=search_kwargs,
                ensemble_config=ensemble_config,
                metric_type=metric_type,
                limit=limit,
                score_threshold=score_threshold,
                return_sources=return_sources,
            )
            if vector_meta:
                vector_metadata['vector'] = vector_meta

            # Get user-specific context
            user_context = await self._build_user_context(
                user_id=user_id,
                session_id=session_id,
            )

            # Get knowledge base context
            kb_context, kb_meta = await self._build_kb_context(
                question,
                user_id=user_id,
                session_id=session_id,
                ctx=ctx,
            )
            if kb_meta.get('activated_kbs'):
                vector_metadata['activated_kbs'] = kb_meta['activated_kbs']

            _mode = output_mode if isinstance(output_mode, str) else output_mode.value

            if output_mode != OutputMode.DEFAULT:
                if 'system_prompt' in kwargs:
                    kwargs['system_prompt'] += OUTPUT_SYSTEM_PROMPT.format(
                        output_mode=_mode
                    )
                else:
                    user_context += OUTPUT_SYSTEM_PROMPT.format(
                        output_mode=_mode
                    )

            system_prompt_addition = system_prompt
            system_prompt = await self.create_system_prompt(
                kb_context=kb_context,
                vector_context=vector_context,
                conversation_context=conversation_context,
                metadata=vector_metadata,
                user_context=user_context,
                **kwargs
            ) + (system_prompt_addition or '')

            self._debug_prompt_dump(
                method="ask_stream",
                system_prompt=system_prompt,
                prompt_for_llm=prompt_for_llm,
                vector_context=vector_context,
                kb_context=kb_context,
                user_context=user_context,
                conversation_context=conversation_context,
                vector_metadata=vector_metadata,
            )

            llm = self._llm
            if (new_llm := kwargs.pop('llm', None)):
                llm = self.configure_llm(llm=new_llm, **kwargs.pop('llm_config', {}))

            async with llm as client:
                # FEAT-266: forward caller identity to the tool manager so
                # per-user credential resolvers (e.g. O365 device-code) can
                # look up the right token — mirrors the propagation in
                # ask() (client._permission_context, consumed by
                # tool_manager.execute_tool's permission_context= kwarg).
                if permission_context is not None:
                    client._permission_context = permission_context

                llm_kwargs = {
                    "prompt": prompt_for_llm,
                    "system_prompt": system_prompt,
                    "model": kwargs.get('model', self._llm_model),
                    "temperature": kwargs.get('temperature', 0),
                    "user_id": user_id,
                    "session_id": session_id,
                }

                if 'tool_type' in kwargs:
                    llm_kwargs['tool_type'] = kwargs['tool_type']

                if max_tokens is not None:
                    llm_kwargs["max_tokens"] = max_tokens

                if structured_output:
                    if isinstance(structured_output, type) and issubclass(structured_output, BaseModel):
                        llm_kwargs["structured_output"] = StructuredOutputConfig(
                            output_type=structured_output
                        )
                    elif isinstance(structured_output, StructuredOutputConfig):
                        llm_kwargs["structured_output"] = structured_output

                full_response = ""
                ai_message = None
                stream_error: Optional[Exception] = None
                try:
                    async for chunk in client.ask_stream(**llm_kwargs):
                        if isinstance(chunk, AIMessage):
                            ai_message = chunk
                        else:
                            full_response += chunk
                            yield chunk
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Capture so the partial text already yielded to the caller
                    # is preserved as a fallback AIMessage instead of being lost.
                    stream_error = exc
                    self.logger.error(
                        "ask_stream: client stream raised after %d chars; "
                        "synthesizing fallback AIMessage: %s",
                        len(full_response), exc,
                    )

                # Save conversation turn — also runs on partial/error so the
                # accumulated text is not lost from memory.
                if use_conversation_history and memory and full_response:
                    turn = ConversationTurn(
                        turn_id=_turn_id,
                        user_id=user_id,
                        user_message=question,
                        assistant_response=full_response,
                        context_used=vector_context if use_vector_context else None,
                        tools_used=[],
                        metadata={
                            'model': kwargs.get('model', self._llm_model)
                        }
                    )
                    await memory.add_turn(user_id, session_id, turn)

                if ai_message is None:
                    # Defensive fallback: client did not yield an AIMessage sentinel
                    # (either because it errored mid-stream, or because the client
                    # implementation forgot to yield the final envelope).
                    # Use prompt_for_llm (the actual text sent to the LLM) so that
                    # ai_message.input is consistent with what client-yielded
                    # AIMessages carry.
                    ai_message = AIMessage(
                        input=prompt_for_llm,
                        output=full_response,
                        response=full_response,
                        model=kwargs.get('model', self._llm_model) or '',
                        provider=getattr(client, 'provider', '') or type(client).__name__,
                        usage=CompletionUsage(
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_tokens=0,
                        ),
                        user_id=user_id,
                        session_id=session_id,
                        turn_id=_turn_id,
                        finish_reason="error" if stream_error else "completed",
                        stop_reason="error" if stream_error else "completed",
                    )
                elif stream_error and not (ai_message.response or '').strip():
                    # Client yielded an AIMessage but it carries no text (e.g.
                    # validation built it before the chunks were attached).
                    # Patch the accumulated text in so the final envelope still
                    # reflects what was actually streamed to the caller.
                    ai_message.response = full_response
                    ai_message.output = ai_message.output or full_response
                    ai_message.finish_reason = "error"
                    ai_message.stop_reason = "error"

                # FEAT-176: emit AfterInvokeEvent on success.
                _stream_duration_ms = (time.perf_counter() - _stream_started_ms) * 1000
                await self.events.emit(AfterInvokeEvent(
                    trace_context=_trace_ctx_stream,
                    agent_name=self.name,
                    method="ask_stream",
                    duration_ms=_stream_duration_ms,
                    source_type="agent",
                    source_name=self.name,
                ))
                yield ai_message

        except asyncio.CancelledError:
            self.logger.info("Ask stream task was cancelled.")
            # FEAT-176: emit InvokeFailedEvent on cancellation.
            _stream_duration_ms = (time.perf_counter() - _stream_started_ms) * 1000
            await self.events.emit(InvokeFailedEvent(
                trace_context=_trace_ctx_stream,
                agent_name=self.name,
                method="ask_stream",
                duration_ms=_stream_duration_ms,
                error_type="CancelledError",
                error_message="Cancelled",
                source_type="agent",
                source_name=self.name,
            ))
            raise
        except Exception as e:
            self.logger.error(f"Error in ask_stream: {e}")
            # FEAT-176: emit InvokeFailedEvent on exception.
            _stream_duration_ms = (time.perf_counter() - _stream_started_ms) * 1000
            await self.events.emit(InvokeFailedEvent(
                trace_context=_trace_ctx_stream,
                agent_name=self.name,
                method="ask_stream",
                duration_ms=_stream_duration_ms,
                error_type=type(e).__name__,
                error_message=str(e),
                source_type="agent",
                source_name=self.name,
            ))
            raise
        finally:
            self._current_trace_context = None
            current_agent_name.reset(_agent_token)  # FEAT-228
