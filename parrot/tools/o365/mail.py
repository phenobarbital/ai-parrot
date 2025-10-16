"""
Office365 Mails Tools.

Specific tools for interacting with Office365 services:
- CreateDraftMessage: Create email drafts
- SearchEmail: Search through emails
- SendEmail: Send emails directly
"""
from typing import Dict, Any, Optional, List, Type
from datetime import datetime
from pathlib import Path
import base64
from pydantic import BaseModel, Field
import aiofiles
from msgraph.generated.models.message import Message
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.importance import Importance
from msgraph.generated.users.item.mail_folders.item.messages.messages_request_builder import (
    MessagesRequestBuilder
)
from msgraph.generated.users.item.send_mail.send_mail_post_request_body import (
    SendMailPostRequestBody
)
from kiota_abstractions.base_request_configuration import RequestConfiguration

from .base import O365Tool, O365ToolArgsSchema, O365Client


# ============================================================================
# CREATE DRAFT MESSAGE TOOL
# ============================================================================

class CreateDraftMessageArgs(O365ToolArgsSchema):
    """Arguments for creating a draft email message."""
    subject: str = Field(
        description="Email subject line"
    )
    body: str = Field(
        description="Email body content (can be HTML or plain text)"
    )
    to_recipients: List[str] = Field(
        description="List of recipient email addresses"
    )
    cc_recipients: Optional[List[str]] = Field(
        default=None,
        description="List of CC recipient email addresses"
    )
    bcc_recipients: Optional[List[str]] = Field(
        default=None,
        description="List of BCC recipient email addresses"
    )
    importance: Optional[str] = Field(
        default="normal",
        description="Email importance: 'low', 'normal', or 'high'"
    )
    is_html: bool = Field(
        default=False,
        description="Whether the body is HTML (True) or plain text (False)"
    )

