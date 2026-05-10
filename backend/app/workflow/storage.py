import json
from typing import List, Optional

from app.runtime_paths import runtime_dir
from app.workflow.models import Workflow

WORKFLOWS_DIR = runtime_dir("workflows")


def save_workflow(workflow: Workflow) -> None:
    path = WORKFLOWS_DIR / f"{workflow.id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workflow.model_dump(), f, ensure_ascii=False, indent=2)


def load_workflow(workflow_id: str) -> Optional[Workflow]:
    path = WORKFLOWS_DIR / f"{workflow_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Workflow(**data)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def list_workflows() -> List[Workflow]:
    workflows = []
    for path in WORKFLOWS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            workflows.append(Workflow(**data))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return sorted(workflows, key=lambda w: w.created_at, reverse=True)


def delete_workflow(workflow_id: str) -> bool:
    path = WORKFLOWS_DIR / f"{workflow_id}.json"
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            pass
    return False
