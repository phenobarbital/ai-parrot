"""
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
"""
import contextlib
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timezone, timedelta
import json
import uuid
import msal
from pydantic import BaseModel, Field
import aiohttp
from azure.identity.aio import ClientSecretCredential
from azure.identity import UsernamePasswordCredential
from msgraph import GraphServiceClient
from msgraph.generated.models.chat import Chat
from msgraph.generated.models.chat_type import ChatType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_collection_response import ChatMessageCollectionResponse
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message_attachment import ChatMessageAttachment
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.generated.chats.chats_request_builder import ChatsRequestBuilder
from msgraph.generated.chats.item.messages.messages_request_builder import MessagesRequestBuilder
from msgraph.generated.teams.teams_request_builder import TeamsRequestBuilder
from msgraph.generated.teams.item.channels.channels_request_builder import ChannelsRequestBuilder
from kiota_abstractions.base_request_configuration import RequestConfiguration
try:
    from navconfig import config as nav_config
    from navconfig.logging import logging
except ImportError:
    import logging
    nav_config = None

from .toolkit import AbstractToolkit
from .decorators import tool_schema
from ..conf import (
    MS_TEAMS_TENANT_ID,
    MS_TEAMS_CLIENT_ID,
    MS_TEAMS_CLIENT_SECRET,
    MS_TEAMS_USERNAME,
    MS_TEAMS_PASSWORD,
    MS_TEAMS_DEFAULT_TEAMS_ID,
    MS_TEAMS_DEFAULT_CHANNEL_ID
)

# Disable verbose logging for external libraries
logging.getLogger('msal').setLevel(logging.INFO)
logging.getLogger('httpcore').setLevel(logging.INFO)
logging.getLogger('azure').setLevel(logging.WARNING)
logging.getLogger('hpack').setLevel(logging.INFO)
logging.getLogger('aiohttp').setLevel(logging.INFO)


# ============================================================================
# Input Schemas
# ============================================================================

class SendMessageToChannelInput(BaseModel):
    """Input schema for sending message to a Teams channel."""
    team_id: str = Field(description="The Team ID where the channel exists")
    channel_id: str = Field(description="The Channel ID to post the message to")
    webhook_url: Optional[str] = Field(
        default=None,
        description="Incoming webhook URL for the channel (alternative to team_id/channel_id)"
    )
    message: Union[str, Dict[str, Any]] = Field(
        description="Message content: plain text, Adaptive Card JSON string, or dict"
    )


class SendMessageToChatInput(BaseModel):
    """Input schema for sending message to a Teams chat."""
    chat_id: str = Field(description="The Chat ID to send the message to")
    message: Union[str, Dict[str, Any]] = Field(
        description="Message content: plain text, Adaptive Card JSON string, or dict"
    )


class SendDirectMessageInput(BaseModel):
    """Input schema for sending direct message to a user."""
    recipient_email: str = Field(
        description="Email address of the recipient user"
    )
    message: Union[str, Dict[str, Any]] = Field(
        description="Message content: plain text, Adaptive Card JSON string, or dict"
    )


class CreateAdaptiveCardInput(BaseModel):
    """Input schema for creating an Adaptive Card."""
    title: str = Field(description="Card title")
    body_text: str = Field(description="Main body text of the card")
    image_url: Optional[str] = Field(
        default=None,
        description="Optional image URL to include in the card"
    )
    link_url: Optional[str] = Field(
        default=None,
        description="Optional link URL"
    )
    link_text: Optional[str] = Field(
        default="Learn more",
        description="Text for the link button"
    )
    facts: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Optional list of facts, each with 'title' and 'value' keys"
    )


class GetUserInput(BaseModel):
    """Input schema for getting user information."""
    email: str = Field(description="Email address of the user to look up")


class CreateChatInput(BaseModel):
    """Input schema for creating a one-on-one chat."""
    recipient_email: str = Field(
        description="Email address of the user to create chat with"
    )

class FindTeamByNameInput(BaseModel):
    """Input schema for finding a team by name."""
    team_name: str = Field(description="Name of the team to search for")


class FindChannelByNameInput(BaseModel):
    """Input schema for finding a channel by name within a team."""
    team_id: str = Field(description="The Team ID to search in")
    channel_name: str = Field(description="Name of the channel to search for")


class GetChannelDetailsInput(BaseModel):
    """Input schema for getting channel details."""
    team_id: str = Field(description="The Team ID")
    channel_id: str = Field(description="The Channel ID")


class GetChannelMembersInput(BaseModel):
    """Input schema for getting channel members."""
    team_id: str = Field(description="The Team ID")
    channel_id: str = Field(description="The Channel ID")


class ExtractChannelMessagesInput(BaseModel):
    """Input schema for extracting channel messages."""
    team_id: str = Field(description="The Team ID")
    channel_id: str = Field(description="The Channel ID")
    start_time: Optional[str] = Field(
        default=None,
        description="Start time for message filter (ISO format, e.g., '2025-01-01T00:00:00Z')"
    )
    end_time: Optional[str] = Field(
        default=None,
        description="End time for message filter (ISO format, e.g., '2025-01-31T23:59:59Z')"
    )
    max_messages: Optional[int] = Field(
        default=None,
        description="Maximum number of messages to retrieve"
    )