class CreateDraftMessageTool(O365Tool):
    """
    Tool for creating draft email messages in Office365.

    This tool creates a draft email message that can be reviewed and sent later.
    The draft is saved in the user's Drafts folder.

    Examples:
        # Create a simple draft
        result = await tool.run(
            subject="Project Update",
            body="Here's the latest update on the project...",
            to_recipients=["colleague@company.com"]
        )

        # Create an HTML draft with CC
        result = await tool.run(
            subject="Monthly Report",
            body="<h1>Report</h1><p>Details here...</p>",
            to_recipients=["boss@company.com"],
            cc_recipients=["team@company.com"],
            importance="high",
            is_html=True
        )
    """

    name: str = "create_draft_message"
    description: str = (
        "Create a draft email message in Office365. "
        "The draft is saved in the Drafts folder and can be sent later."
    )
    args_schema: Type[BaseModel] = CreateDraftMessageArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a draft email using Microsoft Graph API.

        Args:
            client: Authenticated O365Client
            **kwargs: Draft parameters

        Returns:
            Dict with draft details
        """
        # Extract parameters
        subject = kwargs.get('subject')
        body_content = kwargs.get('body')
        to_recipients = kwargs.get('to_recipients', [])
        cc_recipients = kwargs.get('cc_recipients')
        bcc_recipients = kwargs.get('bcc_recipients')
        importance_str = kwargs.get('importance', 'normal')
        is_html = kwargs.get('is_html', False)
        user_id = kwargs.get('user_id')

        try:
            # Get user context
            mailbox = client.get_user_context(user_id=user_id)

            # Build message object
            message = Message()
            message.subject = subject

            # Set body
            message.body = ItemBody()
            message.body.content = body_content
            message.body.content_type = BodyType.Html if is_html else BodyType.Text

            # Helper function to create recipient
            def create_recipient(email: str) -> Recipient:
                recipient = Recipient()
                recipient.email_address = EmailAddress()
                recipient.email_address.address = email
                return recipient

            # Set recipients
            message.to_recipients = [create_recipient(email) for email in to_recipients]

            if cc_recipients:
                message.cc_recipients = [create_recipient(email) for email in cc_recipients]

            if bcc_recipients:
                message.bcc_recipients = [create_recipient(email) for email in bcc_recipients]

            # Set importance
            importance_map = {
                'low': Importance.Low,
                'normal': Importance.Normal,
                'high': Importance.High
            }
            message.importance = importance_map.get(importance_str.lower(), Importance.Normal)

            # Create the draft
            self.logger.info(f"Creating draft message: {subject}")
            draft = await mailbox.messages.post(message)

            self.logger.info(f"Created draft with ID: {draft.id}")

            return {
                "status": "created",
                "id": draft.id,
                "subject": draft.subject,
                "to_recipients": to_recipients,
                "cc_recipients": cc_recipients or [],
                "bcc_recipients": bcc_recipients or [],
                "importance": importance_str,
                "is_html": is_html,
                "web_link": draft.web_link,
                "created_datetime": draft.created_date_time.isoformat() if draft.created_date_time else None
            }

        except Exception as e:
            self.logger.error(f"Failed to create draft message: {e}", exc_info=True)
            raise

# ============================================================================
# SEARCH EMAIL TOOL
# ============================================================================

class SearchEmailArgs(O365ToolArgsSchema):
    """Arguments for searching emails."""
    query: str = Field(
        description="Search query string (supports keywords, from:, to:, subject:, etc.)"
    )
    folder: Optional[str] = Field(
        default="inbox",
        description="Folder to search in: 'inbox', 'sentitems', 'drafts', 'deleteditems', or folder ID"
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of results to return (1-50)"
    )
    include_attachments: bool = Field(
        default=False,
        description="Whether to include attachment information in results"
    )
    order_by: str = Field(
        default="receivedDateTime desc",
        description=(
            "Sort order (e.g., 'receivedDateTime desc', 'subject asc'). "
            "Note: When using search queries, sorting is done client-side after retrieval."
        )
    )

class SearchEmailTool(O365Tool):
    """
    Tool for searching emails in Office365.

    This tool searches through emails with support for:
    - Advanced search queries
    - Folder-specific searches
    - Sorting and limiting results
    - Attachment information

    Search query examples:
        - "project update" - Keywords in subject or body
        - "from:john@company.com" - Emails from specific sender
        - "subject:invoice" - Search in subject only
        - "hasAttachments:true" - Only emails with attachments
        - "received>=2025-01-01" - Emails received after date

    Examples:
        # Search for recent emails
        result = await tool.run(
            query="project deadline",
            max_results=5
        )

        # Search sent items
        result = await tool.run(
            query="from:me to:client@company.com",
            folder="sentitems",
            max_results=10
        )

        # Search with attachments
        result = await tool.run(
            query="invoice hasAttachments:true",
            include_attachments=True
        )
    """

    name: str = "search_email"
    description: str = (
        "Search through emails in Office365. "
        "Supports advanced queries, folder filtering, and sorting."
    )
    args_schema: Type[BaseModel] = SearchEmailArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Search emails using Microsoft Graph API.

        Args:
            client: Authenticated O365Client
            **kwargs: Search parameters

        Returns:
            Dict with search results
        """
        query = kwargs.get('query')
        folder = kwargs.get('folder', 'inbox')
        max_results = min(kwargs.get('max_results', 10), 50)  # Cap at 50
        include_attachments = kwargs.get('include_attachments', False)
        order_by = kwargs.get('order_by', 'receivedDateTime desc')
        user_id = kwargs.get('user_id')

        try:
            # Build the request
            mailbox = client.get_user_context(user_id=user_id)

            # Select fields to return
            select_fields = [
                'id', 'subject', 'from', 'toRecipients', 'receivedDateTime',
                'bodyPreview', 'isRead', 'hasAttachments', 'importance',
                'conversationId', 'webLink'
            ]

            if include_attachments:
                select_fields.append('attachments')

            # Apply folder filter and get appropriate request builder
            folder_map = {
                'inbox': 'inbox',
                'sentitems': 'sentitems',
                'drafts': 'drafts',
                'deleteditems': 'deleteditems'
            }

            if folder.lower() in folder_map:
                folder_name = folder_map[folder.lower()]
                request_builder = mailbox.mail_folders.by_mail_folder_id(folder_name).messages

            else:
                # Direct messages (inbox shortcut)
                request_builder = mailbox.messages

            query_params_obj = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                top=max_results,
                select=select_fields
            )

            # CRITICAL: Only add orderby if NOT using search
            if not query:
                query_params_obj.orderby = [order_by]

            # Add search filter if query provided
            if query:
                query_params_obj.search = f'"{query}"'
                self.logger.info(f"Using search (orderby disabled): '{query}'")
            else:
                self.logger.info(f"Listing messages with orderby: {order_by}")

            # Wrap in RequestConfiguration
            request_config = RequestConfiguration(
                query_parameters=query_params_obj
            )

            # Execute search
            self.logger.info(f"Searching emails: query='{query}', folder='{folder}'")
            messages = await request_builder.get(request_configuration=request_config)

            # Format results
            results = []
            if messages and messages.value:
                for msg in messages.value:
                    result_item = {
                        "id": msg.id,
                        "subject": msg.subject or "(No subject)",
                        # Fix: Use from_ instead of from_prop
                        "from": msg.from_.email_address.address if msg.from_ and msg.from_.email_address else None,
                        "from_name": msg.from_.email_address.name if msg.from_ and msg.from_.email_address else None,
                        "to": [
                            r.email_address.address
                            for r in (msg.to_recipients or [])
                            if r and r.email_address
                        ],
                        "received_datetime": msg.received_date_time.isoformat() if msg.received_date_time else None,
                        "body_preview": msg.body_preview,
                        "is_read": msg.is_read,
                        "has_attachments": msg.has_attachments,
                        "importance": str(msg.importance) if msg.importance else None,
                        "web_link": msg.web_link
                    }

                    # Add attachment info if requested
                    if include_attachments and msg.has_attachments and hasattr(msg, 'attachments'):
                        result_item["attachments"] = [
                            {
                                "name": att.name,
                                "size": att.size,
                                "content_type": att.content_type
                            }
                            for att in (msg.attachments or [])
                        ]

                    results.append(result_item)

            self.logger.info(f"Found {len(results)} emails matching query: {query}")

            return {
                "query": query,
                "folder": folder,
                "total_results": len(results),
                "messages": results
            }

        except Exception as e:
            self.logger.error(f"Failed to search emails: {e}", exc_info=True)
            raise

