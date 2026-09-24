"""Provider-neutral vision adapter — the only caller of ``ask_to_image`` in the new planogram cycle."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Sequence, Type, TypeVar

import cv2
import numpy as np
from pydantic import BaseModel, ValidationError

from parrot_pipelines.planogram.backend import ResolvedBackend

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_COMMON: FrozenSet[str] = frozenset({"model", "max_tokens", "temperature", "structured_output", "reference_images"})
SUPPORTED_KWARGS: Dict[str, FrozenSet[str]] = {
    "google": _COMMON | {"no_memory"},  # verified: google/client.py:4999-5010
    "claude": _COMMON
    | {"no_memory", "system_prompt"},  # verified: anthropic/client.py:1307-1320 (+ no_memory, TASK-3425)
    "openai": _COMMON | {"no_memory"},  # verified: openai/client.py:1468
}
KNOWN_KWARGS: FrozenSet[str] = frozenset().union(*SUPPORTED_KWARGS.values())


class VisionError(RuntimeError):
    """Vision call failed, timed out, or stayed invalid after the repair retry."""


def normalise_kwargs(client_name: str, requested: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the kwargs ``client_name`` supports (unknown provider ⇒ common subset); drop ``None`` values.

    Args:
        client_name: The client's ``client_name`` (lower-cased by the caller).
        requested: Requested keyword arguments.

    Returns:
        The kwargs the provider accepts, without ``None`` values.

    Raises:
        VisionError: a key outside ``KNOWN_KWARGS`` — unknown kwargs are never dropped silently.
    """
    unknown = sorted(set(requested) - KNOWN_KWARGS)
    if unknown:
        raise VisionError(f"unknown ask_to_image kwargs: {', '.join(unknown)}")
    supported = SUPPORTED_KWARGS.get(client_name, _COMMON)
    kept: Dict[str, Any] = {}
    for key, value in requested.items():
        if value is None:
            continue
        if key not in supported:
            logger.debug("ask_to_image kwarg %r not supported by client %r: omitted", key, client_name)
            continue
        kept[key] = value
    return kept


