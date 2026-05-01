"""HTTP handler for user-defined bots — ``/api/v1/user_agents``.

Methods:
    PUT    /api/v1/user_agents               — create
    PATCH  /api/v1/user_agents/{chatbot_id}  — partial update
    GET    /api/v1/user_agents               — list current user's bots
    GET    /api/v1/user_agents/{chatbot_id}  — fetch one
    DELETE /api/v1/user_agents/{chatbot_id}  — delete row + S3 docs

``mcp_config`` and ``tools_config`` may carry credentials. They are stored as
AES-GCM encrypted blobs (transparent to the handler via ``UserBotModel``
accessors) and credential-shaped keys are redacted on GET responses.
"""
from __future__ import annotations

import contextlib
import copy
import os
import tempfile
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import web
from asyncdb.exceptions import NoDataFound
from datamodel.parsers.json import json_encoder
from navconfig.logging import logging
from navigator_session import get_session
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session

from ..models import UserBotModel


# Keys whose values must never be echoed back in GET responses (case-insensitive).
_REDACT_KEYS = {
    "api_key",
    "apikey",
    "api-key",
    "client_secret",
    "oauth2_client_secret",
    "password",
    "token",
    "secret",
    "access_token",
    "refresh_token",
    "private_key",
    "bearer",
}

_REDACT_PLACEHOLDER = "***"


