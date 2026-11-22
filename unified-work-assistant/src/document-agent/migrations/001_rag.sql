CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE IF NOT EXISTS rag_documents (
 namespace text NOT NULL, document_id text NOT NULL, collection_id text NOT NULL,
 active_version text, active boolean NOT NULL DEFAULT false, metadata jsonb NOT NULL,
 indexed_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(namespace, document_id)
);
CREATE TABLE IF NOT EXISTS rag_chunks (
 namespace text NOT NULL, document_id text NOT NULL, version text NOT NULL,
 chunk_id text NOT NULL, profile text NOT NULL, text text NOT NULL,
 metadata jsonb NOT NULL, embedding vector(384) NOT NULL,
 PRIMARY KEY(namespace, document_id, version, chunk_id),
 FOREIGN KEY(namespace, document_id) REFERENCES rag_documents ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS rag_scope ON rag_documents(namespace, collection_id) WHERE active;
CREATE INDEX IF NOT EXISTS rag_text ON rag_chunks USING gin(text gin_trgm_ops);
CREATE TABLE IF NOT EXISTS rag_sync_state (
 namespace text NOT NULL, collection_id text NOT NULL, result jsonb NOT NULL,
 synced_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(namespace,collection_id)
);
CREATE TABLE IF NOT EXISTS rag_workhub_projects (
 namespace text NOT NULL, collection_id text NOT NULL, name text NOT NULL,
 PRIMARY KEY(namespace,collection_id)
);
