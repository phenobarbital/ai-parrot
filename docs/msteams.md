# MS Teams Toolkit for AI-Parrot

A comprehensive toolkit for Microsoft Teams integration, extending `AbstractToolkit` from the ai-parrot library.

## Features

- **Send messages to channels**: Post messages or Adaptive Cards to public Teams channels
- **Send messages to chats**: Send messages to existing group or one-on-one chats
- **Send direct messages**: Send messages directly to users by email address
- **Create adaptive cards**: Build rich, interactive Adaptive Cards with images, links, and facts
- **User management**: Look up users and manage chats
- **Automatic tool generation**: All public async methods automatically become tools for AI agents

## Installation

```bash
pip install msgraph-sdk azure-identity msal aiohttp pydantic
```

## Configuration

The toolkit can be configured via:
1. **Constructor arguments** (recommended)
2. **Configuration file** (using navconfig)
3. **Environment variables**

### Required Settings

#### Application (Service Principal) Authentication
```python
toolkit = MSTeamsToolkit(
    tenant_id="your-tenant-id",
    client_id="your-client-id",
    client_secret="your-client-secret",
    as_user=False
)
```

#### Delegated User Authentication
```python
toolkit = MSTeamsToolkit(
    tenant_id="your-tenant-id",
    client_id="your-client-id",
    as_user=True,
    username="user@example.com",
    password="password"
)
```

### Azure AD App Registration

1. **Register an Azure AD application**:
   - Go to Azure Portal → Azure Active Directory → App registrations
   - Create a new registration

2. **Configure API permissions**:

   For application permissions (as_user=False):
   - `Chat.ReadWrite.All` - Send messages to chats
   - `ChannelMessage.Send` - Send messages to channels
   - `User.Read.All` - Look up users

   For delegated permissions (as_user=True):
   - `Chat.ReadWrite` - Send messages to chats
   - `ChannelMessage.Send` - Send messages to channels
   - `User.Read` - Look up users

3. **Create a client secret** (for application auth)
4. **Grant admin consent** for the permissions

## Usage

### Basic Usage

```python
import asyncio
from parrot.tools.msteams_toolkit import MSTeamsToolkit

async def main():
    # Initialize the toolkit
    toolkit = MSTeamsToolkit(
        tenant_id="your-tenant-id",
        client_id="your-client-id",
        client_secret="your-client-secret"
    )

    # Connect to Microsoft Teams
    await toolkit.connect()

    # Send a simple message to a channel
    await toolkit.send_message_to_channel(
        team_id="team-id",
        channel_id="channel-id",
        message="Hello Teams!"
    )

    # Cleanup
    await toolkit.close()

asyncio.run(main())
```

### Creating and Sending Adaptive Cards

```python
# Create an adaptive card
card = await toolkit.create_adaptive_card(
    title="Sprint Review",
    body_text="Our team completed 23 story points this sprint!",
    image_url="https://example.com/chart.png",
    link_url="https://example.com/sprint",
    link_text="View Sprint Details",
    facts=[
        {"title": "Stories Completed", "value": "12"},
        {"title": "Bugs Fixed", "value": "5"},
        {"title": "Velocity", "value": "23 points"}
    ]
)

# Send the card to a channel
result = await toolkit.send_message_to_channel(
    team_id="team-id",
    channel_id="channel-id",
    message=card
)

print(f"Message sent! ID: {result['id']}")
```

### Sending Direct Messages

```python
# Send a direct message to a user by email
result = await toolkit.send_direct_message(
    recipient_email="colleague@example.com",
    message="Hi! Can we discuss the project?"
)

# Or send an adaptive card as a direct message
card = await toolkit.create_adaptive_card(
    title="Meeting Reminder",
    body_text="Don't forget our meeting at 2 PM today!",
    link_url="https://teams.microsoft.com/meeting",
    link_text="Join Meeting"
)

await toolkit.send_direct_message(
    recipient_email="colleague@example.com",
    message=card
)
```

### Using with AI Agents

The toolkit automatically converts all public async methods into tools that can be used by AI agents:

```python
from parrot.bots.agent import BasicAgent
from parrot.tools.msteams_toolkit import MSTeamsToolkit

async def main():
    # Initialize toolkit
    toolkit = MSTeamsToolkit(
        tenant_id="your-tenant-id",
        client_id="your-client-id",
        client_secret="your-client-secret"
    )
    await toolkit.connect()

    # Create an agent with MS Teams tools
    agent = BasicAgent(
        name="TeamsAgent",
        role="Microsoft Teams Communication Manager",
        tools=toolkit.get_tools(),
        instructions="""
        You can send messages to Teams channels and chats.
        Use adaptive cards for rich, formatted messages.
        You can look up users by email and send them direct messages.
        """
    )

    # The agent can now use all toolkit methods as tools
    response = await agent.run(
        "Send a project update to the engineering channel with our current metrics"
    )

    await toolkit.close()

asyncio.run(main())
```

### Advanced: Custom Adaptive Cards

You can also create custom Adaptive Cards as JSON:

