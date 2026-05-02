# Store Notes

## FTS Search for Tapes

**Problem**: Tapes can fork, which means the same entry may belong to multiple tapes. Full-text search (FTS) over tape content needs to handle this carefully.

### Strategies

#### 1. Duplicate Entries

Store a separate copy of each entry in the FTS index for every tape it belongs to.

- **Pros**: Simple query logic — `SELECT * FROM fts WHERE tape_id = ?`
- **Cons**: Storage overhead; updates to an entry must propagate to all its copies

#### 2. Multi-Value `tape_ids` Field

Store the entry once in the FTS index with a `tape_ids` column (e.g., JSON array or comma-separated list). Update the column on fork.

- **Pros**: No duplication of entry content
- **Cons**: Updates on fork are non-trivial; must append the new tape ID to all inherited entries' `tape_ids` columns

#### 3. Recursive Query + Merge

Traverse the tape fork graph recursively to collect all entries, then merge the result sets.

- **Pros**: No FTS index duplication; single source of truth
- **Cons**: 
  - Query complexity — must traverse parent chain for every search
  - **Ranking/scoring breaks**: SQLite FTS ranks and scores results per-query. If we merge result sets from multiple tape queries, the scores are not directly comparable. A high-scoring match in a parent tape may dominate over a more relevant match in the child tape, or vice versa.
  - Performance — recursive CTEs over large tape histories may be slow

### Open Questions

- Does SQLite FTS5 support global scoring across disjoint result sets? (Likely no — BM25 is query-local.)
- How expensive is strategy 1 (duplicate) in practice? Tape forks are typically short-lived (single-turn thinking branches).
- For strategy 2, can we use SQLite's JSON functions to maintain `tape_ids` efficiently?
