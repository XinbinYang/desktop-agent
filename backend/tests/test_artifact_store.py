import base64

from app import artifact_store
from app.agent import _externalize_artifacts


def _big_base64(num_bytes: int) -> str:
    return base64.b64encode(b"x" * num_bytes).decode("ascii")


def test_store_and_load_round_trip():
    payload = b"\x89PNG fake image bytes" * 4
    b64 = base64.b64encode(payload).decode("ascii")
    stored = artifact_store.store_base64("sess-rt", "art-1", b64, "image/png")
    assert stored is not None
    assert stored["size"] == len(payload)

    loaded = artifact_store.load("sess-rt", "art-1")
    assert loaded is not None
    data, mime = loaded
    assert data == payload
    assert mime == "image/png"

    artifact_store.delete_session_artifacts("sess-rt")
    assert artifact_store.load("sess-rt", "art-1") is None


def test_should_externalize_threshold():
    small = _big_base64(1024)
    large = _big_base64(artifact_store.INLINE_SPILL_THRESHOLD_BYTES + 1)
    assert artifact_store.should_externalize(small) is False
    assert artifact_store.should_externalize(large) is True
    assert artifact_store.should_externalize("") is False


def test_externalize_artifacts_spills_large_and_keeps_small_inline():
    big = _big_base64(artifact_store.INLINE_SPILL_THRESHOLD_BYTES + 100)
    small = _big_base64(512)
    artifacts = [
        {"id": "img-big", "type": "image", "base64": big, "mime_type": "image/png"},
        {"id": "img-small", "type": "image", "base64": small, "mime_type": "image/png"},
    ]

    result = _externalize_artifacts(artifacts, "sess-ext")
    big_out, small_out = result

    # Large payload spilled to disk: base64 dropped, url/ref added.
    assert "base64" not in big_out
    assert big_out["externalized"] is True
    assert big_out["url"] == "/api/sessions/sess-ext/artifacts/img-big"
    assert big_out["artifact_id"] == "img-big"
    loaded = artifact_store.load("sess-ext", "img-big")
    assert loaded is not None

    # Small payload left untouched.
    assert small_out["base64"] == small
    assert "url" not in small_out

    artifact_store.delete_session_artifacts("sess-ext")
