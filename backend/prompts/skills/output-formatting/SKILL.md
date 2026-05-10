---
name: output-formatting
description: Use for ALL responses — standard Markdown output style for clean, professional, scannable agent output. Replaces star ratings with status symbols, enforces consistent heading hierarchy, and specifies clear file reference format.
---

# Output Formatting Style Guide

Every response you generate must follow the formatting rules defined in `STYLE_GUIDE.md`. The goal is clean, professional output that mirrors the quality of Claude Code / Codex — scannable, well-structured, and visually consistent.

## Quick Reference

| Rule                | Do                                         | Don't                          |
|---------------------|--------------------------------------------|---------------------------------|
| Headings            | `##` → `###` → `####`, no skipping        | `#` without `##`, unbalanced   |
| Status              | `✅` `⚠️` `❌` `ℹ️`                        | `★☆` `⭐⭐⭐` Unicode stars      |
| Scores              | `"4/5 — 良好"`                              | `"★★★★☆"`                       |
| File references     | `` `path/to/file:42` ``                    | Bare paths, no line numbers     |
| Conclusions         | `>` blockquote                             | Inline text mixed with details  |
| Code blocks         | Always mark language                       | Unlabelled fences               |
| Tables              | Standard Markdown, header row required     | Nested tables, raw ASCII art    |

Apply these rules in every response. Consistency is the point.
