"""Application configuration with secure handling of sensitive values (SEC-007)."""

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with secure secret handling.

    SEC-007: Sensitive fields use SecretStr to prevent accidental exposure
    in logs, error messages, or repr() output.
    """

    # Database - all credentials must be set via environment variables
    database_url: str = ""  # e.g., postgresql+asyncpg://user:pass@localhost:5432/dbname

    @field_validator("database_url", mode="after")
    @classmethod
    def ensure_asyncpg_driver(cls, v: str) -> str:
        """Convert postgresql:// to postgresql+asyncpg:// for async support."""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    neo4j_uri: str = (
        ""  # e.g., bolt://localhost:7687 or neo4j+s://xxx.databases.neo4j.io
    )
    neo4j_user: str = ""
    neo4j_password: SecretStr = SecretStr("")  # SEC-007: Use SecretStr for passwords
    redis_url: str = ""  # e.g., redis://localhost:6379

    # Provider selection
    llm_provider: str = "ollama"  # "ollama", "nvidia", or "bedrock"
    embedding_provider: str = "ollama"  # "ollama", "nvidia", or "bedrock"

    # Ollama settings (local LLM serving)
    ollama_host: str = "http://ollama:11434"  # Docker service name
    ollama_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768  # nomic-embed-text: 768, NV-EmbedQA: 2048

    # AI Provider (NVIDIA NIM) - SEC-007: Use SecretStr for API keys
    nvidia_api_key: SecretStr = SecretStr("")
    nvidia_model: str = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

    # Amazon Bedrock settings (used when llm_provider="bedrock")
    bedrock_model_id: str = "anthropic.claude-sonnet-4-20250514"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    aws_region: str = "us-west-2"

    # Datadog observability
    dd_trace_enabled: bool = False

    # Embedding Model (NVIDIA NV-EmbedQA) - SEC-007: Use SecretStr for API keys
    nvidia_embedding_api_key: SecretStr = SecretStr("")
    nvidia_embedding_model: str = "nvidia/llama-3.2-nv-embedqa-1b-v2"

    # Embedding cache settings (ML-P1-2)
    embedding_cache_ttl: int = 86400 * 30  # 30 days in seconds
    embedding_cache_min_text_length: int = 10  # Minimum text length to cache
    # SD-QW-002: Embedding batch size for bulk operations
    # Tradeoff: Larger batches = fewer API calls but more memory per request
    # NVIDIA NIM embedding API supports up to ~256 texts per batch
    # Default 32 balances throughput with memory usage and rate limit (30 req/min)
    embedding_batch_size: int = 32

    # Rate limiting
    rate_limit_requests: int = 30  # requests per minute
    rate_limit_window: int = 60  # seconds

    # LLM retry settings (ML-P0-1)
    llm_max_retries: int = 3  # Maximum retry attempts for LLM calls
    llm_retry_base_delay: float = 1.0  # Base delay in seconds for exponential backoff

    # LLM prompt size limits (ML-P1-3)
    # Llama 3.3 Nemotron has 128k context
    max_prompt_tokens: int = 70000  # Maximum input tokens (handles very large conversations)
    prompt_warning_threshold: float = 0.8  # Warn when prompt exceeds this % of max

    # LLM response cache settings (KG-P0-2)
    llm_cache_enabled: bool = True  # Enable/disable LLM response caching
    llm_cache_ttl: int = 86400  # 24 hours in seconds (default)
    llm_extraction_prompt_version: str = (
        "v1"  # Bump when prompts change to invalidate cache
    )
    # LLM model fallback settings (ML-QW-2)
    # If primary model fails, fall back to a secondary model
    llm_fallback_model: str = "nvidia/llama-3.1-nemotron-70b-instruct"  # Fallback model
    llm_fallback_enabled: bool = True  # Enable/disable fallback behavior

    # Entity cache settings (SD-011)
    entity_cache_ttl: int = 300  # 5 minutes in seconds
    entity_cache_enabled: bool = True

    # Message batch settings (SD-010)
    message_batch_size: int = 10  # Flush after N messages
    message_batch_timeout: float = 2.0  # Flush after N seconds

    # Similarity thresholds (KG-P2-2: Configurable thresholds)
    # Decision similarity (ML-P1-4)
    similarity_threshold: float = 0.85  # Minimum similarity for SIMILAR_TO edges
    high_confidence_similarity_threshold: float = 0.90  # For high-confidence matches
    # Entity resolution thresholds
    fuzzy_match_threshold: float = (
        0.85  # Fuzzy string matching threshold (0-1 scale, 85%)
    )
    embedding_similarity_threshold: float = (
        0.90  # Embedding cosine similarity threshold
    )

    # Decision embedding field weights (KG-P1-5)
    # Higher weights increase importance in semantic search
    decision_embedding_weight_title: float = 1.5  # Title gets 1.5x weight
    decision_embedding_weight_decision: float = 1.2  # Decision field gets 1.2x weight
    decision_embedding_weight_rationale: float = 1.0  # Rationale gets base weight
    decision_embedding_weight_context: float = 0.8  # Context gets 0.8x weight
    decision_embedding_weight_trigger: float = 0.8  # Trigger gets 0.8x weight

    # Paths
    claude_logs_path: str = "~/.claude/projects"

    # Auth - SEC-007: Use SecretStr for secret key
    secret_key: SecretStr = SecretStr("")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # App
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def __repr__(self) -> str:
        """Custom repr that masks sensitive values (SEC-007)."""
        # Only show non-sensitive fields in repr
        safe_fields = {
            "database_url": self._mask_url(self.database_url),
            "neo4j_uri": self.neo4j_uri,
            "neo4j_user": self.neo4j_user,
            "redis_url": self._mask_url(self.redis_url),
            "nvidia_model": self.nvidia_model,
            "nvidia_embedding_model": self.nvidia_embedding_model,
            "rate_limit_requests": self.rate_limit_requests,
            "max_prompt_tokens": self.max_prompt_tokens,
            "claude_logs_path": self.claude_logs_path,
            "algorithm": self.algorithm,
            "debug": self.debug,
            "cors_origins": self.cors_origins,
        }
        fields_str = ", ".join(f"{k}={v!r}" for k, v in safe_fields.items())
        return f"Settings({fields_str})"

    @staticmethod
    def _mask_url(url: str) -> str:
        """Mask password in database URLs."""
        if not url:
            return url
        # Simple masking for URLs with passwords
        import re

        return re.sub(r":([^:@]+)@", ":***@", url)

    def get_nvidia_api_key(self) -> str:
        """Safely get NVIDIA API key value."""
        return self.nvidia_api_key.get_secret_value()

    def get_nvidia_embedding_api_key(self) -> str:
        """Safely get NVIDIA embedding API key value."""
        return self.nvidia_embedding_api_key.get_secret_value()

    def get_secret_key(self) -> str:
        """Safely get JWT secret key value."""
        return self.secret_key.get_secret_value()

    def get_neo4j_password(self) -> str:
        """Safely get Neo4j password value."""
        return self.neo4j_password.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
