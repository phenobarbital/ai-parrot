"""Unit tests for plancheck.vision (FEAT-565, TASK-3342). No network, no parrot import."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from plancheck import vision
from plancheck.vision import VisionBackend, VisionError, cache_key, cache_store


class Answer(BaseModel):
    value: int


class _Msg:
    def __init__(self, structured_output: Any = None, output: Any = None) -> None:
        self.structured_output = structured_output
        self.output = output


class FakeGoogle:
    """Has BOTH methods, like GoogleGenAIClient — lane 1 must win."""
    def __init__(self, replies: list[Any]) -> None:
        self.replies, self.calls = replies, []
    async def image_understanding(self, prompt: str, images: Any, **kw: Any) -> Any:
        self.calls.append(("image_understanding", prompt, images, kw)); return self._next()
    async def ask_to_image(self, prompt: str, image: Any, **kw: Any) -> Any:
        self.calls.append(("ask_to_image", prompt, image, kw)); return self._next()
    def _next(self) -> Any:
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeGeneric:
    """Exposes ONLY ask_to_image (OpenAI / Anthropic / future LocalLLMClient). Do NOT subclass FakeGoogle:
    ``hasattr`` would still see ``image_understanding``."""
    def __init__(self, replies: list[Any]) -> None:
        self.replies, self.calls = replies, []
    async def ask_to_image(self, prompt: str, image: Any, **kw: Any) -> Any:
        self.calls.append(("ask_to_image", prompt, image, kw))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class NoVision:
    """Like LocalLLMClient today: no vision method."""


def test_cache_key_stable_and_sensitive() -> None:
    base_kwargs = dict(
        llm="google:gemini-3-flash", base_url=None, max_tokens=8192, stage="identify",
        prompt_version="v1", prompt="hello", schema=Answer, images=[b"img1", b"img2"],
    )
    key = cache_key(**base_kwargs)
    assert key == cache_key(**base_kwargs)  # determinism

    variants = [
        {"images": [b"different", b"img2"]},
        {"prompt": "different prompt"},
        {"base_url": "http://example.com"},
        {"max_tokens": 4096},
        {"stage": "verify"},
        {"prompt_version": "v2"},
    ]
    for change in variants:
        kwargs = dict(base_kwargs)
        kwargs.update(change)
        assert cache_key(**kwargs) != key, change

    class OtherSchema(BaseModel):
        other: str

    kwargs = dict(base_kwargs)
    kwargs["schema"] = OtherSchema
    # OtherSchema has no field named "value" so the json schema differs
    assert cache_key(**kwargs) != key


def test_cache_store_atomic(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "entry.json"

    class NotSerialisable:
        pass

    with pytest.raises(TypeError):
        cache_store(target, {"bad": NotSerialisable()})

    assert not target.exists()
    assert list((tmp_path / "sub").glob("*")) == []


def test_is_local() -> None:
    fake = object()
    assert VisionBackend("llamacpp:x", cache_dir=Path("."), client=fake).is_local is True
    assert VisionBackend("vllm:y", cache_dir=Path("."), client=fake).is_local is True
    assert VisionBackend("ollama", cache_dir=Path("."), client=fake).is_local is True
    assert VisionBackend("google:gemini-3.8-flash", cache_dir=Path("."), client=fake).is_local is False


@pytest.mark.asyncio
async def test_lane_dispatch(tmp_path: Path) -> None:
    google_client = FakeGoogle([_Msg(structured_output=Answer(value=1))])
    async with VisionBackend("google:gemini-3-flash", cache_dir=tmp_path, client=google_client) as backend:
        result = await backend.ask("prompt", [b"img"], Answer, stage="identify", prompt_version="v1")
    assert result == Answer(value=1)
    assert google_client.calls[0][0] == "image_understanding"
    assert google_client.calls[0][2] == [b"img"]
    assert google_client.calls[0][3]["model"] == "gemini-3-flash"

    generic_client = FakeGeneric([_Msg(structured_output=Answer(value=2))])
    async with VisionBackend("openai:gpt-5-mini", cache_dir=tmp_path, client=generic_client) as backend:
        result = await backend.ask("prompt2", [b"a", b"b", b"c"], Answer, stage="verify", prompt_version="v1")
    assert result == Answer(value=2)
    call = generic_client.calls[0]
    assert call[0] == "ask_to_image"
    assert call[2] == b"a"  # first image positional (image=)
    assert call[3]["reference_images"] == [b"b", b"c"]
    assert call[3]["model"] == "gpt-5-mini"
    assert call[3]["max_tokens"] == 8192

    single_client = FakeGeneric([_Msg(structured_output=Answer(value=3))])
    async with VisionBackend("openai:gpt-5-mini", cache_dir=tmp_path, client=single_client) as backend:
        await backend.ask("prompt3", [b"only"], Answer, stage="prices", prompt_version="v1")
    assert single_client.calls[0][3]["reference_images"] is None


@pytest.mark.asyncio
async def test_no_vision_method_is_clear_error(tmp_path: Path) -> None:
    with pytest.raises(VisionError, match="localllm-ask-to-image"):
        async with VisionBackend("llamacpp:x", cache_dir=tmp_path, client=NoVision()):
            pass


@pytest.mark.asyncio
async def test_repair_retry_then_error_not_cached(tmp_path: Path) -> None:
    client = FakeGeneric([_Msg(output="not json"), _Msg(output="still not json")])
    async with VisionBackend("openai:gpt-5-mini", cache_dir=tmp_path, client=client) as backend:
        with pytest.raises(VisionError):
            await backend.ask("prompt", [b"img"], Answer, stage="identify", prompt_version="v1")
    assert len(client.calls) == 2
    assert "rejected" in client.calls[1][1]
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.asyncio
async def test_repair_retry_succeeds_and_caches(tmp_path: Path) -> None:
    client = FakeGeneric([_Msg(output="not json"), _Msg(structured_output=Answer(value=9))])
    async with VisionBackend("openai:gpt-5-mini", cache_dir=tmp_path, client=client) as backend:
        result = await backend.ask("prompt", [b"img"], Answer, stage="identify", prompt_version="v1")
    assert result == Answer(value=9)
    assert len(client.calls) == 2

    second_client = FakeGeneric([])
    async with VisionBackend("openai:gpt-5-mini", cache_dir=tmp_path, client=second_client) as backend:
        cached_result = await backend.ask("prompt", [b"img"], Answer, stage="identify", prompt_version="v1")
    assert cached_result == Answer(value=9)
    assert second_client.calls == []


@pytest.mark.asyncio
async def test_provider_exception_is_vision_error(tmp_path: Path) -> None:
    client = FakeGeneric([RuntimeError("boom")])
    async with VisionBackend("openai:gpt-5-mini", cache_dir=tmp_path, client=client) as backend:
        with pytest.raises(VisionError):
            await backend.ask("prompt", [b"img"], Answer, stage="identify", prompt_version="v1")
    assert len(client.calls) == 1
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.asyncio
async def test_extract_accepts_instance_dict_and_json_string(tmp_path: Path) -> None:
    assert VisionBackend._extract(_Msg(structured_output=Answer(value=1)), Answer) == Answer(value=1)
    assert VisionBackend._extract(_Msg(structured_output={"value": 1}), Answer) == Answer(value=1)
    assert VisionBackend._extract(_Msg(output='```json\n{"value":1}\n```'), Answer) == Answer(value=1)


def test_vision_module_never_touches_sdk_handle() -> None:
    source = Path(vision.__file__).read_text(encoding="utf-8")
    for needle in ("chat.completions", "get_client", "_encode_image_for_openai", ".client."):
        assert needle not in source, needle
    assert not re.search(r"^\s*(?:import|from)\s+(?:openai|anthropic|google\.genai)\b", source, re.M)
