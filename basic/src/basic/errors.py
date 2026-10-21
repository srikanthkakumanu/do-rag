"""Domain exception hierarchy. The API maps these to RFC 9457 problem responses."""

from __future__ import annotations


class BasicRagError(Exception):
    """Root of all domain errors."""


class IngestionError(BasicRagError):
    """A document could not be loaded, parsed, or indexed."""


class RetrievalError(BasicRagError):
    """The vector store failed (infrastructure, not 'no results')."""


class GenerationError(BasicRagError):
    """The LLM call failed after retries."""
