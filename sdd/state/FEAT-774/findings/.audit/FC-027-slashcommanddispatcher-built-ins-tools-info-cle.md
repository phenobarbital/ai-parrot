---
id: FC-027
query_id: Q041
type: read
intent: "CLI slash commands"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-027 — SlashCommandDispatcher: built-ins tools/info/clear/resume/export/stream/create_agent/help/quit; register() hook; ctx.suspend() for device-code prompts

## Summary

`commands.py` has no auth/login command. Relevant to S-4: `CommandContext.suspend()` is documented as the way to yield the terminal to a foreign prompt ('HITL, device code'), and `SlashCommandDispatcher.register()` is the extension hook (agentd adds `/status` etc.). `/info` shows `config.user_id`; `/create_agent` uses `CLIHumanChannel` with target `ctx.config.user_id or "cli_user"`.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/commands.py`
  lines: 41-65, 131-138, 187-211
  symbol: `CommandContext.suspend / register / _register_builtins`
  excerpt: |
    def suspend(self) -> ContextManager[None]:
        """Yield the terminal to a foreign prompt (HITL, device code): inline → LiveRegion.modal(); TUI → App.suspend()."""
    def register(self, cmd: SlashCommand) -> None:
    builtins = [SlashCommand("tools", ...), SlashCommand("info", ...), ..., SlashCommand("quit", ...)]


## Notes

A `/connect <provider>` CLI slash command (mirroring S-2 Telegram) would register here.
