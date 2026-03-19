# Brainstorm: Pulumi Toolkit for Container Deployment

**Date**: 2026-02-28
**Author**: claude-session
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

AI agents need the ability to deploy and manage containerized applications as part of their workflows. Currently, there's no infrastructure-as-code (IaC) toolkit in AI-Parrot that allows agents to:

1. **Plan deployments** before executing them (preview changes)
2. **Apply infrastructure changes** declaratively
3. **Destroy resources** when no longer needed
4. **Check status** of deployed infrastructure

The primary use case is **rapid prototyping of image deployments** — allowing agents to spin up containers (e.g., databases, services, test environments) on-demand using Docker/Docker Compose as the initial provider.

**Who is affected:**
- Developers using AI agents for prototyping
- DevOps teams automating infrastructure through conversational AI
- Platform engineers building self-service deployment workflows

## Constraints & Requirements

- Must inherit from `AbstractToolkit` to integrate with existing tool system
- Must support async operations (AI-Parrot is async-first)
- Operations: `plan`, `apply`, `destroy`, `status` as exposed tools
- Start with **Docker/Docker Compose provider** for simplicity
- Must include CLI installation command: `parrot install pulumi`
- Should not require complex cloud credentials for initial Docker use case
- Should provide preview/dry-run capability before destructive operations
- Must handle state management (Pulumi state backend)

---

## Options Explored

### Option A: Pure Pulumi Automation API (Python SDK)

Use Pulumi's [Automation API](https://www.pulumi.com/docs/using-pulumi/automation-api/) which provides a programmatic interface to Pulumi operations without requiring the CLI.

The Automation API allows embedding Pulumi programs directly in Python code, managing stacks programmatically, and executing operations like `preview`, `up`, `destroy`, and `refresh`.

```
PulumiToolkit
├── async pulumi_plan(stack_name, program_code)
├── async pulumi_apply(stack_name, program_code)
├── async pulumi_destroy(stack_name)
└── async pulumi_status(stack_name)
```

✅ **Pros:**
- Native Python integration — no subprocess calls needed
- Full programmatic control over stack lifecycle
- Can inline Pulumi programs as Python functions
- Type-safe with Pydantic models for inputs/outputs
- Better error handling and structured outputs

❌ **Cons:**
- Requires users to write Pulumi programs in Python (steeper learning curve)
- Automation API has different behavior than CLI in some edge cases
- State management still requires backend configuration (local/cloud)
- Requires `pulumi` binary installed for some operations anyway

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pulumi>=3.0` | Core Pulumi Python SDK | Well-maintained, Pulumi official |
| `pulumi_docker>=4.0` | Docker provider for Pulumi | Creates containers, images, networks |
| `pulumi_command` | Run arbitrary commands | For compose-style orchestration |

🔗 **Existing Code to Reuse:**
- `parrot/tools/toolkit.py` — AbstractToolkit base class
- `parrot/tools/aws/ecs.py` — Pattern for async infrastructure methods
- `parrot/install/cli.py` — CLI installation pattern

---

### Option B: CLI-Based Executor Pattern

Follow the established `BaseExecutor` pattern used by Checkov, Prowler, and Trivy. Wrap the Pulumi CLI as an executor with structured input/output parsing.

This approach treats Pulumi as an external CLI tool, similar to how security scanners are integrated. The toolkit invokes `pulumi preview`, `pulumi up`, `pulumi destroy` via subprocess.

```
PulumiExecutor(BaseExecutor)
├── _build_cli_args() → pulumi preview/up/destroy
├── async preview(project_dir)
├── async up(project_dir)
└── async destroy(project_dir)

PulumiToolkit(AbstractToolkit)
├── async pulumi_plan(project_path, stack_name)
├── async pulumi_apply(project_path, stack_name)
├── async pulumi_destroy(project_path, stack_name)
└── async pulumi_status(project_path, stack_name)
```

✅ **Pros:**
- Consistent with existing security toolkit patterns (Checkov, Prowler)
- Works with any Pulumi program (YAML, Python, TypeScript, Go)
- Easier to debug — CLI output is familiar to users
- Docker execution mode available as fallback
- Reuses battle-tested `BaseExecutor` infrastructure

❌ **Cons:**
- Subprocess overhead for each operation
- Output parsing required (JSON output from `--json` flag)
- Less programmatic control than Automation API
- Requires Pulumi CLI installed (or Docker image)

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pulumi` (CLI) | Pulumi command-line interface | Installed via `curl` or package manager |
| `pulumi_docker` | Docker provider (pip install) | Only needed for Python programs |

