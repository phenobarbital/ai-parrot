---
type: Wiki Entity
title: TelegramAgentWrapper
id: class:parrot.integrations.telegram.wrapper.TelegramAgentWrapper
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps an Agent/AgentCrew/AgentFlow for Telegram integration.
relates_to:
- concept: class:parrot.integrations.telegram.operator_commands.OperatorCommandsMixin
  rel: extends
---

# TelegramAgentWrapper

Defined in [`parrot.integrations.telegram.wrapper`](../summaries/mod:parrot.integrations.telegram.wrapper.md).

```python
class TelegramAgentWrapper(OperatorCommandsMixin)
```

Wraps an Agent/AgentCrew/AgentFlow for Telegram integration.

Manages:
- Per-chat conversation memory
- Message routing from Telegram to agent
- Response formatting for Telegram
- File/image handling

Attributes:
    agent: The AI-Parrot agent instance
    bot: The aiogram Bot instance
    config: Telegram configuration for this agent
    router: aiogram Router with registered handlers
    conversations: Per-chat conversation memories

## Methods

- `def get_bot_commands(self) -> list` — Build list of ``BotCommand`` for Telegram ``setMyCommands`` API.
- `async def register_command_menu(self) -> None` — Publish this bot's command menu to Telegram (setMyCommands + chat menu button).
- `async def handle_start(self, message: Message) -> None` — Handle /start command with welcome message.
- `async def handle_clear(self, message: Message) -> None` — Handle /clear command to reset conversation memory.
- `async def handle_help(self, message: Message) -> None` — Handle /help command — briefing description with available options.
- `async def handle_call(self, message: Message) -> None` — Handle /call command to invoke an agent method.
- `async def handle_whoami(self, message: Message) -> None` — Handle /whoami — returns agent name and description.
- `async def handle_commands(self, message: Message) -> None` — Handle /commands — list all registered commands and functions.
- `async def handle_tool(self, message: Message) -> None` — Handle /tool <name> [args] — invoke a tool by name.
- `async def handle_skill(self, message: Message) -> None` — Handle /skill <name> [args] — invoke a skill by name.
- `async def handle_function(self, message: Message) -> None` — Handle /function <method> [key=val ...] — invoke agent method with kwargs.
- `async def handle_question(self, message: Message) -> None` — Handle /question <text> — pure LLM query without tools.
- `async def handle_login(self, message: Message) -> None` — Handle /login — show login WebApp button via configured strategy.
- `async def handle_logout(self, message: Message) -> None` — Handle /logout — clear authentication state.
- `async def handle_web_app_data(self, message: Message) -> None` — Handle data returned from the login WebApp.
- `async def handle_message(self, message: Message) -> None` — Process incoming text message and send agent response.
- `async def handle_group_ask(self, message: Message) -> None` — Handle /ask command in group chats.
- `async def handle_group_mention(self, message: Message) -> None` — Handle @mention in group chats.
- `async def handle_channel_mention(self, message: Message) -> None` — Handle @mention in channel posts.
- `async def handle_photo(self, message: Message) -> None` — Handle photo messages.
- `async def handle_document(self, message: Message) -> None` — Handle document messages — download and pass to agent.
- `async def close(self) -> None` — Release resources held by the wrapper (call on shutdown).
- `async def handle_voice(self, message: Message) -> None` — Handle voice note (ContentType.VOICE) and audio file (ContentType.AUDIO).
- `async def send_interactive_message(self, chat_id: int, text: str, keyboard: dict, parse_mode: str='Markdown') -> int | None` — Send a proactive message with inline keyboard to a specific chat.
