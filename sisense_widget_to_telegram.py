import os
import sys
import time
import requests
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

BASE_URL = os.environ["SISENSE_BASE_URL"].rstrip("/")
USERNAME = os.environ["SISENSE_USER"]
PASSWORD = os.environ["SISENSE_PASS"]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DASHBOARD_ID = os.environ["DASHBOARD_ID"]
WIDGET_ID = os.environ["WIDGET_ID"]

WIDGET_URL = f"{BASE_URL}/app/main/dashboards/{DASHBOARD_ID}/widgets/{WIDGET_ID}"

def sisense_login_token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/v1/authentication/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError(f"Login ok but token missing: {data}")
    return token

def telegram_send_photo(photo_path: str, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}
        r = requests.post(url, data=data, files=files, timeout=120)
        r.raise_for_status()

def main():
    token = sisense_login_token()

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    caption = f"Sisense Widget Table ({now_utc})"

    out_path = "sisense_widget.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})

        # Sisense UI usually stores auth token in localStorage.
        # We set a few common keys to maximize compatibility.
        context.add_init_script(f"""
            () => {{
              try {{
                localStorage.setItem('access_token', '{token}');
                localStorage.setItem('token', '{token}');
                localStorage.setItem('sisenseToken', '{token}');
                localStorage.setItem('authToken', '{token}');
              }} catch(e) {{}}
            }}
        """)

        page = context.new_page()

        # Go to the widget
        page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=120000)

        # Give it time to load visuals (networkidle sometimes never happens on SPAs)
        page.wait_for_timeout(8000)

        # Try to wait for a table-like element; if it fails, still screenshot the page
        # (selectors vary by Sisense version/theme)
        possible_selectors = [
            "table",
            ".pivot-table",
            ".sisense-table",
            "[data-testid*='table']",
            ".widget",
        ]

        found = False
        for sel in possible_selectors:
            try:
                page.wait_for_selector(sel, timeout=7000)
                found = True
                break
            except Exception:
                pass

        # Full page screenshot works reliably
        page.screenshot(path=out_path, full_page=True)

        context.close()
        browser.close()

    telegram_send_photo(out_path, caption)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
