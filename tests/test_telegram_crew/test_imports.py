"""Verify all public imports from the crew subpackage work correctly."""
import pytest


class TestCrewImports:
    def test_import_transport(self):
        from parrot.integrations.telegram.crew import TelegramCrewTransport
        assert TelegramCrewTransport is not None

    def test_import_config(self):
        from parrot.integrations.telegram.crew import TelegramCrewConfig, CrewAgentEntry
        assert TelegramCrewConfig is not None
        assert CrewAgentEntry is not None

    def test_import_agent_card(self):
        from parrot.integrations.telegram.crew import AgentCard, AgentSkill
        assert AgentCard is not None
        assert AgentSkill is not None

    def test_import_registry(self):
        from parrot.integrations.telegram.crew import CrewRegistry
        assert CrewRegistry is not None

    def test_import_coordinator(self):
        from parrot.integrations.telegram.crew import CoordinatorBot
        assert CoordinatorBot is not None

    def test_import_crew_wrapper(self):
        from parrot.integrations.telegram.crew import CrewAgentWrapper
        assert CrewAgentWrapper is not None

    def test_import_data_payload(self):
        from parrot.integrations.telegram.crew import DataPayload
        assert DataPayload is not None

    def test_import_mention_utilities(self):
        from parrot.integrations.telegram.crew import (
            mention_from_username,
            mention_from_card,
            format_reply,
        )
        assert mention_from_username is not None
        assert mention_from_card is not None
        assert format_reply is not None

    def test_all_exports(self):
        import parrot.integrations.telegram.crew as crew
        expected = [
            "TelegramCrewTransport",
            "TelegramCrewConfig",
            "CrewAgentEntry",
            "AgentCard",
            "AgentSkill",
            "CrewRegistry",
            "CoordinatorBot",
            "CrewAgentWrapper",
            "DataPayload",
            "mention_from_username",
            "mention_from_card",
            "format_reply",
        ]
        for name in expected:
            assert name in crew.__all__, f"{name} missing from __all__"
            assert hasattr(crew, name), f"{name} not accessible on module"


class TestExistingTelegramImportsUnbroken:
    def test_import_bot_manager(self):
        from parrot.integrations.telegram import TelegramBotManager
        assert TelegramBotManager is not None

    def test_import_agent_wrapper(self):
        from parrot.integrations.telegram import TelegramAgentWrapper
        assert TelegramAgentWrapper is not None

    def test_import_filters(self):
        from parrot.integrations.telegram import BotMentionedFilter
        assert BotMentionedFilter is not None

    def test_import_utils(self):
        from parrot.integrations.telegram import extract_query_from_mention
        assert extract_query_from_mention is not None
