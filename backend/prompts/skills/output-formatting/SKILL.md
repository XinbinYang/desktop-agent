---
name: output-formatting
description: Use for ALL responses — Claude-like concise, scannable output. Prioritize high signal density, minimal formatting noise, and consistent code/file references.
---

# Output Formatting Style Guide

Every response you generate must follow the formatting rules defined in `STYLE_GUIDE.md`. The goal is clean, professional output that mirrors the quality of Claude Code / Codex — scannable, well-structured, and visually consistent.

## Quick Reference

| Rule | Do | Don't |
|------|----|-------|
| Brevity | Give direct answer first | Long ceremonial intros |
| Structure | Use headings/lists only when needed | Force report template every time |
| Tool narration | Compress repetitive actions | Dump every read/search step verbatim |
| Symbols | Keep plain text unless needed | Decorative emoji/status icons by default |
| File references | Use `` `path:line` `` when citing code | Bare ambiguous references |
| Tables | Use only for real comparisons | Turn normal answers into tables |

Apply this style consistently unless the user asks for a different format.