# ============================================================================
# SEND EMAIL TOOL
# ============================================================================

class SendEmailArgs(O365ToolArgsSchema):
    """Arguments for sending an email."""
    subject: str = Field(
        description="Email subject line"
    )
    body: str = Field(
        description="Email body content (can be HTML or plain text)"
    )
    to_recipients: List[str] = Field(
        description="List of recipient email addresses"
    )
    cc_recipients: Optional[List[str]] = Field(
        default=None,
        description="List of CC recipient email addresses"
    )
    bcc_recipients: Optional[List[str]] = Field(
        default=None,
        description="List of BCC recipient email addresses"
    )
    importance: Optional[str] = Field(
        default="normal",
        description="Email importance: 'low', 'normal', or 'high'"
    )
    is_html: bool = Field(
        default=False,
        description="Whether the body is HTML (True) or plain text (False)"
    )
    save_to_sent_items: bool = Field(
        default=True,
        description="Whether to save a copy in Sent Items folder"
    )


class SendEmailTool(O365Tool):
    """
    Tool for sending emails directly in Office365.

    This tool sends an email immediately without creating a draft.
    The email is sent and optionally saved to the Sent Items folder.

    Examples:
        # Send a simple email
        result = await tool.run(
            subject="Quick Update",
            body="Just wanted to let you know...",
            to_recipients=["colleague@company.com"]
        )

        # Send HTML email with CC
        result = await tool.run(
            subject="Newsletter",
            body="<h2>This Month's Updates</h2><p>Content here...</p>",
            to_recipients=["subscriber@email.com"],
            cc_recipients=["team@company.com"],
            importance="high",
            is_html=True
        )

        # Send without saving to Sent Items
        result = await tool.run(
            subject="Temporary Message",
            body="This won't be saved in Sent Items",
            to_recipients=["user@company.com"],
            save_to_sent_items=False
        )
    """

    name: str = "send_email"
    description: str = (
        "Send an email directly through Office365. "
        "The email is sent immediately and optionally saved to Sent Items."
    )
    args_schema: Type[BaseModel] = SendEmailArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send an email using Microsoft Graph API.

        Args:
            client: Authenticated O365Client
            **kwargs: Email parameters

        Returns:
            Dict with send confirmation
        """
        # Extract parameters
        subject = kwargs.get('subject')
        body_content = kwargs.get('body')
        to_recipients = kwargs.get('to_recipients', [])
        cc_recipients = kwargs.get('cc_recipients')
        bcc_recipients = kwargs.get('bcc_recipients')
        importance_str = kwargs.get('importance', 'normal')
        is_html = kwargs.get('is_html', False)
        save_to_sent = kwargs.get('save_to_sent_items', True)
        user_id = kwargs.get('user_id')

        try:
            # Get user context
            mailbox = client.get_user_context(user_id=user_id)

            # Build message object
            message = Message()
            message.subject = subject

            # Set body
            message.body = ItemBody()
            message.body.content = body_content
            message.body.content_type = BodyType.Html if is_html else BodyType.Text

            # Helper function to create recipient
            def create_recipient(email: str) -> Recipient:
                recipient = Recipient()
                recipient.email_address = EmailAddress()
                recipient.email_address.address = email
                return recipient

            # Set recipients
            message.to_recipients = [create_recipient(email) for email in to_recipients]

            if cc_recipients:
                message.cc_recipients = [create_recipient(email) for email in cc_recipients]

            if bcc_recipients:
                message.bcc_recipients = [create_recipient(email) for email in bcc_recipients]

            # Set importance
            importance_map = {
                'low': Importance.Low,
                'normal': Importance.Normal,
                'high': Importance.High
            }
            message.importance = importance_map.get(importance_str.lower(), Importance.Normal)

            # Create the request body for send_mail
            request_body = SendMailPostRequestBody()
            request_body.message = message
            request_body.save_to_sent_items = save_to_sent

            # Send the email
            self.logger.info(f"Sending email to {to_recipients}")
            await mailbox.send_mail.post(body=request_body)

            self.logger.info(f"Successfully sent email: {subject}")

            return {
                "status": "sent",
                "subject": subject,
                "to_recipients": to_recipients,
                "cc_recipients": cc_recipients or [],
                "bcc_recipients": bcc_recipients or [],
                "importance": importance_str,
                "is_html": is_html,
                "sent_datetime": datetime.now().isoformat(),
                "saved_to_sent_items": save_to_sent
            }

        except Exception as e:
            self.logger.error(f"Failed to send email: {e}", exc_info=True)
            raise

# ============================================================================
# LIST MESSAGES TOOL
# ============================================================================

class ListMessagesArgs(O365ToolArgsSchema):
    """Arguments for listing email messages."""
    folder: str = Field(
        default="inbox",
        description="Folder to list messages from: 'inbox', 'sentitems', 'drafts', 'deleteditems', or folder ID"
    )
    top: int = Field(
        default=10,
        description="Maximum number of messages to return (1-1000)"
    )
    filter_query: Optional[str] = Field(
        default=None,
        description="OData filter query (e.g., 'isRead eq false', 'hasAttachments eq true')"
    )
    order_by: str = Field(
        default="receivedDateTime desc",
        description="Sort order (e.g., 'receivedDateTime desc', 'subject asc')"
    )
    select_fields: Optional[List[str]] = Field(
        default=None,
        description="Specific fields to retrieve. If None, returns default fields."
    )


class ListMessagesTool(O365Tool):
    """
    Tool for listing email messages from a specified folder.

    This tool allows you to:
    - List messages from any mail folder (Inbox, Sent Items, etc.)
    - Filter messages by various criteria (read status, sender, date, etc.)
    - Limit the number of results
    - Order results by different fields
    - Select specific fields to retrieve

    Filter query examples:
        - "isRead eq false" - Unread messages
        - "hasAttachments eq true" - Messages with attachments
        - "from/emailAddress/address eq 'user@example.com'" - From specific sender
        - "receivedDateTime ge 2025-10-16T00:00:00Z" - Received after date
        - "importance eq 'high'" - High importance messages

    Examples:
        # List recent messages
        result = await tool.run(
            folder="inbox",
            top=20
        )

        # List unread messages
        result = await tool.run(
            folder="inbox",
            filter_query="isRead eq false"
        )

        # List messages from specific sender
        result = await tool.run(
            folder="inbox",
            filter_query="from/emailAddress/address eq 'boss@company.com'",
            top=10
        )
    """

    name: str = "list_messages"
    description: str = (
        "List email messages from a specified folder with optional filtering and sorting. "
        "Supports OData filters for advanced queries."
    )
    args_schema: Type[BaseModel] = ListMessagesArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        List messages using Microsoft Graph API.

        Args:
            client: Authenticated O365Client
            **kwargs: List parameters

        Returns:
            Dict with list of messages
        """
        folder = kwargs.get('folder', 'inbox')
        top = min(kwargs.get('top', 10), 1000)  # Cap at 1000
        filter_query = kwargs.get('filter_query')
        order_by = kwargs.get('order_by', 'receivedDateTime desc')
        select_fields = kwargs.get('select_fields')
        user_id = kwargs.get('user_id')

        try:
            # Get user context
            mailbox = client.get_user_context(user_id=user_id)

            # Default fields to select
            default_fields = [
                'id', 'subject', 'from', 'toRecipients', 'receivedDateTime',
                'sentDateTime', 'hasAttachments', 'importance', 'isRead',
                'bodyPreview', 'internetMessageId', 'webLink'
            ]

            fields = select_fields or default_fields

            # Apply folder filter and get appropriate request builder
            folder_map = {
                'inbox': 'inbox',
                'sentitems': 'sentitems',
                'drafts': 'drafts',
                'deleteditems': 'deleteditems'
            }

            if folder.lower() in folder_map:
                folder_name = folder_map[folder.lower()]
                request_builder = mailbox.mail_folders.by_mail_folder_id(folder_name).messages
            else:
                # Try as direct folder ID or use inbox as fallback
                request_builder = mailbox.messages

            # Build query parameters
            query_params_obj = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                top=top,
                select=fields,
                orderby=[order_by]
            )

            # Add filter if provided
            if filter_query:
                query_params_obj.filter = filter_query

            # Wrap in RequestConfiguration
            request_config = RequestConfiguration(
                query_parameters=query_params_obj
            )

            # Execute request
            self.logger.info(f"Listing messages: folder='{folder}', top={top}, filter='{filter_query}'")
            messages = await request_builder.get(request_configuration=request_config)

            # Format results
            results = []
            if messages and messages.value:
                for msg in messages.value:
                    result_item = {
                        "id": msg.id,
                        "subject": msg.subject or "(No subject)",
                        "from": msg.from_.email_address.address if msg.from_ and msg.from_.email_address else None,
                        "from_name": msg.from_.email_address.name if msg.from_ and msg.from_.email_address else None,
                        "to": [
                            r.email_address.address
                            for r in (msg.to_recipients or [])
                            if r and r.email_address
                        ],
                        "received_datetime": msg.received_date_time.isoformat() if msg.received_date_time else None,
                        "sent_datetime": msg.sent_date_time.isoformat() if msg.sent_date_time else None,
                        "has_attachments": msg.has_attachments,
                        "importance": str(msg.importance) if msg.importance else None,
                        "is_read": msg.is_read,
                        "body_preview": msg.body_preview,
                        "internet_message_id": msg.internet_message_id,
                        "web_link": msg.web_link
                    }
                    results.append(result_item)

            self.logger.info(f"Found {len(results)} messages in folder '{folder}'")

            return {
                "folder": folder,
                "total_results": len(results),
                "messages": results
            }

        except Exception as e:
            self.logger.error(f"Failed to list messages: {e}", exc_info=True)
            raise


