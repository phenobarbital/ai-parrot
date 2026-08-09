---
type: feature
base_branch: dev
---

# Brainstorm: Close three gaps in `PulumiExecutor`

**Date**: 2026-08-09
**Author**: Jesus Lara (investigation by Claude)
**Status**: exploration
**Recommended Option**: Option B
**Scope**: `packages/ai-parrot-tools/src/parrot_tools/pulumi/`

---

## Problem Statement

`PulumiToolkit` / `PulumiExecutor` are the repository's infrastructure-as-code
executor and the natural engine for per-tenant stack provisioning in the SaaS
plane. Building the tenant deployer on them surfaced three defects. Each is
worked around in `parrot_saas/provisioning/pulumi_deployer.py`, but the
workarounds belong upstream: any future consumer will hit the same three.

## The three gaps (verified, with line references)

### 1. `config_values` is silently discarded

`executor.py`:
- `up(...)` accepts `config_values` — docstring line 469: *"Configuration values
  to set (not yet implemented)."*
- `preview(...)` accepts it — docstring line 512: same text.
- `_build_cli_args` never consumes it.

`toolkit.py` passes `config_values=config` at lines 124 and 184, so the toolkit's
own callers already believe this works. A Pulumi program that reads
`pulumi.Config()` gets nothing, and the failure surfaces as a program-level
"missing required configuration" rather than as a dropped argument.

**Workaround in use:** the SaaS deployer writes a `Pulumi.<stack>.yaml` file
into the program directory before invoking `up`.

**Proper fix:** a `_set_config(stack, values)` step issuing
`pulumi config set --stack <stack> <key> <value>` (with `--secret` for secret
values) before the operation, or `--config` flags where the CLI supports them.

### 2. `PulumiConfig.state_backend` is a dead field

Declared with a docstring promising `'local'` or `'file://<path>'`, but a grep
shows it referenced **only** in its own `Field(...)` declaration and that
docstring. There is no `pulumi login`, and `PULUMI_BACKEND_URL` is never set.
In practice the CLI falls back to whatever the ambient environment says —
which, on a fresh machine, is an interactive prompt to log in to Pulumi Cloud.

**Workaround in use:** the SaaS deployer exports `PULUMI_BACKEND_URL` itself,
which works because `_build_process_env` starts from `os.environ.copy()`.

**Proper fix:** honour the field — either run `pulumi login <backend>` once, or
translate it to `PULUMI_BACKEND_URL` in `_build_process_env`. Failing loudly
when unset would also be an improvement over an interactive prompt.

### 3. Docker mode cannot drive the Docker provider

`_build_docker_command` (`security/base_executor.py`, ~L158-195) mounts the
project directory and `pulumi_home` and nothing else. It never mounts
`/var/run/docker.sock` and never passes `--network`. So with `use_docker=True`,
a Pulumi program using `pulumi_docker` runs *inside* a container with no route
to the daemon it is meant to drive.

This is not exotic: Docker is the provider a local, credential-free tenant
stack would naturally use, and it is the one the SaaS plane picked precisely
because it is verifiable without a cloud account.

**Workaround in use:** `use_docker=False` — the deployer runs the host CLI.

**Proper fix:** an `extra_docker_args` / `extra_mounts` hook on the executor
config (the base class already documents an insertion point for "additional
`-v` mounts, `--network`, `-u`"), so a consumer can opt into the socket mount
without the executor hardcoding a privileged default.

### A fourth, smaller note

`expected_exit_codes = [0, 1]` means a `preview` reporting changes (exit 1) is
not an error. That is correct but easy to misread; worth a docstring line,
since a consumer treating exit 1 as failure would break plan/apply.

---

## Constraints & Requirements

- Backwards compatible: existing `PulumiToolkit` callers must not change.
- Mounting the Docker socket grants effective host root, so it must be opt-in
  and documented as such — never a default.
- Fixes should be testable without a cloud account.

---

## Options Explored

### Option A: Leave the workarounds in `parrot_saas`

✅ **Pros:** zero risk to other consumers.
❌ **Cons:** the next consumer rediscovers all three; `config_values` keeps
looking supported while doing nothing, which is worse than not existing.
📊 **Effort:** None (status quo).

### Option B: Fix all three upstream, remove the workarounds — RECOMMENDED

Implement `_set_config`, honour `state_backend`, add `extra_docker_args`.

✅ **Pros:** the API stops lying; the SaaS deployer simplifies; every future
consumer benefits.
❌ **Cons:** touches a package the SaaS work otherwise only consumes; needs its
own tests.
📊 **Effort:** Low-Medium.

### Option C: Replace the CLI executor with the Pulumi Automation API

`pulumi.automation` drives stacks in-process, with config as a first-class API.

✅ **Pros:** removes the whole class of CLI-marshalling bugs.
❌ **Cons:** a new heavyweight dependency and a rewrite of a working executor;
loses the container-isolation option entirely.
📊 **Effort:** High.

---

## Open Questions

- [ ] Should `config_values` support secrets (`--secret`) in the first pass?
      The tenant DSN is a secret and currently side-steps this by going to the
      `SecretStore` instead.
- [ ] Does `state_backend` deserve validation (reject an unrecognised value)
      rather than silent pass-through?
- [ ] Is `extra_docker_args` general enough, or should there be an explicit
      `mount_docker_socket: bool` that is harder to misuse?

## Recommendation

Option B. All three are small, and the `config_values` one is actively
misleading: a parameter accepted and ignored is a worse failure mode than one
that does not exist, because it silently moves the error to the program.
