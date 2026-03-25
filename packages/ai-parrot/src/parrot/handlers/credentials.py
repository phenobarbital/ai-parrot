"""CredentialsHandler — CRUD HTTP view for user database credentials.

Implements GET, POST, PUT, and DELETE operations for per-user database
credential management.  Credentials are:

* Validated with :class:`parrot.handlers.models.credentials.CredentialPayload`
* Saved immediately to the user session vault (Redis-backed)
* Persisted to DocumentDB asynchronously via fire-and-forget
* Encrypted at rest using :mod:`parrot.handlers.credentials_utils`

Routes (registered by :func:`setup_credentials_routes`):
    ``GET    /api/v1/users/credentials``          — list all credentials
    ``POST   /api/v1/users/credentials``          — create a credential
    ``GET    /api/v1/users/credentials/{name}``   — get single credential
    ``PUT    /api/v1/users/credentials/{name}``   — update credential
    ``DELETE /api/v1/users/credentials/{name}``   — delete credential
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from pydantic import ValidationError

from parrot.interfaces.documentdb import DocumentDb
from parrot.handlers.models.credentials import (
    CredentialDocument,
    CredentialPayload,
    CredentialResponse,
)
from parrot.handlers.credentials_utils import (
    decrypt_credential,
    encrypt_credential,
)

try:
    from navigator_session.vault.config import get_active_key_id, load_master_keys
except ImportError:
    get_active_key_id = None  # type: ignore[assignment]
    load_master_keys = None   # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]:
    """Load vault master keys from environment.

    Returns:
        Tuple of (active_key_id, active_master_key, all_master_keys).

    Raises:
        RuntimeError: If vault keys are not configured in the environment.
    """
    if load_master_keys is None or get_active_key_id is None:
        raise RuntimeError(
            "navigator_session.vault.config is not available. "
            "Ensure navigator-session is installed."
        )
    master_keys = load_master_keys()
    active_key_id = get_active_key_id()
    active_key = master_keys[active_key_id]
    return active_key_id, active_key, master_keys


@is_authenticated()
@user_session()
class CredentialsHandler(BaseView):
    """CRUD handler for user database credentials.

    Provides endpoints to create, read, update, and delete asyncdb-syntax
    database credentials.  Each user maintains their own isolated credential
    namespace identified by ``name``.

    Class Attributes:
        COLLECTION: DocumentDB collection name for credential storage.
        SESSION_PREFIX: Key prefix used in the session vault.
    """

    COLLECTION: str = "user_credentials"
    SESSION_PREFIX: str = "_credentials:"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_user_id(self) -> str:
        """Extract the authenticated user's ID from the session.

        Returns:
            User ID string.

        Raises:
            web.HTTPUnauthorized: If session is missing or user_id absent.
        """
        session = getattr(self, '_session', None)
        if not session:
            raise web.HTTPUnauthorized(reason="Session not available.")
        # navigator_auth stores identity inside session['session'] or at top level
        user_id = (
            session.get('session', {}).get('user_id')
            or session.get('user_id')
        )
        if not user_id:
            raise web.HTTPUnauthorized(reason="User ID not found in session.")
        return str(user_id)

    def _session_key(self, name: str) -> str:
        """Build the session vault key for a credential name.

        Args:
            name: Credential name.

        Returns:
            Session key string, e.g. ``_credentials:my-postgres``.
        """
        return f"{self.SESSION_PREFIX}{name}"

    def _set_session_credential(self, name: str, credential_dict: dict) -> None:
        """Store a credential dict in the session vault.

        Args:
            name: Credential name.
            credential_dict: Dict with ``driver`` and ``params`` keys.
        """
        session = getattr(self, '_session', None)
        if session is not None:
            session[self._session_key(name)] = credential_dict

    def _remove_session_credential(self, name: str) -> None:
        """Remove a credential from the session vault.

        Args:
            name: Credential name to remove.
        """
        session = getattr(self, '_session', None)
        if session is not None:
            session.pop(self._session_key(name), None)

    def _get_all_session_credentials(self) -> dict[str, dict]:
        """Collect all credentials stored in the session vault.

        Returns:
            Mapping of credential name → credential dict.
        """
        session = getattr(self, '_session', None)
        if not session:
            return {}
        prefix = self.SESSION_PREFIX
        return {
            key[len(prefix):]: val
            for key, val in session.items()
            if isinstance(key, str) and key.startswith(prefix)
        }

    # ------------------------------------------------------------------
    # GET  /api/v1/users/credentials
    # GET  /api/v1/users/credentials/{name}
    # ------------------------------------------------------------------

    async def get(self) -> web.Response:
        """Retrieve credentials for the authenticated user.

        If a ``{name}`` path parameter is present, returns a single
        :class:`CredentialResponse`.  Otherwise returns a mapping of all
        credential names to their decrypted payloads.

        Returns:
            JSON response with credential(s).

        Raises:
            404 Not Found: If the named credential does not exist.
            500 Internal Server Error: On vault or database errors.
        """
        try:
            user_id = self._get_user_id()
        except web.HTTPUnauthorized as exc:
            return self.error(exc.reason, status=401)

        name: str | None = self.request.match_info.get('name')

        try:
            _, _, master_keys = _load_vault_keys()
        except RuntimeError as exc:
            self.logger.error("Vault key loading failed: %s", exc)
            return self.error("Encryption service unavailable.", status=500)

        async with DocumentDb() as db:
            if name:
                # --- Single credential ---
                doc = await db.read_one(
                    self.COLLECTION,
                    {"user_id": user_id, "name": name},
                )
                if doc is None:
                    return self.error(
                        f"Credential '{name}' not found.", status=404
                    )
                try:
                    cred_dict = decrypt_credential(doc["credential"], master_keys)
                except Exception as exc:
                    self.logger.error(
                        "Failed to decrypt credential '%s' for user %s: %s",
                        name, user_id, exc,
                    )
                    return self.error("Failed to decrypt credential.", status=500)

                response = CredentialResponse(name=name, **cred_dict)
                return self.json_response(response.model_dump())
            else:
                # --- All credentials ---
                docs = await db.read(
                    self.COLLECTION,
                    {"user_id": user_id},
                )
                result: dict[str, Any] = {}
                for doc in docs:
                    cname = doc["name"]
                    try:
                        cred_dict = decrypt_credential(doc["credential"], master_keys)
                        resp = CredentialResponse(name=cname, **cred_dict)
                        result[cname] = resp.model_dump()
                    except Exception as exc:
                        self.logger.warning(
                            "Skipping undecryptable credential '%s': %s",
                            cname, exc,
                        )
                return self.json_response(result)

    # ------------------------------------------------------------------
    # POST  /api/v1/users/credentials
    # ------------------------------------------------------------------

    async def post(self) -> web.Response:
        """Create a new credential for the authenticated user.

        Validates the request body against :class:`CredentialPayload`,
        checks for duplicate names in DocumentDB, saves to the session vault,
        and schedules a fire-and-forget write to DocumentDB.

        Returns:
            201 Created with the :class:`CredentialResponse` payload.

        Raises:
            400 Bad Request: If the body is invalid JSON or fails validation.
            409 Conflict: If a credential with the same name already exists.
            500 Internal Server Error: On vault key or database errors.
        """
        try:
            user_id = self._get_user_id()
        except web.HTTPUnauthorized as exc:
            return self.error(exc.reason, status=401)

        try:
            body = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        try:
            payload = CredentialPayload(**body)
        except ValidationError as exc:
            return self.error(exc.errors(), status=400)

        try:
            active_key_id, active_key, _ = _load_vault_keys()
        except RuntimeError as exc:
            self.logger.error("Vault key loading failed: %s", exc)
            return self.error("Encryption service unavailable.", status=500)

        db = DocumentDb()
        try:
            await db.documentdb_connect()

            # Check for duplicate
            existing = await db.read_one(
                self.COLLECTION,
                {"user_id": user_id, "name": payload.name},
            )
            if existing is not None:
                await db.close()
                return self.error(
                    f"Credential '{payload.name}' already exists.", status=409
                )

            # Save to session vault immediately
            credential_dict = {"driver": payload.driver, "params": payload.params}
            self._set_session_credential(payload.name, credential_dict)
            self.logger.info(
                "Saved credential '%s' to session vault for user %s",
                payload.name, user_id,
            )

            # Build encrypted document
            now = datetime.now(timezone.utc)
            encrypted = encrypt_credential(credential_dict, active_key_id, active_key)
            doc = CredentialDocument(
                user_id=user_id,
                name=payload.name,
                credential=encrypted,
                created_at=now,
                updated_at=now,
            )

            # Fire-and-forget persist to DocumentDB
            db.save_background(
                self.COLLECTION,
                doc.model_dump(mode="json"),
                on_error=lambda e: self.logger.warning(
                    "Background save failed for credential '%s' (user=%s): %s",
                    payload.name, user_id, e,
                ),
            )
            self.logger.info(
                "Scheduled background save for credential '%s' (user=%s)",
                payload.name, user_id,
            )

        except Exception as exc:
            self.logger.error("POST credential failed: %s", exc)
            return self.error("Failed to create credential.", status=500)

        response = CredentialResponse(
            name=payload.name,
            driver=payload.driver,
            params=payload.params,
        )
        return self.json_response(response.model_dump(), status=201)

    # ------------------------------------------------------------------
    # PUT  /api/v1/users/credentials/{name}
    # ------------------------------------------------------------------

    async def put(self) -> web.Response:
        """Update an existing credential for the authenticated user.

        Validates the request body, verifies the credential exists, updates
        the session vault, and schedules a fire-and-forget upsert to DocumentDB.

        Returns:
            200 OK with the updated :class:`CredentialResponse`.

        Raises:
            400 Bad Request: If the body is invalid or fails validation.
            404 Not Found: If the named credential does not exist.
            500 Internal Server Error: On vault or database errors.
        """
        try:
            user_id = self._get_user_id()
        except web.HTTPUnauthorized as exc:
            return self.error(exc.reason, status=401)

        name: str | None = self.request.match_info.get('name')
        if not name:
            return self.error("Credential name is required in the URL.", status=400)

        try:
            body = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        try:
            payload = CredentialPayload(**body)
        except ValidationError as exc:
            return self.error(exc.errors(), status=400)

        try:
            active_key_id, active_key, _ = _load_vault_keys()
        except RuntimeError as exc:
            self.logger.error("Vault key loading failed: %s", exc)
            return self.error("Encryption service unavailable.", status=500)

        db = DocumentDb()
        try:
            await db.documentdb_connect()

            # Verify credential exists
            existing = await db.read_one(
                self.COLLECTION,
                {"user_id": user_id, "name": name},
            )
            if existing is None:
                await db.close()
                return self.error(
                    f"Credential '{name}' not found.", status=404
                )

            # Update session vault
            credential_dict = {"driver": payload.driver, "params": payload.params}
            self._set_session_credential(name, credential_dict)
            self.logger.info(
                "Updated credential '%s' in session vault for user %s",
                name, user_id,
            )

            # Build updated encrypted document
            now = datetime.now(timezone.utc)
            created_at = existing.get("created_at", now)
            encrypted = encrypt_credential(credential_dict, active_key_id, active_key)
            doc = CredentialDocument(
                user_id=user_id,
                name=name,
                credential=encrypted,
                created_at=created_at,
                updated_at=now,
            )

            # Fire-and-forget upsert to DocumentDB
            # Use update_one with upsert to avoid duplicate key errors
            db.save_background(
                self.COLLECTION,
                doc.model_dump(mode="json"),
                on_error=lambda e: self.logger.warning(
                    "Background update failed for credential '%s' (user=%s): %s",
                    name, user_id, e,
                ),
            )
            self.logger.info(
                "Scheduled background update for credential '%s' (user=%s)",
                name, user_id,
            )

        except Exception as exc:
            self.logger.error("PUT credential failed: %s", exc)
            return self.error("Failed to update credential.", status=500)

        response = CredentialResponse(
            name=name,
            driver=payload.driver,
            params=payload.params,
        )
        return self.json_response(response.model_dump())

    # ------------------------------------------------------------------
    # DELETE  /api/v1/users/credentials/{name}
    # ------------------------------------------------------------------

    async def delete(self) -> web.Response:
        """Delete a credential for the authenticated user.

        Verifies the credential exists, removes it from the session vault,
        and deletes it from DocumentDB.

        Returns:
            200 OK with a confirmation message.

        Raises:
            404 Not Found: If the named credential does not exist.
            500 Internal Server Error: On database errors.
        """
        try:
            user_id = self._get_user_id()
        except web.HTTPUnauthorized as exc:
            return self.error(exc.reason, status=401)

        name: str | None = self.request.match_info.get('name')
        if not name:
            return self.error("Credential name is required in the URL.", status=400)

        async with DocumentDb() as db:
            # Verify credential exists
            existing = await db.read_one(
                self.COLLECTION,
                {"user_id": user_id, "name": name},
            )
            if existing is None:
                return self.error(
                    f"Credential '{name}' not found.", status=404
                )

            # Remove from session vault
            self._remove_session_credential(name)
            self.logger.info(
                "Removed credential '%s' from session vault for user %s",
                name, user_id,
            )

            # Delete from DocumentDB
            try:
                await db.delete(
                    self.COLLECTION,
                    {"user_id": user_id, "name": name},
                )
                self.logger.info(
                    "Deleted credential '%s' from DocumentDB for user %s",
                    name, user_id,
                )
            except Exception as exc:
                self.logger.error(
                    "Failed to delete credential '%s' from DocumentDB: %s",
                    name, exc,
                )
                return self.error("Failed to delete credential.", status=500)

        return self.json_response(
            {"message": f"Credential '{name}' deleted successfully."}
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def setup_credentials_routes(app: web.Application) -> None:
    """Register credential management routes on the aiohttp application.

    Registers two routes:
    - ``/api/v1/users/credentials`` — collection-level (GET all, POST create)
    - ``/api/v1/users/credentials/{name}`` — item-level (GET one, PUT, DELETE)

    Args:
        app: The aiohttp :class:`web.Application` instance.
    """
    app.router.add_route("*", "/api/v1/users/credentials", CredentialsHandler)
    app.router.add_route(
        "*", "/api/v1/users/credentials/{name}", CredentialsHandler
    )
    logger.debug(
        "Registered credential routes: "
        "/api/v1/users/credentials and /api/v1/users/credentials/{name}"
    )
