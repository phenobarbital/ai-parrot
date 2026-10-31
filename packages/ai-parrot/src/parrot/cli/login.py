"""`parrot login` / `logout` and the 0600 login file (FEAT-774 M1). Never logs token material."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import fcntl
import json
import logging
import os
import pwd
import stat
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import aiohttp
import click
from pydantic import BaseModel, Field

from parrot.auth.oauth2.device_code import (
    DeviceCodeError,
    discover_authorization_server,
    make_pkce_pair,
    poll_device_token,
    request_device_authorization,
)

logger = logging.getLogger(__name__)
DEFAULT_LOGIN_PATH = Path("~/.parrot/login.json")
DEFAULT_CLIENT_ID = "parrot-cli"
DEFAULT_SCOPES = ("openid", "profile", "email")
CACHE_FILENAME = "connections.cache"  # TASK-4973's ConnectionCache lives next to the login file


class LoginFileError(RuntimeError):
    """Login file unreadable, wrong owner/mode, or a symlink (fail closed)."""


class LoginExpired(RuntimeError):
    """The refresh token was rejected (invalid_grant); run `parrot login` again."""


class LoginPrerequisiteError(RuntimeError):
    """navigator-auth is missing the device endpoint or the `parrot-cli` client (AC-2)."""


class LoginRecord(BaseModel):
    """Contents of ~/.parrot/login.json (0600). Never logged."""

    server_url: str
    client_id: str = DEFAULT_CLIENT_ID
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_at: float
    scopes: List[str] = Field(default_factory=list)
    user_id: str
    email: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    cache_key: str
    issued_at: float


class LoginStore:
    """Atomic, locked, 0600 store for one login record.

    Args:
        path: Login file path; defaults to ``PARROT_LOGIN_FILE`` or ``~/.parrot/login.json``.
        expected_uid: Required owner for every load when reading another user's record.
        read_only: Never write, lock or delete anything next to the login file. A process
            reading another user's login (agentd) must never touch that user's directory.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        expected_uid: Optional[int] = None,
        read_only: bool = False,
    ) -> None:
        raw = path or os.environ.get("PARROT_LOGIN_FILE") or DEFAULT_LOGIN_PATH
        self.path = Path(raw).expanduser()
        self.expected_uid = expected_uid
        self.read_only = read_only

    @classmethod
    def for_uid(cls, uid: int, *, read_only: bool = False) -> "LoginStore":
        """``pwd.getpwuid(uid).pw_dir / .parrot/login.json`` owned by ``uid`` (agentd, TASK-4979)."""
        return cls(Path(pwd.getpwuid(uid).pw_dir) / ".parrot" / "login.json", expected_uid=uid, read_only=read_only)

    @property
    def cache_path(self) -> Path:
        """Return the connection-cache path adjacent to the login file."""
        return self.path.with_name(CACHE_FILENAME)

    @property
    def lock_path(self) -> Path:
        """Return the sidecar lock path used across atomic replacements."""
        return self.path.with_name(self.path.name + ".lock")

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold an exclusive lock on the 0600 sidecar lock file (never through a symlink)."""
        if self.read_only:
            raise LoginFileError(f"login store {self.path} is read-only")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise LoginFileError(f"lock file {self.lock_path} cannot be opened safely") from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def load_optional(self, *, expected_uid: Optional[int] = None) -> Optional[LoginRecord]:
        """Load a valid login record, or return ``None`` when the file is absent.

        Args:
            expected_uid: Required file owner when loading another user's record;
                defaults to the store's own ``expected_uid``.

        Returns:
            The validated login record, or ``None`` when the path does not exist.

        Raises:
            LoginFileError: The path is unsafe, unreadable, or contains invalid data.
        """
        if expected_uid is None:
            expected_uid = self.expected_uid
        flags = os.O_RDONLY | os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LoginFileError(f"login file {self.path} cannot be opened safely") from exc

        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise LoginFileError(f"login file {self.path} is not a regular file")
            if file_stat.st_mode & 0o077:
                raise LoginFileError(f"login file {self.path} must not be accessible by group or other users")
            if expected_uid is not None and file_stat.st_uid != expected_uid:
                raise LoginFileError(f"login file {self.path} is not owned by uid {expected_uid}")
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                fd = -1
                payload = json.load(handle)
            return LoginRecord.model_validate(payload)
        except LoginFileError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise LoginFileError(f"login file {self.path} is invalid") from exc
        finally:
            if fd >= 0:
                os.close(fd)

    def save(self, record: LoginRecord) -> None:
        """Atomically write a login record under the lock file with mode 0600."""
        with self._locked():
            fd, temporary_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp")
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    fd = -1
                    json.dump(record.model_dump(mode="json"), handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, self.path)
                os.chmod(self.path, 0o600)
            except BaseException:
                if fd >= 0:
                    os.close(fd)
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise

    def delete(self) -> bool:
        """Remove the login file; return whether a file was deleted."""
        with self._locked():
            try:
                self.path.unlink()
                return True
            except FileNotFoundError:
                return False


def _json_object(payload: Any, *, operation: str) -> Dict[str, Any]:
    """Validate an OAuth response object without exposing its contents."""
    if not isinstance(payload, dict):
        raise DeviceCodeError("invalid_response", f"{operation} returned an invalid response")
    return payload


async def refresh_login(record: LoginRecord, session: aiohttp.ClientSession) -> LoginRecord:
    """Refresh a login and preserve a rotated refresh token.

    Args:
        record: Existing login record with a refresh token.
        session: Open HTTP client session.

    Returns:
        A copy of the record containing the refreshed token values.

    Raises:
        LoginExpired: The record has no refresh token or the server rejects it.
        DeviceCodeError: Discovery or the refresh response is invalid.
    """
    if not record.refresh_token:
        raise LoginExpired("no refresh token; run `parrot login` again")
    meta = await discover_authorization_server(session, record.server_url)
    token_url = meta.get("token_endpoint")
    if not isinstance(token_url, str) or not token_url:
        raise DeviceCodeError("invalid_metadata", "server metadata has no token_endpoint")
    try:
        async with session.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": record.refresh_token,
                "client_id": record.client_id,
            },
        ) as response:
            status = response.status
            body = _json_object(await response.json(), operation="token refresh")
    except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError) as exc:
        raise DeviceCodeError("refresh_failed", "token refresh failed") from exc

    if body.get("error") == "invalid_grant":
        raise LoginExpired("refresh token was rejected; run `parrot login` again")
    if status != 200:
        raise DeviceCodeError("refresh_failed", f"token refresh failed with HTTP {status}")
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise DeviceCodeError("invalid_response", "token refresh response has no access_token")
    refresh_token = body.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        refresh_token = record.refresh_token
    try:
        expires_in = float(body.get("expires_in", 3600))
    except (TypeError, ValueError) as exc:
        raise DeviceCodeError("invalid_response", "token refresh response has invalid expires_in") from exc
    return record.model_copy(
        update={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + expires_in,
        }
    )


async def _login_flow(server: str, client_id: str, scopes: List[str], open_browser: bool) -> LoginRecord:
    """Complete device authorization and return the resulting login record."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        try:
            meta = await discover_authorization_server(session, server)
        except DeviceCodeError as exc:
            raise LoginPrerequisiteError(f"cannot discover the authorization server at {server}: {exc}") from exc
        device_url = meta.get("device_authorization_endpoint")
        if not isinstance(device_url, str) or not device_url:
            raise LoginPrerequisiteError("server metadata has no device_authorization_endpoint (enable Oauth2Provider)")
        verifier, challenge = make_pkce_pair()
        try:
            authorization = await request_device_authorization(
                session,
                device_url,
                client_id=client_id,
                scopes=scopes,
                code_challenge=challenge,
            )
        except DeviceCodeError as exc:
            if exc.code in {"invalid_client", "unauthorized_client"}:
                raise LoginPrerequisiteError(
                    f"server does not authorize the {client_id} public client for device login"
                ) from exc
            raise

        click.echo(f"Open {authorization.verification_uri}", err=True)
        click.echo(f"Enter code: {authorization.user_code}", err=True)
        if open_browser:
            webbrowser.open(authorization.verification_uri_complete or authorization.verification_uri)

        token_url = meta.get("token_endpoint")
        if not isinstance(token_url, str) or not token_url:
            raise DeviceCodeError("invalid_metadata", "server metadata has no token_endpoint")
        token = await poll_device_token(
            session,
            token_url,
            client_id=client_id,
            authorization=authorization,
            code_verifier=verifier,
        )
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise DeviceCodeError("invalid_response", "device token response has no access_token")
        token_type = token.get("token_type", "Bearer")
        if not isinstance(token_type, str) or not token_type:
            raise DeviceCodeError("invalid_response", "device token response has invalid token_type")

        userinfo_url = meta.get("userinfo_endpoint")
        if not isinstance(userinfo_url, str) or not userinfo_url:
            raise DeviceCodeError("invalid_metadata", "server metadata has no userinfo_endpoint")
        try:
            async with session.get(userinfo_url, headers={"Authorization": f"{token_type} {access_token}"}) as response:
                if response.status != 200:
                    raise DeviceCodeError("userinfo_failed", f"userinfo request failed with HTTP {response.status}")
                identity = _json_object(await response.json(), operation="userinfo request")
        except DeviceCodeError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError) as exc:
            raise DeviceCodeError("userinfo_failed", "userinfo request failed") from exc
        user_id = identity.get("sub")
        if user_id is None or not str(user_id):
            raise DeviceCodeError("invalid_response", "userinfo response has no sub")

        now = time.time()
        try:
            expires_in = float(token.get("expires_in", 3600))
        except (TypeError, ValueError) as exc:
            raise DeviceCodeError("invalid_response", "device token response has invalid expires_in") from exc
        token_scopes = token.get("scope")
        resolved_scopes = token_scopes.replace(",", " ").split() if isinstance(token_scopes, str) else list(scopes)
        refresh_token = token.get("refresh_token")
        return LoginRecord(
            server_url=server,
            client_id=client_id,
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            token_type=token_type,
            expires_at=now + expires_in,
            scopes=resolved_scopes,
            user_id=str(user_id),
            email=identity.get("email") if isinstance(identity.get("email"), str) else None,
            cache_key=base64.urlsafe_b64encode(os.urandom(32)).decode(),
            issued_at=now,
        )


