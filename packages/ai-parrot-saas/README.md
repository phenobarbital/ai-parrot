# ai-parrot-saas

Multi-tenant SaaS control plane and agentic business flows for AI-Parrot.

This distribution is the **acyclic leaf** of the workspace. It is the only
package permitted to depend on `ai-parrot` (flows/agents), `ai-parrot-server`
(HTTP layer, `JobManager`), `ai-parrot-tools` (`PulumiExecutor`) and `navrules`
at the same time. Nothing in the workspace depends on it.

## Why a distinct top-level module

The module is `parrot_saas`, **not** `parrot.saas`. Three distributions already
merge into the `parrot.*` namespace through `pkgutil.extend_path`
(`packages/ai-parrot/src/parrot/__init__.py`), and the repository's root
`conftest.py` documents the import-shadowing that causes. This package follows
the `parrot_tools` / `parrot_formdesigner` / `parrot_pipelines` convention.

## Layout

| Path | Contents |
|---|---|
| `tenancy/` | `TenantContext`, tenant models, repository, runtime cache, resolution middleware |
| `reviews/` | `ReviewSource` port plus the mock and generic-webhook adapters |
| `coupons/` | Coupon domain: models, repository, issuer, delivery |
| `rules/` | navrules integration — Postgres rule storage, ruleset builder, eval context |
| `flows/community_manager/` | The Community Manager `AgentsFlow` (definition, nodes, factories, runner) |
| `provisioning/` | `TenantDeployer` port, shared and Pulumi deployers, Pulumi programs |
| `handlers/` | aiohttp `BaseView` handlers and the `setup_saas_api` entry point |
| `migrations/` | Numbered `.sql` files owning the `saas` schema |

## Design rules this package must keep

1. **Tenant is always explicit.** Every repository method takes `tenant_id` as
   its first positional argument, with no default. There is no ContextVar: the
   flow runs from background workers and shutdown hooks where an ambient value
   would silently read `None`, and a `None` tenant is a data leak rather than a
   crash.
2. **Flow predicates are CEL strings, never Python callables.** A single
   callable predicate makes `AgentsFlow.to_definition()` raise
   `FlowNotExportableError`, which disables checkpointing for the whole flow —
   and with `checkpoint=True` it fails *before any node runs*. The CEL
   constants live in `flows/community_manager/definition.py` and are imported
   by `flow.py` so the declarative and executable graphs cannot drift.
3. **Custom flow nodes must declare an `fsm` field.** The base `Node` does not
   have one, but the scheduler calls `node.fsm.schedule()` unconditionally for
   every node.
4. **Coupon rulesets use `Policy.FIRST_MATCH`.** It is the only navrules policy
   that returns the matching rule's `result` payload, and the only one the
   native backend supports on the sync path.
5. **`PostgresRuleStorage` stays here, not in navrules.** navrules is
   deliberately zero-dependency; adding `asyncdb` upstream would couple a pure,
   Rust-accelerated rules library to a database for every future consumer. It
   moves to a `navrules[postgres]` extra only when a second consumer appears.

## Testing

```bash
source .venv/bin/activate
pytest packages/ai-parrot-saas/tests -v
```

Most of the suite runs with no external services: navrules is pure Python, the
flow is exercised with stub agents and the in-memory review source, and the
repositories have in-memory implementations. Tests needing a real database are
marked `integration` and skipped unless `SAAS_PG_DSN` points at one; the Pulumi
end-to-end test is marked `live` and requires `SAAS_PULUMI_E2E=1` plus a
reachable Docker daemon.
