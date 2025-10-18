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
import json
import uuid
import msal
from pydantic import BaseModel, Field
from azure.identity.aio import ClientSecretCredential
from azure.identity import UsernamePasswordCredential
from msgraph import GraphServiceClient
from msgraph.generated.models.chat import Chat
from msgraph.generated.models.chat_type import ChatType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message_attachment import ChatMessageAttachment
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.chats.chats_request_builder import ChatsRequestBuilder
from kiota_abstractions.base_request_configuration import RequestConfiguration

try:
    from navconfig import config as nav_config
    from navconfig.logging import logging
except ImportError:
    import logging
    nav_config = None

from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema


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


class MSTeamsToolkit(AbstractToolkit):
    """
    Toolkit for interacting with Microsoft Teams via Microsoft Graph API.

    Provides methods for:
    - Sending messages to channels
    - Sending messages to chats
    - Sending direct messages to users
    - Creating adaptive cards
    - Managing chats and users
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
            self.tenant_id = tenant_id or nav_config.get('MS_TEAMS_TENANT_ID')
            self.client_id = client_id or nav_config.get('MS_TEAMS_CLIENT_ID')
            self.client_secret = client_secret or nav_config.get('MS_TEAMS_CLIENT_SECRET')
            self.username = username or nav_config.get('O365_USER')
            self.password = password or nav_config.get('O365_PASSWORD')
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
        team_id: str,
        channel_id: str,
        message: Union[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Send a message or Adaptive Card to a public Teams channel.

        Args:
            team_id: The Team ID where the channel exists
            channel_id: The Channel ID to post the message to
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
