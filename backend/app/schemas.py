from typing import Optional

from pydantic import BaseModel, EmailStr


class LeadCreate(BaseModel):
    name: Optional[str] = None
    email: EmailStr
    niche: Optional[str] = None
    industry: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None


class Lead(LeadCreate):
    id: int

    class Config:
        orm_mode = True
