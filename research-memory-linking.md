# Research: Agentic Memory Systems — Link Generation

Comparison of two open-source agentic memory systems: **Rowboat** and **MemPalace**.

## Rowboat (rowboatlabs/rowboat)

### Architecture
- **Storage**: Plain Markdown files in `~/.rowboat/knowledge/`, organized into folders: People, Organizations, Projects, Topics, Meetings
- **Search**: `grep`/`ripgrep` (literal text matching, case-insensitive)
- **Graph**: No graph database — wiki-links (`[[Folder/Name]]`) inline in markdown content
- **LLM dependency**: Heavy — LLM handles extraction, linking, entity resolution, and traversal

### How Links Are Generated
1. Source material (emails, meetings, voice memos) is collected
2. A **knowledge index** is built by scanning all existing notes (name, email, aliases, metadata)
3. Source material + index are sent to an LLM agent with a detailed system prompt
4. The LLM extracts entities, creates/updates notes, and writes `[[Folder/Name]]` wiki-links
5. The LLM is instructed to maintain **bidirectional links** (if A references B, update B to reference A)
6. A deterministic `wiki-link-rewrite.ts` handles link maintenance when notes are renamed

### Runtime Traversal
- No traversal algorithm — the LLM reads a note, sees `[[links]]`, and decides whether to follow them via `workspace-readFile` tool calls
- Copilot instructions require looking up any mentioned person/org/project in the knowledge base before responding

### Limitations
- No fuzzy/semantic search — typos fail silently
- No alias lookup at runtime — just grep
- Disambiguation is pure LLM judgment
- No temporal query engine — LLM reads dated activity logs and reasons about time

---

## MemPalace (milla-jovovich/mempalace)

### Architecture
- **Storage**: ChromaDB vector database (verbatim text, never summarized) + SQLite temporal knowledge graph
- **Search**: Semantic vector similarity via ChromaDB (handles typos, synonyms, paraphrasing)
- **Graph**: Two separate graphs:
  - Palace graph (`palace_graph.py`): rooms connected by shared wings, BFS traversal
  - Knowledge graph (`knowledge_graph.py`): temporal entity-relationship triples in SQLite
- **LLM dependency**: Light — only used for `general` extraction mode; search is embedding-based

### How Links Are Generated
1. **Palace graph**: Connections are implicit — when the same room name (e.g., "auth-migration") appears in multiple wings, a "tunnel" edge is automatically created
2. **Knowledge graph**: Explicit triples with temporal validity:
   ```python
   kg.add_triple("Maya", "assigned_to", "auth-migration", valid_from="2026-01-15")
   kg.invalidate("Maya", "assigned_to", "auth-migration", ended="2026-02-01")
   ```
3. **Entity detection**: Regex-based heuristic scoring classifies candidates as person/project
4. **Entity registry**: Persistent JSON with aliases, disambiguation, Wikipedia lookup

### Runtime Traversal
- BFS algorithm in `palace_graph.py` — actual graph traversal through rooms connected by shared wings
- Temporal queries: `kg.query_entity("Maya", as_of="2026-01-20")`
- Timeline queries: `kg.timeline("Orion")` — chronological story of an entity
- 4-layer memory stack: L0 (identity, ~50 tokens) + L1 (essential story, ~500-800 tokens) always loaded; L2/L3 on demand

### Strengths Over Rowboat
- Semantic search handles typos and synonyms naturally (96.6% R@5 on LongMemEval)
- First-class temporal validity on facts
- Persistent entity registry with aliases and disambiguation
- Spellcheck with Levenshtein distance
- Actual graph traversal algorithms (BFS), not LLM-dependent
- Zero LLM calls for search/retrieval

---

## Key Tradeoff

| | Rowboat | MemPalace |
|---|---|---|
| **Paradigm** | LLM-curated wiki | Structured vector DB + graph |
| **Human readability** | Excellent (Obsidian-compatible .md files) | Poor (data lives in ChromaDB/SQLite) |
| **Search quality** | Grep (literal) | Semantic vectors (fuzzy) |
| **LLM cost** | High (extraction + traversal) | Low (embedding-only) |
| **Temporal queries** | LLM reads dates in text | SQL with validity windows |
| **Linking** | LLM writes wiki-links (prompt engineering) | Code builds graph edges (algorithms) |

**Rowboat** bets on LLM intelligence for curation and navigation.
**MemPalace** bets on structure + embeddings to replace LLM intelligence at retrieval time.
