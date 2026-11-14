CREATE TABLE IF NOT EXISTS sources(server_id TEXT PRIMARY KEY, identity TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gateway_sessions(
    source TEXT NOT NULL REFERENCES sources(server_id),
    session TEXT NOT NULL, heartbeat TEXT NOT NULL,
    PRIMARY KEY(source,session)
);
CREATE TABLE IF NOT EXISTS tools(
    server_id TEXT NOT NULL, tool_name TEXT NOT NULL, sha256 TEXT NOT NULL,
    definition TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL,
    observed_at TEXT NOT NULL, present INTEGER NOT NULL,
    PRIMARY KEY(server_id, tool_name)
);
CREATE TABLE IF NOT EXISTS history(
    server_id TEXT NOT NULL, tool_name TEXT NOT NULL, sha256 TEXT NOT NULL,
    definition TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL,
    observed_at TEXT NOT NULL, PRIMARY KEY(server_id, tool_name, revision)
);
CREATE TABLE IF NOT EXISTS baselines(
    server_id TEXT NOT NULL, tool_name TEXT NOT NULL, definition TEXT NOT NULL,
    PRIMARY KEY(server_id, tool_name)
);
CREATE TABLE IF NOT EXISTS quarantines(
    server_id TEXT NOT NULL, tool_name TEXT NOT NULL, sha256 TEXT NOT NULL,
    PRIMARY KEY(server_id, tool_name, sha256)
);
CREATE TABLE IF NOT EXISTS tool_blocks(
    server_id TEXT NOT NULL, tool_name TEXT NOT NULL,
    PRIMARY KEY(server_id, tool_name)
);
CREATE TABLE IF NOT EXISTS shared_tool_blocks(
    server_id TEXT NOT NULL, tool_name TEXT NOT NULL,
    PRIMARY KEY(server_id, tool_name)
);
CREATE TABLE IF NOT EXISTS sentinel_stops(server_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS sentinel_calls(
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, session TEXT NOT NULL,
    tool TEXT NOT NULL, sha256 TEXT, revision INTEGER, started_at TEXT NOT NULL,
    ended_at TEXT, state TEXT NOT NULL, reason TEXT
);
CREATE INDEX IF NOT EXISTS sentinel_calls_tool ON sentinel_calls(source,tool,id);
CREATE INDEX IF NOT EXISTS sentinel_calls_time ON sentinel_calls(started_at);
CREATE VIEW IF NOT EXISTS gateway_routes AS
    SELECT server_id AS route, substr(server_id, 9 + instr(substr(server_id, 9), ':')) AS server_id
    FROM sources
    WHERE substr(server_id, 1, 8) = 'gateway:' AND instr(substr(server_id, 9), ':') > 0;
CREATE VIEW IF NOT EXISTS blocked_tool_routes AS
    SELECT server_id, tool_name FROM tool_blocks
    UNION ALL
    SELECT r.route, b.tool_name FROM gateway_routes r
        JOIN shared_tool_blocks b ON b.server_id = r.server_id;
CREATE TABLE IF NOT EXISTS model_decisions(
    server_id TEXT NOT NULL, tool_name TEXT NOT NULL, sha256 TEXT NOT NULL,
    evidence TEXT NOT NULL, PRIMARY KEY(server_id, tool_name, sha256)
);
CREATE TABLE IF NOT EXISTS decision_model(
    id INTEGER PRIMARY KEY CHECK(id=1), artifact TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_overrides(
    server_id TEXT NOT NULL, tool_name TEXT NOT NULL, sha256 TEXT NOT NULL,
    decision TEXT NOT NULL, PRIMARY KEY(server_id, tool_name, sha256)
);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
    tool TEXT, timestamp TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_kind_id ON events(kind, id);
CREATE INDEX IF NOT EXISTS events_source_kind_id ON events(source, kind, id);
CREATE INDEX IF NOT EXISTS events_tool_id ON events(source, tool, id);
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY CHECK (id=1), cursor INTEGER NOT NULL);
INSERT OR IGNORE INTO alerts VALUES (1, 0);
CREATE TABLE IF NOT EXISTS helper_inventory(
    scope TEXT PRIMARY KEY, entries TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS helper_changes(
    id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, change TEXT NOT NULL,
    helper TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS monitoring_settings(
    id INTEGER PRIMARY KEY CHECK(id=1), settings TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approval_policy(
    id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS standalone_servers(
    name TEXT PRIMARY KEY, profile TEXT NOT NULL, state TEXT NOT NULL
);
