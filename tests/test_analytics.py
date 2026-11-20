import pytest
from analytics import categorize_expense, compute_reports_data


def test_categorize_expense_keywords():
    assert categorize_expense("Marjane groceries")["key"] == "groceries"
    assert categorize_expense("Khodra w Desser")["key"] == "groceries"
    assert categorize_expense("Burger & fries")["key"] == "food"
    assert categorize_expense("Fibre Optique IAM")["key"] == "utilities"
    assert categorize_expense("Javel et detergent")["key"] == "home"
    assert categorize_expense("InDrive ride home")["key"] == "transport"
    assert categorize_expense("Random miscellaneous stuff")["key"] == "general"


def test_compute_reports_data_empty():
    res = compute_reports_data([], {})
    assert res["has_data"] is False
    assert res["total_spent_centimes"] == 0
    assert res["expense_count"] == 0
    assert len(res["daily_series"]) == 0
    assert len(res["weekly_series"]) == 0


def test_compute_reports_data_with_expenses():
    roommate_map = {
        1: {"id": 1, "name": "Mohamed", "initials": "MH", "gradient": "g1"},
        2: {"id": 2, "name": "Brahim", "initials": "BR", "gradient": "g2"},
        3: {"id": 3, "name": "Mouad", "initials": "MU", "gradient": "g3"},
    }

    expenses = [
        {
            "id": 1,
            "label": "Marjane Groceries",
            "amount_centimes": 30000,
            "date": "2026-11-10",
            "paid_by_id": 1,
            "shares": {1: 10000, 2: 10000, 3: 10000},
            "participants": [1, 2, 3],
        },
        {
            "id": 2,
            "label": "Tacos dinner",
            "amount_centimes": 12000,
            "date": "2026-11-12",
            "paid_by_id": 2,
            "shares": {1: 4000, 2: 4000, 3: 4000},
            "participants": [1, 2, 3],
        },
        {
            "id": 3,
            "label": "Fiber Internet",
            "amount_centimes": 24900,
            "date": "2026-11-17",
            "paid_by_id": 1,
            "shares": {1: 8300, 2: 8300, 3: 8300},
            "participants": [1, 2, 3],
        },
    ]

    payments = [
        {
            "id": 1,
            "from_roommate_id": 3,
            "to_roommate_id": 1,
            "amount_centimes": 5000,
            "date": "2026-11-18",
        }
    ]

    data = compute_reports_data(expenses, roommate_map, payments)
    assert data["has_data"] is True
    assert data["total_spent_centimes"] == 66900  # 30000 + 12000 + 24900
    assert data["expense_count"] == 3
    assert data["payment_count"] == 1
    assert data["total_payments_centimes"] == 5000

    # Roommate spending check
    mh = next(r for r in data["roommate_series"] if r["id"] == 1)
    br = next(r for r in data["roommate_series"] if r["id"] == 2)
    mu = next(r for r in data["roommate_series"] if r["id"] == 3)

    assert mh["total_paid_centimes"] == 54900
    assert br["total_paid_centimes"] == 12000
    assert mu["total_paid_centimes"] == 0

    assert data["top_spender"] == "Mohamed"
    assert len(data["category_series"]) >= 3  # groceries, food, utilities
    assert len(data["daily_series"]) > 0
    assert len(data["weekly_series"]) >= 2
    assert len(data["dow_series"]) == 7
    assert len(data["top_expenses"]) == 3
