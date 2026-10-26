"""Domain exception hierarchy. The API maps these to RFC 9457 problem responses."""

from __future__ import annotations


class HybridRagError(Exception):
    """Root of all domain errors."""


class IngestionError(HybridRagError):
    """A document could not be loaded, parsed, or indexed."""


class RetrievalError(HybridRagError):
    """The vector store failed (infrastructure, not 'no results')."""


class GenerationError(HybridRagError):
    """The LLM call failed after retries."""
