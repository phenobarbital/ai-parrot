"""Unit tests for the tool-optimizations foundation (TASK-3079, FEAT-543)."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from parrot.mcp.local_server import StdioMCPServer
from parrot.mcp.server_base import LocalServerConfig
from parrot.tools.abstract import ToolResult
from parrot.tools.repo.confinement import PathOutsideRootError, SecretFileError
from pydantic import ValidationError

from parrot_tools.tool_optimizations.base import OptimizationToolkitBase
from parrot_tools.tool_optimizations.models import (
    DelegationPacket,
    GitPrepareFilesArgs,
    GitRecentArgs,
    OperationResult,
    SourceReadArgs,
    StepResult,
    TargetFile,
    WriterApplyArgs,
)
from parrot_tools.tool_optimizations.policy import (
    BudgetError,
    LockTimeoutError,
    OptimizationPolicy,
    PolicyError,
    SymlinkRejectedError,
    WorktreeLock,
    compact_json,
    fit_to_budget,
    measure_json_bytes,
    relative_posix,
    resolve_operand,
)

HEX64 = "a" * 64
HEX32 = "b" * 32


# --------------------------------------------------------------------------- #
# Package import surface
# --------------------------------------------------------------------------- #
def test_package_import_is_pydantic_free():
    """Importing the package must not pull in pydantic (hook runtime stays light)."""
    code = "import sys, parrot_tools.tool_optimizations; print('pydantic' in sys.modules)"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert proc.stdout.strip() == "False"


def test_lazy_exports_resolve():
    """Every advertised export resolves through the PEP 562 __getattr__."""
    import parrot_tools.tool_optimizations as pkg

    for name in pkg.__all__:
        assert getattr(pkg, name) is not None
    with pytest.raises(AttributeError):
        pkg.does_not_exist


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #
def test_policy_minimum_budget(tmp_path):
    """The serialized result budget has a 4096-byte floor."""
    with pytest.raises(ValidationError):
        OptimizationPolicy(repo_root=tmp_path, max_result_bytes=1000)
    assert OptimizationPolicy(repo_root=tmp_path, max_result_bytes=4096).max_result_bytes == 4096


def test_policy_defaults_and_root_resolution(tmp_path):
    """Defaults match the spec and repo_root is resolved to an existing dir."""
    policy = OptimizationPolicy(repo_root=str(tmp_path))
    assert (policy.max_lines, policy.large_file_bytes, policy.max_result_bytes) == (350, 64_000, 64_000)
    assert (policy.command_timeout_seconds, policy.network_timeout_seconds) == (30.0, 120.0)
    assert policy.repo_root == tmp_path.resolve() and policy.repo_root.is_absolute()
    with pytest.raises(ValidationError):
        OptimizationPolicy(repo_root=tmp_path / "missing")
    with pytest.raises(ValidationError):
        OptimizationPolicy(repo_root=tmp_path, unknown_setting=1)


# --------------------------------------------------------------------------- #
# Byte budget
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload", ["x" * 10_000, "ñ" * 10_000, '"\\' * 5_000])
def test_fit_to_budget_respects_escaped_bytes(payload):
    """The budget measures escaped UTF-8 JSON bytes, and output stays valid JSON."""
    res = OperationResult(
        status="ok",
        operation="t",
        data={"records": [payload] * 5},
        elapsed_ms=1,
        steps=[StepResult(name="s", exit_code=0, timed_out=False, state_changed=False, stdout=payload)],
    )
    fitted = fit_to_budget(res, 4096)
    dumped = fitted.model_dump(mode="json")
    assert measure_json_bytes(dumped) <= 4096
    json.loads(json.dumps(dumped))  # still valid JSON
    assert fitted.truncated is True


def test_fit_to_budget_passthrough_and_identity_preserved():
    """A small result is returned untouched; a shrunk one keeps status/operation."""
    small = OperationResult(status="ok", operation="t", data={"a": 1}, elapsed_ms=0)
    assert fit_to_budget(small, 4096) is small

    huge = OperationResult(status="error", operation="git_push", data={"blob": "z" * 200_000}, elapsed_ms=7)
    fitted = fit_to_budget(huge, 4096)
    assert fitted.status == "error"
    assert fitted.operation == "git_push"
    assert fitted.elapsed_ms == 7
    assert measure_json_bytes(fitted.model_dump(mode="json")) <= 4096


def test_fit_to_budget_rejects_unusable_budget():
    """A budget below the floor is a configuration error, not a silent clamp."""
    res = OperationResult(status="ok", operation="t", elapsed_ms=0)
    with pytest.raises(BudgetError):
        fit_to_budget(res, 100)


def test_compact_json_encoding_is_canonical():
    """compact_json uses non-ASCII passthrough and separator-free encoding."""
    assert compact_json({"a": "ñ", "b": [1, 2]}) == '{"a":"ñ","b":[1,2]}'
    assert measure_json_bytes({"a": "ñ"}) == len('{"a":"ñ"}'.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Path policy
# --------------------------------------------------------------------------- #
def test_resolve_operand_rejects_symlink_and_secret(tmp_path):
    """Containment, secret deny-list and symlink components are all enforced."""
    (tmp_path / "real.txt").write_text("x")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    (tmp_path / ".env").write_text("SECRET=1")
    policy = OptimizationPolicy(repo_root=tmp_path)

    with pytest.raises(SymlinkRejectedError):
        resolve_operand(policy, "link.txt", must_exist=True)
    with pytest.raises(SecretFileError):
        resolve_operand(policy, ".env", must_exist=True)
    with pytest.raises(PathOutsideRootError):
        resolve_operand(policy, "../outside", must_exist=False)


def test_resolve_operand_accepts_regular_and_example_files(tmp_path):
    """A plain file and an allow-suffixed secret name both resolve."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x")
    (tmp_path / ".env.example").write_text("SECRET=")
    policy = OptimizationPolicy(repo_root=tmp_path)

    assert resolve_operand(policy, "pkg/mod.py", must_exist=True) == tmp_path / "pkg" / "mod.py"
    assert resolve_operand(policy, ".env.example", must_exist=True) == tmp_path / ".env.example"
    assert relative_posix(policy.repo_root, tmp_path / "pkg" / "mod.py") == "pkg/mod.py"


