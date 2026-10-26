"""Shared Weaviate plumbing: connection factories, date conversion, embedder type."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from weaviate import WeaviateAsyncClient, WeaviateClient, connect_to_custom, use_async_with_custom
from weaviate.auth import AuthCredentials
from weaviate.classes.init import AdditionalConfig, Auth, Timeout

from advanced.config import Settings

# Only for self-provided-vector collections (tests); production vectorizes server-side.
type Embedder = Callable[[str], list[float]]


def to_datetime(d: date) -> datetime:
    """Weaviate DATE properties need RFC 3339 timestamps."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def as_date(value: object) -> date:
    """Convert a Weaviate DATE value back to a `date`."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"unexpected date value from Weaviate: {type(value).__name__}")


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.openai_api_key.get_secret_value()
    return {"X-OpenAI-Api-Key": key} if key else {}


def _auth(settings: Settings) -> AuthCredentials | None:
    key = settings.weaviate_api_key.get_secret_value()
    return Auth.api_key(key) if key else None


_CONFIG = AdditionalConfig(timeout=Timeout(init=10, query=30, insert=120))


def connect_sync(settings: Settings) -> WeaviateClient:
    """Connected sync client. Use as a context manager so it always closes."""
    return connect_to_custom(
        http_host=settings.weaviate_host,
        http_port=settings.weaviate_http_port,
        http_secure=settings.weaviate_secure,
        grpc_host=settings.weaviate_host,
        grpc_port=settings.weaviate_grpc_port,
        grpc_secure=settings.weaviate_secure,
        headers=_headers(settings),
        auth_credentials=_auth(settings),
        additional_config=_CONFIG,
    )


def make_async(settings: Settings) -> WeaviateAsyncClient:
    """Unconnected async client; the FastAPI lifespan calls `connect()`/`close()`."""
    return use_async_with_custom(
        http_host=settings.weaviate_host,
        http_port=settings.weaviate_http_port,
        http_secure=settings.weaviate_secure,
        grpc_host=settings.weaviate_host,
        grpc_port=settings.weaviate_grpc_port,
        grpc_secure=settings.weaviate_secure,
        headers=_headers(settings),
        auth_credentials=_auth(settings),
        additional_config=_CONFIG,
    )
