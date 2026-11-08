from app.extraction.chunking import TranscriptSegment, build_chunks
from app.extraction.merge import merge_records
from app.extraction.provider import ExtractionProvider, FakeExtractionProvider
from app.extraction.validation import validate_records
from app.schemas import ExtractedRecord


def extract_records(
    segments: list[TranscriptSegment],
    provider: ExtractionProvider | None = None,
) -> dict[tuple[str, str], ExtractedRecord]:
    """Run the provider over all chunks and merge repeated records by key."""
    active_provider = provider or FakeExtractionProvider()
    records: dict[tuple[str, str], ExtractedRecord] = {}
    for chunk in build_chunks(segments):
        for record in validate_records(active_provider.extract(chunk), segments):
            key = (record.record_type, record.record_key)
            existing = records.get(key)
            if existing is None:
                records[key] = record
            else:
                merge_records(existing, record)
    return records
