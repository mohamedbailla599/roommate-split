"""Roommate Split Web Application.

Flask application tracking shared roommate expenses, computing balances,
optimizing settlement transfers, and archiving settlement periods.
"""

import base64
import csv
import io
import os
import socket
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from db import get_connection, init_db
from analytics import compute_reports_data
from split_logic import (
    calculate_balances,
    format_mad,
    settle_debts,
    split_expense,
    to_centimes,
)

app = Flask(__name__)

# Environment & Production Configuration
is_debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
is_production = (
    os.environ.get("RENDER") == "true"
    or os.environ.get("FLASK_ENV") == "production"
    or os.environ.get("ENV") == "production"
    or os.environ.get("PRODUCTION") == "true"
)

raw_secret_key = os.environ.get("SECRET_KEY")
raw_app_password = os.environ.get("APP_PASSWORD")

if is_production:
    if not raw_secret_key:
        raise RuntimeError("CRITICAL: SECRET_KEY environment variable is missing. It is required in production mode.")
    if not raw_app_password:
        raise RuntimeError("CRITICAL: APP_PASSWORD environment variable is missing. It is required in production mode.")

app.secret_key = raw_secret_key or "roommate-split-dev-secret-key-2026"
APP_PASSWORD = raw_app_password or "roommate"

app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB max upload
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = not is_debug


# -----------------------------------------------------------------------------
# Rate Limiting & Household Authentication State
# -----------------------------------------------------------------------------
_failed_login_attempts: Dict[str, List[float]] = defaultdict(list)
_failed_login_lock = threading.Lock()
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300  # 5-minute lockout


def get_client_ip() -> str:
    """Extract client IP address considering proxy headers (e.g. Render reverse proxy)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def is_login_rate_limited(ip: str) -> bool:
    """Check if the given IP address is currently locked out after repeated failed logins."""
    now = time.time()
    with _failed_login_lock:
        attempts = [t for t in _failed_login_attempts[ip] if now - t < LOGIN_LOCKOUT_SECONDS]
        _failed_login_attempts[ip] = attempts
        return len(attempts) >= MAX_FAILED_LOGIN_ATTEMPTS


def record_failed_login(ip: str) -> None:
    """Record a failed login attempt for the given IP address."""
    with _failed_login_lock:
        _failed_login_attempts[ip].append(time.time())


def clear_failed_logins(ip: str) -> None:
    """Clear failed login records after a successful login."""
    with _failed_login_lock:
        _failed_login_attempts.pop(ip, None)


def generate_csrf_token() -> str:
    """Generate or retrieve a cryptographically secure CSRF token for the session."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


@app.context_processor
def inject_csrf_token() -> Dict[str, Any]:
    """Expose csrf_token() helper to all Jinja templates."""
    return {"csrf_token": generate_csrf_token}


@app.before_request
def require_household_login() -> Optional[Response]:
    """Ensure every route except /login, /health, /favicon.ico and static files requires authentication."""
    # Allow unauthenticated access to /login, /health, /favicon.ico, and static assets
    if (
        request.endpoint in ("login", "health", "favicon", "static")
        or request.path in ("/login", "/health", "/favicon.ico")
        or request.path.startswith("/static/")
    ):
        return None

    if not session.get("authenticated"):
        next_target = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=next_target))

    return None


@app.before_request
def verify_csrf() -> None:
    """Validate CSRF token for state-changing requests (POST, PUT, DELETE, PATCH)."""
    # Bypass during test suite runs
    if app.config.get("TESTING"):
        return None

    # Safe HTTP methods do not require CSRF tokens
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return None

    submitted_token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    session_token = session.get("csrf_token")

    if not submitted_token or not session_token or not secrets.compare_digest(submitted_token, session_token):
        abort(400, description="CSRF token missing or invalid. Please refresh the page and try again.")

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_AVATARS_DIR = BASE_DIR / "static" / "uploads" / "avatars"
UPLOAD_AVATARS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


def allowed_avatar_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS

AVATAR_GRADIENTS = [
    "linear-gradient(135deg, #0C6E5E 0%, #14B8A6 100%)",   # Forest Jade
    "linear-gradient(135deg, #B45309 0%, #F59E0B 100%)",   # Artisan Amber
    "linear-gradient(135deg, #4338CA 0%, #6366F1 100%)",   # Royal Indigo
    "linear-gradient(135deg, #BE185D 0%, #EC4899 100%)",   # Rose Garnet
    "linear-gradient(135deg, #0369A1 0%, #0EA5E9 100%)",   # Cobalt Azure
    "linear-gradient(135deg, #7C2D12 0%, #EA580C 100%)",   # Rust Sienna
]


def compute_unique_initials(names: List[str]) -> Dict[str, str]:
    """Generates unique 2-letter uppercase initials for each name.
    If initials collide (e.g. Mohamed vs Mouad), finds the first character that differs.
    """
    initials_map: Dict[str, str] = {}
    for name in names:
        parts = name.strip().split()
        if len(parts) >= 2:
            init = (parts[0][0] + parts[1][0]).upper()
        elif len(name) >= 2:
            init = name[:2].upper()
        else:
            init = (name + name).upper()
        initials_map[name] = init

    counts = Counter(initials_map.values())
    colliding = {init for init, cnt in counts.items() if cnt > 1}
    for init in colliding:
        group = [name for name, i in initials_map.items() if i == init]
        for name in group:
            first = name[0].upper()
            diff_char = None
            for other in group:
                if other == name:
                    continue
                for idx in range(1, min(len(name), len(other))):
                    if name[idx].lower() != other[idx].lower():
                        diff_char = name[idx].upper()
                        break
                if diff_char:
                    break
            initials_map[name] = first + (diff_char or (name[1].upper() if len(name) > 1 else ""))

    return initials_map


@app.template_filter("mad")
def mad_filter(centimes: int) -> str:
    """Jinja filter to format centimes as MAD string."""
    return format_mad(centimes)


@app.template_filter("mad_fr")
def mad_fr_filter(centimes: int) -> str:
    """French-style money formatting: 1 250,50 MAD (thin space thousands, comma decimal)."""
    sign = "-" if centimes < 0 else ""
    abs_c = abs(centimes)
    mad = abs_c // 100
    c = abs_c % 100
    mad_str = f"{mad:,}".replace(",", " ")
    return f"{sign}{mad_str},{c:02d} MAD"


