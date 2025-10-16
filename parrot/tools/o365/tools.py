"""
Office365 Tools Implementation.

Specific tools for interacting with Office365 services:
- CreateDraftMessage: Create email drafts
- CreateEvent: Create calendar events
- SearchEmail: Search through emails
- SendEmail: Send emails directly
"""
from typing import Dict, Any, Optional, List, Type
from pydantic import BaseModel, Field
from datetime import datetime
from msgraph.generated.models.message import Message
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.event import Event
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.location import Location
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.attendee_type import AttendeeType

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
        Create a draft message using Microsoft Graph API.

        Args:
            client: Authenticated O365Client
            **kwargs: Message parameters

        Returns:
            Dict with draft message details
        """
        # Extract parameters
        subject = kwargs.get('subject')
        body_content = kwargs.get('body')
        to_recipients = kwargs.get('to_recipients', [])
        cc_recipients = kwargs.get('cc_recipients', [])
        bcc_recipients = kwargs.get('bcc_recipients', [])
        importance = kwargs.get('importance', 'normal')
        is_html = kwargs.get('is_html', False)

        # Build message object
        message = Message()
        message.subject = subject

        # Set body
        message.body = ItemBody()
        message.body.content = body_content
        message.body.content_type = BodyType.Html if is_html else BodyType.Text

        # Set recipients
        def create_recipient(email: str) -> Recipient:
            recipient = Recipient()
            recipient.email_address = EmailAddress()
            recipient.email_address.address = email
            return recipient

        message.to_recipients = [create_recipient(email) for email in to_recipients]

        if cc_recipients:
            message.cc_recipients = [create_recipient(email) for email in cc_recipients]

        if bcc_recipients:
            message.bcc_recipients = [create_recipient(email) for email in bcc_recipients]

        # Set importance
        message.importance = importance

        try:
            # Create the draft
            draft = await client.graph_client.me.messages.post(message)

            self.logger.info(f"Created draft message: {draft.id}")

            return {
                "id": draft.id,
                "subject": draft.subject,
                "created_datetime": draft.created_date_time.isoformat() if draft.created_date_time else None,
                "to_recipients": to_recipients,
                "cc_recipients": cc_recipients or [],
                "bcc_recipients": bcc_recipients or [],
                "importance": importance,
                "web_link": draft.web_link
            }

        except Exception as e:
            self.logger.error(f"Failed to create draft message: {e}")
            raise


# ============================================================================
# CREATE EVENT TOOL
# ============================================================================

class CreateEventArgs(O365ToolArgsSchema):
    """Arguments for creating a calendar event."""
    subject: str = Field(
        description="Event subject/title"
    )
    start_datetime: str = Field(
        description="Event start date and time in ISO format (e.g., '2025-01-20T14:00:00')"
    )
    end_datetime: str = Field(
        description="Event end date and time in ISO format (e.g., '2025-01-20T15:00:00')"
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone for the event (e.g., 'America/New_York', 'Europe/London')"
    )
    body: Optional[str] = Field(
        default=None,
        description="Event description/body content"
    )
    location: Optional[str] = Field(
        default=None,
        description="Event location (e.g., 'Conference Room A', 'Zoom Meeting')"
    )
    attendees: Optional[List[str]] = Field(
        default=None,
        description="List of attendee email addresses"
    )
    is_online_meeting: bool = Field(
        default=False,
        description="Whether to create an online meeting (Teams meeting)"
    )
    is_all_day: bool = Field(
        default=False,
        description="Whether this is an all-day event"
    )


class CreateEventTool(O365Tool):
    """
    Tool for creating calendar events in Office365.

    This tool creates calendar events with support for:
    - Attendees and invitations
    - Online meetings (Teams)
    - All-day events
    - Timezone handling
    - Location and descriptions

    Examples:
        # Create a simple meeting
        result = await tool.run(
            subject="Team Standup",
            start_datetime="2025-01-20T09:00:00",
            end_datetime="2025-01-20T09:30:00",
            timezone="America/New_York",
            attendees=["team@company.com"]
        )

        # Create an online meeting
        result = await tool.run(
            subject="Client Presentation",
            start_datetime="2025-01-21T14:00:00",
            end_datetime="2025-01-21T15:00:00",
            body="Presenting Q4 results",
            attendees=["client@external.com"],
            is_online_meeting=True
        )

        # Create an all-day event
        result = await tool.run(
            subject="Company Holiday",
            start_datetime="2025-12-25T00:00:00",
            end_datetime="2025-12-25T23:59:59",
            is_all_day=True
        )
    """

    name: str = "create_event"
    description: str = (
        "Create a calendar event in Office365. "
        "Supports attendees, online meetings, locations, and timezone handling."
    )
    args_schema: Type[BaseModel] = CreateEventArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a calendar event using Microsoft Graph API.

        Args:
            client: Authenticated O365Client
            **kwargs: Event parameters

        Returns:
            Dict with event details
        """
        # Extract parameters
        subject = kwargs.get('subject')
        start_dt = kwargs.get('start_datetime')
        end_dt = kwargs.get('end_datetime')
        timezone = kwargs.get('timezone', 'UTC')
        body_content = kwargs.get('body')
        location_name = kwargs.get('location')
        attendee_emails = kwargs.get('attendees', [])
        is_online_meeting = kwargs.get('is_online_meeting', False)
        is_all_day = kwargs.get('is_all_day', False)

        # Build event object
        event = Event()
        event.subject = subject
        event.is_all_day = is_all_day

        # Set start and end times
        event.start = DateTimeTimeZone()
        event.start.date_time = start_dt
        event.start.time_zone = timezone

        event.end = DateTimeTimeZone()
        event.end.date_time = end_dt
        event.end.time_zone = timezone

        # Set body if provided
        if body_content:
            event.body = ItemBody()
            event.body.content = body_content
            event.body.content_type = BodyType.Text

        # Set location if provided
        if location_name:
            event.location = Location()
            event.location.display_name = location_name

        # Set attendees if provided
        if attendee_emails:
            event.attendees = []
            for email in attendee_emails:
                attendee = Attendee()
                attendee.type = AttendeeType.Required
                attendee.email_address = EmailAddress()
                attendee.email_address.address = email
                event.attendees.append(attendee)

        # Enable online meeting if requested
        if is_online_meeting:
            event.is_online_meeting = True
            event.online_meeting_provider = "teamsForBusiness"

        try:
            # Create the event
            created_event = await client.graph_client.me.events.post(event)

            self.logger.info(f"Created event: {created_event.id}")

            result = {
                "id": created_event.id,
                "subject": created_event.subject,
                "start": start_dt,
                "end": end_dt,
                "timezone": timezone,
                "location": location_name,
                "attendees": attendee_emails,
                "is_online_meeting": is_online_meeting,
                "web_link": created_event.web_link
            }

            # Add online meeting info if available
            if is_online_meeting and created_event.online_meeting:
                result["join_url"] = created_event.online_meeting.join_url

            return result

        except Exception as e:
            self.logger.error(f"Failed to create event: {e}")
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
        description="Sort order (e.g., 'receivedDateTime desc', 'subject asc')"
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

        try:
            # Build the request
            request_builder = client.graph_client.me.messages

            # Apply folder filter if not default
            folder_map = {
                'inbox': 'inbox',
                'sentitems': 'sentitems',
                'drafts': 'drafts',
                'deleteditems': 'deleteditems'
            }

            if folder.lower() in folder_map:
                folder_name = folder_map[folder.lower()]
                request_builder = client.graph_client.me.mail_folders.by_mail_folder_id(
                    folder_name
                ).messages

            # Configure query parameters
            query_params = {
                'top': max_results,
                'orderby': [order_by]
            }

            # Add search filter if query provided
            if query:
                query_params['search'] = f'"{query}"'

            # Select fields to return
            select_fields = [
                'id', 'subject', 'from', 'toRecipients', 'receivedDateTime',
                'bodyPreview', 'isRead', 'hasAttachments', 'importance',
                'conversationId', 'webLink'
            ]

            if include_attachments:
                select_fields.append('attachments')

            query_params['select'] = select_fields

            # Execute search
            messages = await request_builder.get(request_configuration=query_params)

            # Format results
            results = []
            if messages and messages.value:
                for msg in messages.value:
                    result_item = {
                        "id": msg.id,
                        "subject": msg.subject or "(No subject)",
                        "from": msg.from_prop.email_address.address if msg.from_prop else None,
                        "to": [
                            r.email_address.address
                            for r in (msg.to_recipients or [])
                        ],
                        "received_datetime": msg.received_date_time.isoformat() if msg.received_date_time else None,
                        "body_preview": msg.body_preview,
                        "is_read": msg.is_read,
                        "has_attachments": msg.has_attachments,
                        "importance": msg.importance,
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
            self.logger.error(f"Failed to search emails: {e}")
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
        cc_recipients = kwargs.get('cc_recipients', [])
        bcc_recipients = kwargs.get('bcc_recipients', [])
        importance = kwargs.get('importance', 'normal')
        is_html = kwargs.get('is_html', False)
        save_to_sent = kwargs.get('save_to_sent_items', True)

        # Build message object
        message = Message()
        message.subject = subject

        # Set body
        message.body = ItemBody()
        message.body.content = body_content
        message.body.content_type = BodyType.Html if is_html else BodyType.Text

        # Set recipients
        def create_recipient(email: str) -> Recipient:
            recipient = Recipient()
            recipient.email_address = EmailAddress()
            recipient.email_address.address = email
            return recipient

        message.to_recipients = [create_recipient(email) for email in to_recipients]

        if cc_recipients:
            message.cc_recipients = [create_recipient(email) for email in cc_recipients]

        if bcc_recipients:
            message.bcc_recipients = [create_recipient(email) for email in bcc_recipients]

        # Set importance
        message.importance = importance

        try:
            # Send the email
            await client.graph_client.me.send_mail.post(
                body={
                    "message": message,
                    "saveToSentItems": save_to_sent
                }
            )

            self.logger.info(f"Successfully sent email to {to_recipients}")

            return {
                "status": "sent",
                "subject": subject,
                "to_recipients": to_recipients,
                "cc_recipients": cc_recipients or [],
                "bcc_recipients": bcc_recipients or [],
                "sent_datetime": datetime.now().isoformat(),
                "saved_to_sent_items": save_to_sent
            }

        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            raise


# ============================================================================
# EXPORT ALL TOOLS
# ============================================================================

__all__ = [
    'CreateDraftMessageTool',
    'CreateEventTool',
    'SearchEmailTool',
    'SendEmailTool'
]
