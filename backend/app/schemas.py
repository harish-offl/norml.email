from typing import Optional

from pydantic import BaseModel, Field


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
    last_contacted_at: Optional[str] = None
    next_followup_at: Optional[str] = None
    followup_count: int = 0
    sequence_status: str = "pending"
    reply_received_at: Optional[str] = None
    opt_out_at: Optional[str] = None
    sequence_completed_at: Optional[str] = None
    thread_subject: str = ""
    last_message_id: str = ""


class FollowupSettingsUpdate(BaseModel):
    enabled: bool = False
    followup_1_delay_days: int = Field(default=3, ge=0, le=90)
    followup_2_delay_days: int = Field(default=7, ge=0, le=90)
    final_bump_delay_days: int = Field(default=12, ge=0, le=90)
    followup_1_date: Optional[str] = None
    followup_2_date: Optional[str] = None
    final_bump_date: Optional[str] = None


class FollowupSettingsRead(FollowupSettingsUpdate):
    due_count: int = 0
    scheduled_count: int = 0
    active_count: int = 0
    next_due_at: Optional[str] = None
