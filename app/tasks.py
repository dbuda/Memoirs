from celery import Task
from sqlalchemy import select

from app.celery_app import celery_app
from app.db import SessionLocal
from app.extraction.chunking import TranscriptSegment, build_chunks
from app.extraction.provider import FakeExtractionProvider
from app.extraction.validation import validate_records
from app.models import Evidence, ExtractionRun, Job, KnowledgeRecord, Segment


class RetryableExtractionError(RuntimeError):
    pass


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
                select(Segment).where(Segment.document_id == run.document_id).order_by(Segment.sequence_number)
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
                    records_by_key.setdefault((record.record_type, record.record_key), record)

            for record in records_by_key.values():
                db_record = KnowledgeRecord(
                    run_id=run.id,
                    record_type=record.record_type,
                    record_key=record.record_key,
                    payload=record.payload,
                    confidence=record.confidence,
                    is_explicit=record.is_explicit,
                    is_inferred=record.is_inferred,
                    review_status="pending",
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

            run.status = "completed"
            job.status = "completed"
            db.commit()
            return {"status": "completed", "job_id": job.id, "records": len(records_by_key)}
        except ConnectionError as exc:
            job.status = "retrying"
            job.error_message = str(exc)
            db.commit()
            raise self.retry(exc=exc, countdown=5)
        except Exception as exc:
            run.status = "failed"
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()
            raise
