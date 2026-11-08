import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, ExtractionRun, Job, Segment
from app.services.ingestion import parse_transcript
from app.tasks import extract_document


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IngestResult:
    document: Document
    created: bool


def ingest_document(
    db: Session,
    title: str,
    text: str,
    language: str = "en",
) -> IngestResult:
    digest = content_hash(text)
    existing = db.scalar(select(Document).where(Document.content_hash == digest))
    if existing is not None:
        return IngestResult(document=existing, created=False)

    segments = parse_transcript(text)
    document = Document(
        title=title,
        language=language,
        content_hash=digest,
    )
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
            for position, segment in enumerate(segments, start=1)
        ]
    )
    db.commit()
    db.refresh(document)
    return IngestResult(document=document, created=True)


def queue_extraction(
    db: Session,
    document: Document,
    provider: str = "fake",
    model: str = "deterministic-demo",
    prompt_version: str = "v1",
) -> Job:
    run = ExtractionRun(
        document_id=document.id,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
    )
    db.add(run)
    db.flush()
    job = Job(
        job_type="document_extraction",
        document_id=document.id,
        status="pending",
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = extract_document.delay(job.id, run.id)
    job.task_id = task.id
    db.commit()
    db.refresh(job)
    return job
