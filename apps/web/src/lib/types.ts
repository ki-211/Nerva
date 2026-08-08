export type ChangeItem = {
  id: string;
  operation: 'CREATE_DOCUMENT' | 'ADD_BLOCK' | 'UPDATE_BLOCK' | 'MOVE_BLOCK' | 'ADD_RELATION' | 'MARK_DUPLICATE' | 'REPORT_CONFLICT' | 'UPDATE_DOCUMENT';
  target_document_id: string | null;
  target_title: string;
  before_title: string | null;
  reason: string;
  before: string | null;
  after: string;
  evidence: string;
  confidence: number;
  accepted: boolean | null;
};

export type ChangeSet = {
  id: string;
  source_id: string | null;
  origin: 'ai_ingestion' | 'manual_edit';
  status: 'proposed' | 'applied' | 'partially_applied' | 'rejected' | 'superseded';
  summary: string;
  supersedes_change_set_id: string | null;
  analysis_instruction: string | null;
  created_at: string;
  source: { title: string | null; content: string } | null;
  items: ChangeItem[];
};

export type Document = {
  id: string; title: string; markdown: string; version: number;
  created_at: string; updated_at: string;
};
export type DocumentVersion = {
  version: number; title: string; markdown: string; reason: string; created_at: string;
};
export type KnowledgeEvent = {
  id: string; created_at: string; title: string; summary: string;
  affected_documents: string[]; accepted_count: number; rejected_count: number;
  change_set_id: string; origin: 'ai_ingestion' | 'manual_edit';
};

export type User = { id: string; email: string; display_name: string };

export type MemoryKind = 'style' | 'topic_split' | 'domain' | 'naming' | 'merge_preference';
export type MemoryScope = 'global' | 'document' | 'topic';
export type MemoryStatus = 'active' | 'candidate' | 'suppressed';
export type MemoryOrigin = 'user_explicit' | 'ai_inferred' | 'ai_observed';

export type Memory = {
  id: string;
  kind: MemoryKind;
  content: string;
  scope: MemoryScope;
  scope_ref: string | null;
  status: MemoryStatus;
  confidence: number;
  origin: MemoryOrigin;
  use_count: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
};

export type MemoryCreate = {
  kind: MemoryKind;
  content: string;
  scope?: MemoryScope;
  scope_ref?: string | null;
  status?: MemoryStatus;
  confidence?: number;
  origin?: MemoryOrigin;
};

export type MemoryUpdate = {
  content?: string;
  status?: MemoryStatus;
  confidence?: number;
};

export type SourceProcessing = {
  source_id: string;
  status: 'received' | 'processing' | 'proposed' | 'failed';
  stage: 'queued' | 'ocr' | 'extracting' | 'coverage_repair' | 'retrieving' | 'planning' | 'complete' | 'failed';
  processed_inputs: number;
  total_inputs: number;
  covered_inputs: number;
  input_coverage: { input_index: number; knowledge_unit_count: number }[];
  extraction_attempts: number;
  change_set_id: string | null;
  error: {
    code: string;
    message: string;
    retryable: boolean;
    requires_reupload: boolean;
  } | null;
};
