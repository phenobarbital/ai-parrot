"""`botmanager` minimal target adapter (FEAT-581, M4).

Implements spec §3 "M4"'s ``parrot.e2e.targets.botmanager`` factory, per
spec §2 "Target and Authentication Design":

    botmanager minimal | New library-owned entry point follows the docker
    example; disables registry/database bots and crews explicitly. Real
    navigator-session Redis storage, ``/healthz``, protected fixture
    session probe and a selected real API route.

The launched child is a real, library-owned aiohttp entry point — the same
minimal pattern ``docker/integrations/server.py`` uses (a bare
``web.Application`` plus ``BotManager().setup(app)``), never the full
company webserver (``run.py``). :meth:`_BotManagerAdapter.prepare` never
spawns anything itself; it only returns a validated
:class:`~parrot.e2e.targets.base.LaunchSpec` invoking this module's own
:func:`run_app_entrypoint` inside the child, via the same
``sys.executable -c "..."`` bootstrap technique
:mod:`parrot.e2e.targets.mcp` already uses.

This module deliberately never imports ``parrot.manager.manager``/
``navigator_session`` at module level — only from inside
:func:`run_app_entrypoint` and the route handlers it wires up, all of which
only ever run *inside* the launched child's own process. Importing anything
under ``parrot.tools`` (which ``BotManager`` transitively pulls in, via
``parrot.bots.agent``/``AbstractTool``) calls ``uvloop.install()``, silently
replacing the *global* asyncio event loop policy out from under an
already-running loop — verified independently by TASK-3529 for the sibling
``mcp-toolkit``/``mcp-stdio`` adapters (see that module's own docstring/
``_MCPStdioAdapter.prepare`` note) and just as real a hazard here: the
E2E harness's own process (this module's ``prepare()``/``ready()`` side)
must never trigger it.

The authenticated fixture session/route payload below is the frozen,
verified contract from ``sdd/state/FEAT-581/research/session.md`` (TASK-3518,
Selected Contract §6) — not a guess:

1. Isolate ``navconfig``/``navigator_session`` config resolution by setting
   ``SITE_ROOT`` (pointed at an isolated per-run directory with an empty
   ``env/`` subdirectory) *and* ``REDIS_HOST``/``REDIS_PORT``/``SESSION_DB``
   in the child's environment *before* it starts — the three Redis
   variables alone are not sufficient in this repository, because
   ``navconfig``'s ``Kardex._mapping_`` (populated from the checked-in
   ``env/.env``) silently wins over ``os.environ`` unless ``SITE_ROOT`` is
   also isolated (session.md §2.2-§2.3).
2. ``SessionHandler(storage="redis", use_cookies=True, secure=False)`` —
   ``use_cookies`` defaults to ``False`` and must be passed explicitly.
3. The frozen synthetic user payload: ``{"user_id": "e2e-test-user-3518",
   "email": "e2e-3518@test.local"}``, identity key value
   ``"e2e-test-user-3518"``.
4. ``BotManager.get_user_bot()`` never reads the session cookie on its own
   (its own ``get_session(request)`` call defaults to ``ignore_cookie=True``).
   The protected fixture route calls ``get_session(request,
   ignore_cookie=False)`` itself first and re-populates
   ``request[SESSION_KEY]``/``request[SESSION_ID]`` before delegating.
5. Invalid-cookie denial requires an explicit ``try/except RuntimeError``
   around that call — the library raises rather than returning ``None`` on
   a malformed cookie.
6. The minimal profile has no database configured (``enable_database_bots=
   False``); ``BotManager._fetch_user_bot_model`` (the one DB-touching leaf
   method ``get_user_bot()`` calls) is replaced, at the instance level, with
   a fixture stub returning ``None`` — the exact, disclosed scope boundary
   session.md §3.2 selected ("DB access is out of this task's Scope"), not
   a hidden monkeypatch of anything session/auth-related.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import web

from parrot.e2e import state as e2e_state
from parrot.e2e.errors import E2EConfigError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.targets import redis as e2e_redis
from parrot.e2e.targets.base import LaunchSpec

__all__ = ["build_botmanager_adapter", "run_app_entrypoint"]

logger = logging.getLogger(__name__)

# Boots this module's own entry point from inside the child -- the same
# `sys.executable -c "..."` technique `parrot.e2e.targets.mcp` already uses,
# never a bespoke inlined script or the (possibly stale) installed `parrot`
# console script.
_BOOTMANAGER_BOOTSTRAP = "from parrot.e2e.targets.botmanager import run_app_entrypoint\nrun_app_entrypoint()\n"

# `botmanager` minimal accepts an explicit `port` override (deterministic
# port selection for tests); no other option key is supported. The `full`
# profile (spec §2: "never assume run.py exposes healthz") requires an
# explicit command/readiness contract no task has implemented yet -- see
# `_require_minimal_profile` -- so it has no option surface here at all.
_MINIMAL_SUPPORTED_OPTIONS = frozenset({"port"})

_READY_HTTP_TIMEOUT_S = 2.0
_REDIS_READY_TIMEOUT_S = 10.0
_SESSION_DB = "0"

# Frozen synthetic user payload (session.md §6 item 8) -- reused verbatim,
# never invented ad hoc.
_FIXTURE_USER_ID = "e2e-test-user-3518"
_FIXTURE_EMAIL = "e2e-3518@test.local"
_FIXTURE_CHATBOT_ID = "e2e-fixture-bot"

_BOOTSTRAP_SECRET_ENV = "E2E_BOOTSTRAP_SECRET"
_SERVER_NAME_ENV = "E2E_BOTMANAGER_SERVER_NAME"
_REDIS_DATA_DIR_ENV = "E2E_REDIS_DATA_DIR"
_REDIS_BINARY_ENV = "E2E_REDIS_BINARY"
_APP_PORT_ENV = "PORT"


def _require_kind(config: TargetConfig, expected: str) -> None:
    """Reject a :class:`TargetConfig` whose ``kind`` disagrees with this adapter.

    Args:
        config: The target configuration to validate.
        expected: The one ``kind`` value this adapter handles.

    Raises:
        E2EConfigError: If ``config.kind != expected``.
    """
    if config.kind != expected:
        raise E2EConfigError(
            f"this adapter only handles kind={expected!r}, got {config.kind!r}", reason_code="kind_mismatch"
        )


def _require_minimal_profile(config: TargetConfig) -> None:
    """Reject ``profile="full"`` — this adapter implements the minimal profile only.

    Spec §2: "The full target launches the real application with an
    explicit command/readiness profile, never an assumed ``/healthz``."
    No task has yet defined that explicit contract's shape, so this
    adapter refuses to guess one rather than silently defaulting to the
    minimal entry point under a ``full`` label.

    Args:
        config: The target configuration to validate.

    Raises:
        E2EConfigError: If ``config.profile == "full"``.
    """
    if config.profile == "full":
        raise E2EConfigError(
            "botmanager 'full' profile requires an explicit command/readiness contract "
            "this adapter does not implement (spec §2); only 'minimal' is supported",
            reason_code="botmanager_full_profile_unsupported",
        )


def _reject_unsupported_options(config: TargetConfig) -> None:
    """Reject any ``config.options`` key the minimal profile does not recognize.

    Args:
        config: The target configuration to validate.

    Raises:
        E2EConfigError: If ``config.options`` contains an unsupported key.
    """
    unsupported = sorted(set(config.options) - _MINIMAL_SUPPORTED_OPTIONS)
    if unsupported:
        raise E2EConfigError(
            f"'botmanager' target does not support option key(s) {unsupported}; "
            f"supported: {sorted(_MINIMAL_SUPPORTED_OPTIONS)}",
            reason_code="unsupported_option",
        )


def _validate_port_option(config: TargetConfig) -> Optional[int]:
    """Validate (never allocate) an explicit ``options["port"]`` override.

    Deliberately a pure, environment-independent config check — called
    before any external prerequisite (the ``redis-server`` binary) is
    looked up, so an invalid ``options["port"]`` is always reported as a
    config error (spec §2 exit code 2), never masked by a BLOCKED
    prerequisite error on a host that also happens to be missing
    ``redis-server``.

    Args:
        config: The target configuration to validate.

    Returns:
        The validated positive ``int``, or ``None`` if no override was given.

    Raises:
        E2EConfigError: If ``options["port"]`` is present but is not a
            positive ``int``.
    """
    port_option = config.options.get("port")
    if port_option is None:
        return None
    if isinstance(port_option, bool) or not isinstance(port_option, int) or port_option <= 0:
        raise E2EConfigError(
            f"options['port'] must be a positive integer, got {port_option!r}", reason_code="invalid_option"
        )
    return port_option


@dataclass(frozen=True)
class _BotManagerEndpoint:
    """This adapter's own record of one run's HTTP endpoint and identity.

    Attributes:
        host: The loopback host the child was told to bind.
        port: The loopback port the child was told to bind.
        expected_name: The server name this run's child was configured
            with — the value :meth:`_BotManagerAdapter.ready` requires
            ``GET <base_url>/healthz`` to echo back before trusting
            anything else on this port (spec §2: "Do not mistake a
            pre-existing service's health response for the child.").
    """

    host: str
    port: int
    expected_name: str


class _BotManagerAdapter:
    """`botmanager` minimal target: the real library-owned entry point over HTTP.

    Tracks its own ``run_id -> _BotManagerEndpoint`` mapping (set in
    :meth:`prepare`, consulted in :meth:`ready`) since
    :attr:`parrot.e2e.models.RunState.endpoint` is never populated by the
    supervisor (M3) for any target kind.
    """

    def __init__(self) -> None:
        """Initialize the adapter with an empty per-run endpoint table."""
        self.logger = logging.getLogger(__name__)
        self._endpoints: dict[str, _BotManagerEndpoint] = {}

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Return the minimal BotManager HTTP launch (real private Redis, real session auth).

        Never spawns anything itself — the private Redis instance is
        started by the child's own :func:`run_app_entrypoint`, not here
        (spec/Protocol contract: ``prepare()`` only ever returns a
        validated :class:`LaunchSpec`).

        Args:
            config: Must have ``kind == "botmanager"`` and
                ``profile == "minimal"``. ``options["port"]`` (a positive
                ``int``) overrides the default free-port allocation for
                the app's own HTTP port; every other option key is
                rejected.
            run_id: The run's stable ID — used to name this run's private
                directories and as this run's own server name (the value
                :meth:`ready` cross-checks against ``/healthz``).
            worktree: The owning worktree root.

        Returns:
            A ``stdio=False`` :class:`LaunchSpec` invoking this module's
            own :func:`run_app_entrypoint`, with the isolated Redis/
            session/bootstrap-secret environment (session.md's frozen
            contract) already merged in.

        Raises:
            E2EConfigError: If ``config.kind`` disagrees, ``config.profile
                == "full"``, ``config.options`` carries an unsupported
                key, or ``options["port"]`` is not a positive integer.
            E2EPrerequisiteError: If no ``redis-server`` binary is found on
                ``PATH`` (spec §2: "Missing redis-server blocks required
                authenticated scenarios.").
        """
        _require_kind(config, "botmanager")
        _require_minimal_profile(config)
        _reject_unsupported_options(config)
        explicit_app_port = _validate_port_option(config)

        redis_binary = e2e_redis.find_redis_server_binary()

        redis_port = e2e_redis.allocate_loopback_port()
        app_port = explicit_app_port
        if app_port is None:
            app_port = e2e_redis.allocate_loopback_port()
            while app_port == redis_port:
                app_port = e2e_redis.allocate_loopback_port()
        server_name = f"e2e-botmanager-{run_id}"
        bootstrap_secret = secrets.token_urlsafe(32)

        run_directory = e2e_state.run_dir(run_id, worktree=worktree)
        redis_data_dir = run_directory / "redis-data"
        site_root_dir = run_directory / "site-root"
        site_root_env_dir = site_root_dir / "env"
        site_root_env_dir.mkdir(parents=True, exist_ok=True)
        site_root_dir.chmod(e2e_state.RUN_DIR_MODE)
        site_root_env_dir.chmod(e2e_state.RUN_DIR_MODE)

        env = {
            "SITE_ROOT": str(site_root_dir),
            "REDIS_HOST": "127.0.0.1",
            "REDIS_PORT": str(redis_port),
            "SESSION_DB": _SESSION_DB,
            _BOOTSTRAP_SECRET_ENV: bootstrap_secret,
            _SERVER_NAME_ENV: server_name,
            _REDIS_DATA_DIR_ENV: str(redis_data_dir),
            _REDIS_BINARY_ENV: redis_binary,
            _APP_PORT_ENV: str(app_port),
        }

        argv = [sys.executable, "-c", _BOOTMANAGER_BOOTSTRAP]
        self._endpoints[run_id] = _BotManagerEndpoint(host="127.0.0.1", port=app_port, expected_name=server_name)
        self.logger.debug(
            "botmanager prepare: run_id=%s app_port=%s redis_port=%s name=%s",
            run_id,
            app_port,
            redis_port,
            server_name,
        )
        return LaunchSpec(argv=argv, env=env, cwd=worktree, stdio=False)

    async def ready(self, state: RunState) -> bool:
        """Poll ``<base_url>/healthz`` and verify this run's own server identity.

        Never trusts a bare HTTP 200: a pre-existing, unrelated service
        happening to already listen on this run's loopback port is
        rejected unless ``/healthz`` echoes back exactly the server name
        this adapter itself configured in :meth:`prepare` (spec §2).

        Args:
            state: The run's current state; only ``state.run_id`` is used
                (never ``state.endpoint``, which this target kind's
                supervisor leaves ``None``).

        Returns:
            ``True`` once ``/healthz`` reports ``{"status": "ok", "name":
            <this run's own server name>}``; ``False`` while still
            starting, on any connection error/timeout, or against an
            identity mismatch.
        """
        endpoint = self._endpoints.get(state.run_id)
        if endpoint is None:
            self.logger.debug("botmanager ready: no recorded endpoint for run_id=%s", state.run_id)
            return False

        base_url = f"http://{endpoint.host}:{endpoint.port}"
        timeout = aiohttp.ClientTimeout(total=_READY_HTTP_TIMEOUT_S)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{base_url}/healthz") as response:
                    if response.status != 200:
                        return False
                    body = await response.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            self.logger.debug("botmanager ready: transient error for run_id=%s: %s", state.run_id, exc)
            return False

        if not isinstance(body, dict) or body.get("status") != "ok":
            return False
        if body.get("name") != endpoint.expected_name:
            self.logger.debug("botmanager ready: /healthz identity mismatch for run_id=%s: %r", state.run_id, body)
            return False
        return True


def build_botmanager_adapter() -> _BotManagerAdapter:
    """Build the `botmanager` target adapter.

    Returns:
        A fresh :class:`_BotManagerAdapter` with an empty endpoint table.
    """
    return _BotManagerAdapter()


# ---------------------------------------------------------------------------
# Child-process entry point — runs only inside the launched target, never in
# the E2E harness's own process. Every ``navigator_session``/``BotManager``
# import below is deferred into a function body for exactly that reason (see
# this module's own docstring).
# ---------------------------------------------------------------------------


async def _healthz(request: web.Request) -> web.Response:
    """Real, library-owned health route (spec §2 / docker example pattern).

    Args:
        request: The incoming request (unused beyond routing).

    Returns:
        ``{"status": "ok", "name": <this run's own configured server
        name>}`` — the ``name`` field is this module's own addition over
        the bare docker example, giving :meth:`_BotManagerAdapter.ready` an
        identity to verify against (spec §2: never mistake a pre-existing
        service's health response for the child).
    """
    return web.json_response({"status": "ok", "name": os.environ.get(_SERVER_NAME_ENV, "")})


async def _bootstrap_login(request: web.Request) -> web.Response:
    """E2E-only, secret-guarded bootstrap login (spec §2).

    Requires ``Authorization: Bearer <one-run random secret>`` (provided
    through the child environment by :meth:`_BotManagerAdapter.prepare`,
    never a fixed/predictable value); on success, creates a real stored
    synthetic session through ``navigator_session.new_session`` using the
    frozen synthetic payload (session.md §6 item 8) and returns the normal
    session cookie via the installed session middleware. This route exists
    only in this dedicated E2E entry point and is never registered by
    production ``BotManager.setup()``.

    Args:
        request: The incoming request.

    Returns:
        ``403`` if the bearer secret is missing/wrong; otherwise ``200``
        with ``{"session_id": <new session id>}``.
    """
    from navigator_session import new_session  # noqa: PLC0415
    from navigator_session.conf import SESSION_KEY  # noqa: PLC0415

    expected_secret = os.environ.get(_BOOTSTRAP_SECRET_ENV)
    header = request.headers.get("Authorization", "")
    if not expected_secret or header != f"Bearer {expected_secret}":
        return web.json_response({"error": "forbidden"}, status=403)

    # `new_session()`'s own identity resolution reads `request[SESSION_KEY]`
    # (session.md §6 item 1/5) -- must be set *before* the call, not passed
    # only inside the userdata dict.
    request[SESSION_KEY] = _FIXTURE_USER_ID
    session = await new_session(request, {"user_id": _FIXTURE_USER_ID, "email": _FIXTURE_EMAIL})
    return web.json_response({"session_id": session.session_id})


async def _protected_bot(request: web.Request) -> web.Response:
    """Protected fixture session probe, then a real BotManager API route (spec §2).

    Validates the session cookie itself (never delegating that to
    ``BotManager.get_user_bot()``, which never reads a cookie on its own —
    session.md §6 item 4/5), denying both an anonymous request and an
    invalid/tampered cookie, then re-populates the resolved identity onto
    ``request`` and calls the real ``BotManager.get_user_bot()`` route.

    Args:
        request: The incoming request.

    Returns:
        ``401`` for an anonymous or invalid-cookie request; otherwise
        ``200`` with ``{"bot": <get_user_bot() result>, "user_id":
        <resolved identity>}``.
    """
    from navigator_session import get_session  # noqa: PLC0415
    from navigator_session.conf import SESSION_ID, SESSION_KEY  # noqa: PLC0415

    try:
        session = await get_session(request, ignore_cookie=False)
    except RuntimeError:
        # session.md §6 item 6: an invalid/tampered cookie makes the
        # library itself raise rather than return None -- must be caught
        # explicitly, or this is an unhandled 500, not a clean denial.
        return web.json_response({"error": "invalid_session"}, status=401)
    if session is None:
        return web.json_response({"anonymous": True}, status=401)

    # Use `session.identity` (the dedicated property, frozen at
    # `SessionData.__init__` time from the *loaded* Redis data), never
    # `session.get(SESSION_KEY)` / `session["id"]`: verified directly
    # against the installed `navigator_session` 1.0.1 --
    # `RedisStorage.load_session()` itself overwrites `session[SESSION_KEY]`
    # with the session ID (not the identity) immediately after
    # constructing the `SessionData`, a library quirk in code this task
    # does not own or modify. `session.identity` is unaffected by that
    # later mutation and is the identity `request[SESSION_KEY]` was also
    # populated with by that same call, one line below it.
    identity = session.identity
    request[SESSION_KEY] = identity
    request[SESSION_ID] = session.session_id

    bot_manager = request.app["bot_manager"]
    bot = await bot_manager.get_user_bot(request, _FIXTURE_CHATBOT_ID)
    return web.json_response({"bot": bot, "user_id": identity})


async def _fixture_fetch_user_bot_model(_user_id: object, _chatbot_id: object) -> None:
    """Fixture stub for ``BotManager._fetch_user_bot_model``'s DB lookup.

    The minimal profile has no database configured
    (``enable_database_bots=False``); this exact instance-level
    replacement is the disclosed scope boundary the verified session
    research contract selected (session.md §3.2: "DB access is out of
    this task's Scope"), not a hidden monkeypatch of anything
    session/auth-related.

    Args:
        _user_id: Unused.
        _chatbot_id: Unused.

    Returns:
        ``None``, always — matching a genuine "no user-bot row" result.
    """
    return None


def _build_app() -> web.Application:
    """Build the minimal, library-owned BotManager aiohttp app (spec §2).

    Follows ``docker/integrations/server.py``'s pattern (bare
    ``web.Application`` + ``BotManager().setup(app)``), with discovery/
    database/crews explicitly disabled, real ``navigator-session`` Redis
    session storage, and this module's E2E-only fixture routes.

    Returns:
        The fully configured, not-yet-served application.
    """
    from navigator_session import SessionHandler  # noqa: PLC0415
    from parrot.manager.manager import BotManager  # noqa: PLC0415

    app = web.Application()
    app.router.add_get("/healthz", _healthz)
    app.router.add_post("/e2e/bootstrap-login", _bootstrap_login)
    app.router.add_get("/e2e/protected/bot", _protected_bot)

    SessionHandler(storage="redis", use_cookies=True, secure=False).setup(app)

    bot_manager = BotManager(
        enable_database_bots=False,
        enable_crews=False,
        enable_registry_bots=False,
        enable_swagger_api=False,
    )
    bot_manager._fetch_user_bot_model = _fixture_fetch_user_bot_model
    bot_manager.setup(app)
    return app


def run_app_entrypoint() -> None:
    """Boot this run's private Redis, then serve the minimal BotManager app.

    The real, synchronous child-process bootstrap invoked by
    :meth:`_BotManagerAdapter.prepare`'s own :data:`_BOOTMANAGER_BOOTSTRAP`
    script. Spawns the private, persistence-disabled Redis instance first
    (never the operator's shared Redis), then blocks serving the app via
    ``web.run_app`` — the same call ``docker/integrations/server.py`` uses.
    The Redis child is torn down in ``finally`` on any exit path; it is
    also directly reachable by the supervisor's own ``killpg`` (this
    process's own process group), since it is never given its own session.
    """
    host = "127.0.0.1"
    redis_port = int(os.environ["REDIS_PORT"])
    data_dir = Path(os.environ[_REDIS_DATA_DIR_ENV])
    binary = os.environ.get(_REDIS_BINARY_ENV) or None

    redis_process, _endpoint = e2e_redis.spawn_private_redis(
        host=host, port=redis_port, data_dir=data_dir, timeout_s=_REDIS_READY_TIMEOUT_S, binary=binary
    )
    try:
        app = _build_app()
        port = int(os.environ[_APP_PORT_ENV])
        web.run_app(app, host=host, port=port)
    finally:
        if redis_process.poll() is None:
            redis_process.terminate()
            try:
                redis_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                redis_process.kill()
                with contextlib.suppress(Exception):
                    redis_process.wait(timeout=5.0)
