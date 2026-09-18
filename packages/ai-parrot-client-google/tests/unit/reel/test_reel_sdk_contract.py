"""TASK-3335: public google-genai SDK surface compatibility checks.

Verifies, by direct introspection of the INSTALLED SDK (never a real
network call — construction of a ``genai.Client`` is lazy and makes no
request; every assertion here is `hasattr`/`inspect.signature` on the
already-imported SDK), that every async surface this reel feature depends
on is actually present with a call shape matching how the reel adapters
invoke it:

- ``aio.models.generate_videos`` (``reel/veo.py``)
- ``aio.operations.get`` (``reel/veo.py``, LRO polling)
- ``aio.files.download`` (``reel/veo.py``, clip download)
- ``aio.interactions.create`` (``reel/omni.py``)
- ``aio.live.music.connect`` (``reel/music.py``, Lyria)
- ``aio.aclose`` (every adapter's owned-client cleanup — TASK-3324/3326/3327/3331)

This is the evidence backing ``packages/ai-parrot-client-google/pyproject.toml``'s
``google-genai>=2.23.0`` floor (TASK-3335) — the lowest version these
surfaces were actually verified against, not a guess. A future SDK release
that renames/removes any of them should fail THIS file first, not silently
surface as a runtime ``AttributeError`` deep in a reel adapter.
"""

from __future__ import annotations

import inspect

import pytest
from google import genai


class TestInstalledSdkFloor:
    """The installed SDK meets the declared >=2.23.0 floor."""

    def test_installed_version_meets_declared_floor(self):
        from packaging.version import Version

        installed = Version(genai.__version__)
        assert installed >= Version("2.23.0"), (
            f"Installed google-genai {genai.__version__} is below the declared "
            "floor (>=2.23.0, packages/ai-parrot-client-google/pyproject.toml). "
            "This feature's async reel surfaces were only verified at 2.23.0+."
        )


@pytest.fixture
def async_client():
    """A lazily-constructed AsyncClient — never makes a network call."""
    client = genai.Client(api_key="fake-key-for-introspection-only")
    return client.aio


class TestVeoSubmitPollDownloadSurface:
    """Public async submit/poll/download contract used by reel/veo.py."""

    def test_generate_videos_accepts_model_prompt_image_config_kwargs(self, async_client):
        sig = inspect.signature(async_client.models.generate_videos)
        for param in ("model", "prompt", "image", "config"):
            assert param in sig.parameters, f"aio.models.generate_videos lost the '{param}' parameter"

    def test_operations_get_accepts_an_operation_argument(self, async_client):
        sig = inspect.signature(async_client.operations.get)
        assert "operation" in sig.parameters

    def test_files_download_accepts_file_and_destination_kwargs(self, async_client):
        sig = inspect.signature(async_client.files.download)
        assert "file" in sig.parameters
        assert "destination" in sig.parameters


class TestOmniInteractionsSurface:
    """Public async Interactions contract used by reel/omni.py."""

    def test_interactions_create_is_present_and_callable(self, async_client):
        assert hasattr(async_client, "interactions")
        assert callable(getattr(async_client.interactions, "create", None))


class TestLyriaLiveMusicSurface:
    """Public async live music contract used by reel/music.py."""

    def test_live_music_connect_is_present_and_callable(self, async_client):
        assert hasattr(async_client, "live")
        assert hasattr(async_client.live, "music")
        assert callable(getattr(async_client.live.music, "connect", None))

    def test_live_music_connect_accepts_a_model_kwarg(self, async_client):
        sig = inspect.signature(async_client.live.music.connect)
        assert "model" in sig.parameters


class TestOwnedClientCloseSurface:
    """Every reel adapter closes its owned client via aio.aclose() — TASK-3324/3326/3327/3331."""

    def test_aclose_is_present_and_callable(self, async_client):
        assert callable(getattr(async_client, "aclose", None))


class TestLazyProviderImport:
    """FEAT-523 (TASK-2846): core must not import a provider module at module scope.

    Verifies the reel-facing entry points (the server handler and the
    generation mixin) do not themselves require `google.genai` to be
    importable at MODULE level — the actual provider import happens lazily,
    inside the functions that need it, so the rest of the package stays
    usable even when google-genai (or its transitive Vertex/GCS deps) is
    not installed in a given deployment.
    """

    def test_video_reel_handler_module_has_no_module_level_google_genai_import(self):
        import ast
        from pathlib import Path

        import parrot.handlers.video_reel as video_reel_module

        source = Path(video_reel_module.__file__).read_text()
        tree = ast.parse(source)
        module_level_imports = [
            node for node in ast.iter_child_nodes(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        for node in module_level_imports:
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                assert not name.startswith("google.genai"), (
                    f"video_reel.py imports {name!r} at module scope — provider SDK "
                    "imports must be lazy (inside functions), per FEAT-523 TASK-2846 AC-3."
                )

    def test_generate_video_reel_lazily_imports_google_client(self):
        """`generate_video_reel`'s own callers (the handler's `run_logic`) import
        `GoogleGenAIClient` lazily, function-local — verified directly against
        the handler source (mirrors the existing "FEAT-523 (TASK-2846): lazy
        import" comment at the call site).
        """
        import ast
        from pathlib import Path

        import parrot.handlers.video_reel as video_reel_module

        source = Path(video_reel_module.__file__).read_text()
        assert "from parrot.clients.google import GoogleGenAIClient" in source
        # The import line itself must NOT be at column 0 (module level) —
        # it must be indented (function-local).
        for line in source.splitlines():
            if "from parrot.clients.google import GoogleGenAIClient" in line:
                assert line.startswith((" ", "\t")), (
                    "GoogleGenAIClient import in video_reel.py is at module scope, "
                    "not function-local — violates FEAT-523 TASK-2846 AC-3."
                )
