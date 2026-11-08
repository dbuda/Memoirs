from celery import Task
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.celery_app import celery_app
from app.db import SessionLocal
from app.extraction.chunking import TranscriptSegment, build_chunks
from app.extraction.provider import FakeExtractionProvider
from app.extraction.validation import validate_records
from app.models import Evidence, ExtractionRun, Job, KnowledgeRecord, ReviewDecision, Segment
from app.schemas import ExtractedRecord

MAX_EVIDENCE_PER_RECORD = 8


class RetryableExtractionError(RuntimeError):
    pass


def merge_records(target: ExtractedRecord, source: ExtractedRecord) -> None:
    """Merge repeated mentions of the same record across chunk boundaries."""
    aliases = set(target.payload.get("aliases", []))
    aliases.update(source.payload.get("aliases", []))
    if aliases:
        target.payload["aliases"] = sorted(aliases)

    for key, value in source.payload.items():
        if key == "aliases":
            continue
        if key not in target.payload or target.payload[key] in (None, ""):
            target.payload[key] = value

    spans = {(item.segment_id, item.char_start, item.char_end) for item in target.evidence}
    for item in source.evidence:
        span = (item.segment_id, item.char_start, item.char_end)
        if span in spans or len(target.evidence) >= MAX_EVIDENCE_PER_RECORD:
            continue
        target.evidence.append(item)
        spans.add(span)

    target.confidence = max(target.confidence, source.confidence)
    target.is_explicit = target.is_explicit or source.is_explicit
    target.is_inferred = target.is_inferred and source.is_inferred


class DatabaseTask(Task):
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        with SessionLocal() as db:
            job_id = args[0]
            job = db.get(Job, job_id)
            if job and job.status not in {"completed", "failed"}:
                job.status = "failed"
                job.error_message = str(exc)
                db.commit()


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="memoirs.extract_document",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def extract_document(self, job_id: int, run_id: int) -> dict[str, int | str]:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        run = db.get(ExtractionRun, run_id)
        if job is None or run is None:
            raise ValueError("Extraction job or run not found")

        if job.status == "completed":
            return {"status": "completed", "job_id": job.id}

        job.status = "running"
        job.attempts += 1
        run.status = "running"
        db.commit()

        try:
            source_segments = db.scalars(
                select(Segment)
                .where(Segment.document_id == run.document_id)
                .order_by(Segment.sequence_number)
            ).all()
            segments = [
                TranscriptSegment(
                    id=segment.id,
                    speaker=segment.speaker,
                    text=segment.text,
                    char_start=segment.char_start,
                )
                for segment in source_segments
            ]
            provider = FakeExtractionProvider()
            records_by_key = {}
            for chunk in build_chunks(segments):
                for record in validate_records(provider.extract(chunk), segments):
                    key = (record.record_type, record.record_key)
                    existing = records_by_key.get(key)
                    if existing is None:
                        records_by_key[key] = record
                    else:
                        merge_records(existing, record)

            previous_records = db.scalars(
                select(KnowledgeRecord)
                .join(ExtractionRun)
                .options(selectinload(KnowledgeRecord.reviews))
                .where(
                    ExtractionRun.document_id == run.document_id,
                    ExtractionRun.id != run.id,
                )
                .order_by(KnowledgeRecord.id.desc())
            ).all()
            previous_by_key = {}
            for previous in previous_records:
                previous_by_key.setdefault((previous.record_type, previous.record_key), previous)

            for record in records_by_key.values():
                previous = previous_by_key.get((record.record_type, record.record_key))
                previous_review = (
                    max(previous.reviews, key=lambda review: review.id)
                    if previous and previous.reviews
                    else None
                )
                db_record = KnowledgeRecord(
                    run_id=run.id,
                    record_type=record.record_type,
                    record_key=record.record_key,
                    payload=record.payload,
                    confidence=record.confidence,
                    is_explicit=record.is_explicit,
                    is_inferred=record.is_inferred,
                    review_status=previous_review.decision if previous_review else "pending",
                )
                db.add(db_record)
                db.flush()
                for source in record.evidence:
                    db_evidence = Evidence(
                        extraction_run_id=run.id,
                        segment_id=source.segment_id,
                        char_start=source.char_start,
                        char_end=source.char_end,
                        quote=source.quote,
                    )
                    db_record.evidence.append(db_evidence)

                if previous_review:
                    db_record.reviews.append(
                        ReviewDecision(
                            decision=previous_review.decision,
                            original_value=record.payload,
                            reviewed_value=previous_review.reviewed_value,
                            reviewer_note="Carried forward from the previous extraction run.",
                        )
                    )

            run.status = "completed"
            job.status = "completed"
            db.commit()
            return {"status": "completed", "job_id": job.id, "records": len(records_by_key)}
        except ConnectionError as exc:
            job.status = "retrying"
            job.error_message = str(exc)
            db.commit()
            raise self.retry(exc=exc, countdown=5) from exc
        except Exception as exc:
            run.status = "failed"
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()
            raise
