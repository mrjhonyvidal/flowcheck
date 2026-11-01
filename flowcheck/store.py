"""Commit immutable events together, and reject reused IDs with changed content."""

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from .contracts import order_errors
from .io import canonical


def ingest(records, database):
    if not records:
        raise ValueError("No events to ingest")
    for record in records:
        errors = order_errors(record)
        if errors:
            raise ValueError("Invalid event: " + "; ".join(errors))
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=5)) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
            payload TEXT NOT NULL, currency TEXT NOT NULL, amount_minor INTEGER NOT NULL
        )""")
        inserted, duplicates = 0, 0
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            for record in records:
                payload = canonical(record)
                digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                existing = connection.execute(
                    "SELECT content_hash FROM events WHERE event_id = ?", (record["event_id"],)
                ).fetchone()
                if existing:
                    if existing[0] != digest:
                        raise ValueError(f"Changed content for event_id {record['event_id']}; batch rolled back")
                    duplicates += 1
                    continue
                connection.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)", (
                    record["event_id"], digest, payload, record["currency"], record["amount_minor"]
                ))
                inserted += 1
            totals = dict(connection.execute(
                "SELECT currency, SUM(amount_minor) FROM events GROUP BY currency ORDER BY currency"
            ))
            count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    return {"inserted": inserted, "duplicates": duplicates, "stored_events": count, "totals_minor": totals}
