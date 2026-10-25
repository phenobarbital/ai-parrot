"""Integration tests for the MS Teams authentication lane (FEAT-729).

The lane is assembled by hand (session store + token-exchange client +
strategy + ``register_auth_commands``); ``MSTeamsAgentWrapper`` is never
constructed here — its gate is covered by ``test_msteams_auth_gate.py``.

No live Azure or Navigator endpoint is needed: the exchange is stubbed at the
``aiohttp`` boundary and the adapter is an autospec of the installed
``BotFrameworkAdapter``. The identity-persistence test needs a real Postgres
and skips when none is reachable.
"""

from __future__ import annotations

import inspect
import os
import uuid
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from botbuilder.core import BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ActivityTypes, ChannelAccount, ConversationAccount, ResourceResponse
from botframework.connector.token_api.models import TokenResponse

from parrot.auth.token_exchange import TokenExchangeClient
from parrot.integrations.msteams.auth import MSTeamsAuthStrategy, MSTeamsSessionStore, user_key
from parrot.integrations.msteams.commands import MSTeamsCommandRouter
from parrot.integrations.msteams.commands.auth_commands import register_auth_commands

# Constants mirror sdd/state/FEAT-729/poc/ (the recorded 200 exchange run).
TEAMS_OID = "4e2aa0ea-56b8-49fe-85cf-05e97d479ba6"
TENANT_ID = "af176793-abc4-423e-8fab-dfc4e2bf8b9d"
NAV_USER_ID = "35"
CONNECTION = "graph-sso"
AUTH_URL = "https://nav.example.test/api/v1/login"
GRAPH_TOKEN = "graph-access-token-SECRET"


@pytest.fixture
def teams_activity() -> Activity:
    """Activity with aad_object_id, tenant and a Teams-scoped from id."""
    return Activity(
        type=ActivityTypes.message,
        text="/login",
        from_property=ChannelAccount(id="29:teams-scoped-id", name="J Lara", aad_object_id=TEAMS_OID),
        recipient=ChannelAccount(id="28:bot", name="bot"),
        conversation=ConversationAccount(id="19:conv@thread.tacv2", conversation_type="personal"),
        channel_data={"tenant": {"id": TENANT_ID}},
        service_url="https://smba.example.test/",
    )


@pytest.fixture
def fake_adapter() -> MagicMock:
    """Autospec of the installed BotFrameworkAdapter — signatures cannot drift."""
    adapter = create_autospec(BotFrameworkAdapter, instance=True)
    # Only set results on the autospec'd methods — never replace them, or the
    # real signatures (the point of this fake) are lost.
    adapter.get_user_token.return_value = TokenResponse(connection_name=CONNECTION, token=GRAPH_TOKEN)
    adapter.exchange_token.return_value = TokenResponse(connection_name=CONNECTION, token=GRAPH_TOKEN)
    adapter.get_oauth_sign_in_link.return_value = "https://signin.example.test/link"
    adapter.send_activities.side_effect = lambda ctx, acts: [ResourceResponse(id="1") for _ in acts]
    return adapter


@pytest.fixture
def exchange_response_200() -> Dict[str, Any]:
    """The PoC's real 200 body shape, redacted."""
    return {
        "user_id": int(NAV_USER_ID),
        "username": "jlara@trocglobal.com",
        "email": "jlara@trocglobal.com",
        "token": "navigator-session-token-SECRET",
        "auth_method": "basic",
        "auth_origin": "azure",
        "provider_user_id": TEAMS_OID,
        "external_expires_at": "2099-01-01T00:00:00+00:00",
    }


class _FakeResponse:
    def __init__(self, status: int, body: Dict[str, Any]) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def json(self) -> Dict[str, Any]:
        return self._body

    async def text(self) -> str:
        return str(self._body)


class _FakeSession:
    """Stands in for ``aiohttp.ClientSession`` and records every POST."""

    calls: List[Dict[str, Any]] = []
    status = 200
    body: Dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        type(self).calls.append({"url": url, **kwargs})
        return _FakeResponse(type(self).status, type(self).body)


