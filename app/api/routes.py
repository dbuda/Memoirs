from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Document, Evidence, ExtractionRun, Job, KnowledgeRecord, ReviewDecision
from app.schemas import (
    DocumentCreate,
    DocumentResponse,
    JobResponse,
    RecordResponse,
    ReviewRequest,
)
from app.services.documents import ingest_document, queue_extraction

router = APIRouter()


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)) -> Document:
    try:
        result = ingest_document(db, payload.title, payload.text, payload.language)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.document


@router.post("/documents/{document_id}/extract", response_model=JobResponse, status_code=202)
def start_extraction(document_id: int, db: Session = Depends(get_db)) -> Job:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return queue_extraction(db, document)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/documents/{document_id}/records", response_model=list[RecordResponse])
def list_records(
    document_id: int,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[KnowledgeRecord]:
    latest_run_id = (
        select(func.max(ExtractionRun.id))
        .where(ExtractionRun.document_id == document_id)
        .scalar_subquery()
    )
    return list(
        db.scalars(
            select(KnowledgeRecord)
            .options(
                selectinload(KnowledgeRecord.evidence),
                selectinload(KnowledgeRecord.reviews),
            )
            .where(KnowledgeRecord.run_id == latest_run_id)
            .order_by(KnowledgeRecord.id)
            .limit(min(limit, 500))
            .offset(offset)
        ).all()
    )


@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record(record_id: int, db: Session = Depends(get_db)) -> KnowledgeRecord:
    record = db.scalar(
        select(KnowledgeRecord)
        .options(
            selectinload(KnowledgeRecord.evidence),
            selectinload(KnowledgeRecord.reviews),
        )
        .where(KnowledgeRecord.id == record_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.get("/documents/{document_id}/search", response_model=list[RecordResponse])
def search_records(
    document_id: int,
    q: str = Query(min_length=1, max_length=200),
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[KnowledgeRecord]:
    latest_run_id = (
        select(func.max(ExtractionRun.id))
        .where(ExtractionRun.document_id == document_id)
        .scalar_subquery()
    )
    pattern = f"%{q}%"
    return list(
        db.scalars(
            select(KnowledgeRecord)
            .options(
                selectinload(KnowledgeRecord.evidence),
                selectinload(KnowledgeRecord.reviews),
            )
            .outerjoin(KnowledgeRecord.evidence)
            .where(KnowledgeRecord.run_id == latest_run_id)
            .where(
                or_(
                    cast(KnowledgeRecord.payload, Text).ilike(pattern),
                    Evidence.quote.ilike(pattern),
                )
            )
            .distinct()
            .order_by(KnowledgeRecord.id)
            .limit(min(limit, 500))
            .offset(offset)
        ).all()
    )


@router.post("/review/items/{record_id}", response_model=RecordResponse)
def review_record(
    record_id: int,
    payload: ReviewRequest,
    db: Session = Depends(get_db),
) -> KnowledgeRecord:
    record = db.get(KnowledgeRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    if payload.decision == "corrected" and payload.reviewed_value is None:
        raise HTTPException(status_code=422, detail="reviewed_value is required for a correction")

    decision = ReviewDecision(
        record_id=record.id,
        decision=payload.decision,
        original_value=record.payload,
        reviewed_value=payload.reviewed_value,
        reviewer_note=payload.reviewer_note,
    )
    record.review_status = payload.decision
    db.add(decision)
    db.commit()
    db.refresh(record)
    return record
