"""Domain exception hierarchy. The API maps these to RFC 9457 problem responses."""

from __future__ import annotations


class AdvancedRagError(Exception):
    """Root of all domain errors."""


class IngestionError(AdvancedRagError):
    """A document could not be loaded, parsed, or indexed."""


class RetrievalError(AdvancedRagError):
    """The vector store failed (infrastructure, not 'no results')."""


class GenerationError(AdvancedRagError):
    """The LLM call failed after retries."""
