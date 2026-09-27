-- Runs once on first Postgres start (mounted into /docker-entrypoint-initdb.d).
-- bge-small-en-v1.5 emits 384-dim vectors, so the column is vector(384).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS recipes (
    id          BIGINT PRIMARY KEY,
    name        TEXT NOT NULL,
    minutes     INT,
    tags        TEXT,
    ingredients TEXT,
    steps       TEXT,
    n_steps     INT,
    embedding   vector(384)
);

-- No ivfflat index here on purpose. ivfflat trains its centroids from the rows
-- present when the index is built; built on an empty table the centroids are
-- untrained and a default-probes query can return zero rows. The index is
-- created at the end of ingestion instead (see app/ingest.py), with data loaded.
