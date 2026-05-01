-- FTS5 Sample for Tape Entries
-- See: https://www.sqlite.org/fts5.html

-- ========================================
-- 1. Create FTS5 virtual table
-- ========================================
-- FTS5 creates an inverted index for full-text search.
-- 'content' = the source table to avoid duplicating data.
-- 'content_rowid' = the primary key of the source table.

CREATE VIRTUAL TABLE tape_entries_fts USING fts5(
    tape_id,          -- Foreign key (needed for per-tape filtering)
    kind,             -- Entry kind
    payload,          -- JSON payload as text
    meta,             -- JSON meta as text
    date,             -- ISO timestamp
    content='tape_entries',
    content_rowid='id'
);

-- ========================================
-- 2. Auto-sync triggers (recommended)
-- ========================================
-- FTS5 does NOT auto-update when source table changes.
-- These triggers keep the index in sync.

CREATE TRIGGER tape_entries_ai AFTER INSERT ON tape_entries BEGIN
    INSERT INTO tape_entries_fts(rowid, tape_id, kind, payload, meta, date)
    VALUES (new.id, new.tape_id, new.kind, new.payload, new.meta, new.date);
END;

CREATE TRIGGER tape_entries_ad AFTER DELETE ON tape_entries BEGIN
    INSERT INTO tape_entries_fts(tape_entries_fts, rowid, tape_id, kind, payload, meta, date)
    VALUES ('delete', old.id, old.tape_id, old.kind, old.payload, old.meta, old.date);
END;

CREATE TRIGGER tape_entries_au AFTER UPDATE ON tape_entries BEGIN
    -- FTS5 doesn't support UPDATE directly; do delete + insert
    INSERT INTO tape_entries_fts(tape_entries_fts, rowid, tape_id, kind, payload, meta, date)
    VALUES ('delete', old.id, old.tape_id, old.kind, old.payload, old.meta, old.date);
    INSERT INTO tape_entries_fts(rowid, tape_id, kind, payload, meta, date)
    VALUES (new.id, new.tape_id, new.kind, new.payload, new.meta, new.date);
END;

-- ========================================
-- 3. Initial population (one-time)
-- ========================================
-- Only needed if the source table already has data.

INSERT INTO tape_entries_fts(rowid, tape_id, kind, payload, meta, date)
SELECT id, tape_id, kind, payload, meta, date FROM tape_entries;

-- ========================================
-- 4. Basic queries
-- ========================================

-- 4a. Search for a word across all indexed columns
SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'hello';

-- 4b. Search within a specific tape
SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'hello'
  AND e.tape_id = 1;

-- 4c. Search in a specific column (prefix with column name)
SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'kind:message';

-- 4d. Phrase search (exact phrase)
SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH '"system prompt"';

-- 4e. Prefix search (terms starting with...)
SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'hel*';

-- 4f. Boolean operators
SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'hello AND world';

SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'hello OR world';

SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'hello NOT world';

-- ========================================
-- 5. Ranking with bm25() (relevance)
-- ========================================
-- bm25() returns a score; lower = more relevant.

SELECT e.*, bm25(tape_entries_fts) as rank
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'error'
ORDER BY rank;

-- ========================================
-- 6. Highlighting matches
-- ========================================
-- highlight() wraps matches in <b>..</b> by default.

SELECT 
    e.entry_id,
    e.kind,
    highlight(tape_entries_fts, 2, '<mark>', '</mark>') as highlighted_payload
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'hello';

-- ========================================
-- 7. Snippets (context around matches)
-- ========================================
-- snippet() returns a short excerpt with match highlighting.

SELECT 
    e.entry_id,
    e.kind,
    snippet(tape_entries_fts, 2, '<b>', '</b>', '...', 32) as snippet
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'hello';

-- ========================================
-- 8. Combined with other filters
-- ========================================
-- FTS5 handles the text search; regular WHERE for other filters.

SELECT e.*
FROM tape_entries e
JOIN tape_entries_fts f ON e.id = f.rowid
WHERE f.tape_entries_fts MATCH 'run'
  AND e.tape_id = 1
  AND e.kind IN ('message', 'event')
  AND e.entry_id > 10
ORDER BY e.entry_id
LIMIT 20;

-- ========================================
-- 9. Performance notes
-- ========================================
-- FTS5 is extremely fast for text search because it uses an inverted index.
-- For a table with 1M rows, a MATCH query is typically < 1ms.
-- The JOIN to the source table adds overhead; for best performance,
-- only select columns you need.

-- ========================================
-- 10. Maintenance
-- ========================================

-- Rebuild the index (if it gets corrupted or out of sync):
INSERT INTO tape_entries_fts(tape_entries_fts) VALUES ('rebuild');

-- Optimize the index (run periodically to reduce size):
INSERT INTO tape_entries_fts(tape_entries_fts) VALUES ('optimize');

-- Delete all rows from the index:
INSERT INTO tape_entries_fts(tape_entries_fts) VALUES ('delete-all');

-- ========================================
-- 11. Alternative: Without content table (standalone)
-- ========================================
-- If you don't want to JOIN back to tape_entries, you can store
-- all data in the FTS table itself. But this duplicates data.

CREATE VIRTUAL TABLE tape_entries_fts_standalone USING fts5(
    tape_id UNINDEXED,  -- Not searchable, just stored
    entry_id UNINDEXED,
    kind,
    payload,
    meta,
    date
);

-- Query standalone table directly:
SELECT * FROM tape_entries_fts_standalone WHERE tape_entries_fts_standalone MATCH 'hello';
