"""Safe, non-invasive detection of a usable coding-agent CLI LLM.

Never imports a provider SDK, never spawns a subprocess, never makes a
network call — only entry-point discovery (``LLMFactory.list_providers()``)
and ``shutil.which()`` on the CLI binary.
"""

from __future__ import annotations

import shutil
from typing import Optional

from parrot.clients.factory import LLMFactory

_CLAUDE_CODE_SPEC = "claude-code:claude-haiku-4-5-20251001"
_CODEX_CODE_SPEC = "codex-code:gpt-5.1-codex"


def detect_coding_agent_llm() -> Optional[str]:
    """Detect an available coding-agent CLI and return its default LLMFactory spec.

    Checks Claude Code first, then Codex. Never imports a provider SDK and
    never spawns a subprocess — only entry-point discovery
    (``LLMFactory.list_providers()``) and ``shutil.which`` on the CLI binary.

    Returns:
        ``"claude-code:claude-haiku-4-5-20251001"`` if a Claude Code CLI
        session looks usable; ``"codex-code:gpt-5.1-codex"`` if only Codex
        does; ``None`` if neither is detected.
    """
    providers = LLMFactory.list_providers()
    if "claude-code" in providers and shutil.which("claude"):
        return _CLAUDE_CODE_SPEC
    if "codex-code" in providers and shutil.which("codex"):
        return _CODEX_CODE_SPEC
    return None