```python
custom_card = {
    "type": "AdaptiveCard",
    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
    "version": "1.4",
    "body": [
        {
            "type": "TextBlock",
            "text": "Custom Card",
            "weight": "Bolder",
            "size": "Large"
        },
        {
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column",
                    "width": "auto",
                    "items": [
                        {
                            "type": "Image",
                            "url": "https://example.com/icon.png",
                            "size": "Small"
                        }
                    ]
                },
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": "Multi-column layout",
                            "wrap": True
                        }
                    ]
                }
            ]
        }
    ],
    "actions": [
        {
            "type": "Action.Submit",
            "title": "Submit",
            "data": {"action": "submit"}
        }
    ]
}

# Send the custom card
await toolkit.send_message_to_channel(
    team_id="team-id",
    channel_id="channel-id",
    message=custom_card
)
```

## Available Methods (Tools)

When using the toolkit with an AI agent, all of these methods become available as tools:

### `send_message_to_channel`
Send a message or Adaptive Card to a public Teams channel.

**Parameters:**
- `team_id` (str): The Team ID where the channel exists
- `channel_id` (str): The Channel ID to post the message to
- `message` (str | Dict): Message content (text, Adaptive Card JSON, or dict)

### `send_message_to_chat`
Send a message or Adaptive Card to a private chat.

**Parameters:**
- `chat_id` (str): The Chat ID to send the message to
- `message` (str | Dict): Message content

### `send_direct_message`
Send a direct message or Adaptive Card to a user by email.

**Parameters:**
- `recipient_email` (str): Email address of the recipient
- `message` (str | Dict): Message content

### `create_adaptive_card`
Create a basic Adaptive Card with common elements.

**Parameters:**
- `title` (str): Card title
- `body_text` (str): Main body text
- `image_url` (str, optional): Image URL to include
- `link_url` (str, optional): URL for action button
- `link_text` (str, optional): Text for action button
- `facts` (List[Dict], optional): List of facts with 'title' and 'value'

### `get_user`
Get user information by email address.

**Parameters:**
- `email` (str): Email address of the user

### `create_one_on_one_chat`
Create a new one-on-one chat with a user.

**Parameters:**
- `recipient_email` (str): Email address of the user

## Error Handling

```python
try:
    await toolkit.connect()
except RuntimeError as e:
    print(f"Connection failed: {e}")

try:
    result = await toolkit.send_message_to_channel(
        team_id="invalid-id",
        channel_id="invalid-id",
        message="Test"
    )
except Exception as e:
    print(f"Failed to send message: {e}")
```

## Best Practices

1. **Always call `connect()` before using toolkit methods**:
   ```python
   await toolkit.connect()
   ```

2. **Use application authentication for automated processes**:
   - More secure and doesn't require user credentials
   - Better for production environments

3. **Use delegated authentication for user-specific actions**:
   - Required for creating chats
   - Provides user context in messages

4. **Reuse toolkit instances**:
   - Create one toolkit instance and reuse it
   - Avoid creating multiple instances with the same credentials

5. **Handle errors appropriately**:
   - Check for authentication failures
   - Validate team/channel/chat IDs before sending
   - Handle network errors gracefully

6. **Clean up resources**:
   ```python
   await toolkit.close()
   ```

## Integration with AI-Parrot

### Tool Manager Integration

```python
from parrot.tools.manager import ToolManager

# Create and register the toolkit
toolkit = MSTeamsToolkit(
    tenant_id="your-tenant-id",
    client_id="your-client-id",
    client_secret="your-client-secret"
)
await toolkit.connect()

# Register with tool manager
tool_manager = ToolManager()
tool_manager.register_toolkit(toolkit, prefix="teams_")

# Now all tools are available with 'teams_' prefix
```

### Agent Registry Integration

```python
from parrot.agents.registry import AgentRegistry
from parrot.bots.agent import BasicAgent

registry = AgentRegistry()

@registry.register(
    name="teams_communicator",
    role="Teams Communication Manager"
)
async def create_teams_agent():
    toolkit = MSTeamsToolkit(
        tenant_id="your-tenant-id",
        client_id="your-client-id",
        client_secret="your-client-secret"
    )
    await toolkit.connect()

    return BasicAgent(
        name="TeamsAgent",
        tools=toolkit.get_tools()
    )
```

## Troubleshooting

### Authentication Issues

**Problem**: `Authentication failed: invalid_client`
- **Solution**: Verify your client_id and client_secret are correct
- Check that the app registration is not expired

**Problem**: `Authentication failed: AADSTS70011: Invalid scope`
- **Solution**: Ensure you've configured the correct API permissions in Azure AD
- Grant admin consent for the permissions

### Message Sending Issues

**Problem**: `Team/Channel not found`
- **Solution**: Verify the team_id and channel_id are correct
- Ensure your app has access to the team/channel

**Problem**: `Forbidden: The application does not have permission`
- **Solution**: Add the required permissions in Azure AD
- Grant admin consent

### Chat Creation Issues

**Problem**: `Creating chats requires delegated user authentication`
- **Solution**: Use `as_user=True` when initializing the toolkit
- Provide valid username and password

## Resources

- [Microsoft Graph API Documentation](https://docs.microsoft.com/en-us/graph/api/overview)
- [Adaptive Cards Documentation](https://adaptivecards.io/)
- [Azure AD App Registration Guide](https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
- [Teams Channel Messages API](https://docs.microsoft.com/en-us/graph/api/channel-post-messages)
- [Teams Chat Messages API](https://docs.microsoft.com/en-us/graph/api/chat-post-messages)

## License

This toolkit is part of the AI-Parrot project.
