"""AgentContextLoader and AGENT_CONTEXT_LAYER for provider-agnostic prompt caching.

FEAT-181 — Provider-Agnostic Prompt Caching (Module 3).

Provides:
- ``load_agent_context(agent_id)`` — sync function with mtime-based LRU cache.
- ``AGENT_CONTEXT_LAYER`` — CONFIGURE-phase, cacheable=True PromptLayer that
  renders per-agent context files into the system prompt prefix.

Usage pattern in AbstractBot (TASK-1220):
    1. During configure(), call ``load_agent_context(self.name)`` and put the
       result in the context dict as ``agent_context_content``.
    2. The AGENT_CONTEXT_LAYER condition skips rendering when the value is empty.
"""
from __future__ import annotations

import functools
import logging
from pathlib import Path

from .layers import PromptLayer, RenderPhase

_logger = logging.getLogger(__name__)

# Import AGENT_CONTEXT_DIR at module level so tests can patch it.
# The lazy import inside load_agent_context() is kept as a fallback comment
# but the actual lookup uses this module-level attribute.
try:
    from parrot.conf import AGENT_CONTEXT_DIR  # noqa: F401
except ImportError:
    # Fallback for test environments without full parrot.conf configured.
    import tempfile as _tempfile
    AGENT_CONTEXT_DIR = Path(_tempfile.gettempdir()) / "parrot_agent_context"


# ── Mtime-keyed LRU cache ──────────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _read_cached(path: str, mtime: float) -> str:
    """Read file content, cached by (path, mtime).

    The ``mtime`` parameter ensures the cache is invalidated whenever the file
    is updated on disk. When ``load_agent_context`` detects a changed mtime it
    calls this function with the new mtime value, which produces a distinct
    cache key and triggers a fresh read.

    Args:
        path: Absolute path to the file as a string.
        mtime: ``os.stat().st_mtime`` value at time of call.

    Returns:
        UTF-8 decoded file contents.
    """
    return Path(path).read_text(encoding="utf-8")


def load_agent_context(agent_id: str) -> str:
    """Load the per-agent context file for the given agent ID.

    Reads ``<AGENT_CONTEXT_DIR>/<agent_id>.md`` and returns its content as a
    string. Results are cached by ``(path, st_mtime)`` so file changes are
    detected on the next call without restarting the process.

    Missing files return an empty string (no error raised). This allows
    agents without a dedicated context file to work silently.

    Args:
        agent_id: The agent's unique identifier (used as the filename stem).

    Returns:
        File content as a string, or ``""`` if the file does not exist.
    """
    import parrot.bots.prompts.agent_context as _self_module
    context_dir = getattr(_self_module, "AGENT_CONTEXT_DIR", AGENT_CONTEXT_DIR)
    file_path = Path(context_dir) / f"{agent_id}.md"
    if not file_path.exists():
        return ""
    mtime = file_path.stat().st_mtime
    return _read_cached(str(file_path), mtime)


# ── Built-in AGENT_CONTEXT_LAYER ──────────────────────────────────────────

AGENT_CONTEXT_LAYER = PromptLayer(
    name="agent_context",
    # Priority 12 — between IDENTITY (10) and PRE_INSTRUCTIONS (15).
    # Ensures agent context immediately follows identity in the cacheable prefix.
    priority=12,
    phase=RenderPhase.CONFIGURE,
    cacheable=True,
    template="""<agent_context>
$agent_context_content
</agent_context>""",
    condition=lambda ctx: bool(ctx.get("agent_context_content", "").strip()),
)
