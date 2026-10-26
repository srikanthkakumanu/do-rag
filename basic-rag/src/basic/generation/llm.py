"""OpenAI Responses API answerer with structured output."""

from __future__ import annotations

from typing import Protocol

import openai
import structlog
from openai import AsyncOpenAI, omit
from opentelemetry import trace
from pydantic import BaseModel, ValidationError

from basic.config import Settings
from basic.errors import GenerationError
from basic.generation.assembler import AssembledPrompt

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)


class LLMCitation(BaseModel):
    doc_id: str
    section_path: str


class LLMAnswer(BaseModel):
    """The schema the model must return."""

    answer: str
    citations: list[LLMCitation]
    refused: bool


class SchemaParseError(GenerationError):
    """The model returned output that does not match `LLMAnswer`."""


class Answerer(Protocol):
    @property
    def model(self) -> str: ...

    async def generate(self, prompt: AssembledPrompt) -> LLMAnswer: ...


def make_openai_client(settings: Settings) -> AsyncOpenAI:
    """One client per process; injected, never created per request."""
    return AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value() or None,
        timeout=settings.openai_timeout_s,
        max_retries=2,
    )


class OpenAIAnswerer:
    def __init__(self, client: AsyncOpenAI, settings: Settings) -> None:
        if not settings.openai_chat_model:
            raise GenerationError("OPENAI_CHAT_MODEL is not configured")
        self._client = client
        self._settings = settings

    @property
    def model(self) -> str:
        return self._settings.openai_chat_model

    async def generate(self, prompt: AssembledPrompt) -> LLMAnswer:
        s = self._settings
        with _tracer.start_as_current_span("generation.openai"):
            try:
                response = await self._client.responses.parse(
                    model=s.openai_chat_model,
                    instructions=prompt.instructions,
                    input=prompt.user_input,
                    text_format=LLMAnswer,
                    max_output_tokens=s.max_output_tokens,
                    temperature=omit if s.openai_temperature is None else s.openai_temperature,
                    reasoning=(
                        omit
                        if s.openai_reasoning_effort is None
                        else {"effort": s.openai_reasoning_effort}
                    ),
                    store=False,
                )
            except ValidationError as e:
                raise SchemaParseError("model output failed schema validation") from e
            except openai.OpenAIError as e:
                raise GenerationError(f"OpenAI call failed: {type(e).__name__}") from e

        usage = response.usage
        log.info(
            "llm_usage",
            model=s.openai_chat_model,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cached_tokens=usage.input_tokens_details.cached_tokens if usage else None,
        )
        if response.output_parsed is None:
            raise SchemaParseError("model returned no parsable output")
        return response.output_parsed
