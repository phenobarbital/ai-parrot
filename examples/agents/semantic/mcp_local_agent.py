"""MCP-local semantic layer: one real allow and one real deny (FEAT-769 M4).

The documentation tells operators to "exercise both an explicit allow and an explicit deny
policy against the real server factory". This example does exactly that, through
``create_toolkit_mcp_server`` — the supported MCP-local path.

Usage::

    python examples/agents/semantic/mcp_local_agent.py --smoke     # both decisions, no LLM
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import _common  # noqa: E402  (examples/ is not a package)

from parrot.auth import DataPlanePolicyGuard, RlsRegistry
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.models import SemanticQuery

LOGGER = logging.getLogger(__name__)

#: The name this module registers itself under so the YAML's dotted guard_factory resolves.
FACTORY_MODULE = "semantic_example_mcp_guard_factory"

_QUERY = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])


class ExampleDecisionEvaluator:
    """PBAC evaluator returning one explicit, operator-configured decision."""

    def __init__(self, allow: bool) -> None:
        """Store the explicit decision read from the policy directory."""
        self._allow = allow

    def check_access(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        """Return the configured decision for a single protected resource."""
        del args, kwargs
        return SimpleNamespace(allowed=self._allow)

    def filter_resources(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        """Return every resource only when the decision explicitly permits them."""
        resources = args[2] if len(args) > 2 else kwargs["resource_names"]
        return SimpleNamespace(allowed=list(resources) if self._allow else [])


def build_guard(*, rls_registry: RlsRegistry, policy_dir: str) -> DataPlanePolicyGuard:
    """Load the explicit decision from ``policy_dir`` and fail closed when it is missing.

    This is the host-supplied factory the documented YAML names. Its signature is fixed by
    the bootstrap: keyword-only, ``rls_registry`` injected, ``policy_dir`` from
    ``guard_factory_kwargs``.

    Args:
        rls_registry: Registry supplied by the local bootstrap.
        policy_dir: Directory holding ``decisions.json``.

    Returns:
        A real DataPlanePolicyGuard — never a bypassed one.

    Raises:
        ValueError: When the decision file is absent or malformed.
    """
    policy_path = Path(policy_dir) / "decisions.json"
    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
        allow = data["allow"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Policy decisions are unavailable") from exc
    if not isinstance(allow, bool):
        raise ValueError("Policy decision must be boolean")
    return DataPlanePolicyGuard(evaluator=ExampleDecisionEvaluator(allow), rls_registry=rls_registry)


def write_toolkit_config(directory: Path, *, models: Path, policy_dir: Path, factory: str) -> Path:
    """Write the documented ``.parrot/mcp-toolkits.yaml`` equivalent for a local run.

    Reproduces the block in ``docs/tools/semantic-layer.md`` with only the host-owned
    paths and the factory name substituted.

    Args:
        directory: Directory the config file is written to.
        models: Model directory the toolkit loads.
        policy_dir: Directory holding the explicit decision.
        factory: Dotted path of the guard factory, e.g. ``f"{FACTORY_MODULE}.build_guard"``.

    Returns:
        The path of the written config file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "mcp-toolkits.yaml"
    config.write_text(
        "toolkits:\n"
        "  semantic-layer:\n"
        "    class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit\n"
        "    kwargs:\n"
        f"      models_dir: {models}\n"
        "      dialect: duckdb\n"
        "      agent_id: local-semantic\n"
        "      static_subject: {user_id: operator, tenant_id: local, roles: [admin]}\n"
        f"      guard_factory: {factory}\n"
        f"      guard_factory_kwargs: {{policy_dir: {policy_dir}}}\n"
        "    env: {}\n",
        encoding="utf-8",
    )
    return config


async def run_decision(config: Path, *, allow: bool) -> Any:
    """Execute one governed call through the owned MCP toolkit.

    Args:
        config: Path of a config written by :func:`write_toolkit_config`.
        allow: Only used for logging which decision is being exercised.

    Returns:
        The tool result when the policy allows the call.

    Raises:
        SemanticAccessError: When the policy denies it.
    """
    LOGGER.info("running the %s decision through create_toolkit_mcp_server", "allow" if allow else "deny")
    server = create_toolkit_mcp_server("semantic-layer", root=config.parent, config_path=config)
    tool = server._owned_toolkit.get_tool("sl_compile_query")
    if tool is None:
        raise RuntimeError("sl_compile_query is not exposed by the owned toolkit")
    return await tool._execute(query=_QUERY)


async def smoke() -> dict[str, Any]:
    """Run both the allow and the deny decision against the real server factory.

    Returns:
        A JSON-safe summary of both outcomes.

    Raises:
        RuntimeError: If the deny decision does **not** raise — a silently-succeeding
            denial is a failure, not a pass.
    """
    previous_factory_module = sys.modules.get(FACTORY_MODULE)
    sys.modules[FACTORY_MODULE] = sys.modules[__name__]
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allow_policy = root / "allow-policy"
            allow_policy.mkdir()
            (allow_policy / "decisions.json").write_text(json.dumps({"allow": True}), encoding="utf-8")
            deny_policy = root / "deny-policy"
            deny_policy.mkdir()
            (deny_policy / "decisions.json").write_text(json.dumps({"allow": False}), encoding="utf-8")

            factory = f"{FACTORY_MODULE}.build_guard"
            allow_config = write_toolkit_config(
                root / "allow-config",
                models=_common.MODELS_DIR,
                policy_dir=allow_policy,
                factory=factory,
            )
            deny_config = write_toolkit_config(
                root / "deny-config",
                models=_common.MODELS_DIR,
                policy_dir=deny_policy,
                factory=factory,
            )

            allowed = await run_decision(allow_config, allow=True)
            try:
                await run_decision(deny_config, allow=False)
            except SemanticAccessError:
                denied = "denied"
            else:
                raise RuntimeError("deny unexpectedly succeeded")
            return {"allow": allowed, "deny": denied}
    finally:
        if previous_factory_module is None:
            sys.modules.pop(FACTORY_MODULE, None)
        else:
            sys.modules[FACTORY_MODULE] = previous_factory_module


async def main() -> None:
    """Run both decisions and print a summary."""
    parser = argparse.ArgumentParser(description="MCP-local semantic layer: allow and deny")
    parser.add_argument("--smoke", action="store_true", help="Run both decisions (default)")
    parser.parse_args()
    print(json.dumps(await smoke(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
