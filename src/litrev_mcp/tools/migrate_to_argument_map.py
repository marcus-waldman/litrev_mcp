"""
Migration script: Concept Map -> Argument Map (Hierarchical Structure)

This script migrates the existing concept map schema to support a 3-level hierarchy:
- Topics (high-level themes)
- Propositions (arguable claims, formerly "concepts")
- Evidence (citable support)

Changes:
1. Rename concepts -> propositions
2. Create topics table
3. Create topic_relationships table
4. Create proposition_topics link table
5. Add contested_by column to evidence
6. Remove salience_weight from project_propositions (computed dynamically)
7. Update indexes
"""

import duckdb
from datetime import datetime
from litrev_mcp.tools.rag_db import get_connection


def backup_tables(conn: duckdb.DuckDBPyConnection):
    """Create backup copies of existing tables."""
    print("Creating backup tables...")

    tables_to_backup = [
        'concepts',
        'concept_aliases',
        'project_concepts',
        'concept_relationships',
        'concept_evidence',
        'concept_conflicts'
    ]

    for table in tables_to_backup:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}_backup")
            conn.execute(f"CREATE TABLE {table}_backup AS SELECT * FROM {table}")
            print(f"  [OK] Backed up {table}")
        except Exception as e:
            print(f"  [FAIL] Failed to backup {table}: {e}")
            raise


