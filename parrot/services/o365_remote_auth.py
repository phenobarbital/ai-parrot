"""Utilities to manage remote Office 365 interactive login sessions."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List
from uuid import uuid4

from navconfig.logging import logging

from ..interfaces.o365 import O365Client


@dataclass
class RemoteAuthSession:
    """Metadata for a remote interactive login session."""

    session_id: str
    status: str = "pending"
    login_url: Optional[str] = None
    device_flow: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    result_summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None
    client: Optional[O365Client] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
        }
        if self.login_url:
            data["auth_url"] = self.login_url
        if self.device_flow:
            data["device_flow"] = self.device_flow
        if self.expires_at:
            data["expires_at"] = self.expires_at.isoformat() + "Z"
        if self.result_summary:
            data["result"] = self.result_summary
        if self.error:
            data["error"] = self.error
        return data


class RemoteAuthManager:
    """Manage remote Office 365 interactive login sessions."""

    def __init__(self):
        self._sessions: Dict[str, RemoteAuthSession] = {}
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger("Parrot.O365.RemoteAuth")

    async def start_session(
        self,
        *,
        credentials: Optional[Dict[str, Any]] = None,
        scopes: Optional[List[str]] = None,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a new remote interactive login session."""

        session_id = str(uuid4())
        session = RemoteAuthSession(session_id=session_id)
        async with self._lock:
            self._sessions[session_id] = session

        client = O365Client(credentials=credentials or {})
        session.client = client
        client.processing_credentials()
        client.set_auth_mode("delegated")

        loop = asyncio.get_running_loop()
        login_url_future: asyncio.Future = loop.create_future()
        device_flow_future: asyncio.Future = loop.create_future()

        def _login_callback(url: str) -> bool:
            def _set_login_url() -> None:
                session.login_url = url
                session.updated_at = datetime.utcnow()
                if not login_url_future.done():
                    login_url_future.set_result(url)

            loop.call_soon_threadsafe(_set_login_url)
            return False

        def _device_flow_callback(flow: Dict[str, Any]) -> None:
            def _set_device_flow() -> None:
                session.device_flow = {
                    "user_code": flow.get("user_code"),
                    "verification_uri": flow.get("verification_uri"),
                    "verification_uri_complete": flow.get("verification_uri_complete"),
                    "message": flow.get("message"),
                    "expires_in": flow.get("expires_in"),
                    "interval": flow.get("interval"),
                }
                if flow.get("expires_in"):
                    session.expires_at = datetime.utcnow() + timedelta(seconds=int(flow["expires_in"]))
                session.updated_at = datetime.utcnow()
                if not device_flow_future.done():
                    device_flow_future.set_result(session.device_flow)

            loop.call_soon_threadsafe(_set_device_flow)

        async def _run_login() -> None:
            try:
                result = await client.interactive_login(
                    scopes=scopes,
                    redirect_uri=redirect_uri or "http://localhost",
                    open_browser=False,
                    login_callback=_login_callback,
                    device_flow_callback=_device_flow_callback,
                )
                summary = self._summarize_result(result)
                session.result_summary = summary if summary else None
                session.status = "authorized"
                session.updated_at = datetime.utcnow()
            except Exception as exc:  # pragma: no cover - network/auth errors
                session.status = "failed"
                session.error = str(exc)
                session.updated_at = datetime.utcnow()
                self.logger.error("Remote login session %s failed: %s", session_id, exc)
            finally:
                with contextlib.suppress(Exception):
                    await client.close()
                session.client = None

        session.task = asyncio.create_task(_run_login())

        waiters = []
        if not login_url_future.done():
            waiters.append(login_url_future)
        if not device_flow_future.done():
            waiters.append(device_flow_future)

        if waiters:
            try:
                await asyncio.wait(waiters, timeout=5, return_when=asyncio.FIRST_COMPLETED)
            except Exception:  # pragma: no cover - defensive
                pass

        return session.to_dict()

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return None

        if session.status == "pending" and session.expires_at and datetime.utcnow() > session.expires_at:
            await self._expire_session(session)

        return session.to_dict()

    async def cancel_session(self, session_id: str) -> bool:
        async with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return False

        await self._finalize_session(session, status="cancelled", error="Session cancelled by user")
        return True

    async def shutdown(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())

        for session in sessions:
            await self._finalize_session(session, status=session.status)

    async def _expire_session(self, session: RemoteAuthSession) -> None:
        await self._finalize_session(
            session,
            status="expired",
            error="Authorization session expired before completion",
        )

    async def _finalize_session(
        self,
        session: RemoteAuthSession,
        *,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        if session.task and not session.task.done():
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.task
        if session.client:
            with contextlib.suppress(Exception):
                await session.client.close()
            session.client = None
        session.status = status
        session.error = error
        session.updated_at = datetime.utcnow()

    def _summarize_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        if not result:
            return summary

        if result.get("expires_on"):
            summary["expires_on"] = result["expires_on"]
        if result.get("scope"):
            summary["scope"] = result["scope"]
        if result.get("token_source"):
            summary["token_source"] = result["token_source"]

        account = result.get("account")
        if isinstance(account, dict):
            summary["account"] = {
                "home_account_id": account.get("home_account_id"),
                "environment": account.get("environment"),
                "username": account.get("username"),
            }

        claims = result.get("id_token_claims")
        if isinstance(claims, dict):
            summary["user"] = {
                "name": claims.get("name"),
                "preferred_username": claims.get("preferred_username"),
                "oid": claims.get("oid"),
                "tid": claims.get("tid"),
            }

        return summary


__all__ = ["RemoteAuthManager", "RemoteAuthSession"]
