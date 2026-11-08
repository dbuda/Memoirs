from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, Evidence, ExtractionRun, KnowledgeRecord, Segment
from app.services.documents import ingest_document

TRANSCRIPT = "NORA: Nora Bennett was born in 1949."


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = testing_session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _add_record(
    db: Session,
    run: ExtractionRun,
    segment: Segment,
    record_key: str,
    payload: dict,
    quote: str,
    start: int,
) -> KnowledgeRecord:
    record = KnowledgeRecord(
        run_id=run.id,
        record_type="person" if record_key.startswith("person") else "event",
        record_key=record_key,
        payload=payload,
        confidence=0.9,
        review_status="pending",
    )
    db.add(record)
    db.flush()
    record.evidence.append(
        Evidence(
            extraction_run_id=run.id,
            segment_id=segment.id,
            char_start=start,
            char_end=start + len(quote),
            quote=quote,
        )
    )
    db.commit()
    return record


def _seed(db: Session) -> tuple[int, int]:
    result = ingest_document(db, "Nora", TRANSCRIPT)
    document = result.document
    segment = db.scalars(select(Segment).where(Segment.document_id == document.id)).first()
    assert segment is not None

    old_run = ExtractionRun(
        document_id=document.id,
        provider="fake",
        model="test",
        prompt_version="v1",
        status="completed",
    )
    db.add(old_run)
    db.commit()
    db.refresh(old_run)
    _add_record(
        db,
        old_run,
        segment,
        "person_old",
        {"name": "Old record"},
        "Nora Bennett",
        0,
    )

    latest_run = ExtractionRun(
        document_id=document.id,
        provider="fake",
        model="test",
        prompt_version="v1",
        status="completed",
    )
    db.add(latest_run)
    db.commit()
    db.refresh(latest_run)
    person = _add_record(
        db,
        latest_run,
        segment,
        "person_nora_bennett",
        {"name": "Nora Bennett"},
        "Nora Bennett",
        0,
    )
    _add_record(
        db,
        latest_run,
        segment,
        "event_nora_born__1949",
        {"event_key": "nora_born", "date_text": "1949"},
        "1949",
        segment.text.index("1949"),
    )
    return document.id, person.id


def test_ingestion_is_idempotent(db_session: Session) -> None:
    first = ingest_document(db_session, "Nora", TRANSCRIPT)
    second = ingest_document(db_session, "Nora copy", TRANSCRIPT)

    assert first.created is True
    assert second.created is False
    assert second.document.id == first.document.id


def test_records_endpoint_returns_latest_run_with_pagination(
    client: TestClient, db_session: Session
) -> None:
    document_id, _ = _seed(db_session)

    response = client.get(f"/documents/{document_id}/records")
    assert response.status_code == 200
    keys = {item["record_key"] for item in response.json()}
    assert keys == {"person_nora_bennett", "event_nora_born__1949"}

    paged = client.get(f"/documents/{document_id}/records", params={"limit": 1})
    assert len(paged.json()) == 1

    offset = client.get(f"/documents/{document_id}/records", params={"limit": 1, "offset": 1})
    assert offset.json()[0]["record_key"] != paged.json()[0]["record_key"]


def test_search_matches_payload_and_evidence(client: TestClient, db_session: Session) -> None:
    document_id, _ = _seed(db_session)

    by_name = client.get(f"/documents/{document_id}/search", params={"q": "nora"})
    assert by_name.status_code == 200
    assert {item["record_key"] for item in by_name.json()} == {
        "person_nora_bennett",
        "event_nora_born__1949",
    }

    by_year = client.get(f"/documents/{document_id}/search", params={"q": "1949"})
    assert {item["record_key"] for item in by_year.json()} == {"event_nora_born__1949"}

    missing = client.get(f"/documents/{document_id}/search", params={"q": "1999"})
    assert missing.json() == []


def test_review_correction_and_rejection_change_effective_payload(
    client: TestClient, db_session: Session
) -> None:
    _, record_id = _seed(db_session)

    corrected = client.post(
        f"/review/items/{record_id}",
        json={
            "decision": "corrected",
            "reviewed_value": {"name": "Nora Bennett (reviewed)"},
            "reviewer_note": "Checked against the transcript.",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["effective_payload"] == {"name": "Nora Bennett (reviewed)"}

    fetched = client.get(f"/records/{record_id}")
    assert fetched.status_code == 200
    assert fetched.json()["review_status"] == "corrected"

    rejected = client.post(f"/review/items/{record_id}", json={"decision": "rejected"})
    assert rejected.status_code == 200
    assert rejected.json()["effective_payload"] is None

    missing = client.get("/records/9999")
    assert missing.status_code == 404
