from typing import Tuple, List, Dict, Any, Optional
from asyncdb import AsyncDB
from querysource.conf import default_dsn
from .abstract import AbstractKnowledgeBase
from .redis import RedisKnowledgeBase
from ...utils.helpers import RequestContext
from .cache import TTLCache


class UserInfo(AbstractKnowledgeBase):
    """Class to manage user information."""

    def __init__(self, **kwargs):
        super().__init__(
            name="User Info",
            category="user_context",
            always_active=True,
            activation_patterns=[
                "about me"
            ],
            priority=10,  # High priority
            **kwargs
        )
        self.db = AsyncDB('pg', dsn=default_dsn)
        self.cache =  TTLCache(
            max_size=500,
            default_ttl=600  # 10 minutes for user data
        )
        self._initialized = False

    async def _lazy_init(self):
        """Lazy initialization of resources."""
        if not self._initialized:
            await self.cache.start()
            self._initialized = True

    async def should_activate(self, query: str, context: dict) -> Tuple[bool, float]:
        # Implement activation logic based on user info
        return True, 1.0  # Always activate with high confidence

    async def search(self, query: str, user_id: int, **kwargs) -> List[Dict]:
        """Query Database for User Information."""
        if not user_id:
            return []

        try:
            async with await self.db.connection() as conn:  # pylint: disable=E1101 # noqa
                result = await conn.fetch_one(
                    """
                    SELECT user_id, display_name, username, email, job_code, associate_id as employee_id,
                    associate_id, associate_oid, title, worker_type, manager_id
                    FROM auth.vw_users WHERE user_id = $1
                    """,
                    user_id
                )
                # Ok, Result is an asyncpg Record object, iterate over the columns:
                # iterate over the result and convert in a list of facts:
                facts = []
                user = dict(result)
                for key, value in user.items():
                    if value:
                        facts.append({
                            "content": f"{key.replace('_', ' ').title()}: {value}",
                            "metadata": {
                                    "category": "user_info",
                                    "entity_type": key,
                                    "confidence": 1.0,
                                    "tags": ["user", "profile", key]
                                }
                            })
                return facts
        except Exception as e:
            print(f"Error fetching user info: {e}")
        return []

class UserProfileKB(AbstractKnowledgeBase):
    """KB that queries database for user information."""

    def __init__(self, **kwargs):
        super().__init__(
            name="User Profile",
            category="user_context",
            activation_patterns=[
                "my preferences", "my profile", "my settings",
                "about me", "my role", "my permissions"
            ],
            priority=10  # High priority
        )
        self.db = AsyncDB('pg', dsn=default_dsn)

    async def should_activate(self, query: str, context: Dict) -> Tuple[bool, float]:
        """Check if query references user-specific information."""
        query_lower = query.lower()

        # Direct patterns
        for pattern in self.activation_patterns:
            if pattern in query_lower:
                return True, 1.0

        # Heuristic checks
        personal_indicators = ["my", "me", "i", "our"]
        if any(word in query_lower.split() for word in personal_indicators):
            return True, 0.7

        return False, 0.0

    async def search(self, query: str, user_id: str = None, **kwargs) -> List[Dict]:
        """Query database for user information."""
        if not user_id:
            return []

        async with await self.db.connection() as conn:  # pylint: disable=E1101 # noqa
            user_data = await conn.fetch_one("""
                SELECT
                    first_name, last_name, email,
                    job_code, title, department_code,
                    groups,
                    programs
                FROM auth.vw_users u
                WHERE u.user_id = $1
            """, user_id)

        if not user_data:
            return []

        # Convert to facts
        facts = [
            {
                'content': f"User's name is {user_data['first_name']} {user_data['last_name']}",
                'metadata': {'field': 'name'},
            },
            {
                'content': f"User's job title is {user_data['job_code']} in {user_data['department_code']}",
                'metadata': {'field': 'position'},
            },
        ]

        if user_data['groups']:
            facts.append({
                'content': f"User has groups: {', '.join(user_data['groups'])}",
                'metadata': {'field': 'groups'}
            })

        if user_data['programs']:
            facts.append({
                'content': f"User is enrolled in programs: {', '.join(user_data['programs'])}",
                'metadata': {'field': 'programs'}
            })

        return facts

