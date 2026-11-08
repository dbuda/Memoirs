import re
from typing import Protocol

from app.extraction.chunking import ExtractionChunk
from app.schemas import EvidenceInput, ExtractedRecord


class ExtractionProvider(Protocol):
    def extract(self, chunk: ExtractionChunk) -> list[ExtractedRecord]:
        """Return candidate records for one context-preserving chunk."""


class FakeExtractionProvider:
    """Deterministic provider for local development and regression tests.

    It intentionally extracts a small set of obvious records. The important
    contract is the same one a real structured-output LLM provider will use:
    every candidate carries confidence and source evidence.
    """

    PERSON_PATTERNS = {
        "Nora Bennett": re.compile(r"\bNora Bennett\b"),
        "Priya Bennett": re.compile(r"\bPriya Bennett\b"),
        "Mei Tan": re.compile(r"\bMei Tan\b"),
        "Mei Chen": re.compile(r"\bMei Chen\b"),
        "Alan Bennett": re.compile(r"\bAlan Bennett\b"),
    }

    def extract(self, chunk: ExtractionChunk) -> list[ExtractedRecord]:
        records: list[ExtractedRecord] = []
        seen: set[tuple[str, str]] = set()

        for segment in chunk.segments:
            for canonical_name, pattern in self.PERSON_PATTERNS.items():
                match = pattern.search(segment.text)
                if not match:
                    continue
                key = ("person", canonical_name.lower())
                if key in seen:
                    continue
                seen.add(key)
                records.append(
                    ExtractedRecord(
                        record_type="person",
                        record_key=canonical_name.lower().replace(" ", "_"),
                        payload={"name": canonical_name},
                        confidence=0.99,
                        evidence=[self._evidence(segment, match.start(), match.end())],
                    )
                )

            lantern = re.search(r"\bThe Lantern\b", segment.text)
            if lantern and ("cafe" in segment.text.lower() or "opened" in segment.text.lower()):
                key = ("event", "the_lantern_opened")
                if key not in seen:
                    seen.add(key)
                    records.append(
                        ExtractedRecord(
                            record_type="event",
                            record_key="the_lantern_opened",
                            payload={
                                "name": "The Lantern opening",
                                "date_precision": "uncertain_year",
                            },
                            confidence=0.82,
                            is_explicit=False,
                            is_inferred=True,
                            evidence=[self._evidence(segment, lantern.start(), lantern.end())],
                        )
                    )

        return records

    @staticmethod
    def _evidence(segment, start: int, end: int) -> EvidenceInput:
        return EvidenceInput(
            segment_id=segment.id,
            char_start=start,
            char_end=end,
            quote=segment.text[start:end],
        )
