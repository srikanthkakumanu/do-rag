"""Answer generation over the shared `StructuredLLM` gateway."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from hybrid.config import Settings
from hybrid.generation.assembler import AssembledPrompt
from hybrid.llm import SchemaParseError, StructuredLLM

__all__ = ["Answerer", "LLMAnswer", "LLMCitation", "OpenAIAnswerer", "SchemaParseError"]


class LLMCitation(BaseModel):
    doc_id: str
    section_path: str


class LLMAnswer(BaseModel):
    """The schema the model must return."""

    answer: str
    citations: list[LLMCitation]
    refused: bool


class Answerer(Protocol):
    @property
    def model(self) -> str: ...

    async def generate(self, prompt: AssembledPrompt) -> LLMAnswer: ...


class OpenAIAnswerer:
    def __init__(self, llm: StructuredLLM, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    @property
    def model(self) -> str:
        return self._settings.openai_chat_model

    async def generate(self, prompt: AssembledPrompt) -> LLMAnswer:
        s = self._settings
        return await self._llm.parse(
            model=s.openai_chat_model,
            instructions=prompt.instructions,
            user_input=prompt.user_input,
            schema=LLMAnswer,
            max_output_tokens=s.max_output_tokens,
            reasoning_effort=s.openai_reasoning_effort,
            purpose="answer",
        )
