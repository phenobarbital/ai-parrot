from typing import AsyncIterator, List, Optional, Union, Any
from pathlib import Path
import google.generativeai as genai
from navconfig import config
from .abstract import AbstractClient, MessageResponse


class GenAIClient(AbstractClient):
    """
    Client for interacting with Google's Generative AI.
    """
    def __init__(self, **kwargs):
        api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        genai.configure(api_key=api_key)
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
        Ask a question to Google's Generative AI.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        history = [
            {"role": msg["role"], "parts": [msg["content"][0]["text"]]}
            for msg in messages
        ]

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        tools = self._prepare_tools() if self.tools else None

        model = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
            tools=tools
        )

        chat = model.start_chat(history=history)

        response = await chat.send_message_async(
            prompt,
            generation_config=generation_config
        )

        if response.candidates[0].content.parts[0].function_call:
            for tool_call in response.candidates[0].content.parts:
                tool_result = await self._execute_tool(
                    tool_call.function_call.name, tool_call.function_call.args
                )
                response = await chat.send_message_async(
                    [
                        genai.protos.FunctionResponse(
                            name=tool_call.function_call.name,
                            response={"content": tool_result},
                        )
                    ]
                )


        result = {
            "content": [{"type": "text", "text": response.text}],
            "model": model.model_name,
            "usage": {}, # Not available in GenAI response
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
        Stream Google Generative AI's response using AsyncIterator.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        history = [
            {"role": msg["role"], "parts": [msg["content"][0]["text"]]}
            for msg in messages
        ]

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        model = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt
        )

        chat = model.start_chat(history=history)

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
