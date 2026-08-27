"""Embedded Admin UI serving.

Mounts the compiled Admin UI single-page application (Svelte 5 + Vite)
under ``/admin`` when the ``dist/`` build output is present in the
installed package. Gracefully degrades (registers nothing, logs a single
warning) when the UI was not built — e.g. an install-from-git without
running the Node build pipeline.

Library-owned: :func:`setup_admin_ui` is called from
``BotManager.setup()`` (see ``parrot.manager.manager``), following the
same ``setup_*_routes(app)`` pattern as
``parrot.handlers.credentials.setup_credentials_routes``.
"""
from __future__ import annotations

from pathlib import Path

from aiohttp import web
from navconfig.logging import logging

from .status import AdminStatusHandler

try:
    from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY
except ImportError:  # pragma: no cover - navigator_auth is a core dependency
    AUTH_EXCLUDE_LIST_KEY = None

logger = logging.getLogger(__name__)

#: URL prefix the Admin UI is served under.
DEFAULT_PREFIX = "/admin"

# Only warn once per process, even if setup_admin_ui() is called more than
# once (e.g. tests instantiating multiple BotManagers).
_warned_missing_dist = False


def _dist_dir() -> Path:
    """Resolve the compiled Admin UI ``dist/`` directory.

    Package-relative resolution (mirrors the Telegram static-mount
    precedent in the repo-root ``app.py``): the built assets live next to
    this module inside the installed wheel. Kept as a standalone function
    (not inlined) so tests can monkeypatch it.

    Returns:
        Path to ``parrot/server/ui/dist`` (may not exist).
    """
    return Path(__file__).parent / "dist"


def _register_auth_exclusion(app: web.Application, pattern: str) -> None:
    """Best-effort registration of ``pattern`` in navigator-auth's exclude list.

    Safe when navigator-auth's ``AuthHandler`` was never installed on
    ``app`` (no ``AUTH_EXCLUDE_LIST_KEY`` entry) — degrades to a debug log
    instead of raising, matching the precedent in
    ``parrot.handlers.web_hitl``.

    Deliberately NOT called eagerly from :func:`setup_admin_ui` — see the
    ``on_startup`` registration below for why.

    Args:
        app: The aiohttp application.
        pattern: fnmatch-style URL pattern to exclude from auth enforcement.
    """
    if AUTH_EXCLUDE_LIST_KEY is None:
        logger.debug(
            "navigator_auth not available: skipping exclude-list "
            "registration for %s",
            pattern,
        )
        return
    exclude_list = app.get(AUTH_EXCLUDE_LIST_KEY)
    if exclude_list is None:
        logger.debug(
            "AuthHandler not installed on this app (no %s key): skipping "
            "exclude-list registration for %s",
            AUTH_EXCLUDE_LIST_KEY,
            pattern,
        )
        return
    if pattern not in exclude_list:
        exclude_list.append(pattern)


async def _register_auth_exclusions_on_startup(app: web.Application, prefix: str) -> None:
    """``on_startup`` callback: register the exclude-list patterns for ``prefix``.

    Both real entrypoints (``app.py``/``appauto.py``) call
    ``BotManager.setup(app)`` — which calls :func:`setup_admin_ui` — BEFORE
    ``AuthHandler().setup(app)`` runs. ``AuthHandler.setup()`` itself
    unconditionally OVERWRITES ``app[AUTH_EXCLUDE_LIST_KEY]`` with a fresh
    list (``navigator_auth/auth.py``: ``self.app[AUTH_EXCLUDE_LIST_KEY] =
    list(exclude_list)``), so registering the pattern eagerly — at
    ``setup_admin_ui()`` call time — is either a no-op (key not set yet) or
    would be silently discarded by that later overwrite either way. Every
    ``on_startup`` callback runs only once ``web.Application`` actually
    starts serving (after ALL synchronous ``.setup()`` calls in
    ``__init__``/``configure`` have completed), so by the time this fires
    ``AuthHandler.setup()`` is guaranteed to have already run and
    ``app[AUTH_EXCLUDE_LIST_KEY]`` already holds AuthHandler's real list —
    appending to it here mutates that same list object in place, which the
    ABAC middleware reads live on every request.
    """
    _register_auth_exclusion(app, prefix)
    _register_auth_exclusion(app, f"{prefix}/*")


#: Long-cache/immutable header for hashed Vite assets — the filename hash
#: guarantees a new build gets a new URL, so browsers can cache "forever".
_ASSETS_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _index_response(index_html: Path) -> web.FileResponse:
    """Build the SPA index response with no-cache headers.

    Args:
        index_html: Path to the built ``index.html``.

    Returns:
        A :class:`web.FileResponse` serving ``index_html`` with
        ``Cache-Control: no-cache`` so browsers always revalidate the
        SPA shell (the shell references hashed, long-cached assets).
    """
    response = web.FileResponse(index_html)
    response.headers["Cache-Control"] = "no-cache"
    return response


