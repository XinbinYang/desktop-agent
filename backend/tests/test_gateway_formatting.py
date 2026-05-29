from app.gateway.formatting import (
    _count_unclosed_fences,
    clean_text,
    split_for_discord,
    truncate,
)


def test_clean_text_strips_ansi_and_control_chars():
    raw = "hello\x1b[31m red \x1b[0m\x00world\x07!"
    assert clean_text(raw) == "hello red world!"


def test_truncate_short_circuits():
    assert truncate("abc", 100) == "abc"


def test_truncate_appends_suffix():
    assert truncate("abcdefghij", 6) == "abcde…"
    assert truncate("abcdefghij", 6, suffix=" [...]") == " [...]"


def test_split_for_discord_no_split_under_limit():
    text = "hello world"
    assert split_for_discord(text, limit=1900) == [text]


def test_split_for_discord_preserves_code_fence_across_chunks():
    body = "x" * 50
    text = "before\n```python\n" + body + "\n" + body + "\nafter"
    chunks = split_for_discord(text, limit=80)
    # Each chunk should be a valid balanced markdown snippet (no unmatched fences).
    for chunk in chunks:
        assert _count_unclosed_fences(chunk) == 0
    assert chunks[0].startswith("before")
    assert "after" in chunks[-1]


def test_split_for_discord_handles_no_natural_break():
    text = "a" * 5000
    chunks = split_for_discord(text, limit=1000)
    assert all(len(c) <= 1100 for c in chunks)
    assert "".join(chunks) == text
