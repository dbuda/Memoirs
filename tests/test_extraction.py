import pytest

from app.extraction.chunking import TranscriptSegment, build_chunks
from app.extraction.dates import parse_date_expression
from app.extraction.provider import FakeExtractionProvider
from app.extraction.validation import EvidenceValidationError, validate_records
from app.services.ingestion import parse_transcript


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

    assert {"person", "event"} <= {record.record_type for record in validated}
    assert all(record.evidence for record in validated)


def test_invalid_evidence_is_rejected() -> None:
    segment = TranscriptSegment(id=1, speaker="NORA", text="Nora Bennett")
    record = FakeExtractionProvider().extract(build_chunks([segment])[0])[0]
    record.evidence[0].quote = "not the source"

    with pytest.raises(EvidenceValidationError, match="does not match"):
        validate_records([record], [segment])


def test_ingestion_accepts_transcripts_without_timestamps() -> None:
    segments = parse_transcript("NORA: Nora Bennett opened The Lantern cafe.\n")

    assert len(segments) == 1
    assert segments[0].speaker == "NORA"
    assert segments[0].text == "Nora Bennett opened The Lantern cafe."


def test_date_precision_is_preserved() -> None:
    assert parse_date_expression("born in the spring of 1949") == {
        "date_text": "spring of 1949",
        "date_start": "1949",
        "date_end": "1949",
        "date_precision": "season",
        "is_relative": False,
        "matched_text": "spring of 1949",
    }
    assert parse_date_expression("says January 1, 1979")["date_precision"] == "day"
    assert parse_date_expression("separated in the late eighties") == {
        "date_text": "late eighties",
        "date_start": "1985",
        "date_end": "1989",
        "date_precision": "decade",
        "is_relative": False,
        "matched_text": "late eighties",
    }
    assert parse_date_expression("two years later")["date_precision"] == "relative"


def test_extraction_links_aliases_and_dated_events() -> None:
    segment = TranscriptSegment(
        id=1,
        speaker="NORA",
        text="I was born in the spring of 1949 and my sisters called me Norrie.",
    )

    records = FakeExtractionProvider().extract(build_chunks([segment])[0])
    by_key = {record.record_key: record for record in records}

    assert by_key["person_nora_bennett"].payload["aliases"] == ["Norrie"]
    event = by_key["event_nora_born__1949"]
    assert event.payload["date_precision"] == "season"
    assert event.payload["date_start"] == "1949"


def test_conflicting_event_dates_are_both_preserved() -> None:
    segments = [
        TranscriptSegment(id=1, speaker="NORA", text="The Lantern opened in March 1992."),
        TranscriptSegment(id=2, speaker="NORA", text="The Lantern opened in 1991."),
    ]

    records = FakeExtractionProvider().extract(build_chunks(segments)[0])
    openings = [
        record for record in records if record.record_key.startswith("event_the_lantern_opened")
    ]

    assert {record.payload["event_key"] for record in openings} == {"the_lantern_opened"}
    assert {record.payload["date_start"] for record in openings} == {"1992-03", "1991"}


def test_uncertain_dates_are_marked_inferred() -> None:
    segment = TranscriptSegment(
        id=1,
        speaker="NORA",
        text="I met her at an evening English class, probably in 1988.",
    )

    records = FakeExtractionProvider().extract(build_chunks([segment])[0])
    event = next(record for record in records if record.record_key == "event_nora_mei_met__1988")

    assert event.is_inferred is True
    assert event.is_explicit is False
    assert event.confidence <= 0.62


def test_claims_capture_explicit_relationships() -> None:
    segment = TranscriptSegment(
        id=1,
        speaker="NORA",
        text="We married in September 1970 at St Luke's.",
    )

    records = FakeExtractionProvider().extract(build_chunks([segment])[0])
    claim = next(
        record
        for record in records
        if record.record_key == "claim_nora_bennett_married_to_alan_bennett"
    )

    assert claim.payload["subject"] == "nora_bennett"
    assert claim.payload["predicate"] == "married_to"
    assert claim.payload["object"] == "alan_bennett"


def test_metadata_headers_are_not_treated_as_speaker_lines() -> None:
    segments = parse_transcript(
        "TITLE: An Interview with Nora Bennett\n"
        "SUBJECT: Nora Bennett\n"
        "INTERVIEWER: Helen Ward\n"
        "NORA: I was born in 1949.\n"
    )

    assert [segment.speaker for segment in segments] == ["NORA"]
    assert segments[0].text == "I was born in 1949."
