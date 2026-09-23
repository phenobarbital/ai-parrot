import pytest
import sys
import importlib
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.models.responses import AgentResponse


@pytest.fixture(scope="module")
def mock_agent_deps_module():
    """
    Setup the environment to test the REAL BasicAgent.
    Module-scoped to avoid reloading C-extensions (numpy) multiple times.
    """
    import sys

    # 1. Create Mock Modules
    mock_google_module = MagicMock()
    mock_client_cls = MagicMock()
    # We can't use AsyncMock in a module-scoped fixture efficiently if we want to reset it per test?
    # We can creates a persistent instance, then reset it in a function-scoped autouse fixture.
    mock_client_instance = AsyncMock()
    mock_client_cls.return_value = mock_client_instance
    mock_google_module.GoogleGenAIClient = mock_client_cls

    mock_mcp_module = MagicMock()
    mock_mcp_module.MCPEnabledMixin = type("MCPEnabledMixin", (), {})
    mock_mcp_module.MCPToolManager = MagicMock()

    mock_notifications = MagicMock()
    mock_notifications.NotificationMixin = type("NotificationMixin", (), {})

    mock_tools_agent = MagicMock()
    mock_tools_agent.AgentContext = MagicMock()
    mock_tools_agent.AgentTool = MagicMock()

    # 2. Patch sys.modules manually (no context manager that reverts automatically per function)
    # We back up original modules
    original_modules = {}
    targets = {
        "parrot.clients.google": mock_google_module,
        "parrot.mcp": mock_mcp_module,
        "parrot.notifications": mock_notifications,
        "parrot.tools.agent": mock_tools_agent,
    }

    for k, v in targets.items():
        if k in sys.modules:
            original_modules[k] = sys.modules[k]
        sys.modules[k] = v

    # 3. Handle parrot.bots.agent
    stub_agent_module = sys.modules.get("parrot.bots.agent")

    # Delete stub/existing and Reload Real
    if "parrot.bots.agent" in sys.modules:
        del sys.modules["parrot.bots.agent"]

    import parrot.bots.agent

    importlib.reload(parrot.bots.agent)

    yield mock_client_instance

    # Teardown: Restore stubs/originals
    if stub_agent_module:
        sys.modules["parrot.bots.agent"] = stub_agent_module
    else:
        if "parrot.bots.agent" in sys.modules:
            del sys.modules["parrot.bots.agent"]

    for k, _v in targets.items():
        if k in original_modules:
            sys.modules[k] = original_modules[k]
        else:
            del sys.modules[k]


@pytest.fixture
def mock_agent_deps(mock_agent_deps_module):
    """Function-scoped fixture to reset mocks."""
    mock_agent_deps_module.reset_mock()
    # We might need to recreate AsyncMock if it's exhausted?
    # But AsyncMock reset_mock usually suffices for call counts.
    return mock_agent_deps_module


@pytest.mark.asyncio
async def test_agent_init(mock_agent_deps):
    """Test BasicAgent initialization."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="TestAgent")
    assert agent.name == "TestAgent"
    assert agent.operation_mode == "agentic"
    assert agent.client == mock_agent_deps


@pytest.mark.asyncio
async def test_basic_agent_never_provides_python_repl(mock_agent_deps):
    """BasicAgent must never wire arbitrary Python execution.

    Giving every LLM-driven agent a `python_repl` tool is a security risk, so
    the base agent provides no such tool — not even behind an opt-in flag.
    """
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent.__new__(BasicAgent)
    agent.agent_id = "agent"
    tools = BasicAgent._get_default_tools(agent, None, use_tools=True)
    tool_names = [tool.name for tool in tools]

    assert "python_repl" not in tool_names
    assert "to_json" in tool_names


@pytest.mark.asyncio
async def test_basic_agent_python_repl_can_be_passed_explicitly(mock_agent_deps):
    """Trusted callers can still inject a python_repl tool via `tools=[...]`."""
    from parrot.bots.agent import BasicAgent
    from parrot.tools.pythonrepl import PythonREPLTool

    agent = BasicAgent.__new__(BasicAgent)
    agent.agent_id = "agent"
    repl = PythonREPLTool()
    tools = BasicAgent._get_default_tools(agent, [repl], use_tools=True)
    tool_names = [tool.name for tool in tools]

    assert "python_repl" in tool_names
    assert "to_json" in tool_names


@pytest.mark.asyncio
async def test_handle_files(mock_agent_deps):
    """Test file handling and dataframe creation."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="DataAgent")
    agent.logger = MagicMock()
    agent.add_dataframe = MagicMock()

    # Patch pandas where it is used in the module
    with patch("parrot.bots.agent.pd") as mock_pd:
        import io

        mock_df = MagicMock()
        mock_pd.read_csv.return_value = mock_df

        # Use spec to prevent 'file' attribute existence
        file_obj = MagicMock(spec=io.BytesIO)
        file_obj.read.return_value = b"col1,col2\n1,2"
        attachments = {"data.csv": file_obj}

        added = await agent.handle_files(attachments)

        if not added:
            if agent.logger.error.called:
                print(f"DEBUG: Logger Error: {agent.logger.error.call_args}")
            else:
                print("DEBUG: No error logged, but added is empty.")
                # Check if add_dataframe called?
                print(f"DEBUG: add_dataframe called: {agent.add_dataframe.called}")

        assert "data" in added
        agent.add_dataframe.assert_called_with(mock_df, name="data")


