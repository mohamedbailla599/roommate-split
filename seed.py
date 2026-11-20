"""Seed demo data for roommate-split.

Refuses to run if the database already contains data.
"""

import os
import sys
from datetime import date, timedelta
from db import get_connection, init_db, DATABASE_PATH
from split_logic import split_expense, calculate_balances, format_mad, settle_debts


def seed() -> None:
    # Ensure database exists and schema is loaded
    init_db()

    conn = get_connection()
    try:
        # Check if database already contains data
        roommate_count = conn.execute("SELECT COUNT(*) FROM roommates").fetchone()[0]
        expense_count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]

        if roommate_count > 0 or expense_count > 0:
            print("Database already contains data! Seeding aborted to protect existing data.")
            sys.exit(1)

        print("Seeding demo roommates...")
        cursor = conn.cursor()
        roommates_data = ["Mohamed", "Brahim", "Mouad"]
        roommate_ids = []
        for name in roommates_data:
            cursor.execute("INSERT INTO roommates (name, is_active) VALUES (?, 1)", (name,))
            roommate_ids.append(cursor.lastrowid)

        mohamed_id, brahim_id, mouad_id = roommate_ids
        today = date.today()

        expenses_data = [
            {
                "label": "Weekly Groceries (Marjane)",
                "amount_centimes": 45000,  # 450.00 MAD
                "date": (today - timedelta(days=3)).isoformat(),
                "paid_by_id": mohamed_id,
                "participants": [mohamed_id, brahim_id, mouad_id],
            },
            {
                "label": "Fiber Internet 100Mbps",
                "amount_centimes": 24900,  # 249.00 MAD
                "date": (today - timedelta(days=2)).isoformat(),
                "paid_by_id": brahim_id,
                "participants": [mohamed_id, brahim_id, mouad_id],
            },
            {
                "label": "Coffee & Snacks",
                "amount_centimes": 9000,  # 90.00 MAD
                "date": today.isoformat(),
                "paid_by_id": mouad_id,
                "participants": [mohamed_id, brahim_id, mouad_id],
            },
        ]

        print("Seeding demo expenses & participant shares...")
        for exp in expenses_data:
            cursor.execute(
                """
                INSERT INTO expenses (label, amount_centimes, date, paid_by_id, settlement_id)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (exp["label"], exp["amount_centimes"], exp["date"], exp["paid_by_id"]),
            )
            expense_id = cursor.lastrowid
            shares = split_expense(exp["amount_centimes"], exp["participants"])
            for pid, share_centimes in shares.items():
                cursor.execute(
                    """
                    INSERT INTO expense_participants (expense_id, roommate_id, share_centimes)
                    VALUES (?, ?, ?)
                    """,
                    (expense_id, pid, share_centimes),
                )

        conn.commit()
        print("Demo data seeded successfully!\n")

        # Display summary
        balances = calculate_balances(roommate_ids, expenses_data)
        id_to_name = {
            mohamed_id: "Mohamed",
            brahim_id: "Brahim",
            mouad_id: "Mouad",
        }

        print("Current Balances:")
        print("-------------------------------------------------------------")
        for rid, bal in balances.items():
            name = id_to_name[rid]
            status = "gets back" if bal["net_balance"] > 0 else "owes"
            print(f"- {name:8s}: Paid {format_mad(bal['total_paid']):>10s} | Share {format_mad(bal['total_share']):>10s} | Net {format_mad(bal['net_balance']):>11s} ({status})")

        print("\nSettle Up Plan:")
        print("-------------------------------------------------------------")
        net_balances = {rid: bal["net_balance"] for rid, bal in balances.items()}
        transfers = settle_debts(net_balances)
        if not transfers:
            print("Everyone is even! No transfers needed.")
        else:
            for t in transfers:
                debtor = id_to_name[t["from_id"]]
                creditor = id_to_name[t["to_id"]]
                amount = format_mad(t["amount_centimes"])
                print(f"👉 {debtor} pays {creditor}: {amount}")
        print("-------------------------------------------------------------")

    finally:
        conn.close()


if __name__ == "__main__":
    seed()
