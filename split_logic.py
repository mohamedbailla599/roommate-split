"""Pure domain logic for roommate-split.

No Flask, SQLite, or web framework imports allowed in this module.
All monetary amounts are manipulated as integer centimes.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Union


def to_centimes(val: Any) -> int:
    """Converts a monetary input in MAD to integer centimes.
    
    Accepts strings (e.g. "120.50", "120,50", "50") or integers (e.g. 100 MAD).
    Explicitly rejects floats to avoid precision loss.
    Rejects zero, negative, and invalid values.
    Accepts at most 2 decimal places.
    """
    if isinstance(val, float):
        raise TypeError("Float amounts are not permitted; provide a string or int.")
    
    if isinstance(val, int):
        if val <= 0:
            raise ValueError("Amount must be positive.")
        return val * 100

    if isinstance(val, Decimal):
        dec = val
    elif isinstance(val, str):
        cleaned = val.strip().replace(",", ".")
        if not cleaned:
            raise ValueError("Amount cannot be empty.")
        try:
            dec = Decimal(cleaned)
        except InvalidOperation:
            raise ValueError(f"Invalid amount format: {val}")
    else:
        raise TypeError(f"Unsupported type for amount: {type(val).__name__}")

    if dec <= Decimal(0):
        raise ValueError("Amount must be positive.")

    # Check for maximum 2 decimal places
    # If exponent is negative and < -2, check if extra digits are non-zero
    if dec.as_tuple().exponent < -2:
        # Check if multiplying by 100 leaves any fractional part
        if (dec * 100) % 1 != 0:
            raise ValueError("Amount cannot have more than 2 decimal places.")

    centimes = int((dec * Decimal(100)).to_integral_value())
    if centimes <= 0:
        raise ValueError("Amount must be positive.")
    return centimes


def format_mad(centimes: int) -> str:
    """Formats integer centimes into a user-facing MAD string (e.g. 12050 -> '120.50 MAD')."""
    sign = "-" if centimes < 0 else ""
    abs_c = abs(centimes)
    mad = abs_c // 100
    c = abs_c % 100
    return f"{sign}{mad}.{c:02d} MAD"


def split_expense(total_centimes: int, participant_ids: List[Union[int, str]]) -> Dict[Union[int, str], int]:
    """Splits an expense evenly among participant IDs in integer centimes.
    
    When total_centimes does not divide evenly, remainder centimes are distributed
    deterministically (+1 centime each) to participants in ascending sorted order of their ID.
    The sum of all shares is strictly equal to total_centimes.
    """
    if not isinstance(total_centimes, int):
        raise TypeError(f"total_centimes must be an integer, got {type(total_centimes).__name__}")
    if total_centimes <= 0:
        raise ValueError("Expense amount must be positive.")
    if not participant_ids:
        raise ValueError("At least one participant is required.")

    # Deduplicate while sorting deterministically
    sorted_participants = sorted(list(set(participant_ids)), key=lambda x: str(x))
    n = len(sorted_participants)
    
    base_share, remainder = divmod(total_centimes, n)
    shares: Dict[Union[int, str], int] = {}

    for i, pid in enumerate(sorted_participants):
        shares[pid] = base_share + (1 if i < remainder else 0)

    # Invariant assertion
    assert sum(shares.values()) == total_centimes, "Shares must sum exactly to total_centimes"
    return shares


def calculate_balances(
    roommate_ids: List[Union[int, str]],
    expenses: List[Dict[str, Any]],
    payments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[Union[int, str], Dict[str, int]]:
    """Calculates total paid, total share, and net balance for each roommate.
    
    net_balance = total_paid - total_share.
    Positive net balance means the roommate is owed money (creditor).
    Negative net balance means the roommate owes money (debtor).
    
    Each expense dict should have:
      - 'paid_by_id': ID of payer
      - 'amount_centimes': total expense amount
      - 'shares': dict of {participant_id: share_centimes} (or 'participants' list to compute shares)

    Each payment dict should have:
      - 'from_id' (or 'from_roommate_id'): ID of roommate who made payment
      - 'to_id' (or 'to_roommate_id'): ID of roommate who received payment
      - 'amount_centimes': payment amount in centimes
    """
    balances: Dict[Union[int, str], Dict[str, int]] = {
        rid: {
            "total_paid": 0,
            "total_share": 0,
            "net_balance": 0,
            "expenses_paid": 0,
            "expenses_share": 0,
            "payments_made": 0,
            "payments_received": 0,
        }
        for rid in roommate_ids
    }

    for exp in expenses:
        payer_id = exp["paid_by_id"]
        amount = exp["amount_centimes"]

        if payer_id not in balances:
            balances[payer_id] = {
                "total_paid": 0,
                "total_share": 0,
                "net_balance": 0,
                "expenses_paid": 0,
                "expenses_share": 0,
                "payments_made": 0,
                "payments_received": 0,
            }
        balances[payer_id]["expenses_paid"] += amount
        balances[payer_id]["total_paid"] += amount

        shares = exp.get("shares")
        if shares is None:
            participants = exp.get("participants", [])
            shares = split_expense(amount, participants)

        for pid, share in shares.items():
            if pid not in balances:
                balances[pid] = {
                    "total_paid": 0,
                    "total_share": 0,
                    "net_balance": 0,
                    "expenses_paid": 0,
                    "expenses_share": 0,
                    "payments_made": 0,
                    "payments_received": 0,
                }
            balances[pid]["expenses_share"] += share
            balances[pid]["total_share"] += share

    if payments:
        for p in payments:
            from_id = p.get("from_id") if p.get("from_id") is not None else p.get("from_roommate_id")
            to_id = p.get("to_id") if p.get("to_id") is not None else p.get("to_roommate_id")
            p_amount = p["amount_centimes"]

            if from_id not in balances:
                balances[from_id] = {
                    "total_paid": 0,
                    "total_share": 0,
                    "net_balance": 0,
                    "expenses_paid": 0,
                    "expenses_share": 0,
                    "payments_made": 0,
                    "payments_received": 0,
                }
            if to_id not in balances:
                balances[to_id] = {
                    "total_paid": 0,
                    "total_share": 0,
                    "net_balance": 0,
                    "expenses_paid": 0,
                    "expenses_share": 0,
                    "payments_made": 0,
                    "payments_received": 0,
                }

            balances[from_id]["payments_made"] += p_amount
            balances[from_id]["total_paid"] += p_amount

            balances[to_id]["payments_received"] += p_amount
            balances[to_id]["total_share"] += p_amount

    for rid, data in balances.items():
        data["net_balance"] = data["total_paid"] - data["total_share"]

    return balances


def settle_debts(net_balances: Dict[Union[int, str], int]) -> List[Dict[str, Any]]:
    """Computes the minimal transfer list to settle all debts using greedy matching.
    
    Matches the largest debtor with the largest creditor iteratively.
    Returns a list of transfers:
    [
        {"from_id": debtor_id, "to_id": creditor_id, "amount_centimes": amount}
    ]
    """
    total_net = sum(net_balances.values())
    if total_net != 0:
        raise ValueError(f"Sum of net balances must be 0, got {total_net}")

    # Debtors have net_balance < 0; debt amount is -net_balance
    debtors = [
        [rid, -bal]
        for rid, bal in net_balances.items()
        if bal < 0
    ]
    # Creditors have net_balance > 0; credit amount is net_balance
    creditors = [
        [rid, bal]
        for rid, bal in net_balances.items()
        if bal > 0
    ]

    # Sort deterministically: highest amount first, then by string representation of ID
    debtors.sort(key=lambda x: (x[1], str(x[0])), reverse=True)
    creditors.sort(key=lambda x: (x[1], str(x[0])), reverse=True)

    transfers: List[Dict[str, Any]] = []
    d_idx = 0
    c_idx = 0

    while d_idx < len(debtors) and c_idx < len(creditors):
        debtor = debtors[d_idx]
        creditor = creditors[c_idx]

        debt_amount = debtor[1]
        credit_amount = creditor[1]

        if debt_amount == 0:
            d_idx += 1
            continue
        if credit_amount == 0:
            c_idx += 1
            continue

        transfer_amount = min(debt_amount, credit_amount)
        transfers.append({
            "from_id": debtor[0],
            "to_id": creditor[0],
            "amount_centimes": transfer_amount,
        })

        debtor[1] -= transfer_amount
        creditor[1] -= transfer_amount

        if debtor[1] == 0:
            d_idx += 1
        if creditor[1] == 0:
            c_idx += 1

    return transfers
