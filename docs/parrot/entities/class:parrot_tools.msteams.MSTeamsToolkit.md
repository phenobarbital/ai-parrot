---
type: Wiki Entity
title: MSTeamsToolkit
id: class:parrot_tools.msteams.MSTeamsToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for interacting with Microsoft Teams via Microsoft Graph API.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# MSTeamsToolkit

Defined in [`parrot_tools.msteams`](../summaries/mod:parrot_tools.msteams.md).

```python
class MSTeamsToolkit(AbstractToolkit)
```

Toolkit for interacting with Microsoft Teams via Microsoft Graph API.

Provides methods for:
- Sending messages to channels
- Sending messages to chats
- Sending direct messages to users
- Creating adaptive cards
- Managing chats and users
- Finding teams and channels by name
- Extracting messages from channels and chats
- Getting online meeting IDs from calendar events
- Listing and downloading meeting transcripts
All public async methods are exposed as tools via AbstractToolkit.

## Methods

- `async def send_message_to_channel(self, team_id: Optional[str]=None, channel_id: Optional[str]=None, webhook_url: Optional[str]=None, message: Union[str, Dict[str, Any]]=None) -> Dict[str, Any]` — Send a message or Adaptive Card to a public Teams channel.
- `async def send_message_to_chat(self, chat_id: str, message: Union[str, Dict[str, Any]]) -> Dict[str, Any]` — Send a message or Adaptive Card to a private chat (one-to-one or group chat).
- `async def send_direct_message(self, recipient_email: str, message: Union[str, Dict[str, Any]]) -> Dict[str, Any]` — Send a direct message or Adaptive Card to a user identified by email address.
- `async def create_adaptive_card(self, title: str, body_text: str, image_url: Optional[str]=None, link_url: Optional[str]=None, link_text: str='Learn more', facts: Optional[List[Dict[str, str]]]=None) -> Dict[str, Any]` — Create a basic Adaptive Card that can be used in Teams messages.
- `async def get_user(self, email: str) -> Dict[str, Any]` — Get user information from Microsoft Graph by email address.
- `async def create_one_on_one_chat(self, recipient_email: str) -> Dict[str, Any]` — Create a new one-on-one chat with a user (or return existing chat ID).
- `async def find_team_by_name(self, team_name: str) -> Optional[Dict[str, Any]]` — Find a team by its name and return the team information including ID.
- `async def find_channel_by_name(self, team_id: str, channel_name: str) -> Optional[Dict[str, Any]]` — Find a channel by name within a specific team.
- `async def get_channel_details(self, team_id: str, channel_id: str) -> Dict[str, Any]` — Get detailed information about a specific channel.
- `async def get_channel_members(self, team_id: str, channel_id: str) -> List[Dict[str, Any]]` — Get all members of a specific channel.
- `async def extract_channel_messages(self, team_id: str, channel_id: str, start_time: Optional[str]=None, end_time: Optional[str]=None, max_messages: Optional[int]=None) -> List[Dict[str, Any]]` — Extract messages from a channel within a time range.
- `async def list_user_chats(self, max_chats: int=50) -> List[Dict[str, Any]]` — List all chats for the current user (requires delegated permissions).
- `async def find_chat_by_name(self, chat_name: str) -> Optional[Dict[str, Any]]` — Find a chat by its name/topic (requires delegated permissions).
- `async def find_one_on_one_chat(self, user1_email: str, user2_email: str) -> Optional[Dict[str, Any]]` — Find a one-on-one chat between two users (requires delegated permissions).
- `async def get_chat_messages(self, chat_id: str, start_time: Optional[str]=None, end_time: Optional[str]=None, max_messages: int=50) -> List[Dict[str, Any]]` — Get messages from a specific chat within a time range.
- `async def chat_messages_from_user(self, chat_id: str, user_email: str, start_time: Optional[str]=None, end_time: Optional[str]=None, max_messages: int=50) -> List[Dict[str, Any]]` — Extract all messages from a specific user in a chat within a time range.
- `async def get_online_meeting_id(self, user_id: str, subject: str, start_time: Optional[str]=None, end_time: Optional[str]=None) -> Dict[str, Any]` — Get the online meeting ID from a calendar event by subject.
- `async def list_meeting_transcripts(self, user_id: str, online_meeting_id: str) -> List[Dict[str, Any]]` — List all transcripts for an online meeting.
- `async def get_meeting_transcript(self, user_id: str, online_meeting_id: str, transcript_id: str, format: str='text/vtt') -> Dict[str, Any]` — Download a meeting transcript content.