def test_resolve_operand_symlinked_parent_directory(tmp_path):
    """A symlinked *directory* component is rejected, not just a symlinked file."""
    (tmp_path / "real_dir").mkdir()
    (tmp_path / "real_dir" / "f.txt").write_text("x")
    (tmp_path / "link_dir").symlink_to(tmp_path / "real_dir", target_is_directory=True)
    policy = OptimizationPolicy(repo_root=tmp_path)

    with pytest.raises(SymlinkRejectedError):
        resolve_operand(policy, "link_dir/f.txt", must_exist=True)


def test_resolve_operand_must_exist(tmp_path):
    """must_exist distinguishes a planned CREATE from a missing read operand."""
    policy = OptimizationPolicy(repo_root=tmp_path)
    assert resolve_operand(policy, "new/file.py", must_exist=False) == tmp_path / "new" / "file.py"
    with pytest.raises(PolicyError):
        resolve_operand(policy, "new/file.py", must_exist=True)


# --------------------------------------------------------------------------- #
# Worktree lock
# --------------------------------------------------------------------------- #
async def test_worktree_lock_contention(tmp_path):
    """A second in-process holder times out; the lock file is never deleted."""
    lock = tmp_path / "l.lock"
    async with WorktreeLock(lock, timeout_seconds=1):
        with pytest.raises(LockTimeoutError):
            async with WorktreeLock(lock, timeout_seconds=0.2):
                pass
    assert lock.exists()  # never deleted
    # Released: it can be re-acquired.
    async with WorktreeLock(lock, timeout_seconds=1):
        pass


