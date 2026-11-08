from celery import Task
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.celery_app import celery_app
from app.db import SessionLocal
from app.extraction.chunking import TranscriptSegment
from app.extraction.pipeline import extract_records
from app.models import Evidence, ExtractionRun, Job, KnowledgeRecord, ReviewDecision, Segment


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
            records_by_key = extract_records(segments)

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
