"""Module doc."""
import os
from parrot.tools import AbstractTool


class UserService(BaseService):
    """Main service class."""
    async def get_user(self, user_id: int) -> dict:
        """Fetch a user."""
        return helper(user_id)


def helper(a, b=1):
    """Utility helper."""
    return a
