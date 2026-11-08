from app.config import get_settings
from app.extraction.llm import OpenAICompatibleProvider, ProviderError
from app.extraction.provider import ExtractionProvider, FakeExtractionProvider


def build_provider(name: str | None = None) -> ExtractionProvider:
    settings = get_settings()
    selected = (name or settings.llm_provider).strip().lower()

    if selected in {"fake", "deterministic"}:
        return FakeExtractionProvider()
    if selected in {"openai", "openai-compatible", "llm"}:
        if not settings.llm_api_key:
            raise ProviderError("LLM_API_KEY is required for the LLM provider")
        return OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
    raise ValueError(f"Unknown extraction provider: {selected}")
