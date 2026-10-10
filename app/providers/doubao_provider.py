from app.providers.openai_provider import OpenAIProvider


class DoubaoProvider(OpenAIProvider):
    """Adapter for an explicitly configured Doubao OpenAI-compatible endpoint.

    Account endpoint, model availability and live compatibility require verification.
    """
