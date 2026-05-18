from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

CodingIntentMode = Literal["consult", "execute", "handoff"]


@dataclass(frozen=True)
class CodingMention:
    raw: str
    task: str
    mode: CodingIntentMode


_CODING_MENTION_RE = re.compile(
    r"@(?:coding(?:[-_\s]+agent)?|code[-_\s]*expert)\b",
    re.IGNORECASE,
)

_CONSULT_PATTERNS = [
    r"看一下",
    r"诊断",
    r"分析",
    r"检查",
    r"review",
    r"explain",
    r"diagnose",
    r"inspect",
    r"analy[sz]e",
    r"what(?:'s| is)",
]

_EXECUTE_PATTERNS = [
    r"修复",
    r"修一下",
    r"改",
    r"实现",
    r"新增",
    r"添加",
    r"优化",
    r"重构",
    r"fix",
    r"patch",
    r"implement",
    r"add",
    r"update",
    r"change",
    r"refactor",
    r"build",
]


def classify_coding_intent(text: str) -> CodingIntentMode:
    stripped = (text or "").strip()
    if not stripped:
        return "handoff"
    lowered = stripped.lower()
    if any(re.search(p, lowered, re.IGNORECASE) for p in _EXECUTE_PATTERNS):
        return "execute"
    if any(re.search(p, lowered, re.IGNORECASE) for p in _CONSULT_PATTERNS):
        return "consult"
    return "consult"


def parse_coding_mention(text: str) -> Optional[CodingMention]:
    raw = text or ""
    match = _CODING_MENTION_RE.search(raw)
    if not match:
        return None
    task = (raw[: match.start()] + raw[match.end() :]).strip()
    task = re.sub(r"\s+", " ", task)
    mode = classify_coding_intent(task)
    return CodingMention(raw=match.group(0), task=task, mode=mode)
