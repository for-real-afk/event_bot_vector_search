from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class ExperienceLevel(str, Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    expert = "expert"


class AttendeeCreate(BaseModel):
    """
    Final field list — exactly what the registration form collects.
    `detailed_profile` is the free-text bio that powers semantic search.
    """
    id: str                                 # your main backend's PK
    full_name: str
    email: str
    phone: Optional[str] = None
    organization: str
    role: str
    experience_level: Optional[ExperienceLevel] = None
    detailed_profile: Optional[str] = None  # "Share your detailed profile" — main search signal
    linkedin_url: Optional[str] = None


class AttendeeResult(BaseModel):
    id: str
    full_name: str
    role: str
    organization: str
    experience_level: Optional[str]
    detailed_profile: Optional[str]
    linkedin_url: Optional[str]
    score: float                            # cosine similarity 0-1 (higher = better match)


class AttendeeProfile(BaseModel):
    """Full profile returned by GET /attendees/{id} — includes contact details."""
    id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    organization: str
    role: str
    experience_level: Optional[str]
    detailed_profile: Optional[str]
    linkedin_url: Optional[str]


class SearchResponse(BaseModel):
    query: str
    expanded_query: Optional[str]           # Groq-rewritten query (null if Groq is off)
    total: int
    results: List[AttendeeResult]


class BulkUpsertResponse(BaseModel):
    indexed: int
    message: str
