from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    document: str
    version: str
    visibility: str
    page: str
    section: str


class Chunk(BaseModel):
    text: str
    metadata: ChunkMetadata


class ChunkWithEmbedding(Chunk):
    chunk_id: str
    embedding: list[float]
