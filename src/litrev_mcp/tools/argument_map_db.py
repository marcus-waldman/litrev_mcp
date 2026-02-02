"""
DuckDB database module for Argument Map feature (formerly Concept Map).

Handles schema initialization and CRUD operations for the 3-level argument map:
- Topics: high-level organizational themes (project-scoped)
- Propositions: arguable assertions (global library, formerly "concepts")
- Evidence: citable support linking propositions to insights (project-scoped)

Also handles:
- Relationships between propositions and topics
- Conflict tracking between AI scaffolding and grounded evidence
- Dynamic salience computation (no stored weights)
"""

import logging
import duckdb
from typing import Optional, Any
from datetime import datetime

from litrev_mcp.tools.rag_db import get_connection, get_embedding_dimensions, is_vss_available

logger = logging.getLogger(__name__)


def init_argument_map_schema():
    """Initialize argument map tables in the existing DuckDB database."""
    conn = get_connection()

    # Topics: high-level organizational themes (project-scoped)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            description TEXT,
            project VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project, name)
        )
    """)

    # Topic relationships (broad types: motivates, contextualizes, etc.)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topic_relationships (
            id INTEGER PRIMARY KEY,
            from_topic_id VARCHAR NOT NULL,
            to_topic_id VARCHAR NOT NULL,
            relationship_type VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_topic_id, to_topic_id, relationship_type),
            FOREIGN KEY (from_topic_id) REFERENCES topics(id),
            FOREIGN KEY (to_topic_id) REFERENCES topics(id)
        )
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS topic_relationships_id_seq")

    # Propositions: arguable assertions (global library, formerly "concepts")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS propositions (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            definition TEXT,
            source VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Proposition aliases for flexible matching
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposition_aliases (
            proposition_id VARCHAR NOT NULL,
            alias VARCHAR NOT NULL,
            PRIMARY KEY (proposition_id, alias),
            FOREIGN KEY (proposition_id) REFERENCES propositions(id)
        )
    """)

    # Project-specific proposition links (no salience - computed dynamically)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS project_propositions (
            project VARCHAR NOT NULL,
            proposition_id VARCHAR NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (project, proposition_id),
            FOREIGN KEY (proposition_id) REFERENCES propositions(id)
        )
    """)

    # Proposition relationships (argumentative: supports, contradicts, etc.)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposition_relationships (
            id INTEGER PRIMARY KEY,
            from_proposition_id VARCHAR NOT NULL,
            to_proposition_id VARCHAR NOT NULL,
            relationship_type VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            grounded_in_insight_id VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_proposition_id, to_proposition_id, relationship_type),
            FOREIGN KEY (from_proposition_id) REFERENCES propositions(id),
            FOREIGN KEY (to_proposition_id) REFERENCES propositions(id)
        )
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS proposition_relationships_id_seq")

    # Proposition-topic links (primary + secondary topics)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposition_topics (
            proposition_id VARCHAR NOT NULL,
            topic_id VARCHAR NOT NULL,
            is_primary BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (proposition_id, topic_id),
            FOREIGN KEY (proposition_id) REFERENCES propositions(id),
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
    """)

    # Evidence: citable support for propositions (project-specific)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposition_evidence (
            id INTEGER PRIMARY KEY,
            proposition_id VARCHAR NOT NULL,
            project VARCHAR NOT NULL,
            insight_id VARCHAR NOT NULL,
            claim TEXT NOT NULL,
            pages VARCHAR,
            contested_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (proposition_id) REFERENCES propositions(id)
        )
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS proposition_evidence_id_seq")

    # Conflicts: when AI scaffolding contradicts grounded evidence
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposition_conflicts (
            id INTEGER PRIMARY KEY,
            proposition_id VARCHAR NOT NULL,
            project VARCHAR NOT NULL,
            ai_claim TEXT NOT NULL,
            evidence_claim TEXT NOT NULL,
            insight_id VARCHAR NOT NULL,
            status VARCHAR DEFAULT 'unresolved',
            resolution_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY (proposition_id) REFERENCES propositions(id)
        )
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS proposition_conflicts_id_seq")

    # Proposition embeddings for semantic search (GraphRAG traversal)
    dims = get_embedding_dimensions()
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS proposition_embeddings (
            proposition_id VARCHAR PRIMARY KEY,
            embedding FLOAT[{dims}] NOT NULL,
            embedded_text TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (proposition_id) REFERENCES propositions(id)
        )
    """)
    if is_vss_available():
        try:
            conn.execute("""
                CREATE INDEX IF NOT EXISTS proposition_embeddings_idx
                ON proposition_embeddings USING HNSW (embedding)
                WITH (metric = 'cosine')
            """)
        except (duckdb.CatalogException, Exception) as e:
            logger.warning(f"Could not create HNSW index on proposition_embeddings: {e}")
    else:
        logger.info("Skipping HNSW index on proposition_embeddings (VSS not available)")

    # Create indexes for common queries
    _create_indexes(conn)


def _create_indexes(conn: duckdb.DuckDBPyConnection):
    """Create indexes for efficient querying."""
    indexes = [
        # Topics
        "CREATE INDEX IF NOT EXISTS idx_topics_project ON topics(project)",

        # Topic relationships
        "CREATE INDEX IF NOT EXISTS idx_topic_relationships_from ON topic_relationships(from_topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_topic_relationships_to ON topic_relationships(to_topic_id)",

        # Project propositions
        "CREATE INDEX IF NOT EXISTS idx_project_propositions_project ON project_propositions(project)",
        "CREATE INDEX IF NOT EXISTS idx_project_propositions_proposition ON project_propositions(proposition_id)",

        # Proposition relationships
        "CREATE INDEX IF NOT EXISTS idx_proposition_relationships_from ON proposition_relationships(from_proposition_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_relationships_to ON proposition_relationships(to_proposition_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_relationships_type ON proposition_relationships(relationship_type)",

        # Proposition topics
        "CREATE INDEX IF NOT EXISTS idx_proposition_topics_proposition ON proposition_topics(proposition_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_topics_topic ON proposition_topics(topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_topics_primary ON proposition_topics(is_primary)",

        # Evidence
        "CREATE INDEX IF NOT EXISTS idx_proposition_evidence_proposition ON proposition_evidence(proposition_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_evidence_project ON proposition_evidence(project)",

        # Conflicts
        "CREATE INDEX IF NOT EXISTS idx_proposition_conflicts_project ON proposition_conflicts(project)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_conflicts_status ON proposition_conflicts(status)",
    ]

    for index_sql in indexes:
        try:
            conn.execute(index_sql)
        except duckdb.CatalogException:
            # Index already exists
            pass


# ============================================================================
# CRUD Operations: Topics
# ============================================================================

def topic_exists(topic_id: str) -> bool:
    """Check if a topic exists."""
    conn = get_connection()
    result = conn.execute(
        "SELECT 1 FROM topics WHERE id = ?", [topic_id]
    ).fetchone()
    return result is not None


def get_topic(topic_id: str) -> Optional[dict]:
    """Get a topic by ID."""
    conn = get_connection()
    result = conn.execute("""
        SELECT id, name, description, project, created_at, updated_at
        FROM topics
        WHERE id = ?
    """, [topic_id]).fetchone()

    if not result:
        return None

    return {
        'id': result[0],
        'name': result[1],
        'description': result[2],
        'project': result[3],
        'created_at': str(result[4]) if result[4] else None,
        'updated_at': str(result[5]) if result[5] else None,
    }


def upsert_topic(
    topic_id: str,
    name: str,
    description: Optional[str],
    project: str,
) -> dict:
    """Insert or update a topic. Returns the topic record."""
    conn = get_connection()
    now = datetime.now()

    if topic_exists(topic_id):
        # Update existing
        conn.execute("""
            UPDATE topics
            SET name = ?, description = ?, updated_at = ?
            WHERE id = ?
        """, [name, description, now, topic_id])
    else:
        # Insert new
        conn.execute("""
            INSERT INTO topics (id, name, description, project, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [topic_id, name, description, project, now, now])

    return get_topic(topic_id)


