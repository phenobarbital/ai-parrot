"""Prerequisite and tokenizer guarantees for BotManager E2E scenarios."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from parrot.e2e.errors import E2EPrerequisiteError, EXIT_BLOCKED
from parrot.e2e.models import TargetConfig
from parrot.e2e.targets.botmanager import build_botmanager_adapter
from parrot.skills import parsers


async def test_missing_redis_blocks_authenticated_target_before_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Require a private Redis binary instead of contacting an operator service."""
    monkeypatch.setattr("parrot.e2e.targets.redis.shutil.which", lambda _name: None)
    adapter = build_botmanager_adapter()

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(TargetConfig(kind="botmanager"), run_id="blocked-auth", worktree=tmp_path)

    assert excinfo.value.reason_code == "redis_server_missing"
    assert excinfo.value.exit_code == EXIT_BLOCKED
    assert not (tmp_path / "sdd" / "state" / "e2e").exists()


def test_tokenizer_stays_lazy_at_import_then_caches_first_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Separate import safety from later first-tokenization cache behavior."""
    original_encoding = parsers._ENCODING
    calls: list[str] = []

    class _Encoding:
        def encode(self, text: str) -> list[str]:
            return list(text)

    def _get_encoding(name: str) -> _Encoding:
        calls.append(name)
        return _Encoding()

    monkeypatch.setattr(parsers.tiktoken, "get_encoding", _get_encoding)
    try:
        module = importlib.reload(parsers)
        assert calls == []
        assert module._count_tokens("offline") == 7
        assert module._count_tokens("ok") == 2
        assert calls == ["cl100k_base"]
    finally:
        parsers._ENCODING = original_encoding
