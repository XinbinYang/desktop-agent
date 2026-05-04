from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class KnowledgeIndexRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str
    recursive: bool = True


class KnowledgeSearchRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    query: str
    top_k: int = 5
    source_filter: Optional[str] = None


@router.get("/api/knowledge/docs")
def list_knowledge_docs():
    from app.rag.engine import get_rag_engine
    return {"docs": get_rag_engine().list_docs()}


@router.post("/api/knowledge/index")
async def index_knowledge(req: KnowledgeIndexRequest):
    from app.rag.engine import get_rag_engine
    result = get_rag_engine().index_file(req.path, recursive=req.recursive)
    if "error" in result:
        return {"error": result["error"]}
    return result


@router.delete("/api/knowledge/docs")
def delete_knowledge_doc(path: str):
    from app.rag.engine import get_rag_engine
    return get_rag_engine().delete_doc(path)


@router.post("/api/knowledge/search")
async def search_knowledge(req: KnowledgeSearchRequest):
    from app.rag.engine import get_rag_engine
    results = get_rag_engine().search(req.query, top_k=req.top_k, source_filter=req.source_filter)
    return {"results": [r.model_dump() for r in results]}
