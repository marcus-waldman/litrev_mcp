"""
DuckDB database module for RAG (Retrieval Augmented Generation).

Handles schema initialization, connection management, and CRUD operations
for the literature vector search database.
"""

import duckdb
from pathlib import Path
from typing import Optional
from datetime import datetime

from litrev_mcp.config import config_manager

# Singleton connection
_connection: Optional[duckdb.DuckDBPyConnection] = None


def get_db_path() -> Path:
    """Get path to DuckDB file in .litrev folder."""
    lit_path = config_manager.literature_path
    if not lit_path:
        raise ValueError("Literature path not configured. Run setup_check first.")
    return lit_path / ".litrev" / "literature.duckdb"


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get or create DuckDB connection (singleton)."""
    global _connection
    if _connection is None:
        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _connection = duckdb.connect(str(db_path))
        _init_schema(_connection)
    return _connection


def close_connection():
    """Close the database connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def get_embedding_dimensions() -> int:
    """Get configured embedding dimensions."""
    return config_manager.config.rag.embedding_dimensions


def _init_schema(conn: duckdb.DuckDBPyConnection):
    """Initialize database schema if not exists."""
    # Install and load VSS extension for vector search
    conn.execute("INSTALL vss")
    conn.execute("LOAD vss")

    # Enable experimental persistence for HNSW indexes
    conn.execute("SET hnsw_enable_experimental_persistence = true")

    dims = get_embedding_dimensions()

    # Metadata table: stores RAG configuration used for this database
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_metadata (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL
        )
    """)

    # Check/store embedding dimensions
    existing_dims = conn.execute(
        "SELECT value FROM rag_metadata WHERE key = 'embedding_dimensions'"
    ).fetchone()

    if existing_dims is None:
        # New database - store current config
        conn.execute(
            "INSERT INTO rag_metadata (key, value) VALUES ('embedding_dimensions', ?)",
            [str(dims)]
        )
    else:
        stored_dims = int(existing_dims[0])
        if stored_dims != dims:
            raise ValueError(
                f"Database was created with {stored_dims} dimensions but config specifies {dims}. "
                f"Either update config.yaml to use {stored_dims} dimensions, or delete the database "
                f"and re-index with the new dimension setting."
            )

    # Papers table: metadata about indexed papers
    conn.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            item_key VARCHAR PRIMARY KEY,
            citation_key VARCHAR,
            title VARCHAR,
            authors VARCHAR,
            year INTEGER,
            project VARCHAR NOT NULL,
            pdf_path VARCHAR,
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_chunks INTEGER DEFAULT 0
        )
    """)

    # Chunks table: text segments with embeddings
    # Use a sequence for auto-incrementing IDs
    conn.execute("CREATE SEQUENCE IF NOT EXISTS chunks_id_seq")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY DEFAULT nextval('chunks_id_seq'),
            item_key VARCHAR NOT NULL,
            chunk_index INTEGER NOT NULL,
            page_number INTEGER,
            text VARCHAR NOT NULL,
            embedding FLOAT[{dims}] NOT NULL,
            UNIQUE(item_key, chunk_index)
        )
    """)

    # Create HNSW index for fast vector similarity search
    # Check if index exists first
    try:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS chunks_embedding_idx
            ON chunks USING HNSW (embedding)
            WITH (metric = 'cosine')
        """)
    except duckdb.CatalogException:
        # Index already exists
        pass


def paper_exists(item_key: str) -> bool:
    """Check if a paper is already indexed."""
    conn = get_connection()
    result = conn.execute(
        "SELECT 1 FROM papers WHERE item_key = ?", [item_key]
    ).fetchone()
    return result is not None


def delete_paper(item_key: str):
    """Delete a paper and its chunks from the database."""
    conn = get_connection()
    conn.execute("DELETE FROM chunks WHERE item_key = ?", [item_key])
    conn.execute("DELETE FROM papers WHERE item_key = ?", [item_key])