@pytest.fixture
def navigator(exchange_response_200):
    """Patch the aiohttp boundary of the exchange client; yield the recorded calls."""
    _FakeSession.calls = []
    _FakeSession.status = 200
    _FakeSession.body = exchange_response_200
    with patch("parrot.auth.token_exchange.aiohttp.ClientSession", _FakeSession):
        yield _FakeSession


@pytest.fixture
def lane(fake_adapter):
    """Store + strategy + a router with /login /logout /whoami registered."""
    store = MSTeamsSessionStore("assistant")
    strategy = MSTeamsAuthStrategy(
        config=SimpleNamespace(oauth_connection_name=CONNECTION),
        store=store,
        exchange=TokenExchangeClient(AUTH_URL),
    )
    router = MSTeamsCommandRouter()
    register_auth_commands(router, strategy)
    return SimpleNamespace(store=store, strategy=strategy, router=router)


def _replies(adapter: MagicMock) -> List[str]:
    """Plain-text replies sent through the adapter so far."""
    texts: List[str] = []
    for call in adapter.send_activities.await_args_list:
        for activity in call.args[1]:
            if activity.text:
                texts.append(activity.text)
    return texts


class TestLoginEndToEnd:
    @pytest.mark.asyncio
    async def test_login_command_end_to_end(self, teams_activity, fake_adapter, navigator, lane, caplog):
        """/login -> token -> exchange -> session -> /whoami reports the nav id."""
        caplog.set_level("DEBUG")
        context = TurnContext(fake_adapter, teams_activity)

        assert await lane.router.try_dispatch("/login", context) is True
        assert any(NAV_USER_ID in text for text in _replies(fake_adapter))

        # The exchange hit Navigator with the TokenExchangeAuth method and the Graph token.
        assert len(navigator.calls) == 1
        call = navigator.calls[0]
        assert call["url"] == AUTH_URL
        assert call["headers"]["X-Auth-Method"] == "TokenExchangeAuth"
        assert call["json"]["token"] == GRAPH_TOKEN
        assert call["json"]["provider"] == "azure"

        session = await lane.store.get_or_create(context)
        assert session.authenticated is True
        assert session.nav_user_id == NAV_USER_ID
        # The feature's core claim: the identity Navigator resolved IS the Entra oid of the Teams user.
        assert session.metadata["provider_user_id"] == TEAMS_OID
        assert session.metadata["provider_user_id"] == teams_activity.from_property.aad_object_id
        assert session.user_key == TEAMS_OID == user_key(context)
        assert session.tenant_id == TENANT_ID

        fake_adapter.send_activities.reset_mock()
        whoami = TurnContext(fake_adapter, teams_activity)
        assert await lane.router.try_dispatch("/whoami", whoami) is True
        reply = " ".join(_replies(fake_adapter))
        assert NAV_USER_ID in reply
        assert "jlara@trocglobal.com" in reply
        assert len(navigator.calls) == 1  # /whoami triggered no second exchange

        # No token value reaches a reply or a log record.
        for secret in (GRAPH_TOKEN, "navigator-session-token-SECRET"):
            assert secret not in reply
            assert secret not in caplog.text

    @pytest.mark.asyncio
    async def test_login_unprovisioned_user_gets_no_signin_card(self, teams_activity, fake_adapter, navigator, lane):
        """A 401 'user not found' from Navigator ends in the 'not provisioned' reply."""
        navigator.status = 401
        navigator.body = {"error": "user_not_found"}
        context = TurnContext(fake_adapter, teams_activity)

        assert await lane.router.try_dispatch("/login", context) is True

        assert any("not provisioned" in text for text in _replies(fake_adapter))
        fake_adapter.get_oauth_sign_in_link.assert_not_awaited()
        session = await lane.store.get_or_create(context)
        assert session.authenticated is False
        assert session.metadata["auth_reason"] == "user_not_found"


