from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ResumeCreate(BaseModel):
    source_name: str = Field(min_length=1, max_length=200)
    resume_text: str = Field(min_length=20)
    consent: bool

    @model_validator(mode="after")
    def require_consent(self) -> "ResumeCreate":
        if not self.consent:
            raise ValueError("candidate consent is required")
        return self


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    city: str = Field(default="", max_length=100)
    jd_text: str = Field(min_length=20)
    source_url: HttpUrl | None = None
    source_type: Literal["user_provided", "verified"] = "user_provided"


class InterviewCreate(BaseModel):
    resume_id: str = Field(min_length=1, max_length=64)
    job_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=100)
    max_turns: int = Field(default=2, ge=2, le=6)


class AnswerCreate(BaseModel):
    answer: str = Field(min_length=1, max_length=20_000)


class ReviewCreate(BaseModel):
    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=2000)


class CreatedResource(BaseModel):
    id: str
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    environment: str
    llm_provider: str


class ConversationCreate(BaseModel):
    title: str = Field(default="求职教练对话", min_length=1, max_length=200)
    resume_id: str | None = Field(default=None, max_length=64)
    job_id: str | None = Field(default=None, max_length=64)
    memory_enabled: bool = True


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class MemoryCreate(BaseModel):
    category: Literal["goal", "preference", "experience", "constraint"]
    content: str = Field(min_length=2, max_length=500)


class MemoryUpdate(BaseModel):
    category: Literal["goal", "preference", "experience", "constraint"] | None = None
    content: str | None = Field(default=None, min_length=2, max_length=500)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "MemoryUpdate":
        if self.category is None and self.content is None and self.is_active is None:
            raise ValueError("at least one memory field must change")
        return self

