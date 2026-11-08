import argparse
import json
from pathlib import Path

from app.db import SessionLocal
from app.services.documents import ingest_document, queue_extraction

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "fictional_interviews"


def seed(extract: bool = True) -> None:
    fixtures = sorted(DATA_DIR.glob("*.json"))
    if not fixtures:
        raise SystemExit(f"No JSON fixtures found in {DATA_DIR}")

    with SessionLocal() as db:
        for fixture in fixtures:
            payload = json.loads(fixture.read_text(encoding="utf-8"))
            result = ingest_document(
                db,
                title=payload["title"],
                text=payload["text"],
                language=payload.get("language", "en"),
            )
            state = "created" if result.created else "already exists"
            print(f"{fixture.name}: document {result.document.id} {state}")
            if extract and result.created:
                job = queue_extraction(db, result.document)
                print(f"  queued extraction job {job.id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load fictional interviews into the demo database."
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Only create documents; do not queue extraction jobs.",
    )
    args = parser.parse_args()
    seed(extract=not args.no_extract)


if __name__ == "__main__":
    main()
