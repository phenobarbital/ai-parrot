"""Embedded web UI serving.

Mounts the compiled single-page application (Svelte 5 + Vite) when the
``dist/`` build output is present in the installed package: end-user pages
(``/login``, ``/agents``, ``/agents/<name>/chat``) at the site root and the
administration pages under ``/admin``, with hashed assets at
``/ui/assets/``. Gracefully degrades (registers nothing, logs a single
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
from navconfig import config
from navconfig.logging import logging

from .catalog import AdminCatalogHandler
from .status import AdminStatusHandler

try:
    from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY
except ImportError:  # pragma: no cover - navigator_auth is a core dependency
    AUTH_EXCLUDE_LIST_KEY = None

logger = logging.getLogger(__name__)

#: URL prefix the administration pages are served under.
DEFAULT_PREFIX = "/admin"

#: Top-level SPA sections served at the site root (besides the admin
#: prefix). MUST match ``config.appSections`` in ``ui/src/lib/config.ts``.
SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents")

#: URL prefix of the hashed Vite assets — MUST match ``build.assetsDir``
#: (``ui/assets``, under ``base: '/'``) in ``ui/vite.config.ts``.
ASSETS_PREFIX = "/ui/assets/"

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


async def _register_auth_exclusions_on_startup(
    app: web.Application, patterns: list[str]
) -> None:
    """``on_startup`` callback: register the SPA exclude-list ``patterns``.

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
    for pattern in patterns:
        _register_auth_exclusion(app, pattern)


def _spa_paths(prefix: str, *, mount_root: bool) -> list[str]:
    """Every SPA shell route as ``(exact, children)`` pairs, flattened.

    Args:
        prefix: The administration prefix (e.g. ``/admin``).
        mount_root: Whether the bare site root ``/`` also serves the shell.

    Returns:
        Route paths in registration order, e.g. ``["/", "/login",
        "/login/{tail:.*}", ...]``.
    """
    paths: list[str] = ["/"] if mount_root else []
    for section in (*SPA_SECTIONS, prefix):
        paths.extend([section, f"{section}/{{tail:.*}}"])
    return paths


def _auth_exclusion_patterns(prefix: str, *, mount_root: bool) -> list[str]:
    """fnmatch patterns that make the SPA shell reachable pre-login.

    Segment-boundary anchored (``/agents`` + ``/agents/*``) — ``fnmatch``
    has no notion of ``/`` as special, so a bare ``/agents*`` would also
    exclude an unrelated ``/agentsfoo`` route from auth. ``/`` is an exact
    pattern (fnmatch without wildcards), never ``/*``.
    """
    patterns: list[str] = ["/"] if mount_root else []
    for section in (*SPA_SECTIONS, prefix):
        patterns.extend([section, f"{section}/*"])
    patterns.append(f"{ASSETS_PREFIX}*")
    return patterns


def _root_is_taken(app: web.Application) -> bool:
    """True when some other handler already answers ``GET /``."""
    for resource in app.router.resources():
        if resource.canonical != "/":
            continue
        for route in resource:
            if route.method in ("GET", "*"):
                return True
    return False


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


def _make_root_middleware(index_html: Path):
    """Build a middleware serving the SPA shell for exactly ``GET|HEAD /``.

    Used only when another handler (navigator's default "home" page)
    already owns ``GET /``. Every other request passes straight through.

    Args:
        index_html: Path to the built ``index.html``.

    Returns:
        An aiohttp ``@web.middleware`` coroutine.
    """

    @web.middleware
    async def _root_ui_middleware(request: web.Request, handler):
        if request.path == "/" and request.method in ("GET", "HEAD"):
            return _index_response(index_html)
        return await handler(request)

    return _root_ui_middleware


def _make_assets_cache_header(assets_prefix: str):
    """Build an ``on_response_prepare`` hook that long-caches hashed assets.

    ``router.add_static()`` (aiohttp's ``FileResponse``/``StaticResource``
    machinery) never sets ``Cache-Control`` itself, so the header is
    injected via the ``on_response_prepare`` signal — the standard aiohttp
    hook for tagging responses by path without wrapping the whole app in a
    middleware.

    Args:
        assets_prefix: Path prefix (e.g. ``/ui/assets/``) whose
            responses should get the long-cache/immutable header.

    Returns:
        An ``async def(request, response)`` coroutine suitable for
        ``app.on_response_prepare.append(...)``.
    """

    async def _on_prepare(request: web.Request, response: web.StreamResponse) -> None:
        if request.path.startswith(assets_prefix):
            response.headers["Cache-Control"] = _ASSETS_CACHE_CONTROL

    return _on_prepare