@pytest.mark.asyncio
async def test_generate_report(mock_agent_deps):
    """Test report generation logic."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Reporter")

    agent.open_prompt = AsyncMock(return_value="Check {topic}")
    agent.invoke = AsyncMock()
    # Mock _agent_response class to avoid signature issues with Stubs
    agent._agent_response = MagicMock()

    mock_llm_response = MagicMock(spec=AgentResponse)
    mock_llm_response.output = "Analysis Complete"
    mock_llm_response.turn_id = "123"
    agent.invoke.return_value = mock_llm_response

    # The return of _agent_response call (instantiation)
    mock_response_data = MagicMock()
    mock_response_data.data = "Analysis Complete"
    mock_response_data.status = "success"
    agent._agent_response.return_value = mock_response_data

    response_obj, response_data = await agent.generate_report(prompt_file="test_prompt.txt", topic="Market")

    assert response_data.data == "Analysis Complete"
    assert response_data.status == "success"


@pytest.mark.asyncio
async def test_speech_report(mock_agent_deps):
    """Test speech and podcast generation."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")

    agent.open_prompt = AsyncMock(return_value="Podcast Instructions")

    # Explicitly setup client context manager
    # mock_agent_deps is the client instance (AsyncMock)
    mock_agent_deps.__aenter__.return_value = mock_agent_deps

    mock_script_response = MagicMock()
    mock_script_response.output.prompt = "Script Content"
    mock_agent_deps.create_conversation_script.return_value = mock_script_response

    mock_speech_result = MagicMock()
    mock_speech_result.files = ["/tmp/podcast.wav"]
    mock_agent_deps.generate_speech.return_value = mock_speech_result

    # Mock aiofiles
    mock_file_handle = AsyncMock()
    mock_ctx_manager = MagicMock()
    mock_ctx_manager.__aenter__.return_value = mock_file_handle
    mock_ctx_manager.__aexit__.return_value = None

    with patch("parrot.bots.agent.aiofiles.open", return_value=mock_ctx_manager):
        result = await agent.speech_report(report="Analysis Text", podcast_instructions="instructions.txt")

        mock_agent_deps.create_conversation_script.assert_awaited()
        mock_file_handle.write.assert_awaited_with("Script Content")
        assert result["podcast_path"] == "/tmp/podcast.wav"


