from pydantic import BaseModel, Field
from typing import List, Optional

class Preferences(BaseModel):
    theme: str
    notifications: List[str]

class User(BaseModel):
    user_id: int
    username: str
    is_active: bool
    preferences: Preferences
    last_login: Optional[str] = None
    meta_tags: Optional[List[str]] = None
