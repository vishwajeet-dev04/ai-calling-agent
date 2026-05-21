from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum


class CallStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"


class AgentPhase(str, Enum):
    GREETING = "greeting"
    IDENTITY_CONFIRM = "identity_confirm"
    SURVEY = "survey"
    CLOSING = "closing"
    ENDED = "ended"


class Candidate(BaseModel):
    id: int
    name: str
    phone: str
    status: CallStatus = CallStatus.PENDING
    # Survey answers — dynamic, stored as flat fields for Excel export
    overall_satisfaction: Optional[str] = None
    would_recommend: Optional[str] = None
    issues_faced: Optional[str] = None
    suggestions: Optional[str] = None
    # Meta
    call_duration: Optional[int] = None
    call_sid: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0


class QueueStatus(BaseModel):
    total: int
    pending: int
    in_progress: int
    completed: int
    failed: int
    no_answer: int
    queue_running: bool
    current_candidate: Optional[str] = None


class SurveyQuestion(BaseModel):
    key: str
    question: str
    follow_up: Optional[str] = None  # e.g. "Could you tell me more?"