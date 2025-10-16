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
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.event import Event
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.location import Location
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.attendee_type import AttendeeType
from msgraph.generated.models.importance import Importance
from kiota_abstractions.base_request_configuration import RequestConfiguration

from .base import O365Tool, O365ToolArgsSchema, O365Client


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
        user_id = kwargs.get('user_id')

        try:
            # Get user context
            mailbox = client.get_user_context(user_id=user_id)

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
                # Note: online_meeting_provider might need to be set differently
                # depending on your Graph SDK version
                try:
                    event.online_meeting_provider = "teamsForBusiness"
                except AttributeError:
                    # Some versions use a different property
                    self.logger.warning("Could not set online_meeting_provider, using default")

            # Create the event
            self.logger.info(f"Creating event: {subject}")
            created_event = await mailbox.events.post(event)

            self.logger.info(f"Created event with ID: {created_event.id}")

            result = {
                "status": "created",
                "id": created_event.id,
                "subject": created_event.subject,
                "start": start_dt,
                "end": end_dt,
                "timezone": timezone,
                "location": location_name,
                "attendees": attendee_emails,
                "is_online_meeting": is_online_meeting,
                "is_all_day": is_all_day,
                "web_link": created_event.web_link
            }

            # Add online meeting info if available
            if is_online_meeting and hasattr(created_event, 'online_meeting') and created_event.online_meeting:
                result["join_url"] = getattr(created_event.online_meeting, 'join_url', None)

            return result

        except Exception as e:
            self.logger.error(f"Failed to create event: {e}", exc_info=True)
            raise