async def test_worktree_lock_refuses_other_process(tmp_path):
    """A separate OS process holding flock genuinely blocks acquisition."""
    lock = tmp_path / "cross.lock"
    holder_code = textwrap.dedent(f"""
        import fcntl, os, sys, time
        fd = os.open({str(lock)!r}, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        sys.stdout.write("locked\\n")
        sys.stdout.flush()
        time.sleep(30)
        """)
    holder = subprocess.Popen([sys.executable, "-c", holder_code], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(LockTimeoutError):
            async with WorktreeLock(lock, timeout_seconds=0.3):
                pass
    finally:
        holder.kill()
        holder.wait(timeout=10)
    # The kernel released the flock when the holder died — no stale lock, no unlink.
    assert lock.exists()
    async with WorktreeLock(lock, timeout_seconds=5):
        pass


async def test_worktree_lock_creates_parent_directory(tmp_path):
    """The lock file's directory is created on demand (linked-worktree git dirs)."""
    lock = tmp_path / "worktrees" / "wt" / "parrot-tool-optimizations.lock"
    async with WorktreeLock(lock, timeout_seconds=1):
        assert lock.exists()
    assert os.stat(lock).st_mode & 0o777 == 0o600


# --------------------------------------------------------------------------- #
# Argument models
# --------------------------------------------------------------------------- #
def test_arg_models_forbid_unknown():
    """Argument models reject unknown keys, bad ranges and inconsistent pairs."""
    with pytest.raises(ValidationError):
        GitRecentArgs(ref="HEAD", limit=3, extra=1)
    with pytest.raises(ValidationError):
        GitRecentArgs(limit=51)
    with pytest.raises(ValidationError):
        GitRecentArgs(limit=0)
    with pytest.raises(ValidationError):
        SourceReadArgs(path="a.py", start_line=5)  # end_line missing
    with pytest.raises(ValidationError):
        SourceReadArgs(path="a.py", start_line=9, end_line=2)  # inverted
    with pytest.raises(ValidationError):
        GitPrepareFilesArgs(paths=[])  # must be non-empty
    with pytest.raises(ValidationError):
        WriterApplyArgs(artifact_id="nothex", reviewed_sha256=HEX64)
    with pytest.raises(ValidationError):
        WriterApplyArgs(artifact_id=HEX32, reviewed_sha256="short")

    assert GitRecentArgs().limit == 3
    assert SourceReadArgs(path="a.py").start_line is None
    assert SourceReadArgs(path="a.py", start_line=1, end_line=10).end_line == 10
    assert WriterApplyArgs(artifact_id=HEX32, reviewed_sha256=HEX64).artifact_id == HEX32


def test_arg_model_json_schema_is_generatable():
    """ToolkitTool reads _args_schema and calls model_json_schema()."""
    schema = GitRecentArgs.model_json_schema()
    assert set(schema["properties"]) == {"ref", "limit"}
    assert schema["additionalProperties"] is False
    assert SourceReadArgs.model_json_schema()["properties"]["expected_sha256"] is not None


def test_target_file_action_hash_binding():
    """'create' forbids an expected hash; 'modify' requires one."""
    with pytest.raises(ValidationError):
        TargetFile(path="a.py", action="create", expected_sha256=HEX64, planned_changes="x", blocks=["b"])
    with pytest.raises(ValidationError):
        TargetFile(path="a.py", action="modify", planned_changes="x", blocks=["b"])
    with pytest.raises(ValidationError):
        TargetFile(path="a.py", action="modify", expected_sha256="A" * 64, planned_changes="x", blocks=["b"])
    with pytest.raises(ValidationError):
        TargetFile(path="a.py", action="create", planned_changes="x", blocks=[])

    assert TargetFile(path="a.py", action="create", planned_changes="x", blocks=["b"]).expected_sha256 is None


def _packet(**overrides):
    """Build a minimal valid DelegationPacket payload."""
    payload = {
        "schema_version": 1,
        "task_id": "TASK-3079",
        "spec_path": "sdd/specs/tool-optimizations.spec.md",
        "design_complete": True,
        "targets": [{"path": "a.py", "action": "create", "planned_changes": "x", "blocks": ["b1"]}],
        "implementation_blocks": ["b1"],
        "acceptance_criteria": ["works"],
        "validation_commands": [["pytest", "-q"]],
    }
    payload.update(overrides)
    return payload


def test_delegation_packet_structural_rules():
    """Version, identity, uniqueness, argv shape and unknown fields are enforced."""
    assert DelegationPacket(**_packet()).limits.max_repairs == 1

    with pytest.raises(ValidationError):
        DelegationPacket(**_packet(schema_version=2))
    with pytest.raises(ValidationError):
        DelegationPacket(**_packet(design_complete=False))
    with pytest.raises(ValidationError):
        DelegationPacket(**_packet(task_id="TASK-XY"))
    with pytest.raises(ValidationError):
        DelegationPacket(**_packet(targets=[]))
    with pytest.raises(ValidationError):
        DelegationPacket(**_packet(implementation_blocks=["b1", "b1"]))
    with pytest.raises(ValidationError):
        DelegationPacket(**_packet(validation_commands=[[]]))
    with pytest.raises(ValidationError):
        DelegationPacket(**_packet(unexpected="x"))

    duplicate_targets = [
        {"path": "a.py", "action": "create", "planned_changes": "x", "blocks": ["b1"]},
        {"path": "a.py", "action": "create", "planned_changes": "y", "blocks": ["b1"]},
    ]
    with pytest.raises(ValidationError):
        DelegationPacket(**_packet(targets=duplicate_targets))


# --------------------------------------------------------------------------- #
# Toolkit base: validation seam and result shaping
# --------------------------------------------------------------------------- #
class _Stub(OptimizationToolkitBase):
    """Minimal toolkit used to exercise the shared base class."""

    arg_models = {"git_recent": GitRecentArgs}

    async def git_recent(self, ref: str = "HEAD", limit: int = 3) -> OperationResult:
        """Stub."""
        return OperationResult(status="ok", operation="git_recent", data={"ref": ref, "limit": limit}, elapsed_ms=0)


async def test_pre_execute_validates_raw_arguments(tmp_path):
    """_pre_execute is the enforcement point for raw MCP arguments."""
    toolkit = _Stub(repo_root=tmp_path)
    await toolkit._pre_execute("git_recent", limit=2, _permission_context=None)

    with pytest.raises(ValueError, match="invalid arguments"):
        await toolkit._pre_execute("git_recent", limit=999)
    with pytest.raises(ValueError, match="invalid arguments"):
        await toolkit._pre_execute("git_recent", bogus="x")
    with pytest.raises(ValueError, match="unknown tool"):
        await toolkit._pre_execute("nope", a=1)


async def test_post_execute_wraps_models(tmp_path):
    """A Pydantic result becomes a JSON-safe ToolResult with empty metadata."""
    toolkit = _Stub(repo_root=tmp_path)
    result = OperationResult(status="error", operation="git_recent", elapsed_ms=0)
    wrapped = await toolkit._post_execute("git_recent", result)

    assert isinstance(wrapped, ToolResult)
    assert wrapped.status == "success"  # domain failure != MCP transport error
    assert wrapped.metadata == {}
    assert wrapped.result["status"] == "error"
    assert isinstance(wrapped.result, dict)

    passthrough = ToolResult(status="success", result={"a": 1})
    assert await toolkit._post_execute("git_recent", passthrough) is passthrough
    assert await toolkit._post_execute("git_recent", {"a": 1}) == {"a": 1}


def test_base_records_policy_init_kwargs(tmp_path):
    """Constructor kwargs are captured for remote toolkit reconstruction."""
    toolkit = _Stub(repo_root=tmp_path, max_lines=10, max_result_bytes=8192)
    assert toolkit.policy.max_lines == 10
    assert toolkit.policy.max_result_bytes == 8192
    assert toolkit._init_kwargs["repo_root"] == str(tmp_path.resolve())
    assert toolkit._init_kwargs["max_lines"] == 10
    assert "repo_root" not in toolkit._init_kwargs.get("policy", {})
    json.dumps(toolkit._init_kwargs)  # must stay serializable


def test_base_result_helpers_are_bounded(tmp_path):
    """_ok/_error always return a result inside the configured budget."""
    toolkit = _Stub(repo_root=tmp_path, max_result_bytes=4096)
    ok = toolkit._ok("git_recent", data={"records": ["y" * 5000] * 10})
    assert ok.status == "ok"
    assert measure_json_bytes(ok.model_dump(mode="json")) <= 4096

    err = toolkit._error("git_push", "push_rejected", "rejected", details={"blob": "z" * 100_000})
    assert err.status == "error"
    assert err.error.code == "push_rejected"
    assert measure_json_bytes(err.model_dump(mode="json")) <= 4096

    uncertain = toolkit._error("git_push", "timeout", "unknown", status="uncertain")
    assert uncertain.status == "uncertain"


def test_stub_exposes_only_its_public_method(tmp_path):
    """The base class adds no accidental public async methods (no stray tools)."""
    names = {tool.name for tool in _Stub(repo_root=tmp_path).get_tools()}
    assert names == {"git_recent"}


# --------------------------------------------------------------------------- #
# Raw MCP boundary
# --------------------------------------------------------------------------- #
async def test_mcp_raw_argument_rejection(tmp_path):
    """Policy holds over raw tools/call, which bypasses AbstractTool.execute."""
    server = StdioMCPServer(LocalServerConfig(name="t"))
    server.register_tools(_Stub(repo_root=tmp_path).get_tools())

    bad = await server._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "git_recent", "arguments": {"limit": 999}},
        }
    )
    assert bad["result"]["isError"] is True

    unknown_key = await server._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "git_recent", "arguments": {"limit": 2, "injected": "x"}},
        }
    )
    assert unknown_key["result"]["isError"] is True

    good = await server._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "git_recent", "arguments": {"limit": 2}},
        }
    )
    assert good["result"]["isError"] is False
    payload = json.loads(good["result"]["content"][0]["text"])
    assert payload["data"]["limit"] == 2
    assert payload["status"] == "ok"
    # metadata={} keeps the adapter from appending a second "Metadata:" block.
    assert len(good["result"]["content"]) == 1
