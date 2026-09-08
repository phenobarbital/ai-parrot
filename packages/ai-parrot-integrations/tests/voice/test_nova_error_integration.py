"""Nova denial propagation through the real VoiceBot and handler adapter."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_nova_denial_reaches_browser_and_closes_stream() -> None:
    """An AWS denial must reach the browser without a successful completion."""
    sdk = pytest.importorskip("aws_sdk_bedrock_runtime.models")
    from parrot.bots import VoiceBot
    from parrot.models.voice import VoiceConfig
    from parrot.voice.handler import (
        VoiceChatHandler,
        WebSocketConnection,
        _AskStreamVoiceClient,
        _HandlerVoiceSession,
    )

    bot = VoiceBot(
        system_prompt="Use get_weather when asked about weather.",
        voice_config=VoiceConfig(provider="nova", voice_name="matthew"),
        aws_access_key="test-access",
        aws_secret_key="test-secret",
    )
    bot._llm = bot._create_llm_client(bot._resolve_llm_config())
    ws = MagicMock(closed=False)
    ws.send_json = AsyncMock()
    connection = WebSocketConnection(ws=ws, session_id="denied-session")
    connection.bot = bot
    handler = VoiceChatHandler(bot_factory=lambda: bot)
    session = _HandlerVoiceSession(
        client=_AskStreamVoiceClient(bot, user_id="test-user"),
        send_fn=ws.send_json,
        system_prompt=bot.system_prompt,
        voice_config=bot.voice_config,
        handler=handler,
        connection=connection,
    )
    stream = MagicMock()
    stream.await_output = AsyncMock(side_effect=sdk.AccessDeniedException(message="Missing bedrock:InvokeModel"))
    stream.close = AsyncMock()
    with (
        patch.object(bot._llm, "_open_stream", return_value=stream),
        patch.object(bot._llm, "_send_event", new=AsyncMock()) as send_event,
    ):
        await session.start_turn()
        await asyncio.wait_for(session._task, timeout=5)

    frames = [call.args[0] for call in ws.send_json.await_args_list]
    errors = [frame for frame in frames if frame["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["message"] == "AccessDeniedException: Missing bedrock:InvokeModel"
    assert not any(frame["type"] in ("response_complete", "ready_to_speak") for frame in frames)
    prompts = [
        call.args[1]["event"]["textInput"]["content"]
        for call in send_event.await_args_list
        if "textInput" in call.args[1]["event"]
    ]
    assert any("Use get_weather" in prompt and "$name" not in prompt for prompt in prompts)
    stream.close.assert_awaited_once()
    assert session._queue is None
    await session.close()
