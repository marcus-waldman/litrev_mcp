"""
DuckDB database module for Concept Map feature.

Handles schema initialization and CRUD operations for the concept map:
- Global concept library (shared across projects)
- Project-specific concept links with salience weights
- Relationships between concepts
- Evidence linking concepts to insights
- Conflict tracking between AI knowledge and grounded evidence
"""

import duckdb
from typing import Optional, Any
from datetime import datetime

from litrev_mcp.tools.rag_db import get_connection


def init_concept_map_schema():
    """Initialize concept map tables in the existing DuckDB database."""
    conn = get_connection()

    # Global concept storage (shared across projects)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concepts (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            definition TEXT,
            source VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Concept aliases for flexible matching
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_aliases (
            concept_id VARCHAR NOT NULL,
            alias VARCHAR NOT NULL,
            PRIMARY KEY (concept_id, alias),
            FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE
        )
    """)

    # Project-specific concept links (with salience)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS project_concepts (
            project VARCHAR NOT NULL,
            concept_id VARCHAR NOT NULL,
            salience_weight FLOAT DEFAULT 0.5,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (project, concept_id),
            FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE
        )
    """)

    # Relationships between concepts (global)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_relationships (
            id INTEGER PRIMARY KEY,
            from_concept_id VARCHAR NOT NULL,
            to_concept_id VARCHAR NOT NULL,
            relationship_type VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            grounded_in_insight_id VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_concept_id, to_concept_id, relationship_type),
            FOREIGN KEY (from_concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
            FOREIGN KEY (to_concept_id) REFERENCES concepts(id) ON DELETE CASCADE
        )
    """)

    # Use a sequence for relationship IDs
    conn.execute("CREATE SEQUENCE IF NOT EXISTS concept_relationships_id_seq")

    # Evidence linking concepts to insights (project-specific)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_evidence (
            id INTEGER PRIMARY KEY,
            concept_id VARCHAR NOT NULL,
            project VARCHAR NOT NULL,
            insight_id VARCHAR NOT NULL,
            claim TEXT NOT NULL,
            pages VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE
        )
    """)

    # Use a sequence for evidence IDs
    conn.execute("CREATE SEQUENCE IF NOT EXISTS concept_evidence_id_seq")

    # Conflict tracking (when AI scaffolding contradicts evidence)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_conflicts (
            id INTEGER PRIMARY KEY,
            concept_id VARCHAR NOT NULL,
            project VARCHAR NOT NULL,
            ai_claim TEXT NOT NULL,
            evidence_claim TEXT NOT NULL,
            insight_id VARCHAR NOT NULL,
            status VARCHAR DEFAULT 'unresolved',
            resolution_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE
        )
    """)

    # Use a sequence for conflict IDs
    conn.execute("CREATE SEQUENCE IF NOT EXISTS concept_conflicts_id_seq")

    # Create indexes for common queries
    _create_indexes(conn)


def _create_indexes(conn: duckdb.DuckDBPyConnection):
    """Create indexes for efficient querying."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_project_concepts_project ON project_concepts(project)",
        "CREATE INDEX IF NOT EXISTS idx_project_concepts_concept ON project_concepts(concept_id)",
        "CREATE INDEX IF NOT EXISTS idx_relationships_from ON concept_relationships(from_concept_id)",
        "CREATE INDEX IF NOT EXISTS idx_relationships_to ON concept_relationships(to_concept_id)",
        "CREATE INDEX IF NOT EXISTS idx_relationships_type ON concept_relationships(relationship_type)",
        "CREATE INDEX IF NOT EXISTS idx_evidence_concept ON concept_evidence(concept_id)",
        "CREATE INDEX IF NOT EXISTS idx_evidence_project ON concept_evidence(project)",
        "CREATE INDEX IF NOT EXISTS idx_conflicts_project ON concept_conflicts(project)",
        "CREATE INDEX IF NOT EXISTS idx_conflicts_status ON concept_conflicts(status)",
    ]

    for index_sql in indexes:
        try:
            conn.execute(index_sql)
        except duckdb.CatalogException:
            # Index already exists
            pass


# ============================================================================
# CRUD Operations: Concepts
# ============================================================================

def concept_exists(concept_id: str) -> bool:
    """Check if a concept exists."""
    conn = get_connection()
    result = conn.execute(
        "SELECT 1 FROM concepts WHERE id = ?", [concept_id]
    ).fetchone()
    return result is not None


