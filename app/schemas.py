from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RecordType = Literal["person", "event", "claim", "place", "theme"]
ReviewStatus = Literal["pending", "approved", "corrected", "rejected"]


class EvidenceInput(BaseModel):
    segment_id: int
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class ExtractedRecord(BaseModel):
    record_type: RecordType
    record_key: str = Field(min_length=1)
    payload: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    is_explicit: bool = True
    is_inferred: bool = False
    evidence: list[EvidenceInput] = Field(min_length=1)


class ReviewRequest(BaseModel):
    decision: Literal["approved", "corrected", "rejected"]
    reviewed_value: dict[str, Any] | None = None
    reviewer_note: str | None = None


class DocumentCreate(BaseModel):
    title: str
    text: str
    language: str = "en"


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    language: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    attempts: int
    task_id: str | None
    error_message: str | None


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    segment_id: int
    char_start: int
    char_end: int
    quote: str


class RecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    record_type: str
    record_key: str
    payload: dict[str, Any]
    effective_payload: dict[str, Any] | None
    confidence: float
    is_explicit: bool
    is_inferred: bool
    review_status: str
    evidence: list[EvidenceResponse]
