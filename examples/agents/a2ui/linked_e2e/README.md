# Linked surfaces end to end (FEAT-611)

This directory holds an asserting end-to-end harness for **linked A2UI surfaces** (FEAT-598). It runs
alongside FEAT-610 as a parallel track. It uses three **dedicated E2E slugs** that `seed_staging.py` seeds:
the SQL slugs `epson_e2e_activity` (visits per `day`, `program`, `store_id`) and `epson_e2e_targets` (a static
per-program `target` table), plus the multiquery `epson_e2e_activity_vs_targets_mq` over both. The names are
the module constants `ACTIVITY_SLUG`, `TARGETS_SLUG` and `MQ_SLUG`.

It targets a **live environment — `staging` or `dev`** — with **querysource >= 5.1.2**. Every script refuses to
run unless `ENV` is `staging` or `dev`; production is always refused. Nothing here writes to production.

The dev DB holds data only from 2024-12-31 to 2025-03-23. With `ENV=dev` the runner therefore defaults to
`2025-03-01:2025-03-07` (range A, also used by S1/S3/S5) and `2025-03-11:2025-03-15` (range B).

Two rules apply to every tier:

- **The offline pytest tier is the deterministic verdict.** The live tiers (staging or dev) are live checks.
- **SKIP is not PASS.**

