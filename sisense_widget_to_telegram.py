import os
import sys
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
LOGIN_URL  = f"{BASE_URL}/app/account#/login"

def telegram_send_photo(photo_path: str, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}
        r = requests.post(url, data=data, files=files, timeout=180)
        r.raise_for_status()

def main():
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    caption = f"Sisense Widget Table ({now_utc})"
    out_path = "sisense_widget.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 900},
            # helpful for some auth flows
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari/537.36",
        )
        page = context.new_page()

        # Go to the widget first; if redirected, we'll login
        page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(2000)

        def is_login_page() -> bool:
            url = page.url.lower()
            if "login" in url or "account#/" in url:
                return True
            # also detect by fields presence
            return page.locator("input[placeholder='Username/Email']").count() > 0

        if is_login_page():
            # Ensure we are on login page
            if "login" not in page.url.lower():
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120000)

            # Fill login form (Sisense typical placeholders)
            page.wait_for_selector("input[placeholder='Username/Email']", timeout=30000)
            page.fill("input[placeholder='Username/Email']", USERNAME)
            page.fill("input[placeholder='Password']", PASSWORD)

            # Click login button (try common selectors)
            clicked = False
            for sel in ["button:has-text('Login')", "button:has-text('Log in')", "button[type='submit']"]:
                try:
                    if page.locator(sel).count() > 0:
                        page.click(sel)
                        clicked = True
                        break
                except Exception:
                    pass

            if not clicked:
                raise RuntimeError("Could not find Login button on Sisense login page.")

            # Wait for navigation/auth to complete
            page.wait_for_timeout(4000)

            # Now go to widget again
            page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(8000)

        # Try to wait for any widget content (selectors vary by version)
        # If none found, still screenshot the page (better than failing)
        for sel in ["table", ".widget", ".dashboard", ".pivot", ".sisense-table"]:
            try:
                page.wait_for_selector(sel, timeout=7000)
                break
            except Exception:
                continue

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
