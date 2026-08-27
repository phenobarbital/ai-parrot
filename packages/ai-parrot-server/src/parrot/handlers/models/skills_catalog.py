"""``SkillCatalogEntry`` asyncdb model — durable record + SQL query plane
for the shared skills catalog (FEAT-467 TASK-2515).

PG-first, dual-write design (spec §3 Module 7): this table is the
system-of-record; the ``SkillRegistry`` (Redis + file, shared ``"<org>/
_shared"`` namespace) is a best-effort secondary index for embedding
search + git-like versioning. ``search_index_stale`` marks rows whose
registry write failed — repaired by the startup reconciliation pass or
the admin resync endpoint.

NOTE: deliberately NOT using ``from __future__ import annotations`` —
asyncdb's Model/datamodel Cython field processor introspects
``__annotations__`` directly (no ``typing.get_type_hints()``
resolution) and requires REAL type objects, not the postponed-
evaluation string literals the future import would produce; with it,
constructing ``SkillCatalogEntry(...)`` raises ``TypeError: Expected
type, got str`` inside ``datamodel.validation`` (confirmed empirically
— matches the working, future-import-free ``scheduler/models.py::
AgentSchedule`` pattern; see ``handlers/models/studio_drafts.py`` for
the same fix applied to TASK-2513's model).
"""
import uuid
from datetime import datetime

from asyncdb.models import Field, Model


class SkillCatalogEntry(Model):
    """Database model for the org-wide shared skills catalog (spec §2).

    SQL Table Creation:
    CREATE TABLE IF NOT EXISTS navigator.ai_skills_catalog (
        skill_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name VARCHAR NOT NULL UNIQUE,
        description TEXT NOT NULL,
        category VARCHAR NOT NULL DEFAULT 'general',
        owner VARCHAR NOT NULL,
        triggers JSONB DEFAULT '[]'::JSONB,
        body TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        status VARCHAR NOT NULL DEFAULT 'active',
        search_index_stale BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE INDEX idx_ai_skills_catalog_category ON navigator.ai_skills_catalog(category);
    CREATE INDEX idx_ai_skills_catalog_owner ON navigator.ai_skills_catalog(owner);

    ``skill_id`` mirrors the ``SkillRegistry`` ``Skill.skill_id`` for the
    same entry (FEAT-467 TASK-2515 — ``SkillRegistry.upload_skill``'s
    ``skill_id=`` parameter is used to create the registry-side Skill
    with THIS row's id). ``category`` is constrained to
    ``parrot.skills.models.SkillCategory`` values by the handler; out-of-
    vocabulary values are never persisted (handler-side validation, not
    a DB constraint).
    """
    skill_id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    name: str = Field(required=True)
    description: str = Field(required=True)
    category: str = Field(required=False, default="general")
    owner: str = Field(required=True)
    triggers: list = Field(required=False, default_factory=list)
    body: str = Field(required=True)
    version: int = Field(required=False, default=1)
    status: str = Field(required=False, default="active")
    search_index_stale: bool = Field(required=False, default=False)
    created_at: datetime = Field(required=False, default_factory=datetime.now)
    updated_at: datetime = Field(required=False, default_factory=datetime.now)

    class Meta:
        driver = 'pg'
        name = "ai_skills_catalog"
        schema = "navigator"
        strict = True
        frozen = False
