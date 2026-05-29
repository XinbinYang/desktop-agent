from __future__ import annotations

import re
from typing import List

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = _ANSI_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


def _count_unclosed_fences(text: str) -> int:
    count = 0
    i = 0
    n = len(text)
    while i < n - 2:
        if text[i] == "`" and text[i + 1] == "`" and text[i + 2] == "`":
            count += 1
            i += 3
        else:
            i += 1
    return count % 2


def split_for_discord(text: str, limit: int = 1900) -> List[str]:
    """Split text into chunks <= limit, preserving Markdown code fences.

    Code fences (```) that would be cut mid-block are closed at the chunk
    boundary and reopened in the next chunk (with the same language tag where
    detectable).
    """
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        head, remaining = remaining[:cut], remaining[cut:].lstrip("\n ")

        if _count_unclosed_fences(head) == 1:
            lang = _trailing_fence_language(head)
            head = head + "\n```"
            remaining = f"```{lang}\n" + remaining
        chunks.append(head)
    if remaining:
        # The final chunk may have been re-opened with a fence but not closed.
        if _count_unclosed_fences(remaining) == 1:
            remaining = remaining + "\n```"
        chunks.append(remaining)
    return chunks


def _trailing_fence_language(text: str) -> str:
    m = re.search(r"```([^\s`]*)\s*$", text, re.MULTILINE)
    if not m:
        # find last unmatched fence
        for m2 in re.finditer(r"```([^\s`]*)", text):
            pass
        return m2.group(1) if m2 else ""
    return m.group(1)


def truncate(value: str, limit: int, suffix: str = "…") -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - len(suffix))] + suffix
