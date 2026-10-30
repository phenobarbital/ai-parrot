"""AC30: the CVE operator guide only references names that exist."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
GUIDE = REPO / "docs" / "experts" / "cve-experts.md"
HEADINGS = [
    "Prerequisites",
    "From Python",
    "From the CLI",
    "Over HTTP",
    "Prompts that trigger each action",
    "Reading the result",
    "Overriding and extending",
    "Troubleshooting",
]


def test_cve_docs_headings_in_order() -> None:
    """Verify the eight required headings exist in order."""
    content = GUIDE.read_text()
    found = re.findall(r"^## (.+)$", content, flags=re.MULTILINE)
    # Filter to only the headings we care about (ignore any extra headings)
    found_in_headings = [h for h in found if h in HEADINGS]
    assert found_in_headings == HEADINGS, f"Expected {HEADINGS}, got {found_in_headings}"


def test_cve_docs_reference_real_names() -> None:
    """Verify every backticked tool name, endpoint, and CLI command exists in the codebase."""
    content = GUIDE.read_text()

    # Extract all backtick-enclosed names
    backtick_names = re.findall(r"`([^`]+)`", content)

    # Filter to the ones we need to verify (tools, endpoints, commands)
    # These are the patterns we expect to find in the code
    tool_names = {
        "lookup_cve",
        "search_cves",
        "download_cve",
        "expert_knowledge_search",
        "expert_propose_adr",
    }

    http_endpoints = {
        "/api/v1/chat/",
        "/api/v1/agents/chat/",
    }

    cli_commands = {
        "parrot agent",
        "parrot agent --list",
    }

    # Check each backtick name
    missing: list[str] = []
    for name in backtick_names:
        # Skip generic references like "run-1", "stage", etc.
        if name.startswith("http") or name.startswith("CVE-") or name.startswith("acme"):
            continue
        if name in ["question", "target", "rationale", "top_k", "limit", "cve_id", "package", "ecosystem", "version"]:
            continue
        if name in ["True", "False", "None"]:
            continue

        # Check if it's a tool we need to verify
        is_tool = any(tool in name for tool in ["lookup_cve", "search_cves", "download_cve", "knowledge_search", "propose_adr"])
        is_endpoint = name.startswith("/api/v1/")
        is_cli = name.startswith("parrot")

        if is_tool or is_endpoint or is_cli:
            # Verify the name exists in the source tree
            if is_tool:
                if not _tool_exists(name):
                    missing.append(name)
            elif is_endpoint:
                if not _endpoint_exists(name):
                    missing.append(name)
            elif is_cli:
                if not _cli_command_exists(name):
                    missing.append(name)

    assert not missing, f"Missing references: {missing}"


def _tool_exists(tool_name: str) -> bool:
    """Check if a tool name exists in the CVE toolkit or expert toolkit."""
    # lookup_cve, search_cves, download_cve are in CVEToolkit
    if tool_name in ("lookup_cve", "search_cves", "download_cve"):
        toolkit_path = REPO / "packages/ai-parrot-tools/src/parrot_tools/security/cve/toolkit.py"
        if not toolkit_path.exists():
            return False
        return f"def {tool_name}" in toolkit_path.read_text()

    # expert_knowledge_search, expert_propose_adr are in ExpertKnowledgeToolkit
    if tool_name in ("expert_knowledge_search", "expert_propose_adr"):
        toolkit_path = REPO / "packages/ai-parrot-tools/src/parrot_tools/experts/toolkit.py"
        if not toolkit_path.exists():
            return False
        # The actual method names are knowledge_search and propose_adr
        method_name = "knowledge_search" if "knowledge_search" in tool_name else "propose_adr"
        return f"def {method_name}" in toolkit_path.read_text()

    return False


def _endpoint_exists(endpoint: str) -> bool:
    """Check if an HTTP endpoint exists in the server code."""
    manager_path = REPO / "packages/ai-parrot-server/src/parrot/manager/manager.py"
    if not manager_path.exists():
        return False

    content = manager_path.read_text()

    # /api/v1/chat/ maps to ChatHandler
    if "/api/v1/chat/" in endpoint:
        return 'router.add_view("/api/v1/chat/' in content

    # /api/v1/agents/chat/ maps to AgentTalk
    if "/api/v1/agents/chat/" in endpoint:
        return 'router.add_view("/api/v1/agents/chat/' in content

    return False


def _cli_command_exists(command: str) -> bool:
    """Check if a CLI command exists in the CLI code."""
    cli_path = REPO / "packages/ai-parrot/src/parrot/cli/agent_repl.py"
    if not cli_path.exists():
        return False

    content = cli_path.read_text()

    if command == "parrot agent":
        return '@click.command("agent")' in content

    if command == "parrot agent --list":
        return '"--list"' in content or "list_agents" in content

    return False


def test_cve_docs_no_forbidden_names() -> None:
    """Verify the guide does not reference forbidden names."""
    content = GUIDE.read_text()

    # These should NOT appear in the guide
    forbidden = ["/api/v1/experts/", "parrot experts"]
    found = [name for name in forbidden if name in content]

    assert not found, f"Found forbidden names: {found}"


def test_cve_docs_prompt_table_covers_tools() -> None:
    """Verify the prompt table covers all three CVE tools and expert_propose_adr."""
    content = GUIDE.read_text()

    # Find the table section
    table_section = re.search(
        r"## Prompts that trigger each action.*?(?=## |\Z)", content, re.DOTALL
    )
    assert table_section, "Prompts section not found"

    table_text = table_section.group(0)

    # Check each tool is mentioned in the table
    required_tools = ["lookup_cve", "search_cves", "download_cve", "expert_propose_adr"]
    missing = [tool for tool in required_tools if tool not in table_text]

    assert not missing, f"Missing tools in prompt table: {missing}"