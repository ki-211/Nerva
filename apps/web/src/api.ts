import type { ChangeSet, Document, KnowledgeEvent } from './types';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) throw new Error((await response.json()).detail || '请求失败');
  return response.json();
}

export const api = {
  createIngestion: (content: string, title?: string) => request<ChangeSet>('/v1/ingestions', {
    method: 'POST', body: JSON.stringify({ kind: 'text', content, title: title || null }),
  }),
  applyChangeSet: (id: string, accepted_item_ids: string[]) => request<ChangeSet>(`/v1/change-sets/${id}/apply`, {
    method: 'POST', body: JSON.stringify({ accepted_item_ids }),
  }),
  documents: () => request<Document[]>('/v1/documents'),
  events: () => request<KnowledgeEvent[]>('/v1/knowledge-events'),
};

