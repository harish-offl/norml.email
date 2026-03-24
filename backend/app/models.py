from dataclasses import dataclass


@dataclass(slots=True)
class Lead:
    id: int
    email: str
    name: str = ""
    niche: str = ""
    industry: str = ""
    phone: str = ""
    company: str = ""
    sent_at: str | None = None
    last_status: str = "pending"
    last_error: str = ""
