"""LLM adapter for PageIndex — wraps any AbstractClient for LLM-agnostic calls."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional, Union

from ..clients.base import AbstractClient
from ..models.outputs import StructuredOutputConfig

logger = logging.getLogger("parrot.pageindex")


def extract_json(content: str) -> Any:
    """Extract JSON from LLM text that may contain ```json fences."""
    try:
        start_idx = content.find("```json")
        if start_idx != -1:
            start_idx += 7
            end_idx = content.rfind("```")
            json_content = content[start_idx:end_idx].strip()
        else:
            json_content = content.strip()

        json_content = json_content.replace("None", "null")
        json_content = json_content.replace("\n", " ").replace("\r", " ")
        json_content = " ".join(json_content.split())
        return json.loads(json_content)
    except json.JSONDecodeError:
        try:
            json_content = json_content.replace(",]", "]").replace(",}", "}")
            return json.loads(json_content)
        except Exception:
            logger.error("Failed to parse JSON even after cleanup")
            return {}
    except Exception as e:
        logger.error("Unexpected error extracting JSON: %s", e)
        return {}


class PageIndexLLMAdapter:
    """Wraps any AbstractClient for PageIndex-compatible LLM calls.

    Provides structured output support via Pydantic models and
    fallback JSON extraction for providers without native support.
    """

    def __init__(
        self,
        client: AbstractClient,
        model: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.client = client
        self.model = model or getattr(client, "default_model", None)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def ask(
        self,
        prompt: str,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Send a prompt and return raw text response.

        If structured_output is given, the response will be parsed via
        the provider's native structured output. Falls back to raw text
        with manual JSON extraction on failure.
        """
        for attempt in range(self.max_retries):
            try:
                response = await self.client.ask(
                    prompt=prompt,
                    model=self.model,
                    temperature=temperature,
                    structured_output=structured_output,
                    system_prompt=system_prompt,
                )
                if structured_output and hasattr(response, "structured_output") and response.structured_output:
                    return response.structured_output
                return response.output or ""
            except Exception as e:
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error("Max retries reached")
                    raise

    async def ask_structured(
        self,
        prompt: str,
        output_type: type,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> Any:
        """Send a prompt and return a parsed Pydantic model instance.

        Tries native structured output first, falls back to manual
        JSON extraction and model validation.
        """
        for attempt in range(self.max_retries):
            try:
                response = await self.client.ask(
                    prompt=prompt,
                    model=self.model,
                    temperature=temperature,
                    structured_output=output_type,
                    system_prompt=system_prompt,
                )
                # Native structured output
                if hasattr(response, "structured_output") and response.structured_output:
                    result = response.structured_output
                    if isinstance(result, output_type):
                        return result
                    # Try to re-parse if it came back as dict
                    if isinstance(result, dict):
                        return output_type.model_validate(result)

                # Fallback: parse raw text
                raw_text = response.output or ""
                parsed = extract_json(raw_text)
                if isinstance(parsed, dict):
                    return output_type.model_validate(parsed)
                elif isinstance(parsed, list):
                    return parsed
                return parsed
            except Exception as e:
                logger.warning(
                    "Structured LLM call attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error("Max retries reached for structured call")
                    raise

    async def ask_with_finish_info(
        self,
        prompt: str,
        temperature: float = 0.0,
        chat_history: Optional[list[dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
    ) -> tuple[str, str]:
        """LLM call that returns (text, finish_reason).

        finish_reason is 'finished' or 'max_output_reached'.
        """
        for attempt in range(self.max_retries):
            try:
                full_prompt = prompt
                if chat_history:
                    context_parts = []
                    for msg in chat_history:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")
                        context_parts.append(f"[{role}]: {content}")
                    context_str = "\n".join(context_parts)
                    full_prompt = f"{context_str}\n[user]: {prompt}"

                response = await self.client.ask(
                    prompt=full_prompt,
                    model=self.model,
                    temperature=temperature,
                    system_prompt=system_prompt,
                )
                text = response.output or ""
                # Detect truncation via finish_reason if available
                finish_reason = "finished"
                if hasattr(response, "finish_reason"):
                    fr = response.finish_reason
                    if fr and "length" in str(fr).lower():
                        finish_reason = "max_output_reached"
                return text, finish_reason
            except Exception as e:
                logger.warning(
                    "LLM call with finish info attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error("Max retries reached")
                    raise

    async def ask_json(
        self,
        prompt: str,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> Any:
        """Send a prompt and return parsed JSON (dict or list)."""
        raw = await self.ask(
            prompt=prompt,
            temperature=temperature,
            system_prompt=system_prompt,
        )
        if isinstance(raw, str):
            return extract_json(raw)
        return raw
