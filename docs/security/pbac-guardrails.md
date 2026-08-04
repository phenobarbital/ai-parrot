# PBAC Guardrails — Policy-Driven Tool-Call Denial (FEAT-406)

This document explains the three PBAC enforcement layers ai-parrot ships,
how `PBACToolCallGuardrail` fits into the guard chain, the sample policy
YAML shipped with this feature, and known limitations of the currently
pinned `navigator-auth` version.

## The three enforcement layers

| Layer | Component | When it runs | What the user sees |
|---|---|---|---|
| **Layer 1 — Filtering** | `Guardian.filter_resources()` (FEAT-077) | Agent startup / tool-list resolution | Unauthorized tools are **invisible** — the LLM never sees them |
| **Layer 2 — Resolver** | `PBACPermissionResolver` (FEAT-101, `auth/resolver.py`) | Inside `AbstractTool.execute()`, just before dispatch | Silent deny + audit log warning; covers invocation paths that bypass `ToolManager` |
| **Layer 3 — Guardrail** | `PBACToolCallGuardrail` (FEAT-406, this feature) | `ToolManager.execute_tool()`, pre-execution, before `GrantGuard`/`ConfirmationGuard` | **Explainable** `ToolResult(status="forbidden", error=<operator message>)` — the tool remains visible and the LLM verbalizes *why* it was refused |

All three layers share the **same** `PolicyEvaluator` instance (wired by
`setup_pbac()`), so decisions are always consistent — Layer 3 does not
replace Layers 1/2, it adds a defense-in-depth, explainable denial point.
The 30s decision cache on the shared evaluator makes double/triple
evaluation across layers negligible.

## Guard-chain order

```
LLM emits tool_call
  └─ ToolManager.execute_tool(tool_name, params, permission_context)
       ├─ 1. TOOL_CALL GuardrailPipeline.run()          ← PBACToolCallGuardrail
       │     ├─ ALLOW → continue
       │     └─ DENY  → ToolResult(status="forbidden", error=<message>) → LLM
       ├─ 2. GrantGuard (FEAT-211, unchanged)
       ├─ 3. ConfirmationGuard (FEAT-235, unchanged)
       └─ 4. tool.execute()
             └─ PBACPermissionResolver (Layer 2, unchanged, defense-in-depth)
```

TOOL_CALL runs **first** — a policy-doomed call should never interrupt a
human for confirmation, or consume a bounded grant, on a call the policy
will deny anyway.

## Fail modes

`PBACToolCallGuardrail.on_error = "fail_closed"` (class default — a
security control): if the policy evaluator itself errors while evaluating
a tool call, the call is **blocked** with
`reason="policy_engine_unavailable"` — and the sanitized
`"Policy engine is temporarily unavailable."` message, never the raw
internal exception text.

A specific policy can opt into **fail-open** for its own resource via an
`enforcement: fail_open` extra key — when the evaluator errors while
evaluating a tool covered by that policy, the call passes through instead
of being blocked. Default is `fail_closed` when no covering policy sets
`enforcement`.

