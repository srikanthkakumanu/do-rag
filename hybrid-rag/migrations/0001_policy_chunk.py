"""Create the `PolicyChunk` collection (idempotent). Schema: docs/architecture.md."""

from __future__ import annotations

from weaviate import WeaviateClient
from weaviate.classes.config import Configure, DataType, Property, Tokenization

from hybrid.config import Settings


def up(client: WeaviateClient, settings: Settings) -> None:
    if client.collections.exists(settings.collection_name):
        return
    vector_config = (
        Configure.Vectors.text2vec_openai(
            model=settings.openai_embed_model, source_properties=["content", "doc_title"]
        )
        if settings.weaviate_vectorizer == "text2vec-openai"
        else Configure.Vectors.self_provided()
    )
    field = Tokenization.FIELD
    client.collections.create(
        settings.collection_name,
        vector_config=vector_config,
        properties=[
            Property(name="content", data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="doc_title", data_type=DataType.TEXT, tokenization=Tokenization.WORD),
            Property(name="doc_id", data_type=DataType.TEXT, tokenization=field),
            Property(name="version", data_type=DataType.TEXT, tokenization=field),
            Property(name="section_path", data_type=DataType.TEXT, tokenization=field),
            Property(name="chunk_index", data_type=DataType.INT),
            Property(name="source_type", data_type=DataType.TEXT, tokenization=field),
            Property(name="card_network", data_type=DataType.TEXT, tokenization=field),
            Property(name="reason_codes", data_type=DataType.TEXT_ARRAY, tokenization=field),
            Property(name="jurisdiction", data_type=DataType.TEXT, tokenization=field),
            Property(name="effective_date", data_type=DataType.DATE),
            Property(name="superseded_on", data_type=DataType.DATE),
            Property(name="content_hash", data_type=DataType.TEXT, tokenization=field),
        ],
    )