class TestSsoInvoke:
    @pytest.mark.asyncio
    async def test_signin_token_exchange_invoke(self, teams_activity, fake_adapter, navigator, lane):
        """A signin/tokenExchange invoke routes to exchange_token and completes."""
        fake_adapter.get_user_token.return_value = None  # nothing cached yet
        invoke = teams_activity.deserialize(teams_activity.serialize())
        invoke.type = ActivityTypes.invoke
        invoke.name = "signin/tokenExchange"
        invoke.text = None
        invoke.value = {"id": "x", "connectionName": CONNECTION, "token": "teams-sso-token-SECRET"}
        context = TurnContext(fake_adapter, invoke)

        session = await lane.strategy.ensure_authenticated(context)

        fake_adapter.exchange_token.assert_awaited_once()
        args = fake_adapter.exchange_token.await_args.args
        assert args[1] == CONNECTION
        assert args[2] == teams_activity.from_property.id  # channel user id (from.id), not the oid
        assert args[3].token == "teams-sso-token-SECRET"
        assert session.authenticated is True
        assert session.nav_user_id == NAV_USER_ID
        assert len(navigator.calls) == 1

    @pytest.mark.asyncio
    async def test_signout_clears_session_even_when_adapter_fails(self, teams_activity, fake_adapter, navigator, lane):
        """/logout clears the stored session although the Token Service call raises."""
        context = TurnContext(fake_adapter, teams_activity)
        await lane.strategy.ensure_authenticated(context)
        fake_adapter.sign_out_user.side_effect = RuntimeError("token service down")

        assert await lane.router.try_dispatch("/logout", context) is True

        fresh = await lane.store.get_or_create(TurnContext(fake_adapter, teams_activity))
        assert fresh.authenticated is False


class TestFakeAdapterFidelity:
    """AC-4: the fake mirrors the installed BotFrameworkAdapter's signatures."""

    @pytest.mark.parametrize(
        "method",
        ["get_user_token", "exchange_token", "get_oauth_sign_in_link", "sign_out_user", "send_activities"],
    )
    def test_signature_matches_installed_adapter(self, fake_adapter, method):
        real = list(inspect.signature(getattr(BotFrameworkAdapter, method)).parameters)[1:]  # drop self
        fake = list(inspect.signature(getattr(fake_adapter, method)).parameters)
        assert fake == real

    @pytest.mark.asyncio
    async def test_fake_rejects_calls_the_real_adapter_would_reject(self, fake_adapter):
        with pytest.raises(TypeError):
            await fake_adapter.get_oauth_sign_in_link()  # missing required arguments


# ---------------------------------------------------------------------------
# Jira OAuth callback -> auth.user_identities (needs a real Postgres)
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE auth.user_identities (
    identity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id bigint NOT NULL,
    auth_provider varchar,
    auth_data jsonb,
    attributes jsonb,
    created_at timestamptz,
    provider_user_id varchar,
    scopes jsonb,
    access_token bytea,
    refresh_token bytea,
    id_token bytea,
    token_type varchar,
    expires_at timestamptz,
    refreshed_at timestamptz,
    enabled boolean DEFAULT true,
    key_version integer,
    display_name varchar,
    title varchar,
    nickname varchar,
    email varchar,
    phone varchar,
    short_bio text,
    avatar text
);
CREATE UNIQUE INDEX uq_user_identities_provider_account
    ON auth.user_identities (user_id, auth_provider, provider_user_id)
    WHERE provider_user_id IS NOT NULL;
"""


class _SingleConnPool:
    """Pool facade over one connection so every write shares the test transaction."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def acquire(self) -> "_SingleConnPool._Ctx":
        return _SingleConnPool._Ctx(self._conn)

    class _Ctx:
        def __init__(self, conn: Any) -> None:
            self._conn = conn

        def __await__(self):
            async def _self():
                return self

            return _self().__await__()

        async def __aenter__(self) -> Any:
            return self._conn

        async def __aexit__(self, *exc: Any) -> bool:
            return False


def _dsn() -> str | None:
    dsn = os.environ.get("IDENTITY_PG_DSN")
    if dsn:
        return dsn
    try:
        from parrot.conf import default_dsn

        return default_dsn or None
    except Exception:  # noqa: BLE001
        return None


