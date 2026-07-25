from pathlib import Path
from qdrant_client import QdrantClient, models
import ollama
from ...models.validators.chunks import Chunk, ChunkWithEmbedding

COLLECTIONS = [
    {
        "name": "fixed_size_chunking",
        "chunking_strategy": "A",
    },
    {
        "name": "from_structure_chunking",
        "chunking_strategy": "B",
    }
]

# Initialize Ollama client
oclient = ollama.Client(host="localhost")

# Initialize Qdrant client
qclient = QdrantClient(host="localhost", port=6333)

# Text to embed
text = "Ollama excels in niche applications with specific embeddings"

# Generate embeddings
response = oclient.embeddings(model="qwen3-embedding", prompt=text)
embeddings = response["embedding"]


def upsert_vector_with_payload(chunking_file_path: Path) -> None:
    collection_type = chunking_file_path.name.split(
        "_")[-1].split(".")[0]  # A o B
    collection_name = next(
        (c["name"]
         for c in COLLECTIONS if c["chunking_strategy"] == collection_type), None
    )

    with chunking_file_path.open("r", encoding="utf-8") as f:
        for line in f:
            chunk_data = Chunk.model_validate_json(line)

            # create embeddings for the text of the chunk
            emb_response = oclient.embeddings(
                model="qwen3-embedding", prompt=chunk_data.text)

            embedding_chunk = ChunkWithEmbedding(
                # per il chunk_id, dobbiamo trovare anche la posizione del chunk nel documento, quindi concatenare document, page e section
                chunk_id=chunk_data.metadata.document + "_" +
                chunk_data.metadata.page + "_" + chunk_data.metadata.section,
                text=chunk_data.text,
                metadata=chunk_data.metadata,
                embedding=emb_response["embedding"]
            )
            qclient.upsert(
                collection_name=collection_name,
                points=[
                    models.PointStruct(
                        id=chunk_data.chunk_id,
                        vector=embedding_chunk.embedding,
                        payload={
                            "text": embedding_chunk.text,
                            "metadata": embedding_chunk.metadata.model_dump(),
                        },
                    )
                ],
            )
