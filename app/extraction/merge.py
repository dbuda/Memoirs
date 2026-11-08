from app.schemas import ExtractedRecord

MAX_EVIDENCE_PER_RECORD = 8


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
