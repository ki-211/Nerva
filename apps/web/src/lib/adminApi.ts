import { request } from './api';
import type { AdminUser, Document, KnowledgeOwnership, User } from './types';

export const adminApi = {
  login: (username: string, password: string) => request<User>('/v1/auth/admin-login', {
    method: 'POST', body: JSON.stringify({ username, password }),
  }, { loginSubmission: true }),
  users: () => request<AdminUser[]>('/v1/admin/users'),
  knowledgeOwnership: () => request<KnowledgeOwnership[]>('/v1/admin/knowledge-ownership'),
  createPublicDocument: (title: string, markdown: string) => request<Document>('/v1/admin/public-documents', {
    method: 'POST', body: JSON.stringify({ title, markdown }),
  }),
  updatePublicDocument: (id: string, payload: { title: string; markdown: string; base_version: number; reason?: string }) =>
    request<Document>(`/v1/admin/public-documents/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  unpublishPublicDocument: (id: string) => request<Document>(`/v1/admin/public-documents/${id}`, { method: 'DELETE' }),
};
