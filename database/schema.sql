-- Nerva PostgreSQL schema v1
-- Run this file while connected to the `nerva` database.

BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(40) PRIMARY KEY,
    email VARCHAR(320) NOT NULL UNIQUE,
    display_name VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS email_verification_codes (
    id VARCHAR(40) PRIMARY KEY,
    email VARCHAR(320) NOT NULL,
    code_hash VARCHAR(64) NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    expires_at TIMESTAMPTZ NOT NULL,
    resend_after TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sources (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind VARCHAR(30) NOT NULL,
    title VARCHAR(160),
    content TEXT NOT NULL,
    processing_status VARCHAR(30) NOT NULL CHECK (
        processing_status IN ('received', 'processing', 'proposed', 'failed')
    ),
    ai_provider VARCHAR(40),
    ai_model VARCHAR(160),
    prompt_version VARCHAR(80),
    error_code VARCHAR(80),
    error_message TEXT,
    processing_stage VARCHAR(30) NOT NULL CHECK (
        processing_stage IN ('queued', 'ocr', 'extracting', 'coverage_repair', 'retrieving', 'planning', 'complete', 'failed')
    ),
    processing_started_at TIMESTAMPTZ,
    total_inputs INTEGER NOT NULL CHECK (total_inputs >= 0),
    processed_inputs INTEGER NOT NULL CHECK (
        processed_inputs >= 0 AND processed_inputs <= total_inputs
    ),
    covered_inputs INTEGER NOT NULL CHECK (
        covered_inputs >= 0 AND covered_inputs <= total_inputs
    ),
    extraction_attempts INTEGER NOT NULL CHECK (
        extraction_attempts >= 0 AND extraction_attempts <= 2
    ),
    pending_supersedes_change_set_id VARCHAR(40),
    pending_analysis_instruction TEXT,
    ocr_model VARCHAR(160),
    ocr_prompt_version VARCHAR(80),
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_units (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id VARCHAR(40) NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    input_index INTEGER NOT NULL CHECK (input_index >= 0),
    type VARCHAR(40) NOT NULL,
    subject VARCHAR(160) NOT NULL,
    content TEXT NOT NULL,
    source_span TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(160) NOT NULL,
    markdown TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id VARCHAR(40) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    title VARCHAR(160) NOT NULL,
    markdown TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_document_version UNIQUE (document_id, version)
);

CREATE TABLE IF NOT EXISTS change_sets (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id VARCHAR(40) REFERENCES sources(id) ON DELETE RESTRICT,
    origin VARCHAR(30) NOT NULL CHECK (origin IN ('ai_ingestion', 'manual_edit')),
    status VARCHAR(30) NOT NULL CHECK (
        status IN ('proposed', 'applied', 'partially_applied', 'rejected', 'superseded')
    ),
    summary TEXT NOT NULL,
    supersedes_change_set_id VARCHAR(40) REFERENCES change_sets(id) ON DELETE SET NULL,
    analysis_instruction TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_sources_pending_supersedes') THEN
        ALTER TABLE sources ADD CONSTRAINT fk_sources_pending_supersedes
            FOREIGN KEY (pending_supersedes_change_set_id) REFERENCES change_sets(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS change_items (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    change_set_id VARCHAR(40) NOT NULL REFERENCES change_sets(id) ON DELETE CASCADE,
    operation VARCHAR(40) NOT NULL CHECK (
        operation IN (
            'CREATE_DOCUMENT', 'ADD_BLOCK', 'UPDATE_BLOCK', 'MOVE_BLOCK',
            'ADD_RELATION', 'MARK_DUPLICATE', 'REPORT_CONFLICT', 'UPDATE_DOCUMENT'
        )
    ),
    target_document_id VARCHAR(40) REFERENCES documents(id) ON DELETE SET NULL,
    target_title VARCHAR(160) NOT NULL,
    before_title VARCHAR(160),
    reason TEXT NOT NULL,
    before_text TEXT,
    after_text TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    accepted BOOLEAN
);

CREATE TABLE IF NOT EXISTS knowledge_events (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    change_set_id VARCHAR(40) NOT NULL REFERENCES change_sets(id) ON DELETE RESTRICT,
    title VARCHAR(160) NOT NULL,
    summary TEXT NOT NULL,
    affected_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
    accepted_count INTEGER NOT NULL CHECK (accepted_count >= 0),
    rejected_count INTEGER NOT NULL CHECK (rejected_count >= 0),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS user_memories (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind VARCHAR(30) NOT NULL CHECK (
        kind IN ('style', 'topic_split', 'domain', 'naming', 'merge_preference')
    ),
    content TEXT NOT NULL,
    scope VARCHAR(30) NOT NULL CHECK (scope IN ('global', 'document', 'topic')),
    scope_ref VARCHAR(160),
    status VARCHAR(20) NOT NULL CHECK (status IN ('active', 'candidate', 'suppressed')),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    origin VARCHAR(20) NOT NULL CHECK (
        origin IN ('user_explicit', 'ai_inferred', 'ai_observed')
    ),
    use_count INTEGER NOT NULL DEFAULT 0 CHECK (use_count >= 0),
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id VARCHAR(40) NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    status VARCHAR(20) NOT NULL CHECK (
        status IN ('generating', 'completed', 'failed', 'cancelled')
    ),
    content TEXT NOT NULL,
    model VARCHAR(160),
    grounding VARCHAR(30) CHECK (
        grounding IS NULL OR grounding IN (
            'knowledge', 'knowledge_plus_general', 'general', 'insufficient'
        )
    ),
    citations JSONB NOT NULL,
    error_code VARCHAR(80),
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_codes_email_created ON email_verification_codes (email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sources_user ON sources (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sources_user_status
    ON sources (user_id, processing_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sources_user_stage
    ON sources (user_id, processing_stage, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_units_source ON knowledge_units (source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_units_source_input
    ON knowledge_units (source_id, input_index);
CREATE INDEX IF NOT EXISTS idx_knowledge_units_user
    ON knowledge_units (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_user_updated ON documents (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_versions_document
    ON document_versions (document_id, version DESC);

CREATE INDEX IF NOT EXISTS idx_change_sets_source
    ON change_sets (source_id);

CREATE INDEX IF NOT EXISTS idx_change_sets_status_created
    ON change_sets (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_change_items_change_set
    ON change_items (change_set_id);

CREATE INDEX IF NOT EXISTS idx_change_items_target_document
    ON change_items (target_document_id)
    WHERE target_document_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_events_created_at
    ON knowledge_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_events_user_created
    ON knowledge_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_user_active
    ON user_memories (user_id, status, kind);

CREATE INDEX IF NOT EXISTS idx_memories_user_created
    ON user_memories (user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
    ON chat_sessions (user_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
    ON chat_messages (session_id, created_at);

COMMIT;
