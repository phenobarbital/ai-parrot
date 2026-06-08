# Autonomous Data-Analyst — AI-Parrot Harness Demo

An end-to-end, runnable demo of an **autonomous agent harness** built on
AI-Parrot, operated over a real **Telegram** bot and powered by a real LLM
(**Gemini**). It exercises every capability of the harness that landed on `dev`:

| Capability | Feature | What you'll see |
|---|---|---|
| **Heartbeat** | FEAT-209 | The agent wakes on an interval (wake → assess → maybe-act), not just on messages. |
| **Spawn sub-agents** | FEAT-208 | The agent delegates a bounded task to an *ephemeral* sub-agent (created → run → discarded). |
| **Event ledger + resume** | FEAT-212 | Every lifecycle event is appended to a typed ledger; on restart, incomplete work is re-enqueued. |
| **Grants** | FEAT-211 | The `publish_report` action is gated behind a Telegram approval that opens a 15-min window. |
| **Operator commands** | FEAT-210 | `/health /status /context /memory /mission /model /thread` — operator-only, fail-closed. |
| **Working Memory Toolkit** | core | The agent stores/recalls intermediate DataFrames & findings across ticks (`wm_*` tools). |
| **Telemetry mixin** | FEAT-177 | Every LLM/tool call is observed (cost + spans); zero-infra by default, OTLP-ready. |

> **Business case:** a *data analyst* that quietly watches for new data, keeps a
> working-memory scratchpad of computed results, delegates self-contained
> sub-analyses to throwaway sub-agents, and asks a human before "publishing".

---

## Files

```
examples/autonomous_analyst/
├── agent.py              # AutonomousAnalystAgent: WorkingMemory + spawn + grant-gated publish
├── service.py            # aiohttp service that assembles & starts the whole harness
├── telegram_bots.yaml    # Telegram config (copy to your ENV_DIR)
├── requirements.txt      # runtime deps + optional extras
└── README.md             # this guide
```

---

## How the pieces connect

```
                       setup_telemetry(ObservabilityConfig)        ← observes everything
                                   │  (subscribes to the GLOBAL lifecycle registry)
 web.run_app(app)                  ▼
   └─ BotManager.setup(app) ── app['bot_manager']
        └─ on_startup:
             1. AutonomousAnalystAgent(bot_manager) → bot_manager._bots["autonomous-analyst"]
             2. LedgerRecorder(InMemory|Postgres).start()           ← FEAT-212 capture
             3. AutonomousOrchestrator.start(ledger, resume_on_start=True)   ← FEAT-212 resume
             4. GrantGuard(store, human_manager) → agent.tool_manager.set_grant_guard()  ← FEAT-211
             5. HeartbeatManager(orchestrator).register(...).start() → app['heartbeat_manager']  ← FEAT-209
             6. TelegramBotManager(bot_manager).startup()           ← polls the real bot
                  └─ resolves agent via get_bot("autonomous-analyst")
                  └─ wrapper(app=...) → operator commands read app['heartbeat_manager']/['bot_manager']
```

The agent itself (`agent.py`) carries the **WorkingMemoryToolkit**, a
grant-gated **`publish_report`** tool, and the **`spawn_sub_agent`** tool.

---

## Prerequisites

1. **Python env** with the monorepo installed (always activate first):
   ```bash
   source .venv/bin/activate
   uv pip install -e packages/ai-parrot \
                  -e packages/ai-parrot-server \
                  -e packages/ai-parrot-integrations
   uv pip install aiogram google-genai
   ```
2. **A Gemini API key** — `GOOGLE_API_KEY`. The agent uses Gemini for reasoning
   (and, if you enable voice, for TTS).
