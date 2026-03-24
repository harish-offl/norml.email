from typing import Optional

from pydantic import BaseModel


class LeadCreate(BaseModel):
    name: Optional[str] = None
    email: str
    niche: Optional[str] = None
    industry: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None


class LeadRead(LeadCreate):
    id: int
    sent_at: Optional[str] = None
    last_status: str = "pending"
    last_error: str = ""