🔗 **Existing Code to Reuse:**
- `parrot/tools/security/base_executor.py` — BaseExecutor pattern
- `parrot/tools/security/checkov/executor.py` — CLI argument building
- `parrot/tools/toolkit.py` — AbstractToolkit base class
- `parrot/install/cli.py` — `@install.command()` pattern

---

### Option C: Hybrid Approach (Automation API + CLI Fallback)

Combine the Automation API for programmatic operations with CLI execution for complex scenarios. Use Automation API when running inline Python programs, fall back to CLI for existing project directories.

```
PulumiToolkit(AbstractToolkit)
├── executor: PulumiExecutor  # For CLI operations
├── async pulumi_plan_inline(program: Callable)  # Automation API
├── async pulumi_plan_project(project_path)      # CLI
├── async pulumi_apply_inline(program: Callable)
├── async pulumi_apply_project(project_path)
└── ...
```

✅ **Pros:**
- Best of both worlds — flexibility for different use cases
- Can run both inline programs and existing projects
- Automation API for AI-generated programs, CLI for user projects

❌ **Cons:**
- Higher complexity — two code paths to maintain
- Inconsistent behavior between modes
- Larger dependency footprint
- More testing surface area

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pulumi>=3.0` | Core SDK + Automation API | For inline programs |
| `pulumi_docker>=4.0` | Docker provider | For container operations |
| `pulumi` (CLI) | Command-line interface | For project-based operations |

🔗 **Existing Code to Reuse:**
- All from Options A and B combined

---

### Option D: Docker Compose CLI Direct Integration

Skip Pulumi entirely for the Docker use case. Wrap `docker compose` CLI directly since the initial requirement is Docker Compose provider.

```
DockerComposeToolkit(AbstractToolkit)
├── async compose_up(compose_file, services)
├── async compose_down(compose_file)
├── async compose_ps(compose_file)
├── async compose_logs(compose_file, service)
└── async compose_build(compose_file, services)
```

✅ **Pros:**
- Simplest implementation — no Pulumi dependency
- Docker Compose is ubiquitous and well-understood
- No state management complexity
- Minimal installation requirements

❌ **Cons:**
- Limited to Docker Compose only — no path to cloud providers
- No preview/plan capability (compose doesn't have dry-run)
- Doesn't address the broader IaC need
- Would need separate toolkit for Kubernetes, AWS, etc.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `docker` (CLI) | Docker Compose CLI | Already installed on most systems |

🔗 **Existing Code to Reuse:**
- `parrot/tools/toolkit.py` — AbstractToolkit base class
- `parrot/tools/security/base_executor.py` — CLI execution pattern

---

## Recommendation

**Option B (CLI-Based Executor Pattern)** is recommended because:

1. **Consistency**: Follows the established pattern used by security toolkits (Checkov, Prowler, Trivy). Developers already familiar with the codebase will understand the architecture immediately.

2. **Language Agnostic**: Works with Pulumi programs in any language (Python, TypeScript, YAML, Go), not just Python. This is important because Docker Compose YAML is the most accessible format for rapid prototyping.

3. **Debugging**: CLI output is easier to debug than Automation API errors. Users can replicate commands manually.

4. **Extensibility**: The same pattern will work when adding Kubernetes, AWS, or other providers later.

5. **Installation Simplicity**: `parrot install pulumi` can use the official installer script, and Python packages are only needed if writing Python programs.

**Tradeoff accepted**: We trade programmatic elegance (Option A) for operational simplicity and pattern consistency. The subprocess overhead is acceptable for infrastructure operations that typically take seconds to minutes anyway.

---

## Feature Description

### User-Facing Behavior

**CLI Installation:**
```bash
parrot install pulumi
# Installs Pulumi CLI via official installer
# Optionally installs pulumi_docker Python package
```

**Toolkit Operations (exposed as agent tools):**

1. **`pulumi_plan`**: Preview infrastructure changes without applying
   - Input: project path, stack name, optional config values
   - Output: Structured diff of resources to create/update/delete

2. **`pulumi_apply`**: Apply infrastructure changes
   - Input: project path, stack name, auto-approve flag
   - Output: Applied resources, outputs, timing

3. **`pulumi_destroy`**: Tear down infrastructure
   - Input: project path, stack name, auto-approve flag
   - Output: Destroyed resources confirmation

4. **`pulumi_status`**: Check current stack state
   - Input: project path, stack name
   - Output: Current resources, their states, outputs

**Example Agent Interaction:**
```
User: "Deploy a Redis container for testing"
Agent: I'll create a Docker container using Pulumi.
       [Uses pulumi_plan to preview]
       This will create:
       + docker:index:Container redis-test

       [Uses pulumi_apply after user confirms]
       Deployed! Redis available at localhost:6379
