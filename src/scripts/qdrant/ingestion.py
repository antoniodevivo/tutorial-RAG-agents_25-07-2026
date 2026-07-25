from pathlib import Path
from qdrant_client import models
from ...clients.qdrant import qclient

from ..chunking_simple import EMBED_DIM
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

for collection in COLLECTIONS:
    if not qclient.collection_exists(collection["name"]):
        qclient.recreate_collection(
            collection_name=collection["name"],
            vectors_config=models.VectorParams(
                size=EMBED_DIM, distance=models.Distance.COSINE),
        )


def upsert_vector_with_payload(chunking_file_path: Path) -> None:
    # Nome file da generate_chunks: md_{doc}_chunks-{A|B}.jsonl. Il taglio
    # deve avvenire sull'ultimo "-", non su "_": {doc} può contenere "_"
    # (es. versione "v5.0.3"), quindi split("_")[-1] non isola mai la sola
    # lettera della strategia.
    collection_type = chunking_file_path.stem.rsplit("-", 1)[-1]  # A o B
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
