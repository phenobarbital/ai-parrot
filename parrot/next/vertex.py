from typing import AsyncIterator, Dict, List, Optional, Union, Any
from pathlib import Path
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

    async def ask(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash",
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
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        history = [
            Content(role=msg["role"], parts=[Part.from_text(msg["content"][0]["text"])]) for msg in messages
        ]

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        tools = [Tool.from_function_declarations([
            FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=tool.input_schema
            ) for tool in self.tools.values()
        ])] if self.tools else None

        multimodal_model = GenerativeModel(model_name=model, system_instruction=system_prompt)

        chat = multimodal_model.start_chat(history=history)

        response = await chat.send_message_async(
            prompt,
            generation_config=generation_config,
            tools=tools,
        )

        if response.candidates[0].tool_calls:
            for tool_call in response.candidates[0].tool_calls:
                tool_result = await self._execute_tool(
                    tool_call.function_call.name, tool_call.function_call.args
                )
                response = await chat.send_message_async(
                    [
                        Part.from_function_response(
                            name=tool_call.function_call.name,
                            response={"content": tool_result},
                        )
                    ]
                )

        result = {
            "content": [{"type": "text", "text": response.text}],
            "model": model,
            "usage": {}, # Not available in Vertex AI response
            "stop_reason": "completed",
        }

        # Update conversation memory
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages + [{"role": "assistant", "content": result["content"]}],
            system_prompt
        )

        return await self._handle_structured_output(
            result,
            structured_output
        ) if structured_output else MessageResponse(**result)

    async def ask_stream(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash",
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
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        history = [
            Content(
                role=msg["role"], parts=[Part.from_text(msg["content"][0]["text"])]
            ) for msg in messages
        ]

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
            assistant_content += chunk.text
            yield chunk.text

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

    async def batch_ask(self, requests):
        return await super().batch_ask(requests)
