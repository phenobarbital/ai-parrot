---
type: feature
base_branch: dev
---

# Brainstorm: Cloud `TenantDeployer` adapters (AWS / GCP)

**Date**: 2026-08-09
**Author**: Jesus Lara (investigation by Claude)
**Status**: exploration
**Recommended Option**: Option B
**Depends on**: `pulumi-executor-gaps.brainstorm.md`

---

## Problem Statement

The SaaS plane offers two hosting modes. `shared` runs a tenant inside the
common process, isolated by a `tenant_id` column plus repository-level
enforcement. `dedicated` gives a tenant their own stack — their own database,
their own worker — and that is the isolation an enterprise customer is actually
paying for.

The Community Manager phase built `dedicated` against the **local Docker
provider**: real, runnable and verifiable with no cloud account. Shipping it to
paying customers means AWS or GCP.

## What already exists

- `TenantDeployer` port: `plan` / `apply` / `destroy` / `status`, each returning
  a `DeploymentResult`.
- `SharedDeployer` — no infrastructure; seeds SQL, warms the tenant runtime.
- `PulumiDeployer` — wraps `PulumiExecutor`, one stack per tenant
  (`tenant-<slug>`), with three documented workarounds (see the Pulumi
  brainstorm): `use_docker=False`, an explicitly exported `PULUMI_BACKEND_URL`,
  and a hand-written `Pulumi.<stack>.yaml` because `config_values` is dropped.
- The Docker program provisions a per-tenant network, a Postgres container with
  a generated password, a Redis container, and a worker container, exporting
  the DSN as a **secret** output that goes to the `SecretStore` — never into the
  `deployments.outputs` JSON.
- `saas.deployments` tracks `status ∈ pending|planning|applying|ready|failed|
  destroying|destroyed`, outputs, and `last_error`.

**The seam is deliberately just the program directory.** Adding a cloud is a
sibling `programs/<cloud>/` plus a `program_dir` selector; no interface changes.

## What a cloud adapter has to answer that Docker did not

Docker made several hard questions disappear. They come back:

| Concern | Docker | Cloud |
|---|---|---|
| State backend | Local file + passphrase | Needs S3/GCS with locking, or Pulumi Cloud |
| Credentials | None | Per-environment cloud credentials, and a decision about whose account |
| Cost | Free | Per-tenant spend needs attribution and a ceiling |
| Teardown | Instant | Snapshot/retention policy before destroy |
| Networking | One bridge network | VPC/subnet/security-group design |
| Secrets | `SecretStore` | Could be Secrets Manager instead — the `SecretStore` port already anticipates this |
| Observability | `docker logs` | Per-tenant log/metric routing |

Two of these deserve emphasis:

**State backend locking.** A local file backend has no locking. Two concurrent
provisioning jobs for the same tenant would corrupt state. The Docker path is
protected only by the fact that provisioning runs as a single job per tenant;
a cloud deployment must use a locking backend, or the deployer must take a
Postgres advisory lock per tenant before invoking Pulumi.

**Cost attribution.** A dedicated stack has a floor price (managed Postgres
alone). Without a per-tenant cost readout and a ceiling, `dedicated` is a plan
that can lose money silently on a small customer.

---

## Constraints & Requirements

- No interface change: `TenantDeployer` must stay as-is, or the abstraction
  failed.
- Provisioning must be idempotent and resumable — it runs as a background job
  and a worker can die mid-apply.
- A failed provision must leave the tenant in `failed` with a readable
  `last_error`, never half-live and marked `ready`.
- Destroy must be reversible-by-policy: snapshot first, then destroy.

---

## Options Explored

### Option A: Managed services per tenant (RDS + ECS/Fargate, or Cloud SQL + Cloud Run)

One database instance and one service per tenant.

✅ **Pros:** strongest isolation; the clearest enterprise story; simplest mental
model.

❌ **Cons:** highest floor cost per tenant; slow provisioning (an RDS instance
is minutes, not seconds); quota limits become a real ceiling on tenant count.

📊 **Effort:** Medium.

### Option B: Shared managed database, dedicated compute — RECOMMENDED first step

A database *per tenant* on a shared managed instance (separate database, own
role and credentials), plus a dedicated worker service.

✅ **Pros:** most of the isolation benefit at a fraction of the cost; fast
provisioning; the credential boundary is still real (each tenant's DSN is
distinct and stored in the `SecretStore`).

❌ **Cons:** noisy-neighbour risk at the storage layer; "dedicated" needs honest
description in the contract — it is dedicated compute and a dedicated database,
not dedicated hardware.

📊 **Effort:** Medium.

### Option C: Kubernetes namespace per tenant

✅ **Pros:** dense, cheap per tenant; good quota primitives.
❌ **Cons:** requires a cluster the project does not have today; no Kubernetes
deployment story exists in the repo (`parrot_tools` has a Kubernetes toolkit,
but that is for operating clusters, not for hosting this).
📊 **Effort:** High.

---

## Open Questions

- [ ] Whose cloud account — the platform's, or the customer's (BYOC)? BYOC
      changes credential handling completely and is a plausible enterprise ask
      given the product already does BYOK for model keys.
- [ ] Pulumi state: S3/GCS with locking, or Pulumi Cloud? The dead
      `state_backend` field should be fixed either way.
- [ ] Does `dedicated` also imply a dedicated Redis, or is a namespaced shared
      Redis acceptable? Checkpoints are ephemeral; the answer may differ from
      the database answer.
- [ ] Snapshot retention on destroy — and who pays for it.
- [ ] Should `SecretStore` gain a Secrets Manager adapter as part of this, given
      the port was designed for exactly that?

## Recommendation

Option B, and treat the Pulumi executor fixes as a prerequisite rather than a
parallel task — the config-passing workaround in particular does not scale to a
cloud program with a dozen configuration values, several of them secret.
