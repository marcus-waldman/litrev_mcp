#!/usr/bin/env python3
"""
One-time migration script: local literature.duckdb → MotherDuck cloud.

Usage:
    python scripts/migrate_to_motherduck.py <path_to_local_literature.duckdb>

Requires:
    - MOTHERDUCK_TOKEN environment variable set
    - duckdb Python package installed

What it does:
    1. Connects to MotherDuck (creates database if needed)
    2. Initializes the schema via litrev-mcp's _init_schema
    3. Attaches your local .duckdb file
    4. Copies all rows from each table into MotherDuck
"""

import os
import sys
from pathlib import Path


# Tables to migrate, in dependency order (parents before children)
TABLES = [
    "rag_metadata",
    "papers",
    "chunks",
    # Argument map tables
    "topics",
    "topic_relationships",
    "propositions",
    "proposition_aliases",
    "project_propositions",
    "proposition_relationships",
    "proposition_topics",
    "proposition_evidence",
    "proposition_conflicts",
    "proposition_embeddings",
]


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_to_motherduck.py <path_to_local_literature.duckdb>")
        sys.exit(1)

    local_db_path = Path(sys.argv[1])
    if not local_db_path.exists():
        print(f"ERROR: Local database not found: {local_db_path}")
        sys.exit(1)

    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        print("ERROR: MOTHERDUCK_TOKEN environment variable not set")
        print("Get a token from https://app.motherduck.com/settings")
        sys.exit(1)

    # Allow overriding the database name
    db_name = os.environ.get("MOTHERDUCK_DATABASE", "litrev")

    import duckdb

    print(f"Connecting to MotherDuck (database: {db_name})...")
    md_conn = duckdb.connect(f"md:{db_name}?motherduck_token={token}")

    # Initialize schema on MotherDuck using litrev-mcp's schema init
    print("Initializing schema on MotherDuck...")
    try:
        from litrev_mcp.tools.rag_db import _init_schema
        _init_schema(md_conn)
    except ImportError:
        print("WARNING: Could not import litrev_mcp. Schema must already exist on MotherDuck.")
        print("Install litrev-mcp first: pip install -e .")

    try:
        from litrev_mcp.tools.argument_map_db import init_argument_map_schema
        # Temporarily override get_connection to return our md_conn
        import litrev_mcp.tools.rag_db as rag_db_mod
        original_conn = rag_db_mod._connection
        rag_db_mod._connection = md_conn
        try:
            init_argument_map_schema()
        finally:
            rag_db_mod._connection = original_conn
    except ImportError:
        print("WARNING: Could not import argument_map_db. Argument map schema must already exist.")

    # Attach local database
    print(f"Attaching local database: {local_db_path}")
    md_conn.execute(f"ATTACH '{local_db_path}' AS local_db (READ_ONLY)")

    # Get list of tables in local database
    # Use SHOW TABLES which works reliably across local/remote databases
    local_tables = md_conn.execute("SHOW TABLES FROM local_db").fetchall()
    local_table_names = {t[0] for t in local_tables}

    print(f"Found {len(local_table_names)} tables in local database: {sorted(local_table_names)}")
    print()

    # Migrate each table
    total_rows = 0
    for table in TABLES:
        if table not in local_table_names:
            print(f"  SKIP {table}: not in local database")
            continue

        # Count rows in local
        count = md_conn.execute(f"SELECT COUNT(*) FROM local_db.{table}").fetchone()[0]
        if count == 0:
            print(f"  SKIP {table}: empty")
            continue

        # Check if target already has data
        target_count = md_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if target_count > 0:
            print(f"  SKIP {table}: MotherDuck already has {target_count} rows (local has {count})")
            continue

        print(f"  Migrating {table}: {count} rows...", end=" ", flush=True)
        try:
            md_conn.execute(f"INSERT INTO {table} SELECT * FROM local_db.{table}")
            total_rows += count
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")

    # Detach local database
    md_conn.execute("DETACH local_db")

    print()
    print(f"Migration complete! {total_rows} total rows migrated to MotherDuck ({db_name}).")
    print()
    print("Verify by running: litrev_hello or setup_check")

    md_conn.close()


if __name__ == "__main__":
    main()
