"""Unit tests for the CommCenter persistence models (FEAT-417).

Covers ``NotificationTemplate`` (Module 1) and ``NotificationBatchRecipient``
(Module 2) field defaults, ``Meta`` configuration, and the DDL contract.
"""
import uuid
from pathlib import Path

from parrot.conf import PARROT_SCHEMA
from parrot.handlers.models import NotificationBatchRecipient, NotificationTemplate


class TestNotificationTemplate:
    """Tests for the NotificationTemplate asyncdb model."""

    def test_meta_configuration(self):
        assert NotificationTemplate.Meta.driver == "pg"
        assert NotificationTemplate.Meta.name == "notification_templates"
        assert NotificationTemplate.Meta.schema == PARROT_SCHEMA

    def test_defaults(self):
        t = NotificationTemplate(name="welcome", template_string="Hola {{ name }}")
        assert isinstance(t.template_id, uuid.UUID)
        assert t.is_active is True
        assert t.tags == []

    def test_templates_are_global_no_user_id(self):
        """Templates are global by explicit spec decision."""
        assert "user_id" not in NotificationTemplate.__annotations__

    def test_ddl_has_trigger_and_unique(self):
        sql = Path(
            "packages/ai-parrot-server/src/parrot/handlers/models/"
            "notification_templates_creation.sql"
        ).read_text()
        assert "update_notification_templates_updated_at" in sql
        assert "BEFORE UPDATE" in sql
        assert "UNIQUE" in sql and "name" in sql
        assert "CREATE TABLE IF NOT EXISTS" in sql


class TestNotificationBatchRecipient:
    """Tests for the NotificationBatchRecipient flat tracking model."""

    def test_meta_configuration(self):
        assert NotificationBatchRecipient.Meta.name == "notification_batch_recipients"
        assert NotificationBatchRecipient.Meta.driver == "pg"
        assert NotificationBatchRecipient.Meta.schema == PARROT_SCHEMA

    def test_defaults(self):
        r = NotificationBatchRecipient(
            batch_id=uuid.uuid4(), provider="email", status="pending"
        )
        assert r.attempts == 0
        assert r.published_at is None
        assert r.message_id is None

    def test_ddl_status_vocabulary(self):
        sql = Path(
            "packages/ai-parrot-server/src/parrot/handlers/models/"
            "notification_batches_creation.sql"
        ).read_text()
        for status in ("pending", "publishing", "queued", "skipped", "publish_failed"):
            assert status in sql
        assert "CHECK" in sql
        assert "delivered" not in sql  # not obtainable — see spec §1 Non-Goals

    def test_ddl_indexes_and_trigger(self):
        sql = Path(
            "packages/ai-parrot-server/src/parrot/handlers/models/"
            "notification_batches_creation.sql"
        ).read_text()
        assert "batch_id" in sql
        assert "update_notification_batch_recipients_updated_at" in sql
        assert "BEFORE UPDATE" in sql
