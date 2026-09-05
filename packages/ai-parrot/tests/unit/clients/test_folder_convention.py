"""Folder-convention conformance tests (FEAT-523, TASK-2841; provider
discovery rewritten by TASK-2855).

Spec §2 'Folder convention (normative)' + §4 ``test_convention_three_files``
/ ``test_convention_class_attrs``. Every ``parrot/clients/<provider>/`` must
ship ``__init__.py``, ``client.py``, ``models.py``, and every re-exported
client class must expose ``provider_keys`` (non-empty tuple, primary key
first) and ``models`` (an ``Enum`` subclass, the provider's model
catalogue).

``CONVERTED`` is no longer a hard-coded list (TASK-2855) — it is derived
from ``LLMFactory``'s own real discovery: every distinct
``parrot.clients.<folder>`` package that backs at least one currently
registered ``SUPPORTED_CLIENTS`` entry. A provider key (e.g.
``"codex-agent"``, ``"gemini-live"``) does not always match its folder
name 1:1, so the folder is derived from each resolved class's own
``__module__`` (``parrot.clients.<folder>.<submodule>``) rather than from
the key string itself. Requires satellites to be installed to discover
anything — with zero installed, this file collects zero parametrize
cases (not a failure; see ``test_core_independence.py`` for the
"core imports with none installed" guarantee this file does not need to
provide).
"""

from __future__ import annotations

import enum
import importlib
import pathlib

import pytest

from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS


def _discover_provider_folders() -> list[str]:
    """Every distinct ``parrot.clients.<folder>`` backing a registered key.

    Resolves each ``SUPPORTED_CLIENTS`` value (a real class, or an entry
    point's zero-arg loader) the same way ``LLMFactory.create()`` does,
    then reads the folder name off ``cls.__module__`` — this is the only
    reliable link back to a folder, since factory *keys* (aliases like
    ``"codex-agent"``/``"gemini-live"``) don't always match the folder
    they live in.
    """
    LLMFactory._discover()
    folders: set[str] = set()
    for entry in SUPPORTED_CLIENTS.values():
        cls = entry() if callable(entry) and not isinstance(entry, type) else entry
        parts = cls.__module__.split(".")
        if len(parts) >= 3 and parts[0] == "parrot" and parts[1] == "clients":
            folders.add(parts[2])
    return sorted(folders)


CONVERTED = _discover_provider_folders()


@pytest.mark.parametrize("provider", CONVERTED)
def test_three_canonical_files(provider: str) -> None:
    """Every converted provider folder has the three canonical files."""
    pkg = importlib.import_module(f"parrot.clients.{provider}")
    d = pathlib.Path(pkg.__file__).parent
    for filename in ("__init__.py", "client.py", "models.py"):
        assert (d / filename).exists(), f"{provider}/{filename} is missing"


@pytest.mark.parametrize("provider", CONVERTED)
def test_client_class_attrs(provider: str) -> None:
    """Every re-exported client class has provider_keys + models."""
    pkg = importlib.import_module(f"parrot.clients.{provider}")
    clients = [getattr(pkg, n) for n in pkg.__all__ if n.endswith("Client")]
    assert clients, f"no *Client classes re-exported from parrot.clients.{provider}"
    for cls in clients:
        assert cls.provider_keys, f"{cls.__name__}.provider_keys is empty"
        assert isinstance(
            cls.provider_keys, tuple
        ), f"{cls.__name__}.provider_keys must be a tuple, got {type(cls.provider_keys)}"
        assert issubclass(cls.models, enum.Enum), f"{cls.__name__}.models must be an Enum subclass"


def test_google_media_models_intact() -> None:
    """Media/voice/video-reel models stay in parrot.models.google (spec Non-Goals)."""
    from parrot.models.google import (  # noqa: F401
        TTSVoice,
        MusicGenre,
        VideoReelRequest,
        VoiceRegistry,
    )


def test_google_model_left_parrot_models() -> None:
    """GoogleModel/VertexAIModel are no longer importable from parrot.models.google."""
    with pytest.raises(ImportError):
        from parrot.models.google import GoogleModel  # noqa: F401

    with pytest.raises(ImportError):
        from parrot.models.google import VertexAIModel  # noqa: F401


def test_google_model_importable_from_clients() -> None:
    """GoogleModel/VertexAIModel now live under parrot.clients.google."""
    from parrot.clients.google import GoogleModel, VertexAIModel

    assert issubclass(GoogleModel, enum.Enum)
    assert issubclass(VertexAIModel, enum.Enum)


def test_live_voice_response_moved_to_models_voice() -> None:
    """LiveVoiceResponse (+ its dataclass deps) relocated to parrot.models.voice."""
    from parrot.models.voice import (  # noqa: F401
        LiveCompletionUsage,
        LiveToolCall,
        LiveVoiceResponse,
        VoiceTurnMetadata,
    )


def test_protocols_does_not_import_live() -> None:
    """parrot.clients.protocols no longer imports the .live submodule."""
    import ast

    protocols_path = pathlib.Path(importlib.import_module("parrot.clients.protocols").__file__)
    tree = ast.parse(protocols_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "live":
            pytest.fail("protocols.py still imports from .live")
