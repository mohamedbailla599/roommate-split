"""Analytics and reporting computations for roommate-split.

Aggregates expenses and payments to generate daily, weekly, day-of-week,
category, and per-roommate spending distributions and metrics.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from split_logic import format_mad


CATEGORIES = [
    {
        "key": "groceries",
        "name": "Groceries & Market",
        "keywords": [
            "marjane", "carrefour", "bim", "acima", "khodra", "legume", "fruit",
            "marche", "epicerie", "supermarket", "supermarche", "alimentation",
            "courses", "lait", "pain", "oeuf", "fromage", "viande", "poulet", "boucherie"
        ],
        "color": "#10B981",  # Emerald
    },
    {
        "key": "food",
        "name": "Dining & Takeout",
        "keywords": [
            "snack", "burger", "pizza", "restaurant", "resto", "cafe", "coffee",
            "macdo", "mcdonald", "kfc", "tacos", "food", "repas", "diner", "dej",
            "dejeuner", "sandwich", "chawarma", "glovo", "koutoubia"
        ],
        "color": "#F59E0B",  # Amber
    },
    {
        "key": "utilities",
        "name": "Utilities & Internet",
        "keywords": [
            "wifi", "internet", "inwi", "iam", "orange", "fibre", "fiber", "eau",
            "elec", "electricite", "lydec", "ameedis", "redevance", "facture", "gaz", "bouteille"
        ],
        "color": "#6366F1",  # Indigo
    },
    {
        "key": "home",
        "name": "Home & Cleaning",
        "keywords": [
            "menage", "nettoyage", "javel", "savon", "papier", "detergent",
            "cleaning", "sacs", "poubelle", "mouchoir", "produits", "bricolage", "ampoule"
        ],
        "color": "#EC4899",  # Pink
    },
    {
        "key": "transport",
        "name": "Transport & Travel",
        "keywords": [
            "taxi", "essence", "carburant", "gazole", "diesel", "indrive", "careem",
            "tram", "tramway", "train", "oncf", "bus", "parking", "autoroute", "peage"
        ],
        "color": "#0EA5E9",  # Sky
    },
    {
        "key": "general",
        "name": "Other & General",
        "keywords": [],
        "color": "#8B5CF6",  # Violet
    },
]


def categorize_expense(label: str) -> Dict[str, Any]:
    """Matches an expense description against keyword dictionaries."""
    lower_label = label.lower()
    for cat in CATEGORIES[:-1]:  # check all except 'general'
        for kw in cat["keywords"]:
            if kw in lower_label:
                return cat
    return CATEGORIES[-1]


def compute_reports_data(
    expenses: List[Dict[str, Any]],
    roommate_map: Dict[int, Dict[str, Any]],
    payments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Computes comprehensive metrics and chart datasets from expenses and payments.

    Returns:
        Dict containing summary KPIs, daily timeline, weekly timeline,
        day-of-week breakdown, category breakdown, roommate spending & share breakdown,
        and top expenses.
    """
    payments = payments or []
    total_spent_centimes = sum(e["amount_centimes"] for e in expenses)
    expense_count = len(expenses)
    payment_count = len(payments)
    total_payments_centimes = sum(p["amount_centimes"] for p in payments)

    if expense_count == 0:
        return {
            "has_data": False,
            "total_spent_centimes": 0,
            "total_spent_formatted": format_mad(0),
            "expense_count": 0,
            "payment_count": payment_count,
            "total_payments_centimes": total_payments_centimes,
            "daily_avg_formatted": format_mad(0),
            "weekly_avg_formatted": format_mad(0),
            "top_spender": None,
            "daily_series": [],
            "weekly_series": [],
            "dow_series": [],
            "category_series": [],
            "roommate_series": [],
            "top_expenses": [],
        }

    # Date range and daily grouping
    daily_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for exp in expenses:
        daily_groups[exp["date"]].append(exp)

    sorted_dates = sorted(daily_groups.keys())
    first_date_str = sorted_dates[0]
    last_date_str = sorted_dates[-1]

    try:
        start_d = datetime.strptime(first_date_str, "%Y-%m-%d").date()
        end_d = datetime.strptime(last_date_str, "%Y-%m-%d").date()
        days_span = max(1, (end_d - start_d).days + 1)
    except ValueError:
        days_span = max(1, len(sorted_dates))

    daily_avg_centimes = total_spent_centimes // days_span
    weekly_avg_centimes = int(daily_avg_centimes * 7)

    # 1. Daily timeline series (show all active dates or filled continuous range up to 30 days)
    # If span is reasonable (<= 45 days), fill missing days with 0 for smooth charts
    daily_series = []
    if days_span <= 45:
        cur_d = start_d
        while cur_d <= end_d:
            d_str = cur_d.isoformat()
            day_exps = daily_groups.get(d_str, [])
            day_total = sum(e["amount_centimes"] for e in day_exps)
            daily_series.append({
                "date": d_str,
                "label": cur_d.strftime("%d %b"),
                "short_label": cur_d.strftime("%d"),
                "weekday": cur_d.strftime("%a"),
                "total_centimes": day_total,
                "formatted": format_mad(day_total),
                "count": len(day_exps),
            })
            cur_d += timedelta(days=1)
    else:
        # Long span: only output days with activity
        for d_str in sorted_dates:
            day_exps = daily_groups[d_str]
            day_total = sum(e["amount_centimes"] for e in day_exps)
            try:
                parsed_d = datetime.strptime(d_str, "%Y-%m-%d").date()
                label = parsed_d.strftime("%d %b")
                short_label = parsed_d.strftime("%d")
                weekday = parsed_d.strftime("%a")
            except ValueError:
                label = d_str
                short_label = d_str
                weekday = ""
            daily_series.append({
                "date": d_str,
                "label": label,
                "short_label": short_label,
                "weekday": weekday,
                "total_centimes": day_total,
                "formatted": format_mad(day_total),
                "count": len(day_exps),
            })

    max_daily = max((item["total_centimes"] for item in daily_series), default=1)
    for item in daily_series:
        item["pct_of_max"] = round((item["total_centimes"] / max_daily) * 100, 1) if max_daily > 0 else 0

    # 2. Weekly series
    weekly_groups: Dict[str, Dict[str, Any]] = {}
    for exp in expenses:
        try:
            exp_d = datetime.strptime(exp["date"], "%Y-%m-%d").date()
            # ISO year and week
            iso_year, iso_week, _ = exp_d.isocalendar()
            week_key = f"{iso_year}-W{iso_week:02d}"
            # Calculate Monday of that week
            monday = exp_d - timedelta(days=exp_d.weekday())
            sunday = monday + timedelta(days=6)
            week_label = f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b')}"
        except ValueError:
            week_key = "Unknown"
            week_label = "Other"

        if week_key not in weekly_groups:
            weekly_groups[week_key] = {
                "week_key": week_key,
                "label": week_label,
                "total_centimes": 0,
                "count": 0,
            }
        weekly_groups[week_key]["total_centimes"] += exp["amount_centimes"]
        weekly_groups[week_key]["count"] += 1

    weekly_series = [weekly_groups[k] for k in sorted(weekly_groups.keys())]
    max_weekly = max((w["total_centimes"] for w in weekly_series), default=1)
    for w in weekly_series:
        w["formatted"] = format_mad(w["total_centimes"])
        w["pct_of_max"] = round((w["total_centimes"] / max_weekly) * 100, 1) if max_weekly > 0 else 0

    # 3. Day of week breakdown (Monday=0 to Sunday=6)
    dow_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_shorts = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_totals = [0] * 7
    dow_counts = [0] * 7

    for exp in expenses:
        try:
            exp_d = datetime.strptime(exp["date"], "%Y-%m-%d").date()
            dow_idx = exp_d.weekday()
            dow_totals[dow_idx] += exp["amount_centimes"]
            dow_counts[dow_idx] += 1
        except ValueError:
            pass

    max_dow = max(dow_totals) if max(dow_totals) > 0 else 1
    dow_series = []
    peak_dow_idx = 0
    peak_dow_amount = -1
    for i in range(7):
        pct_of_total = round((dow_totals[i] / total_spent_centimes) * 100, 1) if total_spent_centimes > 0 else 0
        pct_of_max = round((dow_totals[i] / max_dow) * 100, 1)
        if dow_totals[i] > peak_dow_amount:
            peak_dow_amount = dow_totals[i]
            peak_dow_idx = i
        dow_series.append({
            "name": dow_names[i],
            "short_name": dow_shorts[i],
            "total_centimes": dow_totals[i],
            "formatted": format_mad(dow_totals[i]),
            "count": dow_counts[i],
            "pct_of_total": pct_of_total,
            "pct_of_max": pct_of_max,
            "is_peak": False,
        })
    if peak_dow_amount > 0:
        dow_series[peak_dow_idx]["is_peak"] = True

    # 4. Category breakdown
    cat_totals: Dict[str, int] = defaultdict(int)
    cat_counts: Dict[str, int] = defaultdict(int)
    for exp in expenses:
        cat = categorize_expense(exp.get("label", ""))
        cat_totals[cat["key"]] += exp["amount_centimes"]
        cat_counts[cat["key"]] += 1

    category_series = []
    for cat in CATEGORIES:
        amt = cat_totals[cat["key"]]
        cnt = cat_counts[cat["key"]]
        if amt > 0 or cnt > 0:
            pct = round((amt / total_spent_centimes) * 100, 1) if total_spent_centimes > 0 else 0
            category_series.append({
                "key": cat["key"],
                "name": cat["name"],
                "color": cat["color"],
                "total_centimes": amt,
                "formatted": format_mad(amt),
                "count": cnt,
                "pct": pct,
            })
    category_series.sort(key=lambda c: c["total_centimes"], reverse=True)

    # 5. Roommate spending (Who paid) and share (Who consumed)
    roommate_paid: Dict[int, int] = defaultdict(int)
    roommate_paid_count: Dict[int, int] = defaultdict(int)
    roommate_share: Dict[int, int] = defaultdict(int)

    for exp in expenses:
        roommate_paid[exp["paid_by_id"]] += exp["amount_centimes"]
        roommate_paid_count[exp["paid_by_id"]] += 1
        shares = exp.get("shares", {})
        for rid, share_amt in shares.items():
            roommate_share[rid] += share_amt

    roommate_series = []
    top_spender_name = None
    top_spender_amt = -1

    for rid, rdata in roommate_map.items():
        paid = roommate_paid[rid]
        share = roommate_share[rid]
        cnt = roommate_paid_count[rid]
        net = paid - share

        if paid > top_spender_amt:
            top_spender_amt = paid
            top_spender_name = rdata["name"]

        paid_pct = round((paid / total_spent_centimes) * 100, 1) if total_spent_centimes > 0 else 0
        share_pct = round((share / total_spent_centimes) * 100, 1) if total_spent_centimes > 0 else 0

        roommate_series.append({
            "id": rid,
            "name": rdata["name"],
            "initials": rdata.get("initials", rdata["name"][:2].upper()),
            "gradient": rdata.get("gradient", ""),
            "total_paid_centimes": paid,
            "total_paid_formatted": format_mad(paid),
            "paid_pct": paid_pct,
            "total_share_centimes": share,
            "total_share_formatted": format_mad(share),
            "share_pct": share_pct,
            "net_centimes": net,
            "net_formatted": format_mad(net),
            "expense_count": cnt,
        })

    # Sort roommate series by total paid descending
    roommate_series.sort(key=lambda r: r["total_paid_centimes"], reverse=True)

    # Calculate Donut Chart SVG stroke offsets
    # Circumference for radius 40: 2 * pi * 40 = 251.327
    circ = 251.327
    accum_paid_pct = 0.0
    for r in roommate_series:
        pct = r["paid_pct"]
        dash = (pct / 100.0) * circ
        offset = -(accum_paid_pct / 100.0) * circ
        r["donut_dash"] = f"{dash:.2f} {circ:.2f}"
        r["donut_offset"] = f"{offset:.2f}"
        accum_paid_pct += pct

    # 6. Top 5 Largest Expenses
    top_expenses = sorted(expenses, key=lambda e: e["amount_centimes"], reverse=True)[:5]
    top_expenses_formatted = []
    for exp in top_expenses:
        payer = roommate_map.get(exp["paid_by_id"], {})
        top_expenses_formatted.append({
            "id": exp["id"],
            "label": exp["label"],
            "date": exp["date"],
            "amount_centimes": exp["amount_centimes"],
            "amount_formatted": format_mad(exp["amount_centimes"]),
            "payer_name": payer.get("name", "Unknown"),
            "payer_initials": payer.get("initials", "?"),
            "payer_gradient": payer.get("gradient", ""),
            "participants_count": len(exp.get("participants", [])),
        })

    return {
        "has_data": True,
        "total_spent_centimes": total_spent_centimes,
        "total_spent_formatted": format_mad(total_spent_centimes),
        "expense_count": expense_count,
        "payment_count": payment_count,
        "total_payments_centimes": total_payments_centimes,
        "total_payments_formatted": format_mad(total_payments_centimes),
        "days_span": days_span,
        "start_date": first_date_str,
        "end_date": last_date_str,
        "daily_avg_centimes": daily_avg_centimes,
        "daily_avg_formatted": format_mad(daily_avg_centimes),
        "weekly_avg_centimes": weekly_avg_centimes,
        "weekly_avg_formatted": format_mad(weekly_avg_centimes),
        "top_spender": top_spender_name if top_spender_amt > 0 else None,
        "peak_dow": dow_names[peak_dow_idx] if peak_dow_amount > 0 else None,
        "daily_series": daily_series,
        "weekly_series": weekly_series,
        "dow_series": dow_series,
        "category_series": category_series,
        "roommate_series": roommate_series,
        "top_expenses": top_expenses_formatted,
    }
