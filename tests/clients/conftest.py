"""Shared pytest fixtures for ``tests/clients``.

Provides the ``fake_claude_agent_messages`` fixture used by
``test_claude_agent.py`` to mimic the message stream that
:py:func:`claude_agent_sdk.query` would produce.

This conftest also installs lightweight stubs for ``navigator.utils.file``
when the locally-installed ``navigator`` predates the FEAT-123
file-interface migration. Without these, ``parrot.clients.factory``
fails to import (it transitively pulls in ``parrot.interfaces.file``,
which expects ``FileManagerInterface`` and ``LocalFileManager`` from
upstream). The stubs are no-ops once the proper navigator version is
installed.
"""
from __future__ import annotations

import sys
import types
from typing import Any, List

import pytest


def _install_navigator_file_stubs() -> None:
    """Install the FEAT-123 names on ``navigator.utils.file`` if missing.

    The installed ``navigator`` package in some environments lacks the
    file-interface shim names (``FileManagerInterface``, ``FileMetadata``,
    ``LocalFileManager``, ``TempFileManager``, ``FileManagerFactory``).
    ``parrot.interfaces.file`` and ``parrot.tools.filemanager`` import
    them eagerly, which transitively breaks
    ``parrot.clients.factory`` import in this venv.

    We patch ``navigator.utils.file`` to expose any missing names as
    minimal stand-ins so the test suite can exercise the FEAT-124
    factory-registration plumbing in environments that haven't upgraded
    ``navigator`` yet. The stubs are no-ops once the proper navigator
    version is installed.
    """
    try:
        import navigator.utils.file as upstream
    except Exception:  # pragma: no cover
        return

    # Names eagerly imported by parrot.interfaces.file / parrot.tools.filemanager.
    _expected = (
        "FileManagerInterface",
        "FileMetadata",
        "LocalFileManager",
        "TempFileManager",
        "FileManagerFactory",
    )
    base = type("FileManagerInterface", (), {}) if not hasattr(
        upstream, "FileManagerInterface"
    ) else getattr(upstream, "FileManagerInterface")
    if not hasattr(upstream, "FileManagerInterface"):
        upstream.FileManagerInterface = base  # type: ignore[attr-defined]
    for name in _expected:
        if hasattr(upstream, name):
            continue
        # Build a minimal placeholder. ``FileManagerFactory`` is typically a
        # callable returning a manager; we model it as a class instance with
        # a permissive constructor.
        if name == "FileMetadata":
            stub = type(name, (), {})
        elif name == "FileManagerFactory":
            class _Factory:
                """Placeholder for navigator.utils.file.FileManagerFactory."""

                def __init__(self, *_, **__):
                    pass

                def __call__(self, *_, **__):
                    return None

            stub = _Factory
        else:
            stub = type(name, (base,), {})
        setattr(upstream, name, stub)

    # Submodule stand-ins for ``navigator.utils.file.local`` etc.
    if "navigator.utils.file.local" not in sys.modules:
        local_mod = types.ModuleType("navigator.utils.file.local")
        local_mod.LocalFileManager = upstream.LocalFileManager  # type: ignore[attr-defined]
        sys.modules.setdefault("navigator.utils.file.local", local_mod)


_install_navigator_file_stubs()


@pytest.fixture
def fake_claude_agent_messages() -> List[Any]:
    """Build a fake ``claude_agent_sdk.query()`` message stream.

    The stream contains:
      * Two ``AssistantMessage``s carrying ``TextBlock`` content that
        concatenates to ``"hello world"``.
      * A terminal ``ResultMessage`` reporting one successful turn at a
        cost of ``$0.001``.

    When the optional ``[claude-agent]`` extra is installed (the dev venv
    case), the fixture builds real SDK dataclasses. Otherwise it falls
    back to ``types.SimpleNamespace`` stand-ins whose class names match
    so that the duck-typed branches in
    :py:meth:`AIMessageFactory.from_claude_agent` and
    :py:meth:`ClaudeAgentClient.ask_stream` recognise them.
    """
    try:
        from claude_agent_sdk.types import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
        )
        return [
            AssistantMessage(
                content=[TextBlock(text="hello ")],
                model="claude-sonnet-4-6",
            ),
            AssistantMessage(
                content=[TextBlock(text="world")],
                model="claude-sonnet-4-6",
            ),
            ResultMessage(
                subtype="success",
                duration_ms=1000,
                duration_api_ms=800,
                is_error=False,
                num_turns=1,
                session_id="sess-fake-1",
                total_cost_usd=0.001,
                usage={"input_tokens": 10, "output_tokens": 5},
            ),
        ]
    except Exception:  # pragma: no cover
        # SDK is not installed — fall back to namespaces with the right names.
        from types import SimpleNamespace

        def _named(cls_name: str, **fields: Any):
            ns = SimpleNamespace(**fields)
            ns.__class__ = type(cls_name, (), {})
            return ns

        return [
            _named(
                "AssistantMessage",
                content=[_named("TextBlock", text="hello ")],
                model="claude-sonnet-4-6",
                usage=None,
                stop_reason=None,
                session_id=None,
            ),
            _named(
                "AssistantMessage",
                content=[_named("TextBlock", text="world")],
                model="claude-sonnet-4-6",
                usage=None,
                stop_reason=None,
                session_id=None,
            ),
            _named(
                "ResultMessage",
                subtype="success",
                duration_ms=1000,
                duration_api_ms=800,
                is_error=False,
                num_turns=1,
                session_id="sess-fake-1",
                stop_reason=None,
                total_cost_usd=0.001,
                usage={"input_tokens": 10, "output_tokens": 5},
                result=None,
                structured_output=None,
                model_usage=None,
            ),
        ]