def _redact(value: Any) -> Any:
    """Recursively redact credential-shaped keys in dicts/lists."""
    if isinstance(value, dict):
        return {
            k: (_REDACT_PLACEHOLDER if k.lower() in _REDACT_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _deep_merge(base: Any, patch: Any) -> Any:
    """Merge ``patch`` into ``base`` recursively for dict/list config blobs.

    For lists of objects-with-name, items in ``patch`` replace items in
    ``base`` matched by the ``name`` key; otherwise the list is overwritten.
    Explicit ``None`` in a dict value deletes the key.
    """
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for key, val in patch.items():
            if val is None:
                out.pop(key, None)
            elif key in out:
                out[key] = _deep_merge(out[key], val)
            else:
                out[key] = val
        return out
    if isinstance(base, list) and isinstance(patch, list):
        if all(isinstance(it, dict) and "name" in it for it in base + patch):
            by_name = {it["name"]: copy.deepcopy(it) for it in base}
            for it in patch:
                name = it["name"]
                if it.keys() == {"name"} and "_delete" in it.get("name", ""):
                    by_name.pop(name, None)
                else:
                    by_name[name] = _deep_merge(by_name.get(name, {}), it)
            return list(by_name.values())
        return patch
    return patch


@is_authenticated()
@user_session()
class UserAgentHandler(BaseView):
    """CRUD handler for per-user bots."""

    _logger_name: str = "Parrot.UserAgentHandler"

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------
    # Session / auth helpers
    # ------------------------------------------------------------------

    async def _get_session(self) -> Any:
        with contextlib.suppress(AttributeError):
            return self.request.session or await get_session(self.request)
        return await get_session(self.request)

    async def _resolve_user_id(self) -> Optional[int]:
        session = await self._get_session()
        if session is None:
            return None
        return session.get("user_id")

    # ------------------------------------------------------------------
    # Request parsing
    # ------------------------------------------------------------------

    async def _parse_request(self) -> Tuple[Dict[str, Any], List[Tuple[str, str, str]]]:
        """Return ``(config_dict, uploaded_temp_files)``.

        ``uploaded_temp_files`` is a list of tuples ``(field_name, original_name, tmp_path)``.
        Supports both ``application/json`` and ``multipart/form-data`` (the
        latter expects a ``config`` field with the JSON payload plus optional
        ``files[]`` entries).
        """
        content_type = (self.request.content_type or "").lower()
        if content_type.startswith("multipart/"):
            return await self._parse_multipart()
        try:
            data = await self.request.json()
        except Exception:  # noqa: BLE001
            data = {}
        return data, []

    async def _parse_multipart(self) -> Tuple[Dict[str, Any], List[Tuple[str, str, str]]]:
        import json as _json
        config: Dict[str, Any] = {}
        uploads: List[Tuple[str, str, str]] = []
        reader = await self.request.multipart()
        async for part in reader:
            if part is None:
                break
            field_name = part.name
            filename = part.filename
            if filename:
                # Stream to a temp file so it can be uploaded to S3 afterwards.
                suffix = os.path.splitext(filename)[1]
                fd, tmp_path = tempfile.mkstemp(suffix=suffix)
                try:
                    with os.fdopen(fd, "wb") as out:
                        while True:
                            chunk = await part.read_chunk()
                            if not chunk:
                                break
                            out.write(chunk)
                except Exception:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                    raise
                uploads.append((field_name or "files", filename, tmp_path))
            else:
                value = await part.text()
                if field_name == "config":
                    try:
                        config = _json.loads(value)
                    except Exception:
                        return {}, uploads
                else:
                    # Allow arbitrary scalar fields to live alongside config JSON.
                    config[field_name] = value
        return config, uploads

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    _ALLOWED_FIELDS = {
        "name", "description", "avatar", "enabled", "timezone",
        "role", "goal", "backstory", "rationale", "capabilities",
        "prompt_config", "system_prompt_template", "human_prompt_template",
        "pre_instructions",
        "llm", "model_name", "temperature", "max_tokens", "top_k", "top_p",
        "model_config",
        "use_vector", "vector_config", "embedding_model",
        "context_search_limit", "context_score_threshold",
        "tools_enabled", "auto_tool_detection", "tool_threshold",
        "operation_mode",
        "memory_type", "memory_config", "max_context_turns",
        "use_conversation_history",
        "permissions", "language", "disclaimer",
    }
    _ENCRYPTED_FIELDS = {"mcp_config", "tools_config"}

    def _split_payload(
        self, data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Optional[List[dict]], Optional[List[dict]]]:
        """Separate plain columns from encrypted blobs."""
        plain: Dict[str, Any] = {}
        for key, value in data.items():
            if key in self._ALLOWED_FIELDS:
                plain[key] = value
        mcp_config = data.get("mcp_config")
        tools_config = data.get("tools_config")
        return plain, mcp_config, tools_config

    # ------------------------------------------------------------------
    # File upload (S3 via FileManagerToolkit)
    # ------------------------------------------------------------------

    def _file_manager(self):
        """Return a configured FileManagerToolkit (s3 if configured, else local).

        Falls back to the local fs backend in environments without S3 so dev
        flows still work.  Production is expected to set ``S3_BUCKET``.
        """
        try:
            from ...tools.filemanager import FileManagerToolkit  # noqa: PLC0415
        except Exception:
            return None
        bucket = os.environ.get("S3_BUCKET") or os.environ.get("AWS_S3_BUCKET")
        if bucket:
            try:
                return FileManagerToolkit(manager_type="s3", bucket=bucket)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("S3 FileManager unavailable, falling back to local: %s", exc)
        return FileManagerToolkit(manager_type="fs")

    async def _ingest_uploads(
        self,
        user_id: int,
        chatbot_id: str,
        uploads: List[Tuple[str, str, str]],
    ) -> List[dict]:
        if not uploads:
            return []
        toolkit = self._file_manager()
        if toolkit is None:
            self.logger.warning("FileManager unavailable; skipping document ingestion")
            return []
        ingested: List[dict] = []
        destination = f"users_bots/{user_id}/{chatbot_id}"
        for _field, original_name, tmp_path in uploads:
            try:
                meta = await toolkit.upload_file(
                    source_path=tmp_path,
                    destination=destination,
                    destination_name=original_name,
                )
                ingested.append(
                    {
                        "name": meta.get("name", original_name),
                        "path": meta.get("path"),
                        "url": meta.get("url"),
                        "size": meta.get("size"),
                        "content_type": meta.get("content_type"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Failed to upload document %s for bot %s: %s",
                    original_name, chatbot_id, exc,
                )
            finally:
                if os.path.exists(tmp_path):
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_path)
        return ingested

    async def _delete_documents(self, documents: List[dict]) -> None:
        if not documents:
            return
        toolkit = self._file_manager()
        if toolkit is None:
            return
        for doc in documents:
            path = doc.get("path")
            if not path:
                continue
            try:
                await toolkit.delete_file(path=path)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Best-effort S3 delete failed for %s: %s", path, exc)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    @property
    def _db(self):
        return self.request.app["database"]

    async def _list_bots(self, user_id: int) -> List[UserBotModel]:
        async with await self._db.acquire() as conn:
            UserBotModel.Meta.connection = conn
            try:
                rows = await UserBotModel.filter(user_id=user_id)
                return list(rows or [])
            except Exception as exc:  # noqa: BLE001
                self.logger.error("List user bots failed for %s: %s", user_id, exc)
                return []

    async def _get_one(self, user_id: int, chatbot_id: str) -> Optional[UserBotModel]:
        async with await self._db.acquire() as conn:
            UserBotModel.Meta.connection = conn
            try:
                return await UserBotModel.get(user_id=user_id, chatbot_id=chatbot_id)
            except NoDataFound:
                return None

    async def _insert(self, model: UserBotModel) -> UserBotModel:
        async with await self._db.acquire() as conn:
            UserBotModel.Meta.connection = conn
            await model.insert()
        return model

    async def _update(self, model: UserBotModel) -> UserBotModel:
        async with await self._db.acquire() as conn:
            UserBotModel.Meta.connection = conn
            await model.update()
        return model

    async def _delete(self, model: UserBotModel) -> None:
        async with await self._db.acquire() as conn:
            UserBotModel.Meta.connection = conn
            await model.delete()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def _serialize(self, model: UserBotModel) -> Dict[str, Any]:
        """Render a row for API responses, with credential redaction."""
        out = model.to_dict() if hasattr(model, "to_dict") else dict(model.__dict__)
        # Replace encrypted blobs with redacted plaintext
        out["mcp_config"] = _redact(model.get_mcp_config())
        out["tools_config"] = _redact(model.get_tools_config())
        # UUID/datetime serialisation
        if isinstance(out.get("chatbot_id"), uuid.UUID):
            out["chatbot_id"] = str(out["chatbot_id"])
        for ts_key in ("created_at", "updated_at"):
            if isinstance(out.get(ts_key), datetime):
                out[ts_key] = out[ts_key].isoformat()
        return out

    # ------------------------------------------------------------------
    # PUT — create
    # ------------------------------------------------------------------

    async def put(self):
        """Create a new user bot."""
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Authentication required.", status=401)

        data, uploads = await self._parse_request()
        if not data.get("name"):
            return self.error("Field 'name' is required.", status=400)

        plain, mcp_cfg, tools_cfg = self._split_payload(data)
        chatbot_id = uuid.uuid4()

        try:
            model = UserBotModel(
                chatbot_id=chatbot_id,
                user_id=user_id,
                **plain,
            )
        except Exception as exc:  # noqa: BLE001
            return self.error(f"Invalid configuration: {exc}", status=422)

        # Encrypt credential blobs (RuntimeError -> 503 if vault not configured)
        try:
            if mcp_cfg is not None:
                model.set_mcp_config(mcp_cfg)
            if tools_cfg is not None:
                model.set_tools_config(tools_cfg)
        except RuntimeError as exc:
            return self.error(f"Vault not configured: {exc}", status=503)

        # Ingest uploaded files (best-effort) and append to documents.
        ingested = await self._ingest_uploads(user_id, str(chatbot_id), uploads)
        if ingested:
            existing_docs = list(model.documents or [])
            model.documents = existing_docs + ingested

        try:
            await self._insert(model)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Insert user_bot failed: %s", exc, exc_info=True)
            return self.error(f"Could not create bot: {exc}", status=400)

        return web.json_response(
            self._serialize(model),
            status=201,
            dumps=json_encoder,
        )

    # ------------------------------------------------------------------
    # PATCH — partial update
    # ------------------------------------------------------------------

    async def patch(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Authentication required.", status=401)

        chatbot_id = self.request.match_info.get("chatbot_id")
        if not chatbot_id:
            return self.error("Missing chatbot_id in URL.", status=400)

        existing = await self._get_one(user_id, chatbot_id)
        if existing is None:
            return self.error("Bot not found.", status=404)

        data, uploads = await self._parse_request()
        plain, mcp_cfg, tools_cfg = self._split_payload(data)

        # Apply plain-column patches.
        for key, value in plain.items():
            try:
                setattr(existing, key, value)
            except Exception as exc:  # noqa: BLE001
                return self.error(f"Invalid value for {key}: {exc}", status=422)

        # Merge encrypted blobs to preserve untouched credentials.
        try:
            if mcp_cfg is not None:
                merged = _deep_merge(existing.get_mcp_config(), mcp_cfg)
                existing.set_mcp_config(merged)
            if tools_cfg is not None:
                merged = _deep_merge(existing.get_tools_config(), tools_cfg)
                existing.set_tools_config(merged)
        except RuntimeError as exc:
            return self.error(f"Vault not configured: {exc}", status=503)

        # Append any newly uploaded documents.
        ingested = await self._ingest_uploads(user_id, chatbot_id, uploads)
        if ingested:
            existing.documents = list(existing.documents or []) + ingested

        # Optional explicit document removal: payload may include
        # "documents_remove": [<path>, ...]
        remove_paths = data.get("documents_remove")
        if isinstance(remove_paths, list) and remove_paths:
            keep = [d for d in (existing.documents or []) if d.get("path") not in remove_paths]
            removed = [d for d in (existing.documents or []) if d.get("path") in remove_paths]
            await self._delete_documents(removed)
            existing.documents = keep

        try:
            await self._update(existing)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Update user_bot failed: %s", exc, exc_info=True)
            return self.error(f"Could not update bot: {exc}", status=400)

        # Invalidate session cache so next chat rebuilds.
        from ...manager.manager import BotManager  # noqa: PLC0415
        session = await self._get_session()
        BotManager.invalidate_user_bot(session, chatbot_id)

        return web.json_response(
            self._serialize(existing),
            status=200,
            dumps=json_encoder,
        )

    # ------------------------------------------------------------------
    # GET — list / fetch one
    # ------------------------------------------------------------------

    async def get(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Authentication required.", status=401)

        chatbot_id = self.request.match_info.get("chatbot_id")
        if chatbot_id:
            row = await self._get_one(user_id, chatbot_id)
            if row is None:
                return self.error("Bot not found.", status=404)
            return web.json_response(self._serialize(row), dumps=json_encoder)

        rows = await self._list_bots(user_id)
        return web.json_response(
            {"bots": [self._serialize(r) for r in rows]},
            dumps=json_encoder,
        )

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    async def delete(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Authentication required.", status=401)

        chatbot_id = self.request.match_info.get("chatbot_id")
        if not chatbot_id:
            return self.error("Missing chatbot_id in URL.", status=400)

        row = await self._get_one(user_id, chatbot_id)
        if row is None:
            return self.error("Bot not found.", status=404)

        documents = list(row.documents or [])

        try:
            await self._delete(row)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Delete user_bot failed: %s", exc, exc_info=True)
            return self.error(f"Could not delete bot: {exc}", status=400)

        # Best-effort S3 cleanup
        await self._delete_documents(documents)

        from ...manager.manager import BotManager  # noqa: PLC0415
        session = await self._get_session()
        BotManager.invalidate_user_bot(session, chatbot_id)

        return web.json_response({"deleted": True, "chatbot_id": chatbot_id})
