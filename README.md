# Roommate Split (MAD) 🤝

A lightweight, mobile-friendly web application to track shared expenses between roommates, split bills deterministically down to the exact centime, and settle debts with minimal cash transfers.

---

## Features

- **Integer Centimes Precision**: All currency is stored as integer centimes in Moroccan Dirhams (MAD). Never uses floats to prevent rounding errors or monetary drift.
- **Deterministic Remainder Distribution**: When an amount doesn't divide evenly (e.g. 100.00 MAD among 3 people = 33.34, 33.33, 33.33 MAD), leftover centimes are distributed deterministically so the sum of individual shares always matches the total bill.
- **Reports & Analytics Dashboard (`/reports`)**: Complete visual dashboard featuring KPIs, daily/weekly spending rhythm, category intelligence, roommate contribution breakdowns, and interactive bar/donut charts.
- **Roommate Profile Pictures**: Upload, update, or remove custom profile pictures with instant preview and seamless fallback to unique color gradient initials avatars.
- **Partial & Individual Repayments**: When a roommate reimburses another (in full or partially) before the formal settlement, record an interim payment directly from the settlement card or activity feed. Net balances adjust instantly while preserving the mathematical zero-sum guarantee.
- **Neon Cloud PostgreSQL & Offline SQLite**: Connected to Neon Serverless PostgreSQL online with connection pooling (`ThreadedConnectionPool`) and batched query execution for sub-400ms response times, with an automatic fallback to local SQLite for isolated offline unit tests.
- **Subset & Non-Participant Payers**: Expenses can be split among any subset of roommates. A roommate can pay for others without being a consumer.
- **Balances & Settle-Up**: Computes net balances for everyone (who gets money back and who owes) and calculates the minimal number of direct transfers needed to zero everyone out using a greedy optimizer.
- **Polished Custom Modals**: Replaced intrusive browser dialogs with smooth, custom popup confirmation modals with item preview badges.
- **Settlement Archival**: "Mark as settled" archives all current expenses and recorded transfers in a single database transaction, starting a fresh period. Settled records remain permanently viewable and read-only in the History page.
- **Roommate Management**: Add, rename, manage photos, or deactivate roommates. Deactivation is safely blocked if a roommate has an unsettled balance in the current period.
- **CSV Export**: Export current period expenses with participant shares at any time.
- **Mobile-First UI**: Clean CSS, large 44px+ touch targets, responsive navigation, dark/light theme, and no external CSS/JS dependencies.

---

## Requirements & Setup

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.12)

### 2. Installation
Clone or navigate to the repository folder:

```bash
cd roommate-split
```

Create and activate a virtual environment (recommended):
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## Running the App

Start the server:
```bash
python app.py
```

The app will initialize the database and output:
```text
=================================================================
 Roommate Split is running!
 Local access:   http://127.0.0.1:5000
 Network access: http://192.168.x.x:5000 (from phone on same Wi-Fi)
 Host: 0.0.0.0 | Port: 5000 | Debug: False
=================================================================
```

### Accessing from a Phone on the Same Wi-Fi

1. Make sure your phone and computer are connected to the same Wi-Fi network.
2. In your phone's browser, navigate to the **Network access URL** displayed in your terminal (e.g., `http://192.168.1.50:5000`).
3. ⚠️ **Windows Firewall Alert**: When running `python app.py` on Windows for the first time, Windows Defender Firewall may display a prompt asking whether to allow Python to communicate on networks. **Check "Private networks" and click "Allow access"** so your phone can reach the application.

### Debug Mode Configuration
- By default, the server runs with `debug=False` and binds to `0.0.0.0`.
- To enable debug mode during development, set `FLASK_DEBUG=1`.
- For security, debug mode is **never combined with `0.0.0.0`**; when debug mode is enabled, it binds strictly to `127.0.0.1`.

---

## Demo Data (Seeding)

To test the application immediately with realistic roommates and expenses:

```bash
python seed.py
```

This seeds 3 roommates (Mohamed, Brahim, Mouad) and sample expenses covering:
- Even splits across all roommates (Weekly Groceries, Fiber Internet)
- Subset expenses (Cleaning supplies split between 2 roommates)
- Payer who is not a participant (Takeout dinner)
- Uneven remainder distribution (Snacks split with centime remainder)

> **Note**: `seed.py` will refuse to run if the database already contains data to prevent overwriting your real records.

---

## Running Automated Tests

Run the full pytest suite (pure split logic tests and integration web tests):

```bash
pytest
```

Or run with verbose output:
```bash
pytest -v
```

### Test Coverage Highlights:
- Split logic with centime remainder distribution (e.g., 100.00 MAD among 3 people).
- 1 centime split among 3 people.
- Subset of participants and payer-not-participant scenarios.
- Chained debts simplification (A owes B, B owes C $\rightarrow$ A pays C).
- Verifying that applying transfers zeroes out all net balances.
- Scenarios with 2+ creditors and 2+ debtors.
- Comma decimal input parsing (`"120,50"`) and dot input parsing (`"120.50"`).
- Type checking: rejecting floats, negative amounts, zero, and excess decimals.
- Read-only protection on settled expenses (refusing edit/delete).
- Non-zero balance protection when attempting to deactivate a roommate.
- Atomic settlement period archival.
