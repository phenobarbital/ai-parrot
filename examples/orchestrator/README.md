# Helpdesk Orchestrator Example

End-to-end demo of an **orchestrator agent** that:

1. Dispatches a user question to specialist sub-agents (HR, IT, Finance)
   exposed as tools (`agent.as_tool()` pattern).
2. Grounds answers in two RAG backends:
   - **PageIndex** (hierarchical tree) over the training manuals.
   - **Vector store** (FAISS, in-memory) over the company handbook.
3. Holds a multi-round conversation with the user via a lightweight
   Human-in-the-Loop tool (`ask_user_question`).
4. Follows pre-established rules and detects criticality.
5. Escalates to a human via email at two tiers:
   - **Tier-1** — normal-priority ticket + email to the team manager.
   - **Tier-2** — Sev-1 ticket + URGENT email to the on-call director
     (different recipient).

## Layout

```
examples/orchestrator/
├── main.py                — entry point (--scenario flag)
├── orchestrator.py        — wires the OrchestratorAgent
├── subagents.py           — HR, IT, Finance BasicAgents
├── rules.py               — system prompt + criticality config
├── escalation.py          — Tier-1 / Tier-2 tools
├── hitl.py                — ask_user_question tool
├── knowledge/
│   ├── ingest.py          — build real PageIndex + FAISS indexes
│   ├── retrieval.py       — tools w/ graceful fallback to substring search
│   ├── manuals/           — markdown sources (PageIndex tree)
│   └── handbooks/         — markdown sources (FAISS)
└── logs/                  — tickets.csv + audit jsonl emitted at runtime
```

## Setup

```bash
source .venv/bin/activate
uv pip install -e packages/ai-parrot

# Required for the default orchestrator LLM (Google Gemini).
export GOOGLE_API_KEY=...

# Optional — escalation email recipients.
export HELPDESK_TIER1_EMAIL=team-lead@acme.example
export HELPDESK_TIER2_EMAIL=oncall-director@acme.example

# Optional — switch from dry-run to real email via async-notify.
# export HELPDESK_EMAIL=real
```

## Optional: build real indexes

The example runs without this step (the knowledge tools fall back to a
substring scan over the markdown), but to exercise PageIndex + FAISS for
real, run:

```bash
python -m examples.orchestrator.knowledge.ingest
```

This builds:

- `knowledge/.storage/pageindex/<manual>.json` — PageIndex tree per manual.
- An in-process FAISS index over the handbooks (rebuilt at startup).

## Run a scenario

```bash
# HR question — no escalation
python -m examples.orchestrator.main --scenario hr

# IT issue requiring clarification — no escalation
python -m examples.orchestrator.main --scenario it-clarify

# Tier-1 escalation (password reset, team-manager notified)
python -m examples.orchestrator.main --scenario tier1

# Tier-2 escalation (production outage, on-call director paged)
python -m examples.orchestrator.main --scenario tier2
```

Each run prints the orchestrator's final response and any tickets it
created. Inspect `logs/tickets.csv` and `logs/audit_<date>.jsonl` for
the full trace.

## Interactive mode

```bash
python -m examples.orchestrator.main
```

You'll be prompted for a question, and the orchestrator may ask you
clarifying questions back via stdin.

## How the criticality decision is enforced

See `rules.py`. The orchestrator's system prompt instructs the model to
emit a one-line `CLASSIFICATION: tier-1 | tier-2 — <reason>` *before*
calling either escalation tool, and forbids calling both. Combined with
the explicit Tier-1/Tier-2 hint keywords in the prompt, this produces
deterministic routing on the scripted scenarios above.

## What's NOT in this example

- **MS Teams meeting link creation** — intentionally deferred; the
  current escalation tools both use email (to different recipients).
- **Real Jira REST integration** — the example writes to a local CSV so
  the demo is reproducible. In production, swap
  `_create_jira_ticket` in `escalation.py` for a call to your full
  Jira toolkit (the framework's `JiraConnectTool` handles the OAuth
  bridge).
- **Production HITL** — `hitl.py` uses stdin for portability. Production
  deployments should use `parrot.human.HumanInteractionManager` with a
  Telegram/CLI/Web channel and Redis persistence.
