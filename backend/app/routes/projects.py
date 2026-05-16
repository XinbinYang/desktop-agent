from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path

from app.project_manager import ProjectManager
from app.credential_manager import CredentialManager
from app.coding_context import build_repo_map
from app.project_rules import (
    PROJECT_RULES_FILE,
    USER_RULES_DIR,
    USER_RULES_FILE,
    get_project_rules,
    get_user_rules,
)

router = APIRouter()


class OpenProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str


class CreateProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    parent_path: str
    name: str
    template: str = "empty"


class CloneProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    url: str
    path: Optional[str] = None
    token: Optional[str] = None


@router.get("/api/projects")
def list_projects():
    """获取最近项目列表和当前项目"""
    return {
        "projects": ProjectManager.list_recent(),
        "current": ProjectManager.get_current()
    }


@router.get("/api/projects/current")
def get_current_project():
    """获取当前打开的项目"""
    return ProjectManager.get_current()


@router.get("/api/projects/repomap")
def get_project_repomap(max_files: int = 220):
    project = ProjectManager.get_current()
    if not project:
        return {"error": "No current project"}
    return build_repo_map(project["path"], max_files=max(20, min(max_files, 1000)))


@router.post("/api/projects/open")
def open_project(req: OpenProjectRequest):
    """打开一个项目目录"""
    try:
        project = ProjectManager.open_project(req.path)
        # 配置 GCM
        CredentialManager.configure_gcm(req.path)
        return project
    except ValueError as e:
        return {"error": str(e)}


@router.post("/api/projects/clone")
async def clone_project(req: CloneProjectRequest):
    """Clone a Git repository and open it as the current project."""
    from app.tools.git_tool import GitCloneTool

    try:
        if req.path:
            target = Path(req.path).resolve()
        else:
            repo_name = req.url.rstrip("/").split("/")[-1].replace(".git", "")
            current = ProjectManager.get_current()
            target = (Path(current["path"]).parent if current else Path.cwd()) / repo_name
            target = target.resolve()

        result = await GitCloneTool().execute(req.url, str(target), req.token)
        if result.error:
            return {"error": result.error}

        project = ProjectManager.open_project(str(target))
        CredentialManager.configure_gcm(str(target))
        project["message"] = result.output
        return project
    except ValueError as e:
        return {"error": str(e)}


@router.post("/api/projects/close")
def close_project():
    """关闭当前项目"""
    ProjectManager.close_project()
    return {"status": "closed"}


@router.post("/api/projects/create")
def create_project(req: CreateProjectRequest):
    """创建新项目"""
    try:
        return ProjectManager.create_project(req.parent_path, req.name, req.template)
    except ValueError as e:
        return {"error": str(e)}


@router.get("/api/projects/tree")
def get_project_tree(path: str = ""):
    """获取项目文件树"""
    return {"nodes": ProjectManager.get_tree(path)}


# ── Agent rules (.desktop-agent.md / AGENTS.md) ──────────────────────────

class RulesWriteRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    content: str


@router.get("/api/projects/rules")
def get_project_rules_endpoint():
    """读取当前项目的 .desktop-agent.md 规则文件。"""
    project = ProjectManager.get_current()
    if not project:
        return JSONResponse(
            status_code=400,
            content={"error": {"category": "validation", "message": "没有打开的项目"}},
        )
    rules_path = Path(project["path"]) / PROJECT_RULES_FILE
    exists = rules_path.exists()
    content = ""
    if exists:
        try:
            content = rules_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"error": {"category": "internal", "message": f"读取规则文件失败: {e}"}}
    return {"path": str(rules_path), "exists": exists, "content": content}


@router.put("/api/projects/rules")
def save_project_rules_endpoint(req: RulesWriteRequest):
    """保存当前项目的 .desktop-agent.md 规则文件。"""
    project = ProjectManager.get_current()
    if not project:
        return JSONResponse(
            status_code=400,
            content={"error": {"category": "validation", "message": "没有打开的项目"}},
        )
    rules_path = Path(project["path"]) / PROJECT_RULES_FILE
    try:
        rules_path.write_text(req.content, encoding="utf-8")
    except OSError as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"category": "internal", "message": f"保存规则文件失败: {e}"}},
        )
    return {"status": "ok", "path": str(rules_path)}


@router.get("/api/projects/rules/user")
def get_user_rules_endpoint():
    """读取全局用户规则 ~/.desktop-agent/AGENTS.md。"""
    rules_path = Path.home() / USER_RULES_DIR / USER_RULES_FILE
    exists = rules_path.exists()
    content = ""
    if exists:
        try:
            content = rules_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"error": {"category": "internal", "message": f"读取用户规则失败: {e}"}}
    return {"path": str(rules_path), "exists": exists, "content": content}


@router.put("/api/projects/rules/user")
def save_user_rules_endpoint(req: RulesWriteRequest):
    """保存全局用户规则 ~/.desktop-agent/AGENTS.md。"""
    rules_dir = Path.home() / USER_RULES_DIR
    rules_path = rules_dir / USER_RULES_FILE
    try:
        rules_dir.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(req.content, encoding="utf-8")
    except OSError as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"category": "internal", "message": f"保存用户规则失败: {e}"}},
        )
    return {"status": "ok", "path": str(rules_path)}
