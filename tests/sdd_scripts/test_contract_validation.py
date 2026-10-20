"""FEAT-708 M7 — claim → sdd-contract-probe check mapping and caller-side classification.

`_classify` and `_report_usable` are reference implementations of rules the
commands state in Markdown and an agent executes, so they are **drift guards,
not behavioral guarantees** (issue:8eb2e5870472): they prove helper and command
agree, never that a run behaves that way. Each is pinned below to the command
text it mirrors, so editing one without the other fails the suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMANDS = {name: _REPO_ROOT / ".claude" / "commands" / f"{name}.md" for name in ("sdd-brainstorm", "sdd-proposal")}


def _classify(result: dict, expected: str | None) -> str:
    """Map one verified probe result to verified | stale | missing (spec M7 table)."""
    kind = result.get("kind")
    status = result.get("status")
    signature = result.get("signature")
    lines = result.get("lines", [])

    # verified: import found/reexported, file found, anchor found, absent absent
    if kind in ("import", "file", "anchor") and status in ("found", "reexported"):
        return "verified"
    if kind == "absent" and status == "absent":
        return "verified"
    # verified: symbol found with matching signature
    if kind == "symbol" and status == "found" and signature == expected:
        return "verified"
    # stale: symbol found with different signature
    if kind == "symbol" and status == "found" and signature != expected:
        return "stale"
    # stale: anchor ambiguous, absent present
    if kind == "anchor" and status == "ambiguous":
        return "stale"
    if kind == "absent" and status == "present":
        return "stale"
    # missing: import missing/module-missing, symbol/file/anchor missing, file short
    if kind in ("import", "symbol", "file", "anchor") and status == "missing":
        return "missing"
    if kind == "import" and status == "module-missing":
        return "missing"
    if kind == "file" and status == "short":
        return "missing"
    # unknown status
    return "missing"


def _report_usable(report: dict, head: str) -> bool:
    """A report is usable only when its `head` equals the current short HEAD."""
    return report.get("head") == head


# Fixtures from spec §4
sample_contract_claims = [
    {
        "claim": "from parrot.tools import AbstractTool",
        "check": {"id": "c0", "kind": "import", "module": "parrot.tools", "name": "AbstractTool"},
    },
    {
        "claim": "packages/ai-parrot/src/parrot/tools/base.py:42",
        "check": {"id": "c1", "kind": "file", "path": "packages/ai-parrot/src/parrot/tools/base.py", "line": 42},
    },
    {
        "claim": "class Agent(AbstractBot):",
        "expected": "class Agent(AbstractBot):",
        "check": {"id": "c2", "kind": "symbol", "path": "packages/ai-parrot/src/parrot/bots/agent.py", "name": "Agent"},
    },
    {
        "claim": "parrot.tools.NonExistent does not exist",
        "check": {"id": "c3", "kind": "absent", "name": "NonExistent", "scope": "packages/ai-parrot/src/parrot/tools"},
    },
]

sample_probe_report = {
    "repo_root": "/repo",
    "head": "abc1234",
    "results": [
        {
            "id": "c0",
            "kind": "import",
            "status": "found",
            "command": "...",
            "output": "15:class AbstractTool(ABC):",
            "count": 1,
            "lines": [15],
            "signature": "class AbstractTool(ABC):",
            "truncated": False,
            "note": None,
        },
        {
            "id": "c1",
            "kind": "file",
            "status": "short",
            "command": "wc -l < packages/ai-parrot/src/parrot/tools/base.py",
            "output": "38",
            "count": 38,
            "lines": [],
            "signature": None,
            "truncated": False,
            "note": None,
        },
        {
            "id": "c2",
            "kind": "symbol",
            "status": "found",
            "command": "...",
            "output": "88:class Agent(AbstractBot, ToolMixin):",
            "count": 1,
            "lines": [88],
            "signature": "class Agent(AbstractBot, ToolMixin):",
            "truncated": False,
            "note": None,
        },
        {
            "id": "c3",
            "kind": "absent",
            "status": "absent",
            "command": "...",
            "output": "",
            "count": 0,
            "lines": [],
            "signature": None,
            "truncated": False,
            "note": None,
        },
    ],
}

expected_classification = {"c0": "verified", "c1": "missing", "c2": "stale", "c3": "verified"}


def test_claim_extraction_imports():
    """Import claims map to `import` probe checks (`module` + `name`)."""
    for claim in sample_contract_claims:
        check = claim["check"]
        # Only check import claims
        if "from parrot.tools import" in claim["claim"]:
            assert check["kind"] == "import", f"Claim {claim['claim']} should have kind='import'"
            assert "module" in check, f"Import claim {claim['claim']} should have module field"
            assert "name" in check, f"Import claim {claim['claim']} should have name field"
            # absent scope is a directory, not a file
            if claim["claim"].startswith("parrot.tools.NonExistent"):
                assert "scope" in check, "absent claim should have scope field"
                assert check["scope"] == "packages/ai-parrot/src/parrot/tools"


def test_claim_extraction_signatures():
    """Signature claims map to `symbol` checks; `expected` kept by the caller."""
    for claim in sample_contract_claims:
        check = claim["check"]
        if "class Agent" in claim["claim"] or "def some_function" in claim["claim"]:
            assert check["kind"] == "symbol", f"Signature claim {claim['claim']} should have kind='symbol'"
            assert "path" in check, f"Symbol claim {claim['claim']} should have path field"
            assert "name" in check, f"Symbol claim {claim['claim']} should have name field"
            # expected is kept by the caller, not in the check
            assert "expected" not in check, f"Signature claim {claim['claim']} should not have expected in check"


def test_claim_extraction_absent():
    """'Does NOT exist' entries map to `absent` checks scoped to the whole module."""
    for claim in sample_contract_claims:
        if "does not exist" in claim["claim"].lower():
            check = claim["check"]
            assert check["kind"] == "absent", f"absent claim {claim['claim']} should have kind='absent'"
            assert "name" in check, f"absent claim {claim['claim']} should have name field"
            assert "scope" in check, f"absent claim {claim['claim']} should have scope field"
            # scope is the whole module directory, not a file
            assert "/" in check["scope"], f"absent scope {check['scope']} should be a directory path"


def test_claim_extraction_files():
    """`path:NN` citations map to `file` checks with `line`."""
    for claim in sample_contract_claims:
        if ":" in claim["claim"] and not claim["claim"].startswith("class ") and not claim["claim"].startswith("from "):
            check = claim["check"]
            assert check["kind"] == "file", f"File claim {claim['claim']} should have kind='file'"
            assert "path" in check, f"File claim {claim['claim']} should have path field"
            assert "line" in check, f"File claim {claim['claim']} should have line field"


def test_classify_verified():
    """Probe `found`/`absent` results classify as verified with `path:line` evidence."""
    # import found
    result = {"kind": "import", "status": "found", "signature": "class AbstractTool(ABC):", "lines": [15]}
    assert _classify(result, "class AbstractTool(ABC):") == "verified"
    # file found
    result = {"kind": "file", "status": "found", "signature": None, "lines": [42]}
    assert _classify(result, None) == "verified"
    # anchor found
    result = {"kind": "anchor", "status": "found", "signature": None, "lines": [10]}
    assert _classify(result, None) == "verified"
    # absent absent
    result = {"kind": "absent", "status": "absent", "signature": None, "lines": []}
    assert _classify(result, None) == "verified"
    # symbol found with matching signature
    result = {
        "kind": "symbol",
        "status": "found",
        "signature": "class Agent(AbstractBot):",
        "lines": [88],
    }
    assert _classify(result, "class Agent(AbstractBot):") == "verified"


def test_classify_stale_signature():
    """`symbol` found with a different `signature` → stale, actual signature carried."""
    result = {
        "kind": "symbol",
        "status": "found",
        "signature": "class Agent(AbstractBot, ToolMixin):",
        "lines": [88],
    }
    assert _classify(result, "class Agent(AbstractBot):") == "stale"
    # The actual signature is in the result, not the expected
    assert result["signature"] == "class Agent(AbstractBot, ToolMixin):"


def test_classify_absent_present_is_stale():
    """`absent` check returning `present` → stale (entry removed from Does NOT Exist)."""
    result = {"kind": "absent", "status": "present", "signature": None, "lines": []}
    assert _classify(result, None) == "stale"


def test_classify_missing():
    """`missing`/`module-missing`/`short` → missing."""
    # import missing
    result = {"kind": "import", "status": "missing", "signature": None, "lines": []}
    assert _classify(result, None) == "missing"
    # module-missing
    result = {"kind": "import", "status": "module-missing", "signature": None, "lines": []}
    assert _classify(result, None) == "missing"
    # symbol missing
    result = {"kind": "symbol", "status": "missing", "signature": None, "lines": []}
    assert _classify(result, None) == "missing"
    # file missing
    result = {"kind": "file", "status": "missing", "signature": None, "lines": []}
    assert _classify(result, None) == "missing"
    # anchor missing
    result = {"kind": "anchor", "status": "missing", "signature": None, "lines": []}
    assert _classify(result, None) == "missing"
    # file short
    result = {"kind": "file", "status": "short", "signature": None, "lines": []}
    assert _classify(result, None) == "missing"


def test_probe_report_head_mismatch_rejected():
    """Report whose `head` ≠ current HEAD is not used."""
    report = {"head": "def4567", "results": []}
    assert not _report_usable(report, "abc1234")
    # Same head is usable
    report = {"head": "abc1234", "results": []}
    assert _report_usable(report, "abc1234")


def test_fallback_inline_verification():
    """Agent unavailable / report discarded / < ~10 checks → inline verification."""
    # The spec says inline verification happens when:
    # - Agent tool unavailable
    # - Report discarded
    # - Fewer than ~10 checks
    # This is a contract test that the commands mention these fallback conditions
    for command_name in ("sdd-brainstorm", "sdd-proposal"):
        command_path = _COMMANDS[command_name]
        with open(command_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Check for inline fallback mention (~10 checks)
        assert "~10" in content or "~ 10" in content, f"{command_name} should mention ~10 checks fallback"
        # Check for Agent tool mention (the spec says "without the Agent tool")
        assert "Agent" in content and "tool" in content, f"{command_name} should mention Agent tool"


def test_uses_shared_probe_agent():
    """Both commands contain `sdd-contract-probe`; neither defines a fork validator nor `model: "haiku"` on a fork."""
    for command_name in ("sdd-brainstorm", "sdd-proposal"):
        command_path = _COMMANDS[command_name]
        with open(command_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Check for sdd-contract-probe mention
        assert "sdd-contract-probe" in content, f"{command_name} should mention sdd-contract-probe"
        # Check for no fork validator (subagent_type: "fork" in probe paragraphs)
        # Extract probe paragraphs (between "Delegate the flat checks" and "Generate Options" for brainstorm, or similar for proposal)
        if command_name == "sdd-brainstorm":
            # Find the probe section
            probe_start = content.find("Delegate the flat checks")
            probe_end = content.find("### 5. Generate Options")
            if probe_start != -1 and probe_end != -1:
                probe_section = content[probe_start:probe_end]
                # Check for subagent_type: "fork" in probe section
                assert (
                    'subagent_type: "fork"' not in probe_section
                ), f"{command_name} should not use fork in probe section"
        elif command_name == "sdd-proposal":
            # Find the probe section (§4d)
            probe_start = content.find("#### 4d. Citation probe")
            probe_end = content.find("### 5. Phase 3")
            if probe_start != -1 and probe_end != -1:
                probe_section = content[probe_start:probe_end]
                # Check for subagent_type: "fork" in probe section
                assert (
                    'subagent_type: "fork"' not in probe_section
                ), f"{command_name} should not use fork in probe section"
        # Check for no model: "haiku" anywhere in the file
        assert 'model: "haiku"' not in content, f'{command_name} should not have model: "haiku" anywhere'
        # Also check for model: haiku (without quotes)
        assert "model: haiku" not in content, f"{command_name} should not have model: haiku anywhere"


# Drift guards — pin the helpers and the §4d/§5a/§5b ordering to the command
# text (issue:8eb2e5870472).


def test_classification_table_pinned():
    """Every `_classify` outcome must appear as a row of the §5b classification table."""
    text = _COMMANDS["sdd-proposal"].read_text(encoding="utf-8")
    for phrase in (
        "`signature` == `expected` (whitespace-normalized)",
        "`symbol` `found` and `signature` ≠ `expected`",
        "`anchor` `ambiguous`; `absent` `present`",
        "`import` `missing`/`module-missing`",
    ):
        assert phrase in text, f"§5b classification table no longer states: {phrase!r}"


def test_citation_probe_ordering_is_acyclic():
    """§4d launch → §5a provisional → §5b collect+tag → §5a re-run → prompt.

    The original wording had §5a assemble the input and §5b "re-read the tagged
    findings into the §5a input", which never said which assembly the prompt
    receives (issue:8eb2e5870472).
    """
    text = _COMMANDS["sdd-proposal"].read_text(encoding="utf-8")
    assert "Re-read the tagged findings into the §5a input" not in text
    assert "that assembly is **provisional**" in text
    assert "assemble the input now as a **provisional** pass" in text
    assert "**Then re-run §5a** over the tagged findings" in text
    assert text.index("#### 4d.") < text.index("#### 5a.") < text.index("#### 5b.")
