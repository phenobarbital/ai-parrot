from navigator.views import BaseView
from navigator_auth.decorators import user_session

@user_session()
class ProgramsUserHandler(BaseView):
    """
    ProgramsUserHandler.
    description: Handler to get the list of programs for the current user.
    """
    async def get(self):
        """
        Get the list of programs for the authenticated user.
        """
        # In a real scenario, this would query the database based on self._session['user_id']
        # For now, we return the manual data structure as requested.
        
        # We can try to get programs from the user session if available
        # pylint: disable=protected-access
        session = getattr(self, '_session', {})
        user_programs_slugs = session.get('programs', [])
        # We might use user_programs_slugs later to filter
        print(f"User programs: {user_programs_slugs}")
        
        # Mock response matching the requested payload structure
        # We include some default programs + any specific ones
        
        programs = [
            {
                "program_id": 107,
                "program_name": "Finance",
                "description": "Financial management and accounting",
                "attributes": None,
                "program_slug": "finance",
                "program_cat_id": 1,
                "program_type_id": 1,
                "is_active": True,
                "visible": True,
                "created_at": "2024-11-15T13:25:22.861728Z",
                "updated_at": "2024-11-15T13:25:22.861728Z",
                "conditions": None,
                "filtering_show": None,
                "allow_filtering": True,
                "image_url": "mdi:currency-usd", # Using icon from manual-data
                "abbrv": None,
                "created_by": None,
                "color": "#F59E0B" # Extra field helpful for UI
            },
            {
                "program_id": 108,
                "program_name": "Operations",
                "description": "Operations and Employee management",
                "attributes": None,
                "program_slug": "operations",
                "program_cat_id": 1,
                "program_type_id": 1,
                "is_active": True,
                "visible": True,
                "created_at": "2024-11-15T13:25:22.861728Z",
                "updated_at": "2024-11-15T13:25:22.861728Z",
                "conditions": None,
                "filtering_show": None,
                "allow_filtering": True,
                "image_url": "mdi:account-tie",
                "abbrv": None,
                "created_by": None,
                "color": "#10B981"
            },
            {
                "program_id": 109,
                "program_name": "Crew Builder",
                "description": "Design and manage AI agent crews",
                "attributes": None,
                "program_slug": "crewbuilder",
                "program_cat_id": 2,
                "program_type_id": 1,
                "is_active": True,
                "visible": True,
                "created_at": "2024-11-15T13:25:22.861728Z",
                "updated_at": "2024-11-15T13:25:22.861728Z",
                "conditions": None,
                "filtering_show": None,
                "allow_filtering": True,
                "image_url": "mdi:account-group",
                "abbrv": None,
                "created_by": None,
                "color": "#8B5CF6"
            },
            {
                "program_id": 110,
                "program_name": "Navigator",
                "description": "Navigator",
                "attributes": None,
                "program_slug": "navigator",
                "program_cat_id": 2,
                "program_type_id": 1,
                "is_active": True,
                "visible": True,
                "created_at": "2024-11-15T13:25:22.861728Z",
                "updated_at": "2024-11-15T13:25:22.861728Z",
                "conditions": None,
                "filtering_show": None,
                "allow_filtering": True,
                "image_url": "mdi:compass",
                "abbrv": None,
                "created_by": None,
                "color": "#8B5CF6"
            }
        ]
        
        # If user has specific programs in session, we might want to filter or add them
        # For now, just return the static list which matches 'manual-data.ts' content
        # but served via API as requested.
        
        return self.json_response(programs)
