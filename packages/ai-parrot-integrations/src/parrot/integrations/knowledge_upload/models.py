"""Data models for chat-driven knowledge uploads (FEAT-647)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class UploadTargetKind(str, Enum):
    """Where an uploaded document is ingested."""

    BOOKSTORE = "bookstore"
    WIKI = "wiki"


class BookstoreTargetConfig(BaseModel):
    """Bookstore target settings; ``library_dir`` may contain env vars."""

    library_dir: str
    llm: str = "google:gemini-3.1-flash-lite"


class WikiTargetConfig(BaseModel):
    """LLM-wiki target settings; ``wiki_root`` holds ``.parrot/wiki.json``."""

    wiki_root: str
    charter_path: str | None = None
    llm: str = "google:gemini-3.1-flash-lite"


class KnowledgeUploadConfig(BaseModel):
    """Per-bot ``knowledge_upload`` block (one global allow-list per bot)."""

    enabled: bool = False
    allowed_usernames: list[str] = []
    allowed_groups: list[str] = []
    max_size_mb: int = Field(10, gt=0)
    allowed_extensions: list[str] = [".pdf", ".docx", ".md", ".markdown"]
    max_concurrent_jobs: int = Field(2, gt=0)
    slack_pending_window_s: int = Field(300, gt=0)
    bookstore: BookstoreTargetConfig | None = None
    wiki: WikiTargetConfig | None = None


class UploaderIdentity(BaseModel):
    """Who is uploading, as seen by the platform adapter."""

    platform: Literal["telegram", "msteams", "slack"]
    platform_user_id: str
    nav_user_id: str | None = None
    email: str | None = None


class UploadRequest(BaseModel):
    """One upload, bytes held in memory (<= max_size_mb)."""

    target: UploadTargetKind
    identity: UploaderIdentity
    filename: str
    data: bytes
    force: bool = False
    title: str | None = None
    authors: list[str] = []
    topics: list[str] = []


class UploadStatus(str, Enum):
    """Outcome status of an upload request or job."""

    ACCEPTED = "accepted"
    DENIED = "denied"
    INVALID = "invalid"
    ADDED = "added"
    UPDATED = "updated"
    SKIPPED = "skipped"
    REJECTED_BY_TRIAGE = "rejected_by_triage"
    FAILED = "failed"


class UploadOutcome(BaseModel):
    """Result reported to the user (``message``) and to the audit log."""

    job_id: str
    status: UploadStatus
    target: UploadTargetKind
    filename: str
    message: str
    detail: dict[str, Any] = {}
