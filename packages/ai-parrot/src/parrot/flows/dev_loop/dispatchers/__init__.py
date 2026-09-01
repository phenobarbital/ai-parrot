"""Code-agent dispatchers — orchestration glue between AgentsFlow and each
supported LLM coding backend (FEAT-129/270/375).

Originally a single ``dispatcher.py`` module; split into a sub-package
(renamed ``dispatchers``) so each LLM client's dispatcher lives in its own
file: ``claude.py``, ``codex.py``, ``gemini.py``, ``google_coding.py``,
``llm.py`` (the local OpenAI-compatible base loop), ``grok.py``, ``zai.py``,
``moonshot.py``, and ``mantle.py`` (the FEAT-486 read-only counter-reviewer
over the bedrock-mantle endpoint). Shared exceptions, the ``DevLoopCodeDispatcher``
protocol, and the session-host dual-publish shim live in ``_shared.py``.

This ``__init__`` re-exports every public name that used to live on
``parrot.flows.dev_loop.dispatcher``.
"""

from __future__ import annotations

from parrot.flows.dev_loop.dispatchers._shared import (
    DevLoopCodeDispatcher,
    DispatchExecutionError,
    DispatchOutputValidationError,
)
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher
from parrot.flows.dev_loop.dispatchers.gemini import GeminiCodeDispatcher
from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher
from parrot.flows.dev_loop.dispatchers.grok import GrokCodeDispatcher
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.dispatchers.mantle import MantleAdversarialReviewDispatcher
from parrot.flows.dev_loop.dispatchers.moonshot import MoonshotCodeDispatcher
from parrot.flows.dev_loop.dispatchers.nova import (
    NovaAdversarialReviewDispatcher,
    NovaCodeDispatcher,
)
from parrot.flows.dev_loop.dispatchers.zai import ZaiCodeDispatcher

__all__ = [
    "GoogleCodingDispatcher",
    "ClaudeCodeDispatcher",
    "CodexCodeDispatcher",
    "GeminiCodeDispatcher",
    "LLMCodeDispatcher",
    "MantleAdversarialReviewDispatcher",
    "GrokCodeDispatcher",
    "MoonshotCodeDispatcher",
    "NovaAdversarialReviewDispatcher",
    "NovaCodeDispatcher",
    "ZaiCodeDispatcher",
    "DevLoopCodeDispatcher",
    "DispatchExecutionError",
    "DispatchOutputValidationError",
]
