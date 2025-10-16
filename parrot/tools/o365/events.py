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

# events.py (Continued)

# ============================================================================
# LIST EVENTS TOOL
# ============================================================================

class ListEventArgs(O365ToolArgsSchema):
    """Arguments for listing calendar events."""
    start_datetime: Optional[str] = Field(
        default=None,
        description="Optional: Start date and time for the range query in ISO format (e.g., '2025-01-01T00:00:00'). Required for /instances endpoint."
    )
    end_datetime: Optional[str] = Field(
        default=None,
        description="Optional: End date and time for the range query in ISO format (e.g., '2025-01-31T23:59:59'). Required for /instances endpoint."
    )
    top: Optional[int] = Field(
        default=10,
        description="Maximum number of events to return. Defaults to 10."
    )
    filter: Optional[str] = Field(
        default=None,
        description="OData $filter string for advanced filtering (e.g., 'subject eq \"Team Standup\"')"
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone for event start/end times in the response (e.g., 'America/New_York')."
    )

class ListEventsTool(O365Tool):
    """
    Tool for listing events in the user's calendar.

    Uses OData query parameters ($top, $filter) for customization and
    `Prefer: outlook.timezone` header to control response timezones.
    """
    name: str = "list_events"
    description: str = (
        "List upcoming or recent calendar events. "
        "Can filter by date range and use OData queries for advanced filtering."
    )
    args_schema: Type[BaseModel] = ListEventArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        List calendar events using Microsoft Graph API.
        """
        start_dt = kwargs.get('start_datetime')
        end_dt = kwargs.get('end_datetime')
        top = kwargs.get('top', 10)
        filter_query = kwargs.get('filter')
        timezone = kwargs.get('timezone', 'UTC')
        user_id = kwargs.get('user_id')

        try:
            mailbox = client.get_user_context(user_id=user_id)

            # Use RequestConfiguration for headers and query parameters
            request_configuration = RequestConfiguration()

            # Set the timezone preference header
            request_configuration.headers.add("Prefer", f"outlook.timezone=\"{timezone}\"")

            # Set top for pagination
            request_configuration.query_parameters['$top'] = top

            # Set filter
            if filter_query:
                request_configuration.query_parameters['$filter'] = filter_query

            # Check for date range which uses the /calendarView endpoint (or /events if no range)
            if start_dt and end_dt:
                self.logger.info(f"Listing events between {start_dt} and {end_dt} for timezone {timezone}")

                # Note: CalendarView requires start and end date
                request_configuration.query_parameters['startDateTime'] = start_dt
                request_configuration.query_parameters['endDateTime'] = end_dt

                events_response = await mailbox.calendar.calendar_view.get(request_configuration=request_configuration)
            else:
                self.logger.info(f"Listing events with top={top}, timezone={timezone}")
                events_response = await mailbox.events.get(request_configuration=request_configuration)

            event_list = events_response.value or []

            # Format the list for output
            results = [
                {
                    "id": event.id,
                    "subject": event.subject,
                    "start": event.start.date_time if event.start else None,
                    "end": event.end.date_time if event.end else None,
                    "location": event.location.display_name if event.location else None,
                    "is_online_meeting": event.is_online_meeting,
                    "web_link": event.web_link
                } for event in event_list
            ]

            return {
                "status": "success",
                "count": len(results),
                "events": results
            }

        except Exception as e:
            self.logger.error(f"Failed to list events: {e}", exc_info=True)
            raise

# ============================================================================
# GET EVENT TOOL
# ============================================================================

class GetEventArgs(O365ToolArgsSchema):
    """Arguments for retrieving a single calendar event by ID."""
    event_id: str = Field(
        description="The unique ID of the calendar event to retrieve."
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone for event start/end times in the response (e.g., 'America/New_York')."
    )

class GetEventTool(O365Tool):
    """
    Tool for retrieving a single calendar event by its ID.
    """
    name: str = "get_event"
    description: str = (
        "Retrieve the full details of a single calendar event using its unique ID."
    )
    args_schema: Type[BaseModel] = GetEventArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Get a calendar event by ID using Microsoft Graph API.
        """
        event_id = kwargs.get('event_id')
        timezone = kwargs.get('timezone', 'UTC')
        user_id = kwargs.get('user_id')

        try:
            mailbox = client.get_user_context(user_id=user_id)

            # Use RequestConfiguration for headers
            request_configuration = RequestConfiguration()
            request_configuration.headers.add("Prefer", f"outlook.timezone=\"{timezone}\"")

            self.logger.info(f"Retrieving event with ID: {event_id}")

            event = await mailbox.events.by_event_id(event_id).get(
                request_configuration=request_configuration
            )

            # Format the output
            attendees_list = [
                {
                    "email": a.email_address.address,
                    "type": a.type.value,
                    "response": a.status.response.value
                } for a in event.attendees
            ] if event.attendees else []

            return {
                "status": "success",
                "id": event.id,
                "subject": event.subject,
                "body_preview": event.body_preview,
                "body": event.body.content if event.body else None,
                "start": event.start.date_time if event.start else None,
                "end": event.end.date_time if event.end else None,
                "timezone": event.start.time_zone if event.start else None,
                "location": event.location.display_name if event.location else None,
                "is_online_meeting": event.is_online_meeting,
                "join_url": event.online_meeting.join_url if event.online_meeting else None,
                "attendees": attendees_list,
                "web_link": event.web_link
            }

        except Exception as e:
            self.logger.error(f"Failed to get event {event_id}: {e}", exc_info=True)
            raise

