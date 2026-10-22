"""Tests for the JiraSpecialist standup lanes.

Covers the roster resolution (``JIRA_DEVELOPERS`` from the app settings
module), the scheduled private fan-out for the morning and end-of-day
standups, the ``/standup`` Telegram command, and the single-message
non-responder digest posted to the public channel.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.bots.jira_specialist import Developer, JiraSpecialist
from parrot.integrations.telegram import get_current_telegram_chat_id, telegram_chat_scope

ROSTER = [
    {
        "id": "35",
        "name": "Jesus Lara",
        "jira_username": "jlara@example.com",
        "jira_account_id": "557058:5c136372",
        "telegram_chat_id": "286137732",
        "manager_chat_id": "286137732",
        "username": "jlara@example.com",
    },
    {
        "id": "36",
        "name": "Juan Rodriguez",
        "jira_username": "jrodriguez@example.com",
        "jira_account_id": "712020:dcb57da7",
        "telegram_chat_id": "546679977",
        "manager_chat_id": "21228918",
        "username": "jrodriguez@example.com",
    },
    {
        "id": "37",
        "name": "Emmanuel Arroyo",
        "jira_username": "earroyo@example.com",
        "jira_account_id": "712020:5a5622bc",
        "telegram_chat_id": "5966407682",
        "manager_chat_id": "21228918",
        "username": "earroyo@example.com",
    },
]


@pytest.fixture
def agent():
    """A JiraSpecialist with Redis, Jira and navconfig stubbed out."""
    with (
        patch("redis.asyncio.from_url") as redis_factory,
        patch("parrot.bots.jira_specialist.JiraToolkit"),
        patch("parrot.bots.jira_specialist.config") as cfg,
    ):
        redis_factory.return_value = AsyncMock()
        cfg.get.return_value = "dummy"
        cfg.getlist.return_value = []
        bot = JiraSpecialist()
        bot.set_wrapper(AsyncMock())
        bot._app_developer_roster = MagicMock(return_value=[dict(d) for d in ROSTER])
        yield bot


def _chat_ids(mock_call_list):
    return [c.kwargs["chat_id"] for c in mock_call_list]


# ──────────────────────────────────────────────────────────────
# Roster resolution
# ──────────────────────────────────────────────────────────────


class TestStandupRoster:
    def test_app_roster_needs_no_is_developer_flag(self, agent):
        """JIRA_DEVELOPERS is developers-only, so every entry counts."""
        roster = agent._standup_roster()
        assert [d.name for d in roster] == ["Jesus Lara", "Juan Rodriguez", "Emmanuel Arroyo"]

    def test_roster_can_be_narrowed_to_one_developer(self, agent):
        assert [d.id for d in agent._standup_roster(developer_id="36")] == ["36"]

    def test_account_id_survives_model_parsing(self, agent):
        """The morning JQL addresses the dev by accountId, so it must be kept."""
        dev = agent._standup_roster(developer_id="35")[0]
        assert dev.jira_account_id == "557058:5c136372"
        assert agent._morning_standup_instruction(dev, "2026-10-21").count("557058:5c136372") == 1

    def test_morning_instruction_falls_back_to_the_username(self, agent):
        dev = Developer(id="9", name="No Account", username="n@e.com", jira_username="n@e.com", telegram_chat_id=1)
        assert 'assignee = "n@e.com"' in agent._morning_standup_instruction(dev, "2026-10-21")

    def test_malformed_entry_is_skipped_not_fatal(self, agent):
        agent._app_developer_roster = MagicMock(return_value=[{"id": "1"}, dict(ROSTER[0])])
        roster = agent._standup_roster()
        assert [d.id for d in roster] == ["35"]

    def test_empty_app_roster_falls_back_to_the_legacy_loader(self, agent):
        agent._app_developer_roster = MagicMock(return_value=[])
        agent._load_developers_sync = MagicMock(return_value=[Developer(**ROSTER[1])])
        assert [d.id for d in agent._standup_roster()] == ["36"]
        agent._load_developers_sync.assert_called_once_with(developer_id=None)

    def test_app_roster_import_failure_is_not_fatal(self, agent):
        """A library install has no settings.settings; the roster is just empty."""
        del agent._app_developer_roster  # restore the real implementation
        with patch.dict("sys.modules", {"settings.settings": None}):
            assert agent._app_developer_roster() == []


# ──────────────────────────────────────────────────────────────
# Scheduled fan-out
# ──────────────────────────────────────────────────────────────


class TestStandupFanOut:
    @pytest.mark.asyncio
    async def test_morning_standup_runs_once_per_developer_in_their_own_chat(self, agent):
        seen = []

        async def _ask(**kwargs):
            seen.append((kwargs["user_id"], get_current_telegram_chat_id()))
            return MagicMock(output="done")

        agent.ask = AsyncMock(side_effect=_ask)

        summary = await agent.dispatch_morning_standup()

        assert summary["lane"] == "morning"
        assert summary["developers"] == 3
        assert summary["ok"] == 3
        assert summary["errors"] == 0
        # One private conversation per developer, each scoped to their chat.
        assert seen == [("35", "286137732"), ("36", "546679977"), ("37", "5966407682")]
        assert [r["developer"] for r in summary["results"]] == [d["name"] for d in ROSTER]

    @pytest.mark.asyncio
    async def test_morning_standup_tracks_dispatch_and_response(self, agent):
        agent.ask = AsyncMock(return_value=MagicMock(output="done"))
        redis_mock = await agent._get_redis()

        await agent.dispatch_morning_standup()

        keys = [c.args[0] for c in redis_mock.set.call_args_list]
        assert sum(1 for k in keys if k.startswith("standup:dispatched:")) == 3
        assert sum(1 for k in keys if k.startswith("standup:responded:")) == 3

    @pytest.mark.asyncio
    async def test_eod_standup_never_marks_the_morning_answer(self, agent):
        """Both lanes share one responded key per day — EOD must not write it."""
        agent.ask = AsyncMock(return_value=MagicMock(output="done"))
        redis_mock = await agent._get_redis()

        summary = await agent.dispatch_eod_standup()

        assert summary["lane"] == "eod"
        assert summary["ok"] == 3
        keys = [c.args[0] for c in redis_mock.set.call_args_list]
        assert not [k for k in keys if k.startswith("standup:responded:")]
        assert not [k for k in keys if k.startswith("standup:dispatched:")]

    @pytest.mark.asyncio
    async def test_eod_standup_uses_the_end_of_day_instruction(self, agent):
        agent.ask = AsyncMock(return_value=MagicMock(output="done"))
        await agent.dispatch_eod_standup(developer_id="35")
        question = agent.ask.call_args.kwargs["question"]
        assert "end-of-day standup wrap" in question
        assert "plan_tomorrow" in question

    @pytest.mark.asyncio
    async def test_one_failure_does_not_cancel_the_other_developers(self, agent):
        async def _ask(**kwargs):
            if kwargs["user_id"] == "36":
                raise RuntimeError("telegram timeout")
            return MagicMock(output="done")

        agent.ask = AsyncMock(side_effect=_ask)
        redis_mock = await agent._get_redis()

        summary = await agent.dispatch_morning_standup()

        assert summary["ok"] == 2
        assert summary["errors"] == 1
        failed = [r for r in summary["results"] if r["status"] == "error"]
        assert [r["developer"] for r in failed] == ["Juan Rodriguez"]
        # The developer who never answered is dispatched but not responded.
        responded = [c.args[0] for c in redis_mock.set.call_args_list if "responded" in c.args[0]]
        assert not [k for k in responded if k.endswith(":36")]

    @pytest.mark.asyncio
    async def test_empty_roster_is_a_no_op(self, agent):
        agent._app_developer_roster = MagicMock(return_value=[])
        agent._load_developers_sync = MagicMock(return_value=[])
        agent.ask = AsyncMock()

        summary = await agent.dispatch_morning_standup()

        assert summary == {
            "lane": "morning",
            "date": summary["date"],
            "developers": 0,
            "ok": 0,
            "errors": 0,
            "results": [],
        }
        agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_redis_outage_does_not_block_the_standup(self, agent):
        agent.ask = AsyncMock(return_value=MagicMock(output="done"))
        agent._get_redis = AsyncMock(side_effect=ConnectionError("redis down"))

        summary = await agent.dispatch_morning_standup(developer_id="35")

        assert summary["ok"] == 1
        agent.ask.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_lane_is_rejected(self, agent):
        with pytest.raises(ValueError, match="Unknown standup lane"):
            await agent._dispatch_standup_lane(lane="afternoon")

    def test_both_lanes_run_on_a_two_minute_interval(self):
        """Test cadence — swap for @schedule_daily_report once validated."""
        for method in (JiraSpecialist.dispatch_morning_standup, JiraSpecialist.dispatch_eod_standup):
            cfg = method._schedule_config
            assert cfg["schedule_type"] == "interval"
            assert cfg["schedule_config"] == {"minutes": 2}


# ──────────────────────────────────────────────────────────────
# /standup Telegram command
# ──────────────────────────────────────────────────────────────


class TestStandupCommand:
    def test_the_command_is_declared(self):
        meta = JiraSpecialist.standup_command._telegram_command
        assert meta["command"] == "standup"
        assert meta["parse_mode"] == "keyword"

    @pytest.mark.asyncio
    async def test_command_runs_only_the_callers_standup(self, agent):
        agent.ask = AsyncMock(return_value=MagicMock(output="done"))

        with telegram_chat_scope("546679977"):
            reply = await agent.standup_command()

        assert "Juan Rodriguez" in reply
        assert agent.ask.await_count == 1
        assert agent.ask.call_args.kwargs["user_id"] == "36"

    @pytest.mark.asyncio
    async def test_command_accepts_an_explicit_developer_id(self, agent):
        agent.ask = AsyncMock(return_value=MagicMock(output="done"))

        with telegram_chat_scope("999"):
            reply = await agent.standup_command(developer_id="37")

        assert "Emmanuel Arroyo" in reply
        assert agent.ask.call_args.kwargs["user_id"] == "37"

    @pytest.mark.asyncio
    async def test_unknown_chat_gets_the_roster_message(self, agent):
        agent.ask = AsyncMock()

        with telegram_chat_scope("12345"):
            reply = await agent.standup_command()

        assert "12345" in reply
        assert "not in the standup roster" in reply
        agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failed_standup_reports_the_failure(self, agent):
        agent.ask = AsyncMock(side_effect=RuntimeError("boom"))

        with telegram_chat_scope("286137732"):
            reply = await agent.standup_command()

        assert "could not be completed" in reply


# ──────────────────────────────────────────────────────────────
# Non-responder digest
# ──────────────────────────────────────────────────────────────


def _redis_with(agent, *, dispatched, responded):
    """Stub Redis so only the given developer ids look dispatched/answered."""
    redis_mock = AsyncMock()

    async def _exists(key):
        kind, _date, dev_id = key.split(":")[1:]
        wanted = dispatched if kind == "dispatched" else responded
        return 1 if dev_id in wanted else 0

    redis_mock.exists = AsyncMock(side_effect=_exists)
    agent._get_redis = AsyncMock(return_value=redis_mock)
    return redis_mock


class TestNonResponderDigest:
    @pytest.mark.asyncio
    async def test_one_message_lists_every_non_responder(self, agent):
        agent._developers = [Developer(**d) for d in ROSTER]
        agent.public_channel_id = "-1001234567890"
        _redis_with(agent, dispatched={"35", "36", "37"}, responded={"35"})

        result = await agent.escalate_non_responders()

        send = agent._wrapper.bot.send_message
        assert send.await_count == 1, "managers get ONE list, not one DM each"
        assert send.call_args.kwargs["chat_id"] == "-1001234567890"
        text = send.call_args.kwargs["text"]
        assert "• Juan Rodriguez" in text and "• Emmanuel Arroyo" in text
        assert "Jesus Lara" not in text
        assert result["non_responders"] == ["Juan Rodriguez", "Emmanuel Arroyo"]
        assert result["escalated_to"] == ["-1001234567890"]
        assert result["channel_id"] == "-1001234567890"
        assert result["messages_sent"] == 1
        assert result["responded"] == 1
        assert result["total_dispatched"] == 3

    @pytest.mark.asyncio
    async def test_every_silent_developer_is_still_nudged_privately(self, agent):
        agent._developers = [Developer(**d) for d in ROSTER]
        agent.public_channel_id = "-100"
        _redis_with(agent, dispatched={"35", "36", "37"}, responded={"35"})

        await agent.escalate_non_responders()

        assert _chat_ids(agent._wrapper.send_interactive_message.call_args_list) == [546679977, 5966407682]

    @pytest.mark.asyncio
    async def test_explicit_chat_id_overrides_the_channel(self, agent):
        agent._developers = [Developer(**d) for d in ROSTER]
        agent.public_channel_id = "-100"
        _redis_with(agent, dispatched={"36"}, responded=set())

        result = await agent.escalate_non_responders(manager_chat_id=777)

        assert agent._wrapper.bot.send_message.call_args.kwargs["chat_id"] == 777
        assert result["escalated_to"] == [777]

    @pytest.mark.asyncio
    async def test_without_a_channel_it_falls_back_to_one_dm_per_manager(self, agent):
        agent._developers = [Developer(**d) for d in ROSTER]
        agent.public_channel_id = None
        _redis_with(agent, dispatched={"35", "36", "37"}, responded=set())

        with patch("parrot.bots.jira_specialist.JIRA_TELEGRAM_PUBLIC_CHANNEL_ID", None):
            result = await agent.escalate_non_responders()

        # Jesus reports to himself, Juan and Emmanuel share a manager.
        assert sorted(_chat_ids(agent._wrapper.bot.send_message.call_args_list)) == [21228918, 286137732]
        assert result["messages_sent"] == 2
        assert result["channel_id"] is None

    @pytest.mark.asyncio
    async def test_no_channel_and_no_manager_escalates_nowhere(self, agent):
        agent._developers = [Developer(**{**ROSTER[1], "manager_chat_id": None})]
        agent.public_channel_id = None
        _redis_with(agent, dispatched={"36"}, responded=set())

        with patch("parrot.bots.jira_specialist.JIRA_TELEGRAM_PUBLIC_CHANNEL_ID", None):
            result = await agent.escalate_non_responders()

        agent._wrapper.bot.send_message.assert_not_called()
        assert result["non_responders"] == ["Juan Rodriguez"]
        assert result["messages_sent"] == 0

    @pytest.mark.asyncio
    async def test_a_rejected_send_is_reported_not_swallowed_as_success(self, agent):
        agent._developers = [Developer(**d) for d in ROSTER]
        agent.public_channel_id = "-100"
        agent._wrapper.bot.send_message = AsyncMock(side_effect=RuntimeError("chat not found"))
        _redis_with(agent, dispatched={"36"}, responded=set())

        result = await agent.escalate_non_responders()

        assert result["messages_sent"] == 0
        assert result["escalated_to"] == []
        assert result["non_responders"] == ["Juan Rodriguez"]

    @pytest.mark.asyncio
    async def test_nothing_is_sent_when_everybody_answered(self, agent):
        agent._developers = [Developer(**d) for d in ROSTER]
        agent.public_channel_id = "-100"
        _redis_with(agent, dispatched={"35", "36", "37"}, responded={"35", "36", "37"})

        result = await agent.escalate_non_responders()

        agent._wrapper.bot.send_message.assert_not_called()
        agent._wrapper.send_interactive_message.assert_not_called()
        assert result["non_responders"] == []
        assert result["responded"] == 3

    @pytest.mark.asyncio
    async def test_developers_never_dispatched_are_not_escalated(self, agent):
        agent._developers = [Developer(**d) for d in ROSTER]
        agent.public_channel_id = "-100"
        _redis_with(agent, dispatched={"36"}, responded=set())

        result = await agent.escalate_non_responders()

        assert result["total_dispatched"] == 1
        assert result["non_responders"] == ["Juan Rodriguez"]
