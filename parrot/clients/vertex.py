from typing import AsyncIterator, Dict, List, Optional, Union, Any
from enum import Enum
import time
from pathlib import Path
import uuid
from google.oauth2 import service_account
import vertexai
from vertexai.generative_models import (
    GenerativeModel,
    Part,
    Tool,
    FunctionDeclaration,
    Content
)
from vertexai.preview.vision_models import ImageGenerationModel
from navconfig import config, BASE_DIR
from navconfig import config
from .abstract import AbstractClient, MessageResponse
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    CompletionUsage
)
from ..models.google import VertexAIModel


class VertexAIClient(AbstractClient):
    """
    Client for interacting with Google's Vertex AI.
    """
    def __init__(self, **kwargs):
        project_id = kwargs.pop('project_id', config.get("VERTEX_PROJECT_ID"))
        region = kwargs.pop('region', config.get("VERTEX_REGION"))
        config_file = kwargs.pop(
            'config_file',
            config.get('GOOGLE_CREDENTIALS_FILE', 'env/google/vertexai.json')
        )
        region = config.get("VERTEX_REGION")
        config_file = config.get('GOOGLE_CREDENTIALS_FILE', 'env/google/vertexai.json')
        config_dir = BASE_DIR.joinpath(config_file)
        self.vertex_credentials = service_account.Credentials.from_service_account_file(
            str(config_dir)
        )
        vertexai.init(
            project=project_id,
            location=region,
            credentials=self.vertex_credentials
        )
        super().__init__(**kwargs)

    async def __aenter__(self):
        """Initialize the client context."""
        # Vertex AI doesn't need explicit session management
        return self

    def _extract_usage_from_response(self, response) -> Dict[str, Any]:
        """Extract usage metadata from Vertex AI response."""
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            return {
                "prompt_token_count": response.usage_metadata.prompt_token_count,
                "candidates_token_count": response.usage_metadata.candidates_token_count,
                "total_token_count": response.usage_metadata.total_token_count
            }
        return {}

    async def ask(
        self,
        prompt: str,
        model: Union[VertexAIModel, str] = VertexAIModel.GEMINI_2_5_FLASH,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Union[MessageResponse, Any]:
        """
        Ask a question to Vertex AI with optional conversation memory.
        """
        model = model.value if isinstance(model, VertexAIModel) else model

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Convert messages to Vertex AI format
        history = []
        for msg in messages:
            if msg["content"] and isinstance(msg["content"], list) and msg["content"]:
                content_text = msg["content"][0].get("text", "")
                history.append(
                    Content(
                        role=msg["role"],
                        parts=[Part.from_text(content_text)]
                    )
                )

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        # Track tool calls for the response
        all_tool_calls = []

        # Prepare tools
        tools = None
        if self.tools:
            function_declarations = [
                FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.input_schema
                ) for tool in self.tools.values()
            ]
            tools = [
                Tool.from_function_declarations(function_declarations)
            ]

        multimodal_model = GenerativeModel(
            model_name=model,
            system_instruction=system_prompt
        )

        chat = multimodal_model.start_chat(history=history)

        response = await chat.send_message_async(
            prompt,
            generation_config=generation_config,
            tools=tools,
        )

        # Handle function calls
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    # Create ToolCall object and execute
                    tc = ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",  # Generate ID for tracking
                        name=part.function_call.name,
                        arguments=dict(part.function_call.args)
                    )

                    try:
                        start_time = time.time()
                        tool_result = await self._execute_tool(
                            part.function_call.name,
                            dict(part.function_call.args)
                        )
                        execution_time = time.time() - start_time

                        tc.result = tool_result
                        tc.execution_time = execution_time

                        # Send tool result back to model
                        response = await chat.send_message_async(
                            Part.from_function_response(
                                name=part.function_call.name,
                                response={"content": tool_result},
                            )
                        )
                    except Exception as e:
                        tc.error = str(e)
                        # Send error back to model
                        response = await chat.send_message_async(
                            Part.from_function_response(
                                name=part.function_call.name,
                                response={"content": f"Error: {str(e)}"},
                            )
                        )

                    all_tool_calls.append(tc)

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

        # Update conversation memory
        messages.append(
            {"role": "assistant", "content": [{"type": "text", "text": response.text}]}
        )
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt
        )

        # Extract usage information
        usage_data = self._extract_usage_from_response(response)

        # Create AIMessage using factory (we'll use the gemini factory since it's similar)
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

        # Override usage with proper Vertex AI usage data
        if usage_data:
            ai_message.usage = CompletionUsage(
                prompt_tokens=usage_data.get("prompt_token_count", 0),
                completion_tokens=usage_data.get("candidates_token_count", 0),
                total_tokens=usage_data.get("total_token_count", 0),
                extra_usage=usage_data
            )

        # Update provider
        ai_message.provider = "vertex_ai"

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Union[VertexAIModel, str] = VertexAIModel.GEMINI_2_5_FLASH,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream Vertex AI's response using AsyncIterator.
        """
        model = model.value if isinstance(model, VertexAIModel) else model

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )
        # Convert messages to Vertex AI format
        history = []
        for msg in messages:
            if msg["content"] and isinstance(msg["content"], list) and msg["content"]:
                content_text = msg["content"][0].get("text", "")
                history.append(
                    Content(
                        role=msg["role"],
                        parts=[Part.from_text(content_text)]
                    )
                )

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        multimodal_model = GenerativeModel(model_name=model, system_instruction=system_prompt)

        chat = multimodal_model.start_chat(history=history)

        response = await chat.send_message_async(
            prompt,
            generation_config=generation_config,
            stream=True
        )

        assistant_content = ""
        async for chunk in response:
            if chunk.text:
                assistant_content += chunk.text
                yield chunk.text

        # Update conversation memory
        if assistant_content:
            messages.append(
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_content}]
                }
            )
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages,
                system_prompt
            )

    async def batch_ask(self, requests) -> List[AIMessage]:
        """Process multiple requests in batch."""
        # Vertex AI doesn't have a native batch API, so we process sequentially
        results = []
        for request in requests:
            result = await self.ask(**request)
            results.append(result)
        return results