| Scenario | What it validates | Where |
|---|---|---|
| S1 | Server lane: publish, `GET` JSON and `?format=html` (no execution), refresh with params, the `X-Parrot-Refresh-Warnings` header, share token plus bearer refresh, 409 (baked surface, stale refresh), and 403 (deny policy / no guard) | `run_e2e.py` |
| S2 | Dashboard TOOL: join, `transform.ops`, FilterBar `param`, local FilterBar, validated at publish; a refresh with two date ranges changes `activity` rows and leaves `targets` unchanged; Python↔TS parity | `run_e2e.py`, golden/parity tests |
| S3 | Multiquery: `multi_output="targets"`, the `result` fallback returns a different frame, and a missing output returns 502 `data_stage` | `run_e2e.py` |
| S5 | Tenant route: `tenant="public"` through `/api/v1/public/queries/{slug}` and through `/refresh` | `run_e2e.py` |
| S4 | Manual and exploratory (never required): a real agent chat renders and refreshes the surface in the admin UI | [checklist](#6-manual-s4--admin-chat) |

## Requirements

| Requirement | Why / how |
|---|---|
| `querysource >= 5.1.2` | Pinned by TASK-3831. Check it with `python -c "import querysource; print(querysource.__version__)"`. |
| `ENV=staging` or `ENV=dev` in the shell | This is the navconfig **selector**. The scripts check `os.environ["ENV"]`, not `navconfig.ENV`, because `env/staging/.env` itself sets `ENV=production`. `seed_staging.py` also requires the resolved `DBNAME` to contain the selected env name (and never `prod`). |
| Run from the **main checkout root** | `env/` is gitignored, so worktrees have no `env/staging/.env` or `env/dev/.env`. |
| Network access to the target Postgres | Staging (and production) are unreachable from outside the network; the dev DB is reachable. `prove-policy` needs no DB, but everything else does, including server startup (QS `initialize_tenants`). |
| `navigator-auth` installed | Provides `/api/v1/login` (BasicAuth). PBAC also needs it: without it no data-plane guard is built, and linked saves answer 403 (docs §6). |
| E2E users | `E2E_USER` / `E2E_PASSWORD`. Optionally a second user, `E2E_SHARE_USER` / `E2E_SHARE_PASSWORD`, for the share-bearer refresh. |
| Node >= 24 and pnpm 9.15.9 | Needed only for the vitest legs. Use `nvm use 24` and `corepack enable` (the UI's `packageManager` field pins pnpm). Then run `pnpm install --frozen-lockfile` in `packages/ai-parrot-server/ui`. The UI uses pnpm only; there is no npm lockfile. |
| Demo policy dir | `policies/source-epson.yaml` allows `source:read` on the public `epson_*` slugs. `server.py --guard-mode policy` and `seed_staging.py prove-policy` use it. |

## Files

| File | What it is |
|---|---|
| `dashboard_tool.py` | `build_epson_activity_dashboard`: the S2 TOOL. It has 4 sources (`activity`, `targets`, `attainment`, `kpis`), KPIs, a bar chart, an attainment table, a date FilterBar (param-bound) and a Program FilterBar (local). |
| `agent.py` | `EpsonLinkedAgent` (`epson_linked`) with the `qs_*` tools, the dashboard TOOL and `publish_surface`. It binds a pctx from the authenticated `user_id` in `ask()`. |
| `server.py` | The example app. The mount order is QuerySource → `setup_dataplane_guard` → BotManager (+ agent) → AuthHandler(BasicAuth). |
| `run_e2e.py` | The asserting HTTP runner for S1/S2/S3/S5. |
| `seed_staging.py` | Live-target verification and the idempotent seed of the three E2E slugs. |
| `policies/source-epson.yaml` | The demo PBAC policy. |

## 1. Seed the live target (once)

Run these steps in order, from the main checkout root (`ENV=staging` works the same way):

```bash
ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py prove-policy                  # no DB
ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py describe                      # read-only
ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py seed-sql --confirm            # write: SQL slugs
ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py preview --firstdate 2025-03-01 --lastdate 2025-03-07
ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py seed --confirm                # write: SQL + MQ
ENV=dev python examples/agents/a2ui/linked_e2e/seed_staging.py describe                      # all three present
```

1. `prove-policy` builds real guards and expects **allow** with `policies/` and **deny** with a control dir.
2. `describe` runs `describe_slug` on all three slugs. It logs the program, placeholders and fields, and
   reports a slug that is not seeded yet as `{"missing": true}`.
3. `seed-sql --confirm` upserts `epson_e2e_activity` and `epson_e2e_targets` into
   `<QS_QUERIES_SCHEMA>.<QS_QUERIES_TABLE>` (default `public.queries`) with asyncpg and the navconfig DB
   credentials (`DBHOST`/`DBPORT`/`DBUSER`/`DBPWD`/`DBNAME`, `PGSSLMODE` → `ssl`). It uses
   `INSERT … ON CONFLICT (query_slug) DO UPDATE` and prints `inserted` or `updated` per slug. Both slugs use
   `program_slug='epson'`, `program_id=19`, provider `db`, parser `pgSQLParser` and `is_cached=false`.
4. `preview` validates `MQ_PIPELINE` and runs it inline. It fails unless the frames are exactly
   `{result, targets}`. Pass a range that holds data (the defaults `FDOM`/`TODAY` are empty on dev).
5. `seed --confirm` runs `seed-sql` first and then upserts `epson_e2e_activity_vs_targets_mq`.
   - Both writes ask for an interactive `yes` (`--yes` skips the prompt).
   - Both are idempotent, so run them a second time to show that.
6. Record the outcome in `sdd/state/FEAT-611/findings/F020-staging-slug-definitions.md`. That includes the
   slug definitions, the frame keys, and two date ranges with different data for S2.

The multiquery has no server-side Join, because a Join output can never be named `result`. The two frames
are `result` and `targets`, and the join lives in the descriptor's `transform.ops`.

## 2. Start the servers

```bash
ENV=dev python examples/agents/a2ui/linked_e2e/server.py --port 5000                      # policy (default)
ENV=dev python examples/agents/a2ui/linked_e2e/server.py --port 5001 --guard-mode deny    # S1 403: real guard, empty policy dir
ENV=dev python examples/agents/a2ui/linked_e2e/server.py --port 5002 --guard-mode none    # S1 403: no guard at all
```

Other flags are `--host` (default `127.0.0.1`) and `--llm` (an agent LLM string, such as
`google:gemini-2.5-flash`). `--llm` is needed only for `--via-agent` and for S4.

The agent is added with `add_bot` **before** startup, because the guard is injected only into bots that are
registered at startup. `none` mode sets `PARROT_PBAC_POLICY_DIR` before `parrot` is imported, so it needs a
fresh process.

## 3. Run the scenarios

```bash
ENV=dev E2E_USER=… E2E_PASSWORD=… \
  python examples/agents/a2ui/linked_e2e/run_e2e.py --base-url http://127.0.0.1:5000 \
  --deny-base-url http://127.0.0.1:5001 --noguard-base-url http://127.0.0.1:5002
```

| Flag / env var | Meaning |
|---|---|
| `--base-url` / `E2E_BASE_URL` | Policy-mode server. Default `http://127.0.0.1:5000`. |
| `--deny-base-url` / `E2E_DENY_BASE_URL` | Deny-mode server. Without it, the S1 403 (policy) check is SKIP. |
| `--noguard-base-url` / `E2E_NOGUARD_BASE_URL` | No-guard server. Without it, the S1 403 (no guard) check is SKIP. |
| `--via-agent` | S1 takes its envelope from an agent chat, which exercises the chat → envelope lift. It needs an LLM key. |
| `--scenarios` | Default `s1,s2,s3,s5`. |
| `--timeout` | Per-session HTTP timeout in seconds. Default 300. |
| `E2E_SHARE_USER` / `E2E_SHARE_PASSWORD` | A second, logged-in user for the share-bearer refresh. Without it, the E2E user acts as the bearer. |
| `E2E_S2_RANGE_A` / `E2E_S2_RANGE_B` | `firstdate:lastdate`. Defaults are `FDOM:TODAY` and `YESTERDAY:YESTERDAY` on staging, and `2025-03-01:2025-03-07` and `2025-03-11:2025-03-15` on dev. |
| `E2E_RANGE` | `firstdate:lastdate` for S1/S3/S5 and the S2 publish. Defaults to the ENV's range A. |
| `AUTH_USERNAME_ATTRIBUTE` / `AUTH_PASSWORD_ATTRIBUTE` | Login body field names. Defaults are `username` and `password`. |

Each check prints PASS, FAIL or SKIP. The exit code is:

- **0** only when at least one check ran and every non-skipped check passed;
- **1** otherwise;
- **2** when the run is refused (`ENV` is not `staging` or `dev`, or `E2E_USER`/`E2E_PASSWORD` is missing).

## 4. Pytest tiers

```bash
pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py -q     # deterministic, no DB
ENV=dev E2E_USER=… E2E_PASSWORD=… \
  pytest -m staging packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py
```

The **live** tier keeps the marker name `staging`, but it means "live target (staging or dev)". It skips
unless three conditions hold: `ENV` is `staging` or `dev`, querysource >= 5.1.2, and
`E2E_USER`/`E2E_PASSWORD` set. It needs a running server at `E2E_BASE_URL`. It also reads
`E2E_DENY_BASE_URL`, `E2E_NOGUARD_BASE_URL` and `E2E_VIA_AGENT=1`. It fails when every check in a scenario
was skipped.

**Worktrees**: point `PYTHONPATH` at the worktree sources, or the venv will import the main checkout's
packages:

```bash
WT=$(pwd)
export PYTHONPATH=$WT/packages/ai-parrot/src:$WT/packages/ai-parrot-tools/src:$WT/packages/ai-parrot-server/src:$WT/packages/ai-parrot-visualizations/src
```

If `parrot.utils.types` fails to import, symlink the compiled Cython `.so` files from the main checkout.
They are `parrot/utils/types*.so` and `parrot/utils/parsers/toml*.so`. Leave them untracked.

## 5. Golden, parity and vitest (offline)

```bash
pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py
pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_parity.py
pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_seed_staging_guard.py
# vitest wrappers (Node >= 24 + pnpm; they SKIP without pnpm or ui/node_modules, and a skip is not a pass)
pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py
pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_canvas_linked.py
pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_surface.py
pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_dsl.py
pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_runtime.py
pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_types.py
```

- **Parity fixture.** `contract/fixtures/parity/epson_dashboard_params.json` (under
  `packages/ai-parrot/src/parrot/outputs/a2ui/linked/`) pins the conditions and rows for both lanes. The
  conditions cover declared, undeclared and locked cases.
- **Golden envelope.** `contract/fixtures/envelopes/linked_epson_dashboard.json`. Regenerate it with
  `PARROT_REGEN_GOLDEN=1 pytest …/test_epson_dashboard_golden.py`.

## 6. Manual S4 — admin chat

S4 is exploratory and never required. Record each expectation as observed or not observed.

1. Start `ENV=dev python examples/agents/a2ui/linked_e2e/server.py --port 5000 --llm <provider:model>`.
2. Start the admin UI against it:

   ```bash
   cd packages/ai-parrot-server/ui
   PUBLIC_API_URL=http://127.0.0.1:5000 pnpm dev
   ```

   A2UI is on unless `PUBLIC_AGENTCHAT_A2UI=false`. Open `/admin` and log in as the E2E user.
3. Chat with agent `epson_linked` using output mode **A2UI** (`output_mode=a2ui`). Ask for the Epson activity
   dashboard for a date range that has data.

| # | Expected observation |
|---|---|
| a | A canvas tab opens for the linked surface (Column root, `mode: "a2ui"`). |
| b | `A2UISurface` renders the KPI row, the bar chart and the attainment table. |
| c | Changing **From** / **To** in the "Date range" FilterBar re-queries **only** `activity`. This is the browser lane (`parrot_param`): the chart changes, and `targets` is not re-fetched. |
| d | The **Program** FilterBar filters rows locally, with no network request. |
| e | The **Refresh** button appears **only** when the message's `metadata.a2ui_surface_id` is present, which happens after the agent ran `publish_surface`. Before publishing, there is no button. |
| f | Refresh calls `POST /api/v1/ui/surfaces/{id}/refresh` with the current params. The rows update, "data as of" moves, and any `X-Parrot-Refresh-Warnings` entries show as notices. |
| g | If a refresh fails (for example, the server is stopped), a notice appears and the existing rows stay. |

## Known gotchas and follow-ups

- **Startup needs a real Postgres** (QS 5.1.x `initialize_tenants`). There is no offline server mode.
- **Empty date range → 502 `data_stage`.** Pick ranges with data. On dev, `FDOM`/`TODAY` is empty; the
  runner's dev defaults avoid it, but the dashboard TOOL's own defaults (and the agent's) are still `FDOM`/`TODAY`.
- **`/refresh` params are not persisted.** A later refresh with `{}` reverts to the stored placeholders. The
  UI always re-sends the current params.
- **Lane asymmetry.** The date FilterBar re-queries only `activity` in the browser lane. A server refresh
  broadcasts `firstdate`/`lastdate` to every activity-backed source (`activity`, `attainment`, `kpis`).
- **Stale-refresh 409.** Against a live target, this check depends on winning a race. It is SKIP when the race is
  not won.
- **Share bearers must be logged in.** There is no anonymous share viewing.
- **`MQ_PIPELINE` is provisional** (open placeholder comment in `seed_staging.py`). It is not yet known whether
  `epson_e2e_targets` (which has no date placeholders) tolerates the `firstdate`/`lastdate` that MultiQS
  forwards to every query. The live `preview` run confirms this.
- **Python left join with a real null left key.** The right-hand columns still become object dtype (pd.NA),
  so a `derive` on them fails. The fix covers only the empty-null case.
- **`$state` proxy vs `structuredClone`.** `InfographicCanvas` passes `$state.snapshot(envelope)`.
  `A2UISurface` should take the snapshot itself.
- **Core toolkit runs unguarded.** `QuerysourceToolkit.build_linked_surface` runs with `pctx=None,
  guard=None`. Only the example TOOL is hardened; this is escalated as spec §8 Q4.
- **`ask_stream` does not bind the pctx.** Only `EpsonLinkedAgent.ask()` binds it, so the dashboard TOOL
  fails closed on streaming chats.
- **Local dev `env/.env`.** It sets `AUTH_USER_MODEL=resources.users.User`, which is not in the repo. Staging
  uses `navigator_auth.models.User`; check what `env/dev/.env` sets before starting `server.py` on dev.

## Live run log (2026-09-29, `ENV=dev`)

Staging Postgres was unreachable from the workstation, so the live tier ran on `env/dev/.env`, using the dedicated
`epson_e2e_*` slugs.

**Results**
- `run_e2e.py`: 32/32 PASS, exit 0.
- `pytest -m staging`: 4/4 PASS.
- Evidence: `sdd/state/FEAT-611/findings/F020-staging-slug-definitions.md`.

**Things you need to know before running it elsewhere**
1. **querysource 5.1.2 needs a schema migration.** Run
   `ALTER TABLE public.queries ADD COLUMN IF NOT EXISTS columns_definition varchar[] DEFAULT '{}';`
   Without it, every `QueryModel` read fails (toolkit describe/build, `SlugCatalog`). Direct `QS(slug=...)` still works.
2. **The tenant routes need PBAC grants.** `/api/v1/{tenant}/queries/...` pre-flights `slug:execute` and
   `datasource:use` on the app's PBAC evaluator, and answers a bare 404 when denied. The example policy dir grants
   both for `epson_e2e_*`.
3. **MultiQS only applies conditions keyed by child query name.** A linked multiquery source cannot
   re-parametrize its children per refresh, so the stored pipeline pins them.
4. **Every source has to declare the date placeholders.** `/refresh` broadcasts params to all sources, so any
   sibling slug must declare `{firstdate}`/`{lastdate}`; otherwise QS appends them as WHERE filters.
5. **S4 (admin UI) and `--via-agent` need an LLM client provider registered as an installed distribution.**
   Putting a package on PYTHONPATH is not enough.
