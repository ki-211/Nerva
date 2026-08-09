import type { AdminUser, ChatMessage, ChatSession, ChatStreamHandlers, ChangeSet, Document, DocumentVersion, KnowledgeEvent, KnowledgeOwnership, Memory, MemoryCreate, MemoryUpdate, SearchResponse, SourceProcessing, User } from './types';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const REQUEST_TIMEOUT_MS = 10_000;

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
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: init?.signal ?? controller.signal,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('API 服务连接超时，请确认后端已启动', 0, 'API_TIMEOUT', undefined, true);
    }
    throw new ApiError('无法连接 API 服务，请确认后端已启动', 0, 'API_UNAVAILABLE', undefined, true);
  } finally {
    window.clearTimeout(timeout);
  }
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

async function streamChat(
  path: string, body: object | undefined, handlers: ChatStreamHandlers, signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST', credentials: 'include', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new ApiError('浏览器不支持流式响应', 0, 'CHAT_STREAM_UNAVAILABLE');
  if (!response.headers.get('Content-Type')?.includes('text/event-stream')) {
    throw new ApiError('对话服务返回了非流式响应', 0, 'CHAT_STREAM_INVALID_CONTENT_TYPE', undefined, true);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let terminalEventReceived = false;

  const handleBlock = (block: string) => {
    let event = '';
    let data = '';
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      if (line.startsWith('data:')) data += line.slice(5).trim();
    }
    if (!event || !data) return;
    let payload: any;
    try {
      payload = JSON.parse(data);
    } catch {
      throw new ApiError('对话流数据格式无效', 0, 'CHAT_STREAM_INVALID_EVENT', undefined, true);
    }
    if (event === 'start') handlers.onStart(payload);
    if (event === 'delta') handlers.onDelta(payload.text || '');
    if (event === 'memory_candidates') handlers.onMemoryCandidates(payload.memories || []);
    if (event === 'done') {
      terminalEventReceived = true;
      handlers.onDone(payload.message);
    }
    if (event === 'error') {
      terminalEventReceived = true;
      handlers.onError(payload);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || '';
    blocks.forEach(handleBlock);
    if (done) break;
  }
  if (buffer.trim()) handleBlock(buffer);
  if (!terminalEventReceived) {
    throw new ApiError('对话连接提前中断，请重试', 0, 'CHAT_STREAM_INTERRUPTED', undefined, true);
  }
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
  adminLogin: (username: string, password: string) => request<User>('/v1/auth/admin-login', {
    method: 'POST', body: JSON.stringify({ username, password }),
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
  search: (query: string, limit = 8, includePublic = true) => {
    const params = new URLSearchParams({ q: query, limit: String(limit), include_public: String(includePublic) });
    return request<SearchResponse>(`/v1/search?${params}`);
  },
  publicDocuments: () => request<Document[]>('/v1/public-documents'),
  publicDocument: (id: string) => request<Document>(`/v1/public-documents/${id}`),
  adminUsers: () => request<AdminUser[]>('/v1/admin/users'),
  knowledgeOwnership: () => request<KnowledgeOwnership[]>('/v1/admin/knowledge-ownership'),
  adminDocument: (id: string) => request<Document>(`/v1/admin/documents/${id}`),
  createPublicDocument: (title: string, markdown: string) => request<Document>('/v1/admin/public-documents', {
    method: 'POST', body: JSON.stringify({ title, markdown }),
  }),
  updatePublicDocument: (id: string, payload: { title: string; markdown: string; base_version: number; reason?: string }) =>
    request<Document>(`/v1/admin/public-documents/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  unpublishPublicDocument: (id: string) => request<Document>(`/v1/admin/public-documents/${id}`, { method: 'DELETE' }),
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
  chatSessions: () => request<ChatSession[]>('/v1/chat/sessions'),
  createChatSession: (title = '新对话') => request<ChatSession>('/v1/chat/sessions', {
    method: 'POST', body: JSON.stringify({ title }),
  }),
  updateChatSession: (id: string, title: string) => request<ChatSession>(`/v1/chat/sessions/${id}`, {
    method: 'PATCH', body: JSON.stringify({ title }),
  }),
  deleteChatSession: (id: string) => request<void>(`/v1/chat/sessions/${id}`, { method: 'DELETE' }),
  chatMessages: (id: string) => request<ChatMessage[]>(`/v1/chat/sessions/${id}/messages`),
  sendChatMessage: (
    id: string, content: string, handlers: ChatStreamHandlers, signal?: AbortSignal, includePublic = true,
  ) => streamChat(`/v1/chat/sessions/${id}/messages`, { content, include_public: includePublic }, handlers, signal),
  retryChatMessage: (
    messageId: string, handlers: ChatStreamHandlers, signal?: AbortSignal,
  ) => streamChat(`/v1/chat/messages/${messageId}/retry`, undefined, handlers, signal),
};