@pytest.fixture
async def authdb_pool() -> AsyncIterator[_SingleConnPool]:
    """One asyncdb connection inside a transaction that is always rolled back."""
    dsn = _dsn()
    if not dsn:
        pytest.skip("no Postgres DSN (set IDENTITY_PG_DSN)")
    try:
        from asyncdb import AsyncDB

        db = AsyncDB("pg", dsn=dsn, timeout=10)
        await db.connection()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres unreachable: {exc}")
    raw = db.engine()
    exists = await raw.fetchval("SELECT to_regclass('auth.user_identities') IS NOT NULL")
    has_index = await raw.fetchval(
        "SELECT count(*) FROM pg_indexes WHERE schemaname='auth' "
        "AND tablename='user_identities' AND indexdef LIKE '%provider_user_id%'"
    )
    if exists and not has_index:
        await db.close()
        pytest.skip("auth.user_identities predates navigator-auth 0.28.8")
    tx = raw.transaction()
    await tx.start()
    if not exists:
        await raw.execute(_SCHEMA_DDL)  # transactional DDL: the rollback removes it
    try:
        yield _SingleConnPool(db)
    finally:
        await tx.rollback()
        await db.close()


class TestJiraCallbackRegression:
    @pytest.mark.asyncio
    async def test_jira_callback_persists_identity(self, authdb_pool):
        """handle_msteams_jira_callback leaves a real row (42P10 regression)."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback
        from parrot.services.identity_mapping import IdentityMappingService

        service = IdentityMappingService(authdb_pool)
        nav_user = str(9_000_000_000 + uuid.uuid4().int % 1_000_000_000)
        request = MagicMock()
        request.rel_url.query = {}
        request.app = {"identity_mapping_service": service}
        token_set = SimpleNamespace(
            display_name="J Lara", email="jlara@trocglobal.com", site_url="https://x.atlassian.net"
        )
        # The real shape: ``user_id`` is the Teams AAD object id (a GUID), and
        # the navigator-auth bigint rides in ``extra["nav_user_id"]``.
        state = {
            "user_id": TEAMS_OID,
            "extra": {
                "nav_user_id": nav_user,
                "conversation_reference": {"conversation": {"tenantId": TENANT_ID}},
            },
        }

        response = await handle_msteams_jira_callback(request, token_set, state)

        assert "could not be saved" not in response.text.lower()
        row = await service.get_identity(nav_user, "msteams")
        assert row is not None
        assert row["provider_user_id"] == TEAMS_OID
        assert row["auth_data"]["aad_object_id"] == TEAMS_OID
        assert row["email"] == "jlara@trocglobal.com"
        assert row["auth_data"]["tenant_id"] == TENANT_ID

    @pytest.mark.asyncio
    async def test_jira_callback_without_nav_id_writes_nothing(self, authdb_pool):
        """A GUID-only state must not reach the bigint cast (issue:187ce3fe3b93)."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback
        from parrot.services.identity_mapping import IdentityMappingService

        service = IdentityMappingService(authdb_pool)
        request = MagicMock()
        request.rel_url.query = {}
        request.app = {"identity_mapping_service": service}
        token_set = SimpleNamespace(
            display_name="J Lara", email="jlara@trocglobal.com", site_url="https://x.atlassian.net"
        )
        state = {
            "user_id": TEAMS_OID,
            "extra": {"conversation_reference": {"conversation": {"tenantId": TENANT_ID}}},
        }

        # Counted, not asserted absent: the table is the deployment's real one
        # and may already hold rows for this oid from an earlier session.
        # Queried on provider_user_id, since looking the GUID up as a user_id
        # is the very bigint cast this test exists to keep out of the path.
        async def _rows_for_oid() -> int:
            async with authdb_pool.acquire() as conn:
                return await conn.engine().fetchval(
                    "SELECT count(*) FROM auth.user_identities WHERE provider_user_id = $1",
                    TEAMS_OID,
                )

        before = await _rows_for_oid()
        response = await handle_msteams_jira_callback(request, token_set, state)

        # Nothing was expected to be written, so the page carries no warning...
        assert "could not be saved" not in response.text.lower()
        # ...and no new row appeared.
        assert await _rows_for_oid() == before