def setup_admin_ui(
    app: web.Application,
    *,
    prefix: str = DEFAULT_PREFIX,
    mount_root: bool | None = None,
) -> bool:
    """Mount the embedded web UI if the compiled ``dist/`` is present.

    Registers:
      - A static mount for hashed assets at :data:`ASSETS_PREFIX`
        (``/ui/assets/``) with a long-cache/immutable ``Cache-Control``
        header injected via ``on_response_prepare``.
      - ``index.html`` (SPA history-mode router fallback, ``no-cache``) for
        the end-user sections (:data:`SPA_SECTIONS`: ``/login``,
        ``/agents``), the administration ``prefix`` (``/admin``), each as
        the exact path plus its ``/{tail}`` children, and — when
        ``mount_root`` is true and nothing else already serves it — the
        bare site root ``/``. Every mount is anchored on a path *segment*
        boundary and there is deliberately NO root catch-all, so ``/api/*``,
        ``/static/*``, ``/a2a`` and any lookalike route (``/administer``)
        are never shadowed.
      - The matching navigator-auth exclude-list patterns, so the HTML
        shell is reachable pre-login (auth enforcement lives entirely in
        the JSON API, not in the SPA shell routes). Registered via an
        ``on_startup`` callback rather than eagerly — see
        :func:`_register_auth_exclusions_on_startup` for why (both real
        entrypoints call this function before ``AuthHandler().setup(app)``
        has run).

    Args:
        app: The aiohttp :class:`web.Application` to mount routes on.
        prefix: URL prefix the administration pages are served under.
            Defaults to ``/admin``.
        mount_root: Also serve the SPA at ``/`` (redirected client-side to
            the agent list or login). ``None`` (default) reads the
            ``PARROT_UI_AT_ROOT`` setting (default ``true``). When ``GET /`` is already registered
            on ``app`` (navigator's default home page), it is served by a
            middleware scoped to exactly ``/`` instead.

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
    app.router.add_view("/api/v1/admin/catalog", AdminCatalogHandler)

    dist = _dist_dir()
    index_html = dist / "index.html"
    if not index_html.exists():
        if not _warned_missing_dist:
            logger.warning(
                "Web UI dist/ not found at %s: the compiled UI was not "
                "built (install-from-git without the Node build step, or "
                "a UI-less wheel). Run `make build-server-ui` to build it. "
                "Registering no UI routes; the JSON API is unaffected.",
                dist,
            )
            _warned_missing_dist = True
        return False

    router = app.router
    if mount_root is None:
        mount_root = config.getboolean("PARROT_UI_AT_ROOT", fallback=True)

    # Hashed static assets (Vite emits them into dist/ui/assets/ and
    # references them as /ui/assets/*). Cache-Control is injected via
    # on_response_prepare since add_static()/FileResponse never set it.
    assets_dir = dist / "ui" / "assets"
    if assets_dir.is_dir():
        router.add_static(
            ASSETS_PREFIX,
            path=assets_dir,
            name="admin_ui_assets",
            show_index=False,
            follow_symlinks=False,
        )
        app.on_response_prepare.append(_make_assets_cache_header(ASSETS_PREFIX))

    async def _spa_fallback(request: web.Request) -> web.StreamResponse:
        return _index_response(index_html)

    root_taken = mount_root and _root_is_taken(app)
    for path in _spa_paths(prefix, mount_root=mount_root and not root_taken):
        router.add_get(path, _spa_fallback)
    if root_taken:
        # navigator's AppHandler.CreateApp() always registers its own
        # placeholder ``GET /`` ("home"); aiohttp has no public API to
        # replace a route, so the bare root is answered by a middleware
        # that only ever intercepts exactly ``GET|HEAD /``.
        app.middlewares.append(_make_root_middleware(index_html))

    patterns = _auth_exclusion_patterns(prefix, mount_root=mount_root)
    # Deferred to on_startup — see _register_auth_exclusions_on_startup's
    # docstring for why eager registration here would race AuthHandler.setup().
    app.on_startup.append(
        lambda app: _register_auth_exclusions_on_startup(app, patterns)
    )

    return True