```

### Internal Behavior

```
┌─────────────────────────────────────────────────────────────┐
│                      PulumiToolkit                          │
│  (AbstractToolkit subclass)                                 │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ pulumi_plan │  │pulumi_apply │  │pulumi_destroy│         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          ▼                                  │
│              ┌───────────────────────┐                      │
│              │    PulumiExecutor     │                      │
│              │   (BaseExecutor)      │                      │
│              ├───────────────────────┤                      │
│              │ _build_cli_args()     │                      │
│              │ _parse_json_output()  │                      │
│              │ run_command()         │                      │
│              └───────────┬───────────┘                      │
│                          │                                  │
│                          ▼                                  │
│              ┌───────────────────────┐                      │
│              │   asyncio.subprocess  │                      │
│              │   pulumi preview/up   │                      │
│              └───────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

**Flow for `pulumi_apply`:**
1. Toolkit receives `pulumi_apply(project_path, stack_name, config)`
2. Validates project directory exists and contains Pulumi.yaml
3. Calls `PulumiExecutor.up(project_path, stack_name, json=True)`
4. Executor builds CLI args: `pulumi up --stack <name> --yes --json`
5. Runs subprocess with timeout, captures stdout/stderr
6. Parses JSON output into structured `ToolResult`
7. Returns success/error with resource details

### Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| Pulumi CLI not installed | Return clear error with install instructions |
| Project directory missing | Validate path before execution, return actionable error |
| Stack doesn't exist | Auto-create stack on first apply (configurable) |
| Apply fails mid-way | Return partial success with failed resource details |
| Timeout during operation | Kill subprocess, return timeout error with stack state |
| Concurrent operations on same stack | Pulumi handles via lock files; surface lock errors |
| Missing Docker daemon | Detect and return specific "Docker not running" error |
| Invalid Pulumi program | Parse and return Pulumi's validation errors |

---

## Capabilities

### New Capabilities
- `pulumi-toolkit`: Core toolkit with plan/apply/destroy/status operations
- `pulumi-install-cli`: CLI command to install Pulumi and providers
- `pulumi-docker-provider`: Docker/Docker Compose deployment support

### Modified Capabilities
- `parrot-install-cli`: Add `pulumi` subcommand to existing install group

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/` | extends | New `pulumi/` subdirectory with toolkit |
| `parrot/install/cli.py` | modifies | Add `@install.command() pulumi` |
| `parrot/tools/registry.py` | extends | Register PulumiToolkit |
| Agent tool discovery | extends | New infrastructure tools available |
| `pyproject.toml` | modifies | Optional `pulumi` extras group |

---

## Open Questions

- [ ] **State backend**: Should we default to local file state or offer Pulumi Cloud? — *Owner: architect*
- [ ] **Multi-stack support**: How to handle projects with multiple stacks (dev/staging/prod)? — *Owner: architect*
- [ ] **Secrets handling**: How to pass secrets to Pulumi programs securely? — *Owner: security*
- [ ] **YAML vs Python programs**: Should we provide a simplified YAML DSL for common patterns? — *Owner: DX team*
- [ ] **Resource quotas**: Should we limit what resources agents can create (e.g., no expensive cloud resources)? — *Owner: platform*