def get_concept(concept_id: str) -> Optional[dict]:
    """Get a concept by ID."""
    conn = get_connection()
    result = conn.execute("""
        SELECT id, name, definition, source, created_at, updated_at
        FROM concepts
        WHERE id = ?
    """, [concept_id]).fetchone()

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


def upsert_concept(
    concept_id: str,
    name: str,
    definition: Optional[str],
    source: str,
) -> dict:
    """Insert or update a concept. Returns the concept record."""
    conn = get_connection()
    now = datetime.now()

    if concept_exists(concept_id):
        # Update existing
        conn.execute("""
            UPDATE concepts
            SET name = ?, definition = ?, source = ?, updated_at = ?
            WHERE id = ?
        """, [name, definition, source, now, concept_id])
    else:
        # Insert new
        conn.execute("""
            INSERT INTO concepts (id, name, definition, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [concept_id, name, definition, source, now, now])

    return get_concept(concept_id)


def delete_concept(concept_id: str):
    """Delete a concept and all related data (cascades)."""
    conn = get_connection()
    conn.execute("DELETE FROM concepts WHERE id = ?", [concept_id])


def get_project_concepts(
    project: str,
    filter_source: Optional[str] = None,
    min_salience: float = 0.0,
) -> list[dict]:
    """
    Get all concepts for a project with evidence counts.

    Args:
        project: Project code
        filter_source: Optional filter ('insight' or 'ai_knowledge')
        min_salience: Minimum salience weight to include
    """
    conn = get_connection()

    sql = """
        SELECT
            c.id,
            c.name,
            c.definition,
            c.source,
            pc.salience_weight,
            COUNT(DISTINCT e.id) AS evidence_count
        FROM concepts c
        JOIN project_concepts pc ON c.id = pc.concept_id
        LEFT JOIN concept_evidence e ON c.id = e.concept_id AND e.project = pc.project
        WHERE pc.project = ?
    """
    params = [project]

    if filter_source:
        sql += " AND c.source = ?"
        params.append(filter_source)

    if min_salience > 0:
        sql += " AND pc.salience_weight >= ?"
        params.append(min_salience)

    sql += """
        GROUP BY c.id, c.name, c.definition, c.source, pc.salience_weight
        ORDER BY pc.salience_weight DESC
    """

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'id': r[0],
            'name': r[1],
            'definition': r[2],
            'source': r[3],
            'salience': r[4],
            'evidence_count': r[5],
        }
        for r in results
    ]


# ============================================================================
# CRUD Operations: Project Concepts
# ============================================================================

def link_concept_to_project(
    project: str,
    concept_id: str,
    salience_weight: float = 0.5,
):
    """Link a concept to a project with salience weight."""
    conn = get_connection()

    # Upsert
    conn.execute("""
        INSERT INTO project_concepts (project, concept_id, salience_weight, added_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (project, concept_id) DO UPDATE SET
            salience_weight = EXCLUDED.salience_weight
    """, [project, concept_id, salience_weight, datetime.now()])


def update_concept_salience(project: str, concept_id: str, salience_weight: float):
    """Update salience weight for a concept in a project."""
    conn = get_connection()
    conn.execute("""
        UPDATE project_concepts
        SET salience_weight = ?
        WHERE project = ? AND concept_id = ?
    """, [salience_weight, project, concept_id])


def unlink_concept_from_project(project: str, concept_id: str):
    """Remove a concept from a project (does not delete the concept itself)."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM project_concepts
        WHERE project = ? AND concept_id = ?
    """, [project, concept_id])


# ============================================================================
# CRUD Operations: Aliases
# ============================================================================

def add_alias(concept_id: str, alias: str):
    """Add an alias for a concept."""
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO concept_aliases (concept_id, alias)
        VALUES (?, ?)
    """, [concept_id, alias])


def get_aliases(concept_id: str) -> list[str]:
    """Get all aliases for a concept."""
    conn = get_connection()
    results = conn.execute("""
        SELECT alias FROM concept_aliases WHERE concept_id = ?
    """, [concept_id]).fetchall()
    return [r[0] for r in results]


def delete_alias(concept_id: str, alias: str):
    """Remove an alias."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM concept_aliases
        WHERE concept_id = ? AND alias = ?
    """, [concept_id, alias])


# ============================================================================
# CRUD Operations: Relationships
# ============================================================================