@app.template_filter("friendly_date")
def friendly_date_filter(date_str: str) -> str:
    """Formats ISO date string (YYYY-MM-DD) into a human, polished label."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = date.today()
        if d == today:
            return f"Today · {d.strftime('%d %b')}"
        elif d == today - timedelta(days=1):
            return f"Yesterday · {d.strftime('%d %b')}"
        elif d.year == today.year:
            return d.strftime("%A, %d %b")
        else:
            return d.strftime("%d %b %Y")
    except Exception:
        return date_str


def get_local_ip() -> str:
    """Attempts to find the local network IP for phone access on the same Wi-Fi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


CACHED_LOCAL_IP = get_local_ip()


@app.context_processor
def inject_ui_helpers():
    return {
        "local_ip": CACHED_LOCAL_IP,
        "server_port": int(os.environ.get("PORT", 5000)),
    }


def get_roommate_map(conn) -> Dict[int, Dict[str, Any]]:
    """Fetches all roommates and returns a map with computed initials and gradients."""
    roommates = conn.execute("SELECT * FROM roommates ORDER BY id ASC").fetchall()
    names = [r["name"] for r in roommates]
    initials_map = compute_unique_initials(names)

    roommate_map = {}
    for r in roommates:
        d = dict(r)
        d["initials"] = initials_map.get(d["name"], d["name"][:2].upper())
        d["gradient"] = AVATAR_GRADIENTS[(d["id"] - 1) % len(AVATAR_GRADIENTS)]
        roommate_map[d["id"]] = d
    return roommate_map


def get_active_period_data(conn):
    """Fetches all data needed to calculate current period balances using batched queries."""
    roommate_map = get_roommate_map(conn)

    expenses_rows = conn.execute(
        """
        SELECT e.*, r.name as paid_by_name
        FROM expenses e
        JOIN roommates r ON e.paid_by_id = r.id
        WHERE e.settlement_id IS NULL
        ORDER BY e.date DESC, e.id DESC
        """
    ).fetchall()

    # Batch fetch all participants for all active expenses in a SINGLE roundtrip
    parts_rows = conn.execute(
        """
        SELECT ep.expense_id, ep.roommate_id, ep.share_centimes, r.name
        FROM expense_participants ep
        JOIN roommates r ON ep.roommate_id = r.id
        JOIN expenses e ON ep.expense_id = e.id
        WHERE e.settlement_id IS NULL
        ORDER BY ep.expense_id, ep.roommate_id ASC
        """
    ).fetchall()

    parts_by_exp = defaultdict(list)
    shares_by_exp = defaultdict(dict)
    for p in parts_rows:
        p_dict = dict(p)
        rm = roommate_map.get(p_dict["roommate_id"])
        if rm:
            p_dict["initials"] = rm["initials"]
            p_dict["gradient"] = rm["gradient"]
            p_dict["avatar_url"] = rm.get("avatar_url")
        parts_by_exp[p["expense_id"]].append(p_dict)
        shares_by_exp[p["expense_id"]][p["roommate_id"]] = p["share_centimes"]

    expenses = []
    for exp_row in expenses_rows:
        exp_dict = dict(exp_row)
        payer = roommate_map.get(exp_dict["paid_by_id"])
        if payer:
            exp_dict["paid_by_initials"] = payer["initials"]
            exp_dict["paid_by_gradient"] = payer["gradient"]
            exp_dict["paid_by_avatar_url"] = payer.get("avatar_url")

        exp_dict["participants"] = parts_by_exp.get(exp_dict["id"], [])
        exp_dict["shares"] = shares_by_exp.get(exp_dict["id"], {})
        expenses.append(exp_dict)

    # Fetch active payments in current period
    payments_rows = conn.execute(
        """
        SELECT p.*, rf.name as from_name, rt.name as to_name
        FROM payments p
        JOIN roommates rf ON p.from_roommate_id = rf.id
        JOIN roommates rt ON p.to_roommate_id = rt.id
        WHERE p.settlement_id IS NULL
        ORDER BY p.date DESC, p.id DESC
        """
    ).fetchall()

    payments = []
    for prow in payments_rows:
        pdict = dict(prow)
        f_rm = roommate_map.get(pdict["from_roommate_id"], {})
        t_rm = roommate_map.get(pdict["to_roommate_id"], {})
        pdict["from_initials"] = f_rm.get("initials", pdict["from_name"][:2].upper())
        pdict["from_gradient"] = f_rm.get("gradient", AVATAR_GRADIENTS[0])
        pdict["from_avatar_url"] = f_rm.get("avatar_url")
        pdict["to_initials"] = t_rm.get("initials", pdict["to_name"][:2].upper())
        pdict["to_gradient"] = t_rm.get("gradient", AVATAR_GRADIENTS[1])
        pdict["to_avatar_url"] = t_rm.get("avatar_url")
        payments.append(pdict)

    all_rids = list(roommate_map.keys())
    balances_data = calculate_balances(all_rids, expenses, payments)

    return roommate_map, expenses, payments, balances_data


@app.route("/health")
def health() -> Response:
    """Liveness probe for Render health checks. Never touches the database."""
    return Response('{"status": "healthy"}', mimetype="application/json", status=200)


@app.route("/favicon.ico")
def favicon() -> Response:
    """Serve favicon.ico directly at root URL for browsers."""
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    """Household shared password login."""
    next_url = request.args.get("next") or request.form.get("next") or url_for("expenses")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("expenses")

    if session.get("authenticated"):
        return redirect(next_url)

    ip = get_client_ip()

    if request.method == "POST":
        if is_login_rate_limited(ip):
            flash("Too many failed login attempts. Please wait 5 minutes before trying again.", "danger")
            return render_template("login.html", next_url=next_url), 429

        submitted_password = request.form.get("password", "")
        if secrets.compare_digest(submitted_password, APP_PASSWORD):
            clear_failed_logins(ip)
            session["authenticated"] = True
            session["authenticated_at"] = time.time()
            session["csrf_token"] = secrets.token_hex(32)
            flash("Household unlocked. Welcome back!", "success")
            return redirect(next_url)

        record_failed_login(ip)
        flash("Incorrect household password. Please try again.", "danger")
        return render_template("login.html", next_url=next_url), 401

    return render_template("login.html", next_url=next_url)


