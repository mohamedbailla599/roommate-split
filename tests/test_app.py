"""Integration tests for roommate-split Flask application."""

import io
import os
import tempfile
import pytest

from app import app
from db import init_db, get_connection


@pytest.fixture
def client():
    # Use a temporary database for isolation during test execution
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    
    old_db_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = db_path
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-key"

    with app.app_context():
        init_db(db_path)

    with app.test_client() as client:
        yield client

    if old_db_path:
        os.environ["DATABASE_PATH"] = old_db_path
    else:
        os.environ.pop("DATABASE_PATH", None)

    if os.path.exists(db_path):
        os.remove(db_path)


def test_homepage_redirects_to_expenses(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/expenses" in response.headers["Location"]


def test_add_and_rename_roommates(client):
    # Add roommate
    res = client.post("/roommates/add", data={"name": "Youssef"}, follow_redirects=True)
    assert res.status_code == 200
    assert b"Youssef" in res.data
    assert b"added successfully" in res.data

    # Add second roommate
    client.post("/roommates/add", data={"name": "Amina"}, follow_redirects=True)

    # Rename Youssef to Youssef B.
    res_rename = client.post("/roommates/1/rename", data={"name": "Youssef B."}, follow_redirects=True)
    assert res_rename.status_code == 200
    assert b"Youssef B." in res_rename.data
    assert b"renamed to" in res_rename.data


def test_delete_roommate(client):
    # Add a roommate
    client.post("/roommates/add", data={"name": "Temporary Roommate"})
    res = client.get("/roommates")
    assert b"Temporary Roommate" in res.data

    # Delete the roommate (no expenses associated)
    res_del = client.post("/roommates/1/delete", follow_redirects=True)
    assert res_del.status_code == 200
    assert b"deleted successfully" in res_del.data

    # Verify roommate is removed from the table on subsequent request
    res_after = client.get("/roommates")
    assert b"Temporary Roommate" not in res_after.data


def test_delete_roommate_blocked_with_expenses(client):
    client.post("/roommates/add", data={"name": "Mohamed"})
    client.post("/roommates/add", data={"name": "Brahim"})

    client.post("/expenses/add", data={
        "label": "Groceries",
        "amount": "50.00",
        "date": "2026-11-20",
        "paid_by_id": "1",
        "participants": ["1", "2"],
    })

    # Attempting to delete Mohamed (payer) must be blocked
    res = client.post("/roommates/1/delete", follow_redirects=True)
    assert b"Cannot delete" in res.data
    assert b"Mohamed" in res.data
    assert b"associated expenses" in res.data


def test_add_expense_with_comma_and_dot(client):
    client.post("/roommates/add", data={"name": "Youssef"})
    client.post("/roommates/add", data={"name": "Amina"})

    # Add expense with comma decimal separator
    res1 = client.post("/expenses/add", data={
        "label": "Groceries",
        "amount": "120,50",
        "date": "2026-11-20",
        "paid_by_id": "1",
        "participants": ["1", "2"],
    }, follow_redirects=True)
    assert res1.status_code == 200
    assert b"120.50 MAD" in res1.data

    # Add expense with dot separator
    res2 = client.post("/expenses/add", data={
        "label": "Cleaning supplies",
        "amount": "40.00",
        "date": "2026-11-20",
        "paid_by_id": "2",
        "participants": ["1", "2"],
    }, follow_redirects=True)
    assert res2.status_code == 200
    assert b"40.00 MAD" in res2.data


def test_payer_automatically_included_in_split(client):
    client.post("/roommates/add", data={"name": "Youssef"})
    client.post("/roommates/add", data={"name": "Mehdi"})
    client.post("/roommates/add", data={"name": "Salma"})

    # Youssef (id 1) pays, but user only selected Mehdi (id 2) and Salma (id 3)
    res = client.post("/expenses/add", data={
        "label": "khodra",
        "amount": "56.00",
        "date": "2026-11-19",
        "paid_by_id": "1",
        "participants": ["2", "3"],  # Note: payer '1' not included in form selection
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b"khodra" in res.data
    # Must be split between all 3 people: Youssef, Mehdi, Salma
    assert b"Split between 3 people" in res.data
    assert b"18.67 MAD" in res.data or b"18.66 MAD" in res.data


def test_block_deactivating_roommate_with_nonzero_balance(client):
    client.post("/roommates/add", data={"name": "Youssef"})
    client.post("/roommates/add", data={"name": "Amina"})

    # Add expense so Youssef is owed and Amina owes
    client.post("/expenses/add", data={
        "label": "Groceries",
        "amount": "100.00",
        "date": "2026-11-20",
        "paid_by_id": "1",
        "participants": ["1", "2"],
    })

    # Try to deactivate Youssef (creditor)
    res_y = client.post("/roommates/1/toggle-status", follow_redirects=True)
    assert b"Cannot deactivate Youssef" in res_y.data
    assert b"unsettled balance" in res_y.data

    # Try to deactivate Amina (debtor)
    res_a = client.post("/roommates/2/toggle-status", follow_redirects=True)
    assert b"Cannot deactivate Amina" in res_a.data
    assert b"unsettled balance" in res_a.data

    # Settle up
    client.post("/settle-up")

    # Now that balances are zeroed, deactivation must succeed
    res_success = client.post("/roommates/2/toggle-status", follow_redirects=True)
    assert b"has been deactivated" in res_success.data


def test_refuse_settle_up_when_no_expenses(client):
    client.post("/roommates/add", data={"name": "Youssef"})
    client.post("/roommates/add", data={"name": "Amina"})

    # No expenses recorded yet
    res = client.post("/settle-up", follow_redirects=True)
    assert res.status_code == 200
    assert b"There are no active expenses in the current period to settle" in res.data


def test_settle_up_archives_and_makes_expenses_readonly(client):
    client.post("/roommates/add", data={"name": "Youssef"})
    client.post("/roommates/add", data={"name": "Amina"})

    # Add expense
    client.post("/expenses/add", data={
        "label": "Dinner",
        "amount": "80.00",
        "date": "2026-11-20",
        "paid_by_id": "1",
        "participants": ["1", "2"],
    })

    # Balances page shows 1 transfer: Amina pays Youssef 40.00 MAD
    res_bal = client.get("/balances")
    assert b"Amina" in res_bal.data
    assert b"Youssef" in res_bal.data
    assert b"40.00 MAD" in res_bal.data

    # Perform Settle-Up
    res_settle = client.post("/settle-up", follow_redirects=True)
    assert b"successfully settled and archived" in res_settle.data

    # Active expenses should now be empty
    res_exp = client.get("/expenses")
    assert b"No expenses recorded yet" in res_exp.data

    # Attempt to edit archived expense must be refused
    res_edit = client.get("/expenses/1/edit", follow_redirects=True)
    assert b"Settled expenses are archived and read-only" in res_edit.data

    # Attempt to delete archived expense must be refused
    res_del = client.post("/expenses/1/delete", follow_redirects=True)
    assert b"Settled expenses are archived and read-only" in res_del.data

    # History page shows the settlement and transfer record
    res_hist = client.get("/history")
    assert b"Settlement #1" in res_hist.data
    assert b"40.00 MAD" in res_hist.data
    assert b"Dinner" in res_hist.data


def test_export_csv(client):
    client.post("/roommates/add", data={"name": "Youssef"})
    client.post("/roommates/add", data={"name": "Amina"})

    client.post("/expenses/add", data={
        "label": "Supermarket",
        "amount": "65.50",
        "date": "2026-11-20",
        "paid_by_id": "1",
        "participants": ["1", "2"],
    })

    res = client.get("/expenses/export.csv")
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    assert "attachment; filename=" in res.headers["Content-Disposition"]
    
    csv_content = res.data.decode("utf-8")
    assert "Supermarket" in csv_content
    assert "65.50" in csv_content
    assert "Youssef" in csv_content


def test_record_partial_and_full_payment_flow(client):
    # Setup 3 roommates
    client.post("/roommates/add", data={"name": "Mohamed"})
    client.post("/roommates/add", data={"name": "Brahim"})
    client.post("/roommates/add", data={"name": "Mouad"})

    # Mohamed pays 23.00 MAD for all 3
    client.post("/expenses/add", data={
        "label": "Groceries",
        "amount": "23.00",
        "date": "2026-11-20",
        "paid_by_id": "1",
        "participants": ["1", "2", "3"],
    })

    # Check initial balances on /balances
    res_bal1 = client.get("/balances")
    assert b"15.33 MAD" in res_bal1.data   # Mohamed gets back 15.33
    assert b"-7.67 MAD" in res_bal1.data   # Brahim owes 7.67
    assert b"-7.66 MAD" in res_bal1.data   # Mouad owes 7.66

    # Brahim gives a partial payment of 5.00 MAD to Mohamed
    res_pay = client.post("/payments/add", data={
        "from_roommate_id": "2",
        "to_roommate_id": "1",
        "amount": "5.00",
        "date": "2026-11-20",
        "notes": "Cash partial payment",
    }, follow_redirects=True)
    assert res_pay.status_code == 200

    # Check updated balances
    res_bal2 = client.get("/balances")
    assert b"10.33 MAD" in res_bal2.data   # Mohamed gets back 10.33
    assert b"-2.67 MAD" in res_bal2.data   # Brahim now only owes 2.67!
    assert b"-7.66 MAD" in res_bal2.data   # Mouad still owes 7.66 (untouched)

    # Brahim gives the remaining 2.67 MAD to Mohamed
    client.post("/payments/add", data={
        "from_roommate_id": "2",
        "to_roommate_id": "1",
        "amount": "2.67",
        "date": "2026-11-20",
        "notes": "Final payment",
    }, follow_redirects=True)

    # Check that Brahim is now fully settled (0.00 MAD) and only Mouad owes Mohamed
    res_bal3 = client.get("/balances")
    assert b"0.00 MAD" in res_bal3.data    # Brahim is even
    assert b"7.66 MAD" in res_bal3.data    # Mohamed gets back 7.66, Mouad owes 7.66

    # In expenses feed, payments appear with delete buttons
    res_exp = client.get("/expenses")
    assert b"Payment: Brahim" in res_exp.data
    assert b"Mohamed" in res_exp.data


def test_reports_page_empty(client):
    res = client.get("/reports")
    assert res.status_code == 200
    assert b"Spending Reports" in res.data
    assert b"No Spending Data Found" in res.data


def test_reports_page_with_expenses_and_filtering(client):
    # Setup roommates
    client.post("/roommates/add", data={"name": "Mohamed"})
    client.post("/roommates/add", data={"name": "Brahim"})
    client.post("/roommates/add", data={"name": "Mouad"})

    # Add expenses
    client.post("/expenses/add", data={
        "label": "Marjane Groceries",
        "amount": "300.00",
        "date": "2026-11-15",
        "paid_by_id": "1",
        "participants": ["1", "2", "3"],
    })
    client.post("/expenses/add", data={
        "label": "Tacos Snack",
        "amount": "90.00",
        "date": "2026-11-16",
        "paid_by_id": "2",
        "participants": ["1", "2", "3"],
    })

    # Record interim payment
    client.post("/payments/add", data={
        "from_roommate_id": "3",
        "to_roommate_id": "1",
        "amount": "50.00",
        "date": "2026-11-17",
        "notes": "Partial repayment",
    })

    # Test default /reports (current period)
    res_curr = client.get("/reports")
    assert res_curr.status_code == 200
    assert b"390,00 MAD" in res_curr.data  # Total spent
    assert b"Mohamed" in res_curr.data      # Top Spender
    assert b"Groceries" in res_curr.data    # Category
    assert b"Daily View" in res_curr.data
    assert b"Weekly View" in res_curr.data

    # Test /reports?period=all
    res_all = client.get("/reports?period=all")
    assert res_all.status_code == 200
    assert b"390,00 MAD" in res_all.data

    # Settle up
    res_settle = client.post("/settle-up", follow_redirects=True)
    assert res_settle.status_code == 200

    # After settling, current period should be empty
    res_after = client.get("/reports?period=current")
    assert res_after.status_code == 200
    assert b"No Spending Data Found" in res_after.data

    # But settlement #1 should contain the archived data
    res_s1 = client.get("/reports?period=1")
    assert res_s1.status_code == 200
    assert b"390,00 MAD" in res_s1.data

    # And /reports?period=all should also still contain it
    res_all_after = client.get("/reports?period=all")
    assert res_all_after.status_code == 200
    assert b"390,00 MAD" in res_all_after.data


def test_roommate_avatar_upload_and_remove(client):
    # Add roommate
    client.post("/roommates/add", data={"name": "Yassine"}, follow_redirects=True)

    # Try invalid file
    bad_data = {
        "avatar": (io.BytesIO(b"fake content"), "malicious.exe")
    }
    res_bad = client.post("/roommates/1/avatar", data=bad_data, content_type="multipart/form-data", follow_redirects=True)
    assert b"Invalid image type" in res_bad.data

    # Valid PNG upload
    good_data = {
        "avatar": (io.BytesIO(b"\x89PNG\r\n\x1a\nfakeimagebytes"), "my_photo.png")
    }
    res_good = client.post("/roommates/1/avatar", data=good_data, content_type="multipart/form-data", follow_redirects=True)
    assert res_good.status_code == 200
    assert b"Profile picture for Yassine updated successfully!" in res_good.data
    assert b"data:image/" in res_good.data

    # Remove avatar
    res_remove = client.post("/roommates/1/avatar/remove", follow_redirects=True)
    assert res_remove.status_code == 200
    assert b"Profile picture for Yassine removed." in res_remove.data


def test_csrf_protection_rejects_forged_requests(client):
    """Verify that CSRF protection rejects forged POST requests when active."""
    client.application.config["TESTING"] = False
    try:
        # 1. POST without any CSRF token is rejected with 400 Bad Request
        res_blocked = client.post("/roommates/add", data={"name": "Attacker"})
        assert res_blocked.status_code == 400
        assert b"CSRF token missing or invalid" in res_blocked.data

        # 2. GET generates a session CSRF token
        client.get("/roommates")
        with client.session_transaction() as sess:
            valid_token = sess.get("csrf_token")
        assert valid_token is not None

        # 3. POST with the valid session token succeeds
        res_ok = client.post(
            "/roommates/add",
            data={"name": "Legitimate", "csrf_token": valid_token},
            follow_redirects=True,
        )
        assert res_ok.status_code == 200
        assert b"Legitimate" in res_ok.data
    finally:
        client.application.config["TESTING"] = True

