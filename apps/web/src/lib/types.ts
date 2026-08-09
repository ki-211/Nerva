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
  created_at: string; updated_at: string; visibility: 'private' | 'public';
  index_status: 'pending' | 'ready' | 'failed';
};
export type DocumentVersion = {
  version: number; title: string; markdown: string; reason: string; created_at: string;
};

export type RetrievalMode = 'hybrid' | 'keyword' | 'empty';
export type SearchItem = {
  document_id: string;
  title: string;
  excerpt: string;
  document_version: number;
  chunk_id: string;
  matching_mode: RetrievalMode;
  score: number;
  visibility: 'private' | 'public';
};
export type SearchResponse = {
  items: SearchItem[];
  retrieval_mode: RetrievalMode;
  fallback_reason: string | null;
};
export type KnowledgeEvent = {
  id: string; created_at: string; title: string; summary: string;
  affected_documents: string[]; accepted_count: number; rejected_count: number;
  change_set_id: string; origin: 'ai_ingestion' | 'manual_edit';
};

export type User = { id: string; email: string; display_name: string; role: 'user' | 'admin' };

export type AdminUser = User & {
  username: string | null;
  status: 'active' | 'disabled';
  document_count: number;
  public_document_count: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeOwnership = {
  id: string;
  user_id: string;
  owner_email: string;
  owner_display_name: string;
  title: string;
  version: number;
  visibility: 'private' | 'public';
  index_status: 'pending' | 'ready' | 'failed';
  created_at: string;
  updated_at: string;
};

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
};

export type MemoryUpdate = {
  content?: string;
  status?: MemoryStatus;
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

export type ChatGrounding = 'knowledge' | 'knowledge_plus_general' | 'general' | 'insufficient';
export type ChatMessageStatus = 'generating' | 'completed' | 'failed' | 'cancelled';

export type ChatSession = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatCitation = {
  ref: string;
  document_id: string;
  title: string;
  excerpt: string;
  visibility: 'private' | 'public';
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  status: ChatMessageStatus;
  content: string;
  model: string | null;
  grounding: ChatGrounding | null;
  citations: ChatCitation[];
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
  include_public: boolean;
  memory_candidates?: Memory[];
};

export type ChatStreamHandlers = {
  onStart: (payload: { session_id: string; user_message_id: string; assistant_message_id: string }) => void;
  onDelta: (text: string) => void;
  onMemoryCandidates: (memories: Memory[]) => void;
  onDone: (message: ChatMessage) => void;
  onError: (error: ApiStreamError) => void;
};

export type ApiStreamError = {
  code: string;
  message: string;
  retryable: boolean;
  request_id?: string;
};

export type ResearchMode = 'smart' | 'web' | 'ai';
export type ResearchBasis = 'web' | 'ai';

export type ResearchSession = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ResearchCitation = {
  ordinal: number;
  title: string;
  url: string;
  domain: string;
  accessed_at: string;
};

export type ResearchMessage = {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  status: ChatMessageStatus;
  content: string;
  requested_mode: ResearchMode | null;
  basis: ResearchBasis | null;
  model: string | null;
  citations: ResearchCitation[];
  error_code: string | null;
  ingestion_source_id: string | null;
  created_at: string;
  completed_at: string | null;
};

export type ResearchStreamHandlers = {
  onStart: (payload: {
    session_id: string;
    user_message_id: string;
    assistant_message_id: string;
    requested_mode: ResearchMode;
  }) => void;
  onDelta: (text: string) => void;
  onSources: (citations: ResearchCitation[], basis: ResearchBasis) => void;
  onDone: (message: ResearchMessage) => void;
  onError: (error: ApiStreamError) => void;
};
