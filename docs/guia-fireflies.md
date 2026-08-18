  examples/agents/fireflies_daemon.yaml

  Config YAML listo para producción. Solo necesitas:
  parrot serve examples/agents/fireflies_daemon.yaml

  examples/agents/fireflies_obsidian_daemon.py

  Ejemplo programático con una async factory (create_agent) que construye el agente con control total. Dos formas de usarlo:

  # Opción A — ejecutar el script directamente
  python examples/agents/fireflies_obsidian_daemon.py

  # Opción B — usar la factory como target de agentd
  parrot serve examples.agents.fireflies_obsidian_daemon:create_agent \
      --name fireflies-sync

  Una vez corriendo el daemon, desde otra terminal:

  ┌─────────────────────────────────┬───────────────────────────────────────────────────────────────────┐
  │             Acción              │                              Comando                              │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Invocar método directo          │ /invoke sync_fireflies_transcripts {"limit": 5}                   │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Resumir una reunión             │ /invoke summarize_transcript {"note_title": "2026-08-18-standup"} │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Estado del daemon               │ parrot status fireflies-sync                                      │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Exponer a Claude Code vía MCP   │ claude mcp add fireflies-sync -- parrot mcp-serve fireflies-sync  │
  ├─────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Instalar como servicio systemd  │ parrot install-service examples/agents/fireflies_daemon.yaml      │
  └─────────────────────────────────┴───────────────────────────────────────────────────────────────────┘

  El YAML expone sync_fireflies_transcripts y summarize_transcript en exposed_methods, así que tanto /invoke desde la consola como invoke_method desde MCP pueden llamarlos. El scheduler queda habilitado para registrar crons via /schedules
  add si quieres automatizar la sincronización cada 8 horas.
