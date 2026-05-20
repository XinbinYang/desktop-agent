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
    try:
        return {"docs": get_rag_engine().list_docs()}
    except Exception as exc:
        return {"docs": [], "error": str(exc)}


@router.post("/api/knowledge/index")
async def index_knowledge(req: KnowledgeIndexRequest):
    from app.rag.engine import get_rag_engine
    try:
        result = get_rag_engine().index_file(req.path, recursive=req.recursive)
    except Exception as exc:
        result = {"error": str(exc)}
    if "error" in result:
        return {"error": result["error"]}
    return result


@router.delete("/api/knowledge/docs")
def delete_knowledge_doc(path: str):
    from app.rag.engine import get_rag_engine
    try:
        return get_rag_engine().delete_doc(path)
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/api/knowledge/search")
async def search_knowledge(req: KnowledgeSearchRequest):
    from app.rag.engine import get_rag_engine
    try:
        results = get_rag_engine().search(req.query, top_k=req.top_k, source_filter=req.source_filter)
        return {"results": [r.model_dump() for r in results]}
    except Exception as exc:
        return {"results": [], "error": str(exc)}


@router.delete("/api/knowledge")
def clear_knowledge():
    from app.rag.engine import get_rag_engine
    try:
        return get_rag_engine().clear_all()
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/api/knowledge/stats")
def knowledge_stats():
    from app.rag.engine import get_rag_status
    return get_rag_status()


# ── Memory endpoints (cross-session project memory) ──────────────────────

from pydantic import BaseModel


class MemorySaveRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    type: str = "project_knowledge"  # user_preference, project_knowledge, decision_log, reference
    content: str
    tags: list[str] = []


@router.get("/api/memory")
def list_memories():
    from app.memory import load_memories
    from app.project_manager import ProjectManager
    project = ProjectManager.get_current()
    if not project:
        return {"error": {"category": "validation", "message": "没有打开的项目"}}
    entries = load_memories(project["path"])
    return {"memories": [e.to_dict() for e in entries]}


@router.post("/api/memory")
def save_memory_endpoint(req: MemorySaveRequest):
    from app.memory import save_memory
    from app.project_manager import ProjectManager
    project = ProjectManager.get_current()
    if not project:
        return {"error": {"category": "validation", "message": "没有打开的项目"}}
    entry = save_memory(project["path"], req.type, req.content, req.tags)
    if entry:
        return {"status": "ok", "memory": entry.to_dict()}
    return {"error": {"category": "internal", "message": "保存记忆失败"}}


@router.delete("/api/memory/{memory_id}")
def delete_memory_endpoint(memory_id: str):
    from app.memory import delete_memory
    from app.project_manager import ProjectManager
    project = ProjectManager.get_current()
    if not project:
        return {"error": {"category": "validation", "message": "没有打开的项目"}}
    ok = delete_memory(project["path"], memory_id)
    return {"status": "ok" if ok else "not_found"}
