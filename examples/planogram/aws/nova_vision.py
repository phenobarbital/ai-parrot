"""Bedrock Converse image transport for Nova — the ``ask_to_image`` shim (FEAT-592).

Prototype for the eventual ``BedrockConverseBase`` image support; today that client
drops image attachments outright (verified: bedrock.py:725-745).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel

from parrot.clients.amazon.nova.client import NovaClient

logger = logging.getLogger(__name__)

_GEO_PREFIXES = ("us.", "eu.", "jp.", "global.")


class NovaAnswer:
    """Minimal AIMessage-like carrier. ``VisionAdapter._extract`` reads ``.output``."""

    def __init__(self, output: str, usage: Dict[str, int], image_bytes: int) -> None:
        self.output = output
        self.usage = usage
        self.image_bytes = image_bytes


class NovaVisionClient:
    """``ask_to_image``-compatible Bedrock Converse image transport for Nova."""

    client_name: str = "nova"

    def __init__(self, nova: NovaClient, model_id: str) -> None:
        """Bind an already-configured NovaClient and its fully resolved model id."""
        self._nova = nova
        self._model_id = model_id
        self.logger = logger
        #: Real Bedrock call/usage accounting — incremented only when ``ask_to_image``
        #: actually reaches Converse. ``VisionAdapter.ask()`` discards ``NovaAnswer``
        #: (it returns only the parsed schema) and its cache short-circuits BEFORE
        #: calling this client, so these are the only place a cache hit is visible.
        self.calls_made: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_image_bytes_sent: int = 0

    @classmethod
    async def create(
        cls,
        *,
        aws_id: Optional[str] = None,
        region: Optional[str] = None,
        model: str = "nova-2-lite",
        region_prefix: Optional[str] = "us",
    ) -> "NovaVisionClient":
        """Build a NovaClient, resolve the geo-prefixed model id, and open the runtime client.

        Raises:
            RuntimeError: The resolved model id carries no geo/global prefix.
        """
        nova = NovaClient(model=model, aws_id=aws_id, region=region, region_prefix=region_prefix)
        # ``_ensure_client()`` caches the aioboto3 client per event loop so ``close()`` tears it
        # down. A bare ``get_client()`` builds an uncached client whose aiohttp session leaks
        # ("Unclosed client session" at exit).
        await nova._ensure_client()
        model_id = nova._translate_model(model)
        if not model_id.startswith(_GEO_PREFIXES):
            await nova.close()
            raise RuntimeError(f"Nova vision model id must have a geo/global prefix: {model_id}")
        return cls(nova=nova, model_id=model_id)

    @property
    def resolved_model_id(self) -> str:
        """The exact id sent to Bedrock, e.g. ``us.amazon.nova-2-lite-v1:0``."""
        return self._model_id

    @property
    def resolved_region(self) -> str:
        """The AWS region ``NovaClient`` actually resolved, not the raw ``--region`` flag.

        Mirrors ``resolved_model_id``: ``bedrock.py``'s credential chain resolves
        ``self._region`` through ``kwarg -> profile.region_name -> BEDROCK_AWS_REGION
        -> AWS_REGION_NAME -> "us-east-1"``, so an unset ``--region`` must read this
        property rather than echo ``None`` into ``run.json``.
        """
        return self._nova._region

    @staticmethod
    def _assert_has_image(blocks: Sequence[Dict[str, Any]]) -> int:
        """Guard: the request must carry an image block; return its total bytes.

        Raises:
            RuntimeError: No block in ``blocks`` is an ``{"image": ...}`` block.
        """
        total = sum(len(block["image"]["source"]["bytes"]) for block in blocks if "image" in block)
        if total == 0:
            raise RuntimeError("Converse request carries no image block - refusing to send a " "text-only vision call")
        return total

    @staticmethod
    def _schema_instruction(schema: Type[BaseModel]) -> str:
        """Render ``schema.model_json_schema()`` into a 'reply with only this JSON' rule."""
        return "Reply with only JSON that conforms to this schema:\n" + json.dumps(schema.model_json_schema())

    async def ask_to_image(
        self,
        *,
        prompt: str,
        image: bytes,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
        structured_output: Optional[Type[BaseModel]] = None,
        reference_images: Optional[List[bytes]] = None,
    ) -> NovaAnswer:
        """Make one Converse call with PNG image content and return the raw text.

        Raises:
            RuntimeError: The request carries no image content block, or Converse returns no text block.
        """
        prompt_text = prompt
        if structured_output is not None:
            prompt_text = f"{prompt}\n\n{self._schema_instruction(structured_output)}"
        blocks: List[Dict[str, Any]] = [{"text": prompt_text}]
        for image_bytes in [image, *(reference_images or [])]:
            blocks.append({"image": {"format": "png", "source": {"bytes": image_bytes}}})

        image_bytes = self._assert_has_image(blocks)
        client = await self._nova._ensure_client()  # cached per loop; closed by ``aclose()``
        response = await client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": blocks}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        self.calls_made += 1  # reached Bedrock — the only place a VisionAdapter cache hit is visible
        self.total_image_bytes_sent += image_bytes
        content = response.get("output", {}).get("message", {}).get("content", [])
        text = next((block["text"] for block in content if "text" in block), None)
        if text is None:
            raise RuntimeError("Converse response carries no text content block")
        raw_usage = response.get("usage", {})
        usage = {
            "input_tokens": int(raw_usage.get("inputTokens", 0)),
            "output_tokens": int(raw_usage.get("outputTokens", 0)),
        }
        self.total_input_tokens += usage["input_tokens"]
        self.total_output_tokens += usage["output_tokens"]
        return NovaAnswer(output=text, usage=usage, image_bytes=image_bytes)

    async def aclose(self) -> None:
        """Close the composed NovaClient — verified: bedrock.py:673 ``async def close``."""
        await self._nova.close()
