from __future__ import annotations

import os

from app.collaboration import targeting


def test_existing_absolute_prefix_limits_probe_count(monkeypatch):
    target = r"C:\repo" if os.name == "nt" else "/tmp/repo"
    calls: list[str] = []

    def fake_normalize(value: object) -> str:
        text = str(value)
        calls.append(text)
        return target if text == target else ""

    monkeypatch.setattr(targeting, "_normalize_existing_project_path", fake_normalize)

    resolved = targeting._existing_absolute_prefix(f"{target} " + ("tail " * 2000))

    assert resolved == target
    assert len(calls) <= targeting._MAX_PREFIX_PROBES + 1
    assert max(len(value) for value in calls) <= targeting._MAX_MENTIONED_PATH_CHARS


def test_resolve_collaboration_target_extracts_mentioned_existing_path(tmp_path):
    result = targeting.resolve_collaboration_target(
        user_message=f"请检查 {tmp_path} 后面的说明文字",
        allow_global=False,
    )

    assert result.ok
    assert result.source == "message"
    assert result.project_path


def test_normalize_rejects_unc_paths_without_filesystem_probe():
    # UNC / network paths must be rejected before any Path.exists()/.resolve()
    # call: on Windows those issue a blocking SMB call that can hang the event
    # loop indefinitely. URL authorities (//host/path) are the common trigger.
    assert targeting._normalize_existing_project_path("//www.example.com/outlooks/steo") == ""
    assert targeting._normalize_existing_project_path("\\\\fileserver\\share\\repo") == ""


def test_resolve_collaboration_target_ignores_url_in_message():
    # A message that mentions a URL must not be treated as a project path and
    # must not hang on a UNC/SMB lookup.
    result = targeting.resolve_collaboration_target(
        user_message="参考 https://www.example.com/outlooks/steo/ 的数据",
        allow_global=False,
    )

    assert not result.ok
    assert not result.project_path