def delete_topic(topic_id: str):
    """Delete a topic and related data."""
    conn = get_connection()
    # Manual cascade
    conn.execute("DELETE FROM topic_relationships WHERE from_topic_id = ? OR to_topic_id = ?", [topic_id, topic_id])
    conn.execute("DELETE FROM proposition_topics WHERE topic_id = ?", [topic_id])
    conn.execute("DELETE FROM topics WHERE id = ?", [topic_id])


def get_project_topics(project: str) -> list[dict]:
    """Get all topics for a project with proposition counts."""
    conn = get_connection()

    results = conn.execute("""
        SELECT
            t.id,
            t.name,
            t.description,
            COUNT(DISTINCT pt.proposition_id) AS proposition_count,
            COUNT(DISTINCT CASE WHEN pt.is_primary THEN pt.proposition_id END) AS primary_count
        FROM topics t
        LEFT JOIN proposition_topics pt ON t.id = pt.topic_id
        WHERE t.project = ?
        GROUP BY t.id, t.name, t.description
        ORDER BY t.name
    """, [project]).fetchall()

    return [
        {
            'id': r[0],
            'name': r[1],
            'description': r[2],
            'proposition_count': r[3],
            'primary_count': r[4],
        }
        for r in results
    ]


def add_topic_relationship(
    from_topic_id: str,
    to_topic_id: str,
    relationship_type: str,
):
    """Add a relationship between topics."""
    conn = get_connection()

    conn.execute("""
        INSERT INTO topic_relationships (
            id, from_topic_id, to_topic_id, relationship_type, created_at
        )
        VALUES (nextval('topic_relationships_id_seq'), ?, ?, ?, ?)
        ON CONFLICT (from_topic_id, to_topic_id, relationship_type) DO NOTHING
    """, [from_topic_id, to_topic_id, relationship_type, datetime.now()])


