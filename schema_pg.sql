CREATE TABLE IF NOT EXISTS roommates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    avatar_url TEXT,
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
