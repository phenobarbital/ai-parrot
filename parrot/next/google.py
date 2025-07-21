import asyncio
from typing import AsyncIterator, List, Optional, Union, Any
import time
from enum import Enum
from pathlib import Path
import uuid
from google import genai
from google.genai.types import GenerateContentConfig, Content, Part, ModelContent, UserContent
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential
from navconfig import config
from .abstract import AbstractClient, MessageResponse
from .models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    StructuredOutputConfig,
    OutputFormat
)

class GoogleModel(Enum):
    """Enum for Google AI models."""
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite-preview-06-17"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_0_FLASH = "gemini-2.0-flash-001"
    IMAGEN_3_FAST = "Imagen 3 Fast"


class GoogleGenAIClient(AbstractClient):
    """
    Client for interacting with Google's Generative AI, with support for parallel function calling.
    """
    def __init__(self, **kwargs):
        api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        super().__init__(**kwargs)
        self.client = genai.Client(api_key=api_key)

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

    async def __aenter__(self):
        """Initialize the client context."""
        # Google GenAI doesn't need explicit session management
        return self

    async def ask(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Union[MessageResponse, Any]:
        """
        Ask a question to Google's Generative AI with support for parallel tool calls.
        """
        model = model.value if isinstance(model, GoogleModel) else model
        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Handle enhanced structured output
        if isinstance(structured_output, StructuredOutputConfig):
            config = structured_output
        else:
            # Backward compatibility - assume JSON
            config = StructuredOutputConfig(
                output_type=structured_output,
                format=OutputFormat.JSON
            ) if structured_output else None

        # Prepare conversation history, is a list of Content objects
        history = []
        for msg in messages:
            content = msg['content']
            if not content:
                continue
            part = Part(text=content[0].get("text", ""))
            role = msg['role'].lower()
            if role == 'user':
                history.append(UserContent(parts=[part]))
            elif role == 'model':
                history.append(ModelContent(parts=[part]))
            else:
                # Handle other roles or raise an error if needed
                print(f"Unknown role: {role}")


        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        if structured_output:
            if isinstance(structured_output, type):
                # Pydantic model passed directly
                generation_config["response_mime_type"] = "application/json"
                generation_config["response_schema"] = structured_output
            elif isinstance(structured_output, StructuredOutputConfig):
                if structured_output.format == OutputFormat.JSON:
                    generation_config["response_mime_type"] = "application/json"
                    generation_config["response_schema"] = structured_output.output_type


        # Track tool calls for the response
        all_tool_calls = []

        tools = None
        if self.tools:
            # Convert to newer API format
            function_declarations = []
            for tool in self.tools.values():
                function_declarations.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": self._fix_tool_schema(tool.input_schema.copy())
                })
            function_declarations.append(
                types.Tool(
                    google_search=types.GoogleSearch()
                )
            )
            function_declarations.append(
                types.Tool(code_execution=types.ToolCodeExecution)
            )
            tools = function_declarations

        # Build contents for conversation
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            if role in ["user", "model"]:
                text_parts = [part["text"] for part in msg["content"] if "text" in part]
                if text_parts:
                    contents.append({
                        "role": role,
                        "parts": [{"text": " ".join(text_parts)}]
                    })

        # Add the current prompt
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })
        chat = self.client.aio.chats.create(
            model=model,
            history=history
        )
        # Create the model instance
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=GenerateContentConfig(
                system_instruction=system_prompt,
                tools=tools,
                **generation_config
            )
        )

        # Handle parallel function calls
        if response.candidates and response.candidates[0].content.parts:
            function_calls = [
                part.function_call
                for part in response.candidates[0].content.parts
                if hasattr(part, 'function_call') and part.function_call
            ]

            if function_calls:
                tool_call_objects = []
                # Execute all tool calls concurrently
                for fc in function_calls:
                    tc = ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",  # Generate ID for tracking
                        name=fc.name,
                        arguments=dict(fc.args)
                    )
                    tool_call_objects.append(tc)

                start_time = time.time()
                tool_execution_tasks = [
                    self._execute_tool(fc.name, dict(fc.args)) for fc in function_calls
                ]
                tool_results = await asyncio.gather(*tool_execution_tasks, return_exceptions=True)

                execution_time = time.time() - start_time

                # Update ToolCall objects with results
                for tc, result in zip(tool_call_objects, tool_results):
                    tc.execution_time = execution_time / len(tool_call_objects)
                    if isinstance(result, Exception):
                        tc.error = str(result)
                    else:
                        tc.result = result

                all_tool_calls.extend(tool_call_objects)

                # Prepare the function responses to send back to the model
                function_response_parts = []
                for fc, result in zip(function_calls, tool_results):
                    if isinstance(result, Exception):
                        response_content = f"Error: {str(result)}"
                    else:
                        response_content = result

                    function_response_parts.append({
                        "function_response": {
                            "name": fc.name,
                            "response": {"content": response_content},
                        }
                    })

                # Send the tool results back to the model
                response = await chat.send_message(function_response_parts)


        # Handle structured output
        final_output = None
        if structured_output:
            try:
                if hasattr(structured_output, 'model_validate_json'):
                    final_output = structured_output.model_validate_json(response.text)
                elif hasattr(structured_output, 'model_validate'):
                    parsed_json = self._json.loads(response.text)
                    final_output = structured_output.model_validate(parsed_json)
                else:
                    final_output = self._json.loads(response.text)
            except Exception:
                final_output = response.text

        # Update conversation memory with the final response
        final_assistant_message = {
            "role": "assistant", "content": [{"type": "text", "text": response.text}]
        }
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages + [final_assistant_message],
            system_prompt
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=all_tool_calls
        )

        # Override provider to distinguish from Vertex AI
        ai_message.provider = "google_genai"

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
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
        model = model.value if isinstance(model, GoogleModel) else model

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Prepare conversation history, is a list of Content objects
        history = []
        for msg in messages:
            content = msg['content']
            if not content:
                continue
            part = Part(text=content[0].get("text", ""))
            role = msg['role'].lower()
            if role == 'user':
                history.append(UserContent(parts=[part]))
            elif role == 'model':
                history.append(ModelContent(parts=[part]))
            else:
                # Handle other roles or raise an error if needed
                print(f"Unknown role: {role}")

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        tools = None
        if self.tools:
            # Convert to newer API format
            function_declarations = []
            for tool in self.tools.values():
                function_declarations.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": self._fix_tool_schema(tool.input_schema.copy())
                })
            function_declarations.append(
                types.Tool(code_execution=types.ToolCodeExecution),
                types.Tool(
                    google_search=types.GoogleSearch()
                )
            )
            tools = function_declarations

        # Start the chat session
        chat = self.client.aio.chats.create(
            model=model,
            history=history,
            config=GenerateContentConfig(
                system_instruction=system_prompt,
                tools=tools,
                **generation_config
            )
        )

        assistant_content = ""
        async for chunk in await chat.send_message_stream(prompt):
            if chunk.text:
                assistant_content += chunk.text
                yield chunk.text

        # Update conversation memory
        if assistant_content:
            final_assistant_message = {
                "role": "assistant", "content": [
                    {"type": "text", "text": assistant_content}
                ]
            }
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages + [final_assistant_message],
                system_prompt
            )

    async def batch_ask(self, requests) -> List[AIMessage]:
        """Process multiple requests in batch."""
        # Google GenAI doesn't have a native batch API, so we process sequentially
        results = []
        for request in requests:
            result = await self.ask(**request)
            results.append(result)
        return results
