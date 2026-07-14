import sqlite3

from tradingagents.rnd.storage import init_db


def test_v2_thesis_tables_are_additive_migrations():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"thesis_snapshots", "thesis_reviews"}.issubset(tables)
