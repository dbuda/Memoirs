from fastapi.testclient import TestClient

from app.celery_app import celery_app
from app.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_extraction_task_is_registered() -> None:
    assert "memoirs.extract_document" in celery_app.tasks
