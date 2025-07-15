from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class Link(Document):
    original_url: str
    original_url_hash: str = Field(index=True, unique=True)
    slug: str = Field(index=True, unique=True)
    owner_id: Optional[str] = None
    password: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    click_count: int = 0
    notes: Optional[str] = None

    class Settings:
        name = "links"  # MongoDB collection
