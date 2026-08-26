from typing import Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    reply: str
    intent: Optional[str] = None
    sources: list = []
    engine: str = "langchain"   # langchain | crew
    used_crew: bool = False
    cache_hit: bool = False

class IngestResponse(BaseModel):
    file_name: str
    chunks: int
    total_chunks: int
