"""Unit tests for ClaudeAgentRunOptions extensions (TASK-875).

Adds coverage for the four extension fields required by the dev-loop
dispatcher: ``agents``, ``setting_sources``, ``extra_args``, and
``system_prompt`` (existing field, defaults asserted here for parity).
"""

from __future__ import annotations

from parrot.clients.claude_agent import ClaudeAgentRunOptions


class TestExtendedRunOptions:
    """Smoke tests for the new fields added by TASK-875."""

    def test_new_fields_default_none(self):
        opts = ClaudeAgentRunOptions()
        assert opts.agents is None
        assert opts.setting_sources is None
        assert opts.extra_args is None
        assert opts.system_prompt is None

    def test_setting_sources_literal_validated(self):
        opts = ClaudeAgentRunOptions(setting_sources=["project", "user"])
        assert opts.setting_sources == ["project", "user"]

    def test_extra_args_accepts_none_values(self):
        opts = ClaudeAgentRunOptions(
            extra_args={"verbose": None, "output-format": "json"}
        )
        assert opts.extra_args["verbose"] is None
        assert opts.extra_args["output-format"] == "json"

    def test_agents_accepts_dict_of_arbitrary_objects(self):
        # The runtime annotation is Dict[str, Any] — Pydantic should not
        # complain about an arbitrary AgentDefinition-shaped object.
        class _FakeAgentDef:
            description = "fake"
            tools = ["Read"]
            prompt = "be terse"

        opts = ClaudeAgentRunOptions(agents={"sdd-worker": _FakeAgentDef()})
        assert "sdd-worker" in opts.agents

    def test_system_prompt_round_trip(self):
        opts = ClaudeAgentRunOptions(system_prompt="be helpful")
        assert opts.system_prompt == "be helpful"

    def test_no_extra_field_breakage(self):
        # The pre-existing extra_options field should still default to {}.
        opts = ClaudeAgentRunOptions()
        assert opts.extra_options == {}


class TestBuildOptionsForwardsExtensions:
    """Verify the merge block in _build_options forwards new fields.

    These tests build a ClaudeAgentClient with monkey-patched
    ``_import_sdk`` so we don't require the [claude-agent] extra to be
    installed.
    """

    def test_build_options_forwards_agents_and_setting_sources(self, monkeypatch):
        from parrot.clients import claude_agent as ca_module

        captured = {}

        class _FakeOptions:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        def _fake_import_sdk():
            return (None, None, _FakeOptions)

        monkeypatch.setattr(ca_module, "_import_sdk", _fake_import_sdk)

        client = ca_module.ClaudeAgentClient()
        run_opts = ca_module.ClaudeAgentRunOptions(
            agents={"sdd-worker": object()},
            setting_sources=["project"],
            extra_args={"output-format": "json", "verbose": None},
        )
        client._build_options(run_options=run_opts)
        assert "agents" in captured and "sdd-worker" in captured["agents"]
        assert captured["setting_sources"] == ["project"]
        assert captured["extra_args"] == {
            "output-format": "json",
            "verbose": None,
        }

    def test_build_options_omits_unset_extension_fields(self, monkeypatch):
        from parrot.clients import claude_agent as ca_module

        captured = {}

        class _FakeOptions:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        def _fake_import_sdk():
            return (None, None, _FakeOptions)

        monkeypatch.setattr(ca_module, "_import_sdk", _fake_import_sdk)

        client = ca_module.ClaudeAgentClient()
        client._build_options()
        # Default-constructed options must not leak any of the new keys.
        assert "agents" not in captured
        assert "setting_sources" not in captured
        assert "extra_args" not in captured
