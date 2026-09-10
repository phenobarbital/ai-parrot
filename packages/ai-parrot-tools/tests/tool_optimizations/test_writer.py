"""Unit tests for TargetedWriterToolkit.writer_generate (TASK-3085, FEAT-543)."""

import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from parrot_tools.tool_optimizations.models import WriterLimits
from parrot_tools.tool_optimizations.writer import SYSTEM_PROMPT, TargetedWriterToolkit, build_prompt

from .fixtures import GOOD_PATCH, make_repo_with_target, make_valid_task

#: Exactly the keyword arguments the writer is allowed to pass to `ask`.
EXPECTED_ASK_KWARGS = {"prompt", "system_prompt", "max_tokens", "temperature", "use_tools", "history"}


class FakeClient:
    """A recording stand-in exposing only the attributes the writer may use.

    Any attribute access outside the documented surface raises, so the test
    suite fails loudly if the writer starts depending on something new.
    """

    _ALLOWED = {
        "model",
        "_fallback_model",
        "ask",
        "close",
        "calls",
        "entered",
        "exited",
        "_responses",
        "_delay",
        "_metadata",
        "_usage",
        "_response_model",
        "__aenter__",
        "__aexit__",
    }

    def __init__(
        self,
        responses,
        *,
        fallback=None,
        delay=0.0,
        metadata=None,
        usage=(10, 20, 30),
        model="qwen3-coder-480b-a35b",
        response_model=None,
    ):
        """Initialize the fake.

        Args:
            responses: Successive `ask` return payloads.
            fallback: The `_fallback_model` value to advertise.
            delay: Seconds to sleep inside `ask`.
            metadata: Metadata attached to every response.
            usage: (prompt, completion, total) token counts.
            model: The client's *configured* model identity.
            response_model: The model identity the provider reports back,
                when it differs from the configured one (a substitution).
        """
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "_fallback_model", fallback)
        object.__setattr__(self, "_responses", list(responses))
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "entered", 0)
        object.__setattr__(self, "exited", 0)
        object.__setattr__(self, "_delay", delay)
        object.__setattr__(self, "_metadata", metadata or {})
        object.__setattr__(self, "_usage", usage)
        object.__setattr__(self, "_response_model", response_model or model)

    def __getattr__(self, name):
        """Fail loudly when the writer touches an undocumented attribute."""
        raise AssertionError(f"the writer touched an unexpected client attribute: {name!r}")

    async def __aenter__(self):
        """Record entry."""
        object.__setattr__(self, "entered", self.entered + 1)
        return self

    async def __aexit__(self, *exc_info):
        """Record exit."""
        object.__setattr__(self, "exited", self.exited + 1)
        return False

    async def close(self):
        """No resources to release."""

    async def ask(self, **kwargs):
        """Record the call and return the next scripted response."""
        self.calls.append(kwargs)
        if self._delay:
            await asyncio.sleep(self._delay)
        payload = self._responses.pop(0)
        usage = SimpleNamespace(
            prompt_tokens=self._usage[0], completion_tokens=self._usage[1], total_tokens=self._usage[2]
        )
        return SimpleNamespace(
            response=payload if isinstance(payload, str) else None,
            output=payload,
            model=self._response_model,
            provider="bedrock-converse",
            usage=usage,
            metadata=dict(self._metadata),
        )


