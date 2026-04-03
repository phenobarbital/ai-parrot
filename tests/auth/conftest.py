"""Shared fixtures for PBAC tests.

Provides reusable test fixtures for:
- Sample YAML policy files (using tmp_path)
- EvalContext instances for engineering and guest users
- Mock ToolManager, DatasetManager, and MCP server configs
- Mock Guardian and PolicyEvaluator
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import pytest

# ---------------------------------------------------------------------------
# sys.path fixup: ensure worktree source is imported over the editable install
# ---------------------------------------------------------------------------
# The editable install in .venv points to the main repo's packages/ai-parrot/src.
# We need the worktree's version so that parrot.auth.pbac and the updated
# parrot.auth.permission (with to_eval_context) are importable.
_WORKTREE_SRC = Path(__file__).parent.parent.parent / "packages" / "ai-parrot" / "src"
if str(_WORKTREE_SRC) not in sys.path:
    sys.path.insert(0, str(_WORKTREE_SRC))

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Policy YAML files
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_policies_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with test policy YAML files."""
    policy = {
        "version": "1.0",
        "defaults": {"effect": "deny"},
        "policies": [
            {
                "name": "engineering_tools",
                "effect": "allow",
                "resources": ["tool:*"],
                "actions": ["tool:execute", "tool:list"],
                "subjects": {"groups": ["engineering"]},
                "priority": 20,
            },
            {
                "name": "business_hours_agent",
                "effect": "allow",
                "resources": ["agent:*"],
                "actions": ["agent:chat"],
                "subjects": {"groups": ["*"]},
                "conditions": {"environment": {"is_business_hours": True}},
                "priority": 10,
            },
            {
                "name": "public_tools_all",
                "effect": "allow",
                "resources": ["tool:public_*"],
                "actions": ["tool:execute", "tool:list"],
                "subjects": {"groups": ["*"]},
                "priority": 5,
            },
            {
                "name": "jira_tools_engineering",
                "effect": "allow",
                "resources": ["tool:jira_*"],
                "actions": ["tool:execute", "tool:list"],
                "subjects": {"groups": ["engineering"]},
                "priority": 15,
            },
        ],
    }
    policy_file = tmp_path / "test_policies.yaml"
    if _YAML_AVAILABLE:
        policy_file.write_text(yaml.dump(policy))
    return tmp_path


@pytest.fixture
def empty_policies_dir(tmp_path: Path) -> Path:
    """An empty temporary directory (no policy files)."""
    return tmp_path


@pytest.fixture
def malformed_policies_dir(tmp_path: Path) -> Path:
    """A temporary directory containing a malformed YAML file plus a valid one."""
    # Valid file
    valid = {
        "version": "1.0",
        "defaults": {"effect": "deny"},
        "policies": [
            {
                "name": "valid_policy",
                "effect": "allow",
                "resources": ["tool:*"],
                "actions": ["tool:execute"],
                "subjects": {"groups": ["*"]},
            }
        ],
    }
    (tmp_path / "valid.yaml").write_text(
        yaml.dump(valid) if _YAML_AVAILABLE else "version: '1.0'\npolicies: []\n"
    )
    # Malformed file
    (tmp_path / "bad.yaml").write_text("{{{{invalid: yaml: [[[")
    return tmp_path


# ---------------------------------------------------------------------------
# EvalContext helpers
# ---------------------------------------------------------------------------

def _make_eval_context_dict(
    username: str,
    groups: list[str],
    roles: list[str] | None = None,
    programs: list[str] | None = None,
) -> Any:
    """Build a minimal EvalContext-like object for testing.

    Uses the same structure as to_eval_context() so it works with
    PolicyEvaluator.check_access().
    """
    try:
        from navigator_auth.abac.context import EvalContext
        userinfo = {
            "username": username,
            "user_id": username,
            "groups": list(groups),
            "roles": list(roles or []),
            "programs": list(programs or []),
        }
        ctx = EvalContext.__new__(EvalContext)
        ctx.store = {
            "request": None,
            "user": username,
            "userinfo": userinfo,
            "session": None,
        }
        ctx._columns = list(ctx.store.keys())
        return ctx
    except ImportError:
        return None