class SessionStateKB(AbstractKnowledgeBase):
    """KB that retrieves from session state."""
    def __init__(self, **kwargs):
        super().__init__(
            name="User Session",
            category="session",
            activation_patterns=[
                "preferences", "prefer", "like", "favorite",
                "based on what I like"
            ]
        )

    async def search(self, query: str, ctx: RequestContext = None, **kwargs) -> List[Dict]:
        """Extract relevant session state."""
        if not ctx or not ctx.request:
            return []

        session = ctx.request.session
        facts = []

        # Extract current workflow state
        if 'current_workflow' in session:
            facts.append({
                'content': f"User is currently working on: {session['current_workflow']}",
                'metadata': {'source': 'session'}
            })

        return facts

class UserPreferences(RedisKnowledgeBase):
    """KB for user preferences stored in Redis."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="User Preferences",
            category="preferences",
            activation_patterns=[
                "preferences", "prefer", "like", "favorite",
                "based on what I like", "my preferences"
            ],
            namespace="user_prefs",
            use_hash_storage=True,
            ttl=86400 * 365,  # 1 year expiration
            **kwargs,
        )

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Retrieve user preferences matching the query.

        Args:
            query: Search query
            user_id: User identifier (required)
            **kwargs: Additional parameters

        Returns:
            List of preference facts
        """
        if not user_id:
            return []

        # Get all preferences for user
        prefs = await self.get(user_id)

        if not prefs:
            return []

        facts = []
        query_lower = query.lower()

        for key, value in prefs.items():
            # Check if query matches key or value
            if query_lower in key.lower() or query_lower in str(value).lower():
                # Calculate relevance
                relevance = 1.0 if query_lower == key.lower() else 0.5
                if query_lower in str(value).lower():
                    relevance += 0.3

                facts.append({
                    'content': f"User prefers {key}: {value}",
                    'metadata': {
                        'preference': key,
                        'value': value,
                        'user_id': user_id
                    },
                    'source': 'user_preferences',
                    'relevance': min(relevance, 1.0)  # Cap at 1.0
                })

        # Sort by relevance
        facts.sort(key=lambda x: x['relevance'], reverse=True)
        return facts

    async def set_preference(
        self,
        user_id: str,
        preference: str,
        value: Any
    ) -> bool:
        """
        Set a single user preference.

        Args:
            user_id: User identifier
            preference: Preference name
            value: Preference value

        Returns:
            True if successful
        """
        return await self.insert(user_id, value, field=preference)

    async def get_preference(
        self,
        user_id: str,
        preference: str,
        default: Any = None
    ) -> Any:
        """
        Get a single user preference.

        Args:
            user_id: User identifier
            preference: Preference name
            default: Default value if not found

        Returns:
            Preference value or default
        """
        return await self.get(user_id, field=preference, default=default)

    async def delete_preference(
        self,
        user_id: str,
        preference: str
    ) -> bool:
        """
        Delete a single user preference.

        Args:
            user_id: User identifier
            preference: Preference name

        Returns:
            True if successful
        """
        return await self.delete(user_id, field=preference)

    async def get_all_preferences(self, user_id: str) -> Dict[str, Any]:
        """
        Get all preferences for a user.

        Args:
            user_id: User identifier

        Returns:
            Dict of all preferences
        """
        return await self.get(user_id, default={})

    async def clear_all_preferences(self, user_id: str) -> bool:
        """
        Clear all preferences for a user.

        Args:
            user_id: User identifier

        Returns:
            True if successful
        """
        return await self.delete(user_id)

    async def update_preferences(
        self,
        user_id: str,
        preferences: Dict[str, Any]
    ) -> bool:
        """
        Update multiple preferences at once.

        Args:
            user_id: User identifier
            preferences: Dictionary of preferences to update

        Returns:
            True if successful
        """
        return await self.update(user_id, preferences)

    async def has_preference(
        self,
        user_id: str,
        preference: str
    ) -> bool:
        """
        Check if a user has a specific preference set.

        Args:
            user_id: User identifier
            preference: Preference name

        Returns:
            True if preference exists
        """
        return await self.exists(user_id, field=preference)

    async def list_user_preference_keys(self, user_id: str) -> List[str]:
        """
        Get list of all preference keys for a user.

        Args:
            user_id: User identifier

        Returns:
            List of preference keys
        """
        prefs = await self.get_all_preferences(user_id)
        return list(prefs.keys()) if prefs else []
