---
type: Wiki Summary
title: parrot_tools.msteams
id: mod:parrot_tools.msteams
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MS Teams Toolkit - A unified toolkit for Microsoft Teams operations.
relates_to:
- concept: class:parrot_tools.msteams.ChatMessagesFromUserInput
  rel: defines
- concept: class:parrot_tools.msteams.CreateAdaptiveCardInput
  rel: defines
- concept: class:parrot_tools.msteams.CreateChatInput
  rel: defines
- concept: class:parrot_tools.msteams.ExtractChannelMessagesInput
  rel: defines
- concept: class:parrot_tools.msteams.FindChannelByNameInput
  rel: defines
- concept: class:parrot_tools.msteams.FindChatByNameInput
  rel: defines
- concept: class:parrot_tools.msteams.FindOneOnOneChatInput
  rel: defines
- concept: class:parrot_tools.msteams.FindTeamByNameInput
  rel: defines
- concept: class:parrot_tools.msteams.GetChannelDetailsInput
  rel: defines
- concept: class:parrot_tools.msteams.GetChannelMembersInput
  rel: defines
- concept: class:parrot_tools.msteams.GetChatMessagesInput
  rel: defines
- concept: class:parrot_tools.msteams.GetMeetingTranscriptInput
  rel: defines
- concept: class:parrot_tools.msteams.GetOnlineMeetingIdInput
  rel: defines
- concept: class:parrot_tools.msteams.GetUserInput
  rel: defines
- concept: class:parrot_tools.msteams.ListMeetingTranscriptsInput
  rel: defines
- concept: class:parrot_tools.msteams.ListUserChatsInput
  rel: defines
- concept: class:parrot_tools.msteams.MSTeamsToolkit
  rel: defines
- concept: class:parrot_tools.msteams.SendDirectMessageInput
  rel: defines
- concept: class:parrot_tools.msteams.SendMessageToChannelInput
  rel: defines
- concept: class:parrot_tools.msteams.SendMessageToChatInput
  rel: defines
- concept: func:parrot_tools.msteams.create_msteams_toolkit
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.msteams`

MS Teams Toolkit - A unified toolkit for Microsoft Teams operations.

This toolkit wraps common MS Teams actions as async tools, extending AbstractToolkit.
It supports authentication via Azure AD (service principal or delegated user).

Dependencies:
    - msgraph-sdk
    - azure-identity
    - msal
    - aiohttp
    - pydantic

Example usage:
    toolkit = MSTeamsToolkit(
        tenant_id="your-tenant-id",
        client_id="your-client-id",
        client_secret="your-client-secret",
        as_user=False  # Set to True for delegated auth
    )

    # Initialize the toolkit
    await toolkit.connect()

    # Get all tools
    tools = toolkit.get_tools()

    # Or use methods directly
    await toolkit.send_message_to_channel(
        team_id="team-id",
        channel_id="channel-id",
        message="Hello Teams!"
    )

Notes:
- All public async methods become tools via AbstractToolkit
- Supports both application permissions and delegated user permissions
- Adaptive cards can be sent as strings, dicts, or created via create_adaptive_card

## Classes

- **`SendMessageToChannelInput(BaseModel)`** — Input schema for sending message to a Teams channel.
- **`SendMessageToChatInput(BaseModel)`** — Input schema for sending message to a Teams chat.
- **`SendDirectMessageInput(BaseModel)`** — Input schema for sending direct message to a user.
- **`CreateAdaptiveCardInput(BaseModel)`** — Input schema for creating an Adaptive Card.
- **`GetUserInput(BaseModel)`** — Input schema for getting user information.
- **`CreateChatInput(BaseModel)`** — Input schema for creating a one-on-one chat.
- **`FindTeamByNameInput(BaseModel)`** — Input schema for finding a team by name.
- **`FindChannelByNameInput(BaseModel)`** — Input schema for finding a channel by name within a team.
- **`GetChannelDetailsInput(BaseModel)`** — Input schema for getting channel details.
- **`GetChannelMembersInput(BaseModel)`** — Input schema for getting channel members.
- **`ExtractChannelMessagesInput(BaseModel)`** — Input schema for extracting channel messages.
- **`ListUserChatsInput(BaseModel)`** — Input schema for listing user chats.
- **`FindChatByNameInput(BaseModel)`** — Input schema for finding a chat by name/topic.
- **`FindOneOnOneChatInput(BaseModel)`** — Input schema for finding a one-on-one chat between two users.
- **`GetChatMessagesInput(BaseModel)`** — Input schema for getting messages from a chat.
- **`ChatMessagesFromUserInput(BaseModel)`** — Input schema for extracting messages from a specific user in a chat.
- **`GetOnlineMeetingIdInput(BaseModel)`** — Input schema for getting online meeting ID from a calendar event by subject.
- **`ListMeetingTranscriptsInput(BaseModel)`** — Input schema for listing meeting transcripts.
- **`GetMeetingTranscriptInput(BaseModel)`** — Input schema for downloading a meeting transcript.
- **`MSTeamsToolkit(AbstractToolkit)`** — Toolkit for interacting with Microsoft Teams via Microsoft Graph API.

## Functions

- `def create_msteams_toolkit(tenant_id: Optional[str]=None, client_id: Optional[str]=None, client_secret: Optional[str]=None, as_user: bool=False, username: Optional[str]=None, password: Optional[str]=None, **kwargs) -> MSTeamsToolkit` — Create and return a configured MSTeamsToolkit instance.