> **Two failure shapes, one contract** (code-review finding): navigator-auth's
> `PolicyEvaluator.check_access()` catches its own Rust-engine exceptions
> **internally** and returns a normal DENY `EvaluationResult` (`allowed=False,
> matched_policy=None, reason="Evaluation engine error: <detail>"`) instead of
> raising — it does not propagate the exception to the guardrail. `check()`
> detects this specific shape (`matched_policy is None` + a
> `"Evaluation engine error"`-prefixed reason) and routes it through the exact
> same `_policy_enforcement()`/fail-mode logic as a genuinely raised exception
> (e.g. a bug in our own `to_eval_context()`/`Environment()`/enrichment code),
> rather than surfacing `result.reason` verbatim as a normal DENY — which would
> both leak internal engine detail to the LLM (violating the "never leak rule
> internals" denial-hygiene constraint, spec §7) and make the
> `enforcement: fail_open` escape hatch permanently unreachable for the
> scenario it exists to cover.
>
> **Known limitation**: `_policy_enforcement()`'s fail-open lookup matches by
> `covers_resource()` only — it does not check the covering policy's
> `subjects`/`conditions` against the calling user's `EvalContext`. Two
> overlapping policies for the same resource with different subjects (one
> fail-closed, one fail-open) will downgrade fail-open for every caller
> matching the resource, not only the subject the fail-open policy targets.
> Acceptable for a best-effort fail-mode escape hatch; be aware of it if you
> layer multiple `enforcement`-tagged policies for the same resource with
> different subjects.

> **Known limitation (navigator-auth version gap)**: the currently pinned
> `navigator_auth.abac.policies.evaluator.PolicyLoader.load_from_dict()`
> only forwards a fixed, explicit set of keys from a policy YAML entry
> into `ResourcePolicy` (`name`, `description`, `effect`, `resources`,
> `actions`, `subjects`, `conditions`, `environment`, `priority`,
> `enforcing`) — it does **not** forward arbitrary extra top-level keys
> (like `enforcement:`) into `ResourcePolicy.attributes`. This means an
> `enforcement: fail_open` key written in a YAML file loaded via the
> standard `load_from_file`/`load_from_directory` path is currently
> **silently ignored** (the policy still loads and evaluates fine — the
> fail-mode override just doesn't take effect from YAML yet). The two
> sample YAML files below still document the intended syntax
> (forward-compatible once/if a future `navigator-auth` release adds
> passthrough for extra policy keys), but to actually exercise
> `enforcement: fail_open` today you must construct a `ResourcePolicy`
> directly in Python with `enforcement="fail_open"` as an extra keyword
> argument (`AbstractPolicy.__init__`'s `**kwargs` → `self.attributes`) —
> exactly what `PBACToolCallGuardrail`'s own end-to-end test does.

## Sample policies

`policies/tool-business-hours.yaml` and `policies/tool-business-hours-soft.yaml`
demonstrate a business-hours DENY rule at the TOOL_CALL guardrail layer.
Both are scoped to a **demo-only** resource pattern
(`tool:demo_business_hours_only` / `tool:demo_business_hours_only_soft`)
rather than a wildcard (`tool:*`) — every `*.yaml` file in `policies/` is
loaded automatically at startup (see `policies/README.md`), so a wildcard
DENY here would become a live production policy gating **every** real
tool for **every** user outside business hours. Broaden the `resources:`
pattern deliberately, with review, if you want this enforced repo-wide.

```yaml
# policies/tool-business-hours.yaml
policies:
  - name: demo_business_hours_tool_deny
    effect: deny
    resources:
      - "tool:demo_business_hours_only"
    actions:
      - "tool:execute"
    subjects:
      groups:
        - "*"
    conditions:
      environment:
        is_business_hours: false
    enforcement: fail_closed   # see the limitation note above
    priority: 5
```

## Server-clock limitation

`Environment.is_business_hours` (and the related `hour`/`dow`/`day_segment`
fields) are computed from the **server's local clock**, using
navigator-auth's global `BUSINESS_HOURS_START`/`BUSINESS_HOURS_END`/
`BUSINESS_DAYS` config — there is no per-policy timezone support in v1.
Deployments spanning multiple timezones will evaluate business-hours
conditions against the server's own local time, not the requesting user's
timezone. `Environment` does accept an explicit `timestamp`/`hour`/`minute`
at construction, so a future version could inject a tz-adjusted time
without any navigator-auth change — out of scope for this feature.

## PBAC attribute enrichment

`PBACToolCallGuardrail` accepts an optional `userinfo_service` (a
`parrot.auth.userinfo.UserInfoService`) at construction. When provided,
`check()` fetches the session user's curated `EmployeeProfile` and merges
`job_code`, `department_code`, `groups`, and `programs` onto the
`EvalContext.userinfo` dict before evaluation.

> **Known limitation**: `PolicyEvaluator._build_user_context()` (the
> function that projects `EvalContext.userinfo` into the Rust evaluation
> engine) only forwards `username`, `groups`, and `roles` — it does not
> currently read `job_code`, `department_code`, or `programs`. Enrichment
> of `groups` therefore has a real effect on policy evaluation (subject
> group matching); the other enriched fields are available on the
> `EvalContext` for forward-compatibility with future policies/navigator-
> auth versions, but do not currently change any ALLOW/DENY outcome.

A profile-fetch failure during enrichment is logged as a warning and never
blocks the tool call — evaluation proceeds with session-only attributes.

## `UserInfo`/`UserProfileKB` coexistence

The existing knowledge bases in `parrot/stores/kb/user.py` (`UserInfo`,
`UserProfileKB`) flatten `auth.vw_users` into prose facts for the system
prompt's `<userdata>` block. `UserInfoService` (FEAT-406) is a separate,
structured source feeding PBAC evaluation and `UserinfoTool`'s JSON output.
Both coexist untouched — this feature does not migrate or remove the KBs.
