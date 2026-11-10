from enum import StrEnum

from pydantic import BaseModel, Field


class Difficulty(StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class ResumeProfile(BaseModel):
    education: list[str] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=50)
    projects: list[str] = Field(default_factory=list, max_length=30)
    research_directions: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[str] = Field(default_factory=list, max_length=30)


class JobAnalysis(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    evidence_quality: str = Field(pattern="^(low|medium|high)$")
    confirmed_requirements: list[str] = Field(default_factory=list, max_length=30)
    inferred_requirements: list[str] = Field(default_factory=list, max_length=30)
    strengths: list[str] = Field(default_factory=list, max_length=20)
    gaps: list[str] = Field(default_factory=list, max_length=20)
    interview_focus: list[str] = Field(default_factory=list, max_length=20)


class InterviewQuestion(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    topic: str = Field(min_length=1, max_length=100)
    difficulty: Difficulty = Difficulty.medium
    expected_points: list[str] = Field(default_factory=list, max_length=15)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)


class ScoreDimensions(BaseModel):
    relevance: int = Field(ge=0, le=20)
    correctness: int = Field(ge=0, le=30)
    depth: int = Field(ge=0, le=20)
    engineering: int = Field(ge=0, le=20)
    communication: int = Field(ge=0, le=10)


class AnswerEvaluation(BaseModel):
    dimensions: ScoreDimensions
    total_score: int = Field(ge=0, le=100)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    weaknesses: list[str] = Field(default_factory=list, max_length=10)
    evidence_from_answer: list[str] = Field(default_factory=list, max_length=10)
    feedback: str = Field(min_length=1, max_length=2000)


class FollowupQuestion(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    reason: str = Field(min_length=1, max_length=500)
    expected_points: list[str] = Field(default_factory=list, max_length=10)


class FinalReport(BaseModel):
    initial_score: int = Field(ge=0, le=100)
    followup_score: int = Field(ge=0, le=100)
    final_score: int = Field(ge=0, le=100)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    weaknesses: list[str] = Field(default_factory=list, max_length=10)
    learning_plan: list[str] = Field(default_factory=list, max_length=10)
    decision_support_note: str = Field(min_length=1, max_length=2000)


class MemoryCandidate(BaseModel):
    category: str = Field(pattern="^(goal|preference|experience|constraint)$")
    content: str = Field(min_length=2, max_length=500)


class CareerCoachReply(BaseModel):
    reply: str = Field(min_length=1, max_length=6000)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list, max_length=5)


class ConversationSummary(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)

