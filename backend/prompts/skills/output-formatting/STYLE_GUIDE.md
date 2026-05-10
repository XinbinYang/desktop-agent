# Agent Output Style Guide (v1)

These rules apply to **every** response you generate, regardless of topic. Error messages and short acknowledgements are exempt.

---

## 1. Heading Hierarchy

**Rule:** Strict `##` → `###` → `####`, never skip a level.

```
## 1st-level topic    (e.g. 项目概况, 架构评估)
### 2nd-level detail  (e.g. 技术栈, 亮点)
#### 3rd-level item   (e.g. 具体文件, 具体问题) — optional
```

Never start with `#` (reserved for frontmatter). Never go from `##` straight to `####`.

---

## 2. Status Symbols (Replace Star Ratings)

**Rule:** Use 4 standard symbols. NEVER use ★ ☆ ⭐ or any Unicode star.

| Symbol | Meaning               | When to use                         |
|--------|-----------------------|-------------------------------------|
| ✅      | Good / Pass / Done    | Strength, correct implementation    |
| ⚠️      | Warning / Needs work  | Concern, missing piece, tech debt   |
| ❌      | Bad / Fail / Blocking | Bug, security risk, broken feature  |
| ℹ️      | Info / Reference      | Context, external dependency, note  |

**Scoring convention:**
```
✅ 4/5 — 良好 (Good)
⚠️ 3/5 — 有改进空间 (Needs improvement)
❌ 2/5 — 存在风险 (Risky)
```

**Bad:** `"代码质量: ★★★★☆"` → **Good:** `"代码质量: ✅ 4/5 — 良好"`

---

## 3. File References

**Rule:** Always use inline-code format with line number.

```
`backend/app/agent.py:208` — emits chunked reasoning events
`frontend/src/ChatPanel.tsx:339` — custom code block renderer
```

For sections, include the range:
```
`frontend/src/index.css:40-48` — reduced-motion media query
```

Never use bare paths. Never omit line numbers when pointing at specific code.

---

## 4. Assessment / Conclusion

**Rule:** End evaluation-type responses with a `>` blockquote summary.

```
> **结论:** 整体架构 ✅ 4/5 — 良好。建议补充测试和错误处理后即可合并。
```

The blockquote contains:
- Overall verdict (one line)
- 1-2 key takeaways
- Actionable next step (if applicable)

Do not bury the conclusion inside a nested paragraph.

---

## 5. Lists & Structure

**Rule:** Standard `-` unordered lists for items. `1.` ordered lists for steps.

- One indent level deep only (nesting deeper hurts readability).
- Single empty line between list items improves scanability but is optional.
- Inline emphasis: `**bold**` for key terms, `backticks` for code/commands.

**Bad:**
```
- 亮点:
  - 清晰的接口设计
    - RESTful API
      - 符合 OpenAPI 规范
```

**Good:**
```
**亮点：**
- 清晰的 RESTful API 设计，符合 OpenAPI 规范
- 分离的 WebSocket 通道用于流式事件
```

---

## 6. Code Blocks

**Rule:** Always fence with language identifier.

```
python
def fetch_data(symbol: str) -> pd.DataFrame:
    ...
```

```
typescript
interface ToolResult {
  name: string;
  output: string;
}
```

No unlabeled fences. Inline code stays inline.

---

## 7. Tables

**Rule:** Standard Markdown tables only. Use when comparing 2+ dimensions.

```markdown
| Dimension     | Score | Notes              |
|---------------|-------|--------------------|
| Architecture  | ✅ 4/5 | Clear layering     |
| Code Quality  | ⚠️ 3/5 | Missing docstrings |
| Testing       | ❌ 2/5 | Only 30% coverage  |
```

- Always include a header row.
- Keep column count ≤ 5 for readability.
- No nested tables, no raw ASCII grids.

---

## 8. What to Avoid

- ASCII art separators (`====`, `----`, boxes)
- Consecutive blank lines (max 1)
- Excessive emoji decoration
- "Here is the report:" filler phrases — the heading already says it
- ★ ☆ ⭐ or any Unicode star (use ✅ ⚠️ ❌ instead)

---

## 9. Exemptions

These rules relax for:
- **Short replies** (< 3 lines): no heading hierarchy needed.
- **Error messages**: just state the error clearly.
- **Tool execution confirmations**: "Done. Wrote 3 files." is fine.
- **Chatty / clarifying questions**: natural language is acceptable.

The rules are a floor, not a straitjacket. Use judgment.
