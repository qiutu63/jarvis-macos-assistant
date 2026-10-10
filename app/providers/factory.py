from app.config.settings import Settings
from app.providers.mock_provider import MockProvider
from app.providers.openai_provider import OpenAIProvider


def create_provider(settings: Settings):
    if settings.provider == "mock":
        return MockProvider()
    # Ollama Cloud exposes OpenAI-compatible Chat Completions at ollama.com/v1.
    return OpenAIProvider(api_key=settings.api_key.get_secret_value(), base_url=settings.base_url,
                          model=settings.model, timeout=settings.request_timeout)
