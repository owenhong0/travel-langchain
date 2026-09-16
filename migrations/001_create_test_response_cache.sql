-- Cache table for test-mode response replay.
-- Stores outputs from expensive external calls (LLM / Tavily / Duffel),
-- keyed by a hash of call type + canonicalized args + schema version.
-- Only ever read/written when config.configurable.test_mode is true.

CREATE TABLE IF NOT EXISTS test_response_cache (
    id SERIAL PRIMARY KEY,
    cache_key CHAR(64) NOT NULL UNIQUE,     -- sha256 hex digest
    call_type TEXT NOT NULL,                 -- 'llm' | 'tavily_search' | 'tavily_extract' | 'duffel'
    schema_version TEXT NOT NULL,            -- bump to invalidate stale entries after prompt/logic changes
    input_snapshot JSONB NOT NULL,           -- human-readable copy of the args, for debugging collisions
    output_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_test_cache_lookup ON test_response_cache (cache_key);
CREATE INDEX IF NOT EXISTS idx_test_cache_call_type ON test_response_cache (call_type);