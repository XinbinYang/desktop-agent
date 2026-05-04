from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from pathlib import Path

from app.project_manager import ProjectManager
from app.credential_manager import CredentialManager

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
