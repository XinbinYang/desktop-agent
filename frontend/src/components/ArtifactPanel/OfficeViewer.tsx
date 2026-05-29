import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  FileSpreadsheet,
  FolderOpen,
  Package,
  Presentation,
  Save,
  Search,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { API_BASE } from '../../config';
import type { ArtifactItem, ArtifactPayload } from '../../types';

interface OfficeViewerProps {
  item: ArtifactItem;
}

type OfficeKind = 'excel' | 'ppt' | 'office';

interface OfficeManifest {
  version?: number;
  artifact_id?: string;
  kind?: string;
  title?: string;
  file_url?: string;
  file_path?: string;
  mime_type?: string;
  size?: number;
  sha256?: string;
  workbook?: Record<string, any>;
  presentation?: Record<string, any>;
  previews?: ArtifactPayload[];
  qa_summary?: Record<string, any>;
  render_engine?: string;
  render_issues?: string[];
  available_actions?: string[];
}

function formatBytes(value?: number): string {
  if (!value || value < 0) return '';
  if (value < 1024) return `${value} B`;
  const kb = value / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(1)} MB`;
}

function assetUrl(url?: string): string {
  if (!url) return '';
  if (url.startsWith('/')) return `${API_BASE}${url}`;
  return url;
}

function fileKind(item: Pick<ArtifactPayload, 'title' | 'mimeType' | 'mime_type' | 'kind'>): OfficeKind {
  const title = item.title || '';
  const ext = title.split('.').pop()?.toLowerCase();
  const mime = item.mimeType || item.mime_type || '';
  if (item.kind === 'excel' || ext === 'xlsx' || ext === 'xls' || mime.includes('spreadsheet')) return 'excel';
  if (item.kind === 'ppt' || ext === 'pptx' || ext === 'ppt' || mime.includes('presentation')) return 'ppt';
  return 'office';
}

function kindLabel(kind: string): string {
  if (kind === 'excel') return 'Excel workbook';
  if (kind === 'ppt') return 'PowerPoint deck';
  return 'Office file';
}

function fileIcon(kind: string) {
  return kind === 'ppt' ? Presentation : FileSpreadsheet;
}

function normalizeFile(item: ArtifactItem): ArtifactPayload {
  return {
    id: item.id,
    type: item.type,
    title: item.title,
    url: item.url,
    path: item.path,
    mimeType: item.mimeType,
    size: item.size,
    kind: item.kind,
    workbook: item.workbook,
    presentation: item.presentation,
    previews: item.previews,
    qa_summary: item.qaSummary,
    engine: item.engine,
    office_manifest_id: item.officeManifestId,
    manifest_path: item.manifestPath,
    manifest_url: item.manifestUrl,
    viewer_manifest_url: item.viewerManifestUrl,
    sha256: item.sha256,
    render_issues: item.renderIssues,
    available_actions: item.availableActions,
  };
}

function manifestUrlFor(file: ArtifactPayload): string {
  if (file.viewer_manifest_url) return file.viewer_manifest_url;
  if (file.manifest_url) return file.manifest_url;
  if (file.office_manifest_id) return `/api/office/${file.office_manifest_id}/manifest`;
  if (file.id?.startsWith('artifact_')) return `/api/office/${file.id}/manifest`;
  return '';
}

const QABadge: React.FC<{ status?: string }> = ({ status }) => {
  const value = status || 'unknown';
  const passed = value === 'passed';
  return (
    <span className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium ${passed ? 'bg-emerald-100 text-emerald-700' : value === 'failed' ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-700'}`}>
      <CheckCircle2 className="h-3 w-3" />
      {value}
    </span>
  );
};

function workbookSheets(workbook?: Record<string, any>): any[] {
  return Array.isArray(workbook?.sheets) ? workbook?.sheets : [];
}

function sheetDisplayRows(sheet: any): any[][] {
  if (Array.isArray(sheet?.rows)) return sheet.rows;
  if (Array.isArray(sheet?.sample)) {
    return sheet.sample.map((row: any[]) => row.map((value) => ({ value, formula: null, address: '' })));
  }
  return [];
}

function columnLabel(index: number): string {
  let value = index + 1;
  let label = '';
  while (value > 0) {
    const remainder = (value - 1) % 26;
    label = String.fromCharCode(65 + remainder) + label;
    value = Math.floor((value - 1) / 26);
  }
  return label;
}

