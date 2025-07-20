
from typing import AsyncIterator, List, Optional, Union, Any
from pathlib import Path
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa
from navconfig import config
import openai
from .abstract import AbstractClient, MessageResponse


class OpenAIClient(AbstractClient):
    """Client for interacting with OpenAI's API.
    """
    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.openai.com/v1",
        **kwargs
    ):
        self.api_key = api_key or config.get('OPENAI_API_KEY')
        self.base_url = base_url
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        super().__init__(**kwargs)
        openai.api_key = self.api_key

    async def ask(
        self,
        prompt: str,
        model: str = "gpt-4-turbo",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Optional[type] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Union[MessageResponse, Any]:

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt)

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        tools = self._prepare_tools() if self.tools else None

        response = await openai.ChatCompletion.acreate(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            stream=False
        )

        result = response.choices[0].message

        # Handle tool calls in a loop
        while result.get('tool_calls'):
            tool_results = []

            for tool_call in result['tool_calls']:
                tool_name = tool_call['function']['name']
                tool_args = json_decoder(tool_call['function']['arguments'])

                try:
                    tool_result = await self._execute_tool(tool_name, tool_args)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "name": tool_name,
                        "content": str(tool_result)
                    })
                except Exception as e:
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "name": tool_name,
                        "content": str(e)
                    })

            messages.append(result)
            messages.extend(tool_results)

            response = await openai.ChatCompletion.acreate(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False
            )

            result = response.choices[0].message

        messages.append(result)

        # Update conversation memory
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt
        )

        final_result = {
            "content": [{"type": "text", "text": result['content']}],
            "model": model,
            "usage": response.usage,
            "stop_reason": "completed",
        }

        return await self._handle_structured_output(
            final_result,
            structured_output
        ) if structured_output else MessageResponse(**final_result)

    async def ask_stream(
        self,
        prompt: str,
        model: str = "gpt-4-turbo",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AsyncIterator[str]:

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt)

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        response = await openai.types.chat.ChatCompletion.acreate(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True
        )

        assistant_content = ""
        async for chunk in response:
            text_chunk = chunk.choices[0].delta.get('content', '')
            assistant_content += text_chunk
            yield text_chunk

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
