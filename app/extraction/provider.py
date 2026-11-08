import re
from typing import Protocol

from app.extraction.chunking import ExtractionChunk, TranscriptSegment
from app.extraction.dates import parse_date_expression
from app.extraction.rules import (
    CLAIM_PATTERNS,
    EVENT_PATTERNS,
    PEOPLE,
    PLACES,
    THEMES,
    UNCERTAINTY_CUES,
)
from app.schemas import EvidenceInput, ExtractedRecord

_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
_MONTH_PRECISIONS = {"day", "month"}


class ExtractionProvider(Protocol):
    def extract(self, chunk: ExtractionChunk) -> list[ExtractedRecord]:
        """Return candidate records for one context-preserving chunk."""


def _surface_pattern(surface: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(surface)}\b", re.IGNORECASE)


def _slug(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", value.lower()).strip("_")


def _sentence_span(text: str, position: int) -> tuple[int, int]:
    start = 0
    end = len(text)
    for match in _SENTENCE_END.finditer(text):
        if match.end() <= position:
            start = match.end()
        else:
            end = match.end()
            break
    while start < position and text[start].isspace():
        start += 1
    return start, end


def _is_uncertain(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in UNCERTAINTY_CUES)


class FakeExtractionProvider:
    """Deterministic baseline provider for local development and regression tests.

    The class name is kept for compatibility with existing jobs. It now covers
    people, aliases, places, dated events, explicit relationships and themes.
    Every candidate still carries confidence and exact source evidence, which is
    the same contract a structured-output LLM provider must satisfy.
    """

    def __init__(self) -> None:
        self._people = self._compile_catalog(PEOPLE)
        self._places = self._compile_catalog(PLACES)
        self._events = [
            {**pattern, "compiled": re.compile(pattern["pattern"], re.IGNORECASE)}
            for pattern in EVENT_PATTERNS
        ]
        self._claims = [
            {**pattern, "compiled": re.compile(pattern["pattern"], re.IGNORECASE)}
            for pattern in CLAIM_PATTERNS
        ]
        self._themes = {
            theme: [re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE) for keyword in keywords]
            for theme, keywords in THEMES.items()
        }
        self._theme_keywords = THEMES

    @staticmethod
    def _compile_catalog(
        catalog: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        compiled: list[dict[str, object]] = []
        for entry in catalog:
            for surface in entry["surfaces"]:
                compiled.append(
                    {
                        "key": entry["key"],
                        "name": entry["name"],
                        "surface": surface,
                        "compiled": _surface_pattern(surface),
                    }
                )
        compiled.sort(key=lambda item: len(item["surface"]), reverse=True)
        return compiled

    def extract(self, chunk: ExtractionChunk) -> list[ExtractedRecord]:
        records: list[ExtractedRecord] = []
        for segment in chunk.segments:
            records.extend(self._extract_catalog(segment, self._people, "person"))
            records.extend(self._extract_catalog(segment, self._places, "place"))
            records.extend(self._extract_events(segment))
            records.extend(self._extract_claims(segment))
            records.extend(self._extract_themes(segment))
        return records

    def _extract_catalog(
        self,
        segment: TranscriptSegment,
        catalog: list[dict[str, object]],
        record_type: str,
    ) -> list[ExtractedRecord]:
        matches: list[tuple[int, int, dict[str, object]]] = []
        for entry in catalog:
            match = entry["compiled"].search(segment.text)
            if match:
                matches.append((match.start(), match.end(), entry))

        matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        chosen: list[tuple[int, int, dict[str, object]]] = []
        for match in matches:
            if any(not (match[1] <= other[0] or match[0] >= other[1]) for other in chosen):
                continue
            chosen.append(match)

        records: list[ExtractedRecord] = []
        seen: set[str] = set()
        for start, end, entry in sorted(chosen, key=lambda item: item[0]):
            key = str(entry["key"])
            if key in seen:
                continue
            seen.add(key)
            surface = str(entry["surface"])
            name = str(entry["name"])
            payload: dict[str, object] = {"name": name}
            is_alias = surface.lower() != name.lower()
            if is_alias:
                payload["aliases"] = [surface]
            records.append(
                ExtractedRecord(
                    record_type=record_type,
                    record_key=f"{record_type}_{key}",
                    payload=payload,
                    confidence=0.8 if is_alias else 0.95,
                    is_explicit=not is_alias,
                    is_inferred=is_alias,
                    evidence=[self._evidence(segment, start, end)],
                )
            )
        return records

    def _extract_events(self, segment: TranscriptSegment) -> list[ExtractedRecord]:
        records: list[ExtractedRecord] = []
        for pattern in self._events:
            speakers = pattern.get("speakers")
            if speakers and segment.speaker.upper() not in speakers:
                continue
            seen: set[str] = set()
            for match in pattern["compiled"].finditer(segment.text):
                sentence_start, sentence_end = _sentence_span(segment.text, match.start())
                sentence = segment.text[sentence_start:sentence_end]
                date = (
                    parse_date_expression(match.group(0))
                    or parse_date_expression(sentence[match.end() - sentence_start :])
                    or parse_date_expression(sentence)
                    or parse_date_expression(segment.text)
                )
                uncertain = _is_uncertain(sentence)

                if date and date["date_text"] not in sentence:
                    quote_start, quote_end = 0, len(segment.text)
                else:
                    quote_start, quote_end = sentence_start, sentence_end

                key = str(pattern["key"])
                if date and date["date_start"]:
                    key = f"{key}__{_slug(str(date['date_start']))}"
                if key in seen:
                    continue
                seen.add(key)

                payload: dict[str, object] = {
                    "event_key": pattern["key"],
                    "name": pattern["summary"],
                    "event_type": pattern["event_type"],
                }
                if pattern.get("subject"):
                    payload["subject"] = pattern["subject"]
                if date:
                    payload.update(
                        {
                            "date_text": date["date_text"],
                            "date_start": date["date_start"],
                            "date_end": date["date_end"],
                            "date_precision": date["date_precision"],
                            "is_relative": date["is_relative"],
                        }
                    )
                else:
                    payload["date_precision"] = "unknown"

                precision = str(date["date_precision"]) if date else "unknown"
                confidence = 0.55
                if date:
                    confidence = 0.88 if precision in _MONTH_PRECISIONS else 0.8
                if uncertain:
                    confidence = min(confidence, 0.62)

                records.append(
                    ExtractedRecord(
                        record_type="event",
                        record_key=f"event_{key}",
                        payload=payload,
                        confidence=confidence,
                        is_explicit=not uncertain,
                        is_inferred=uncertain,
                        evidence=[self._evidence(segment, quote_start, quote_end)],
                    )
                )
        return records

    def _extract_claims(self, segment: TranscriptSegment) -> list[ExtractedRecord]:
        records: list[ExtractedRecord] = []
        for pattern in self._claims:
            speakers = pattern.get("speakers")
            if speakers and segment.speaker.upper() not in speakers:
                continue
            match = pattern["compiled"].search(segment.text)
            if not match:
                continue
            start, end = _sentence_span(segment.text, match.start())
            records.append(
                ExtractedRecord(
                    record_type="claim",
                    record_key=f"claim_{pattern['key']}",
                    payload={
                        "subject": pattern["subject"],
                        "predicate": pattern["predicate"],
                        "object": pattern["object"],
                        "claim_text": segment.text[start:end].strip(),
                    },
                    confidence=0.86,
                    evidence=[self._evidence(segment, start, end)],
                )
            )
        return records

    def _extract_themes(self, segment: TranscriptSegment) -> list[ExtractedRecord]:
        records: list[ExtractedRecord] = []
        for theme, patterns in self._themes.items():
            match = next(
                (found for pattern in patterns if (found := pattern.search(segment.text))),
                None,
            )
            if match is None:
                continue
            start, end = _sentence_span(segment.text, match.start())
            records.append(
                ExtractedRecord(
                    record_type="theme",
                    record_key=f"theme_{theme}",
                    payload={
                        "theme": theme,
                        "keywords": self._theme_keywords[theme],
                    },
                    confidence=0.55,
                    is_explicit=False,
                    is_inferred=True,
                    evidence=[self._evidence(segment, start, end)],
                )
            )
        return records

    @staticmethod
    def _evidence(segment: TranscriptSegment, start: int, end: int) -> EvidenceInput:
        return EvidenceInput(
            segment_id=segment.id,
            char_start=start,
            char_end=end,
            quote=segment.text[start:end],
        )