def get_topic_relationships(topic_id: Optional[str] = None) -> list[dict]:
    """Get topic relationships, optionally filtered by topic."""
    conn = get_connection()

    sql = """
        SELECT
            r.id,
            r.from_topic_id,
            t1.name AS from_name,
            r.to_topic_id,
            t2.name AS to_name,
            r.relationship_type
        FROM topic_relationships r
        JOIN topics t1 ON r.from_topic_id = t1.id
        JOIN topics t2 ON r.to_topic_id = t2.id
        WHERE 1=1
    """
    params = []

    if topic_id:
        sql += " AND (r.from_topic_id = ? OR r.to_topic_id = ?)"
        params.extend([topic_id, topic_id])

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'id': r[0],
            'from_topic_id': r[1],
            'from_name': r[2],
            'to_topic_id': r[3],
            'to_name': r[4],
            'relationship_type': r[5],
        }
        for r in results
    ]


def delete_topic_relationship(
    from_topic_id: str,
    to_topic_id: str,
    relationship_type: str,
):
    """Delete a specific topic relationship."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM topic_relationships
        WHERE from_topic_id = ? AND to_topic_id = ? AND relationship_type = ?
    """, [from_topic_id, to_topic_id, relationship_type])


# ============================================================================
# CRUD Operations: Propositions (formerly Concepts)
# ============================================================================

def proposition_exists(proposition_id: str) -> bool:
    """Check if a proposition exists."""
    conn = get_connection()
    result = conn.execute(
        "SELECT 1 FROM propositions WHERE id = ?", [proposition_id]
    ).fetchone()
    return result is not None


def get_proposition(proposition_id: str) -> Optional[dict]:
    """Get a proposition by ID."""
    conn = get_connection()
    result = conn.execute("""
        SELECT id, name, definition, source, created_at, updated_at
        FROM propositions
        WHERE id = ?
    """, [proposition_id]).fetchone()

    if not result:
        return None

    return {
        'id': result[0],
        'name': result[1],
        'definition': result[2],
        'source': result[3],
        'created_at': str(result[4]) if result[4] else None,
        'updated_at': str(result[5]) if result[5] else None,
    }