@app.route("/logout")
def logout() -> Response:
    """Log out of household and clear session."""
    session.clear()
    flash("You have been logged out of your household.", "info")
    return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("expenses"))


@app.route("/expenses")
def expenses():
    conn = get_connection()
    try:
        roommate_map, expenses_list, payments_list, _ = get_active_period_data(conn)
        total_centimes = sum(e["amount_centimes"] for e in expenses_list)

        # Merge expenses and payments into a unified activity feed
        feed_items = []
        for e in expenses_list:
            item = dict(e)
            item["item_type"] = "expense"
            feed_items.append(item)
        for p in payments_list:
            item = dict(p)
            item["item_type"] = "payment"
            feed_items.append(item)

        # Group unified items by date
        # Sort by date DESC, then by id DESC
        feed_items.sort(key=lambda x: (x["date"], x["id"]), reverse=True)

        return render_template(
            "expenses.html",
            active_page="expenses",
            feed_items=feed_items,
            expenses=expenses_list,
            payments=payments_list,
            total_centimes=total_centimes,
            active_roommates=[r for r in roommate_map.values() if r["is_active"]],
            today=date.today().isoformat(),
        )
    finally:
        conn.close()


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    conn = get_connection()
    try:
        active_roommates_rows = conn.execute(
            "SELECT * FROM roommates WHERE is_active = 1 ORDER BY name ASC"
        ).fetchall()

        if not active_roommates_rows:
            flash("Please add at least one active roommate before recording expenses.", "warning")
            return redirect(url_for("roommates"))

        names = [r["name"] for r in active_roommates_rows]
        initials_map = compute_unique_initials(names)
        active_roommates = []
        for r in active_roommates_rows:
            d = dict(r)
            d["initials"] = initials_map.get(d["name"], d["name"][:2].upper())
            d["gradient"] = AVATAR_GRADIENTS[(d["id"] - 1) % len(AVATAR_GRADIENTS)]
            active_roommates.append(d)

        if request.method == "POST":
            label = request.form.get("label", "").strip()
            amount_raw = request.form.get("amount", "").strip()
            expense_date = request.form.get("date", "").strip()
            paid_by_id_raw = request.form.get("paid_by_id")
            participant_ids_raw = request.form.getlist("participants")

            # Validations
            errors = []
            if not label:
                errors.append("Expense description is required.")
            
            try:
                amount_centimes = to_centimes(amount_raw)
            except (ValueError, TypeError) as e:
                errors.append(f"Invalid amount: {str(e)}")
                amount_centimes = None

            if not expense_date:
                errors.append("Date is required.")

            try:
                paid_by_id = int(paid_by_id_raw) if paid_by_id_raw else None
            except ValueError:
                paid_by_id = None

            if not paid_by_id or paid_by_id not in [r["id"] for r in active_roommates]:
                errors.append("A valid active payer must be selected.")

            try:
                participant_ids = [int(p) for p in participant_ids_raw]
            except ValueError:
                participant_ids = []

            # Ensure the person who paid is always included in the split alongside selected participants
            if paid_by_id and paid_by_id not in participant_ids:
                participant_ids.append(paid_by_id)

            if not participant_ids:
                errors.append("At least one participant must be selected to share the expense.")

            if errors:
                for err in errors:
                    flash(err, "danger")
                return render_template(
                    "expense_form.html",
                    active_page="expenses",
                    is_edit=False,
                    roommates=active_roommates,
                    today=expense_date or date.today().isoformat(),
                    expense={"label": label, "paid_by_id": paid_by_id},
                    formatted_amount=amount_raw,
                    selected_participant_ids=participant_ids,
                )

            # Split logic with deterministic remainder
            shares = split_expense(amount_centimes, participant_ids)

            # Insert into database in a single transaction
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO expenses (label, amount_centimes, date, paid_by_id, settlement_id)
                    VALUES (?, ?, ?, ?, NULL)
                    """,
                    (label, amount_centimes, expense_date, paid_by_id),
                )
                expense_id = cursor.lastrowid
                for pid, share_centimes in shares.items():
                    cursor.execute(
                        """
                        INSERT INTO expense_participants (expense_id, roommate_id, share_centimes)
                        VALUES (?, ?, ?)
                        """,
                        (expense_id, pid, share_centimes),
                    )

            flash(f"Expense '{label}' ({format_mad(amount_centimes)}) added successfully.", "success")
            return redirect(url_for("expenses"))

        return render_template(
            "expense_form.html",
            active_page="expenses",
            is_edit=False,
            roommates=active_roommates,
            today=date.today().isoformat(),
            expense=None,
            formatted_amount="",
            selected_participant_ids=[r["id"] for r in active_roommates],
        )
    finally:
        conn.close()


@app.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
def edit_expense(expense_id: int):
    conn = get_connection()
    try:
        expense_row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if not expense_row:
            flash("Expense not found.", "danger")
            return redirect(url_for("expenses"))

        # Refuse edit if expense belongs to a settled period
        if expense_row["settlement_id"] is not None:
            flash("Settled expenses are archived and read-only. They cannot be edited.", "warning")
            return redirect(url_for("history"))

        roommates_rows = conn.execute("SELECT * FROM roommates ORDER BY name ASC").fetchall()
        names = [r["name"] for r in roommates_rows]
        initials_map = compute_unique_initials(names)
        roommates = []
        for r in roommates_rows:
            d = dict(r)
            d["initials"] = initials_map.get(d["name"], d["name"][:2].upper())
            d["gradient"] = AVATAR_GRADIENTS[(d["id"] - 1) % len(AVATAR_GRADIENTS)]
            roommates.append(d)

        if request.method == "POST":
            label = request.form.get("label", "").strip()
            amount_raw = request.form.get("amount", "").strip()
            expense_date = request.form.get("date", "").strip()
            paid_by_id_raw = request.form.get("paid_by_id")
            participant_ids_raw = request.form.getlist("participants")

            errors = []
            if not label:
                errors.append("Expense description is required.")

            try:
                amount_centimes = to_centimes(amount_raw)
            except (ValueError, TypeError) as e:
                errors.append(f"Invalid amount: {str(e)}")
                amount_centimes = None

            if not expense_date:
                errors.append("Date is required.")

            try:
                paid_by_id = int(paid_by_id_raw) if paid_by_id_raw else None
            except ValueError:
                paid_by_id = None

            if not paid_by_id:
                errors.append("A valid payer must be selected.")

            try:
                participant_ids = [int(p) for p in participant_ids_raw]
            except ValueError:
                participant_ids = []

            # Ensure the person who paid is always included in the split alongside selected participants
            if paid_by_id and paid_by_id not in participant_ids:
                participant_ids.append(paid_by_id)

            if not participant_ids:
                errors.append("At least one participant must be selected.")

            if errors:
                for err in errors:
                    flash(err, "danger")
                return render_template(
                    "expense_form.html",
                    active_page="expenses",
                    is_edit=True,
                    roommates=roommates,
                    expense={"label": label, "paid_by_id": paid_by_id, "date": expense_date},
                    formatted_amount=amount_raw,
                    selected_participant_ids=participant_ids,
                )

            shares = split_expense(amount_centimes, participant_ids)

            with conn:
                conn.execute(
                    """
                    UPDATE expenses
                    SET label = ?, amount_centimes = ?, date = ?, paid_by_id = ?
                    WHERE id = ?
                    """,
                    (label, amount_centimes, expense_date, paid_by_id, expense_id),
                )
                conn.execute("DELETE FROM expense_participants WHERE expense_id = ?", (expense_id,))
                for pid, share_centimes in shares.items():
                    conn.execute(
                        """
                        INSERT INTO expense_participants (expense_id, roommate_id, share_centimes)
                        VALUES (?, ?, ?)
                        """,
                        (expense_id, pid, share_centimes),
                    )

            flash("Expense updated successfully.", "success")
            return redirect(url_for("expenses"))

        # GET request
        participant_rows = conn.execute(
            "SELECT roommate_id FROM expense_participants WHERE expense_id = ?",
            (expense_id,),
        ).fetchall()
        selected_pids = [p["roommate_id"] for p in participant_rows]
        formatted_mad_val = f"{expense_row['amount_centimes'] / 100:.2f}"

        return render_template(
            "expense_form.html",
            active_page="expenses",
            is_edit=True,
            roommates=roommates,
            expense=dict(expense_row),
            formatted_amount=formatted_mad_val,
            selected_participant_ids=selected_pids,
        )
    finally:
        conn.close()


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
def delete_expense(expense_id: int):
    conn = get_connection()
    try:
        expense_row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if not expense_row:
            flash("Expense not found.", "danger")
            return redirect(url_for("expenses"))

        # Refuse delete if expense belongs to a settled period
        if expense_row["settlement_id"] is not None:
            flash("Settled expenses are archived and read-only. They cannot be deleted.", "warning")
            return redirect(url_for("history"))

        with conn:
            conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))

        flash("Expense deleted successfully.", "info")
        return redirect(url_for("expenses"))
    finally:
        conn.close()


@app.route("/expenses/export.csv")
def export_csv():
    conn = get_connection()
    try:
        _, expenses_list, payments_list, _ = get_active_period_data(conn)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Type", "Description", "Paid By", "Amount (MAD)", "Participants", "Participant Shares (MAD)"])

        for exp in expenses_list:
            participants_str = ", ".join(p["name"] for p in exp["participants"])
            shares_str = "; ".join(f"{p['name']}: {p['share_centimes'] / 100:.2f}" for p in exp["participants"])
            writer.writerow([
                exp["date"],
                "Expense",
                exp["label"],
                exp["paid_by_name"],
                f"{exp['amount_centimes'] / 100:.2f}",
                participants_str,
                shares_str,
            ])

        for p in payments_list:
            writer.writerow([
                p["date"],
                "Payment",
                f"Payment: {p['from_name']} -> {p['to_name']}" + (f" ({p['notes']})" if p['notes'] else ""),
                p["from_name"],
                f"{p['amount_centimes'] / 100:.2f}",
                p["to_name"],
                f"{p['to_name']}: {p['amount_centimes'] / 100:.2f}",
            ])

        output.seek(0)
        filename = f"roommate_expenses_{date.today().isoformat()}.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        conn.close()


@app.route("/reports")
def reports():
    period_filter = request.args.get("period", "current").strip()
    conn = get_connection()
    try:
        # 1. Fetch all roommates
        roommate_map = get_roommate_map(conn)

        # 2. Fetch past settlement periods
        periods_rows = conn.execute(
            "SELECT * FROM settlement_periods ORDER BY id DESC"
        ).fetchall()
        settlement_periods = [dict(p) for p in periods_rows]

        # 3. Query expenses according to period_filter
        if period_filter == "all":
            expenses_query = """
                SELECT e.*, r.name as paid_by_name
                FROM expenses e
                JOIN roommates r ON e.paid_by_id = r.id
                ORDER BY e.date ASC, e.id ASC
            """
            expenses_params = ()
            parts_query = """
                SELECT ep.expense_id, ep.roommate_id, ep.share_centimes, r.name
                FROM expense_participants ep
                JOIN roommates r ON ep.roommate_id = r.id
                JOIN expenses e ON ep.expense_id = e.id
                ORDER BY ep.expense_id, ep.roommate_id ASC
            """
            parts_params = ()
            payments_query = """
                SELECT p.*, rf.name as from_name, rt.name as to_name
                FROM payments p
                JOIN roommates rf ON p.from_roommate_id = rf.id
                JOIN roommates rt ON p.to_roommate_id = rt.id
                ORDER BY p.date ASC, p.id ASC
            """
            payments_params = ()
        elif period_filter.isdigit():
            pid = int(period_filter)
            expenses_query = """
                SELECT e.*, r.name as paid_by_name
                FROM expenses e
                JOIN roommates r ON e.paid_by_id = r.id
                WHERE e.settlement_id = ?
                ORDER BY e.date ASC, e.id ASC
            """
            expenses_params = (pid,)
            parts_query = """
                SELECT ep.expense_id, ep.roommate_id, ep.share_centimes, r.name
                FROM expense_participants ep
                JOIN roommates r ON ep.roommate_id = r.id
                JOIN expenses e ON ep.expense_id = e.id
                WHERE e.settlement_id = ?
                ORDER BY ep.expense_id, ep.roommate_id ASC
            """
            parts_params = (pid,)
            payments_query = """
                SELECT p.*, rf.name as from_name, rt.name as to_name
                FROM payments p
                JOIN roommates rf ON p.from_roommate_id = rf.id
                JOIN roommates rt ON p.to_roommate_id = rt.id
                WHERE p.settlement_id = ?
                ORDER BY p.date ASC, p.id ASC
            """
            payments_params = (pid,)
        else:
            period_filter = "current"
            expenses_query = """
                SELECT e.*, r.name as paid_by_name
                FROM expenses e
                JOIN roommates r ON e.paid_by_id = r.id
                WHERE e.settlement_id IS NULL
                ORDER BY e.date ASC, e.id ASC
            """
            expenses_params = ()
            parts_query = """
                SELECT ep.expense_id, ep.roommate_id, ep.share_centimes, r.name
                FROM expense_participants ep
                JOIN roommates r ON ep.roommate_id = r.id
                JOIN expenses e ON ep.expense_id = e.id
                WHERE e.settlement_id IS NULL
                ORDER BY ep.expense_id, ep.roommate_id ASC
            """
            parts_params = ()
            payments_query = """
                SELECT p.*, rf.name as from_name, rt.name as to_name
                FROM payments p
                JOIN roommates rf ON p.from_roommate_id = rf.id
                JOIN roommates rt ON p.to_roommate_id = rt.id
                WHERE p.settlement_id IS NULL
                ORDER BY p.date ASC, p.id ASC
            """
            payments_params = ()

        expenses_rows = conn.execute(expenses_query, expenses_params).fetchall()
        parts_rows = conn.execute(parts_query, parts_params).fetchall()
        payments_rows = conn.execute(payments_query, payments_params).fetchall()

        parts_by_exp = defaultdict(list)
        shares_by_exp = defaultdict(dict)
        for p in parts_rows:
            p_dict = dict(p)
            rm = roommate_map.get(p_dict["roommate_id"])
            if rm:
                p_dict["initials"] = rm["initials"]
                p_dict["gradient"] = rm["gradient"]
            parts_by_exp[p["expense_id"]].append(p_dict)
            shares_by_exp[p["expense_id"]][p["roommate_id"]] = p["share_centimes"]

        expenses_list = []
        for exp_row in expenses_rows:
            exp_dict = dict(exp_row)
            payer = roommate_map.get(exp_dict["paid_by_id"])
            if payer:
                exp_dict["paid_by_initials"] = payer["initials"]
                exp_dict["paid_by_gradient"] = payer["gradient"]

            exp_dict["participants"] = parts_by_exp.get(exp_dict["id"], [])
            exp_dict["shares"] = shares_by_exp.get(exp_dict["id"], {})
            expenses_list.append(exp_dict)

        payments_list = []
        for prow in payments_rows:
            pdict = dict(prow)
            f_rm = roommate_map.get(pdict["from_roommate_id"], {})
            t_rm = roommate_map.get(pdict["to_roommate_id"], {})
            pdict["from_initials"] = f_rm.get("initials", pdict["from_name"][:2].upper())
            pdict["from_gradient"] = f_rm.get("gradient", AVATAR_GRADIENTS[0])
            pdict["to_initials"] = t_rm.get("initials", pdict["to_name"][:2].upper())
            pdict["to_gradient"] = t_rm.get("gradient", AVATAR_GRADIENTS[1])
            payments_list.append(pdict)

        report_data = compute_reports_data(expenses_list, roommate_map, payments_list)

        return render_template(
            "reports.html",
            active_page="reports",
            report=report_data,
            period_filter=period_filter,
            settlement_periods=settlement_periods,
            roommate_map=roommate_map,
        )
    finally:
        conn.close()


@app.route("/balances")
def balances():
    conn = get_connection()
    try:
        roommate_map, expenses_list, payments_list, balances_data = get_active_period_data(conn)
        total_period_centimes = sum(e["amount_centimes"] for e in expenses_list)
        max_abs = max([abs(b["net_balance"]) for b in balances_data.values()] or [1])

        roommate_balances = []
        for rid, rdata in roommate_map.items():
            b = balances_data.get(rid, {"total_paid": 0, "total_share": 0, "net_balance": 0})
            net = b["net_balance"]
            ratio = round((abs(net) / max_abs) * 100, 1) if max_abs > 0 else 0
            roommate_balances.append({
                "id": rid,
                "name": rdata["name"],
                "initials": rdata.get("initials", rdata["name"][:2].upper()),
                "gradient": rdata.get("gradient", AVATAR_GRADIENTS[0]),
                "avatar_url": rdata.get("avatar_url"),
                "is_active": rdata["is_active"],
                "total_paid": b["total_paid"],
                "total_share": b["total_share"],
                "expenses_paid": b.get("expenses_paid", 0),
                "payments_made": b.get("payments_made", 0),
                "payments_received": b.get("payments_received", 0),
                "net_balance": net,
                "balance_ratio": ratio,
            })

        # Calculate minimal transfers using greedy matching
        net_map = {r["id"]: r["net_balance"] for r in roommate_balances}
        raw_transfers = settle_debts(net_map)

        display_transfers = []
        for t in raw_transfers:
            debtor = roommate_map.get(t["from_id"], {})
            creditor = roommate_map.get(t["to_id"], {})
            display_transfers.append({
                "from_id": t["from_id"],
                "debtor_name": debtor.get("name", "Unknown"),
                "debtor_initials": debtor.get("initials", "??"),
                "debtor_gradient": debtor.get("gradient", AVATAR_GRADIENTS[0]),
                "debtor_avatar_url": debtor.get("avatar_url"),
                "to_id": t["to_id"],
                "creditor_name": creditor.get("name", "Unknown"),
                "creditor_initials": creditor.get("initials", "??"),
                "creditor_gradient": creditor.get("gradient", AVATAR_GRADIENTS[1]),
                "creditor_avatar_url": creditor.get("avatar_url"),
                "amount_centimes": t["amount_centimes"],
            })

        active_roommates = [r for r in roommate_map.values() if r["is_active"]]

        return render_template(
            "balances.html",
            active_page="balances",
            roommate_balances=roommate_balances,
            transfers=display_transfers,
            expenses_count=len(expenses_list),
            payments_count=len(payments_list),
            total_period_centimes=total_period_centimes,
            active_roommates=active_roommates,
            today=date.today().isoformat(),
        )
    finally:
        conn.close()


@app.route("/payments/add", methods=["POST"])
def add_payment():
    conn = get_connection()
    try:
        from_id_raw = request.form.get("from_roommate_id")
        to_id_raw = request.form.get("to_roommate_id")
        amount_raw = request.form.get("amount", "").strip()
        payment_date = request.form.get("date", "").strip() or date.today().isoformat()
        notes = request.form.get("notes", "").strip()

        errors = []
        try:
            from_id = int(from_id_raw) if from_id_raw else None
            to_id = int(to_id_raw) if to_id_raw else None
        except ValueError:
            from_id = to_id = None

        if not from_id or not to_id:
            errors.append("Both payer and recipient must be selected.")
        elif from_id == to_id:
            errors.append("Payer and recipient cannot be the same roommate.")

        try:
            amount_centimes = to_centimes(amount_raw)
        except (ValueError, TypeError) as e:
            errors.append(f"Invalid amount: {str(e)}")
            amount_centimes = None

        if not payment_date:
            errors.append("Payment date is required.")

        if from_id and to_id and not errors:
            r_from = conn.execute("SELECT * FROM roommates WHERE id = ?", (from_id,)).fetchone()
            r_to = conn.execute("SELECT * FROM roommates WHERE id = ?", (to_id,)).fetchone()
            if not r_from or not r_to:
                errors.append("Selected roommates must exist.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return redirect(request.referrer or url_for("balances"))

        with conn:
            conn.execute(
                """
                INSERT INTO payments (from_roommate_id, to_roommate_id, amount_centimes, date, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (from_id, to_id, amount_centimes, payment_date, notes or None),
            )

        flash(f"Payment of {format_mad(amount_centimes)} from {r_from['name']} to {r_to['name']} recorded successfully.", "success")
        return redirect(request.referrer or url_for("balances"))
    finally:
        conn.close()