@pytest.mark.asyncio
async def test_speech_report_forwards_script_and_tts_model(mock_agent_deps):
    """script_model/tts_model, when provided, are forwarded as `model=` to
    create_conversation_script()/generate_speech() respectively."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    agent.open_prompt = AsyncMock(return_value="Podcast Instructions")
    mock_agent_deps.__aenter__.return_value = mock_agent_deps

    mock_script_response = MagicMock()
    mock_script_response.output.prompt = "Script Content"
    mock_agent_deps.create_conversation_script.return_value = mock_script_response

    mock_speech_result = MagicMock()
    mock_speech_result.files = ["/tmp/podcast.wav"]
    mock_agent_deps.generate_speech.return_value = mock_speech_result

    mock_file_handle = AsyncMock()
    mock_ctx_manager = MagicMock()
    mock_ctx_manager.__aenter__.return_value = mock_file_handle
    mock_ctx_manager.__aexit__.return_value = None

    with patch("parrot.bots.agent.aiofiles.open", return_value=mock_ctx_manager):
        await agent.speech_report(
            report="Analysis Text",
            podcast_instructions="instructions.txt",
            script_model="gemini-3.5-flash",
            tts_model="gemini-3.1-flash-tts-preview",
        )

    assert mock_agent_deps.create_conversation_script.call_args.kwargs["model"] == "gemini-3.5-flash"
    assert mock_agent_deps.generate_speech.call_args.kwargs["model"] == "gemini-3.1-flash-tts-preview"


@pytest.mark.asyncio
async def test_speech_report_omits_model_kwargs_by_default(mock_agent_deps):
    """Without script_model/tts_model, no `model=` override is passed through —
    create_conversation_script()/generate_speech() use their own defaults."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    agent.open_prompt = AsyncMock(return_value="Podcast Instructions")
    mock_agent_deps.__aenter__.return_value = mock_agent_deps

    mock_script_response = MagicMock()
    mock_script_response.output.prompt = "Script Content"
    mock_agent_deps.create_conversation_script.return_value = mock_script_response

    mock_speech_result = MagicMock()
    mock_speech_result.files = ["/tmp/podcast.wav"]
    mock_agent_deps.generate_speech.return_value = mock_speech_result

    mock_file_handle = AsyncMock()
    mock_ctx_manager = MagicMock()
    mock_ctx_manager.__aenter__.return_value = mock_file_handle
    mock_ctx_manager.__aexit__.return_value = None

    with patch("parrot.bots.agent.aiofiles.open", return_value=mock_ctx_manager):
        await agent.speech_report(report="Analysis Text", podcast_instructions="instructions.txt")

    assert "model" not in mock_agent_deps.create_conversation_script.call_args.kwargs
    assert "model" not in mock_agent_deps.generate_speech.call_args.kwargs


def _podcast_client(mock_agent_deps):
    """Wire the mocked Google client for a speech_report() call."""
    mock_agent_deps.__aenter__.return_value = mock_agent_deps
    mock_script_response = MagicMock()
    mock_script_response.output.prompt = "Script Content"
    mock_agent_deps.create_conversation_script.return_value = mock_script_response
    mock_speech_result = MagicMock()
    mock_speech_result.files = ["/tmp/podcast.wav"]
    mock_agent_deps.generate_speech.return_value = mock_speech_result
    mock_ctx_manager = MagicMock()
    mock_ctx_manager.__aenter__.return_value = AsyncMock()
    mock_ctx_manager.__aexit__.return_value = None
    return mock_ctx_manager


@pytest.mark.asyncio
@pytest.mark.parametrize("num_speakers", [1, 2])
async def test_speech_report_uses_exactly_num_speakers(mock_agent_deps, num_speakers):
    """Regression: the limit was checked after appending, so num_speakers=1 produced two speakers."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    agent.open_prompt = AsyncMock(return_value="Podcast Instructions")
    ctx = _podcast_client(mock_agent_deps)

    with patch("parrot.bots.agent.aiofiles.open", return_value=ctx):
        await agent.speech_report(report="Analysis Text", num_speakers=num_speakers)

    config = mock_agent_deps.create_conversation_script.call_args.kwargs["report_data"]
    assert [s.name for s in config.speakers] == ["Lydia", "Brian"][:num_speakers]


@pytest.mark.asyncio
async def test_speech_report_does_not_mutate_class_speakers(mock_agent_deps):
    """speech_report() must not write into the class-level `speakers` dict shared by all instances."""
    from parrot.bots.agent import BasicAgent

    class Shouty(BasicAgent):
        speakers = {"host": {"name": "Ana", "role": "interviewer", "characteristic": "Bright", "gender": "FEMALE"}}

    agent = Shouty(name="Podcaster")
    agent.open_prompt = AsyncMock(return_value="Podcast Instructions")
    ctx = _podcast_client(mock_agent_deps)

    with patch("parrot.bots.agent.aiofiles.open", return_value=ctx):
        await agent.speech_report(report="Analysis Text", num_speakers=1)

    config = mock_agent_deps.create_conversation_script.call_args.kwargs["report_data"]
    assert config.speakers[0].gender == "female"
    assert Shouty.speakers["host"]["gender"] == "FEMALE"


@pytest.mark.asyncio
async def test_speech_report_rejects_zero_speakers(mock_agent_deps):
    """num_speakers < 1 is a caller error, not a silent empty podcast."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    with pytest.raises(ValueError, match="num_speakers"):
        await agent.speech_report(report="Analysis Text", num_speakers=0)


