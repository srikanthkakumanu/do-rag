"""Typed application settings, loaded from the environment / `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

type Vectorizer = Literal["text2vec-openai", "none"]
type ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]

# This project's own .env (hybrid-rag/.env), independent of the working directory.
PROJECT_ENV_FILE: Final = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Single source of configuration. Inject it; never read `os.environ` directly."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ENV_FILE, env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    # OpenAI
    openai_api_key: SecretStr = Field(default=SecretStr(""))
    openai_chat_model: str = "gpt-5.4-mini"  # answers; override with OPENAI_CHAT_MODEL
    openai_fast_model: str = "gpt-5.4-nano"  # extraction + graph plan; "" -> chat model
    openai_embed_model: str = "text-embedding-3-small"
    openai_temperature: float | None = Field(default=None, ge=0.0, le=0.2)
    # Reasoning models only (e.g., gpt-5.x); omitted when unset.
    openai_reasoning_effort: ReasoningEffort | None = "low"
    openai_fast_reasoning_effort: ReasoningEffort | None = "none"
    openai_timeout_s: float = Field(default=30.0, gt=0)
    max_output_tokens: int = Field(default=600, gt=0)

    # Weaviate
    weaviate_url: str = "http://localhost:8082"
    weaviate_grpc_port: int = 50053
    weaviate_api_key: SecretStr = Field(default=SecretStr(""))
    weaviate_vectorizer: Vectorizer = "text2vec-openai"
    collection_name: str = "PolicyChunk"

    # Neo4j (knowledge graph); empty password = no auth (local dev only)
    neo4j_uri: str = "bolt://localhost:7688"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = Field(default=SecretStr(""))
    neo4j_database: str = "neo4j"
    neo4j_timeout_s: float = Field(default=10.0, gt=0)
    graph_max_facts: int = Field(default=12, gt=0, le=50)
    extract_concurrency: int = Field(default=4, gt=0, le=16)

    # Retrieval
    hybrid_alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    top_k: int = Field(default=5, gt=0, le=20)
    min_score: float = Field(default=0.0, ge=0.0)
    max_vector_distance: float | None = Field(default=0.75, gt=0.0, le=2.0)

    # Generation
    prompt_version: str = "v1"
    source_token_budget: int = Field(default=3000, gt=0)

    # API
    required_role: str = "disputes.read"
    log_level: str = "INFO"

    @property
    def fast_model(self) -> str:
        return self.openai_fast_model or self.openai_chat_model

    @property
    def weaviate_host(self) -> str:
        return urlparse(self.weaviate_url).hostname or "localhost"

    @property
    def weaviate_http_port(self) -> int:
        parsed = urlparse(self.weaviate_url)
        return parsed.port or (443 if parsed.scheme == "https" else 8080)

    @property
    def weaviate_secure(self) -> bool:
        return urlparse(self.weaviate_url).scheme == "https"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings instance (cached)."""
    return Settings()
