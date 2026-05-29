from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

CodingIntentMode = Literal["consult", "execute", "handoff", "plan_then_execute", "critic", "verify_only"]


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

_VERIFY_ONLY_PATTERNS = [
    r"跑.*(测试|构建|build)",
    r"执行.*(pytest|vitest|npm\s+test|测试)",
    r"验证.*(测试|构建|build|是否通过)",
    r"run\s+(tests?|pytest|vitest|npm\s+test)",
    r"verify\s+(the\s+)?(build|tests?)",
    r"check\s+(if|whether).*(build|tests?|passes)",
]

_CRITIC_PATTERNS = [
    r"(执行|实现|修改|修复).*(审查|review|复核)",
    r"(审查|review|critic).*(改动|diff|changes?)",
    r"(execute|implement|fix).*(review|critic)",
]

_PLAN_THEN_EXECUTE_PATTERNS = [
    r"先.*(计划|方案).*(执行|实现|修改)",
    r"(计划|方案).*(然后|再).*(执行|实现|修改)",
    r"plan\s+(then|and)\s+(execute|implement|build)",
    r"(大改|复杂|多文件|架构|重构).*(实现|修改|执行)",
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
    if any(re.search(p, lowered, re.IGNORECASE) for p in _VERIFY_ONLY_PATTERNS):
        return "verify_only"
    if any(re.search(p, lowered, re.IGNORECASE) for p in _CRITIC_PATTERNS):
        return "critic"
    if any(re.search(p, lowered, re.IGNORECASE) for p in _PLAN_THEN_EXECUTE_PATTERNS):
        return "plan_then_execute"
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
