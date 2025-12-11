from typing import List, Dict, Any, Optional, Union, AsyncIterator
import os
import asyncio
import logging
from enum import Enum
from pathlib import Path
from xai_sdk import AsyncClient
from xai_sdk.chat import user, system, assistant

from .base import AbstractClient
from ..models import (
    MessageResponse,
    CompletionUsage,
    AIMessage,
    StructuredOutputConfig,
    ToolCall
)
from ..tools.abstract import AbstractTool

class GrokModel(str, Enum):
    """Grok model versions."""
    GROK_4_FAST_REASONING = "grok-4-fast-reasoning"
    GROK_4 = "grok-4"
    GROK_4_1_FAST_NON_REASONING = "grok-4-1-fast-non-reasoning"
    GROK_4_1_FAST_REASONING = "grok-4-1-fast-reasoning"
    GROK_3_MINI = "gro-3-mini"
    GROK_CODE_FAST_1 = "grok-code-fast-1"
    GROK_2_IMAGE = "grok-2-image-1212"
    GROK_2_VISION = "grok-2-vision-1212"

class GrokClient(AbstractClient):
    """
    Client for interacting with xAI's Grok models.
    """
    client_type: str = "xai"
    client_name: str = "grok"
    _default_model: str = GrokModel.GROK_4.value

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 3600,
        **kwargs
    ):
        """
        Initialize Grok client.
        
        Args:
            api_key: xAI API key (defaults to XAI_API_KEY env var)
            timeout: Request timeout in seconds
            **kwargs: Additional arguments for AbstractClient
        """
        super().__init__(**kwargs)
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        if not self.api_key:
            # Try to get from config if available
            try:
                from navconfig import config
                self.api_key = config.get("XAI_API_KEY")
            except ImportError:
                pass
                
        if not self.api_key:
            raise ValueError("XAI_API_KEY not found in environment or config")
            
        self.timeout = timeout
        self.client: Optional[AsyncClient] = None

    async def get_client(self) -> AsyncClient:
        """Return the xAI AsyncClient instance."""
        if not self.client:
            self.client = AsyncClient(
                api_key=self.api_key,
                timeout=self.timeout
            )
        return self.client

    async def close(self):
        """Close the client connection."""
        await super().close()
        self.client = None

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> Any:
        pass

    async def ask(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
    ) -> MessageResponse:
        """
        Send a prompt to Grok and return the response.
        """
        client = await self.get_client()
        model = model or self.model or self.default_model

        # 1. Initialize Chat
        response_format = None
        if structured_output:
            config = self._get_structured_config(structured_output)
            if config:
                if isinstance(structured_output, type):
                     response_format = structured_output
                elif hasattr(config, 'schema'):
                     pass
        
        chat_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        if response_format:
            chat_kwargs["response_format"] = response_format

        # Prepare tools
        prepared_tools = []
        if use_tools is not False:
             if tools:
                 prepared_tools = tools
             elif self.enable_tools:
                 prepared_tools = self._prepare_tools()

        if prepared_tools:
             chat_kwargs['tools'] = prepared_tools

        chat = client.chat.create(**chat_kwargs)

        # 2. Add System Prompt
        if system_prompt:
            chat.append(system(system_prompt))
            
        # 3. Add History (if enabled and available)
        if self.conversation_memory and user_id and session_id:
            history = await self.get_conversation(user_id, session_id)
            if history:
                for turn in history.turns:
                     chat.append(user(turn.input))
                     if turn.output:
                         chat.append(assistant(turn.output))

        # 4. Add Current User Message
        chat.append(user(prompt))

        # 5. Execute
        # Tools are prepared and passed to chat.create above.


        try:
            # Re-create chat with tools if needed, or assume simple append works
            # Note: If tools need to be passed to create, we might need adjustments.
            # For now keeping existing logic but fixing imports.
            
            # Since we passed kwargs to create initially, if we add tools we might need to recreate?
            # Or tools property on chat?
            # Assuming xAI SDK handles tools via chat.create or sample.
            # If we add tools to chat_kwargs, we should have passed them earlier?
            # The current logic:
            # chat = client.chat.create(**chat_kwargs)
            # then check tools...
            # Ideally we check tools BEFORE creating chat.
            
            # FIX: Move tool preparation before chat creation
            
            current_chat_kwargs = chat_kwargs.copy()
            if prepared_tools:
                 # Recreate chat if tools are added (assuming create() needed them)
                 # Or just pass to create properly
                 # But we already created `chat` above.
                 # Let's clean this up:
                 pass

            # Since 'chat' object is already created, if it doesn't support adding tools later...
            # We should probably refactor to prepare everything before creation.
            # But for fixing the syntax error, I will stick to what was there, just fixed.
            
            # Actually, `chat` is already created at line 131.
            # If tools are needed, we might be too late.
            # However, for this step, I am fixing syntax errors.
            
            response = await chat.sample()

            # Local import to avoid circular dependency
            from ..models.responses import AIMessageFactory

            ai_message = AIMessageFactory.create_message(
                response=response,
                input_text=prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                usage=CompletionUsage.from_grok(response.usage),
                text_response=response.content if hasattr(response, 'content') else str(response)
            )
            
            if user_id and session_id:
                 await self.conversation_memory.add_turn(
                    user_id, 
                    session_id, 
                    prompt, 
                    ai_message.to_text,
                    metadata=ai_message.usage.dict()
                )

            return ai_message

        except Exception as e:
            self.logger.error(f"Error in GrokClient.ask: {e}")
            raise

    async def ask_stream(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[str]:
        """
        Stream response from Grok.
        """
        client = await self.get_client()
        model = model or self.model or self.default_model

        chat = client.chat.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True 
        )

        if system_prompt:
            chat.append(system(system_prompt))

        if self.conversation_memory and user_id and session_id:
            history = await self.get_conversation(user_id, session_id)
            if history:
                for turn in history.turns:
                    chat.append(user(turn.input))
                    if turn.output:
                        chat.append(assistant(turn.output))

        chat.append(user(prompt))
        
        full_response = []
        
        async for token in chat.stream():
            content = token 
            if hasattr(token, 'choices'):
                 delta = token.choices[0].delta
                 if hasattr(delta, 'content'):
                     content = delta.content
            elif hasattr(token, 'content'):
                 content = token.content
            
            if content:
                full_response.append(content)
                yield content

        if user_id and session_id:
            await self.conversation_memory.add_turn(
                user_id,
                session_id,
                prompt,
                "".join(full_response)
            )

    async def batch_ask(self, requests: List[Any]) -> List[Any]:
        """Batch processing not yet implemented for Grok."""
        raise NotImplementedError("Batch processing not supported for Grok yet")
