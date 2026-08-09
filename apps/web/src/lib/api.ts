import type { AdminUser, ChatMessage, ChatSession, ChatStreamHandlers, ChangeSet, Document, DocumentVersion, KnowledgeEvent, KnowledgeOwnership, Memory, MemoryCreate, MemoryUpdate, SearchResponse, SourceProcessing, User } from './types';
import { clientLogger } from './clientLogger';
import {
  actionForError, ApiError, categoryForStatus, fallbackMessage, signalSessionExpired,
  signalOperationFailure,
} from './errors';

export { ApiError } from './errors';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const CLIENT_TYPE = import.meta.env.VITE_CLIENT_TYPE || 'web-development';
const CLIENT_VERSION = import.meta.env.VITE_APP_VERSION || '0.1.0';
const REQUEST_TIMEOUT_MS = 15_000;
const DOWNLOAD_TIMEOUT_MS = 120_000;
const UPLOAD_TIMEOUT_MS = 300_000;
const STREAM_CONNECT_TIMEOUT_MS = 30_000;

type ErrorPayload = {
  code?: string; message?: string; retryable?: boolean; request_id?: string;
  source_id?: string; current_version?: number; requires_reupload?: boolean;
};

function requestHeaders(headers?: HeadersInit): Headers {
  const result = new Headers(headers);
  result.set('X-Nerva-Client', CLIENT_TYPE);
  result.set('X-Nerva-Version', CLIENT_VERSION);
  return result;
}

function networkError(code: string, message: string, retryable = true): ApiError {
  return new ApiError(message, 0, code, undefined, retryable, undefined, false, undefined, 'network', 'retry');
}

function logApiFailure(operation: string, error: ApiError): void {
  clientLogger.warn('api_operation_failed', {
    operation, errorCode: error.code, requestId: error.requestId,
    status: error.status, category: error.category, action: error.action,
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  init?.signal?.addEventListener('abort', () => controller.abort(), { once: true });
  const headers = requestHeaders(init?.headers);
  headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: controller.signal,
      credentials: 'include',
      headers,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      const mapped = networkError('API_TIMEOUT', '服务响应超时，请检查网络后重试');
      logApiFailure(`${init?.method || 'GET'} ${path}`, mapped);
      if ((init?.method || 'GET').toUpperCase() !== 'GET') signalOperationFailure(mapped);
      throw mapped;
    }
    const mapped = networkError('API_UNAVAILABLE', '服务暂时不可用，请检查网络');
    logApiFailure(`${init?.method || 'GET'} ${path}`, mapped);
    if ((init?.method || 'GET').toUpperCase() !== 'GET') signalOperationFailure(mapped);
    throw mapped;
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    const error = await responseError(response);
    logApiFailure(`${init?.method || 'GET'} ${path}`, error);
    if (error.status === 401 && !path.includes('/auth/code-login') && !path.includes('/auth/admin-login')) {
      signalSessionExpired();
    }
    const isLoginSubmission = path.includes('/auth/code-login') || path.includes('/auth/admin-login');
    if ((init?.method || 'GET').toUpperCase() !== 'GET' && ![409, 422].includes(error.status)
      && !(isLoginSubmission && [400, 401, 403, 429].includes(error.status))) {
      signalOperationFailure(error);
    }
    throw error;
  }
  if (response.status === 204) return undefined as T;
  try {
    return await response.json() as T;
  } catch (cause) {
    const requestId = response.headers.get('X-Request-ID') || undefined;
    const error = new ApiError(
      '服务返回了无效响应，请稍后重试', response.status, 'API_INVALID_RESPONSE',
      undefined, true, undefined, false, requestId, 'server', 'retry',
    );
    clientLogger.error('api_invalid_success_response', cause, {
      operation: `${init?.method || 'GET'} ${path}`, errorCode: error.code, requestId,
    });
    throw error;
  }
}

