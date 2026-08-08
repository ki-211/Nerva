import type { ChangeSet, Document, DocumentVersion, KnowledgeEvent, Memory, MemoryCreate, MemoryUpdate, SourceProcessing, User } from './types';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public sourceId?: string,
    public retryable = false,
    public currentVersion?: number,
    public requiresReupload = false,
  ) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    throw await responseError(response);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function responseError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  if (detail && typeof detail === 'object') {
    return new ApiError(
      detail.message || '请求失败', response.status, detail.code,
      detail.source_id, Boolean(detail.retryable), detail.current_version,
      Boolean(detail.requires_reupload),
    );
  }
  return new ApiError(typeof detail === 'string' ? detail : '请求失败', response.status);
}

function responseFilename(response: Response, fallback: string): string {
  const disposition = response.headers.get('Content-Disposition') || '';
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  if (encoded) {
    try { return decodeURIComponent(encoded); } catch { /* Use the fallback below. */ }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)?.[1];
  return plain || fallback;
}

async function download(path: string, fallbackFilename: string): Promise<void> {
  const response = await fetch(`${BASE}${path}`, { credentials: 'include' });
  if (!response.ok) throw await responseError(response);
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = responseFilename(response, fallbackFilename);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

function uploadImages(
  files: File[], title: string, note: string,
  onProgress: (percentage: number) => void,
): Promise<SourceProcessing> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    if (title.trim()) form.append('title', title.trim());
    if (note.trim()) form.append('note', note.trim());
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/v1/image-ingestions`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      const body = (() => { try { return JSON.parse(xhr.responseText || '{}'); } catch { return {}; } })();
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as SourceProcessing);
        return;
      }
      const detail = body.detail;
      reject(new ApiError(
        typeof detail === 'object' ? detail.message || '图片上传失败' : detail || '图片上传失败',
        xhr.status, detail?.code, detail?.source_id, Boolean(detail?.retryable),
        undefined, Boolean(detail?.requires_reupload),
      ));
    };
    xhr.onerror = () => reject(new ApiError('无法连接图片上传服务', 0));
    xhr.send(form);
  });
}

export const api = {
  sendVerificationCode: (email: string) => request<void>('/v1/auth/verification-codes', {
    method: 'POST', body: JSON.stringify({ email }),
  }),
  codeLogin: (email: string, verification_code: string) => request<User>('/v1/auth/code-login', {
    method: 'POST', body: JSON.stringify({ email, verification_code }),
  }),
  logout: () => request<void>('/v1/auth/logout', { method: 'POST' }),
  me: () => request<User>('/v1/auth/me'),
  createIngestion: (content: string, title?: string) => request<ChangeSet>('/v1/ingestions', {
    method: 'POST', body: JSON.stringify({ kind: 'text', content, title: title || null }),
  }),
  retrySource: (sourceId: string) => request<ChangeSet | SourceProcessing>(`/v1/sources/${sourceId}/retry`, {
    method: 'POST',
  }),
  reprocessSource: (sourceId: string, instruction?: string) => request<SourceProcessing>(`/v1/sources/${sourceId}/reprocess`, {
    method: 'POST', body: JSON.stringify({ instruction: instruction?.trim() || null }),
  }),
  uploadImages,
  sourceProcessing: (sourceId: string) => request<SourceProcessing>(`/v1/sources/${sourceId}/processing`),
  applyChangeSet: (id: string, accepted_item_ids: string[]) => request<ChangeSet>(`/v1/change-sets/${id}/apply`, {
    method: 'POST', body: JSON.stringify({ accepted_item_ids }),
  }),
  changeSet: (id: string) => request<ChangeSet>(`/v1/change-sets/${id}`),
  documents: () => request<Document[]>('/v1/documents'),
  document: (id: string) => request<Document>(`/v1/documents/${id}`),
  documentVersions: (id: string) => request<DocumentVersion[]>(`/v1/documents/${id}/versions`),
  updateDocument: (id: string, payload: { title: string; markdown: string; base_version: number; reason?: string }) =>
    request<Document>(`/v1/documents/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  exportMarkdown: (scope: 'library' | 'document', documentId?: string, version?: number) => {
    const query = new URLSearchParams({ scope });
    if (documentId) query.set('document_id', documentId);
    if (version != null) query.set('version', String(version));
    return download(`/v1/exports/markdown?${query}`, scope === 'library' ? 'nerva-library.zip' : 'knowledge.md');
  },
  exportKnowledgePackage: (scope: 'library' | 'document', documentId?: string) => {
    const query = new URLSearchParams({ scope });
    if (documentId) query.set('document_id', documentId);
    return download(`/v1/exports/knowledge-package?${query}`, 'nerva-knowledge-package.zip');
  },
  events: () => request<KnowledgeEvent[]>('/v1/knowledge-events'),
  memories: (status?: 'active' | 'candidate' | 'suppressed') => {
    const query = status ? `?status=${status}` : '';
    return request<Memory[]>(`/v1/memories${query}`);
  },
  createMemory: (payload: MemoryCreate) => request<Memory>('/v1/memories', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  updateMemory: (id: string, payload: MemoryUpdate) => request<Memory>(`/v1/memories/${id}`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  deleteMemory: (id: string) => request<void>(`/v1/memories/${id}`, { method: 'DELETE' }),
};
