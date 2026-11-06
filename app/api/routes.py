from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Document, ExtractionRun, Job, KnowledgeRecord, ReviewDecision, Segment
from app.schemas import (
    DocumentCreate,
    DocumentResponse,
    JobResponse,
    RecordResponse,
    ReviewRequest,
)
from app.services.ingestion import parse_transcript
from app.tasks import extract_document


router = APIRouter()


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)) -> Document:
    try:
        parsed_segments = parse_transcript(payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    document = Document(title=payload.title, language=payload.language)
    db.add(document)
    db.flush()
    db.add_all(
        [
            Segment(
                document_id=document.id,
                speaker=segment.speaker,
                sequence_number=position,
                text=segment.text,
                char_start=segment.char_start,
                char_end=segment.char_end,
            )
            for position, segment in enumerate(parsed_segments, start=1)
        ]
    )
    db.commit()
    db.refresh(document)
    return document


@router.post("/documents/{document_id}/extract", response_model=JobResponse, status_code=202)
def start_extraction(document_id: int, db: Session = Depends(get_db)) -> Job:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    run = ExtractionRun(document_id=document.id, provider="fake", model="deterministic-demo")
    db.add(run)
    db.flush()
    job = Job(job_type="document_extraction", document_id=document.id, status="pending", attempts=0)
    db.add(job)
    db.commit()
    db.refresh(job)

    task = extract_document.delay(job.id, run.id)
    job.task_id = task.id
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/documents/{document_id}/records", response_model=list[RecordResponse])
def list_records(document_id: int, db: Session = Depends(get_db)) -> list:
    latest_run_id = (
        select(func.max(ExtractionRun.id))
        .where(ExtractionRun.document_id == document_id)
        .scalar_subquery()
    )
    records = db.scalars(
        select(KnowledgeRecord)
        .options(selectinload(KnowledgeRecord.evidence), selectinload(KnowledgeRecord.reviews))
        .where(KnowledgeRecord.run_id == latest_run_id)
        .order_by(KnowledgeRecord.id)
    ).all()
    return records


@router.post("/review/items/{record_id}", response_model=RecordResponse)
def review_record(record_id: int, payload: ReviewRequest, db: Session = Depends(get_db)):
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
