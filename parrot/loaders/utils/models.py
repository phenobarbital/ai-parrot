from typing import Optional, Union
from datetime import datetime
from pathlib import PurePath
from datamodel import BaseModel, Field

def uuid_to_str(obj) -> str:
    return str(obj)

class BotData(BaseModel):
    chatbot_id: str = Field(primary_key=True, required=True, encoder=uuid_to_str)
    name: str = Field(required=True)
    source_type: str = Field(required=True, default='content')
    category: str = Field(required=True, default='data')
    tags: Optional[list[str]] = Field(required=False, default_factory=list)
    document_type: str = Field(required=False, default='document')
    loader: str = Field(required=True, default='TXTLoader')
    source_path: Union[str,PurePath] = Field(required=False)
    extensions: list[str] = Field(required=False)
    data: Optional[Union[list,dict]] = Field(required=False)
    arguments: Optional[dict] = Field(default_factory=dict)
    version: int = Field(required=True, default=1)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:
        name: str = 'chatbots_data'
