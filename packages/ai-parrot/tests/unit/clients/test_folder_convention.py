"""Folder-convention conformance tests (FEAT-523, TASK-2841).

Spec §2 'Folder convention (normative)' + §4 ``test_convention_three_files``
/ ``test_convention_class_attrs``. Every ``parrot/clients/<provider>/`` must
ship ``__init__.py``, ``client.py``, ``models.py``, and every re-exported
client class must expose ``provider_keys`` (non-empty tuple, primary key
first) and ``models`` (an ``Enum`` subclass, the provider's model
catalogue).

``CONVERTED`` is appended to by every later folder-conversion task
(TASK-2842..2845) as their providers land — do not remove entries.
"""
from __future__ import annotations

import enum
import importlib
import pathlib

import pytest

#: Providers already migrated to the `clients/<provider>/{__init__,client,
#: models}.py` convention. TASK-2841 lands "google"; later tasks append.
CONVERTED = ["google"]


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
        assert isinstance(cls.provider_keys, tuple), (
            f"{cls.__name__}.provider_keys must be a tuple, got {type(cls.provider_keys)}"
        )
        assert issubclass(cls.models, enum.Enum), (
            f"{cls.__name__}.models must be an Enum subclass"
        )


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

    protocols_path = (
        pathlib.Path(importlib.import_module("parrot.clients.protocols").__file__)
    )
    tree = ast.parse(protocols_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "live":
            pytest.fail("protocols.py still imports from .live")
