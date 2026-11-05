# Fireflies Agent Examples

  examples/agents/fireflies_daemon.yaml

  Production-ready YAML config. All you need is:
  parrot serve examples/agents/fireflies_daemon.yaml

  examples/agents/fireflies_obsidian_daemon.py

  Programmatic example with an async factory (create_agent) that builds the agent with full control. Two ways to use it:

  # Option A — run the script directly
  python examples/agents/fireflies_obsidian_daemon.py

  # Option B — use the factory as the agentd target
  parrot serve examples.agents.fireflies_obsidian_daemon:create_agent \
      --name fireflies-sync

  Once the daemon is running, from another terminal:

  ┌─────────────────────────────────┬───────────────────────────────────────────────────────────────────┐
  │             Action              │                              Command                              │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Invoke a method directly        │ /invoke sync_fireflies_transcripts {"limit": 5}                   │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Summarize a meeting             │ /invoke summarize_transcript {"note_title": "2026-08-18-standup"} │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Daemon status                   │ parrot status fireflies-sync                                      │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Expose to Claude Code via MCP   │ claude mcp add fireflies-sync -- parrot mcp-serve fireflies-sync  │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Install as a systemd service    │ parrot install-service examples/agents/fireflies_daemon.yaml      │
  └─────────────────────────────────┴───────────────────────────────────────────────────────────────────┘

  The YAML exposes sync_fireflies_transcripts and summarize_transcript in exposed_methods, so both /invoke from the console and invoke_method from MCP can call them. The scheduler is enabled so you can register crons via /schedules
  add if you want to automate the sync every 8 hours.
