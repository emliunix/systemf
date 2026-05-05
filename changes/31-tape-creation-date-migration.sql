-- One-off migration: Add 'created' column to tapes table
-- Run this against your tape_store.db before starting the app
--
-- SQLite supports ALTER TABLE ADD COLUMN with NOT NULL when a DEFAULT is provided.

ALTER TABLE tapes ADD COLUMN created TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00';

-- Verify
PRAGMA table_info(tapes);
