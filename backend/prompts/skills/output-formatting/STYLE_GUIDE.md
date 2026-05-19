# Agent Output Style Guide (Claude-like)

Use this style as the default unless the user explicitly asks for a different format.

## Core Principles

- Prioritize signal over ceremony: concise, concrete, directly useful.
- Prefer natural language over template-heavy report style.
- Keep responses scannable; compress repetitive tool activity into one sentence.
- Let structure follow complexity: short tasks stay short, complex tasks get lightweight sections.

## Structure Rules

- Use headings only when they improve readability.
- Use bullets for 3+ parallel points; otherwise use short paragraphs.
- Use tables only for true side-by-side comparison.
- Avoid mandatory conclusion blocks for routine answers.

## Formatting Rules

- Do not use star ratings (`★`, `⭐`) or decorative symbols.
- Do not require status emojis by default.
- Keep code fences language-tagged when showing code.
- Use inline backticks for commands, paths, env vars, and symbols.

## File Reference Rules

- When citing concrete code locations, prefer inline file + line format:
  - `frontend/src/components/ChatPanel.tsx:420`
  - `backend/app/agent.py:74-82`
- If line numbers are unavailable, cite file paths only.

## Tone Rules

- No self-narration ("I will now...", "let me summarize...").
- No long completion checklists unless the user asks for them.
- End with the direct outcome and at most one next action suggestion.

## Exemptions

- Short confirmations and quick Q&A can be one sentence.
- Error responses should be direct and minimal.
