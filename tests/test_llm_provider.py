import json

import httpx
import pytest

from app.extraction.chunking import TranscriptSegment, build_chunks
from app.extraction.factory import build_provider
from app.extraction.llm import OpenAICompatibleProvider, ProviderError
from app.extraction.validation import validate_records


def _chunk():
    segment = TranscriptSegment(id=7, speaker="NORA", text="Nora Bennett was born in 1949.")
    return segment, build_chunks([segment])[0]


def _completion(records: list[dict]) -> dict:
    return {
        "choices": [
            {"message": {"content": json.dumps({"records": records})}},
        ]
    }


def test_llm_provider_sends_schema_and_validates_records() -> None:
    segment, chunk = _chunk()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json=_completion(
                [
                    {
                        "record_type": "person",
                        "record_key": "person_nora_bennett",
                        "payload": {"name": "Nora Bennett"},
                        "confidence": 0.9,
                        "is_explicit": True,
                        "is_inferred": False,
                        "evidence": [
                            {
                                "segment_id": 7,
                                "char_start": 0,
                                "char_end": 12,
                                "quote": "Nora Bennett",
                            }
                        ],
                    }
                ]
            ),
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://llm.test/v1",
    )
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    records = provider.extract(chunk)
    validated = validate_records(records, [segment])

    assert captured["model"] == "test-model"
    assert captured["response_format"]["type"] == "json_schema"
    assert "SEGMENT 7" in captured["messages"][1]["content"]
    assert validated[0].record_key == "person_nora_bennett"


def test_llm_provider_raises_on_api_error() -> None:
    _, chunk = _chunk()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom")),
        base_url="https://llm.test/v1",
    )
    provider = OpenAICompatibleProvider(api_key="k", model="m", client=client)

    with pytest.raises(ProviderError, match="500"):
        provider.extract(chunk)


def test_llm_provider_raises_on_invalid_json() -> None:
    _, chunk = _chunk()
    response = {"choices": [{"message": {"content": "not json"}}]}
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
        base_url="https://llm.test/v1",
    )
    provider = OpenAICompatibleProvider(api_key="k", model="m", client=client)

    with pytest.raises(ProviderError, match="invalid JSON"):
        provider.extract(chunk)


def test_provider_factory_selects_the_deterministic_provider() -> None:
    assert build_provider("fake").__class__.__name__ == "FakeExtractionProvider"

    with pytest.raises(ValueError, match="Unknown extraction provider"):
        build_provider("missing")
