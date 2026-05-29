import { API_BASE } from '../config';
import type { ArtifactPayload, ImageAttachment } from '../types';

export function normalizeImageAttachment(value: unknown): ImageAttachment | null {
  if (!value) return null;
  if (typeof value === 'string') {
    return { base64: value, mimeType: 'image/png' };
  }
  if (typeof value !== 'object') return null;
  const raw = value as Record<string, any>;
  const base64 = typeof raw.base64 === 'string' ? raw.base64 : undefined;
  const url = typeof raw.url === 'string' ? raw.url : undefined;
  if (!base64 && !url) return null;
  return {
    id: typeof raw.id === 'string' ? raw.id : undefined,
    base64,
    url,
    title: typeof raw.title === 'string' ? raw.title : undefined,
    caption: typeof raw.caption === 'string' ? raw.caption : undefined,
    mimeType: typeof raw.mimeType === 'string' ? raw.mimeType : typeof raw.mime_type === 'string' ? raw.mime_type : undefined,
    mime_type: typeof raw.mime_type === 'string' ? raw.mime_type : undefined,
    path: typeof raw.path === 'string' ? raw.path : undefined,
    width: typeof raw.width === 'number' ? raw.width : undefined,
    height: typeof raw.height === 'number' ? raw.height : undefined,
    source: typeof raw.source === 'string' ? raw.source : undefined,
    toolCallId: typeof raw.toolCallId === 'string' ? raw.toolCallId : typeof raw.tool_call_id === 'string' ? raw.tool_call_id : undefined,
    tool_call_id: typeof raw.tool_call_id === 'string' ? raw.tool_call_id : undefined,
  };
}

export function normalizeArtifactPayload(value: unknown): ArtifactPayload | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, any>;
  const type = typeof raw.type === 'string' ? raw.type : '';
  if (!type) return null;
  const title = typeof raw.title === 'string' && raw.title.trim()
    ? raw.title
    : typeof raw.path === 'string'
      ? raw.path.split(/[\\/]/).pop() || 'Artifact'
      : 'Artifact';
  const id = typeof raw.id === 'string' && raw.id.trim()
    ? raw.id
    : `${type}:${raw.url || raw.path || title}`;
  const image = normalizeImageAttachment(raw) || {};
  const nestedFiles = normalizeArtifactPayloads(raw.files);
  const nestedPreviews = normalizeArtifactPayloads(raw.previews);
  return {
    ...image,
    id,
    type,
    title,
    content: typeof raw.content === 'string' ? raw.content : undefined,
    url: typeof raw.url === 'string' ? raw.url : undefined,
    base64: typeof raw.base64 === 'string' ? raw.base64 : undefined,
    timestamp: typeof raw.timestamp === 'number' ? raw.timestamp : undefined,
    source: typeof raw.source === 'string' ? raw.source : undefined,
    sourceTool: typeof raw.sourceTool === 'string' ? raw.sourceTool : undefined,
    source_tool: typeof raw.source_tool === 'string' ? raw.source_tool : undefined,
    path: typeof raw.path === 'string' ? raw.path : undefined,
    size: typeof raw.size === 'number' ? raw.size : undefined,
    mimeType: typeof raw.mimeType === 'string' ? raw.mimeType : typeof raw.mime_type === 'string' ? raw.mime_type : undefined,
    mime_type: typeof raw.mime_type === 'string' ? raw.mime_type : undefined,
    kind: typeof raw.kind === 'string' ? raw.kind : undefined,
    files: nestedFiles.length > 0 ? nestedFiles : undefined,
    previews: nestedPreviews.length > 0 ? nestedPreviews : undefined,
    qa_summary: raw.qa_summary && typeof raw.qa_summary === 'object' ? raw.qa_summary : undefined,
    engine: typeof raw.engine === 'string' ? raw.engine : undefined,
    office_manifest_id: typeof raw.office_manifest_id === 'string' ? raw.office_manifest_id : undefined,
    manifest_path: typeof raw.manifest_path === 'string' ? raw.manifest_path : undefined,
    manifest_url: typeof raw.manifest_url === 'string' ? raw.manifest_url : undefined,
    viewer_manifest_url: typeof raw.viewer_manifest_url === 'string' ? raw.viewer_manifest_url : undefined,
    sha256: typeof raw.sha256 === 'string' ? raw.sha256 : undefined,
    render_issues: Array.isArray(raw.render_issues) ? raw.render_issues.filter((item: unknown): item is string => typeof item === 'string') : undefined,
    available_actions: Array.isArray(raw.available_actions) ? raw.available_actions.filter((item: unknown): item is string => typeof item === 'string') : undefined,
    workbook: raw.workbook && typeof raw.workbook === 'object' ? raw.workbook : undefined,
    presentation: raw.presentation && typeof raw.presentation === 'object' ? raw.presentation : undefined,
  };
}

export function normalizeArtifactPayloads(value: unknown): ArtifactPayload[] {
  if (!Array.isArray(value)) return [];
  return value
    .map(normalizeArtifactPayload)
    .filter((item): item is ArtifactPayload => Boolean(item));
}

export function imageAttachmentFromBlock(block: { base64?: string; image?: ImageAttachment; url?: string; title?: string; mimeType?: string }): ImageAttachment | null {
  return normalizeImageAttachment(block.image || {
    base64: block.base64,
    url: block.url,
    title: block.title,
    mimeType: block.mimeType,
  });
}

export function imageAttachmentSrc(image: ImageAttachment): string {
  if (image.url) {
    if (image.url.startsWith('/')) return `${API_BASE}${image.url}`;
    return image.url;
  }
  if (image.base64) {
    if (image.base64.startsWith('data:')) return image.base64;
    return `data:${image.mimeType || image.mime_type || 'image/png'};base64,${image.base64}`;
  }
  return '';
}

export function imageAttachmentLabel(image: ImageAttachment, fallback: string): string {
  return image.title || image.caption || fallback;
}