3. **A Telegram bot token** — talk to [@BotFather](https://t.me/BotFather),
   `/newbot`, copy the token.
4. **Your numeric Telegram id** — message [@userinfobot](https://t.me/userinfobot)
   to get it. This is your `operator_chat_id`.

---

## Configure

1. Copy the Telegram config into your environment's `ENV_DIR`
   (where `navconfig` looks — typically the repo's `env/` or `$ENV_DIR`):
   ```bash
   cp examples/autonomous_analyst/telegram_bots.yaml "$ENV_DIR/telegram_bots.yaml"
   ```
   Edit it: set `bot_token`, put your numeric id in **both** `allowed_chat_ids`
   and `operator_chat_ids`. Keep `chatbot_id: "autonomous-analyst"` unchanged —
   it must match `CHATBOT_ID` in `service.py`.

2. Export the secrets:
   ```bash
   export GOOGLE_API_KEY="AIza..."             # Gemini
   export TELEGRAM_BOT_TOKEN="123456:ABC-..."  # from @BotFather
   export OPERATOR_CHAT_IDS="123456789"        # your numeric id (informational)
   # Optional knobs:
   export HEARTBEAT_INTERVAL=120               # seconds between ticks (default 120)
   # export REDIS_URL="redis://localhost:6379" # enables the event-bus trigger path
   # export OTLP_ENDPOINT="http://localhost:4318"   # ship telemetry to a collector
   # export LEDGER_PG_DSN="postgres://..."     # + wire app['database'] for durable ledger
   ```

---

## Run

```bash
source .venv/bin/activate
python examples/autonomous_analyst/service.py
```

You should see, in order: telemetry booted → agent registered → ledger recorder
subscribed → orchestrator started (resume: 0 jobs first time) → heartbeat started
→ Telegram polling started.

---

## Drive the demo from Telegram

As the **operator** (a chat id in `operator_chat_ids`):

| Command | Shows |
|---|---|
| `/health` | Heartbeat liveness — tick/action counts, last tick, consecutive errors. |
| `/status` | Running tasks, active ephemeral sub-agents, scheduler/heartbeat state. |
| `/mission` | The heartbeat's current objective prompt (read-only). |
| `/model` | The agent's LLM/model (read-only). |
| `/memory`, `/context` | The conversation's working/recall memory (read-only). |
| `/thread <task>` | Fork a bounded job into an **ephemeral sub-agent** and get the result. |

Then **chat normally** to make the analyst work:

1. *"Here's some sales data: [paste CSV or describe it]. Compute monthly totals
   and store them."* → the agent uses `wm_compute_and_store` and stores a
   DataFrame under a key in **working memory**.
2. *"Now correlate that with the marketing-spend you stored earlier."* → it
   **recalls** from working memory instead of re-asking.
3. *"Spin up a helper to rank the top-5 months by growth."* → it calls
   `spawn_sub_agent` (FEAT-208): an ephemeral analyst runs that one task with a
   restricted toolset and is then discarded.
4. *"Publish this as a report titled 'Q2 review'."* → `publish_report` is
   `requires_grant`, so the **GrantGuard** asks you (✅ Approve / ❌ Reject). Approve
   once and the **15-min window** lets follow-up publishes through without
   re-asking.

Meanwhile the **heartbeat** fires every `HEARTBEAT_INTERVAL` seconds: it assesses
whether there's pending work and, if so, runs its mission against the same
working-memory scratchpad. Everything (turns, tool calls, grants) is appended to
the **ledger**, and each call is recorded by **telemetry**.

---

## Verifying each capability

- **Telemetry:** with no OTLP endpoint, watch stdout for `parrot.usage`
  structured log lines after each LLM/tool call (cost + tokens). With
  `OTLP_ENDPOINT` set, traces/metrics appear in your collector (see
  `packages/ai-parrot/src/parrot/observability/examples/docker-compose.observability.yml`).
- **Heartbeat:** `/health` tick count climbs every interval.
- **Working memory:** ask it to store, then in a later message ask it to recall
  by key — it should not recompute.
- **Spawn:** `/thread "summarize stored findings"` returns a sub-agent result;
  the sub-agent leaves no entry behind (teardown verified in FEAT-208 tests).
- **Grant:** trigger `publish_report`; you get an approval prompt; deny → action
  blocked (`forbidden`); approve → it runs and a window opens.
- **Ledger + resume:** stop the service mid-task and restart; on a durable
  (Postgres) ledger the orchestrator re-enqueues the incomplete execution at
  startup (`Resume complete: N job(s) re-enqueued`).

---

## Production deployment

### Durable ledger (recommended)
The in-memory ledger is volatile, so **crash-resume is a no-op** with it. For
real resume, back the ledger with Postgres:

1. Provision Postgres and expose it to the app as `app["database"]` (asyncdb).
   The simplest path is to run this agent inside the full AI-Parrot server app
   (`app.py`), which already wires `app["database"]`; then `build_ledger()`
   automatically selects `PostgresLedgerBackend` and calls `ensure_schema()`.
2. The ledger table (`harness_ledger`) and indexes are created idempotently on
   startup.

### Redis (optional)
Set `REDIS_URL` to enable the orchestrator's event-bus + job-injection triggers
(otherwise the heartbeat is the only trigger, which is fine for the demo).

### systemd unit
```ini
# /etc/systemd/system/parrot-analyst.service
[Unit]
Description=AI-Parrot Autonomous Analyst
After=network-online.target

[Service]
Type=simple
User=parrot
WorkingDirectory=/opt/ai-parrot
EnvironmentFile=/opt/ai-parrot/examples/autonomous_analyst/.env   # GOOGLE_API_KEY, TELEGRAM_BOT_TOKEN, ...
ExecStart=/opt/ai-parrot/.venv/bin/python examples/autonomous_analyst/service.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now parrot-analyst
journalctl -u parrot-analyst -f
```
On restart, the Postgres ledger + `resume_on_start=True` recover in-flight work —
the systemd `Restart=on-failure` and the harness resume together give you
aphelion-style continuity.

### Observability stack (optional)
```bash
docker compose -f packages/ai-parrot/src/parrot/observability/examples/docker-compose.observability.yml up -d
export OTLP_ENDPOINT=http://localhost:4318
```
Grafana dashboards ship alongside that compose file.

---

## Security notes

- **Operator commands are fail-closed.** Leave `operator_chat_ids` empty and
  *no one* can run them. List only trusted ids.
- **`publish_report` (and any real side-effecting tool) is grant-gated.** Mark
  sensitive tools with `routing_meta={"requires_grant": True, ...}`; the
  `GrantGuard` intercepts them in `ToolManager.execute_tool` and, without an
  approval channel, **denies** rather than runs.
- **Sub-agents can never exceed the parent's toolset** — `SpawnSubAgentTool`
  intersects the requested tools with `SUBAGENT_ALLOWED_TOOLS` (see `agent.py`).

---

## Notes & caveats

- This demo registers the agent **programmatically** (`bot_manager._bots[...]`)
  for clarity. In a full deployment you'd typically register it via the agent
  registry / DB and let `BotManager.on_startup` load it.
- The heartbeat's `_has_pending_work()` here always returns `True` to make the
  demo lively. Wire it to a real signal (queue depth, dataset freshness) in
  production so the tick is a genuine *assess* step, not a cron.
- Voice reply (FEAT-213) is included as an opt-in toggle in `telegram_bots.yaml`
  but commented out; enable `tts_enabled`/`reply_in_kind` to try voice↔voice.