def upsert_proposition(
    proposition_id: str,
    name: str,
    definition: Optional[str],
    source: str,
) -> dict:
    """Insert or update a proposition. Returns the proposition record."""
    conn = get_connection()
    now = datetime.now()

    if proposition_exists(proposition_id):
        # Update existing
        conn.execute("""
            UPDATE propositions
            SET name = ?, definition = ?, source = ?, updated_at = ?
            WHERE id = ?
        """, [name, definition, source, now, proposition_id])
    else:
        # Insert new
        conn.execute("""
            INSERT INTO propositions (id, name, definition, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [proposition_id, name, definition, source, now, now])

    return get_proposition(proposition_id)


def delete_proposition(proposition_id: str):
    """Delete a proposition and all related data (manual cascade since DuckDB doesn't support ON DELETE CASCADE)."""
    conn = get_connection()
    # Manual cascade: delete related data first
    conn.execute("DELETE FROM proposition_aliases WHERE proposition_id = ?", [proposition_id])
    conn.execute("DELETE FROM project_propositions WHERE proposition_id = ?", [proposition_id])
    conn.execute("DELETE FROM proposition_relationships WHERE from_proposition_id = ? OR to_proposition_id = ?", [proposition_id, proposition_id])
    conn.execute("DELETE FROM proposition_evidence WHERE proposition_id = ?", [proposition_id])
    conn.execute("DELETE FROM proposition_conflicts WHERE proposition_id = ?", [proposition_id])
    conn.execute("DELETE FROM proposition_embeddings WHERE proposition_id = ?", [proposition_id])
    # Now delete the proposition itself
    conn.execute("DELETE FROM propositions WHERE id = ?", [proposition_id])


def get_project_propositions(
    project: str,
    filter_source: Optional[str] = None,
) -> list[dict]:
    """
    Get all propositions for a project with evidence counts.

    Args:
        project: Project code
        filter_source: Optional filter ('insight' or 'ai_knowledge')

    Note: Salience is now computed dynamically at query time, not stored.
    """
    conn = get_connection()

    sql = """
        SELECT
            c.id,
            c.name,
            c.definition,
            c.source,
            COUNT(DISTINCT e.id) AS evidence_count
        FROM propositions c
        JOIN project_propositions pc ON c.id = pc.proposition_id
        LEFT JOIN proposition_evidence e ON c.id = e.proposition_id AND e.project = pc.project
        WHERE pc.project = ?
    """
    params = [project]

    if filter_source:
        sql += " AND c.source = ?"
        params.append(filter_source)

    sql += """
        GROUP BY c.id, c.name, c.definition, c.source
        ORDER BY c.name
    """

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'id': r[0],
            'name': r[1],
            'definition': r[2],
            'source': r[3],
            'evidence_count': r[4],
        }
        for r in results
    ]


# ============================================================================
# CRUD Operations: Project Propositions
# ============================================================================

def link_proposition_to_project(
    project: str,
    proposition_id: str,
):
    """Link a proposition to a project. Salience is computed dynamically."""
    conn = get_connection()

    # Upsert
    conn.execute("""
        INSERT INTO project_propositions (project, proposition_id, added_at)
        VALUES (?, ?, ?)
        ON CONFLICT (project, proposition_id) DO NOTHING
    """, [project, proposition_id, datetime.now()])


def unlink_proposition_from_project(project: str, proposition_id: str):
    """Remove a proposition from a project (does not delete the proposition itself)."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM project_propositions
        WHERE project = ? AND proposition_id = ?
    """, [project, proposition_id])


# ============================================================================
# CRUD Operations: Proposition-Topic Links
# ============================================================================

def link_proposition_to_topic(
    proposition_id: str,
    topic_id: str,
    is_primary: bool = False,
):
    """Link a proposition to a topic (primary or secondary)."""
    conn = get_connection()

    conn.execute("""
        INSERT INTO proposition_topics (proposition_id, topic_id, is_primary, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (proposition_id, topic_id) DO UPDATE SET
            is_primary = EXCLUDED.is_primary
    """, [proposition_id, topic_id, is_primary, datetime.now()])


def unlink_proposition_from_topic(proposition_id: str, topic_id: str):
    """Remove a proposition-topic link."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM proposition_topics
        WHERE proposition_id = ? AND topic_id = ?
    """, [proposition_id, topic_id])


def get_proposition_topics(proposition_id: str) -> list[dict]:
    """Get all topics for a proposition."""
    conn = get_connection()

    results = conn.execute("""
        SELECT
            pt.topic_id,
            t.name,
            t.description,
            pt.is_primary
        FROM proposition_topics pt
        JOIN topics t ON pt.topic_id = t.id
        WHERE pt.proposition_id = ?
        ORDER BY pt.is_primary DESC, t.name
    """, [proposition_id]).fetchall()

    return [
        {
            'topic_id': r[0],
            'name': r[1],
            'description': r[2],
            'is_primary': r[3],
        }
        for r in results
    ]


