"""``LlamaCppDelegate`` — grammar-constrained tool proposals from ``llama-server`` (FEAT-590)."""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Mapping, Optional, Sequence, Type, Union

import aiohttp
from pydantic import BaseModel

from .protocol import DelegateBackendError, ToolCallProposal, ToolSpec

__all__ = ("LlamaCppDelegate",)


def _namespace_refs(node: Any, prefix: str, hoisted_defs: Dict[str, Any]) -> Any:
    """Rewrite ``$ref: "#/$defs/X"`` -> ``"#/$defs/<prefix>__X"`` recursively, and
    hoist the corresponding ``$defs`` entries (once) into ``hoisted_defs``.
    """
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "$defs" and isinstance(value, dict):
                for def_name, def_schema in value.items():
                    hoisted_defs[f"{prefix}__{def_name}"] = _namespace_refs(def_schema, prefix, hoisted_defs)
                continue
            if key == "$ref" and isinstance(value, str) and value.startswith("#/$defs/"):
                out[key] = f"#/$defs/{prefix}__{value[len('#/$defs/'):]}"
                continue
            out[key] = _namespace_refs(value, prefix, hoisted_defs)
        return out
    if isinstance(node, list):
        return [_namespace_refs(item, prefix, hoisted_defs) for item in node]
    return node