class ListUserChatsInput(BaseModel):
    """Input schema for listing user chats."""
    max_chats: Optional[int] = Field(
        default=50,
        description="Maximum number of chats to retrieve"
    )


class FindChatByNameInput(BaseModel):
    """Input schema for finding a chat by name/topic."""
    chat_name: str = Field(description="Name or topic of the chat to search for")


class FindOneOnOneChatInput(BaseModel):
    """Input schema for finding a one-on-one chat between two users."""
    user1_email: str = Field(description="Email of the first user")
    user2_email: str = Field(description="Email of the second user")


class GetChatMessagesInput(BaseModel):
    """Input schema for getting messages from a chat."""
    chat_id: str = Field(description="The Chat ID")
    start_time: Optional[str] = Field(
        default=None,
        description="Start time for message filter (ISO format)"
    )
    end_time: Optional[str] = Field(
        default=None,
        description="End time for message filter (ISO format)"
    )
    max_messages: Optional[int] = Field(
        default=50,
        description="Maximum number of messages to retrieve"
    )


class ChatMessagesFromUserInput(BaseModel):
    """Input schema for extracting messages from a specific user in a chat."""
    chat_id: str = Field(description="The Chat ID")
    user_email: str = Field(description="Email of the user whose messages to extract")
    start_time: Optional[str] = Field(
        default=None,
        description="Start time for message filter (ISO format)"
    )
    end_time: Optional[str] = Field(
        default=None,
        description="End time for message filter (ISO format)"
    )
    max_messages: Optional[int] = Field(
        default=50,
        description="Maximum number of messages to retrieve"
    )


