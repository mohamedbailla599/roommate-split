"""Captures product-grade screenshots of roommate-split across viewports and themes.
Uses a temporary isolated database with demo data and Chrome DevTools Protocol (CDP)
for exact device metric emulation on Windows.
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import websockets

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)

TEMP_DB = str(Path("temp_screenshot.db").resolve())


def setup_temp_db():
    if os.path.exists(TEMP_DB):
        os.remove(TEMP_DB)

    os.environ["DATABASE_PATH"] = TEMP_DB
    import db, split_logic

    db.init_db(TEMP_DB)
    conn = db.get_connection(TEMP_DB)
    cursor = conn.cursor()

    # 1. Insert 3 roommates: Mohamed, Brahim, Mouad
    cursor.execute("INSERT INTO roommates (name, is_active) VALUES ('Mohamed', 1)")
    m_id = cursor.lastrowid
    cursor.execute("INSERT INTO roommates (name, is_active) VALUES ('Brahim', 1)")
    b_id = cursor.lastrowid
    cursor.execute("INSERT INTO roommates (name, is_active) VALUES ('Mouad', 1)")
    mu_id = cursor.lastrowid

    today = date.today()

    # 2. Add an archived settlement in history
    cursor.execute(
        "INSERT INTO settlement_periods (settled_at, total_expenses_centimes, notes) VALUES (?, ?, ?)",
        ((today - timedelta(days=7)).isoformat() + " 18:30:00", 36000, "Settlement for Week 1"),
    )
    settlement_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO expenses (label, amount_centimes, date, paid_by_id, settlement_id) VALUES (?, ?, ?, ?, ?)",
        ("Cleaning Kit & Utensils", 36000, (today - timedelta(days=8)).isoformat(), m_id, settlement_id),
    )
    archived_exp_id = cursor.lastrowid
    for pid, share in [(m_id, 12000), (b_id, 12000), (mu_id, 12000)]:
        cursor.execute(
            "INSERT INTO expense_participants (expense_id, roommate_id, share_centimes) VALUES (?, ?, ?)",
            (archived_exp_id, pid, share),
        )
    cursor.execute(
        "INSERT INTO settlement_transfers (settlement_id, from_roommate_id, to_roommate_id, amount_centimes) VALUES (?, ?, ?, ?)",
        (settlement_id, b_id, m_id, 12000),
    )
    cursor.execute(
        "INSERT INTO settlement_transfers (settlement_id, from_roommate_id, to_roommate_id, amount_centimes) VALUES (?, ?, ?, ?)",
        (settlement_id, mu_id, m_id, 12000),
    )

    # 3. Add active current expenses
    active_expenses = [
        {
            "label": "Weekly Groceries (Marjane)",
            "amount_centimes": 45000,  # 450.00 MAD
            "date": (today - timedelta(days=2)).isoformat(),
            "paid_by_id": m_id,
            "participants": [m_id, b_id, mu_id],
        },
        {
            "label": "Fiber Internet 100Mbps",
            "amount_centimes": 24900,  # 249.00 MAD
            "date": (today - timedelta(days=1)).isoformat(),
            "paid_by_id": b_id,
            "participants": [m_id, b_id, mu_id],
        },
        {
            "label": "Speciality Coffee & Snacks",
            "amount_centimes": 9000,  # 90.00 MAD
            "date": today.isoformat(),
            "paid_by_id": mu_id,
            "participants": [m_id, b_id, mu_id],
        },
    ]

    for exp in active_expenses:
        cursor.execute(
            "INSERT INTO expenses (label, amount_centimes, date, paid_by_id, settlement_id) VALUES (?, ?, ?, ?, NULL)",
            (exp["label"], exp["amount_centimes"], exp["date"], exp["paid_by_id"]),
        )
        exp_id = cursor.lastrowid
        shares = split_logic.split_expense(exp["amount_centimes"], exp["participants"])
        for pid, s in shares.items():
            cursor.execute(
                "INSERT INTO expense_participants (expense_id, roommate_id, share_centimes) VALUES (?, ?, ?)",
                (exp_id, pid, s),
            )

    conn.commit()
    conn.close()
    print("Temporary database populated with test data.")


async def capture_all_cdp():
    pages = [
        ("balances", "http://127.0.0.1:5002/balances"),
        ("expenses", "http://127.0.0.1:5002/expenses"),
        ("reports", "http://127.0.0.1:5002/reports"),
        ("expense_form", "http://127.0.0.1:5002/expenses/add"),
        ("roommates", "http://127.0.0.1:5002/roommates"),
        ("history", "http://127.0.0.1:5002/history"),
    ]

    viewports = [
        ("mobile", 390, 844, True),
        ("desktop", 1280, 800, False),
    ]

    themes = ["light", "dark"]

    res = urllib.request.urlopen("http://127.0.0.1:9222/json/list").read().decode("utf-8")
    tabs = json.loads(res)
    ws_url = tabs[0]["webSocketDebuggerUrl"]

    msg_id = 0

    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        for page_name, url in pages:
            for vp_name, width, height, is_mobile in viewports:
                for theme in themes:
                    filename = SCREENSHOTS_DIR / f"{page_name}_{vp_name}_{theme}.png"
                    target_url = f"{url}?theme={theme}"

                    # 1. Override device metrics
                    msg_id += 1
                    await ws.send(
                        json.dumps({
                            "id": msg_id,
                            "method": "Emulation.setDeviceMetricsOverride",
                            "params": {
                                "width": width,
                                "height": height,
                                "deviceScaleFactor": 1,
                                "mobile": is_mobile,
                            },
                        })
                    )
                    await ws.recv()

                    # 2. Navigate
                    msg_id += 1
                    await ws.send(
                        json.dumps({
                            "id": msg_id,
                            "method": "Page.navigate",
                            "params": {"url": target_url},
                        })
                    )
                    await ws.recv()
                    await asyncio.sleep(0.4)

                    # 3. Capture screenshot
                    msg_id += 1
                    await ws.send(
                        json.dumps({
                            "id": msg_id,
                            "method": "Page.captureScreenshot",
                            "params": {"format": "png"},
                        })
                    )
                    raw_resp = await ws.recv()
                    resp = json.loads(raw_resp)
                    if "result" in resp and "data" in resp["result"]:
                        img_bytes = base64.b64decode(resp["result"]["data"])
                        with open(filename, "wb") as f:
                            f.write(img_bytes)
                        print(f"Captured: {filename.name} ({len(img_bytes)} bytes)")
                    else:
                        print(f"FAILED to capture: {filename.name}. Resp: {raw_resp[:200]}")

        # Capture confirmation modal popup
        for theme in ["light", "dark"]:
            msg_id += 1
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Emulation.setDeviceMetricsOverride",
                "params": {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False},
            }))
            await ws.recv()

            msg_id += 1
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.navigate",
                "params": {"url": f"http://127.0.0.1:5002/expenses?theme={theme}"},
            }))
            await ws.recv()
            await asyncio.sleep(0.4)

            # Click delete button on first expense
            msg_id += 1
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.querySelector('form[data-confirm] button').click();"},
            }))
            await ws.recv()
            await asyncio.sleep(0.3)

            msg_id += 1
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.captureScreenshot",
                "params": {"format": "png"},
            }))
            raw_resp = await ws.recv()
            resp = json.loads(raw_resp)
            if "result" in resp and "data" in resp["result"]:
                modal_file = SCREENSHOTS_DIR / f"confirm_modal_popup_{theme}.png"
                with open(modal_file, "wb") as f:
                    f.write(base64.b64decode(resp["result"]["data"]))
                print(f"Captured: {modal_file.name}")


def run_screenshots():
    setup_temp_db()

    # Start Flask server on port 5002
    server_env = os.environ.copy()
    server_env["DATABASE_PATH"] = TEMP_DB
    server_env["PORT"] = "5002"
    server_env["HOST"] = "127.0.0.1"

    server_proc = subprocess.Popen([sys.executable, "app.py"], env=server_env)
    time.sleep(1.5)

    chrome_tmp = tempfile.mkdtemp()
    chrome_proc = subprocess.Popen([
        CHROME_PATH,
        "--headless=new",
        "--disable-gpu",
        "--remote-debugging-port=9222",
        f"--user-data-dir={chrome_tmp}",
        "about:blank",
    ])
    time.sleep(1.5)

    try:
        asyncio.run(capture_all_cdp())
    finally:
        chrome_proc.terminate()
        chrome_proc.wait()
        server_proc.terminate()
        server_proc.wait()
        if os.path.exists(TEMP_DB):
            os.remove(TEMP_DB)
        print("Completed screenshot capture pass.")


if __name__ == "__main__":
    run_screenshots()