@click.command("login")
@click.option("--server", envvar="PARROT_SERVER_URL", required=True, help="AI-Parrot / navigator-auth base URL.")
@click.option("--client-id", envvar="PARROT_CLI_CLIENT_ID", default=DEFAULT_CLIENT_ID, show_default=True)
@click.option("--scopes", default=None, help="Space- or comma-separated scopes (default: openid profile email).")
@click.option("--no-browser", is_flag=True, default=False, help="Print the verification URL instead of opening it.")
def login(server: str, client_id: str, scopes: Optional[str], no_browser: bool) -> None:
    """Log in with the RFC 8628 device grant and store ~/.parrot/login.json (0600)."""
    wanted = scopes.replace(",", " ").split() if scopes else list(DEFAULT_SCOPES)
    store = LoginStore()
    try:
        record = asyncio.run(_login_flow(server, client_id, wanted, not no_browser))
    except (LoginPrerequisiteError, DeviceCodeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    store.save(record)
    record = asyncio.run(_fill_from_me(store, record))
    click.echo(f"Logged in as {record.email or record.user_id}", err=True)


async def _revoke_login(record: LoginRecord) -> None:
    """Attempt to revoke a login token without exposing or propagating failures."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            meta = await discover_authorization_server(session, record.server_url)
            revocation_url = meta.get("revocation_endpoint")
            if not isinstance(revocation_url, str) or not revocation_url:
                return
            token = record.refresh_token or record.access_token
            async with session.post(
                revocation_url,
                data={"token": token, "client_id": record.client_id},
            ) as response:
                await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError, DeviceCodeError, TypeError, ValueError):
        return


@click.command("logout")
def logout() -> None:
    """Revoke the login (best effort) and delete the login file and the connection cache."""
    store = LoginStore()
    try:
        record = store.load_optional()
    except LoginFileError:
        record = None
    if record is not None:
        asyncio.run(_revoke_login(record))
    store.delete()
    try:
        store.cache_path.unlink()
    except FileNotFoundError:
        pass


async def _fill_from_me(store: LoginStore, record: LoginRecord) -> LoginRecord:
    """Copy roles and tenant from the connections API into the login file on a best-effort basis."""
    from parrot.auth.oauth2.remote_client import ServerConnectionsClient

    try:
        async with ServerConnectionsClient(store) as client:
            who = await client.me()
    except Exception as exc:  # noqa: BLE001 -- the login itself already succeeded
        logger.warning("Could not read /api/v1/connections/me after login: %s", type(exc).__name__)
        return record
    updated = record.model_copy(update={"roles": list(who.roles), "tenant_id": who.tenant_id or record.tenant_id})
    store.save(updated)
    return updated


@click.command("whoami")
def whoami() -> None:
    """Print the Navigator identity behind the current login."""
    from parrot.auth.oauth2.remote_client import NotLoggedIn, ServerConnectionsClient, WhoAmI

    async def read_identity() -> WhoAmI:
        async with ServerConnectionsClient(LoginStore()) as client:
            return await client.me()

    try:
        identity = asyncio.run(read_identity())
    except (NotLoggedIn, LoginExpired):
        click.echo("Not logged in — run `parrot login`", err=True)
        sys.exit(1)

    click.echo(f"User ID: {identity.user_id}")
    click.echo(f"Email: {identity.email or '-'}")
    click.echo(f"Tenant: {identity.tenant_id or '-'}")
    click.echo(f"Roles: {', '.join(identity.roles) or '-'}")
