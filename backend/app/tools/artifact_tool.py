import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import quote

from app.coding_runs import effective_project_path
from app.runtime_paths import personal_workspace_dir, runtime_dir, workspace_root
from app.tools.base import BaseTool, ToolResult


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}
OFFICE_EXTENSIONS = {".xlsx", ".xls", ".pptx", ".ppt"}
PREVIEWABLE_EXTENSIONS: dict[str, str] = {
    ".html": "web",
    ".htm": "web",
    ".csv": "data",
    ".json": "data",
    ".md": "code",
    ".txt": "code",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".svg": "image",
    ".gif": "image",
    ".webp": "image",
    ".mp4": "video",
    ".webm": "video",
    ".mov": "video",
    ".xlsx": "office",
    ".xls": "office",
    ".pptx": "office",
    ".ppt": "office",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_OFFICE_BYTES = 64 * 1024 * 1024


def _safe_segment(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._")
    return cleaned[:120] or fallback


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _existing_source_path(raw_path: str, agent_type: str = "") -> Optional[Path]:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve() if path.exists() else None

    candidates: list[Path] = []
    if agent_type == "personal":
        candidates.append(personal_workspace_dir() / path)
    project_path = effective_project_path()
    if project_path:
        candidates.append(Path(project_path) / path)
    candidates.extend([
        runtime_dir("office") / path,
        workspace_root() / path,
        runtime_dir("preview") / path,
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _allowed_roots(agent_type: str = "") -> list[Path]:
    roots = [
        runtime_dir("office"),
        runtime_dir("preview"),
        workspace_root(),
    ]
    if agent_type == "personal":
        roots.insert(0, personal_workspace_dir())
    project_path = effective_project_path()
    if project_path:
        roots.append(Path(project_path))
    normalized: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key not in seen:
            normalized.append(resolved)
            seen.add(key)
    return normalized


def _validate_source(path: Path, agent_type: str = "") -> Optional[str]:
    if not path.exists() or not path.is_file():
        return "File does not exist or is not a regular file."
    if not any(_is_relative_to(path, root) for root in _allowed_roots(agent_type)):
        return "Path is not in an allowed image/artifact source directory."
    return None


def _guess_mime(path: Path) -> str:
    mime, _encoding = mimetypes.guess_type(path.name)
    if path.suffix.lower() == ".svg":
        return "image/svg+xml"
    return mime or "application/octet-stream"


def _image_dimensions(path: Path) -> tuple[Optional[int], Optional[int]]:
    if path.suffix.lower() == ".svg":
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:2000]
        except OSError:
            return None, None
        width_match = re.search(r'\bwidth=["\']?([0-9.]+)', text)
        height_match = re.search(r'\bheight=["\']?([0-9.]+)', text)
        try:
            width = int(float(width_match.group(1))) if width_match else None
            height = int(float(height_match.group(1))) if height_match else None
            return width, height
        except (TypeError, ValueError):
            return None, None

    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
            return int(width), int(height)
    except Exception:
        return None, None


def _preview_url(path: Path) -> str:
    preview_root = runtime_dir("preview").resolve()
    rel = path.resolve().relative_to(preview_root)
    return "/preview/" + "/".join(quote(part) for part in rel.parts)


def _copy_to_session_preview(source: Path, session_id: str, title: str = "") -> Path:
    preview_root = runtime_dir("preview")
    safe_session = _safe_segment(session_id or "default", "default")
    session_dir = preview_root / safe_session
    session_dir.mkdir(parents=True, exist_ok=True)
    display_name = _safe_segment(title or source.name, source.name)
    if not display_name.lower().endswith(source.suffix.lower()):
        display_name = f"{display_name}{source.suffix}"
    target = session_dir / f"{uuid.uuid4().hex[:8]}_{display_name}"
    if source.resolve() == target.resolve():
        return target
    shutil.copy2(source, target)
    return target


def publish_file_artifact(
    path: str,
    *,
    session_id: str = "default",
    title: str = "",
    caption: str = "",
    source_tool: str = "",
    tool_call_id: str = "",
    agent_type: str = "",
    artifact_type: str | None = None,
    require_image: bool = False,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    source = _existing_source_path(path, agent_type=agent_type)
    if source is None:
        return None, "File does not exist or cannot be resolved from the allowed workspace roots."

    validation_error = _validate_source(source, agent_type=agent_type)
    if validation_error:
        return None, validation_error

    ext = source.suffix.lower()
    inferred_type = artifact_type or PREVIEWABLE_EXTENSIONS.get(ext)
    if require_image:
        inferred_type = "image"
    if not inferred_type:
        return None, f"Unsupported artifact file type: {ext or '(none)'}"

    mime_type = _guess_mime(source)
    if inferred_type == "image":
        if ext not in IMAGE_EXTENSIONS or not mime_type.startswith("image/"):
            return None, "File is not a supported image type."
        max_bytes = MAX_IMAGE_BYTES
    elif inferred_type == "office":
        if ext not in OFFICE_EXTENSIONS:
            return None, "File is not a supported Office artifact type."
        max_bytes = MAX_OFFICE_BYTES
    else:
        max_bytes = MAX_ARTIFACT_BYTES

    try:
        size = source.stat().st_size
    except OSError as exc:
        return None, f"Could not inspect file: {exc}"
    if size > max_bytes:
        return None, f"File is too large to publish ({size} bytes, max {max_bytes} bytes)."

    try:
        target = _copy_to_session_preview(source, session_id, title or source.name)
    except OSError as exc:
        return None, f"Could not copy artifact into preview storage: {exc}"

    width, height = _image_dimensions(target) if inferred_type == "image" else (None, None)
    artifact: Dict[str, Any] = {
        "id": f"artifact_{uuid.uuid4().hex[:12]}",
        "type": inferred_type,
        "title": title or source.name,
        "url": _preview_url(target),
        "mime_type": mime_type,
        "path": str(target),
        "source": source_tool,
        "tool_call_id": tool_call_id,
        "size": size,
    }
    if caption:
        artifact["caption"] = caption
    if width:
        artifact["width"] = width
    if height:
        artifact["height"] = height
    if inferred_type == "office":
        try:
            from app.office_artifacts.manifest import register_office_artifact

            artifact = register_office_artifact(
                target,
                artifact=artifact,
                session_id=session_id or "default",
                source_tool=source_tool,
                tool_call_id=tool_call_id,
            )
        except Exception as exc:
            artifact["office_manifest_error"] = str(exc)
    return artifact, None


def publish_many_file_artifacts(
    paths: Iterable[tuple[str, str, str | None]],
    *,
    session_id: str,
    source_tool: str,
    tool_call_id: str = "",
    agent_type: str = "",
) -> list[Dict[str, Any]]:
    artifacts: list[Dict[str, Any]] = []
    for path, title, artifact_type in paths:
        artifact, _error = publish_file_artifact(
            path,
            session_id=session_id,
            title=title,
            source_tool=source_tool,
            tool_call_id=tool_call_id,
            agent_type=agent_type,
            artifact_type=artifact_type,
            require_image=artifact_type == "image",
        )
        if artifact:
            artifacts.append(artifact)
    return artifacts


class ImagePublishTool(BaseTool):
    name = "image_publish"
    description = (
        "Publish a generated PNG/JPG/SVG/GIF/WebP image into the chat. Use this after "
        "creating charts or screenshots as files so the user can see them inline."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Image file path, absolute or relative to the Personal workspace/current project."},
            "title": {"type": "string", "description": "Optional display title for the image."},
            "caption": {"type": "string", "description": "Optional caption shown with the image artifact."},
        },
        "required": ["path"],
    }

    async def execute(
        self,
        path: str,
        title: str = "",
        caption: str = "",
        session_id: str = "default",
        tool_call_id: str = "",
        agent_type: str = "",
    ) -> ToolResult:
        artifact, error = publish_file_artifact(
            path,
            session_id=session_id or "default",
            title=title,
            caption=caption,
            source_tool=self.name,
            tool_call_id=tool_call_id,
            agent_type=agent_type,
            require_image=True,
        )
        if error:
            return ToolResult(error=error)
        assert artifact is not None
        output = f"Image published: {artifact['title']} ({artifact['url']})"
        return ToolResult(output=output, metadata={"artifacts": [artifact]})


class OfficePublishTool(BaseTool):
    name = "office_publish"
    description = (
        "Publish a generated Excel or PowerPoint file into the chat as an Office "
        "artifact. Supports .xlsx, .xls, .pptx, and .ppt files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Office file path, absolute or relative to the Personal workspace/current project."},
            "title": {"type": "string", "description": "Optional display title for the Office artifact."},
            "caption": {"type": "string", "description": "Optional caption shown with the Office artifact."},
        },
        "required": ["path"],
    }

    async def execute(
        self,
        path: str,
        title: str = "",
        caption: str = "",
        session_id: str = "default",
        tool_call_id: str = "",
        agent_type: str = "",
    ) -> ToolResult:
        artifact, error = publish_file_artifact(
            path,
            session_id=session_id or "default",
            title=title,
            caption=caption,
            source_tool=self.name,
            tool_call_id=tool_call_id,
            agent_type=agent_type,
            artifact_type="office",
        )
        if error:
            return ToolResult(error=error)
        assert artifact is not None
        output = f"Office artifact published: {artifact['title']} ({artifact['url']})"
        return ToolResult(output=output, metadata={"artifacts": [artifact]})