def _setup(tmp_path):
    """Build the fixture repo and its eligible TASK file."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    return repo, task.relative_to(repo).as_posix()


def _artifacts(repo):
    """List published artifact directories."""
    root = repo / "artifacts" / "tool-optimizations"
    return (
        [entry for entry in root.iterdir() if entry.is_dir() and not entry.name.startswith(".tmp-")]
        if root.exists()
        else []
    )


# --------------------------------------------------------------------------- #
# Constructor / configuration
# --------------------------------------------------------------------------- #
def test_constructor_rejects_client_that_permits_fallback(tmp_path):
    """A client with a fallback model could silently answer as another model."""
    with pytest.raises(ValueError, match="fallback"):
        TargetedWriterToolkit(repo_root=tmp_path, llm_client=FakeClient([], fallback="claude-haiku-4-5"))

    toolkit = TargetedWriterToolkit(repo_root=tmp_path, llm_client=FakeClient([], fallback=None))
    assert toolkit.llm_dependent_tools == {"writer_generate"}
    assert toolkit.confirming_tools == {"writer_apply"}


def test_tool_surface(tmp_path):
    """Both tools exist; only generation depends on a model."""
    tools = TargetedWriterToolkit(repo_root=tmp_path).get_tools()
    assert {tool.name for tool in tools} == {"writer_generate", "writer_apply"}
    apply_tool = next(tool for tool in tools if tool.name == "writer_apply")
    assert (apply_tool.routing_meta or {}).get("requires_confirmation") is True


def test_importing_writer_does_not_import_aws_sdk():
    """Provider satellites stay lazy: git/reader/writer import without boto."""
    import subprocess
    import sys

    code = "import parrot_tools.tool_optimizations.writer, sys; print(any('boto' in m for m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"


async def test_no_client_configured(tmp_path):
    """Without a client, generation reports it rather than crashing."""
    repo, task = _setup(tmp_path)
    result = await TargetedWriterToolkit(repo_root=repo).writer_generate(task)
    assert result.status == "error"
    assert result.error.code == "no_client"


async def test_client_lifecycle(tmp_path):
    """The toolkit opens and closes a client it owns, exactly once."""
    fake = FakeClient([])
    toolkit = TargetedWriterToolkit(repo_root=tmp_path, llm_client=fake)
    await toolkit._ensure_open()
    await toolkit._ensure_open()
    assert fake.entered == 1
    await toolkit._close()
    assert fake.exited == 1

    shared = FakeClient([])
    borrower = TargetedWriterToolkit(repo_root=tmp_path, llm_client=shared, owns_client=False)
    await borrower._ensure_open()
    await borrower._close()
    assert shared.entered == 0 and shared.exited == 0


# --------------------------------------------------------------------------- #
# Contract gating — no model call
# --------------------------------------------------------------------------- #
async def test_invalid_contract_makes_no_call(tmp_path):
    """An ineligible TASK never reaches the delegate (AC7)."""
    repo, task = _setup(tmp_path)
    task_file = repo / task
    task_file.write_text(task_file.read_text().replace('"design_complete": true', '"design_complete": false'))

    fake = FakeClient([GOOD_PATCH])
    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.status == "error"
    assert result.error.code == "invalid_packet"
    assert fake.calls == []
    assert _artifacts(repo) == []


async def test_stale_contract_makes_no_call(tmp_path):
    """A target edited after the packet was written also short-circuits."""
    repo, task = _setup(tmp_path)
    (repo / "pkg" / "__init__.py").write_text("changed\n")

    fake = FakeClient([GOOD_PATCH])
    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.status == "error"
    assert result.error.code in {"stale_target", "stale_reference"}
    assert fake.calls == []


# --------------------------------------------------------------------------- #
# Successful generation
# --------------------------------------------------------------------------- #
async def test_generate_ok_and_no_target_mutation(tmp_path):
    """A valid diff is stored as an artifact and no target file is touched."""
    repo, task = _setup(tmp_path)
    before = (repo / "pkg" / "__init__.py").read_bytes()
    fake = FakeClient([GOOD_PATCH])

    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.status == "ok"
    assert (repo / result.data["patch_path"]).exists()
    assert result.data["targets"] == ["pkg/__init__.py", "pkg/greeter.py"]
    assert result.data["repairs"] == 0
    assert result.data["usage"] == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    assert result.data["actual_model"] == "qwen3-coder-480b-a35b"

    # Generation must never mutate the worktree.
    assert (repo / "pkg" / "__init__.py").read_bytes() == before
    assert not (repo / "pkg" / "greeter.py").exists()

    artifact = _artifacts(repo)[0]
    assert {entry.name for entry in artifact.iterdir()} == {"manifest.json", "patch.diff", "packet.json"}
    stored = (artifact / "patch.diff").read_text()
    assert hashlib.sha256(stored.encode()).hexdigest() == result.data["patch_sha256"]


async def test_call_uses_exactly_the_approved_kwargs(tmp_path):
    """No tools, no history, no research — and nothing else is passed."""
    repo, task = _setup(tmp_path)
    fake = FakeClient([GOOD_PATCH])
    await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)

    call = fake.calls[0]
    assert set(call) == EXPECTED_ASK_KWARGS
    assert call["use_tools"] is False
    assert call["history"] is None
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 8192
    assert call["system_prompt"] == SYSTEM_PROMPT
    assert "model" not in call  # a per-call override would be a substitution channel


async def test_prompt_contains_only_approved_content(tmp_path):
    """The delegate sees the packet and its excerpts, never whole files."""
    repo, task = _setup(tmp_path)
    (repo / "pkg" / "secret_other.py").write_text("UNAPPROVED CONTENT MARKER\n")
    fake = FakeClient([GOOD_PATCH])
    await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)

    prompt = fake.calls[0]["prompt"]
    assert "UNAPPROVED CONTENT MARKER" not in prompt
    assert "TASK-9999" in prompt
    assert "impl-greeter" in prompt
    assert "pytest tests/test_greeter.py passes" in prompt


async def test_usage_unknown_is_recorded_as_none(tmp_path):
    """Missing provider usage is unknown, never zero."""
    repo, task = _setup(tmp_path)
    fake = FakeClient([GOOD_PATCH], usage=(0, 0, 0))
    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.data["usage"] == {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}


# --------------------------------------------------------------------------- #
# Repair budget
# --------------------------------------------------------------------------- #
async def test_one_repair_then_success(tmp_path):
    """A malformed patch earns exactly one repair, with a bounded diagnostic."""
    repo, task = _setup(tmp_path)
    fake = FakeClient(["```diff\nnope\n```", GOOD_PATCH])

    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.status == "ok"
    assert result.data["repairs"] == 1
    assert len(fake.calls) == 2
    assert "not_a_patch" in fake.calls[1]["prompt"]
    assert result.data["usage"]["total_tokens"] == 60  # summed across both attempts


async def test_two_failures_stop_without_artifact(tmp_path):
    """The repair budget is one; a second failure ends the operation."""
    repo, task = _setup(tmp_path)
    fake = FakeClient(["prose only", "still prose", GOOD_PATCH])

    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.status == "error"
    assert result.error.code == "not_a_patch"
    assert result.error.details["repairs"] == 1
    assert len(fake.calls) == 2
    assert _artifacts(repo) == []


async def test_out_of_scope_patch_is_rejected(tmp_path):
    """A diff touching an unapproved file is refused, not applied."""
    repo, task = _setup(tmp_path)
    rogue = "--- a/pkg/other.py\n+++ b/pkg/other.py\n@@ -1 +1 @@\n-a\n+b\n"
    fake = FakeClient([rogue, rogue])

    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.status == "error"
    assert result.error.code == "path_outside_scope"
    assert _artifacts(repo) == []


# --------------------------------------------------------------------------- #
# Model identity
# --------------------------------------------------------------------------- #
async def test_model_substitution_rejected_without_repair(tmp_path):
    """A fallback answer aborts immediately — a repair would compound it."""
    repo, task = _setup(tmp_path)
    fake = FakeClient([GOOD_PATCH, GOOD_PATCH], metadata={"used_fallback_model": True})

    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.error.code == "model_substituted"
    assert len(fake.calls) == 1
    assert _artifacts(repo) == []


async def test_unexpected_model_identity_rejected(tmp_path):
    """When operators pin model ids, an unlisted identity is a substitution."""
    repo, task = _setup(tmp_path)
    fake = FakeClient([GOOD_PATCH], response_model="some-other-model")
    toolkit = TargetedWriterToolkit(
        repo_root=repo, llm_client=fake, expected_model_ids=("qwen.qwen3-coder-480b-a35b-v1:0",)
    )
    result = await toolkit.writer_generate(task)
    assert result.error.code == "model_substituted"
    assert result.error.details["configured"] == "qwen3-coder-480b-a35b"
    assert result.error.details["actual"] == "some-other-model"


async def test_translated_bedrock_model_id_is_accepted(tmp_path):
    """Bedrock reports a translated id; operators list it and it passes."""
    repo, task = _setup(tmp_path)
    fake = FakeClient([GOOD_PATCH], response_model="qwen.qwen3-coder-480b-a35b-v1:0")
    toolkit = TargetedWriterToolkit(
        repo_root=repo, llm_client=fake, expected_model_ids=("qwen.qwen3-coder-480b-a35b-v1:0",)
    )
    result = await toolkit.writer_generate(task)
    assert result.status == "ok"


async def test_tool_call_and_structured_output_rejected(tmp_path):
    """The delegate has no tools; a structured response is a contract breach."""
    repo, task = _setup(tmp_path)

    fake = FakeClient([{"tool": "read_file"}])
    result = await TargetedWriterToolkit(repo_root=repo, llm_client=fake).writer_generate(task)
    assert result.error.code == "unexpected_tool_call"

    fake2 = FakeClient([GOOD_PATCH], metadata={"tool_calls": [{"name": "x"}]})
    result2 = await TargetedWriterToolkit(repo_root=repo, llm_client=fake2).writer_generate(task)
    assert result2.error.code == "unexpected_tool_call"


# --------------------------------------------------------------------------- #
# Deadline and cancellation
# --------------------------------------------------------------------------- #
async def test_deadline_exceeded(tmp_path):
    """A slow provider hits the operation deadline and stores nothing."""
    repo, task = _setup(tmp_path)
    fake = FakeClient([GOOD_PATCH], delay=5.0)
    toolkit = TargetedWriterToolkit(repo_root=repo, llm_client=fake, limits=WriterLimits(generation_deadline_seconds=1))
    result = await toolkit.writer_generate(task)
    assert result.status == "error"
    assert result.error.code == "deadline_exceeded"
    assert _artifacts(repo) == []


async def test_cancellation_leaves_no_artifact(tmp_path):
    """Cancelling mid-call publishes nothing and does not swallow the cancel."""
    repo, task = _setup(tmp_path)
    fake = FakeClient([GOOD_PATCH], delay=5.0)
    toolkit = TargetedWriterToolkit(repo_root=repo, llm_client=fake)

    task_handle = asyncio.create_task(toolkit.writer_generate(task))
    await asyncio.sleep(0.1)
    task_handle.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_handle

    assert _artifacts(repo) == []
    assert not (repo / "pkg" / "greeter.py").exists()


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
async def test_build_prompt_is_deterministic(tmp_path):
    """The same contract renders the same prompt every time."""
    from parrot_tools.tool_optimizations.contracts import validate_contract
    from parrot_tools.tool_optimizations.policy import OptimizationPolicy

    repo, task = _setup(tmp_path)
    contract = await validate_contract(OptimizationPolicy(repo_root=repo), task)
    assert build_prompt(contract) == build_prompt(contract)
    assert "Return only the unified diff" in build_prompt(contract)


def test_system_prompt_forbids_prose_and_scope_creep():
    """The delegate's instructions pin the output shape and the file scope."""
    assert "ONLY a unified diff" in SYSTEM_PROMPT
    assert "no markdown fences" in SYSTEM_PROMPT
    assert "Never touch any other" in SYSTEM_PROMPT
    assert "Never invent an API" in SYSTEM_PROMPT


async def test_writer_apply_rejects_unknown_artifact(tmp_path):
    """Apply refuses an artifact it never generated (full behaviour: TASK-3086)."""
    repo, _task = _setup(tmp_path)
    result = await TargetedWriterToolkit(repo_root=repo).writer_apply("0" * 32, "a" * 64)
    assert result.status == "error"
    assert result.error.code == "artifact_not_found"


async def test_writer_apply_validates_its_arguments(tmp_path):
    """A malformed artifact id or review hash never reaches the store."""
    repo, _task = _setup(tmp_path)
    toolkit = TargetedWriterToolkit(repo_root=repo)
    assert (await toolkit.writer_apply("not-hex", "a" * 64)).error.code == "invalid_arguments"
    assert (await toolkit.writer_apply("0" * 32, "short")).error.code == "invalid_arguments"
