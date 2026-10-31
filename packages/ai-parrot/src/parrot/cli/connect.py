"""`parrot connect` / `connections` / `disconnect` (FEAT-774 M6)."""

from __future__ import annotations

import asyncio
import hmac
import logging
import sys
import time
import webbrowser
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import click

from parrot.auth.oauth2.local_cache import CachedConnection, ConnectionCache, open_connection_cache
from parrot.auth.oauth2.paste import parse_pasted_redirect
from parrot.auth.oauth2.remote_client import NotLoggedIn, ServerConnectionsClient
from parrot.cli.login import LoginStore

logger = logging.getLogger(__name__)


class ConnectFailed(RuntimeError):
    """A connect attempt ended without a connection (one-line reason)."""


def _ts(value: Optional[str]) -> float:
    """Convert an optional ISO datetime to a Unix timestamp."""
    return datetime.fromisoformat(value).timestamp() if value else 0.0


def _completed_after(status: Dict[str, Any], started_at: float) -> bool:
    """Return whether a connection was touched after this attempt started."""
    return (
        status.get("status") == "connected"
        and max(_ts(status.get("connected_at")), _ts(status.get("updated_at"))) >= started_at
    )


async def _run_device_flow(
    client: ServerConnectionsClient,
    provider: str,
    *,
    open_browser: bool,
    echo: Callable[[str], None],
) -> None:
    """Run the server-mediated device flow through completion."""
    authorization = await client.device_start(provider)
    verification_uri = str(authorization["verification_uri"])
    echo(f"Enter code {authorization['user_code']} at:\n  {verification_uri}")
    if open_browser:
        webbrowser.open(str(authorization.get("verification_uri_complete") or verification_uri))

    deadline = time.monotonic() + float(authorization.get("expires_in", 600))
    interval = float(authorization.get("interval", 2.0))
    while True:
        result = await client.device_poll(provider, str(authorization["handle"]))
        status = result.get("status")
        if status == "completed":
            return
        if status in {"failed", "expired"}:
            raise ConnectFailed(str(result.get("reason") or f"device authorization {status}"))
        if status != "pending":
            raise ConnectFailed(f"unexpected device authorization status: {status or 'missing'}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ConnectFailed("device authorization expired")
        interval = float(result.get("interval", interval))
        await asyncio.sleep(min(interval, remaining))


async def run_connect(
    client: ServerConnectionsClient,
    cache: ConnectionCache,
    provider: str,
    *,
    scopes: Optional[List[str]],
    open_browser: bool,
    paste: bool,
    device: bool,
    prompt: Callable[[str], str],
    echo: Callable[[str], None],
    poll_interval_s: float = 2.0,
) -> Dict[str, Any]:
    """Connect a provider and pull its access token into the encrypted cache."""
    if device:
        await _run_device_flow(client, provider, open_browser=open_browser, echo=echo)
    else:
        attempt = await client.start_connect(provider, scopes=scopes)
        echo(f"Open this URL to connect {provider}:\n  {attempt.auth_url}")
        if open_browser:
            webbrowser.open(attempt.auth_url)

        completed = False
        if not paste:
            deadline = time.monotonic() + attempt.expires_in
            while True:
                status = await client.status(provider)
                if _completed_after(status, attempt.started_at):
                    completed = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(poll_interval_s, remaining))

        if not completed:
            code, state = parse_pasted_redirect(prompt("Paste the redirected URL"))
            if state is None or not hmac.compare_digest(state, attempt.state):
                raise ConnectFailed("state mismatch")
            await client.complete(provider, code=code, state=state)

    pulled = await client.pull_token(provider)
    await cache.put(
        CachedConnection(
            provider=provider,
            access_token=pulled.access_token,
            expires_at=pulled.expires_at,
            scopes=list(pulled.scopes),
            account_id=pulled.account_id,
            pulled_at=time.time(),
        )
    )
    return {"provider": provider, "account_id": pulled.account_id, "status": "connected"}


def _require_login(store: LoginStore) -> None:
    """Exit with the standard hint when no CLI login exists."""
    if store.load_optional() is None:
        click.echo("Not logged in — run `parrot login`", err=True)
        sys.exit(2)


def _scope_list(scopes: Optional[str]) -> Optional[List[str]]:
    """Parse a comma- or space-separated Click option."""
    return scopes.replace(",", " ").split() if scopes else None


@click.command("connect")
@click.argument("provider")
@click.option("--scopes", default=None, help="Comma- or space-separated provider scopes.")
@click.option("--no-browser", is_flag=True, default=False, help="Do not open the authorization URL.")
@click.option("--paste", is_flag=True, default=False, help="Paste the redirected URL immediately.")
@click.option("--device", is_flag=True, default=False, help="Use the provider device authorization flow.")
def connect(provider: str, scopes: Optional[str], no_browser: bool, paste: bool, device: bool) -> None:
    """Connect PROVIDER for the current CLI login."""
    store = LoginStore()
    _require_login(store)

    async def _connect() -> Dict[str, Any]:
        async with ServerConnectionsClient(store) as client:
            cache = open_connection_cache(store)
            return await run_connect(
                client,
                cache,
                provider,
                scopes=_scope_list(scopes),
                open_browser=not no_browser,
                paste=paste,
                device=device,
                prompt=lambda text: click.prompt(text, err=True),
                echo=lambda text: click.echo(text, err=True),
            )

    try:
        result = asyncio.run(_connect())
    except NotLoggedIn:
        click.echo("Not logged in — run `parrot login`", err=True)
        sys.exit(2)
    except ConnectFailed as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Connected {result['provider']} as {result['account_id'] or '-'}", err=True)


@click.command("connections")
def connections() -> None:
    """List provider connections for the current CLI login."""
    store = LoginStore()
    _require_login(store)

    async def _list_connections() -> List[Dict[str, Any]]:
        async with ServerConnectionsClient(store) as client:
            return await client.list()

    try:
        rows = asyncio.run(_list_connections())
    except NotLoggedIn:
        click.echo("Not logged in — run `parrot login`", err=True)
        sys.exit(2)
    click.echo("Provider\tStatus\tAccount\tScopes\tExpires")
    for row in rows:
        scopes = row.get("scopes_granted") or []
        click.echo(
            "\t".join(
                [
                    str(row.get("provider") or "-"),
                    str(row.get("status") or "-"),
                    str(row.get("account_id") or row.get("display_account_name") or "-"),
                    ", ".join(scopes) or "-",
                    str(row.get("expires_at") or "-"),
                ]
            )
        )


@click.command("disconnect")
@click.argument("provider")
def disconnect(provider: str) -> None:
    """Disconnect PROVIDER and remove its locally cached token."""
    store = LoginStore()
    _require_login(store)

    async def _disconnect() -> None:
        async with ServerConnectionsClient(store) as client:
            await client.disconnect(provider)
        cache = open_connection_cache(store)
        await cache.delete(provider)

    try:
        asyncio.run(_disconnect())
    except NotLoggedIn:
        click.echo("Not logged in — run `parrot login`", err=True)
        sys.exit(2)
    click.echo(f"Disconnected {provider}", err=True)