def _make_assets_cache_header(assets_prefix: str):
    """Build an ``on_response_prepare`` hook that long-caches hashed assets.

    ``router.add_static()`` (aiohttp's ``FileResponse``/``StaticResource``
    machinery) never sets ``Cache-Control`` itself, so the header is
    injected via the ``on_response_prepare`` signal — the standard aiohttp
    hook for tagging responses by path without wrapping the whole app in a
    middleware.

    Args:
        assets_prefix: Path prefix (e.g. ``/admin/assets/``) whose
            responses should get the long-cache/immutable header.

    Returns:
        An ``async def(request, response)`` coroutine suitable for
        ``app.on_response_prepare.append(...)``.
    """

    async def _on_prepare(request: web.Request, response: web.StreamResponse) -> None:
        if request.path.startswith(assets_prefix):
            response.headers["Cache-Control"] = _ASSETS_CACHE_CONTROL

    return _on_prepare


def setup_admin_ui(app: web.Application, *, prefix: str = DEFAULT_PREFIX) -> bool:
    """Mount the embedded Admin UI if the compiled ``dist/`` is present.

    Registers:
      - A static mount for hashed assets at ``{prefix}/assets/`` with a
        long-cache/immutable ``Cache-Control`` header injected via
        ``on_response_prepare``.
      - ``GET {prefix}`` (exact) and ``GET {prefix}/{{tail:.*}}`` (path
        children) returning ``index.html`` (SPA history-mode router
        fallback) so deep links survive a hard refresh. Anchored on a
        path *segment* boundary (trailing ``/``) rather than a bare
        string prefix, so a future route like ``/administer`` is never
        accidentally swallowed by this catch-all.
      - ``{prefix}`` and ``{prefix}/*`` in navigator-auth's exclude list
        (segment-boundary fnmatch patterns — ``fnmatch`` has no notion of
        ``/`` as special, so a bare ``{prefix}*`` would also exclude an
        unrelated ``/administer`` from auth), so the HTML shell is
        reachable pre-login (auth enforcement lives entirely in the JSON
        API, not in the SPA shell route). Registered via an ``on_startup``
        callback rather than eagerly — see
        :func:`_register_auth_exclusions_on_startup` for why (both real
        entrypoints call this function before ``AuthHandler().setup(app)``
        has run).

    Args:
        app: The aiohttp :class:`web.Application` to mount routes on.
        prefix: URL prefix the UI is served under. Defaults to ``/admin``.

    Returns:
        ``True`` when the SPA routes were registered, ``False`` when
        ``dist/`` is absent (a single WARNING is logged; the SPA mount is
        skipped but the JSON API below is registered either way — it is
        UI-agnostic).
    """
    global _warned_missing_dist

    # JSON API: registers unconditionally, independent of dist/ — the
    # status endpoint is UI-agnostic and useful even on an install-from-git
    # that never ran the Node build.
    app.router.add_view("/api/v1/admin/status", AdminStatusHandler)

    dist = _dist_dir()
    index_html = dist / "index.html"
    if not index_html.exists():
        if not _warned_missing_dist:
            logger.warning(
                "Admin UI dist/ not found at %s: the compiled UI was not "
                "built (install-from-git without the Node build step, or "
                "a UI-less wheel). Registering no %s routes; the JSON API "
                "is unaffected.",
                dist,
                prefix,
            )
            _warned_missing_dist = True
        return False

    router = app.router

    # Hashed static assets. Cache-Control is injected via
    # on_response_prepare since add_static()/FileResponse never set it.
    assets_dir = dist / "assets"
    assets_prefix = f"{prefix}/assets/"
    if assets_dir.is_dir():
        router.add_static(
            assets_prefix,
            path=assets_dir,
            name="admin_ui_assets",
            show_index=False,
            follow_symlinks=False,
        )
        app.on_response_prepare.append(_make_assets_cache_header(assets_prefix))

    async def _spa_fallback(request: web.Request) -> web.StreamResponse:
        return _index_response(index_html)

    # SPA fallback, segment-boundary anchored (exact prefix + "prefix/…")
    # so it never shadows /api/* routes registered elsewhere on the app,
    # nor any future non-SPA route whose path merely starts with the same
    # characters (e.g. /administer).
    router.add_get(prefix, _spa_fallback, name="admin_ui_index_root")
    router.add_get(f"{prefix}/{{tail:.*}}", _spa_fallback, name="admin_ui_index")

    # Deferred to on_startup — see _register_auth_exclusions_on_startup's
    # docstring for why eager registration here would race AuthHandler.setup().
    app.on_startup.append(
        lambda app: _register_auth_exclusions_on_startup(app, prefix)
    )

    return True
