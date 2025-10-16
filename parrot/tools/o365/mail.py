"""
Office365 Mails Tools.

Specific tools for interacting with Office365 services:
- CreateDraftMessage: Create email drafts
- SearchEmail: Search through emails
- SendEmail: Send emails directly
"""
from typing import Dict, Any, Optional, List, Type
from datetime import datetime
from pydantic import BaseModel, Field
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
