from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LeadIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    message: str = Field(..., min_length=1, max_length=5000)
    source: Optional[str] = Field(default=None, max_length=200)


class LeadOut(BaseModel):
    id: UUID
    duplicate: bool
    crm_status: str
    notify_status: str
    ack_status: str
    received_at: datetime
