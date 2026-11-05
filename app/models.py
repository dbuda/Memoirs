from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(16), default="en")
    source_version: Mapped[str] = mapped_column(String(64), default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    segments: Mapped[list["Segment"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    runs: Mapped[list["ExtractionRun"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    speaker: Mapped[str] = mapped_column(String(128))
    sequence_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    document: Mapped[Document] = relationship(back_populates="segments")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64), default="v1")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    document: Mapped[Document] = relationship(back_populates="runs")
    records: Mapped[list["KnowledgeRecord"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class KnowledgeRecord(Base):
    __tablename__ = "knowledge_records"
    __table_args__ = (UniqueConstraint("run_id", "record_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"))
    record_type: Mapped[str] = mapped_column(String(32))
    record_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column()
    is_explicit: Mapped[bool] = mapped_column(default=True)
    is_inferred: Mapped[bool] = mapped_column(default=False)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    run: Mapped[ExtractionRun] = relationship(back_populates="records")
    evidence: Mapped[list["Evidence"]] = relationship(
        secondary="record_evidence",
        back_populates="records",
    )
    reviews: Mapped[list["ReviewDecision"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    extraction_run_id: Mapped[int] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"))
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"))
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    records: Mapped[list[KnowledgeRecord]] = relationship(
        secondary="record_evidence",
        back_populates="evidence",
    )


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("knowledge_records.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(32))
    original_value: Mapped[dict[str, Any]] = mapped_column(JSON)
    reviewed_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    record: Mapped[KnowledgeRecord] = relationship(back_populates="reviews")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RecordEvidence(Base):
    __tablename__ = "record_evidence"

    record_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_records.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
