"""Unit tests for split_logic.py.

Covers:
- Uneven splits with remainders
- 1 centime among 3 people
- Subset of participants
- Payer who is not a participant
- Three or more people with chained debts
- Everyone already even
- Net balances sum to 0
- Applying returned transfers brings every balance to 0
- Scenario with 2+ creditors and 2+ debtors
- Comma input handling
- Rejecting float, zero, negative, and invalid amounts
- Currency formatting
"""

import pytest
from split_logic import (
    calculate_balances,
    format_mad,
    settle_debts,
    split_expense,
    to_centimes,
)


class TestToCentimes:
    def test_valid_string_with_period(self):
        assert to_centimes("120.50") == 12050
        assert to_centimes("10.05") == 1005
        assert to_centimes("5") == 500

    def test_valid_string_with_comma(self):
        assert to_centimes("120,50") == 12050
        assert to_centimes("0,75") == 75
        assert to_centimes(" 49,99 ") == 4999

    def test_valid_integer(self):
        assert to_centimes(100) == 10000
        assert to_centimes(1) == 100

    def test_reject_float(self):
        with pytest.raises(TypeError, match="Float amounts are not permitted"):
            to_centimes(120.50)
        with pytest.raises(TypeError, match="Float amounts are not permitted"):
            to_centimes(0.01)

    def test_reject_zero(self):
        with pytest.raises(ValueError, match="Amount must be positive"):
            to_centimes("0")
        with pytest.raises(ValueError, match="Amount must be positive"):
            to_centimes("0.00")
        with pytest.raises(ValueError, match="Amount must be positive"):
            to_centimes(0)

    def test_reject_negative(self):
        with pytest.raises(ValueError, match="Amount must be positive"):
            to_centimes("-10.00")
        with pytest.raises(ValueError, match="Amount must be positive"):
            to_centimes("-5")
        with pytest.raises(ValueError, match="Amount must be positive"):
            to_centimes(-5)

    def test_reject_more_than_two_decimal_places(self):
        with pytest.raises(ValueError, match="more than 2 decimal places"):
            to_centimes("12.345")
        with pytest.raises(ValueError, match="more than 2 decimal places"):
            to_centimes("0,001")

    def test_reject_invalid_strings(self):
        with pytest.raises(ValueError):
            to_centimes("")
        with pytest.raises(ValueError):
            to_centimes("abc")
        with pytest.raises(TypeError):
            to_centimes(None)


class TestFormatMad:
    def test_format_positive(self):
        assert format_mad(12050) == "120.50 MAD"
        assert format_mad(5) == "0.05 MAD"
        assert format_mad(100) == "1.00 MAD"

    def test_format_zero(self):
        assert format_mad(0) == "0.00 MAD"

    def test_format_negative(self):
        assert format_mad(-12050) == "-120.50 MAD"
        assert format_mad(-50) == "-0.50 MAD"


class TestSplitExpense:
    def test_even_split(self):
        shares = split_expense(3000, [1, 2, 3])
        assert shares == {1: 1000, 2: 1000, 3: 1000}
        assert sum(shares.values()) == 3000

    def test_uneven_split_with_remainders(self):
        # 100.00 MAD = 10000 centimes among 3 people
        # 10000 = 3333 * 3 + 1 -> sorted participants [1, 2, 3]
        # participant 1 gets 3334, 2 gets 3333, 3 gets 3333
        shares = split_expense(10000, [1, 2, 3])
        assert shares[1] == 3334
        assert shares[2] == 3333
        assert shares[3] == 3333
        assert sum(shares.values()) == 10000

    def test_one_centime_among_three_people(self):
        # 1 centime among 3 people -> 1, 0, 0
        shares = split_expense(1, [1, 2, 3])
        assert shares[1] == 1
        assert shares[2] == 0
        assert shares[3] == 0
        assert sum(shares.values()) == 1

    def test_deterministic_regardless_of_input_order(self):
        shares1 = split_expense(100, [3, 1, 2])
        shares2 = split_expense(100, [1, 2, 3])
        assert shares1 == shares2

    def test_single_participant(self):
        shares = split_expense(1550, [1])
        assert shares == {1: 1550}

    def test_empty_participants_raises_error(self):
        with pytest.raises(ValueError, match="At least one participant is required"):
            split_expense(1000, [])

    def test_negative_or_zero_amount_raises_error(self):
        with pytest.raises(ValueError, match="Expense amount must be positive"):
            split_expense(0, [1, 2])
        with pytest.raises(ValueError, match="Expense amount must be positive"):
            split_expense(-100, [1, 2])


