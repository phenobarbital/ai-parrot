from typing import AsyncIterator, List, Optional, Union, Any
from pathlib import Path
from logging import getLogger
import json
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa
from navconfig import config
from groq import AsyncGroq
from .abstract import AbstractClient, MessageResponse


getLogger('httpx').setLevel('WARNING')
getLogger('httpcore').setLevel('WARNING')
getLogger('groq').setLevel('INFO')


class GroqModel:
    """Enum-like class for Groq models."""
    KIMI_K2_INSTRUCT = "moonshotai/kimi-k2-instruct"
    LLAMA_4_SCOUT_17B = "meta-llama/llama-4-scout-17b-16e-instruct"
    LLAMA_4_MAVERICK_17B = "meta-llama/llama-4-maverick-17b-128e-instruct"
    MISTRAL_SABA_24B = "mistral-saba-24b"
    DEEPSEEK_R1_DISTILL_70B = "deepseek-r1-distill-llama-70b"
    LLAMA_3_3_70B_VERSATILE = "llama-3.3-70b-versatile"
    LLAMA_3_1_8B_INSTANT = "llama-3.1-8b-instant"
    GEMMA2_9B_IT = "gemma2-9b-it"
    QWEN_QWEN3_32B = "qwen/qwen3-32b"


class GroqClient(AbstractClient):
    """Client for interacting with Groq's API."""

    agent_type: str = "groq"
    model: str = GroqModel.LLAMA_3_3_70B_VERSATILE

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.groq.com/openai/v1",
        **kwargs
    ):
        self.api_key = api_key or config.get('GROQ_API_KEY')
        self.base_url = base_url
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        super().__init__(**kwargs)
        self.client = AsyncGroq(api_key=self.api_key)

    def _prepare_groq_tools(self) -> List[dict]:
        """Convert registered tools to Groq format."""
        if not self.tools:
            return []

        groq_tools = []
        for tool in self.tools.values():
            groq_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema
                }
            })
        return groq_tools

    def _prepare_structured_output_format(self, structured_output: type) -> dict:
        """Prepare response format for structured output."""
        if not structured_output:
            return {}

        # Handle Pydantic models
        if hasattr(structured_output, 'model_json_schema'):
            schema = structured_output.model_json_schema()
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": structured_output.__name__.lower(),
                        "schema": schema
                    }
                }
            }

        # Fallback for other types
        return {
            "response_format": {
                "type": "json_object"
            }
        }

    async def ask(
        self,
        prompt: str,
        model: str = GroqModel.LLAMA_3_3_70B_VERSATILE,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        top_p: float = 0.9,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Union[MessageResponse, Any]:
        """Ask Groq a question with optional conversation memory."""

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Prepare tools
        tools = self._prepare_groq_tools()

        # Groq doesn't support combining structured output with tools
        # Priority: tools first, then structured output in separate request if needed
        use_tools = bool(tools)
        use_structured_output = bool(structured_output)
        if use_tools and use_structured_output:
            # Handle tools first, structured output later
            structured_output_for_later = structured_output
            structured_output = None
        else:
            structured_output_for_later = None
        # Prepare request arguments
        request_args = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False
        }

        # Add tools if available and not conflicting with structured output
        if use_tools and not use_structured_output:
            request_args["tools"] = tools
            request_args["tool_choice"] = "auto"
            # Enable parallel tool calls for supported models
            if model != GroqModel.GEMMA2_9B_IT:
                request_args["parallel_tool_calls"] = True

        # Add structured output format if no tools
        if structured_output and not use_tools:
            request_args.update(
                self._prepare_structured_output_format(structured_output)
            )

        # Make initial request
        response = await self.client.chat.completions.create(**request_args)
        result = response.choices[0].message

        # Handle tool calls in a loop (only if tools were enabled)
        if use_tools:
            while result.tool_calls:
                tool_results = []

                for tool_call in result.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = json_decoder(tool_call.function.arguments)

                    try:
                        tool_result = await self._execute_tool(tool_name, tool_args)
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": str(tool_result)
                        })
                    except Exception as e:
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": f"Error: {str(e)}"
                        })

                # Add assistant message and tool results
                messages.append({
                    "role": "assistant",
                    "content": result.content,
                    "tool_calls": [
                        tc.dict() if hasattr(tc, 'dict') else tc for tc in result.tool_calls
                    ]
                })
                messages.extend(tool_results)

                # Continue conversation with tool results
                continue_args = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                    "stream": False
                }

                response = await self.client.chat.completions.create(**continue_args)
                result = response.choices[0].message

        # If we have structured output to handle after tools
        if structured_output_for_later and use_tools:
            # Add the final tool response to messages
            if result.content:
                messages.append({
                    "role": "assistant",
                    "content": result.content
                })

            # Make a new request for structured output
            messages.append({
                "role": "user",
                "content": "Please format the above response according to the requested structure."
            })

            structured_args = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": False
            }

            structured_args.update(
                self._prepare_structured_output_format(structured_output_for_later)
            )

            response = await self.client.chat.completions.create(**structured_args)
            result = response.choices[0].message

        # Add final assistant message
        messages.append({
            "role": "assistant",
            "content": result.content
        })

        # Update conversation memory
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt
        )

        # Prepare final result
        final_result = {
            "content": [{"type": "text", "text": result.content}],
            "model": model,
            "usage": response.usage.dict() if hasattr(
                response.usage,
                'dict'
            ) else response.usage.__dict__,
            "stop_reason": "completed",
        }

        # Handle structured output
        final_structured_output = structured_output or structured_output_for_later
        if final_structured_output:
            return await self._handle_structured_output(
                final_result,
                final_structured_output
            )
        else:
            return MessageResponse(**final_result)

    async def ask_stream(
        self,
        prompt: str,
        model: str = GroqModel.LLAMA_3_3_70B_VERSATILE,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        top_p: float = 0.9,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream Groq's response with optional conversation memory."""

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Prepare request arguments
        request_args = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": True
        }

        # Note: Streaming with tools is more complex, for now we'll stream without tools
        # In production, you might want to handle tool calls differently for streaming
        tools = self._prepare_groq_tools()
        if tools:
            request_args["tools"] = tools
            request_args["tool_choice"] = "auto"

        response_stream = await self.client.chat.completions.create(**request_args)

        assistant_content = ""
        async for chunk in response_stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text_chunk = chunk.choices[0].delta.content
                assistant_content += text_chunk
                yield text_chunk

        # Update conversation memory if content was generated
        if assistant_content:
            messages.append({
                "role": "assistant",
                "content": assistant_content
            })
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages,
                system_prompt
            )

    async def batch_ask(self, requests):
        """Process multiple requests in batch."""
        return await super().batch_ask(requests)
