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
    markdown TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_document_version UNIQUE (document_id, version)
);

CREATE TABLE IF NOT EXISTS change_sets (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id VARCHAR(40) NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    status VARCHAR(30) NOT NULL CHECK (
        status IN ('proposed', 'applied', 'partially_applied', 'rejected')
    ),
    summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS change_items (
    id VARCHAR(40) PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    change_set_id VARCHAR(40) NOT NULL REFERENCES change_sets(id) ON DELETE CASCADE,
    operation VARCHAR(40) NOT NULL CHECK (
        operation IN (
            'CREATE_DOCUMENT', 'ADD_BLOCK', 'UPDATE_BLOCK', 'MOVE_BLOCK',
            'ADD_RELATION', 'MARK_DUPLICATE', 'REPORT_CONFLICT'
        )
    ),
    target_document_id VARCHAR(40) REFERENCES documents(id) ON DELETE SET NULL,
    target_title VARCHAR(160) NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_codes_email_created ON email_verification_codes (email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sources_user ON sources (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_user_updated ON documents (user_id, updated_at DESC);

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

COMMIT;