function cellAddress(rowIndex: number, colIndex: number, cell: any): string {
  return String(cell?.address || `${columnLabel(colIndex)}${rowIndex + 1}`);
}

function cellRawValue(cell: any): any {
  if (cell?.formula) return cell.formula;
  return cell?.value ?? '';
}

function cellText(cell: any): string {
  const value = cellRawValue(cell);
  if (value == null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function parseLiteral(value: string): string | number | boolean | null {
  const text = value.trim();
  if (!text) return '';
  if (text === 'true') return true;
  if (text === 'false') return false;
  if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text);
  return value;
}

function styleForCell(cell: any): React.CSSProperties {
  const style = cell?.style || {};
  const result: React.CSSProperties = {};
  if (style.fill && typeof style.fill === 'string' && style.fill.startsWith('#') && style.fill.toUpperCase() !== '#000000') {
    result.backgroundColor = style.fill;
  }
  if (style.font_color && typeof style.font_color === 'string' && style.font_color.startsWith('#')) {
    result.color = style.font_color;
  }
  if (style.bold) result.fontWeight = 700;
  if (style.italic) result.fontStyle = 'italic';
  return result;
}

const ChartPreview: React.FC<{ sheet: any }> = ({ sheet }) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const charts = Array.isArray(sheet?.charts) ? sheet.charts : [];

  useEffect(() => {
    if (!ref.current || charts.length === 0) return undefined;
    const rows = sheetDisplayRows(sheet).slice(1, 9);
    const points = rows.map((row) => ({
      label: cellText(row[0]) || '',
      value: Number(cellRawValue(row.find((cell) => typeof cellRawValue(cell) === 'number')) || 0),
    })).filter((point) => point.label && Number.isFinite(point.value));
    if (!points.length) return undefined;
    const chart = echarts.init(ref.current);
    chart.setOption({
      animation: false,
      grid: { left: 40, right: 14, top: 24, bottom: 28 },
      xAxis: { type: 'category', data: points.map((point) => point.label), axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
      series: [{ type: 'bar', data: points.map((point) => point.value), itemStyle: { color: '#2563eb' } }],
      tooltip: { trigger: 'axis' },
    });
    return () => chart.dispose();
  }, [charts.length, sheet]);

  if (!charts.length) return null;
  return (
    <div className="border-l border-border bg-app p-3">
      <div className="mb-2 text-xs font-medium text-fg-secondary">Charts</div>
      <div ref={ref} className="h-44 w-72 rounded border border-border bg-white" />
      <div className="mt-2 max-w-72 text-[11px] text-fg-muted">
        {charts.map((chart: any) => chart.title || chart.type).filter(Boolean).join(' · ')}
      </div>
    </div>
  );
};

const WorkbookViewer: React.FC<{
  file: ArtifactPayload;
  manifest?: OfficeManifest;
  onStatus: (status: string) => void;
}> = ({ file, manifest, onStatus }) => {
  const workbook = manifest?.workbook || file.workbook || {};
  const sheets = workbookSheets(workbook);
  const [activeSheetName, setActiveSheetName] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [zoom, setZoom] = useState(100);
  const [selected, setSelected] = useState<{ row: number; col: number } | null>(null);
  const [editText, setEditText] = useState('');
  const [edits, setEdits] = useState<Record<string, { sheet: string; cell: string; value: string }>>({});
  const [savedCopy, setSavedCopy] = useState<ArtifactPayload | null>(null);
  const [saving, setSaving] = useState(false);
  const activeSheet = sheets.find((sheet) => sheet.name === activeSheetName) || sheets[0];
  const rows = sheetDisplayRows(activeSheet);

  useEffect(() => {
    if (sheets[0]?.name && (!activeSheetName || !sheets.some((sheet) => sheet.name === activeSheetName))) {
      setActiveSheetName(String(sheets[0].name));
    }
  }, [activeSheetName, sheets]);

  const selectedCell = selected ? rows[selected.row]?.[selected.col] : null;
  const selectedAddress = selected && selectedCell ? cellAddress(selected.row, selected.col, selectedCell) : 'A1';
  const selectedKey = activeSheet ? `${activeSheet.name}!${selectedAddress}` : '';
  const selectedHasFormula = Boolean(selectedCell?.formula);

  useEffect(() => {
    if (!selectedCell) {
      setEditText('');
      return;
    }
    const pending = edits[selectedKey];
    setEditText(pending ? pending.value : cellText(selectedCell));
  }, [edits, selectedCell, selectedKey]);

  const filteredRows = useMemo(() => {
    const textQuery = query.trim().toLowerCase();
    const filterQuery = filter.trim().toLowerCase();
    if (!textQuery && !filterQuery) return rows;
    const header = rows[0] ? [rows[0]] : [];
    const body = rows.slice(1).filter((row) => {
      const joined = row.map(cellText).join(' ').toLowerCase();
      return (!textQuery || joined.includes(textQuery)) && (!filterQuery || joined.includes(filterQuery));
    });
    return [...header, ...body];
  }, [filter, query, rows]);

  const updateEdit = (value: string) => {
    setEditText(value);
    if (!selected || !activeSheet || selectedHasFormula) return;
    setEdits((prev) => ({
      ...prev,
      [selectedKey]: { sheet: activeSheet.name, cell: selectedAddress, value },
    }));
  };

  const copySelection = async () => {
    if (!selectedCell) return;
    await navigator.clipboard?.writeText(cellText(selectedCell));
    onStatus(`Copied ${selectedAddress}`);
  };

  const saveEdits = async () => {
    const artifactId = manifest?.artifact_id || file.office_manifest_id || file.id;
    const payload = Object.values(edits).map((edit) => ({
      sheet: edit.sheet,
      cell: edit.cell,
      value: parseLiteral(edit.value),
    }));
    if (!artifactId || payload.length === 0) return;
    setSaving(true);
    try {
      const response = await fetch(assetUrl(`/api/office/${artifactId}/xlsx/simple-edits`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ edits: payload, output_name: file.title }),
      });
      if (!response.ok) throw new Error(await response.text());
      const saved = await response.json();
      setSavedCopy(saved);
      setEdits({});
      onStatus(`Saved edited workbook copy: ${saved.title || 'workbook'}`);
    } catch (error) {
      onStatus(error instanceof Error ? error.message : 'Could not save workbook edits');
    } finally {
      setSaving(false);
    }
  };

  const openSavedCopy = async () => {
    if (!savedCopy) return;
    if (savedCopy.path && window.electronAPI?.openPath) {
      const error = await window.electronAPI.openPath(savedCopy.path);
      onStatus(error || 'Opened saved copy');
      return;
    }
    if (savedCopy.url) {
      window.open(assetUrl(savedCopy.url), '_blank', 'noopener,noreferrer');
      onStatus('Opened saved copy URL');
    }
  };

  if (!sheets.length) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-sm text-fg-muted">
        Workbook structure is unavailable. Open the local file for full editing.
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-white">
      <div className="shrink-0 border-b border-border bg-surface">
        <div className="flex flex-wrap items-center gap-2 px-3 py-2">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {sheets.map((sheet) => (
              <button
                key={sheet.name}
                type="button"
                onClick={() => { setActiveSheetName(sheet.name); setSelected(null); }}
                className={`rounded px-3 py-1.5 text-xs ${sheet.name === activeSheet?.name ? 'bg-accent text-white' : 'text-fg-secondary hover:bg-surface-hover'}`}
              >
                {sheet.name}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1 rounded border border-border bg-app px-2 py-1 text-xs text-fg-secondary">
            <Search className="h-3.5 w-3.5" />
            <input aria-label="Search workbook" value={query} onChange={(event) => setQuery(event.target.value)} className="w-32 bg-transparent outline-none" placeholder="Search" />
          </label>
          <input aria-label="Filter rows" value={filter} onChange={(event) => setFilter(event.target.value)} className="w-32 rounded border border-border bg-app px-2 py-1 text-xs outline-none" placeholder="Filter rows" />
          <button type="button" aria-label="Zoom out workbook" onClick={() => setZoom((value) => Math.max(60, value - 10))} className="rounded border border-border bg-app p-1.5 hover:bg-surface-hover">
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <span className="w-12 text-center text-xs text-fg-muted">{zoom}%</span>
          <button type="button" aria-label="Zoom in workbook" onClick={() => setZoom((value) => Math.min(180, value + 10))} className="rounded border border-border bg-app p-1.5 hover:bg-surface-hover">
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="flex items-center gap-2 border-t border-border px-3 py-2">
          <span className="w-14 rounded border border-border bg-app px-2 py-1 text-center font-mono text-xs text-fg-secondary">{selectedAddress}</span>
          <input
            aria-label="Formula bar"
            value={editText}
            onChange={(event) => updateEdit(event.target.value)}
            disabled={!selectedCell || selectedHasFormula}
            className="min-w-0 flex-1 rounded border border-border bg-app px-2 py-1 text-xs outline-none disabled:text-fg-muted"
            placeholder={selectedHasFormula ? 'Formula cells are read-only in lightweight preview' : 'Select a cell to inspect or edit value'}
          />
          <button type="button" onClick={copySelection} disabled={!selectedCell} className="inline-flex items-center gap-1.5 rounded border border-border bg-app px-2 py-1 text-xs text-fg hover:bg-surface-hover disabled:opacity-50">
            <Copy className="h-3.5 w-3.5" />
            Copy
          </button>
          <button type="button" onClick={saveEdits} disabled={saving || Object.keys(edits).length === 0} className="inline-flex items-center gap-1.5 rounded border border-border bg-app px-2 py-1 text-xs text-fg hover:bg-surface-hover disabled:opacity-50">
            <Save className="h-3.5 w-3.5" />
            Save copy
          </button>
          {savedCopy && (
            <button type="button" onClick={openSavedCopy} className="rounded border border-border bg-app px-2 py-1 text-xs text-fg hover:bg-surface-hover">
              Open saved
            </button>
          )}
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-auto bg-white">
          <div style={{ transform: `scale(${zoom / 100})`, transformOrigin: 'top left' }} className="inline-block p-3">
            <table className="border-collapse text-xs text-fg">
              <thead>
                <tr>
                  <th className="sticky left-0 top-0 z-30 h-7 w-12 border border-border bg-surface-alt" />
                  {Array.from({ length: Math.max(activeSheet?.col_limit || 0, filteredRows[0]?.length || 0) }).map((_, colIndex) => (
                    <th key={colIndex} className="sticky top-0 z-20 h-7 min-w-28 border border-border bg-surface-alt px-2 text-center font-medium text-fg-muted">
                      {columnLabel(colIndex)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row, rowIndex) => (
                  <tr key={`${activeSheet?.name}-${rowIndex}`}>
                    <th className="sticky left-0 z-10 h-7 w-12 border border-border bg-surface-alt px-2 text-right font-normal text-fg-muted">
                      {rowIndex + 1}
                    </th>
                    {row.map((cell, colIndex) => {
                      const address = cellAddress(rowIndex, colIndex, cell);
                      const key = `${activeSheet?.name}!${address}`;
                      const pending = edits[key]?.value;
                      const selectedHere = selected?.row === rowIndex && selected?.col === colIndex;
                      return (
                        <td
                          key={address}
                          onClick={() => setSelected({ row: rowIndex, col: colIndex })}
                          style={styleForCell(cell)}
                          className={`h-7 min-w-28 max-w-56 cursor-cell border border-border px-2 py-1 align-middle ${rowIndex === 0 ? 'bg-slate-900 font-semibold text-white' : 'bg-white'} ${selectedHere ? 'outline outline-2 outline-accent' : ''}`}
                        >
                          <span className="block truncate">{pending ?? cellText(cell)}</span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <ChartPreview sheet={activeSheet} />
      </div>
    </div>
  );
};

function presentationSlides(presentation?: Record<string, any>): any[] {
  return Array.isArray(presentation?.slides) ? presentation?.slides : [];
}

function previewForSlide(previews: ArtifactPayload[], slideIndex: number): ArtifactPayload | undefined {
  const slidePreviews = previews.filter((preview) => preview.kind === 'ppt_slide');
  return slidePreviews[slideIndex];
}

const StructuralSlide: React.FC<{ slide: any; presentation?: Record<string, any>; zoom: number }> = ({ slide, presentation, zoom }) => {
  const width = Number(presentation?.slide_width || 13.333);
  const height = Number(presentation?.slide_height || 7.5);
  const shapes = Array.isArray(slide?.shapes) ? slide.shapes : [];
  return (
    <div
      className="relative mx-auto overflow-hidden border border-border bg-[#f8f4ea] shadow-sm"
      style={{ width: `${Math.round(960 * zoom / 100)}px`, aspectRatio: `${width} / ${height}` }}
    >
      {shapes.map((shape: any) => {
        const bounds = shape.bounds || {};
        const left = `${(Number(bounds.x || 0) / width) * 100}%`;
        const top = `${(Number(bounds.y || 0) / height) * 100}%`;
        const boxWidth = `${(Number(bounds.w || 1) / width) * 100}%`;
        const boxHeight = `${(Number(bounds.h || 1) / height) * 100}%`;
        const text = String(shape.text || '');
        return (
          <div
            key={shape.index}
            className={`absolute overflow-hidden p-2 text-slate-900 ${shape.has_table ? 'border border-slate-300 bg-white/80' : shape.has_image ? 'border border-slate-300 bg-slate-200' : ''}`}
            style={{ left, top, width: boxWidth, height: boxHeight }}
          >
            {shape.has_table && Array.isArray(shape.table) ? (
              <table className="h-full w-full border-collapse text-[10px]">
                <tbody>
                  {shape.table.slice(0, 6).map((row: any[], rowIndex: number) => (
                    <tr key={rowIndex}>
                      {row.slice(0, 4).map((cell, colIndex) => (
                        <td key={colIndex} className="border border-slate-300 px-1 py-0.5">{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : text ? (
              <div className={`${shape.index === 1 ? 'text-xl font-semibold' : 'text-sm'} leading-tight`}>{text}</div>
            ) : shape.has_image ? (
              <div className="flex h-full items-center justify-center text-xs text-slate-500">Image</div>
            ) : null}
          </div>
        );
      })}
      {!shapes.length && (
        <div className="flex h-full items-center justify-center text-sm text-fg-muted">{slide?.title || 'Slide preview'}</div>
      )}
    </div>
  );
};

const DeckViewer: React.FC<{
  file: ArtifactPayload;
  manifest?: OfficeManifest;
  previews: ArtifactPayload[];
}> = ({ file, manifest, previews }) => {
  const presentation = manifest?.presentation || file.presentation || {};
  const slides = presentationSlides(presentation);
  const [activeIndex, setActiveIndex] = useState(0);
  const [query, setQuery] = useState('');
  const [zoom, setZoom] = useState(100);
  const activeSlide = slides[activeIndex] || {};
  const activePreview = previewForSlide(previews, activeIndex);
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return new Set<number>();
    return new Set(slides
      .map((slide, index) => ({ index, text: [slide.title, ...(slide.texts || []), slide.notes].join(' ').toLowerCase() }))
      .filter((entry) => entry.text.includes(needle))
      .map((entry) => entry.index));
  }, [query, slides]);

  useEffect(() => {
    if (activeIndex >= Math.max(slides.length, 1)) setActiveIndex(0);
  }, [activeIndex, slides.length]);

  const go = (next: number) => setActiveIndex(Math.min(Math.max(next, 0), Math.max(0, slides.length - 1)));

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-app">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-2">
        <button type="button" aria-label="Previous slide" onClick={() => go(activeIndex - 1)} className="rounded border border-border bg-app p-1.5 hover:bg-surface-hover">
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="text-xs text-fg-secondary">{slides.length ? activeIndex + 1 : 0} / {slides.length || 0}</span>
        <button type="button" aria-label="Next slide" onClick={() => go(activeIndex + 1)} className="rounded border border-border bg-app p-1.5 hover:bg-surface-hover">
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
        <input
          aria-label="Go to slide"
          type="number"
          min={1}
          max={Math.max(1, slides.length)}
          value={slides.length ? activeIndex + 1 : 0}
          onChange={(event) => go(Number(event.target.value || 1) - 1)}
          className="w-16 rounded border border-border bg-app px-2 py-1 text-xs outline-none"
        />
        <label className="ml-auto flex items-center gap-1 rounded border border-border bg-app px-2 py-1 text-xs text-fg-secondary">
          <Search className="h-3.5 w-3.5" />
          <input aria-label="Search slides" value={query} onChange={(event) => setQuery(event.target.value)} className="w-40 bg-transparent outline-none" placeholder="Search deck" />
        </label>
        <button type="button" aria-label="Zoom out deck" onClick={() => setZoom((value) => Math.max(50, value - 10))} className="rounded border border-border bg-app p-1.5 hover:bg-surface-hover">
          <ZoomOut className="h-3.5 w-3.5" />
        </button>
        <span className="w-12 text-center text-xs text-fg-muted">{zoom}%</span>
        <button type="button" aria-label="Zoom in deck" onClick={() => setZoom((value) => Math.min(160, value + 10))} className="rounded border border-border bg-app p-1.5 hover:bg-surface-hover">
          <ZoomIn className="h-3.5 w-3.5" />
        </button>
        <button type="button" onClick={() => setZoom(100)} className="rounded border border-border bg-app px-2 py-1 text-xs hover:bg-surface-hover">Fit</button>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="w-48 shrink-0 overflow-auto border-r border-border bg-surface p-2">
          {slides.map((slide, index) => {
            const preview = previewForSlide(previews, index);
            const active = index === activeIndex;
            return (
              <button
                key={slide.id || index}
                type="button"
                onClick={() => setActiveIndex(index)}
                className={`mb-2 block w-full rounded border p-1 text-left ${active ? 'border-accent bg-accent/10' : 'border-border bg-app hover:bg-surface-hover'}`}
              >
                {preview?.url ? (
                  <img src={assetUrl(preview.url)} alt={preview.title || `Slide ${index + 1}`} className="aspect-video w-full rounded object-cover" />
                ) : (
                  <div className="flex aspect-video items-center justify-center rounded bg-surface-alt text-[10px] text-fg-muted">{index + 1}</div>
                )}
                <div className="mt-1 flex items-center gap-1 text-[10px] text-fg-muted">
                  <span>{index + 1}</span>
                  <span className="truncate">{slide.title || `Slide ${index + 1}`}</span>
                  {matches.has(index) && <span className="ml-auto rounded bg-accent/10 px-1 text-accent">match</span>}
                </div>
              </button>
            );
          })}
        </div>
        <div className="min-w-0 flex-1 overflow-auto p-5">
          {activePreview?.url ? (
            <img
              src={assetUrl(activePreview.url)}
              alt={activePreview.title || 'PowerPoint preview'}
              className="mx-auto border border-border bg-white shadow-sm"
              style={{ width: `${Math.round(960 * zoom / 100)}px` }}
            />
          ) : slides.length ? (
            <StructuralSlide slide={activeSlide} presentation={presentation} zoom={zoom} />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-fg-muted">
              Deck structure is unavailable. Open the local file for full editing.
            </div>
          )}
        </div>
        <div className="hidden w-72 shrink-0 overflow-auto border-l border-border bg-surface p-3 xl:block">
          <div className="text-xs font-semibold text-fg">Slide text</div>
          <div className="mt-2 space-y-2 text-xs text-fg-secondary">
            <div className="font-medium text-fg">{activeSlide.title || `Slide ${activeIndex + 1}`}</div>
            {(activeSlide.texts || []).map((text: string, index: number) => (
              <p key={index} className="leading-relaxed">{text}</p>
            ))}
            {activeSlide.notes && (
              <div className="mt-3 rounded border border-border bg-app p-2">
                <div className="mb-1 font-medium text-fg">Notes</div>
                <p className="leading-relaxed">{activeSlide.notes}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export const OfficeViewer: React.FC<OfficeViewerProps> = ({ item }) => {
  const [status, setStatus] = useState('');
  const [manifestByFile, setManifestByFile] = useState<Record<string, OfficeManifest | null>>({});
  const files = item.type === 'office_package' && item.files?.length ? item.files : [normalizeFile(item)];
  const [activeFileId, setActiveFileId] = useState(files[0]?.id || item.id);
  const activeFile = files.find((file) => file.id === activeFileId) || files[0] || normalizeFile(item);
  const manifestUrl = manifestUrlFor(activeFile);
  const manifest = manifestByFile[activeFile.id] || undefined;
  const effectiveKind = fileKind({ ...activeFile, kind: manifest?.kind || activeFile.kind });
  const Icon = useMemo(() => (item.type === 'office_package' ? Package : fileIcon(effectiveKind)), [item.type, effectiveKind]);
  const previews = [
    ...(manifest?.previews || []),
    ...(activeFile.previews || []),
    ...(item.previews || []),
  ];
  const qaSummary = manifest?.qa_summary || item.qaSummary || activeFile.qa_summary || {};
  const activeQa = effectiveKind === 'excel' ? qaSummary.excel : effectiveKind === 'ppt' ? qaSummary.ppt : qaSummary;
  const engine = manifest?.render_engine || activeFile.engine || item.engine;
  const effectiveFile: ArtifactPayload = {
    ...activeFile,
    kind: manifest?.kind || activeFile.kind,
    workbook: manifest?.workbook || activeFile.workbook,
    presentation: manifest?.presentation || activeFile.presentation,
    previews,
    office_manifest_id: manifest?.artifact_id || activeFile.office_manifest_id,
  };

  useEffect(() => {
    if (!manifestUrl || manifestByFile[activeFile.id] !== undefined) return;
    let cancelled = false;
    fetch(assetUrl(manifestUrl))
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!cancelled) setManifestByFile((prev) => ({ ...prev, [activeFile.id]: data }));
      })
      .catch(() => {
        if (!cancelled) setManifestByFile((prev) => ({ ...prev, [activeFile.id]: null }));
      });
    return () => { cancelled = true; };
  }, [activeFile.id, manifestByFile, manifestUrl]);

  const openPath = async (file: ArtifactPayload = activeFile) => {
    if (file.path && window.electronAPI?.openPath) {
      const error = await window.electronAPI.openPath(file.path);
      setStatus(error || 'Opened');
      return;
    }
    const url = manifest?.file_url || file.url;
    if (url) {
      window.open(assetUrl(url), '_blank', 'noopener,noreferrer');
      setStatus('Opened preview URL');
      return;
    }
    setStatus('No local path or URL is available');
  };

  const revealPath = async (file: ArtifactPayload = activeFile) => {
    if (!file.path || !window.electronAPI?.revealPath) {
      setStatus('Reveal is unavailable');
      return;
    }
    const error = await window.electronAPI.revealPath(file.path);
    setStatus(error || 'Shown in folder');
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-app">
      <div className="shrink-0 border-b border-border bg-surface px-4 py-3">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded bg-accent/10 text-accent">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-fg">{item.title}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <span>{item.type === 'office_package' ? `${files.length} final files` : kindLabel(effectiveKind)}</span>
              {formatBytes(item.size || activeFile.size || manifest?.size) && <span>{formatBytes(item.size || activeFile.size || manifest?.size)}</span>}
              {engine && <span>{engine}</span>}
              {activeQa?.qa_status && <QABadge status={activeQa.qa_status} />}
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <button type="button" onClick={() => openPath()} className="inline-flex items-center gap-1.5 rounded border border-border bg-app px-3 py-1.5 text-xs text-fg hover:bg-surface-hover">
              <ExternalLink className="h-3.5 w-3.5" />
              Open
            </button>
            <button type="button" onClick={() => revealPath()} className="inline-flex items-center gap-1.5 rounded border border-border bg-app px-3 py-1.5 text-xs text-fg hover:bg-surface-hover">
              <FolderOpen className="h-3.5 w-3.5" />
              Show
            </button>
          </div>
        </div>
        {files.length > 1 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {files.map((file) => {
              const itemKind = fileKind(file);
              const FileIcon = fileIcon(itemKind);
              const active = file.id === activeFile.id;
              return (
                <button
                  key={file.id}
                  type="button"
                  onClick={() => setActiveFileId(file.id)}
                  className={`inline-flex min-w-0 items-center gap-2 rounded border px-3 py-2 text-xs ${active ? 'border-accent bg-accent/10 text-fg' : 'border-border bg-app text-fg-secondary hover:bg-surface-hover'}`}
                >
                  <FileIcon className="h-3.5 w-3.5 shrink-0" />
                  <span className="max-w-56 truncate">{file.title}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {effectiveKind === 'excel' ? (
        <WorkbookViewer file={effectiveFile} manifest={manifest} onStatus={setStatus} />
      ) : effectiveKind === 'ppt' ? (
        <DeckViewer file={effectiveFile} manifest={manifest} previews={previews} />
      ) : (
        <div className="flex flex-1 items-center justify-center p-6 text-sm text-fg-muted">
          This Office file can be opened locally. No inline preview metadata is available.
        </div>
      )}

      {status && <div className="shrink-0 border-t border-border bg-surface px-4 py-2 text-xs text-fg-secondary">{status}</div>}
    </div>
  );
};
