import asyncio
from typing import AsyncIterator, List, Optional, Union, Any
from pathlib import Path
import google.generativeai as genai
from navconfig import config
from .abstract import AbstractClient, MessageResponse


class GenAIClient(AbstractClient):
    """
    Client for interacting with Google's Generative AI, with support for parallel function calling.
    """
    def __init__(self, **kwargs):
        api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        genai.configure(api_key=api_key)
        super().__init__(**kwargs)

    def _fix_tool_schema(self, schema: dict):
        """Recursively converts schema type values to uppercase for GenAI compatibility."""
        if isinstance(schema, dict):
            for key, value in schema.items():
                if key == 'type' and isinstance(value, str):
                    schema[key] = value.upper()
                else:
                    self._fix_tool_schema(value)
        elif isinstance(schema, list):
            for item in schema:
                self._fix_tool_schema(item)
        return schema


    async def ask(
        self,
        prompt: str,
        model: str = "gemini-1.5-flash",
        max_tokens: int = 8192,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Union[MessageResponse, Any]:
        """
        Ask a question to Google's Generative AI with support for parallel tool calls.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        history = [
            {"role": msg["role"], "parts": [part["text"] for part in msg["content"]]}
            for msg in messages
        ]

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        # Prepare tools: rename 'input_schema' to 'parameters' and fix type casing.
        prepared_tools = None
        if self.tools:
            tool_definitions = self._prepare_tools()
            for tool_def in tool_definitions:
                if 'input_schema' in tool_def:
                    schema = tool_def.pop('input_schema')
                    tool_def['parameters'] = self._fix_tool_schema(schema)
            prepared_tools = tool_definitions


        model_instance = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
            tools=prepared_tools
        )

        chat = model_instance.start_chat(history=history)

        response = await chat.send_message_async(
            prompt,
            generation_config=generation_config
        )

        # Handle parallel function calls
        if response.candidates and response.candidates[0].content.parts:
            function_calls = [part.function_call for part in response.candidates[0].content.parts if hasattr(part, 'function_call') and part.function_call]

            if function_calls:
                # Execute all tool calls concurrently
                tool_execution_tasks = [
                    self._execute_tool(fc.name, dict(fc.args)) for fc in function_calls
                ]
                tool_results = await asyncio.gather(*tool_execution_tasks)

                # Prepare the function responses to send back to the model
                function_response_parts = [
                    {
                        "function_response": {
                            "name": fc.name,
                            "response": {"content": result},
                        }
                    }
                    for fc, result in zip(function_calls, tool_results)
                ]

                # Send the tool results back to the model
                response = await chat.send_message_async(function_response_parts)


        result = {
            "content": [{"type": "text", "text": response.text}],
            "model": model_instance.model_name,
            "usage": {}, # Not available in GenAI response
            "stop_reason": "completed",
        }

        # Update conversation memory with the final response
        final_assistant_message = {"role": "assistant", "content": result["content"]}
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages + [final_assistant_message],
            system_prompt
        )

        return await self._handle_structured_output(
            result,
            structured_output
        ) if structured_output else MessageResponse(**result)

    async def ask_stream(
        self,
        prompt: str,
        model: str = "gemini-1.5-flash",
        max_tokens: int = 8192,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream Google Generative AI's response using AsyncIterator.
        Note: Tool calling is not supported in streaming mode with this implementation.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        history = [
            {"role": msg["role"], "parts": [part["text"] for part in msg["content"]]}
            for msg in messages
        ]

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        model_instance = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt
        )

        chat = model_instance.start_chat(history=history)

        response = await chat.send_message_async(
            prompt,
            generation_config=generation_config,
            stream=True
        )

        assistant_content = ""
        async for chunk in response:
            assistant_content += chunk.text
            yield chunk.text

        # Update conversation memory
        if assistant_content:
            final_assistant_message = {"role": "assistant", "content": [{"type": "text", "text": assistant_content}]}
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages + [final_assistant_message],
                system_prompt
            )

    async def batch_ask(self, requests):
        return await super().batch_ask(requests)
