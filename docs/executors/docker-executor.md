# Docker Tool Executor & Execution Policy

Run agent tools (and Agents-as-Tools) inside Docker containers instead of
in-process, and declare per-agent which tools/toolkits are dispatched
remotely and through which executor.

## Why

Tools like shell wrappers, `PythonREPLTool`, or third-party API toolkits run
arbitrary-ish code. Executing them in the agent's own process gives them the
agent's memory, credentials, and filesystem. The remote-executor framework
(`parrot.tools.executors`) already relocates `_execute` to another runtime
(k8s Job, Qworker); `DockerToolExecutor` adds container-level isolation on
any host with a Docker Engine — no cluster required.

## Quick start

```python
from parrot.bots.agent import Agent
from parrot.tools.pythonrepl import PythonREPLTool

agent = Agent(
    tools=[PythonREPLTool(), my_toolkit],
    execution_policy={
        "rules": {
            # exact tool name → sandboxed, fully offline container
            "python_repl": {"name": "docker",
                            "options": {"network_mode": "none"}},
            # toolkit class name → every tool it generates
            "MyToolkit": {"name": "docker",
                          "options": {"mode": "ephemeral"}},
            # wildcards match tool names; "*" is the catch-all
            "shell_*": "docker",
        }
    },
)
```

Or wire an executor explicitly (always wins over the policy):

```python
from parrot.tools.executors import DockerToolExecutor

tool = PythonREPLTool(executor=DockerToolExecutor(network_mode="none"))
```

Install the client dependency with `uv pip install ai-parrot[remote-tools]`
(brings `aiodocker` and `kubernetes_asyncio`).

## DockerToolExecutor

Same wire protocol as the k8s executor: the JSON
`ToolExecutionEnvelope` is uploaded into the container (via
`put_archive`, so it never appears in `docker inspect` or `ps`), the
container runs `python -m parrot.cli.tool_worker --envelope <path>`, and
the sentinel-delimited `ToolResult` JSON is parsed from its output.
Permission checks, arg validation, lifecycle events, and output
scrubbing all stay on the caller — only `_execute` is relocated.

### Lifecycle modes

| Mode | Behaviour | Trade-off |
|---|---|---|
| `warm` (default) | One long-lived container, each call is a `docker exec`; torn down after `idle_ttl_seconds` (default 300) of inactivity, or on `close()`. A timed-out call resets the container. | Best latency; calls share container state between reaps. |
| `ephemeral` | Create → run → force-remove per call. | Strongest isolation, pays container start latency every call. |

### Security defaults

Containers run with `CapDrop=ALL`, `no-new-privileges`, memory limit
`512m`, half a CPU (`nano_cpus=500_000_000`), `pids_limit=256`. The
network defaults to `bridge`; set `network_mode="none"` for tools that
must not reach the network. All are constructor `options` overridable
per policy rule.

### Configuration (navconfig / environment)

| Setting | Default | Meaning |
|---|---|---|
| `DOCKER_HOST` | *(auto)* | Engine endpoint (`unix:///...` or `tcp://...`). |
| `DOCKER_TOOL_IMAGE` | `parrot-tools:latest` | Worker image (same one the k8s executor uses; must ship `parrot.cli.tool_worker`). |
| `DOCKER_EXECUTOR_MODE` | `warm` | `warm` or `ephemeral`. |
| `DOCKER_IDLE_TTL_SECONDS` | `300` | Warm-container idle TTL. |
| `DOCKER_NETWORK_MODE` | `bridge` | Default network mode. |

## ExecutionPolicy

`ExecutionPolicy` maps rule keys to executor specs. Precedence:

1. exact tool name,
2. toolkit class name or `tool_prefix` (covers every generated tool),
3. `fnmatch` wildcard against the tool name (declaration order),
4. wildcard against the toolkit name,
5. the `"*"` catch-all.

A spec is `{"name": <registry key>, "options": {...}}` with optional
`remote_timeout_seconds` / `webhook_callback_url` overrides; a bare
string (`"docker"`) or a live executor instance also work. Registry
names: `local`, `docker`, `k8s`, `qworker` (`docker-sandbox` is
reserved for a future Docker Sandboxes / `sbx` microVM executor).

Each rule instantiates its executor **once** — every tool matching the
rule shares it (one warm container, not N). The policy is applied by
`ToolManager` at registration; a tool constructed with an explicit
`executor=` is never overridden. On bot `cleanup()` the policy closes
every executor it built (live instances you passed in stay yours to
close).

## Agents-as-Tools

An `AgentTool` wraps a live agent, which can't be serialized. When an
`AgentTool` is dispatched remotely, the envelope carries the agent's
**registry name** (`agent_ref`); the worker reconstructs the agent via
`parrot.registry.agent_registry.get_instance()` (running its async
`configure()`), rebuilds the `AgentTool`, and executes the question.

Requirements:

- the agent must be registered (e.g. `@register_agent`) under the same
  name in the worker image's environment;
- the container needs the sub-agent's LLM credentials — pass them via
  the executor's `env` option (e.g. `{"OPENAI_API_KEY": ...}`);
- `context_filter` / `execution_memory` are live-only and do not travel;
  cross-pollination state stays on the caller.

Unregistered agents fail fast with a `ValueError` at envelope-build time.

## Building the worker image

`docker/tool-worker/Dockerfile` builds the `parrot-tools:latest` image the
executors reference (shared by `DockerToolExecutor` and `K8sToolExecutor`):

```bash
# from the repository root
make docker-tool-worker
# or directly:
docker build -f docker/tool-worker/Dockerfile -t parrot-tools:latest .
```

The image ships `ai-parrot` + `ai-parrot-tools` and runs
`python -m parrot.cli.tool_worker` as an unprivileged user under tini.
Build args:

| Arg | Default | Purpose |
|---|---|---|
| `PARROT_EXTRAS` | `llms` | ai-parrot extras — the default bakes in the OpenAI/Google/Groq/Anthropic SDKs so Agents-as-Tools work; pass `""` for a lean tools-only image. |
| `TOOLS_EXTRAS` | *(empty)* | ai-parrot-tools per-tool extras, e.g. `pdf,jira,aws,analysis`. |
| `EXTRA_PIP_PACKAGES` | `qworker` | Extra PyPI packages baked in (the default lets the same image serve as a Qworker runtime). |
| `PYTHON_VERSION` | `3.11` | Base image Python. |

Private wheels (e.g. a proprietary `qclient` build) dropped into
`docker/tool-worker/wheels/` before building are installed automatically.

The image bakes **no secrets**: navconfig is scaffolded with an empty env
file so every setting (LLM API keys, `QWORKER_*`, DSNs) is read from
environment variables — supply them per-executor via the `env` option, or
at the k8s Job / compose level.

## Notes

- [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) (`sbx`
  microVMs) is the intended next isolation tier behind the same
  `AbstractToolExecutor` interface; it is CLI-only today and requires
  bare-metal KVM, so the registry merely reserves the name.
- Webhook (`pending`) delivery is not yet implemented for the Docker
  executor; the envelope field is carried through for parity later.
