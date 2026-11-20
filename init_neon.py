"""Initializes the database schema on Neon PostgreSQL and migrates any existing data."""

import os
import psycopg2

NEON_URL = os.environ.get("DATABASE_URL")
if not NEON_URL:
    raise ValueError("DATABASE_URL environment variable is required. Please set it in .env or your environment.")

DDL = """
CREATE TABLE IF NOT EXISTS roommates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settlement_periods (
    id SERIAL PRIMARY KEY,
    settled_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    total_expenses_centimes INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS expenses (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    amount_centimes INTEGER NOT NULL,
    date TEXT NOT NULL,
    paid_by_id INTEGER NOT NULL REFERENCES roommates(id),
    settlement_id INTEGER REFERENCES settlement_periods(id),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS expense_participants (
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    roommate_id INTEGER NOT NULL REFERENCES roommates(id),
    share_centimes INTEGER NOT NULL,
    PRIMARY KEY (expense_id, roommate_id)
);

CREATE TABLE IF NOT EXISTS settlement_transfers (
    id SERIAL PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES settlement_periods(id) ON DELETE CASCADE,
    from_roommate_id INTEGER NOT NULL REFERENCES roommates(id),
    to_roommate_id INTEGER NOT NULL REFERENCES roommates(id),
    amount_centimes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    from_roommate_id INTEGER NOT NULL REFERENCES roommates(id),
    to_roommate_id INTEGER NOT NULL REFERENCES roommates(id),
    amount_centimes INTEGER NOT NULL,
    date TEXT NOT NULL,
    notes TEXT,
    settlement_id INTEGER REFERENCES settlement_periods(id),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
"""


def init_neon():
    conn = psycopg2.connect(NEON_URL)
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()

    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
    )
    tables = [r[0] for r in cur.fetchall()]
    print("Neon database initialized with tables:", tables)

    # Check if roommates exist, if not seed Mohamed, Brahim, Mouad
    cur.execute("SELECT COUNT(*) FROM roommates")
    count = cur.fetchone()[0]
    if count == 0:
        for name in ["Mohamed", "Brahim", "Mouad"]:
            cur.execute("INSERT INTO roommates (name, is_active) VALUES (%s, 1)", (name,))
        conn.commit()
        print("Seeded default roommates: Mohamed, Brahim, Mouad into Neon!")
    else:
        cur.execute("SELECT id, name, is_active FROM roommates ORDER BY id")
        print("Existing roommates in Neon:", cur.fetchall())

    conn.close()


if __name__ == "__main__":
    init_neon()
