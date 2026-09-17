"""Vision backend adapter for the planogram compliance check (FEAT-565, Module 6).

One coroutine — prompt + images + Pydantic schema -> validated instance — over any ai-parrot
client, with a disk cache. Two duck-typed lanes; provider SDK objects are never touched here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

LOCAL_PROVIDERS: frozenset[str] = frozenset({"local", "localllm", "ollama", "llamacpp", "vllm"})
PREREQUISITE_FEATURE: str = "localllm-ask-to-image"


class VisionError(RuntimeError):
    """Provider, transport or schema failure after the repair retry."""


def split_llm(llm: str) -> tuple[str, str | None]:
    """Split ``"provider:model"`` into (lower-cased provider, model or None).

    Mirrors ``LLMFactory.parse_llm_string`` without importing parrot.
    """
    if ":" in llm:
        provider, model = llm.split(":", 1)
        provider = provider.strip().lower()
        model = model.strip()
        return provider, (model or None)
    return llm.strip().lower(), None


def cache_key(llm: str, base_url: str | None, max_tokens: int, stage: str, prompt_version: str,
              prompt: str, schema: type[BaseModel], images: Sequence[bytes]) -> str:
    """Return the sha256 hex digest of a canonical JSON of ALL arguments (images by their sha256)."""
    payload = {
        "llm": llm,
        "base_url": base_url,
        "max_tokens": max_tokens,
        "stage": stage,
        "prompt_version": prompt_version,
        "prompt": prompt,
        "schema": schema.model_json_schema(),
        "images": [hashlib.sha256(image).hexdigest() for image in images],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_store(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write ``payload`` as JSON: temp file in the same directory + ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
        ) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(serialized)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def _cache_load(path: Path, schema: type[T]) -> T | None:
    """Return the cached, re-validated instance, or None when absent, corrupt or incompatible."""
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        return schema.model_validate(payload["parsed"])
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        logger.warning("Discarding invalid cache entry at %s: %s", path, exc)
        return None


class VisionBackend:
    """Adapter: prompt + images + Pydantic schema -> validated instance."""

    def __init__(self, llm: str, *, cache_dir: Path, base_url: str | None = None,
                 api_key: str | None = None, max_tokens: int = 8192, client: Any | None = None) -> None:
        """Create (or accept) the ai-parrot client.

        Args:
            llm: ``"provider:model"`` string understood by ``LLMFactory``.
            cache_dir: Response cache directory (resolved to an absolute path immediately).
            base_url: Optional server URL for OpenAI-compatible/local providers.
            api_key: Optional API key override.
            max_tokens: Generation cap, also part of the cache key.
            client: TEST SEAM — a pre-built client; when given, parrot is never imported.
        """
        self.llm = llm
        self.provider, self.model = split_llm(llm)
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.cache_dir = Path(cache_dir).resolve()  # BEFORE the lazy parrot import (navconfig chdir)
        if client is None:
            from parrot.clients.factory import LLMFactory  # lazy: verified factory.py:257

            kwargs: dict[str, Any] = {}
            if base_url is not None:
                kwargs["base_url"] = base_url
            if api_key is not None:
                kwargs["api_key"] = api_key
            client = LLMFactory.create(llm, model_args={"temperature": 0.0, "max_tokens": max_tokens}, **kwargs)
        self._llm_client: Any = client

    @property
    def is_local(self) -> bool:
        """True for provider keys local/localllm/ollama/llamacpp/vllm."""
        return self.provider in LOCAL_PROVIDERS

    async def __aenter__(self) -> "VisionBackend":
        """Fail fast when the client has no vision method, then enter the client."""
        if not hasattr(self._llm_client, "image_understanding") and not hasattr(self._llm_client, "ask_to_image"):
            raise VisionError(
                f"client {type(self._llm_client).__name__} has no vision method; "
                f"it needs feature '{PREREQUISITE_FEATURE}'"
            )
        if hasattr(self._llm_client, "__aenter__"):
            await self._llm_client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the client context when it has one."""
        if hasattr(self._llm_client, "__aexit__"):
            exc_args = exc if exc else (None, None, None)
            await self._llm_client.__aexit__(*exc_args)

    async def ask(self, prompt: str, images: Sequence[bytes], schema: type[T], *, stage: str,
                  prompt_version: str) -> T:
        """Cache lookup -> lane dispatch -> validate -> one repair retry -> cache store.

        Raises:
            ValueError: ``images`` is empty.
            VisionError: provider failure, or the answer is invalid after the repair retry.
        """
        if not images:
            raise ValueError("images must not be empty")

        key = cache_key(self.llm, self.base_url, self.max_tokens, stage, prompt_version, prompt, schema, images)
        path = self.cache_dir / f"{key}.json"
        cached = _cache_load(path, schema)
        if cached is not None:
            logger.debug("Vision cache hit for stage=%s key=%s", stage, key)
            return cached

        try:
            message = await self._call(prompt, images, schema)
        except Exception as exc:
            raise VisionError(f"vision call failed for stage {stage!r}: {exc}") from exc

        try:
            result = self._extract(message, schema)
        except (ValidationError, ValueError) as exc:
            repair_prompt = (
                f"{prompt}\n\nYour previous answer was rejected: {exc}. "
                "Return ONLY valid JSON for the schema."
            )
            try:
                message = await self._call(repair_prompt, images, schema)
            except Exception as inner_exc:
                raise VisionError(f"vision call failed for stage {stage!r}: {inner_exc}") from inner_exc
            try:
                result = self._extract(message, schema)
            except (ValidationError, ValueError) as second_exc:
                raise VisionError(
                    f"vision answer invalid after repair retry for stage {stage!r}: {second_exc}"
                ) from second_exc

        cache_store(
            path,
            {"llm": self.llm, "stage": stage, "prompt_version": prompt_version, "parsed": result.model_dump(mode="json")},
        )
        return result

    async def _call(self, prompt: str, images: Sequence[bytes], schema: type[T]) -> Any:
        """Dispatch to lane 1 (``image_understanding``) or lane 2 (``ask_to_image``); return the AIMessage."""
        model_kw: dict[str, Any] = {"model": self.model} if self.model else {}
        if hasattr(self._llm_client, "image_understanding"):  # lane 1 — Google (analysis.py:438)
            return await self._llm_client.image_understanding(
                prompt, images=list(images), structured_output=schema, temperature=0.0, stateless=True, **model_kw
            )
        return await self._llm_client.ask_to_image(  # lane 2 — generic common subset
            prompt, image=images[0], reference_images=list(images[1:]) or None, structured_output=schema,
            temperature=0.0, max_tokens=self.max_tokens, **model_kw
        )

    @staticmethod
    def _extract(message: Any, schema: type[T]) -> T:
        """Turn an AIMessage into a ``schema`` instance (raises ValidationError / ValueError)."""
        for candidate in (getattr(message, "structured_output", None), getattr(message, "output", None)):
            if candidate is None:
                continue
            if isinstance(candidate, schema):
                return candidate
            if isinstance(candidate, BaseModel):
                return schema.model_validate(candidate.model_dump())
            if isinstance(candidate, (dict, list)):
                return schema.model_validate(candidate)
            if isinstance(candidate, str):
                text = candidate.strip()
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                return schema.model_validate(parsed)
        raise ValueError("no structured output in response")
