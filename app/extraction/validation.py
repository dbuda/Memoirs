from collections.abc import Iterable

from app.extraction.chunking import TranscriptSegment
from app.schemas import ExtractedRecord


class EvidenceValidationError(ValueError):
    pass


def validate_record(record: ExtractedRecord, segments: dict[int, TranscriptSegment]) -> ExtractedRecord:
    if not record.evidence:
        raise EvidenceValidationError(f"{record.record_key}: evidence is required")

    for evidence in record.evidence:
        segment = segments.get(evidence.segment_id)
        if segment is None:
            raise EvidenceValidationError(f"{record.record_key}: unknown segment {evidence.segment_id}")
        if evidence.char_end > len(segment.text) or evidence.char_start >= evidence.char_end:
            raise EvidenceValidationError(f"{record.record_key}: evidence offsets are out of bounds")
        actual_quote = segment.text[evidence.char_start : evidence.char_end]
        if actual_quote != evidence.quote:
            raise EvidenceValidationError(f"{record.record_key}: evidence quote does not match source")

    return record


def validate_records(
    records: Iterable[ExtractedRecord], segments: Iterable[TranscriptSegment]
) -> list[ExtractedRecord]:
    segment_map = {segment.id: segment for segment in segments}
    return [validate_record(record, segment_map) for record in records]
