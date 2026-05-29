---
name: office-presentations
description: Create, edit, validate, render, and publish product-grade PowerPoint decks with the Office artifact tools.
---

# Office Presentations

Use this skill when the user asks for PPT, PPTX, PowerPoint, slides, decks, presentations, reports, strategy documents, or a slide deliverable.

## Core Contract: Semantic Content Only

`ppt_create` / `ppt_edit` run a deterministic auto-layout engine. **You provide semantic content; the engine computes every coordinate, font size, line wrap, and page break.**

- **Never set `x`, `y`, `w`, or `h` on blocks.** Hand-computed coordinates cause overlap and overflow. The engine measures real text and places everything.
- Set a `layout` per slide: `cover`, `section`, `bullets`, `table`, `kpi`, `two-column`, `data-story`, or `comparison`.
- A slide is `{layout, kicker, title, subtitle, footer, blocks: [...], speaker_notes}`.
- Block types: `text`, `bullets`, `table`, `kpi_cards`, `chart`, `callout`, `image`. The engine auto-paginates a slide into continuation pages when content overflows.

## Slide Discipline (the engine relies on this)

- One claim per slide. The `title` states the takeaway; the `subtitle` adds one line of context.
- Bullets: <= 6 items per block, one idea each — not sentences crammed into a cell.
- Tables: <= 6 columns and <= 8 body rows per slide. If data is larger, split it or turn it into a `chart`.
- Prefer `kpi_cards` for headline numbers and `chart` for comparisons over dense tables. Dense numeric tables are the #1 cause of unreadable slides.
- Keep each cell value short (a number, a phrase). Long prose belongs in `text`/`callout`, not table cells.

## Example slide spec

```json
{
  "layout": "kpi",
  "kicker": "组合全景",
  "title": "新秩序多空组合 · 全景",
  "subtitle": "做多 57% | 做空 38% | 尾部保护 5%",
  "footer": "投资组合分析 · 2026",
  "blocks": [
    {"type": "kpi_cards", "items": [
      {"value": "57%", "label": "做多 新秩序赢家"},
      {"value": "38%", "label": "做空 旧秩序输家"},
      {"value": "+19%", "label": "净敞口"}
    ]},
    {"type": "table", "header": true, "rows": [
      ["类别", "权重", "逻辑"],
      ["AI 基建", "20%", "芯片代工 + Cloud 高增长"]
    ]},
    {"type": "callout", "heading": "核心转变", "text": "从买什么资产，转为做多/做空/对冲什么。"}
  ]
}
```

## Workflow

1. Draft a claim spine first: one clear job for every slide.
2. Build with `ppt_create` / `ppt_edit` using semantic specs only.
3. Always call `ppt_render` after creating or editing.
4. For Excel+PPT deliverables, reuse the workbook's data model and finish with `office_package_publish`.
5. Only publish the final `.pptx` plus the preview/contact-sheet artifacts needed for QA.

## Mandatory QA Loop

After every render, QA the deck before publishing:

1. Render with `ppt_render` (or `office_package_qa`).
2. **Always** read the text layout QA report in the tool result — `layout_errors`, `layout_warnings`, `issues`. Any `layout_error` (overlap, out-of-bounds, text overflow, empty slide) is a hard blocker. This check works for every model.
3. **If you can see images**, the render also returns slide previews — inspect each one like a human reviewer for crowding, weak hierarchy, broken tables/charts, and anything pure geometry checks miss. If you cannot see images, rely on the layout report from step 2.
4. If QA reports problems, fix them with `ppt_edit` and render again. Repeat until the layout report is clean.
5. Only call `office_package_publish` once QA is clean.

The final reply should summarize slide count, layout errors/warnings, render engine, and the published files.
