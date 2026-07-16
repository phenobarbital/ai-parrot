---
type: Wiki Entity
title: DockerToolkit
id: class:parrot_tools.docker.toolkit.DockerToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for managing Docker containers and compose stacks.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# DockerToolkit

Defined in [`parrot_tools.docker.toolkit`](../summaries/mod:parrot_tools.docker.toolkit.md).

```python
class DockerToolkit(AbstractToolkit)
```

Toolkit for managing Docker containers and compose stacks.

Each public async method is exposed as a separate tool with the `docker_` prefix.

Available Operations:
- docker_ps: List running containers
- docker_images: List available images
- docker_run: Launch a new container
- docker_stop: Stop a running container
- docker_start: Start a stopped container
- docker_restart: Restart an existing container
- docker_rm: Remove a container
- docker_logs: View container logs
- docker_inspect: Get detailed container info
- docker_prune: Clean up unused resources
- docker_build: Build a Docker image
- docker_exec: Execute a command in a container
- docker_compose_generate: Generate a docker-compose.yml
- docker_compose_up: Deploy a compose stack
- docker_compose_down: Tear down a compose stack
- docker_test: Health-check a running container

Example:
    toolkit = DockerToolkit()
    tools = toolkit.get_tools()

    # Use with agent
    agent = Agent(tools=tools)

## Methods

- `async def docker_ps(self, all: bool=False, filters: Optional[Dict[str, str]]=None) -> DockerOperationResult` — List Docker containers.
- `async def docker_images(self, filters: Optional[Dict[str, str]]=None) -> DockerOperationResult` — List Docker images.
- `async def docker_inspect(self, container: str) -> DockerOperationResult` — Get detailed container information.
- `async def docker_logs(self, container: str, tail: int=100, since: Optional[str]=None) -> DockerOperationResult` — View container logs.
- `async def docker_run(self, image: str, name: Optional[str]=None, ports: Optional[List[Dict[str, Any]]]=None, volumes: Optional[List[Dict[str, Any]]]=None, env_vars: Optional[Dict[str, str]]=None, command: Optional[str]=None, detach: bool=True, restart_policy: Optional[str]=None, cpu_limit: Optional[str]=None, memory_limit: Optional[str]=None) -> DockerOperationResult` — Launch a new Docker container.
- `async def docker_stop(self, container: str, timeout: int=10) -> DockerOperationResult` — Stop a running container.
- `async def docker_start(self, container: str) -> DockerOperationResult` — Start a stopped Docker container.
- `async def docker_restart(self, container: str, timeout: int=10) -> DockerOperationResult` — Restart an existing Docker container.
- `async def docker_rm(self, container: str, force: bool=False, volumes: bool=False) -> DockerOperationResult` — Remove a Docker container.
- `async def docker_build(self, tag: str, dockerfile_path: str='.', build_args: Optional[Dict[str, str]]=None, no_cache: bool=False) -> DockerOperationResult` — Build a Docker image from a Dockerfile.
- `async def docker_exec(self, container: str, command: str, workdir: Optional[str]=None, env_vars: Optional[Dict[str, str]]=None, user: Optional[str]=None) -> DockerOperationResult` — Execute a command inside a running container.
- `async def docker_compose_generate(self, project_name: str, services: Dict[str, Dict[str, Any]], output_path: str='./docker-compose.yml') -> DockerOperationResult` — Generate a docker-compose.yml file from service definitions.
- `async def docker_compose_up(self, compose_file: str='./docker-compose.yml', detach: bool=True, build: bool=False) -> DockerOperationResult` — Deploy a docker-compose stack.
- `async def docker_compose_down(self, compose_file: str='./docker-compose.yml', volumes: bool=False, remove_orphans: bool=True) -> DockerOperationResult` — Tear down a docker-compose stack.
- `async def docker_prune(self, containers: bool=True, images: bool=False, volumes: bool=False) -> PruneResult` — Clean up unused Docker resources.
- `async def docker_test(self, container: str, port: Optional[int]=None, endpoint: Optional[str]=None) -> DockerOperationResult` — Health-check a running container.
