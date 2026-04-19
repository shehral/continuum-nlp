"""LLM Provider abstraction layer.

Demo serves Ollama (local). The NVIDIA NIM provider is retained as a
documented baseline for the local-vs-cloud comparison in the project
report; switch via LLM_PROVIDER=nvidia. The Amazon Bedrock provider was
archived (out of demo scope).
"""

from config import get_settings
from services.llm_providers.base import BaseEmbeddingProvider, BaseLLMProvider


def get_llm_provider() -> BaseLLMProvider:
    """Factory: return the configured LLM provider."""
    settings = get_settings()
    provider_name = getattr(settings, "llm_provider", "ollama")

    if provider_name == "nvidia":
        from services.llm_providers.nvidia import NvidiaLLMProvider

        return NvidiaLLMProvider()
    # Default: Ollama
    from services.llm_providers.ollama import OllamaLLMProvider

    return OllamaLLMProvider()


def get_embedding_provider() -> BaseEmbeddingProvider:
    """Factory: return the configured embedding provider."""
    settings = get_settings()
    embedding_provider = getattr(settings, "embedding_provider", "ollama")

    if embedding_provider == "nvidia":
        from services.llm_providers.nvidia import NvidiaEmbeddingProvider

        return NvidiaEmbeddingProvider()
    # Default: Ollama
    from services.llm_providers.ollama import OllamaEmbeddingProvider

    return OllamaEmbeddingProvider()


__all__ = [
    "BaseLLMProvider",
    "BaseEmbeddingProvider",
    "get_llm_provider",
    "get_embedding_provider",
]
