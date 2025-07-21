import asyncio
import json
from typing import AsyncIterator, Dict, List, Optional, Union, Any
from dataclasses import dataclass
import time
from enum import Enum
from pathlib import Path
import uuid
from navconfig import config
from datamodel.exceptions import ParserError  # pylint: disable=E0611 # noqa
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .abstract import AbstractClient, MessageResponse, BatchRequest
from .models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    CompletionUsage
)

class ClaudeModel(Enum):
    """Enum for Claude models."""
    SONNET_4 = "claude-sonnet-4-20250514"
    OPUS_4 = "claude-opus-4-20241022"
    SONNET_3_5 = "claude-3-5-sonnet-20241022"
    HAIKU_3_5 = "claude-3-5-haiku-20241022"


class ClaudeClient(AbstractClient):
    """Client for interacting with the Claude API."""
    version: str = "2023-06-01"
    agent_type: str = "claude"

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.anthropic.com",
        **kwargs
    ):
        self.api_key = api_key or config.get('ANTHROPIC_API_KEY')
        self.base_url = base_url
        self.base_headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.version
        }
        super().__init__(**kwargs)

    async def ask(
        self,
        prompt: str,
        model: Union[Enum, str] = ClaudeModel.SONNET_4,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Union[MessageResponse, Any]:
        """Ask Claude a question with optional conversation memory."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")


        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt)

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }

        if system_prompt:
            payload["system"] = system_prompt

        if self.tools:
            payload["tools"] = self._prepare_tools()

        # Track tool calls for the response
        all_tool_calls = []

        # Handle tool calls in a loop
        while True:
            async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
                response.raise_for_status()
                result = await response.json()

                # Check if Claude wants to use a tool
                if result.get("stop_reason") == "tool_use":
                    tool_results = []

                    for content_block in result["content"]:
                        if content_block["type"] == "tool_use":
                            tool_name = content_block["name"]
                            tool_input = content_block["input"]
                            tool_id = content_block["id"]

                            # Create ToolCall object and execute
                            tc = ToolCall(
                                id=tool_id,
                                name=tool_name,
                                arguments=tool_input
                            )

                            try:
                                start_time = time.time()
                                tool_result = await self._execute_tool(tool_name, tool_input)
                                execution_time = time.time() - start_time

                                tc.result = tool_result
                                tc.execution_time = execution_time

                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": str(tool_result)
                                })
                            except Exception as e:
                                tc.error = str(e)
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "is_error": True,
                                    "content": str(e)
                                })

                            all_tool_calls.append(tc)

                    # Add tool results and continue conversation
                    messages.append({"role": "assistant", "content": result["content"]})
                    messages.append({"role": "user", "content": tool_results})
                    payload["messages"] = messages
                else:
                    # No more tool calls, add assistant response and break
                    messages.append({"role": "assistant", "content": result["content"]})
                    break

        # Handle structured output
        final_output = None
        if structured_output:
            # Extract text content from Claude's response
            text_content = ""
            for content_block in result["content"]:
                if content_block["type"] == "text":
                    text_content += content_block["text"]

            try:
                if hasattr(structured_output, 'model_validate_json'):
                    final_output = structured_output.model_validate_json(text_content)
                elif hasattr(structured_output, 'model_validate'):
                    parsed_json = json.loads(text_content)
                    final_output = structured_output.model_validate(parsed_json)
                else:
                    final_output = json.loads(text_content)
            except Exception as e:
                # If structured parsing fails, keep the original text
                final_output = text_content

        # Update conversation memory
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_claude(
            response=result,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
            tool_calls=all_tool_calls
        )

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Union[ClaudeModel, str] = ClaudeModel.SONNET_4,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream Claude's response using AsyncIterator with optional conversation memory."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        payload = {
            "model": model.value if isinstance(model, Enum) else model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
            "stream": True
        }

        if system_prompt:
            payload["system"] = system_prompt

        if self.tools:
            payload["tools"] = self._prepare_tools()

        assistant_content = ""
        async with self.session.post(f"{self.base_url}/v1/messages", json=payload) as response:
            response.raise_for_status()

            async for line in response.content:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    data = line[6:]
                    if data == '[DONE]':
                        break
                    try:
                        event = json_decoder(data)
                        if event.get('type') == 'content_block_delta':
                            delta = event.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                text_chunk = delta.get('text', '')
                                assistant_content += text_chunk
                                yield text_chunk
                    except (ParserError, json.JSONDecodeError):
                        continue

        # Update conversation memory
        if assistant_content:
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_content}]
            })
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages,
                system_prompt
            )

    async def batch_ask(self, requests: List[BatchRequest]) -> List[AIMessage]:
        """Process multiple requests in batch."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Prepare batch payload in correct format
        batch_payload = {
            "requests": [
                {
                    "custom_id": req.custom_id,
                    "params": req.params
                }
                for req in requests
            ]
        }

        # Add beta header for Message Batches API
        headers = {"anthropic-beta": "message-batches-2024-09-24"}

        # Create batch
        async with self.session.post(
            f"{self.base_url}/v1/messages/batches",
            json=batch_payload,
            headers=headers
        ) as response:
            response.raise_for_status()
            batch_info = await response.json()
            batch_id = batch_info["id"]

        # Poll for completion
        while True:
            async with self.session.get(
                f"{self.base_url}/v1/messages/batches/{batch_id}",
                headers=headers
            ) as response:
                response.raise_for_status()
                batch_status = await response.json()

                if batch_status["processing_status"] == "ended":
                    break
                elif batch_status["processing_status"] in ["failed", "canceled"]:
                    raise RuntimeError(f"Batch processing failed: {batch_status}")

                await asyncio.sleep(5)  # Wait 5 seconds before polling again

        # Retrieve results - the results_url is provided in the batch status
        results_url = batch_status.get("results_url")
        if results_url:
            async with self.session.get(results_url) as response:
                response.raise_for_status()
                results_text = await response.text()

                # Parse JSONL format and convert to AIMessage
                results = []
                for line in results_text.strip().split('\n'):
                    if line:
                        batch_result = json_decoder(line)
                        # Extract the response from batch format
                        if 'response' in batch_result and 'body' in batch_result['response']:
                            claude_response = batch_result['response']['body']

                            # Create AIMessage from batch result
                            ai_message = AIMessageFactory.from_claude(
                                response=claude_response,
                                input_text="Batch request",  # We don't have original prompt in batch
                                model=claude_response.get('model', 'unknown'),
                                turn_id=str(uuid.uuid4())
                            )
                            results.append(ai_message)
                        else:
                            # Fallback for unexpected format
                            results.append(batch_result)

                return results
        else:
            raise RuntimeError("No results URL provided in batch status")