@pytest.fixture
def engineering_eval_ctx():
    """EvalContext for an engineering team member."""
    return _make_eval_context_dict(
        username="eng_user",
        groups=["engineering"],
        roles=["engineer"],
        programs=["acme_corp"],
    )


@pytest.fixture
def guest_eval_ctx():
    """EvalContext for a guest user with no special groups."""
    return _make_eval_context_dict(
        username="guest_user",
        groups=["guest"],
        roles=[],
    )


@pytest.fixture
def superuser_eval_ctx():
    """EvalContext for a superuser."""
    return _make_eval_context_dict(
        username="admin_user",
        groups=["superuser", "admin"],
        roles=["admin"],
    )


# ---------------------------------------------------------------------------
# UserSession / PermissionContext fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engineering_user_session():
    """UserSession for an engineering user."""
    try:
        from parrot.auth.permission import UserSession
        return UserSession(
            user_id="eng-1",
            tenant_id="acme",
            roles=frozenset({"engineer"}),
            metadata={"groups": ["engineering"], "programs": ["acme_corp"]},
        )
    except ImportError:
        return MagicMock(
            user_id="eng-1",
            tenant_id="acme",
            roles=frozenset({"engineer"}),
            metadata={"groups": ["engineering"], "programs": ["acme_corp"]},
        )


@pytest.fixture
def guest_user_session():
    """UserSession for a guest user."""
    try:
        from parrot.auth.permission import UserSession
        return UserSession(
            user_id="guest-1",
            tenant_id="acme",
            roles=frozenset(),
            metadata={"groups": ["guest"]},
        )
    except ImportError:
        return MagicMock(
            user_id="guest-1",
            tenant_id="acme",
            roles=frozenset(),
            metadata={"groups": ["guest"]},
        )


# ---------------------------------------------------------------------------
# PolicyEvaluator fixture (real, loaded from test policies)
# ---------------------------------------------------------------------------

@pytest.fixture
def policy_evaluator(sample_policies_dir: Path):
    """A real PolicyEvaluator loaded with test policies."""
    try:
        from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader
        from navigator_auth.abac.policies.abstract import PolicyEffect
        evaluator = PolicyEvaluator(
            default_effect=PolicyEffect.DENY,
            cache_ttl_seconds=30,
        )
        policies = PolicyLoader.load_from_directory(sample_policies_dir)
        evaluator.load_policies(policies)
        return evaluator
    except (ImportError, Exception):
        return None


# ---------------------------------------------------------------------------
# Mock ToolManager
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_tool_manager():
    """Mock ToolManager with a set of tools."""
    tm = MagicMock()
    tm.list_tools.return_value = [
        "jira_create", "jira_search", "public_search",
        "admin_delete", "github_pr",
    ]
    tm.remove_tool = MagicMock()
    return tm


# ---------------------------------------------------------------------------
# Mock DatasetManager
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_dataset_manager():
    """Mock DatasetManager with some datasets."""
    dm = MagicMock()
    dm.list_dataframes.return_value = {
        "sales_data": {},
        "hr_confidential": {},
        "public_sales": {},
    }
    dm.remove_dataset = MagicMock()
    return dm


# ---------------------------------------------------------------------------
# Mock MCP server configs
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mcp_configs():
    """List of mock MCP server configs."""
    github_cfg = MagicMock()
    github_cfg.name = "github"
    admin_cfg = MagicMock()
    admin_cfg.name = "admin_server"
    jira_cfg = MagicMock()
    jira_cfg.name = "jira"
    return [github_cfg, admin_cfg, jira_cfg]
