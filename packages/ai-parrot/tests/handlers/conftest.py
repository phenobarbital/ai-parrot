"""Conftest for handler tests.

Registers new parrot subpackages and modules created in this worktree so
they are importable alongside the editable install (which contains compiled
Cython extensions).

Two bootstrap steps are performed before handler modules are loaded:

1. **aiohttp-aware BaseView stub** — The top-level ``tests/conftest.py``
   installs a plain ``navigator.views.BaseView`` stub that inherits only from
   ``object``, so ``issubclass(InfographicTalk, AbstractView)`` returns False
   and aiohttp's router falls back to ``handler_wrapper``.  We replace that
   stub with a minimal ``BaseView`` that inherits from ``aiohttp.web.View`` and
   provides the ``json_response`` / ``error`` / ``query_parameters`` helpers
   that handler code relies on.

2. **No-op auth decorators** — ``is_authenticated`` and ``user_session`` are
   replaced with pass-through factories while ``parrot.handlers.infographic``
   is loaded so that ``InfographicTalk.post`` / ``.get`` are plain undecorated
   coroutines.  The test fixture subclass then only needs to override the
   PBAC / agent / session helpers.
"""
from __future__ import annotations

import importlib.util
import json as _json
import sys
from pathlib import Path
from typing import Dict, List

from aiohttp import web
from aiohttp.web_urldispatcher import View as _AioView

_WORKTREE_SRC = Path(__file__).resolve().parents[2] / "src"


def _register_module(dotted_name: str, file_path: Path) -> None:
    """Register a module from file_path under dotted_name in sys.modules."""
    if dotted_name in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(dotted_name, file_path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = module
    spec.loader.exec_module(module)


def _register_package(dotted_name: str, pkg_dir: Path) -> None:
    """Register a package from pkg_dir under dotted_name in sys.modules."""
    if dotted_name in sys.modules:
        return
    init = pkg_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        dotted_name,
        init,
        submodule_search_locations=[str(pkg_dir)],
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    module.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
    module.__package__ = dotted_name
    sys.modules[dotted_name] = module
    spec.loader.exec_module(module)


# ---------------------------------------------------------------------------
# Step 1: Replace navigator.views stub with an aiohttp-aware version
#
# The top-level tests/conftest.py uses sys.modules.setdefault to install a
# plain BaseView (no aiohttp ancestry).  We upgrade it here so that
# AgentTalk → BaseView → aiohttp.web.View → AbstractView.
# We only patch if the current BaseView does NOT already inherit from
# aiohttp's AbstractView.
# ---------------------------------------------------------------------------

from aiohttp.abc import AbstractView as _AbstractView  # noqa: E402


class _TestBaseView(_AioView):
    """Minimal BaseView for handler tests.

    Inherits from aiohttp.web.View so aiohttp's router treats handler
    subclasses as proper AbstractView instances (not function wrappers).
    Provides the helper methods that InfographicTalk / AgentTalk call.
    """

    def post_init(self, *args, **kwargs) -> None:  # noqa: D401
        pass  # overridden by concrete handlers to set up loggers

    def json_response(
        self,
        data: object,
        *,
        status: int = 200,
        **kwargs,
    ) -> web.Response:
        """Return a JSON web.Response."""
        return web.Response(
            text=_json.dumps(data, default=str),
            content_type="application/json",
            status=status,
        )

    def error(
        self,
        message: str,
        *,
        status: int = 400,
        **kwargs,
    ) -> web.Response:
        """Return a JSON error web.Response."""
        return web.Response(
            text=_json.dumps({"error": message}),
            content_type="application/json",
            status=status,
        )

    @staticmethod
    def query_parameters(request: web.Request) -> Dict[str, str]:
        """Return query string parameters as a plain dict."""
        return dict(request.rel_url.query)


def _patch_navigator_views_stub() -> None:
    """Replace stub BaseView with the aiohttp-aware version."""
    _nav_views = sys.modules.get("navigator.views")
    if _nav_views is None:
        return
    _base = getattr(_nav_views, "BaseView", None)
    if _base is not None and issubclass(_base, _AbstractView):
        return  # already aiohttp-aware, nothing to do
    _nav_views.BaseView = _TestBaseView
    # Also patch navigator.views.base if present
    _nav_views_base = sys.modules.get("navigator.views.base")
    if _nav_views_base is not None:
        _nav_views_base.BaseView = _TestBaseView


_patch_navigator_views_stub()

# ---------------------------------------------------------------------------
# Step 2: Bootstrap parrot and helpers
# ---------------------------------------------------------------------------

# Ensure parrot is loaded from the editable install first.
import parrot  # noqa: E402

# Patch ThemeRegistry to add list_themes_detailed
from parrot.models.infographic import ThemeRegistry  # noqa: E402

if not hasattr(ThemeRegistry, "list_themes_detailed"):
    def list_themes_detailed(self) -> List[Dict[str, str]]:
        """Return theme summaries with key colour tokens."""
        return [
            {
                "name": t.name,
                "primary": t.primary,
                "neutral_bg": t.neutral_bg,
                "body_bg": t.body_bg,
            }
            for t in sorted(self._themes.values(), key=lambda x: x.name)
        ]

    ThemeRegistry.list_themes_detailed = list_themes_detailed  # type: ignore[attr-defined]

# Register parrot.helpers package from worktree src
_helpers_dir = _WORKTREE_SRC / "parrot" / "helpers"
_register_package("parrot.helpers", _helpers_dir)
_register_module("parrot.helpers.infographics", _helpers_dir / "infographics.py")
if not hasattr(parrot, "helpers"):
    parrot.helpers = sys.modules["parrot.helpers"]  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Step 3: Load parrot.handlers.infographic with no-op auth decorators
# ---------------------------------------------------------------------------

def _noop_auth_factory(*_args: object, **_kwargs: object):  # type: ignore[return]
    """Return a pass-through decorator (replaces is_authenticated/user_session)."""
    def _passthrough(handler):  # type: ignore[return]
        return handler
    return _passthrough


import navigator_auth.decorators as _auth_dec  # noqa: E402

_orig_is_authenticated = _auth_dec.is_authenticated
_orig_user_session = _auth_dec.user_session

_auth_dec.is_authenticated = _noop_auth_factory  # type: ignore[attr-defined]
_auth_dec.user_session = _noop_auth_factory  # type: ignore[attr-defined]

try:
    _handlers_dir = _WORKTREE_SRC / "parrot" / "handlers"
    _register_module(
        "parrot.handlers.infographic",
        _handlers_dir / "infographic.py",
    )
finally:
    # Always restore original decorators so other tests/modules are unaffected.
    _auth_dec.is_authenticated = _orig_is_authenticated  # type: ignore[attr-defined]
    _auth_dec.user_session = _orig_user_session  # type: ignore[attr-defined]
