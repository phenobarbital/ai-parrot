import asyncio
import json
from typing import AsyncIterator, Dict, List, Optional, Union, Any
from dataclasses import dataclass
from pathlib import Path
from navconfig import config
from datamodel.exceptions import ParserError  # pylint: disable=E0611 # noqa
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .abstract import AbstractClient, MessageResponse, BatchRequest


class ClaudeModel:
    SONNET_4 = "claude-sonnet-4-20250514"
    OPUS_4 = "claude-opus-4-20241022"
    SONNET_3_5 = "claude-3-5-sonnet-20241022"
    HAIKU_3_5 = "claude-3-5-haiku-20241022"


class ClaudeClient(AbstractClient):
    """Client for interacting with the Claude API."""
    version: str = "2023-06-01"

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
        model: str = ClaudeModel.SONNET_4,
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

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt)

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }

        if system_prompt:
            payload["system"] = system_prompt

        if self.tools:
            payload["tools"] = self._prepare_tools()


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

                            try:
                                tool_result = await self._execute_tool(tool_name, tool_input)
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": str(tool_result)
                                })
                            except Exception as e:
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "is_error": True,
                                    "content": str(e)
                                })

                    # Add tool results and continue conversation
                    messages.append({"role": "assistant", "content": result["content"]})
                    messages.append({"role": "user", "content": tool_results})
                    payload["messages"] = messages
                else:
                    # No more tool calls, add assistant response and break
                    messages.append({"role": "assistant", "content": result["content"]})
                    break

        # Handle tool calls if needed
        if result.get("stop_reason") == "tool_use":
            result = await self._process_tool_calls(
                result,
                messages,
                payload,
                endpoint=f"{self.base_url}/v1/messages"
            )
        else:
            messages.append({"role": "assistant", "content": result["content"]})

        # Update conversation memory
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt
        )
        return await self._handle_structured_output(
            result,
            structured_output
        ) if structured_output else MessageResponse(
            content=result["content"],
            model=model,
            usage=result.get("usage", {}),
            stop_reason=result.get("stop_reason", "completed")
        )

    async def ask_stream(
        self,
        prompt: str,
        model: str = ClaudeModel.SONNET_4,
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

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        payload = {
            "model": model,
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
            messages.append(
                {"role": "assistant", "content": [{"type": "text", "text": assistant_content}]}
            )
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages,
                system_prompt
            )
        # Finalize the response
        yield assistant_content

    async def batch_ask(self, requests: List[BatchRequest]) -> List[MessageResponse]:
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

                # Parse JSONL format
                results = []
                for line in results_text.strip().split('\n'):
                    if line:
                        results.append(json_decoder(line))
                return results
        else:
            raise RuntimeError("No results URL provided in batch status")
