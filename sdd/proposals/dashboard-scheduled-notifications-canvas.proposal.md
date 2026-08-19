---
id: FEAT-430
title: Scheduled dashboard delivery (artifact refresh → signed share → Teams card/email) with v1-html/v2-a2ui coexistence
slug: dashboard-scheduled-notifications-canvas
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-08-18
  summary_oneline: "Self-service scheduled delivery of Navigator dashboards via Teams/Email, plus A2UI Canvas Builder target state"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-430/
created: 2026-08-18
updated: 2026-08-18
---

# FEAT-430 — Scheduled Dashboard Delivery & Canvas Builder

> **Mode**: enrichment
> **Confidence**: high (9 findings, 5 repos, budget `loose`, not truncated)
> **Source**: `file: /home/jelitox/BRAINSTORM-dashboard-notify-canvas.md` (rev 2.1)
> **Audit**: [`sdd/state/FEAT-430/`](../state/FEAT-430/)

---

## 0. Origin

A brainstorm (rev 2.1, Javier León, incorporating Jesús's review) describing scheduled
delivery of Carlos's Navigator dashboards via Microsoft Teams and Email, split into two
specs: **SPEC-A** (PoC — scheduled delivery of today's Claude-generated HTML artifacts)
and **SPEC-B** (target state — agent-generated A2UI + Canvas Builder).

The brainstorm explicitly asks (§6) that all its §3 claims be **re-verified against the
repos**. This proposal is that verification. All five referenced repos were available
locally: `ai-parrot`, `navigator-api`, `navigator-auth`, `navigator-front`, `flowtask`.

**User constraint added during this run:** the v1→v2 transition is **feature-flagged
coexistence** — existing `v1-html` support is retained and `v2-a2ui` is added alongside.
No replacement, no forced migration.

---

## 1. Synthesis Summary

**The build delta for SPEC-A is substantially smaller than the brainstorm estimates.**

The two hardest items it plans to construct — (a) secure artifact storage with
credential-free, time-bounded URLs, and (b) Adaptive Card delivery — **already exist and
ship today** in `ai-parrot`. What remains genuinely new is a refresh function, a
dashboard-scoped scheduling wrapper, a card-aware callback, a settings panel, and a
one-field discriminator to satisfy the coexistence requirement.

The brainstorm's core architectural instincts hold up: the scheduler is the right
substrate, delivery must be card+URL, and static publishing must be rejected. What
changes is **how much has to be built to get there**.

---

## 2. Codebase Findings

### 2.1 Localization (verified)

| Component | Location | Finding |
|---|---|---|
| Schedule table/model | `ai-parrot-server/.../scheduler/models.py::AgentSchedule` | F001 |
| Callback contract | `ai-parrot-server/.../scheduler/functions/__init__.py::BaseSchedulerCallback` | F002 |
| Existing notify callback | same file `::SendNotifyReportCallback` | F002 |
| Adaptive Card builder | `ai-parrot/.../notifications/__init__.py::build_teams_card` (L100-156) | F003 |
| Card sender | same file `::send_teams_card` (L1101+), `_is_teams_card` (L76) | F003 |
| Jinja template engine | `notify/templates.py::TemplateParser` (async-notify 1.5.5) | F004 |
| Live share URL construction | `navigator-api/apps/ambassador/views.py::_build_offers_urls` (L325-347) | F005 |
| Ephemeral token mint | `navigator-auth/.../backends/idp/__init__.py::create_ephemeral_token` (L265) | F006 |
| A2UI artifact/delivery | `ai-parrot/.../outputs/a2ui/{artifacts,delivery,deeplink}.py` | F007 |
| A2UI → card renderer | `ai-parrot-visualizations/.../a2ui_renderers/adaptive_cards.py` | F007 |
| **Artifact store (S3)** | `ai-parrot/.../storage/artifacts.py::ArtifactStore` | F008 |
| **Signed iframe URLs** | `ai-parrot/.../storage/artifact_signing.py` | F008 |
| Dashboard entity | `navigator-api/resources/dashboards/models.py::Dashboard` | F009 |

### 2.2 Claims CONFIRMED

- **§3.1 AgentScheduler** — `navigator.agents_scheduler` exists exactly as described:
  `method_name` schedules arbitrary Python methods, `metadata` JSONB is a natural slot
  for `dashboard_id`, `callbacks` JSONB drives delivery, plus
  `enabled`/`last_run`/`next_run`/`run_count`. [F001]
- **§3.2 the callback gap is real and narrow** — `SendNotifyReportCallback.run()` sends
  `message` as plain text/markdown; no card is ever constructed. [F002]
- **rev2 #8 Teams cards** — confirmed, and stronger than claimed (see 2.3). [F003]
- **rev2 #4 the naked-URL problem** — confirmed **in live production code**:

  ```python
  _api_key = config.get("AMBASSADOR_ANONYM_USER_TOKEN")
  query_params = {"referalcode": lead_id, "apikey": _api_key}
  ```

  A static, environment-wide, non-expiring, non-revocable token is emailed to external
  leads. This makes HI-3 a **fix to existing behavior**, not just a constraint on new
  code — which raises SPEC-A's value. [F005]
- **§3.4 dashboard sharing exists** — URL shape
  `https://connect[.<env>].trocdigital.io/share/dashboard/<dashboard_id>`, and
  `Dashboard.shared: bool` is a modeled property. [F005, F009]

### 2.3 Claims CORRECTED

1. **Adaptive Card work is smaller than stated.** [F003]
   `NotificationMixin` already ships `build_teams_card(title, text, *, sections, actions,
   files, version="1.5")`, `send_teams_card()`, and `_is_teams_card()` auto-detection so
   `send_notification(message=<card>)` routes cards automatically. The method's own
   docstring example is almost verbatim the SPEC-A payload (title + text +
   `Action.OpenUrl` → dashboard URL). **No card model, renderer, or schema work.**

2. **async-notify does NOT accept an inline Jinja2 stream.** [F004]
   `providers/base.py` does `self._tpl.get_template(template)`, and `get_template` is a
   `FileSystemLoader` filename lookup. There is no `from_string` anywhere in the package.
   Passing a raw Jinja string raises `FileNotFoundError`. Jinja itself IS long-standing
   and needs no new engine (rev2 #7 correct on that point) — but the "or inline stream"
   alternative does not exist. The config key is also `TEMPLATE_DIR`, not `TEMPLATES_DIR`.

3. **Ephemeral tokens are user-scoped with a 30-minute default, not dashboard-scoped
   1-24h.** [F006]
   `create_ephemeral_token(data, expiration=1800)` mints a JWT for the *authenticated
   caller* (`user_id`, `username`, `session_id`) with **no resource scope claim**. Handing
   that to a recipient grants them the sender's identity — strictly worse than today's
   anonymous token. Arbitrary TTLs are possible via `expiration`, but a dashboard-scoped
   share token is **new construction**, both minting and enforcement.

4. **The §4.1.B storage/sharing design is redundant — a better mechanism already
   exists.** [F008] *(headline finding)*

   FEAT-103 + FEAT-197 already ship:
   - `ArtifactStore` wired at `app['artifact_store']`, with `get_public_url` documented as
     "**S3 presigned, ALWAYS** — infographics are never hosted on public S3"
   - `GET /api/v1/artifacts/public/{signature}/{artifact_id}.html`, whose stated purpose is
     "so the frontend can embed a frozen infographic in an `<iframe>` **without an auth
     round-trip**" — signature `{expiry}.{base64url(HMAC-SHA256(KEY, "{id}|{expiry}"))}`

   | Brainstorm §4.1.B | Existing FEAT-197/103 |
   |---|---|
   | non-expiring internal token | expiry baked into every signature |
   | credential hidden by middleware | **no credential in the URL at all** |
   | new middleware to build | serving route + verifier already shipped |
   | new S3 wiring | `ArtifactStore` already initialized |

5. **FEAT-273 is broader than "agents respond in A2UI".** [F007]
   It already contains `RenderedArtifact` (baked static output), `deliver_artifact()`
   (explicitly bridging onto the *existing* `NotificationMixin.send_notification` — "never
   a new delivery stack"), `DeepLinkService` (single-use, TTL-bound **opaque** Redis
   tokens whose "URL embeds ONLY the opaque id — never the payload"), and renderers for
   `adaptive_cards`, `ssr_html`, `interactive_html`, `pdf`. This largely answers SPEC-B
   open question §5.1.D before SPEC-B starts.

### 2.4 Risks NOT anticipated by the brainstorm

- **`AgentSchedule` requires `agent_id` and `agent_name`** with `Meta.strict = True`. A
  dashboard refresh is not an agent. *Resolved: sentinel values (§5 Q3).* [F001]
- **`BaseSchedulerCallback.process_output()` assumes an `AIMessage`.** A plain dict
  returned by `refresh_dashboard_artifact` falls through to `str(result)` and stringifies
  into the message body. Worse, `SendNotifyReportCallback` auto-attaches a CSV whenever
  `payload["data"]` is DataFrame-coercible (`attach_data` defaults **True**) — an
  unwanted attachment that soft-violates HI-4. The card-aware callback must define its
  own payload contract rather than reuse `process_output()`. [F002]
- **A third notify entry point exists.** navigator-api already sends templated email via
  `NotifyClient` / `NOTIFY_WORKER_STREAM` (`template="email_lead.html"`), beyond the two
  the brainstorm names. The spec must pick which entry point SPEC-A's email path uses. [F005]
- **`public=True` publishes to a world-readable `STATIC_DIR`.** Given rev2 #3, SPEC-A must
  pin `public=False` and forbid that branch for dashboard artifacts. [F008]

---

## 3. Hypothesis / Scope

### 3.1 Revised SPEC-A build delta

| # | Item | Brainstorm estimate | Verified reality |
|---|---|---|---|
| 1 | `refresh_dashboard_artifact()` | new | **new** (unchanged) |
| 2 | Secure storage + sharing | S3 + middleware + token | **adopt FEAT-197/103** — config + wiring |
| 3 | Card-aware callback | "small extension" | **smaller** — call existing `build_teams_card` |
| 4 | Thin NavAPI wrapper | new | **new** (unchanged) |
| 5 | Settings panel (Svelte 5) | new | **new** (unchanged) |
| 6 | Module-level sharing | optional | **defer** — `module_id` exists, not needed for v1 |
| 7 | `artifact_type` discriminator | — | **new** (added for coexistence) |

Items 2 and 3 shrink materially; item 7 is added.

### 3.2 Design decisions (resolved with the user)

- **D1 — Storage/sharing:** adopt FEAT-197 HMAC-signed artifact URLs + `ArtifactStore`
  presigned S3. Drop the proposed permanent-token + middleware design. [resolves U1]
- **D2 — Link target:** the Adaptive Card links to the **Navigator dashboard share page**
  (`/share/dashboard/<dashboard_id>`); the dashboard renders the iframe pointing at the
  freshly signed artifact URL. Keeps the artifact behind Navigator and preserves
  navigation context. [resolves U4]
- **D3 — Scheduler fit:** use sentinel `agent_id`/`agent_name` (e.g. `system` /
  `dashboard_refresh`). No schema change, no risk to existing consumers, reversible. [C9]
- **D4 — Templates:** file-based templates in `TEMPLATE_DIR` only. Ship 1-2. Drop the
  "inline Jinja2 stream" alternative. HI-5 unchanged. [C5]

### 3.3 Coexistence design (the user's feature-flag constraint)

Two existing structures make this a dispatch detail rather than an architectural fork:

- **Discriminator:** `Dashboard.attributes` (JSONB) carries
  `{"artifact_type": "v1-html" | "v2-a2ui"}`, **defaulting to `v1-html` when absent** —
  so every existing dashboard keeps working with zero migration. [F009]
- **Common output type:** both generators emit a `RenderedArtifact` (F007), so storage,
  signing, sharing and delivery are written **once** and are identical for both paths.

```
refresh_dashboard_artifact(dashboard_id)
  └─ dispatch on attributes.artifact_type (default "v1-html")
       ├─ v1-html  → re-run today's ETL generation      ─┐
       └─ v2-a2ui  → agent → A2UI CreateSurface → render ─┤
                                                          ▼
                                          RenderedArtifact (common)
                                                          ▼
                              ArtifactStore.save → signed URL (FEAT-197)
                                                          ▼
                              card-aware callback → Teams card + share URL
```

This satisfies HI-6 literally: only the generation branch is disposable.

### 3.4 Hard invariants — status after verification

| ID | Invariant | Status |
|---|---|---|
| HI-1 | All scheduling through AgentScheduler | holds [F001] |
| HI-2 | Generation decoupled from storage/delivery | holds, and `RenderedArtifact` enforces it [F007] |
| HI-3 | No long-lived credential in delivered URLs | **strengthened** — FEAT-197 puts no credential in the URL at all [F008] |
| HI-4 | Card + URL only, never attachments | holds, but requires disabling `attach_data` [F002] |
| HI-5 | async-notify Jinja, no template persistence | holds, file-based only [F004] |
| HI-6 | SPEC-A pipeline reusable by SPEC-B | holds, via `RenderedArtifact` + discriminator [F007, F009] |

---

## 4. Confidence Map

| Claim | Confidence | Basis |
|---|---|---|
| C1 Scheduler substrate exists as described | high | F001, F002 — direct source |
| C2 Adaptive Card path already complete | high | F003 — direct source |
| C3 Secure signed artifact URLs already exist | high | F008, F007 — direct source |
| C4 Naked-URL problem live in production | high | F005 — direct source |
| C5 No inline Jinja stream support | high | F004 — installed pkg 1.5.5 |
| C6 Ephemeral tokens user-scoped, 30-min default | high | F006 — direct source |
| C7 A2UI ships artifact/delivery/card renderer | high | F007 — direct source |
| C8 `attributes` is a migration-free flag seam | medium | F009 — inferred fit, not yet exercised |
| C9 `agent_id`/`agent_name` required | high | F001 — direct source |
| C10 Widget→artifact resolution unlocated | low | F009 — absence of evidence |

---

## 5. Open Questions

- [x] **Q1 — Adopt existing FEAT-197 signed-URL mechanism?** → **Yes.** Reuse
  `ArtifactStore` + `artifact_signing`; drop the permanent-token + middleware design.
- [x] **Q2 — Card link target?** → **Navigator dashboard share page**, not the raw signed
  artifact URL.
- [x] **Q3 — `agent_id`/`agent_name` requirement?** → **Sentinel values**; no schema change.
- [x] **Q4 — Inline Jinja templates?** → **File-based in `TEMPLATE_DIR` only**; ship 1-2.
- [ ] **Q5 — Which entity holds the iframe widget and its artifact URL?** Not located;
  `Dashboard` carries only `allow_widgets` + `widget_location`. Blocks the first step of
  `refresh_dashboard_artifact`. **Needs the widgets module or Carlos.** [C10]
- [ ] **Q6 — ETL generation extraction:** reuse the Flowtask task, or extract the
  generation function into a callable? Needs alignment with Carlos (brainstorm §6.3).
- [ ] **Q7 — Which notify entry point for email:** the scheduler callback, or
  navigator-api's existing `NotifyClient`/`NOTIFY_WORKER_STREAM`? [F005]
- [ ] **Q8 — Signature TTL policy:** what expiry for a scheduled send, and what is the
  re-request flow once a link expires?

---

## 6. Recommended Next Step

→ **`/sdd-spec FEAT-430`**

Localization is high-confidence across five repos, four design decisions are resolved,
and the build delta is concrete. Q5-Q8 are design/alignment questions that the spec can
carry, not discovery gaps that block it — with one caveat: **Q5 should be resolved before
task decomposition**, since `refresh_dashboard_artifact`'s first step depends on it.

**Scope note:** this proposal covers SPEC-A plus the coexistence seam that keeps SPEC-B
non-breaking. A separate proposal for SPEC-B (Canvas Builder, permissions, knowledge
transfer) should run independently, as brainstorm §6.4 intends — and it starts from a
better position than the brainstorm assumed, given F007.

---

## 7. Research Audit

- State: `sdd/state/FEAT-430/`
- Source: `sdd/state/FEAT-430/source.md`
- Findings: `sdd/state/FEAT-430/findings/F001..F009`
- Synthesis: `sdd/state/FEAT-430/synthesis.json`
- Budget: `loose` — not truncated
- Repos examined: `ai-parrot` (wiki-indexed), `navigator-api`, `navigator-auth`,
  `flowtask`, plus async-notify 1.5.5 as installed
- Method: wiki-first for `ai-parrot` (`wikitoolkit query` → `page`), direct grep/read for
  the sibling repos, which are not wiki-indexed