@app.route("/payments/<int:payment_id>/delete", methods=["POST"])
def delete_payment(payment_id: int):
    conn = get_connection()
    try:
        payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if not payment:
            flash("Payment record not found.", "danger")
            return redirect(url_for("expenses"))

        if payment["settlement_id"] is not None:
            flash("Settled payments are archived and read-only. They cannot be deleted.", "warning")
            return redirect(url_for("history"))

        with conn:
            conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))

        flash("Payment record deleted successfully.", "info")
        return redirect(request.referrer or url_for("expenses"))
    finally:
        conn.close()


@app.route("/settle-up", methods=["POST"])
def settle_up():
    conn = get_connection()
    try:
        roommate_map, expenses_list, payments_list, balances_data = get_active_period_data(conn)

        # Refuse if current period has no expenses or payments
        if not expenses_list and not payments_list:
            flash("There are no active expenses in the current period to settle.", "warning")
            return redirect(url_for("balances"))

        net_map = {rid: b["net_balance"] for rid, b in balances_data.items()}
        transfers = settle_debts(net_map)
        total_expenses_centimes = sum(e["amount_centimes"] for e in expenses_list)

        # Execute entire settlement archival in a single atomic database transaction
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO settlement_periods (total_expenses_centimes, notes)
                VALUES (?, ?)
                """,
                (total_expenses_centimes, f"Settlement on {date.today().isoformat()}"),
            )
            settlement_id = cursor.lastrowid

            # Archive all active expenses
            cursor.execute(
                "UPDATE expenses SET settlement_id = ? WHERE settlement_id IS NULL",
                (settlement_id,),
            )

            # Archive all active payments
            cursor.execute(
                "UPDATE payments SET settlement_id = ? WHERE settlement_id IS NULL",
                (settlement_id,),
            )

            # Store the computed remaining settlement transfers
            for t in transfers:
                cursor.execute(
                    """
                    INSERT INTO settlement_transfers (settlement_id, from_roommate_id, to_roommate_id, amount_centimes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (settlement_id, t["from_id"], t["to_id"], t["amount_centimes"]),
                )

        flash("Current period has been successfully settled and archived!", "success")
        return redirect(url_for("history"))
    finally:
        conn.close()


