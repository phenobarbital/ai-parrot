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
from typing import Union

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

@functools.lru_cache(maxsize=256)
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


def read_text_cached(path: Union[str, Path]) -> str:
    """Public mtime-keyed cached text read (FEAT-321).

    Thin wrapper that stats ``path`` and delegates to the shared
    :func:`_read_cached` LRU cache, so callers outside this module (e.g. the
    identity loader) reuse the same cache instead of maintaining their own.

    Args:
        path: Path to the file to read.

    Returns:
        UTF-8 decoded file contents, or ``""`` when the file does not exist
        or cannot be statted.
    """
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return ""
    return _read_cached(str(p), mtime)


def load_agent_context(agent_id: str) -> str:
    """Load the per-agent context file for the given agent ID.

    Reads ``<AGENT_CONTEXT_DIR>/<agent_id>.md`` and returns its content as a
    string. Results are cached by ``(path, st_mtime)`` so file changes are
    detected on the next call without restarting the process.

    Missing files return an empty string (no error raised). This allows
    agents without a dedicated context file to work silently.

    The agent context directory is created lazily on first call to avoid
    side effects at import time (read-only container filesystems, tests).

    Args:
        agent_id: The agent's unique identifier (used as the filename stem).

    Returns:
        File content as a string, or ``""`` if the file does not exist.
    """
    context_dir = Path(AGENT_CONTEXT_DIR)
    # Lazy directory creation: only attempt when the directory is absent.
    if not context_dir.exists():
        try:
            context_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _logger.debug(
                "Could not create agent context directory %s: %s",
                context_dir,
                exc,
            )
    file_path = context_dir / f"{agent_id}.md"
    if not file_path.exists():
        return ""
    return read_text_cached(file_path)


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
