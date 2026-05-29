from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.office_artifacts.manifest import (
    OfficeArtifactEditError,
    OfficeArtifactNotFound,
    get_manifest,
    update_xlsx_simple_edits,
)


router = APIRouter(prefix="/api/office", tags=["office"])


class SimpleCellEdit(BaseModel):
    sheet: str
    cell: str
    value: Any = None


class SimpleEditRequest(BaseModel):
    edits: list[SimpleCellEdit] = Field(default_factory=list)
    output_name: str = ""


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/{artifact_id}/manifest")
async def office_manifest(artifact_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_manifest, artifact_id)
    except OfficeArtifactNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/{artifact_id}/workbook")
async def office_workbook(artifact_id: str) -> dict[str, Any]:
    try:
        manifest = await asyncio.to_thread(get_manifest, artifact_id)
    except OfficeArtifactNotFound as exc:
        raise _not_found(exc) from exc
    workbook = manifest.get("workbook")
    if not isinstance(workbook, dict):
        raise HTTPException(status_code=404, detail="Workbook preview is not available for this artifact.")
    return workbook


@router.get("/{artifact_id}/slides")
async def office_slides(artifact_id: str) -> dict[str, Any]:
    try:
        manifest = await asyncio.to_thread(get_manifest, artifact_id)
    except OfficeArtifactNotFound as exc:
        raise _not_found(exc) from exc
    presentation = manifest.get("presentation")
    if not isinstance(presentation, dict):
        raise HTTPException(status_code=404, detail="Slide preview is not available for this artifact.")
    return presentation


@router.post("/{artifact_id}/xlsx/simple-edits")
async def office_xlsx_simple_edits(artifact_id: str, request: SimpleEditRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            update_xlsx_simple_edits,
            artifact_id,
            [item.model_dump() for item in request.edits],
            output_name=request.output_name,
        )
    except OfficeArtifactNotFound as exc:
        raise _not_found(exc) from exc
    except OfficeArtifactEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
