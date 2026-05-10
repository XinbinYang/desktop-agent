from pydantic import BaseModel
from typing import Optional


class DocumentChunk(BaseModel):
    id: str
    source_path: str
    content: str
    embedding: Optional[list[float]] = None
    metadata: dict = {}


class SearchResult(BaseModel):
    chunk_id: str
    source_path: str
    content: str
    score: float