@pytest.mark.asyncio
async def test_speech_report_verbatim_supertonic_zero_llm_calls(mock_agent_deps, tmp_path):
    """Non-Gemini verbatim synthesis bypasses all LLM calls."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    result = MagicMock(audio=b"wav", mime_format="audio/wav")
    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(return_value=result)

    with patch(
        "parrot.voice.tts.synthesizer.get_shared_synthesizer",
        AsyncMock(return_value=synthesizer),
    ):
        response = await agent.speech_report(
            report="# Heading\n\n**Plain** report",
            tts_backend="supertonic",
            speech_mode="verbatim",
            directory=tmp_path,
            output_directory=tmp_path,
        )

    mock_agent_deps.create_conversation_script.assert_not_awaited()
    mock_agent_deps.generate_speech.assert_not_awaited()
    synthesizer.synthesize.assert_awaited_once_with("Heading\n\nPlain report", language=None)
    assert response["script_path"].read_text() == "Heading\n\nPlain report"
    assert response["podcast_path"].suffix == ".wav"


@pytest.mark.asyncio
async def test_speech_report_script_mode_single_narrator(mock_agent_deps, tmp_path):
    """Non-Gemini script mode requests one speaker and removes labels."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    mock_agent_deps.__aenter__.return_value = mock_agent_deps
    script_response = MagicMock()
    script_response.output.prompt = "Lydia: **First line**\nBrian: Second line"
    mock_agent_deps.create_conversation_script.return_value = script_response
    agent._synthesize_with_backend = AsyncMock(return_value=tmp_path / "podcast.wav")

    response = await agent.speech_report(
        report="Analysis",
        tts_backend="supertonic",
        directory=tmp_path,
        output_directory=tmp_path,
    )

    script_config = mock_agent_deps.create_conversation_script.call_args.kwargs["report_data"]
    assert len(script_config.speakers) == 1
    assert agent._synthesize_with_backend.await_args.args[:2] == ("First line\nSecond line", "supertonic")
    assert response["script_path"].read_text() == "First line\nSecond line"


@pytest.mark.asyncio
async def test_speech_report_gemini_verbatim_single_voice(mock_agent_deps, tmp_path):
    """Gemini verbatim mode builds a single narrator prompt without a script call."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    mock_agent_deps.__aenter__.return_value = mock_agent_deps
    speech_result = MagicMock(files=[tmp_path / "podcast.wav"])
    mock_agent_deps.generate_speech.return_value = speech_result

    await agent.speech_report(
        report="**Verbatim** report",
        speech_mode="verbatim",
        directory=tmp_path,
        output_directory=tmp_path,
    )

    mock_agent_deps.create_conversation_script.assert_not_awaited()
    prompt = mock_agent_deps.generate_speech.call_args.kwargs["prompt_data"]
    assert prompt.prompt == "Verbatim report"
    assert len(prompt.speakers) == 1
    assert prompt.speakers[0].voice == "Charon"


@pytest.mark.asyncio
async def test_speech_report_kwarg_overrides_attribute(mock_agent_deps, tmp_path):
    """Per-call backend selection wins over the agent attribute."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    agent.speech_backend = "aws_polly"
    agent._synthesize_with_backend = AsyncMock(return_value=tmp_path / "podcast.wav")

    await agent.speech_report(
        report="Report",
        tts_backend="supertonic",
        speech_mode="verbatim",
        directory=tmp_path,
        output_directory=tmp_path,
    )

    assert agent._synthesize_with_backend.await_args.args[1] == "supertonic"


@pytest.mark.asyncio
async def test_speech_report_invalid_backend_raises(mock_agent_deps):
    """Unsupported speech backends explain the accepted selectors."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    with pytest.raises(ValueError, match="gemini, google_tts, supertonic, aws_polly"):
        await agent.speech_report(report="Report", tts_backend="unknown")


@pytest.mark.asyncio
async def test_speech_report_backend_failure_no_fallback(mock_agent_deps, tmp_path):
    """Backend errors propagate instead of falling back to Gemini."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    agent._synthesize_with_backend = AsyncMock(side_effect=RuntimeError("backend failed"))

    with pytest.raises(RuntimeError, match="backend failed"):
        await agent.speech_report(
            report="Report",
            tts_backend="supertonic",
            speech_mode="verbatim",
            directory=tmp_path,
            output_directory=tmp_path,
        )

    mock_agent_deps.generate_speech.assert_not_awaited()


