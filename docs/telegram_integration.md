# Telegram Bot Integration Guide

## Quick Start: Exposing an AI-Parrot agent via Telegram

### Step 1: Create a Telegram Bot (via BotFather)

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` command
3. Choose a name: e.g., **NavParrotBot**
4. Choose a username: e.g., **nav_parrot_bot**
5. Copy the bot token: `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`

---

### Step 2: Set the Bot Token

Add to your `.env` file (in `env/.env`):

```bash
HRAGENT_TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
```

> The env var format is `{AGENT_NAME}_TELEGRAM_TOKEN`

---

### Step 3: Create Configuration

Create `env/telegram_bots.yaml`:

```yaml
agents:
  HRAgent:
    chatbot_id: hr_agent     # Must match bot name in BotManager
    welcome_message: "👋 Hello! I'm your HR Assistant. Send me a message!"
```

---

### Step 4: Start the Application

When BotManager starts, Telegram bots automatically begin polling:

```python
from aiohttp import web
from parrot.manager import BotManager

app = web.Application()
manager = BotManager()
manager.setup(app)

# Telegram bots start automatically on startup
web.run_app(app, port=5000)
```

---

### Step 5: Chat with Your Bot

1. Open Telegram
2. Search for your bot: **@nav_parrot_bot**
3. Send `/start` → See welcome message
4. Send any message → Get AI response!

---

## Configuration Options

```yaml
agents:
  MyAgent:
    chatbot_id: my_bot_id          # Required: bot ID in BotManager
    bot_token: "xxx:yyy"           # Optional: or use ENV var
    welcome_message: "Hello!"      # Optional: /start response
    allowed_chat_ids: [123, 456]   # Optional: restrict access
    system_prompt_override: "..."  # Optional: custom prompt
```

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message |
| `/clear` | Reset conversation memory |

---

## Example: Your NavParrotBot Setup

```yaml
# env/telegram_bots.yaml
agents:
  NavParrotBot:
    chatbot_id: hr_agent
    welcome_message: "👋 Hi! I'm NavParrotBot, your HR assistant. How can I help?"
```

```bash
# env/.env
NAVPARROTBOT_TELEGRAM_TOKEN=your_token_from_botfather
```

## Custom Commands:

You can define custom commands in the configuration file:

```yaml
agents:
  NavParrotBot:
    chatbot_id: hr_agent
    welcome_message: "👋 Hi! I'm NavParrotBot, your HR assistant. How can I help?"
    commands:
      report: generate_report     # /report -> agent.generate_report()
      stats: get_statistics       # /stats -> agent.get_statistics()
      summary: daily_summary      # /summary -> agent.daily_summary()
```
Try /help in Telegram to see all available commands and callable methods!

That's it! When your app starts, NavParrotBot will respond to messages via Telegram.