def add_relationship(
    from_concept_id: str,
    to_concept_id: str,
    relationship_type: str,
    source: str,
    grounded_in_insight_id: Optional[str] = None,
):
    """Add a relationship between concepts."""
    conn = get_connection()

    # Upsert based on unique constraint
    conn.execute("""
        INSERT INTO concept_relationships (
            id, from_concept_id, to_concept_id, relationship_type,
            source, grounded_in_insight_id, created_at
        )
        VALUES (nextval('concept_relationships_id_seq'), ?, ?, ?, ?, ?, ?)
        ON CONFLICT (from_concept_id, to_concept_id, relationship_type) DO UPDATE SET
            source = EXCLUDED.source,
            grounded_in_insight_id = EXCLUDED.grounded_in_insight_id
    """, [from_concept_id, to_concept_id, relationship_type, source, grounded_in_insight_id, datetime.now()])


def get_relationships(
    concept_id: Optional[str] = None,
    relationship_type: Optional[str] = None,
    direction: str = 'both',  # 'from', 'to', or 'both'
) -> list[dict]:
    """Get relationships, optionally filtered."""
    conn = get_connection()

    sql = """
        SELECT
            r.id,
            r.from_concept_id,
            c1.name AS from_name,
            r.to_concept_id,
            c2.name AS to_name,
            r.relationship_type,
            r.source,
            r.grounded_in_insight_id
        FROM concept_relationships r
        JOIN concepts c1 ON r.from_concept_id = c1.id
        JOIN concepts c2 ON r.to_concept_id = c2.id
        WHERE 1=1
    """
    params = []

    if concept_id:
        if direction == 'from':
            sql += " AND r.from_concept_id = ?"
            params.append(concept_id)
        elif direction == 'to':
            sql += " AND r.to_concept_id = ?"
            params.append(concept_id)
        else:  # both
            sql += " AND (r.from_concept_id = ? OR r.to_concept_id = ?)"
            params.extend([concept_id, concept_id])

    if relationship_type:
        sql += " AND r.relationship_type = ?"
        params.append(relationship_type)

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'id': r[0],
            'from_concept_id': r[1],
            'from_name': r[2],
            'to_concept_id': r[3],
            'to_name': r[4],
            'relationship_type': r[5],
            'source': r[6],
            'grounded_in': r[7],
        }
        for r in results
    ]


def delete_relationship(
    from_concept_id: str,
    to_concept_id: str,
    relationship_type: str,
):
    """Delete a specific relationship."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM concept_relationships
        WHERE from_concept_id = ? AND to_concept_id = ? AND relationship_type = ?
    """, [from_concept_id, to_concept_id, relationship_type])


# ============================================================================
# CRUD Operations: Evidence
# ============================================================================

def add_evidence(
    concept_id: str,
    project: str,
    insight_id: str,
    claim: str,
    pages: Optional[str] = None,
):
    """Add evidence linking a concept to an insight."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO concept_evidence (
            id, concept_id, project, insight_id, claim, pages, created_at
        )
        VALUES (nextval('concept_evidence_id_seq'), ?, ?, ?, ?, ?, ?)
    """, [concept_id, project, insight_id, claim, pages, datetime.now()])


def get_evidence(concept_id: str, project: Optional[str] = None) -> list[dict]:
    """Get evidence for a concept, optionally filtered by project."""
    conn = get_connection()

    sql = """
        SELECT id, concept_id, project, insight_id, claim, pages, created_at
        FROM concept_evidence
        WHERE concept_id = ?
    """
    params = [concept_id]

    if project:
        sql += " AND project = ?"
        params.append(project)

    sql += " ORDER BY created_at DESC"

    results = conn.execute(sql, params).fetchall()

    return [
        {
            'id': r[0],
            'concept_id': r[1],
            'project': r[2],
            'insight_id': r[3],
            'claim': r[4],
            'pages': r[5],
            'created_at': str(r[6]) if r[6] else None,
        }
        for r in results
    ]


def delete_evidence(evidence_id: int):
    """Delete an evidence record."""
    conn = get_connection()
    conn.execute("DELETE FROM concept_evidence WHERE id = ?", [evidence_id])


# ============================================================================
# CRUD Operations: Conflicts
# ============================================================================

