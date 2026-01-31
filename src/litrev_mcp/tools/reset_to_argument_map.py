"""
Reset concept map tables and create fresh argument map schema.

This drops all existing concept map tables and creates a new 3-level hierarchy:
- Topics (high-level themes)
- Propositions (arguable claims)
- Evidence (citable support)
"""

import duckdb
from litrev_mcp.tools.rag_db import get_connection


def drop_old_tables(conn: duckdb.DuckDBPyConnection):
    """Drop all old concept map tables."""
    print("Dropping old concept map tables...")

    tables_to_drop = [
        'concept_conflicts',
        'concept_evidence',
        'concept_relationships',
        'project_concepts',
        'concept_aliases',
        'concepts',
    ]

    for table in tables_to_drop:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            print(f"  [OK] Dropped {table}")
        except Exception as e:
            print(f"  [SKIP] {table}: {e}")

    # Drop sequences
    sequences = [
        'concept_relationships_id_seq',
        'concept_evidence_id_seq',
        'concept_conflicts_id_seq',
    ]

    for seq in sequences:
        try:
            conn.execute(f"DROP SEQUENCE IF EXISTS {seq}")
        except:
            pass


def create_argument_map_schema(conn: duckdb.DuckDBPyConnection):
    """Create the new argument map schema."""
    print("\nCreating argument map schema...")

    # Topics: high-level organizational themes
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
    print("  [OK] Created topics table")

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
    print("  [OK] Created topic_relationships table")

    # Propositions: arguable assertions (formerly "concepts")
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
    print("  [OK] Created propositions table")

    # Proposition aliases
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposition_aliases (
            proposition_id VARCHAR NOT NULL,
            alias VARCHAR NOT NULL,
            PRIMARY KEY (proposition_id, alias),
            FOREIGN KEY (proposition_id) REFERENCES propositions(id)
        )
    """)
    print("  [OK] Created proposition_aliases table")

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
    print("  [OK] Created project_propositions table")

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
    print("  [OK] Created proposition_relationships table")

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
    print("  [OK] Created proposition_topics table")

    # Evidence: citable support for propositions
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
    print("  [OK] Created proposition_evidence table")

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
    print("  [OK] Created proposition_conflicts table")


def create_indexes(conn: duckdb.DuckDBPyConnection):
    """Create indexes for efficient querying."""
    print("\nCreating indexes...")

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

    for idx_sql in indexes:
        try:
            conn.execute(idx_sql)
        except Exception as e:
            print(f"  [WARN] {e}")

    print("  [OK] Created all indexes")


def verify_schema(conn: duckdb.DuckDBPyConnection):
    """Verify the new schema is in place."""
    print("\nVerifying schema...")

    expected_tables = [
        'topics',
        'topic_relationships',
        'propositions',
        'proposition_aliases',
        'project_propositions',
        'proposition_relationships',
        'proposition_topics',
        'proposition_evidence',
        'proposition_conflicts',
    ]

    for table in expected_tables:
        result = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  [OK] {table}: {result} rows")

    print("\n[SUCCESS] Argument map schema ready!")


def reset_to_argument_map():
    """Main function to reset and create argument map."""
    conn = get_connection()

    print("=" * 70)
    print("RESET: Concept Map -> Argument Map (Fresh Start)")
    print("=" * 70)
    print()

    drop_old_tables(conn)
    create_argument_map_schema(conn)
    create_indexes(conn)
    verify_schema(conn)


if __name__ == "__main__":
    reset_to_argument_map()
