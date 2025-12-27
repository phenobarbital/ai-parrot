"""
BaseBot - Concrete implementation of AbstractBot.

This module provides BaseBot, a concrete implementation of the AbstractBot
abstract base class. It implements all required abstract methods.
"""
from typing import Optional, Union, Type, AsyncIterator
from collections.abc import Callable
import uuid
import asyncio
from pydantic import BaseModel
from .abstract import AbstractBot
from ..models import AIMessage, StructuredOutputConfig
from ..models.outputs import OutputMode
from ..utils.helpers import RequestContext
from ..security import PromptInjectionException
from .prompts import (
    OUTPUT_SYSTEM_PROMPT
)

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

    async def conversation(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: str = 'COSINE',
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
        **kwargs
    ) -> AIMessage:
        """
        Conversation method with vector store and history integration.

        Args:
            question: The user's question
            session_id: Session identifier for conversation history
            user_id: User identifier
            search_type: Type of search to perform ('similarity', 'mmr', 'ensemble')
            search_kwargs: Additional search parameters
            metric_type: Metric type for vector search (e.g., 'COSINE', 'EUCLIDEAN')
            limit: Maximum number of context items to retrieve
            score_threshold: Minimum score for context relevance
            use_vector_context: Whether to retrieve context from vector store
            use_conversation_history: Whether to use conversation history
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage: The response from the LLM
        """
        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        turn_id = str(uuid.uuid4())

        limit = kwargs.get(
            'limit',
            self.context_search_limit
        )
        score_threshold = kwargs.get(
            'score_threshold', self.context_score_threshold
        )

        try:
            # Get conversation history using unified memory
            conversation_history = None
            conversation_context = ""

            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await self.get_conversation_history(
                    user_id, session_id
                ) or await self.create_conversation_history(
                    user_id, session_id
                )  # noqa
                conversation_context = self.build_conversation_context(conversation_history)

            # Get vector context if store exists and enabled
            kb_context, user_context, vector_context, vector_metadata = await self._build_context(
                question,
                user_id=user_id,
                session_id=session_id,
                ctx=ctx,
                use_vectors=use_vector_context,
                search_type=search_type,
                search_kwargs=search_kwargs,
                ensemble_config=ensemble_config,
                metric_type=metric_type,
                limit=limit,
                score_threshold=score_threshold,
                return_sources=return_sources,
                **kwargs
            )

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
            system_prompt = await self.create_system_prompt(
                kb_context=kb_context,
                vector_context=vector_context,
                conversation_context=conversation_context,
                metadata=vector_metadata,
                user_context=user_context,
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

            # Ensure model is set, falling back to client default if needed
            try:
                if not kwargs.get('model'):
                    if hasattr(llm, 'default_model') and llm.default_model:
                        kwargs['model'] = llm.default_model
                    elif llm.client_type == 'google':
                        kwargs['model'] = 'gemini-2.5-flash'
            except Exception:
                kwargs['model'] = 'gemini-2.5-flash'
            # Make the LLM call using the Claude client
            # Retry Logic
            retries = kwargs.get('retries', 0)

            try:
                for attempt in range(retries + 1):
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

                            # Determine output mode
                            format_kwargs = format_kwargs or {}
                            if output_mode != OutputMode.DEFAULT:
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

                            # return the response Object:
                            return self.get_response(
                                response,
                                return_sources,
                                return_context
                            )
                    except Exception as e:
                        if attempt < retries:
                            self.logger.warning(
                                f"Error in conversation (attempt {attempt + 1}/{retries + 1}): {e}. Retrying..."
                            )
                            await asyncio.sleep(1)
                            continue
                        raise e
            finally:
                await self._llm.close()

        except asyncio.CancelledError:
            self.logger.info("Conversation task was cancelled.")
            raise
        except Exception as e:
            self.logger.error(
                f"Error in conversation: {e}"
            )
            raise

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
        # Generate session ID if not provided
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or "anonymous"
        turn_id = str(uuid.uuid4())

        # SECURITY: Sanitize question
        try:
            question = await self._sanitize_question(
                question=question,
                user_id=user_id,
                session_id=session_id,
                context={'method': 'invoke'}
            )
        except PromptInjectionException as e:
            return AIMessage(
                content="Your request could not be processed due to security concerns.",
                metadata={'error': 'security_block'}
            )

        try:
            # Get conversation history using unified memory
            conversation_history = None
            conversation_context = ""

            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await self.get_conversation_history(user_id, session_id) or await self.create_conversation_history(user_id, session_id)  # noqa
                conversation_context = self.build_conversation_context(conversation_history)

            # Create system prompt (no vector context)
            system_prompt = await self.create_system_prompt(
                conversation_context=conversation_context,
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
                    "prompt": question,
                    "system_prompt": system_prompt,
                    "temperature": kwargs.get('temperature', None),
                    "user_id": user_id,
                    "session_id": session_id,
                }

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
                return self.get_response(
                    response,
                    return_sources=False,
                    return_context=False
                )

        except asyncio.CancelledError:
            self.logger.info("Conversation task was cancelled.")
            raise
        except Exception as e:
            self.logger.error(f"Error in conversation: {e}")
            raise

    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: str = 'COSINE',
        use_vector_context: bool = True,
        use_conversation_history: bool = True,
        return_sources: bool = True,
        memory: Optional[Callable] = None,
        ensemble_config: dict = None,
        ctx: Optional[RequestContext] = None,
        structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        format_kwargs: dict = None,
        use_tools: bool = True,
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
        # Generate session ID if not provided
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or "anonymous"
        turn_id = str(uuid.uuid4())

        # Security: sanitize the user's question:
        try:
            question = await self._sanitize_question(
                question=question,
                user_id=user_id,
                session_id=session_id,
                context={'method': 'ask'}
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

        # Set max_tokens using bot default when provided
        default_max_tokens = self._llm_kwargs.get('max_tokens', None)
        max_tokens = kwargs.get('max_tokens', default_max_tokens)
        limit = kwargs.get('limit', self.context_search_limit)
        score_threshold = kwargs.get('score_threshold', self.context_score_threshold)

        try:
            # Get conversation history
            conversation_history = None
            conversation_context = ""
            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await self.get_conversation_history(
                    user_id, session_id
                ) or await self.create_conversation_history(
                    user_id, session_id
                )  # noqa
                conversation_context = self.build_conversation_context(conversation_history)

            # Get vector context
            kb_context, user_context, vector_context, vector_metadata = await self._build_context(
                question,
                user_id=user_id,
                session_id=session_id,
                ctx=ctx,
                use_vectors=use_vector_context,
                search_type=search_type,
                search_kwargs=search_kwargs,
                ensemble_config=ensemble_config,
                metric_type=metric_type,
                limit=limit,
                score_threshold=score_threshold,
                return_sources=return_sources,
                **kwargs
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
            system_prompt = await self.create_system_prompt(
                kb_context=kb_context,
                vector_context=vector_context,
                conversation_context=conversation_context,
                metadata=vector_metadata,
                user_context=user_context,
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

            # Make the LLM call
            # Retry Logic Mode
            retries = kwargs.get('retries', 0)

            try:
                for attempt in range(retries + 1):
                    try:
                        # Make the LLM call
                        async with llm as client:
                            llm_kwargs = {
                                "prompt": question,
                                "system_prompt": system_prompt,
                                "temperature": kwargs.get('temperature', None),
                                "user_id": user_id,
                                "session_id": session_id,
                                "use_tools": use_tools,
                            }

                            if max_tokens is not None:
                                llm_kwargs["max_tokens"] = max_tokens

                            if structured_output:
                                if isinstance(structured_output, type) and issubclass(structured_output, BaseModel):
                                    llm_kwargs["structured_output"] = StructuredOutputConfig(
                                        output_type=structured_output
                                    )
                                elif isinstance(structured_output, StructuredOutputConfig):
                                    llm_kwargs["structured_output"] = structured_output

                            response = await client.ask(**llm_kwargs)

                            # Enhance response with metadata
                            response.set_vector_context_info(
                                used=bool(vector_context),
                                context_length=len(vector_context) if vector_context else 0,
                                search_results_count=vector_metadata.get('search_results_count', 0),
                                search_type=search_type if vector_context else None,
                                score_threshold=score_threshold,
                                sources=vector_metadata.get('sources', []),
                                source_documents=vector_metadata.get('source_documents', [])
                            )

                            response.set_conversation_context_info(
                                used=bool(conversation_context),
                                context_length=len(conversation_context) if conversation_context else 0
                            )

                            if return_sources and vector_metadata.get('source_documents'):
                                response.source_documents = vector_metadata['source_documents']
                                response.context_sources = vector_metadata.get('context_sources', [])

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

                            # Determine output mode
                            format_kwargs = format_kwargs or {}
                            if output_mode in [
                                OutputMode.TELEGRAM,
                                OutputMode.MSTEAMS,
                            ]:
                                response.output_mode = output_mode

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
                            return response
                    except Exception as e:
                        if attempt < retries:
                            self.logger.warning(
                                f"Error in ask (attempt {attempt + 1}/{retries + 1}): {e}. Retrying..."
                            )
                            await asyncio.sleep(1)
                            continue
                        raise e
            finally:
                await self._llm.close()

        except asyncio.CancelledError:
            self.logger.info("Ask task was cancelled.")
            raise
        except Exception as e:
            self.logger.error(f"Error in ask: {e}")
            raise

    async def ask_stream(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: str = 'COSINE',
        use_vector_context: bool = True,
        use_conversation_history: bool = True,
        return_sources: bool = True,
        memory: Optional[Callable] = None,
        ensemble_config: dict = None,
        ctx: Optional[RequestContext] = None,
        structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream responses using the same preparation logic as :meth:`ask`."""

        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        turn_id = str(uuid.uuid4())

        limit = kwargs.get(
            'limit',
            self.context_search_limit
        )
        score_threshold = kwargs.get(
            'score_threshold', self.context_score_threshold
        )

        try:
            # Get conversation history using unified memory
            conversation_history = None
            conversation_context = ""

            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await self.get_conversation_history(
                    user_id, session_id
                ) or await self.create_conversation_history(
                    user_id, session_id
                )

                conversation_context = self.build_conversation_context(conversation_history)

            # Get vector context if store exists and enabled
            kb_context, user_context, vector_context, vector_metadata = await self._build_context(
                question,
                user_id=user_id,
                session_id=session_id,
                ctx=ctx,
                use_vectors=use_vector_context,
                search_type=search_type,
                search_kwargs=search_kwargs,
                ensemble_config=ensemble_config,
                metric_type=metric_type,
                limit=limit,
                score_threshold=score_threshold,
                return_sources=return_sources,
                **kwargs
            )

            # Create system prompt
            system_prompt = await self.create_system_prompt(
                kb_context=kb_context,
                vector_context=vector_context,
                conversation_context=conversation_context,
                metadata=vector_metadata,
                user_context=user_context,
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

            # Make the LLM call using client streaming
            async with llm as client:
                llm_kwargs = {
                    "prompt": question,
                    "system_prompt": system_prompt,
                    "temperature": kwargs.get('temperature', None),
                    "user_id": user_id,
                    "session_id": session_id,
                }

                if (_model := kwargs.get('model', None)):
                    llm_kwargs["model"] = _model

                max_tokens = kwargs.get('max_tokens', self._llm_kwargs.get('max_tokens'))
                if max_tokens is not None:
                    llm_kwargs["max_tokens"] = max_tokens

                async for chunk in client.ask_stream(**llm_kwargs):
                    yield chunk

        except asyncio.CancelledError:
            self.logger.info("Stream task was cancelled.")
            raise
        except Exception as e:
            self.logger.error(f"Error in ask_stream: {e}")
            raise