class LlamaCppDelegate:
    """HTTP client for ``llama-server --parallel N``; natively async, no pool."""

    backend_name = "llamacpp"

    def __init__(
        self,
        base_url: str,
        *,
        model: Optional[str] = None,
        max_tools: int = 5,
        max_input_chars: int = 4000,
        timeout: float = 30.0,
        use_logprobs: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tools = max_tools
        self.max_input_chars = max_input_chars
        self.timeout = timeout
        self.use_logprobs = use_logprobs
        self._session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(f"{__name__}.LlamaCppDelegate")

    def _call_schema(self, tools: Sequence[ToolSpec]) -> Dict[str, Any]:
        """oneOf of {name: const, arguments: <schema>} per tool, plus {name: null} to decline."""
        branches: list[Dict[str, Any]] = []
        hoisted_defs: Dict[str, Any] = {}
        for spec in tools:
            parameters = _namespace_refs(spec.parameters or {"type": "object"}, spec.name, hoisted_defs)
            branches.append(
                {
                    "type": "object",
                    "properties": {
                        "name": {"const": spec.name},
                        "arguments": parameters,
                    },
                    "required": ["name", "arguments"],
                    "additionalProperties": False,
                }
            )
        branches.append(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "null"},
                },
                "required": ["name"],
                "additionalProperties": False,
            }
        )
        schema: Dict[str, Any] = {"oneOf": branches}
        if hoisted_defs:
            schema["$defs"] = hoisted_defs
        return schema

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST to the endpoint chosen by the spike; map any failure to DelegateBackendError."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        url = f"{self.base_url}/v1/chat/completions"
        try:
            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise DelegateBackendError(f"llama-server returned status {resp.status}: {text}")
                return await resp.json()
        except DelegateBackendError:
            raise
        except Exception as exc:
            raise DelegateBackendError(f"HTTP request to llama-server failed: {exc}") from exc

    async def propose_call(
        self, instruction: str, tools: Sequence[ToolSpec], facts: Optional[Mapping[str, str]] = None
    ) -> ToolCallProposal:
        """Propose one call; ``name=None`` when the model takes the decline branch."""
        started = time.monotonic()
        schema = self._call_schema(tools)

        # Build system prompt
        lines = [
            "You are a tool-call proposer. Given an instruction, propose exactly "
            'one call from the tools below, or decline with {"name": null} if '
            "none of them fit. Never invent a tool name or argument key.",
            "Tools:",
        ]
        for spec in tools:
            lines.append(f"- {spec.name}: {spec.description or ''}".strip())
        system_prompt = "\n".join(lines)

        # Build user prompt with facts if provided
        user_lines = []
        if facts:
            user_lines.append("Facts:")
            for k, v in facts.items():
                user_lines.append(f"{k}: {v}")
        user_lines.append(f"Instruction: {instruction}")
        user_prompt = "\n".join(user_lines)

        payload: Dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "tool_call", "schema": schema, "strict": True},
            },
            "temperature": 0.0,
            "n_predict": 256,
        }
        if self.model:
            payload["model"] = self.model
        if self.use_logprobs:
            payload["logprobs"] = True
            payload["top_logprobs"] = 1

        body = await self._post(payload)
        latency_ms = (time.monotonic() - started) * 1000.0

        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
            parsed = json_loads_or_raise(content)
        except Exception as exc:
            raise DelegateBackendError(f"Failed to parse llama-server response: {exc}") from exc

        confidence: Optional[float] = None
        if self.use_logprobs:
            try:
                logprobs_obj = choice.get("logprobs")
                if logprobs_obj and logprobs_obj.get("content"):
                    token_logprobs = [t["logprob"] for t in logprobs_obj["content"] if "logprob" in t]
                    if token_logprobs:
                        avg_logprob = sum(token_logprobs) / len(token_logprobs)
                        confidence = math.exp(avg_logprob)
            except Exception as exc:
                self.logger.warning("Failed to compute confidence from logprobs: %s", exc)

        proposed_name = parsed.get("name")
        arguments = parsed.get("arguments", {}) if proposed_name is not None else {}

        return ToolCallProposal(
            name=proposed_name,
            arguments=arguments,
            confidence=confidence,
            backend=self.backend_name,
            latency_ms=latency_ms,
        )

    async def extract(self, text: str, schema: Union[Type[BaseModel], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Constrained extraction of a short text into ``schema``; ``None`` if nothing fits."""
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            target_schema = schema.model_json_schema()
        else:
            target_schema = dict(schema)

        # Wrap schema to make it nullable or allow a "failed" flag, or just use the schema directly.
        # Let's use the schema directly but wrap it in a oneOf with a null/empty fallback so we can return None if nothing fits.
        # Or we can just request the schema directly. If the model fails to fit, it might raise or return invalid JSON,
        # but with strict json_schema, llama-server forces it to fit.
        # To allow "nothing fits", we can wrap the schema in a oneOf:
        # oneOf: [ target_schema, {type: "object", properties: {failed: {const: true}}, required: [failed]} ]
        wrapped_schema = {
            "oneOf": [
                target_schema,
                {
                    "type": "object",
                    "properties": {"failed": {"const": True}},
                    "required": ["failed"],
                    "additionalProperties": False,
                },
            ]
        }

        payload: Dict[str, Any] = {
            "messages": [
                {
                    "role": "system",
                    "content": 'Extract structured data from the text. If the text does not fit the schema, return {"failed": true}.',
                },
                {"role": "user", "content": text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "extracted_data", "schema": wrapped_schema, "strict": True},
            },
            "temperature": 0.0,
            "n_predict": 256,
        }
        if self.model:
            payload["model"] = self.model

        try:
            body = await self._post(payload)
            choice = body["choices"][0]
            content = choice["message"]["content"]
            parsed = json_loads_or_raise(content)
        except Exception as exc:
            # A backend failure (HTTP error, malformed response) is indistinguishable
            # from "nothing fits" to the caller by design (both return None), but it
            # must not be indistinguishable in the logs -- log it as a warning so a
            # llama-server outage is diagnosable instead of silently read as a decline.
            self.logger.warning("extract() found nothing or the backend failed: %s", exc)
            return None

        if parsed.get("failed") is True:
            return None
        return parsed

    async def aclose(self) -> None:
        """Close the HTTP session. Idempotent."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


def json_loads_or_raise(text: str) -> Any:
    import json

    return json.loads(text)