# ============================================================================
# GET MESSAGE TOOL
# ============================================================================

class GetMessageArgs(O365ToolArgsSchema):
    """Arguments for retrieving a specific message."""
    message_id: str = Field(
        description="The ID of the message to retrieve"
    )
    include_body: bool = Field(
        default=True,
        description="Whether to include the full message body content"
    )


class GetMessageTool(O365Tool):
    """
    Tool for retrieving a specific email message by its ID.

    This tool retrieves complete information about a single message, including:
    - Full message headers (subject, sender, recipients, dates)
    - Message body content (if include_body=True)
    - Attachment information
    - Message metadata (read status, importance, conversation ID)

    Use this tool when you need detailed information about a specific message,
    such as reading the full content or checking for attachments.

    Examples:
        # Get message with body
        result = await tool.run(
            message_id="AAMkAGI...",
            include_body=True
        )

        # Get message metadata only (faster)
        result = await tool.run(
            message_id="AAMkAGI...",
            include_body=False
        )
    """

    name: str = "get_message"
    description: str = (
        "Retrieve a specific email message by its ID with complete details. "
        "Can include full body content and attachment information."
    )
    args_schema: Type[BaseModel] = GetMessageArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Get a specific message using Microsoft Graph API.

        Args:
            client: Authenticated O365Client
            **kwargs: Get parameters

        Returns:
            Dict with message details
        """
        message_id = kwargs.get('message_id')
        include_body = kwargs.get('include_body', True)
        user_id = kwargs.get('user_id')

        try:
            # Get user context
            mailbox = client.get_user_context(user_id=user_id)

            # Select fields based on whether body is needed
            if include_body:
                select_fields = [
                    'id', 'subject', 'from', 'toRecipients', 'ccRecipients', 'bccRecipients',
                    'receivedDateTime', 'sentDateTime', 'hasAttachments', 'importance', 'isRead',
                    'body', 'bodyPreview', 'internetMessageId', 'conversationId', 'webLink'
                ]
            else:
                select_fields = [
                    'id', 'subject', 'from', 'toRecipients', 'ccRecipients', 'bccRecipients',
                    'receivedDateTime', 'sentDateTime', 'hasAttachments', 'importance', 'isRead',
                    'bodyPreview', 'internetMessageId', 'conversationId', 'webLink'
                ]

            # Build query parameters
            query_params_obj = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                select=select_fields
            )

            request_config = RequestConfiguration(
                query_parameters=query_params_obj
            )

            # Get the message
            self.logger.info(f"Getting message: {message_id}")
            message = await mailbox.messages.by_message_id(message_id).get(
                request_configuration=request_config
            )

            if not message:
                raise ValueError(f"Message {message_id} not found")

            # Format result
            result = {
                "id": message.id,
                "subject": message.subject or "(No subject)",
                "from": message.from_.email_address.address if message.from_ and message.from_.email_address else None,
                "from_name": message.from_.email_address.name if message.from_ and message.from_.email_address else None,
                "to_recipients": [
                    r.email_address.address
                    for r in (message.to_recipients or [])
                    if r and r.email_address
                ],
                "cc_recipients": [
                    r.email_address.address
                    for r in (message.cc_recipients or [])
                    if r and r.email_address
                ],
                "bcc_recipients": [
                    r.email_address.address
                    for r in (message.bcc_recipients or [])
                    if r and r.email_address
                ],
                "received_datetime": message.received_date_time.isoformat() if message.received_date_time else None,
                "sent_datetime": message.sent_date_time.isoformat() if message.sent_date_time else None,
                "has_attachments": message.has_attachments,
                "importance": str(message.importance) if message.importance else None,
                "is_read": message.is_read,
                "body_preview": message.body_preview,
                "internet_message_id": message.internet_message_id,
                "conversation_id": message.conversation_id,
                "web_link": message.web_link
            }

            # Add body if requested
            if include_body and message.body:
                result["body"] = {
                    "content_type": str(message.body.content_type) if message.body.content_type else "text",
                    "content": message.body.content or ""
                }

            self.logger.info(f"Retrieved message: {message.subject}")

            return result

        except Exception as e:
            self.logger.error(f"Failed to get message {message_id}: {e}", exc_info=True)
            raise


# ============================================================================
# DOWNLOAD ATTACHMENT TOOL
# ============================================================================

class DownloadAttachmentArgs(O365ToolArgsSchema):
    """Arguments for downloading an email attachment."""
    message_id: str = Field(
        description="The ID of the message containing the attachment"
    )
    attachment_id: str = Field(
        description="The ID of the attachment to download"
    )
    destination: str = Field(
        description="Local path where the attachment should be saved"
    )


class DownloadAttachmentTool(O365Tool):
    """
    Tool for downloading email attachments to local storage.

    This tool downloads a specific attachment from an email message and saves it
    to a specified location on the local filesystem.

    Before downloading, you should:
    1. Use GetMessageTool to retrieve the message and check hasAttachments
    2. List the attachments to get their IDs and names
    3. Use this tool to download specific attachments

    The tool will:
    - Create parent directories if they don't exist
    - Decode and save the attachment content
    - Return the path where the file was saved

    Examples:
        # Download attachment
        result = await tool.run(
            message_id="AAMkAGI...",
            attachment_id="AAMkAGI...Attach...",
            destination="/tmp/documents/report.pdf"
        )
    """

    name: str = "download_attachment"
    description: str = (
        "Download an email attachment to local storage. "
        "Saves the attachment file to the specified destination path."
    )
    args_schema: Type[BaseModel] = DownloadAttachmentArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Download an attachment using Microsoft Graph API.

        Args:
            client: Authenticated O365Client
            **kwargs: Download parameters

        Returns:
            Dict with download confirmation and path
        """
        message_id = kwargs.get('message_id')
        attachment_id = kwargs.get('attachment_id')
        destination = kwargs.get('destination')
        user_id = kwargs.get('user_id')

        try:
            # Get user context
            mailbox = client.get_user_context(user_id=user_id)

            # Get attachment info
            self.logger.info(f"Getting attachment {attachment_id} from message {message_id}")
            attachment = await mailbox.messages.by_message_id(message_id)\
                .attachments.by_attachment_id(attachment_id).get()

            if not attachment:
                raise ValueError(f"Attachment {attachment_id} not found")

            # Prepare destination path
            destination_path = Path(destination)
            destination_path.parent.mkdir(parents=True, exist_ok=True)

            # Handle different attachment types
            if hasattr(attachment, 'content_bytes') and attachment.content_bytes:
                # File attachment with content
                content = base64.b64decode(attachment.content_bytes)
                async with aiofiles.open(destination_path, "wb") as f:
                    await f.write(content)

                self.logger.info(f"Downloaded attachment '{attachment.name}' to {destination_path}")

                return {
                    "status": "downloaded",
                    "attachment_id": attachment.id,
                    "attachment_name": attachment.name,
                    "size": attachment.size,
                    "content_type": attachment.content_type,
                    "destination": str(destination_path)
                }
            else:
                raise ValueError(f"Attachment {attachment_id} has no downloadable content")

        except Exception as e:
            self.logger.error(f"Failed to download attachment {attachment_id}: {e}", exc_info=True)
            raise
