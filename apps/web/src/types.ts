export type ChangeItem = {
  id: string;
  operation: 'CREATE_DOCUMENT' | 'ADD_BLOCK' | 'UPDATE_BLOCK' | 'MOVE_BLOCK' | 'ADD_RELATION' | 'MARK_DUPLICATE' | 'REPORT_CONFLICT';
  target_document_id: string | null;
  target_title: string;
  reason: string;
  before: string | null;
  after: string;
  evidence: string;
  confidence: number;
};

export type ChangeSet = {
  id: string;
  source_id: string;
  status: 'proposed' | 'applied' | 'partially_applied' | 'rejected';
  summary: string;
  created_at: string;
  items: ChangeItem[];
};

export type Document = { id: string; title: string; markdown: string; version: number; updated_at: string };
export type KnowledgeEvent = {
  id: string; created_at: string; title: string; summary: string;
  affected_documents: string[]; accepted_count: number; rejected_count: number;
};

