"""`JiraInterface` — shared auth resolution + read surface (FEAT-454, M1).

The single Jira read implementation in the repo: both ``JiraToolkit``
(TASK-2402) and the wiki sweep (``parrot.knowledge.wiki.jira_sync``,
TASK-2403) consume this class. Read-only — ticket mutation stays
``JiraToolkit``'s job.

Two disciplines are non-negotiable, carried over from ``JiraToolkit``
because getting either wrong is silent and self-perpetuating:

1. **No auth heuristic.** An unresolved ``auth_type`` leaves the interface
   *unauthenticated*; every read raises :class:`JiraAuthError` rather than
   guessing a mode or falling back to env credentials.
2. **An empty result set is not proof of an empty scope.** Jira Cloud
   answers a failed auth with ``200`` + an empty list +
   ``X-Seraph-Loginreason: AUTHENTICATED_FAILED``. An empty first search
   page (or an empty project list) triggers a ``/myself`` probe, and a
   failed probe raises instead of returning an empty-but-successful result.

The ``jira`` (pycontribs) distribution is optional and lazily imported —
importing this module must never require it to be installed.
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from .errors import JiraAuthError, JiraDependencyError
from .parse import parse_issue

try:
    # Optional config source; fall back to env vars if missing — same
    # tolerance as parrot_tools.jiratoolkit.
    from navconfig import config as nav_config  # type: ignore
except Exception:  # noqa: BLE001 — pragma: no cover - optional dependency
    nav_config = None

logger = logging.getLogger(__name__)


def _cfg(key: str, default: str | None = None) -> str | None:
    """Resolve a config key: navconfig first, then ``os.getenv``."""
    if (nav_config is not None) and hasattr(nav_config, "get"):
        val = nav_config.get(key)
        if val is not None:
            return str(val)
    return os.getenv(key, default)


def _import_jira():
    """Import the pycontribs ``jira`` client, or raise actionably.

    Returns:
        The ``jira.JIRA`` class.

    Raises:
        JiraDependencyError: If the optional ``jira`` distribution is not
            installed.
    """
    try:
        from jira import JIRA
    except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
        raise JiraDependencyError(
            "The Jira read interface needs the optional `jira` "
            "distribution. Install it with:  pip install 'ai-parrot[jira]'"
        ) from exc
    return JIRA


# Atlassian returns this header on 200 responses when an auth attempt was
# made but failed (common on Jira Cloud with a stale API token).
_SERAPH_HEADER = "X-Seraph-Loginreason"
_SERAPH_FAIL_VALUES = {"AUTHENTICATED_FAILED", "AUTHENTICATION_DENIED"}

# Candidate names for the acceptance-criteria custom field, matched
# case-insensitively against `GET /rest/api/2/field` when
# `JIRA_WIKI_AC_FIELD` is not set (spec §8, resolved).
_AC_FIELD_NAMES: tuple[str, ...] = (
    "acceptance criteria",
    "acceptance criterion",
    "criterios de aceptacion",
)

# Bounded per-user client cache for oauth2_3lo mode — mirrors
# jiratoolkit.py:1007 (_CLIENT_CACHE_MAX_SIZE).
_CLIENT_CACHE_MAX_SIZE = 100

# Read-only OAuth 2.0 (3LO) scopes. Narrower than JiraToolkit's
# _OAUTH_SCOPES (which includes write:jira-work) — this interface never
# writes to Jira (spec §3 M1, Non-Goals).
OAUTH_SCOPES: tuple[str, ...] = (
    "read:jira-work",
    "read:jira-user",
    "offline_access",
)


class JiraInterface:
    """Shared Jira read interface. Lazily imports ``jira``.

    Owns connection/auth resolution (every mode ``JiraToolkit`` supports:
    ``basic_auth``, ``token_auth``, ``oauth`` (1.0a), ``oauth2_3lo`` via
    :class:`parrot.auth.jira_oauth.JiraOAuthManager`) and the read surface:
    paginated JQL search, issue fetch, changelog, remote links, project
    metadata, an auth probe, and acceptance-criteria field resolution.

    Note on ``oauth2_3lo``: the interface accepts a duck-typed
    ``credential_resolver`` exposing an async ``resolve()`` returning a
    token-set-like object with ``access_token``, ``api_base_url`` and
    (optionally) ``account_id`` attributes — e.g.
    :class:`parrot.auth.jira_oauth.JiraTokenSet`. Unlike ``JiraToolkit``
    (which resolves per ``(channel, user_id)`` from a
    ``PermissionContext``), this interface has no per-call user context in
    its read-method signatures, so ``credential_resolver.resolve()`` is
    called with no arguments — it is expected to already be scoped to a
    single identity when 3LO is used through this interface directly.
    """

    def __init__(
        self,
        server_url: str | None = None,
        auth_type: str | None = None,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        oauth_consumer_key: str | None = None,
        oauth_key_cert: str | None = None,
        oauth_access_token: str | None = None,
        oauth_access_token_secret: str | None = None,
        credential_resolver: Any = None,
        request_timeout: float = 30.0,
        verify_credentials: bool = True,
        verify_tls: bool = False,
    ) -> None:
        """Initialize the interface. Never makes a network call.

        Args:
            server_url: Jira instance base URL. Required for the static
                auth modes; optional for ``oauth2_3lo``, whose URL is
                resolved per-user at call time.
            auth_type: One of ``basic_auth``/``token_auth``/``oauth``/
                ``oauth2_3lo``. Falls back to ``JIRA_AUTH_TYPE``. If left
                unresolved, the interface is unauthenticated and every read
                raises :class:`JiraAuthError` — no heuristic fallback.
            username: Basic-auth username. Falls back to ``JIRA_USERNAME``.
            password: Basic-auth password/token. Falls back to
                ``JIRA_PASSWORD``/``JIRA_API_TOKEN``.
            token: Personal access token for ``token_auth``. Falls back to
                ``JIRA_SECRET_TOKEN``.
            oauth_consumer_key: OAuth 1.0a consumer key.
            oauth_key_cert: OAuth 1.0a private key — PEM content or a path
                to a PEM file.
            oauth_access_token: OAuth 1.0a access token.
            oauth_access_token_secret: OAuth 1.0a access token secret.
            credential_resolver: Duck-typed per-user token resolver for
                ``oauth2_3lo`` (see class docstring).
            request_timeout: HTTP timeout in seconds, passed to
                ``JIRA(timeout=...)``.
            verify_credentials: When ``True``, probe ``/myself`` on first
                use of a static-mode client and raise on a definitive
                rejection.
            verify_tls: TLS verification for static-mode clients. Defaults
                to ``False`` to match ``JiraToolkit``'s existing behaviour
                (`jiratoolkit.py:960`) — override for a stricter run.
        """
        self.logger = logging.getLogger(__name__)

        # No auth-type heuristic (jiratoolkit.py:767-775): an unresolved
        # auth_type leaves the interface unauthenticated.
        _configured_auth = auth_type or _cfg("JIRA_AUTH_TYPE")
        self.auth_type: str | None = _configured_auth.lower() if _configured_auth else None

        # oauth2_3lo resolves its server URL per-user at call time.
        self.server_url = server_url or _cfg("JIRA_INSTANCE") or ""

        self.username = username or _cfg("JIRA_USERNAME")
        self.password = password or _cfg("JIRA_PASSWORD") or _cfg("JIRA_API_TOKEN")
        self.token = token or _cfg("JIRA_SECRET_TOKEN")

        self.oauth_consumer_key = oauth_consumer_key or _cfg("JIRA_OAUTH_CONSUMER_KEY")
        self.oauth_key_cert = oauth_key_cert or _cfg("JIRA_OAUTH_KEY_CERT")
        self.oauth_access_token = oauth_access_token or _cfg("JIRA_OAUTH_ACCESS_TOKEN")
        self.oauth_access_token_secret = oauth_access_token_secret or _cfg("JIRA_OAUTH_ACCESS_TOKEN_SECRET")

        self.credential_resolver = credential_resolver
        self.request_timeout = request_timeout
        self.verify_credentials = verify_credentials
        self.verify_tls = verify_tls

        self._client: Any = None
        self._verified = False
        # oauth2_3lo per-user client cache: {cache_key: (client, token_hash)}
        self._client_cache: dict[str, tuple[Any, str]] = {}
        # resolve_ac_field_id() cache (process/instance lifetime).
        self._ac_field_id: str | None = None
        self._ac_field_resolved = False

    # ------------------------------------------------------------------
    # Client construction
    # ------------------------------------------------------------------

    def _build_client(self) -> Any:
        """Build a static-mode (non-3LO) ``jira.JIRA`` client.

        Synchronous — callers wrap this in ``asyncio.to_thread``.

        Raises:
            ValueError: For missing/partial credentials, or an unsupported
                ``auth_type``.
        """
        jira_cls = _import_jira()
        options: dict[str, Any] = {
            "server": self.server_url,
            "verify": self.verify_tls,
            "headers": {"Accept-Encoding": "gzip, deflate"},
        }

        if self.auth_type == "basic_auth":
            if not (self.username and self.password):
                raise ValueError("basic_auth requires username and password")
            return jira_cls(
                options=options,
                basic_auth=(self.username, self.password),
                timeout=self.request_timeout,
            )

        if self.auth_type == "token_auth":
            if not self.token:
                raise ValueError("token_auth requires a Personal Access Token")
            return jira_cls(
                options=options,
                token_auth=self.token,
                timeout=self.request_timeout,
            )

        if self.auth_type == "oauth":
            key_cert = self._read_key_cert(self.oauth_key_cert)
            oauth_dict = {
                "access_token": self.oauth_access_token,
                "access_token_secret": self.oauth_access_token_secret,
                "consumer_key": self.oauth_consumer_key,
                "key_cert": key_cert,
            }
            if not all(oauth_dict.values()):
                raise ValueError("oauth requires consumer_key, key_cert, access_token, " "access_token_secret")
            return jira_cls(options=options, oauth=oauth_dict, timeout=self.request_timeout)

        raise ValueError(f"Unsupported auth_type: {self.auth_type}")

    @staticmethod
    def _read_key_cert(value: str | None) -> str | None:
        """Read an OAuth 1.0a key cert: PEM content, or a path to one."""
        if not value:
            return None
        if os.path.exists(value):
            with open(value, "r", encoding="utf-8") as fh:
                return fh.read()
        return value

    def _build_client_from_token(self, token_set: Any) -> Any:
        """Build a ``jira.JIRA`` client backed by an OAuth 2.0 (3LO) token.

        The pycontribs ``jira`` library does not expose Bearer auth as a
        first-class option; it honours any headers passed via
        ``options['headers']``. Points ``server`` at the Atlassian gateway
        derived from the token set's ``cloud_id``.
        """
        jira_cls = _import_jira()
        options: dict[str, Any] = {
            "server": token_set.api_base_url,
            "verify": True,
            "headers": {
                "Authorization": f"Bearer {token_set.access_token}",
                "Accept-Encoding": "gzip, deflate",
            },
        }
        return jira_cls(options=options, timeout=self.request_timeout)

    @staticmethod
    def _token_fingerprint(token_set: Any) -> str:
        """Stable string fingerprint of a token (survives PYTHONHASHSEED)."""
        at = getattr(token_set, "access_token", "") or ""
        return (at[:16] + at[-8:]) if len(at) > 24 else at

    def attach_client(self, client: Any) -> None:
        """Attach an already-resolved ``jira.JIRA`` client.

        Bypasses this interface's own auth resolution entirely for every
        subsequent call. This is the delegation seam ``JiraToolkit`` uses
        (TASK-2402, G1) so ``oauth2_3lo``'s per-``(channel, user_id)``
        token resolution — which this interface's own
        ``credential_resolver.resolve()`` has no context to perform — is
        resolved exactly once, inside the toolkit's own ``_pre_execute``,
        and simply reused here rather than duplicated.

        Args:
            client: An already-constructed ``jira.JIRA`` client (or any
                stand-in used by tests), or ``None`` to clear it.
        """
        self._client = client

    async def _ensure_client_3lo(self) -> Any:
        """Resolve (and cache) the per-user ``jira.JIRA`` client for 3LO.

        Raises:
            JiraAuthError: When no ``credential_resolver`` is configured, or
                it cannot resolve a token set for the current identity.
        """
        if self.credential_resolver is None:
            raise JiraAuthError("oauth2_3lo requires a credential_resolver to resolve a " "per-user token set.")
        token_set = await self.credential_resolver.resolve()
        if token_set is None:
            raise JiraAuthError(
                "No authorized Jira account found for oauth2_3lo — the user "
                "must complete the OAuth 2.0 authorization flow."
            )
        token_hash = self._token_fingerprint(token_set)
        cache_key = getattr(token_set, "account_id", None) or "default"
        cached = self._client_cache.get(cache_key)
        if cached is not None and cached[1] == token_hash:
            self._client = cached[0]
            return self._client

        client = await asyncio.to_thread(self._build_client_from_token, token_set)
        if len(self._client_cache) >= _CLIENT_CACHE_MAX_SIZE:
            oldest_key = next(iter(self._client_cache))
            self._client_cache.pop(oldest_key, None)
        self._client_cache[cache_key] = (client, token_hash)
        self._client = client
        return self._client

    async def _ensure_client(self) -> Any:
        """Resolve (and cache) the underlying ``jira.JIRA`` client.

        Raises:
            JiraAuthError: When ``auth_type`` is unresolved, or 3LO
                credential resolution fails.
            ValueError: When a static mode is selected but ``server_url``
                is missing, or credentials for the selected mode are
                incomplete.
            JiraDependencyError: When the ``jira`` distribution is absent.
        """
        if self.auth_type is None:
            raise JiraAuthError(
                "Jira is not authenticated: no credentials were provided. "
                "Configure JIRA_AUTH_TYPE (basic_auth/token_auth/oauth/"
                "oauth2_3lo) with matching credentials."
            )

        # An already-attached client (see attach_client(), TASK-2402) always
        # wins, for every auth mode including oauth2_3lo — this is the seam
        # JiraToolkit's delegation uses so a per-user 3LO token, which this
        # interface's own credential_resolver.resolve() cannot see (it has
        # no (channel, user_id) context), is resolved exactly once, inside
        # the toolkit's own _pre_execute, never duplicated here.
        if self._client is not None:
            return self._client

        if self.auth_type == "oauth2_3lo":
            return await self._ensure_client_3lo()

        if not self.server_url:
            raise ValueError("Jira server_url is required (e.g., https://your.atlassian.net)")
        self._client = await asyncio.to_thread(self._build_client)
        if self.verify_credentials and not self._verified:
            await self._verify_static_credentials()
            self._verified = True
        return self._client

    # ------------------------------------------------------------------
    # Auth verification / the AUTHENTICATED_FAILED trap
    # ------------------------------------------------------------------

    def _probe_auth_sync(self) -> dict[str, Any]:
        """Raw HTTP probe against ``/myself``. Never raises.

        pycontribs' ``JIRA.myself()`` does not surface response headers,
        and Jira Cloud returns a 200 + ``X-Seraph-Loginreason:
        AUTHENTICATED_FAILED`` when the session is anonymous after a
        failed auth attempt. Going through the underlying session lets us
        read those headers directly (mirrors
        ``JiraToolkit._probe_auth_sync``, ``jiratoolkit.py:2156``).

        Returns:
            A result dict with at least ``authenticated: bool``.
        """
        client = self._client
        options = getattr(client, "_options", {}) or {}
        base = options.get("server") or self.server_url
        api_path = "/rest/api/3/myself" if self.auth_type == "oauth2_3lo" else "/rest/api/2/myself"
        url = f"{base.rstrip('/')}{api_path}"
        session = getattr(client, "_session", None)
        if session is None:
            return {
                "authenticated": False,
                "error": "No underlying session available on JIRA client.",
            }
        try:
            response = session.get(url)
        except Exception as exc:  # noqa: BLE001 — transport failures too
            return {
                "authenticated": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        headers = dict(response.headers or {})
        seraph = headers.get(_SERAPH_HEADER) or headers.get(_SERAPH_HEADER.lower())
        seraph_failed = bool(seraph) and seraph.upper() in _SERAPH_FAIL_VALUES
        status = response.status_code
        is_http_ok = 200 <= status < 300
        authenticated = is_http_ok and not seraph_failed

        result: dict[str, Any] = {
            "authenticated": authenticated,
            "status_code": status,
            "seraph_login_reason": seraph,
        }
        if not authenticated:
            result["error"] = f"HTTP {status}" + (f" — {seraph}" if seraph else "")
        return result

    async def _verify_static_credentials(self) -> None:
        """Probe ``/myself`` right after building a static-mode client.

        Only *definitive* rejections raise — a probe that cannot reach the
        server at all (offline, DNS, timeout) logs a warning and leaves the
        client in place, since transport problems are not a credential
        verdict (mirrors ``JiraToolkit._verify_static_credentials``).

        Raises:
            JiraAuthError: When Jira answered the probe and the session is
                not authenticated (401/403, or a Seraph failure header).
        """
        try:
            result = await asyncio.to_thread(self._probe_auth_sync)
        except Exception as exc:  # noqa: BLE001 — a broken probe is not a verdict
            self.logger.warning(
                "Could not verify Jira credentials (probe raised: %s); " "continuing unverified.",
                exc,
            )
            return
        if result.get("authenticated"):
            return
        status = result.get("status_code")
        definitive = status in (401, 403) or (status is not None and 200 <= status < 300)
        if not definitive:
            self.logger.warning(
                "Could not verify Jira credentials (probe failed: %s); " "continuing unverified.",
                result.get("error"),
            )
            return
        raise JiraAuthError(
            f"Jira rejected the configured credentials for "
            f"{self.server_url!r} (auth_type={self.auth_type}): "
            f"{result.get('error')}"
        )

    async def _probe_myself(self) -> dict[str, Any]:
        """Probe ``/myself``; raise on a definitive authentication failure.

        Used by :meth:`search_issues` / :meth:`get_projects` when an empty
        result page is not proof of an empty scope — Jira Cloud's silent
        ``AUTHENTICATED_FAILED`` trap (`jiratoolkit.py:2257-2266`).

        Raises:
            JiraAuthError: When the probe reveals the session is not
                authenticated.
        """
        result = await asyncio.to_thread(self._probe_auth_sync)
        if not result.get("authenticated"):
            raise JiraAuthError(
                "Jira authentication probe failed"
                + (
                    f" (status={result.get('status_code')}, " f"seraph={result.get('seraph_login_reason')})"
                    if result.get("status_code") is not None
                    else ""
                )
                + f": {result.get('error') or 'unknown error'}. An empty "
                "result set was not trusted as proof of an empty scope."
            )
        return result

    async def verify_auth(self) -> dict[str, Any]:
        """Verify the interface is authenticated against Jira. Never raises.

        Performs a raw ``GET /rest/api/{2,3}/myself`` so the Atlassian
        ``X-Seraph-Loginreason`` header is inspected — this catches the
        silent-auth-failure case where the API still returns HTTP 200 but
        serves anonymous content.

        Returns:
            A result dict with at least ``authenticated: bool``.
        """
        await self._ensure_client()
        return await asyncio.to_thread(self._probe_auth_sync)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_issue(self, key: str, *, fields: str | None = None, expand: str | None = None) -> dict[str, Any]:
        """Fetch a single raw issue payload by key.

        Args:
            key: Issue key, e.g. ``"NAV-9372"``.
            fields: Comma-separated field list, or ``None`` for the
                client's default.
            expand: Comma-separated expand list — pass
                ``"renderedFields,changelog"`` to get HTML descriptions and
                the changelog in one call.

        Returns:
            The raw issue dict (``Issue.raw``).
        """
        client = await self._ensure_client()

        def _run() -> dict[str, Any]:
            issue_obj = client.issue(key, fields=fields, expand=expand)
            raw = getattr(issue_obj, "raw", None)
            if isinstance(raw, dict):
                return raw
            return {
                "id": getattr(issue_obj, "id", None),
                "key": getattr(issue_obj, "key", None),
            }

        return await asyncio.to_thread(_run)

    async def search_issues(
        self,
        jql: str,
        *,
        fields: str | None = None,
        expand: str | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw issue dicts matching ``jql``, paging until exhausted.

        Deployment-aware pagination (FEAT-454 follow-up): Jira Cloud's
        offset-based ``/search`` endpoint is gone — pycontribs delegates
        ``search_issues(startAt=0)`` to the cursor-based
        ``enhanced_search_issues`` and *raises* for any ``startAt > 0``
        (`jira/client.py:3629-3640`). That response carries no ``total``
        either, so an offset loop silently stopped after the first page
        (exactly ``page_size`` issues). On Cloud this therefore follows
        ``nextPageToken``; on Server/DC it keeps the ``startAt`` loop.

        An empty first page is not trusted as proof of an empty scope
        (the Jira Cloud ``AUTHENTICATED_FAILED`` trap) — it triggers a
        ``/myself`` probe, which raises on a definitive rejection.

        Args:
            jql: JQL scope.
            fields: Comma-separated field list, or ``None`` for all.
            expand: Comma-separated expand list.
            page_size: Page size for each underlying search call.

        Yields:
            Raw issue dicts, one per matching issue.
        """
        client = await self._ensure_client()

        # `_is_cloud` reads the `deploymentType` captured at construction
        # time (`jira/client.py:658-667`) — a plain attribute read, no I/O.
        # A fake/stubbed client without it degrades to the Server path.
        if bool(getattr(client, "_is_cloud", False)):
            async for raw in self._search_issues_cloud(
                client,
                jql,
                fields=fields,
                expand=expand,
                page_size=page_size,
            ):
                yield raw
            return

        start_at = 0
        while True:
            page = await asyncio.to_thread(
                client.search_issues,
                jql,
                startAt=start_at,
                maxResults=page_size,
                fields=fields,
                expand=expand,
                json_result=True,
            )
            issues = (page or {}).get("issues") or []
            if not issues:
                if start_at == 0:
                    await self._probe_myself()
                return
            for raw in issues:
                yield raw
            start_at += len(issues)
            total = (page or {}).get("total")
            if total is not None:
                if start_at >= total:
                    return
            # A missing `total` must NOT be read as "we are done" (that is
            # what truncated Cloud sweeps at exactly one page) — page on
            # until a short page proves exhaustion. Only when `total` is
            # absent: a Server/DC instance may cap `maxResults` below the
            # requested page size, so a short page alone proves nothing.
            elif len(issues) < page_size:
                return

    async def _search_issues_cloud(
        self,
        client: Any,
        jql: str,
        *,
        fields: str | None,
        expand: str | None,
        page_size: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """Cursor-paginate Jira Cloud's ``/search/jql`` endpoint.

        Args:
            client: The resolved pycontribs ``JIRA`` client.
            jql: JQL scope.
            fields: Comma-separated field list, or ``None`` for all.
            expand: Comma-separated expand list.
            page_size: Page size for each underlying search call.

        Yields:
            Raw issue dicts, one per matching issue.

        Raises:
            JiraAuthError: When the first page is empty and the
                ``/myself`` probe reveals an unauthenticated session.
        """
        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        first_page = True
        while True:
            page = await asyncio.to_thread(
                client.enhanced_search_issues,
                jql,
                nextPageToken=next_page_token,
                maxResults=page_size,
                fields=fields,
                expand=expand,
                json_result=True,
            )
            issues = (page or {}).get("issues") or []
            if not issues:
                if first_page:
                    await self._probe_myself()
                return
            for raw in issues:
                yield raw
            first_page = False

            if (page or {}).get("isLast") is True:
                return
            next_page_token = (page or {}).get("nextPageToken")
            if not next_page_token:
                return
            if next_page_token in seen_tokens:
                # A non-advancing cursor would loop forever. It must RAISE,
                # not return: a silent stop here is indistinguishable from
                # "scope exhausted", which is precisely how the offset loop
                # this replaced managed to truncate a corpus and still let
                # its caller record a complete-looking watermark.
                raise RuntimeError(
                    f"Jira returned a repeated nextPageToken for JQL {jql!r} "
                    f"after {len(seen_tokens) + 1} page(s) — refusing to treat "
                    "a non-advancing cursor as the end of the scope."
                )
            seen_tokens.add(next_page_token)

    async def approximate_issue_count(self, jql: str) -> int | None:
        """Return Jira Cloud's approximate issue count for ``jql``.

        A **canary, never a gate**: the endpoint is explicitly approximate,
        Cloud-only, and this method swallows every failure — callers use it
        to notice a sweep that came up short (the truncated-pagination
        class of bug), not to decide correctness.

        Args:
            jql: JQL scope.

        Returns:
            The approximate count, or ``None`` when the deployment does not
            offer the endpoint or the call failed.
        """
        client = await self._ensure_client()
        if not bool(getattr(client, "_is_cloud", False)):
            return None
        counter = getattr(client, "approximate_issue_count", None)
        if counter is None:
            return None
        try:
            count = await asyncio.to_thread(counter, jql)
        except Exception as exc:  # noqa: BLE001 — a canary must never raise
            self.logger.debug("approximate_issue_count failed for %r: %s", jql, exc)
            return None
        return count if isinstance(count, int) else None

    async def configure_connection_pool(self, size: int) -> None:
        """Right-size the underlying ``requests`` connection pool.

        pycontribs never mounts an adapter of its own, so the session
        inherits ``requests``' default ``pool_maxsize=10``. Driving more
        concurrent reads than that (see the sweep's ``concurrency``) makes
        every overflow discard its connection and pay a fresh TLS
        handshake. Mounting a right-sized ``HTTPAdapter`` does not disturb
        the library's retry handling, which lives in ``ResilientSession``,
        not in the adapter.

        A no-op for ``size <= 10`` (the default pool already covers it),
        and for any client without a mountable session.

        Args:
            size: Peak number of concurrent requests to size the pool for.
        """
        if size <= 10:
            return
        client = await self._ensure_client()
        session = getattr(client, "_session", None)
        if session is None or not hasattr(session, "mount"):
            return
        from requests.adapters import HTTPAdapter

        adapter = HTTPAdapter(pool_connections=size, pool_maxsize=size)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        self.logger.debug("Sized the Jira connection pool for %d concurrent requests.", size)

    async def get_changelog(self, key: str, page_size: int = 100) -> list[dict[str, Any]]:
        """Fetch the full changelog for an issue, paging as needed.

        Mirrors ``JiraToolkit._get_full_changelog`` (`jiratoolkit.py:1314`).

        Args:
            key: Issue key.
            page_size: Page size for each underlying changelog call.

        Returns:
            A flat list of raw changelog history entries.
        """
        client = await self._ensure_client()

        def _fetch_page(start_at: int) -> dict[str, Any]:
            # client._get_json is pycontribs' own documented internal
            # accessor for endpoints it does not wrap publicly; mirrors
            # jiratoolkit.py:1321.
            return client._get_json(
                f"issue/{key}/changelog",
                params={"startAt": start_at, "maxResults": page_size},
            )

        start_at = 0
        all_entries: list[dict[str, Any]] = []
        while True:
            page = await asyncio.to_thread(_fetch_page, start_at)
            values = page.get("values") or page.get("histories") or []
            if not values:
                break
            all_entries.extend(values)

            is_last = page.get("isLast")
            total = page.get("total")
            max_results = page.get("maxResults", page_size)
            cur_start = page.get("startAt", start_at)

            if is_last is True:
                break
            if total is not None and (cur_start + max_results) >= total:
                break
            start_at = cur_start + max_results

        return all_entries

    async def get_projects(self) -> list[dict[str, Any]]:
        """List all accessible projects.

        An empty result is probed via ``/myself`` before being trusted,
        for the same reason as :meth:`search_issues`.

        Returns:
            A list of ``{"id", "key", "name"}`` dicts.
        """
        client = await self._ensure_client()

        def _run():
            return client.projects()

        projs = await asyncio.to_thread(_run)
        project_list = [{"id": p.id, "key": p.key, "name": p.name} for p in projs]
        if project_list:
            return project_list
        await self._probe_myself()
        return []

    async def get_remote_links(self, key: str) -> list[dict[str, Any]]:
        """Fetch raw remote-link entries for an issue.

        Remote links come from a separate endpoint
        (``/rest/api/2/issue/{key}/remotelink``), not from ``fields``.

        Args:
            key: Issue key.

        Returns:
            A list of raw remote-link dicts (each ``RemoteLink.raw``).
        """
        client = await self._ensure_client()

        def _run():
            return client.remote_links(key)

        links = await asyncio.to_thread(_run)
        return [getattr(link, "raw", None) or {} for link in links]

    # ------------------------------------------------------------------
    # JiraToolkit delegation seam (TASK-2402, G1) — thin, object-returning
    # transport primitives. Unlike get_issue()/get_projects() above (which
    # project straight to dicts for the sweep), these hand back raw
    # pycontribs objects so JiraToolkit can keep applying its own existing
    # projection (_issue_to_dict) unchanged, preserving byte-identical
    # tool output.
    # ------------------------------------------------------------------

    async def list_projects(self) -> list[dict[str, Any]]:
        """Raw ``client.projects()`` call — no empty-result auth probing.

        Unlike :meth:`get_projects`, this never probes ``/myself`` on an
        empty result — callers needing that guard (``JiraToolkit
        .jira_get_projects``) already have their own probe and error
        message and must keep using it unchanged.

        Returns:
            A list of ``{"id", "key", "name"}`` dicts.
        """
        client = await self._ensure_client()

        def _run():
            return client.projects()

        projs = await asyncio.to_thread(_run)
        return [{"id": p.id, "key": p.key, "name": p.name} for p in projs]

    async def fetch_issue_object(self, key: str, *, fields: str | None = None, expand: str | None = None) -> Any:
        """Fetch and return the raw pycontribs ``Issue`` object — transport only.

        Callers needing a dict apply their own projection (e.g.
        ``JiraToolkit._issue_to_dict``, which is LLM-shaped and not
        ``JiraIssue``-shaped) — this method does not project at all, so
        that projection stays byte-identical wherever it already lives.

        Args:
            key: Issue key, e.g. ``"NAV-9372"``.
            fields: Comma-separated field list, or ``None`` for the
                client's default.
            expand: Comma-separated expand list.

        Returns:
            The raw pycontribs ``Issue`` object.
        """
        client = await self._ensure_client()

        def _run():
            return client.issue(key, fields=fields, expand=expand)

        return await asyncio.to_thread(_run)

    async def fetch_issues(
        self,
        jql: str,
        *,
        fields: str | list[str] | None = None,
        expand: str | None = None,
        max_results: int | None = 100,
        page_size: int = 100,
    ) -> list[Any]:
        """Fetch raw pycontribs ``Issue`` objects for ``jql`` — transport only.

        Mirrors ``JiraToolkit.jira_search_issues``'s own pre-existing loop
        verbatim (TASK-2402, G1): Jira Cloud's current search endpoint is
        cursor- (``nextPageToken``-) based, not offset-based, so this uses
        ``enhanced_search_issues`` rather than :meth:`search_issues`
        above (which wraps the older, still-valid-for-Server/DC
        ``startAt`` API). No auth probing on an empty result — callers
        needing that guard have their own, and none of the tool paths
        this feeds currently probe empty search results either.

        Args:
            jql: JQL scope.
            fields: Comma-separated field string, a list of fields, or
                ``None`` for every field.
            expand: Comma-separated expand list.
            max_results: Cap on the number of issues to fetch; ``None``
                fetches every matching issue.
            page_size: Page size per underlying call.

        Returns:
            A list of raw pycontribs ``Issue`` objects, not projected.
        """
        client = await self._ensure_client()
        # A truthiness check on the *string* case only — matches
        # JiraToolkit's original inline `fields.split(',') if fields else
        # None` exactly, so an empty string degrades to None (every field),
        # not to `['']` (TASK-2402 adversarial review finding). A list is
        # passed through unchanged for callers that already have one.
        if isinstance(fields, str):
            field_list = fields.split(",") if fields else None
        else:
            field_list = fields

        def _run_page(page_token: str | None, current_max: int):
            return client.enhanced_search_issues(
                jql,
                maxResults=current_max,
                fields=field_list,
                expand=expand,
                nextPageToken=page_token,
            )

        all_issues: list[Any] = []
        fetched = 0
        next_page_token: str | None = None
        is_last = False
        while not is_last:
            if max_results is None:
                size = page_size
            else:
                remaining = max_results - fetched
                if remaining <= 0:
                    break
                size = min(remaining, page_size)

            result_list = await asyncio.to_thread(_run_page, next_page_token, size)
            batch = list(result_list)

            next_page_token = getattr(result_list, "nextPageToken", None)
            is_last = getattr(result_list, "isLast", True)

            if not batch:
                break
            all_issues.extend(batch)
            fetched += len(batch)

            if max_results is not None and fetched >= max_results:
                break
            if is_last or next_page_token is None:
                break

        return all_issues

    async def resolve_ac_field_id(self) -> str | None:
        """Resolve the acceptance-criteria custom-field id.

        ``JIRA_WIKI_AC_FIELD`` wins when set. Otherwise the field is
        matched by name (case-insensitive) against ``GET
        /rest/api/2/field``, and the result is cached for the lifetime of
        this instance. Never raises — a Jira instance without the field is
        normal; the renderer then omits the acceptance-criteria section
        entirely rather than emitting an empty one, so determinism holds
        either way (spec §8, resolved).

        Returns:
            The resolved custom-field id, or ``None``.
        """
        if self._ac_field_resolved:
            return self._ac_field_id

        configured = _cfg("JIRA_WIKI_AC_FIELD")
        if configured:
            self._ac_field_id = configured
            self._ac_field_resolved = True
            return self._ac_field_id

        try:
            client = await self._ensure_client()
            fields = await asyncio.to_thread(client.fields)
        except Exception as exc:  # noqa: BLE001 — degrade, never raise
            self.logger.debug("Could not resolve AC field id: %s", exc)
            self._ac_field_id = None
            self._ac_field_resolved = True
            return None

        for field in fields or []:
            name = (field.get("name") or "").strip().lower()
            if name in _AC_FIELD_NAMES:
                self._ac_field_id = field.get("id")
                self._ac_field_resolved = True
                return self._ac_field_id

        self._ac_field_id = None
        self._ac_field_resolved = True
        return None

    # ------------------------------------------------------------------
    # Pure projection (delegates to TASK-2399's parse.parse_issue)
    # ------------------------------------------------------------------

    parse_issue = staticmethod(parse_issue)
