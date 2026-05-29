"""Office artifact manifest and lightweight preview helpers."""

from app.office_artifacts.manifest import (
    OfficeArtifactNotFound,
    get_manifest,
    register_office_artifact,
)

__all__ = [
    "OfficeArtifactNotFound",
    "get_manifest",
    "register_office_artifact",
]
