"""One structured-output gateway to OpenAI, shared by the planner, reranker, and answerer."""

from __future__ import annotations

from typing import Protocol

import openai
import structlog
from openai import AsyncOpenAI, omit
from opentelemetry import trace
from pydantic import BaseModel, ValidationError

from hybrid.config import ReasoningEffort, Settings
from hybrid.errors import GenerationError

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)


class SchemaParseError(GenerationError):
    """The model returned output that does not match the requested schema."""


class StructuredLLM(Protocol):
    async def parse[T: BaseModel](
        self,
        *,
        model: str,
        instructions: str,
        user_input: str,
        schema: type[T],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort | None = None,
        purpose: str,
    ) -> T: ...


def make_openai_client(settings: Settings) -> AsyncOpenAI:
    """One client per process; injected, never created per request."""
    return AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value() or None,
        timeout=settings.openai_timeout_s,
        max_retries=2,
    )


class OpenAIStructuredLLM:
    """`StructuredLLM` over the Responses API (`responses.parse`, `store=False`)."""

    def __init__(self, client: AsyncOpenAI, settings: Settings) -> None:
        self._client = client
        self._temperature = settings.openai_temperature

    async def parse[T: BaseModel](
        self,
        *,
        model: str,
        instructions: str,
        user_input: str,
        schema: type[T],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort | None = None,
        purpose: str,
    ) -> T:
        if not model:
            raise GenerationError("OpenAI model is not configured (OPENAI_CHAT_MODEL)")
        with _tracer.start_as_current_span(f"llm.{purpose}"):
            try:
                response = await self._client.responses.parse(
                    model=model,
                    instructions=instructions,
                    input=user_input,
                    text_format=schema,
                    max_output_tokens=max_output_tokens,
                    temperature=omit if self._temperature is None else self._temperature,
                    reasoning=omit if reasoning_effort is None else {"effort": reasoning_effort},
                    store=False,
                )
            except ValidationError as e:
                raise SchemaParseError(f"{purpose}: output failed schema validation") from e
            except openai.OpenAIError as e:
                raise GenerationError(f"{purpose}: OpenAI call failed ({type(e).__name__})") from e

        usage = response.usage
        log.info(
            "llm_usage",
            purpose=purpose,
            model=model,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cached_tokens=usage.input_tokens_details.cached_tokens if usage else None,
        )
        if response.output_parsed is None:
            raise SchemaParseError(f"{purpose}: no parsable output")
        return response.output_parsed