def get_topic_propositions(topic_id: str, primary_only: bool = False) -> list[dict]:
    """Get all propositions for a topic."""
    conn = get_connection()

    sql = """
        SELECT
            pt.proposition_id,
            p.name,
            p.definition,
            p.source,
            pt.is_primary
        FROM proposition_topics pt
        JOIN propositions p ON pt.proposition_id = p.id
        WHERE pt.topic_id = ?
    """
    params = [topic_id]

    if primary_only:
        sql += " AND pt.is_primary = TRUE"

    sql += " ORDER BY pt.is_primary DESC, p.name"

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'proposition_id': r[0],
            'name': r[1],
            'definition': r[2],
            'source': r[3],
            'is_primary': r[4],
        }
        for r in results
    ]


# ============================================================================
# CRUD Operations: Aliases
# ============================================================================

def add_alias(proposition_id: str, alias: str):
    """Add an alias for a proposition."""
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO proposition_aliases (proposition_id, alias)
        VALUES (?, ?)
    """, [proposition_id, alias])


def get_aliases(proposition_id: str) -> list[str]:
    """Get all aliases for a proposition."""
    conn = get_connection()
    results = conn.execute("""
        SELECT alias FROM proposition_aliases WHERE proposition_id = ?
    """, [proposition_id]).fetchall()
    return [r[0] for r in results]


def delete_alias(proposition_id: str, alias: str):
    """Remove an alias."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM proposition_aliases
        WHERE proposition_id = ? AND alias = ?
    """, [proposition_id, alias])


# ============================================================================
# CRUD Operations: Relationships
# ============================================================================

def add_relationship(
    from_proposition_id: str,
    to_proposition_id: str,
    relationship_type: str,
    source: str,
    grounded_in_insight_id: Optional[str] = None,
):
    """Add a relationship between propositions."""
    conn = get_connection()

    # Upsert based on unique constraint
    conn.execute("""
        INSERT INTO proposition_relationships (
            id, from_proposition_id, to_proposition_id, relationship_type,
            source, grounded_in_insight_id, created_at
        )
        VALUES (nextval('proposition_relationships_id_seq'), ?, ?, ?, ?, ?, ?)
        ON CONFLICT (from_proposition_id, to_proposition_id, relationship_type) DO UPDATE SET
            source = EXCLUDED.source,
            grounded_in_insight_id = EXCLUDED.grounded_in_insight_id
    """, [from_proposition_id, to_proposition_id, relationship_type, source, grounded_in_insight_id, datetime.now()])


def get_relationships(
    proposition_id: Optional[str] = None,
    relationship_type: Optional[str] = None,
    direction: str = 'both',  # 'from', 'to', or 'both'
) -> list[dict]:
    """Get relationships, optionally filtered."""
    conn = get_connection()

    sql = """
        SELECT
            r.id,
            r.from_proposition_id,
            c1.name AS from_name,
            r.to_proposition_id,
            c2.name AS to_name,
            r.relationship_type,
            r.source,
            r.grounded_in_insight_id
        FROM proposition_relationships r
        JOIN propositions c1 ON r.from_proposition_id = c1.id
        JOIN propositions c2 ON r.to_proposition_id = c2.id
        WHERE 1=1
    """
    params = []

    if proposition_id:
        if direction == 'from':
            sql += " AND r.from_proposition_id = ?"
            params.append(proposition_id)
        elif direction == 'to':
            sql += " AND r.to_proposition_id = ?"
            params.append(proposition_id)
        else:  # both
            sql += " AND (r.from_proposition_id = ? OR r.to_proposition_id = ?)"
            params.extend([proposition_id, proposition_id])

    if relationship_type:
        sql += " AND r.relationship_type = ?"
        params.append(relationship_type)

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'id': r[0],
            'from_proposition_id': r[1],
            'from_name': r[2],
            'to_proposition_id': r[3],
            'to_name': r[4],
            'relationship_type': r[5],
            'source': r[6],
            'grounded_in': r[7],
        }
        for r in results
    ]


def delete_relationship(
    from_proposition_id: str,
    to_proposition_id: str,
    relationship_type: str,
):
    """Delete a specific relationship."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM proposition_relationships
        WHERE from_proposition_id = ? AND to_proposition_id = ? AND relationship_type = ?
    """, [from_proposition_id, to_proposition_id, relationship_type])


# ============================================================================
# CRUD Operations: Evidence
# ============================================================================

def add_evidence(
    proposition_id: str,
    project: str,
    insight_id: str,
    claim: str,
    pages: Optional[str] = None,
    contested_by: Optional[str] = None,
):
    """Add evidence linking a proposition to an insight."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO proposition_evidence (
            id, proposition_id, project, insight_id, claim, pages, contested_by, created_at
        )
        VALUES (nextval('proposition_evidence_id_seq'), ?, ?, ?, ?, ?, ?, ?)
    """, [proposition_id, project, insight_id, claim, pages, contested_by, datetime.now()])


def get_evidence(proposition_id: str, project: Optional[str] = None) -> list[dict]:
    """Get evidence for a proposition, optionally filtered by project."""
    conn = get_connection()

    sql = """
        SELECT id, proposition_id, project, insight_id, claim, pages, contested_by, created_at
        FROM proposition_evidence
        WHERE proposition_id = ?
    """
    params = [proposition_id]

    if project:
        sql += " AND project = ?"
        params.append(project)

    sql += " ORDER BY created_at DESC"

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'id': r[0],
            'proposition_id': r[1],
            'project': r[2],
            'insight_id': r[3],
            'claim': r[4],
            'pages': r[5],
            'contested_by': r[6],
            'created_at': str(r[7]) if r[7] else None,
        }
        for r in results
    ]


def delete_evidence(evidence_id: int):
    """Delete an evidence record."""
    conn = get_connection()
    conn.execute("DELETE FROM proposition_evidence WHERE id = ?", [evidence_id])


# ============================================================================
# CRUD Operations: Conflicts
# ============================================================================

def add_conflict(
    proposition_id: str,
    project: str,
    ai_claim: str,
    evidence_claim: str,
    insight_id: str,
) -> int:
    """Add a conflict. Returns the conflict ID."""
    conn = get_connection()
    result = conn.execute("""
        INSERT INTO proposition_conflicts (
            id, proposition_id, project, ai_claim, evidence_claim,
            insight_id, status, created_at
        )
        VALUES (nextval('proposition_conflicts_id_seq'), ?, ?, ?, ?, ?, 'unresolved', ?)
        RETURNING id
    """, [proposition_id, project, ai_claim, evidence_claim, insight_id, datetime.now()]).fetchone()
    return result[0]


def get_conflicts(
    project: Optional[str] = None,
    status: str = 'unresolved',
) -> list[dict]:
    """Get conflicts, optionally filtered."""
    conn = get_connection()

    sql = """
        SELECT
            cf.id,
            c.name AS concept_name,
            cf.proposition_id,
            cf.project,
            cf.ai_claim,
            cf.evidence_claim,
            cf.insight_id,
            cf.status,
            cf.resolution_note,
            cf.created_at,
            cf.resolved_at
        FROM proposition_conflicts cf
        JOIN propositions c ON cf.proposition_id = c.id
        WHERE 1=1
    """
    params = []

    if project:
        sql += " AND cf.project = ?"
        params.append(project)

    if status != 'all':
        sql += " AND cf.status = ?"
        params.append(status)

    sql += " ORDER BY cf.created_at DESC"

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'id': r[0],
            'concept_name': r[1],
            'proposition_id': r[2],
            'project': r[3],
            'ai_claim': r[4],
            'evidence_claim': r[5],
            'insight_id': r[6],
            'status': r[7],
            'resolution_note': r[8],
            'created_at': str(r[9]) if r[9] else None,
            'resolved_at': str(r[10]) if r[10] else None,
        }
        for r in results
    ]


def resolve_conflict(
    conflict_id: int,
    resolution: str,
    note: Optional[str] = None,
):
    """Resolve a conflict with a resolution status."""
    conn = get_connection()
    conn.execute("""
        UPDATE proposition_conflicts
        SET status = ?, resolution_note = ?, resolved_at = ?
        WHERE id = ?
    """, [resolution, note, datetime.now(), conflict_id])


# ============================================================================
# Query Operations
# ============================================================================

def find_gaps(
    project: str,
) -> list[dict]:
    """
    Find AI knowledge propositions that lack grounded evidence.

    Returns propositions that:
    - Have source='ai_knowledge'
    - Have no evidence in the project

    Note: Salience filtering should be done at query time using dynamic computation.
    """
    conn = get_connection()

    results = conn.execute("""
        SELECT
            c.id,
            c.name,
            c.definition
        FROM propositions c
        JOIN project_propositions pc ON c.id = pc.proposition_id
        LEFT JOIN proposition_evidence e ON c.id = e.proposition_id AND e.project = pc.project
        WHERE pc.project = ?
          AND c.source = 'ai_knowledge'
          AND e.proposition_id IS NULL
        ORDER BY c.name
    """, [project]).fetchall()

    return [
        {
            'id': r[0],
            'name': r[1],
            'definition': r[2],
        }
        for r in results
    ]


def get_argument_map_stats(project: Optional[str] = None) -> dict:
    """Get statistics about the argument map."""
    conn = get_connection()

    if project:
        # Project-specific stats
        total = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM propositions c
            JOIN project_propositions pc ON c.id = pc.proposition_id
            WHERE pc.project = ?
        """, [project]).fetchone()[0]

        grounded = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM propositions c
            JOIN project_propositions pc ON c.id = pc.proposition_id
            LEFT JOIN proposition_evidence e ON c.id = e.proposition_id AND e.project = ?
            WHERE pc.project = ? AND c.source = 'insight'
        """, [project, project]).fetchone()[0]

        scaffolding = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM propositions c
            JOIN project_propositions pc ON c.id = pc.proposition_id
            LEFT JOIN proposition_evidence e ON c.id = e.proposition_id AND e.project = ?
            WHERE pc.project = ? AND c.source = 'ai_knowledge' AND e.proposition_id IS NOT NULL
        """, [project, project]).fetchone()[0]

        gaps = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM propositions c
            JOIN project_propositions pc ON c.id = pc.proposition_id
            LEFT JOIN proposition_evidence e ON c.id = e.proposition_id AND e.project = ?
            WHERE pc.project = ? AND c.source = 'ai_knowledge' AND e.proposition_id IS NULL
        """, [project, project]).fetchone()[0]

        relationships = conn.execute("""
            SELECT COUNT(DISTINCT r.id)
            FROM proposition_relationships r
            JOIN project_propositions pc1 ON r.from_proposition_id = pc1.proposition_id
            JOIN project_propositions pc2 ON r.to_proposition_id = pc2.proposition_id
            WHERE pc1.project = ? AND pc2.project = ?
        """, [project, project]).fetchone()[0]
    else:
        # Global stats
        total = conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0]
        grounded = conn.execute("SELECT COUNT(*) FROM propositions WHERE source = 'insight'").fetchone()[0]
        scaffolding = conn.execute("SELECT COUNT(*) FROM propositions WHERE source = 'ai_knowledge'").fetchone()[0]
        gaps = 0  # Can't compute gaps without project context
        relationships = conn.execute("SELECT COUNT(*) FROM proposition_relationships").fetchone()[0]

    return {
        'total_propositions': total,
        'grounded': grounded,
        'ai_scaffolding': scaffolding,
        'gaps': gaps,
        'relationships': relationships,
    }


# ============================================================================
# Embedding Operations (for GraphRAG traversal)
# ============================================================================

def upsert_proposition_embedding(
    proposition_id: str,
    embedding: list[float],
    embedded_text: str,
):
    """Insert or update a proposition's embedding vector."""
    conn = get_connection()
    now = datetime.now()

    existing = conn.execute(
        "SELECT 1 FROM proposition_embeddings WHERE proposition_id = ?",
        [proposition_id]
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE proposition_embeddings
            SET embedding = ?, embedded_text = ?, updated_at = ?
            WHERE proposition_id = ?
        """, [embedding, embedded_text, now, proposition_id])
    else:
        conn.execute("""
            INSERT INTO proposition_embeddings (proposition_id, embedding, embedded_text, updated_at)
            VALUES (?, ?, ?, ?)
        """, [proposition_id, embedding, embedded_text, now])


def search_similar_propositions(
    query_embedding: list[float],
    project: Optional[str] = None,
    max_results: int = 10,
    min_score: float = 0.3,
) -> list[dict]:
    """
    Search for propositions by embedding similarity.

    Uses HNSW index for fast cosine similarity search.
    Returns list of dicts with: proposition_id, name, definition, source, score.
    """
    conn = get_connection()
    dims = get_embedding_dimensions()

    sql = f"""
        SELECT
            p.id,
            p.name,
            p.definition,
            p.source,
            array_cosine_similarity(pe.embedding, ?::FLOAT[{dims}]) as score
        FROM proposition_embeddings pe
        JOIN propositions p ON pe.proposition_id = p.id
    """
    params: list[Any] = [query_embedding]

    if project:
        sql += " JOIN project_propositions pp ON p.id = pp.proposition_id AND pp.project = ?"
        params.append(project)

    sql += " ORDER BY score DESC LIMIT ?"
    params.append(max_results)

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'proposition_id': r[0],
            'name': r[1],
            'definition': r[2],
            'source': r[3],
            'score': round(r[4], 4) if r[4] else 0.0,
        }
        for r in results
        if r[4] and r[4] >= min_score
    ]


def get_proposition_neighbors(
    proposition_ids: list[str],
    relationship_types: Optional[list[str]] = None,
    project: Optional[str] = None,
) -> dict:
    """
    Get neighboring propositions connected by relationships.

    Args:
        proposition_ids: IDs to expand from
        relationship_types: Only follow these types (None = all)
        project: Scope to project propositions

    Returns:
        dict with 'propositions' (new neighbor dicts) and 'relationships' (edge dicts)
    """
    conn = get_connection()

    if not proposition_ids:
        return {'propositions': [], 'relationships': []}

    placeholders = ', '.join(['?' for _ in proposition_ids])

    sql = f"""
        SELECT
            r.id,
            r.from_proposition_id,
            c1.name AS from_name,
            r.to_proposition_id,
            c2.name AS to_name,
            r.relationship_type,
            r.source,
            r.grounded_in_insight_id
        FROM proposition_relationships r
        JOIN propositions c1 ON r.from_proposition_id = c1.id
        JOIN propositions c2 ON r.to_proposition_id = c2.id
        WHERE (r.from_proposition_id IN ({placeholders})
           OR r.to_proposition_id IN ({placeholders}))
    """
    params: list[Any] = list(proposition_ids) + list(proposition_ids)

    if relationship_types:
        type_placeholders = ', '.join(['?' for _ in relationship_types])
        sql += f" AND r.relationship_type IN ({type_placeholders})"
        params.extend(relationship_types)

    if project:
        sql += """
            AND r.from_proposition_id IN (SELECT proposition_id FROM project_propositions WHERE project = ?)
            AND r.to_proposition_id IN (SELECT proposition_id FROM project_propositions WHERE project = ?)
        """
        params.extend([project, project])

    results = conn.execute(sql, params).fetchall()

    neighbor_ids = set()
    relationships = []
    for r in results:
        relationships.append({
            'id': r[0],
            'from_proposition_id': r[1],
            'from_name': r[2],
            'to_proposition_id': r[3],
            'to_name': r[4],
            'relationship_type': r[5],
            'source': r[6],
            'grounded_in': r[7],
        })
        neighbor_ids.add(r[1])
        neighbor_ids.add(r[3])

    # Get details for new neighbors (not in original set)
    new_ids = neighbor_ids - set(proposition_ids)
    propositions = []
    if new_ids:
        id_placeholders = ', '.join(['?' for _ in new_ids])
        prop_results = conn.execute(f"""
            SELECT id, name, definition, source
            FROM propositions
            WHERE id IN ({id_placeholders})
        """, list(new_ids)).fetchall()

        propositions = [
            {
                'proposition_id': r[0],
                'name': r[1],
                'definition': r[2],
                'source': r[3],
            }
            for r in prop_results
        ]

    return {
        'propositions': propositions,
        'relationships': relationships,
    }


def get_embedding_status(project: Optional[str] = None) -> dict:
    """Get status of proposition embeddings."""
    conn = get_connection()

    if project:
        total = conn.execute("""
            SELECT COUNT(*) FROM project_propositions WHERE project = ?
        """, [project]).fetchone()[0]

        embedded = conn.execute("""
            SELECT COUNT(*)
            FROM proposition_embeddings pe
            JOIN project_propositions pp ON pe.proposition_id = pp.proposition_id
            WHERE pp.project = ?
        """, [project]).fetchone()[0]

        stale = conn.execute("""
            SELECT COUNT(*)
            FROM proposition_embeddings pe
            JOIN propositions p ON pe.proposition_id = p.id
            JOIN project_propositions pp ON p.id = pp.proposition_id
            WHERE pp.project = ?
              AND pe.embedded_text != (p.name || ': ' || COALESCE(p.definition, ''))
        """, [project]).fetchone()[0]
    else:
        total = conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0]
        embedded = conn.execute("SELECT COUNT(*) FROM proposition_embeddings").fetchone()[0]
        stale = 0

    return {
        'total_propositions': total,
        'embedded': embedded,
        'not_embedded': total - embedded,
        'stale': stale,
    }