@app.route("/history")
def history():
    conn = get_connection()
    try:
        roommate_map = get_roommate_map(conn)
        periods_rows = conn.execute(
            "SELECT * FROM settlement_periods ORDER BY id DESC"
        ).fetchall()

        if not periods_rows:
            return render_template(
                "history.html",
                active_page="history",
                settlements=[],
            )

        # Batch fetch all historical transfers in a single query
        transfers_rows = conn.execute(
            """
            SELECT st.*, r1.name as debtor_name, r2.name as creditor_name
            FROM settlement_transfers st
            JOIN roommates r1 ON st.from_roommate_id = r1.id
            JOIN roommates r2 ON st.to_roommate_id = r2.id
            ORDER BY st.id ASC
            """
        ).fetchall()
        transfers_by_period = defaultdict(list)
        for t in transfers_rows:
            td = dict(t)
            d = roommate_map.get(td["from_roommate_id"], {})
            c = roommate_map.get(td["to_roommate_id"], {})
            td["debtor_initials"] = d.get("initials", td["debtor_name"][:2].upper())
            td["debtor_gradient"] = d.get("gradient", AVATAR_GRADIENTS[0])
            td["creditor_initials"] = c.get("initials", td["creditor_name"][:2].upper())
            td["creditor_gradient"] = c.get("gradient", AVATAR_GRADIENTS[1])
            transfers_by_period[td["settlement_id"]].append(td)

        # Batch fetch all historical payments in a single query
        payments_rows = conn.execute(
            """
            SELECT p.*, rf.name as from_name, rt.name as to_name
            FROM payments p
            JOIN roommates rf ON p.from_roommate_id = rf.id
            JOIN roommates rt ON p.to_roommate_id = rt.id
            WHERE p.settlement_id IS NOT NULL
            ORDER BY p.date DESC, p.id DESC
            """
        ).fetchall()
        payments_by_period = defaultdict(list)
        for prow in payments_rows:
            pd = dict(prow)
            f_rm = roommate_map.get(pd["from_roommate_id"], {})
            t_rm = roommate_map.get(pd["to_roommate_id"], {})
            pd["from_initials"] = f_rm.get("initials", pd["from_name"][:2].upper())
            pd["from_gradient"] = f_rm.get("gradient", AVATAR_GRADIENTS[0])
            pd["to_initials"] = t_rm.get("initials", pd["to_name"][:2].upper())
            pd["to_gradient"] = t_rm.get("gradient", AVATAR_GRADIENTS[1])
            payments_by_period[pd["settlement_id"]].append(pd)

        # Batch fetch all historical expenses in a single query
        expenses_rows = conn.execute(
            """
            SELECT e.*, r.name as paid_by_name
            FROM expenses e
            JOIN roommates r ON e.paid_by_id = r.id
            WHERE e.settlement_id IS NOT NULL
            ORDER BY e.date DESC, e.id DESC
            """
        ).fetchall()

        # Batch fetch all participants for settled expenses in a single query
        parts_rows = conn.execute(
            """
            SELECT ep.expense_id, ep.roommate_id, ep.share_centimes, r.name
            FROM expense_participants ep
            JOIN roommates r ON ep.roommate_id = r.id
            JOIN expenses e ON ep.expense_id = e.id
            WHERE e.settlement_id IS NOT NULL
            ORDER BY ep.expense_id, ep.roommate_id ASC
            """
        ).fetchall()
        parts_by_exp = defaultdict(list)
        for pr in parts_rows:
            pd = dict(pr)
            rm = roommate_map.get(pd["roommate_id"], {})
            pd["initials"] = rm.get("initials", pd["name"][:2].upper())
            pd["gradient"] = rm.get("gradient", AVATAR_GRADIENTS[0])
            parts_by_exp[pd["expense_id"]].append(pd)

        expenses_by_period = defaultdict(list)
        for exp_row in expenses_rows:
            exp_dict = dict(exp_row)
            payer = roommate_map.get(exp_dict["paid_by_id"], {})
            exp_dict["paid_by_initials"] = payer.get("initials", exp_dict["paid_by_name"][:2].upper())
            exp_dict["paid_by_gradient"] = payer.get("gradient", AVATAR_GRADIENTS[0])
            exp_dict["participants"] = parts_by_exp.get(exp_dict["id"], [])
            expenses_by_period[exp_dict["settlement_id"]].append(exp_dict)

        settlements = []
        for p in periods_rows:
            p_dict = dict(p)
            p_dict["transfers"] = transfers_by_period.get(p_dict["id"], [])
            p_dict["payments"] = payments_by_period.get(p_dict["id"], [])
            p_dict["expenses"] = expenses_by_period.get(p_dict["id"], [])
            settlements.append(p_dict)

        return render_template(
            "history.html",
            active_page="history",
            settlements=settlements,
        )
    finally:
        conn.close()


