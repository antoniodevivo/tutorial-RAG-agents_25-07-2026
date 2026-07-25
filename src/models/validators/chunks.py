from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    document: str
    version: str
    visibility: str
    date: str
    page: str
    section: str
    # Componenti dell'identità del chunk, persistiti per poterla ricostruire:
    # `chunk_id` è un hash e da solo non dice più da dove viene.
    ordinal: int
    config: str


class Chunk(BaseModel):
    text: str
    metadata: ChunkMetadata


class ChunkWithEmbedding(Chunk):
    chunk_id: str
    embedding: list[float]
