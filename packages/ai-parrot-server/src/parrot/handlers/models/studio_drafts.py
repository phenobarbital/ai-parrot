"""``StudioDraft`` asyncdb model — lifecycle state/audit for generated
agent drafts (FEAT-467 TASK-2513).

Draft ``.py`` content lives on disk at ``AGENTS_DIR/_drafts/<name>.py``
(and, once activated, at ``AGENTS_DIR/<name>.py``); this table holds
ONLY the lifecycle state/audit trail (status, validation findings,
ownership) — never the source itself. Pattern:
``scheduler/models.py::AgentSchedule``.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from asyncdb.models import Field, Model


class StudioDraft(Model):
    """Database model for Studio draft-agent lifecycle state (spec §2).

    SQL Table Creation:
    CREATE TABLE IF NOT EXISTS navigator.studio_drafts (
        draft_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name VARCHAR NOT NULL UNIQUE,
        file_path VARCHAR NOT NULL,
        status VARCHAR NOT NULL DEFAULT 'draft',
        validation_report JSONB DEFAULT '{}'::JSONB,
        base_class VARCHAR,
        owner_user_id VARCHAR NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        activated_at TIMESTAMP WITH TIME ZONE
    );

    CREATE INDEX idx_studio_drafts_status ON navigator.studio_drafts(status);
    CREATE INDEX idx_studio_drafts_owner ON navigator.studio_drafts(owner_user_id);

    ``status`` values: ``draft`` | ``validated`` | ``failed`` | ``activated``
    (spec §3 Module 5 — assigned by the drafts handler, never client-supplied).
    """
    draft_id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    name: str = Field(required=True)
    file_path: str = Field(required=True)
    status: str = Field(required=False, default="draft")
    validation_report: dict = Field(required=False, default_factory=dict)
    base_class: str | None = Field(required=False)
    owner_user_id: str = Field(required=True)
    created_at: datetime = Field(required=False, default_factory=datetime.now)
    updated_at: datetime = Field(required=False, default_factory=datetime.now)
    activated_at: datetime | None = Field(required=False)

    class Meta:
        driver = 'pg'
        name = "studio_drafts"
        schema = "navigator"
        strict = True
        frozen = False
