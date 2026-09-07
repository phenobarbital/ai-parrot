# Dedicated tenant stack — local Docker

A Pulumi program that gives one tenant its own Postgres, Redis and worker on a
local Docker daemon. Driven by
`parrot_saas.provisioning.pulumi_deployer.PulumiDeployer`; you should not need
to run it by hand except when debugging.

## Why it is not part of the workspace

`requirements.txt` here is deliberately separate from the uv workspace. The
program runs under Pulumi's own interpreter, and the Pulumi SDK has no business
in the dependency tree of an API deployment that will never provision anything.

## Running it by hand

```bash
cd packages/ai-parrot-saas/src/parrot_saas/provisioning/programs/docker
python -m venv venv && ./venv/bin/pip install -r requirements.txt

export PULUMI_BACKEND_URL="file://$(pwd)/../../../../../.pulumi-state"
export PULUMI_CONFIG_PASSPHRASE="parrot-saas-local"

pulumi stack init tenant-bar-pepe
pulumi config set tenantId bar-pepe
pulumi config set hostPort 18000
pulumi up
```

`pulumi stack output dsn --show-secrets` prints the connection string. In
normal operation the deployer never prints it: it moves it into the tenant
secret store under `deployment:<stack>:dsn` and records only that reference in
`saas.deployments.outputs`.

## Three things about the executor this works around

The toolkit's `PulumiExecutor` has gaps the deployer routes around rather than
patching upstream (see `sdd/proposals/pulumi-executor-gaps.brainstorm.md`):

- **`config_values` is accepted and discarded** by `preview()` and `up()` —
  their docstrings say "not yet implemented". The deployer writes
  `Pulumi.<stack>.yaml` itself before running.
- **`PulumiConfig.state_backend` is a dead field.** Nothing reads it. The
  deployer exports `PULUMI_BACKEND_URL` instead, which works because
  `_build_process_env` starts from `os.environ.copy()`.
- **Docker mode cannot drive the Docker provider.** `_build_docker_command`
  mounts the project directory and nothing else — never `/var/run/docker.sock`
  — so Pulumi-in-a-container has no daemon to talk to. The deployer forces
  `use_docker=False` and uses the host CLI.

## Outputs contract

`tenant_id`, `network`, `host_port`, `worker_container`, `postgres_container`,
`redis_container`, `redis_url`, and `dsn` (secret). A cloud sibling program
must export the same names — that contract is what makes `program_dir` the only
thing that changes between providers.
