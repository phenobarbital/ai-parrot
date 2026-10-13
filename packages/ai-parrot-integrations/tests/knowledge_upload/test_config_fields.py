"""FEAT-647 TASK-4186 — knowledge_upload block on the integration configs."""

import pytest
from pydantic import ValidationError

from parrot.integrations.knowledge_upload.models import KnowledgeUploadConfig
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.slack.models import SlackAgentConfig
from parrot.integrations.telegram.models import TelegramAgentConfig

CONFIGS = [TelegramAgentConfig, MSTeamsAgentConfig, SlackAgentConfig]

BLOCK = {
    "enabled": True,
    "allowed_usernames": ["jlara"],
    "allowed_groups": ["odoo_curators"],
    "max_size_mb": 5,
    "bookstore": {"library_dir": "/tmp/library"},
}


@pytest.mark.parametrize("cls", CONFIGS)
def test_absent_block_is_disabled(cls):
    cfg = cls.from_dict("bot", {"chatbot_id": "x"})
    assert isinstance(cfg.knowledge_upload, KnowledgeUploadConfig)
    assert cfg.knowledge_upload.enabled is False
    assert cfg.knowledge_upload.max_size_mb == 10
    assert cfg.knowledge_upload.allowed_usernames == []
    assert cfg.knowledge_upload.allowed_groups == []
    assert cfg.knowledge_upload.bookstore is None
    assert cfg.knowledge_upload.wiki is None


@pytest.mark.parametrize("cls", CONFIGS)
def test_block_is_parsed(cls):
    cfg = cls.from_dict("bot", {"chatbot_id": "x", "knowledge_upload": BLOCK})
    assert cfg.knowledge_upload.enabled is True
    assert cfg.knowledge_upload.allowed_usernames == ["jlara"]
    assert cfg.knowledge_upload.allowed_groups == ["odoo_curators"]
    assert cfg.knowledge_upload.max_size_mb == 5
    assert cfg.knowledge_upload.bookstore is not None
    assert cfg.knowledge_upload.bookstore.library_dir == "/tmp/library"


@pytest.mark.parametrize("cls", CONFIGS)
def test_empty_yaml_block_means_defaults(cls):
    cfg = cls.from_dict("bot", {"chatbot_id": "x", "knowledge_upload": None})
    assert cfg.knowledge_upload.enabled is False


@pytest.mark.parametrize("cls", CONFIGS)
def test_invalid_block_raises(cls):
    with pytest.raises(ValidationError):
        cls.from_dict("bot", {"chatbot_id": "x", "knowledge_upload": {"max_size_mb": 0}})
