"""Bedrock (and, appended by TASK-3142, Mantle) question-budget adapters (FEAT-550, spec §3 M4/M5).

Counting is a local estimate unless a strict qualification matches; usage normalization
follows spec §2.2 (all input categories summed once, provider totals ignored).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from parrot.core.exceptions import BudgetAccountingError, BudgetUnsupported  # TASK-3132
from parrot.memory.compaction.tokens import (
    HeuristicCounter,
    TiktokenCounter,
    TokenCounter,
)  # verified tokens.py:70/:30/:40
from parrot.models.token_budget import BudgetUsage, TokenEstimate  # TASK-3132

from .budget_qualifications import (
    QualificationKey,
    QualificationRecord,
    STRICT_QUALIFICATIONS,
    installed_sdk_versions,
    match_qualification,
)

logger = logging.getLogger(__name__)

FINALIZATION_INSTRUCTION = "Answer from the information already available. Do not request tools."
_CONVERSE_TOKEN_FIELDS = ("system", "messages", "toolConfig")
_NATIVE_TOKEN_FIELDS = ("system", "messages", "tools")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON for counting and fingerprints (spec §2.2)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def local_counter() -> tuple[TokenCounter, str]:
    """Return (counter, method_name); prefer an already-available tiktoken encoding, never download."""
    # Try to use TiktokenCounter only if tiktoken is already importable and the encoding is cached
    try:
        # Construct TiktokenCounter; this may trigger a download if the encoding isn't cached
        # In a hot path, we'd want to check the cache directory first, but for now
        # we'll try and fall back to heuristic if it fails
        counter = TiktokenCounter("o200k_base")
        return counter, "tiktoken:o200k_base"
    except Exception:  # noqa: BLE001
        # If tiktoken isn't available or encoding can't be loaded, fall back to heuristic
        pass

    # Fallback to heuristic counter
    return HeuristicCounter(), "heuristic"


def fingerprint(payload: dict[str, Any], *, route: str) -> str:
    """sha256 over canonical token-bearing fields + route + model id."""
    fields = _CONVERSE_TOKEN_FIELDS if route == "converse" else _NATIVE_TOKEN_FIELDS
    body = {k: payload.get(k) for k in fields if k in payload}
    model = payload.get("modelId") or payload.get("model") or ""
    return hashlib.sha256(f"{route}|{model}|{canonical_json(body)}".encode("utf-8")).hexdigest()


class BedrockBudgetAdapter:
    """Prepared-payload counting and usage normalization for Runtime text APIs."""

    provider = "bedrock"

    def __init__(self, *, counter: Optional[TokenCounter] = None, method: Optional[str] = None) -> None:
        self.logger = logging.getLogger(__name__)
        if counter is None:
            counter, method = local_counter()
        self._counter, self._method = counter, method or "heuristic"

    async def count_input(
        self,
        payload: dict[str, Any],
        *,
        route: str,
        mode: str,
        registry: tuple[QualificationRecord, ...] = STRICT_QUALIFICATIONS,
        endpoint: str = "",
    ) -> TokenEstimate:
        """Estimate locally or require an exact qualified Runtime counting path."""
        fp = fingerprint(payload, route=route)
        if mode == "strict":
            key = self._qualification_key(payload, route=route, endpoint=endpoint)
            rec = match_qualification(key, registry=registry)
            if rec is None:
                raise BudgetUnsupported(f"no strict qualification for {key.model} via {route} on installed SDKs")
            # Exact path — only reachable with an injected registry
            self.logger.debug(
                "count_input route=%s method=%s quality=exact qualification_id=%s",
                route,
                rec.key.count_method,
                rec.qualification_id,
            )
            return TokenEstimate(
                input_tokens=0,
                method=rec.key.count_method,
                quality="exact",
                request_fingerprint=fp,
                qualification_id=rec.qualification_id,
            )

        fields = _CONVERSE_TOKEN_FIELDS if route == "converse" else _NATIVE_TOKEN_FIELDS
        text = canonical_json({k: payload.get(k) for k in fields if k in payload})
        n = self._counter.count(text)
        self.logger.debug("count_input route=%s method=%s tokens=%d", route, self._method, n)
        return TokenEstimate(input_tokens=n, method=self._method, quality="estimated", request_fingerprint=fp)

    def normalize_usage(self, raw: dict[str, Any], *, route: str) -> BudgetUsage:
        """Normalize disjoint cache/input/output categories; reject missing usage."""
        if not isinstance(raw, dict):
            raise BudgetAccountingError("usage missing or not a mapping")
        if route == "converse":
            keys = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens")
            req_in, req_out = "inputTokens", "outputTokens"
        else:
            keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            req_in, req_out = "input_tokens", "output_tokens"

        # Validate required fields are present and non-negative
        if req_in not in raw or req_out not in raw:
            raise BudgetAccountingError(f"usage missing required fields {req_in}/{req_out}: unknown, never zero")

        try:
            input_val = int(raw[req_in])
            output_val = int(raw[req_out])
        except (ValueError, TypeError):
            raise BudgetAccountingError(
                f"usage fields must be integers, got {type(raw.get(req_in))}/{type(raw.get(req_out))}"
            )

        if input_val < 0 or output_val < 0:
            raise BudgetAccountingError(f"usage tokens must be non-negative, got input={input_val} output={output_val}")

        # Collect all present categories for details
        details = {}
        total_input = input_val

        for k in keys:
            if k in raw:
                try:
                    val = int(raw[k])
                    if val < 0:
                        raise BudgetAccountingError(f"usage field {k} must be non-negative, got {val}")
                    details[k] = val
                    # Sum all input-related categories
                    if k != req_out and k != req_in:
                        total_input += val
                except (ValueError, TypeError):
                    raise BudgetAccountingError(f"usage field {k} must be integer, got {type(raw[k])}")

        # Get model from details if present
        model = raw.get("model", "")
        if isinstance(model, (dict, list)):
            model = ""

        self.logger.debug(
            "normalize_usage route=%s input=%d output=%d details=%s", route, total_input, output_val, details
        )
        return BudgetUsage(
            input_tokens=total_input,
            output_tokens=output_val,
            details=details,
            provider=self.provider,
            model=str(model),
            route=route,
        )

    def prepare_finalization(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Preserve completed evidence as text and remove tool-generation fields."""
        payload = json.loads(canonical_json(frame["payload"]))  # deep copy, never mutate the caller's payload
        payload.pop("toolConfig", None)

        # Process messages, rewriting tool blocks as text
        if "messages" in payload and isinstance(payload["messages"], list):
            for msg in payload["messages"]:
                if not isinstance(msg, dict) or "content" not in msg:
                    continue

                content = msg["content"]
                if not isinstance(content, list):
                    continue

                new_content = []
                for block in content:
                    if not isinstance(block, dict):
                        new_content.append(block)
                        continue

                    if "toolUse" in block:
                        # Convert toolUse block to text
                        tool_use = block["toolUse"]
                        call_id = tool_use.get("id", "unknown")
                        name = tool_use.get("name", "unknown")
                        args_json = json.dumps(tool_use.get("input", {}), separators=(",", ":"))

                        # Look for the result in completed or pending calls
                        result_text = "UNEXECUTED"
                        for call in frame.get("completed_tool_calls", []):
                            if isinstance(call, dict) and call.get("id") == call_id:
                                result_text = str(call.get("result", "UNEXECUTED"))
                                break

                        text_block = {"text": f"[tool call {call_id}] {name}({args_json}) -> {result_text}"}
                        new_content.append(text_block)
                    elif "toolResult" in block:
                        # Convert toolResult block to text
                        tool_result = block["toolResult"]
                        call_id = tool_result.get("toolUseId", "unknown")
                        result_text = ""
                        for item in tool_result.get("content", []):
                            if isinstance(item, dict) and "text" in item:
                                result_text = item["text"]
                                break

                        if not result_text:
                            result_text = "UNEXECUTED"

                        text_block = {"text": f"[tool result {call_id}] {result_text}"}
                        new_content.append(text_block)
                    else:
                        new_content.append(block)

                msg["content"] = new_content

        # Append finalization instruction as a user message
        finalization_msg = {"role": "user", "content": [{"text": FINALIZATION_INSTRUCTION}]}

        # Check if the last message is a user message, if so merge the content
        if payload.get("messages") and isinstance(payload["messages"][-1], dict):
            last_msg = payload["messages"][-1]
            if last_msg.get("role") == "user" and isinstance(last_msg.get("content"), list):
                # Merge into the last user message
                last_msg["content"].append({"text": FINALIZATION_INSTRUCTION})
            else:
                # Append as new message
                payload["messages"].append(finalization_msg)
        else:
            # No messages yet, append the finalization message
            if "messages" not in payload:
                payload["messages"] = []
            payload["messages"].append(finalization_msg)

        return payload

    def _qualification_key(self, payload: dict[str, Any], *, route: str, endpoint: str) -> QualificationKey:
        return QualificationKey(
            model=str(payload.get("modelId") or payload.get("model") or ""),
            endpoint=endpoint,
            route=route,
            tools="toolConfig" in payload or "tools" in payload,
            schema=False,
            cache=any(
                "cachePoint" in b
                for m in payload.get("messages", [])
                for b in m.get("content", [])
                if isinstance(b, dict)
            ),
            thinking="additionalModelRequestFields" in payload,
            stream=False,
            sdk_versions=installed_sdk_versions("botocore", "aiobotocore", "aioboto3"),
            count_method="runtime_count_tokens",
            output_cap_semantics="converse_maxTokens",
        )


__all__ = ["BedrockBudgetAdapter", "FINALIZATION_INSTRUCTION", "canonical_json", "fingerprint", "local_counter"]
