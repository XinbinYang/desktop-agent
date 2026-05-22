from __future__ import annotations

import json
import re
from typing import Any, Dict, Literal

from pydantic import BaseModel

from app.collaboration.models import TaskPacket
from app.config import get_model_for_agent


class ClarificationResolution(BaseModel):
    action: Literal["answer", "ask_user"] = "ask_user"
    answer: str = ""
    reason: str = ""
    confidence: float = 0.0
    answered_by: str = "personal_auto"


def _content_from_response(response: Dict[str, Any]) -> str:
    try:
        message = (response.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or ""
    except Exception:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if text:
                    parts.append(str(text))
            elif block:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"```[a-zA-Z]*\n?", "", text or "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_resolution(data: Dict[str, Any], options: list[str]) -> ClarificationResolution:
    action = str(data.get("action") or "").strip().lower()
    answer = str(data.get("answer") or "").strip()
    reason = str(data.get("reason") or "").strip()
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    if action != "answer" or not answer or confidence < 0.75:
        return ClarificationResolution(
            action="ask_user",
            reason=reason or "Personal Agent was not confident enough to answer automatically.",
            confidence=confidence,
            answered_by="personal",
        )

    if options and answer not in options:
        normalized = {option.lower(): option for option in options}
        answer_key = answer.lower()
        if answer_key in normalized:
            answer = normalized[answer_key]
        else:
            return ClarificationResolution(
                action="ask_user",
                reason="Automatic answer did not exactly match the available options.",
                confidence=confidence,
                answered_by="personal",
            )

    return ClarificationResolution(
        action="answer",
        answer=answer,
        reason=reason,
        confidence=confidence,
        answered_by="personal_auto",
    )


async def resolve_personal_clarification(
    clarification: Dict[str, Any],
    packet: TaskPacket,
    *,
    model_id: str = "",
) -> ClarificationResolution:
    """Let Personal Agent conservatively decide whether it can answer a Coding question.

    Failure and low confidence deliberately fall back to asking the user.
    """
    from app.models import ModelRouter

    model = model_id or get_model_for_agent("personal")
    options = [
        str(option).strip()
        for option in (clarification.get("options") or [])
        if str(option).strip()
    ]
    payload = {
        "clarification": {
            "question": str(clarification.get("question") or ""),
            "options": options,
            "context": str(clarification.get("context") or "")[:3000],
            "recommendation": str(clarification.get("recommendation") or "")[:2000],
        },
        "delegated_task": {
            "goal": packet.goal,
            "mode": packet.mode,
            "user_intent": packet.user_intent,
            "product_intent": packet.product_intent,
            "constraints": packet.constraints[:8],
            "acceptance_criteria": packet.acceptance_criteria[:8],
            "context": packet.context,
        },
    }
    system_prompt = (
        "You are the Personal Agent arbitrating a Coding Agent clarification request.\n"
        "Answer automatically only when the answer is clearly implied by the task context, "
        "explicit user preference, the Coding Agent recommendation, or a safe technical choice.\n"
        "Choose ask_user for product behavior, UX preference, privacy/credentials, destructive or "
        "irreversible actions, missing context, or any uncertainty.\n"
        "If options are provided and you answer, the answer must exactly equal one option.\n"
        "Reply only as JSON: "
        "{\"action\":\"answer|ask_user\",\"answer\":\"\",\"reason\":\"\",\"confidence\":0.0}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:14000]},
    ]
    try:
        response = await ModelRouter(model).chat_completion_non_stream(
            messages,
            tools=[],
            temperature=0.0,
            max_tokens=400,
            thinking_intensity="low",
        )
        data = _parse_json_object(_content_from_response(response))
        return _normalize_resolution(data, options)
    except Exception as exc:
        return ClarificationResolution(
            action="ask_user",
            reason=f"Personal Agent arbitration failed: {exc}",
            confidence=0.0,
            answered_by="personal",
        )
