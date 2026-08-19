---
kind: file
jira_key: null
source_path: /home/jelitox/BRAINSTORM-dashboard-notify-canvas.md
fetched_at: 2026-08-18T23:48:00Z
summary_oneline: "Scheduled delivery of Navigator dashboards (HTML artifact refresh -> secure share -> Teams card/email) plus A2UI Canvas Builder target state"
user_constraints:
  - "Feature-flagged coexistence: keep v1-html supported, add v2-a2ui alongside (no replacement)"
---

# BRAINSTORM — Dashboard Scheduled Notifications & Canvas Builder (A2UI)

> **Status:** Ready for `sdd-proposal` processing (local repo, wiki toolkit + Claude Code multi-repo project)
> **Author:** Javier León (@jelitox)
> **Date:** 2026-08-18 — **rev 2.1** (incorporates Jesús's review + entity-model & PoC framing clarifications)
> **Sources:** Team chat + Jesús's corrections. Claims below must be **re-verified against the repos via wiki toolkit** during sdd-proposal — this doc is input, not ground truth.
> **Execution model:** Two specs (SPEC-A, SPEC-B) derived from a single brainstorm

---

## 0. Review corrections applied (rev 2)

Jesús's feedback on rev 1, applied throughout:

1. **Entity model clarified (rev 2.1).** Carlos's report **is a Navigator dashboard** — but its charts/widgets are NOT built with Navigator's native widget libraries. The visual content is a **Claude-generated, self-contained HTML artifact** (produced by an ETL against data slugs) attached to an **iframe widget inside the Navigator dashboard**. Two distinct entities, two distinct lifecycles: the *Navigator dashboard* (persisted entity, hosts the iframe widget, where the notifications settings panel lives) and the *HTML artifact* (the thing that must be regenerated, stored securely, and shared). Rev 1's error was treating them as one; the refresh/storage/sharing pipeline targets the **artifact**, never the dashboard entity.
2. **Teams cannot receive ~1MB of HTML. Period.** Delivery via Teams is **Adaptive Card with a preamble + URL** only. The artifact never travels as an attachment.
3. **Static publishing is rejected.** These dashboards contain strategic financial/economic company data. No unprotected `/static/`. Storage goes to **S3**, with a secure sharing model (see §4.1.B).
4. **The naked-URL problem:** a share URL that embeds an API key distributes credentials indiscriminately. The sharing model must use **navigator-auth ephemeral tokens (1–24h)** and hide any long-lived credential behind a middleware.
5. **FEAT-273 is DONE** — it has been finished for a long time. SPEC-B is not blocked on its delivery; the dependency is **verifying the end-to-end integration locally** (wiki toolkit against the repo), not waiting for it to be built.
6. **Scheduler CRUD framing corrected:** Jesús always knew the table and CRUD exist — his point was that **nobody uses it**. Adoption, not existence, is the gap.
7. **Notification template DB table + rendering engine: YAGNI.** async-notify consumes templates from `TEMPLATES_DIR` and also accepts a **Jinja2 stream as text** (`template={jinja2 stream}`). Jinja support has existed "since the world began" — there is no "new rendering engine" to build. We have zero templates today; a DB store + CRUD is premature. If/when needed, the component implementing the send decides how to fetch a Jinja2 template from DB.
8. **Confirmed:** `NotificationMixin` in MS Teams mode **can send Adaptive Cards** (verified locally against ai-parrot).
9. **Method:** all research for the proposal/spec phases runs against local repos with wiki toolkit — not from memory or web assumptions.
10. **(rev 2.1) SPEC-A is explicitly the PoC** of the final proposal, which is SPEC-B. The pipeline built in SPEC-A (scheduling, sharing, delivery) is the permanent part; the HTML-artifact generation is the disposable part.
11. **(rev 2.1) Sharing reuses Navigator's existing dashboard-sharing functionality** (token scoped to a single dashboard), with a possible module-level sharing extension — instead of inventing a new share mechanism over raw S3 URLs.

---

## 1. Problem Statement

Carlos's reports are **Navigator dashboards whose visual content is a Claude-generated, self-contained HTML artifact** (produced by an ETL against data slugs) embedded via an iframe widget — instead of native Navigator widgets. These dashboards need **scheduled delivery via Microsoft Teams and Email**, configurable by the user from the dashboard itself.

**Entity model (critical for scoping):**

```
Navigator dashboard (entity)          ← settings panel, scheduling scope (dashboard_id)
  └── iframe widget
        └── HTML artifact (Claude-generated, ETL-produced, self-contained)
                                      ← what gets regenerated, stored in S3, and shared
```

Target user story (v1):

> A user configures on a specific report: *"send it every day via Teams to jlara@ at 6am"*.

Today this delivery exists only as a hardcoded step inside an ETL. There is no self-service scheduling, no card-based Teams delivery, and no secure sharing model for the artifact URL.

### Core architectural facts

- **Self-contained = must regenerate.** The HTML embeds all data at generation time; it does not consume slugs at runtime. Every scheduled send requires regenerating the artifact first.
- **Teams delivery = card + URL.** The artifact is too large to send; the card carries a preamble and a link. Therefore the **secure reachability of that URL is a first-class requirement**, not an afterthought: today the URL travels with an API key, which is direct, indiscriminate credential distribution.

### Long-term direction (v2)

Move artifact generation to **agent-generated, deterministically refreshable A2UI structures** (FEAT-273 — already built) and give Navigator an **Artifact & Canvas Builder** so reports are composed from real catalog components instead of opaque HTML blobs.

---

## 2. Execution Strategy: Two Specs

**Framing (critical): SPEC-A is the PoC of the final solution, which is SPEC-B.** SPEC-A proves the end-to-end loop (scheduled refresh → secure share → card delivery) using today's Claude-generated HTML artifacts as the content mechanism. SPEC-B is the target-state proposal, where content generation moves to agent-produced A2UI structures composed in Navigator's Canvas Builder. Everything SPEC-A builds around the artifact (scheduling, sharing, delivery) is designed to survive into SPEC-B unchanged.

| | SPEC-A | SPEC-B |
|---|---|---|
| **Name** | Scheduled Dashboard Delivery (v1 — PoC) | Artifact & Canvas Builder (v2 — A2UI, final proposal) |
| **Scope** | Per-dashboard scheduled delivery: artifact refresh → secure share (Navigator dashboard sharing) → Teams Adaptive Card + Email | Agent-generated multi-dashboard infographics in A2UI + visual Canvas Builder in Navigator |
| **Dependency** | None new (scheduler, notify, Navigator dashboard sharing, nav-auth ephemeral tokens all exist) | FEAT-273 (done) — requires local end-to-end verification + integration work |
| **Relationship** | PoC: validates the delivery pipeline with minimal new construction | Final state: replaces the artifact-generation step; reuses SPEC-A's scheduling, sharing, and notify pipeline. Formats coexist during transition |

---

## 3. Known substrate (to re-verify via wiki toolkit during sdd-proposal)

### 3.1 AgentScheduler (ai-parrot-server) — exists; adoption is the gap

- Postgres table `navigator.agents_scheduler`; `method_name` schedules arbitrary Python methods (not agents only); `schedule_type`: once/daily/weekly/monthly/interval/cron/crontab; `send_result` (email on success); `callbacks` (JSONB); `enabled`/`last_run`/`next_run`/`run_count`; `metadata` (natural place for report scoping).
- REST CRUD exists (`/api/v1/parrot/scheduler/schedules` + `/callbacks` catalog + `restart`; PATCH supports pause/resume). **It exists but nobody uses it** — SPEC-A becomes its first real consumer, which means budgeting for hardening/bugs found on first adoption.
- NavAPI already boots `ai-parrot-server`, so the scheduler is already running. No new infrastructure.

### 3.2 Notify stack — cards and Jinja already solved

- `send_notify_report` callback exists (Telegram / **MS Teams** / Slack, attachments, auto-CSV).
- **Confirmed: NotificationMixin in Teams mode sends Adaptive Cards.**
- async-notify templates: consumed from `TEMPLATES_DIR`, or passed inline as a **Jinja2 stream in text** — Jinja rendering is long-standing, built-in functionality. **No new rendering engine is needed.**
- The gap is narrow: the scheduler's callback today passes `message` as plain text/markdown — it does not build a card from a template. Extending the callback (or adding a card-aware one) to feed a rendered Adaptive Card to NotificationMixin is the actual work.
- Flowtask's `SendNotify` and the scheduler callback both sit on Notify underneath — one substrate, two entry points. The card vocabulary and recipients model (`name + account.provider + address`) are the same; keep the config shape compatible.

### 3.3 Artifact generation — what Carlos's flow actually is

- The report **is a Navigator dashboard** (persisted entity) containing an **iframe widget** that points to a **Claude-generated, self-contained HTML artifact** produced by an ETL against data slugs. The artifact — not the dashboard entity — is what embeds the data and goes stale.
- **Role of each entity in this pipeline:** the Navigator dashboard provides the *scoping and configuration surface* (its settings host the notifications panel; `dashboard_id` is the natural scheduling scope key). The artifact is the *refresh/storage/sharing target*. Navigator's `/api/v1/dashboards` CRUD is relevant only for reading dashboard identity/metadata — it plays no role in artifact generation.
- The refresh step for SPEC-A is therefore: **invoke/re-run the generation that the ETL performs today** (regenerate the HTML artifact), packaged as a callable method the scheduler can execute (`method_name`). Exact extraction strategy (reuse the ETL task vs. extract the generation function) to be resolved in the proposal with repo access.
- **Current storage:** the generated artifact lives as a **static file on the file server**, and the iframe widget points to it. SPEC-A iterates this to private S3 behind a middleware (see §4.1.B).
- After regeneration, the iframe widget's target must resolve to the **new** artifact version (versioned S3 key vs. stable key overwrite — resolve in proposal, considering cache behavior in the iframe).

### 3.4 navigator-auth & Navigator dashboard sharing

- navigator-auth supports **ephemeral tokens with 1–24h lifetime** — building block for secure share URLs.
- **Navigator already has dashboard-sharing functionality**: a dashboard is shared via a token, and that token grants access **only to that specific dashboard**. This is the natural share mechanism for the URL delivered in the Teams card / email — the recipient lands on the shared Navigator dashboard (which renders the iframe widget with the fresh artifact), instead of hitting the raw artifact directly.
- **Possible extension (to evaluate in proposal):** module-level sharing — extending the sharing functionality so a module (not just a full dashboard) can be shared with its own scoped token.

### 3.5 FEAT-273 / A2UI — done, pending adoption

- Agents respond in generic A2UI (Agent-2-UI) structures; deterministic adapter bridges legacy `InfographicResponse` (flat typed blocks) to A2UI `CreateSurface` envelopes with real catalog components (KPICard, Chart, DataTable, …). Infographic toolkit and A2UI artifacts exist in ai-parrot.
- The recurring organizational risk named in chat: capabilities exist but wait on single-person knowledge ("only Jesús knows how to use it"). SPEC-B must include knowledge transfer / documentation as a deliverable, not just integration.

---

## 4. SPEC-A — Scheduled Report Delivery (v1)

### 4.1 Functional scope

**A. Refresh function (backend — new)**

`refresh_dashboard_artifact(dashboard_id)` — callable registered via `method_name` on the AgentScheduler. Scoped by the **Navigator dashboard**; acts on its attached **HTML artifact**:

1. Resolves the dashboard's iframe widget → identifies the artifact to regenerate
2. Re-runs the generation the ETL performs today (regenerates the self-contained HTML against slugs)
3. Stores the artifact per the secure storage model (B), ensuring the iframe widget resolves to the fresh version
4. Produces the share URL (ephemeral) and hands context to the notify callback (D)

**Hard invariant:** refresh + storage decoupled from delivery. SPEC-B swaps only the generation mechanism.

**B. Secure artifact storage & sharing model (backend)**

*Storage — current state and iteration target (Jesús's constraint):*
- **Today:** the artifact is stored as a **static file on the file server**. This is the current state, acceptable only as starting point — these artifacts contain strategic financial data and should not remain on unprotected static storage.
- **SPEC-A iterates storage to S3**: artifact written to a **private S3 bucket**, accessed via a **non-expiring internal token consumed only by a middleware** that hides that credential entirely; the iframe widget inside Navigator resolves the artifact through it.
- Migration path: the refresh function writes to S3 from day one; existing static-file artifacts are migrated or naturally replaced on their first scheduled refresh.

*Sharing (primary mechanism — reuse Navigator dashboard sharing):*
- The URL delivered in the Teams card / email is a **Navigator dashboard share link**: Navigator's existing sharing functionality issues a token scoped to **that dashboard only**. The recipient opens the shared dashboard, which renders the iframe widget with the freshly regenerated artifact.
- This keeps the artifact itself entirely behind Navigator + the middleware; the only thing traveling in chat/inbox is a dashboard-scoped share token.
- Token lifetime: evaluate combining with navigator-auth ephemeral keys (1–24h) so shared links expire — TTL policy (per send?) is an open design point.
- **Possible extension (proposal to evaluate):** module-level sharing — share a single module with its own scoped token, for cases where a full dashboard share is too broad.
- Result: no long-lived credential ever travels in a chat or inbox; access is scoped (dashboard or module) and time-bounded.

*Open design points for the proposal:* share-token TTL policy and expiry behavior (re-request flow?), versioned S3 keys vs. stable-key overwrite (iframe cache behavior), middleware placement (NavAPI route vs. existing gateway), module-sharing scope.

**C. Scheduling (wiring only — no new scheduler code)**

- Schedules created/managed through the **existing AgentScheduler CRUD**; SPEC-A is its first real consumer (budget for first-adopter hardening).
- Config: `method_name: refresh_dashboard_artifact`, `metadata: {dashboard_id}`, `schedule_type` + `schedule_config` from user input, `callbacks` for delivery.
- Thin NavAPI wrapper endpoint recommended (`/api/v1/dashboards/{dashboard_id}/notifications` or similar) for dashboard-scoping + permissions, translating to scheduler CRUD calls. UI never touches the generic scheduler surface directly. The settings panel lives in the **Navigator dashboard's** existing settings surface.

**D. Teams Adaptive Card + Email delivery (backend — small extension)**

- Extend `send_notify_report` (or add a card-aware callback) to build an **Adaptive Card**: preamble text + `Action.OpenUrl` pointing to the ephemeral share URL. **The HTML never travels as attachment.**
- Card content rendered from a **Jinja2 template using async-notify's existing template support** — `TEMPLATES_DIR` file or inline Jinja2 stream. System variables injected by the refresh function: `report_title`, `generated_at`, `share_url`.
- Email path: same Jinja2 template mechanism (async-notify `send_email` template support), linking the same ephemeral URL.
- **No DB template store, no template CRUD, no new rendering engine (YAGNI).** Start with 1–2 templates in `TEMPLATES_DIR`. If a real need for user-managed templates emerges later, the send component defines how to fetch a Jinja2 template from DB at that point.

**E. UI — settings panel (frontend Svelte 5)**

Per-dashboard "Notifications" section (lives in the Navigator dashboard's settings):

- Toggle on/off; channels (Teams / Email / both); recipients (async-notify model: name + provider + address); frequency (daily/weekly/days + time)
- Template selection limited to the available `TEMPLATES_DIR` set (no template editing in v1)
- Upcoming sends (`next_run`) + basic history (`last_run`, `run_count`; sent/failed at log level)
- Edit / pause / resume / delete via the wrapper → scheduler PATCH/DELETE

### 4.2 Build delta

1. `refresh_dashboard_artifact` function (resolve iframe widget → extract/invoke today's ETL generation)
2. Storage iteration: **static file server (today) → private S3 behind middleware** (hidden permanent token) + share-link integration with **Navigator's existing dashboard sharing** (dashboard-scoped token, optionally ephemeral via nav-auth)
3. Card-aware callback extension (Adaptive Card from Jinja template + dashboard share URL)
4. Thin NavAPI wrapper for dashboard-scoped schedule CRUD
5. Settings panel (Svelte 5)
6. (Optional, evaluate in proposal) module-level sharing extension

Everything else — scheduler, CRUD, triggers, pause/resume, Teams/email transport, Jinja templating, dashboard sharing — already exists and is wired, not built.

### 4.3 Hard invariants

- **HI-1:** No parallel scheduling system; all scheduling through AgentScheduler.
- **HI-2:** Artifact generation decoupled from storage/sharing and from delivery.
- **HI-3:** No long-lived credential ever appears in a delivered URL; sharing only via Navigator's dashboard-scoped share tokens (time-bounded via nav-auth ephemeral keys), with the S3 credential hidden behind the middleware.
- **HI-4:** Teams delivery is card + URL only; artifacts never attached.
- **HI-5:** Template handling uses async-notify's existing Jinja mechanisms; no persistence layer for templates in v1.
- **HI-6:** SPEC-A is a PoC: every pipeline component (scheduling, sharing, delivery) must be reusable as-is by SPEC-B; only the artifact-generation step is disposable.

### 4.4 Out of scope (v1)

- A2UI / agent generation (SPEC-B)
- Template editor / DB-backed template management
- Live (runtime-API) dashboards
- Migration of existing ETL sends (they coexist; both sit on Notify anyway)

### 4.5 Open questions for the proposal (with repo access)

- Extraction strategy for the ETL generation step → callable method (resolving the dashboard's iframe widget to its artifact)
- Navigator dashboard-sharing integration: token issuance flow from the scheduler context, TTL/expiry policy, whether module-level sharing is in v1 or deferred
- Versioned S3 keys vs. stable-key overwrite (iframe cache behavior after refresh)
- Middleware placement (NavAPI route vs. existing gateway)
- First-adopter findings on scheduler CRUD (validation, error handling, restart semantics)
- `as_user: true` semantics parity between Flowtask SendNotify and the scheduler callback

---

## 5. SPEC-B — Artifact & Canvas Builder (v2 — A2UI)

> FEAT-273 is **done**. SPEC-B's work is local verification, integration, and adoption — not waiting on platform delivery.

### 5.1 Functional scope

**A. Generation engine — Agent + A2UI**

- Agent reads multiple data sources (slugs, querysources, other connections) and responds in **A2UI `CreateSurface` envelopes** with catalog components (`KPICard`, `Chart`, `DataTable`, …), via the existing deterministic `InfographicResponse` → A2UI adapter.
- Output structure is **deterministically refreshable**: same source inputs regenerate the same updated structure — replacing the "opaque HTML blob" model.

**B. Canvas Builder in Navigator**

- Visual composition from catalog components. Two permission levels: **self-service** (business users, no-code, guided options) and **advanced** (Nav/dev: granular envelope config, new data sources, custom components). Requires role differentiation in Navigator.

**C. Coexistence & progressive replacement**

- v2 replaces artifact generation report by report; **no forced migration, no cutoff**. Each report carries its artifact type (`v1-html` | `v2-a2ui`); the pipeline dispatches on it. SPEC-A's settings panel works identically for both.

**D. Pipeline reuse (per HI-2/HI-3)**

- Scheduling, S3+ephemeral sharing model, card delivery: unchanged. Only the refresh step differs.
- To resolve in spec: A2UI → sendable/viewable rendering for the share URL target (the interactive surface lives in Navigator; the card's URL points there or to a rendered snapshot in S3).

**E. Knowledge transfer (explicit deliverable)**

- Local end-to-end verification of FEAT-273 (wiki toolkit, repo access), documented runbook/wiki so infographics + A2UI stop being single-person knowledge. This addresses the stated adoption bottleneck directly.

### 5.2 Out of scope

- Automatic migration of v1 reports
- Full catalog expansion beyond existing FEAT-273 components
- Building Navigator's permission system from scratch (assess existing base first)

### 5.3 Risks

- Adoption/knowledge-concentration risk (mitigated by 5.1.E)
- A2UI → sendable-format rendering may need work beyond FEAT-273's scope
- Two-level Canvas Builder permissions may exceed this spec's boundary

---

## 6. Next Steps (method per Jesús)

1. Move this brainstorm into the **local repo** and run it through **`sdd-proposal` with wiki toolkit + Claude Code project connected to the relevant repos** (ai-parrot, async-notify, navigator-auth, the ETL repo). All §3 claims re-verified there.
2. Proposal resolves: ETL-generation extraction, S3+middleware sharing design, ephemeral TTL policy, callback extension shape.
3. Align with Carlos on the generation step reuse.
4. SPEC-B proposal runs in parallel: local FEAT-273 end-to-end verification is its first task.
