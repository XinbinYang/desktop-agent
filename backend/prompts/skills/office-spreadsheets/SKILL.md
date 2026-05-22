---
name: office-spreadsheets
description: Create, edit, validate, render, and publish product-grade Excel workbooks with the Office artifact tools.
---

# Office Spreadsheets

Use this skill when the user asks for Excel, XLSX, spreadsheets, workbooks, formulas, tables, charts, dashboards, or an analytical workbook deliverable.

## Product-Grade Workflow

1. For a standalone workbook, call `excel_create` or `excel_edit`, then always call `excel_validate` and `excel_render`.
2. For an Excel+PPT deliverable, first call `office_package_create`, build the workbook, run `office_package_qa`, then finish with `office_package_publish`.
3. For analytical/financial workbooks, prefer `quality_profile: "analysis_dashboard"` unless the user asks for a plain data file.
4. Never stop at CSV or raw Python output when the user expects Excel. The final user-facing file must be `.xlsx`.
5. Keep scratch/build files in the Office runtime workspace. Only final `.xlsx` artifacts should be published.
6. Publishing a workbook must create an Office Artifact Manifest v2. Do not publish image-only substitutes for workbook tasks.

## Workbook Quality Bar

- Default analytical structure: `Dashboard`, `Data`, `Assumptions`, and `Checks`.
- Pass sheet data with `columns` + `rows` (not a raw `data` grid) so the header row is auto-styled, frozen, and bordered.
- Column widths are auto-fitted to content — do **not** hand-tune `widths` unless a specific column must be a fixed size.
- Use typed semantic values for numbers, currency, percent, multiples, dates, and formulas. Never store a visible number as a string like `"$388.91"` or `"47%"` — `excel_create` reports `text_as_number_count` and any nonzero count is a defect to fix.
- Use formulas for derived values and keep editable drivers in the `Assumptions` sheet.
- Add tables, filters, validation, conditional formatting, number formats, and native charts where useful.
- Make the first sheet presentation-ready: KPI strip, clear labels, chart area, and check/status cells.
- Prefer a native chart over a wall of numbers whenever the point is a comparison or trend.

## QA Contract

- Validate formulas/reference errors before final delivery.
- Always read the text QA report in the tool result (issues, formula errors, `text_as_number_count`). This works for every model.
- `excel_render` and `office_package_qa` also return rendered sheet images — **if you can see images**, inspect them for clipped columns, blank areas, numbers-as-text, or a structurally weak first sheet. Fix and rerun QA before publishing.
- Render previews with native Excel COM when available; if unavailable, accept the structural preview but say so.
- The manifest must include workbook structure, previews, file hash, QA summary, render engine, and viewer actions.
- For Excel+PPT deliverables, the PPT must reuse this workbook's data model — keep numbers and labels consistent across both files.
- Final reply should summarize sheet count, formula/check status, chart count, and preview/render engine.