class TestCalculateBalances:
    def test_net_balances_sum_to_zero(self):
        roommates = [1, 2, 3, 4]
        expenses = [
            {"paid_by_id": 1, "amount_centimes": 10000, "participants": [1, 2, 3, 4]},
            {"paid_by_id": 2, "amount_centimes": 5000, "participants": [2, 3]},
            {"paid_by_id": 4, "amount_centimes": 2350, "participants": [1, 4]},
        ]
        balances = calculate_balances(roommates, expenses)
        total_net = sum(b["net_balance"] for b in balances.values())
        assert total_net == 0

    def test_subset_of_participants(self):
        roommates = [1, 2, 3, 4]
        # Only roommates 1 and 2 share the expense of 2000 centimes paid by 1
        expenses = [
            {"paid_by_id": 1, "amount_centimes": 2000, "participants": [1, 2]}
        ]
        balances = calculate_balances(roommates, expenses)
        assert balances[1]["total_paid"] == 2000
        assert balances[1]["total_share"] == 1000
        assert balances[1]["net_balance"] == 1000  # Creditor: gets 10.00 MAD

        assert balances[2]["total_paid"] == 0
        assert balances[2]["total_share"] == 1000
        assert balances[2]["net_balance"] == -1000  # Debtor: owes 10.00 MAD

        assert balances[3]["net_balance"] == 0
        assert balances[4]["net_balance"] == 0

    def test_payer_who_is_not_a_participant(self):
        roommates = [1, 2, 3]
        # Roommate 1 pays 3000 centimes for 2 and 3 only (e.g. food takeout for them)
        expenses = [
            {"paid_by_id": 1, "amount_centimes": 3000, "participants": [2, 3]}
        ]
        balances = calculate_balances(roommates, expenses)
        assert balances[1]["total_paid"] == 3000
        assert balances[1]["total_share"] == 0
        assert balances[1]["net_balance"] == 3000  # Gets full 3000 back

        assert balances[2]["total_paid"] == 0
        assert balances[2]["total_share"] == 1500
        assert balances[2]["net_balance"] == -1500

        assert balances[3]["total_paid"] == 0
        assert balances[3]["total_share"] == 1500
        assert balances[3]["net_balance"] == -1500

    def test_partial_payment_reduces_debt(self):
        # 1 paid 3000 centimes for 1, 2, 3 (1000 each)
        # Balances: 1: +2000, 2: -1000, 3: -1000
        # 2 gives partial payment of 400 centimes to 1
        roommates = [1, 2, 3]
        expenses = [{"paid_by_id": 1, "amount_centimes": 3000, "participants": [1, 2, 3]}]
        payments = [{"from_id": 2, "to_id": 1, "amount_centimes": 400}]
        balances = calculate_balances(roommates, expenses, payments)

        assert balances[2]["net_balance"] == -600  # Owes only 6.00 MAD now
        assert balances[1]["net_balance"] == 1600  # Gets back 16.00 MAD
        assert balances[3]["net_balance"] == -1000  # Still owes 10.00 MAD
        assert sum(b["net_balance"] for b in balances.values()) == 0

    def test_full_payment_clears_single_roommate(self):
        # 2 pays full 1000 centimes to 1, while 3 has not paid yet
        roommates = [1, 2, 3]
        expenses = [{"paid_by_id": 1, "amount_centimes": 3000, "participants": [1, 2, 3]}]
        payments = [{"from_id": 2, "to_id": 1, "amount_centimes": 1000}]
        balances = calculate_balances(roommates, expenses, payments)

        assert balances[2]["net_balance"] == 0  # 2 is completely settled!
        assert balances[1]["net_balance"] == 1000  # 1 is now only owed by 3
        assert balances[3]["net_balance"] == -1000  # 3 still owes full 1000

        # Transfers should only show 3 pays 1
        transfers = settle_debts({rid: b["net_balance"] for rid, b in balances.items()})
        assert len(transfers) == 1
        assert transfers[0] == {"from_id": 3, "to_id": 1, "amount_centimes": 1000}


class TestSettleDebts:
    def test_everyone_already_even(self):
        net_balances = {1: 0, 2: 0, 3: 0}
        transfers = settle_debts(net_balances)
        assert transfers == []

    def test_chained_debts(self):
        # A owes B 50 MAD (-5000), B owes C 50 MAD (B net = 0), C is owed 50 MAD (+5000)
        net_balances = {"A": -5000, "B": 0, "C": 5000}
        transfers = settle_debts(net_balances)
        # Settle up resolves directly: A pays C 50 MAD
        assert len(transfers) == 1
        assert transfers[0] == {"from_id": "A", "to_id": "C", "amount_centimes": 5000}

    def test_scenario_with_multiple_creditors_and_debtors(self):
        # 2 debtors, 2 creditors:
        # A: -6000 (owes 60 MAD)
        # B: -4000 (owes 40 MAD)
        # C: +7000 (gets 70 MAD)
        # D: +3000 (gets 30 MAD)
        net_balances = {"A": -6000, "B": -4000, "C": 7000, "D": 3000}
        transfers = settle_debts(net_balances)

        # Check that sum of transfers equals total debt
        total_transferred = sum(t["amount_centimes"] for t in transfers)
        assert total_transferred == 10000

        # Check applying transfers brings every balance to 0
        simulated = dict(net_balances)
        for t in transfers:
            simulated[t["from_id"]] += t["amount_centimes"]
            simulated[t["to_id"]] -= t["amount_centimes"]

        for rid, bal in simulated.items():
            assert bal == 0, f"Roommate {rid} balance not 0 after settlement: {bal}"

    def test_complex_multi_roommate_balances_zeroed(self):
        # A realistic scenario with 5 roommates
        net_balances = {
            1: -12500,  # owes 125.00
            2: -3500,   # owes 35.00
            3: 8000,    # gets 80.00
            4: 7500,    # gets 75.00
            5: 500,     # gets 5.00
        }
        assert sum(net_balances.values()) == 0

        transfers = settle_debts(net_balances)
        assert len(transfers) <= 4  # Greedy settlement produces at most N-1 transfers

        # Verify all balances zero out
        simulated = dict(net_balances)
        for t in transfers:
            assert t["amount_centimes"] > 0
            simulated[t["from_id"]] += t["amount_centimes"]
            simulated[t["to_id"]] -= t["amount_centimes"]

        for rid, bal in simulated.items():
            assert bal == 0, f"Roommate {rid} balance not zero: {bal}"

    def test_invalid_net_balances_sum_raises_error(self):
        with pytest.raises(ValueError, match="Sum of net balances must be 0"):
            settle_debts({1: -100, 2: 90})