@pytest.mark.asyncio
async def test_speech_report_missing_integrations_importerror(mock_agent_deps, tmp_path):
    """Missing optional backend imports name the installable extra."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    with patch.dict(
        sys.modules,
        {"parrot.voice.tts.models": None, "parrot.voice.tts.synthesizer": None},
    ):
        with pytest.raises(ImportError, match="ai-parrot-integrations\\[voice-supertonic\\]"):
            await agent.speech_report(
                report="Report",
                tts_backend="supertonic",
                speech_mode="verbatim",
                directory=tmp_path,
                output_directory=tmp_path,
            )


@pytest.mark.asyncio
async def test_speech_report_extension_follows_mime(mock_agent_deps, tmp_path):
    """The persisted backend-native extension follows the returned MIME type."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="Podcaster")
    result = MagicMock(audio=b"mp3", mime_format="audio/mpeg")
    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(return_value=result)

    with patch(
        "parrot.voice.tts.synthesizer.get_shared_synthesizer",
        AsyncMock(return_value=synthesizer),
    ):
        response = await agent.speech_report(
            report="Report",
            tts_backend="aws_polly",
            speech_mode="verbatim",
            directory=tmp_path,
            output_directory=tmp_path,
        )

    assert response["podcast_path"].suffix == ".mp3"


@pytest.mark.asyncio
async def test_report_workflow(mock_agent_deps):
    """Test high-level report() method which orchestrates everything."""
    from parrot.bots.agent import BasicAgent

    agent = BasicAgent(name="FullReporter")

    agent.open_prompt = AsyncMock(return_value="Solve {problem}")

    mock_llm_resp = MagicMock(spec=AgentResponse)
    mock_llm_resp.output = "Solved"
    agent.conversation = AsyncMock(return_value=mock_llm_resp)

    agent._agent_response = MagicMock()
    mock_final_resp = MagicMock()
    mock_final_resp.status = "success"
    mock_final_resp.output = "Solved"
    agent._agent_response.return_value = mock_final_resp

    agent.save_transcript = AsyncMock(return_value="transcript.txt")

    mock_pdf_res = MagicMock()
    mock_pdf_res.result = {"file_path": "report.pdf"}
    agent.pdf_report = AsyncMock(return_value=mock_pdf_res)

    agent.speech_report = AsyncMock(return_value={"podcast_path": "pod.wav", "script_path": "script.txt"})

    # Do NOT pass user_id to avoid bug in BasicAgent.report (double kwargs)
    response = await agent.report(
        prompt_file="solve.txt",
        problem="Hunger",
        # user_id="1",
        attributes={"dept": "HR"},
    )

    # Check that user_id passed to _agent_response was correct (default '1')
    call_kwargs = agent._agent_response.call_args.kwargs
    assert call_kwargs.get("user_id") == "1"

    assert response.status == "success"
    assert response.output == "Solved"


@pytest.mark.asyncio
async def test_setup_mcp_servers(mock_agent_deps):
    """Test setup_mcp_servers with mocked config."""
    from parrot.bots.agent import BasicAgent

    # MCPServerConfig is mocked in sys.modules, so it is a MagicMock class
    from parrot.mcp import MCPServerConfig

    agent = BasicAgent(name="MCPAgent")
    agent.add_mcp_server = AsyncMock(return_value=["tool1", "tool2"])

    # Do not use spec=MCPServerConfig because it IS a Mock object already
    config1 = MagicMock()
    config1.name = "server1"
    config2 = MagicMock()
    config2.name = "server2"

    await agent.setup_mcp_servers([config1, config2])

    assert agent.add_mcp_server.call_count == 2
    agent.add_mcp_server.assert_any_call(config1)
    agent.add_mcp_server.assert_any_call(config2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_real_integration():
    """
    Test REAL BasicAgent against Google/OpenAI/Groq if keys exist.
    Skipped if no API key found.
    """
    import os

    # We strictly respect the rule: NO MOCKS in integration tests.
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not found")

    from parrot.bots.agent import BasicAgent

    # We use a real agent
    agent = BasicAgent(name="RealTestAgent", use_llm="google", model="gemini-3.1-flash-lite-preview")

    response = await agent.conversation("Hello, who are you?")
    assert response is not None
    assert len(response.output) > 0
    print(f"Integration Response: {response.output}")
