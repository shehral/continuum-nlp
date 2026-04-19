"""Ollama provider — locally-served LLM via Ollama's OpenAI-compatible API.

Used for CS 6120 NLP final project deployment on GCP T4 GPU.
Ollama serves both chat (llama3.1:8b) and embedding (nomic-embed-text) models.
"""

from typing import AsyncIterator

import httpx
from openai import AsyncOpenAI

from config import get_settings
from services.llm_providers.base import BaseEmbeddingProvider, BaseLLMProvider
from utils.logging import get_logger

logger = get_logger(__name__)


class OllamaLLMProvider(BaseLLMProvider):
    """LLM provider using Ollama's OpenAI-compatible API."""

    def __init__(self, model: str | None = None):
        settings = get_settings()
        ollama_host = settings.ollama_host.rstrip("/")
        self.client = AsyncOpenAI(
            base_url=f"{ollama_host}/v1",
            api_key="ollama",  # required by client but ignored by Ollama
        )
        self._model = model or settings.ollama_model

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ) -> tuple[str, dict]:
        response = await self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content or ""
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }

        return content, usage

    async def generate_stream(
        self,
        messages: list[dict],
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Embedding provider using Ollama's native /api/embed endpoint.

    Uses nomic-embed-text (768 dimensions) by default.
    Ollama's embedding endpoint is NOT OpenAI-compatible, so we use httpx directly.
    """

    def __init__(self):
        settings = get_settings()
        self._host = settings.ollama_host.rstrip("/")
        self._model = settings.ollama_embedding_model
        self._dimensions = settings.embedding_dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(
        self,
        texts: list[str],
        input_type: str = "passage",
    ) -> list[list[float]]:
        # Ollama's /api/embed accepts a list of inputs directly
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._host}/api/embed",
                json={
                    "model": self._model,
                    "input": texts,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["embeddings"]