class MSTeamsToolkit(AbstractToolkit):
    """
    Toolkit for interacting with Microsoft Teams via Microsoft Graph API.

    Provides methods for:
    - Sending messages to channels
    - Sending messages to chats
    - Sending direct messages to users
    - Creating adaptive cards
    - Managing chats and users
    - Finding teams and channels by name
    - Extracting messages from channels and chats
    All public async methods are exposed as tools via AbstractToolkit.
    """

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        as_user: bool = False,
        username: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize the MS Teams toolkit.

        Args:
            tenant_id: Azure AD tenant ID
            client_id: Azure AD application client ID
            client_secret: Azure AD application client secret (for app-only auth)
            as_user: If True, use delegated user permissions instead of application
            username: Username for delegated auth (required if as_user=True)
            password: Password for delegated auth (required if as_user=True)
            **kwargs: Additional toolkit arguments
        """
        super().__init__(**kwargs)

        # Load from config if not provided
        if nav_config:
            self.tenant_id = tenant_id or MS_TEAMS_TENANT_ID or nav_config.get('MS_TEAMS_TENANT_ID')
            self.client_id = client_id or MS_TEAMS_CLIENT_ID or nav_config.get('MS_TEAMS_CLIENT_ID')
            self.client_secret = client_secret or MS_TEAMS_CLIENT_SECRET or nav_config.get('MS_TEAMS_CLIENT_SECRET')  # noqa
            self.username = username or MS_TEAMS_USERNAME or nav_config.get('O365_USER')
            self.password = password or MS_TEAMS_PASSWORD or nav_config.get('O365_PASSWORD')
        else:
            self.tenant_id = tenant_id
            self.client_id = client_id
            self.client_secret = client_secret
            self.username = username
            self.password = password

        if not all([self.tenant_id, self.client_id]):
            raise ValueError(
                "tenant_id and client_id are required. "
                "Provide them as arguments or set MS_TEAMS_TENANT_ID and MS_TEAMS_CLIENT_ID in config."
            )

        self.as_user = as_user

        if self.as_user and not all([self.username, self.password]):
            raise ValueError(
                "username and password are required when as_user=True. "
                "Provide them as arguments or set O365_USER and O365_PASSWORD in config."
            )

        if not self.as_user and not self.client_secret:
            raise ValueError(
                "client_secret is required for application auth. "
                "Provide it as argument or set MS_TEAMS_CLIENT_SECRET in config."
            )

        # These will be set during connect()
        self._client = None
        self._graph: Optional[GraphServiceClient] = None
        self._token = None
        self._owner_id = None
        self._connected = False

    async def _connect(self):
        """
        Establish connection to Microsoft Graph API.

        This method must be called before using any toolkit methods.
        """
        if self._connected:
            return

        scopes = ["https://graph.microsoft.com/.default"]
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"

        try:
            if self.as_user:
                # Delegated user authentication
                app = msal.PublicClientApplication(
                    self.client_id,
                    authority=authority
                )
                result = app.acquire_token_by_username_password(
                    username=self.username,
                    password=self.password,
                    scopes=scopes
                )
                self._client = UsernamePasswordCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id,
                    username=self.username,
                    password=self.password
                )
            else:
                # Application authentication
                app = msal.ConfidentialClientApplication(
                    self.client_id,
                    authority=authority,
                    client_credential=self.client_secret
                )
                result = app.acquire_token_for_client(scopes=scopes)
                self._client = ClientSecretCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )

            # Extract token
            if "access_token" not in result:
                error = result.get("error", "Unknown error")
                desc = result.get("error_description", "No description")
                raise RuntimeError(f"Authentication failed: {error} - {desc}")

            self._token = result["access_token"]

            # Create Graph client
            self._graph = GraphServiceClient(
                credentials=self._client,
                scopes=scopes
            )

            # Get owner ID if using delegated auth
            if self.as_user:
                me = await self._graph.me.get()
                self._owner_id = me.id

            self._connected = True
            logging.info("Successfully connected to Microsoft Teams")

        except Exception as e:
            raise RuntimeError(f"Failed to connect to Microsoft Teams: {e}") from e

    async def _ensure_connected(self):
        """Ensure the toolkit is connected before operations."""
        if not self._connected:
            await self._connect()

    @tool_schema(SendMessageToChannelInput)
    async def send_message_to_channel(
        self,
        team_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        webhook_url: Optional[str] = None,
        message: Union[str, Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a message or Adaptive Card to a public Teams channel.

        Can use either:
        1. Webhook URL (recommended for application permissions) - works without Graph API
        2. Team ID + Channel ID (requires delegated user permissions)

        Args:
            team_id: The Team ID where the channel exists (not needed if webhook_url is provided)
            channel_id: The Channel ID to post the message to (not needed if webhook_url is provided)
            webhook_url: Incoming webhook URL for the channel (alternative to team_id/channel_id)
            message: Message content - can be:
                - Plain text string
                - Adaptive Card JSON string
                - Dict with 'body' and 'attachments' keys

        Returns:
            Dict containing the sent message information

        Note:
            With application permissions, you must use webhook_url.
            With delegated user permissions, you can use either method.
        """
        await self._ensure_connected()

        # Parse and prepare the message
        prepared_message = await self._prepare_message(message)

        if webhook_url:
            return await self._send_via_webhook(webhook_url, prepared_message)

        if not team_id or not channel_id:
            team_id = MS_TEAMS_DEFAULT_TEAMS_ID
            channel_id = MS_TEAMS_DEFAULT_CHANNEL_ID

        # Create the ChatMessage request
        request_body = ChatMessage(
            subject=None,
            body=ItemBody(
                content_type=BodyType.Html,
                content=prepared_message["body"]["content"]
            ),
            attachments=[
                ChatMessageAttachment(
                    id=att.get("id"),
                    content_type=att.get(
                        "contentType",
                        "application/vnd.microsoft.card.adaptive"
                    ),
                    content=att.get("content", ""),
                    content_url=None,
                    name=None,
                    thumbnail_url=None,
                )
                for att in prepared_message.get("attachments", [])
            ]
        )

        # Send the message
        result = await self._graph.teams.by_team_id(
            team_id
        ).channels.by_channel_id(channel_id).messages.post(request_body)

        return {
            "id": result.id,
            "created_datetime": str(result.created_date_time),
            "web_url": result.web_url,
            "success": True
        }

    @tool_schema(SendMessageToChatInput)
    async def send_message_to_chat(
        self,
        chat_id: str,
        message: Union[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Send a message or Adaptive Card to a private chat (one-to-one or group chat).

        Args:
            chat_id: The Chat ID to send the message to
            message: Message content - can be:
                - Plain text string
                - Adaptive Card JSON string
                - Dict with 'body' and 'attachments' keys

        Returns:
            Dict containing the sent message information
        """
        await self._ensure_connected()

        # Parse and prepare the message
        prepared_message = await self._prepare_message(message)

        # Create the ChatMessage request
        request_body = ChatMessage(
            subject=None,
            body=ItemBody(
                content_type=BodyType.Html,
                content=prepared_message["body"]["content"]
            ),
            attachments=[
                ChatMessageAttachment(
                    id=att.get("id"),
                    content_type=att.get(
                        "contentType",
                        "application/vnd.microsoft.card.adaptive"
                    ),
                    content=att.get("content", ""),
                    content_url=None,
                    name=None,
                    thumbnail_url=None,
                )
                for att in prepared_message.get("attachments", [])
            ]
        )

        # Send the message
        result = await self._graph.chats.by_chat_id(chat_id).messages.post(request_body)

        return {
            "id": result.id,
            "created_datetime": str(result.created_date_time),
            "web_url": result.web_url,
            "success": True
        }

    @tool_schema(SendDirectMessageInput)
    async def send_direct_message(
        self,
        recipient_email: str,
        message: Union[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Send a direct message or Adaptive Card to a user identified by email address.

        This method will:
        1. Look up the user by email
        2. Find or create a one-on-one chat with the user
        3. Send the message to that chat

        Args:
            recipient_email: Email address of the recipient user
            message: Message content - can be:
                - Plain text string
                - Adaptive Card JSON string
                - Dict with 'body' and 'attachments' keys

        Returns:
            Dict containing the sent message information
        """
        await self._ensure_connected()

        # Get the recipient user
        user = await self.get_user(recipient_email)
        user_id = user["id"]

        # Find or create chat
        chat_id = await self._find_or_create_chat(user_id)

        # Send the message to the chat
        return await self.send_message_to_chat(chat_id, message)

    @tool_schema(CreateAdaptiveCardInput)
    async def create_adaptive_card(
        self,
        title: str,
        body_text: str,
        image_url: Optional[str] = None,
        link_url: Optional[str] = None,
        link_text: str = "Learn more",
        facts: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Create a basic Adaptive Card that can be used in Teams messages.

        Args:
            title: Card title
            body_text: Main body text of the card
            image_url: Optional image URL to include in the card
            link_url: Optional link URL for a button
            link_text: Text for the link button (default: "Learn more")
            facts: Optional list of facts, each with 'title' and 'value' keys

        Returns:
            Dict representing an Adaptive Card that can be passed to send methods
        """
        # Build the card body
        card_body = [
            {
                "type": "TextBlock",
                "text": title,
                "weight": "Bolder",
                "size": "Large",
                "wrap": True
            },
            {
                "type": "TextBlock",
                "text": body_text,
                "wrap": True,
                "spacing": "Medium"
            }
        ]

        # Add image if provided
        if image_url:
            card_body.append({
                "type": "Image",
                "url": image_url,
                "size": "Large",
                "spacing": "Medium"
            })

        # Add facts if provided
        if facts:
            fact_set = {
                "type": "FactSet",
                "facts": [
                    {"title": f"{fact['title']}:", "value": fact["value"]}
                    for fact in facts
                ],
                "spacing": "Medium"
            }
            card_body.append(fact_set)

        # Build the card
        adaptive_card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": card_body
        }

        # Add actions if link provided
        if link_url:
            adaptive_card["actions"] = [
                {
                    "type": "Action.OpenUrl",
                    "title": link_text,
                    "url": link_url
                }
            ]

        return adaptive_card

    @tool_schema(GetUserInput)
    async def get_user(self, email: str) -> Dict[str, Any]:
        """
        Get user information from Microsoft Graph by email address.

        Args:
            email: Email address of the user to look up

        Returns:
            Dict containing user information (id, displayName, mail, etc.)
        """
        await self._ensure_connected()

        try:
            # Try direct lookup first
            user_info = await self._graph.users.by_user_id(email).get()

            if not user_info:
                # If direct lookup fails, search by mail filter
                users = await self._graph.users.get(
                    request_configuration=RequestConfiguration(
                        query_parameters={
                            "$filter": f"mail eq '{email}'"
                        }
                    )
                )

                if not users.value:
                    raise ValueError(f"No user found with email: {email}")

                user_info = users.value[0]

            return {
                "id": user_info.id,
                "displayName": user_info.display_name,
                "mail": user_info.mail,
                "userPrincipalName": user_info.user_principal_name,
                "jobTitle": user_info.job_title,
                "officeLocation": user_info.office_location
            }

        except Exception as e:
            raise RuntimeError(f"Failed to get user info for {email}: {e}") from e

    @tool_schema(CreateChatInput)
    async def create_one_on_one_chat(self, recipient_email: str) -> Dict[str, Any]:
        """
        Create a new one-on-one chat with a user (or return existing chat ID).

        Args:
            recipient_email: Email address of the user to chat with

        Returns:
            Dict containing chat information
        """
        await self._ensure_connected()

        # Get the recipient user
        user = await self.get_user(recipient_email)
        user_id = user["id"]

        # Find or create chat
        chat_id = await self._find_or_create_chat(user_id)

        # Get chat details
        chat = await self._graph.chats.by_chat_id(chat_id).get()

        return {
            "id": chat.id,
            "chatType": str(chat.chat_type),
            "webUrl": chat.web_url,
            "createdDateTime": str(chat.created_date_time)
        }

    @tool_schema(FindTeamByNameInput)
    async def find_team_by_name(self, team_name: str) -> Optional[Dict[str, Any]]:
        """
        Find a team by its name and return the team information including ID.

        Args:
            team_name: Name of the team to search for

        Returns:
            Dict containing team information (id, displayName, description) or None if not found
        """
        await self._ensure_connected()

        try:
            # Get all teams (joined teams if using delegated permissions)
            teams = await self._graph.teams.get()

            if not teams or not teams.value:
                return None

            # Search for team by name (case-insensitive)
            for team in teams.value:
                if team.display_name and team_name.lower() in team.display_name.lower():
                    return {
                        "id": team.id,
                        "displayName": team.display_name,
                        "description": team.description,
                        "webUrl": team.web_url if hasattr(team, 'web_url') else None
                    }

            return None

        except Exception as e:
            raise RuntimeError(f"Failed to find team '{team_name}': {e}") from e

    @tool_schema(FindChannelByNameInput)
    async def find_channel_by_name(
        self,
        team_id: str,
        channel_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find a channel by name within a specific team.

        Args:
            team_id: The Team ID to search in
            channel_name: Name of the channel to search for

        Returns:
            Dict containing channel information (id, displayName, description) or None if not found
        """
        await self._ensure_connected()

        try:
            # Get all channels in the team
            channels = await self._graph.teams.by_team_id(team_id).channels.get()

            if not channels or not channels.value:
                return None

            # Search for channel by name (case-insensitive)
            for channel in channels.value:
                if channel.display_name and channel_name.lower() in channel.display_name.lower():
                    return {
                        "id": channel.id,
                        "displayName": channel.display_name,
                        "description": channel.description,
                        "webUrl": channel.web_url if hasattr(channel, 'web_url') else None,
                        "membershipType": str(channel.membership_type) if hasattr(channel, 'membership_type') else None
                    }

            return None

        except Exception as e:
            raise RuntimeError(f"Failed to find channel '{channel_name}' in team {team_id}: {e}") from e

    @tool_schema(GetChannelDetailsInput)
    async def get_channel_details(
        self,
        team_id: str,
        channel_id: str
    ) -> Dict[str, Any]:
        """
        Get detailed information about a specific channel.

        Args:
            team_id: The Team ID
            channel_id: The Channel ID

        Returns:
            Dict containing detailed channel information
        """
        await self._ensure_connected()

        try:
            channel = await self._graph.teams.by_team_id(team_id).channels.by_channel_id(channel_id).get()

            return {
                "id": channel.id,
                "displayName": channel.display_name,
                "description": channel.description,
                "email": channel.email if hasattr(channel, 'email') else None,
                "webUrl": channel.web_url if hasattr(channel, 'web_url') else None,
                "membershipType": str(channel.membership_type) if hasattr(channel, 'membership_type') else None,
                "createdDateTime": str(channel.created_date_time) if hasattr(channel, 'created_date_time') else None
            }

        except Exception as e:
            raise RuntimeError(f"Failed to get channel details: {e}") from e

    @tool_schema(GetChannelMembersInput)
    async def get_channel_members(
        self,
        team_id: str,
        channel_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all members of a specific channel.

        Args:
            team_id: The Team ID
            channel_id: The Channel ID

        Returns:
            List of dicts containing member information
        """
        await self._ensure_connected()

        try:
            members = await self._graph.teams.by_team_id(
                team_id
            ).channels.by_channel_id(channel_id).members.get()

            if not members or not members.value:
                return []

            members_list = []
            for member in members.value:
                member_info = {
                    "id": member.id,
                    "displayName": member.display_name if hasattr(member, 'display_name') else None,
                    "email": member.email if hasattr(member, 'email') else None,
                    "roles": member.roles if hasattr(member, 'roles') else [],
                }

                # Get user details if available
                if hasattr(member, 'user_id'):
                    member_info["userId"] = member.user_id

                members_list.append(member_info)

            return members_list

        except Exception as e:
            raise RuntimeError(f"Failed to get channel members: {e}") from e

    @tool_schema(ExtractChannelMessagesInput)
    async def extract_channel_messages(
        self,
        team_id: str,
        channel_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_messages: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract messages from a channel within a time range.

        Args:
            team_id: The Team ID
            channel_id: The Channel ID
            start_time: Start time for message filter (ISO format, e.g., '2025-01-01T00:00:00Z')
            end_time: End time for message filter (ISO format, e.g., '2025-01-31T23:59:59Z')
            max_messages: Maximum number of messages to retrieve

        Returns:
            List of dicts containing message information
        """
        await self._ensure_connected()

        try:
            # Build query parameters
            query_params = {
                "orderby": ["lastModifiedDateTime desc"],
                "top": min(50, max_messages) if max_messages else 50
            }

            # Add time filter if provided
            if start_time and end_time:
                query_params["filter"] = (
                    f"lastModifiedDateTime gt {start_time} and "
                    f"lastModifiedDateTime lt {end_time}"
                )
            elif start_time:
                query_params["filter"] = f"lastModifiedDateTime gt {start_time}"
            elif end_time:
                query_params["filter"] = f"lastModifiedDateTime lt {end_time}"

            # Create request configuration
            request_config = RequestConfiguration(
                query_parameters=query_params
            )

            # Get messages
            messages = []
            response = await self._graph.teams.by_team_id(
                team_id
            ).channels.by_channel_id(channel_id).messages.get(
                request_configuration=request_config
            )

            if response and response.value:
                messages.extend(response.value)

            # Handle pagination
            next_link = response.odata_next_link if response else None
            while next_link and (not max_messages or len(messages) < max_messages):
                response = await self._graph.teams.by_team_id(
                    team_id
                ).channels.by_channel_id(channel_id).messages.with_url(next_link).get()

                if response and response.value:
                    messages.extend(response.value)

                next_link = response.odata_next_link if response else None

            # Trim to max_messages if specified
            if max_messages:
                messages = messages[:max_messages]

            # Convert to dicts
            return self._format_messages(messages)

        except Exception as e:
            raise RuntimeError(f"Failed to extract channel messages: {e}") from e

    @tool_schema(ListUserChatsInput)
    async def list_user_chats(self, max_chats: int = 50) -> List[Dict[str, Any]]:
        """
        List all chats for the current user (requires delegated permissions).

        Args:
            max_chats: Maximum number of chats to retrieve (default: 50)

        Returns:
            List of dicts containing chat information
        """
        await self._ensure_connected()

        if not self.as_user:
            raise RuntimeError(
                "Listing user chats requires delegated user permissions. "
                "Initialize toolkit with as_user=True."
            )

        try:
            # Get chats
            query_params = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters(
                expand=["members"],
                top=min(max_chats, 50)
            )

            request_config = RequestConfiguration(
                query_parameters=query_params
            )

            chats = []
            response = await self._graph.chats.get(request_configuration=request_config)

            if response and response.value:
                chats.extend(response.value)

            # Handle pagination
            next_link = response.odata_next_link if response else None
            while next_link and len(chats) < max_chats:
                response = await self._graph.chats.with_url(next_link).get()

                if response and response.value:
                    chats.extend(response.value)

                next_link = response.odata_next_link if response else None

            # Trim to max_chats
            chats = chats[:max_chats]

            # Format results
            chats_list = []
            for chat in chats:
                chat_info = {
                    "id": chat.id,
                    "topic": chat.topic,
                    "chatType": str(chat.chat_type),
                    "createdDateTime": str(chat.created_date_time) if hasattr(chat, 'created_date_time') else None,
                    "lastUpdatedDateTime": str(chat.last_updated_date_time) if hasattr(chat, 'last_updated_date_time') else None,
                    "webUrl": chat.web_url if hasattr(chat, 'web_url') else None
                }

                # Add member info if available
                if hasattr(chat, 'members') and chat.members:
                    chat_info["members"] = [
                        {
                            "displayName": m.display_name if hasattr(m, 'display_name') else None,
                            "userId": m.user_id if hasattr(m, 'user_id') else None
                        }
                        for m in chat.members
                    ]

                chats_list.append(chat_info)

            return chats_list

        except Exception as e:
            raise RuntimeError(f"Failed to list user chats: {e}") from e

    @tool_schema(FindChatByNameInput)
    async def find_chat_by_name(self, chat_name: str) -> Optional[Dict[str, Any]]:
        """
        Find a chat by its name/topic (requires delegated permissions).

        Args:
            chat_name: Name or topic of the chat to search for

        Returns:
            Dict containing chat information or None if not found
        """
        await self._ensure_connected()

        if not self.as_user:
            raise RuntimeError(
                "Finding chats by name requires delegated user permissions. "
                "Initialize toolkit with as_user=True."
            )

        try:
            # Get all chats
            chats = await self.list_user_chats(max_chats=100)

            # Search for chat by name/topic (case-insensitive)
            return next(
                (
                    chat
                    for chat in chats
                    if chat.get("topic")
                    and chat_name.lower() in chat["topic"].lower()
                ),
                None,
            )

        except Exception as e:
            raise RuntimeError(
                f"Failed to find chat '{chat_name}': {e}"
            ) from e

    @tool_schema(FindOneOnOneChatInput)
    async def find_one_on_one_chat(
        self,
        user1_email: str,
        user2_email: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find a one-on-one chat between two users (requires delegated permissions).

        Args:
            user1_email: Email of the first user
            user2_email: Email of the second user

        Returns:
            Dict containing chat information or None if not found
        """
        await self._ensure_connected()

        if not self.as_user:
            raise RuntimeError(
                "Finding one-on-one chats requires delegated user permissions. "
                "Initialize toolkit with as_user=True."
            )

        try:
            # Get user IDs
            user1 = await self.get_user(user1_email)
            user2 = await self.get_user(user2_email)

            user1_id = user1["id"]
            user2_id = user2["id"]

            # Search for existing chat
            query_params = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters(
                filter="chatType eq 'oneOnOne'",
                expand=["members"]
            )

            request_config = RequestConfiguration(
                query_parameters=query_params
            )

            chats = await self._graph.chats.get(request_configuration=request_config)

            if not chats or not chats.value:
                return None

            # Find chat with both users
            for chat in chats.value:
                if not chat.members:
                    continue

                member_ids = {m.user_id for m in chat.members if hasattr(m, 'user_id')}

                if user1_id in member_ids and user2_id in member_ids:
                    return {
                        "id": chat.id,
                        "topic": chat.topic,
                        "chatType": str(chat.chat_type),
                        "webUrl": chat.web_url if hasattr(chat, 'web_url') else None,
                        "createdDateTime": str(chat.created_date_time) if hasattr(chat, 'created_date_time') else None
                    }

            return None

        except Exception as e:
            raise RuntimeError(f"Failed to find one-on-one chat: {e}") from e

    @tool_schema(GetChatMessagesInput)
    async def get_chat_messages(
        self,
        chat_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_messages: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get messages from a specific chat within a time range.

        Args:
            chat_id: The Chat ID
            start_time: Start time for message filter (ISO format)
            end_time: End time for message filter (ISO format)
            max_messages: Maximum number of messages to retrieve (default: 50)

        Returns:
            List of dicts containing message information
        """
        await self._ensure_connected()

        try:
            # Build query parameters
            query_params = {
                "orderby": ["lastModifiedDateTime desc"],
                "top": min(50, max_messages)
            }

            # Add time filter
            if start_time and end_time:
                query_params["filter"] = (
                    f"lastModifiedDateTime gt {start_time} and "
                    f"lastModifiedDateTime lt {end_time}"
                )
            elif start_time:
                query_params["filter"] = f"lastModifiedDateTime gt {start_time}"
            elif end_time:
                query_params["filter"] = f"lastModifiedDateTime lt {end_time}"
            else:
                # Default to last 24 hours if no time specified
                start = (datetime.utcnow() - timedelta(days=1)).isoformat() + 'Z'
                end = datetime.utcnow().isoformat() + 'Z'
                query_params["filter"] = (
                    f"lastModifiedDateTime gt {start} and "
                    f"lastModifiedDateTime lt {end}"
                )

            request_config = RequestConfiguration(
                query_parameters=query_params
            )

            # Get messages
            messages = []
            response = await self._graph.chats.by_chat_id(chat_id).messages.get(
                request_configuration=request_config
            )

            if isinstance(response, ChatMessageCollectionResponse) and response.value:
                messages.extend(response.value)

            # Handle pagination
            next_link = response.odata_next_link if response else None
            while next_link and len(messages) < max_messages:
                response = await self._graph.chats.by_chat_id(chat_id).messages.with_url(next_link).get()

                if response and response.value:
                    messages.extend(response.value)

                next_link = response.odata_next_link if response else None

            # Trim to max_messages
            messages = messages[:max_messages]

            return self._format_messages(messages)

        except Exception as e:
            raise RuntimeError(f"Failed to get chat messages: {e}") from e

    @tool_schema(ChatMessagesFromUserInput)
    async def chat_messages_from_user(
        self,
        chat_id: str,
        user_email: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_messages: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Extract all messages from a specific user in a chat within a time range.

        Args:
            chat_id: The Chat ID
            user_email: Email of the user whose messages to extract
            start_time: Start time for message filter (ISO format)
            end_time: End time for message filter (ISO format)
            max_messages: Maximum number of messages to retrieve (default: 50)

        Returns:
            List of dicts containing message information from the specified user
        """
        await self._ensure_connected()

        try:
            # Get user info
            user = await self.get_user(user_email)
            user_id = user["id"]

            # Get all messages
            all_messages = await self.get_chat_messages(
                chat_id=chat_id,
                start_time=start_time,
                end_time=end_time,
                max_messages=max_messages
            )

            # Filter messages by user
            return [
                msg for msg in all_messages
                if msg.get("from") and msg["from"].get("userId") == user_id
            ]

        except Exception as e:
            raise RuntimeError(f"Failed to get messages from user {user_email}: {e}") from e

    async def _prepare_message(
        self,
        message: Union[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Prepare a message for sending.

        Converts various message formats into the standard format expected by Graph API.
        """
        if isinstance(message, dict):
            # Already in dict format
            if "body" in message and "attachments" in message:
                return message
            elif "type" in message and message["type"] == "AdaptiveCard":
                # It's an Adaptive Card dict
                attachment_id = str(uuid.uuid4())
                return {
                    "body": {
                        "content": f'<attachment id="{attachment_id}"></attachment>'
                    },
                    "attachments": [
                        {
                            "id": attachment_id,
                            "contentType": "application/vnd.microsoft.card.adaptive",
                            "content": json.dumps(message)
                        }
                    ]
                }
            else:
                # Treat as plain message
                return {
                    "body": {"content": str(message)},
                    "attachments": []
                }

        elif isinstance(message, str):
            # Check if it's JSON string containing an Adaptive Card
            with contextlib.suppress(json.JSONDecodeError):
                parsed = json.loads(message)
                if parsed.get("type") == "AdaptiveCard":
                    attachment_id = str(uuid.uuid4())
                    return {
                        "body": {
                            "content": f'<attachment id="{attachment_id}"></attachment>'
                        },
                        "attachments": [
                            {
                                "id": attachment_id,
                                "contentType": "application/vnd.microsoft.card.adaptive",
                                "content": message  # Keep as JSON string
                            }
                        ]
                    }

            # Plain text message
            return {
                "body": {"content": message},
                "attachments": []
            }

        else:
            raise ValueError(f"Unsupported message type: {type(message)}")

    async def _find_or_create_chat(self, user_id: str) -> str:
        """
        Find an existing one-on-one chat with a user or create a new one.

        Args:
            user_id: The user ID to find/create chat with

        Returns:
            Chat ID
        """
        # Try to find existing chat
        existing_chat_id = await self._find_existing_chat(user_id)

        if existing_chat_id:
            return existing_chat_id

        # Create new chat
        if not self.as_user or not self._owner_id:
            raise RuntimeError(
                "Creating chats requires delegated user authentication (as_user=True)"
            )

        return await self._create_new_chat(self._owner_id, user_id)

    async def _find_existing_chat(self, user_id: str) -> Optional[str]:
        """Find an existing one-on-one chat with a user."""
        query_params = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters(
            filter="chatType eq 'oneOnOne'",
            expand=["members"]
        )

        request_configuration = RequestConfiguration(
            query_parameters=query_params
        )

        chats = await self._graph.chats.get(
            request_configuration=request_configuration
        )

        if not chats.value:
            return None

        for chat in chats.value:
            if not chat.members:
                continue
            member_ids = [m.user_id for m in chat.members]
            if user_id in member_ids:
                return chat.id

        return None

    async def _create_new_chat(self, owner_id: str, user_id: str) -> str:
        """Create a new one-on-one chat."""
        request_body = Chat(
            chat_type=ChatType.OneOnOne,
            members=[
                AadUserConversationMember(
                    odata_type="#microsoft.graph.aadUserConversationMember",
                    roles=["owner"],
                    additional_data={
                        "user@odata.bind": f"https://graph.microsoft.com/beta/users('{owner_id}')"
                    }
                ),
                AadUserConversationMember(
                    odata_type="#microsoft.graph.aadUserConversationMember",
                    roles=["owner"],
                    additional_data={
                        "user@odata.bind": f"https://graph.microsoft.com/beta/users('{user_id}')"
                    }
                )
            ]
        )

        result = await self._graph.chats.post(request_body)
        return result.id

    async def _send_via_webhook(
        self,
        webhook_url: str,
        message: Union[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Send a message via Teams incoming webhook.

        This method works with application permissions and doesn't require Graph API.

        Args:
            webhook_url: The incoming webhook URL for the channel
            message: Message content (text, dict, or adaptive card)

        Returns:
            Dict with success status
        """
        # Prepare webhook payload
        if isinstance(message, dict):
            if "type" in message and message["type"] == "AdaptiveCard":
                # It's an Adaptive Card
                payload = {
                    "type": "message",
                    "attachments": [
                        {
                            "contentType": "application/vnd.microsoft.card.adaptive",
                            "content": message
                        }
                    ]
                }
            elif "@type" in message:
                # Already a webhook message card
                payload = message
            else:
                # Plain dict with text
                payload = {
                    "@type": "MessageCard",
                    "@context": "http://schema.org/extensions",
                    "text": json.dumps(message)
                }
        elif isinstance(message, str):
            # Check if it's JSON
            try:
                parsed = json.loads(message)
                if parsed.get("type") == "AdaptiveCard":
                    payload = {
                        "type": "message",
                        "attachments": [
                            {
                                "contentType": "application/vnd.microsoft.card.adaptive",
                                "content": parsed
                            }
                        ]
                    }
                else:
                    # Plain text
                    payload = {
                        "@type": "MessageCard",
                        "@context": "http://schema.org/extensions",
                        "text": message
                    }
            except json.JSONDecodeError:
                # Plain text
                payload = {
                    "@type": "MessageCard",
                    "@context": "http://schema.org/extensions",
                    "text": message
                }
        else:
            raise ValueError(f"Unsupported message type: {type(message)}")

        # Send via webhook
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status not in [200, 201]:
                    error_text = await response.text()
                    raise RuntimeError(
                        f"Webhook request failed with status {response.status}: {error_text}"
                    )

                return {
                    "success": True,
                    "status": response.status,
                    "method": "webhook"
                }

    def _format_messages(self, messages: List) -> List[Dict[str, Any]]:
        """
        Format ChatMessage objects into dictionaries.

        Args:
            messages: List of ChatMessage objects

        Returns:
            List of dictionaries with formatted message data
        """
        formatted = []

        for msg in messages:
            if not isinstance(msg, ChatMessage):
                continue

            message_dict = {
                "id": msg.id,
                "messageType": str(msg.message_type) if hasattr(msg, 'message_type') else None,
                "createdDateTime": str(msg.created_date_time) if hasattr(msg, 'created_date_time') else None,
                "lastModifiedDateTime": str(msg.last_modified_date_time) if hasattr(msg, 'last_modified_date_time') else None,
                "subject": msg.subject if hasattr(msg, 'subject') else None,
                "importance": str(msg.importance) if hasattr(msg, 'importance') else None,
                "webUrl": msg.web_url if hasattr(msg, 'web_url') else None
            }

            # Add body content
            if hasattr(msg, 'body') and msg.body:
                message_dict["body"] = {
                    "contentType": str(msg.body.content_type) if hasattr(msg.body, 'content_type') else None,
                    "content": msg.body.content if hasattr(msg.body, 'content') else None
                }

            # Add sender information
            if hasattr(msg, 'from_') and msg.from_:
                from_info = {}
                if hasattr(msg.from_, 'user') and msg.from_.user:
                    from_info["userId"] = msg.from_.user.id if hasattr(msg.from_.user, 'id') else None
                    from_info["displayName"] = msg.from_.user.display_name if hasattr(msg.from_.user, 'display_name') else None
                message_dict["from"] = from_info

            # Add attachments if any
            if hasattr(msg, 'attachments') and msg.attachments:
                message_dict["attachments"] = [
                    {
                        "id": att.id if hasattr(att, 'id') else None,
                        "contentType": att.content_type if hasattr(att, 'content_type') else None,
                        "name": att.name if hasattr(att, 'name') else None,
                        "contentUrl": att.content_url if hasattr(att, 'content_url') else None
                    }
                    for att in msg.attachments
                ]

            # Add reactions if any
            if hasattr(msg, 'reactions') and msg.reactions:
                message_dict["reactions"] = [
                    {
                        "reactionType": r.reaction_type if hasattr(r, 'reaction_type') else None,
                        "createdDateTime": str(r.created_date_time) if hasattr(r, 'created_date_time') else None
                    }
                    for r in msg.reactions
                ]

            formatted.append(message_dict)

        return formatted

    def __del__(self):
        """Cleanup resources."""
        self._client = None
        self._graph = None
        self._token = None
        self._connected = False

# ============================================================================
# Helper function for easy initialization
# ============================================================================

def create_msteams_toolkit(
    tenant_id: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    as_user: bool = False,
    username: Optional[str] = None,
    password: Optional[str] = None,
    **kwargs
) -> MSTeamsToolkit:
    """
    Create and return a configured MSTeamsToolkit instance.

    Args:
        tenant_id: Azure AD tenant ID
        client_id: Azure AD application client ID
        client_secret: Azure AD application client secret
        as_user: If True, use delegated user permissions
        username: Username for delegated auth
        password: Password for delegated auth
        **kwargs: Additional toolkit arguments

    Returns:
        Configured MSTeamsToolkit instance
    """
    return MSTeamsToolkit(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        as_user=as_user,
        username=username,
        password=password,
        **kwargs
    )