def create_new_tables(conn: duckdb.DuckDBPyConnection):
    """Create the new tables for the argument map."""
    print("\nCreating new tables...")

    # Topics table
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

    # Topic relationships
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

    # Proposition-topic links
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposition_topics (
            proposition_id VARCHAR NOT NULL,
            topic_id VARCHAR NOT NULL,
            is_primary BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (proposition_id, topic_id)
        )
    """)
    print("  [OK] Created proposition_topics table")


def rename_concepts_to_propositions(conn: duckdb.DuckDBPyConnection):
    """Rename all concept tables to proposition tables."""
    print("\nRenaming concept tables to proposition tables...")

    renames = [
        ('concepts', 'propositions'),
        ('concept_aliases', 'proposition_aliases'),
        ('project_concepts', 'project_propositions'),
        ('concept_relationships', 'proposition_relationships'),
        ('concept_evidence', 'proposition_evidence'),
        ('concept_conflicts', 'proposition_conflicts'),
    ]

    for old_name, new_name in renames:
        try:
            conn.execute(f"ALTER TABLE {old_name} RENAME TO {new_name}")
            print(f"  [OK] Renamed {old_name} -> {new_name}")
        except Exception as e:
            print(f"  [FAIL] Failed to rename {old_name}: {e}")
            raise


def update_column_references(conn: duckdb.DuckDBPyConnection):
    """Update column names that reference 'concept' to 'proposition'."""
    print("\nUpdating column references...")

    # proposition_aliases: concept_id -> proposition_id
    conn.execute("""
        ALTER TABLE proposition_aliases
        RENAME COLUMN concept_id TO proposition_id
    """)
    print("  [OK] Updated proposition_aliases.proposition_id")

    # project_propositions: concept_id -> proposition_id
    conn.execute("""
        ALTER TABLE project_propositions
        RENAME COLUMN concept_id TO proposition_id
    """)
    print("  [OK] Updated project_propositions.proposition_id")

    # proposition_relationships
    conn.execute("""
        ALTER TABLE proposition_relationships
        RENAME COLUMN from_concept_id TO from_proposition_id
    """)
    conn.execute("""
        ALTER TABLE proposition_relationships
        RENAME COLUMN to_concept_id TO to_proposition_id
    """)
    print("  [OK] Updated proposition_relationships foreign keys")

    # proposition_evidence: concept_id -> proposition_id
    conn.execute("""
        ALTER TABLE proposition_evidence
        RENAME COLUMN concept_id TO proposition_id
    """)
    print("  [OK] Updated proposition_evidence.proposition_id")

    # proposition_conflicts: concept_id -> proposition_id
    conn.execute("""
        ALTER TABLE proposition_conflicts
        RENAME COLUMN concept_id TO proposition_id
    """)
    print("  [OK] Updated proposition_conflicts.proposition_id")


def add_contested_by_column(conn: duckdb.DuckDBPyConnection):
    """Add contested_by column to proposition_evidence."""
    print("\nAdding contested_by column to evidence...")

    conn.execute("""
        ALTER TABLE proposition_evidence
        ADD COLUMN contested_by TEXT
    """)
    print("  [OK] Added contested_by column")


def remove_salience_weight(conn: duckdb.DuckDBPyConnection):
    """Remove salience_weight column (will be computed dynamically)."""
    print("\nRemoving salience_weight column (now computed dynamically)...")

    # DuckDB doesn't support DROP COLUMN directly, so we need to recreate the table
    conn.execute("""
        CREATE TABLE project_propositions_new (
            project VARCHAR NOT NULL,
            proposition_id VARCHAR NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (project, proposition_id),
            FOREIGN KEY (proposition_id) REFERENCES propositions(id)
        )
    """)

    # Copy data
    conn.execute("""
        INSERT INTO project_propositions_new (project, proposition_id, added_at)
        SELECT project, proposition_id, added_at
        FROM project_propositions
    """)

    # Drop old table and rename new one
    conn.execute("DROP TABLE project_propositions")
    conn.execute("ALTER TABLE project_propositions_new RENAME TO project_propositions")

    print("  [OK] Removed salience_weight (now dynamic)")


def update_indexes(conn: duckdb.DuckDBPyConnection):
    """Drop old indexes and create new ones."""
    print("\nUpdating indexes...")

    # Drop old indexes (may fail if they don't exist, that's OK)
    old_indexes = [
        'idx_project_concepts_project',
        'idx_project_concepts_concept',
        'idx_relationships_from',
        'idx_relationships_to',
        'idx_relationships_type',
        'idx_evidence_concept',
        'idx_evidence_project',
        'idx_conflicts_project',
        'idx_conflicts_status',
    ]

    for idx in old_indexes:
        try:
            conn.execute(f"DROP INDEX IF EXISTS {idx}")
        except:
            pass

    # Create new indexes
    new_indexes = [
        # Project propositions
        "CREATE INDEX IF NOT EXISTS idx_project_propositions_project ON project_propositions(project)",
        "CREATE INDEX IF NOT EXISTS idx_project_propositions_proposition ON project_propositions(proposition_id)",

        # Proposition relationships
        "CREATE INDEX IF NOT EXISTS idx_proposition_relationships_from ON proposition_relationships(from_proposition_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_relationships_to ON proposition_relationships(to_proposition_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_relationships_type ON proposition_relationships(relationship_type)",

        # Evidence
        "CREATE INDEX IF NOT EXISTS idx_proposition_evidence_proposition ON proposition_evidence(proposition_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_evidence_project ON proposition_evidence(project)",

        # Conflicts
        "CREATE INDEX IF NOT EXISTS idx_proposition_conflicts_project ON proposition_conflicts(project)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_conflicts_status ON proposition_conflicts(status)",

        # Topics
        "CREATE INDEX IF NOT EXISTS idx_topics_project ON topics(project)",

        # Topic relationships
        "CREATE INDEX IF NOT EXISTS idx_topic_relationships_from ON topic_relationships(from_topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_topic_relationships_to ON topic_relationships(to_topic_id)",

        # Proposition topics
        "CREATE INDEX IF NOT EXISTS idx_proposition_topics_proposition ON proposition_topics(proposition_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_topics_topic ON proposition_topics(topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_proposition_topics_primary ON proposition_topics(is_primary)",
    ]

    for idx_sql in new_indexes:
        try:
            conn.execute(idx_sql)
        except Exception as e:
            print(f"  ! Warning: {e}")

    print("  [OK] Updated all indexes")


def verify_migration(conn: duckdb.DuckDBPyConnection):
    """Verify that the migration was successful."""
    print("\nVerifying migration...")

    expected_tables = [
        'propositions',
        'proposition_aliases',
        'project_propositions',
        'proposition_relationships',
        'proposition_evidence',
        'proposition_conflicts',
        'topics',
        'topic_relationships',
        'proposition_topics'
    ]

    for table in expected_tables:
        result = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  [OK] {table}: {result} rows")

    # Check that propositions table has same count as backed up concepts
    old_count = conn.execute("SELECT COUNT(*) FROM concepts_backup").fetchone()[0]
    new_count = conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0]

    if old_count == new_count:
        print(f"\n[OK] Migration successful: {old_count} propositions preserved")
    else:
        print(f"\n[FAIL] Migration issue: {old_count} concepts -> {new_count} propositions")
        raise Exception("Data count mismatch!")


def rollback_migration(conn: duckdb.DuckDBPyConnection):
    """Rollback the migration by restoring from backups."""
    print("\nRolling back migration...")

    tables = [
        'concepts',
        'concept_aliases',
        'project_concepts',
        'concept_relationships',
        'concept_evidence',
        'concept_conflicts'
    ]

    for table in tables:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM {table}_backup")
            print(f"  [OK] Restored {table}")
        except Exception as e:
            print(f"  [FAIL] Failed to restore {table}: {e}")

    print("[OK] Rollback complete")


def run_migration(dry_run: bool = True):
    """
    Run the complete migration.

    Args:
        dry_run: If True, rolls back after verification. If False, commits changes.
    """
    conn = get_connection()

    print("=" * 70)
    print("MIGRATION: Concept Map -> Argument Map")
    print("=" * 70)

    if dry_run:
        print("\n[DRY RUN] Changes will be rolled back\n")
    else:
        print("\n[LIVE MODE] Changes will be committed\n")

    try:
        # Step 1: Backup
        backup_tables(conn)

        # Step 2: Create new tables
        create_new_tables(conn)

        # Step 3: Rename tables
        rename_concepts_to_propositions(conn)

        # Step 4: Update column references
        update_column_references(conn)

        # Step 5: Add contested_by column
        add_contested_by_column(conn)

        # Step 6: Remove salience_weight
        remove_salience_weight(conn)

        # Step 7: Update indexes
        update_indexes(conn)

        # Step 8: Verify
        verify_migration(conn)

        if dry_run:
            print("\n[ROLLBACK] Rolling back (dry run mode)...")
            rollback_migration(conn)
            print("\n[OK] Dry run complete. Run with dry_run=False to commit.")
        else:
            print("\n[SUCCESS] Migration complete and committed!")
            print("   Backup tables remain available for safety.")

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        print("   Attempting rollback...")
        try:
            rollback_migration(conn)
            print("[OK] Rollback successful")
        except Exception as rollback_error:
            print(f"[ERROR] Rollback also failed: {rollback_error}")
            print("   Manual intervention may be required.")
        raise


if __name__ == "__main__":
    import sys

    # Allow running with --live flag
    dry_run = '--live' not in sys.argv

    run_migration(dry_run=dry_run)