async function responseError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get('X-Request-ID') || undefined;
  const body = await response.json().catch(() => null) as { error?: ErrorPayload; detail?: ErrorPayload | string } | null;
  const legacy = body?.detail;
  const payload: ErrorPayload = body?.error || (legacy && typeof legacy === 'object' ? legacy : {});
  const retryable = Boolean(payload.retryable || response.status >= 500);
  const message = payload.message || (typeof legacy === 'string' ? legacy : fallbackMessage(response.status));
  const requiresReupload = Boolean(payload.requires_reupload);
  return new ApiError(
    message, response.status, payload.code || `HTTP_${response.status}`,
    payload.source_id, retryable, payload.current_version, requiresReupload,
    payload.request_id || requestId, categoryForStatus(response.status),
    actionForError(response.status, retryable, requiresReupload),
  );
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
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      credentials: 'include', signal: controller.signal, headers: requestHeaders(),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      const mapped = networkError('DOWNLOAD_TIMEOUT', '下载超时，请检查网络后重试');
      logApiFailure(`DOWNLOAD ${path}`, mapped);
      throw mapped;
    }
    const mapped = networkError('DOWNLOAD_UNAVAILABLE', '下载服务暂时不可用，请检查网络');
    logApiFailure(`DOWNLOAD ${path}`, mapped);
    throw mapped;
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    const error = await responseError(response);
    logApiFailure(`DOWNLOAD ${path}`, error);
    if (error.status === 401) signalSessionExpired();
    signalOperationFailure(error);
    throw error;
  }
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
  const controller = new AbortController();
  signal?.addEventListener('abort', () => controller.abort(), { once: true });
  const connectTimeout = window.setTimeout(() => controller.abort(), STREAM_CONNECT_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: 'POST', credentials: 'include', signal: controller.signal,
      headers: requestHeaders({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      const mapped = networkError('CHAT_STREAM_CONNECT_TIMEOUT', '连接对话服务超时，请重试');
      logApiFailure(`SSE ${path}`, mapped);
      throw mapped;
    }
    const mapped = networkError('CHAT_STREAM_UNAVAILABLE', '对话服务暂时不可用，请检查网络');
    logApiFailure(`SSE ${path}`, mapped);
    throw mapped;
  } finally {
    window.clearTimeout(connectTimeout);
  }
  if (!response.ok) {
    const error = await responseError(response);
    logApiFailure(`SSE ${path}`, error);
    if (error.status === 401) signalSessionExpired();
    throw error;
  }
  if (!response.body) throw networkError('CHAT_STREAM_UNAVAILABLE', '当前客户端无法接收流式响应');
  if (!response.headers.get('Content-Type')?.includes('text/event-stream')) {
    throw networkError('CHAT_STREAM_INVALID_CONTENT_TYPE', '对话服务返回了无效响应');
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
      throw networkError('CHAT_STREAM_INVALID_EVENT', '对话流数据格式无效');
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
      const streamError = new ApiError(
        payload.message || '对话生成失败', 0, payload.code || 'CHAT_STREAM_ERROR',
        undefined, Boolean(payload.retryable), undefined, false, payload.request_id,
        'server', payload.retryable ? 'retry' : 'none',
      );
      logApiFailure(`SSE ${path}`, streamError);
      handlers.onError({
        ...payload,
        request_id: streamError.requestId,
        message: streamError.message,
      });
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
    const error = networkError('CHAT_STREAM_INTERRUPTED', '对话连接提前中断，请重试');
    logApiFailure(`SSE ${path}`, error);
    throw error;
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
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    xhr.setRequestHeader('X-Nerva-Client', CLIENT_TYPE);
    xhr.setRequestHeader('X-Nerva-Version', CLIENT_VERSION);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      const body = (() => { try { return JSON.parse(xhr.responseText || '{}'); } catch { return {}; } })();
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as SourceProcessing);
        return;
      }
      const detail: ErrorPayload | string = body.error || body.detail || {};
      const payload: ErrorPayload = typeof detail === 'object' ? detail : {};
      const retryable = Boolean(payload.retryable || xhr.status >= 500);
      const requiresReupload = Boolean(payload.requires_reupload);
      const error = new ApiError(
        payload.message || (typeof detail === 'string' ? detail : fallbackMessage(xhr.status)),
        xhr.status, payload.code || `HTTP_${xhr.status}`,
        payload.source_id, retryable, payload.current_version, requiresReupload,
        payload.request_id || xhr.getResponseHeader('X-Request-ID') || undefined,
        categoryForStatus(xhr.status), actionForError(xhr.status, retryable, requiresReupload),
      );
      if (error.status === 401) signalSessionExpired();
      logApiFailure('UPLOAD /v1/image-ingestions', error);
      signalOperationFailure(error);
      reject(error);
    };
    xhr.onerror = () => {
      const error = networkError('UPLOAD_UNAVAILABLE', '图片上传服务暂时不可用，请检查网络');
      logApiFailure('UPLOAD /v1/image-ingestions', error);
      signalOperationFailure(error);
      reject(error);
    };
    xhr.ontimeout = () => {
      const error = networkError('UPLOAD_TIMEOUT', '图片上传超时，请检查网络后重试');
      logApiFailure('UPLOAD /v1/image-ingestions', error);
      signalOperationFailure(error);
      reject(error);
    };
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