# ============================================================================
# UPDATE EVENT TOOL
# ============================================================================

class UpdateEventArgs(O365ToolArgsSchema):
    """Arguments for updating a calendar event."""
    event_id: str = Field(
        description="The unique ID of the calendar event to update."
    )
    subject: Optional[str] = Field(
        default=None,
        description="Optional: New event subject/title"
    )
    start_datetime: Optional[str] = Field(
        default=None,
        description="Optional: New event start date and time in ISO format (e.g., '2025-01-20T14:00:00')"
    )
    end_datetime: Optional[str] = Field(
        default=None,
        description="Optional: New event end date and time in ISO format (e.g., '2025-01-20T15:00:00')"
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone for the event's start/end times (e.g., 'America/New_York')."
    )
    body: Optional[str] = Field(
        default=None,
        description="Optional: New event description/body content"
    )
    location: Optional[str] = Field(
        default=None,
        description="Optional: New event location (e.g., 'Conference Room B', 'New Zoom Link'). Set to empty string to clear."
    )
    # Note: Updating attendees is complex (add/remove) and usually done via a full Event object replacement/PATCH,
    # but for simplicity, we'll keep the core fields for this tool.
    send_updates: Optional[bool] = Field(
        default=True,
        description="Whether to send update notifications to attendees. Defaults to True."
    )
    is_online_meeting: Optional[bool] = Field(
        default=None,
        description="Optional: Whether to make this an online meeting (Teams meeting)."
    )

class UpdateEventTool(O365Tool):
    """
    Tool for updating an existing calendar event in Office365.

    The update uses a PATCH operation, so only fields provided will be updated.
    """
    name: str = "update_event"
    description: str = (
        "Update an existing calendar event using its ID. "
        "Only provide the fields you want to change."
    )
    args_schema: Type[BaseModel] = UpdateEventArgs

    async def _execute_graph_operation(
        self,
        client: O365Client,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Update a calendar event using Microsoft Graph API (PATCH).
        """
        event_id = kwargs.get('event_id')
        user_id = kwargs.get('user_id')
        timezone = kwargs.get('timezone', 'UTC')

        # Determine if we should send updates
        send_updates = kwargs.get('send_updates', True)

        # Build the update object (Event model with only fields to update)
        update_event = Event()

        if subject := kwargs.get('subject'):
            update_event.subject = subject

        if body_content := kwargs.get('body'):
            update_event.body = ItemBody(content=body_content, content_type=BodyType.Text)

        if location_name := kwargs.get('location'):
            # Clear location if an empty string is passed
            if location_name.strip() == "":
                update_event.location = Location(display_name="")
            else:
                update_event.location = Location(display_name=location_name)

        # Handle start and end time updates (requires both to be consistently set if changing)
        start_dt = kwargs.get('start_datetime')
        end_dt = kwargs.get('end_datetime')

        if start_dt:
            update_event.start = DateTimeTimeZone(date_time=start_dt, time_zone=timezone)
        if end_dt:
            update_event.end = DateTimeTimeZone(date_time=end_dt, time_zone=timezone)

        if is_online_meeting := kwargs.get('is_online_meeting'):
            update_event.is_online_meeting = is_online_meeting
            # The online_meeting_provider might need to be set if creating a new one
            if is_online_meeting:
                try:
                    update_event.online_meeting_provider = "teamsForBusiness"
                except AttributeError:
                    self.logger.warning("Could not set online_meeting_provider in update")

        # Set up request configuration for sending updates header
        request_configuration = RequestConfiguration()
        if send_updates is False:
            request_configuration.headers.add(
                "Prefer", "outlook.sendUpdateNotificationsForRecipients=\"None\""
            )
        elif send_updates is True:
            # Send updates to all attendees
            request_configuration.headers.add(
                "Prefer", "outlook.sendUpdateNotificationsForRecipients=\"All\""
            )


        try:
            mailbox = client.get_user_context(user_id=user_id)
            self.logger.info(f"Updating event with ID: {event_id}. Send updates: {send_updates}")

            # Send the PATCH request
            updated_event = await mailbox.events.by_event_id(event_id).patch(
                update_event,
                request_configuration=request_configuration
            )

            # Note: The PATCH request typically returns a 200 OK or 204 No Content
            # and may not return the full updated object in all SDK versions.
            # We return a status and the ID.
            return {
                "status": "updated",
                "id": event_id,
                "subject": subject or updated_event.subject,
                "start": start_dt or updated_event.start.date_time if updated_event.start else None,
                "end": end_dt or updated_event.end.date_time if updated_event.end else None,
                "web_link": updated_event.web_link
            }

        except Exception as e:
            self.logger.error(f"Failed to update event {event_id}: {e}", exc_info=True)
            raise
