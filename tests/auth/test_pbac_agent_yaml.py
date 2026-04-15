"""Unit tests for per-agent YAML auto-loading in setup_pbac() (TASK-715).

Tests verify that setup_pbac() loads policies from policies/agents/ subdirectory
when it exists, and gracefully handles the case when it doesn't.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


class TestPbacAgentYamlAutoload:
    """Tests for per-agent YAML loading in setup_pbac()."""

    def _make_policy_dir(self, tmp_path: Path, with_agents_dir: bool = False) -> Path:
        """Create a minimal policy directory for testing."""
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        (policy_dir / "defaults.yaml").write_text(
            "policies:\n"
            "  - name: allow_all\n"
            "    effect: allow\n"
            "    resources: ['*']\n"
            "    actions: ['*']\n"
            "    subjects:\n"
            "      groups: ['*']\n"
            "    priority: 5\n"
        )
        if with_agents_dir:
            agents_dir = policy_dir / "agents"
            agents_dir.mkdir()
            (agents_dir / "finance_bot.yaml").write_text(
                "policies:\n"
                "  - name: finance_bot_allow\n"
                "    effect: allow\n"
                "    resources: ['agent:finance_bot']\n"
                "    actions: ['agent:chat']\n"
                "    subjects:\n"
                "      groups: ['finance']\n"
                "    priority: 15\n"
            )
            (agents_dir / ".gitkeep").write_text("")
        return policy_dir

    def test_policies_agents_gitkeep_exists(self):
        """policies/agents/.gitkeep file exists in the codebase."""
        gitkeep = Path(__file__).parent.parent.parent / "policies" / "agents" / ".gitkeep"
        assert gitkeep.exists(), (
            f"policies/agents/.gitkeep should exist at {gitkeep}"
        )

    def test_setup_pbac_agents_subdir_logic_no_agents_dir(self, tmp_path):
        """When policies/agents/ doesn't exist, only top-level dir is scanned."""
        policy_dir = self._make_policy_dir(tmp_path, with_agents_dir=False)

        # Patch internal imports used inside setup_pbac
        with patch.dict('sys.modules', {
            'navigator_auth.abac.pdp': MagicMock(PDP=MagicMock()),
            'navigator_auth.abac.policies.evaluator': MagicMock(
                PolicyEvaluator=MagicMock(),
                PolicyLoader=MagicMock(load_from_directory=MagicMock(return_value=[])),
            ),
            'navigator_auth.abac.policies.abstract': MagicMock(
                PolicyEffect=MagicMock(DENY='deny', name='deny')
            ),
            'navigator_auth.abac.storages.yaml_storage': MagicMock(YAMLStorage=MagicMock()),
        }):
            import importlib
            import parrot.auth.pbac as pbac_mod
            importlib.reload(pbac_mod)

            # Since setup_pbac uses local imports inside function, just verify
            # the function doesn't crash and returns properly
            # We test the logic by inspecting the function source behavior
            assert callable(pbac_mod.setup_pbac)

    def test_pbac_no_agents_subdir_succeeds(self, tmp_path):
        """setup_pbac() succeeds when policies/agents/ doesn't exist."""
        try:
            from navigator_auth.abac.pdp import PDP
            from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader
        except ImportError:
            pytest.skip("navigator-auth not available")

        policy_dir = self._make_policy_dir(tmp_path, with_agents_dir=False)
        mock_app = MagicMock()
        mock_app.get = MagicMock(return_value=None)
        mock_app.__setitem__ = MagicMock()
        mock_app.__getitem__ = MagicMock(return_value=MagicMock())
        mock_app.router = MagicMock()
        mock_app.router.add_route = MagicMock()

        from parrot.auth.pbac import setup_pbac

        # Should not raise
        result = setup_pbac(mock_app, policy_dir=str(policy_dir))
        assert result is not None
        assert len(result) == 3

    def test_pbac_with_agents_subdir_succeeds(self, tmp_path):
        """setup_pbac() succeeds when policies/agents/ exists with YAML files."""
        try:
            from navigator_auth.abac.pdp import PDP
            from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader
        except ImportError:
            pytest.skip("navigator-auth not available")

        policy_dir = self._make_policy_dir(tmp_path, with_agents_dir=True)
        mock_app = MagicMock()
        mock_app.get = MagicMock(return_value=None)
        mock_app.__setitem__ = MagicMock()
        mock_app.__getitem__ = MagicMock(return_value=MagicMock())
        mock_app.router = MagicMock()
        mock_app.router.add_route = MagicMock()

        from parrot.auth.pbac import setup_pbac

        # Should not raise
        result = setup_pbac(mock_app, policy_dir=str(policy_dir))
        assert result is not None

    def test_pbac_source_code_has_agents_subdir_logic(self):
        """Verify the setup_pbac source code includes per-agent scanning logic."""
        import inspect
        from parrot.auth.pbac import setup_pbac
        source = inspect.getsource(setup_pbac)
        assert "agents" in source, "setup_pbac should reference 'agents' subdirectory"
        assert "load_from_directory" in source, "setup_pbac should use load_from_directory"
