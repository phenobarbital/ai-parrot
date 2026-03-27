"""Integration tests for Docker Toolkit.

These tests run against a live Docker daemon. They are skipped
automatically when Docker is not available.

Run with:
    pytest tests/tools/docker/test_integration.py -v -m integration
"""

import asyncio
import os
import shutil
import uuid

import pytest

from parrot.tools.docker.toolkit import DockerToolkit

docker_available = shutil.which("docker") is not None

# Unique prefix for all test resources to avoid collisions
TEST_PREFIX = f"parrot-test-{uuid.uuid4().hex[:8]}"


def _container_name(suffix: str) -> str:
    """Generate a unique container name for tests."""
    return f"{TEST_PREFIX}-{suffix}"


@pytest.fixture
def toolkit():
    """Create a DockerToolkit instance."""
    return DockerToolkit()



@pytest.mark.integration
@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestDockerIntegrationPS:
    """Test docker_ps against live daemon."""

    @pytest.mark.asyncio
    async def test_docker_ps_live(self, toolkit):
        """docker_ps should return a successful result."""
        result = await toolkit.docker_ps()
        assert result.success is True
        assert result.operation == "docker_ps"

    @pytest.mark.asyncio
    async def test_docker_ps_all(self, toolkit):
        """docker_ps with all=True should include stopped containers."""
        result = await toolkit.docker_ps(all=True)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_docker_images_live(self, toolkit):
        """docker_images should return a successful result."""
        result = await toolkit.docker_images()
        assert result.success is True
        assert result.operation == "docker_images"


@pytest.mark.integration
@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestDockerIntegrationLifecycle:
    """Full container lifecycle: run -> logs -> exec -> stop -> rm."""

    @pytest.mark.asyncio
    async def test_run_logs_exec_stop_rm(self, toolkit):
        """Full lifecycle test with an alpine container."""
        name = _container_name("lifecycle")

        try:
            # 1. Run a container
            result = await toolkit.docker_run(
                image="alpine:latest",
                name=name,
                command="sh -c 'echo hello-parrot && sleep 30'",
                detach=True,
            )
            assert result.success is True, f"docker_run failed: {result.error}"

            # Wait briefly for container to start
            await asyncio.sleep(2)

            # 2. Check logs
            log_result = await toolkit.docker_logs(container=name, tail=10)
            assert log_result.success is True, f"docker_logs failed: {log_result.error}"
            assert "hello-parrot" in log_result.output

            # 3. Exec a command inside
            exec_result = await toolkit.docker_exec(
                container=name,
                command="echo exec-works",
            )
            assert exec_result.success is True, f"docker_exec failed: {exec_result.error}"
            assert "exec-works" in exec_result.output

            # 4. Inspect
            inspect_result = await toolkit.docker_inspect(container=name)
            assert inspect_result.success is True, f"docker_inspect failed: {inspect_result.error}"
            assert name in inspect_result.output

            # 5. Test health (container running check)
            test_result = await toolkit.docker_test(container=name)
            assert test_result.success is True, f"docker_test failed: {test_result.error}"
            assert "running" in test_result.output.lower()

            # 6. Stop
            stop_result = await toolkit.docker_stop(container=name, timeout=5)
            assert stop_result.success is True, f"docker_stop failed: {stop_result.error}"

            # 7. Remove
            rm_result = await toolkit.docker_rm(container=name)
            assert rm_result.success is True, f"docker_rm failed: {rm_result.error}"

        finally:
            # Cleanup: force remove in case test failed midway
            await toolkit.docker_rm(container=name, force=True)


@pytest.mark.integration
@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestDockerIntegrationBuild:
    """Test docker_build against live daemon."""

    @pytest.mark.asyncio
    async def test_docker_build(self, toolkit):
        """Build an image from the test Dockerfile."""
        fixtures_dir = os.path.join(
            os.path.dirname(__file__), "fixtures"
        )
        tag = f"{TEST_PREFIX}-build:test"

        try:
            result = await toolkit.docker_build(
                tag=tag,
                dockerfile_path=fixtures_dir,
                no_cache=True,
            )
            assert result.success is True, f"docker_build failed: {result.error}"

            # Verify image exists
            images_result = await toolkit.docker_images()
            assert images_result.success is True

        finally:
            # Cleanup: remove the built image
            from parrot.tools.docker.executor import DockerExecutor

            executor = DockerExecutor()
            await executor.run_command(["rmi", "-f", tag])


@pytest.mark.integration
@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestDockerIntegrationCompose:
    """Test compose generate -> up -> down lifecycle."""

    @pytest.mark.asyncio
    async def test_compose_generate_and_up(self, toolkit, tmp_path):
        """Generate a compose file, deploy it, then tear it down."""
        compose_file = str(tmp_path / "docker-compose.yml")

        try:
            # 1. Generate compose file
            gen_result = await toolkit.docker_compose_generate(
                project_name="parrot-test",
                services={"alpine-test": {"image": "alpine:latest", "command": "sh -c 'echo compose-test && sleep 30'", "restart": "no"}},
                output_path=compose_file,
            )
            assert gen_result.success is True, f"compose_generate failed: {gen_result.error}"
            assert os.path.exists(compose_file)

            # 2. Deploy
            up_result = await toolkit.docker_compose_up(
                compose_file=compose_file, detach=True
            )
            assert up_result.success is True, f"compose_up failed: {up_result.error}"

            # Wait for container to start
            await asyncio.sleep(2)

        finally:
            # 3. Tear down (always clean up)
            await toolkit.docker_compose_down(
                compose_file=compose_file,
                volumes=True,
                remove_orphans=True,
            )
            # Don't assert success here — cleanup should be best-effort


@pytest.mark.integration
@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestDockerIntegrationPrune:
    """Test docker_prune operations."""

    @pytest.mark.asyncio
    async def test_docker_prune_containers(self, toolkit):
        """Prune stopped containers (safe operation)."""
        result = await toolkit.docker_prune(
            containers=True, images=False, volumes=False
        )
        assert result.success is True


@pytest.mark.integration
@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestDockerIntegrationHealth:
    """Test docker_test health check."""

    @pytest.mark.asyncio
    async def test_docker_test_not_found(self, toolkit):
        """Health-check a non-existent container should fail."""
        result = await toolkit.docker_test(
            container="parrot-nonexistent-container-xyz"
        )
        assert result.success is False
        assert "not found" in result.error.lower() or result.error

    @pytest.mark.asyncio
    async def test_docker_test_running(self, toolkit):
        """Health-check a running container should succeed."""
        name = _container_name("health")
        try:
            await toolkit.docker_run(
                image="alpine:latest",
                name=name,
                command="sleep 30",
                detach=True,
            )
            await asyncio.sleep(1)

            result = await toolkit.docker_test(container=name)
            assert result.success is True
            assert "running" in result.output.lower()

        finally:
            await toolkit.docker_rm(container=name, force=True)
