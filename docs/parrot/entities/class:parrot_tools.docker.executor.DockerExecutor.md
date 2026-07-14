---
type: Wiki Entity
title: DockerExecutor
id: class:parrot_tools.docker.executor.DockerExecutor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async executor for Docker CLI commands.
relates_to:
- concept: class:parrot_tools.security.base_executor.BaseExecutor
  rel: extends
---

# DockerExecutor

Defined in [`parrot_tools.docker.executor`](../summaries/mod:parrot_tools.docker.executor.md).

```python
class DockerExecutor(BaseExecutor)
```

Async executor for Docker CLI commands.

Wraps the Docker CLI and docker compose CLI for structured
container management operations. Parses JSON output into
Pydantic models.

Example:
    config = DockerConfig(docker_cli="docker")
    executor = DockerExecutor(config)

    if await executor.check_daemon():
        result = await executor.run_command(["ps", "--format", "json"])

## Methods

- `async def check_daemon(self) -> bool` — Check if Docker daemon is running.
- `async def check_compose(self) -> bool` — Check if docker compose v2 is available.
- `async def run_command(self, args: list[str], timeout: Optional[int]=None) -> tuple[str, str, int]` — Execute a Docker CLI command asynchronously.
- `async def run_compose_command(self, args: list[str], timeout: Optional[int]=None) -> tuple[str, str, int]` — Execute a docker compose command asynchronously.
- `def parse_ps_output(self, raw: str) -> list[ContainerInfo]` — Parse docker ps JSON output into ContainerInfo list.
- `def parse_images_output(self, raw: str) -> list[ImageInfo]` — Parse docker images JSON output into ImageInfo list.
- `def build_run_args(self, inp: ContainerRunInput) -> list[str]` — Build docker run CLI arguments from ContainerRunInput.
- `def build_exec_args(self, inp: DockerExecInput) -> list[str]` — Build docker exec CLI arguments from DockerExecInput.
- `def build_build_args(self, inp: DockerBuildInput) -> list[str]` — Build docker build CLI arguments from DockerBuildInput.
- `def make_error_result(self, operation: str, error: str) -> DockerOperationResult` — Create a failed DockerOperationResult.
- `def make_success_result(self, operation: str, output: str='', containers: Optional[list[ContainerInfo]]=None, images: Optional[list[ImageInfo]]=None) -> DockerOperationResult` — Create a successful DockerOperationResult.
