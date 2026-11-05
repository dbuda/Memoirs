import pytest

from app.extraction.chunking import TranscriptSegment, build_chunks
from app.extraction.provider import FakeExtractionProvider
from app.extraction.validation import EvidenceValidationError, validate_records


def test_chunking_preserves_segment_context() -> None:
    segments = [
        TranscriptSegment(id=1, speaker="NORA", text="First segment"),
        TranscriptSegment(id=2, speaker="NORA", text="Second segment"),
        TranscriptSegment(id=3, speaker="NORA", text="Third segment"),
    ]

    chunks = build_chunks(segments, max_chars=30, overlap_segments=1)

    assert len(chunks) == 2
    assert chunks[0].segments[0].id == 1
    assert chunks[1].segments[0].id == 2


def test_fake_provider_returns_evidence_backed_records() -> None:
    segment = TranscriptSegment(
        id=1,
        speaker="NORA",
        text="Nora Bennett opened The Lantern cafe with Mei Tan.",
    )

    records = FakeExtractionProvider().extract(build_chunks([segment])[0])
    validated = validate_records(records, [segment])

    assert {record.record_type for record in validated} == {"person", "event"}
    assert all(record.evidence for record in validated)


def test_invalid_evidence_is_rejected() -> None:
    segment = TranscriptSegment(id=1, speaker="NORA", text="Nora Bennett")
    record = FakeExtractionProvider().extract(build_chunks([segment])[0])[0]
    record.evidence[0].quote = "not the source"

    with pytest.raises(EvidenceValidationError, match="does not match"):
        validate_records([record], [segment])