def add_conflict(
    concept_id: str,
    project: str,
    ai_claim: str,
    evidence_claim: str,
    insight_id: str,
) -> int:
    """Add a conflict. Returns the conflict ID."""
    conn = get_connection()
    result = conn.execute("""
        INSERT INTO concept_conflicts (
            id, concept_id, project, ai_claim, evidence_claim,
            insight_id, status, created_at
        )
        VALUES (nextval('concept_conflicts_id_seq'), ?, ?, ?, ?, ?, 'unresolved', ?)
        RETURNING id
    """, [concept_id, project, ai_claim, evidence_claim, insight_id, datetime.now()]).fetchone()
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
            cf.concept_id,
            cf.project,
            cf.ai_claim,
            cf.evidence_claim,
            cf.insight_id,
            cf.status,
            cf.resolution_note,
            cf.created_at,
            cf.resolved_at
        FROM concept_conflicts cf
        JOIN concepts c ON cf.concept_id = c.id
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
            'concept_id': r[2],
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
        UPDATE concept_conflicts
        SET status = ?, resolution_note = ?, resolved_at = ?
        WHERE id = ?
    """, [resolution, note, datetime.now(), conflict_id])


# ============================================================================
# Query Operations
# ============================================================================

def find_gaps(
    project: str,
    min_salience: float = 0.5,
) -> list[dict]:
    """
    Find salient AI knowledge concepts that lack grounded evidence.

    Returns concepts that:
    - Have source='ai_knowledge'
    - Have high salience (>= min_salience)
    - Have no evidence in the project
    """
    conn = get_connection()

    results = conn.execute("""
        SELECT
            c.id,
            c.name,
            c.definition,
            pc.salience_weight
        FROM concepts c
        JOIN project_concepts pc ON c.id = pc.concept_id
        LEFT JOIN concept_evidence e ON c.id = e.concept_id AND e.project = pc.project
        WHERE pc.project = ?
          AND c.source = 'ai_knowledge'
          AND e.concept_id IS NULL
          AND pc.salience_weight >= ?
        ORDER BY pc.salience_weight DESC
    """, [project, min_salience]).fetchall()

    return [
        {
            'id': r[0],
            'name': r[1],
            'definition': r[2],
            'salience': r[3],
        }
        for r in results
    ]


def get_concept_map_stats(project: Optional[str] = None) -> dict:
    """Get statistics about the concept map."""
    conn = get_connection()

    if project:
        # Project-specific stats
        total = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM concepts c
            JOIN project_concepts pc ON c.id = pc.concept_id
            WHERE pc.project = ?
        """, [project]).fetchone()[0]

        grounded = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM concepts c
            JOIN project_concepts pc ON c.id = pc.concept_id
            LEFT JOIN concept_evidence e ON c.id = e.concept_id AND e.project = ?
            WHERE pc.project = ? AND c.source = 'insight'
        """, [project, project]).fetchone()[0]

        scaffolding = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM concepts c
            JOIN project_concepts pc ON c.id = pc.concept_id
            LEFT JOIN concept_evidence e ON c.id = e.concept_id AND e.project = ?
            WHERE pc.project = ? AND c.source = 'ai_knowledge' AND e.concept_id IS NOT NULL
        """, [project, project]).fetchone()[0]

        gaps = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM concepts c
            JOIN project_concepts pc ON c.id = pc.concept_id
            LEFT JOIN concept_evidence e ON c.id = e.concept_id AND e.project = ?
            WHERE pc.project = ? AND c.source = 'ai_knowledge' AND e.concept_id IS NULL
        """, [project, project]).fetchone()[0]

        relationships = conn.execute("""
            SELECT COUNT(DISTINCT r.id)
            FROM concept_relationships r
            JOIN project_concepts pc1 ON r.from_concept_id = pc1.concept_id
            JOIN project_concepts pc2 ON r.to_concept_id = pc2.concept_id
            WHERE pc1.project = ? AND pc2.project = ?
        """, [project, project]).fetchone()[0]
    else:
        # Global stats
        total = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        grounded = conn.execute("SELECT COUNT(*) FROM concepts WHERE source = 'insight'").fetchone()[0]
        scaffolding = conn.execute("SELECT COUNT(*) FROM concepts WHERE source = 'ai_knowledge'").fetchone()[0]
        gaps = 0  # Can't compute gaps without project context
        relationships = conn.execute("SELECT COUNT(*) FROM concept_relationships").fetchone()[0]

    return {
        'total_concepts': total,
        'grounded': grounded,
        'ai_scaffolding': scaffolding,
        'gaps': gaps,
        'relationships': relationships,
    }