@app.route("/roommates", methods=["GET"])
def roommates():
    conn = get_connection()
    try:
        roommate_map, _, _, balances_data = get_active_period_data(conn)
        roommates_list = []
        for rid, rdata in roommate_map.items():
            b = balances_data.get(rid, {"net_balance": 0})
            roommates_list.append({
                "id": rid,
                "name": rdata["name"],
                "initials": rdata.get("initials", rdata["name"][:2].upper()),
                "gradient": rdata.get("gradient", AVATAR_GRADIENTS[0]),
                "avatar_url": rdata.get("avatar_url"),
                "is_active": rdata["is_active"],
                "net_balance": b["net_balance"],
            })

        return render_template(
            "roommates.html",
            active_page="roommates",
            roommates=roommates_list,
        )
    finally:
        conn.close()


@app.route("/roommates/<int:roommate_id>/avatar", methods=["POST"])
def update_roommate_avatar(roommate_id: int):
    conn = get_connection()
    try:
        roommate = conn.execute("SELECT * FROM roommates WHERE id = ?", (roommate_id,)).fetchone()
        if not roommate:
            flash("Roommate not found.", "danger")
            return redirect(url_for("roommates"))

        if "avatar" not in request.files:
            flash("No file was selected.", "danger")
            return redirect(url_for("roommates"))

        file = request.files["avatar"]
        if not file or file.filename == "":
            flash("Please choose an image file to upload.", "danger")
            return redirect(url_for("roommates"))

        if not allowed_avatar_file(file.filename):
            flash("Invalid image type. Supported formats: PNG, JPG, JPEG, WEBP, GIF.", "danger")
            return redirect(url_for("roommates"))

        # Convert to compact base64 data URL to store directly in DB
        # Ensures 100% serverless compatibility on Vercel without read-only filesystem issues
        try:
            from PIL import Image, ImageOps
            img = Image.open(file.stream)
            img = ImageOps.exif_transpose(img)
            img.thumbnail((256, 256))
            buf = io.BytesIO()
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGBA")
                img.save(buf, format="PNG", optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                avatar_url = f"data:image/png;base64,{b64}"
            else:
                img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=85, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                avatar_url = f"data:image/jpeg;base64,{b64}"
        except Exception:
            file.stream.seek(0)
            raw_bytes = file.read()
            ext = file.filename.rsplit(".", 1)[1].lower()
            mime = "image/png" if ext == "png" else "image/jpeg"
            b64 = base64.b64encode(raw_bytes).decode("utf-8")
            avatar_url = f"data:{mime};base64,{b64}"

        with conn:
            conn.execute("UPDATE roommates SET avatar_url = ? WHERE id = ?", (avatar_url, roommate_id))

        flash(f"Profile picture for {roommate['name']} updated successfully!", "success")
        return redirect(url_for("roommates"))
    finally:
        conn.close()


@app.route("/roommates/<int:roommate_id>/avatar/remove", methods=["POST"])
def remove_roommate_avatar(roommate_id: int):
    conn = get_connection()
    try:
        roommate = conn.execute("SELECT * FROM roommates WHERE id = ?", (roommate_id,)).fetchone()
        if not roommate:
            flash("Roommate not found.", "danger")
            return redirect(url_for("roommates"))

        old_avatar = roommate["avatar_url"]
        if old_avatar and old_avatar.startswith("/static/uploads/avatars/"):
            old_filename = old_avatar.split("/")[-1]
            old_path = UPLOAD_AVATARS_DIR / old_filename
            if old_path.exists():
                try:
                    old_path.unlink()
                except Exception:
                    pass

        with conn:
            conn.execute("UPDATE roommates SET avatar_url = NULL WHERE id = ?", (roommate_id,))

        flash(f"Profile picture for {roommate['name']} removed.", "info")
        return redirect(url_for("roommates"))
    finally:
        conn.close()


@app.route("/roommates/add", methods=["POST"])
def add_roommate():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Roommate name cannot be empty.", "danger")
        return redirect(url_for("roommates"))

    conn = get_connection()
    try:
        with conn:
            conn.execute("INSERT INTO roommates (name, is_active) VALUES (?, 1)", (name,))
        flash(f"Roommate '{name}' added successfully.", "success")
        return redirect(url_for("roommates"))
    finally:
        conn.close()


@app.route("/roommates/<int:roommate_id>/rename", methods=["POST"])
def rename_roommate(roommate_id: int):
    new_name = request.form.get("name", "").strip()
    if not new_name:
        flash("Name cannot be empty.", "danger")
        return redirect(url_for("roommates"))

    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE roommates SET name = ? WHERE id = ?", (new_name, roommate_id))
        flash(f"Roommate renamed to '{new_name}'.", "success")
        return redirect(url_for("roommates"))
    finally:
        conn.close()


@app.route("/roommates/<int:roommate_id>/toggle-status", methods=["POST"])
def toggle_roommate_status(roommate_id: int):
    conn = get_connection()
    try:
        roommate = conn.execute("SELECT * FROM roommates WHERE id = ?", (roommate_id,)).fetchone()
        if not roommate:
            flash("Roommate not found.", "danger")
            return redirect(url_for("roommates"))

        # If deactivating, check whether they have a non-zero net balance in the current period
        if roommate["is_active"] == 1:
            _, _, _, balances_data = get_active_period_data(conn)
            r_balance = balances_data.get(roommate_id, {}).get("net_balance", 0)

            if r_balance != 0:
                flash(
                    f"Cannot deactivate {roommate['name']}: they have an unsettled balance of {format_mad(r_balance)} in the current period. Please settle up first before deactivating.",
                    "danger",
                )
                return redirect(url_for("roommates"))

            with conn:
                conn.execute("UPDATE roommates SET is_active = 0 WHERE id = ?", (roommate_id,))
            flash(f"Roommate '{roommate['name']}' has been deactivated.", "info")
        else:
            with conn:
                conn.execute("UPDATE roommates SET is_active = 1 WHERE id = ?", (roommate_id,))
            flash(f"Roommate '{roommate['name']}' has been reactivated.", "success")

        return redirect(url_for("roommates"))
    finally:
        conn.close()


@app.route("/roommates/<int:roommate_id>/delete", methods=["POST"])
def delete_roommate(roommate_id: int):
    conn = get_connection()
    try:
        roommate = conn.execute("SELECT * FROM roommates WHERE id = ?", (roommate_id,)).fetchone()
        if not roommate:
            flash("Roommate not found.", "danger")
            return redirect(url_for("roommates"))

        # Check if roommate is referenced in any expenses, shares, settlement transfers, or payments
        paid_count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE paid_by_id = ?", (roommate_id,)
        ).fetchone()[0]
        share_count = conn.execute(
            "SELECT COUNT(*) FROM expense_participants WHERE roommate_id = ?", (roommate_id,)
        ).fetchone()[0]
        transfer_count = conn.execute(
            "SELECT COUNT(*) FROM settlement_transfers WHERE from_roommate_id = ? OR to_roommate_id = ?",
            (roommate_id, roommate_id),
        ).fetchone()[0]
        payment_count = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE from_roommate_id = ? OR to_roommate_id = ?",
            (roommate_id, roommate_id),
        ).fetchone()[0]

        if paid_count > 0 or share_count > 0 or transfer_count > 0 or payment_count > 0:
            flash(
                f"Cannot delete '{roommate['name']}': they have associated expenses, payments, or settlement history. You can deactivate them instead to preserve records.",
                "warning",
            )
            return redirect(url_for("roommates"))

        old_avatar = roommate["avatar_url"]
        if old_avatar and old_avatar.startswith("/static/uploads/avatars/"):
            old_filename = old_avatar.split("/")[-1]
            old_path = UPLOAD_AVATARS_DIR / old_filename
            if old_path.exists():
                try:
                    old_path.unlink()
                except Exception:
                    pass

        with conn:
            conn.execute("DELETE FROM roommates WHERE id = ?", (roommate_id,))

        flash(f"Roommate '{roommate['name']}' deleted successfully.", "info")
        return redirect(url_for("roommates"))
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()

    debug_env = os.environ.get("FLASK_DEBUG") == "1"
    port = int(os.environ.get("PORT", 5000))

    if debug_env:
        # If debug is enabled, ensure we never combine it with 0.0.0.0
        host = os.environ.get("HOST", "127.0.0.1")
        if host == "0.0.0.0":
            print("WARNING: debug mode requested but host is 0.0.0.0. Enforcing debug=False for security.")
            debug = False
        else:
            debug = True
    else:
        # Default run: debug=False and binds to 0.0.0.0 for home network access
        host = os.environ.get("HOST", "0.0.0.0")
        debug = False

    local_ip = get_local_ip()
    print("=" * 65)
    print(f" Roommate Split is running!")
    print(f" Local access:   http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        print(f" Network access: http://{local_ip}:{port} (from phone on same Wi-Fi)")
    print(f" Host: {host} | Port: {port} | Debug: {debug}")
    print("=" * 65)

    app.run(host=host, port=port, debug=debug)