def insert_paper(
    item_key: str,
    citation_key: str,
    title: str,
    authors: str,
    year: Optional[int],
    project: str,
    pdf_path: str,
    total_chunks: int,
):
    """Insert a paper record."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO papers (item_key, citation_key, title, authors, year, project, pdf_path, total_chunks, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [item_key, citation_key, title, authors, year, project, pdf_path, total_chunks, datetime.now()])


def insert_chunk(
    item_key: str,
    chunk_index: int,
    page_number: Optional[int],
    text: str,
    embedding: list[float],
):
    """Insert a chunk with its embedding."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO chunks (item_key, chunk_index, page_number, text, embedding)
        VALUES (?, ?, ?, ?, ?)
    """, [item_key, chunk_index, page_number, text, embedding])


def insert_chunks_batch(
    item_key: str,
    chunks: list[dict],
    embeddings: list[list[float]],
):
    """
    Batch insert all chunks for a paper in a single transaction.

    Args:
        item_key: The paper's item key
        chunks: List of chunk dicts with 'chunk_index', 'page_number', 'text'
        embeddings: List of embedding vectors corresponding to chunks
    """
    conn = get_connection()

    # Prepare data for batch insert
    data = [
        (item_key, chunk['chunk_index'], chunk.get('page_number'), chunk['text'], embedding)
        for chunk, embedding in zip(chunks, embeddings)
    ]

    # Use executemany for efficient batch insert
    conn.executemany("""
        INSERT INTO chunks (item_key, chunk_index, page_number, text, embedding)
        VALUES (?, ?, ?, ?, ?)
    """, data)


def search_similar(
    query_embedding: list[float],
    project: Optional[str] = None,
    max_results: int = 10,
) -> list[dict]:
    """
    Search for similar chunks using vector similarity.

    Returns list of dicts with: citation_key, title, authors, year, page_number, text, score
    """
    conn = get_connection()
    dims = get_embedding_dimensions()

    # Build query with optional project filter
    sql = f"""
        SELECT
            p.citation_key,
            p.title,
            p.authors,
            p.year,
            c.page_number,
            c.text,
            array_cosine_similarity(c.embedding, ?::FLOAT[{dims}]) as score
        FROM chunks c
        JOIN papers p ON c.item_key = p.item_key
    """
    params = [query_embedding]

    if project:
        sql += " WHERE p.project = ?"
        params.append(project)

    sql += """
        ORDER BY score DESC
        LIMIT ?
    """
    params.append(max_results)

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'citation_key': r[0],
            'title': r[1],
            'authors': r[2],
            'year': r[3],
            'page_number': r[4],
            'text': r[5],
            'score': round(r[6], 4) if r[6] else 0.0,
        }
        for r in results
    ]


def get_indexed_papers(project: Optional[str] = None) -> list[dict]:
    """Get list of indexed papers, optionally filtered by project."""
    conn = get_connection()

    sql = "SELECT item_key, citation_key, title, total_chunks, indexed_at FROM papers"
    params = []

    if project:
        sql += " WHERE project = ?"
        params.append(project)

    sql += " ORDER BY indexed_at DESC"

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'item_key': r[0],
            'citation_key': r[1],
            'title': r[2],
            'total_chunks': r[3],
            'indexed_at': str(r[4]) if r[4] else None,
        }
        for r in results
    ]


def get_stats() -> dict:
    """Get database statistics."""
    conn = get_connection()

    paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    project_counts = conn.execute(
        "SELECT project, COUNT(*) FROM papers GROUP BY project"
    ).fetchall()

    # Get stored embedding dimensions
    dims_result = conn.execute(
        "SELECT value FROM rag_metadata WHERE key = 'embedding_dimensions'"
    ).fetchone()
    dims = int(dims_result[0]) if dims_result else get_embedding_dimensions()

    # Estimate storage size (dims * 4 bytes per float * chunk_count)
    estimated_embedding_size_mb = (dims * 4 * chunk_count) / (1024 * 1024)

    return {
        'total_papers': paper_count,
        'total_chunks': chunk_count,
        'papers_by_project': {r[0]: r[1] for r in project_counts},
        'embedding_dimensions': dims,
        'estimated_embedding_size_mb': round(estimated_embedding_size_mb, 2),
    }
