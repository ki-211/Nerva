import type { ChangeSet, Document, KnowledgeEvent, User } from './types';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(body.detail || '请求失败', response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
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
  applyChangeSet: (id: string, accepted_item_ids: string[]) => request<ChangeSet>(`/v1/change-sets/${id}/apply`, {
    method: 'POST', body: JSON.stringify({ accepted_item_ids }),
  }),
  documents: () => request<Document[]>('/v1/documents'),
  events: () => request<KnowledgeEvent[]>('/v1/knowledge-events'),
};