def cache_key(
    backend: str,
    max_tokens: int,
    stage: str,
    prompt_version: str,
    prompt: str,
    schema: Type[BaseModel],
    images: Sequence[bytes],
) -> str:
    """sha256 over a canonical JSON of all arguments incl. ``schema.model_json_schema()`` and image digests.

    Args:
        backend: ``ResolvedBackend.as_string()``.
        max_tokens: Output budget.
        stage: Pipeline stage name.
        prompt_version: Prompt template version.
        prompt: The final prompt text.
        schema: Structured-output schema.
        images: Encoded images (main first).

    Returns:
        The hex digest.
    """
    payload = {
        "backend": backend,
        "max_tokens": max_tokens,
        "stage": stage,
        "prompt_version": prompt_version,
        "prompt": prompt,
        "schema_name": f"{schema.__module__}.{schema.__qualname__}",
        "schema": schema.model_json_schema(),
        "images": [hashlib.sha256(image).hexdigest() for image in images],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def encode_png(image: np.ndarray) -> bytes:
    """PNG-encode a BGR array. Module-level and picklable — run it through the CPU executor, never inline.

    Args:
        image: BGR (or gray) ``uint8`` array.

    Returns:
        PNG bytes.

    Raises:
        ValueError: OpenCV could not encode the array.
    """
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("cv2.imencode failed")
    return buffer.tobytes()


def _read_json(path: Path) -> Any:
    """Blocking JSON read (run through ``asyncio.to_thread``)."""
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Blocking atomic-ish JSON write (run through ``asyncio.to_thread``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


class VisionAdapter:
    """Prompt + images + Pydantic schema → validated instance, on any client exposing ``ask_to_image``."""

    def __init__(
        self,
        client: Any,
        backend: ResolvedBackend,
        *,
        semaphore: asyncio.Semaphore,
        cache_dir: Optional[Path] = None,
        max_tokens: int = 8192,
        timeout: float = 120.0,
        repair_retries: int = 1,
    ) -> None:
        """Bind a client and its resolved backend.

        Args:
            client: An LLM client exposing ``ask_to_image``.
            backend: The resolved backend (the model kwarg is sent only when pinned).
            semaphore: Bounds concurrent provider calls (shared per pipeline run).
            cache_dir: Response cache directory; ``None`` disables the cache.
            max_tokens: Output budget of every call.
            timeout: Per-call timeout in seconds.
            repair_retries: Repair prompts after an invalid answer (0 disables).

        Raises:
            VisionError: when the client has no ``ask_to_image``.
        """
        if not hasattr(client, "ask_to_image"):
            raise VisionError(
                f"client {type(client).__name__} has no ask_to_image; it cannot drive the planogram cycle"
            )
        self.client = client
        self.backend = backend
        self.client_name = str(getattr(client, "client_name", "") or "").lower()
        self.semaphore = semaphore
        self.cache_dir = Path(cache_dir).resolve() if cache_dir else None
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.repair_retries = repair_retries
        self.logger = logging.getLogger(__name__)

    async def ask(
        self,
        prompt: str,
        images: Sequence[bytes],
        schema: Type[T],
        *,
        stage: str,
        prompt_version: str,
        system_prompt: Optional[str] = None,
    ) -> T:
        """Ask one structured question about images.

        ``images[0]`` is the main image, the rest go as ``reference_images``.

        Args:
            prompt: The prompt.
            images: Encoded images (at least one).
            schema: Pydantic schema the answer must validate into.
            stage: Stage name (cache key + logs).
            prompt_version: Prompt template version (cache key).
            system_prompt: Optional system prompt (native or folded into the prompt).

        Returns:
            A validated ``schema`` instance.

        Raises:
            ValueError: ``images`` is empty.
            VisionError: provider failure, timeout, or an answer still invalid after the repair retries.
        """
        if not images:
            raise ValueError("images must not be empty")
        key = cache_key(
            self.backend.as_string(),
            self.max_tokens,
            stage,
            prompt_version,
            self._final_prompt(prompt, system_prompt),
            schema,
            images,
        )
        cached = await self._cache_load(key, schema)
        if cached is not None:
            self.logger.debug("vision cache hit: stage=%s key=%s", stage, key)
            return cached

        attempt_prompt = prompt
        last_error: Optional[Exception] = None
        for attempt in range(self.repair_retries + 1):
            message = await self._call(attempt_prompt, images, schema, system_prompt, stage)
            try:
                result = self._extract(message, schema)
            except (ValidationError, ValueError) as exc:
                last_error = exc
                self.logger.debug("vision answer invalid (stage=%s, attempt=%d): %s", stage, attempt + 1, exc)
                attempt_prompt = (
                    f"{prompt}\n\nYour previous answer was rejected: {exc}. Return ONLY valid JSON for the schema."
                )
                continue
            await self._cache_store(key, stage, prompt_version, result)
            return result
        raise VisionError(
            f"vision answer invalid after {self.repair_retries} repair retr"
            f"{'y' if self.repair_retries == 1 else 'ies'} for stage {stage!r}: {last_error}"
        ) from last_error

    def _final_prompt(self, prompt: str, system_prompt: Optional[str]) -> str:
        """Prompt as sent: the system prompt is folded in when the provider has no native support."""
        if system_prompt and "system_prompt" not in SUPPORTED_KWARGS.get(self.client_name, _COMMON):
            return f"{system_prompt}\n\n{prompt}"
        return prompt

    async def _call(
        self,
        prompt: str,
        images: Sequence[bytes],
        schema: Type[T],
        system_prompt: Optional[str],
        stage: str = "",
    ) -> Any:
        """One provider call under the semaphore and the timeout; provider exceptions → VisionError."""
        final_prompt = self._final_prompt(prompt, system_prompt)
        native_system = system_prompt if final_prompt == prompt else None
        requested: Dict[str, Any] = {
            "model": self.backend.model,
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
            "structured_output": schema,
            "reference_images": list(images[1:]) or None,
            "no_memory": True,
            "system_prompt": native_system,
        }
        kwargs = normalise_kwargs(self.client_name, requested)
        async with self.semaphore:
            try:
                return await asyncio.wait_for(
                    self.client.ask_to_image(prompt=final_prompt, image=images[0], **kwargs), timeout=self.timeout
                )
            except asyncio.TimeoutError as exc:
                raise VisionError(f"vision call timed out after {self.timeout}s (stage {stage!r})") from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - every provider failure becomes a VisionError
                raise VisionError(f"vision call failed (stage {stage!r}): {exc}") from exc

    @staticmethod
    def _extract(message: Any, schema: Type[T]) -> T:
        """AIMessage-like → schema instance. Raises ValidationError / ValueError."""
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
                    text = text.strip("`").strip()
                    if text.lower().startswith("json"):
                        text = text[4:]
                    text = text.strip()
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                return schema.model_validate(parsed)
        raise ValueError("no structured output in response")

    async def _cache_load(self, key: str, schema: Type[T]) -> Optional[T]:
        """Read a cached answer; any failure (missing, corrupt, schema-incompatible) is a miss."""
        if self.cache_dir is None:
            return None
        path = self.cache_dir / f"{key}.json"
        try:
            payload = await asyncio.to_thread(_read_json, path)
            return schema.model_validate(payload["parsed"])
        except FileNotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001 - a bad cache entry is only a miss
            self.logger.debug("vision cache entry unusable (%s): %s", key, exc)
            return None

    async def _cache_store(self, key: str, stage: str, prompt_version: str, result: BaseModel) -> None:
        """Store a validated answer (no-op when the cache is disabled; failures are logged, not raised)."""
        if self.cache_dir is None:
            return
        payload = {
            "backend": self.backend.as_string(),
            "stage": stage,
            "prompt_version": prompt_version,
            "parsed": result.model_dump(mode="json"),
        }
        try:
            await asyncio.to_thread(_write_json, self.cache_dir / f"{key}.json", payload)
        except OSError as exc:
            self.logger.warning("vision cache write failed (%s): %s", key, exc)
