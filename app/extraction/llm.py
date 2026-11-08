import json
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.extraction.chunking import ExtractionChunk
from app.schemas import ExtractedRecord

PROMPT_VERSION = "extraction-v1"

_RECORDS_ADAPTER = TypeAdapter(list[ExtractedRecord])

SYSTEM_PROMPT = """You extract structured, evidence-linked records from memoir interviews.
Return only JSON matching the provided schema.

Rules:
- Allowed record_type values: person, event, claim, place, theme.
- Use stable snake_case record_key values. Reuse the same key for the same entity or event.
- Every record needs at least one evidence span.
- segment_id must refer to a segment in the user message.
- char_start and char_end are zero-based offsets into that segment's TEXT, end-exclusive.
- quote must be an exact substring of the referenced segment text.
- Keep explicit facts, inferred values and uncertain dates separate.
- Create separate event records when witnesses give conflicting dates.
- Never invent names, dates or relationships that are not supported by the text.
"""

RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "record_type": {
                        "type": "string",
                        "enum": ["person", "event", "claim", "place", "theme"],
                    },
                    "record_key": {"type": "string"},
                    "payload": {"type": "object", "additionalProperties": True},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "is_explicit": {"type": "boolean"},
                    "is_inferred": {"type": "boolean"},
                    "evidence": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "segment_id": {"type": "integer"},
                                "char_start": {"type": "integer", "minimum": 0},
                                "char_end": {"type": "integer", "minimum": 1},
                                "quote": {"type": "string", "minLength": 1},
                            },
                            "required": ["segment_id", "char_start", "char_end", "quote"],
                        },
                    },
                },
                "required": [
                    "record_type",
                    "record_key",
                    "payload",
                    "confidence",
                    "evidence",
                ],
            },
        }
    },
    "required": ["records"],
}


class ProviderError(RuntimeError):
    pass


def render_chunk(chunk: ExtractionChunk) -> str:
    blocks = []
    for segment in chunk.segments:
        blocks.append(f"SEGMENT {segment.id}\nSPEAKER: {segment.speaker}\nTEXT:\n{segment.text}")
    return "\n\n".join(blocks)


class OpenAICompatibleProvider:
    """Structured-output provider for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def extract(self, chunk: ExtractionChunk) -> list[ExtractedRecord]:
        request = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_chunk(chunk)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction",
                    "schema": RECORD_SCHEMA,
                    "strict": False,
                },
            },
        }
        response = self._client.post("/chat/completions", json=request)
        if response.status_code >= 400:
            raise ProviderError(
                f"LLM request failed with {response.status_code}: {response.text[:500]}"
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError("LLM response did not contain message content") from exc

        if not isinstance(content, str):
            raise ProviderError("LLM response content was not plain JSON text")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc

        records = parsed.get("records") if isinstance(parsed, dict) else None
        if not isinstance(records, list):
            raise ProviderError("LLM response JSON did not contain a records list")

        try:
            return _RECORDS_ADAPTER.validate_python(records)
        except ValidationError as exc:
            raise ProviderError(f"LLM returned invalid records: {exc}") from exc
