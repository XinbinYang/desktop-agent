import base64

import pytest

import app.tools.artifact_tool as artifact_tool
from app.runtime_paths import personal_workspace_dir
from app.tools.artifact_tool import ImagePublishTool


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@pytest.mark.asyncio
async def test_image_publish_publishes_png_from_personal_workspace():
    source = personal_workspace_dir() / "chart.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(PNG_BYTES)

    result = await ImagePublishTool().execute(
        path=str(source),
        title="Equity curve",
        session_id="session-images",
        agent_type="personal",
    )

    assert result.error == ""
    artifact = result.metadata["artifacts"][0]
    assert artifact["type"] == "image"
    assert artifact["title"] == "Equity curve"
    assert artifact["mime_type"] == "image/png"
    assert artifact["url"].startswith("/preview/session-images/")
    assert artifact["path"].endswith(".png")


@pytest.mark.asyncio
async def test_image_publish_publishes_svg_from_personal_workspace():
    source = personal_workspace_dir() / "chart.svg"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        '<svg width="320" height="180" xmlns="http://www.w3.org/2000/svg"></svg>',
        encoding="utf-8",
    )

    result = await ImagePublishTool().execute(
        path="chart.svg",
        session_id="session-svg",
        agent_type="personal",
    )

    assert result.error == ""
    artifact = result.metadata["artifacts"][0]
    assert artifact["type"] == "image"
    assert artifact["mime_type"] == "image/svg+xml"
    assert artifact["width"] == 320
    assert artifact["height"] == 180


@pytest.mark.asyncio
async def test_image_publish_rejects_non_image_from_allowed_workspace():
    source = personal_workspace_dir() / "note.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("not an image", encoding="utf-8")

    result = await ImagePublishTool().execute(
        path=str(source),
        session_id="session-text",
        agent_type="personal",
    )

    assert "not a supported image" in result.error


@pytest.mark.asyncio
async def test_image_publish_rejects_path_outside_allowed_roots(tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG_BYTES)

    result = await ImagePublishTool().execute(
        path=str(outside),
        session_id="session-outside",
        agent_type="personal",
    )

    assert "allowed image/artifact source" in result.error


@pytest.mark.asyncio
async def test_image_publish_rejects_oversized_image(monkeypatch):
    monkeypatch.setattr(artifact_tool, "MAX_IMAGE_BYTES", 4)
    source = personal_workspace_dir() / "large.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(PNG_BYTES)

    result = await ImagePublishTool().execute(
        path=str(source),
        session_id="session-large",
        agent_type="personal",
    )

    assert "too large" in result.error
