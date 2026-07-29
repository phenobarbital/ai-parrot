"""Tests for DockerToolExecutor with a fully mocked aiodocker.

We never reach a real Docker daemon — the ``aiodocker`` module is
replaced with a fake that records container/exec/image operations and
returns the output we expect the worker process to print between the
sentinel markers. This locks down the executor's orchestration logic
(warm reuse, ephemeral create→remove, envelope upload, sentinel
parsing, timeout handling, idle-TTL reaping, close) without requiring
Docker in CI.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any, Dict

import pytest


@pytest.fixture
def docker_mocks(monkeypatch):
    """Inject a fake ``aiodocker`` module with the API surface used by
    :class:`DockerToolExecutor`. Returns the shared mock state."""
    state: Dict[str, Any] = {
        "created": [],          # {"config": ..., "name": ...}
        "started": [],
        "deleted": [],
        "put_archives": [],     # (container_name, path, tar_bytes)
        "exec_cmds": [],
        "images_inspected": [],
        "images_pulled": [],
        "client_urls": [],
        "client_closes": 0,
        "output": "",           # worker stdout the fake returns
        "image_missing": False,
        "hang_exec": False,     # make exec output never arrive
    }

    class _Stream:
        def __init__(self):
            data = state["output"].encode("utf-8")
            self._chunks = [data] if data else []

        async def read_out(self):
            if state["hang_exec"]:
                await asyncio.sleep(3600)
            if self._chunks:
                return types.SimpleNamespace(stream=1, data=self._chunks.pop(0))
            return None

    class _ExecStart:
        async def __aenter__(self):
            return _Stream()

        async def __aexit__(self, *exc_info):
            return False

    class _Exec:
        id = "exec-abc123"

        def start(self, detach=False):
            return _ExecStart()

    class _Container:
        def __init__(self, config, name):
            self.id = f"cid-{name}"
            self.name = name
            self.config = config

        async def start(self):
            state["started"].append(self.name)

        async def put_archive(self, path, data):
            state["put_archives"].append((self.name, path, data))
            return True

        async def exec(self, cmd, stdout=True, stderr=True, **kwargs):
            state["exec_cmds"].append(cmd)
            return _Exec()

        async def wait(self):
            if state["hang_exec"]:
                await asyncio.sleep(3600)
            return {"StatusCode": 0}

        async def log(self, stdout=True, stderr=True):
            return [state["output"]]

        async def delete(self, force=False):
            state["deleted"].append(self.name)

    class _Containers:
        async def create(self, config, name=None):
            state["created"].append({"config": config, "name": name})
            return _Container(config, name)

    class _Images:
        async def inspect(self, image):
            state["images_inspected"].append(image)
            if state["image_missing"]:
                raise RuntimeError("404 image not found")
            return {"Id": "sha256:abc"}

        async def pull(self, image):
            state["images_pulled"].append(image)

    class _Docker:
        def __init__(self, url=None):
            state["client_urls"].append(url)
            self.containers = _Containers()
            self.images = _Images()

        async def close(self):
            state["client_closes"] += 1

    fake_module = types.ModuleType("aiodocker")
    fake_module.Docker = _Docker
    monkeypatch.setitem(sys.modules, "aiodocker", fake_module)

    yield state


def _wrap_output(payload: dict) -> str:
    body = json.dumps(payload)
    return (
        "info: worker chatter\n"
        f"__PARROT_TOOL_RESULT_BEGIN__\n{body}\n__PARROT_TOOL_RESULT_END__\n"
    )


def _envelope(timeout: int = 5):
    from parrot.tools.executors import ToolExecutionEnvelope

    return ToolExecutionEnvelope(
        tool_import_path="tests.tools.executors._fixtures:EchoTool",
        tool_init_kwargs={},
        arguments={"msg": "ping"},
        timeout_seconds=timeout,
    )


def _executor(**kwargs):
    from parrot.tools.executors.docker import DockerToolExecutor

    kwargs.setdefault("image", "parrot-tools:test")
    return DockerToolExecutor(**kwargs)


@pytest.mark.asyncio
async def test_warm_mode_reuses_one_container(docker_mocks):
    docker_mocks["output"] = _wrap_output(
        {"success": True, "status": "success", "result": "echo:ping",
         "metadata": {"tool": "echo_tool"}}
    )
    ex = _executor(mode="warm")

    result1 = await ex.execute(_envelope())
    result2 = await ex.execute(_envelope())

    assert result1.status == "success"
    assert result1.result == "echo:ping"
    assert result1.metadata.get("executor") == "docker"
    assert result1.metadata.get("mode") == "warm"
    assert result1.metadata.get("container_id", "").startswith("cid-")
    assert result2.status == "success"
    # One warm container serves both calls.
    assert len(docker_mocks["created"]) == 1
    assert docker_mocks["created"][0]["config"]["Cmd"] == ["sleep", "infinity"]
    # Each call uploads its own envelope and runs the worker via exec.
    assert len(docker_mocks["put_archives"]) == 2
    assert len(docker_mocks["exec_cmds"]) == 2
    assert "parrot.cli.tool_worker" in " ".join(docker_mocks["exec_cmds"][0])

    await ex.close()
    assert len(docker_mocks["deleted"]) == 1
    assert docker_mocks["client_closes"] == 1
    # close() is idempotent.
    await ex.close()


@pytest.mark.asyncio
async def test_ephemeral_mode_creates_and_removes_per_call(docker_mocks):
    docker_mocks["output"] = _wrap_output(
        {"success": True, "status": "success", "result": "echo:ping",
         "metadata": {}}
    )
    ex = _executor(mode="ephemeral")

    result = await ex.execute(_envelope())
    await ex.execute(_envelope())

    assert result.status == "success"
    assert result.metadata.get("mode") == "ephemeral"
    assert len(docker_mocks["created"]) == 2
    assert len(docker_mocks["deleted"]) == 2
    cmd = docker_mocks["created"][0]["config"]["Cmd"]
    assert cmd[:4] == ["python", "-m", "parrot.cli.tool_worker", "--envelope"]
    # Envelope was uploaded before start.
    assert len(docker_mocks["put_archives"]) == 2
    await ex.close()


@pytest.mark.asyncio
async def test_missing_result_markers_is_error(docker_mocks):
    docker_mocks["output"] = "no markers, just chatter\n"
    ex = _executor(mode="warm")
    result = await ex.execute(_envelope())
    assert result.status == "error"
    assert "result block" in (result.error or "")
    await ex.close()


@pytest.mark.asyncio
async def test_invalid_json_is_error(docker_mocks):
    docker_mocks["output"] = (
        "__PARROT_TOOL_RESULT_BEGIN__\nnot-json\n__PARROT_TOOL_RESULT_END__\n"
    )
    ex = _executor(mode="ephemeral")
    result = await ex.execute(_envelope())
    assert result.status == "error"
    assert "invalid JSON" in (result.error or "")
    await ex.close()


@pytest.mark.asyncio
async def test_timeout_returns_error_and_resets_warm_container(docker_mocks):
    docker_mocks["output"] = "irrelevant"
    docker_mocks["hang_exec"] = True
    ex = _executor(mode="warm")
    result = await ex.execute(_envelope(timeout=1))
    assert result.status == "error"
    assert "did not finish" in (result.error or "")
    # The stuck warm container was torn down so the next call starts clean.
    assert len(docker_mocks["deleted"]) == 1
    await ex.close()


@pytest.mark.asyncio
async def test_hardened_host_config(docker_mocks):
    docker_mocks["output"] = _wrap_output(
        {"success": True, "status": "success", "result": "ok", "metadata": {}}
    )
    ex = _executor(
        mode="ephemeral",
        network_mode="none",
        mem_limit="256m",
        pids_limit=64,
        env={"FOO": "bar"},
        labels={"team": "data"},
        volumes=["/data:/data:ro"],
    )
    await ex.execute(_envelope())

    config = docker_mocks["created"][0]["config"]
    host = config["HostConfig"]
    assert host["NetworkMode"] == "none"
    assert host["Memory"] == 256 * 1024**2
    assert host["PidsLimit"] == 64
    assert host["CapDrop"] == ["ALL"]
    assert host["SecurityOpt"] == ["no-new-privileges"]
    assert host["Binds"] == ["/data:/data:ro"]
    assert "FOO=bar" in config["Env"]
    assert config["Labels"]["team"] == "data"
    assert config["Labels"]["parrot-executor"] == "true"
    await ex.close()


@pytest.mark.asyncio
async def test_idle_ttl_reaps_warm_container(docker_mocks):
    docker_mocks["output"] = _wrap_output(
        {"success": True, "status": "success", "result": "ok", "metadata": {}}
    )
    ex = _executor(mode="warm", idle_ttl_seconds=60)
    await ex.execute(_envelope())
    assert len(docker_mocks["deleted"]) == 0

    # Not idle long enough — nothing happens.
    assert await ex._maybe_reap() is False
    # Simulate the TTL having elapsed.
    ex._last_used -= 61
    assert await ex._maybe_reap() is True
    assert len(docker_mocks["deleted"]) == 1
    # The next call transparently creates a fresh warm container.
    result = await ex.execute(_envelope())
    assert result.status == "success"
    assert len(docker_mocks["created"]) == 2
    await ex.close()


@pytest.mark.asyncio
async def test_pull_policy(docker_mocks):
    docker_mocks["output"] = _wrap_output(
        {"success": True, "status": "success", "result": "ok", "metadata": {}}
    )
    # missing + image present locally → inspect only, no pull.
    ex = _executor(mode="ephemeral", pull_policy="missing")
    await ex.execute(_envelope())
    assert docker_mocks["images_inspected"] == ["parrot-tools:test"]
    assert docker_mocks["images_pulled"] == []
    await ex.close()

    # missing + image absent → pulled.
    docker_mocks["image_missing"] = True
    ex = _executor(mode="ephemeral", pull_policy="missing")
    await ex.execute(_envelope())
    assert docker_mocks["images_pulled"] == ["parrot-tools:test"]
    await ex.close()

    # always → pulled without inspecting.
    docker_mocks["image_missing"] = False
    inspected_before = len(docker_mocks["images_inspected"])
    ex = _executor(mode="ephemeral", pull_policy="always")
    await ex.execute(_envelope())
    assert docker_mocks["images_pulled"][-1] == "parrot-tools:test"
    assert len(docker_mocks["images_inspected"]) == inspected_before
    await ex.close()


@pytest.mark.asyncio
async def test_execute_after_close_is_error(docker_mocks):
    ex = _executor(mode="warm")
    await ex.close()
    result = await ex.execute(_envelope())
    assert result.status == "error"
    assert "closed" in (result.error or "")


def test_invalid_mode_and_pull_policy_raise(docker_mocks):
    with pytest.raises(ValueError, match="mode"):
        _executor(mode="sometimes")
    with pytest.raises(ValueError, match="pull_policy"):
        _executor(pull_policy="occasionally")


def test_mem_limit_parsing(docker_mocks):
    from parrot.tools.executors.docker import _mem_bytes

    assert _mem_bytes(1024) == 1024
    assert _mem_bytes("512m") == 512 * 1024**2
    assert _mem_bytes("1G") == 1024**3
    assert _mem_bytes("128k") == 128 * 1024
    with pytest.raises(ValueError):
        _mem_bytes("lots")


def test_missing_aiodocker_raises_clear_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "aiodocker", None)
    from parrot.tools.executors.docker import DockerToolExecutor

    with pytest.raises(ImportError, match="remote-tools"):
        DockerToolExecutor(image="x")
