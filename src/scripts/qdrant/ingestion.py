from pathlib import Path
from qdrant_client import models
from ...clients.qdrant import qclient

from ...models.validators.chunks import ChunkWithEmbedding

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
CHUNK_DIR = BASE_DIR / "docs" / "chunks"

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


def upsert_vector_with_payload(chunking_file_path: Path) -> None:
    collection_type = chunking_file_path.name.split(
        "_")[-1].split(".")[0]  # A o B
    collection_name = next(
        (c["name"]
         for c in COLLECTIONS if c["chunking_strategy"] == collection_type), None
    )

    with chunking_file_path.open("r", encoding="utf-8") as f:
        for line in f:
            # Il chunk arriva già completo di identità ed embedding: qui si
            # decide solo cosa farne nell'indice.
            chunk_data = ChunkWithEmbedding.model_validate_json(line)

            qclient.upsert(
                collection_name=collection_name,
                points=[
                    models.PointStruct(
                        id=chunk_data.chunk_id,
                        vector=chunk_data.embedding,
                        payload={
                            "text": chunk_data.text,
                            "metadata": chunk_data.metadata.model_dump(),
                        },
                    )
                ],
            )


def ingest_all_chunks() -> None:
    for jsonl_file in CHUNK_DIR.glob("*.jsonl"):
        upsert_vector_with_payload(jsonl_file)
